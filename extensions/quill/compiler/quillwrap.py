"""quill wrap: generate a Quill module that calls a C or C++ library.

    quill wrap zlib.h --name Zlib --link z --yes

reads the header and writes zlib.ql. Every function becomes a `native` method bound to
the C symbol (class ZlibRaw, the exact C view), and the ones that can be made safe get a
friendly method on Zlib: strings are `str`, byte arrays are `List[int]`, C structs behind
pointers become classes, and no pointer ever shows up. C++ headers get a generated
`extern "C"` shim (compiled and linked automatically) that also turns C++ exceptions into
Quill `Error`s. See docs/native.md.

The parser reads declarations, not code: it understands the plain C subset real headers
use (prototypes, typedefs, struct/enum, #define constants) and a simple C++ subset
(classes with public methods, constructors, namespaces, std::string). Anything it cannot
express is reported, never guessed.
"""
import os
import re
import sys
from dataclasses import dataclass, field

CAVEATS = """\
Quill's authors acknowledge that wrapping native code gives up guarantees Quill
otherwise provides. Read this before you rely on a wrapper:

  1. The compiler cannot check C or C++. A wrong declaration, a wrong size or a bad
     pointer crashes the program or corrupts memory, with no Quill error to explain it.
  2. Memory a library allocates is not reference counted. A handle is only freed if you
     say how (--owns); otherwise it leaks, or dangles if you free it yourself too soon.
  3. C has no exceptions: error codes stay your job. C++ exceptions are caught in the
     shim and rethrown as Quill `Error`s.
  4. Callbacks, structs by value, output parameters and variadic functions are not
     wrapped automatically. They appear in the raw class (or are listed as skipped).
  5. --sanitize and heap_live() cannot see inside the native library.
  6. Native code is platform specific. The library must be installed on every machine
     that builds the program, and a wrapper made here may need regenerating elsewhere.
  7. `bring` and `needs` do not support native code; they only fetch Quill source.
     Wrap a library you downloaded and installed yourself and keep the wrapper in your
     own project. A package fetched with `needs` that contains native code is refused.
"""

QUALS = {"const", "volatile", "restrict", "__restrict", "__restrict__", "extern", "static", "inline",
         "__inline", "__inline__", "register", "_Noreturn", "constexpr", "noexcept", "virtual", "explicit"}
NUM_WORDS = {"unsigned", "signed", "short", "long", "int", "char", "float", "double", "void", "_Bool", "bool"}
STD_TYPES = {"size_t": "size_t", "ssize_t": "ssize_t", "ptrdiff_t": "ssize_t", "intptr_t": "ssize_t",
             "uintptr_t": "size_t", "off_t": "llong", "time_t": "llong",
             "int8_t": "i8", "int16_t": "i16", "int32_t": "i32", "int64_t": "i64",
             "uint8_t": "u8", "uint16_t": "u16", "uint32_t": "u32", "uint64_t": "u64"}
C_SPELLING = {"char": "char", "schar": "signed char", "uchar": "unsigned char", "short": "short",
              "ushort": "unsigned short", "int": "int", "uint": "unsigned int", "long": "long",
              "ulong": "unsigned long", "llong": "long long", "ullong": "unsigned long long",
              "size_t": "size_t", "ssize_t": "ptrdiff_t", "float": "float", "double": "double", "bool": "bool",
              "i8": "int8_t", "i16": "int16_t", "i32": "int32_t", "i64": "int64_t",
              "u8": "uint8_t", "u16": "uint16_t", "u32": "uint32_t", "u64": "uint64_t"}
BYTE_BASES = {"void", "uchar", "u8", "i8", "schar"}
LEN_NAME = re.compile(r"^(len|length|size|sz|n|num|count|nbytes|bytes|datalen|buflen|data_len|data_size)$", re.I)
OWNING_NAME = re.compile(r"(^|_)(new|create|open|alloc|init|make|load|parse|clone|dup|copy|from|build)", re.I)


class WrapError(Exception):
    pass


@dataclass
class T:
    """A C type: a scalar name ('int', 'double', 'void'), 'struct:Name' or 'fnptr',
    plus pointer depth. cname is the spelling used in C++ shims."""
    base: str
    ptr: int = 0
    const: bool = False
    cpp: str = ""            # original C++ spelling, for shims
    enum: str = ""           # enum type name, when the base came from an enum
    ref: bool = False        # a C++ reference


@dataclass
class Param:
    name: str
    t: T
    sem: str = ""            # int float bool str handle:S bytes out ptr callback unsupported:why
    qtype: str = ""          # raw Quill type


@dataclass
class Func:
    name: str                # C symbol
    ret: T
    params: list
    variadic: bool = False
    owner: str = ""          # C++ class (methods and constructors)
    kind: str = "free"       # free | ctor | dtor | method | static
    qname: str = ""
    note: str = ""           # why it is raw only / skipped
    cpp_call: str = ""       # how the shim reaches the C++ entity
    const_method: bool = False


# ---------------------------------------------------------------- type handling

class Types:
    def __init__(self, cpp=False):
        self.typedefs = {}          # name -> T
        self.structs = set()        # known struct/class names (opaque handles)
        self.enums = {}             # enum name -> {const: value}
        self.cpp = cpp
        self.classes = set()

    def resolve(self, toks):
        """Turn a token list (words and '*') into a T."""
        spelled = " ".join(toks)
        ptr = toks.count("*")
        before = toks[:toks.index("*")] if "*" in toks else toks
        const = "const" in before
        words = [w for w in toks if w not in ("*", "&", "&&") and w not in QUALS]
        ref = "&" in toks
        if not words:
            raise WrapError("empty type")
        if words[0] in ("struct", "union", "class") and len(words) > 1:
            t = T("struct:" + words[1], ptr, const, spelled, ref=ref)
            self.structs.add(words[1])
            return t
        if words[0] == "enum":
            return T("int", ptr, const, spelled, enum=words[1] if len(words) > 1 else "", ref=ref)
        if all(w in NUM_WORDS for w in words):
            return T(self.numeric(words), ptr, const, spelled, ref=ref)
        if len(words) == 1:
            w = words[0]
            if w in self.typedefs:
                d = self.typedefs[w]
                return T(d.base, d.ptr + ptr, const or d.const, spelled, enum=d.enum, ref=ref)
            if w in STD_TYPES:
                return T(STD_TYPES[w], ptr, const, spelled, ref=ref)
            if w in self.enums:
                return T("int", ptr, const, spelled, enum=w, ref=ref)
            self.structs.add(w)
            return T("struct:" + w, ptr, const, spelled, ref=ref)
        raise WrapError(f"cannot read the type '{spelled}'")

    @staticmethod
    def numeric(words):
        longs, unsigned = words.count("long"), "unsigned" in words
        if "double" in words:
            if longs:
                raise WrapError("long double is not supported")
            return "double"
        if "float" in words:
            return "float"
        if "void" in words:
            return "void"
        if "bool" in words or "_Bool" in words:
            return "bool"
        if "char" in words:
            return "uchar" if unsigned else "schar" if "signed" in words else "char"
        if "short" in words:
            return "ushort" if unsigned else "short"
        if longs >= 2:
            return "ullong" if unsigned else "llong"
        if longs == 1:
            return "ulong" if unsigned else "long"
        return "uint" if unsigned else "int"

    def classify(self, t, is_return=False):
        """-> (semantic, C type name for the raw signature)."""
        if t.base == "fnptr":
            return "callback", "ptr"
        if t.ptr == 0:
            if t.base.startswith("struct:"):
                return "unsupported:" + t.base[7:] + " passed by value", "ptr"
            if t.base == "void":
                return "void", "void"
            if t.base in ("float", "double"):
                return "float", t.base
            if t.base == "bool":
                return "bool", "bool"
            return "int", t.base
        if t.ptr == 1 and t.base == "char" and (t.const or is_return):
            return "str", "cstr"            # a non-const char* parameter may be written to: raw only
        if t.ptr == 1 and t.base.startswith("struct:"):
            return "handle:" + t.base[7:], "ptr"
        if t.ptr == 1 and t.base in BYTE_BASES:
            return "bytes", "ptr"
        if t.ptr == 1 and t.base not in ("fnptr",):
            return "out", "ptr"
        return "ptr", "ptr"


def split_params(text):
    out, depth, cur = [], 0, ""
    for ch in text:
        if ch in "(<[":
            depth += 1
        elif ch in ")>]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur)
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur)
    return [p.strip() for p in out]


TOKEN = re.compile(r"::|[A-Za-z_]\w*|\*|&&|&|\.\.\.")


def parse_param(types, text, i, strip_ns=False):
    text = re.sub(r"=.*$", "", text).strip()                  # default argument
    if text == "...":
        return None
    fp = re.search(r"\(\s*\*\s*(\w*)\s*\)", text)
    if fp:
        return Param(fp.group(1) or f"arg{i}", T("fnptr", 1))
    arrays = len(re.findall(r"\[[^\]]*\]", text))
    text = re.sub(r"\[[^\]]*\]", "", text)
    if strip_ns:
        text = text.replace("std::", "")
    toks = TOKEN.findall(text)
    words = [w for w in toks if w not in ("*", "&", "&&") and w not in QUALS]
    name = f"arg{i}"
    if words and words[0] in ("struct", "union", "enum", "class"):
        has_name = len(words) >= 3
    else:
        has_name = len(words) >= 2 and words[-1] not in NUM_WORDS and not (words[-1] in types.typedefs and len(words) == 2 and False)
    if has_name:
        name = words[-1]
        idx = max(k for k, w in enumerate(toks) if w == name)
        toks = toks[:idx] + toks[idx + 1:]
    t = types.resolve(toks)
    t.ptr += arrays
    return Param(name, t)


# ---------------------------------------------------------------- C header parsing

def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
    return re.sub(r"//[^\n]*", " ", text)


def join_continuations(text):
    return re.sub(r"\\\r?\n", " ", text)


MACRO_NUM = re.compile(r"^\(?\s*(-?\s*(?:0[xX][0-9a-fA-F]+|\d+\.\d*(?:[eE][-+]?\d+)?|\d+(?:[eE][-+]?\d+)?|\d+))\s*[uUlLfF]*\s*\)?$")


def parse_macros(text, wanted_ok=True):
    consts = {}
    for m in re.finditer(r"^[ \t]*#[ \t]*define[ \t]+([A-Za-z_]\w*)[ \t]+(.+)$", text, flags=re.M):
        name, val = m.group(1), m.group(2).strip()
        mm = MACRO_NUM.match(val)
        if mm:
            num = mm.group(1).replace(" ", "")
            try:
                consts[name] = int(num, 0) if re.fullmatch(r"-?(0[xX][0-9a-fA-F]+|\d+)", num) else float(num)
            except ValueError:
                pass
        elif re.fullmatch(r'"(?:[^"\\]|\\.)*"', val):
            consts[name] = val[1:-1]
    return consts


def drop_preprocessor(text):
    return "\n".join("" if re.match(r"\s*#", ln) else ln for ln in text.split("\n"))


def clean_attributes(text, strip):
    text = re.sub(r"__attribute__\s*\(\(.*?\)\)", " ", text)
    text = re.sub(r"__declspec\s*\([^)]*\)", " ", text)
    text = re.sub(r"\bOF\s*\((\(.*?\))\)", r"\1", text)         # K&R compatibility macro: OF((args))
    text = re.sub(r"\b(__cdecl|__stdcall|WINAPI|CALLBACK|__extension__|_Nonnull|_Nullable)\b", " ", text)
    for m in strip:
        text = re.sub(r"\b" + re.escape(m) + r"\b(\s*\([^)]*\))?", " ", text)
    return re.sub(r'extern\s+"C"\s*\{?', " ", text)


def statements(text):
    """Top-level declarations: (text, body) where body is the {...} of a struct/enum."""
    out, cur, i, n = [], "", 0, len(text)
    while i < n:
        ch = text[i]
        if ch == "{":
            depth, j = 1, i + 1
            while j < n and depth:
                depth += (text[j] == "{") - (text[j] == "}")
                j += 1
            body = text[i + 1:j - 1]
            if re.search(r"\b(struct|union|enum)\b[^;(){}]*$", cur) or re.search(r"\btypedef\b", cur):
                cur += " {} "
                out.append(("body", body))
            else:                                    # a function body: forget the whole definition
                cur = ""
                out.append(("skip", None))
                if j < n and text[j] == ";":
                    j += 1
            i = j
            continue
        if ch == "}":
            i += 1
            continue
        if ch == ";":
            bodies = []
            while out and out[-1][0] in ("body", "skip"):
                bodies.append(out.pop())
            real = [b[1] for b in bodies if b[0] == "body"]
            if cur.strip():
                out.append(("stmt", (cur.strip(), real[-1] if real else None)))
            cur = ""
        else:
            cur += ch
        i += 1
    return [s[1] for s in out if s[0] == "stmt"]


def enum_values(body, into, enumname=None):
    cur = -1
    for item in body.split(","):
        item = item.strip()
        if not item:
            continue
        m = re.match(r"([A-Za-z_]\w*)\s*(?:=\s*(.+))?$", item, re.S)
        if not m:
            continue
        if m.group(2):
            v = m.group(2).strip()
            try:
                cur = int(v, 0)
            except ValueError:
                try:
                    cur = eval_simple(v, into)
                except Exception:
                    cur += 1
                    continue
        else:
            cur += 1
        into[m.group(1)] = cur


def eval_simple(expr, known):
    e = re.sub(r"\b([A-Za-z_]\w*)\b", lambda m: str(known[m.group(1)]) if m.group(1) in known else m.group(0), expr)
    if not re.fullmatch(r"[\d\s+\-*/()|&^~<>xXa-fA-F]+", e):
        raise ValueError(expr)
    return int(eval(e.replace("/", "//"), {"__builtins__": {}}))


def parse_c(text, strip=()):
    """-> (functions, constants, types)"""
    raw = join_continuations(strip_comments(text))
    consts = parse_macros(raw)
    text = clean_attributes(drop_preprocessor(raw), strip)
    types = Types()
    funcs, enumconsts = [], {}
    for stmt, body in statements(text):
        s = re.sub(r"\s+", " ", stmt)
        if s.startswith("typedef"):
            rest = s[len("typedef"):].strip()
            mm = re.match(r"(enum)\s*(\w*)\s*\{\}\s*(\w+)$", rest) or re.match(r"(enum)\s+(\w+)\s+(\w+)$", rest)
            if mm:
                tag, name = mm.group(2), mm.group(3)
                if body:
                    vals = {}
                    enum_values(body, vals)
                    enumconsts.update(vals)
                    types.enums[tag or name] = vals
                types.typedefs[name] = T("int", enum=tag or name)
                continue
            mm = re.match(r"(struct|union)\s*(\w*)\s*\{\}\s*(.+)$", rest)
            if mm:
                tag = mm.group(2)
                for decl in mm.group(3).split(","):
                    d = decl.strip()
                    stars = d.count("*")
                    nm = d.replace("*", "").strip()
                    types.structs.add(tag or nm)
                    types.typedefs[nm] = T("struct:" + (tag or nm), stars)
                continue
            mm = re.match(r"(.+?)\(\s*\*\s*(\w+)\s*\)\s*\(.*\)$", rest)
            if mm:
                types.typedefs[mm.group(2)] = T("fnptr", 1)
                continue
            if "(" in rest:
                continue
            try:
                toks = TOKEN.findall(rest)
                alias = toks[-1]
                types.typedefs[alias] = types.resolve(toks[:-1])
            except WrapError:
                pass
            continue
        m = re.match(r"(enum)\s*(\w*)\s*\{\}\s*$", s)
        if m and body is not None:
            vals = {}
            enum_values(body, vals)
            enumconsts.update(vals)
            types.enums[m.group(2) or f"anon{len(types.enums)}"] = vals
            continue
        if re.match(r"(struct|union)\s+\w+\s*(\{\})?$", s):
            types.structs.add(s.split()[1])
            continue
        if "(" not in s or s.startswith(("struct", "union", "enum")) and "{" in s:
            continue
        fp = parse_prototype(types, s)
        if fp:
            funcs.append(fp)
    consts.update({k: v for k, v in enumconsts.items()})
    return funcs, consts, types


def parse_prototype(types, s):
    m = re.match(r"^(.*?)\b([A-Za-z_]\w*)\s*\((.*)\)\s*$", s)
    if not m or m.group(2) in ("if", "while", "return", "sizeof"):
        return None
    pre, name, args = m.group(1), m.group(2), m.group(3)
    if "static" in pre.split() and "inline" in pre.split():
        return None
    if "(" in pre or not pre.strip():
        return None
    f = Func(name, None, [])
    try:
        f.ret = types.resolve(TOKEN.findall(pre))
        plist = split_params(args)
        if len(plist) == 1 and plist[0] in ("void", ""):
            plist = []
        for i, p in enumerate(plist):
            if p.strip() == "...":
                f.variadic = True
                continue
            f.params.append(parse_param(types, p, i))
    except WrapError as e:
        f.note = "skipped: " + str(e)
    return f


# ---------------------------------------------------------------- C++ header parsing

def match_brace(text, i):
    depth, j = 0, i
    while j < len(text):
        depth += (text[j] == "{") - (text[j] == "}")
        j += 1
        if depth == 0:
            return j
    return len(text)


def parse_cpp(text, strip=()):
    raw = join_continuations(strip_comments(text))
    consts = parse_macros(raw)
    text = clean_attributes(drop_preprocessor(raw), strip)
    types = Types(cpp=True)
    funcs, classes = [], {}
    enumconsts = {}

    def scan(body, ns):
        i, n = 0, len(body)
        cur = ""
        while i < n:
            ch = body[i]
            m = re.match(r"\s*namespace\s+(\w+)\s*\{", body[i:]) if ch in "n \t\n" and not cur.strip() else None
            if m:
                start = i + m.end() - 1
                end = match_brace(body, start)
                scan(body[start + 1:end - 1], ns + [m.group(1)])
                i = end
                continue
            m = re.match(r"\s*(?:template\s*<[^>]*>\s*)(class|struct)\b", body[i:]) if not cur.strip() else None
            if m:                                           # templates are not wrapped
                j = body.find("{", i)
                i = match_brace(body, j)
                while i < n and body[i] in " ;\n":
                    i += 1
                continue
            m = re.match(r"\s*(class|struct)\s+(\w+)\s*(?::\s*[^{;]*)?\{", body[i:]) if not cur.strip() else None
            if m:
                start = i + m.end() - 1
                end = match_brace(body, start)
                parse_class(m.group(2), m.group(1) == "struct", body[start + 1:end - 1], ns)
                i = end
                while i < n and body[i] in " ;":
                    i += 1
                continue
            m = re.match(r"\s*enum\s+(?:class\s+|struct\s+)?(\w+)\s*(?::\s*[\w ]+)?\{", body[i:]) if not cur.strip() else None
            if m:
                start = i + m.end() - 1
                end = match_brace(body, start)
                vals = {}
                enum_values(body[start + 1:end - 1], vals)
                types.enums[m.group(1)] = vals
                enumconsts.update({m.group(1) + "_" + k: v for k, v in vals.items()})
                i = end
                while i < n and body[i] in " ;":
                    i += 1
                continue
            if ch == "{":                                   # an inline function body
                i = match_brace(body, i)
                cur = ""
                continue
            if ch == ";":
                st = re.sub(r"\s+", " ", cur).strip()
                cur = ""
                i += 1
                if st and "(" in st and not st.startswith(("typedef", "using", "template", "friend")):
                    add_free(st, ns)
                continue
            cur += ch
            i += 1

    def cpp_sig(st):
        st = re.sub(r"\b(noexcept|override|final)\b", " ", st)
        st = re.sub(r"=\s*(0|default|delete)\s*$", "", st.strip()).strip()
        return st

    def make(name, pre, args, owner, kind, ns, const_m):
        f = Func(name, None, [], owner=owner, kind=kind, const_method=const_m)
        try:
            if kind == "ctor":
                f.ret = T("struct:" + owner, 1)
            else:
                f.ret = types.resolve(TOKEN.findall(pre.replace("std::", ""))) if pre.strip() else T("void")
            plist = split_params(args)
            if len(plist) == 1 and plist[0] in ("void", ""):
                plist = []
            for i, p in enumerate(plist):
                if p.strip() == "...":
                    f.variadic = True
                    continue
                f.params.append(parse_param(types, p, i, strip_ns=True))
        except WrapError as e:
            f.note = "skipped: " + str(e)
        f.cpp_call = "::".join(ns + [name]) if not owner else name
        return f

    def add_free(st, ns):
        st = cpp_sig(st)
        m = re.match(r"^(.*?)\b(\w+)\s*\((.*)\)\s*(const)?\s*$", st)
        if not m or not m.group(1).strip():
            return
        funcs.append(make(m.group(2), m.group(1), m.group(3), "", "free", ns, False))

    def parse_class(name, is_struct, body, ns):
        types.structs.add(name)
        types.classes.add(name)
        qual = "::".join(ns + [name])
        cls = classes.setdefault(name, dict(qual=qual, methods=[], base=None))
        public = is_struct
        i, n, cur = 0, len(body), ""
        while i < n:
            ch = body[i]
            m = re.match(r"\s*(public|private|protected)\s*:", body[i:]) if not cur.strip() else None
            if m:
                public = m.group(1) == "public"
                i += m.end()
                continue
            if ch == "{":
                st = re.sub(r"\s+", " ", cur).strip()
                if re.match(r"(class|struct|enum|union)\b", st) or "=" in st and "(" not in st:
                    i = match_brace(body, i)
                    cur = ""
                    continue
                j = match_brace(body, i)                    # an inline body: the declaration ends here
                i = j
                if public and st:
                    member(st, name, qual)
                cur = ""
                continue
            if ch == ";":
                st = re.sub(r"\s+", " ", cur).strip()
                cur = ""
                i += 1
                if public and st and "(" in st and not st.startswith(("typedef", "using", "friend", "template")):
                    member(st, name, qual)
                continue
            cur += ch
            i += 1

    def member(st, cls, qual):
        st = cpp_sig(st)
        if st.startswith("~") or re.match(r"(virtual\s+)?~", st):
            classes[cls]["dtor"] = True
            return
        const_m = bool(re.search(r"\)\s*const\s*$", st))
        st = re.sub(r"\)\s*const\s*$", ")", st)
        m = re.match(r"^(.*?)\b(\w+)\s*\((.*)\)\s*(?::.*)?$", st)
        if not m:
            return
        pre, name, args = m.group(1).strip(), m.group(2), m.group(3)
        pre_words = pre.split()
        static = "static" in pre_words
        if "operator" in st:
            return
        if name == cls and not pre.replace("explicit", "").strip():
            if re.search(r"\b" + re.escape(cls) + r"\s*(const\s*)?(&&|&)", args):     # copy/move constructors
                return
            f = make(name, "", args, cls, "ctor", [], False)
        else:
            f = make(name, pre, args, cls, "static" if static else "method", [], const_m)
        classes[cls]["methods"].append(f)

    scan(text, [])
    return funcs, consts, types, classes, enumconsts


# ---------------------------------------------------------------- shim generation (C++)

def cpp_type(t):
    """How to spell a raw (extern "C") parameter/return type in the shim."""
    if t.base == "fnptr":
        return "void*"
    if t.base.startswith("struct:"):
        return t.base[7:] + "*" * max(t.ptr, 1)
    base = C_SPELLING.get(t.base, t.base)
    if t.base == "void" and t.ptr == 0:
        return "void"
    return ("const " if t.const and t.ptr else "") + base + "*" * t.ptr


def make_shim(lib, header_name, funcs, classes, types, enum_names):
    """C++ source exposing everything as extern "C". Returns (source, raw functions)."""
    raw, body = [], []
    err = f"{lib}_error_text"
    out = [f"// Generated by `quill wrap`. Compiled and linked automatically; do not edit.",
           "#include <string>", "#include <cstdlib>", "#include <cstring>", "#include <exception>",
           f'#include "{header_name}"', "",
           f"static thread_local std::string {err};",
           "static char* quill_dup(const std::string& s) {",
           "    char* p = (char*)std::malloc(s.size() + 1);",
           "    std::memcpy(p, s.c_str(), s.size() + 1);",
           "    return p;", "}", "", 'extern "C" {', "",
           f"char* {lib}_take_error(void) {{",
           f"    if ({err}.empty()) return nullptr;",
           f"    char* p = quill_dup({err});",
           f"    {err}.clear();",
           "    return p;", "}", ""]
    used = set()

    def qual(n):
        return classes[n]["qual"] if n in classes else n

    def uniq(n):
        k, cand = 2, n
        while cand in used:
            cand, k = f"{n}_{k}", k + 1
        used.add(cand)
        return cand

    def arg_in(p, name):
        """expression passing raw parameter `name` to the C++ call"""
        t = p.t
        if is_string(t):
            return f"std::string({name})"
        if t.base.startswith("struct:") and t.ptr == 0:
            return f"*{name}"
        if t.base.startswith("struct:") and t.ref:
            return f"*{name}"
        if t.enum:
            return f"static_cast<{t.enum}>({name})"
        return name

    def is_string(t):
        return t.base == "struct:string" or t.base == "struct:string_view"

    def shim_raw_param(p):
        t = p.t
        if is_string(t):
            return "const char*"
        if t.base.startswith("struct:") and t.ptr == 0 and not t.ref:
            return None
        if t.base.startswith("struct:"):
            return qual(t.base[7:]) + "*"
        if t.ref and not t.base.startswith("struct:"):
            return None
        return cpp_type(t)

    def emit(f, call_expr, selfcls=None, ctor=False, dtor=False):
        cname = uniq(f.cname)
        params = []
        names = []
        if selfcls:
            params.append(f"{selfcls}* self")
        ok = True
        for i, p in enumerate(f.params):
            rp = shim_raw_param(p)
            if rp is None or p.t.base == "fnptr" or p.t.ptr > 1 or (not p.t.base.startswith("struct:") and p.t.ptr and not (p.t.base == "char" or p.t.base in BYTE_BASES)):
                f.note = f"skipped: parameter '{p.name}' ({p.t.cpp or p.t.base}) cannot cross the C boundary"
                return
            params.append(f"{rp} {p.name}")
            names.append(arg_in(p, p.name))
        rt = f.ret
        ret_c, wrap = "void", None
        if ctor:
            ret_c = f"{qual(f.owner)}*"
        elif rt.base != "void" or rt.ptr:
            if is_string(rt) and not rt.ptr:
                ret_c = "char*"
            elif rt.base.startswith("struct:"):
                ret_c = qual(rt.base[7:]) + "*"
            elif rt.base == "fnptr" or rt.ptr > 1 or (rt.ptr and rt.base not in ("char",) and rt.base not in BYTE_BASES):
                f.note = f"skipped: the return type ({rt.cpp or rt.base}) cannot cross the C boundary"
                return
            else:
                ret_c = cpp_type(rt)
        args = ", ".join(names)
        if ctor:
            expr = f"new {classes[f.owner]['qual']}({args})"
        elif dtor:
            expr = f"delete self"
        else:
            expr = call_expr.replace("@ARGS@", args)
        zero = "nullptr" if ("*" in ret_c) else "0"
        lines = [f"{ret_c} {cname}({', '.join(params) if params else 'void'}) {{", "    try {"]
        if dtor:
            lines.append("        delete self;")
        elif ret_c == "void":
            lines.append(f"        {expr};")
        elif is_string(rt) and not rt.ptr:
            lines.append(f"        return quill_dup(std::string({expr}));")
        elif rt.base.startswith("struct:") and rt.ptr == 0 and not rt.ref:
            lines.append(f"        return new {qual(rt.base[7:])}({expr});")
        elif rt.base.startswith("struct:") and (rt.ref or rt.ptr == 1):
            lines.append(f"        return &({expr});" if rt.ref else f"        return {expr};")
        elif rt.enum:
            lines.append(f"        return static_cast<int>({expr});")
        else:
            lines.append(f"        return {expr};")
        lines += ["    } catch (const std::exception& e) {", f"        {err} = e.what();",
                  "    } catch (...) {", f'        {err} = "unknown C++ exception";', "    }"]
        if ret_c != "void":
            lines.append(f"    return {zero};")
        lines += ["}", ""]
        out.extend(lines)
        f.cname = cname
        if selfcls:
            f.has_self = True
            f.params = [Param("self", T("struct:" + f.owner, 1))] + f.params
        raw.append(f)

    for f in funcs:
        f.cname = f"{lib}_{f.name}"
        if f.note or f.variadic:
            f.note = f.note or "skipped: variadic"
            continue
        emit(f, "::".join(filter(None, [f.cpp_call])) + "(@ARGS@)")
    for cname, c in classes.items():
        c.setdefault("dtor", False)
        c["new_ctors"] = []
        for f in c["methods"]:
            if f.note or f.variadic:
                f.note = f.note or "skipped: variadic"
                continue
            if f.kind == "ctor":
                f.cname = f"{lib}_{cname}_new"
                emit(f, "", ctor=True)
            elif f.kind == "static":
                f.cname = f"{lib}_{cname}_{f.name}"
                emit(f, f"{c['qual']}::{f.name}(@ARGS@)")
            else:
                f.cname = f"{lib}_{cname}_{f.name}"
                emit(f, f"self->{f.name}(@ARGS@)", selfcls=c["qual"])
        d = Func(f"{lib}_{cname}_delete", T("void"), [], owner=cname, kind="dtor")
        d.cname = d.name
        emit(d, "", selfcls=c["qual"], dtor=True)
        c["delete"] = d
    out += ['} // extern "C"', ""]
    return "\n".join(out), raw


# ---------------------------------------------------------------- Quill generation

def camel(name):
    parts = [p for p in re.split(r"[_\W]+", name) if p]
    return "".join(p[:1].upper() + p[1:] for p in parts) or "Lib"


def sanitize_name(name, keywords):
    n = re.sub(r"\W", "_", name)
    if n[:1].isdigit():
        n = "_" + n
    return n + "_" if n in keywords or n in ("self", "native", "init", "deinit") else n


@dataclass
class Report:
    friendly: list = field(default_factory=list)
    raw_only: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    handles: dict = field(default_factory=dict)
    constants: int = 0
    out: str = ""
    shim: str = ""


def qt(sem):
    if sem == "cppstr":
        return "int"
    if sem == "float":
        return "float"
    if sem == "bool":
        return "bool"
    if sem == "str":
        return "str"
    if sem == "void":
        return "void"
    return "int"


def generate(a, header_paths):
    from quill import KEYWORDS
    keywords = set(KEYWORDS)
    texts = []
    for hp in header_paths:
        with open(hp, encoding="utf-8", errors="replace") as f:
            texts.append(f.read())
    text = "\n".join(texts)
    cpp = a.lang == "c++" or (a.lang is None and header_paths[0].lower().endswith((".hpp", ".hh", ".hxx", ".h++")))
    lib = camel(a.name or os.path.splitext(os.path.basename(header_paths[0]))[0])
    raw_cls, lib_cls = lib + "Raw", lib
    prefixes = list(a.prefix or [])
    owns = dict(o.split("=", 1) for o in (a.owns or []))
    if cpp:
        funcs, consts, types, classes, enumconsts = parse_cpp(text, a.strip or ())
        consts.update(enumconsts)
    else:
        funcs, consts, types = parse_c(text, a.strip or ())
        classes = {}
    if a.only:
        funcs = [f for f in funcs if re.search(a.only, f.name)]
    if a.skip:
        funcs = [f for f in funcs if not re.search(a.skip, f.name)]

    shim_src = ""
    rep_pre, parse_funcs_all = [], list(funcs)
    if cpp:
        header_name = os.path.basename(header_paths[0])
        shim_src, shim_raw = make_shim(lib.lower(), header_name, funcs, classes, types, set(types.enums))
        funcs = [f for f in shim_raw if f.kind in ("free", "static", "method", "ctor", "dtor")]
        allf = funcs
        every = list(parse_funcs_all) + [m for c in classes.values() for m in c["methods"]]
        for f in every:
            if f not in shim_raw and (f.note or f.variadic):
                rep_pre.append((f.owner + "::" + f.name if f.owner else f.name, f.note or "variadic (...) functions cannot be called from Quill"))
    else:
        allf = funcs
    rep = Report()
    rep.skipped.extend(rep_pre)
    lib_prefix = lib.lower()

    # classify every function
    handle_classes = {}

    def handle_name(struct):
        if cpp:
            return struct
        n = camel(struct)
        if n in (raw_cls, lib_cls):
            n += "Handle"
        return n

    usable = []
    for f in allf:
        if f.note:
            rep.skipped.append((f.name, f.note))
            continue
        if f.variadic:
            rep.skipped.append((f.name, "variadic (...) functions cannot be called from Quill"))
            continue
        f.rname = f.cname if cpp else f.name
        for p in f.params:
            if cpp and p.t.base in ("struct:string", "struct:string_view"):
                p.sem, p.ctype = "str", "cstr"
            elif cpp and p.t.base.startswith("struct:") and p.t.base[7:] in types.classes:
                p.sem, p.ctype = "handle:" + p.t.base[7:], "ptr"
            else:
                p.sem, p.ctype = types.classify(p.t)
        if cpp and f.ret.base in ("struct:string", "struct:string_view") and f.ret.ptr == 0:
            f.rsem, f.rctype = "cppstr", "ptr"
        elif cpp and f.ret.base.startswith("struct:") and f.ret.base[7:] in types.classes:
            f.rsem, f.rctype = "handle:" + f.ret.base[7:], "ptr"
        else:
            f.rsem, f.rctype = types.classify(f.ret, True)
        if f.rsem.startswith("unsupported"):
            rep.skipped.append((f.name, "returns " + f.rsem.split(":", 1)[1]))
            continue
        bad = next((p for p in f.params if p.sem.startswith("unsupported")), None)
        if bad:
            rep.skipped.append((f.name, bad.sem.split(":", 1)[1]))
            continue
        usable.append(f)

    out = []
    w = out.append
    w(f"# Generated by `quill wrap` from {', '.join(os.path.basename(h) for h in header_paths)}.")
    w("#")
    for line in CAVEATS.rstrip().split("\n"):
        w(("# " + line).rstrip())
    w("#")
    w(f"# {raw_cls}: every function exactly as C sees it (addresses are plain ints).")
    w(f"# {lib_cls}: the friendly layer. Add your own Quill code here or in new files; regenerate")
    w("# only into a different file, because `quill wrap` overwrites its output.")
    w("")
    uses_buffer = False
    friendly = []

    def own_free(struct):
        return owns.get(struct)

    # ---- friendly layer
    def friendly_for(f):
        nonlocal uses_buffer
        params, call, pre = [], [], []
        i = 0
        used_names = set()
        plist = f.params[1:] if getattr(f, "has_self", False) else f.params
        while i < len(plist):
            p = plist[i]
            pname = sanitize_name(p.name, keywords)
            while pname in used_names:
                pname += "_"
            used_names.add(pname)
            if p.sem == "bytes" and p.t.const and i + 1 < len(f.params) and f.params[i + 1].sem == "int" and \
                    f.params[i + 1].t.ptr == 0 and (LEN_NAME.match(f.params[i + 1].name or "") or True) and f.params[i + 1].ctype in ("size_t", "uint", "int", "ulong", "long", "u32", "u64", "ullong", "llong", "ssize_t"):
                params.append(f"{pname}: List[int]")
                pre.append(f"buf{i} = Buffer.of({pname})")
                call += [f"buf{i}.address()", f"{pname}.size()"]
                uses_buffer = True
                i += 2
                continue
            if p.sem in ("int", "float", "bool", "str"):
                params.append(f"{pname}: {qt(p.sem)}")
                call.append(pname)
            elif p.sem.startswith("handle:"):
                cls = handle_name(p.sem.split(":", 1)[1])
                handle_classes.setdefault(p.sem.split(":", 1)[1], cls)
                params.append(f"{pname}: {cls}")
                call.append(f"{cls}.addr({pname})")
            else:
                why = {"bytes": "a byte buffer without a length it can pair with (use Buffer)",
                       "out": "an output parameter (use Buffer and read it back)",
                       "callback": "a callback", "ptr": "a pointer to a pointer"}.get(p.sem, p.sem)
                return None, f"raw only: '{p.name}' is {why}"
            i += 1
        # return
        sem = f.rsem
        if sem == "cppstr":
            rtype = "str"
        elif sem in ("int", "float", "bool", "str", "void"):
            rtype = qt(sem)
        elif sem.startswith("handle:"):
            struct = sem.split(":", 1)[1]
            cls = handle_name(struct)
            handle_classes.setdefault(struct, cls)
            rtype = cls
        elif sem == "bytes" or sem == "out" or sem == "ptr":
            return None, "raw only: it returns a pointer to memory the wrapper cannot size"
        else:
            return None, f"raw only: {sem}"
        return (params, call, pre, rtype), None

    lines_fr, lines_raw = {}, []
    members = {}              # class name -> [method source]
    lib_methods, ctor_names = [], {}

    def raw_decl(f):
        qparams = []
        for i, p in enumerate(f.params):
            nm = sanitize_name(p.name, keywords)
            qparams.append(f"{nm}: {qt(p.sem)}")
        # a char* return that must be freed by the caller travels as an address
        rsem, rct = f.rsem, f.rctype
        if rsem == "str" and a.free_strings and not f.ret.const:
            rsem, rct = "ptr", "ptr"
        ret = "" if rsem == "void" else f" -> {qt(rsem)}"
        csig = ", ".join(p.ctype for p in f.params)
        cret = "" if f.rctype == "void" else f" -> {rct}"
        rname = sanitize_name(f.rname, keywords)
        f.rsem_eff = rsem
        return f'    native static def {rname}({", ".join(qparams)}){ret} = "{f.rname}({csig}){cret}"', rname

    seen_raw, seen_lib = set(), set()
    raw_lines = []
    for f in usable:
        decl, rname = raw_decl(f)
        if rname in seen_raw:
            continue
        seen_raw.add(rname)
        f.rq = rname
        raw_lines.append(decl)

    # error check for C++ shims
    check_src = []
    if cpp:
        raw_lines.append(f'    native static def takeError() -> int = "{lib_prefix}_take_error() -> ptr"')
        check_src = [f"    static def check():",
                     f"        p = {raw_cls}.takeError()",
                     f"        if p != 0:",
                     f"            throw new Error(__native_take(p))"]

    def prefix_strip(n):
        for pre in prefixes:
            if n.startswith(pre) and len(n) > len(pre):
                return n[len(pre):]
        return n

    method_src = {"": []}
    if cpp:
        for cname_ in classes:
            handle_classes[cname_] = cname_
    release_fns = set(owns.values())
    for f in usable:
        fr, why = friendly_for(f)
        if f.name in release_fns:
            rep.raw_only.append((f.name, f"released automatically; call close() on the object instead"))
            continue
        if fr is None:
            rep.raw_only.append((f.name if not cpp else f.cname, why))
            continue
        params, call, pre, rtype = fr
        base = f.name if not cpp else f.name
        qn = sanitize_name(prefix_strip(base), keywords)
        owner = f.owner if cpp else ""
        if cpp and f.kind == "ctor":
            qn = "create"
        used = seen_lib if not owner else method_src.setdefault("used:" + owner, set())
        while qn in used:
            qn += "2" if not qn[-1].isdigit() else str(int(qn[-1]) + 1)
        used.add(qn)
        body = [f"        {l}" for l in pre]
        callexpr = f"{raw_cls}.{f.rq}({', '.join(call if not (cpp and f.kind in ('method',)) else ['self.handle'] + call)})"
        rsem = getattr(f, "rsem_eff", f.rsem)
        if f.rsem == "str" and a.free_strings and not f.ret.const and not cpp:
            post_free = True
        else:
            post_free = False
        if f.rsem == "cppstr":
            body.append(f"        r = {callexpr}")
            body.append(f"        {raw_cls_check(cpp, lib)}")
            body.append("        if r == 0:")
            body.append("            return null")
            body.append("        return __native_take(r)")
            rtype = "str"
        elif f.rsem == "void" or f.kind == "dtor":
            body.append(f"        {callexpr}")
            if cpp:
                body.append(f"        {raw_cls_check(cpp, lib)}")
        elif f.rsem.startswith("handle:"):
            struct = f.rsem.split(":", 1)[1]
            cls = handle_name(struct)
            owned = bool(own_free(struct) or cpp) and bool(OWNING_NAME.search(f.name) or (cpp and f.kind == "ctor") or (cpp and f.ret.ptr == 0 and not f.ret.ref))
            body.append(f"        r = {callexpr}")
            if cpp:
                body.append(f"        {raw_cls_check(cpp, lib)}")
            body.append(f"        return {cls}.wrap(r, {'true' if owned else 'false'})")
        elif post_free:
            body.append(f"        r = {callexpr}")
            body.append("        s = __native_cstr(r)")
            body.append(f"        {raw_cls}.{sanitize_name(a.free_strings, keywords)}(r)")
            body.append("        return s")
        else:
            body.append(f"        r = {callexpr}")
            if cpp:
                body.append(f"        {raw_cls_check(cpp, lib)}")
            body.append("        return r")
        ret_txt = "" if rtype == "void" else f" -> {rtype}"
        if cpp and f.kind in ("method",):
            src = [f"    def {qn}(self{', ' if params else ''}{', '.join(params)}){ret_txt}:"] + body
            members.setdefault(owner, []).append("\n".join(src))
        elif cpp and f.kind in ("static", "ctor"):
            src = [f"    static def {qn}({', '.join(params)}){ret_txt}:"] + body
            members.setdefault(owner, []).append("\n".join(src))
        elif cpp and f.kind == "dtor":
            continue
        else:
            src = [f"    static def {qn}({', '.join(params)}){ret_txt}:"] + body
            lib_methods.append("\n".join(src))
        rep.friendly.append(f"{lib_cls}.{qn}" if not owner else f"{owner}.{qn}")

    # constants
    const_src = []
    for k, v in sorted(consts.items()):
        if not re.fullmatch(r"[A-Za-z_]\w*", k):
            continue
        qn = sanitize_name(k, keywords)
        if isinstance(v, int) and not (-(2 ** 63) <= v < 2 ** 63):
            continue
        if isinstance(v, str):
            const_src.append(f'    static def {qn}() -> str:\n        return "{v}"')
        elif isinstance(v, float):
            const_src.append(f"    static def {qn}() -> float:\n        return {v!r}")
        else:
            const_src.append(f"    static def {qn}() -> int:\n        return {v}")
    rep.constants = len(const_src)

    # ---- assemble
    if uses_buffer:
        w("bring std.native")
        w("")
    for lb in a.link or []:
        w(f'native link "{lb}"')
    for d in a.libdir or []:
        w(f'native libdir "{d}"')
    inc_dirs = list(a.include or [])
    if cpp and os.path.dirname(os.path.abspath(header_paths[0])) not in [os.path.abspath(x) for x in inc_dirs]:
        inc_dirs.append(os.path.dirname(os.path.abspath(header_paths[0])))
    outdir = os.path.dirname(os.path.abspath(a.out))
    def rel(p):
        try:
            return os.path.relpath(p, outdir).replace("\\", "/")
        except ValueError:
            return p.replace("\\", "/")
    for d in inc_dirs:
        w(f'native include "{rel(d)}"')
    for s in a.source or []:
        w(f'native source "{rel(os.path.abspath(s))}"')
    if cpp:
        w(f'native source "{rel(a.shim_path)}"')
        w(f'native flag "-std={a.std}"')
    for fl in a.flag or []:
        w(f'native flag "{fl}"')
    w("")
    w(f"class {raw_cls}:")
    if not raw_lines:
        w("    pass")
    out.extend(raw_lines)
    w("")

    # handle classes
    for struct, cls in sorted(handle_classes.items()):
        free = own_free(struct)
        w(f"class {cls}:")
        w("    handle: int")
        w("    owned: bool")
        w("")
        w("    def init(self, handle: int, owned: bool):")
        w("        self.handle = handle")
        w("        self.owned = owned")
        w("")
        w(f"    static def wrap(handle: int, owned: bool) -> {cls}:")
        w("        if handle == 0:")
        w("            return null")
        w(f"        return new {cls}(handle, owned)")
        w("")
        w(f"    static def addr(x: {cls}) -> int:")
        w("        if x == null:")
        w("            return 0")
        w("        return x.handle")
        if cpp:
            d = classes[struct]["delete"]
            free_call = f"{raw_cls}.{sanitize_name(d.cname, keywords)}(self.handle)"
        elif free:
            free_call = f"{raw_cls}.{sanitize_name(free, keywords)}(self.handle)"
        else:
            free_call = None
        if free_call:
            w("")
            w("    def deinit(self):")
            w("        self.close()")
            w("")
            w("    # release the native object now; safe to call twice")
            w("    def close(self):")
            w("        if self.owned and self.handle != 0:")
            w(f"            {free_call}")
            w("        self.handle = 0")
            w("        self.owned = false")
        for m in members.get(struct, []):
            w("")
            w(m)
        w("")
        rep.handles[cls] = free or ("delete (generated)" if cpp else None)

    w(f"class {lib_cls}:")
    body_parts = const_src + lib_methods + (["\n".join(check_src)] if check_src else [])
    if not body_parts:
        w("    pass")
    for i, part in enumerate(body_parts):
        w(part)
        w("")
    rep.out = "\n".join(out).rstrip() + "\n"
    rep.shim = shim_src
    rep.lib, rep.raw_cls, rep.cpp = lib, raw_cls, cpp
    return rep


def raw_cls_check(cpp, lib):
    return f"{lib}.check()" if cpp else "pass"


# ---------------------------------------------------------------- command line

def add_parser(sub):
    sp = sub.add_parser("wrap", help="generate a Quill wrapper for a C or C++ library")
    sp.add_argument("headers", nargs="+", help="the header file(s) describing the library")
    sp.add_argument("--name", help="class name of the wrapper (default: from the header name)")
    sp.add_argument("--out", help="output .ql file (default: NAME.ql in the current folder)")
    sp.add_argument("--link", action="append", metavar="LIB", help="library to link, like -l (repeatable)")
    sp.add_argument("--libdir", action="append", metavar="DIR", help="where to find libraries, like -L")
    sp.add_argument("--include", action="append", metavar="DIR", help="include directory, like -I")
    sp.add_argument("--source", action="append", metavar="FILE", help="a .c/.cpp file to compile into the program")
    sp.add_argument("--flag", action="append", metavar="FLAG", help="extra compiler flag")
    sp.add_argument("--prefix", action="append", metavar="P", help="strip this prefix from function names")
    sp.add_argument("--strip", action="append", metavar="MACRO", help="export macro to ignore in prototypes")
    sp.add_argument("--owns", action="append", metavar="Struct=free_fn",
                    help="objects of this struct are released with free_fn when no longer used")
    sp.add_argument("--free-strings", metavar="FN", help="free returned (non-const) char* with FN after copying")
    sp.add_argument("--only", metavar="REGEX", help="wrap only functions matching this")
    sp.add_argument("--skip", metavar="REGEX", help="leave out functions matching this")
    sp.add_argument("--lang", choices=["c", "c++"], help="force the language (default: by file extension)")
    sp.add_argument("--std", default="c++17", help="C++ standard for generated shims (default c++17)")
    sp.add_argument("--yes", action="store_true", help="acknowledge the caveats without being asked")
    return sp


def acknowledge(a):
    print(CAVEATS, file=sys.stderr)
    if a.yes or os.environ.get("QUILL_WRAP_YES"):
        print("(acknowledged with --yes)\n", file=sys.stderr)
        return True
    if not sys.stdin.isatty():
        print("quill wrap: pass --yes to confirm you have read the above.", file=sys.stderr)
        return False
    try:
        return input("Type 'yes' to continue: ").strip().lower() == "yes"
    except EOFError:
        return False


def run(a):
    for h in a.headers:
        if not os.path.isfile(h):
            print(f"quill wrap: no such file {h}", file=sys.stderr)
            return 1
    if not acknowledge(a):
        print("quill wrap: stopped.", file=sys.stderr)
        return 1
    name = a.name or os.path.splitext(os.path.basename(a.headers[0]))[0]
    a.out = a.out or (re.sub(r"\W", "_", name).lower() + ".ql")
    a.shim_path = os.path.splitext(a.out)[0] + "_shim.cpp"
    try:
        rep = generate(a, a.headers)
    except WrapError as e:
        print(f"quill wrap: {e}", file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(rep.out)
    if rep.cpp:
        with open(a.shim_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(rep.shim)
    print(f"wrote {a.out}" + (f" and {a.shim_path}" if rep.cpp else ""))
    print(f"  {len(rep.friendly)} friendly method(s) on {rep.lib}, {len(rep.raw_only)} raw only, "
          f"{len(rep.skipped)} skipped, {rep.constants} constant(s)")
    if rep.handles:
        for cls, free in rep.handles.items():
            print(f"  handle class {cls}: " + (f"released with {free}" if free else
                  "NOT released automatically (pass --owns Struct=free_function if the library has one)"))
    for n, why in rep.raw_only:
        print(f"  raw only  {n}: {why}")
    for n, why in rep.skipped:
        print(f"  skipped   {n}: {why}")
    print(f"use it:  bring {os.path.splitext(os.path.basename(a.out))[0]}   (see docs/native.md)")
    return 0

#!/usr/bin/env python3
"""Quill language server (Language Server Protocol over stdio, no dependencies).

Features: diagnostics (the real compiler front end and type checker), document and
workspace symbols, completion (keywords, classes, members through `self.`, variables
and class names), hover, go to definition, signature help.

The server imports the Quill compiler from ../compiler (bundled with the extension) or
from QUILL_COMPILER_DIR, so what it reports is exactly what `quill build` would report.
"""
import builtins
import json
import os
import queue
import re
import sys
import threading
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
COMPILER_DIR = os.environ.get("QUILL_COMPILER_DIR") or os.path.join(HERE, "..", "compiler")
sys.path.insert(0, os.path.abspath(COMPILER_DIR))
import quill  # noqa: E402

KEYWORDS = sorted(quill.KEYWORDS)
PRIMITIVES = ["int", "float", "bool", "str", "void"]
SNIPPETS = {
    "main": "class Main:\n    static def main():\n        $0",
    "class": "class ${1:Name}:\n    def init(self$2):\n        $0",
    "def": "def ${1:name}(self$2) -> ${3:void}:\n    $0",
    "try": "try:\n    $1\ncatch e: ${2:Error}:\n    $0",
}


# ───────────────────────────── transport ─────────────────────────────

def read_message(stream):
    length = None
    while True:
        line = stream.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    if length is None:
        return None
    return json.loads(stream.read(length).decode("utf-8"))


def send(msg):
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    out = sys.stdout.buffer
    out.write(b"Content-Length: %d\r\n\r\n" % len(body) + body)
    out.flush()


def respond(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    send(msg)


def notify(method, params):
    send({"jsonrpc": "2.0", "method": method, "params": params})


def uri_to_path(uri):
    return urllib.request.url2pathname(urllib.parse.urlparse(uri).path)


def path_to_uri(path):
    return "file://" + urllib.parse.quote(os.path.abspath(path))


# ───────────────────────────── analysis ─────────────────────────────

class Workspace:
    def __init__(self):
        self.docs = {}              # uri -> text
        self.good = {}              # uri -> last successfully parsed [ClassDecl]
        self.prelude = None
        self.roots = []

    # ---- reading files with unsaved buffers overlaid ----
    def overlay_open(self, file, *a, **kw):
        if isinstance(file, (str, os.PathLike)):
            real = os.path.realpath(file)
            for uri, text in self.docs.items():
                if os.path.realpath(uri_to_path(uri)) == real:
                    import io
                    return io.StringIO(text)
        return builtins.open(file, *a, **kw)

    def get_prelude(self):
        if self.prelude is None:
            decls = quill.Parser(quill.lex(quill.PRELUDE)).program()
            prim = os.path.join(os.path.abspath(COMPILER_DIR), "std", "primitives.ql")
            if os.path.exists(prim):
                with open(prim, encoding="utf-8") as f:
                    decls += quill.Parser(quill.lex(f.read())).program()
            for d in decls:
                d.file = "<built-in>"
            self.prelude = decls
        return self.prelude

    def parse_own(self, uri):
        text = self.docs.get(uri, "")
        try:
            decls = quill.Parser(quill.lex(text)).program()
            for d in decls:
                d.file = uri_to_path(uri)
            self.good[uri] = decls
        except quill.CompileError:
            pass
        except Exception:
            pass
        return self.good.get(uri, [])

    def all_classes(self, uri):
        """Classes visible from a document: built-ins, the document's own, and its modules'."""
        found = {d.name: d for d in self.get_prelude()}
        path = uri_to_path(uri)
        quill.open = self.overlay_open
        try:
            decls, _ = quill.load_program(path)
            for d in decls:
                found[d.name] = d
        except Exception:
            for d in self.parse_own(uri):
                found[d.name] = d
        finally:
            quill.open = builtins.open
        return found

    def diagnose(self, uri):
        path = uri_to_path(uri)
        quill.open = self.overlay_open
        try:
            try:
                quill.compile_file(path)
            except quill.CompileError as e:
                return [self.to_diag(uri, e)]
            except RecursionError:
                return []
            except Exception as e:  # compiler bug: do not spam the user with it
                sys.stderr.write(f"internal compiler error: {e!r}\n")
                return []
        finally:
            quill.open = builtins.open
        return []

    def to_diag(self, uri, e):
        here = uri_to_path(uri)
        text = self.docs.get(uri, "")
        lines = text.split("\n")
        msg = e.msg
        line = e.line or 1
        if e.file and os.path.realpath(e.file) != os.path.realpath(here) and e.file != "<built-in>":
            msg = f"in {os.path.basename(e.file)}:{line}: {msg}"
            line = 1
        line = max(1, min(line, len(lines)))
        src = lines[line - 1] if lines else ""
        start = len(src) - len(src.lstrip())
        end = len(src.rstrip())
        # underline the quoted name in the message when it appears on that line
        m = re.search(r"['`\"]?([A-Za-z_][\w.]*)['`\"]?", msg)
        for cand in re.findall(r"(?:class|method|field|variable|name|type) ([A-Za-z_][\w.\[\]]*)", msg):
            i = src.find(cand)
            if i >= 0:
                start, end = i, i + len(cand)
                break
        return {"range": {"start": {"line": line - 1, "character": start},
                          "end": {"line": line - 1, "character": max(end, start + 1)}},
                "severity": 1, "source": "quill", "message": msg}


ws = Workspace()


# ---- helpers over the class table ----

def base_type(t):
    t = (t or "").strip()
    if t.startswith("weak "):
        t = t[5:]
    return t.split("[", 1)[0]


def type_args(t):
    if "[" not in t:
        return []
    inner = t[t.index("[") + 1:t.rindex("]")]
    out, depth, cur = [], 0, ""
    for ch in inner:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    out.append(cur.strip())
    return out


def subst(s, tparams, args):
    for tp, a in zip(tparams, args):
        s = re.sub(rf"\b{re.escape(tp)}\b", a, s)
    return s


def members(classes, tname):
    """All members of a type, own first then inherited: [(kind, name, decl, owner)]."""
    out, seen, todo = [], set(), [tname]
    while todo:
        t = todo.pop(0)
        c = classes.get(base_type(t))
        if not c or c.name in seen:
            continue
        seen.add(c.name)
        for f in c.fields:
            out.append(("field", f.name, f, c))
        for m in c.methods:
            out.append(("method", m.name, m, c))
        todo.extend(c.supers)
    return out


def method_sig(m, owner=None, targs=None):
    ps = ", ".join(f"{n}: {t}" for n, t in m.params)
    ret = m.ret or "void"
    s = f"{'static ' if m.static else ''}def {m.name}({ps}) -> {ret}"
    if owner is not None and owner.tparams and targs:
        s = subst(s, owner.tparams, targs)
    return s


def class_sig(c):
    kind = "interface" if c.interface else ("abstract class" if c.abstract else "class")
    name = c.name + (f"[{', '.join(c.tparams)}]" if c.tparams else "")
    return f"{kind} {name}" + (f" < {', '.join(c.supers)}" if c.supers else "")


def class_at(decls, line1):
    best = None
    for d in decls:
        if d.line <= line1 and (best is None or d.line >= best.line):
            best = d
    return best


def var_type(text, name, line0):
    """The declared type of a variable/parameter/field: looks upward for `name: Type`,
    then `name = new Type(...)`."""
    lines = text.split("\n")
    pat = re.compile(rf"\b{re.escape(name)}\s*:\s*((?:weak\s+)?[A-Za-z_][\w.]*(?:\[[^\]=]*\])?)")
    for i in range(min(line0, len(lines) - 1), -1, -1):
        for m in pat.finditer(lines[i]):
            return m.group(1)
    new = re.compile(rf"\b{re.escape(name)}\s*=\s*new\s+([A-Za-z_][\w.]*(?:\[[^\]]*\])?)")
    for i in range(min(line0, len(lines) - 1), -1, -1):
        m = new.search(lines[i])
        if m:
            return m.group(1)
    return None


def receiver_before(text, line0, col):
    """The expression just before a `.` at (line0, col): returns ('self'|'name'|None, name)."""
    line = text.split("\n")[line0][:col]
    m = re.search(r"([A-Za-z_][\w]*)\s*$", line)
    return m.group(1) if m else None


def word_at(text, line0, col):
    lines = text.split("\n")
    if line0 >= len(lines):
        return None, 0, 0
    s = lines[line0]
    col = min(col, len(s))
    a = col
    while a > 0 and (s[a - 1].isalnum() or s[a - 1] == "_"):
        a -= 1
    b = col
    while b < len(s) and (s[b].isalnum() or s[b] == "_"):
        b += 1
    return (s[a:b] or None), a, b


def resolve_receiver(uri, text, line0, name):
    """Type string of the receiver name, or None. `self` -> enclosing class;
    a class name -> that class (static access)."""
    classes = ws.all_classes(uri)
    if name == "self":
        c = class_at(ws.parse_own(uri), line0 + 1)
        return c.name if c else None
    if name in classes:
        return name
    return var_type(text, name, line0)


# ───────────────────────────── features ─────────────────────────────

SYMBOL_KIND = {"class": 5, "interface": 11, "method": 6, "field": 8, "constructor": 9}


def name_range(text, line1, name):
    lines = text.split("\n")
    line0 = max(0, min(line1 - 1, len(lines) - 1))
    i = lines[line0].find(name)
    i = max(i, 0)
    return {"start": {"line": line0, "character": i}, "end": {"line": line0, "character": i + len(name)}}


def document_symbols(uri):
    text = ws.docs.get(uri, "")
    decls = ws.parse_own(uri)
    lines = text.split("\n")
    out = []
    for i, c in enumerate(decls):
        end_line = (decls[i + 1].line - 2) if i + 1 < len(decls) else len(lines) - 1
        children = []
        for f in c.fields:
            r = name_range(text, f.line, f.name)
            children.append({"name": f.name, "detail": f.type, "kind": SYMBOL_KIND["field"], "range": r, "selectionRange": r})
        for m in c.methods:
            r = name_range(text, m.line, m.name)
            kind = SYMBOL_KIND["constructor"] if m.name == "init" else SYMBOL_KIND["method"]
            children.append({"name": m.name, "detail": method_sig(m)[4:], "kind": kind, "range": r, "selectionRange": r})
        sel = name_range(text, c.line, c.name)
        out.append({"name": c.name, "detail": class_sig(c), "kind": SYMBOL_KIND["interface" if c.interface else "class"],
                    "range": {"start": {"line": c.line - 1, "character": 0}, "end": {"line": max(end_line, c.line - 1), "character": 0}},
                    "selectionRange": sel, "children": children})
    return out


def completion(uri, pos):
    text = ws.docs.get(uri, "")
    line0, col = pos["line"], pos["character"]
    line = text.split("\n")[line0] if line0 < len(text.split("\n")) else ""
    before = line[:col]
    classes = ws.all_classes(uri)
    items = []

    # member access: `recv.` or `recv.par`
    m = re.search(r"([A-Za-z_]\w*)\s*\.\s*([A-Za-z_]\w*)?$", before)
    if m and not re.search(r"\b(bring|native)\b", before):
        recv = m.group(1)
        t = resolve_receiver(uri, text, line0, recv)
        if t:
            static_only = recv in classes and recv != "self" and var_type(text, recv, line0) is None
            targs = type_args(t)
            for kind, name, decl, owner in members(classes, t):
                if kind == "method":
                    if static_only and not decl.static:
                        continue
                    if not static_only and decl.static:
                        continue
                    if decl.access == "private" and recv != "self":
                        continue
                    if name == "init":
                        continue
                    sig = method_sig(decl, owner, targs)
                    snippet = name + "(" + ", ".join(f"${{{i + 1}:{p}}}" for i, (p, _) in enumerate(decl.params)) + ")"
                    items.append({"label": name, "kind": 2, "detail": sig, "insertText": snippet,
                                  "insertTextFormat": 2, "documentation": f"from {owner.name}"})
                elif not static_only:
                    if decl.access == "private" and recv != "self":
                        continue
                    ft = subst(decl.type, owner.tparams, targs) if owner.tparams else decl.type
                    items.append({"label": name, "kind": 5, "detail": f"{name}: {ft}", "documentation": f"from {owner.name}"})
            return items
        return items

    # `new Foo(`
    if re.search(r"\bnew\s+\w*$", before) or re.search(r"(instanceof|as)\s+\w*$", before) \
            or re.search(r":\s*\w*$", before) or re.search(r"->\s*\w*$", before) or re.search(r"<\s*\w*$", before):
        for name, c in classes.items():
            if not name.startswith("__"):
                items.append({"label": name, "kind": 8 if c.interface else 7, "detail": class_sig(c)})
        for p in PRIMITIVES:
            items.append({"label": p, "kind": 14})
        return items

    # general position: keywords, classes, snippets, names in scope
    for k in KEYWORDS:
        items.append({"label": k, "kind": 14})
    for k, body in SNIPPETS.items():
        items.append({"label": k, "kind": 15, "insertText": body, "insertTextFormat": 2, "detail": "snippet"})
    for p in PRIMITIVES:
        items.append({"label": p, "kind": 14})
    for name, c in classes.items():
        if not name.startswith("__"):
            items.append({"label": name, "kind": 7, "detail": class_sig(c)})
    for b in ("print", "len", "str", "int", "float", "range", "hash", "typename", "heap_live"):
        items.append({"label": b, "kind": 3, "detail": "built-in"})
    # locals and parameters seen above the cursor in this method
    seen = set()
    lines = text.split("\n")
    for i in range(line0, -1, -1):
        for nm in re.findall(r"\b([a-z_]\w*)\s*:\s*[A-Za-z_]", lines[i]):
            if nm not in seen and nm not in quill.KEYWORDS:
                seen.add(nm)
                items.append({"label": nm, "kind": 6, "detail": var_type(text, nm, line0) or ""})
        if re.match(r"\s*(static\s+)?(public\s+|private\s+|protected\s+)*def\b", lines[i]) or lines[i].startswith("class "):
            break
    return items


def hover(uri, pos):
    text = ws.docs.get(uri, "")
    line0, col = pos["line"], pos["character"]
    word, a, b = word_at(text, line0, col)
    if not word:
        return None
    classes = ws.all_classes(uri)
    line = text.split("\n")[line0]
    md = None
    # member of a receiver?
    m = re.search(r"([A-Za-z_]\w*)\s*\.\s*$", line[:a])
    if m:
        t = resolve_receiver(uri, text, line0, m.group(1))
        if t:
            targs = type_args(t)
            for kind, name, decl, owner in members(classes, t):
                if name == word:
                    md = (method_sig(decl, owner, targs) if kind == "method"
                          else f"{decl.access} {name}: {subst(decl.type, owner.tparams, targs)}") + f"\n\n// from {owner.name}"
                    break
    if md is None and word in classes:
        c = classes[word]
        ms = [f"    {method_sig(x)}" for x in c.methods if x.access != "private"][:12]
        md = class_sig(c) + (":\n" + "\n".join(ms) if ms else "")
    if md is None and word == "self":
        c = class_at(ws.parse_own(uri), line0 + 1)
        md = f"self: {c.name}" if c else None
    if md is None and word in quill.KEYWORDS:
        return None
    if md is None:
        t = var_type(text, word, line0)
        if t:
            md = f"{word}: {t}"
    if md is None:
        return None
    return {"contents": {"kind": "markdown", "value": "```quill\n" + md + "\n```"},
            "range": {"start": {"line": line0, "character": a}, "end": {"line": line0, "character": b}}}


def location_of(decl_file, line1, name):
    if decl_file in (None, "<built-in>"):
        return None
    try:
        with builtins.open(decl_file, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    # prefer an unsaved buffer
    for u, t in ws.docs.items():
        if os.path.realpath(uri_to_path(u)) == os.path.realpath(decl_file):
            text = t
    return {"uri": path_to_uri(decl_file), "range": name_range(text, line1, name)}


def definition(uri, pos):
    text = ws.docs.get(uri, "")
    line0, col = pos["line"], pos["character"]
    word, a, b = word_at(text, line0, col)
    if not word:
        return None
    classes = ws.all_classes(uri)
    line = text.split("\n")[line0]
    m = re.search(r"([A-Za-z_]\w*)\s*\.\s*$", line[:a])
    if m:
        t = resolve_receiver(uri, text, line0, m.group(1))
        if t:
            for kind, name, decl, owner in members(classes, t):
                if name == word:
                    return location_of(getattr(owner, "file", None), decl.line, name)
    if word in classes:
        c = classes[word]
        return location_of(getattr(c, "file", None), c.line, c.name)
    # a local variable: jump to its declaration
    lines = text.split("\n")
    pat = re.compile(rf"\b{re.escape(word)}\s*(?::|=)")
    for i in range(line0, -1, -1):
        mm = pat.search(lines[i])
        if mm and (i != line0 or mm.start() < a):
            return {"uri": uri, "range": {"start": {"line": i, "character": mm.start()}, "end": {"line": i, "character": mm.start() + len(word)}}}
    return None


def signature_help(uri, pos):
    text = ws.docs.get(uri, "")
    line0, col = pos["line"], pos["character"]
    before = text.split("\n")[line0][:col]
    # find the innermost unclosed `(`
    depth, i, commas = 0, len(before) - 1, 0
    while i >= 0:
        ch = before[i]
        if ch == ")":
            depth += 1
        elif ch == "(":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            commas += 1
        i -= 1
    if i < 0:
        return None
    head = before[:i]
    classes = ws.all_classes(uri)
    nm = re.search(r"(?:([A-Za-z_]\w*)\s*\.\s*)?([A-Za-z_]\w*)\s*$", head)
    if not nm:
        return None
    recv, name = nm.group(1), nm.group(2)
    decl = owner = None
    targs = []
    if re.search(r"\bnew\s+$", head[:nm.start()] + head[nm.start():nm.start()]) or re.search(r"\bnew\s+" + re.escape(name) + r"\s*$", head):
        c = classes.get(name)
        if c:
            decl = next((m for m in c.methods if m.name == "init"), None)
            owner = c
    elif recv:
        t = resolve_receiver(uri, text, line0, recv)
        if t:
            targs = type_args(t)
            for kind, n, d, o in members(classes, t):
                if kind == "method" and n == name:
                    decl, owner = d, o
                    break
    if decl is None:
        return None
    label = method_sig(decl, owner, targs)
    params = [{"label": f"{p}: {subst(t, owner.tparams, targs) if owner.tparams and targs else t}"} for p, t in decl.params]
    return {"signatures": [{"label": label, "parameters": params}], "activeSignature": 0,
            "activeParameter": min(commas, max(len(params) - 1, 0))}


def workspace_symbols(query):
    out = []
    q = query.lower()
    for root in ws.roots:
        for dirpath, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "build", "out")]
            for fn in files:
                if not fn.endswith(".ql"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with builtins.open(p, encoding="utf-8") as f:
                        text = f.read()
                    decls = quill.Parser(quill.lex(text)).program()
                except Exception:
                    continue
                for c in decls:
                    items = [(c.name, 5, c.line, None)] + [(m.name, 6, m.line, c.name) for m in c.methods]
                    for nm, kind, line, cont in items:
                        if q in nm.lower():
                            out.append({"name": nm, "kind": kind, "containerName": cont or "",
                                        "location": {"uri": path_to_uri(p), "range": name_range(text, line, nm)}})
                if len(out) > 300:
                    return out
    return out


# ───────────────────────────── server loop ─────────────────────────────

def publish(uri):
    notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": ws.diagnose(uri)})


def handle(msg, pending_diag):
    method, id_, p = msg.get("method"), msg.get("id"), msg.get("params") or {}
    try:
        if method == "initialize":
            ws.roots = [uri_to_path(f["uri"]) for f in (p.get("workspaceFolders") or [])]
            if not ws.roots and p.get("rootUri"):
                ws.roots = [uri_to_path(p["rootUri"])]
            respond(id_, {"capabilities": {
                "textDocumentSync": {"openClose": True, "change": 1, "save": {"includeText": False}},
                "completionProvider": {"triggerCharacters": [".", " "], "resolveProvider": False},
                "hoverProvider": True, "definitionProvider": True,
                "documentSymbolProvider": True, "workspaceSymbolProvider": True,
                "signatureHelpProvider": {"triggerCharacters": ["(", ","]},
            }, "serverInfo": {"name": "quill-lsp", "version": "1.0.0"}})
        elif method == "shutdown":
            respond(id_, None)
        elif method == "exit":
            sys.exit(0)
        elif method == "textDocument/didOpen":
            d = p["textDocument"]
            ws.docs[d["uri"]] = d["text"]
            ws.parse_own(d["uri"])
            pending_diag.add(d["uri"])
        elif method == "textDocument/didChange":
            uri = p["textDocument"]["uri"]
            ws.docs[uri] = p["contentChanges"][-1]["text"]
            ws.parse_own(uri)
            pending_diag.add(uri)
        elif method == "textDocument/didSave":
            pending_diag.add(p["textDocument"]["uri"])
        elif method == "textDocument/didClose":
            uri = p["textDocument"]["uri"]
            ws.docs.pop(uri, None)
            notify("textDocument/publishDiagnostics", {"uri": uri, "diagnostics": []})
        elif method == "textDocument/completion":
            respond(id_, {"isIncomplete": False, "items": completion(p["textDocument"]["uri"], p["position"])})
        elif method == "textDocument/hover":
            respond(id_, hover(p["textDocument"]["uri"], p["position"]))
        elif method == "textDocument/definition":
            respond(id_, definition(p["textDocument"]["uri"], p["position"]))
        elif method == "textDocument/documentSymbol":
            respond(id_, document_symbols(p["textDocument"]["uri"]))
        elif method == "textDocument/signatureHelp":
            respond(id_, signature_help(p["textDocument"]["uri"], p["position"]))
        elif method == "workspace/symbol":
            respond(id_, workspace_symbols(p.get("query", "")))
        elif id_ is not None:
            respond(id_, error={"code": -32601, "message": f"method not found: {method}"})
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"error handling {method}: {e!r}\n")
        if id_ is not None:
            respond(id_, None)


def main():
    q = queue.Queue()

    def reader():
        stream = sys.stdin.buffer
        while True:
            m = read_message(stream)
            q.put(m)
            if m is None:
                return

    threading.Thread(target=reader, daemon=True).start()
    pending = set()
    while True:
        try:
            msg = q.get(timeout=0.15 if pending else None)
        except queue.Empty:
            msg = "idle"
        if msg is None:
            return
        if msg == "idle":
            # the editor went quiet: now run the (slower) compiler check once per document
            for uri in list(pending):
                if uri in ws.docs:
                    publish(uri)
            pending.clear()
            continue
        handle(msg, pending)


if __name__ == "__main__":
    main()

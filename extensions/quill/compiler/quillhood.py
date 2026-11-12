"""quill hood: Under the hood.

Shows what the compiler does with a program: the modules it loaded, how each class is
laid out in memory, which generic classes were instantiated, where reference counts
change and where exceptions are checked, how native (C/C++) calls convert their
arguments, and the exact commands that built the executable.

    quill hood [file.ql]                    the whole story, in short
    quill hood file.ql --only classes       one or more sections:
                                            overview modules classes generics
                                            functions native build
    quill hood file.ql --class Point        the memory layout of one class
    quill hood file.ql --ir Main.main       the LLVM IR of one function, annotated
    quill hood file.ql --no-build           skip running clang

Nothing here changes how your program behaves; it only explains it.
"""
import os
import re
import sys
import time

STD_ROOT = os.path.realpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "std"))
SECTIONS = ["overview", "modules", "classes", "generics", "functions", "native", "build"]
SIZES = {"i64": 8, "double": 8, "ptr": 8, "i1": 1}


def add_parser(sub):
    sp = sub.add_parser("hood", help="Under the hood: show what the compiler does with a program",
                        description=__doc__, formatter_class=__import__("argparse").RawDescriptionHelpFormatter)
    sp.add_argument("file", nargs="?", help="a .ql file (default: the project's start module)")
    sp.add_argument("--only", metavar="SECTIONS", help="comma separated: " + ", ".join(SECTIONS))
    sp.add_argument("--class", dest="cls", metavar="NAME", help="show the memory layout of one class")
    sp.add_argument("--ir", metavar="Class.method", help="show the LLVM IR of a function, annotated")
    sp.add_argument("--all", action="store_true", help="list every function and class, not just the largest")
    sp.add_argument("--no-build", action="store_true", help="do not run the C toolchain")
    sp.add_argument("-O", default="1", help="optimization level used for the build section (0-3)")
    return sp


def shown_path(p):
    rel = os.path.relpath(p)
    return p if rel.startswith("..") else rel


def heading(text):
    print()
    print(f"== {text} " + "=" * max(3, 66 - len(text)))


def split_functions(ir):
    """symbol -> list of IR lines, for every function the compiler wrote."""
    funcs, cur, name = {}, None, None
    for line in ir.split("\n"):
        m = re.match(r'define [^@]*@("?)([^"(]+)\1\(', line)
        if m:
            name, cur = m.group(2), []
            funcs[name] = cur
        elif cur is not None:
            if line == "}":
                cur = None
            else:
                cur.append(line)
    return funcs


def facts(lines):
    body = [ln for ln in lines if ln.startswith("  ") and not ln.strip().startswith(";")]
    text = "\n".join(body)
    return dict(
        instr=len(body),
        retain=text.count("@quill_retain("),
        release=len(re.findall(r"@quill_release_(?:str|obj)\(", text)),
        alloc=len(re.findall(r"@quill_alloc\(", text)),
        checks=len(re.findall(r"load i32, ptr @quill_pending", text)),
        unwind=sum(1 for ln in lines if re.match(r"unw[.\w]*:", ln)),
        calls=text.count(" call "),
    )


def layout(mod, ci):
    """[(offset, name, type, llvm type, size)] and the total payload size."""
    rows, off = [("0", "(vtable)", "ptr", "ptr", 8)], 8
    for name, t in ci.fields:
        lt = mod.llty(t)
        size = SIZES.get(lt, 8)
        off = (off + size - 1) // size * size
        rows.append((str(off), name, t, lt, size))
        off += size
    total = (off + 7) // 8 * 8
    return rows, total


def kind_of(ci, info):
    if ci.name in info["builtin"]:
        return "built-in"
    path = info["origin"].get(ci.name, "")
    if path and os.path.realpath(path).startswith(STD_ROOT):
        return "std library"
    if "[" in ci.name:
        return "generic instance"
    if ci.is_interface:
        return "interface"
    return "yours"


def table(rows, header, widths=None):
    cols = list(zip(*([header] + rows))) if rows else [[h] for h in header]
    w = [max(len(str(c)) for c in col) for col in cols]
    print("  " + "  ".join(str(h).ljust(w[i]) for i, h in enumerate(header)))
    print("  " + "  ".join("-" * w[i] for i in range(len(header))))
    for r in rows:
        print("  " + "  ".join(str(c).ljust(w[i]) for i, c in enumerate(r)))


def annotate(line):
    notes = [
        ("@quill_retain(", "+1 reference"),
        ("@quill_release_str(", "-1 reference (the string is freed at 0)"),
        ("@quill_release_obj(", "-1 reference (the object is dropped at 0)"),
        ("@quill_alloc(", "heap allocation: a 16 byte header (strong and weak counts) then the payload"),
        ("load i32, ptr @quill_pending", "has an exception been thrown? (checked after every call)"),
        ("@quill_str_from_c(", "copy a C string into a new Quill string"),
        ("inttoptr", "an address kept as an int becomes a pointer again, for the C call"),
        ("ptr null, i32 1", "the size of the object (the usual sizeof trick)"),
    ]
    for key, note in notes:
        if key in line:
            return f"{line:<70} ; {note}"
    if re.match(r"unw[.\w]*:", line):
        return f"{line:<70} ; cleanup that runs when an exception passes through"
    return line


def run(a):
    import quill
    path = a.file
    if path is None:
        import quillpkg
        try:
            path, _ = quillpkg.default_entry()
        except quillpkg.PackageError as e:
            print(f"quill: {e}", file=sys.stderr)
            return 1
    natives, info = quill.NativeSpec(), {}
    t0 = time.time()
    try:
        ir = quill.compile_file(path, natives, info)
    except quill.CompileError as e:
        print(f"{e.file or path}:{e.line}: error: {e.msg}", file=sys.stderr)
        return 1
    compile_secs = time.time() - t0
    mod = info["module"]
    funcs = split_functions(ir)
    stats = {n: facts(lines) for n, lines in funcs.items()}
    only = set((a.only or "").split(",")) - {""}
    unknown = only - set(SECTIONS)
    if unknown:
        print(f"quill hood: unknown section {', '.join(sorted(unknown))} (choose from {', '.join(SECTIONS)})", file=sys.stderr)
        return 2

    print(f"Under the hood: {shown_path(path)}")

    if a.ir:
        want = [n for n in funcs if n == a.ir] or [n for n in funcs if a.ir in n]
        if not want:
            print(f"quill hood: no function matches {a.ir}. Try one of: " +
                  ", ".join(sorted(n for n in funcs if not n.startswith(("drop.", "quill_")))[:12]), file=sys.stderr)
            return 1
        for n in want[:3]:
            heading(f"LLVM IR of {n}")
            f = stats[n]
            print(f"  {f['instr']} instructions, {f['retain']} retain, {f['release']} release, "
                  f"{f['checks']} exception checks, {f['alloc']} allocations")
            print()
            for line in funcs[n]:
                print("  " + annotate(line))
        return 0

    if a.cls:
        ci = mod.classes.get(a.cls) or next((c for n, c in mod.classes.items() if n.endswith("." + a.cls)), None)
        if not ci:
            print(f"quill hood: no class {a.cls}", file=sys.stderr)
            return 1
        show_layout(mod, ci, info)
        return 0

    def want(section):
        return not only or section in only

    classes = list(mod.classes.values())
    user_funcs = [(n, s) for n, s in stats.items() if not n.startswith(("quill_", "drop.", "main"))]
    totals = {k: sum(s[k] for s in stats.values()) for k in ("instr", "retain", "release", "alloc", "checks", "unwind")}

    if want("overview"):
        heading("The pipeline")
        mods = info.get("modules", [])
        print(f"  1. read       {len(mods)} module(s), {sum(m['tokens'] for m in mods)} tokens")
        yours = [c for c in classes if kind_of(c, info) == "yours"]
        gens = [c for c in classes if "[" in c.name]
        std = [c for c in classes if kind_of(c, info) == "std library"]
        print(f"  2. understand {len(classes)} classes: {len(yours)} yours, {len(std)} from std, "
              f"{len(gens)} generic instances, {len(classes) - len(yours) - len(gens) - len(std)} built-in or interface; "
              f"{len(mod.iface_ids)} interface method id(s)")
        print(f"  3. generate   {len(funcs)} functions, {totals['instr']} LLVM instructions "
              f"({len(ir.splitlines())} lines of IR, {len(ir)} bytes) in {compile_secs * 1000:.0f} ms")
        print(f"  4. memory     {totals['retain']} retain and {totals['release']} release sites, "
              f"{totals['alloc']} allocation sites; {len(mod.strings)} string literal(s)")
        print(f"  5. exceptions {totals['checks']} checks after calls, {totals['unwind']} cleanup paths")
        if natives.active:
            print(f"  6. native     {len(mod.native_bindings)} C function(s) bound; "
                  f"{len(natives.sources)} source file(s), {len(natives.libs)} link flag(s)")
        print(f"  {'7' if natives.active else '6'}. build       clang compiles the IR (see: quill hood --only build)")

    if want("modules"):
        heading("Modules")
        rows = []
        for m in info.get("modules", []):
            rows.append((shown_path(m["path"]),
                         m["package"], m["alias"] or "-", len(m["classes"]), m["lines"], "yes" if m["native"] else ""))
        table(rows, ["file", "package", "as", "classes", "lines", "native"])

    if want("classes"):
        heading("Classes")
        rows = []
        for ci in classes:
            _, size = layout(mod, ci)
            kind = kind_of(ci, info)
            if kind == "built-in" and not a.all:
                continue
            rows.append((ci.name, kind, ci.parent.name if ci.parent else "-", len(ci.fields),
                         "-" if ci.is_interface else 16 + size, len(ci.vtable)))
        table(rows, ["class", "kind", "parent", "fields", "heap bytes", "vtable slots"])
        print("  heap bytes = 16 byte header (strong and weak count) + vtable pointer + fields.")
        print("  built-in classes are hidden; --all shows them. --class NAME shows one layout.")

    if want("generics"):
        heading("Generics")
        inst = [c for c in classes if "[" in c.name]
        if not inst:
            print("  none instantiated")
        else:
            print("  Generics are templates: every method is compiled again for each type.")
            rows = []
            for c in inst:
                base = c.name.split("[", 1)[0]
                rows.append((c.name, f"{base}[{', '.join(mod.templates[base].tparams)}]" if base in mod.templates else "-",
                             len(c.methods), sum(stats.get(f'{c.name}.{m}', {}).get("instr", 0) for m in c.methods)))
            table(rows, ["instance", "template", "methods", "instructions"])

    if want("functions"):
        heading("Functions" + ("" if a.all else " (largest first; --all for every one)"))
        rows = sorted(((n, s) for n, s in stats.items() if not n.startswith(("quill_", "drop.", "itable."))),
                      key=lambda x: -x[1]["instr"])
        if not a.all:
            rows = rows[:12]
        table([(n, s["instr"], s["calls"], s["retain"], s["release"], s["alloc"], s["checks"], s["unwind"])
               for n, s in rows],
              ["function", "instr", "calls", "retain", "release", "alloc", "exc checks", "cleanups"])
        print("  retain/release: reference count changes. exc checks: 'did that call throw?' after each call.")
        print("  cleanups: code that releases locals when an exception passes through. --ir NAME shows a function.")

    if want("native"):
        if natives.active or mod.native_bindings:
            heading("Native code")
            print("  Pointers never reach Quill code: they are ints inside wrapper objects.")
            print(f"  modules: {', '.join(os.path.basename(m) for m in natives.modules)}")
            if natives.sources: print(f"  compiled with the program: {', '.join(shown_path(s) for s in natives.sources)}")
            if natives.libs or natives.libdirs: print(f"  linked: {' '.join(natives.libdirs + natives.libs)}")
            if natives.includes or natives.flags: print(f"  compiler flags: {' '.join(natives.includes + natives.flags)}")
            for name, sig, steps, ret in mod.native_bindings:
                print(f"\n  {name}  <->  {sig}")
                for st in steps:
                    print(f"      in   {st}")
                print(f"      out  {ret}")
            if not mod.native_bindings:
                print("  (no native methods are used by this program)")
        elif only and "native" in only:
            heading("Native code")
            print("  this program uses no native code")

    if want("build") and not a.no_build:
        heading("Build")
        import tempfile
        quill.COMMAND_LOG.clear()
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "prog")
            os.environ.setdefault("QUILL_QUIET_NATIVE", "1")
            try:
                exe = quill.build(path, out, f"-O{a.O}")
                size = os.path.getsize(exe)
            except SystemExit:
                exe, size = None, 0
            for cmd, code, secs in quill.COMMAND_LOG:
                shown = " ".join(os.path.basename(c) if os.sep in c or "/" in c else c for c in cmd)
                print(f"  [{secs:5.2f}s] {'ok ' if code == 0 else 'ERR'} {shown}")
            if exe:
                print(f"  result: a {size // 1024} KiB native executable")
    return 0


def show_layout(mod, ci, info):
    heading(f"Layout of {ci.name}")
    rows, total = layout(mod, ci)
    print(f"  kind: {kind_of(ci, info)}   parent: {ci.parent.name if ci.parent else '-'}")
    print(f"  a 16 byte header comes first: strong count at -16, weak count at -8 (before the pointer you hold)")
    print()
    table(rows, ["offset", "field", "Quill type", "LLVM type", "bytes"])
    print(f"\n  payload {total} bytes, heap block {16 + total} bytes")
    if ci.vtable:
        print("\n  vtable (slot: method)")
        for i, name in enumerate(ci.vtable):
            print(f"    {i + 2}: {name}")
        print("    0: drop (releases the fields)    1: interface table")
    print("\n  references to this object are counted; a field of class type is a pointer to its own block.")

#!/usr/bin/env python3
"""End-to-end tests: spawn the language server and talk LSP to it."""
import json, os, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER = os.path.join(ROOT, "extensions", "quill", "server", "quill_lsp.py")

class Client:
    def __init__(self):
        self.p = subprocess.Popen([sys.executable, SERVER], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.n = 0
        self.diags = {}
    def send(self, obj):
        b = json.dumps(obj).encode()
        self.p.stdin.write(b"Content-Length: %d\r\n\r\n" % len(b) + b); self.p.stdin.flush()
    def read(self):
        n = 0
        while True:
            line = self.p.stdout.readline().strip()
            if not line: break
            if line.lower().startswith(b"content-length:"): n = int(line.split(b":")[1])
        return json.loads(self.p.stdout.read(n))
    def request(self, method, params):
        self.n += 1; self.send({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params})
        while True:
            m = self.read()
            if m.get("method") == "textDocument/publishDiagnostics": self.diags[m["params"]["uri"]] = m["params"]["diagnostics"]; continue
            if m.get("id") == self.n: return m.get("result")
    def notify(self, method, params): self.send({"jsonrpc": "2.0", "method": method, "params": params})
    def wait_diags(self, uri):
        self.diags.pop(uri, None)
        t = time.time()
        while uri not in self.diags and time.time() - t < 20:
            m = self.read()
            if m.get("method") == "textDocument/publishDiagnostics": self.diags[m["params"]["uri"]] = m["params"]["diagnostics"]
        return self.diags.get(uri)

GOOD = '''class Animal:
    name: str
    def init(self, name: str):
        self.name = name
    def speak(self) -> str:
        return "..."
    private def secret(self) -> int:
        return 1

class Dog < Animal:
    def speak(self) -> str:
        return "Woof"
    def fetch(self, times: int) -> int:
        return times

class Main:
    static def main():
        d: Dog = new Dog("Rex")
        xs = new List[int]()
        print(d.speak())
'''

failures = []
sys.path.insert(0, os.path.dirname(SERVER))
import quill_lsp
def check(name, cond, info=""):
    print(("pass " if cond else "FAIL ") + name + ("" if cond else f"  {info}"))
    if not cond: failures.append(name)

for uri, want in [("file:///c%3A/Users/a%20b/x.ql", "c:\\Users\\a b\\x.ql"), ("file:///C:/Users/x.ql", "C:\\Users\\x.ql"), ("file://srv/share/x.ql", "\\\\srv\\share\\x.ql")]:
    got = quill_lsp.uri_to_path(uri, windows=True)
    check("windows uri " + uri, got == want, got)
check("posix uri", quill_lsp.uri_to_path("file:///Users/a%20b/x.ql", windows=False) == "/Users/a b/x.ql")

c = Client()
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "a.ql"); uri = "file://" + path
    open(path, "w").write(GOOD)
    c.request("initialize", {"rootUri": "file://" + d, "capabilities": {}})
    c.notify("initialized", {})
    c.notify("textDocument/didOpen", {"textDocument": {"uri": uri, "languageId": "quill", "version": 1, "text": GOOD}})
    check("clean file has no diagnostics", c.wait_diags(uri) == [])

    bad = GOOD.replace("return times", "return \"x\"")
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 2}, "contentChanges": [{"text": bad}]})
    dg = c.wait_diags(uri)
    check("type error reported on the right line", dg and dg[0]["range"]["start"]["line"] == 13, dg)

    syn = GOOD.replace("name: str\n", "name: str\n    ???\n")
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 3}, "contentChanges": [{"text": syn}]})
    dg = c.wait_diags(uri)
    check("syntax error reported", dg and "unexpected" in dg[0]["message"], dg)

    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 4}, "contentChanges": [{"text": GOOD}]})
    check("error clears when fixed", c.wait_diags(uri) == [])

    syms = c.request("textDocument/documentSymbol", {"textDocument": {"uri": uri}})
    names = [s["name"] for s in syms]
    check("document symbols list classes", names == ["Animal", "Dog", "Main"], names)
    check("symbols have members", [x["name"] for x in syms[1]["children"]] == ["speak", "fetch"], syms[1])

    lines = GOOD.split("\n")
    li = next(i for i, l in enumerate(lines) if "print(d.speak" in l)
    col = lines[li].index("d.speak") + 2
    comp = c.request("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": li, "character": col}})
    labels = {i["label"] for i in comp["items"]}
    check("member completion includes own and inherited", {"speak", "fetch", "name"} <= labels, labels)
    check("member completion hides private and init", "secret" not in labels and "init" not in labels, labels)

    li2 = next(i for i, l in enumerate(lines) if "xs = new List" in l)
    new_text = GOOD.replace("print(d.speak())", "xs.")
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 5}, "contentChanges": [{"text": new_text}]})
    nl = new_text.split("\n"); li3 = next(i for i, l in enumerate(nl) if l.strip() == "xs.")
    comp = c.request("textDocument/completion", {"textDocument": {"uri": uri}, "position": {"line": li3, "character": len(nl[li3])}})
    labels = {i["label"] for i in comp["items"]}
    check("generic List members complete", {"add", "get", "size"} <= labels, sorted(labels)[:10])
    sigs = {i["label"]: i["detail"] for i in comp["items"]}
    check("generic signature substitutes T", "int" in sigs.get("add", ""), sigs.get("add"))

    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 6}, "contentChanges": [{"text": GOOD}]})
    h = c.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": {"line": li, "character": col + 1}})
    check("hover shows method signature", h and "def speak" in h["contents"]["value"], h)
    h = c.request("textDocument/hover", {"textDocument": {"uri": uri}, "position": {"line": 9, "character": 7}})
    check("hover on class shows inheritance", h and "class Dog < Animal" in h["contents"]["value"], h)

    df = c.request("textDocument/definition", {"textDocument": {"uri": uri}, "position": {"line": li, "character": col + 1}})
    check("go to definition of a method", df and df["uri"] == uri and df["range"]["start"]["line"] == 10, df)
    df = c.request("textDocument/definition", {"textDocument": {"uri": uri}, "position": {"line": 9, "character": 16}})
    check("go to definition of parent class", df and df["range"]["start"]["line"] == 0, df)

    sh_text = GOOD.replace("print(d.speak())", "d.fetch(")
    c.notify("textDocument/didChange", {"textDocument": {"uri": uri, "version": 7}, "contentChanges": [{"text": sh_text}]})
    sl = sh_text.split("\n"); lj = next(i for i, l in enumerate(sl) if "d.fetch(" in l)
    sh = c.request("textDocument/signatureHelp", {"textDocument": {"uri": uri}, "position": {"line": lj, "character": len(sl[lj])}})
    check("signature help", sh and "fetch(times: int)" in sh["signatures"][0]["label"], sh)

    ws_syms = c.request("workspace/symbol", {"query": "dog"})
    check("workspace symbols search", ws_syms and ws_syms[0]["name"] == "Dog", ws_syms)

c.request("shutdown", None); c.notify("exit", {})
print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)

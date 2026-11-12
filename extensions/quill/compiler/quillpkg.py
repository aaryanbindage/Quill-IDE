"""Quill's package manager: manifests, versions, dependency resolution, the lock
file, fetching, and the module lookup the compiler uses for `bring`.

A project is a folder with a `quill.pkg` manifest. Dependencies come from git
repositories (their versions are the repository's tags) or from local folders.
`quill install` resolves them, writes `quill.lock`, and unpacks git packages under
`.quill/deps/`. See docs/packages.md.
"""

import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import dataclass, field

MANIFEST = "quill.pkg"
LOCKFILE = "quill.lock"
STORE = ".quill"
SKIP_DIRS = {".git", STORE, "build"}
NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class PackageError(Exception):
    pass


class IntegrityError(PackageError):
    """Package files do not match the hash in the lock file."""


# ───────────────────────────── versions ─────────────────────────────

def parse_version(text, what="version"):
    m = re.fullmatch(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", text.strip())
    if not m:
        raise PackageError(f"bad {what} {text!r}: write it as MAJOR.MINOR.PATCH")
    return tuple(int(g or 0) for g in m.groups())


def fmt_version(v):
    return ".".join(map(str, v))


@dataclass(frozen=True)
class Constraint:
    """Which versions a `needs` line accepts: `any`, `1.4` (that or newer, same
    major), `=1.4.2` (exactly), or `1.2..2.0` (from 1.2.0 up to, excluding, 2.0.0)."""
    text: str
    lo: tuple = (0, 0, 0)
    hi: tuple = None          # exclusive upper bound; None = unbounded

    @staticmethod
    def parse(text):
        t = text.strip()
        if t in ("", "any"):
            return Constraint("any")
        if t.startswith("="):
            v = parse_version(t[1:], "constraint")
            return Constraint(t, v, (v[0], v[1], v[2] + 1))
        if ".." in t:
            a, b = t.split("..", 1)
            lo, hi = parse_version(a, "constraint"), parse_version(b, "constraint")
            if lo >= hi:
                raise PackageError(f"empty range {t!r}")
            return Constraint(t, lo, hi)
        lo = parse_version(t, "constraint")
        # compatible releases: anything newer within the same major version
        # (for 0.x, within the same minor, since 0.x makes no stability promise)
        hi = (lo[0] + 1, 0, 0) if lo[0] > 0 else (0, lo[1] + 1, 0)
        return Constraint(t, lo, hi)

    def allows(self, v):
        return v >= self.lo and (self.hi is None or v < self.hi)

    def __str__(self):
        return self.text


# ───────────────────────────── manifest ─────────────────────────────

@dataclass(frozen=True)
class Source:
    kind: str                 # "path" or "git"
    where: str                # absolute folder, or repository location
    ref_kind: str = ""        # "", "branch", "rev" or "tag" (git only)
    ref: str = ""

    def describe(self):
        s = f"{self.kind} {self.where}"
        return s + (f" {self.ref_kind} {self.ref}" if self.ref_kind else "")


@dataclass
class Need:
    name: str
    constraint: Constraint
    source: Source
    line: int = 0


@dataclass
class Manifest:
    dir: str
    name: str = ""
    version: tuple = (0, 0, 0)
    about: str = ""
    source: str = "src"
    start: str = ""
    needs: list = field(default_factory=list)

    @property
    def src_dir(self):
        return os.path.join(self.dir, self.source)


def tokens(line, lineno, where):
    """Split a manifest line into words; "double quotes" keep spaces in one word,
    and an unquoted # starts a comment."""
    out, cur, quoted, i = [], "", False, 0
    started = False
    while i < len(line):
        ch = line[i]
        if quoted:
            if ch == '"':
                quoted = False
            else:
                cur += ch
        elif ch == '"':
            quoted, started = True, True
        elif ch == "#":
            break
        elif ch in " \t":
            if cur or started:
                out.append(cur)
            cur, started = "", False
        else:
            cur += ch
        i += 1
    if quoted:
        raise PackageError(f"{where}:{lineno}: unterminated quote")
    if cur or started:
        out.append(cur)
    return out


def looks_remote(where):
    return "://" in where or re.match(r"^[\w.-]+@[\w.-]+:", where) is not None


def parse_manifest(text, dir, where=MANIFEST):
    m = Manifest(dir=os.path.abspath(dir))
    seen = set()
    for lineno, raw in enumerate(text.splitlines(), 1):
        words = tokens(raw, lineno, where)
        if not words:
            continue
        key, rest = words[0], words[1:]

        def fail(msg):
            raise PackageError(f"{where}:{lineno}: {msg}")

        if key in ("package", "version", "source", "start", "about"):
            if key in seen:
                fail(f"{key} is given twice")
            seen.add(key)
        if key == "about":
            m.about = raw.split(None, 1)[1].split("#")[0].strip() if len(raw.split(None, 1)) > 1 else ""
        elif key in ("package", "version", "source", "start"):
            if len(rest) != 1:
                fail(f"{key} takes one value")
            if key == "package":
                if not NAME_RE.match(rest[0]):
                    fail(f"package name {rest[0]!r} must be letters, digits and _ (it is used in `bring`)")
                m.name = rest[0]
            elif key == "version":
                try:
                    m.version = parse_version(rest[0])
                except PackageError as e:
                    fail(str(e))
            elif key == "source":
                m.source = rest[0]
            else:
                m.start = rest[0]
        elif key == "needs":
            m.needs.append(parse_need(rest, m.dir, where, lineno))
        else:
            fail(f"unknown keyword {key!r} (expected package, version, about, source, start or needs)")
    if not m.name:
        raise PackageError(f"{where}: missing `package NAME`")
    if "version" not in seen:
        raise PackageError(f"{where}: missing `version`")
    names = set()
    for n in m.needs:
        if n.name == m.name:
            raise PackageError(f"{where}:{n.line}: a package cannot need itself")
        if n.name in names:
            raise PackageError(f"{where}:{n.line}: {n.name} is needed twice")
        names.add(n.name)
    return m


def parse_need(words, dir, where, lineno):
    def fail(msg):
        raise PackageError(f"{where}:{lineno}: {msg}")

    if not words:
        fail("needs: expected a package name")
    name = words[0]
    if not NAME_RE.match(name):
        fail(f"package name {name!r} must be letters, digits and _")
    rest = words[1:]
    cons = "any"
    if rest and rest[0] != "at":
        cons, rest = rest[0], rest[1:]
    try:
        constraint = Constraint.parse(cons)
    except PackageError as e:
        fail(str(e))
    if not rest or rest[0] != "at":
        fail(f"needs {name}: say where it comes from, e.g. `at git URL` or `at path DIR`")
    rest = rest[1:]
    if len(rest) < 2 or rest[0] not in ("path", "git"):
        fail("expected `at path DIR` or `at git URL`")
    kind, where_ = rest[0], rest[1]
    rest = rest[2:]
    ref_kind = ref = ""
    if rest:
        if kind != "git" or len(rest) != 2 or rest[0] not in ("branch", "rev", "tag"):
            fail("unexpected words; git sources may end with `branch NAME`, `rev COMMIT` or `tag NAME`")
        ref_kind, ref = rest
    if where_.startswith("-") or ref.startswith("-"):
        fail("paths, urls and refs cannot start with '-'")
    if kind == "path" or (not looks_remote(where_) and not os.path.isabs(where_)):
        where_ = os.path.normpath(os.path.join(dir, where_))
    return Need(name, constraint, Source(kind, where_, ref_kind, ref), lineno)


def load_manifest(dir):
    path = os.path.join(dir, MANIFEST)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        raise PackageError(f"no {MANIFEST} in {dir}")
    return parse_manifest(text, dir, path)


def format_need(name, constraint, source, project_dir):
    def q(w):
        return f'"{w}"' if (not w or re.search(r"[\s#\"]", w)) else w

    where = source.where
    if source.kind == "path" or not looks_remote(where):
        try:
            where = os.path.relpath(where, project_dir).replace(os.sep, "/")
        except ValueError:
            pass                      # different drive on Windows: keep it absolute
    parts = ["needs", name, str(constraint), "at", source.kind, q(where)]
    if source.ref_kind:
        parts += [source.ref_kind, q(source.ref)]
    return " ".join(parts)


def edit_manifest(dir, drop=None, add=None):
    """Remove the `needs` line for `drop` and/or add (or replace) the line `add`,
    keeping comments and layout. Returns the old text so the caller can roll back."""
    path = os.path.join(dir, MANIFEST)
    with open(path, encoding="utf-8", newline="") as f:
        old = f.read()
    nl = "\r\n" if "\r\n" in old else "\n"
    add_name = add.split()[1] if add else None
    out, last_needs, placed = [], None, False
    for i, raw in enumerate(old.splitlines()):
        words = tokens(raw, i + 1, path)
        if words and words[0] == "needs" and len(words) > 1:
            if words[1] == drop:
                continue
            if words[1] == add_name:
                out.append(add)
                placed = True
            else:
                out.append(raw)
            last_needs = len(out)
        else:
            out.append(raw)
    if add and not placed:
        if last_needs is None:
            if out and out[-1].strip():
                out.append("")
            out.append(add)
        else:
            out.insert(last_needs, add)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(nl.join(out) + nl)
    return old


# ───────────────────────────── lock file ─────────────────────────────

@dataclass
class Locked:
    name: str
    version: tuple
    source: Source
    commit: str = ""
    hash: str = ""
    needs: list = field(default_factory=list)


LOCK_HEADER = "# quill.lock: written by `quill install`. Commit it; do not edit it.\n"


def write_lock(project, locked):
    out = [LOCK_HEADER, "lock 1\n"]
    for p in sorted(locked.values(), key=lambda p: p.name):
        out.append(f"\npinned {p.name} {fmt_version(p.version)}\n")
        s = p.source
        where = s.where
        if s.kind == "path":
            try:
                where = os.path.relpath(where, project).replace(os.sep, "/")
            except ValueError:
                pass                  # another drive: keep the absolute path
        out.append(f"    from {s.kind} {where}\n")
        if s.ref_kind:
            out.append(f"    ref {s.ref_kind} {s.ref}\n")
        if p.commit:
            out.append(f"    commit {p.commit}\n")
        if p.hash:
            out.append(f"    hash {p.hash}\n")
        for n in sorted(p.needs):
            out.append(f"    needs {n}\n")
    with open(os.path.join(project, LOCKFILE), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out))


def read_lock(project):
    """The locked packages, or None when there is no lock file."""
    path = os.path.join(project, LOCKFILE)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    locked, cur, seen_header = {}, None, False
    for lineno, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue

        def fail(msg):
            raise PackageError(f"{LOCKFILE}:{lineno}: {msg}")

        w = raw.split()
        if not raw.startswith(" "):
            if w[0] == "lock":
                if w[1:] != ["1"]:
                    fail("unsupported lock file version; update quill")
                seen_header = True
            elif w[0] == "pinned" and len(w) == 3:
                try:
                    cur = Locked(w[1], parse_version(w[2]), None)
                except PackageError as e:
                    fail(str(e))
                locked[cur.name] = cur
            else:
                fail("unexpected line")
        else:
            if cur is None:
                fail("entry outside a `pinned` block")
            if w[0] == "from" and len(w) >= 3:
                where = " ".join(w[2:])
                if w[1] == "path":
                    where = os.path.normpath(os.path.join(project, where))
                cur.source = Source(w[1], where, cur.source.ref_kind if cur.source else "",
                                    cur.source.ref if cur.source else "")
            elif w[0] == "ref" and len(w) == 3 and cur.source:
                cur.source = Source(cur.source.kind, cur.source.where, w[1], w[2])
            elif w[0] == "commit" and len(w) == 2:
                cur.commit = w[1]
            elif w[0] == "hash" and len(w) == 2:
                cur.hash = w[1]
            elif w[0] == "needs" and len(w) == 2:
                cur.needs.append(w[1])
            else:
                fail("unexpected entry")
    if not seen_header:
        raise PackageError(f"{LOCKFILE}: missing `lock 1` header")
    for p in locked.values():
        if p.source is None:
            raise PackageError(f"{LOCKFILE}: package {p.name} has no `from` line")
    return locked


# ───────────────────────────── hashing and unpacking ─────────────────────────────

def tree_hash(root):
    """sha256 over every file's path and contents (ignoring .git, .quill and build)."""
    h = hashlib.sha256()
    for base, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for name in sorted(files):
            full = os.path.join(base, name)
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            with open(full, "rb") as f:
                digest = hashlib.sha256(f.read()).hexdigest()
            h.update(f"{rel}\0{digest}\n".encode())
    return "sha256:" + h.hexdigest()


def safe_extract(tar, dest):
    root = os.path.realpath(dest)
    for member in tar.getmembers():
        target = os.path.realpath(os.path.join(dest, member.name))
        if target != root and not target.startswith(root + os.sep):
            raise PackageError(f"unsafe path in package archive: {member.name}")
        if member.issym() or member.islnk():
            raise PackageError(f"links are not allowed in packages: {member.name}")
    tar.extractall(dest, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))


def run_git(args, git_dir=None, cwd=None):
    cmd = ["git"] + (["--git-dir", git_dir] if git_dir else []) + args
    try:
        r = subprocess.run(cmd, capture_output=True, cwd=cwd)
    except FileNotFoundError:
        raise PackageError("git is required for git dependencies, but it was not found on PATH")
    if r.returncode:
        err = r.stderr.decode("utf-8", "replace").strip().splitlines()
        raise PackageError(f"git {args[0]} failed: {err[-1] if err else 'unknown error'}")
    return r.stdout


# ───────────────────────────── fetching candidates ─────────────────────────────

class Candidate:
    """One installable version of a package."""

    def __init__(self, version, source, loader, commit=""):
        self.version, self.source, self.commit = version, source, commit
        self._loader, self._manifest = loader, None

    @property
    def manifest(self):
        if self._manifest is None:
            self._manifest = self._loader()
        return self._manifest


class Fetcher:
    def __init__(self, home=None, offline=False):
        self.home = home or os.environ.get("QUILL_HOME") or os.path.join(os.path.expanduser("~"), ".quill")
        self.offline = offline or bool(os.environ.get("QUILL_OFFLINE"))
        self.refreshed = set()
        self.memo = {}

    # -- git cache: one bare mirror per repository --
    def mirror(self, url):
        key = hashlib.sha1(url.encode()).hexdigest()[:16]
        path = os.path.join(self.home, "git", key + ".git")
        if not os.path.isdir(path):
            if self.offline:
                raise PackageError(f"{url} is not in the cache and --offline was given")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            run_git(["clone", "--bare", "--quiet", "--", url, path])
            self.refreshed.add(url)
        elif url not in self.refreshed and not self.offline:
            run_git(["fetch", "--quiet", "--force", "--tags", "--", url,
                     "+refs/heads/*:refs/heads/*"], git_dir=path)
            self.refreshed.add(url)
        return path

    def git_manifest(self, mirror, rev, source):
        try:
            text = run_git(["show", f"{rev}:{MANIFEST}"], git_dir=mirror).decode("utf-8")
        except PackageError:
            raise PackageError(f"{source.where} at {rev[:12]} has no {MANIFEST}")
        return parse_manifest(text, source.where, f"{source.where}:{MANIFEST}")

    def candidates(self, source):
        key = source
        if key in self.memo:
            return self.memo[key]
        out = self.memo[key] = self._candidates(source)
        return out

    def _candidates(self, source):
        if source.kind == "path":
            if not os.path.isdir(source.where):
                raise PackageError(f"path dependency {source.where} does not exist")
            m = load_manifest(source.where)
            return [Candidate(m.version, source, lambda m=m: m)]
        mirror = self.mirror(source.where)
        if source.ref_kind:
            spec = {"branch": f"refs/heads/{source.ref}^{{commit}}",
                    "tag": f"refs/tags/{source.ref}^{{commit}}",
                    "rev": f"{source.ref}^{{commit}}"}[source.ref_kind]
            try:
                rev = run_git(["rev-parse", "--verify", "--quiet", spec], git_dir=mirror).decode().strip()
            except PackageError:
                raise PackageError(f"{source.where} has no {source.ref_kind} {source.ref}")
            m = self.git_manifest(mirror, rev, source)
            return [Candidate(m.version, source, lambda m=m: m, commit=rev)]
        out = []
        lines = run_git(["for-each-ref", "--format=%(refname:short) %(objectname) %(*objectname)",
                         "refs/tags"], git_dir=mirror).decode().splitlines()
        for line in lines:
            w = line.split()
            if not w:
                continue
            tag, obj, peeled = w[0], w[1], (w[2] if len(w) > 2 else "")
            try:
                v = parse_version(tag)
            except PackageError:
                continue                       # not a version tag
            commit = peeled or obj
            out.append(Candidate(v, source, self._tag_loader(mirror, commit, source, tag, v), commit=commit))
        out.sort(key=lambda c: c.version, reverse=True)
        return out

    def _tag_loader(self, mirror, commit, source, tag, v):
        def load():
            m = self.git_manifest(mirror, commit, source)
            if m.version != v:
                raise PackageError(f"tag {tag} of {source.where} contains version {fmt_version(m.version)}")
            return m
        return load

    def export(self, source, commit, dest):
        """Unpack the files of `commit` into the empty folder `dest`."""
        mirror = self.mirror(source.where)
        data = run_git(["archive", "--format=tar", commit], git_dir=mirror)
        os.makedirs(dest, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            safe_extract(tar, dest)


# ───────────────────────────── resolution ─────────────────────────────

@dataclass
class Req:
    name: str
    constraint: Constraint
    source: Source
    by: str


def resolve(root, fetcher, prefer=None, log=None):
    """Pick one version of every package in the dependency tree of `root` so that all
    constraints hold. Returns {name: Candidate}. Newest versions are tried first
    (`prefer` {name: version} are tried before that, to keep a lock file stable);
    on a conflict earlier choices are revisited."""
    prefer = prefer or {}
    problems = []

    def conflict_text():
        return problems[-1] if problems else "no solution"

    def attempt(queue, chosen, wants):
        if not queue:
            return chosen
        req, rest = queue[0], queue[1:]
        if req.name == root.name:
            raise PackageError(f"{req.by} needs {root.name}, which is the package being built")
        wants = {**wants, req.name: wants.get(req.name, []) + [req]}
        reqs = wants[req.name]
        first = reqs[0]
        if req.source != first.source:
            raise PackageError(
                f"{req.name} is needed from two different places:\n"
                f"    {first.source.describe()}   (needed by {first.by})\n"
                f"    {req.source.describe()}   (needed by {req.by})")
        if req.name in chosen:
            cand = chosen[req.name]
            if all(r.constraint.allows(cand.version) for r in reqs):
                return attempt(rest, chosen, wants)
            problems.append(explain(req.name, reqs))
            return None
        cands = list(fetcher.candidates(req.source))
        pv = prefer.get(req.name)
        cands.sort(key=lambda c: (c.version == pv, c.version), reverse=True)
        tried = False
        for cand in cands:
            if not all(r.constraint.allows(cand.version) for r in reqs):
                continue
            tried = True
            m = cand.manifest
            nxt = rest + [Req(n.name, n.constraint, n.source, f"{req.name} {fmt_version(cand.version)}")
                          for n in m.needs]
            got = attempt(nxt, {**chosen, req.name: cand}, wants)
            if got is not None:
                return got
        if not tried:
            problems.append(explain(req.name, reqs, [fmt_version(c.version) for c in cands]))
        return None

    def explain(name, reqs, available=None):
        who = "\n".join(f"    {r.constraint}   (needed by {r.by})" for r in reqs)
        avail = f"\n  available versions: {', '.join(available) or 'none'}" if available is not None else ""
        return f"no version of {name} satisfies every requirement:\n{who}{avail}"

    queue = [Req(n.name, n.constraint, n.source, f"{root.name} (this package)") for n in root.needs]
    result = attempt(queue, {}, {})
    if result is None:
        raise PackageError(conflict_text())
    check_cycles(root, result)
    return result


def check_cycles(root, chosen):
    graph = {n: [d.name for d in c.manifest.needs] for n, c in chosen.items()}
    state = {}

    def visit(n, path):
        if state.get(n) == 2:
            return
        if state.get(n) == 1:
            cyc = path[path.index(n):] + [n]
            raise PackageError("dependency cycle: " + " -> ".join(cyc))
        state[n] = 1
        for d in graph.get(n, []):
            visit(d, path + [n])
        state[n] = 2

    for d in root.needs:
        visit(d.name, [root.name])


# ───────────────────────────── installing ─────────────────────────────

def deps_dir(project):
    return os.path.join(project, STORE, "deps")


def package_dir(project, p):
    """Where the files of a locked package live."""
    if p.source.kind == "path":
        return p.source.where
    return os.path.join(deps_dir(project), f"{p.name}-{fmt_version(p.version)}")


def materialize(project, locked, fetcher, say=None):
    """Make sure every locked git package is unpacked and intact; fills in hashes
    the first time a package is seen."""
    say = say or (lambda *_: None)
    wanted = set()
    for p in locked.values():
        dest = package_dir(project, p)
        if p.source.kind == "path":
            if not os.path.isdir(dest):
                raise PackageError(f"path dependency {p.name} is missing: {dest}")
            continue
        wanted.add(os.path.basename(dest))
        if os.path.isdir(dest) and p.hash and tree_hash(dest) == p.hash:
            continue
        if os.path.isdir(dest):
            say(f"  repairing {p.name} {fmt_version(p.version)} (files changed)")
            shutil.rmtree(dest)
        say(f"  unpacking {p.name} {fmt_version(p.version)}")
        fetcher.export(p.source, p.commit, dest)
        h = tree_hash(dest)
        if p.hash and h != p.hash:
            shutil.rmtree(dest)
            raise IntegrityError(
                f"{p.name} {fmt_version(p.version)} does not match the hash in {LOCKFILE}\n"
                f"  locked:   {p.hash}\n  received: {h}\n"
                "  the repository changed under its tag, or the lock file was edited")
        p.hash = h
    base = deps_dir(project)
    if os.path.isdir(base):
        for name in os.listdir(base):
            if name not in wanted:
                shutil.rmtree(os.path.join(base, name), ignore_errors=True)


def lock_from(project, chosen):
    locked = {}
    for name, c in chosen.items():
        m = c.manifest
        locked[name] = Locked(name, c.version, c.source, c.commit, "", [n.name for n in m.needs])
    return locked


def lock_is_consistent(project, root, locked):
    """Do the locked packages satisfy every `needs` line in the tree?"""
    def check(manifest, by, seen):
        for n in manifest.needs:
            p = locked.get(n.name)
            if p is None or p.source != n.source or not n.constraint.allows(p.version):
                return False
            if n.name in seen:
                continue
            seen.add(n.name)
            try:
                dm = load_manifest(package_dir(project, p))
            except PackageError:
                return False
            if dm.version != p.version or sorted(x.name for x in dm.needs) != sorted(p.needs):
                return False
            if not check(dm, n.name, seen):
                return False
        return True

    return check(root, root.name, set()) and set(locked) == reachable(project, root, locked)


def reachable(project, root, locked):
    out, stack = set(), [n.name for n in root.needs]
    while stack:
        n = stack.pop()
        if n in out or n not in locked:
            continue
        out.add(n)
        stack.extend(locked[n].needs)
    return out


def install(project, offline=False, frozen=False, update=None, say=None, fetcher=None):
    """Resolve and unpack the dependencies of the project in `project`.
    frozen: fail instead of changing the lock file. update: names to re-resolve
    (True = all) ignoring what the lock file says."""
    say = say or (lambda *_: None)
    root = load_manifest(project)
    fetcher = fetcher or Fetcher(offline=offline)
    locked = read_lock(project)
    if not root.needs:
        if locked:
            os.remove(os.path.join(project, LOCKFILE))
        shutil.rmtree(deps_dir(project), ignore_errors=True)
        return {}
    if locked and not update:
        try:
            materialize(project, locked, fetcher, say)
            ok = lock_is_consistent(project, root, locked)
        except IntegrityError:
            raise
        except PackageError:
            if frozen:
                raise
            ok = False
        if ok:
            say("lock file is up to date")
            write_lock(project, locked)
            return locked
        if frozen:
            raise PackageError(f"{LOCKFILE} does not match {MANIFEST}; run `quill install` and commit the result")
    elif frozen:
        raise PackageError(f"no {LOCKFILE}; run `quill install` first")
    prefer = {}
    if locked:
        for n, p in locked.items():
            if update is not True and n not in (update or ()):
                prefer[n] = p.version
    say("resolving dependencies")
    chosen = resolve(root, fetcher, prefer)
    new = lock_from(project, chosen)
    if locked:
        # keep hashes of packages whose commit did not change
        for n, p in new.items():
            old = locked.get(n)
            if old and old.commit == p.commit and old.version == p.version and old.source == p.source:
                p.hash = old.hash
    materialize(project, new, fetcher, say)
    write_lock(project, new)
    for n in sorted(new):
        say(f"  {n} {fmt_version(new[n].version)}")
    return new


# ───────────────────────────── context for the compiler ─────────────────────────────

@dataclass
class Package:
    name: str
    root: str
    src: str
    needs: list
    version: tuple = (0, 0, 0)


STD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "std")
_std = []


def std_package():
    """The bundled standard library, as one package (the same object every time, so
    modules of std that bring each other share a namespace)."""
    if not _std:
        _std.append(Package("std", STD_DIR, STD_DIR, []))
    return _std[0]


def std_modules():
    try:
        return sorted("std." + f[:-3] for f in os.listdir(STD_DIR) if f.endswith(".ql"))
    except OSError:
        return []


class Context:
    """Maps `bring a.b.c` to a file for the compiler."""

    def __init__(self, root, packages):
        self.root, self.packages = root, packages

    def package_of(self, path):
        return self.root

    def resolve(self, pkg, dotted):
        segs = dotted.split(".")
        first = segs[0]
        local = os.path.join(pkg.src, *segs) + ".ql"
        if first == "std" and first not in pkg.needs and not os.path.exists(local):
            if len(segs) == 1:
                raise PackageError("`bring std` needs a module: std.math, std.random or std.stats")
            target = os.path.join(STD_DIR, *segs[1:]) + ".ql"
            if not os.path.exists(target):
                raise PackageError(f"the standard library has no module `{dotted}` "
                                   f"(available: {', '.join(std_modules())})")
            return target, std_package()
        if first in pkg.needs:
            dep = self.packages[first]
            if len(segs) == 1:
                target = os.path.join(dep.src, first + ".ql")
            else:
                target = os.path.join(dep.src, *segs[1:]) + ".ql"
            if os.path.exists(local):
                raise PackageError(
                    f"`bring {dotted}` is ambiguous: {first} is both a dependency and a module of this package")
            if not os.path.exists(target):
                raise PackageError(f"package {first} has no module `{dotted}` (looked for {target})")
            return target, dep
        if not os.path.exists(local):
            raise PackageError(f"no module `{dotted}` (looked for {local})")
        return local, pkg


def find_project(start):
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, MANIFEST)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def context_for(entry):
    """The module context for compiling `entry`: its project (with locked
    dependencies) when it sits inside one, otherwise just its own folder."""
    entry = os.path.abspath(entry)
    project = find_project(os.path.dirname(entry))
    if project is None:
        return Context(Package("", os.path.dirname(entry), os.path.dirname(entry), []), {})
    m = load_manifest(project)
    root = Package(m.name, project, m.src_dir, [n.name for n in m.needs], m.version)
    packages = {}
    if m.needs:
        locked = read_lock(project)
        if locked is None:
            raise PackageError(f"this project has dependencies but no {LOCKFILE}; run `quill install`")
        if not lock_is_consistent_quick(project, m, locked):
            raise PackageError(f"{LOCKFILE} does not match {MANIFEST}; run `quill install`")
        for n, p in locked.items():
            d = package_dir(project, p)
            if not os.path.isdir(d):
                raise PackageError(f"package {n} is not installed; run `quill install`")
            if p.source.kind == "git" and tree_hash(d) != p.hash:
                raise PackageError(f"package {n} was modified after install; run `quill install` to restore it")
            dm = load_manifest(d)
            packages[n] = Package(n, d, dm.src_dir, [x.name for x in dm.needs], p.version)
    return Context(root, packages)


def lock_is_consistent_quick(project, root, locked):
    """Root-level check only (the full tree is verified by `quill install`)."""
    for n in root.needs:
        p = locked.get(n.name)
        if p is None or p.source != n.source or not n.constraint.allows(p.version):
            return False
    return True


def default_entry(project=None):
    """The file `quill run` starts from when no file is named."""
    project = find_project(project or os.getcwd())
    if project is None:
        raise PackageError(f"no {MANIFEST} here; name a .ql file or run inside a project")
    m = load_manifest(project)
    if not m.start:
        raise PackageError(f"{m.name} is a library (its {MANIFEST} has no `start` line); name a file to run")
    return os.path.join(m.src_dir, *m.start.split(".")) + ".ql", m


# ───────────────────────────── commands ─────────────────────────────

MAIN_TEMPLATE = '''class Main:
    static def main():
        print("hello from {name}")
'''
LIB_TEMPLATE = '''class {cls}:
    static def greet(who: str) -> str:
        return "hello, " + who
'''


def say_out(*a):
    print(*a)


def sanitize_name(text):
    n = re.sub(r"[^A-Za-z0-9_]", "_", text) or "app"
    return n if not n[0].isdigit() else "_" + n


def cmd_new(name, lib=False, dir=None):
    if not NAME_RE.match(name):
        raise PackageError(f"package name {name!r} must be letters, digits and _")
    dest = os.path.abspath(dir or name)
    if os.path.exists(dest) and os.listdir(dest):
        raise PackageError(f"{dest} already exists and is not empty")
    os.makedirs(os.path.join(dest, "src"), exist_ok=True)
    start = "" if lib else "start main\n"
    write(os.path.join(dest, MANIFEST), f"package {name}\nversion 0.1.0\nsource src\n{start}")
    if lib:
        write(os.path.join(dest, "src", name + ".ql"), LIB_TEMPLATE.format(cls=name[0].upper() + name[1:]))
    else:
        write(os.path.join(dest, "src", "main.ql"), MAIN_TEMPLATE.format(name=name))
    write(os.path.join(dest, ".gitignore"), f"{STORE}/\nbuild/\n")
    return dest


def cmd_init(dir, lib=False):
    dir = os.path.abspath(dir)
    if os.path.exists(os.path.join(dir, MANIFEST)):
        raise PackageError(f"{MANIFEST} already exists")
    name = sanitize_name(os.path.basename(dir))
    src = "src" if os.path.isdir(os.path.join(dir, "src")) else "."
    start = "start main\n" if os.path.exists(os.path.join(dir, src, "main.ql")) and not lib else ""
    write(os.path.join(dir, MANIFEST), f"package {name}\nversion 0.1.0\nsource {src}\n{start}")
    return name


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def cmd_add(project, name, constraint, source, offline=False, say=None):
    if not NAME_RE.match(name):
        raise PackageError(f"package name {name!r} must be letters, digits and _")
    m = load_manifest(project)
    if name == m.name:
        raise PackageError("a package cannot need itself")
    cons = Constraint.parse(constraint or "any")
    old = edit_manifest(project, add=format_need(name, cons, source, project))
    try:
        locked = install(project, offline=offline, say=say)
    except PackageError:
        write(os.path.join(project, MANIFEST), old)
        raise
    if not constraint and name in locked:
        # pin the new dependency to the compatible range of what was chosen
        v = locked[name].version
        shown = f"{v[0]}.{v[1]}" if v[0] > 0 or v[1] > 0 else fmt_version(v)
        edit_manifest(project, add=format_need(name, Constraint.parse(shown), source, project))
        install(project, offline=True, say=lambda *_: None)
    return locked


def cmd_drop(project, name, say=None):
    m = load_manifest(project)
    if name not in [n.name for n in m.needs]:
        raise PackageError(f"{m.name} does not need {name}")
    old = edit_manifest(project, drop=name)
    try:
        install(project, offline=True, say=say)
    except PackageError:
        write(os.path.join(project, MANIFEST), old)
        raise


def tree_lines(project):
    root = load_manifest(project)
    locked = read_lock(project) or {}
    lines = [f"{root.name} {fmt_version(root.version)}"]

    def walk(names, prefix, seen):
        names = sorted(names)
        for i, n in enumerate(names):
            last = i == len(names) - 1
            p = locked.get(n)
            label = f"{n} {fmt_version(p.version)}" if p else f"{n} (not installed)"
            again = n in seen
            lines.append(f"{prefix}{'`-- ' if last else '|-- '}{label}{' (see above)' if again and p and p.needs else ''}")
            if p and not again:
                walk(p.needs, prefix + ("    " if last else "|   "), seen | {n})

    walk([n.name for n in root.needs], "", {root.name})
    return lines


# ───────────────────────────── command line ─────────────────────────────

def cli(cmd, args):
    """Run a package command. `args` is an argparse namespace. Returns an exit code."""
    try:
        project = find_project(os.getcwd()) if cmd not in ("new", "init") else None
        if cmd in ("install", "update", "add", "drop", "tree") and project is None:
            raise PackageError(f"no {MANIFEST} here; create one with `quill init` or `quill new`")
        if cmd == "new":
            dest = cmd_new(args.name, args.lib)
            print(f"created {os.path.relpath(dest)}")
        elif cmd == "init":
            name = cmd_init(os.getcwd(), args.lib)
            print(f"created {MANIFEST} for {name}")
        elif cmd == "install":
            install(project, offline=args.offline, frozen=args.locked, say=say_out)
        elif cmd == "update":
            install(project, offline=args.offline, update=set(args.names) or True, say=say_out)
        elif cmd == "add":
            if args.git and args.path:
                raise PackageError("choose either --git or --path")
            if not (args.git or args.path):
                raise PackageError("say where it comes from: --git URL or --path DIR")
            if args.git:
                where = args.git
                if not looks_remote(where) and not os.path.isabs(where):
                    where = os.path.abspath(where)
                ref = ("branch", args.branch) if args.branch else ("rev", args.rev) if args.rev \
                    else ("tag", args.tag) if args.tag else ("", "")
                source = Source("git", where, *ref)
            else:
                source = Source("path", os.path.abspath(args.path))
            cmd_add(project, args.name, args.version, source, offline=args.offline, say=say_out)
            print(f"added {args.name}")
        elif cmd == "drop":
            cmd_drop(project, args.name, say=say_out)
            print(f"dropped {args.name}")
        elif cmd == "tree":
            print("\n".join(tree_lines(project)))
        return 0
    except PackageError as e:
        print(f"quill: {e}", file=sys.stderr)
        return 1

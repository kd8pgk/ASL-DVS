#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tempfile

TOOL_RE = re.compile(
    r"^(?P<stem>[A-Za-z0-9][A-Za-z0-9_]*?)_v(?P<ver>\d{1,6}(?:_\d{1,6})*)(?:_(?P<date>\d{8}))?\.(?P<ext>py|sh)$")
PY_VERSION_RE = re.compile(r"""^(?:VERSION|APP_VERSION|SCRIPT_VERSION)\s*=\s*["']([^"']+)["']""", re.M)
SH_VERSION_RE = re.compile(r"^#\s*\S+\.sh\s+v(\S+)", re.M)
SCRIPT_RE = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.S | re.I)
PAGE_RE = re.compile(r"<!doctype html|<html[\s>]|<body[\s>]", re.I)
JS_NAME_RE = re.compile(r"^_*(?:[A-Z0-9]+_)*JS$")
PLACEHOLDER_RE = re.compile(r"^\s*\{\w+\}\s*$")
CHANNEL_FILES = ("channels/rules.json", "channels/overrides.json")
STABLE_FILE = "channels/stable.json"

errors = []
notes = []


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def fail(msg):
    errors.append(msg)


def git(*args, check=True):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def show(rev, path):
    r = subprocess.run(["git", "show", f"{rev}:{path}"], capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", errors="replace")


def parse_tool(name):
    m = TOOL_RE.match(os.path.basename(name))
    if not m or "/" in name:
        return None
    return m.group("stem"), tuple(int(p) for p in m.group("ver").split("_")), m.group("ext")


def split_version(v):
    core, _, suffix = v.partition("-")
    try:
        return tuple(int(p) for p in core.split(".")), suffix
    except ValueError:
        return None, suffix


def file_version(text, ext):
    m = (PY_VERSION_RE if ext == "py" else SH_VERSION_RE).search(text)
    return m.group(1) if m else None


def load_aliases(rev):
    text = show(rev, "channels/rules.json")
    if text is None:
        return {}
    try:
        return json.loads(text).get("aliases", {})
    except ValueError:
        return {}


class _Strip(ast.NodeTransformer):
    def visit_Constant(self, node):
        if isinstance(node.value, (str, bytes)):
            return ast.copy_location(ast.Constant(value=type(node.value)()), node)
        return node


def py_shape(text):
    return ast.dump(_Strip().visit(ast.parse(text)), include_attributes=False)


def sh_shape(text):
    lines = [ln for ln in text.splitlines() if not SH_VERSION_RE.match(ln)]
    body = "\n".join(lines)
    body = re.sub(r'"(?:\\.|[^"\\])*"', '""', body)
    body = re.sub(r"'[^']*'", "''", body)
    return body


def module_strings(tree):
    env = {}

    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            return env.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            a, b = ev(node.left), ev(node.right)
            return a + b if a is not None and b is not None else None
        return None

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            v = ev(node.value)
            if v is not None:
                env[node.targets[0].id] = v
    return env


def page_scripts(text):
    tree = ast.parse(text)
    env = module_strings(tree)
    sources = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "<script" in node.value:
            sources.append((node.lineno, node.value))
        elif isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant):
                    parts.append(v.value)
                elif isinstance(v.value, ast.Name) and v.value.id in env:
                    parts.append(env[v.value.id])
                else:
                    parts.append("null")
            s = "".join(parts)
            if "<script" in s:
                sources.append((node.lineno, s))
    for name, value in env.items():
        if "<script" in value:
            sources.append((0, value))
    seen = set()
    for name, value in env.items():
        if JS_NAME_RE.match(name) and not PAGE_RE.search(value) and value.strip():
            seen.add(value)
            yield 0, value, False
    for lineno, src in sources:
        if not PAGE_RE.search(src):
            continue
        for m in SCRIPT_RE.finditer(src):
            attrs = m.group("attrs").lower()
            if "src=" in attrs:
                continue
            t = re.search(r"type\s*=\s*[\"']?([^\"'\s>]+)", attrs)
            if t and t.group(1) not in ("text/javascript", "module", "application/javascript"):
                continue
            body = m.group("body")
            if not body.strip() or body in seen or PLACEHOLDER_RE.match(body):
                continue
            seen.add(body)
            yield lineno, body, (t and t.group(1) == "module")


def check_python(path, text):
    try:
        compile(text, path, "exec")
    except SyntaxError as e:
        fail(f"{path}: does not compile: {e}")
        return False
    r = subprocess.run([sys.executable, "-m", "pyflakes", path], capture_output=True, text=True)
    if r.returncode != 0:
        out = (r.stdout + r.stderr).strip()
        if "No module named pyflakes" in out:
            fail("pyflakes is not installed (pip install pyflakes)")
        else:
            fail(f"{path}: pyflakes:\n{out}")
    return True


def check_page_js(path, text):
    for lineno, body, is_module in page_scripts(text):
        with tempfile.NamedTemporaryFile("w", suffix=".mjs" if is_module else ".js", delete=False) as f:
            f.write(body)
            tmp = f.name
        try:
            r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True)
        except FileNotFoundError:
            fail("node is not installed, so page JavaScript could not be checked")
            return
        finally:
            os.unlink(tmp)
        if r.returncode != 0:
            msg = (r.stderr or r.stdout).strip().replace(tmp, f"{path}<script near line {lineno}>")
            fail(f"{path}: page JavaScript does not parse:\n{msg}")


def check_shell(path):
    r = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
    if r.returncode != 0:
        fail(f"{path}: bash -n:\n{r.stderr.strip()}")


def check_changelog(stem, name, version):
    path = f"changelogs/{stem}.md"
    if not os.path.isfile(path):
        fail(f"{name}: {path} is missing")
        return
    text = read(path)
    cur = next((ln for ln in text.splitlines() if ln.startswith("Current file:")), "")
    if f"`{name}`" not in cur:
        fail(f"{path}: the 'Current file' line does not name `{name}`")
    head = next((ln for ln in text.splitlines() if ln.startswith("## ")), "")
    if version not in head.split():
        fail(f"{path}: the top entry is '{head}', not {version}")


def check_launchers():
    texts = {}
    for name in sorted(os.listdir(".")):
        if not name.endswith(".py") or not os.path.isfile(name):
            continue
        try:
            tree = ast.parse(read(name))
        except SyntaxError:
            continue
        for node in tree.body:
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name) and node.targets[0].id == "_LAUNCHER_CODE"
                    and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
                texts[name] = node.value.value
    if len(set(texts.values())) > 1:
        groups = {}
        for name, t in texts.items():
            groups.setdefault(t, []).append(name)
        fail("the shared launcher text differs between files: "
             + " | ".join(", ".join(v) for v in groups.values()))


def check_channel_json(path):
    try:
        data = json.loads(read(path))
    except (OSError, ValueError) as e:
        fail(f"{path}: not valid JSON: {e}")
        return
    if path.endswith("overrides.json"):
        for key in ("hold", "hotfix"):
            val = data.get(key, {})
            if not isinstance(val, dict) or not all(
                    isinstance(k, str) and isinstance(v, list) and all(isinstance(x, str) for x in v)
                    for k, v in val.items()):
                fail(f"{path}: '{key}' must map a tool name to a list of version strings")
        extra = set(data) - {"hold", "hotfix"}
        if extra:
            fail(f"{path}: unknown keys {sorted(extra)}")
    else:
        for key, typ in (("lag", int), ("soak_days", (int, float)), ("fallback_days", (int, float)),
                         ("cosmetic_since", str), ("floors", dict), ("aliases", dict)):
            if not isinstance(data.get(key), typ):
                fail(f"{path}: '{key}' is missing or the wrong type")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--head", default="HEAD")
    args = ap.parse_args()

    base = git("merge-base", args.base, args.head).strip()
    diff = git("diff", "--name-status", "--no-renames", base, args.head)
    added, deleted, modified = [], [], []
    for line in diff.splitlines():
        status, _, path = line.partition("\t")
        {"A": added, "D": deleted, "M": modified}.get(status[:1], modified).append(path)

    aliases = load_aliases(args.head)
    canon = lambda s: aliases.get(s, s)

    base_tools = {}
    for path in git("ls-tree", "--name-only", base).splitlines():
        t = parse_tool(path)
        if t:
            base_tools.setdefault(canon(t[0]), []).append(path)

    head_tools = {}
    for path in git("ls-tree", "--name-only", args.head).splitlines():
        t = parse_tool(path)
        if t:
            head_tools.setdefault(canon(t[0]), []).append(path)
    for stem, files in head_tools.items():
        if len(files) > 1:
            fail(f"more than one file for tool '{stem}': {', '.join(sorted(files))}")

    readme = read("README.md") if os.path.isfile("README.md") else ""
    changed = [p for p in added + modified if os.path.isfile(p)]

    for path in changed:
        text = read(path)
        if path.endswith(".py"):
            if check_python(path, text):
                check_page_js(path, text)
        elif path.endswith(".sh"):
            check_shell(path)
        elif path.startswith("channels/") and path.endswith(".json"):
            if path == STABLE_FILE:
                fail(f"{STABLE_FILE} is written only by the promotion workflow; leave it out of pull requests")
            elif path in CHANNEL_FILES:
                check_channel_json(path)

    for path in modified:
        if parse_tool(path):
            fail(f"{path}: changed in place; every change needs a new version and file name")

    for path in added:
        t = parse_tool(path)
        if not t:
            continue
        stem, name_ver, ext = t
        stem_c = canon(stem)
        text = read(path)
        version = file_version(text, ext)
        if not version:
            fail(f"{path}: no VERSION / APP_VERSION / SCRIPT_VERSION (or .sh title line) found")
            continue
        vt, suffix = split_version(version)
        if vt is None:
            fail(f"{path}: version '{version}' is not numeric")
            continue
        if vt != name_ver:
            fail(f"{path}: file name says {'.'.join(map(str, name_ver))}, the file says {version}")
        want_suffix = "pi02w" if stem.endswith("_pi02w") else ""
        if suffix != want_suffix:
            fail(f"{path}: version '{version}' must {'end in -pi02w' if want_suffix else 'have no suffix'}")
        if len(vt) not in (3, 4):
            fail(f"{path}: version '{version}' must have three parts (release) or four (cosmetic)")
        if f"`{path}`" not in readme and path not in readme:
            fail(f"README.md does not list {path}")
        check_changelog(stem, path, version)

        prev = [p for p in base_tools.get(stem_c, []) if p in deleted]
        prev_ver = None
        if prev:
            pt = parse_tool(prev[0])
            prev_ver = pt[1]
            if vt <= prev_ver:
                fail(f"{path}: version {version} is not newer than {prev[0]}")
        if len(vt) == 4:
            if not prev:
                fail(f"{path}: a cosmetic version (four parts) needs the previous file of the same tool")
                continue
            if vt[:3] != prev_ver[:3] or vt[3] != (prev_ver[3] + 1 if len(prev_ver) == 4 else 1):
                fail(f"{path}: cosmetic {version} must follow {'.'.join(map(str, prev_ver))} "
                     f"as {'.'.join(map(str, prev_ver[:3]))}.{prev_ver[3] + 1 if len(prev_ver) == 4 else 1}")
            old = show(base, prev[0])
            try:
                same = (py_shape(old) == py_shape(text)) if ext == "py" else (sh_shape(old) == sh_shape(text))
            except SyntaxError:
                same = False
            if not same:
                fail(f"{path}: marked cosmetic (four parts) but the code changed, not just text; "
                     f"make it a release ({'.'.join(map(str, prev_ver[:2]))}.{prev_ver[2] + 1})")
            else:
                notes.append(f"{path}: cosmetic check passed (only strings changed)")

    for path in deleted:
        t = parse_tool(path)
        if t and not head_tools.get(canon(t[0])):
            notes.append(f"{path}: tool '{canon(t[0])}' removed")

    check_launchers()

    for n in notes:
        print(f"note: {n}")
    if errors:
        print(f"\n{len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK: {len(changed)} changed file(s) checked against {base[:10]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

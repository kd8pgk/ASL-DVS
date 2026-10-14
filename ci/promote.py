#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone

TOOL_RE = re.compile(
    r"^(?P<stem>[A-Za-z0-9][A-Za-z0-9_]*?)_v(?P<ver>\d{1,6}(?:_\d{1,6})*)(?:_(?P<date>\d{8}))?\.(?P<ext>py|sh)$")
PY_VERSION_RE = re.compile(r"""^(?:VERSION|APP_VERSION|SCRIPT_VERSION)\s*=\s*["']([^"']+)["']""", re.M)
SH_VERSION_RE = re.compile(r"^#\s*\S+\.sh\s+v(\S+)", re.M)
DAY = 86400


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def vtuple(s):
    return tuple(int(p) for p in s.partition("-")[0].split("."))


def read_json(ref, path, default):
    r = subprocess.run(["git", "show", f"{ref}:{path}"], capture_output=True, text=True)
    if r.returncode != 0:
        return default
    return json.loads(r.stdout)


def builds(ref, aliases):
    out = git("log", "--first-parent", "-m", "--no-renames", "--diff-filter=A", "--name-only",
              "--format=@%H %ct", ref)
    seen, result, commit, ts = set(), {}, None, 0
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("@"):
            commit, t = line[1:].split()
            ts = int(t)
            continue
        if "/" in line:
            continue
        m = TOOL_RE.match(line)
        if not m or line in seen:
            continue
        seen.add(line)
        stem = aliases.get(m.group("stem"), m.group("stem"))
        result.setdefault(stem, []).append({
            "file": line, "file_stem": m.group("stem"), "ext": m.group("ext"),
            "vt": tuple(int(p) for p in m.group("ver").split("_")),
            "commit": commit, "time": ts,
        })
    for lst in result.values():
        lst.sort(key=lambda b: (b["time"], b["vt"]))
    return result


def file_version(commit, b):
    text = git("show", f"{commit}:{b['file']}")
    m = (PY_VERSION_RE if b["ext"] == "py" else SH_VERSION_RE).search(text)
    return m.group(1) if m else ".".join(map(str, b["vt"]))


def name_version(stem, b):
    return ".".join(map(str, b["vt"])) + ("-pi02w" if stem.endswith("_pi02w") else "")


def pick(stem, blist, rules, overrides, now):
    lag = int(rules["lag"])
    soak = float(rules["soak_days"]) * DAY
    fallback = float(rules["fallback_days"]) * DAY
    cosmetic_since = parse_iso(rules["cosmetic_since"])
    floor = rules.get("floors", {}).get(stem)
    held = set(overrides.get("hold", {}).get(stem, []))
    hotfix = set(overrides.get("hotfix", {}).get(stem, []))

    releases = [b for b in blist
                if not (len(b["vt"]) == 4 and b["time"] >= cosmetic_since)]
    best = None
    for i, r in enumerate(releases):
        ver = name_version(stem, r)
        if ver in held:
            continue
        if r["file_stem"] != stem:
            continue
        if floor and r["vt"] < vtuple(floor):
            continue
        newer = releases[i + 1:]
        when = []
        if len(newer) >= lag:
            when.append((max(newer[lag - 1]["time"], r["time"] + soak), "count"))
        gap_end = newer[0]["time"] if newer else now
        if gap_end - r["time"] >= fallback:
            when.append((r["time"] + fallback, "age"))
        if ver in hotfix:
            when.append((r["time"], "hotfix"))
        when = [w for w in when if w[0] <= now]
        if when:
            best = (r, min(when))
    return best, len(releases), len(blist)


def compute(ref, now):
    rules = read_json(ref, "channels/rules.json", None)
    if rules is None:
        raise SystemExit("channels/rules.json is missing")
    overrides = read_json(ref, "channels/overrides.json", {})
    aliases = rules.get("aliases", {})
    current = {}
    for path in git("ls-tree", "--name-only", ref).splitlines():
        m = TOOL_RE.match(path)
        if m:
            current[aliases.get(m.group("stem"), m.group("stem"))] = path
    history = builds(ref, aliases)
    tools, report = {}, []
    for stem in sorted(current):
        best, n_rel, n_all = pick(stem, history.get(stem, []), rules, overrides, now)
        if not best:
            report.append(f"{stem}: no stable build yet ({n_rel} release(s), {n_all} build(s) on testing)")
            continue
        b, (at, reason) = best
        tools[stem] = {
            "file": b["file"],
            "version": file_version(b["commit"], b),
            "commit": b["commit"],
            "blob": git("rev-parse", f"{b['commit']}:{b['file']}").strip(),
            "landed": iso(b["time"]),
            "promoted": iso(at),
            "reason": reason,
        }
        report.append(f"{stem}: {tools[stem]['version']} ({reason}, promoted {iso(at)}); testing has {current[stem]}")
    return {"channel": "stable", "tools": tools}, report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--now", help="ISO time to compute for (testing)")
    ap.add_argument("--out", default="channels/stable.json")
    ap.add_argument("--print", action="store_true", dest="print_only")
    args = ap.parse_args()
    now = parse_iso(args.now) if args.now else datetime.now(timezone.utc).timestamp()
    data, report = compute(args.ref, now)
    text = json.dumps(data, indent=1, sort_keys=True) + "\n"
    for line in report:
        print(line)
    if args.print_only:
        sys.stdout.write(text)
        return 0
    try:
        old = open(args.out, encoding="utf-8").read()
    except OSError:
        old = None
    if old == text:
        print("stable.json unchanged")
        return 0
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

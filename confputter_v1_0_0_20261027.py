#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import datetime
import difflib
import grp
import hashlib
import json
import os
import pwd
import re
import shutil
import socket
import sys

VERSION = "1.0.0"
ROOT = os.environ.get("CONFPUTTER_ROOT", "")
BACKUP_DIR = os.environ.get("CONFPUTTER_BACKUPS") or os.path.join(ROOT or "/", "var/lib/confputter/backups")
KEEP_BACKUPS = 10
MAX_SNAPSHOT = 3000000
MAX_SECRET = 500
DIFF_LINES = 40

AREAS = [
    ("/etc/asterisk/", "ASL3 / Asterisk", False),
    ("/etc/allmon3/", "Allmon3", False),
    ("/opt/Analog_Bridge/", "DVSwitch", False),
    ("/opt/MMDVM_Bridge/", "DVSwitch", False),
    ("/opt/YSFGateway/", "DVSwitch", False),
    ("/opt/P25Gateway/", "DVSwitch", False),
    ("/opt/NXDNGateway/", "DVSwitch", False),
    ("/opt/Analog_Reflector/", "DVSwitch", False),
    ("/var/lib/dvswitch/dvs/var.txt", "DVSwitch", False),
    ("/etc/dvswitch/", "DVSwitch", False),
    ("/opt/USRP2M17/", "USRP2M17", False),
    ("/etc/svxlink/", "SvxLink", False),
    ("/usr/local/etc/svxlink/", "SvxLink", False),
    ("/etc/asl_dvs/", "Node tools", False),
    ("/etc/sysmon/", "Node tools", False),
    ("/etc/44helper/", "Node tools", False),
    ("/etc/firewalld/", "Firewall", True),
    ("/etc/sysctl.d/90-44helper", "Firewall", True),
    ("/etc/fail2ban/", "Firewall", True),
    ("/etc/wireguard/", "WireGuard", True),
]
NEVER = re.compile(r"(^/etc/asl_dvs/instmon_|\.md$|\.key$|\.pem$|/auth\.txt$|\.bak$|~$|\.swp$)")
RESTART = [
    ("/etc/asterisk/", "asterisk"), ("/etc/allmon3/", "allmon3"), ("/opt/Analog_Bridge/", "analog_bridge"),
    ("/opt/MMDVM_Bridge/", "mmdvm_bridge"), ("/opt/YSFGateway/", "ysfgateway"), ("/opt/P25Gateway/", "p25gateway"),
    ("/opt/NXDNGateway/", "nxdngateway"), ("/opt/USRP2M17/", "usrp2m17"), ("/etc/svxlink/", "svxlink"),
    ("/usr/local/etc/svxlink/", "svxlink"), ("/etc/firewalld/", "firewall-cmd --reload"),
    ("/etc/wireguard/", "wg-quick@wg0"), ("/etc/asl_dvs/", "nodecontrol, nodetalker"), ("/etc/sysmon/", "sysmon"),
    ("/etc/44helper/", "44helper"),
]

def atomic_write(path, data, mode=None, new_mode=0o600, skip_same=False):
    import os
    import secrets
    import stat
    path = os.fspath(path)
    if isinstance(data, str):
        data = data.encode("utf-8")
    folder = os.path.dirname(path) or "."
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None and not stat.S_ISREG(st.st_mode):
        st = None
    if skip_same and st is not None:
        try:
            with open(path, "rb") as fh:
                if fh.read() == data:
                    return False
        except OSError:
            pass
    tmp = os.path.join(folder, ".%s.%s.tmp" % (os.path.basename(path), secrets.token_hex(6)))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        if st is not None and os.geteuid() == 0:
            os.fchown(fd, st.st_uid, st.st_gid)
        if mode is not None:
            os.fchmod(fd, mode)
        elif st is not None:
            os.fchmod(fd, stat.S_IMODE(st.st_mode))
        else:
            os.fchmod(fd, new_mode)
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.close(fd)
    try:
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass
    return True

def fill_secrets(text, current, supplied=None, is_json=False):
    import json
    import re
    tag_re = re.compile(r"<redacted:[0-9a-f]{8}>")
    hdr_re = re.compile(r"^\s*\[([^\]]+)\]")
    supplied = supplied or {}
    if is_json:
        try:
            data = json.loads(text)
            cur = json.loads(current) if current is not None else None
        except ValueError:
            data = None
            cur = None
        if data is not None:
            resolved = [0]
            unresolved = []

            def walk(node, cnode, path):
                if isinstance(node, dict):
                    return {k: walk(v, cnode.get(k) if isinstance(cnode, dict) else None, path + [str(k)])
                            for k, v in node.items()}
                if isinstance(node, list):
                    return [walk(v, cnode[i] if isinstance(cnode, list) and i < len(cnode) else None,
                                 path + [str(i)]) for i, v in enumerate(node)]
                if isinstance(node, str) and tag_re.fullmatch(node):
                    if node in supplied:
                        resolved[0] += 1
                        return supplied[node]
                    if cnode is not None and not (isinstance(cnode, str) and tag_re.fullmatch(cnode)):
                        resolved[0] += 1
                        return cnode
                    unresolved.append({"line": 0, "key": ".".join(path), "tag": node})
                    return ""
                return node
            out = walk(data, cur, [])
            return json.dumps(out, indent=1, sort_keys=True) + "\n", resolved[0], unresolved
    by_sec = {}
    if current is not None:
        sec = ""
        for line in current.split("\n"):
            hm = hdr_re.match(line)
            if hm:
                sec = hm.group(1)
            by_sec.setdefault(sec, []).append(line)
    out = []
    unresolved = []
    resolved = 0
    seen = {}
    sec = ""
    for n, line in enumerate(text.split("\n"), 1):
        hm = hdr_re.match(line)
        if hm:
            sec = hm.group(1)
        body = line.lstrip()
        tags = tag_re.findall(body)
        if not tags:
            out.append(line)
            continue
        indent = line[:len(line) - len(body)]
        parts = tag_re.split(body)
        shape = tag_re.sub("\x00", body)
        k = seen.get((sec, shape), 0)
        seen[(sec, shape)] = k + 1
        got = None
        if not all(t in supplied for t in tags):
            pats = [re.escape(p).replace("\\ ", r"\s*") for p in parts]
            rx = "^" + "".join(pats[i] + ("(.*?)" if i < len(pats) - 1 else "") for i in range(len(pats))) + "$"
            try:
                pat = re.compile(rx)
            except re.error:
                pat = None
            if pat is not None:
                hits = []
                for cur_line in by_sec.get(sec, []):
                    cm = pat.match(cur_line.lstrip())
                    if cm:
                        hits.append(cm)
                if k < len(hits):
                    got = hits[k].groups()
        vals = []
        for i, t in enumerate(tags):
            if t in supplied:
                vals.append(supplied[t])
                resolved += 1
            elif got is not None:
                vals.append(got[i])
                resolved += 1
            else:
                vals.append("")
                if not body.startswith((";", "#")):
                    unresolved.append({"line": n, "key": parts[0].strip()[:40], "tag": t})
        new = indent + parts[0]
        for i, v in enumerate(vals):
            new += v + parts[i + 1]
        out.append(new)
    return "\n".join(out), resolved, unresolved


def real(path):
    return os.path.join(ROOT or "/", path.lstrip("/"))


def read_bytes(path):
    try:
        with open(real(path), "rb") as fh:
            return fh.read()
    except OSError:
        return None


def parse_snapshot(text):
    lines = text.split("\n")
    info = {"host": "", "taken": "", "made_by": "", "banner": "", "manifest": {}, "files": {}}
    for ln in lines[:40]:
        if ln.startswith("# Node config snapshot:"):
            info["host"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("- Taken:"):
            info["taken"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("- Made by:"):
            info["made_by"] = ln.split(":", 1)[1].strip()
        elif ln.startswith("> ") and not info["banner"]:
            info["banner"] = ln[2:].strip()
    if not info["host"]:
        raise ValueError("This file is not a confgetter snapshot (no '# Node config snapshot:' heading).")
    section = ""
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## ") and not ln.startswith("### "):
            section = ln[3:].strip()
        elif section == "Manifest" and ln.startswith("| /"):
            cols = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cols) >= 8:
                info["manifest"][cols[0]] = {"group": cols[1], "size": cols[2], "mode": cols[3], "owner": cols[4],
                                             "note": cols[7]}
        elif ln.startswith("### /") and section not in ("Commands", "Manifest", "Skipped"):
            path = ln[4:].strip()
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            fm = re.match(r"^(`{3,})$", lines[j]) if j < len(lines) else None
            if fm:
                fence = fm.group(1)
                k = j + 1
                body = []
                while k < len(lines) and lines[k] != fence:
                    body.append(lines[k])
                    k += 1
                info["files"][path] = "\n".join(body) + "\n"
                i = k
        i += 1
    if not info["files"]:
        raise ValueError("No config files were found in this snapshot.")
    return info


def classify(path, entry):
    if not path.startswith("/") or os.path.normpath(path) != path:
        return None, "not a normal path", False
    if NEVER.search(path):
        return None, "never restored (state, key or document file)", False
    for prefix, label, careful in AREAS:
        if path.startswith(prefix):
            if "trimmed" in (entry or {}).get("note", ""):
                return None, "the snapshot holds only the first part of this file", False
            return label, "", careful
    return None, "system file, not restored", False


def is_comment(line):
    return line.lstrip().startswith(";")


def significant(line):
    return line.strip() != "" and not is_comment(line)


def merge_keep_comments(current, new):
    cur = current.split("\n")
    new_lines = [ln for ln in new.split("\n") if significant(ln)]
    idx = [i for i, ln in enumerate(cur) if significant(ln)]
    base = [cur[i] for i in idx]
    sm = difflib.SequenceMatcher(None, base, new_lines, autojunk=False)
    out = []
    ci = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "insert":
            out.extend(new_lines[j1:j2])
            continue
        start = idx[i1]
        out.extend(cur[ci:start])
        end = idx[i2 - 1] + 1
        if tag == "equal":
            out.extend(cur[start:end])
        else:
            if tag == "replace":
                out.extend(new_lines[j1:j2])
            out.extend(ln for ln in cur[start:end] if not significant(ln))
        ci = end
    out.extend(cur[ci:])
    return "\n".join(out)


def without_comments(text):
    return [ln for ln in text.split("\n") if significant(ln)]


SECRETISH = re.compile(r"(pass|pwd|secret|token|psk|private_?key|preshared|api_?key|auth_?key)", re.I)
KV_LINE = re.compile(r"^(\s*[;#]?\s*)([A-Za-z0-9_.\- ]+?)(\s*(?:=>|=|:)\s*)(.*)$")
REGISTER_LINE = re.compile(r"(register\s*=>?\s*[^:@\s]+:)([^@\s]+)(@)", re.I)
JSON_SECRETISH = re.compile(r'("[^"]*(?:pass|secret|token|psk|key|pin|email)[^"]*"\s*:\s*)"[^"]*"', re.I)


def hide(text, values):
    for v in values:
        if len(v) >= 3:
            text = text.replace(v, "<hidden>")
    text = REGISTER_LINE.sub(lambda m: m.group(1) + "<hidden>" + m.group(3), text)
    text = JSON_SECRETISH.sub(lambda m: m.group(1) + '"<hidden>"', text)
    m = KV_LINE.match(text)
    if m and SECRETISH.search(m.group(2)) and m.group(4):
        text = m.group(1) + m.group(2) + m.group(3) + "<hidden>"
    return text


def diff_info(cur, new, secret_values):
    a = cur.split("\n") if cur is not None else []
    b = new.split("\n")
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    added = removed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("replace", "delete"):
            removed += i2 - i1
        if tag in ("replace", "insert"):
            added += j2 - j1
    lines = []
    for ln in difflib.unified_diff(a, b, lineterm="", n=0):
        if ln.startswith(("---", "+++")):
            continue
        lines.append(hide(ln, secret_values)[:200])
        if len(lines) >= DIFF_LINES:
            lines.append("... more changes not shown")
            break
    return added, removed, lines


def kept_values(content, text):
    tag_re = re.compile(r"<redacted:[0-9a-f]{8}>")
    out = set()
    a = content.split("\n")
    b = text.split("\n")
    if len(a) != len(b):
        return out
    for x, y in zip(a, b):
        if not tag_re.search(x):
            continue
        rx = "^" + "(.*?)".join(re.escape(p) for p in tag_re.split(x)) + "$"
        m = re.match(rx, y)
        if m:
            out.update(v for v in m.groups() if v)
    return out


def build_plan(info, supplied, keep_comments):
    rows = []
    for path in sorted(info["files"]):
        entry = info["manifest"].get(path, {})
        label, reason, careful = classify(path, entry)
        row = {"path": path, "group": label or "", "careful": careful, "mode": entry.get("mode", ""),
               "owner": entry.get("owner", ""), "unresolved": [], "added": 0, "removed": 0, "diff": [],
               "merged": False, "checked": False, "data": None, "kept": 0}
        if label is None:
            row.update(status="skipped", note=reason)
            rows.append(row)
            continue
        if not os.path.isdir(os.path.dirname(real(path))):
            row.update(status="skipped", note="folder not on this node (not installed)")
            rows.append(row)
            continue
        cur_bytes = read_bytes(path)
        cur = None if cur_bytes is None else cur_bytes.decode("utf-8", "replace")
        text, resolved, unresolved = fill_secrets(info["files"][path], cur, supplied, path.endswith(".json"))
        filled = text
        merged = False
        if keep_comments and cur is not None and path.endswith((".conf", ".ini")):
            if any(is_comment(ln) for ln in cur.split("\n")) and not any(is_comment(ln) for ln in text.split("\n")):
                text = merge_keep_comments(cur, text)
                merged = True
        data = text.encode("utf-8")
        same_json = False
        if path.endswith(".json") and cur is not None:
            try:
                same_json = json.loads(cur) == json.loads(text)
            except ValueError:
                same_json = False
        if same_json:
            data = cur_bytes
        row.update(data=data, merged=merged, unresolved=unresolved, kept=resolved)
        hidden = kept_values(info["files"][path], filled) | set(supplied.values())
        if cur_bytes is None:
            status = "new"
        elif cur_bytes == data:
            status = "same"
        elif path.endswith((".conf", ".ini")) and without_comments(cur) == without_comments(text):
            status = "comments"
        else:
            status = "changed"
        row["status"] = status
        if status in ("changed", "new", "comments"):
            row["added"], row["removed"], row["diff"] = diff_info(cur, text, hidden)
        row["checked"] = status in ("new", "changed") and not careful
        row["note"] = {"new": "file does not exist on this node", "changed": "differs from this node",
                       "same": "already as the snapshot says",
                       "comments": "only comment lines differ (left as they are unless you tick it)"}[status]
        if merged:
            row["note"] += "; this node's comments are kept"
        rows.append(row)
    return rows


def restart_hints(paths):
    out = []
    for p in paths:
        for prefix, hint in RESTART:
            if p.startswith(prefix) and hint not in out:
                out.append(hint)
    return out


def public_rows(rows):
    return [{k: v for k, v in r.items() if k != "data"} for r in rows]


def secrets_needed(rows):
    where = {}
    for r in rows:
        if r["status"] in ("skipped",) or r["data"] is None:
            continue
        for u in r["unresolved"]:
            where.setdefault(u["tag"], []).append("%s: %s" % (r["path"], u["key"] or "line %d" % u["line"]))
    return [{"tag": t, "where": w[:6], "count": len(w)} for t, w in sorted(where.items())]


def load_supplied(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError("The secrets file must hold one JSON object.")
    out = {}
    for tag, value in data.items():
        if not re.fullmatch(r"<redacted:[0-9a-f]{8}>", str(tag)):
            raise ValueError("Not a secret tag: %s" % tag)
        value = str(value)
        if len(value) > MAX_SECRET or any(c in value for c in "\r\n\0"):
            raise ValueError("A secret value is too long or has a line break in it.")
        if value:
            out[tag] = value
    return out


def read_snapshot(path):
    if os.path.getsize(path) > MAX_SNAPSHOT:
        raise ValueError("The snapshot is larger than %d bytes." % MAX_SNAPSHOT)
    with open(path, encoding="utf-8", errors="replace") as fh:
        return parse_snapshot(fh.read())


def snapshot_head(info):
    this = socket.gethostname()
    return {"host": info["host"], "taken": info["taken"], "made_by": info["made_by"], "banner": info["banner"],
            "this_host": this, "host_match": info["host"] == this}


def do_preview(args):
    info = read_snapshot(args.snapshot)
    rows = build_plan(info, load_supplied(args.secrets_file), not args.no_keep_comments)
    warnings = []
    head = snapshot_head(info)
    if not head["host_match"]:
        warnings.append("This snapshot is from '%s' and this node is '%s'." % (head["host"], head["this_host"]))
    if info["banner"]:
        warnings.append("Edited copy: " + info["banner"])
    return {"ok": True, "mode": "preview", "snapshot": head, "files": public_rows(rows),
            "secrets": secrets_needed(rows), "warnings": warnings,
            "restart": restart_hints([r["path"] for r in rows if r["status"] in ("new", "changed")])}


def owner_ids(owner, current_path):
    try:
        user, group = owner.split(":", 1)
        return pwd.getpwnam(user).pw_uid, grp.getgrnam(group).gr_gid
    except (KeyError, ValueError):
        try:
            st = os.stat(real(current_path))
            return st.st_uid, st.st_gid
        except OSError:
            return None, None


def backup_ids():
    try:
        names = os.listdir(BACKUP_DIR)
    except OSError:
        return []
    return sorted(n for n in names if re.fullmatch(r"\d{8}-\d{6}(-\d+)?", n))


def read_backup(bid):
    try:
        with open(os.path.join(BACKUP_DIR, bid, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def list_backups():
    out = []
    for bid in reversed(backup_ids()):
        m = read_backup(bid)
        if m:
            out.append({"id": bid, "created": m.get("created", ""), "snapshot": m.get("snapshot", ""),
                        "files": len(m.get("files", {})), "undone": bool(m.get("undone"))})
    return out


def prune_backups():
    ids = backup_ids()
    for bid in ids[:-KEEP_BACKUPS]:
        shutil.rmtree(os.path.join(BACKUP_DIR, bid), ignore_errors=True)


def new_backup_id():
    base = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    bid, n = base, 1
    while os.path.exists(os.path.join(BACKUP_DIR, bid)):
        n += 1
        bid = "%s-%d" % (base, n)
    return bid


def do_apply(args):
    info = read_snapshot(args.snapshot)
    supplied = load_supplied(args.secrets_file)
    rows = build_plan(info, supplied, not args.no_keep_comments)
    only = set(args.only or [])
    if only:
        unknown = only - {r["path"] for r in rows}
        if unknown:
            return {"ok": False, "mode": "apply", "error": "Not in this snapshot: " + ", ".join(sorted(unknown))}
        targets = [r for r in rows if r["path"] in only and r["status"] in ("new", "changed", "comments")]
    else:
        targets = [r for r in rows if r["checked"]]
    if not targets:
        return {"ok": True, "mode": "apply", "written": [], "failed": [], "backup": "",
                "message": "Nothing to write: every file already matches, or none was chosen.",
                "restart": [], "unresolved": []}
    os.makedirs(BACKUP_DIR, mode=0o700, exist_ok=True)
    os.chmod(BACKUP_DIR, 0o700)
    bid = new_backup_id()
    bdir = os.path.join(BACKUP_DIR, bid)
    os.makedirs(bdir, mode=0o700)
    os.makedirs(os.path.join(bdir, "files"), mode=0o700)
    manifest = {"created": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "snapshot": os.path.basename(args.snapshot), "files": {}, "undone": ""}
    for r in targets:
        old = read_bytes(r["path"])
        rec = {"existed": old is not None, "written_sha": ""}
        if old is not None:
            st = os.stat(real(r["path"]))
            rec.update(uid=st.st_uid, gid=st.st_gid, mode=st.st_mode & 0o7777,
                       sha=hashlib.sha256(old).hexdigest())
            dest = os.path.join(bdir, "files", r["path"].lstrip("/"))
            os.makedirs(os.path.dirname(dest), mode=0o700, exist_ok=True)
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as fh:
                fh.write(old)
        manifest["files"][r["path"]] = rec
    with open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    os.chmod(os.path.join(bdir, "manifest.json"), 0o600)
    written, failed = [], []
    for r in targets:
        path = r["path"]
        try:
            mode = int(r["mode"], 8) if re.fullmatch(r"[0-7]{3,4}", r["mode"] or "") else None
            atomic_write(real(path), r["data"], mode=mode)
            uid, gid = owner_ids(r["owner"], path)
            if uid is not None and os.geteuid() == 0:
                os.chown(real(path), uid, gid)
            manifest["files"][path]["written_sha"] = hashlib.sha256(r["data"]).hexdigest()
            written.append(path)
        except OSError as exc:
            failed.append({"path": path, "error": str(exc)})
            break
    with open(os.path.join(bdir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    prune_backups()
    unresolved = [{"path": r["path"], "key": u["key"] or "line %d" % u["line"]}
                  for r in targets if r["path"] in written for u in r["unresolved"]]
    return {"ok": not failed, "mode": "apply", "written": written, "failed": failed, "backup": bid,
            "restart": restart_hints(written), "unresolved": unresolved,
            "message": "Wrote %d file(s). The files they replaced are saved as backup %s." % (len(written), bid)}


def do_undo(args):
    bid = args.id
    if not bid:
        for cand in reversed(backup_ids()):
            m = read_backup(cand)
            if m and not m.get("undone"):
                bid = cand
                break
    m = read_backup(bid) if bid else None
    if not m or not re.fullmatch(r"\d{8}-\d{6}(-\d+)?", bid):
        return {"ok": False, "mode": "undo", "error": "No backup to undo."}
    if m.get("undone"):
        return {"ok": False, "mode": "undo", "error": "Backup %s was already undone." % bid}
    restored, removed, kept = [], [], []
    for path, rec in sorted(m["files"].items()):
        if not rec.get("written_sha"):
            continue
        cur = read_bytes(path)
        if rec.get("existed"):
            saved = os.path.join(BACKUP_DIR, bid, "files", path.lstrip("/"))
            with open(saved, "rb") as fh:
                data = fh.read()
            atomic_write(real(path), data, mode=rec.get("mode"))
            if os.geteuid() == 0:
                os.chown(real(path), rec.get("uid", 0), rec.get("gid", 0))
            restored.append(path)
        elif cur is not None and hashlib.sha256(cur).hexdigest() == rec["written_sha"]:
            os.unlink(real(path))
            removed.append(path)
        else:
            kept.append(path)
    m["undone"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(BACKUP_DIR, bid, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=1)
    return {"ok": True, "mode": "undo", "backup": bid, "restored": restored, "removed": removed, "kept": kept,
            "restart": restart_hints(restored + removed)}


def render_text(res):
    out = []
    if not res.get("ok") and res.get("error"):
        return "Error: " + res["error"]
    if res["mode"] == "preview":
        s = res["snapshot"]
        out.append("Snapshot from %s, taken %s (%s)" % (s["host"], s["taken"], s["made_by"]))
        out += ["Warning: " + w for w in res["warnings"]]
        for r in res["files"]:
            extra = ""
            if r["status"] in ("changed", "new", "comments"):
                extra = " (+%d -%d lines)" % (r["added"], r["removed"])
            out.append("  [%s] %s: %s%s" % ("x" if r["checked"] else " ", r["path"], r["status"], extra))
            if r["status"] == "skipped":
                out[-1] += " - " + r["note"]
        if res["secrets"]:
            out.append("Secrets this node does not have (give them with --secrets-file):")
            out += ["  %s  %s" % (x["tag"], "; ".join(x["where"][:2])) for x in res["secrets"]]
        if res["restart"]:
            out.append("Restart needed after a restore: " + ", ".join(res["restart"]))
        out.append("Preview only: nothing was changed.")
    elif res["mode"] == "apply":
        out.append(res.get("message", ""))
        out += ["  wrote " + p for p in res["written"]]
        out += ["  FAILED %s: %s" % (f["path"], f["error"]) for f in res["failed"]]
        if res["unresolved"]:
            out.append("Written with an empty secret (set by hand):")
            out += ["  %s: %s" % (u["path"], u["key"]) for u in res["unresolved"]]
        if res["restart"]:
            out.append("Restart needed: " + ", ".join(res["restart"]))
    elif res["mode"] == "undo":
        out.append("Undid backup %s." % res["backup"])
        out += ["  restored " + p for p in res["restored"]]
        out += ["  removed " + p for p in res["removed"]]
        out += ["  left alone (changed since): " + p for p in res["kept"]]
    else:
        out += ["%s  %s  %d file(s)%s" % (b["id"], b["created"], b["files"], "  (undone)" if b["undone"] else "")
                for b in res["backups"]] or ["No backups."]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Put the files of a confgetter snapshot back on this node.")
    ap.add_argument("--snapshot")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--preview", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--undo", action="store_true")
    group.add_argument("--list-backups", action="store_true")
    ap.add_argument("--only", action="append")
    ap.add_argument("--secrets-file")
    ap.add_argument("--no-keep-comments", action="store_true")
    ap.add_argument("--id")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)
    if args.version:
        print(VERSION)
        return 0
    if not ROOT and os.geteuid() != 0:
        print("Run as root: sudo python3 %s ..." % sys.argv[0], file=sys.stderr)
        return 2
    try:
        if args.list_backups:
            res = {"ok": True, "mode": "list", "backups": list_backups()}
        elif args.undo:
            res = do_undo(args)
        else:
            if not args.snapshot:
                print("--snapshot is required", file=sys.stderr)
                return 2
            res = do_apply(args) if args.apply else do_preview(args)
    except (OSError, ValueError) as exc:
        res = {"ok": False, "mode": "apply" if args.apply else "preview", "error": str(exc)}
    if args.json:
        json.dump(res, sys.stdout)
        sys.stdout.write("\n")
    else:
        print(render_text(res))
    return 0 if res.get("ok") else 3


if __name__ == "__main__":
    sys.exit(main())

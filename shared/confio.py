USED_BY = {
    "atomic_write": ("nodecontrol", "nodecontrol_pi02w", "sysmon", "sysmon_pi02w", "nodetalker",
                     "amp_nodetalker", "44helper", "wifimon", "confputter", "pibrary", "noderecorder"),
    "ami_credentials": ("nodetalker", "noderecorder"),
    "http_get": ("44helper",),
    "fill_secrets": ("44helper", "confputter"),
    "firewall_backend": ("sysmon_pi02w", "nodecontrol_pi02w", "wifimon", "instmon", "44helper",
                         "nodetalker", "amp_nodetalker", "pibrary", "noderecorder"),
    "open_firewall_port": ("sysmon_pi02w", "nodecontrol_pi02w", "wifimon", "instmon", "44helper",
                           "nodetalker", "amp_nodetalker", "pibrary", "noderecorder"),
    "close_firewall_port": ("sysmon_pi02w", "nodecontrol_pi02w", "wifimon", "instmon", "44helper",
                            "nodetalker", "amp_nodetalker", "pibrary", "noderecorder"),
    "system_profile": ("44helper", "wifimon"),
    "allmon3_sync": ("44helper", "nodecontrol", "nodecontrol_pi02w", "nodetalker", "noderecorder"),
    "suitelog_redact": ("nodetalker", "instmon"),
    "suitelog_append": ("nodetalker", "instmon"),
    "suitelog_rows": ("nodetalker", "instmon"),
    "suitelog_flag": ("nodetalker", "instmon"),
    "rpt_scan": ("noderecorder", "44helper", "nodecontrol", "nodecontrol_pi02w"),
    "rpt_next_free": ("44helper", "nodecontrol", "nodecontrol_pi02w"),
    "rpt_remove_private": ("noderecorder",),
    "svc_table": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "svc_uptime_text": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "svc_unit_info": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "svc_classify": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "svc_rows": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "reg_parse": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "svc_reg_state": ("nodetalker", "nodecontrol", "nodecontrol_pi02w"),
    "sess_policy": (),
    "sess_digest": (),
    "sess_stamp": (),
    "sess_dead": (),
    "sess_new": (),
    "sess_check": (),
    "sess_drop": (),
    "sess_drop_all": (),
    "sess_dump": (),
    "sess_load": (),
    "sess_cookie_name": (),
    "sess_cookie": (),
    "sess_cookie_clear": (),
    "sess_token_from": (),
    "lock_wait": (),
    "lock_fail": (),
    "lock_ok": (),
    "login_ui_html": ("nodetalker", "noderecorder", "instmon", "nodecontrol", "nodecontrol_pi02w", "sysmon", "sysmon_pi02w", "pibrary", "wifimon", "44helper"),
    "login_ui_inject": ("nodetalker", "noderecorder", "instmon", "nodecontrol", "nodecontrol_pi02w", "sysmon", "sysmon_pi02w", "pibrary", "wifimon", "44helper"),
}


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


def http_get(url, max_bytes, timeout=20):
    import urllib.request
    if not url.startswith("https://"):
        raise ValueError("only https addresses are fetched")
    req = urllib.request.Request(url, headers={"User-Agent": "asl-dvs"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("the download is larger than %d bytes" % max_bytes)
    return data


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


def firewall_backend():
    import shutil
    import subprocess
    try:
        if shutil.which("firewall-cmd") and subprocess.run(
                ["firewall-cmd", "--state"], capture_output=True, text=True, timeout=10).stdout.strip() == "running":
            return "firewalld"
        if shutil.which("ufw") and "Status: active" in subprocess.run(
                ["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout:
            return "ufw"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "none"


def open_firewall_port(port, proto="tcp"):
    import re
    import subprocess
    spec = "%d/%s" % (port, proto)
    backend = firewall_backend()
    if backend == "firewalld":
        zone = subprocess.run(["firewall-cmd", "--get-default-zone"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        check = ["firewall-cmd", "--zone=" + zone, "--query-port=" + spec]
        target = subprocess.run(["firewall-cmd", "--zone=" + zone, "--get-target"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        if target == "ACCEPT" or subprocess.run(check, capture_output=True, text=True,
                                                timeout=10).stdout.strip() == "yes":
            return "=", "%s is already open in firewalld zone %s" % (spec, zone)
        subprocess.run(["firewall-cmd", "--zone=" + zone, "--add-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        subprocess.run(["firewall-cmd", "--permanent", "--zone=" + zone, "--add-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        if subprocess.run(check, capture_output=True, text=True, timeout=10).stdout.strip() == "yes":
            return "+", "opened %s in firewalld zone %s (now and after a reboot)" % (spec, zone)
        return "!", "could not open %s in firewalld zone %s" % (spec, zone)
    if backend == "ufw":
        allow = r"^%d/%s\s+ALLOW" % (port, proto)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if "Default: allow (incoming)" in status or re.search(allow, status, re.M):
            return "=", "%s is already open in ufw" % spec
        subprocess.run(["ufw", "allow", spec], capture_output=True, text=True, timeout=10)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if re.search(allow, status, re.M):
            return "+", "opened %s in ufw" % spec
        return "!", "could not open %s in ufw" % spec
    return "=", "no active firewall (ufw or firewalld), so %s is not blocked" % spec


def close_firewall_port(port, proto="tcp"):
    import re
    import subprocess
    spec = "%d/%s" % (port, proto)
    backend = firewall_backend()
    if backend == "firewalld":
        zone = subprocess.run(["firewall-cmd", "--get-default-zone"],
                              capture_output=True, text=True, timeout=10).stdout.strip()
        check = ["firewall-cmd", "--zone=" + zone, "--query-port=" + spec]
        was_open = subprocess.run(check, capture_output=True, text=True, timeout=10).stdout.strip() == "yes"
        subprocess.run(["firewall-cmd", "--zone=" + zone, "--remove-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        subprocess.run(["firewall-cmd", "--permanent", "--zone=" + zone, "--remove-port=" + spec],
                       capture_output=True, text=True, timeout=10)
        if subprocess.run(check, capture_output=True, text=True, timeout=10).stdout.strip() == "yes":
            return "!", "could not close %s in firewalld zone %s" % (spec, zone)
        if was_open:
            return "-", "closed %s in firewalld zone %s" % (spec, zone)
        return "=", "%s was not open in firewalld zone %s" % (spec, zone)
    if backend == "ufw":
        allow = r"^%d/%s\s+ALLOW" % (port, proto)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if not re.search(allow, status, re.M):
            return "=", "%s was not open in ufw" % spec
        subprocess.run(["ufw", "--force", "delete", "allow", spec], capture_output=True, text=True, timeout=10)
        status = subprocess.run(["ufw", "status", "verbose"], capture_output=True, text=True, timeout=10).stdout
        if re.search(allow, status, re.M):
            return "!", "could not close %s in ufw" % spec
        if "Default: allow (incoming)" in status:
            return "!", "closed %s in ufw, but ufw's default allows incoming traffic, so it stays reachable" % spec
        return "-", "closed %s in ufw" % spec
    return "=", "no active firewall (ufw or firewalld), so there is no %s rule to close" % spec


def ami_credentials(conf_path, user="", secret=""):
    if user and secret:
        return user, secret
    try:
        with open(conf_path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return "", ""
    name = ""
    word = ""
    section = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and "]" in line:
            if name and word and section.lower() != "general":
                return name, word
            section = line[1:line.index("]")].strip()
            name = section
            word = ""
            continue
        if "=" in line:
            k, _, v = line.partition("=")
            if k.strip().lower() == "secret":
                word = v.strip()
    if name and word and section.lower() != "general":
        return name, word
    return "", ""


def system_profile(root="/"):
    import os
    import subprocess

    def path(rel):
        return os.path.join(root, rel)

    def read(rel):
        try:
            with open(path(rel), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return ""

    def active(unit):
        try:
            return subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True,
                                  timeout=5).stdout.strip() == "active"
        except (OSError, subprocess.SubprocessError):
            return False

    osr = {}
    for line in read("etc/os-release").splitlines():
        key, sep, val = line.partition("=")
        if sep:
            osr[key.strip()] = val.strip().strip('"').strip("'")
    model = read("proc/device-tree/model").replace("\0", "").strip()
    arch = ""
    try:
        arch = subprocess.run(["dpkg", "--print-architecture"], capture_output=True, text=True,
                              timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if not arch:
        arch = os.uname().machine
    ifaces = []
    try:
        for name in sorted(os.listdir(path("sys/class/net"))):
            if os.path.isdir(path("sys/class/net/" + name + "/wireless")):
                ifaces.append(name)
    except OSError:
        pass
    wpa_sockets = False
    for rel in ("run/wpa_supplicant", "var/run/wpa_supplicant"):
        try:
            if os.listdir(path(rel)):
                wpa_sockets = True
        except OSError:
            pass
    if active("NetworkManager.service"):
        manager = "NetworkManager"
    elif wpa_sockets:
        manager = "wpa_supplicant"
    elif active("systemd-networkd.service"):
        manager = "systemd-networkd"
    else:
        manager = "unknown"
    up = [name for name in ifaces if read("sys/class/net/" + name + "/operstate").strip() == "up"]
    if up:
        wifi_iface = up[0]
    else:
        wifi_iface = "wlan0" if "wlan0" in ifaces else (ifaces[0] if ifaces else "")
    return {
        "board": "pi" if "raspberry pi" in model.lower() else "other",
        "model": model,
        "os_id": osr.get("ID", ""),
        "os_name": osr.get("PRETTY_NAME", ""),
        "codename": osr.get("VERSION_CODENAME", ""),
        "version_id": osr.get("VERSION_ID", ""),
        "arch": arch,
        "wifi_manager": manager,
        "wifi_iface": wifi_iface,
        "wifi_ifaces": ifaces,
    }


def allmon3_sync(text, add=(), remove=(), own=""):
    import re
    hdr = re.compile(r"^\s*\[([^\]]+)\]")
    kvre = re.compile(r"^\s*([^;=\s][^=]*?)\s*=>?\s*(.*)$")
    lines = text.splitlines()
    secs = []
    for i, line in enumerate(lines):
        m = hdr.match(line)
        if m:
            if secs:
                secs[-1]["end"] = i
            secs.append({"name": m.group(1).strip(), "start": i, "end": len(lines)})
    names = {s["name"] for s in secs}
    notes = []
    public = [s for s in secs if s["name"].isdigit() and not 1000 <= int(s["name"]) <= 1999]
    public.sort(key=lambda s: s["name"] != own)
    drop = set()
    for s in secs:
        if s["name"] in remove:
            drop.update(range(s["start"], s["end"]))
            notes.append("allmon3.ini: [%s] removed" % s["name"])
    out = [line for i, line in enumerate(lines) if i not in drop]
    adds = sorted((n for n in add if n not in names and n not in remove), key=int)
    if adds and not public:
        notes.append("allmon3.ini has no public node section to copy host/user/pass from; add "
                     + ", ".join(adds) + " to Allmon3 by hand")
        return "\n".join(out) + "\n", notes
    for n in adds:
        src = public[0]
        body = []
        for i in range(src["start"] + 1, src["end"]):
            s = lines[i].strip()
            m = None if not s or s.startswith(";") or s.startswith("[") else kvre.match(lines[i])
            if m and m.group(1).strip().lower() in ("host", "port", "user", "pass"):
                body.append(lines[i].rstrip())
        while out and not out[-1].strip():
            out.pop()
        out += ["", "[%s]" % n] + body
        notes.append("allmon3.ini: [%s] added (host/user/pass copied from [%s])" % (n, src["name"]))
    return "\n".join(out) + "\n", notes


def suitelog_redact(text, salt):
    import hashlib
    import ipaddress
    import re

    def tag(kind, value):
        return "%s:%s" % (kind, hashlib.sha256((salt + value.lower()).encode("utf-8")).hexdigest()[:4])

    def hide(m):
        return m.group(1) + "[hidden]"

    def ip4(m):
        if m.string[max(0, m.start() - 5):m.start()] == '"v":"':
            return m.group(0)
        try:
            a = ipaddress.IPv4Address(m.group(0))
        except ValueError:
            return m.group(0)
        if a.is_loopback or a.is_unspecified:
            return m.group(0)
        return tag("ip", m.group(0))

    def ip6(m):
        try:
            a = ipaddress.IPv6Address(m.group(0))
        except ValueError:
            return m.group(0)
        if a.is_loopback or a.is_unspecified:
            return m.group(0)
        return tag("ip", m.group(0))

    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [hidden]", text)
    text = re.sub(r"(?i)(\b(?:pass(?:word|wd|phrase)?|psk|secret|token|api[_-]?key|auth(?:orization)?|cookie|credential)s?[\"']?\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;&\"']+)", hide, text)
    text = re.sub(r"(?i)(\bssid\b\s*[:=]?\s*)(?:\"[^\"]*\"|'[^']*')", lambda m: m.group(1) + tag("ssid", m.group(0)), text)
    text = re.sub(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b", lambda m: tag("mac", m.group(0)), text)
    text = re.sub(r"(?<![\w:.])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?![\w:.])", ip6, text)
    text = re.sub(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", ip4, text)
    return text


def suitelog_append(path, row, salt=None, seg_max=10000000):
    import fcntl
    import json
    import os
    import time
    if "t" not in row:
        row = dict(row, t=int(time.time() * 1000))
    line = json.dumps(row, separators=(",", ":"))
    if salt:
        line = suitelog_redact(line, salt)
    data = (line + "\n").encode("utf-8")
    os.makedirs(os.path.dirname(path) or ".", mode=0o755, exist_ok=True)
    lock = os.open(path + ".lock", os.O_RDWR | os.O_CREAT, 0o644)
    try:
        locked = False
        for _ in range(50):
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except BlockingIOError:
                time.sleep(0.01)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, data)
            size = os.fstat(fd).st_size
        finally:
            os.close(fd)
        if not locked or size < seg_max:
            return False
        try:
            if os.stat(path).st_size >= seg_max:
                os.replace(path, path + ".1")
                return True
        except FileNotFoundError:
            pass
        return False
    finally:
        os.close(lock)


def suitelog_rows(path, kinds=None):
    import json
    for name in (path + ".1", path):
        try:
            fh = open(name, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for ln in fh:
                try:
                    row = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(row, dict) and (kinds is None or row.get("kind") in kinds):
                    yield row


def suitelog_flag(path):
    try:
        with open(path, "r", encoding="ascii", errors="replace") as fh:
            return fh.read(64).strip() or "x"
    except OSError:
        return None


def rpt_scan(text):
    import re
    hdr = re.compile(r"^\s*\[([^\]]+)\]\s*(\([^)]*\))?")
    rxline = re.compile(r"^\s*rxchannel\s*=>?\s*([^;\s]+)", re.I)
    usrp = re.compile(r"USRP/[^:\s]+:(\d+):(\d+)", re.I)
    lines = text.split("\n")
    secs = []
    for i, line in enumerate(lines):
        m = hdr.match(line)
        if m:
            if secs:
                secs[-1]["end"] = i
            secs.append({"name": m.group(1).strip(), "start": i, "end": len(lines),
                         "template": (m.group(2) or "").replace(" ", "")})
    used = set()
    ports = set()
    notes = {}
    rx = {}
    nodes_sec = None
    for s in secs:
        name = s["name"]
        if name.isdigit():
            used.add(name)
        elif name.lower().startswith("functions") and name[9:].isdigit():
            used.add(name[9:])
        if name.lower() == "nodes":
            nodes_sec = s
            for i in range(s["start"] + 1, s["end"]):
                body = lines[i].split(";", 1)[0]
                key = body.split("=", 1)[0].strip()
                if "=" in body and key.isdigit():
                    used.add(key)
        for i in range(s["start"] + 1, s["end"]):
            m = rxline.match(lines[i])
            if m:
                rx[name] = m.group(1)
                u = usrp.match(m.group(1))
                if u:
                    ports.update((int(u.group(1)), int(u.group(2))))
        notes[name] = lines[s["start"] - 1].strip() if s["start"] > 0 else ""
    return {"lines": lines, "secs": secs, "used": used, "ports": ports, "notes": notes, "rx": rx,
            "nodes": nodes_sec}


def rpt_next_free(used, start, stop, reserved=()):
    for n in range(int(start), int(stop) + 1):
        s = str(n)
        if s not in used and s not in reserved:
            return s
    return ""


def rpt_remove_private(text, node, marker):
    scan = rpt_scan(text)
    sec = next((s for s in scan["secs"] if s["name"] == node), None)
    if sec is None or scan["notes"].get(node) != marker:
        return text, False
    lines = scan["lines"]
    stop = sec["end"]
    if stop - 1 > sec["start"] and lines[stop - 1].strip().startswith(";"):
        stop -= 1
    while stop - 1 > sec["start"] and not lines[stop - 1].strip():
        stop -= 1
    drop = set(range(sec["start"] - 1, stop))
    ns = scan["nodes"]
    if ns is not None:
        for i in range(ns["start"] + 1, ns["end"]):
            body = lines[i].split(";", 1)[0]
            if "=" in body and body.split("=", 1)[0].strip() == node:
                drop.add(i)
    out = []
    after_drop = False
    for i, line in enumerate(lines):
        if i in drop:
            after_drop = True
            continue
        if not line.strip() and after_drop and out and not out[-1].strip():
            continue
        if line.strip():
            after_drop = False
        out.append(line)
    return "\n".join(out), True


def svc_table():
    return (("asterisk", "Asterisk", ("asterisk",)),
            ("ab", "Analog Bridge", ("analog_bridge", "Analog_Bridge")),
            ("mmdvm", "MMDVM Bridge", ("mmdvm_bridge",)),
            ("stfu", "STFU", ("stfu",)),
            ("m17", "USRP2M17", ("usrp2m17",)))


def svc_uptime_text(sec):
    sec = int(max(0, sec))
    if sec < 60:
        return "Running"
    if sec < 3600:
        return f"Running {sec // 60} min"
    if sec < 86400:
        return f"Running {sec // 3600} h {sec % 3600 // 60} min"
    return f"Running {sec // 86400} d {sec % 86400 // 3600} h"


def svc_unit_info(units, run):
    out = {}
    text = run(["show", "-p", "Id,LoadState,ActiveState,SubState,Result,ExecMainStatus,NRestarts,ActiveEnterTimestampMonotonic",
                *units]) or ""
    for block in text.split("\n\n"):
        kv = dict(ln.split("=", 1) for ln in block.splitlines() if "=" in ln)
        if kv.get("Id"):
            out[kv["Id"]] = kv
    return out


def svc_classify(kv, now_mono):
    if not kv:
        return "warn", "Could not read the service state", True
    if kv.get("LoadState") == "not-found":
        return "off", "Not installed", False
    active, sub = kv.get("ActiveState", ""), kv.get("SubState", "")
    try:
        restarts = int(kv.get("NRestarts") or 0)
    except ValueError:
        restarts = 0
    if active == "active":
        try:
            began = int(kv.get("ActiveEnterTimestampMonotonic") or 0) / 1e6
        except ValueError:
            began = 0.0
        up = now_mono - began if began > 0 else None
        if restarts >= 3 and up is not None and up < 600.0:
            return "warn", f"Restarting often: {restarts} restarts", True
        return "on", svc_uptime_text(up) if up is not None else "Running", True
    if active == "activating":
        if sub == "auto-restart":
            return "warn", "Restarting after a stop" + (f" ({restarts} restarts)" if restarts else ""), True
        return "warn", "Starting...", True
    if active == "reloading":
        return "warn", "Reloading...", True
    if active == "deactivating":
        return "warn", "Stopping...", True
    if active == "failed":
        code = kv.get("ExecMainStatus", "")
        nice = {"exit-code": "exited with an error", "signal": "killed by a signal", "core-dump": "crashed",
                "timeout": "timed out", "start-limit-hit": "restarted too often", "watchdog": "watchdog timeout",
                "oom-kill": "out of memory"}
        why = f"exit code {code}" if code not in ("", "0") else nice.get(kv.get("Result") or "", "")
        return "fail", "Failed" + (f": {why}" if why else ""), True
    if active == "inactive":
        return "fail", "Stopped", True
    return "warn", f"State: {active or 'unknown'}", True


def svc_rows(run, now_mono, stfu_probe=None):
    table = svc_table()
    info = svc_unit_info([u + ".service" for _k, _l, units in table for u in units], run)
    rows = []
    for key, label, units in table:
        unit = next((u for u in units if (info.get(u + ".service") or {}).get("LoadState") not in (None, "not-found")), units[0])
        light, detail, installed = svc_classify(info.get(unit + ".service"), now_mono)
        restartable = installed and light != "off"
        if key == "stfu" and not installed and stfu_probe is not None:
            by_hand = stfu_probe()
            if by_hand is not None:
                light, detail = ("on", "Running, started by hand (no service)") if by_hand else ("fail", "Not running (no service)")
        rows.append({"key": key, "label": label, "unit": unit + ".service", "light": light, "detail": detail,
                     "installed": installed, "restartable": restartable})
    return rows


def reg_parse(out, node):
    import re
    if not out.strip() or not node:
        return "unknown"
    bad = ("unregist", "rejected", "failed", "timeout", "timed out", "authentication")
    cols_re = re.compile(r"^\s*(\S+)\s+(\S+)\s+(\S+)\s+(\d+)\s+(.+?)\s*$")
    pat = re.compile(r"(?<!\d)" + re.escape(node) + r"(?!\d)")
    state = "unregistered"
    for line in out.splitlines():
        cols = cols_re.match(line)
        if cols and cols.group(2) == node:
            text = cols.group(5).lower()
        elif pat.search(line):
            text = " ".join(t for t in line.lower().split() if "." not in t)
        else:
            continue
        if any(w in text for w in bad):
            return "unregistered"
        state = "registered" if re.search(r"\bregistered\b", text) else "unknown"
    return state


def svc_reg_state(node, asterisk_on, parsed):
    node = str(node or "").strip()
    if not node.isdigit():
        return "none", "No node number found"
    if 1000 <= int(node) <= 1999:
        return "private", "Private node: it never registers with AllStarLink"
    if not asterisk_on:
        return "unknown", "Asterisk is not running"
    if parsed is None:
        return "unknown", "Asterisk did not answer"
    if parsed == "registered":
        return "registered", "Registered"
    if parsed == "unregistered":
        return "unregistered", "Not registered"
    return "unknown", "Not known yet"


def sess_policy(tier):
    if tier == "standard":
        return {"idle": 12 * 3600, "absolute": 0, "renew": 3600, "max": 50}
    if tier == "strict":
        return {"idle": 2 * 3600, "absolute": 12 * 3600, "renew": 3600, "max": 50}
    raise ValueError("unknown session tier: %s" % (tier,))


def sess_digest(token):
    import hashlib
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


def sess_stamp(password_hash):
    import hashlib
    return hashlib.sha256((password_hash or "").encode("utf-8")).hexdigest()[:32]


def sess_dead(rec, now):
    return rec["idle"] <= now or bool(rec["abs"] and rec["abs"] <= now)


def sess_new(store, policy, now, stamp="", ip=""):
    import secrets
    for key in [k for k, r in store.items() if sess_dead(r, now)]:
        del store[key]
    while len(store) >= policy["max"]:
        del store[min(store, key=lambda k: store[k]["born"])]
    token = secrets.token_hex(32)
    idle = now + policy["idle"]
    hard = now + policy["absolute"] if policy["absolute"] else 0
    store[sess_digest(token)] = {"idle": min(idle, hard) if hard else idle, "abs": hard, "born": now,
                                 "renew": now, "stamp": stamp, "ip": ip}
    return token, int(min(idle, hard) - now if hard else idle - now)


def sess_check(store, token, policy, now, stamp=None, touch=True, ip=None):
    if not token:
        return False, False, 0
    key = sess_digest(token)
    rec = store.get(key)
    if rec is None:
        return False, False, 0
    if (sess_dead(rec, now) or (stamp is not None and rec["stamp"] != stamp)
            or (ip is not None and rec["ip"] and rec["ip"] != ip)):
        del store[key]
        return False, False, 0
    if touch:
        rec["idle"] = now + policy["idle"]
        if rec["abs"]:
            rec["idle"] = min(rec["idle"], rec["abs"])
    renew = bool(touch and now - rec["renew"] >= policy["renew"])
    if renew:
        rec["renew"] = now
    return True, renew, int(rec["idle"] - now)


def sess_drop(store, token):
    return store.pop(sess_digest(token), None) is not None if token else False


def sess_drop_all(store):
    count = len(store)
    store.clear()
    return count


def sess_dump(store, boot):
    return {"v": 1, "boot": boot, "sessions": {k: dict(r) for k, r in store.items()}}


def sess_load(store, data, boot, now):
    if (not isinstance(data, dict) or data.get("v") != 1 or data.get("boot") != boot
            or not isinstance(data.get("sessions"), dict)):
        return 0
    loaded = 0
    for key, rec in data["sessions"].items():
        if not isinstance(key, str) or len(key) != 64 or not isinstance(rec, dict):
            continue
        if not all(isinstance(rec.get(f), (int, float)) and not isinstance(rec.get(f), bool)
                   for f in ("idle", "abs", "born", "renew")):
            continue
        if not isinstance(rec.get("stamp"), str) or not isinstance(rec.get("ip"), str):
            continue
        clean = {f: rec[f] for f in ("idle", "abs", "born", "renew", "stamp", "ip")}
        if sess_dead(clean, now):
            continue
        store[key] = clean
        loaded += 1
    return loaded


def sess_cookie_name(name, secure):
    return ("__Host-" if secure else "") + name


def sess_cookie(name, token, max_age, secure):
    parts = [sess_cookie_name(name, secure) + "=" + token, "Path=/", "HttpOnly", "SameSite=Strict",
             "Max-Age=%d" % max(0, int(max_age))]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def sess_cookie_clear(name, secure):
    return sess_cookie(name, "", 0, secure)


def sess_token_from(cookie_header, name):
    wanted = (name, "__Host-" + name)
    for part in (cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key in wanted and value:
            return value
    return None


def lock_wait(state, ip, now, wan=False):
    recent = state.setdefault("wan", [])
    while recent and now - recent[0] > 600:
        recent.pop(0)
    rec = state.setdefault("ip", {}).get(ip)
    wait = max(0.0, rec["until"] - now) if rec else 0.0
    if wan and len(recent) >= 20:
        wait = max(wait, recent[0] + 600 - now)
    return wait


def lock_fail(state, ip, now, wan=False):
    table = state.setdefault("ip", {})
    recent = state.setdefault("wan", [])
    for key in [k for k, r in table.items() if now - r["last"] > 3600 and r["until"] <= now]:
        del table[key]
    while len(table) >= 1000 and ip not in table:
        del table[min(table, key=lambda k: table[k]["last"])]
    if wan:
        recent.append(now)
        del recent[:-20]
    rec = table.setdefault(ip, {"n": 0, "until": 0.0, "last": now})
    rec["n"] += 1
    rec["last"] = now
    if rec["n"] >= 5:
        rec["until"] = now + min(5 * 2 ** min(rec["n"] - 5, 10), 300)
    return max(0.0, rec["until"] - now)


def lock_ok(state, ip):
    state.setdefault("ip", {}).pop(ip, None)


def login_ui_html(input_id, nonce=""):
    import json
    attr = ' nonce="%s"' % nonce if nonce else ""
    css = (
        ".pw-wrap{position:relative;display:block}"
        ".pw-wrap>input{box-sizing:border-box;width:100%;padding-right:2.7rem}"
        ".pw-wrap>.pw-eye{position:absolute!important;top:50%!important;right:.3rem!important;transform:translateY(-50%)!important;"
        "width:2.1rem!important;height:2.1rem!important;min-width:0!important;min-height:0!important;margin:0!important;padding:0!important;"
        "border:0!important;border-radius:4px!important;background:transparent!important;color:inherit!important;opacity:.7;"
        "cursor:pointer;box-shadow:none!important;filter:none!important;text-shadow:none!important;text-transform:none!important;"
        "letter-spacing:0!important;font-size:1rem!important;line-height:1!important;display:flex!important;align-items:center!important;"
        "justify-content:center!important}"
        ".pw-wrap>.pw-eye:hover,.pw-wrap>.pw-eye:focus-visible{opacity:1;background:rgba(127,127,127,.2)!important;box-shadow:none!important;filter:none!important}"
        ".pw-wrap>.pw-eye:active{transform:translateY(-50%)!important}"
        ".pw-eye svg{width:1.25rem;height:1.25rem;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;"
        "stroke-linejoin:round;pointer-events:none}"
        ".pw-eye .pw-off{display:none}"
        '.pw-eye[aria-pressed="true"] .pw-on{display:none}'
        '.pw-eye[aria-pressed="true"] .pw-off{display:block}'
    )
    skin = (
        ".lg-screen{position:fixed;inset:0;z-index:9999;display:flex;flex-direction:column;align-items:center;justify-content:center;"
        "gap:14px;box-sizing:border-box;padding:24px 16px 56px;background:#070b13;color:#e6edf6;"
        "font-family:'Readex Pro',Arial,Helvetica,sans-serif}"
        ".lg-screen.hidden,.lg-screen[hidden]{display:none}"
        ".lg-card{box-sizing:border-box;width:100%;max-width:320px;margin:0;padding:25.6px 22.4px 19.2px;background:#121a29;"
        "border:1px solid #2c3d5a;border-radius:10px;box-shadow:0 12px 40px rgba(0,0,0,.5);display:flex;flex-direction:column;"
        "gap:12px;text-align:center}"
        ".lg-form{margin:0;padding:0;display:flex;flex-direction:column;gap:12px}"
        ".lg-title{margin:0 0 4px;padding:0;font-family:inherit;font-size:18.4px;font-weight:700;line-height:1.2;"
        "letter-spacing:.02em;color:#ffd040;text-shadow:none}"
        "input.lg-in{box-sizing:border-box;width:100%;min-height:0;height:auto;margin:0;padding:9.6px 11.2px;font-family:inherit;"
        "font-size:15.2px;line-height:1.2;background:#0a1020;color:#fff;border:1px solid #2c3d5a;border-radius:6px;outline:none}"
        "input.lg-in:focus,input.lg-in:focus-visible{border-color:#ffd040;outline:none}"
        "button.lg-btn{box-sizing:border-box;width:100%;min-height:0;margin:0;padding:10.4px;font-family:inherit;font-size:14.4px;"
        "font-weight:700;line-height:1.2;letter-spacing:0;text-transform:none;background:#ffd040;color:#1a1300;border:0;"
        "border-radius:6px;cursor:pointer;box-shadow:none;text-shadow:none;filter:none;transition:none}"
        "button.lg-btn:hover:not(:disabled){background:#ffd040;color:#1a1300;filter:brightness(1.08);box-shadow:none}"
        "button.lg-btn:disabled{opacity:.5;cursor:default}"
        ".lg-msg{min-height:17.6px;margin:0;font-size:12.8px;line-height:1.3;color:#ff5d73;text-align:center}"
        ".lg-note{margin:0;max-width:300px;font-size:12.5px;color:#ff5d73}.lg-note:empty{display:none}"
        "button.lg-link{width:auto;min-height:0;margin:0 auto;padding:3.2px 8px;background:none;border:0;box-shadow:none;"
        "color:#8aa0bf;font-family:inherit;font-size:12.8px;text-decoration:underline;text-transform:none;letter-spacing:0;cursor:pointer}"
        ".lg-license{position:absolute;left:0;right:0;bottom:14px;text-align:center;font-size:11.5px;letter-spacing:.04em;color:#7d8aa0}"
        ".lg-license a{color:#6cb6ff}"
    )
    js = (
        "(function(){var ID=" + json.dumps(input_id).replace("</", "<\\/") + ";"
        "function go(){var input=document.getElementById(ID);if(!input||input.getAttribute('data-pw-eye'))return;"
        "input.setAttribute('data-pw-eye','1');"
        "var wrap=document.createElement('span');wrap.className='pw-wrap';"
        "input.parentNode.insertBefore(wrap,input);wrap.appendChild(input);"
        "var b=document.createElement('button');b.type='button';b.className='pw-eye';"
        "b.innerHTML='<svg class=\"pw-on\" viewBox=\"0 0 24 24\" aria-hidden=\"true\"><path d=\"M1 12s4-7 11-7 11 7 11 7-4 7-11 7S1 12 1 12z\"/>"
        "<circle cx=\"12\" cy=\"12\" r=\"3\"/></svg><svg class=\"pw-off\" viewBox=\"0 0 24 24\" aria-hidden=\"true\">"
        "<path d=\"M17.9 17.9A10.9 10.9 0 0 1 12 19C5 19 1 12 1 12a18.5 18.5 0 0 1 5.1-5.9M9.9 5.1A10.9 10.9 0 0 1 12 5c7 0 11 7 11 7"
        "a18.5 18.5 0 0 1-2.2 3.2M14.1 14.1a3 3 0 1 1-4.2-4.2\"/><path d=\"M1 1l22 22\"/></svg>';"
        "function show(on){input.type=on?'text':'password';b.setAttribute('aria-pressed',on?'true':'false');"
        "var t=on?'Hide password':'Show password';b.setAttribute('aria-label',t);b.title=t;}"
        "show(false);"
        "b.addEventListener('mousedown',function(e){e.preventDefault();});"
        "b.addEventListener('click',function(){show(input.type==='password');input.focus();});"
        "if(input.form)input.form.addEventListener('submit',function(){show(false);});"
        "document.addEventListener('visibilitychange',function(){if(document.hidden)show(false);});"
        "window.addEventListener('pagehide',function(){show(false);});"
        "wrap.appendChild(b);}"
        "if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',go);else go();})();"
    )
    return "<style%s>%s</style><script%s>%s</script>" % (attr, skin + css, attr, js)


def login_ui_inject(html, input_id, nonce=""):
    head, sep, tail = html.rpartition("</body>")
    if not sep:
        return html
    return head + login_ui_html(input_id, nonce) + sep + tail

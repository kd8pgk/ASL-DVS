USED_BY = {
    "atomic_write": ("nodecontrol", "nodecontrol_pi02w", "sysmon", "sysmon_pi02w", "nodetalker",
                     "amp_nodetalker", "44helper", "wifimon", "confputter", "pibrary"),
    "ami_credentials": ("nodetalker",),
    "http_get": ("44helper",),
    "fill_secrets": ("44helper", "confputter"),
    "firewall_backend": ("sysmon_pi02w", "nodecontrol_pi02w", "wifimon", "instmon", "44helper",
                         "nodetalker", "amp_nodetalker", "pibrary"),
    "open_firewall_port": ("sysmon_pi02w", "nodecontrol_pi02w", "wifimon", "instmon", "44helper",
                           "nodetalker", "amp_nodetalker", "pibrary"),
    "close_firewall_port": ("sysmon_pi02w", "nodecontrol_pi02w", "wifimon", "instmon", "44helper",
                            "nodetalker", "amp_nodetalker", "pibrary"),
    "system_profile": ("44helper", "wifimon"),
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
    return {
        "board": "pi" if "raspberry pi" in model.lower() else "other",
        "model": model,
        "os_id": osr.get("ID", ""),
        "os_name": osr.get("PRETTY_NAME", ""),
        "codename": osr.get("VERSION_CODENAME", ""),
        "version_id": osr.get("VERSION_ID", ""),
        "arch": arch,
        "wifi_manager": manager,
        "wifi_iface": "wlan0" if "wlan0" in ifaces else (ifaces[0] if ifaces else ""),
        "wifi_ifaces": ifaces,
    }

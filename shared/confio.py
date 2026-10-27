USED_BY = {
    "atomic_write": ("nodecontrol", "nodecontrol_pi02w", "sysmon", "sysmon_pi02w", "nodetalker",
                     "amp_nodetalker", "44helper", "wifimon", "confputter"),
    "http_get": ("44helper",),
    "fill_secrets": ("44helper", "confputter"),
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

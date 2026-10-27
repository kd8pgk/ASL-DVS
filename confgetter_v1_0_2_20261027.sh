#!/usr/bin/env bash
# confgetter.sh  v1.0.2  (2026-10-27)
set -u

CONFGETTER_VERSION="1.0.2"
ROOT="${CONFGETTER_ROOT:-}"
OUT_DIR="${ROOT}/etc/asl_dvs/instmon_library/snapshots"
KEEP=10
MAX_BYTES=1500000
FILE_MAX=200000

usage() {
    echo "Usage: confgetter.sh [--out DIR] [--keep N]"
    echo "Copies the node's ASL3, DVSwitch, USRP2M17, Allmon3, SvxLink, firewall, 44Net and tool"
    echo "config files, with secrets redacted, into one Markdown file for Claude to read."
    echo "  --out DIR   where to write the snapshot (default ${OUT_DIR})"
    echo "  --keep N    keep the newest N snapshots in DIR (default ${KEEP})"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out) OUT_DIR="${2:-}"; shift 2 ;;
        --keep) KEEP="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[[ -n "$OUT_DIR" ]] || { echo "--out needs a folder" >&2; exit 2; }
[[ "$KEEP" =~ ^[0-9]+$ && "$KEEP" -ge 1 ]] || { echo "--keep needs a number of 1 or more" >&2; exit 2; }
if [[ -z "$ROOT" && $EUID -ne 0 ]]; then
    echo "Run as root: sudo confgetter.sh" >&2
    exit 1
fi
command -v python3 >/dev/null 2>&1 || { echo "python3 is needed and was not found" >&2; exit 1; }

mkdir -p "$OUT_DIR" || { echo "Cannot create $OUT_DIR" >&2; exit 1; }
chmod 0700 "$OUT_DIR" 2>/dev/null || true

WORK="$(mktemp -d)" || { echo "Cannot make a temporary folder" >&2; exit 1; }
trap 'rm -rf "$WORK"' EXIT

UNITS=(nodecontrol sysmon instmon wifimon 44helper nodetalker amp_nodetalker asl_dvs_watchdog.timer
       asterisk allmon3 analog_bridge mmdvm_bridge md380-emu usrp2m17 svxlink stfu asl-zello-bridge
       44net-tunnel 44helper-netready wg-quick@wg0 firewalld fail2ban cloudflared)

n=0
run() {
    local label="$1"; shift
    command -v "$1" >/dev/null 2>&1 || return 0
    n=$((n + 1))
    printf '%s\t%s\n' "$n" "$label" >> "$WORK/labels.tsv"
    timeout 20 "$@" > "$WORK/cmd_$n.txt" 2>&1 || true
}

if [[ -z "$ROOT" ]]; then
    echo "Reading system state..."
    run "uname -a" uname -a
    run "uptime" uptime
    run "df -h /" df -h /
    run "free -h" free -h
    run "systemctl --failed" systemctl --failed --no-legend --no-pager
    run "installed packages (radio, firewall, VPN)" dpkg-query -W -f '${Package} ${Version}\n' \
        'asl3*' 'allmon3' 'dvswitch*' 'svxlink*' 'firewalld' 'fail2ban' 'wireguard*' 'cloudflared' 'nftables'
    run "firewall-cmd --list-all-zones" firewall-cmd --list-all-zones
    run "nft list ruleset" nft list ruleset
    run "wg show" wg show
    run "ip addr" ip addr
    run "ip rule" ip rule
    run "ip route show table all" ip route show table all
    run "asterisk -rx 'core show version'" asterisk -rx "core show version"
    run "asterisk -rx 'rpt localnodes'" asterisk -rx "rpt localnodes"
    for u in "${UNITS[@]}"; do
        if systemctl cat "$u" > "$WORK/unit.tmp" 2>/dev/null; then
            n=$((n + 1))
            printf '%s\t%s\n' "$n" "systemctl cat $u" >> "$WORK/labels.tsv"
            mv "$WORK/unit.tmp" "$WORK/cmd_$n.txt"
        fi
    done
fi

export CG_ROOT="$ROOT" CG_OUT_DIR="$OUT_DIR" CG_KEEP="$KEEP" CG_MAX_BYTES="$MAX_BYTES" \
       CG_FILE_MAX="$FILE_MAX" CG_WORK="$WORK" CG_VERSION="$CONFGETTER_VERSION" CG_UNITS="${UNITS[*]}"

python3 - <<'PY'
import datetime
import glob
import grp
import hashlib
import json
import os
import pwd
import re
import secrets
import socket
import stat

ROOT = os.environ["CG_ROOT"]
OUT_DIR = os.environ["CG_OUT_DIR"]
KEEP = int(os.environ["CG_KEEP"])
MAX_BYTES = int(os.environ["CG_MAX_BYTES"])
FILE_MAX = int(os.environ["CG_FILE_MAX"])
WORK = os.environ["CG_WORK"]
VERSION = os.environ["CG_VERSION"]
UNITS = os.environ["CG_UNITS"].split()
SALT = secrets.token_bytes(16)

GROUPS = [
    ("ASL3 / Asterisk", ["etc/asterisk/*.conf", "etc/asterisk/custom/**/*"]),
    ("DVSwitch", ["opt/Analog_Bridge/*.ini", "opt/MMDVM_Bridge/*.ini", "opt/YSFGateway/*.ini",
                  "opt/P25Gateway/*.ini", "opt/NXDNGateway/*.ini", "opt/Analog_Reflector/*.ini",
                  "etc/Analog_Bridge/*.ini", "etc/MMDVM_Bridge/*.ini", "etc/YSFGateway/*.ini",
                  "etc/P25Gateway/*.ini", "etc/NXDNGateway/*.ini", "etc/Analog_Reflector/*.ini",
                  "etc/dvswitch/*", "var/lib/dvswitch/dvs/var.txt"]),
    ("USRP2M17", ["opt/USRP2M17/*.ini"]),
    ("Allmon3", ["etc/allmon3/*.ini"]),
    ("SvxLink", ["etc/svxlink/**/*", "usr/local/etc/svxlink/**/*"]),
    ("Firewall and 44Net Connect", ["etc/firewalld/firewalld.conf", "etc/firewalld/zones/*.xml",
                                    "etc/firewalld/services/*.xml", "etc/wireguard/*.conf",
                                    "etc/sysctl.d/*.conf", "etc/fail2ban/jail.local", "etc/fail2ban/jail.d/*",
                                    "etc/ssh/sshd_config.d/*.conf"]),
    ("Node tools", ["etc/asl_dvs/*.conf", "etc/asl_dvs/*.json", "etc/sysmon/*.conf", "etc/44helper/*.conf",
                    "etc/wifimon/*.conf", "etc/NetworkManager/conf.d/*.conf", "etc/modprobe.d/wifimon-*.conf",
                    "etc/systemd/system.conf.d/*.conf"]),
    ("Network and system", ["etc/os-release", "etc/hostname", "etc/hosts", "etc/resolv.conf",
                            "etc/network/interfaces", "etc/network/interfaces.d/*", "etc/dhcpcd.conf",
                            "etc/NetworkManager/system-connections/*", "etc/wpa_supplicant/*.conf",
                            "etc/asound.conf", "etc/systemd/journald.conf"]),
]
ASTERISK_KEY = {"rpt.conf", "extensions.conf", "iax.conf", "modules.conf", "manager.conf", "echolink.conf",
                "savenode.conf", "simpleusb.conf", "usbradio.conf", "pjsip.conf", "rpt_http_registrations.conf",
                "voter.conf", "logger.conf"}
SKIP_NAME = re.compile(r"(\.key|\.pem|\.p12|\.pfx|\.crt|\.der|\.csr|privatekey|credentials|token|secret|"
                       r"auth\.txt|\.bak|\.swp|~)$", re.I)
ALLOWED_TREES = ("/etc/", "/opt/", "/var/lib/dvswitch/", "/usr/local/etc/", "/usr/lib/os-release",
                 "/run/systemd/resolve/")
DENY = re.compile(r"^/etc/(shadow|gshadow|sudoers|ssh/ssh_host_|ssl/private/|cloudflared/|ampersand/)")
SECRET_KEY = re.compile(r"(pass(word|wd|phrase)?|pwd|secret|token|psk|private_?key|preshared_?key|api_?key|"
                        r"auth_?key|login_?key|shared_?key|wpa_?key)", re.I)
KV = re.compile(r"^(\s*(?:export\s+)?)([A-Za-z0-9_.\-]+)(\s*(?:=>|=|:)\s*)(.*?)(\s*)$")
REGISTER = re.compile(r"(register\s*=>?\s*[^:@\s]+:)(?!<redacted:)([^@\s]+)(@)", re.I)
URLQ = re.compile(r"([?&](?:pass|password|pwd|secret|token|key)=)(?!<redacted:)([^&\s\"']+)", re.I)
FLAG = re.compile(r"(--(?:token|password|pass|secret)[=\s]+)(?!<redacted:)(\S+)", re.I)
EMAIL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
MAC = re.compile(r"\b([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}):[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}\b")
PIPE_PASS = re.compile(r"^(password|passwd|pass|pwd)$", re.I)
PRIVATE_KEY = re.compile(r"^e_?mail$", re.I)
ENVKV = re.compile(r"\b([A-Za-z_]*(?:PASS|SECRET|TOKEN|PSK|PRIVATE_?KEY)[A-Za-z_]*=)(?!<redacted:)([^\s\"']+)", re.I)
counts = {"redacted": 0}


def tag(value):
    counts["redacted"] += 1
    return "<redacted:%s>" % hashlib.sha256(SALT + value.encode("utf-8", "replace")).hexdigest()[:8]


def redact_line(line):
    if not line.strip():
        return line
    stripped = line.lstrip()
    if stripped.startswith(";") or stripped.startswith("#"):
        body = stripped[1:]
        lead = line[:len(line) - len(stripped)] + stripped[0]
        return lead + redact_line(body) if KV.match(body) else line
    line = REGISTER.sub(lambda m: m.group(1) + tag(m.group(2)) + m.group(3), line)
    line = URLQ.sub(lambda m: m.group(1) + tag(m.group(2)), line)
    line = FLAG.sub(lambda m: m.group(1) + tag(m.group(2)), line)
    line = ENVKV.sub(lambda m: m.group(1) + tag(m.group(2)), line)
    line = EMAIL.sub(lambda m: tag(m.group(0)), line)
    line = MAC.sub(lambda m: m.group(1) + ":xx:xx:xx", line)
    m = KV.match(line)
    if m and SECRET_KEY.search(m.group(2)) and m.group(4) and not m.group(4).startswith("<redacted:"):
        return m.group(1) + m.group(2) + m.group(3) + tag(m.group(4)) + m.group(5)
    return line


def redact_json(obj):
    if isinstance(obj, dict):
        return {k: (tag(json.dumps(v)) if (SECRET_KEY.search(str(k)) or PRIVATE_KEY.match(str(k)))
                    and v not in ("", None)
                    else redact_json(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_json(v) for v in obj]
    return obj


def redact_pipes(lines):
    col = None
    out = []
    for ln in lines:
        s = ln.strip()
        if s.startswith("["):
            col = 1 if "server" in s.lower() else None
        elif s[:1] in ("#", ";") and "|" in s:
            names = [f.strip() for f in s.lstrip("#;").split("|")]
            col = next((i for i, f in enumerate(names) if PIPE_PASS.match(f)), None)
        elif col is not None and "|" in s and s[:1] not in ("#", ";"):
            parts = ln.split("|")
            if len(parts) > col and parts[col].strip():
                parts[col] = tag(parts[col].strip())
                ln = "|".join(parts)
        out.append(ln)
    return out


def redact_text(text, path=""):
    if path.endswith(".json"):
        try:
            return json.dumps(redact_json(json.loads(text)), indent=1, sort_keys=True) + "\n"
        except ValueError:
            pass
    return "\n".join(redact_line(ln) for ln in redact_pipes(text.split("\n")))


def real(rel):
    return os.path.join(ROOT or "/", rel)


def shown(full):
    return "/" + os.path.relpath(full, ROOT) if ROOT else full


def dpkg_conffiles():
    out = {}
    try:
        with open(real("var/lib/dpkg/status"), encoding="utf-8", errors="replace") as fh:
            inside = False
            for line in fh:
                if line.startswith("Conffiles:"):
                    inside = True
                    continue
                if inside and line.startswith(" "):
                    parts = line.split()
                    if len(parts) >= 2:
                        out[parts[0]] = parts[1]
                    continue
                inside = False
    except OSError:
        pass
    return out


def owner(st):
    try:
        u = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        u = str(st.st_uid)
    try:
        g = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        g = str(st.st_gid)
    return u + ":" + g


def fence(text):
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


conffiles = dpkg_conffiles()
seen = set()
entries = []
skipped = []
for group, patterns in GROUPS:
    for pat in patterns:
        for full in sorted(glob.glob(real(pat), recursive=True)):
            if full in seen or not os.path.isfile(full):
                continue
            seen.add(full)
            path = shown(full)
            name = os.path.basename(full)
            target = shown(os.path.realpath(full))
            if not target.startswith(ALLOWED_TREES) or DENY.search(target):
                skipped.append((path, "points outside the config folders, never copied"))
                continue
            if SKIP_NAME.search(name):
                skipped.append((path, "secret or backup file, never copied"))
                continue
            try:
                st = os.stat(full)
                with open(full, "rb") as fh:
                    raw = fh.read(FILE_MAX + 1)
            except OSError as e:
                skipped.append((path, "unreadable: %s" % e.strerror))
                continue
            if b"\0" in raw[:8192]:
                skipped.append((path, "binary file"))
                continue
            digest = hashlib.sha256(raw).hexdigest()
            md5 = hashlib.md5(raw).hexdigest()
            if (path.startswith("/etc/asterisk/") and path.count("/") == 3 and name not in ASTERISK_KEY
                    and conffiles.get(path) == md5):
                skipped.append((path, "same as the package default"))
                continue
            note = "trimmed to %d bytes" % FILE_MAX if len(raw) > FILE_MAX else ""
            text = redact_text(raw[:FILE_MAX].decode("utf-8", "replace"), path)
            entries.append({"group": group, "path": path, "size": st.st_size,
                            "mode": "%04o" % stat.S_IMODE(st.st_mode), "owner": owner(st),
                            "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                            "sha": digest[:12], "note": note, "text": text})

commands = []
labels = os.path.join(WORK, "labels.tsv")
if os.path.isfile(labels):
    with open(labels, encoding="utf-8") as fh:
        for line in fh:
            num, label = line.rstrip("\n").split("\t", 1)
            try:
                with open(os.path.join(WORK, "cmd_%s.txt" % num), encoding="utf-8", errors="replace") as c:
                    out = c.read(FILE_MAX)
            except OSError:
                continue
            commands.append((label, redact_text(out)))
elif ROOT:
    for u in UNITS:
        for d in ("etc/systemd/system", "lib/systemd/system"):
            f = real(os.path.join(d, u if "." in u else u + ".service"))
            if os.path.isfile(f):
                with open(f, encoding="utf-8", errors="replace") as c:
                    commands.append(("unit file " + shown(f), redact_text(c.read(FILE_MAX))))
                break

tools = []
for f in sorted(glob.glob(real("usr/local/bin/*"))):
    try:
        with open(f, encoding="utf-8", errors="replace") as c:
            head = c.read(4096)
    except OSError:
        continue
    m = re.search(r"^(?:VERSION|APP_VERSION|SCRIPT_VERSION)\s*=\s*[\"']([^\"']+)", head, re.M)
    m = m or re.search(r"^#\s*\S+\.sh\s+v(\S+)", head, re.M)
    if m:
        tools.append((shown(os.path.realpath(f)) if ROOT else os.path.realpath(f), m.group(1)))

host = socket.gethostname().split(".")[0] or "node"
now = datetime.datetime.now().astimezone()
used = 0
body_parts = []
current = None
left_out = []
for e in entries:
    block = "### %s\n\n%s\n%s\n%s\n\n" % (e["path"], fence(e["text"]), e["text"].rstrip("\n"), fence(e["text"]))
    if used + len(block) > MAX_BYTES:
        left_out.append(e["path"])
        e["note"] = (e["note"] + "; " if e["note"] else "") + "left out: size budget"
        continue
    if e["group"] != current:
        current = e["group"]
        body_parts.append("## %s\n\n" % current)
    body_parts.append(block)
    used += len(block)
cmd_parts = []
for label, out in commands:
    block = "### %s\n\n%s\n%s\n%s\n\n" % (label, fence(out), out.rstrip("\n"), fence(out))
    if used + len(block) > MAX_BYTES:
        left_out.append(label)
        continue
    cmd_parts.append(block)
    used += len(block)

head = ["# Node config snapshot: %s" % host, "",
        "A read-only copy of a ham radio node's configuration: AllStarLink 3 (Asterisk app_rpt), DVSwitch, "
        "USRP2M17, Allmon3, SvxLink, firewalld, WireGuard (44Net Connect) and the Node Controller tools. "
        "Use it to find errors and differences. Nothing on the node was changed to make it.", "",
        "- Taken: %s" % now.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "- Made by: confgetter.sh %s" % VERSION,
        "- Files copied: %d. Skipped: %d. Left out for size: %d." % (len(entries) - len(left_out), len(skipped),
                                                                 len(left_out)),
        "- Secrets: %d values replaced with `<redacted:xxxxxxxx>`. The same secret gets the same tag within "
        "this file only, so matching tags mean matching values." % counts["redacted"], ""]
if tools:
    head += ["## Installed tools", "", "| Tool | Version |", "|---|---|"]
    head += ["| %s | %s |" % t for t in tools]
    head.append("")
head += ["## Manifest", "", "| Path | Group | Size | Mode | Owner | Modified | SHA-256 | Note |",
         "|---|---|---|---|---|---|---|---|"]
for e in entries:
    head.append("| %s | %s | %d | %s | %s | %s | %s | %s |" % (e["path"], e["group"], e["size"], e["mode"],
                                                               e["owner"], e["mtime"], e["sha"], e["note"]))
head.append("")
if skipped:
    head += ["## Skipped", "", "| Path | Why |", "|---|---|"]
    head += ["| %s | %s |" % s for s in skipped]
    head.append("")
text = "\n".join(head) + "\n" + "".join(body_parts)
if cmd_parts:
    text += "## Commands\n\n" + "".join(cmd_parts)

stamp = now.strftime("%Y%m%d-%H%M%S")
final = os.path.join(OUT_DIR, "confgetter_%s_%s.md" % (re.sub(r"[^A-Za-z0-9_-]", "_", host), stamp))
tmp = os.path.join(OUT_DIR, ".confgetter.%s.tmp" % secrets.token_hex(6))
fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)
except BaseException:
    try:
        os.unlink(tmp)
    except OSError:
        pass
    raise
snaps = sorted(glob.glob(os.path.join(OUT_DIR, "confgetter_*.md")), key=os.path.getmtime, reverse=True)
for old in snaps[KEEP:]:
    try:
        os.unlink(old)
    except OSError:
        pass
print("Snapshot written: %s (%d bytes, %d files, %d secrets redacted)" % (final, len(text.encode("utf-8")),
                                                                         len(entries) - len(left_out),
                                                                         counts["redacted"]))
PY

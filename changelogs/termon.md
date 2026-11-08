# Terminal Monitor (termon) changelog

Current file: `termon_v0_1_7_20261108.py`. Newest entries first.

## 0.1.7 (2026-11-08)

Answers the external security audit of termon 0.1.5 (`Security Audit Report - termon v0.1.5`) and a review of 0.1.6. The tool is added to the repo with this version. This is a release: Python and page JavaScript behaviour changed.

Findings fixed:

- **H1, no TLS.** termon now serves HTTPS by default. On first start it creates a self-signed certificate (EC P-256, 10 years, names and LAN addresses of the node) in `/etc/asl_dvs/termon_tls/` (folder 0700, key 0600), the same way Node Talker does. The session cookie is then `__Host-termon_session` with `Secure`. If HTTPS is on and no certificate can be made (no `openssl`), termon does not start; it never falls back to clear text by itself. `https = false` in `/etc/asl_dvs/termon.conf` turns HTTPS off, and the log then warns that the password and terminal travel in clear text. A plain-HTTP request to the HTTPS port gets no answer. Open `https://<node address>:7878/` and accept the certificate once.
- **H2, DNS rebinding.** Already closed in 0.1.6 (Host allowlist, one Host header, Origin and Sec-Fetch-Site checks on POST). Kept, and now covered by tests, including a duplicate Host header and a refused Host on a method other than GET or POST.
- **H3, lockout bypass by IPv6 rotation.** Lockouts are keyed on the /64 prefix for IPv6 (an IPv4-mapped address uses its IPv4 key), so rotating addresses inside one prefix shares one count. The lockout ceiling is 900 s (was 300 s). A global speed bump was added: after 20 failed sign-ins from any source in 5 minutes, each further wrong password is answered 2 s late. It never refuses a correct password, so it cannot lock the administrator out (see M1). The tracking table has a hard cap and drops the oldest unlocked entries first.
- **H4, shared root password, no audit trail.** The terminal is a root shell by design, so the account model is not changed. Sign-ins (and failed ones), lockouts, terminal opens and closes (who, from where, how long, exit code), package installs, port changes and allowed-name changes are now written to the journal and to syslog (`termon`, facility authpriv). Commands typed are not logged.
- **M1, lockout used against the administrator.** Kept per source on purpose; the new global limit slows guessing and does not lock anyone out. The cap on the tracking table means a flood of addresses cannot evict a locked source before unlocked ones.
- **M2, opening a terminal closed everyone's.** Opening a terminal replaces only that login's own terminal. Different logins keep theirs, up to 4 terminals at once (the next one is refused with 409). Sign out, session expiry and the page's close request still end only the owning login's terminal.
- **M3, `pty.fork()` in a threaded process.** The shell and monitor programs now start with `subprocess.Popen` on a pty (the child makes itself a session leader, takes the pty as its controlling terminal and execs; no Python code runs between fork and exec in the threaded server). Descriptors are closed by `close_fds`, so the listening socket is still never inherited.
- **M4, other HTTP methods skipped the checks.** Every method now goes through the same gate (LAN, proxy headers, Host) and is then answered 405 with `Allow: GET, POST`, with the security headers. Malformed requests and parser errors (`send_error`) also carry the security headers and a JSON `message`.
- **M5, Transfer-Encoding.** Any `Transfer-Encoding` header is refused with 501. A request needs exactly one `Content-Length`, plain ASCII digits (so `1_0`, `+2` and spaces no longer parse).
- **M6, `unsafe-inline` scripts.** The page script and style blocks carry a per-response nonce and `script-src` is `'self' 'nonce-...'` with no `unsafe-inline`. `style-src` keeps `'unsafe-inline'` because xterm.js writes its own style elements and the page uses style attributes; script execution is what the audit asked to close. Added `object-src 'none'`, `Cross-Origin-Opener-Policy` and `Cross-Origin-Resource-Policy: same-origin`. The page's close-on-unload request is now a keepalive `fetch` (a beacon cannot send the new header below).
- **M7, `sh -c` in the installer.** `apt-get update` and `apt-get install` run as two argument lists, no shell. The package is still checked against a fixed list first. A failed update stops the install.
- **M8, unanchored `termon*.service` glob.** `--install` and `--uninstall` remove only units named `termon.service` or `termon-<name>.service`, and only unit files whose `ExecStart` runs termon (or links).

Found in review, fixed:

- A password containing a NUL byte was cut at the NUL by the C `crypt` call, so a correct password followed by `\0junk` signed in. NUL is refused.
- Every POST needs `X-Requested-With: XMLHttpRequest` (page requests send it), on top of the JSON content type, `SameSite=Strict`, Origin and Sec-Fetch-Site checks.
- Peers outside the LAN are dropped at accept, before the TLS handshake or any parsing. The gate in the handler stays.
- Error replies use the `message` key (repo convention for new tools); the page reads `message`.
- Cleanup timers for closing terminals are daemon threads.

Not changed, and why: the password is the node's root password (the tool's purpose is a root terminal on the node; a separate unprivileged account would remove what it is for). The audit's Low items L1 to L10 are not itemized in the report; the review above covers what the source showed.

Tests: `ci/test_termon.py` (new), and termon is in the server and security tables.

## 0.1.6 (2026-11-08)

- Idle limit: a session ends 2 hours after its last click or keystroke. The output stream and its reconnects no longer keep it alive. Ending a session (sign out or expiry) closes its terminal. The session cookie has no Max-Age.
- Host header check against DNS rebinding: IP addresses, localhost, this node's names and names saved in Setup (Allowed names) are accepted; any other name, and a missing or duplicate Host header, gets 403. Origin and Sec-Fetch-Site check on every POST. Referrer-Policy is now same-origin.

## 0.1.5 (2026-11-08)

- Security audit fixes. Password checks run one at a time, so parallel guesses cannot outrun the lockout. Sockets time out after 30 s, at most 64 connections are served at once, and the accept backlog is 64, so a flood of half-open requests no longer holds threads forever. Shells and apt no longer inherit systemd service variables (NOTIFY_SOCKET, WATCHDOG_*, INVOCATION_ID, LISTEN_*).

## 0.1.4 (2026-11-08)

- Fix `--install` refusing to run when started with sudo. The check now only counts termon server processes (Python), not sudo or the installer itself, so only the server is stopped and only a shell inside a termon server is refused.

## 0.1.3 (2026-11-08)

- One terminal at a time: opening one closes any other. Single-instance lock (`/run/termon.lock`): a second copy refuses to start. `--install` and `--uninstall` remove the existing termon units, unit files, install folder and link, and kill other termon processes with their children first. Config is kept. `--install` refuses to run inside a termon shell.

## 0.1.2 (2026-11-08)

- Fix "too many terminals" after page reloads. One shell and one program per login: opening again replaces the old one. Sessions with no page attached are closed after 10 minutes. The page sends a close request when it unloads.

## 0.1.1 (2026-11-08)

- Setup card can be collapsed. It starts collapsed on each page load; the state is not saved.

## 0.1.0 (2026-11-08)

- New tool. Built on Node Talker 0.10.24's server, root login, config and install code. Two pages: Monitor (top, htop or btop; opens the program chosen last time) and Terminal (root bash shell over a PTY).
- xterm.js 5.3.0 and xterm-addon-fit 0.8.0 are embedded (gzip+base64, sha256 checked). Copy-output buffer is kept in the browser only.
- Setup card: install htop, btop or procps (top) with apt, and change the port (default 7878).
- LAN only: loopback, RFC 1918 and link-local peers. Tailscale 100.64.0.0/10 and fd7a:115c:a1e0::/48 are refused. Requests carrying proxy headers are refused.
- Session transport is Server-Sent Events for output and POST for input (stdlib only; no WebSocket). Login tickets last 60 s.
- `--install` does not edit rpt.conf. It reports Node Talker feed hooks that are still present.

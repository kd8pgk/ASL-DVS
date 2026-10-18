# nodelisten changelog

Current file: `nodelisten_v0_2_0_20261018.py`. Newest entries first.

## 0.2.0 (2026-10-18)

Background listening, aimed at Android Chrome. Page changes only; the server and
stream are unchanged.

- **Plays through a media element.** The Web Audio output now goes to a hidden
  `<audio>` element (`MediaStreamAudioDestinationNode` -> `srcObject`) instead of
  straight to the speakers. The browser then treats the page as playing media, which
  is what lets Android keep it going in the background and with the screen off. If
  the element can't play, it falls back to the 0.1.0 path.
- **Phone media controls.** Media Session metadata ("Node <number>", "Node Listen",
  the Pi's address) and play / pause / stop handlers, so the notification and lock
  screen show it and can stop or restart it. The playing / paused state follows the
  Listen button.
- **Keep the screen on while listening** (checkbox, remembered in the browser). It
  uses the Screen Wake Lock API, which browsers only allow over HTTPS or on
  localhost, so on a plain `http://<pi>:8993` page the checkbox stays hidden.
- A line under the Listen card says playback can carry on in the background.

## 0.1.0 (2026-10-18)

First release. A common tool: one stdlib-only file, built on the same skeleton
as instmon and Pibrary (root-password login, sessions and lockout, the
X-Requested-With check, the `sd_notify` watchdog, `--install` / `--uninstall`,
the shared launcher).

- **Listen card.** Listen / Stop, volume (0-200%), a level meter, and lights for
  "feed from Asterisk" and "audio passing". The browser reads `GET /api/listen`
  as a stream (8 kHz mu-law, 64 kbit/s) and plays it with Web Audio, about
  0.25-0.5 s behind the node. It reconnects by itself after 3 s if the stream
  drops. Listeners are capped (default 3; a full house gets a 503).
- **Node card.** Lists the numbered nodes in `/etc/asterisk/rpt.conf` and their
  `outstreamcmd` (own, another one, or inherited from a template). **Send its
  audio here** adds
  `outstreamcmd = /usr/bin/python3,/usr/local/bin/nodelisten.py,--feed,<udp_port>`
  to that node's stanza, with a comment line above it, after backing rpt.conf up
  to `/etc/asl_dvs/nodelisten_backups/` (last 10 kept). Only one node is hooked at
  a time. A node with someone else's `outstreamcmd` (for example Broadcastify) is
  refused. **Remove** takes the line out; **Restart Asterisk** asks first. The
  card also shows whether the feeder process is running and the UDP input state.
- **Feed mode.** `nodelisten.py --feed <port>` is what Asterisk runs: it copies
  stdin to `127.0.0.1:<port>/udp` and never stops on send errors, so Asterisk's
  pipe never blocks while Node Listen restarts.
- **Audio pump.** A 20 ms clock takes the node's audio from a short queue (0.5 s
  cap, trimmed past 0.2 s to keep the delay low) and sends silence when the node
  is quiet, so the browser's timing stays steady.
- **Settings.** Web port (8993), UDP port (6200), max listeners, and **Listen
  without logging in** (off by default: listening only, never the Node or
  Settings cards). Changing a port restarts the service; a new UDP port also
  rewrites the rpt.conf line.
- **Watchdog.** systemd's watchdog ping needs both the web server and the audio
  pump to be alive.
- Config in `/etc/asl_dvs/nodelisten.conf`. `--uninstall` removes the rpt.conf
  line (with a backup) and keeps the config and backups.
- Not yet in the installer, the uninstaller or instmon's tool list; install it
  with its own `--install` or from instmon's library.

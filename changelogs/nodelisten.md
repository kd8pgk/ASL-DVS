# nodelisten changelog

Current file: `nodelisten_v0_3_0_20261019.py`. Newest entries first.

## 0.3.0 (2026-10-19)

Node Listen becomes a phone page for the LAN: listen, push-to-talk and a short
favorites list, with no app to install.

- **Four tabs** (bottom bar): **Status** (node, receive and transmit lights,
  feed, links from `rpt lstats`), **Connect**, **Listen** (with push-to-talk)
  and **Setup** (the receive hook, the transmit node, favorites, settings, log).
  The header links to the Node Controller Dashboard (its port from
  `/etc/asl_dvs/asl_dvs.conf`, default 8989). Logged out, only Listen shows,
  and only with **Listen without logging in** on.
- **HTTPS, on by default.** Browsers only allow the microphone on a secure page.
  Node Listen makes a self-signed certificate on first start
  (`/etc/asl_dvs/nodelisten_tls/`, names and LAN addresses in it) and serves
  HTTPS on the same port; a plain `http://` request is sent a 301 to
  `https://`, so old links (the Dashboard's Listen button) still work. The
  browser shows a warning to accept. The session cookie gets `Secure`. An
  **HTTPS** setting turns it off (push-to-talk then can't work); changing it
  restarts the service.
- **Push-to-talk** to private node **1921**: hold the big button (or Space /
  Enter on it). The page records the microphone with echo cancelling, cuts it
  to 8 kHz 16-bit in the browser (AudioWorklet, ScriptProcessor fallback) and
  sends 20 ms frames over a WebSocket (`/api/talk`, login and same-origin
  required). Node Listen sends them as USRP to `127.0.0.1:32018` with keyup set,
  three keyup=0 frames on release, and drains what Asterisk sends back on
  34018. Listen audio is muted while you talk.
  - Unkeys on release, at the **time-out** (`tot_sec`, 30-600 s, default 120),
    1 s after frames stop (**dead-man**), or when the page closes, loses
    focus or is hidden.
  - **Busy lockout** (on by default): PTT is refused while the node is passing
    audio. One talker at a time.
  - Every keyup and unkey is logged with the address and length.
- **Transmit node card** (Setup): **Add node 1921** appends a `[1921]` stanza
  (the main node's template, `rxchannel = USRP/127.0.0.1:34018:32018`,
  `duplex = 0`, no hang time, no telemetry, no courtesy tone) and
  `1921 = radio@127.0.0.1/1921,NONE` under `[nodes]`, after backing rpt.conf
  up. It refuses if rpt.conf already has a `[1921]` it didn't add. **Remove**
  takes both out. A **link keeper** checks `rpt lstats` every 20 s and issues
  `rpt cmd <main> ilink 3 1921` when 1921 isn't linked.
- **Favorites, up to 10** (Setup): network (ASL or EchoLink), number and name,
  saved to `/etc/asl_dvs/nodelisten_favorites.json`. A list offers the
  Dashboard's ASL and EchoLink favorites (bridge nodes left out). Node 1921 and
  duplicates are refused. The **Connect** tab has them in a drop-down;
  Connect runs `rpt cmd <main> ilink 3 <node>` (EchoLink as `3` + six digits),
  Disconnect runs `ilink 1` for each linked favorite only, so the transmit node,
  bridges and links made elsewhere stay.
- The main node is the one picked for the receive hook, else the Dashboard's
  `asl_node`.
- The systemd watchdog also needs the transmit pacer alive, and its health
  check speaks HTTPS when HTTPS is on.
- `--uninstall` removes node 1921 as well as the `outstreamcmd` line.
- Setup-page messages with long paths wrap instead of widening the page on a
  phone.

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

# nodelisten changelog

Current file: `nodelisten_v0_4_3_20261019.py`. Newest entries first.

## 0.4.3 (2026-10-19)

- **An update keeps node 1921 and the audio feed.** InstMon's Full Update runs
  the installed version's `--uninstall` and then the new file's `--install`.
  The uninstall removes the transmit node 1921 and the `outstreamcmd` line from
  rpt.conf, and the install used to leave them out, so Setup asked to add node
  1921 again. Now `--uninstall` notes what it removed in
  `/etc/asl_dvs/nodelisten_restore.json` (mode 0600), and an `--install` within
  30 minutes puts those lines back and deletes the note; an older note is
  ignored and deleted. A plain uninstall still leaves rpt.conf clean.
- The note is written by 0.4.3 and later, so updating from 0.4.2 or older
  still drops node 1921 that one time; press **Add node 1921** on Setup after
  that update, or install 0.4.3 from InstMon's Library card instead.

## 0.4.2 (2026-10-19)

- **Node Controller** (header) drops the arrow icon and goes back to the
  Dashboard's tab instead of opening a new one each time: it switches to the
  open Dashboard tab without reloading it, or opens the Dashboard once in a new
  tab when there isn't one. A Dashboard older than 9.3.90-pi02w doesn't name
  its tab, so the first press opens one new Dashboard tab and later presses
  reuse it.
- The page names its own tab, so the Dashboard's **Listen** button (9.3.90-pi02w
  or later) finds it even when Node Listen was opened from a bookmark.

## 0.4.1 (2026-10-19)

- **Cleaner TX audio.** The page now resamples the mic to 8 kHz with a filtered
  (windowed-sinc) resampler, so sounds above 3.4 kHz no longer fold back as
  hiss and whine; it was a plain average before.
- **TX buffer** on the Tune card: 60, 120 (default), 200 or 300 ms of mic audio
  are held before the node is fed (was a fixed 60 ms). If the phone's audio
  stalls and the buffer runs dry, Node Listen sends silence and waits for the
  buffer to refill instead of feeding the node a few ms at a time. The card shows
  **TX gaps** (live while talking, else the last transmission), and the log
  counts them at unkey. Raise the buffer if gaps show up.
- **This device's microphone** (Tune card, kept in each browser): **Automatic
  gain**, **Noise suppression**, **Echo cancellation** (now off by default; the
  listen audio is muted while you talk), **Voice filter** (cuts rumble below
  about 250 Hz) and **Mic gain** (-12 to +24 dB, applied in the page; browsers
  can't set the phone's own mic volume). With automatic gain on the browser
  undoes most of the mic gain, so turn it off for a fixed level.
- **Test mic**: records 4 s, plays back what the node would get, and rates the
  peak (too hot, good, quiet). Nothing is sent to the node.

## 0.4.0 (2026-10-19)

- **Tune card** (Setup), opt in with **Adjust audio levels here**: **Mic to node
  (TX)** and **Node to phone (RX)** gains, -12 to +12 dB, and the **Listen
  buffer** (0.15, 0.25, 0.5 or 1 s). Off, audio passes through unchanged and the
  buffer is 0.25 s. Gains apply at once, with clipping; the card shows the TX
  peak (live while talking, else the last transmission) and the RX level. When
  SysMon answers on port 9999 the card points to it for the node's own levels
  (radio, DVSwitch and USRP gains).
- **Connect from** (Connect tab): pick the local node that makes the link, from
  rpt.conf's numbered nodes (not 1921, not the Dashboard's bridge nodes); the
  main node is the default. Shown when there is a choice.
- **Connects go through Node Controller when it runs.** When the connecting node
  is the Dashboard's node and the Dashboard (pi02w 9.3.89 or later) answers, Node
  Listen sends the connect or disconnect to the Dashboard's local API
  (`POST /api/local/action` on 127.0.0.1, with the key in
  `/etc/asl_dvs/local_api.key`, made by whichever starts first, mode 0600). The
  Dashboard switches to its ASL or Echo tab (dropping any digital bridge, so the
  phone can't bridge DMR to AllStar), connects as if you had pressed Connect, and
  counts the link as its own, so its permanent-link "Bridging risk" banner and
  extra-link clean-up leave it alone. A refusal from the Dashboard is shown as
  is. Without the Dashboard, or with an older one, Node Listen connects directly
  as before.
- The header's **Node Controller** link is hidden when the Dashboard isn't
  running.
- The busy lockout's grace after Node Listen's own unkey is 1 s (was 2 s), so
  quick re-presses can't key over someone who answers straight away.

## 0.3.1 (2026-10-19)

Fixes from an audit of 0.3.0.

- **`[nodes]` line follows the IAX port.** 0.3.0 always wrote
  `1921 = radio@127.0.0.1/1921,NONE`, so on a node whose `bindport` in
  `/etc/asterisk/iax.conf` isn't 4569 (44helper's Nodes tab recommends
  4560-4580 for several nodes on one network) node 1921 could never link. Node
  Listen now reads `bindport` from `[general]` (following `#include` /
  `#tryinclude`, two levels deep) and writes `radio@127.0.0.1:<port>/1921`
  when it isn't 4569, the same rule as the Dashboard's Phone nodes. The
  transmit card says when the line is missing or has the wrong port, and **Add
  node 1921** fixes it (with a backup). Remove takes out the line whatever its
  port.
- **PTT is refused while 1921 isn't linked** ("not linked yet": Asterisk not
  restarted since it was added, or the link keeper hasn't relinked it), instead
  of appearing to transmit into nothing.
- **No false "busy" right after your own transmission.** The node's audio comes
  back on the listen feed about half a second late, so pressing PTT again
  straight after letting go was refused as busy. The busy lockout now ignores
  the 2 s after Node Listen's own unkey.
- **First press with the microphone prompt.** The browser's permission prompt
  takes focus, which released PTT at once on the very first press. Losing focus
  no longer releases PTT while the microphone is being opened.

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
- Node 1921 is linked only while Node Listen runs: on stop (systemd's SIGTERM)
  Node Listen unlinks it (`ilink 1 1921`), and **Remove** unlinks it before
  taking it out of rpt.conf. The Dashboard (pi02w 9.3.87) leaves it alone while
  Node Listen runs and unlinks it if Node Listen isn't running.
- After you let go of PTT the listen audio stays muted for 1 s, so the delayed
  tail of your own transmission doesn't play back.
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

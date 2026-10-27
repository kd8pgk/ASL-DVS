# Node Talker Mobile changelog

Current version: `0.6.0`. The app is in `android/`; its version is `appVersion` in `android/app/build.gradle.kts`. Newest entries first.

## 0.6.0 (2026-10-27)

- **Phase 3 of the native tabs: the Connect tab is the app's own.** On the
  same Node Talker versions and conditions as the Listen tab (0.9.35, 0.9.39,
  0.9.40, logged in), the Connect tab is drawn by the app. Setup is still the
  node's page, and any other Node Talker version keeps the page's Connect tab.
- **Same screen as the page:** the Favorites card (picker, mode and number,
  label, Connect/Disconnect), the Tune card (mode, DMR network, D-STAR and
  M17 module, find box, pick list, LH, Save, Connect/Disconnect), the
  "Tuned:" line, and Disconnect All with its confirmation and progress.
- **Same rules as the page:** the pick lists load and search through the
  node's own `/api/tune-list` and `/api/tune-search` (cached for 5 minutes,
  search after 300 ms for AllStar and EchoLink); the typed-number checks, the
  hints, the button states and the "add the network to Node Controller" question
  are the page's; connecting hops to the Listen tab and shows the result there
  for 8 seconds, and returns to Connect if it fails.
- **Tune sizes** (Text and Height on the Setup tab) apply to the Tune card.
- **One status poll for both tabs** (every 1.5 s while one is showing).
- The router now handles several native tabs; the page is parked on Setup
  while a native tab is showing.

## 0.5.0 (2026-10-26)

- **Phase 2 of the native tabs: the Listen tab is the app's own.** When the
  node runs Node Talker 0.9.35, 0.9.39 or 0.9.40 (the versions the tab was
  checked against), the audio mode is App audio and you are logged in, the
  Listen tab is drawn by the app instead of the page. On any other Node Talker
  version, or with Page audio, it stays the node's page, as before. Connect and
  Setup are still the page.
- **Same screen as the page:** Connect/Disconnect feed and a volume slider; the
  status row (node, feed, RX, TX, listeners); the spectrum with the page's
  colors and scale, the level meter with its peak hold and clip line, and the
  meter bar; Hold to talk (or Tap to talk) with the wait after receive and its
  countdown, the busy and time-out messages, and the guard timer with its
  10 s warning beeps; the link line under the button; and **Mark kerchunk**
  beside push-to-talk while a kerchunk test runs.
- **It reads your Setup choices from the page:** hold or tap, the guard time,
  the wait after receive, mic gain, Spectrum on/off, Auto start, and the
  Listen tab's Text and Height sizes. Change them on the Setup tab and they
  apply when you come back to Listen.
- **The spectrum works in the app.** The page cannot draw one while the app
  plays the audio (its analyser is not running), so the page's Listen tab shows
  an empty box there. The native tab computes it from the audio it plays.
- **Volume goes to 200 %.** Above 100 % the app amplifies the audio (the page's
  volume slider stopped at 100 % in the app).
- **Text size** scales all the text on the tab. (On the page, the Listen Text
  slider changes almost nothing, because most of the tab's text has a fixed
  size.)
- **Vibration** on key-up, un-key, the guard warning and a refused press, like
  the page in a browser (adds the Vibrate permission).
- **No more crash when the page's display process dies.** If the phone runs low
  on memory and Android stops the page's WebView, the app shows "The page
  stopped" with Retry instead of closing.
- **The page and the app are checked against each other.** `ci/check_repo.py`
  now also fails when the app's spectrum scale and palette stops, or its
  push-to-talk timings (wait after receive, tap guard, warning time) and guard
  choices, differ from the page's.
- **Not on the native tab yet:** the audio-check badge and the headset-button
  setting. They stay on the page (Page audio, or another Node Talker version).

## 0.4.0 (2026-10-26)

- **Phase 1 of the native tabs: the foundation.** Nothing changes on the
  Connect, Listen and Setup tabs yet; they are still the node's own page. The
  app can now read the node itself, which the native Listen and Connect tabs
  in the next versions build on.
- **A tab bar of the app's own** (Connect, Listen, Setup) replaces the page's
  bottom bar inside the app. It follows the page: tapping a tab switches the
  page's tab, and it stays hidden on the login screen. The page and the other
  tools are unchanged, so any node still works.
- **Node client** (`NodeApi`): reads `/api/health`, `/api/whoami` and
  `/api/status` and posts to the node's other endpoints with the node's pinned
  certificate. It uses the login the page already made, so no password is
  stored in the app, and it sends the `X-Requested-With` header the node
  requires on every POST.
- **Version check** (`Compat`): when a node's page has loaded, the app asks
  which Node Talker version it runs, and the node list shows it under the
  address. A native tab will be used only when the node runs a version the app
  was checked against; on any other version the tab stays the node's page, so a
  native screen is never out of date.
- **Colors match the page.** `colors.xml` holds every color of the page's
  `:root` block, and `ci/check_repo.py` now fails when they differ.
- The status poll starts with the first native tab (0.5.0), the first screen
  that needs it.

## 0.3.1 (2026-10-21)

- **Renamed Node Talker Mobile** (was Node Talker for Android): the name
  under the icon, on the node list and on the releases. The package, the
  release tags (`android-vX.Y.Z`) and the APK file name stay the same.
- **Updates install over the old app.** Test builds were signed with a debug
  key made fresh on each build machine, so Android refused to install one
  over another ("app not installed" / package conflict). Every build is now
  signed with the same debug key, kept in `android/app/debug.keystore`
  (password `android`, as Android's own debug key). Uninstall once to get
  0.3.1; later builds install over it and keep your nodes and settings.

## 0.3.0 (2026-10-21)

- **Phase 3: transmit in the app** (needs Node Talker 0.6.11; app audio).
  The page's push-to-talk button keys through the app, which opens the talk
  channel itself and sends the phone's microphone (8 kHz), so:
  - push-to-talk works on a plain `http://` node too (a browser needs HTTPS
    for the microphone);
  - a tap-to-talk transmission carries on with the screen locked.
- It always unkeys on release, when the page's guard timer runs out (the
  app keeps that time itself), when a phone call or other audio takes
  over, and when the talk channel drops; the node's own time-out and busy
  lock still apply.
- Receive is muted while talking and comes back 1 s after.
- Notification shows "Ready to talk" and "Transmitting".
- **Audio settings:** "Phone's echo and noise filter" for the microphone (on
  by default; turn it off if the audio sounds choppy or muffled).
- Asks for the microphone the first time push-to-talk is used.
- **Background play everywhere:** another app playing sound (music, video)
  no longer pauses receive; only a phone call (or a voice assistant)
  does. Hold-to-talk unkeys when the screen goes off or you switch apps
  (the button can't be held); tap-to-talk keeps going.
- **Battery** button on the node list: opens Android's setting to let Node
  Talker run in the background, with a warning while battery saver may stop
  it. Page audio's setting now says it stops when the screen goes off.

## 0.2.1 (2026-10-21)

- **Fix:** a node saved as plain HTTP whose Node Talker uses HTTPS opened in
  the phone's browser (Node Talker sends plain HTTP on to HTTPS, and the app
  took that for an outside link). The app now follows it, switches the node
  to HTTPS and saves that; the certificate question follows once.

## 0.2.0 (2026-10-21)

- **Phase 2: receive in the background ("app audio", the default).** With
  Node Talker 0.6.10 or later, Listen on the page plays through the app,
  which keeps playing with the screen locked or the app in the background.
  - A notification shows the node and its state (connecting, listening,
    reconnecting, paused) with **Stop**; tapping it opens the node.
  - Reconnects by itself (1 s, then up to every 10 s) if the stream drops.
  - Pauses for a phone call or other audio and carries on after.
  - Keeps Wi-Fi awake while listening.
  - Push-to-talk on the page mutes it; the page's volume slider sets it.
- **Audio settings** (node list): app audio or page audio (as in a browser,
  for when app audio sounds bad); receive buffer 100–1000 ms (default
  300 ms; raise it if audio breaks up); speaker (media volume) or earpiece
  (call volume). Changes apply at once to a node that is playing.
- Android 13+ asks once to show notifications.
- An older Node Talker (without the page side) keeps page audio.

## 0.1.0 (2026-10-21)

- **First build (phase 1: the shell).** Sideload only, signed with a debug key.
- **Nodes:** a list of saved Node Talker addresses (name, address, port,
  HTTPS). Tap to open; press and hold to edit, delete or forget the
  certificate. A full URL can be pasted in the address field.
- **The page:** a node opens its Node Talker page and nothing else. Links to
  any other address (LH, Node Controller, InstMon) open in the phone's
  browser. The app adds `NodeTalkerApp/<version>` to the browser name it
  sends, so a future Node Talker can tell it is inside the app.
- **Certificate:** a node on HTTPS with Node Talker's own certificate asks
  once, showing its SHA-256 fingerprint and the command to check it on the
  Pi. The app remembers it, opens the node without warnings after that, and
  stops with a warning if the certificate ever changes.
- **Plain HTTP** to a node works (Android blocks it unless the app allows it).
- **Microphone** for the page (page audio, HTTPS only, as in a browser):
  Android asks once for the permission.
- **Favorites file:** Download saves through Android's file picker; Upload
  picks a file.
- **Keep the screen on** while a node is open (on the node list).
- Android 8.0 and newer; targets Android 16.

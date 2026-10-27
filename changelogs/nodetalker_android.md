# Node Talker Mobile changelog

Current version: `0.4.0`. The app is in `android/`; its version is `appVersion` in `android/app/build.gradle.kts`. Newest entries first.

## 0.4.0 (2026-10-27)

- **The splash welcomes the node's owner.** It opens with "Welcome to the
  *callsign* Node Talker Mobile" above the icon, and "Licensed under CC BY-NC
  4.0" below it. Tapping the license line opens the license page. With no
  callsign set, the line reads "Welcome to Node Talker Mobile".
- **A Callsign button on the node list.** It sets the callsign shown on the
  splash. It is saved on the device, is up to 16 letters, digits, / or -, and
  can be left empty.
- **The name stays on one line.** Every "Node Talker Mobile" in the app's
  text is joined with non-breaking spaces, so it never wraps.

## 0.3.4 (2026-10-27)

- **The node list now names the repository's license, CC BY-NC 4.0**
  (Attribution-NonCommercial), the same as the `LICENSE` file. 0.3.3 said
  CC BY 4.0 by mistake. Tapping it opens the CC BY-NC 4.0 license.

## 0.3.3 (2026-10-27)

- **Splash screen:** the app opens on its icon, centered on the app's dark
  background, for three seconds, then shows the node list. Opening the app
  from its notification goes straight to the node page, as before.
- **Credits and license on the node list:** "By KD8PGK · Built with Claude AI
  (Anthropic)" and "Licensed under CC BY 4.0" under the app version. Tap the
  license to open it on creativecommons.org.

## 0.3.2 (2026-10-27)

- **No more debug build.** The APK is now a release build, named
  `NodeTalker-0.3.2.apk` (no `-debug`), and the app is no longer debuggable.
  It is signed with the same key as 0.3.1, so it installs over it and keeps
  your nodes and settings.
- Fixes from a code audit:
  - **The page closing no longer closes the app.** If the phone ran low on
    memory or the page's display process stopped, the whole app closed; it
    now shows "The page stopped" with Retry.
  - **Opening the talk channel for another node stops the old node's
    receive cleanly**; before, it stopped but still showed as playing.
  - **The talk channel can't be left open by a race** when it is closed just
    as it finishes connecting.
  - **Stopping receive no longer closes the audio stream on the main
    thread**, which some Android versions refuse.
  - **A microphone that stops working no longer spins the CPU.**
  - **Saving a download** shows an error instead of closing the app if
    Android refuses the chosen file.

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

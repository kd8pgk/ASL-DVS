# Node Talker Mobile changelog

Current version: `0.10.12`. The app is in `android/`; its version is `appVersion` in `android/app/build.gradle.kts`. Newest entries first.

## 0.10.12 (2026-11-04)

- **Clean-up filters, for received and sent audio.** The Audio dialog has two new check boxes under "Clean-up filters", both off by default: "Received audio" (the audio the phone plays) and "Sent audio" (the phone's microphone before it goes to the node). When on, each path runs a high-pass at 150 Hz (cuts rumble), a low-pass at 3.4 kHz (cuts hiss above speech), a gentle lift around 2.5 kHz for clearer speech, and a squelch that mutes between words (opens at -40 dBFS, closes at -46 dBFS, holds for 80 ms, with short fades so words are not clipped).
- **The microphone is filtered before it is reduced to 8 kHz.** Before, a 16 kHz or 48 kHz microphone was reduced by averaging neighbouring samples, which let higher sounds fold back into the voice band. Now a low-pass at 3.4 kHz runs first, every time, whatever the microphone rate. Nothing changes in what is sent: still 8 kHz, 16-bit, mono.
- Playback and the spectrum use the filtered audio when the received-audio check box is on.
- Changing the check boxes restarts the listen feed, as the other audio settings do.
- Filtering is done on the phone; the node is unchanged. CTCSS (sub-audible tone) removal for a radio on the Pi is a separate change and is not in this version.
- 8 more unit tests for the filters (39 in all), run in CI.

## 0.10.11 (2026-11-03)

From the audit of Node Talker and Node Talker Mobile with a test server.

- **A message split over several frames is now put back together.** Before, the talk channel delivered the first part and dropped the rest. Pings that arrive between the parts are still answered. A message over 1 MB, a part with nothing to continue and a new message started before the last one ended are refused. The node never splits messages today, so nothing changes in use.
- **The app checks the node's answer to the talk channel request.** It now verifies the `Sec-WebSocket-Accept` key and refuses a node whose answer does not match, with "bad answer from the node". Every Node Talker version computes it, so nothing changes with a real node.
- **The app no longer retries every second against a node that accepts and then drops at once.** The wait between tries (listen feed 1 s, talk channel 2 s, up to 10 s) now goes back to the start only after a connection stayed up for 5 s. Before, any connection reset it, so a feed that opened and closed straight away was retried every second for ever.
- More unit tests: 31 in all (the talk channel, the node address helpers and the new wait rule), run in CI.
- Works with any Node Talker. Node Talker 0.10.10 also drops a listener that stops reading after 20 to 26 s instead of about 4.5 minutes.

## 0.10.10 (2026-11-03)

- **Unit tests.** The app now has JVM unit tests for the talk channel (`WsClient`) and the node address helpers (`Node`): the upgrade request, the refusal messages, masked frames at every length form, reading text, answering pings with pongs, close frames, and the frame-size limits. They run in CI (`testReleaseUnitTest`) before the APK is built. JUnit 4 is a test-only dependency; the APK does not include it.
- **Talk channel uses `java.util.Base64`** for the WebSocket key instead of `android.util.Base64`. The bytes sent are the same; the change lets the tests run on the JVM.
- **Known gap, found by the tests:** a text message split over continuation frames is not put back together (the first part is delivered and the rest is dropped). The node never splits messages, so nothing is affected today. Kept as an ignored test until it is fixed.
- No change in what the app does for the user.

## 0.10.9 (2026-11-03)

- **The version number now follows Node Talker.** From this build the app's version is Node Talker's (0.10.9), so the two are easy to compare. Numbers may be skipped or repeated apart: an app-only change takes Node Talker's next number. The jump from 0.6.5 is deliberate. The internal version code is now `X*1000000 + Y*1000 + Z` (it was `X*10000 + Y*100 + Z`), so it keeps rising and does not collide when a patch number passes 99. 0.10.9 is 10009, above 0.6.5 (605), so it installs over the old app.
- **Spectrum when the app plays the audio.** The app computes the spectrum from the audio it is about to play (512 samples, Blackman window, 128 bars from 0 to 4 kHz, the same dB range and smoothing as the browser) and sends it to the page about 25 times a second, but only while the Listen tab is showing, Spectrum is on and audio is playing. Nothing is sent over the network.

## 0.6.5 (2026-11-03)

- **The app records why the feed connects and disconnects.** Every start and stop of listening is saved on the phone and sent to the node (Log tab and `nodetalker_listenlog.jsonl`) as user or system with a reason: the button, the notification's Stop, a headset button, page auto-start, the balancer run, Bluetooth connecting or leaving, a changed sound setting, login rejected, or the service destroyed by Android. Details for system events: screen, app in front, Doze, battery saver, battery optimisation, standby bucket, network.
- **If Android kills the app while it was listening**, the next launch notices (it saved "listening" and the app never said stop) and records "process killed" with Android's own exit reason (for example low memory or excessive resource use) on Android 11 and later.
- **Light on a slow link.** A few hundred bytes per event, only when one happens. Events wait in the phone (up to 200) until the node can be reached.
- Needs Node Talker 0.10.8 on the node; an older node ignores the events.

## 0.6.4 (2026-11-03)

- **The receive-health report now says what the phone's connection was doing**, to tell a phone problem from the Pi's or the internet. It adds: Wi-Fi or mobile data, Wi-Fi signal, frequency and slowest link speed, network changes, battery saver, idle mode, VPN and metered; and for the listen stream: reconnects with the reason (timeout, connect, closed, http), time to first audio, and the longest time audio stopped arriving.
- **Light on a slow link.** Nothing extra is sent: the same small report goes out every 30 seconds only when something happened, plus one short report every 2.5 minutes when all is quiet (about 250 bytes). The phone's signal is read locally every 5 seconds. No probing and no new requests.
- Needs two new permissions without any prompt: network state and Wi-Fi state. No location permission; the Wi-Fi name is not read.
- Nodes older than Node Talker 0.10.7 ignore the new values.

## 0.6.3 (2026-11-02)

- **Receive health can tell the phone's connection from the phone itself.** The report the app sends to the node every 30 seconds now says it comes from the Android app, and splits its underruns in two: those where the audio ran out (the connection) and those where the phone's player fell behind while audio was waiting (the phone itself). It also reports the longest time playback was interrupted. The listen stream is marked as the app's, so the node can see how much audio was waiting to be sent to the phone.
- Nodes older than Node Talker 0.10.3 ignore the extra values and show the report as before.

## 0.6.2 (2026-11-02)

- **Receive health "Phone / browser" row now fills on the phone.** Listen plays audio inside the app, so the node page had nothing to count and the row stayed empty. The app now counts its own underruns, queue resets and silence while it plays, and reports them to the node every 30 seconds. Counting starts 3 seconds after play begins and pauses while muted or when another app holds the audio. Nodes older than Node Talker 0.10.0 have no such row; the app stops reporting to them.

## 0.6.1 (2026-10-28)

- **Bluetooth settings on the Bluetooth card.** Three settings, all off by default, so nothing changes until you turn one on:
  - **Start Listen when a Bluetooth device connects.** Starts Listen on the node you used last.
  - **Stop Listen when the Bluetooth device disconnects.** Listen stops when no Bluetooth output is left.
  - **Start Listen again when the device returns, if a disconnect stopped it.** Only available with the stop setting on.

  These work while the app is open or Listen runs. Android may refuse to start Listen from the background; if it does, tap Listen on the node page. The settings need no Bluetooth permission.

## 0.6.0 (2026-10-28)

- **Bluetooth audio card (read only).** The node list has a Bluetooth button that opens Bluetooth audio. It shows, as Android reports them while the app is open:
  - the Bluetooth audio device and its profile (call headset, music, or other);
  - whether a Bluetooth microphone is connected;
  - the output Node Talker uses (Bluetooth, wired headset, earpiece or phone speaker);
  - the last connect or disconnect, with its time, from the moment the app opened;
  - the media and call volumes, each as a step of its maximum;
  - a note that headset buttons are ignored while Listen or Talk runs.

  The card updates while it is open. Nothing in it needs a Bluetooth permission; the app's permissions are unchanged.

## 0.5.3 (2026-10-28)

- **Node Talker holds the phone's media session while it runs.** Android sends the resume from a Bluetooth connection to the app that holds the media session, so another player (such as VLC) no longer starts its last podcast when a speaker connects. Node Talker ignores play, pause and stop from that session, so headset buttons do nothing while the app runs. The session lasts while Listen or Talk runs; once the app has stopped, Android's resume can reach other players again.

## 0.5.2 (2026-10-28)

- **Listening resumes when another app lets go of the audio.** If another app (a Bluetooth app, navigation, a music app) held the audio when Listen started, or took it while listening, Node Talker stayed silent until you tapped Listen again. It now asks Android to wait for the audio and starts again on its own once the other app lets go.

## 0.5.1 (2026-10-28)

- **Speaker or earpiece is set on the node page.** The choice moved from the app's Audio settings to the Setup card's Headset / audio output card, as "Sound through (app audio)". The app's Audio settings no longer have the Output choice. Changing it there restarts listening at once.
- **The page can read the app's settings.** The app reports its output, receive buffer and microphone filter, so the Phone card shows them.

## 0.5.0 (2026-10-28)

- **Louder listening, three ways.** All three are in the audio settings (Audio settings on the node list):
  - **Output hints.** "Speaker / media volume" is marked louder, and "Earpiece / call volume" quieter. Keep the phone's media volume up for speaker listening.
  - **The page's volume slider works above 100 % in the app.** The slider runs to 200 %. Before, the app stopped at 100 %, so the top half did nothing. Above 100 % now adds up to +6 dB (200 % is +6 dB, the same as in a browser).
  - **Extra loudness (new setting, off by default).** Adds 0 to 12 dB in 1 dB steps, applied with the platform's `LoudnessEnhancer` on the playback session. It works in both speaker and earpiece mode. The slider's extra and this setting add together, capped at 18 dB. Saving the settings restarts listening so the new value applies at once.

## 0.4.0 (2026-10-27)

- **The splash welcomes KD8PGK.** It opens with "Welcome to the KD8PGK Node
  Talker Mobile" above the icon, and "Licensed under CC BY-NC 4.0" below it.
  Tapping the license line opens the license page.
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

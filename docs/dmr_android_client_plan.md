# DMR Android client: reference plan

Status: PAUSED. No code written. Reference only.

## 1. Fact-check of the original plan

| Claim | Verdict | Notes |
|---|---|---|
| Kotlin, ForegroundService, UDP socket | Correct | Standard design for keeping a socket alive in the background. |
| 8 kHz, 20 ms frames | Correct, with one error | 20 ms at 8 kHz is 160 samples = 320 bytes (16-bit mono). The original "640 bytes" is 16-bit stereo. |
| Port 62031 (MMDVM Host) vs 62030 (older variant) | Unverified | Sources disagree. The BrandMeister wiki gives 62030 as the default; 62031 is common in configs. The split by variant was not confirmed. |
| Login is a "CONFIG packet" that gets an "ACK" | Incomplete | Homebrew login is RPTL (send repeater ID), then master sends a random salt, then RPTK (SHA-256 of salt plus password), then RPTC (config, callsign, etc.), then periodic ping/pong. |
| Repeater ID = DMR ID + ESSID | Correct in concept | 7-digit DMR ID plus a 2-digit suffix = 9 digits. The suffix is not a separate field. |
| BrandMeister forbids software clients impersonating Homebrew/MMDVM | Direction likely right, quote unverified | Reported as: Homebrew/MMDVM reserved for hotspots and repeaters with an onboard RF module. Exact wording not retrieved. Treat as a blocker until BrandMeister confirms in writing. |
| 9990 is a Parrot | Correct, but dated | BrandMeister wiki: place a private call to 9990. Alternative is MCC+997 (e.g., 234997 for the UK). One page says 9990 will be retired. Confirm the current ID before testing. |
| md380 firmware is a safe, open vocoder basis | Not supported | Firmware is Tytera's proprietary code with unclear licence. Forum threads raise legal concerns about the encoder. |
| DroidStar and VoxDMR are prior art | DroidStar confirmed | Vocoder is a user-supplied plugin; user is responsible for licensing. VoxDMR not verified. |

Gaps in the original plan:
- DMR burst and superframe framing is the hard part and was glossed over.
- Android 14+ needs the microphone foreground service type; Android 13+ needs POST_NOTIFICATIONS.
- Check the current status of Jetpack Security EncryptedSharedPreferences before depending on it.

## 2. DMR framing (four layers)

1. Audio to AMBE frames. 8 kHz PCM, 160 samples per 20 ms, encoded to one AMBE+2 frame (72 bits, 3600 bit/s; about 49 speech bits + 23 FEC). Three frames = 60 ms = one voice superframe.
2. Superframe to bursts (air interface). TDMA: each 30 ms frame has two timeslots; each slot carries one 264-bit burst. A voice superframe spans six bursts. The first burst carries the voice sync pattern; others carry embedded signalling interleaved with voice bits. A call starts with a voice header (source, destination, call type) and ends with a terminator. Exact bit split must be checked against ETSI TS 102 361 before coding.
3. Bursts to network packet (Homebrew DMRD, 55 bytes): 4-byte magic "DMRD"; sequence number; source DMR ID (3 bytes); destination ID = talkgroup or private-call number (3 bytes); repeater ID = DMR ID + ESSID (4 bytes); flags byte (slot, call type, frame type); stream ID constant for the transmission; 33-byte DMR burst. Verify offsets and sizes against the spec.
4. Phone side. The app does audio, vocoding, and burst assembly. Receive runs in reverse: parse DMRD, extract bursts, pull out AMBE frames, decode to PCM, play through a jitter buffer.

Most of the work is burst/superframe logic and the vocoder, not the UDP socket.

## 3. Vocoder (gating decision)

- DMR requires AMBE+2. No substitute codec works on DMR (Codec 2 is open but not DMR-compatible).
- Option A: commercial AMBE+2 software licence from DVSI. Clean route; costs money; quote must cover an Android/ARM app that is distributed.
- Option B: md380 firmware or community encoders. Not recommended (proprietary firmware, unclear licence, encoder legal concerns).
- Option C: hardware AMBE chip over USB. Not standalone.
- Recommendation: get a DVSI quote first. If the licence is not viable, the project stops here regardless of network.

## 4. BrandMeister (network decision)

- Reported position: Homebrew/MMDVM reserved for hotspots and repeaters with an RF radio; software-only clients copying those protocols are not allowed. Get exact wording in writing.
- Options:
  1. Ask BrandMeister whether a software client may connect and which protocol they would approve.
  2. Target a network that permits software clients; check each network's policy first.
  3. Put the protocol layer behind an interface so the network can change without rewriting audio or burst code.
- Recommendation: contact BrandMeister first (replies are slow). Build network-independent parts (burst/superframe logic, audio pipeline) only after the vocoder decision.

## 5. Staged plan (for when the project resumes)

- Stage 0: Policy and licence gate (no code). Written network permission; vocoder licence decision.
- Stage 1: Protocol spike against a private LAN test server. Login (RPTL/RPTK/RPTC) and ping/pong. Exit: stable login for one hour.
- Stage 2: DMRD and burst codec, no audio. Exit: captured bursts decode and re-encode byte-for-byte.
- Stage 3: Vocoder behind an interface (encode/decode of 160-sample frames). Exit: WAV round trip with measured quality.
- Stage 4: Audio pipeline without network (AudioRecord/AudioTrack, 8 kHz mono, 20 ms framing, jitter buffer). Exit: five-minute local loopback with no dropouts.
- Stage 5: Foreground service (microphone type, WakeLock, notification), config screen, state machine (Disconnected, Connecting, Connected, TX, RX). Exit: survives screen-off and network switches.
- Stage 6: Integration on a permitted network (echo/Parrot with current ID, private call, talkgroup test), soak test, reconnection test.
- Stage 7: Release: Play Store policy for amateur-radio apps, vocoder licence notices, user docs.

## 6. Open decisions

1. Vocoder: request DVSI licence quote? Who pays?
2. Network: contact BrandMeister? Second network candidate?
3. Scope: new repository, separate from ASL-DVS.

Status: paused. Nothing has been written to any repository.

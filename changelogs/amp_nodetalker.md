# Node Talker for AMP changelog

Current file: `amp_nodetalker_v0_3_3_20261028.py`. Before 0.3.0 the tool was Node Listen for AMP, the file was `amp_nodelisten_v….py` and this log was `amp_nodelisten.md`. Newest entries first.

## 0.3.3.1 (2026-10-28)

- **Node Controller look.** The page uses the Node Controller colours and Readex Pro, embedded in the page like Node Controller does. Cards, the header, the tab bar and the browser theme colour match the new palette. Layout and behaviour are unchanged.

## 0.3.3 (2026-10-28)

- **The page opens on the Connect tab.** Each time Node Talker for AMP starts or the page is loaded again, it opens on Connect instead of the tab that was last open. The last tab is no longer remembered.

## 0.3.2 (2026-10-27)

- **The port opens on install and closes on uninstall.** Install checks that Node Talker for AMP's port (8993, or the port in its config) is open in the firewall (ufw or firewalld) and opens it if it is not. With no active firewall nothing changes. Uninstall removes the service first and closes the port last. The check is shared through `firewall_backend`, `open_firewall_port` and `close_firewall_port` in `shared/confio.py`, kept identical in each tool and checked by the repo check.

## 0.3.1 (2026-10-27)

- **Config files are written the same safe way in every tool.** Every write goes through one shared function (`atomic_write`, kept identical in each tool and checked by the repo check): a private temp file with a random name in the same folder, fsync, then a rename. An edited file keeps its owner and mode. A symlink at the path is replaced, not followed.

## 0.3.0 (2026-10-20)

**Node Listen for AMP is now Node Talker for AMP.** It does the same things as
before. The service, files and paths are renamed:

| | Was | Now |
|---|---|---|
| Service | `amp_nodelisten.service` | `amp_nodetalker.service` |
| Program | `/usr/local/bin/amp_nodelisten.py` | `/usr/local/bin/amp_nodetalker.py` |
| Settings | `amp_nodelisten.conf` `[amp_nodelisten]` | `amp_nodetalker.conf` `[amp_nodetalker]` |
| Data | `amp_nodelisten_favorites.json`, `_tls/`, `_backups/` | `amp_nodetalker_…` |

The page, messages and logs say Node Talker.

- **Install over Node Listen for AMP** moves the settings and data,
  including the AMP secret and the HTTPS certificate.
  - It stops the old service and keeps its unit until `amp_nodetalker` has
    started. If `amp_nodetalker` doesn't start, the old service is put back.
- **Kept working for older versions:**
  - `amp_nodetalker.service` has `Alias=amp_nodelisten.service`.
  - `/usr/local/bin/amp_nodelisten.py` and the old settings and data paths
    stay as symlinks.
  - The settings file holds the same settings under both `[amp_nodetalker]`
    and `[amp_nodelisten]`.
- **AMP's login is unchanged.** The user stays `nodelisten`, so the line
  already in AMP's login file (`nodelisten <password>`) keeps working.

## 0.2.1 (2026-10-20)

- **From Node Listen 0.4.20** (fixes from an external-interface audit).
- **Login could reject the right password** when several logins ran at once
  and the `/etc/shadow` check was used (no `pam` module). `crypt(3)` uses one
  shared buffer; the call now runs under a lock. In a test with 16 threads,
  0.2.0 rejected about half of the correct passwords. A wrong password was
  never accepted.
- **HTTPS that can't start is no longer silent.** A certificate that won't load
  is moved aside (`….bad`) and a new one is made, once. If HTTPS still can't
  start, the page is served over plain HTTP as before (internet logins stay
  blocked without HTTPS), and the login card says in red that the page is not
  encrypted and the password is sent in plain text.
- **`systemctl` calls have a timeout** (120 s) and report a missing or stuck
  `systemctl` instead of hanging or crashing the install.
- **Install keeps the previous version until the restart works.** The old
  `amp_nodelisten_v….py` is removed only after `systemctl restart` succeeds.
  The copy and the symlink use unique temporary names. A failed
  `daemon-reload` or `enable` is now reported.
- **HTTP-to-HTTPS redirect:** a request with a bad `Host` header is sent to the
  Pi's LAN address, not to `127.0.0.1`.
- The internet-login gate (20 failed internet logins in 10 minutes pauses
  internet logins) stays. It now keeps only the last 20 failures.
- Not taken from 0.4.20: the transmit sequence fix. Here, transmit goes over
  the IAX call, whose sequence numbers are already set under the call's lock.

## 0.2.0 (2026-10-20)

- **From Node Listen 0.4.18 and 0.4.19.**
- **Connect turns into Disconnect.** On the Connect tab, the Connect card's
  button reads **Disconnect** (in red) when the selected favorite is linked,
  and pressing it drops that favorite's call only. Other calls, and Node
  Listen's own link, stay up. The Links card loses the "Linked favorites" line,
  its small Disconnect button and the note under them.
- **Headset / audio output** (new Setup card), for a wired, USB-C or
  Bluetooth headset. Saved in this browser only.
  - **Audio output:** a list of outputs where the browser can switch (Chrome
    with `setSinkId`); elsewhere a note says to pick the headset in Android's
    sound settings.
  - **Microphone for push-to-talk:** Default (follows Android), or a chosen
    mic. If the chosen mic is gone, the default is used.
  - **Headset button:** Listen on / off (as before), **Push to talk**, or Off.
    Push to talk: press once to talk, press again to stop. It uses the same
    transmit as the Talk button, with the same time-out, and the button reads
    `TALKING (headset)`. Android only passes the button to the page while Node
    Listen is playing.
  - Shows which output and microphone are in use. **Show device names** asks
    for the microphone once when the browser hides the names.
- **Headset unplugged or output lost.** When Android pauses playback on its own
  (headset unplugged, Bluetooth dropped), Node Listen stops transmitting, stops
  listening and says so, where before it kept showing "playing". When the
  headset comes back within 30 minutes, listening starts again.
- After a transmission, playback is resumed straight away if the phone paused
  it, so the sound comes back to the headset.
- **Audio check** report adds the audio output, the microphone, how many times
  the headset was unplugged or the output was lost, and how many transmissions
  came from the headset button.

## 0.1.0 (2026-10-20)

- **First release.** The page, the RX cleanup (cut below 300 Hz, automatic
  level, squelch-tail gate), the microphone chain, push-to-talk, the meters,
  the spectrum, the mic test and the Audio check are Node Listen 0.4.17's.
- **The link to AMP.** Node Listen calls the AMP node over IAX2 like a private
  link: user `nodelisten` (`amp_user`) with a password made on first start
  (`amp_secret`), calling in as node 1921 (`amp_caller`). It hears everything
  the node passes, and push-to-talk goes out to the radio and every link.
  16-bit audio when AMP offers it, μ-law otherwise. It answers AMP's
  keepalives, pings AMP every 10 s, and links again (2 s, doubling up to
  30 s) when the call drops or AMP stops answering for 30 s.
- **Finds AMP by itself.** From the running `amp-server` (its `--config`,
  `--httpport`, `--httppwd` and `--iaxport`), or `amp-server.json` in a home
  directory: the node number, the IAX port, the web port and password, and
  the login file (`authFile`, AMP's default `/etc/ampersand/auth.txt`).
  Any of them can be set by hand under **AMP link, Advanced**. When more than
  one `amp-server` runs on the Pi, it takes the one whose config path (or IAX
  port) is set there, otherwise the oldest, and the card says how many run.
- **Set up for me** (Setup tab, AMP link card) writes Node Listen's line into
  AMP's login file (a backup goes to `/etc/asl_dvs/amp_nodelisten_backups/`;
  a new file is given to AMP's user) and touches `amp-server.json`, so AMP
  reloads it within a second. Nothing else of AMP's is changed.
- **Links and Connect** come from AMP's web API: the Links table is AMP's
  calls (talking, permanent or linked), Connect asks AMP to call the node and
  waits up to 15 s for it to appear (or returns AMP's own reason at once, such
  as `Call to 2002 failed: DNS error (SRV)`), and Disconnect drops only
  linked favorites. Favorites are AllStar node numbers or a direct address
  (`iax:user@192.168.1.20:4569/12345,password`); **From AMP…** copies AMP's
  own favorites.
- **The status line** shows **link** (green while linked to AMP) instead of
  feed: AMP sends audio only while something is active. Push-to-talk shows
  `Busy: <call>` while another station talks, from AMP's talker ID.
- **Login:** the password of `root`, or, when root has no password (usual on a
  plain Raspberry Pi OS), of the user that runs `amp-server`. `login_user`
  in the config file picks another account.
- **The AMP pill** in the title bar opens AMP's own web page; the Audio levels
  card links to it for the node's own levels.
- **Left out:** everything that needs Asterisk (the Receive and Transmit
  cards, `rpt.conf`, Restart Asterisk), the Node Controller and SysMon links,
  EchoLink and M17 favorites, and **Test through the node**: AMP doesn't send
  a caller's own audio back, so the round trip can't be recorded.
- Install: `sudo python3 amp_nodelisten_v0_1_0_20261020.py --install`
  (service `amp_nodelisten`, port 8993, settings in
  `/etc/asl_dvs/amp_nodelisten.conf`, mode 600 as it holds the AMP password).
  Uninstall leaves Node Listen's line in AMP's login file and says so.

# amp_nodelisten changelog

Current file: `amp_nodelisten_v0_1_0_20261020.py`. Newest entries first.

Node Listen for AMP is a fork of Node Listen (`nodelisten_v*.py`, from 0.4.17)
for a node that runs the Ampersand AMP server (`amp-server`) instead of
Asterisk. It stands alone: the other tools in this repo don't use it, and it
doesn't use them.

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

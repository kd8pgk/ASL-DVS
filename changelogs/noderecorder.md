# Node Recorder changelog

Current file: `noderecorder_v0_1_0_20261102.py`. Newest entries first.

## 0.1.0 (2026-11-02)

- **New tool, phase 1 (strip and skeleton).** Node Recorder is forked from Node Talker 0.10.1. It is receive-only and will record on a schedule; this build has no recording yet. The web page and status are on port 8995, with Connect, Record and Setup tabs.
- **Audio comes from the private node 1921.** The tool listens for the USRP audio Asterisk sends to node 1921 (UDP 34018) and reads the key-up flag from each packet. When Node Talker is running it owns the port and node, so Node Recorder listens on `127.0.0.1:9995/udp` instead, where Node Talker 0.10.1 and later forward the same packets. Node Recorder lets go of 34018 within a few seconds of Node Talker starting. There is no `outstreamcmd` line and no `--feed` hook.
- **Node 1921 is shared.** Without Node Talker, Setup adds node 1921 to rpt.conf (the same stanza Node Talker writes, with its own note line) and keeps it linked to the main node. With Node Talker it leaves the node alone. Uninstalling hands the node to Node Talker when it is installed, and removes it otherwise.
- **Kept from Node Talker:** the receive chain (300 Hz cut, auto level, gate), the Connect tab and Tune card, Disconnect All, the System, Links, Digital and Favorites cards, login and the log.
- **Removed from Node Talker:** transmit and push-to-talk, the phone patch, the tone test, the balance run, kerchunk logging, receive health, the Audio check, the Listen tab and the `outstreamcmd` feed. The Listen tab is replaced by a Record tab that shows the feed, the level and the node.
- **Files:** settings in `/etc/asl_dvs/noderecorder/noderecorder.conf`; service `noderecorder.service`; program `/usr/local/bin/noderecorder.py`.
- This is a release, not a cosmetic build.

# Node config snapshot: nodehost

A read-only copy of a ham radio node's configuration: AllStarLink 3 (Asterisk app_rpt), DVSwitch, USRP2M17, Allmon3, SvxLink, firewalld, WireGuard (44Net Connect) and the Node Controller tools. Use it to find errors and differences. Nothing on the node was changed to make it.

- Taken: 2026-10-27 12:11:06 EDT
- Made by: confgetter.sh 1.0.2
- Files copied: 104. Skipped: 94. Left out for size: 0.
- Secrets: 94 values replaced with `<redacted:xxxxxxxx>`. The same secret gets the same tag within this file only, so matching tags mean matching values.

## Installed tools

| Tool | Version |
|---|---|
| /usr/local/lib/asl_dvs/44helper/44helper_v0_0_216_20261019.py | 0.0.216 |
| /usr/local/lib/asl_dvs/nodecontrol/nodecontrol_pi02w_v9_3_95_20261027.py | 9.3.95-pi02w |
| /usr/local/bin/confgetter.sh | 1.0.2 |
| /usr/local/lib/asl_dvs/instmon/instmon_v2_79_1_20261027.py | 2.79.1 |
| /usr/local/lib/asl_dvs/nodecontrol/nodecontrol_pi02w_v9_3_95_20261027.py | 9.3.95-pi02w |
| /usr/local/lib/asl_dvs/nodetalker/nodetalker_v0_9_41_20261027.py | 0.9.41 |
| /usr/local/lib/asl_dvs/nodetalker/nodetalker_v0_9_41_20261027.py | 0.9.41 |
| /usr/local/lib/asl_dvs/sysmon/sysmon_pi02w_v6_13_78_20261027.py | 6.13.78-pi02w |
| /usr/local/lib/asl_dvs/wifimon/wifimon_v5_39_2_20261027.py | 5.39.2 |

## Manifest

| Path | Group | Size | Mode | Owner | Modified | SHA-256 | Note |
|---|---|---|---|---|---|---|---|
| /etc/asterisk/asterisk.conf | ASL3 / Asterisk | 7389 | 0644 | asterisk:asterisk | 2026-10-14 19:42 | d84789ce2773 |  |
| /etc/asterisk/dvs_phone_extensions.conf | ASL3 / Asterisk | 4917 | 0640 | root:asterisk | 2026-10-11 10:03 | e3babd18061d |  |
| /etc/asterisk/dvs_phone_pjsip.conf | ASL3 / Asterisk | 1591 | 0640 | root:asterisk | 2026-10-06 12:12 | 6422e15c6f6e |  |
| /etc/asterisk/echolink.conf | ASL3 / Asterisk | 2077 | 0644 | asterisk:asterisk | 2026-05-28 14:41 | efba786e628d |  |
| /etc/asterisk/extensions.conf | ASL3 / Asterisk | 9076 | 0644 | asterisk:asterisk | 2026-10-14 19:42 | ffc0cc10ad09 |  |
| /etc/asterisk/iax.conf | ASL3 / Asterisk | 5345 | 0644 | asterisk:asterisk | 2026-10-18 07:08 | becd76ffe4e4 |  |
| /etc/asterisk/logger.conf | ASL3 / Asterisk | 426 | 0644 | asterisk:asterisk | 2026-05-28 14:41 | e081ef3fa671 |  |
| /etc/asterisk/manager.conf | ASL3 / Asterisk | 475 | 0644 | asterisk:asterisk | 2026-07-12 13:53 | a16cbd520a0d |  |
| /etc/asterisk/modules.conf | ASL3 / Asterisk | 12736 | 0644 | asterisk:asterisk | 2026-10-14 19:42 | a15557fbdec7 |  |
| /etc/asterisk/pjsip.conf | ASL3 / Asterisk | 91193 | 0644 | asterisk:asterisk | 2026-10-02 11:38 | 330bbfff8b9d |  |
| /etc/asterisk/rpt.conf | ASL3 / Asterisk | 37914 | 0644 | asterisk:asterisk | 2026-10-23 03:47 | 052839fe2572 |  |
| /etc/asterisk/rpt_http_registrations.conf | ASL3 / Asterisk | 126 | 0644 | asterisk:asterisk | 2026-10-11 08:55 | 6c47d3e6fcca |  |
| /etc/asterisk/savenode.conf | ASL3 / Asterisk | 76 | 0644 | asterisk:asterisk | 2026-10-11 08:55 | 8fb594903e9c |  |
| /etc/asterisk/simpleusb.conf | ASL3 / Asterisk | 8987 | 0644 | asterisk:asterisk | 2026-10-11 08:55 | 2ef62200997c |  |
| /etc/asterisk/usbradio.conf | ASL3 / Asterisk | 12810 | 0644 | asterisk:asterisk | 2026-10-11 08:55 | 487b96bb4445 |  |
| /etc/asterisk/voter.conf | ASL3 / Asterisk | 5256 | 0644 | asterisk:asterisk | 2026-10-11 08:55 | 306b643f26a7 |  |
| /etc/asterisk/custom/README.md | ASL3 / Asterisk | 6608 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | b68b28e06134 |  |
| /etc/asterisk/custom/iax/iaxclient-users.conf | ASL3 / Asterisk | 1856 | 0644 | asterisk:asterisk | 2026-05-28 14:41 | f5384e67383b |  |
| /etc/asterisk/custom/iax/iaxrpt-users.conf | ASL3 / Asterisk | 2127 | 0644 | asterisk:asterisk | 2026-05-28 14:41 | 6bb125ba71db |  |
| /etc/asterisk/custom/rpt/AIOC.conf | ASL3 / Asterisk | 283 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | cf64695e3ec1 |  |
| /etc/asterisk/custom/rpt/AllScan-UCI.conf | ASL3 / Asterisk | 1049 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 8153cc5e9ea5 |  |
| /etc/asterisk/custom/rpt/HotSpotRadios.conf | ASL3 / Asterisk | 894 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 378717d58240 |  |
| /etc/asterisk/custom/rpt/SHARI.conf | ASL3 / Asterisk | 685 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 5a37af9c5883 |  |
| /etc/asterisk/custom/rpt/audio-archiving.conf | ASL3 / Asterisk | 324 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 3f45b2f24bf7 |  |
| /etc/asterisk/custom/rpt/hotspot-wait-times.conf | ASL3 / Asterisk | 299 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 97c69d382048 |  |
| /etc/asterisk/custom/rpt/keyed-gpio4.conf | ASL3 / Asterisk | 341 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 4d4d1dc7dbd5 |  |
| /etc/asterisk/custom/rpt/keyed-gpio8.conf | ASL3 / Asterisk | 341 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | cb6cf007dbd9 |  |
| /etc/asterisk/custom/simpleusb/AllScan-UCI.conf | ASL3 / Asterisk | 705 | 0644 | asterisk:asterisk | 2026-08-23 08:33 | 2f0e5cb802b9 |  |
| /etc/asterisk/custom/simpleusb/HotSpotRadios.conf | ASL3 / Asterisk | 1278 | 0644 | asterisk:asterisk | 2026-08-23 08:33 | 578d69308583 |  |
| /etc/asterisk/custom/simpleusb/SHARI.conf | ASL3 / Asterisk | 1038 | 0644 | asterisk:asterisk | 2026-08-23 08:33 | 4bbac46bf345 |  |
| /etc/asterisk/custom/simpleusb/clip-led-gpio1.conf | ASL3 / Asterisk | 783 | 0644 | asterisk:asterisk | 2026-08-23 08:33 | 7460e9b96331 |  |
| /etc/asterisk/custom/usbradio/AIOC.conf | ASL3 / Asterisk | 552 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | 66fe5e27ce29 |  |
| /etc/asterisk/custom/usbradio/clip-led-gpio1.conf | ASL3 / Asterisk | 575 | 0644 | asterisk:asterisk | 2026-03-07 20:03 | c9d3b456dff9 |  |
| /opt/Analog_Bridge/Analog_Bridge.ini | DVSwitch | 5211 | 0644 | root:root | 2026-10-12 18:48 | b798d9adb714 |  |
| /opt/MMDVM_Bridge/DVSwitch.ini | DVSwitch | 4997 | 0644 | root:root | 2026-07-20 17:49 | f554e9b00275 |  |
| /opt/MMDVM_Bridge/MMDVM_Bridge.ini | DVSwitch | 1487 | 0644 | root:root | 2026-10-12 18:48 | 10f42f2ef226 |  |
| /opt/YSFGateway/YSFGateway.ini | DVSwitch | 1156 | 0644 | root:root | 2026-07-12 13:21 | 5ace0f8de48f |  |
| /opt/P25Gateway/P25Gateway.ini | DVSwitch | 645 | 0644 | root:root | 2025-09-09 12:09 | 4b71882c6746 |  |
| /opt/NXDNGateway/NXDNGateway.ini | DVSwitch | 1326 | 0644 | root:root | 2026-07-12 13:21 | 5f2695a50b38 |  |
| /var/lib/dvswitch/dvs/var.txt | DVSwitch | 1047 | 0644 | root:root | 2026-07-12 13:21 | 9964856a8107 |  |
| /opt/USRP2M17/USRP2M17.ini | USRP2M17 | 290 | 0644 | root:root | 2026-10-27 11:49 | 59b88fcc9f5e |  |
| /etc/allmon3/allmon3.ini | Allmon3 | 2419 | 0660 | allmon3:allmon3 | 2026-10-11 11:42 | 6087e21fecc8 |  |
| /etc/allmon3/web.ini | Allmon3 | 4639 | 0644 | root:root | 2026-10-14 17:52 | 63a18379f90e |  |
| /etc/firewalld/firewalld.conf | Firewall and 44Net Connect | 4692 | 0600 | root:root | 2026-06-08 15:33 | e20d795619a6 |  |
| /etc/firewalld/zones/44NetConnect.xml | Firewall and 44Net Connect | 134 | 0644 | root:root | 2026-10-18 03:47 | c196b22fc37d |  |
| /etc/firewalld/zones/allstarlink.xml | Firewall and 44Net Connect | 864 | 0644 | root:root | 2026-10-19 18:43 | 5abab55d16a2 |  |
| /etc/firewalld/zones/block.xml | Firewall and 44Net Connect | 312 | 0644 | root:root | 2026-10-18 03:47 | 4df14daad533 |  |
| /etc/firewalld/zones/dmz.xml | Firewall and 44Net Connect | 306 | 0644 | root:root | 2026-10-18 03:47 | ca6f4fe0c529 |  |
| /etc/firewalld/zones/drop.xml | Firewall and 44Net Connect | 304 | 0644 | root:root | 2026-10-18 03:47 | 69ce60960115 |  |
| /etc/firewalld/zones/external.xml | Firewall and 44Net Connect | 317 | 0644 | root:root | 2026-10-18 03:47 | 22b8d0e58503 |  |
| /etc/firewalld/zones/home.xml | Firewall and 44Net Connect | 382 | 0644 | root:root | 2026-10-18 03:47 | 2342f9353862 |  |
| /etc/firewalld/zones/internal.xml | Firewall and 44Net Connect | 397 | 0644 | root:root | 2026-10-18 03:47 | abe0216d5dde |  |
| /etc/firewalld/zones/nm-shared.xml | Firewall and 44Net Connect | 726 | 0644 | root:root | 2026-10-18 03:47 | 9a6afca562b5 |  |
| /etc/firewalld/zones/public.xml | Firewall and 44Net Connect | 328 | 0644 | root:root | 2026-10-18 03:47 | 0648dd2d581b |  |
| /etc/firewalld/zones/trusted.xml | Firewall and 44Net Connect | 175 | 0644 | root:root | 2026-10-18 03:47 | 1638fe12372e |  |
| /etc/firewalld/zones/work.xml | Firewall and 44Net Connect | 324 | 0644 | root:root | 2026-10-18 03:47 | ac6f177fb7be |  |
| /etc/firewalld/services/44Helper.xml | Firewall and 44Net Connect | 134 | 0644 | root:root | 2026-08-12 02:37 | be5d45d60829 |  |
| /etc/firewalld/services/5160.xml | Firewall and 44Net Connect | 130 | 0644 | root:root | 2026-09-29 11:25 | 68d95ad2f654 |  |
| /etc/firewalld/services/Dashboard--8989-8989.xml | Firewall and 44Net Connect | 144 | 0644 | root:root | 2026-07-30 02:46 | 0bc4af620661 |  |
| /etc/firewalld/services/Instamon.xml | Firewall and 44Net Connect | 134 | 0644 | root:root | 2026-08-11 09:06 | c6a8db0793cf |  |
| /etc/firewalld/services/Sysmon--9999-9999.xml | Firewall and 44Net Connect | 134 | 0644 | root:root | 2026-07-12 11:32 | a72cb1467907 |  |
| /etc/firewalld/services/astmgr.xml | Firewall and 44Net Connect | 176 | 0644 | root:root | 2026-01-02 19:38 | d9938770ac60 |  |
| /etc/firewalld/services/custom--10000-20000.xml | Firewall and 44Net Connect | 104 | 0644 | root:root | 2026-10-01 09:15 | 93f301244a57 |  |
| /etc/firewalld/services/custom--8991.xml | Firewall and 44Net Connect | 97 | 0644 | root:root | 2026-09-23 14:58 | 9a6e3445566f |  |
| /etc/firewalld/services/custom--8993-8993.xml | Firewall and 44Net Connect | 170 | 0644 | root:root | 2026-10-19 18:43 | 1f3fc0539f18 |  |
| /etc/firewalld/services/custom--sip.xml | Firewall and 44Net Connect | 97 | 0644 | root:root | 2026-09-29 11:22 | d98f4a76e22e |  |
| /etc/firewalld/services/echolink.xml | Firewall and 44Net Connect | 173 | 0644 | root:root | 2026-01-02 19:38 | b9f7aa9bfcdc |  |
| /etc/firewalld/services/iax2.xml | Firewall and 44Net Connect | 190 | 0644 | root:root | 2026-01-02 19:38 | 0423428f27dc |  |
| /etc/firewalld/services/rtcm.xml | Firewall and 44Net Connect | 177 | 0644 | root:root | 2026-01-02 19:38 | ea381a9f5406 |  |
| /etc/wireguard/wg0.conf | Firewall and 44Net Connect | 1556 | 0600 | root:root | 2026-10-18 14:20 | 2ecb0803332f |  |
| /etc/sysctl.d/90-44helper-halftunnel.conf | Firewall and 44Net Connect | 95 | 0644 | root:root | 2026-10-18 14:20 | a0036ce549d6 |  |
| /etc/sysctl.d/98-rpi.conf | Firewall and 44Net Connect | 92 | 0644 | root:root | 2023-05-10 02:00 | f832f97a3459 |  |
| /etc/asl_dvs/asl_dvs.conf | Node tools | 9536 | 0600 | root:root | 2026-10-20 03:04 | fa6d8894a611 |  |
| /etc/asl_dvs/nodelisten.conf | Node tools | 727 | 0644 | root:root | 2026-10-27 10:37 | c7650cf294fc |  |
| /etc/asl_dvs/nodelisten_favorites.conf | Node tools | 790 | 0600 | root:root | 2026-10-27 10:37 | 138c3b7ad1cb |  |
| /etc/asl_dvs/nodetalker.conf | Node tools | 727 | 0644 | root:root | 2026-10-27 10:37 | c7650cf294fc |  |
| /etc/asl_dvs/nodetalker_favorites.conf | Node tools | 790 | 0600 | root:root | 2026-10-27 10:37 | 138c3b7ad1cb |  |
| /etc/asl_dvs/instmon_channel.json | Node tools | 26 | 0600 | root:root | 2026-10-14 19:34 | 0a9781ee54e2 |  |
| /etc/asl_dvs/instmon_diskimg_schedule.json | Node tools | 275 | 0600 | root:root | 2026-09-03 14:25 | f4dbeb89ef27 |  |
| /etc/asl_dvs/instmon_full_update.json | Node tools | 432 | 0600 | root:root | 2026-10-26 09:05 | 7134c9865642 |  |
| /etc/asl_dvs/instmon_locks.json | Node tools | 61 | 0600 | root:root | 2026-10-27 12:08 | 675cafbf220a |  |
| /etc/asl_dvs/nodelisten_favorites.json | Node tools | 532 | 0644 | root:root | 2026-10-27 10:37 | 9c3b082fa9d7 |  |
| /etc/asl_dvs/nodelisten_tuned.json | Node tools | 53 | 0644 | root:root | 2026-10-26 15:33 | 316eea8402e2 |  |
| /etc/asl_dvs/nodetalker_favorites.json | Node tools | 532 | 0644 | root:root | 2026-10-27 10:37 | 9c3b082fa9d7 |  |
| /etc/asl_dvs/nodetalker_tuned.json | Node tools | 53 | 0644 | root:root | 2026-10-26 15:33 | 316eea8402e2 |  |
| /etc/asl_dvs/phone.json | Node tools | 2886 | 0600 | root:root | 2026-10-18 15:36 | 83901f0a5ebf |  |
| /etc/sysmon/sysmon.conf | Node tools | 2983 | 0644 | root:root | 2026-10-22 18:18 | 14b2bebfc558 |  |
| /etc/44helper/44helper.conf | Node tools | 630 | 0600 | root:root | 2026-10-13 19:14 | bd0305d2f92b |  |
| /etc/wifimon/wifimon.conf | Node tools | 335 | 0600 | root:root | 2026-10-20 02:52 | c9be7a9d15d1 |  |
| /etc/NetworkManager/conf.d/90-wifimon-powersave.conf | Node tools | 180 | 0644 | root:root | 2026-10-19 18:29 | 7cde17f75583 |  |
| /etc/systemd/system.conf.d/90-asl_dvs-hwwatchdog.conf | Node tools | 142 | 0644 | root:root | 2026-10-19 18:29 | 430f9d400850 |  |
| /etc/os-release | Network and system | 376 | 0644 | root:root | 2026-10-14 19:42 | 46bffa575d0d |  |
| /etc/hostname | Network and system | 9 | 0644 | root:root | 2026-10-11 16:19 | bbafc2d5c6b0 |  |
| /etc/hosts | Network and system | 126 | 0644 | root:root | 2026-09-28 07:56 | 0052ffbe32fa |  |
| /etc/resolv.conf | Network and system | 926 | 0644 | systemd-resolve:systemd-resolve | 2026-10-26 15:49 | 6e842f9fad6f |  |
| /etc/dhcpcd.conf | Network and system | 1274 | 0644 | root:root | 2025-12-25 04:40 | dfb64a3df977 |  |
| /etc/NetworkManager/system-connections/N0CALL004-wifimenu-0d4dc4c5.nmconnection | Network and system | 261 | 0600 | root:root | 2026-10-12 18:09 | dc524a85357b |  |
| /etc/NetworkManager/system-connections/N0CALL2-wifimenu-3f58db75.nmconnection | Network and system | 305 | 0600 | root:root | 2026-10-20 02:52 | b15094742ad1 |  |
| /etc/NetworkManager/system-connections/N0CALL3.nmconnection | Network and system | 271 | 0600 | root:root | 2026-10-20 02:52 | 0eea94dd7a0d |  |
| /etc/NetworkManager/system-connections/HomeWiFi-DD.nmconnection | Network and system | 340 | 0600 | root:root | 2026-10-12 18:09 | a5450dceeadf |  |
| /etc/NetworkManager/system-connections/asl-fallback-ap.nmconnection | Network and system | 385 | 0600 | root:root | 2026-10-27 12:10 | 7a17fb496491 |  |
| /etc/NetworkManager/system-connections/asl-fallback-ap.nmconnection.GS5FX3 | Network and system | 385 | 0600 | root:root | 2026-10-23 06:26 | 7a17fb496491 |  |
| /etc/NetworkManager/system-connections/asl-fallback-ap.nmconnection.IEIQX3 | Network and system | 385 | 0600 | root:root | 2026-10-18 16:42 | 7a17fb496491 |  |
| /etc/systemd/journald.conf | Network and system | 1429 | 0644 | root:root | 2025-09-03 14:35 | b7ab521d85bb |  |

## Skipped

| Path | Why |
|---|---|
| /etc/asterisk/acl.conf | same as the package default |
| /etc/asterisk/adsi.conf | same as the package default |
| /etc/asterisk/aeap.conf | same as the package default |
| /etc/asterisk/agents.conf | same as the package default |
| /etc/asterisk/alarmreceiver.conf | same as the package default |
| /etc/asterisk/amd.conf | same as the package default |
| /etc/asterisk/app_skel.conf | same as the package default |
| /etc/asterisk/ari.conf | same as the package default |
| /etc/asterisk/ast_debug_tools.conf | same as the package default |
| /etc/asterisk/calendar.conf | same as the package default |
| /etc/asterisk/ccss.conf | same as the package default |
| /etc/asterisk/cdr.conf | same as the package default |
| /etc/asterisk/cdr_adaptive_odbc.conf | same as the package default |
| /etc/asterisk/cdr_beanstalkd.conf | same as the package default |
| /etc/asterisk/cdr_custom.conf | same as the package default |
| /etc/asterisk/cdr_manager.conf | same as the package default |
| /etc/asterisk/cdr_odbc.conf | same as the package default |
| /etc/asterisk/cdr_pgsql.conf | same as the package default |
| /etc/asterisk/cdr_sqlite3_custom.conf | same as the package default |
| /etc/asterisk/cdr_tds.conf | same as the package default |
| /etc/asterisk/cel.conf | same as the package default |
| /etc/asterisk/cel_beanstalkd.conf | same as the package default |
| /etc/asterisk/cel_custom.conf | same as the package default |
| /etc/asterisk/cel_odbc.conf | same as the package default |
| /etc/asterisk/cel_pgsql.conf | same as the package default |
| /etc/asterisk/cel_sqlite3_custom.conf | same as the package default |
| /etc/asterisk/cel_tds.conf | same as the package default |
| /etc/asterisk/chan_dahdi.conf | same as the package default |
| /etc/asterisk/chan_mobile.conf | same as the package default |
| /etc/asterisk/chan_websocket.conf | same as the package default |
| /etc/asterisk/cli.conf | same as the package default |
| /etc/asterisk/cli_aliases.conf | same as the package default |
| /etc/asterisk/cli_permissions.conf | same as the package default |
| /etc/asterisk/codecs.conf | same as the package default |
| /etc/asterisk/confbridge.conf | same as the package default |
| /etc/asterisk/config_test.conf | same as the package default |
| /etc/asterisk/console.conf | same as the package default |
| /etc/asterisk/dbsep.conf | same as the package default |
| /etc/asterisk/dnsmgr.conf | same as the package default |
| /etc/asterisk/dsp.conf | same as the package default |
| /etc/asterisk/enum.conf | same as the package default |
| /etc/asterisk/extconfig.conf | same as the package default |
| /etc/asterisk/extensions_minivm.conf | same as the package default |
| /etc/asterisk/features.conf | same as the package default |
| /etc/asterisk/festival.conf | same as the package default |
| /etc/asterisk/followme.conf | same as the package default |
| /etc/asterisk/func_odbc.conf | same as the package default |
| /etc/asterisk/geolocation.conf | same as the package default |
| /etc/asterisk/gps.conf | same as the package default |
| /etc/asterisk/hep.conf | same as the package default |
| /etc/asterisk/http.conf | same as the package default |
| /etc/asterisk/iaxprov.conf | same as the package default |
| /etc/asterisk/indications.conf | same as the package default |
| /etc/asterisk/meetme.conf | same as the package default |
| /etc/asterisk/minivm.conf | same as the package default |
| /etc/asterisk/motif.conf | same as the package default |
| /etc/asterisk/musiconhold.conf | same as the package default |
| /etc/asterisk/ooh323.conf | same as the package default |
| /etc/asterisk/phoneprov.conf | same as the package default |
| /etc/asterisk/pjproject.conf | same as the package default |
| /etc/asterisk/pjsip_notify.conf | same as the package default |
| /etc/asterisk/pjsip_wizard.conf | same as the package default |
| /etc/asterisk/prometheus.conf | same as the package default |
| /etc/asterisk/queuerules.conf | same as the package default |
| /etc/asterisk/queues.conf | same as the package default |
| /etc/asterisk/res_config_mysql.conf | same as the package default |
| /etc/asterisk/res_config_odbc.conf | same as the package default |
| /etc/asterisk/res_config_sqlite3.conf | same as the package default |
| /etc/asterisk/res_corosync.conf | same as the package default |
| /etc/asterisk/res_curl.conf | same as the package default |
| /etc/asterisk/res_fax.conf | same as the package default |
| /etc/asterisk/res_http_media_cache.conf | same as the package default |
| /etc/asterisk/res_ldap.conf | same as the package default |
| /etc/asterisk/res_odbc.conf | same as the package default |
| /etc/asterisk/res_parking.conf | same as the package default |
| /etc/asterisk/res_pgsql.conf | same as the package default |
| /etc/asterisk/res_snmp.conf | same as the package default |
| /etc/asterisk/res_stun_monitor.conf | same as the package default |
| /etc/asterisk/res_usbradio.conf | same as the package default |
| /etc/asterisk/resolver_unbound.conf | same as the package default |
| /etc/asterisk/rpt_auth.conf | same as the package default |
| /etc/asterisk/rtp.conf | same as the package default |
| /etc/asterisk/say.conf | same as the package default |
| /etc/asterisk/sla.conf | same as the package default |
| /etc/asterisk/smdi.conf | same as the package default |
| /etc/asterisk/sorcery.conf | same as the package default |
| /etc/asterisk/stasis.conf | same as the package default |
| /etc/asterisk/statsd.conf | same as the package default |
| /etc/asterisk/stir_shaken.conf | same as the package default |
| /etc/asterisk/test_sorcery.conf | same as the package default |
| /etc/asterisk/udptl.conf | same as the package default |
| /etc/asterisk/voicemail.conf | same as the package default |
| /etc/asterisk/websocket_client.conf | same as the package default |
| /etc/asterisk/xmpp.conf | same as the package default |

## ASL3 / Asterisk

### /etc/asterisk/asterisk.conf

```
; In order for Asterisk to process the [directories](!) stanza below,
; you will need to remove the (!) suffix, which marks this as a template.
; The compiled-in defaults are typically sufficient, so most users will 
; not have to do this.
[directories](!)
astcachedir => /var/cache/asterisk
astetcdir => /etc/asterisk
astmoddir => /usr/lib/aarch64-linux-gnu/asterisk/modules
astvarlibdir => /var/lib/asterisk
astdbdir => /var/lib/asterisk
astkeydir => /var/lib/asterisk
astdatadir => /usr/share/asterisk
astagidir => /usr/share/asterisk/agi-bin
astspooldir => /var/spool/asterisk
astrundir => /var/run/asterisk
astlogdir => /var/log/asterisk
astsbindir => /usr/sbin

[options]
;verbose = 3
;debug = 3
;trace = 0              ; Set the trace level.
;refdebug = yes			; Enable reference count debug logging.
;alwaysfork = yes		; Same as -F at startup.
;nofork = yes			; Same as -f at startup.
;quiet = yes			; Same as -q at startup.
;timestamp = yes		; Same as -T at startup.
;execincludes = yes		; Support #exec in config files.
;console = yes			; Run as console (same as -c at startup).
;highpriority = yes		; Run realtime priority (same as -p at
				; startup).
;initcrypto = yes		; Initialize crypto keys (same as -i at
				; startup).
;nocolor = yes			; Disable console colors.
;dontwarn = yes			; Disable some warnings.
;dumpcore = yes			; Dump core on crash (same as -g at startup).
;languageprefix = yes		; Use the new sound prefix path syntax.
;systemname = my_system_name	; Prefix uniqueid with a system name for
				; Global uniqueness issues.
;autosystemname = yes		; Automatically set systemname to hostname,
				; uses 'localhost' on failure, or systemname if
				; set.
;mindtmfduration = 80		; Set minimum DTMF duration in ms (default 80 ms)
				; If we get shorter DTMF messages, these will be
				; changed to the minimum duration
;maxcalls = 10			; Maximum amount of calls allowed.
;maxload = 0.9			; Asterisk stops accepting new calls if the
				; load average exceed this limit.
;maxfiles = 1000		; Maximum amount of openfiles.
;minmemfree = 1			; In MBs, Asterisk stops accepting new calls if
				; the amount of free memory falls below this
				; watermark.
;cache_media_frames = yes	; Cache media frames for performance
				; Disable this option to help track down media frame
				; mismanagement when using valgrind or MALLOC_DEBUG.
				; The cache gets in the way of determining if the
				; frame is used after being freed and who freed it.
				; NOTE: This option has no effect when Asterisk is
				; compiled with the LOW_MEMORY compile time option
				; enabled because the cache code does not exist.
				; Default yes
;cache_record_files = yes	; Cache recorded sound files to another
				; directory during recording.
;record_cache_dir = /tmp	; Specify cache directory (used in conjunction
				; with cache_record_files).
;transmit_silence = yes		; Transmit silence while a channel is in a
				; waiting state, a recording only state, or
				; when DTMF is being generated.  Note that the
				; silence internally is generated in raw signed
				; linear format. This means that it must be
				; transcoded into the native format of the
				; channel before it can be sent to the device.
				; It is for this reason that this is optional,
				; as it may result in requiring a temporary
				; codec translation path for a channel that may
				; not otherwise require one.
;transcode_via_sln = yes	; Build transcode paths via SLINEAR, instead of
				; directly.
;runuser = asterisk		; The user to run as.
;rungroup = asterisk		; The group to run as.
;lightbackground = yes		; If your terminal is set for a light-colored
				; background.
;forceblackbackground = yes     ; Force the background of the terminal to be
                                ; black, in order for terminal colors to show
                                ; up properly.
;defaultlanguage = en           ; Default language
documentation_language = en_US	; Set the language you want documentation
				; displayed in. Value is in the same format as
				; locale names.
;hideconnect = yes		; Hide messages displayed when a remote console
				; connects and disconnects.
;lockconfdir = no		; Protect the directory containing the
				; configuration files (/etc/asterisk) with a
				; lock.
;stdexten = gosub		; How to invoke the extensions.conf stdexten.
				; gosub - Invoke the stdexten using a gosub as
				;         documented in extensions.conf.sample.
				; Default gosub.
;live_dangerously = no		; Enable the execution of 'dangerous' dialplan
				; functions and configuration file access from
				; external sources (AMI, etc.) These functions
				; (such as SHELL) are considered dangerous
				; because they can allow privilege escalation.
				; Configuration files are considered dangerous
				; if they exist outside of the Asterisk
				; configuration directory.
				; Default no
;entityid=00:11:22:xx:xx:xx	; Entity ID.
				; This is in the form of a MAC address.
				; It should be universally unique.
				; It must be unique between servers communicating
				; with a protocol that uses this value.
				; This is currently is used by DUNDi and
				; Exchanging Device and Mailbox State
				; using protocols: XMPP, Corosync and PJSIP.
;rtp_use_dynamic = yes          ; When set to "yes" RTP dynamic payload types
                                ; are assigned dynamically per RTP instance vs.
                                ; allowing Asterisk to globally initialize them
                                ; to pre-designated numbers (defaults to "yes").
;rtp_pt_dynamic = 35		; Normally the Dynamic RTP Payload Type numbers
				; are 96-127, which allow just 32 formats. The
				; starting point 35 enables the range 35-63 and
				; allows 29 additional formats. When you use
				; more than 32 formats in the dynamic range and
				; calls are not accepted by a remote
				; implementation, please report this and go
				; back to value 96.
;hide_messaging_ami_events = no;  This option, if enabled, will
                ; suppress all of the Message/ast_msg_queue channel's
                ; housekeeping AMI and ARI channel events.  This can
                ; reduce the load on the manager and ARI applications
                ; when the Digium Phone Module for Asterisk is in use.
sounds_search_custom_dir = yes;  This option, if enabled, will
                ; cause Asterisk to search for sounds files in
                ; AST_DATA_DIR/sounds/custom before searching the
                ; normal directories like AST_DATA_DIR/sounds/<lang>.
;channel_storage_backend = ao2_legacy ; Select the channel storage backend
                ; to use for live operation.
                ;   ao2_legacy:  Original implementation (default)
                ; Depending on compile options, the following may also be
                ; available:
                ;   cpp_map_name_id: Use C++ Maps to index both
                ;                    channel name and channel uniqueid.
                ; See http://s.asterisk.net/dc679ec3 for more information.
;disable_remote_console_shell = no; Prevent remote console CLI sessions
                ; from executing shell commands with the '!' prefix.
                ; Default: no

; Changing the following lines may compromise your security.
;[files]
;astctlpermissions = 0660
;astctlowner = root
;astctlgroup = apache
;astctl = asterisk.ctl
```

### /etc/asterisk/dvs_phone_extensions.conf

```
; asl_dvs_dashboard - Phone tab dialplan (rewritten on every apply; do not edit)

[dvs-invalid]
exten => s,1,Wait(1)
 same => n,Playback(ss-noservice)
 same => n,Hangup()

; Outgoing (autopatch): the live network is read from AstDB 'dvsphone/active'.
[dvs-phone-out]
exten => _X.,1,Set(DVSNET=${DB(dvsphone/active)})
 same => n,Set(DVSOPT=)
 same => n,GotoIf($[${DB_EXISTS(dvsphone/then)}]?then:net)
 same => n(then),Set(DVSOPT=D(${DB_DELETE(dvsphone/then)}))
 same => n(net),GotoIf($["${DVSNET}" = ""]?bad)
 same => n,GotoIf($["${DB(dvsphone/patch)}" = "0"]?bad)
 same => n,Goto(dvs-net-${DVSNET},${EXTEN},1)
 same => n(bad),Goto(dvs-invalid,s,1)
exten => i,1,Goto(dvs-invalid,s,1)
exten => t,1,Hangup()

; Dialed from the radio (*61): hand the number to the dashboard, which places the call.
[dvs-radio-out]
exten => _X.,1,NoOp(radio dial)
 same => n,System(/var/lib/asterisk/dvs_phone_dialreq "${EXTEN}" "${DB(dvsphone/active)}")
 same => n,Hangup()
exten => i,1,Hangup()
exten => t,1,Hangup()

; Tones as sound (v9.3.16): plays touch-tone recordings, whispered into
; the live call by ChanSpy.  Only the dashboard starts this.
[dvs-tones]
exten => s,1,Answer()
 same => n,Wait(0.5)
 same => n,Playback(${DVSTONES})
 same => n,Wait(0.3)
 same => n,Hangup()

; ---- Ham Over IP (Hams Over IP) -- node 1001 ----
[dvs-node-dvshoip]
exten => _X.,1,Set(DVSNET=dvshoip)
 same => n,Set(DVSOPT=)
 same => n,GotoIf($[${DB_EXISTS(dvsphone/then)}]?then:net)
 same => n(then),Set(DVSOPT=D(${DB_DELETE(dvsphone/then)}))
 same => n(net),GotoIf($["${DB(dvsphone/patch)}" = "0"]?bad)
 same => n,Goto(dvs-net-dvshoip,${EXTEN},1)
 same => n(bad),Goto(dvs-invalid,s,1)
exten => i,1,Goto(dvs-invalid,s,1)
exten => t,1,Hangup()

[dvs-radio-dvshoip]
exten => _X.,1,NoOp(radio dial)
 same => n,System(/var/lib/asterisk/dvs_phone_dialreq "${EXTEN}" dvshoip)
 same => n,Hangup()
exten => i,1,Hangup()
exten => t,1,Hangup()

[dvs-net-dvshoip]
exten => 0098,1,NoOp(test call)
 same => n,Set(CALLERID(num)=400999)
 same => n,Dial(PJSIP/3194@dvshoip,60,${DVSOPT})
 same => n,Hangup()
exten => 0097,1,NoOp(voicemail)
 same => n,Set(CALLERID(num)=400999)
 same => n,Dial(PJSIP/*97@dvshoip,60,${DVSOPT})
 same => n,Hangup()
exten => _X.,1,NoOp(extension call)
 same => n,Set(CALLERID(num)=400999)
 same => n,Dial(PJSIP/${EXTEN}@dvshoip,60,${DVSOPT})
 same => n,Hangup()
exten => i,1,Goto(dvs-invalid,s,1)

[dvs-in-dvshoip]
exten => _[+0-9].,1,NoOp(incoming call from ${CALLERID(num)})
 same => n,GotoIf($["${DB(dvsphone/open)}" = "1" & "${DB(dvsphone/active)}" = "dvshoip"]?open)
 same => n,Busy(20)
 same => n,Hangup()
 same => n(open),NoOp()
 same => n(connect),Answer()
 same => n,Wait(1)
 same => n,Playback(rpt/connected)
 same => n,rpt(1001,Pv)
 same => n,Hangup()
exten => s,1,NoOp(incoming call from ${CALLERID(num)})
 same => n,GotoIf($["${DB(dvsphone/open)}" = "1" & "${DB(dvsphone/active)}" = "dvshoip"]?open)
 same => n,Busy(20)
 same => n,Hangup()
 same => n(open),NoOp()
 same => n(connect),Answer()
 same => n,Wait(1)
 same => n,Playback(rpt/connected)
 same => n,rpt(1001,Pv)
 same => n,Hangup()

; ---- AmateurWire (AmateurWire) -- node 1002 ----
[dvs-node-dvsamateurwire]
exten => _X.,1,Set(DVSNET=dvsamateurwire)
 same => n,Set(DVSOPT=)
 same => n,GotoIf($[${DB_EXISTS(dvsphone/then)}]?then:net)
 same => n(then),Set(DVSOPT=D(${DB_DELETE(dvsphone/then)}))
 same => n(net),GotoIf($["${DB(dvsphone/patch)}" = "0"]?bad)
 same => n,Goto(dvs-net-dvsamateurwire,${EXTEN},1)
 same => n(bad),Goto(dvs-invalid,s,1)
exten => i,1,Goto(dvs-invalid,s,1)
exten => t,1,Hangup()

[dvs-radio-dvsamateurwire]
exten => _X.,1,NoOp(radio dial)
 same => n,System(/var/lib/asterisk/dvs_phone_dialreq "${EXTEN}" dvsamateurwire)
 same => n,Hangup()
exten => i,1,Hangup()
exten => t,1,Hangup()

[dvs-net-dvsamateurwire]
exten => 0097,1,NoOp(voicemail)
 same => n,Set(CALLERID(num)=400998)
 same => n,Set(CALLERID(name)=N0CALL)
 same => n,Dial(PJSIP/*97@dvsamateurwire,60,${DVSOPT})
 same => n,Hangup()
exten => _X.,1,NoOp(extension call)
 same => n,Set(CALLERID(num)=400998)
 same => n,Set(CALLERID(name)=N0CALL)
 same => n,Dial(PJSIP/${EXTEN}@dvsamateurwire,60,${DVSOPT})
 same => n,Hangup()
exten => i,1,Goto(dvs-invalid,s,1)

[dvs-in-dvsamateurwire]
exten => _[+0-9].,1,NoOp(incoming call from ${CALLERID(num)})
 same => n,GotoIf($["${DB(dvsphone/open)}" = "1" & "${DB(dvsphone/active)}" = "dvsamateurwire"]?open)
 same => n,Busy(20)
 same => n,Hangup()
 same => n(open),NoOp()
 same => n(connect),Answer()
 same => n,Wait(1)
 same => n,Playback(rpt/connected)
 same => n,rpt(1002,Pv)
 same => n,Hangup()
exten => s,1,NoOp(incoming call from ${CALLERID(num)})
 same => n,GotoIf($["${DB(dvsphone/open)}" = "1" & "${DB(dvsphone/active)}" = "dvsamateurwire"]?open)
 same => n,Busy(20)
 same => n,Hangup()
 same => n(open),NoOp()
 same => n(connect),Answer()
 same => n,Wait(1)
 same => n,Playback(rpt/connected)
 same => n,rpt(1002,Pv)
 same => n,Hangup()
```

### /etc/asterisk/dvs_phone_pjsip.conf

```
; asl_dvs_dashboard - Phone tab SIP accounts (rewritten on every apply)

[dvs-transport]
type=transport
protocol=udp
bind=0.0.0.0:5060
local_net=198.51.100.1/24
local_net=127.0.0.1/32

; ---- Ham Over IP ----
[dvshoip-auth]
type=auth
auth_type=userpass
username=400999
password=<redacted:de3f17c5>

[dvshoip-reg]
type=registration
outbound_auth=dvshoip-auth
server_uri=sip:premium.hamsoverip.com:5160
client_uri=sip:<redacted:cc9804d8>
retry_interval=60
contact_user=400999
expiration=3600
line=yes
endpoint=dvshoip

[dvshoip]
type=aor
contact=sip:premium.hamsoverip.com:5160
qualify_frequency=60

[dvshoip]
type=endpoint
context=dvs-in-dvshoip
disallow=all
allow=ulaw
allow=alaw
allow=gsm
aors=dvshoip
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes
dtmf_mode=rfc4733
outbound_auth=dvshoip-auth
from_user=400999
from_domain=premium.hamsoverip.com
callerid=<400999>

[dvshoip]
type=identify
endpoint=dvshoip
match=premium.hamsoverip.com

; ---- AmateurWire ----
[dvsamateurwire-auth]
type=auth
auth_type=userpass
username=400998
password=<redacted:b00044e6>

[dvsamateurwire]
type=aor
contact=sip:pbx1-wv.amateurwire.org:5060
qualify_frequency=60

[dvsamateurwire]
type=endpoint
context=dvs-in-dvsamateurwire
disallow=all
allow=ulaw
allow=alaw
allow=gsm
aors=dvsamateurwire
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes
dtmf_mode=rfc4733
outbound_auth=dvsamateurwire-auth
from_user=400998
from_domain=pbx1-wv.amateurwire.org
callerid="N0CALL" <400998>

[dvsamateurwire]
type=identify
endpoint=dvsamateurwire
match=pbx1-wv.amateurwire.org
```

### /etc/asterisk/echolink.conf

```
; If you are going to use this channel driver, you MUST enable it in modules.conf
; change:
; noload => chan_echolink.so 		; echolink Channel Driver
; to:
; load => chan_echolink 			; echolink Channel Driver

[el0]
call = INVALID						; Change this!
pwd = <redacted:2a4e61cd>
name = YOUR NAME					; Change this!
qth = INVALID						; Change this!
email = INVALID						; Change this!
node = 000000                       ; Change this!
; Data for EchoLink Status Page
lat = 0.0							; Latitude in decimal degrees
lon = 0.0							; Longitude in decimal degrees
freq = 0.0                          ; not mandatory Frequency in MHz
tone = 0.0                          ; not mandatory CTCSS Tone (0 for none)
power = 0							; 0=0W, 1=1W, 2=4W, 3=9W, 4=16W, 5=25W, 6=36W, 7=49W, 8=64W, 9=81W (Power in Watts)
height = 0							; 0=10 1=20 2=40 3=80 4=160 5=320 6=640 7=1280 8=2560 9=5120 (AMSL in Feet)
gain = 0							; Gain in db (0-9)
dir = 0								; 0=omni 1=45deg 2=90deg 3=135deg 4=180deg 5=225deg 6=270deg 7=315deg 8=360deg (Direction)

; Message to show on the echolink connect page. Use \n for new lines.
; message = This is the first line\nThis is another line\nThis is another line

maxstns = 20						; Max Stations

rtcptimeout = 10					; Max number of missed heartbeats from EL
recfile = /tmp/echolink_recorded.gsm	;
astnode = 500002						; Change this!
context = radio-secure				; Default in code is radio-secure

; Max 4 servers
server1 = nasouth.echolink.org
server2 = naeast.echolink.org
server3 = servers.echolink.org
server4 = backup.echolink.org

; To deny w6xxx you would add the statement: deny = w6xxx
; To prohibit computer-based connections you would write: permit = *-*
; To allow access to only a select group of callsigns: permit = w6abc,w6def,...

; permit							; comma delimited list of callsign, type (-r)
; deny


; Remote text commands thru netcat:
; o.conip <IPaddress>    (request a connect)
; o.dconip <IPaddress>   (request a disconnect)
; o.rec                  (turn on/off recording)

; ipaddr
; port

#tryinclude "custom/echolink.conf"
```

### /etc/asterisk/extensions.conf

```
[general]

static = yes       ; These two lines prevent the command-line interface
writeprotect = yes ; from overwriting the config file. Leave them here.

[globals]
HOMENPA = 44505 ; change this to your Area Code

TAILFILEINDEX=0 ; used for telemetry, do not remove/change

[default]
exten => i,1,Hangup

[radio-secure]
exten => _XXXX!,1,Set(NODENUM=${CALLERID(num)})
	same => n,NoOp(Connect from node ${NODENUM} to node ${EXTEN} using ${CHANNEL(channeltype)})
	same => n,ExecIf($[!${RPT_NODE(${EXTEN},exists)}]?Hangup) ; disconnect if requested node is not on this server
	same => n,GotoIf($["${CHANNEL(channeltype)}" = "IAX2"]?:allowlist)              ; if not IAX2, skip IP check

	; if peer IP is localhost, connect
	same => n,NoOp(Channel Peer IP: ${CHANNEL(peerip)})
	same => n,GotoIf($["${CHANNEL(peerip)}" = "127.0.0.1"]?connect)                 ; if localhost; connect

	; if allowlist/extension doesn't exist, check the denylist
	same => n(allowlist),GotoIf($[${DB_KEYCOUNT(allowlist/${EXTEN})} = 0]?denylist) ; no allowlist, check denylist
	; if allowlist/extension/callerID exists, connect
	same => n,GotoIf(${DB_EXISTS(allowlist/${EXTEN}/${NODENUM})}?connect)           ; in allowlist, connect
	same => n,NoOp(${NODENUM} not in allowlist, Hangup)
	same => n,Hangup

	; if denylist/extension/callerID doesn't exist, connect
	same => n(denylist),GotoIf(${DB_EXISTS(denylist/${EXTEN}/${NODENUM})}?:connect) ; not in denylist, connect
	same => n,NoOp(${NODENUM} is in denylist, Hangup)
	same => n,Hangup

	; connect!
	same => n(connect),Rpt(${EXTEN})
	same => n,Hangup
		
[iaxrpt]
; Entered from iaxrpt in iax.conf
; Info: The X option passed to the Rpt application
; disables the normal security checks.
; Because incoming connections are validated in iax.conf,
; and we don't know where the user will be coming from in advance,
; the X option is required.
exten => _XXXX!,1,Set(NODENUM=${CALLERID(num)})
	same => n,NoOp(Connect from node ${NODENUM} to node ${EXTEN} using ${CHANNEL(channeltype)})
	same => n,ExecIf($[!${RPT_NODE(${EXTEN},exists)}]?Hangup) ; disconnect if requested node is not on this server
	same => n,Rpt(${EXTEN},X)
	same => n,Hangup

[iax-client] ; for IAX VoIP clients.
exten => _XXXX!,1,Set(NODENUM=${CALLERID(num)})
	same => n,NoOp(Connect from node ${NODENUM} to node ${EXTEN} using ${CHANNEL(channeltype)})
	same => n,ExecIf($[!${RPT_NODE(${EXTEN},exists)}]?Hangup) ; disconnect if requested node is not on this server
	same => n,Ringing()
	same => n,Wait(10)
	same => n,Answer()
	same => n,Set(CALLSIGN=${CALLERID(name)})
	same => n,NoOp(Caller ID name is ${CALLSIGN})
	same => n,NoOp(Caller ID number is ${NODENUM})
	same => n,GotoIf(${ISNULL(${CALLSIGN})}?hangit)
	same => n,Playback(rpt/connected-to&rpt/node)
	same => n,SayDigits(${EXTEN})
	same => n,Rpt(${EXTEN},P,${CALLSIGN}-P)
	same => n(hangit),NoOp(No Caller ID Name)
	same => n,Playback(connection-failed)
	same => n,Wait(1)
	same => n,Hangup

; Comment-out the following clause if you want Allstar Autopatch service
[pstn-out]
exten => _NXXNXXXXXX,1,Wait(1)
	same => n,Playback(ss-noservice)
	same => n,Hangup

; Un-comment out the following clause if you want Allstar Autopatch service
;[pstn-out]
;exten => _NXXNXXXXXX,1,Wait(1)
; same => n, Dial(IAX2/allstar-autopatch/\${EXTEN})
; same => n,Busy

[invalidnum]
exten => s,1,Wait(3)
	same => n,Playback(ss-noservice)
	same => n,Wait(1)
	same => n,Hangup

[radio]
exten => _X11,1,Goto(check_route,${EXTEN},1);
exten => _NXXXXXX,1,Goto(check_route,1${HOMENPA}${EXTEN},1)
exten => _1XXXXXXXXXX,1,Goto(check_route,${EXTEN},1)
exten => _07XX,1,Goto(parkedcalls,${EXTEN:1},1)
exten => 00,1,Goto(my-ip,s,1)

[check_route]
exten => _X.,1,NoOp(${EXTEN})
; no 800
exten => _1800NXXXXXX,2,Goto(invalidnum,s,1)
exten => _1888NXXXXXX,2,Goto(invalidnum,s,1)
exten => _1877NXXXXXX,2,Goto(invalidnum,s,1)
exten => _1866NXXXXXX,2,Goto(invalidnum,s,1)
exten => _1855NXXXXXX,2,Goto(invalidnum,s,1)
; no X00 NPA
exten => _1X00XXXXXXX,2,Goto(invalidnum,s,1)
; no X11 NPA
exten => _1X11XXXXXXX,2,Goto(invalidnum,s,1)
; no X11
exten => _X11,2,Goto(invalidnum,s,1)
; no 555 Prefix in any NPA
exten => _1NXX555XXXX,2,Goto(invalidnum,s,1)
; no 976 Prefix in any NPA
exten => _1NXX976XXXX,2,Goto(invalidnum,s,1)
; no NPA=809
exten => _1809XXXXXXX,2,Goto(invalidnum,s,1)
; no NPA=900
exten => _1900XXXXXXX,2,Goto(invalidnum,s,1)

; okay, route it
exten => _1NXXXXXXXXX,2,Goto(pstn-out,${EXTEN:1},1)
exten => _X.,2,Goto(invalidnum,s,1)

[my-ip]
exten => s,1,Wait(1)
	same => n,SayAlpha(${CURL(http://myip.vg)})
	same => n,Hangup

[allstar-sys]
exten => _1.,1,Rpt(${EXTEN:1},Rrpt/node:NODE:rpt/in-call:digits/0:PARKED,120)
exten => _1.,n,Hangup

exten => _2.,1,Ringing
exten => _2.,n,Wait(3)
exten => _2.,n,Answer
exten => _2.,n,Playback(rpt/node)
exten => _2.,n,Saydigits(${EXTEN:1})
exten => _2.,n,Rpt(${EXTEN:1},P,${CALLERID(name)}-P)
exten => _2.,n,Hangup

exten => _3.,1,Ringing
exten => _3.,n,Wait(3)
exten => _3.,n,Answer
exten => _3.,n,Playback(rpt/node)
exten => _3.,n,Saydigits(${EXTEN:1})
exten => _3.,n,Rpt(${EXTEN:1},Pv,${CALLERID(name)}-P)
exten => _3.,n,Hangup

exten => _4.,1,Ringing
exten => _4.,n,Wait(3)
exten => _4.,n,Answer
exten => _4.,n,Playback(rpt/node)
exten => _4.,n,Saydigits(${EXTEN:1})
exten => _4.,n,Rpt(${EXTEN:1},D,${CALLERID(name)}-P)
exten => _4.,n,Hangup

exten => _5.,1,Ringing
exten => _5.,n,Wait(3)
exten => _5.,n,Answer
exten => _5.,n,Playback(rpt/node)
exten => _5.,n,Saydigits(${EXTEN:1})
exten => _5.,n,Rpt(${EXTEN:1},Dv,${CALLERID(name)}-P)
exten => _5.,n,Hangup

[allstar-public]
exten => s,1,Ringing
	same => n,Set(RESP=${CURL(https://register.allstarlink.org/cgi-bin/authwebphone.pl?${CALLERID(name)})})
	same => n,GotoIf($["${RESP:0:1}" = "?"]?hangit)
	same => n,GotoIf($["${RESP:0:1}" = ""]?hangit)
	same => n,GotoIf($["${RESP:0:5}" != "OHYES"]?hangit)
	same => n,Set(CALLSIGN=${RESP:5})
	same => n,Set(NODENUM=${CALLERID(num)})

	; if allowlist/extension doesn't exist, check the denylist
	same => n,GotoIf($[${DB_KEYCOUNT(allowlist/${NODENUM})} = 0]?denylist)              ; no allowlist, check denylist
	; if allowlist/extension/callsign exists, connect
	same => n,GotoIf(${DB_EXISTS(allowlist/${NODENUM}/${CALLSIGN})}?connect)            ; in allowlist, connect
	same => n,NoOp(${CALLSIGN} not in allowlist, Hangup)
	same => n,Hangup

	; if denylist/extension/callsign doesn't exist, connect
	same => n(denylist),GotoIf(${DB_EXISTS(denylist/${NODENUM}/${CALLSIGN})}?:connect) ; not in denylist, connect
	same => n,NoOp(${CALLSIGN} is in denylist, Hangup)
	same => n,Hangup

	; connect!
	same => n(connect),Set(CALLERID(name)=${CALLSIGN})
	same => n,Set(CALLERID(num)=0)
	same => n,Wait(3)
	same => n,Playback(rpt/connected-to&rpt/node,noanswer)
	same => n,SayDigits(${NODENUM})
	same => n,Rpt(${NODENUM},X)
	same => n,Hangup

	; hangup!
	same => n(hangit),Answer
	same => n,Wait(1)
	same => n,Hangup

[telemetry]
;  
; This stanza and extensions are used by "app_rpt" to play a telemetry 
; file (e.g. tailmessages).  
;  
; The following TAIL extension provides support for playing messages after  
; keying.  If this extension does not exist, app_rpt will play the telemetry  
; based on the rpt.conf "tailmessagelist" variable.  
; 
; An equivalent to the rpt.conf "tailmessage" configuration follows:  
; Modify the TAILFILES value to contain the list of tail files separated with ",".  
;  
;exten => TAIL,1,Set(TAILFILES=custom/yourtailmsg,/tmp/yourothertailmsg) ; add , separated tail files to play
;	same => n,Set(index=$[${GLOBAL(TAILFILEINDEX)} % ${FIELDQTY(TAILFILES,\,)} + 1])
;	same => n,Set(file=${CUT(TAILFILES,\,,${index})})
;	same => n,Playback(${file})
;	same => n,Set(GLOBAL(TAILFILEINDEX)=$[${TAILFILEINDEX} + 1]) 
;	same => n,Hangup() 

; Customization to the tail message is possible by adding to this extension as follows:
;exten => TAIL,1,Set(TAILFILES=custom/yourtailmsg,/tmp/yourothertailmsg) ; add , separated tail files to play
;	same => n,Set(index=$[${GLOBAL(TAILFILEINDEX)} % ${FIELDQTY(TAILFILES,\,)} + 1])
;	same => n,Set(file=${CUT(TAILFILES,\,,${index})})
;	same => n,Playback(${file})
; 	;after playing the tail message, play a weather announcement
;  	same => n,Playback(/tmp/current-weather)
;  	;after playing the weather announcement, play a traffic announcement
;  	same => n,Playback(/tmp/current-traffic)
;	same => n,Set(GLOBAL(TAILFILEINDEX)=$[${TAILFILEINDEX} + 1]) 
;  	same => n,Hangup()

; Say the time of day
exten => TIME,1,ExecIfTime(0:00-11:59,*,*,*?Playback(rpt/goodmorning))
	same => n,ExecIfTime(12:00-17:59,*,*,*?Playback(rpt/goodafternoon))
	same => n,ExecIfTime(18:00-23:59,*,*,*?Playback(rpt/goodevening))
	same => n,Playback(rpt/thetimeis)
	same => n,SayUnixTime(RPT_TELEM_TIME(),,IMp) ; Standard "say time"
	;same => n,SayUnixTime(RPT_TELEM_TIME(),,${IF($[${STRFTIME(${UNIXTIME},,%-M) = 0}]?IMp:Ip)}) ; Alternate "say time" without o'clock
	same => n,Hangup()

#tryinclude "custom/extensions.conf"

; >>> dvs-phone (managed by asl_dvs_dashboard - edits inside are overwritten) >>>
#tryinclude dvs_phone_extensions.conf
; <<< dvs-phone <<<
```

### /etc/asterisk/iax.conf

```
; Inter-Asterisk eXchange driver definition

[general]
; !!! IAX registration will be discontinued at some point !!!
; Setup rpt_http_registrations.conf instead.
; remove the leading ";"
;register => 652702:<redacted:77b33f97>@register.allstarlink.org    ; This must be changed to your node number, password 
;register => 652702:<redacted:10c828f3>@register.allstarlink.org

bindport = 4569                 ; bindport and bindaddr may be specified

; NOTE: bindport must be specified BEFORE
; bindaddr or may be specified on a specific
; bindaddr if followed by colon and port
;  (e.g. bindaddr=198.51.100.2:4569)

; bindaddr = 198.51.100.2        ; more than once to bind to multiple
 ;bindaddr = 198.51.100.3
bindaddr = 0.0.0.0
                                ; addresses, but the first will be the 
                                ; default

disallow = all                  ; The permitted codecs for outgoing connections 
;Audio Quality   Bandwidth
;allow = ulaw                   ; best      87 kbps
;allow = adpcm                  ; good      55 kbps
;allow = gsm                    ; mediocre  36 kbps
allow = ulaw
allow = adpcm
;allow = g722
;allow = g726aal2
allow = gsm
;allow = ilbc


jitterbuffer = yes
forcejitterbuffer = yes                                                           
dropcount = 2                                                                     
maxjitterbuffer = 1000                                                            
maxjitterinterps = 10                                                             
resyncthreshold = 500           ; set to -1 to disable                                                           
maxexcessbuffer = 80                                                              
minexcessbuffer = 10                                                              
jittershrinkrate = 1                                                              
tos = 0x1E                                                                  
autokill = yes                                                                    
delayreject = yes                                                                 
; iaxthreadcount = 30                                                              
; iaxmaxthreadcount = 150   

maxcallnumbers_nonvalidated = 10 ; Reduce the security threat of not using call tokens (iaxRpt)
                                 ; by limiting connections, adjust as reasonable for your system

; Incoming radio connections

[radio]
type = user
disallow = all
allow = ulaw
allow = adpcm
;allow = g722
;allow = g726aal2
allow = gsm
;allow = ilbc
codecpriority = host
context = radio-secure
transfer = no

; The (!) for the [iaxrpt](!) section indicates this is a template. As such, we can store the 
; actual users to authenticate in a separate file, to keep from cluttering up iax.conf.
; The actual file used to store the users is included with the #tryinclude directive below.
[iaxrpt]                      ; Connect from iaxrpt Username field (PC AllStar Client (iaxRpt))
type = user                      ; Notice type is user here <---------------
context = iaxrpt                 ; Context to jump to in extensions.conf
auth = md5
host = dynamic
secret = <redacted:10c828f3>
disallow = all
;allow = slin16                   ; un-comment to allow high-fidelity codec (make sure to load module)
;allow = slin                     ; un-comment to allow high-fidelity codec (make sure to load module)
allow = ulaw
allow = adpcm
allow = gsm                       
transfer = no
requirecalltoken = <redacted:b4596763>
; Source the users to authenticate from here:
#tryinclude custom/iax/iaxrpt-users.conf      ; PC clients to authenticate

; The (!) for the [iaxclient](!) section indicates this is a template. As such, we can store the 
; actual users to authenticate in a separate file, to keep from cluttering up iax.conf.
; The actual file used to store the users is included with the #tryinclude directive below.
[iaxclient]                   ; Connect from iax client (Zoiper,DVSwitch Mobile, etc.)
type = friend                    ; Notice type here is friend <--------------
context = iax-client             ; Context to jump to in extensions.conf
auth = md5
host = dynamic
secret = <redacted:10c828f3>
disallow = all
;allow = slin16                   ; un-comment to allow high-fidelity codec (make sure to load module)
;allow = slin                     ; un-comment to allow high-fidelity codec (make sure to load module)
allow = ulaw
allow = adpcm
allow = gsm
transfer = no
; Source the users to authenticate from here:
#tryinclude custom/iax/iaxclient-users.conf    ; Mobile clients to authenticate

[allstar-sys]
type = user
context = allstar-sys
auth = rsa
inkeys = allstar
disallow = all
allow = ulaw
allow = adpcm
allow = gsm

[allstar-public]
type = user
context = allstar-public
auth = md5
secret = <redacted:df6dfb4c>
disallow = all
;calltokenoptional=<redacted:04e931b7>
requirecalltoken = <redacted:73fa6bc1>
allow = ulaw
allow = adpcm
allow = gsm

; The following should be un-commented to support Allstar Autopatch service
; [allstar-autopatch]
; type = peer
; host = register.allstarlink.org
; username = <One of the Node numbers on this server>
; secret = <redacted:08675d61>
; auth = md5
; disallow = all
; allow = ulaw
; transfer = no

#tryinclude "custom/iax.conf"
```

### /etc/asterisk/logger.conf

```
;
; Logging Configuration
;
[general]
dateformat=%F %T.%3q   ; with milliseconds

[logfiles]
;
; Format is "filename" and then "levels" of debugging to be included:
;    debug
;    notice
;    warning
;    error
;
; Special filename "console" represents the system console
;
;debug.log => debug
console => notice,warning,error,dtmf,debug,verbose
;console => notice,warning,error,dtmf
messages.log => notice,warning,error,dtmf
```

### /etc/asterisk/manager.conf

```
;
; Asterisk Call Management support
;

; By default asterisk will listen on localhost only. 
[general]
enabled = yes
port = 5038
bindaddr = 127.0.0.1				; Comment when not localhost access
									
[kd8pgk]
secret = <redacted:10c828f3>
read = all,system,call,log,verbose,command,agent,user,config
write = all,system,call,log,verbose,command,agent,user,config
;deny = 0.0.0.0/0.0.0.0				; Uncomment when not localhost
;permit=198.51.100.4/255.255.255.255     ; Uncomment when not localhost
```

### /etc/asterisk/modules.conf

```
;
; Asterisk module loading configuration file
;

;
; You can enable or disable any of the asterisk modules
;
; To enable a module, use  : load = module_name.so
; To disable a module, use : noload = module_name.so
;

;
; For ASL (app_rpt), you need to enable the channel driver modules you will
; be using. You will find the modules in the "Channel Driver" section, below.
;
; The most common ASL (app_rpt) channel drivers are:
;
;   chan_dahdi.so      DAHDI Telephony
;   chan_echolink.so   Echolink Channel Driver
;   chan_simpleusb.so  Simple USB Radio Interface Channel Driver
;   chan_usbradio.so   USB Console Channel Driver
;   chan_usrp.so       USRP Channel Module
;   chan_voter.so      Voter Radio Channel Driver
;

[modules]
autoload = no

;load = func_frame_trace                ; Debug

; Applications

load    = app_authenticate.so            ; Authentication Application
load    = app_dial.so                    ; Dialing Application
load    = app_exec.so                    ; Executes dialplan applications
noload  = app_gps.so                     ; GPS Interface
load    = app_playback.so                ; Sound File Playback Application
require = app_rpt.so                     ; Radio Repeater/Remote Base Application
load    = app_sayunixtime.so             ; Say time
load    = app_sendtext.so                ; Send and Receive Text Applications
load    = app_system.so                  ; Generic System() application
load    = app_transfer.so                ; Transfers a caller to another extension

; Bridging

require = bridge_softmix.so              ; Multi-party software based channel mixing

; Channel Drivers

require = chan_bridge_media.so           ; Bridge Media Channel Driver
noload  = chan_dahdi.so                  ; DAHDI Telephony w/PRI & SS7 & MFC/R2
noload  = chan_echolink.so               ; Echolink Channel Driver
require = chan_iax2.so                   ; Inter Asterisk eXchange (Ver 2)
noload  = chan_mobile.so                 ; Bluetooth Mobile Device Channel Driver
noload  = chan_ooh323.so                 ; Objective Systems H323 Channel
load    = chan_simpleusb.so              ; SimpleUSB Radio Interface Channel Driver
noload  = chan_tlb.so                    ; TheLinkBox Channel Driver
noload  = chan_usbradio.so               ; USB Console Channel Driver
load  = chan_usrp.so                   ; USRP Channel Module
noload  = chan_voter.so                  ; Voter Radio Channel Driver

; Codecs

; CODEC          AUDIO QUALITY   BANDWIDTH (including IP and Ethernet headers)
; ULAW           best            87 kilobits per second (kbps)
; ADPCM          good            55 kbps
; GSM            mediocre        36 kbps
; g726aal2
; ilbc

load    = codec_adpcm.so                 ; Adaptive Differential PCM Coder/Decoder
load    = codec_alaw.so                  ; A-law Coder/Decoder
load    = codec_a_mu.so                  ; A-law and Mulaw direct Coder/Decoder
noload  = codec_dahdi.so                 ; Generic DAHDI Transcoder Codec Translator
noload  = codec_g722.so                  ; ITU G.722-64kbps G722 Transcoder
load    = codec_g726.so                  ; ITU G.726-32kbps G726 Transcoder
load    = codec_gsm.so                   ; GSM Coder/Decoder
noload  = codec_resample.so              ; SLIN Resampling Codec
load    = codec_ulaw.so                  ; mu-Law Coder/Decoder

; Formats

load    = format_g723.so                 ; G.723.1 Simple Timestamp File Format
load    = format_g726.so                 ; Raw G.726 (16/24/32/40kbps) data
noload  = format_g729.so                 ; Raw G.729 data
load    = format_gsm.so                  ; Raw GSM data
load    = format_h263.so                 ; Raw H.263 data
load    = format_h264.so                 ; Raw H.264 data
load    = format_ilbc.so                 ; Raw iLBC data
load    = format_mp3.so                  ; MP3 format [Any rate but 8000hz mono is optimal]
load    = format_pcm.so                  ; Raw/Sun uLaw/ALaw 8KHz (PCM,PCMA,AU), G.722 16Khz
load    = format_sln.so                  ; Raw Signed Linear Audio support (SLN) 8khz-192khz
load    = format_vox.so                  ; Dialogic VOX (ADPCM) File Format
load    = format_wav_gsm.so              ; Microsoft WAV format (Proprietary GSM)
load    = format_wav.so                  ; Microsoft WAV/WAV16 format (8kHz/16kHz Signed Linear)

; Functions

load    = func_base64.so                 ; base64 encode/decode dialplan functions
load    = func_callerid.so               ; Party ID related dialplan functions (Caller-ID, Connected-line, Redirecting)
load    = func_cdr.so                    ; Call Detail Record (CDR) dialplan functions
load    = func_channel.so                ; Channel information dialplan functions
load    = func_curl.so                   ; Load external URL
load    = func_cut.so                    ; Cut out information from a string
load    = func_db.so                     ; Database (astdb) related dialplan functions
load    = func_enum.so                   ; ENUM related dialplan functions
load    = func_env.so                    ; Environment/filesystem dialplan functions
load    = func_global.so                 ; Variable dialplan functions
load    = func_groupcount.so             ; Channel group dialplan functions
load    = func_logic.so                  ; Logical dialplan functions
load    = func_math.so                   ; Mathematical dialplan function
load    = func_md5.so                    ; MD5 digest dialplan functions
load    = func_rand.so                   ; Random number dialplan function
load    = func_realtime.so               ; Read/Write/Store/Destroy values from a RealTime repository
noload  = func_sha1.so                   ; SHA-1 computation dialplan function
load    = func_strings.so                ; String handling dialplan functions
noload  = func_timeout.so                ; Channel timeout dialplan functions
noload  = func_uri.so                    ; URI encode/decode dialplan functions

; Core/PBX

load    = pbx_config.so                  ; Text Extension Configuration

; Resources

load    = res_crypto.so                  ; Cryptographic Digital Signatures
require = res_curl.so                    ; cURL Resource Module
require = res_rpt_http_registrations.so  ; RPT HTTP Periodic Registrations
noload  = res_timing_dahdi.so            ; DAHDI Timing Interface
load    = res_timing_timerfd.so          ; Timerfd Timing Interface is preferred for ASL3
require = res_usbradio.so                ; USB Radio Resource

;
; The following modules are used by configurations that are setup for
; an "autopatch" or support SIP phones.  If needed, uncomment each of
; the following lines (by removing the leading ";").
;
;load   = bridge_builtin_features.so                  ; Built in bridging features
;load   = bridge_builtin_interval_features.so         ; Built in bridging interval features
;load   = bridge_holding.so                           ; Holding bridge module
;load   = bridge_native_rtp.so                        ; Native RTP bridging module
;load   = bridge_simple.so                            ; Simple two channel bridging module
;load   = chan_pjsip.so                               ; PJSIP Channel Driver
;load   = func_pjsip_endpoint.so                      ; Get information about a PJSIP endpoint
;load   = func_sorcery.so                             ; Get a field from a sorcery object
;load   = func_devstate.so                            ; Gets or sets a device state in the dialplan
;load   = res_pjproject.so                            ; PJPROJECT Log and Utility Support
;load   = res_pjsip_acl.so                            ; PJSIP ACL Resource
;load   = res_pjsip_authenticator_digest.so           ; PJSIP authentication resource
;load   = res_pjsip_caller_id.so                      ; PJSIP Caller ID Support
;load   = res_pjsip_dialog_info_body_generator.so     ; PJSIP Extension State Dialog Info+XML Provider
;load   = res_pjsip_diversion.so                      ; PJSIP Add Diversion Header Support
;load   = res_pjsip_dtmf_info.so                      ; PJSIP DTMF INFO Support
;load   = res_pjsip_endpoint_identifier_anonymous.so  ; PJSIP Anonymous endpoint identifier
;load   = res_pjsip_endpoint_identifier_ip.so         ; PJSIP IP endpoint identifier
;load   = res_pjsip_endpoint_identifier_user.so       ; PJSIP username endpoint identifier
;load   = res_pjsip_exten_state.so                    ; PJSIP Extension State Notifications
;load   = res_pjsip_header_funcs.so                   ; PJSIP Header Functions
;load   = res_pjsip_logger.so                         ; PJSIP Packet Logger
;load   = res_pjsip_messaging.so                      ; PJSIP Messaging Support
;load   = res_pjsip_mwi_body_generator.so             ; PJSIP MWI resource
;load   = res_pjsip_mwi.so                            ; PJSIP MWI resource
;load   = res_pjsip_nat.so                            ; PJSIP NAT Support
;load   = res_pjsip_notify.so                         ; CLI/AMI PJSIP NOTIFY Support
;load   = res_pjsip_one_touch_record_info.so          ; PJSIP INFO One Touch Recording Support
;load   = res_pjsip_outbound_authenticator_digest.so  ; PJSIP authentication resource
;load   = res_pjsip_outbound_publish.so               ; PJSIP Outbound Publish Support
;load   = res_pjsip_outbound_registration.so          ; PJSIP Outbound Registration Support
;load   = res_pjsip_path.so                           ; PJSIP Path Header Support
;load   = res_pjsip_pidf_body_generator.so            ; PJSIP Extension State PIDF Provider
;load   = res_pjsip_pidf_digium_body_supplement.so    ; PJSIP PIDF Sangoma presence supplement
;load   = res_pjsip_pidf_eyebeam_body_supplement.so   ; PJSIP PIDF Eyebeam supplement
;load   = res_pjsip_publish_asterisk.so               ; PJSIP Asterisk Event PUBLISH Support
;load   = res_pjsip_pubsub.so                         ; PJSIP event resource
;load   = res_pjsip_refer.so                          ; PJSIP Blind and Attended Transfer Support
;load   = res_pjsip_registrar.so                      ; PJSIP Registrar Support
;load   = res_pjsip_rfc3326.so                        ; PJSIP RFC3326 Support
;load   = res_pjsip_sdp_rtp.so                        ; PJSIP SDP RTP/AVP stream handler
;load   = res_pjsip_send_to_voicemail.so              ; PJSIP REFER Send to Voicemail Support
;load   = res_pjsip_session.so                        ; PJSIP Session resource
;load   = res_pjsip.so                                ; Basic SIP resource
;noload = res_pjsip_t38.so                            ; PJSIP T.38 UDPTL Support
;noload = res_pjsip_transport_websocket.so            ; PJSIP WebSocket Transport Support
;load   = res_pjsip_xpidf_body_generator.so           ; PJSIP Extension State PIDF Provider
;load   = res_rtp_asterisk.so                         ; Asterisk RTP Stack
;load   = res_sorcery_astdb.so                        ; Sorcery Astdb Object Wizard
;load   = res_sorcery_config.so                       ; Sorcery Configuration File Object Wizard
;load   = res_sorcery_memory.so                       ; Sorcery In-Memory Object Wizard
;load   = res_sorcery_realtime.so                     ; Sorcery Realtime Object Wizard

; >>> dvs-phone (managed by asl_dvs_dashboard - edits inside are overwritten) >>>
load => bridge_builtin_features.so
load => bridge_builtin_interval_features.so
load => bridge_holding.so
load => bridge_native_rtp.so
load => bridge_simple.so
load => bridge_softmix.so
load => chan_bridge_media.so
load => app_verbose.so
load => app_read.so
load => app_system.so
load => func_callerid.so
load => app_senddtmf.so
load => app_chanspy.so
load => app_playback.so
load => format_pcm.so
load => chan_pjsip.so
load => func_pjsip_endpoint.so
load => func_sorcery.so
load => func_devstate.so
load => res_pjproject.so
load => res_pjsip_acl.so
load => res_pjsip_authenticator_digest.so
load => res_pjsip_caller_id.so
load => res_pjsip_diversion.so
load => res_pjsip_dtmf_info.so
load => res_pjsip_endpoint_identifier_anonymous.so
load => res_pjsip_endpoint_identifier_ip.so
load => res_pjsip_endpoint_identifier_user.so
load => res_pjsip_exten_state.so
load => res_pjsip_header_funcs.so
load => res_pjsip_logger.so
load => res_pjsip_messaging.so
load => res_pjsip_nat.so
load => res_pjsip_notify.so
load => res_pjsip_outbound_authenticator_digest.so
load => res_pjsip_outbound_registration.so
load => res_pjsip_path.so
load => res_pjsip_pubsub.so
load => res_pjsip_refer.so
load => res_pjsip_registrar.so
load => res_pjsip_rfc3326.so
load => res_pjsip_sdp_rtp.so
load => res_pjsip_session.so
load => res_pjsip.so
load => res_rtp_asterisk.so
load => res_sorcery_astdb.so
load => res_sorcery_config.so
load => res_sorcery_memory.so
load => res_sorcery_realtime.so
; <<< dvs-phone <<<
```

### /etc/asterisk/pjsip.conf

```
; PJSIP Configuration Samples and Quick Reference
;
; This file has several very basic configuration examples, to serve as a quick
; reference to jog your memory when you need to write up a new configuration.
; It is not intended to teach PJSIP configuration or serve as an exhaustive
; reference of options and potential scenarios.
;
; This file has two main sections.
; First, manually written examples to serve as a handy reference.
; Second, a list of all possible PJSIP config options by section. This is
; pulled from the XML config help. It only shows the synopsis for every item.
; If you want to see more detail please check the documentation sources
; mentioned at the top of this file.

; ============================================================================
; NOTICE NOTICE NOTICE NOTICE NOTICE NOTICE NOTICE NOTICE NOTICE NOTICE
;
; This file does not maintain the complete option documentation.
; ============================================================================

; Documentation
;
; The official documentation is at https://docs.asterisk.org
; You can read the XML configuration help via Asterisk command line with
; "config show help res_pjsip", then you can drill down through the various
; sections and their options.
;

;========!!!!!!!!!!!!!!!!!!!  SECURITY NOTICE  !!!!!!!!!!!!!!!!!!!!===========
;
; At a minimum please read the file "README-SERIOUSLY.bestpractices.txt",
; located in the Asterisk source directory before starting Asterisk.
; Otherwise you risk allowing the security of the Asterisk system to be
; compromised. Beyond that please visit and read the security information in
; the documentation at: https://docs.asterisk.org/Deployment/Important-Security-Considerations/
;
; A few basics to pay attention to:
;
; Anonymous Calls
;
; By default anonymous inbound calls via PJSIP are not allowed. If you want to
; route anonymous calls you'll need to define an endpoint named "anonymous".
; res_pjsip_endpoint_identifier_anonymous.so handles that functionality so it
; must be loaded. It is not recommended to accept anonymous calls.
;
; Access Control Lists
;
; See the example ACL configuration in this file. Read the configuration help
; for the section and all of its options. Look over the samples in acl.conf
; and documentation at https://docs.asterisk.org/Configuration/Core-Configuration/Named-ACLs/
; If possible, restrict access to only networks and addresses you trust.
;
; Dialplan Contexts
;
; When defining configuration (such as an endpoint) that links into
; dialplan configuration, be aware of what that dialplan does. It's easy to
; accidentally provide access to internal or outbound dialing extensions which
; could cost you severely. The "context=" line in endpoint configuration
; determines which dialplan context inbound calls will enter into.
;
;=============================================================================

; Overview of Configuration Section Types Used in the Examples
;
; * Transport "transport"
;   * Configures res_pjsip transport layer interaction.
; * Endpoint "endpoint"
;   * Configures core SIP functionality related to SIP endpoints.
; * Authentication "auth"
;   * Stores inbound or outbound authentication credentials for use by trunks,
;     endpoints, registrations.
; * Address of Record "aor"
;   * Stores contact information for use by endpoints.
; * Endpoint Identification "identify"
;   * Maps a host directly to an endpoint
; * Access Control List "acl"
;   * Defines a permission list or references one stored in acl.conf
; * Registration "registration"
;   * Contains information about an outbound SIP registration
; * Resource Lists
;   * Contains information for configuring resource lists.
; * Phone Provisioning "phoneprov"
;   * Contains information needed by res_phoneprov for autoprovisioning

; The following sections show example configurations for various scenarios.
; Most require a couple or more configuration types configured in concert.

;=============================================================================

; Naming of Configuration Sections
;
; Configuration section names are denoted with enclosing brackets,
; e.g. [6001]
; In most cases, you can name a section whatever makes sense to you. For example
; you might name a transport [transport-udp-nat] to help you remember how that
; section is being used. However, in some cases, ("endpoint" and "aor" types)
; the section name has a relationship to its function.
;
; Depending on the modules loaded, Asterisk can match SIP requests to an
; endpoint or aor in a few ways:
;
; 1) Match a section name for endpoint type sections to the username in the
;    "From" header of inbound SIP requests.
; 2) Match a section name for aor type sections to the username in the "To"
;    header of inbound SIP REGISTER requests.
; 3) With an identify type section configured, match an inbound SIP request of
;    any type to an endpoint or aor based on the IP source address of the
;    request.
;
; Note that sections can have the same name as long as their "type" options are
; set to different values. In most cases it makes sense to have associated
; configuration sections use the same name, as you'll see in the examples within
; this file.

;===============EXAMPLE TRANSPORTS============================================
;
; A few examples for potential transport options.
;
; For the NAT transport example, be aware that the options starting with
; the prefix "external_" will only apply to communication with addresses
; outside the range set with "local_net=".
;
; You can have more than one of any type of transport, as long as it doesn't
; use the same resources (bind address, port, etc) as the others.

; Basic UDP transport
;
;[transport-udp]
;type=transport
;protocol=udp    ;udp,tcp,tls,ws,wss,flow
;bind=0.0.0.0

; UDP transport behind NAT
;
;[transport-udp-nat]
;type=transport
;protocol=udp
;bind=0.0.0.0
;local_net=198.51.100.5/24
;external_media_address=198.51.100.6
;external_signaling_address=198.51.100.6

; Basic IPv6 UDP transport
;
;[transport-udp-ipv6]
;type=transport
;protocol=udp
;bind=::

; Example IPv4 TLS transport
;
;[transport-tls]
;type=transport
;protocol=tls
;bind=0.0.0.0
;cert_file=/path/mycert.crt
;priv_key_file=/path/mykey.key
;cipher=ADH-AES256-SHA,ADH-AES128-SHA
;method=tlsv1

; Example flow transport
;
; A flow transport is used to reference a flow of signaling with a specific
; target. All endpoints or other objects that reference the transport will use
; the same underlying transport and can share runtime discovered transport
; configuration (such as service routes). The protocol in use will be determined
; based on the URI used to establish the connection. Currently only TCP and TLS
; are supported.
;
;[transport-flow]
;type=transport
;protocol=flow

; Example IPv4 TCP transport with Keepalive options
;
;[transport-tcp]
;type=transport
;protocol=tcp
;bind=0.0.0.0
;tcp_keepalive_enable=yes        ; Enable TCP keepalive (yes/no)
;tcp_keepalive_idle_time=30      ; Time in seconds the connection needs to remain idle before TCP starts sending keepalive probes
;tcp_keepalive_interval_time=10  ; The time in seconds between individual keepalive probes
;tcp_keepalive_probe_count=5     ; The maximum number of keepalive probes TCP should send before dropping the connection

; Example IPv4 TLS transport with Keepalive options
;
;[transport-tls]
;type=transport
;protocol=tls
;bind=0.0.0.0
;cert_file=/path/to/mycert.crt
;priv_key_file=/path/to/mykey.key
;cipher=ADH-AES256-SHA,ADH-AES128-SHA
;method=tlsv1
;tcp_keepalive_enable=yes        ; Enable TCP keepalive (yes/no)
;tcp_keepalive_idle_time=30      ; Time in seconds the connection needs to remain idle before TCP starts sending keepalive probes
;tcp_keepalive_interval_time=10  ; The time in seconds between individual keepalive probes
;tcp_keepalive_probe_count=5     ; The maximum number of keepalive probes TCP should send before dropping the connection

;===============OUTBOUND REGISTRATION WITH OUTBOUND AUTHENTICATION============
;
; This is a simple registration that works with some SIP trunking providers.
; You'll need to set up the auth example "mytrunk_auth" below to enable outbound
; authentication. Note that we use "outbound_auth=" for outbound authentication
; instead of "auth=", which is for inbound authentication.
;
; If you are registering to a server from behind NAT, be sure you assign a transport
; that is appropriately configured with NAT related settings. See the NAT transport example.
;
; "contact_user=" sets the SIP contact header's user portion of the SIP URI
; this will affect the extension reached in dialplan when the far end calls you at this
; registration. The default is 's'.
;
; If you would like to enable line support and have incoming calls related to this
; registration go to an endpoint automatically the "line" and "endpoint" options must
; be set. The "endpoint" option specifies what endpoint the incoming call should be
; associated with.

;[mytrunk]
;type=registration
;transport=transport-udp
;outbound_auth=mytrunk_auth
;server_uri=sip:sip.example.com
;client_uri=sip:<redacted:aac6ed68>
;contact_user=1234567890
;retry_interval=60
;forbidden_retry_interval=600
;expiration=3600
;line=yes
;endpoint=mytrunk

;[mytrunk_auth]
;type=auth
;auth_type=userpass
;password=<redacted:23dd86a9>
;username=1234567890
;realm=sip.example.com

;===============ENDPOINT CONFIGURED AS A TRUNK, OUTBOUND AUTHENTICATION=======
;
; This is one way to configure an endpoint as a trunk. It is set up with
; "outbound_auth=" to enable authentication when dialing out through this
; endpoint. There is no inbound authentication set up since a provider will
; not normally authenticate when calling you.
;
; The identify configuration enables IP address matching against this endpoint.
; For calls from a trunking provider, the From user may be different every time,
; so we want to match against IP address instead of From user.
;
; If you want the provider of your trunk to know where to send your calls
; you'll need to use an outbound registration as in the example above this
; section.
;
; NAT
;
; At a basic level configure the endpoint with a transport that is set up
; with the appropriate NAT settings. There may be some additional settings you
; need here based on your NAT/Firewall scenario. Look to the CLI config help
; "config show help res_pjsip endpoint" or on https://docs.asterisk.org/ for
; other NAT related options and configuration. We've included a few below.
;
; AOR
;
; Endpoints use one or more AOR sections to store their contact details.
; You can define multiple contact addresses in SIP URI format in multiple
; "contact=" entries.
;

;[mytrunk]
;type=endpoint
;transport=transport-udp
;context=from-external
;disallow=all
;allow=ulaw
;outbound_auth=mytrunk_auth
;aors=mytrunk
;                   ;A few NAT relevant options that may come in handy.
;force_rport=yes    ;It's a good idea to read the configuration help for each
;direct_media=no    ;of these options.
;ice_support=yes

;[mytrunk]
;type=aor
;contact=sip:198.51.100.7:5060
;contact=sip:198.51.100.8:5060

;[mytrunk]
;type=identify
;endpoint=mytrunk
;match=198.51.100.7
;match=198.51.100.8
;match=198.51.100.9:5061/24


;=============ENDPOINT CONFIGURED AS A TRUNK, INBOUND AUTH AND REGISTRATION===
;
; Here we are allowing a remote device to register to Asterisk and requiring
; that they authenticate for registration and calls.
; You'll note that this configuration is essentially the same as configuring
; an endpoint for use with a SIP phone.


;[7000]
;type=endpoint
;context=from-external
;disallow=all
;allow=ulaw
;transport=transport-udp
;auth=7000
;aors=7000

;[7000]
;type=auth
;auth_type=userpass
;password=<redacted:ecfd9804>
;username=7000

;[7000]
;type=aor
;max_contacts=1


;===============ENDPOINT CONFIGURED FOR USE WITH A SIP PHONE==================
;
; This example includes the endpoint, auth and aor configurations. It
; requires inbound authentication and allows registration, as well as references
; a transport that you'll need to uncomment from the previous examples.
;
; Uncomment one of the transport lines to choose which transport you want. If
; not specified then the default transport chosen is the first compatible transport
; in the configuration file for the contact URL.
;
; Modify the "max_contacts=" line to change how many unique registrations to allow.
;
; Use the "contact=" line instead of max_contacts= if you want to statically
; define the location of the device.
;
; If using the TLS enabled transport, you may want the "media_encryption=sdes"
; option to additionally enable SRTP, though they are not mutually inclusive.
;
; If this endpoint were remote, and it was using a transport configured for NAT
; then you likely want to use "direct_media=no" to prevent audio issues.


;[6001]
;type=endpoint
;transport=transport-udp
;context=from-internal
;disallow=all
;allow=ulaw
;allow=gsm
;auth=6001
;aors=6001
;
; A few more transports to pick from, and some related options below them.
;
;transport=transport-tls
;media_encryption=sdes
;transport=transport-udp-ipv6
;transport=transport-udp-nat
;direct_media=no
;
; MWI related options

;aggregate_mwi=yes
;mailboxes=6001@default,7001@default
;mwi_from_user=6001
;
; Extension and Device state options
;
;device_state_busy_at=1
;allow_subscribe=yes
;sub_min_expiry=30
;
; STIR/SHAKEN support.
;
;stir_shaken=no
;stir_shaken_profile=my_profile

;[6001]
;type=auth
;auth_type=userpass
;password=<redacted:149a3001>
;username=6001

;[6001]
;type=aor
;max_contacts=1
;contact=sip:<redacted:3e859c22>:5060

;===============ENDPOINT BEHIND NAT OR FIREWALL===============================
;
; This example assumes your transport is configured with a public IP and the
; endpoint itself is behind NAT and maybe a firewall, rather than having
; Asterisk behind NAT. For the sake of simplicity, we'll assume a typical
; VOIP phone. The most important settings to configure are:
;
;  * direct_media, to ensure Asterisk stays in the media path
;  * rtp_symmetric and force_rport options to help the far-end NAT/firewall
;
; Depending on the settings of your remote SIP device or NAT/firewall device
; you may have to experiment with a combination of these settings.
;
; If both Asterisk and the remote phones are a behind NAT/firewall then you'll
; have to make sure to use a transport with appropriate settings (as in the
; transport-udp-nat example).
;
;[6002]
;type=endpoint
;transport=transport-udp
;context=from-internal
;disallow=all
;allow=ulaw
;auth=6002
;aors=6002
;direct_media=no
;rtp_symmetric=yes
;force_rport=yes
;rewrite_contact=yes  ; necessary if endpoint does not know/register public ip:port
;ice_support=yes   ;This is specific to clients that support NAT traversal
                   ;for media via ICE,STUN,TURN. See the docs at:
                   ;https://docs.asterisk.org/Configuration/Miscellaneous/Interactive-Connectivity-Establishment-ICE-in-Asterisk/
                   ;for a deeper explanation of this topic.

;[6002]
;type=auth
;auth_type=userpass
;password=<redacted:4bbe0667>
;username=6002

;[6002]
;type=aor
;max_contacts=2

;===============DEFAULT ENDPOINT FOR OUTBOUND REQUESTS TO URI===================
;
; This is an example default outbound endpoint.  The global setting:
; default_outbound_endpoint needs to be set to such an endpoint in order to be
; able to send an outbound request to a URI without a specified endpoint.
;
;[default_outbound_endpoint]
;type=endpoint
;context=none-invalid


;============EXAMPLE ACL CONFIGURATION==========================================
;
; The ACL or Access Control List section defines a set of permissions to permit
; or deny access to various address or addresses. Alternatively it references an
; ACL configuration already set in acl.conf.
;
; The ACL configuration is independent of individual endpoint configuration and
; operates on all inbound SIP communication using res_pjsip.

; Reference an ACL defined in acl.conf.
;
;[acl]
;type=acl
;acl=example_named_acl1

; Reference a contactacl specifically.
;
;[acl]
;type=acl
;contact_acl=example_contact_acl1

; Define your own ACL here in pjsip.conf and
; permit or deny by IP address or range.
;
;[acl]
;type=acl
;deny=0.0.0.0/0.0.0.0
;permit=198.51.100.10/24
;deny=198.51.100.11

; Restrict based on Contact Headers rather than IP.
; Define options multiple times for various addresses or use a comma-delimited string.
;
;[acl]
;type=acl
;contact_deny=0.0.0.0/0.0.0.0
;contact_permit=198.51.100.10/24
;contact_permit=198.51.100.11
;contact_permit=198.51.100.12,198.51.100.13

; Restrict based on Contact Headers rather than IP and use
; advanced syntax. Note the bang symbol used for "NOT", so we can deny
; 198.51.100.14/32 within the permit= statement.
;
;[acl]
;type=acl
;contact_deny=0.0.0.0/0.0.0.0
;contact_permit=198.51.100.10
;permit=198.51.100.10/24, !198.51.100.14/32


;============EXAMPLE RLS CONFIGURATION==========================================
;
;Asterisk provides support for RFC 4662 Resource List Subscriptions. This allows
;for an endpoint to, through a single subscription, subscribe to the states of
;multiple resources. Resource lists are configured in pjsip.conf using the
;resource_list configuration object. Below is an example of a resource list that
;allows an endpoint to subscribe to the presence of alice, bob, and carol.

;[my_list]
;type=resource_list
;list_item=alice
;list_item=bob
;list_item=carol
;event=presence

;The "event" option in the resource list corresponds to the SIP event-package
;that the subscribed resources belong to. A resource list can only provide states
;for resources that belong to the same event-package. This means that you cannot
;create a list that is a combination of presence and message-summary resources,
;for instance. Any event-package that Asterisk supports can be used in a resource
;list (presence, dialog, and message-summary). Whenever support for a new event-
;package is added to Asterisk, support for that event-package in resource lists
;will automatically be supported.

;The "list_item" options indicate the names of resources to subscribe to. The
;way these are interpreted is event-package specific. For instance, with presence
;list_items, hints in the dialplan are looked up. With message-summary list_items,
;mailboxes are looked up using your installed voicemail provider (app_voicemail
;by default). Note that in the above example, the list_item options were given
;one per line. However, it is also permissible to provide multiple list_item
;options on a single line (e.g. list_item = alice,bob,carol).

;In addition to the options presented in the above configuration, there are two
;more configuration options that can be set.
; * full_state: dictates whether Asterisk should always send the states of
;   all resources in the list at once. Defaults to "no". You should only set
;   this to "yes" if you are interoperating with an endpoint that does not
;   behave correctly when partial state notifications are sent to it.
; * notification_batch_interval: By default, Asterisk will send a NOTIFY request
;   immediately when a resource changes state. This option causes Asterisk to
;   start batching resource state changes for the specified number of milliseconds
;   after a resource changes states. This way, if multiple resources change state
;   within a brief interval, Asterisk can send a single NOTIFY request with all
;   of the state changes reflected in it.

;There is a limitation to the size of resource lists in Asterisk. If a constructed
;notification from Asterisk will exceed 64000 bytes, then the message is deemed
;too large to send. If you find that you are seeing error messages about SIP
;NOTIFY requests being too large to send, consider breaking your lists into
;sub-lists.

;============EXAMPLE PHONEPROV CONFIGURATION================================

; Before configuring provisioning here, see the documentation for res_phoneprov
; and configure phoneprov.conf appropriately.

; For each user to be autoprovisioned, a [phoneprov] configuration section
; must be created.  At a minimum, the 'type', 'PROFILE' and 'MAC' variables must
; be set.  All other variables are optional.
; Example:

;[1000]
;type=phoneprov               ; must be specified as 'phoneprov'
;endpoint=1000                ; Required only if automatic setting of
                              ; USERNAME, SECRET, DISPLAY_NAME and CALLERID
                              ; are needed.
;PROFILE=digium               ; required
;MAC=deadbeef4dad             ; required
;SERVER=myserver.example.com  ; A standard variable
;TIMEZONE=America/Denver      ; A standard variable
;MYVAR=somevalue              ; A user confdigured variable

; If the phoneprov sections have common variables, it is best to create a
; phoneprov template.  The example below will produce the same configuration
; as the one specified above except that MYVAR will be overridden for
; the specific user.
; Example:

;[phoneprov_defaults](!)
;type=phoneprov               ; must be specified as 'phoneprov'
;PROFILE=digium               ; required
;SERVER=myserver.example.com  ; A standard variable
;TIMEZONE=America/Denver      ; A standard variable
;MYVAR=somevalue              ; A user configured variable

;[1000](phoneprov_defaults)
;endpoint=1000                ; Required only if automatic setting of
                              ; USERNAME, SECRET, DISPLAY_NAME and CALLERID
                              ; are needed.
;MAC=deadbeef4dad             ; required
;MYVAR=someOTHERvalue         ; A user confdigured variable

; To have USERNAME and SECRET automatically set, the endpoint
; specified here must in turn have an outbound_auth section defined.

; Fuller example:

;[1000]
;type=endpoint
;outbound_auth=1000-auth
;callerid=My Name <8005551212>
;transport=transport-udp-nat

;[1000-auth]
;type=auth
;auth_type=userpass
;username=myname
;password=<redacted:7d4266e1>

;[phoneprov_defaults](!)
;type=phoneprov               ; must be specified as 'phoneprov'
;PROFILE=someprofile          ; required
;SERVER=myserver.example.com  ; A standard variable
;TIMEZONE=America/Denver      ; A standard variable
;MYVAR=somevalue              ; A user configured variable

;[1000](phoneprov_defaults)
;endpoint=1000                ; Required only if automatic setting of
                              ; USERNAME, SECRET, DISPLAY_NAME and CALLERID
                              ; are needed.
;MAC=deadbeef4dad             ; required
;MYVAR=someUSERvalue          ; A user confdigured variable
;LABEL=1000                   ; A standard variable

; The previous sections would produce a template substitution map as follows:

;MAC=deadbeef4dad               ;added by pp1000
;USERNAME=myname                ;automatically added by 1000-auth username
;SECRET=<redacted:7d4266e1>                ;automatically added by 1000-auth password
;PROFILE=someprofile            ;added by defaults
;SERVER=myserver.example.com    ;added by defaults
;SERVER_PORT=5060               ;added by defaults
;MYVAR=someUSERvalue            ;added by defaults but overdidden by user
;CALLERID=8005551212            ;automatically added by 1000 callerid
;DISPLAY_NAME=My Name           ;automatically added by 1000 callerid
;TIMEZONE=America/Denver        ;added by defaults
;TZOFFSET=252100                ;automatically calculated by res_phoneprov
;DST_ENABLE=1                   ;automatically calculated by res_phoneprov
;DST_START_MONTH=3              ;automatically calculated by res_phoneprov
;DST_START_MDAY=9               ;automatically calculated by res_phoneprov
;DST_START_HOUR=3               ;automatically calculated by res_phoneprov
;DST_END_MONTH=11               ;automatically calculated by res_phoneprov
;DST_END_MDAY=2                 ;automatically calculated by res_phoneprov
;DST_END_HOUR=1                 ;automatically calculated by res_phoneprov
;ENDPOINT_ID=1000               ;automatically added by this module
;AUTH_ID=1000-auth              ;automatically added by this module
;TRANSPORT_ID=transport-udp-nat ;automatically added by this module
;LABEL=1000                     ;added by user

; MODULE PROVIDING BELOW SECTION(S): res_pjsip
;==========================ENDPOINT SECTION OPTIONS=========================
;[endpoint]
;  SYNOPSIS: Endpoint
;100rel=yes     ; Allow support for RFC3262 provisional ACK tags (default:
                ; "yes")
;aggregate_mwi=yes      ;  (default: "yes")
;allow= ; Media Codec s to allow (default: "")
;allow_overlap=yes ; Enable RFC3578 overlap dialing support. (default: "yes")
;overlap_context=default ; Context to used for overlap dialing matches
                         ; (default: same as context option)
;aors=  ; AoR s to be used with the endpoint (default: "")
;auth=  ; Authentication Object s associated with the endpoint (default: "")
;callerid=      ; CallerID information for the endpoint (default: "")
;callerid_privacy=allowed_not_screened      ; Default privacy level (default: "allowed_not_screened")
;callerid_tag=  ; Internal id_tag for the endpoint (default: "")
;context=default        ; Dialplan context for inbound sessions (default:
                        ; "default")
;direct_media_glare_mitigation=none     ; Mitigation of direct media re INVITE
                                        ; glare (default: "none")
;direct_media_method=invite     ; Direct Media method type (default: "invite")
;trust_connected_line=yes       ; Accept Connected Line updates from this endpoint
                                ; (default: "yes")
;send_connected_line=yes        ; Send Connected Line updates to this endpoint
                                ; (default: "yes")
;connected_line_method=invite   ; Connected line method type.
                                ; When set to "invite", check the remote's
                                ; Allow header and if UPDATE is allowed, send
                                ; UPDATE instead of INVITE to avoid SDP
                                ; renegotiation.  If UPDATE is not Allowed,
                                ; send INVITE.
                                ; If set to "update", send UPDATE regardless
                                ; of what the remote Allows.
                                ; (default: "invite")
;direct_media=yes       ; Determines whether media may flow directly between
                        ; endpoints (default: "yes")
;disable_direct_media_on_nat=no ; Disable direct media session refreshes when
                                ; NAT obstructs the media session (default:
                                ; "no")
;disallow=      ; Media Codec s to disallow (default: "")
;dtmf_mode=rfc4733      ; DTMF mode (default: "rfc4733")
;media_address=         ; IP address used in SDP for media handling (default: "")
;bind_rtp_to_media_address=     ; Bind the RTP session to the media_address.
                                ; This causes all RTP packets to be sent from
                                ; the specified address. (default: "no")
;force_rport=yes        ; Force use of return port (default: "yes")
;ice_support=no ; Enable the ICE mechanism to help traverse NAT (default: "no")
;identify_by=username   ; A comma-separated list of ways the Endpoint or AoR can be
                        ; identified.
                        ; "username": Identify by the From or To username and domain
                        ; "auth_username": Identify by the Authorization username and realm
                        ; "ip": Identify by the source IP address
                        ; "header": Identify by a configured SIP header value.
                        ; "request_uri": Identify by the configured SIP request URI.
                        ; In the username and auth_username cases, if an exact match
                        ; on both username and domain/realm fails, the match is
                        ; retried with just the username.
                        ; (default: "username,ip")
;redirect_method=user   ; How redirects received from an endpoint are handled
                        ; (default: "user")
;follow_redirect_methods=   ; A comma-separated list of SIP methods for which redirects are followed.
                            ; Currently, only "message" is supported.
                            ; (default: "")
;mailboxes=     ; NOTIFY the endpoint when state changes for any of the specified mailboxes.
                ; Asterisk will send unsolicited MWI NOTIFY messages to the endpoint when state
                ; changes happen for any of the specified mailboxes. (default: "")
;voicemail_extension= ; The voicemail extension to send in the NOTIFY Message-Account header
                      ; (default: global/default_voicemail_extension)
;mwi_subscribe_replaces_unsolicited=no
                      ; An MWI subscribe will replace unsoliticed NOTIFYs
                      ; (default: "no")
;moh_suggest=default    ; Default Music On Hold class (default: "default")
;moh_passthrough=<redacted:96520373>    ; Pass Music On Hold through using SIP re-invites with sendonly
                        ; when placing on hold and sendrecv when taking off hold
;outbound_auth= ; Authentication object used for outbound requests (default:
                ; "")
;outbound_proxy=        ; Proxy through which to send requests, a full SIP URI
                        ; must be provided (default: "")
;rewrite_contact=no     ; Allow Contact header to be rewritten with the source
                        ; IP address port (default: "no")
;rtp_symmetric=no       ; Enforce that RTP must be symmetric (default: "no")
;send_diversion=yes     ; Send the Diversion header conveying the diversion
                        ; information to the called user agent (default: "yes")
;send_pai=no    ; Send the P Asserted Identity header (default: "no")
;send_rpid=no   ; Send the Remote Party ID header (default: "no")
;rpid_immediate=no      ; Send connected line updates on unanswered incoming calls immediately. (default: "no")
;timers_min_se=90       ; Minimum session timers expiration period (default:
                        ; "90")
;timers=yes     ; Session timers for SIP packets (default: "yes")
;timers_sess_expires=1800       ; Maximum session timer expiration period
                                ; (default: "1800")
;transport=     ; Explicit transport configuration to use (default: "")
                ; This will force the endpoint to use the specified transport
                ; configuration to send SIP messages.  You need to already know
                ; what kind of transport (UDP/TCP/IPv4/etc) the endpoint device
                ; will use.

;trust_id_inbound=no    ; Accept identification information received from this
                        ; endpoint (default: "no")
;trust_id_outbound=no   ; Send private identification details to the endpoint
                        ; (default: "no")
;type=  ; Must be of type endpoint (default: "")
;use_ptime=no   ; Use Endpoint s requested packetisation interval (default:
                ; "no")
;use_avpf=no    ; Determines whether res_pjsip will use and enforce usage of
                ; AVPF for this endpoint (default: "no")
;media_encryption=no    ; Determines whether res_pjsip will use and enforce
                        ; usage of media encryption for this endpoint (default:
                        ; "no")
;media_encryption_optimistic=no ; Use encryption if possible but don't fail the call
                                ; if not possible.
;g726_non_standard=no   ; When set to "yes" and an endpoint negotiates g.726
                        ; audio then g.726 for AAL2 packing order is used contrary
                        ; to what is recommended in RFC3551. Note, 'g726aal2' also
                        ; needs to be specified in the codec allow list
                        ; (default: "no")
;inband_progress=no     ; Determines whether chan_pjsip will indicate ringing
                        ; using inband progress (default: "no")
;call_group=    ; The numeric pickup groups for a channel (default: "")
;pickup_group=  ; The numeric pickup groups that a channel can pickup (default:
                ; "")
;named_call_group=      ; The named pickup groups for a channel (default: "")
;named_pickup_group=    ; The named pickup groups that a channel can pickup
                        ; (default: "")
;device_state_busy_at=0 ; The number of in use channels which will cause busy
                        ; to be returned as device state (default: "0")
;t38_udptl=no   ; Whether T 38 UDPTL support is enabled or not (default: "no")
;t38_udptl_ec=none      ; T 38 UDPTL error correction method (default: "none")
;t38_udptl_maxdatagram=0        ; T 38 UDPTL maximum datagram size (default:
                                ; "0")
;fax_detect=no  ; Whether CNG tone detection is enabled (default: "no")
;fax_detect_timeout=30  ; How many seconds into a call before fax_detect is
                        ; disabled for the call.
                        ; Zero disables the timeout.
                        ; (default: "0")
;t38_udptl_nat=no       ; Whether NAT support is enabled on UDPTL sessions
                        ; (default: "no")
;t38_bind_rtp_to_media_address=     ; Bind the UDPTL session to the media_address.
                                    ; This causes all UDPTL packets to be sent from
                                    ; the specified address. (default: "no")
;tone_zone=     ; Set which country s indications to use for channels created
                ; for this endpoint (default: "")
;language=      ; Set the default language to use for channels created for this
                ; endpoint (default: "")
;one_touch_recording=no ; Determines whether one touch recording is allowed for
                        ; this endpoint (default: "no")
;record_on_feature=automixmon   ; The feature to enact when one touch recording
                                ; is turned on (default: "automixmon")
;record_off_feature=automixmon  ; The feature to enact when one touch recording
                                ; is turned off (default: "automixmon")
;rtp_engine=asterisk    ; Name of the RTP engine to use for channels created
                        ; for this endpoint (default: "asterisk")
;allow_transfer=yes     ; Determines whether SIP REFER transfers are allowed
                        ; for this endpoint (default: "yes")
;sdp_owner=-    ; String placed as the username portion of an SDP origin o line
                ; (default: "-")
;sdp_session=Asterisk   ; String used for the SDP session s line (default:
                        ; "Asterisk")
;tos_audio=0    ; DSCP TOS bits for audio streams (default: "0")
;tos_video=0    ; DSCP TOS bits for video streams (default: "0")
;cos_audio=0    ; Priority for audio streams (default: "0")
;cos_video=0    ; Priority for video streams (default: "0")
;allow_subscribe=yes    ; Determines if endpoint is allowed to initiate
                        ; subscriptions with Asterisk (default: "yes")
;sub_min_expiry=0       ; The minimum allowed expiry time for subscriptions
                        ; initiated by the endpoint (default: "0")
;from_user=     ; Username to use in From header for requests to this endpoint
                ; (default: "")
;mwi_from_user= ; Username to use in From header for unsolicited MWI NOTIFYs to
                ; this endpoint (default: "")
;from_domain=   ; Domain to user in From header for requests to this endpoint
                ; (default: "")
;dtls_verify=no ; Verify that the provided peer certificate is valid (default:
                ; "no")
;dtls_rekey=0   ; Interval at which to renegotiate the TLS session and rekey
                ; the SRTP session (default: "0")
;dtls_auto_generate_cert= ; Enable ephemeral DTLS certificate generation (default:
                          ; "no")
;dtls_cert_file=          ; Path to certificate file to present to peer (default:
                          ; "")
;dtls_private_key=        <redacted:8a40e7e4>
                          ; "")
;dtls_cipher=   ; Cipher to use for DTLS negotiation (default: "")
;dtls_ca_file=  ; Path to certificate authority certificate (default: "")
;dtls_ca_path=  ; Path to a directory containing certificate authority
                ; certificates (default: "")
;dtls_setup=    ; Whether we are willing to accept connections connect to the
                ; other party or both (default: "")
;dtls_fingerprint= ; Hash to use for the fingerprint placed into SDP
                   ; (default: "SHA-256")
;srtp_tag_32=no ; Determines whether 32 byte tags should be used instead of 80
                ; byte tags (default: "no")
;set_var=       ; Variable set on a channel involving the endpoint. For multiple
                ; channel variables specify multiple 'set_var'(s)
;rtp_keepalive= ; Interval, in seconds, between comfort noise RTP packets if
                ; RTP is not flowing. This setting is useful for ensuring that
                ; holes in NATs and firewalls are kept open throughout a call.
;rtp_timeout=      ; Hang up channel if RTP is not received for the specified
                   ; number of seconds when the channel is off hold (default:
                   ; "0" or not enabled)
;rtp_timeout_hold= ; Hang up channel if RTP is not received for the specified
                   ; number of seconds when the channel is on hold (default:
                   ; "0" or not enabled)
;rtp_port_start=   ; Per-endpoint starting RTP port number, overriding the
                   ; global rtp.conf setting. Must be used together with
                   ; rtp_port_end. (default: "0" or use global range)
;rtp_port_end=     ; Per-endpoint ending RTP port number, overriding the
                   ; global rtp.conf setting. Must be used together with
                   ; rtp_port_start. (default: "0" or use global range)
;contact_user= ; On outgoing requests, force the user portion of the Contact
               ; header to this value (default: "")
;incoming_call_offer_pref= ; Based on this setting, a joint list of
                           ; preferred codecs between those received in an
                           ; incoming SDP offer (remote), and those specified
                           ; in the endpoint's "allow" parameter (local)
                           ; is created and is passed to the Asterisk core.
                           ;
                           ; local - Include all codecs in the local list that
                           ; are also in the remote list preserving the local
                           ; order. (default).
                           ; local_first - Include only the first codec in the
                           ; local list that is also in the remote list.
                           ; remote - Include all codecs in the remote list that
                           ; are also in the local list preserving remote list
                           ; order.
                           ; remote_first - Include only the first codec in
                           ; the remote list that is also in the local list.
;outgoing_call_offer_pref= ; Based on this setting, a joint list of
                           ; preferred codecs between those received from the
                           ; Asterisk core (remote), and those specified in
                           ; the endpoint's "allow" parameter (local) is
                           ; created and is used to create the outgoing SDP
                           ; offer.
                           ;
                           ; local - Include all codecs in the local list that
                           ; are also in the remote list preserving the local
                           ; order.
                           ; local_merge - Include all codecs in the local list
                           ; preserving the local order.
                           ; local_first - Include only the first codec in the
                           ; local list.
                           ; remote - Include all codecs in the remote list that
                           ; are also in the local list preserving remote list
                           ; order.
                           ; remote_merge - Include all codecs in the local list
                           ; preserving the remote list order. (default)
                           ; remote_first - Include only the first codec in the
                           ; remote list that is also in the local list.
;preferred_codec_only=no   ; Respond to a SIP invite with the single most
                           ; preferred codec rather than advertising all joint
                           ; codec capabilities. This limits the other side's
                           ; codec choice to exactly what we prefer.
                           ; default is no.
                           ; NOTE: This option is deprecated in favor
                           ; of incoming_call_offer_pref.  Setting both
                           ; options is unsupported.
;asymmetric_rtp_codec= ; Allow the sending and receiving codec to differ and
                       ; not be automatically matched (default: "no")
;refer_blind_progress= ; Whether to notifies all the progress details on blind
                       ; transfer (default: "yes"). The value "no" is useful
                       ; for some SIP phones (Mitel/Aastra, Snom) which expect
                       ; a sip/frag "200 OK" after REFER has been accepted.
;notify_early_inuse_ringing = ; Whether to notifies dialog-info 'early'
                              ; on INUSE && RINGING state (default: "no").
                              ; The value "yes" is useful for some SIP phones
                              ; (Cisco SPA) to be able to indicate and pick up
                              ; ringing devices.
;max_audio_streams= ; The maximum number of allowed negotiated audio streams
                    ; (default: 1)
;max_video_streams= ; The maximum number of allowed negotiated video streams
                    ; (default: 1)
;webrtc= ; When set to "yes" this also enables the following values that are needed
         ; for webrtc: rtcp_mux, use_avpf, ice_support, and use_received_transport.
         ; The following configuration settings also get defaulted as follows:
         ;     media_encryption=dtls
         ;     dtls_verify=fingerprint
         ;     dtls_setup=actpass
         ; A dtls_cert_file and a dtls_ca_file still need to be specified.
         ; Default for this option is "no"
;incoming_mwi_mailbox = ; Mailbox name to use when incoming MWI NOTIFYs are
                        ; received.
                        ; If an MWI NOTIFY is received FROM this endpoint,
                        ; this mailbox will be used when notifying other modules
                        ; of MWI status changes.  If not set, incoming MWI
                        ; NOTIFYs are ignored.
;follow_early_media_fork = ; On outgoing calls, if the UAS responds with
                           ; different SDP attributes on subsequent 18X or 2XX
                           ; responses (such as a port update) AND the To tag
                           ; on the subsequent response is different than that
                           ; on the previous one, follow it.  This usually
                           ; happens when the INVITE is forked to multiple UASs
                           ; and more than 1 sends an SDP answer.
                           ; This option must also be enabled in the system
                           ; section.
                           ; (default: yes)
;accept_multiple_sdp_answers =
                           ; On outgoing calls, if the UAS responds with
                           ; different SDP attributes on non-100rel 18X or 2XX
                           ; responses (such as a port update) AND the To tag on
                           ; the subsequent response is the same as that on the
                           ; previous one, process it. This can happen when the
                           ; UAS needs to change ports for some reason such as
                           ; using a separate port for custom ringback.
                           ; This option must also be enabled in the system
                           ; section.
                           ; (default: no)
;suppress_q850_reason_headers =
                           ; Suppress Q.850 Reason headers for this endpoint.
                           ; Some devices can't accept multiple Reason headers
                           ; and get confused when both 'SIP' and 'Q.850' Reason
                           ; headers are received.  This option allows the
                           ; 'Q.850' Reason header to be suppressed.
                           ; (default: no)
;ignore_183_without_sdp =
                           ; Do not forward 183 when it doesn't contain SDP.
                           ; Certain SS7 internetworking scenarios can result in
                           ; a 183 to be generated for reasons other than early
                           ; media.  Forwarding this 183 can cause loss of
                           ; ringback tone.  This flag emulates the behavior of
                           ; chan_sip and prevents these 183 responses from
                           ; being forwarded.
                           ; (default: no)
;stir_shaken =
                           ; If this is enabled, STIR/SHAKEN operations will be
                           ; performed on this endpoint. This includes inbound
                           ; and outbound INVITEs. On an inbound INVITE, Asterisk
                           ; will check for an Identity header and attempt to
                           ; verify the call. On an outbound INVITE, Asterisk will
                           ; add an Identity header that others can use to verify
                           ; calls from this endpoint. Additional configuration is
                           ; done in stir_shaken.conf.
                           ; The STIR_SHAKEN dialplan function must be used to get
                           ; the verification results on inbound INVITEs. Nothing
                           ; happens to the call if verification fails; it's up to
                           ; you to determine what to do with the results.
                           ; (default: no)
;stir_shaken_profile =
                           ; If a profile is specified (defined in stir_shaken.conf),
                           ; this endpoint will follow the rules defined there.
;allow_unauthenticated_options =
                           ; By default, chan_pjsip will challenge an incoming
                           ; OPTIONS request for authentication credentials just
                           ; as it would an INVITE request. This is consistent
                           ; with RFC 3261.
                           ; There are many UAs that use an OPTIONS request as a
                           ; "ping" and they expect a 200 response indicating that
                           ; the remote party is up and running without a need to
                           ; authenticate.
                           ; Setting allow_unauthenticated_options to 'yes' will
                           ; instruct chan_pjsip to skip the authentication step
                           ; when it receives an OPTIONS request for this
                           ; endpoint.
                           ; There are security implications to enabling this
                           ; setting as it can allow information disclosure to
                           ; occur - specifically, if enabled, an external party
                           ; could enumerate and find the endpoint name by
                           ; sending OPTIONS requests and examining the
                           ; responses.
                           ; (default: no)

;geoloc_incoming_call_profile =
                ; This geolocation profile will be applied to all calls received
                ; by the channel driver from the remote endpoint before they're
                ; forwarded to the dialplan.
;geoloc_outgoing_call_profile =
                ; This geolocation profile will be applied to all calls received
                ; by the channel driver from the dialplan before they're forwarded
                ; the remote endpoint.
;
; send_aoc =
                ; This options turns on and off support for sending AOC to endpoints.
                ; AOC updates can be sent using the AOCMessage AMI action or come
                ; from PRI channels.
                ; (default: no)
;
; tenantid =
                ; Sets the tenant ID for this endpoint. It can be read in dialplan
                ; with the CHANNEL function, and it can be changed later via dialplan
                ; using the same CHANNEL function if needed. Setting tenant ID here
                ; will cause it to show up on channel creation and the initial
                ; channel snapshot.
;
; suppress_moh_on_sendonly = no
                ; Normally, when one party in a call sends Asterisk an SDP with
                ; a "sendonly" or "inactive" attribute it means "hold" and
                ; causes Asterisk to start playing MOH back to the other party.
                ; This can be problematic if it happens at certain times, such
                ; as in a 183 Progress message, because the MOH will replace
                ; any early media you may be playing to the calling party. If
                ; you set this option to "yes" on an endpoint and the endpoint
                ; receives an SDP with "sendonly" or "inactive", Asterisk will
                ; NOT play MOH back to the other party.
                ; NOTE: This doesn't just apply to 183 responses.  MOH will
                ; be suppressed when the attribute appears in any SDP received
                ; including INVITEs, re-INVITES, and other responses.
                ; (default: no)

;==========================AUTH SECTION OPTIONS=========================
;[auth]
;  SYNOPSIS: Authentication type
;
;  Note: Using the same auth section for inbound and outbound
;  authentication is not recommended.  There is a difference in
;  meaning for an empty realm setting between inbound and outbound
;  authentication uses.
;
;  Note on Digest Algorithms: The currently supported digest algorithms are
;  "MD5", "SHA-256" and "SHA-512-256" but availability may be limited by
;  the versions of PJProject and OpenSSL installed.  Run the CLI command
;  `pjproject show buildopts` to see the algorithms currently available and
;  see the documentation linked below for more info.
;
;  Detailed discussion for this object, especially regarding hash algorithms
;  and realms can be found at
;  https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/PJSIP-Authentication

;type=       ; Must be auth (default: "")

;auth_type=  ; Authentication mechanism.
             ; Must be one of:
             ; "digest"      : The standard HTTP/SIP digest
             ;    authentication. "password" and/or one or more
             ;    "password_digest" parameters must also be specified.
             ; "google_oauth": Google OAuth authentication used by
             ;    Google Voice.
             ; "userpass"    : (deprecated).  Automatically converted
             ;    to "digest".  Used to mean plain-text password but
             ;    that is now determined automatically.
             ; "md5"         : (deprecated)   Automatically converted
             ;    to "digest".  Used to mean pre-hashed password but
             ;    that is now determined automatically.
             ; (default: "digest")

;realm=      ; For incoming authentication (asterisk is the UAS),
             ; this is the realm to be sent on WWW-Authenticate
             ; headers.  If not specified, the global object's
             ; "default_realm" will be used.
             ;
             ; For outgoing authentication (asterisk is the UAC), this
             ; must either be the realm the server is expected to send,
             ; or left blank or contain a single '*' to automatically
             ; use the realm sent by the server. If you have multiple
             ; auth objects for an endpoint, the realm is also used to
             ; match the auth object to the realm the server sent.
             ;
             ; Using the same auth section for inbound and outbound
             ; authentication is not recommended.  There is a difference in
             ; meaning for an empty realm setting between inbound and outbound
             ; authentication uses.
             ;
             ; If more than one auth object with the same realm or
             ; more than one wildcard auth object is associated to
             ; an endpoint, only the first one of each defined on
             ; the endpoint will be used.
             ;
             ; (default: "")

;username=   ; Username to use for account (Required)

;password=   <redacted:152f2c4a>

;password_digest= <redacted:749a583f>
             ; As an alternative to specifying a plain text password, you can
             ; specify pre-computed digests.
             ;
             ; <digest-spec> = <IANA_digest_algorithm>:<hashed-credential>
             ; <IANA_digest_algorithm>: One of the supported hash algorithms
             ;    which currently are "MD5", "SHA-256" and "SHA-512-256" but
             ;    see the note above.
             ; <hashed-credential>:  The result of passing the following
             ;    string through the selected hash algorithm:
             ;    <username>:<realm>:<password>
             ; Example:
             ; $ echo -n "fred:asterisk:mypass" | openssl dgst -md5
             ; MD5(stdin)= 43a8d9be3da524f9a59ca0593d7b1b5d
             ; would be specified as...
;password_digest = <redacted:cdc8de26>
             ; You can specify this parameter once for each algorithm.
             ; See the documentation linked above for more info.

;md5_cred=   ; (deprecated)  Will be automatically converted to a
             ; "password_digest" parameter.

;supported_algorithms_uas= <IANA_digest_algorithm>[,<IANA_digest_algorithm>]...
             ; Specify the digest algorithms to offer when this auth object
             ; is used by Asterisk acting as a UAS.  Specify one or more of
             ; the supported hash algorithms, which currently are "MD5",
             ; "SHA-256" and "SHA-512-256", but see the note above.
             ; The default is the value specified in the global object's
             ; default_auth_algorithms_uas parameter.

;supported_algorithms_uac= <IANA_digest_algorithm>[,<IANA_digest_algorithm>]...
             ; Specify the digest algorithms to respond with when this auth
             ; object is used by Asterisk acting as a UAC.  Specify one or more of
             ; the supported hash algorithms, which currently are "MD5",
             ; "SHA-256" and "SHA-512-256", but see the note above.
             ; The default is the value specified in the global object's
             ; default_auth_algorithms_uac parameter.

;nonce_lifetime=32 ; Lifetime of a nonce associated with this
             ; authentication config (default: "32")

; For the Google OAuth authentication mechanism, the following parameters are
; required:
;refresh_token=  <redacted:d2f68262>
;oauth_clientid= ; OAuth 2.0 application's client id
;oauth_secret=   <redacted:404f1a7e>


;==========================DOMAIN_ALIAS SECTION OPTIONS=========================
;[domain_alias]
;  SYNOPSIS: Domain Alias
;type=  ; Must be of type domain_alias (default: "")
;domain=        ; Domain to be aliased (default: "")


;==========================TRANSPORT SECTION OPTIONS=========================
;[transport]
;  SYNOPSIS: SIP Transport
;
;bind=  ; IP Address and optional port to bind to for this transport (default:
        ; "")
; Note that for the Websocket transport the TLS configuration is configured
; in http.conf and is applied for all HTTPS traffic.
;ca_list_file=  ; File containing a list of certificates to read TLS ONLY
                ; (default: "")
;ca_list_path=  ; Path to directory containing certificates to read TLS ONLY.
                ; PJProject version 2.4 or higher is required for this option to
                ; be used.
                ; (default: "")
;cert_file=     ; Certificate file for endpoint TLS ONLY
                ; Will read .crt or .pem file but only uses cert,
                ; a .key file must be specified via priv_key_file.
                ; Since PJProject version 2.5: If the file name ends in _rsa,
                ; for example "asterisk_rsa.pem", the files "asterisk_dsa.pem"
                ; and/or "asterisk_ecc.pem" are loaded (certificate, inter-
                ; mediates, private key), to support multiple algorithms for
                ; server authentication (RSA, DSA, ECDSA). If the chains are
                ; different, at least OpenSSL 1.0.2 is required. This option
                ; can be reloaded resulting in an updated certificate if the
                ; filename remains unchanged.
                ; (default: "")
;cipher=        ; Preferred cryptography cipher names TLS ONLY (default: "")
;method=        ; Method of SSL transport TLS ONLY (default: "")
;priv_key_file= ; Private key file TLS ONLY. This option can be reloaded
                ; resulting in an updated private key if the filename remains
                ; unchanged.
                ; (default: "")
;verify_client= ; Require verification of client certificate TLS ONLY (default:
                ; "")
;verify_server= ; Require verification of server certificate TLS ONLY (default:
                ; "")
;require_client_cert=   ; Require client certificate TLS ONLY (default: "")
;domain=        ; Domain the transport comes from (default: "")
;external_media_address=        ; External IP address to use in RTP handling
                                ; (default: "")
;external_signaling_address=    ; External address for SIP signalling (default:
                                ; "")
;external_signaling_port=0      ; External port for SIP signalling (default:
                                ; "0")
;local_net=     ; Network to consider local used for NAT purposes (default: "")
;password=      <redacted:283de1e9>
;protocol=udp   ; Protocol to use for SIP traffic (default: "udp")
;type=  ; Must be of type transport (default: "")
;tos=0  ; Enable TOS for the signalling sent over this transport (default: "0")
;cos=0  ; Enable COS for the signalling sent over this transport (default: "0")
;websocket_write_timeout=100    ; Default write timeout to set on websocket
                                ; transports. This value may need to be adjusted
                                ; for connections where Asterisk must write a
                                ; substantial amount of data and the receiving
                                ; clients are slow to process the received
                                ; information. Value is in milliseconds; default
                                ; is 100 ms.
;allow_reload=no    ; Although transports can now be reloaded, that may not be
                    ; desirable because of the slight possibility of dropped
                    ; calls. To make sure there are no unintentional drops, if
                    ; this option is set to 'no' (the default) changes to the
                    ; particular transport will be ignored. If set to 'yes',
                    ; changes (if any) will be applied.
;symmetric_transport=no ; When a request from a dynamic contact comes in on a
                        ; transport with this option set to 'yes', the transport
                        ; name will be saved and used for subsequent outgoing
                        ; requests like OPTIONS, NOTIFY and INVITE.  It's saved
                        ; as a contact uri parameter named 'x-ast-txp' and will
                        ; display with the contact uri in CLI, AMI, and ARI
                        ; output.  On the outgoing request, if a transport
                        ; wasn't explicitly set on the endpoint AND the request
                        ; URI is not a hostname, the saved transport will be
                        ; used and the 'x-ast-txp' parameter stripped from the
                        ; outgoing packet.
;allow_wildcard_certs=no ; In conjunction with verify_server, if 'yes' allow use
                         ; of wildcards, i.e. '*.' in certs for common, and
                         ; subject alt names of type DNS for TLS transport
                         ; types. Note, names must start with the wildcard.
                         ; Partial wildcards, e.g. 'f*.example.com' and
                         ; 'foo.*.com' are disallowed. As well, names only
                         ; match against a single level meaning '*.example.com'
                         ; matches 'foo.example.com', but not
                         ; 'foo.bar.example.com'. Defaults to 'no'.

;==========================AOR SECTION OPTIONS=========================
;[aor]
;  SYNOPSIS: The configuration for a location of an endpoint
;contact=       ; Permanent contacts assigned to AoR (default: "")
;default_expiration=3600        ; Default expiration time in seconds for
                                ; contacts that are dynamically bound to an AoR
                                ; (default: "3600")
;mailboxes=           ; Allow subscriptions for the specified mailbox(es)
                      ; This option applies when an external entity subscribes to an AoR
                      ; for Message Waiting Indications. (default: "")
;voicemail_extension= ; The voicemail extension to send in the NOTIFY Message-Account header
                      ; (default: global/default_voicemail_extension)
;maximum_expiration=7200        ; Maximum time to keep an AoR (default: "7200")
;max_contacts=0 ; Maximum number of contacts that can bind to an AoR (default:
                ; "0")
;minimum_expiration=60  ; Minimum keep alive time for an AoR (default: "60")
;remove_existing=no     ; Allow a registration to succeed by displacing any existing
                        ; contacts that now exceed the max_contacts count.  Any
                        ; removed contacts are the next to expire.  The behaviour is
                        ; beneficial when rewrite_contact is enabled and max_contacts
                        ; is greater than one.  The removed contact is likely the old
                        ; contact created by rewrite_contact that the device is
                        ; refreshing.
                        ; (default: "no")
;remove_unavailable=no  ; If remove_existing is disabled, will allow a registration
                        ; to succeed by removing only unavailable contacts when
                        ; max_contacts is exceeded. This will reject a registration
                        ; that exceeds max_contacts if no unavailable contacts are
                        ; present to remove. If remove_existing is enabled, will
                        ; prioritize removal of unavailable contacts before removing
                        ; expiring soonest.  This tames the behavior of remove_existing
                        ; to only remove an available contact if an unavailable one is
                        ; not present.
                        ; (default: "no")
;type=  ; Must be of type aor (default: "")
;qualify_frequency=0    ; Interval at which to qualify an AoR via OPTIONS requests.
                        ; (default: "0")
;qualify_timeout=3.0      ; Qualify timeout in fractional seconds (default: "3.0")
;qualify_2xx_only=no    ; If true, only qualify AoR if OPTIONS request returns 2XX
                        ; (default: "no")
;authenticate_qualify=no        ; Authenticates a qualify request if needed
                                ; (default: "no")
;outbound_proxy=        ; Proxy through which to send OPTIONS requests, a full SIP URI
                        ; must be provided (default: "")


;==========================SYSTEM SECTION OPTIONS=========================
;[system]
;  SYNOPSIS: Options that apply to the SIP stack as well as other system-wide settings
;timer_t1=500   ; Set transaction timer T1 value milliseconds (default: "500")
;timer_b=32000  ; Set transaction timer B value milliseconds (default: "32000")
;compact_headers=no     ; Use the short forms of common SIP header names
                        ; (default: "no")
;taskpool_minimum_size=4      ; Minimum number of taskprocessors in the res_pjsip
                              ; taskpool (default: "4")
;taskpool_initial_size=4      ; Initial number of taskprocessors in the res_pjsip
                              ; taskpool (default: "4")
;taskpool_auto_increment=1    ; The amount by which the number of taskprocessors is
                              ; incremented when necessary (default: "1")
;taskpool_idle_timeout=60     ; Number of seconds before an idle taskprocessor
                              ; should be disposed of (default: "60")
;taskpool_max_size=50 ; Maximum number of taskprocessors in the res_pjsip taskpool
                      ; A value of 0 indicates no maximum (default: "50")
;disable_tcp_switch=yes ; Disable automatic switching from UDP to TCP transports
                        ; if outgoing request is too large.
                        ; See RFC 3261 section 18.1.1.
                        ; Disabling this option has been known to cause interoperability
                        ; issues, so disable at your own risk.
                        ; (default: "yes")
;follow_early_media_fork = ; On outgoing calls, if the UAS responds with
                           ; different SDP attributes on subsequent 18X or 2XX
                           ; responses (such as a port update) AND the To tag
                           ; on the subsequent response is different than that
                           ; on the previous one, follow it.  This usually
                           ; happens when the INVITE is forked to multiple UASs
                           ; and more than 1 sends an SDP answer.
                           ; This option must also be enabled on endpoints that
                           ; require this functionality.
                           ; (default: yes)
;accept_multiple_sdp_answers =
                           ; On outgoing calls, if the UAS responds with
                           ; different SDP attributes on non-100rel 18X or 2XX
                           ; responses (such as a port update) AND the To tag on
                           ; the subsequent response is the same as that on the
                           ; previous one, process it. This can happen when the
                           ; UAS needs to change ports for some reason such as
                           ; using a separate port for custom ringback.
                           ; This option must also be enabled on endpoints that
                           ; require this functionality.
                           ; (default: no)
;disable_rport=no ; Disable the use of "rport" in outgoing requests.
;type=  ; Must be of type system (default: "")

;==========================GLOBAL SECTION OPTIONS=========================
;[global]
;  SYNOPSIS: Options that apply globally to all SIP communications
;max_forwards=70        ; Value used in Max Forwards header for SIP requests
                        ; (default: "70")
;type=  ; Must be of type global (default: "")
;user_agent=Asterisk PBX        ; Allows you to change the user agent string
                                ; The default user agent string also contains
                                ; the Asterisk version. If you don't want to
                                ; expose this, change the user_agent string.
;default_outbound_endpoint=default_outbound_endpoint    ; Endpoint to use when
                                                        ; sending an outbound
                                                        ; request to a URI
                                                        ; without a specified
                                                        ; endpoint (default: "d
                                                        ; efault_outbound_endpo
                                                        ; int")
;debug=no ; Enable/Disable SIP debug logging.  Valid options include yes|no
          ; or a host address (default: "no")
;keep_alive_interval=90 ; The interval (in seconds) at which to send (double CRLF)
                        ; keep-alives on all active connection-oriented transports;
                        ; for connection-less like UDP see qualify_frequency.
                        ; (default: "90")
;contact_expiration_check_interval=30
                        ; The interval (in seconds) to check for expired contacts.
;disable_multi_domain=no
            ; Disable Multi Domain support.
            ; If disabled it can improve realtime performace by reducing
            ; number of database requsts
            ; (default: "no")
;endpoint_identifier_order=ip,username,anonymous
            ; The order by which endpoint identifiers are given priority.
            ; Currently, "ip", "header", "username", "auth_username" and "anonymous"
            ; are valid identifiers as registered by the res_pjsip_endpoint_identifier_*
            ; modules.  Some modules like res_pjsip_endpoint_identifier_user register
            ; more than one identifier.  Use the CLI command "pjsip show identifiers"
            ; to see the identifiers currently available.
            ; (default: ip,username,anonymous)
;max_initial_qualify_time=4 ; The maximum amount of time (in seconds) from
                            ; startup that qualifies should be attempted on all
                            ; contacts.  If greater than the qualify_frequency
                            ; for an aor, qualify_frequency will be used instead.
;regcontext=sipregistrations  ; If regcontext is specified, Asterisk will dynamically
                              ; create and destroy a NoOp priority 1 extension for a
                              ; given endpoint who registers or unregisters with us.
                              ; The extension added is the name of the endpoint.
;default_voicemail_extension=asterisk
                   ; The voicemail extension to send in the NOTIFY Message-Account header
                   ; if not set on endpoint or aor.
                   ; (default: "")
;
; The following unidentified_request options are only used when "auth_username"
; matching is enabled in "endpoint_identifier_order".
;
;unidentified_request_count=5   ; The number of unidentified requests that can be
                                ; received from a single IP address in
                                ; unidentified_request_period seconds before a security
                                ; event is generated. (default: 5)
;unidentified_request_period=5  ; See above.  (default: 5 seconds)
;unidentified_request_prune_interval=30
                                ; The interval at which unidentified requests
                                ; are check to see if they can be pruned.  If they're
                                ; older than twice the unidentified_request_period,
                                ; they're pruned.
;
;default_from_user=asterisk     ; When Asterisk generates an outgoing SIP request, the
                                ; From header username will be set to this value if
                                ; there is no better option (such as CallerID or
                                ; endpoint/from_user) to be used
;default_realm=asterisk         ; When Asterisk generates a challenge, the digest realm
                                ; will be set to this value if there is no better option
                                ; (such as auth/realm) to be used.

                    ; Asterisk Task Processor Queue Size
                    ; On heavy loaded system with DB storage you may need to increase
                    ; taskprocessor queue.
                    ; If the taskprocessor queue size reached high water level,
                    ; the alert is triggered.
                    ; If the alert is set the pjsip distibutor stops processing incoming
                    ; requests until the alert is cleared.
                    ; The alert is cleared when taskprocessor queue size drops to the
                    ; low water clear level.
                    ; The next options set taskprocessor queue levels for MWI.
;mwi_tps_queue_high=500 ; Taskprocessor high water alert trigger level.
;mwi_tps_queue_low=450  ; Taskprocessor low water clear alert level.
                    ; The default is -1 for 90% of high water level.

                    ; Unsolicited MWI
                    ; If there are endpoints configured with unsolicited MWI
                    ; then res_pjsip_mwi module tries to send MWI to all endpoints on startup.
;mwi_disable_initial_unsolicited=no ; Disable sending unsolicited mwi to all endpoints on startup.
                    ; If disabled then unsolicited mwi will start processing
                    ; on the endpoint's next contact update.

;ignore_uri_user_options=no ; Enable/Disable ignoring SIP URI user field options.
                    ; If you have this option enabled and there are semicolons
                    ; in the user field of a SIP URI then the field is truncated
                    ; at the first semicolon.  This effectively makes the semicolon
                    ; a non-usable character for PJSIP endpoint names, extensions,
                    ; and AORs.  This can be useful for improving compatability with
                    ; an ITSP that likes to use user options for whatever reason.
                    ; Example:
                    ; URI: "sip:1235557890;phone-context=<redacted:a0d2d593>;user=phone"
                    ; The user field is "1235557890;phone-context=national"
                    ; Which becomes this: "1235557890"
                    ;
                    ; Note: The caller-id and redirecting number strings obtained
                    ; from incoming SIP URI user fields are always truncated at the
                    ; first semicolon.

;send_contact_status_on_update_registration=no ; Enable sending AMI ContactStatus
                    ; event when a device refreshes its registration
                    ; (default: "no")

;taskprocessor_overload_trigger=global
                ; Set the trigger the distributor will use to detect
                ; taskprocessor overloads.  When triggered, the distributor
                ; will not accept any new requests until the overload has
                ; cleared.
                ; "global": (default) Any taskprocessor overload will trigger.
                ; "pjsip_only": Only pjsip taskprocessor overloads will trigger.
                ; "none":  No overload detection will be performed.
                ; WARNING: The "none" and "pjsip_only" options should be used
                ; with extreme caution and only to mitigate specific issues.
                ; Under certain conditions they could make things worse.

;norefersub=yes     ; Enable sending norefersub option tag in Supported header to advertise
                    ; that the User Agent is capable of accepting a REFER request with
                    ; creating an implicit subscription (see RFC 4488).
                    ; (default: "yes")

;all_codecs_on_empty_reinvite=yes
                    ; On reception of a re-INVITE without SDP Asterisk will send an SDP
                    ; offer in the 200 OK response containing all configured codecs on the
                    ; endpoint, instead of simply those that have already been negotiated.
                    ; RFC 3261 specifies this as a SHOULD requirement.
                    ; (default: "no")

;allow_sending_180_after_183=yes	; Allow Asterisk to send 180 Ringing to an endpoint
					; after 183 Session Progress has been send.
					; If disabled Asterisk will instead send only a
					; 183 Session Progress to the endpoint.
					; (default: "no")

;default_auth_algorithms_uas = MD5
             ; The default list of digest algorithms to support when an
             ; auth object is used as a UAS. See the "supported_algorithms_uas"
             ; parameter in the "auth" object above.
             ; The default is MD5

;default_auth_algorithms_uac = MD5
             ; The default list of digest algorithms to support when an
             ; auth object is used as a UAC. See the "supported_algorithms_uac"
             ; parameter in the "auth" object above.
             ; The default is MD5


; MODULE PROVIDING BELOW SECTION(S): res_pjsip_acl
;==========================ACL SECTION OPTIONS=========================
;[acl]
;  SYNOPSIS: Access Control List
;acl=   ; List of IP ACL section names in acl conf (default: "")
;contact_acl=   ; List of Contact ACL section names in acl conf (default: "")
;contact_deny=  ; List of Contact header addresses to deny (default: "")
;contact_permit=        ; List of Contact header addresses to permit (default:
                        ; "")
;deny=  ; List of IP addresses to deny access from (default: "")
;permit=        ; List of IP addresses to permit access from (default: "")
;type=  ; Must be of type acl (default: "")




; MODULE PROVIDING BELOW SECTION(S): res_pjsip_outbound_registration
;==========================REGISTRATION SECTION OPTIONS=========================
;[registration]
;  SYNOPSIS: The configuration for outbound registration
;auth_rejection_permanent=yes   ; Determines whether failed authentication
                                ; challenges are treated as permanent failures
                                ; (default: "yes")
;client_uri=    ; Client SIP URI used when attemping outbound registration
                ; (default: "")
;contact_user=  ; Contact User to use in request (default: "")
;expiration=3600        ; Expiration time for registrations in seconds
                        ; (default: "3600")
;max_retries=10 ; Maximum number of registration attempts (default: "10")
;outbound_auth= ; Authentication object to be used for outbound registrations
                ; (default: "")
;outbound_proxy=        ; Proxy through which to send registrations, a full SIP URI
                        ; must be provided (default: "")
;max_random_initial_delay=10    ; Maximum random delay for initial registrations (default: 10)
                                ; Generally it is a good idea to space out registrations
                                ; to not overload the system. If you have a small number
                                ; of registrations and need them to register more quickly,
                                ; you can reduce this to a lower value.
;retry_interval=60      ; Interval in seconds between retries if outbound
                        ; registration is unsuccessful (default: "60")
;forbidden_retry_interval=0     ; Interval used when receiving a 403 Forbidden
                                ; response (default: "0")
;fatal_retry_interval=0 ; Interval used when receiving a fatal response.
                        ; (default: "0") A fatal response is any permanent
                        ; failure (non-temporary 4xx, 5xx, 6xx) response
                        ; received from the registrar. NOTE - if also set
                        ; the 'forbidden_retry_interval' takes precedence
                        ; over this one when a 403 is received. Also, if
                        ; 'auth_rejection_permanent' equals 'yes' a 401 and
                        ; 407 become subject to this retry interval.
;server_uri=    ; SIP URI of the server to register against (default: "")
;transport=     ; Transport used for outbound authentication (default: "")
;line=          ; When enabled this option will cause a 'line' parameter to be
                ; added to the Contact header placed into the outgoing
                ; registration request. If the remote server sends a call
                ; this line parameter will be used to establish a relationship
                ; to the outbound registration, ultimately causing the
                ; configured endpoint to be used (default: "no")
;endpoint=      ; When line support is enabled this configured endpoint name
                ; is used for incoming calls that are related to the outbound
                ; registration (default: "")
;type=  ; Must be of type registration (default: "")




; MODULE PROVIDING BELOW SECTION(S): res_pjsip_endpoint_identifier_ip
;==========================IDENTIFY SECTION OPTIONS=========================
;[identify]
;  SYNOPSIS: Identifies endpoints via some criteria.
;
; NOTE: If multiple matching criteria are provided then an inbound request will
; be matched to the endpoint if it matches ANY of the criteria.
;endpoint=      ; Name of endpoint identified (default: "")
;srv_lookups=yes        ; Perform SRV lookups for provided hostnames. (default: yes)
;match= ; Comma separated list of IP addresses, networks, or hostnames to match
        ; against (default: "")
;match_header= ; SIP header with specified value to match against (default: "")
;type=  ; Must be of type identify (default: "")




;========================PHONEPROV_USER SECTION OPTIONS=======================
;[phoneprov]
;  SYNOPSIS: Contains variables for autoprovisioning each user
;endpoint=      ; The endpoint from which to gather username, secret, etc. (default: "")
;PROFILE=       ; The name of a profile configured in phoneprov.conf (default: "")
;MAC=           ; The mac address for this user (default: "")
;OTHERVAR=      ; Any other name value pair to be used in templates (default: "")
                ; Common variables include LINE, LINEKEYS, etc.
                ; See phoneprov.conf.sample for others.
;type=          ; Must be of type phoneprov (default: "")



; MODULE PROVIDING BELOW SECTION(S): res_pjsip_outbound_publish
;======================OUTBOUND_PUBLISH SECTION OPTIONS=====================
; See https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Publishing-Extension-State/
; for more information.
;[outbound-publish]
;type=outbound-publish     ; Must be of type 'outbound-publish'.

;expiration=3600           ; Expiration time for publications in seconds

;outbound_auth=            ; Authentication object(s) to be used for outbound
                           ; publishes.
                           ; This is a comma-delimited list of auth sections
                           ; defined in pjsip.conf used to respond to outbound
                           ; authentication challenges.
                           ; Using the same auth section for inbound and
                           ; outbound authentication is not recommended.  There
                           ; is a difference in meaning for an empty realm
                           ; setting between inbound and outbound authentication
                           ; uses. See the auth realm description for details.

;outbound_proxy=           ; SIP URI of the outbound proxy used to send publishes.
                           ; Consider adding \;lr to keep user@domain in the request URI.

;server_uri=               ; SIP URI of the server and entity to publish to.
                           ; This is the URI at which to find the entity and
                           ; server to send the outbound PUBLISH to.
                           ; This URI is used as the request URI of the outbound
                           ; PUBLISH request from Asterisk.

;from_uri=                 ; SIP URI to use in the From header.
                           ; This is the URI that will be placed into the From
                           ; header of outgoing PUBLISH messages. If no URI is
                           ; specified then the URI provided in server_uri will
                           ; be used.

;to_uri=                   ; SIP URI to use in the To header.
                           ; This is the URI that will be placed into the To
                           ; header of outgoing PUBLISH messages. If no URI is
                           ; specified then the URI provided in server_uri will
                           ; be used.

;event=                    ; Event type of the PUBLISH.

;max_auth_attempts=        ; Maximum number of authentication attempts before
                           ; stopping the pub.

;transport=                ; Transport used for outbound publish.
                           ; A transport configured in pjsip.conf. As with other
                           ; res_pjsip modules, this will use the first
                           ; available transport of the appropriate type if
                           ; unconfigured.

;multi_user=no             ; Enable multi-user support (Asterisk 14+ only)



; MODULE PROVIDING BELOW SECTION(S): res_pjsip_pubsub
; See https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Resource-List-Subscriptions-RLS/
; for more information.
;=============================RESOURCE-LIST===================================
;[resource_list]
;type=resource_list        ; Must be of type 'resource_list'.

;event=                    ; The SIP event package that the list resource.
                           ; belongs to.  The SIP event package describes the
                           ; types of resources that Asterisk reports the state
                           ; of.

;list_item=                ; The name of a resource to report state on.
                           ; In general Asterisk looks up list items in the
                           ; following way:
                           ;  1. Check if the list item refers to another
                           ;     configured resource list.
                           ;  2. Pass the name of the resource off to
                           ;     event-package-specific handlers to find the
                           ;     specified resource.
                           ; The second part means that the way the list item
                           ; is specified depends on what type of list this is.
                           ; For instance, if you have the event set to
                           ; presence, then list items should be in the form of
                           ; dialplan_extension@dialplan_context. For
                           ; message-summary, mailbox names should be listed.

;full_state=no             ; Indicates if the entire list's state should be
                           ; sent out.
                           ; If this option is enabled, and a resource changes
                           ; state, then Asterisk will construct a notification
                           ; that contains the state of all resources in the
                           ; list. If the option is disabled, Asterisk will
                           ; construct a notification that only contains the
                           ; states of resources that have changed.
                           ; NOTE: Even with this option disabled, there are
                           ; certain situations where Asterisk is forced to send
                           ; a notification with the states of all resources in
                           ; the list. When a subscriber renews or terminates
                           ; its subscription to the list, Asterisk MUST send
                           ; a full state notification.

;notification_batch_interval=0
                           ; Time Asterisk should wait, in milliseconds,
                           ; before sending notifications.

;resource_display_name=no  ; Indicates whether display name of resource
                           ; or the resource name being reported.
                           ; If this option is enabled, the Display Name
                           ; will be reported as resource name.
                           ; If the event set to presence or dialog,
                           ; the HINT name will be set as the Display Name.
                           ; For example:
                           ;  exten => 1234,hint,PJSIP/user1234(Alice)
                           ; If enabled the resource name will be 'Alice'.
                           ; If disabled the resource name will be '1234'.
                           ; The message-summary is not supported yet.


;==========================INBOUND_PUBLICATION================================
; See https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Exchanging-Device-and-Mailbox-State-Using-PJSIP/
; for more information.
;[inbound-publication]
;type=                     ; Must be of type 'inbound-publication'.

;endpoint=                 ; Optional name of an endpoint that is only allowed
                           ; to publish to this resource.


; MODULE PROVIDING BELOW SECTION(S): res_pjsip_publish_asterisk
;==========================ASTERISK_PUBLICATION===============================
; See https://docs.asterisk.org/Configuration/Channel-Drivers/SIP/Configuring-res_pjsip/Exchanging-Device-and-Mailbox-State-Using-PJSIP/
; for more information.
;[asterisk-publication]
;type=asterisk-publication ; Must be of type 'asterisk-publication'.

;devicestate_publish=      ; Optional name of a publish item that can be used
                           ; to publish a req.

;mailboxstate_publish=     ; Optional name of a publish item that can be used
                           ; to publish a req.

;device_state=no           ; Whether we should permit incoming device state
                           ; events.

;device_state_filter=      ; Optional regular expression used to filter what
                           ; devices we accept events for.

;mailbox_state=no          ; Whether we should permit incoming mailbox state
                           ; events.

;mailbox_state_filter=     ; Optional regular expression used to filter what
                           ; mailboxes we accept events for.


;================================TEL URIs=====================================
;
; Asterisk has TEL URI support, but with limited scope. Support is only for
; TEL URIs present in traffic from a remote party. Asterisk does not generate
; any TEL URIs of its own.
;
; Currently, the allowed request types are INVITE, ACK, BYE, and CANCEL. Any
; other request type that contains a TEL URI will behave as it did before.
; TEL URIs are allowed in the request, From, and To headers.
;
; You can match a TEL URI From header by IP, header, or auth_username.

; >>> dvs-phone (managed by asl_dvs_dashboard - edits inside are overwritten) >>>
#tryinclude dvs_phone_pjsip.conf
; <<< dvs-phone <<<
```

### /etc/asterisk/rpt.conf

```
;*********************************************
;********   Template-tized rpt.conf   ********
;*********************************************
; Note to editors: set tabs to 4 space characters. No wrap to keep comments neat.
; vim: tabstop=4
;
; Radio Repeater configuration file for use with app_rpt ASL3
;

[general]
rtpstart = 10000
rtpend = 10003
node_lookup_method = dns            ; method used to lookup nodes
                                    ; dns = dns lookup only (default)
                                    ; both = dns lookup first, followed by external file
                                    ; file = external file lookup only

; The domain name used for DNS lookups when the node lookup method is "dns" or
; "both".  The default domain is "nodes.allstarlink.org" and does not need to
; be defined here.  Only set "dns_node_domain" if a) you really know what you're
; doing and b) you need to use an alternate DNS domain for node resolution.
;dns_node_domain = nodes.allstarlink.org

; When using DNS, "app_rpt" must know the length of the longest node number.
; The current maximum is 6 digits and does not need to be defined here. The
; "max_dns_node_length" variable can be used to limit queries to shorter (or
; longer) node numbers.
;max_dns_node_length = 6

[nodes]
500004 = <redacted:3f78149c>/500004,NONE
; >>> dvs-phone (managed by asl_dvs_dashboard - edits inside are overwritten) >>>
1001 = <redacted:3f78149c>/1001,NONE
1002 = <redacted:3f78149c>/1002,NONE
; <<< dvs-phone <<<

; If you are using automatic update for AllStarLink nodes, and you probably are,
; no AllStarLink remote nodes should be defined here. Only place a definition
; for your local nodes, and private (not on AllStarLink directory) nodes here.

; Sample nodes on this server. These are required. Use IP 127.0.0.1
; IAX port number if not the default 4569.
;500005 = <redacted:3f78149c>/500005,NONE

; Sample public or private node behind your router.
;1001 = <redacted:ed085888>:4568/1001,NONE

; Sample private node on the internet.
;1000 = <redacted:032036c1>:4569/1000,NONE

500001 = <redacted:3f78149c>:4569/500001,NONE

;
; Your nodes are configured in two places.  Below, you will find
; a section that starts with :
;
;   [node-main](!)
;
; This is where you configure the defaults for your all your  node.
;

;
; You should configure each of your individual nodes at the end of
; the file with sections that would look like :
;
;   [500002](node-main)
;   rxchannel = SimpleUSB/500002
;
; This is where you specify any per-node settings that differ from
; the default values.
;

500002 = <redacted:3f78149c>:4569/500002,NONE
500003 = <redacted:3f78149c>:4569/500003,NONE

[node-main](!)
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;; Template for all your nodes ;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;;; rxchannel ;;;
; Must also be enabled in modules.conf
; Enable the selected channel driver in modules.conf !!!
; Rx/Tx audio/signaling channel. Choose ONLY 1 per node stanza.
; rxchannel = Local/pseudo          ; No radio (hub)
; rxchannel = SimpleUSB/500002        ; SimpleUSB
; rxchannel = Radio/500002            ; USBRadio (DSP)
; rxchannel = Voter/500002            ; RTCM device
; rxchannel = USRP/127.0.0.1:34001:32001    ;GNU Radio interface USRP

rxchannel = Local/pseudo            ; No radio (hub)

duplex = 0                          ; 0 = Half duplex with no telemetry tones or hang time.
                                    ;     Special Case: Full duplex if linktolink is set to yes.
                                    ;     This mode is preferred when interfacing with an external multiport repeater controller.
                                    ;     Comment out idrecording and idtalkover to suppress IDs also
                                    ; 1 = Half duplex with telemetry tones and hang time. Do not repeat audio.
                                    ;     This mode is preferred when interfacing a simplex node.
                                    ; 2 = Full Duplex with telemetry tones and hang time.
                                    ;     This mode is preferred when interfacing a repeater.
                                    ; 3 = Full Duplex with telemetry tones and hang time, but no repeated audio.
                                    ; 4 = Full Duplex with telemetry tones and hang time. Repeated audio only when the autopatch is down.

linktolink = no                     ; disables forcing physical half-duplex operation of main repeater while
                                    ; still keeping half-duplex semantics (optional)

linkmongain = -22                   ; Link Monitor Gain adjusts the audio level of monitored nodes when a signal from another node or the local receiver is received.
                                    ; If linkmongain is set to a negative number the monitored audio will decrease by the set amount in db.
                                    ; If linkmongain set to a positive number monitored audio will increase by the set amount in db.
                                    ; The value of linkmongain is in db. The default value is 0 db.

erxgain = -3                        ; EchoLink receive gain adjustment
                                    ; Note: Gain is in db-volts (20logVI/VO)
etxgain = 3                         ; EchoLink transmit gain adjustment
                                    ; Note: Gain is in db-volts (20logVI/VO)
;eannmode = 1                       ; 1 = Say only node number on EchoLink connects (default = 1)
                                    ; 2 = say phonetic call sign only on EchoLink connects
                                    ; 3 = say phonetic call sign and node number on EchoLink connects

;echolinkdefault = 2                ; 0 = Telemetry output off
                                    ; 1 = Telemetry output on
                                    ; 2 = Timed telemetry output on command execution and for a short time thereafter
                                    ; 3 = Follow local telemetry mode

;echolinkdynamic = 1                ; 0 = Disallow users to change current EchoLink telemetry setting with a COP command
                                    ; 1 = Allow users to change the setting with a COP command

controlstates = controlstates       ; System control state stanza
events = events                     ; Events Management
functions = functions               ; Repeater Function stanza
link_functions = functions          ; Link Function stanza
morse = morse                       ; Morse stanza
phone_functions = functions         ; Phone Function stanza
scheduler = schedule                ; Scheduler stanza
telemetry = telemetry               ; Telemetry stanza
wait_times = wait-times             ; Wait times stanza

;inxlat = *,#,0123456789ABCD,Y      ; The Y is for dialtone on function, a la CACTUS
                                    ; https://allstarlink.github.io/config/rpt_conf/#inxlat

context = radio                     ; dialing context for phone
callerid = "Repeater" <0000000000>  ; callerid for phone calls
accountcode = RADIO                 ; account code (optional)

hangtime = 500                     ; squelch tail hang time (in ms) (optional, default 5 seconds, 5000 ms)
althangtime = 500                  ; longer squelch tail
totime = 180000                     ; transmit time-out time (in ms) (optional, default to 180000 ms (3 minutes), maximum 9999999 ms (166 minutes))
time_out_reset_unkey_interval = 0   ; The minimum time for no carrier detect after the transmitter drops in a time out condition (optional).
									; This can be used to filter for noise and picket fencing during a time out condition.
									; Value is in milliseconds. Default is 0ms, minimum is 0ms, maximum is 3000ms
time_out_reset_kerchunk_interval = 250 ; Allows users to reset the time out timer when there is a signal coming in from a link (optional).
									; A value of 0 disables this feature. Valid only if time_time_out_reset_unkey_interval is non zero. 
									; Value is in milliseconds. Default is 250ms, minimum is 0ms, maximum is 3000ms
idrecording = |iNOTSET              ; id recording or morse string
;idtalkover =                       ; Talkover ID (optional) default is none
idtime = 540000                     ; id interval time (in ms) (optional) Default 5 minutes (300000 ms)
politeid = 30000                    ; time in milliseconds before ID timer expires to try and ID in the tail. (optional, default 30000)

;tailmessagelist=custom/yourtailmessage ; This list is ignored if the dialplan (extensions.conf) contains the extension TAIL
;tailsquashedtime=900000            ; 15 minutes
;tailmessagetime=21600000           ; 6 hours (200000000 ms, 55.5555 hours is the max value possible)

unlinkedct = ct2                    ; Send a this courtesy tone when the user unkeys if the node is not connected to any other nodes. (optional, default is none)
remotect = ct3                      ; remote linked courtesy tone (indicates a remote is in the list of links)
linkunkeyct = ct8                   ; sent when a transmission received over the link unkeys
;nolocallinkct = 0                  ; Send unlinkedct instead if another local node is connected to this node (hosted on the same PC).

;connpgm = yourconnectprogram       ; Disabled. Execute a program you specify on connect. (default)
                                    ; passes 2 command line arguments to your program:
                                    ; 1. node number in this stanza (us)
                                    ; 2. node number being connected to us (them)
;discpgm = yourdisconnectprogram    ; Disabled. Execute a program you specify on disconnect. (default)
                                    ; passes 2 command line arguments to your program:
                                    ; 1. node number in this stanza (us)
                                    ; 2. node number being disconnected from us (them)

;lnkactenable = 0                   ; Set to 1 to enable the link activity timer. Applicable to standard nodes only.

;lnkacttime = 1800                  ; Link activity timer time in seconds.
;lnkactmacro = *52                  ; Function to execute when link activity timer expires.
;lnkacttimerwarn = rpt/timeout-warning ; Message to play when the link activity timer has 30 seconds left.

;remote_inact_timeout =             ; Specifies the amount of time without keying from the link. Set to 0 to disable timeout. (15 * 60)
;remote_timeout =                   ; Session time out for remote base. Set to 0 to disable. (60 * 60)
;remote_timeout_warning_freq =      ; 30
;remote_timeout_warning =           ; (3 * 60)

;nounkeyct = 0                      ; Set to a 1 to eliminate courtesy tones and associated delays.

holdofftelem = 0                    ; Hold off all telemetry when signal is present on receiver or from connected nodes
                                    ; except when an ID needs to be done and there is a signal coming from a connected node.

telemnomdb = -3                     ; Telemetry Nominal Amplitude reference in dB
telemduckdb = -15                   ; Telemetry Ducking in dB when local or link voice TX in progress

telemdefault = 0                    ; 0 = telemetry output off
                                    ; 1 = telemetry output on (default = 1)
                                    ; 2 = timed telemetry output on command execution and for a short time thereafter.

telemdynamic = yes                  ; yes = disallow users to change the local telemetry setting with a COP command
                                    ; 1 = Allow users to change the setting with a COP command. (default = 1)

;beaconing = 0                      ; Send ID regardless of repeater activity (Required in the UK, but probably illegal in the US)

parrot = 0                          ; Parrot mode will echo the audio you transmit back to the node
                                    ; 0 = Parrot mode off or enabled with COP commands (default = 0)
                                    ; 1 = Parrot mode always on

parrottime = 1000                   ; Set the amount of time in milliseconds
                                    ; to wait before parroting what was received

;rxnotch=1065,40                    ; (Optional) Notch a particular frequency for a specified
                                    ; b/w. app_rpt must have been compiled with
                                    ; the notch option

;startup_macro =                    ; Best use in your node stanza (below) when more than one node

;nodenames = /usr/share/asterisk/sounds/custom/nodenames ; Point to alternate nodenames sound directory

;aprstt = general                   ; To enable APRStt, set this value to the stanza to use in gps.conf
                                    ; module app_gps.so will need to be enabled

; *** Status Reporting ***
;
; Uncomment the following "statpost_url" line to enable status reporting
; of all of your nodes to "stats.allstarlink.org".  To enable reporting
; of a single node then add the line (without the leading ";") to the
; per-node stanza(s).
;
;statpost_url = http://stats.allstarlink.org/uhandler ; Status updates
;
; Uncomment the following "statpost_time" line to control how frequently
; your nodes reports it's connected links.  This time does not affect the
; reporting of key up/down changes.
;statpost_time = 60                 ; (optional) time (in seconds) (min 30, max 600, default 60)

; *** Audio Archiving ***
;
; The following "archivedir" line can be used to enable a simple log and
; audio recorder of the activity on a node. When enabled, a series of
; recordings, one for each active COR on the node. The file(s) will be
; named with the date and time down to the 1/100th of a second. This
; logging can be useful in debugging, policing, or other creative things.
;
; The "archiveformat" line can be used to specify the format of the audio
; recordings. By default, the format will be "wav49" (GSM in a .WAV file).
; Other options you may consider include "wav" (SLIN in a .wav file) and
; "gsm" (GSM in straight gsm format).
;
; The "archivedatefmt" line can be used to specify the filename used for
; the recordings.  By default, the files will use a "%Y%m%d%H%M%S" date
; format that maps to YYYYMMDDHHMMSS.  If desired, you can specify any
; date format supported by the C function strftime(3) API.  For more
; precision, you can also include the '%[n]q' format to add fractions
; of a second, with leading zeros.
;
; The "archiveaudio" line can be used to control whether the both the
; simple activity log and audio recordings are included in the archive
; directory.  If set to "no" then only the log will be created (the
; audio recordings will not be saved).
;
; The "archivedir", "archiveformat", and "archivedatefmt" lines can be
; enabled here (affecting all nodes) or in the per-node stanzas (for
; recording of individual nodes).
;
; Note: enabling these recordings can adversely impact the CPU utilization
;       on the device and consume large amounts of the available storage.
;
;archivedir = /var/spool/asterisk/monitor ; top-level recording directory
;archiveformat = wav49                    ; audio format (default = wav49)
;archivedatefmt = %Y%m%d%H%M%S%2q         ; date/time (time to 1/100th secs)
;archiveaudio = yes                       ; enable/disable audio recordings (default = yes)

;;; End of node-main template

[functions-main](!)
;;;;;;;;;;;;;;;;;;; functions stanza ;;;;;;;;;;;;;;;;;;;
; Prefix    Functions
; *1        Disconnect Link
; *2        Monitor Link
; *3        Connect Link
; *4        Command Mode
; *5        Macros
; *6        User Functions
; *7        Connection Status/Functions
; *8        User Functions
; *9        User Functions
; *0        User Functions
; *A        User Functions
; *B        User Functions
; *C        User Functions
; *D        User Functions

;;;;;; Mandatory Command Codes ;;;;;
1 = ilink,1                         ; Disconnect specified link
2 = ilink,2                         ; Connect specified link -- monitor only
3 = ilink,3                         ; Connect specified link -- transceive
4 = ilink,4                         ; Enter command mode on specified link
70 = ilink,5                        ; System status
99 = cop,6                          ; PTT (phone mode only)

;;;;; Macro Commands ;;;;;
5 = macro

;;;;; Autopatch Commands ;;;;;
; Note, This may be a good place for other 2 digit frequently used commands
;61 = autopatchup,noct = 1,farenddisconnect = 1,dialtime = 20000  ; Autopatch up
;62 = autopatchdn                                                 ; Autopatch down

; autopatchup can optionally take comma delimited setting=value pairs:
;   context = string                ; Override default context with "string"
;   dialtime = ms                   ; Specify the max number of milliseconds between phone number digits (1000 milliseconds = 1 second)
;   farenddisconnect = 1            ; Automatically disconnect when called party hangs up
;   noct = 1                        ; Don't send repeater courtesy tone during autopatch calls
;   quiet = 1                       ; Don't send dial tone, or connect messages. Do not send patch down message when called party hangs up
                                    ; Example: 123=autopatchup,dialtime=20000,noct=1,farenddisconnect=1

;;;;; Status Commands ;;;;;
; 1 - Force ID (global)
; 2 - Give Time of Day (global)
; 3 - Give software Version (global)
; 4 - Give GPS location info
; 5 - Last (DTMF) user
; 11 - Force ID (local only)
; 12 - Give Time of Day (local only)

721 = status,1                      ; Force ID (global)
722 = status,2                      ; Give Time of Day (global)
723 = status,3                      ; Give software Version (global)
724 = status,4                      ; Give GPS location info
725 = status,5                      ; Last (DTMF) user
711 = status,11                     ; Force ID (local only)
712 = status,12                     ; Give Time of Day (local only)

;;;;; Link Commands ;;;;;
; 1 - Disconnect specified link
; 2 - Connect specified link -- monitor only
; 3 - Connect specified link -- transceive
; 4 - Enter command mode on specified link
; 5 - System status
; 6 - Disconnect all links
; 7 - Last Node to Key Up
; 8 - Connect specified link -- local monitor only
; 9 - Send Text Message (9,<destnodeno or 0 (for all)>,Message Text, etc.
; 10 - unused
; 11 - Disconnect a previously permanently connected link
; 12 - Permanently connect specified link -- monitor only
; 13 - Permanently connect specified link -- transceive
; 15 - Full system status (all nodes)
; 16 - Reconnect links disconnected with "disconnect all links"
; 17 - MDC test (for diag purposes)
; 18 - Permanently connect specified link -- local monitor only

;;;;; ilink commands ;;;;;
; commands 1 through 5 are defined in the Mandatory Command section

; 806 = ilink,6                     ; Disconnect all links
; 807 = ilink,7                     ; Last Node to Key Up
; 808 = ilink,8                     ; Connect specified link -- local monitor only
; 809 = ilink,9,500002,"Testing"      ; would send a text message to node 500002 replace 500002 with 0 for all connected nodes
; 810 = ilink,10                    ; unused
; 811 = ilink,11                    ; Disconnect a previously permanently connected link
; 812 = ilink,12                    ; Permanently connect specified link -- monitor only
; 813 = ilink,13                    ; Permanently connect specified link -- transceive
; 815 = ilink,15                    ; Full system status (all nodes)
; 816 = ilink,16                    ; Reconnect links disconnected with "disconnect all links"
; 817 = ilink,17                    ; MDC test (for diag purposes)
; 818 = ilink,18                    ; Permanently connect specified link -- local monitor only

;;;;; Control operator (cop) functions. ;;;;;
;Change these to something other than these codes listed below!

;901 = cop,1                        ; System warm boot
;902 = cop,2                        ; System enable
;903 = cop,3                        ; System disable

;904 = cop,4                        ; Test tone on/off (toggle)
;905 = cop,5                        ; Dump system variables on console (debug use only)

;907 = cop,7                        ; Time out timer enable
;908 = cop,8                        ; Time out timer disable

;909 = cop,9                        ; Autopatch enable
;910 = cop,10                       ; Autopatch disable

;911 = cop,11                       ; User linking functions enable
;912 = cop,12                       ; User linking functions disable

;913 = cop,13                       ; Query system control state
;914 = cop,14                       ; Set system control state

;915 = cop,15                       ; Scheduler enable
;916 = cop,16                       ; Scheduler disable

;917 = cop,17                       ; User functions enable (time, id, etc)
;918 = cop,18                       ; User functions disable

;919 = cop,19                       ; Select alternate hang time (althangtime)
;920 = cop,20                       ; Select standard hangtime (hangtime)

;921 = cop,21                       ; Enable Parrot Mode
;922 = cop,22                       ; Disable Parrot Mode
;923 = cop,23                       ; Birdbath (Current Parrot Cleanup/Flush)

;924 = cop,24                       ; Flush all telemetry
;925 = cop,25                       ; Query last node un-keyed
;926 = cop,26                       ; Query all nodes keyed/unkeyed
;930 = cop,30                       ; Recall Memory Setting in attached transceiver

;931 = cop,31                       ; Channel Selector for parallel programmed transceiver

;932 = cop,32                       ; Touchtone pad test: command + Digit string + # to playback all digits pressed

;933 = cop,33                       ; Local Telemetry Output Enable
;934 = cop,34                       ; Local Telemetry Output Disable
;935 = cop,35                       ; Local Telemetry Output on Demand

;936 = cop,36                       ; Foreign Link Local Output Path Enable
;937 = cop,37                       ; Foreign Link Local Output Path Disable
;938 = cop,38                       ; Foreign Link Local Output Path Follows Local Telemetry
;939 = cop,39                       ; Foreign Link Local Output Path on Demand

;942 = cop,42                       ; EchoLink announce node # only
;943 = cop,43                       ; EchoLink announce node Callsign only
;944 = cop,44                       ; EchoLink announce node # & Callsign

;945 = cop,45                       ; Link Activity timer enable
;946 = cop,46                       ; Link Activity timer disable
;947 = cop,47                       ; Reset "Link Config Changed" Flag

;948 = cop,48                       ; Send Page Tone (Tone specs separated by parenthesis)

; 949 = cop,49                      ; Disable incoming connections (control state noice)
; 950 = cop,50                      ; Enable incoming connections (control state noicd)

; 951 = cop,51                      ; Enable sleep mode
; 952 = cop,52                      ; Disable sleep mode
; 953 = cop,53                      ; Wake up from sleep
; 954 = cop,54                      ; Go to sleep
; 955 = cop,55                      ; Parrot Once if parrot mode is disabled

; 956 = cop,56                      ; RX CTCSS Enable
; 957 = cop,57                      ; RX CTCSS Disable

; 958 = cop,58                      ; TX CTCSS On Input only Enable
; 959 = cop,59                      ; TX CTCSS On Input only Disable

; 960 = cop,60                      ; Send MDC-1200 Burst (cop,60,type,UnitID[,DestID,SubCode])
                                    ; Type is 'I' for PttID, 'E' for Emergency, and 'C' for Call
                                    ; (SelCall or Alert), or 'SX' for STS (ststus), where X is 0-F.
                                    ; DestID and subcode are only specified for  the 'C' type message.
                                    ; UnitID is the local systems UnitID. DestID is the MDC1200 ID of
                                    ; the radio being called, and the subcodes are as follows:
                                    ; Subcode '8205' is Voice Selective Call for Spectra ('Call')
                                    ; Subcode '8015' is Voice Selective Call for Maxtrac ('SC') or
                                    ; Astro-Saber('Call')
                                    ; Subcode '810D' is Call Alert (like Maxtrac 'CA')

; 961 = cop,61                      ; Send Message to USB to control GPIO pins (cop,61,GPIO1=0[,GPIO4=1].....)
; 962 = cop,62                      ; Send Message to USB to control GPIO pins, quietly (cop,62,GPIO1=0[,GPIO4=1].....)

; 963 = cop,63                      ; Send pre-configured APRStt notification (cop,63,CALL[,OVERLAYCHR])
; 964 = cop,64                      ; Send pre-configured APRStt notification, quietly (cop,64,CALL[,OVERLAYCHR])
; 965 = cop,65                      ; Send POCSAG page (equipped channel types only)

; [functions-remote]
;;;;; Functions for remote bases ;;;;;
;
; 0 = remote,1                      ; Retrieve Memory
; 1 = remote,2                      ; Set freq.
; 2 = remote,3                      ; Set TX PL tone
; 3 = remote,4                      ; Set RX PL tone
; 40 = remote,100                   ; RX PL off
; 41 = remote,101                   ; RX PL on
; 42 = remote,102                   ; TX PL off
; 43 = remote,103                   ; TX PL on
; 44 = remote,104                   ; Low Power
; 45 = remote,105                   ; Medium Power
; 46 = remote,106                   ; High Power
; 51 = remote,5                     ; Long status query
; 52 = remote,140                   ; Short status query
; 61 = remote,61                    ; Set mode to FM
; 62 = remote,62                    ; Set mode to USB
; 63 = remote,63                    ; Set mode to LSB
; 64 = remote,64                    ; Set mode to AM
; 67 = remote,210                   ; Send a *
; 69 = remote,211                   ; Send a #
; 711 = remote,107                  ; Bump -20
; 714 = remote,108                  ; Bump -100
; 717 = remote,109                  ; Bump -500
; 713 = remote,110                  ; Bump +20
; 716 = remote,111                  ; Bump +100
; 719 = remote,112                  ; Bump +500
; 721 = remote,113                  ; Scan - slow
; 724 = remote,114                  ; Scan - quick
; 727 = remote,115                  ; Scan - fast
; 723 = remote,116                  ; Scan + slow
; 726 = remote,117                  ; Scan + quick
; 729 = remote,118                  ; Scan + fast
; 79 = remote,119                   ; Tune
; 91 = remote,99,CALLSIGN,LICENSETAG     ; Remote base login.
                                    ; Define a different DTMF sequence for each user which is
                                    ; authorized to use the remote base to control access to it.
                                    ; For example 9139583=remote,99,WB6NIL,G would grant access to
                                    ; the remote base and announce WB6NIL as being logged in.
                                    ; Another entry, 9148351=remote,99,WA6ZFT,E would grant access to
                                    ; the remote base and announce WA6ZFT as being logged in.
                                    ; When the remote base is disconnected from the originating node, the
                                    ; user will be logged out. The LICENSETAG argument is used to enforce
                                    ; TX frequency limits. See [txlimits] below.
; 85 = cop,6                        ; Remote base telephone key


[functions](functions-main)

[telemetry-main](!)
;;;;; Telemetry ;;;;;
; Telemetry entries can be shared across all repeaters, or defined for each repeater.
; Can be a tone sequence, morse string, or a file
;
; |t - Tone escape sequence
;
; Tone sequences consist of 1 or more 4-tuple entries (freq1, freq2, duration, amplitude)
; Single frequencies are created by setting freq1 or freq2 to zero.
;
; |m - Morse escape sequence
;
; Sends Morse code at the telemetry amplitude and telemetry frequency as defined in the
; [morse] section.
;
; Follow with an alphanumeric string
;
; |i - Morse ID escape sequence
;
; Sends Morse code at the ID amplitude and ID frequency as defined in the
; [morse] section.
;

ct1 = |t(350,0,100,2048)(500,0,100,2048)(660,0,100,2048)
ct2 = |t(660,880,150,2048)
ct3 = |t(440,0,150,4096)
ct4 = |t(550,0,150,2048)
ct5 = |t(660,0,150,2048)
ct6 = |t(880,0,150,2048)
ct7 = |t(660,440,150,2048)
ct8 = |t(700,1100,150,2048)
ct9 = |t(1633,0,50,1000)(0,0,30,0)(1209,0,50,1000)
remotemon = |t(1209,0,50,2048)                            ; local courtesy tone when receive only
remotetx = |t(1633,0,50,3000)(0,0,80,0)(1209,0,50,3000)   ; local courtesy tone when linked Trancieve mode
cmdmode = |t(900,903,200,2048)
functcomplete = |t(1000,0,100,2048)(0,0,100,0)(1000,0,100,2048)
remcomplete = |t(650,0,100,2048)(0,0,100,0)(650,0,100,2048)(0,0,100,0)(650,0,100,2048)
pfxtone = |t(350,440,30000,3072)
patchup = rpt/callproceeding
patchdown = rpt/callterminated

; As far as what the numbers mean,
; (000,000,010,000)
;   |   |   |   |-------amplitude
;   |   |   |-------------duration
;   |   |-------------------Tone 2
;   |-------------------------Tone 1

; So, with 0,0,10,0 That says No Tone1, No Tone2, 10ms duration, 0 Amplitude.
; Use it for a delay.  Fine tuning for how long before telemetry is sent, in conjunction with the telemdelay parameter)
; The numbers, like 350,440,10,2048 are 350Hz, 440Hz, 10ms delay, amplitude of 2048.

[telemetry](telemetry-main)

[morse-main](!)
;;;;; Morse code ;;;;;
; Morse code parameters, these are common to all repeaters.
speed = 20                          ; Approximate speed in WPM
frequency = 800                     ; Morse Telemetry Frequency
amplitude = 4096                    ; Morse Telemetry Amplitude
idfrequency = 1065                  ; Morse ID Frequency
idamplitude = 1024                  ; Morse ID Amplitude

;[morse]
;speed = 35                         ; Not legal in the USA
;frequency = 800                    ; Morse Telemetry Frequency
;amplitude = 4096                   ; Morse Telemetry Amplitude
;idfrequency = 750                  ; Morse ID Frequency        *Changed
;idamplitude = 512                  ; Morse ID Amplitude        *Changed


[morse](morse-main)

[wait-times-main](!)
; This section allows wait times for telemetry events to be adjusted
; A section for wait times can be defined for every repeater
telemwait = 2000                    ; Time to wait before sending most telemetry
idwait = 500                        ; Time to wait before starting ID
unkeywait = 2000                    ; Time to wait after unkey before sending CT's and link telemetry
calltermwait = 2000                 ; Time to wait before announcing "call terminated"

[wait-times](wait-times-main)

[wait-times_hd]
; Sample for half-duplex
telemwait = 100                     ; Time to wait before sending most telemetry
idwait = 100                        ; Time to wait before starting ID
unkeywait = 100                     ; Time to wait after unkey before sending CT's and link telemetry
calltermwait = 2000                 ; Time to wait before announcing "call terminated"

[memory]
;;;;; Remote base memories ;;;;;
; Memories for remote bases (not for repeaters or hotspots). Seldom used.
;00 = 146.580,100.0,m
;01 = 147.030,103.5,m+t
;02 = 147.240,103.5,m+t
;03 = 147.765,79.7,m-t
;04 = 146.460,100.0,m
;05 = 146.550,100.0,m

[macro]
;;;;;  Macro commands ;;;;;
;1 = *812000
;2 = *822000
;3 = *832000
;4 = *31998*32000

;[daq-list]
;;;;; Data Acquisition configuration ;;;;;
;Where: device_name1 and device_name2 are stanzas you define in this file
;device = daq-cham-1
;device = device_name1
;device = device_name2

;[daq-cham-1]                       ; Defined in [daq-list]
; Device name
;hwtype = uchameleon                ; DAQ hardware type
;devnode = /dev/ttyUSB0             ; DAQ device node (if required)
;1 = inadc                          ; Pin definition for an ADC channel
;2 = inadc
;3 = inadc
;4 = inadc
;5 = inadc
;6 = inadc
;7 = inadc
;8 = inadc
;9 = inp                            ; Pin definition for an input with a weak pullup resistor
;10 = inp
;11 = inp
;12 = inp
;13 = in                            ; Pin definition for an input without a weak pullup resistor
;14 = out                           ; Pin definition for an output
;15 = out
;16 = out
;17 = out
;18 = out

;[meter-faces]
;
;face = scale(scalepre,scalediv,scalepost),word/?,...
;
; scalepre = offset to add before dividing with scalediv
; scalediv = full scale/number of whole units (e.g. 256/20 or 12.8 for 20 volts).
; scalepost = offset to add after dividing with scalediv
;
;face = range(X-Y:word,X2-Y2:word,...),word/?,...
;face = bit(low-word,high-word),word/?,...
;
; word/? is either a word in /usr/share/asterisk/sounds or one of its subdirectories,
; or a question mark which is  a placeholder for the measured value.
;
;
; Battery voltage 0-20 volts
;batvolts = scale(0,12.8,0),rpt/thevoltageis,?,ha/volts
; 4 quadrant wind direction
;winddir = range(0-33:north,34-96:west,97-160:south,161-224:east,225-255:north),rpt/thewindis,?
; LM34 temperature sensor with 130 deg. F full scale
;lm34f = scale(0,1.969,0),rpt/thetemperatureis,?,degrees,fahrenheit
; Status poll (non alarmed)
;light = bit(ha/off,ha/on),ha/light,?

;[alarms]
;
;tag = device,pin,node,ignorefirst,func-low,func-hi
;
;tag = a unique name for the alarm
;device = daq device to poll
;pin = the device pin to be monitored
;ignorefirstalarm = set to 1 to throwaway first alarm event, or 0 to report it
;node = the node number to execute the function on
;func-low = the DTMF function to execute on a high to low transition
;func-high = the DTMF function to execute on a low to high transition
;
; a  '-' as a function name is shorthand for no-operation
;
;door = daq-cham-1,9,1,2017,*7,-
;pwrfail = daq-cham-1,10,0,2017,*911111,-

[events-main](!)
;;;;; Events Management ;;;;;
;status,2 = c|f|RPT_NUMLINKS               ; Say time of day when all links disconnect.

[events](events-main)

[controlstates]
;;;;; Control states ;;;;;
; Allow several control operator functions to be changed at once using one command (good for scheduling)
;statenum = copcmd,[copcmd]... https://allstarlink.github.io/config/rpt_conf/#control-states-stanza
0 = rptena,lnkena,apena,totena,ufena,noicd  ; Normal operation
1 = rptena,lnkena,apdis,totdis,ufena,noice  ; Net and news operation
2 = rptena,lnkdis,apdis,totena,ufdis,noice  ; Repeater only operation

[schedule]
;;;;; Scheduler - execute a macro at a given time ;;;;;
;dtmf_function =  m h dom mon dow   ; ala cron, star is implied
;2 = 00 00 * * *                    ; at midnight, execute macro 2.

#tryinclude "custom/rpt.conf"
#tryinclude "custom/rpt/*.conf"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;; Configure your nodes here ;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;
; Note: there is no need to duplicate entire settings. Only
;       place settings that are different than the template.
;

;;;;;;;;;;;;;;;;;;; Your node settings here ;;;;;;;;;;;;;;;;;;;
[events-652702](events-main,events-hotspotradio-usb)

[500001](node-main)
; nodelisten: sends this node's audio to the Node Listen page (remove it from that page)
outstreamcmd = /usr/bin/python3,/usr/local/bin/nodelisten.py,--feed,6200
rxchannel = SimpleUSB/500001
events = events-500001
statpost_url = http://stats.allstarlink.org/uhandler
idrecording = |iN0CALL
duplex = 0
hangtime = 100
;startup_macro = *31999

;;;;;;;;;;;;;;;;;; Settings for another node ;;;;;;;;;;;;;;;;;;
;[500005](node-main)
;startup_macro = *8132000
;morse = morse_500005                 ; Sample morse stanza for node 500005

[500002](node-main)
rxchannel = USRP/127.0.0.1:34001:32001
idrecording = |iN0CALL
duplex = 0
hangtime = 100
linktolink = no


[500003](node-main)
rxchannel = USRP/127.0.0.1:34008:32008
idrecording = |iN0CALL
duplex = 0
hangtime = 100
linktolink = no

; >>> dvs-phone (managed by asl_dvs_dashboard - edits inside are overwritten) >>>
[1001](node-main)
rxchannel = Local/pseudo
context = dvs-node-dvshoip
callerid = "Phone" <0000000000>
functions = functions1001
phone_functions = functions1001
link_functions = functions1001
duplex = 1
voxtimeout = 10000
voxrecover = 2000
simplexpatchdelay = 25
simplexphonedelay = 25

[functions1001]
61 = autopatchup,noct=1,farenddisconnect=1,dialtime=20000,context=dvs-radio-dvshoip,quiet=1
62 = cmd,/var/lib/asterisk/dvs_phone_hangup
63 = cop,9
64 = cop,10
65 = cmd,/var/lib/asterisk/dvs_phone_hangup
99 = cop,6
980 = cmd,/var/lib/asterisk/dvs_phone_tonecode 0
981 = cmd,/var/lib/asterisk/dvs_phone_tonecode 1
982 = cmd,/var/lib/asterisk/dvs_phone_tonecode 2

[1002](node-main)
rxchannel = Local/pseudo
context = dvs-node-dvsamateurwire
callerid = "Phone" <0000000000>
functions = functions1002
phone_functions = functions1002
link_functions = functions1002
duplex = 1
voxtimeout = 10000
voxrecover = 2000
simplexpatchdelay = 25
simplexphonedelay = 25

[functions1002]
61 = autopatchup,noct=1,farenddisconnect=1,dialtime=20000,context=dvs-radio-dvsamateurwire,quiet=1
62 = cmd,/var/lib/asterisk/dvs_phone_hangup
63 = cop,9
64 = cop,10
65 = cmd,/var/lib/asterisk/dvs_phone_hangup
99 = cop,6
980 = cmd,/var/lib/asterisk/dvs_phone_tonecode 0
981 = cmd,/var/lib/asterisk/dvs_phone_tonecode 1
982 = cmd,/var/lib/asterisk/dvs_phone_tonecode 2
; <<< dvs-phone <<<

; nodelisten: transmit node for the Node Listen page (remove it from that page)
[500004](node-main)
rxchannel = USRP/127.0.0.1:34018:32018
duplex = 0
hangtime = 0
althangtime = 0
holdofftelem = 1
telemdefault = 0
nounkeyct = 1
```

### /etc/asterisk/rpt_http_registrations.conf

```
[general]
register_interval = 180 ; every 3 minutes

[registrations]
register => 500001:<redacted:ce67a6b3>@register.allstarlink.org
```

### /etc/asterisk/savenode.conf

```
# config file for /usr/sbin/savenode
NODE=500001
PASSWORD=<redacted:10c828f3>
ENABLE=1
```

### /etc/asterisk/simpleusb.conf

```
;!
;! Automatically generated configuration file
;! Filename: simpleusb.conf (/etc/asterisk/simpleusb.conf)
;! Generator: chan_simpleusb
;! Creation Date: Sun Aug 23 08:33:51 2026
;!
;***************************************************
;********   Template-tized simpleusb.conf   ********
;***************************************************
; Note to editors: set tabs to 4 space characters. No wrap to keep comments neat.
; vim: tabstop=4
;
; SimpleUSB channel driver Configuration File
;
; See https://allstarlink.github.io/config/simpleusb_conf/ for full option documentation.
;
;;;;;                 New to ASL3                 ;;;;;
;;;;; The SimpleUSB "tune" settings have moved to ;;;;;
;;;;; this file. The simpleusb_tune_usb_500002.conf ;;;;;
;;;;; file is no longer used.                     ;;;;;

; If you are going to use this channel driver, you MUST enable it in modules.conf
; change:
; noload => chan_simpleusb.so       ; CM1xx USB Cards with Radio Interface Channel Driver (No DSP)
; noload => res_usbradio.so         ; Required for both simpleusb and usbradio
; to:
; load => chan_simpleusb.so         ; CM1xx USB Cards with Radio Interface Channel Driver (No DSP)
; load => res_usbradio.so           ; Required for both simpleusb and usbradio

[general]
;------------------------------ JITTER BUFFER CONFIGURATION --------------------------
jbenable = yes              ; Enables the use of a jitterbuffer on the receiving side of an
                              ; simpleusb channel. Defaults to "no". An enabled jitterbuffer will
                              ; be used only if the sending side can create and the receiving
                              ; side can not accept jitter. The simpleusb channel can't accept jitter,
                              ; thus an enabled jitterbuffer on the receive simpleusb side will always
                              ; be used if the sending side can create jitter.

jbmaxsize = 200             ; Max length of the jitterbuffer in milliseconds.

jbresyncthreshold = 1000    ; Jump in the frame timestamps over which the jitterbuffer is
                              ; resynchronized. Useful to improve the quality of the voice, with
                              ; big jumps in/broken timestamps, usually sent from exotic devices
                              ; and programs. Defaults to 1000.

jbimpl = fixed              ; Jitterbuffer implementation, used on the receiving side of an simpleusb
                              ; channel. Two implementations are currently available - "fixed"
                              ; (with size always equals to jbmax-size) and "adaptive" (with
                              ; variable size, actually the new jb of IAX2). Defaults to fixed.

jblog = no                  ; Enables jitterbuffer frame logging. Defaults to "no".
;-----------------------------------------------------------------------------------

[node-main](!)
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;; Template for all your SimpleUSB nodes ;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

eeprom = 0                          ; EEPROM installed: 0,1
                                    ; 0 = no (radio interface does not have an EEPROM)
                                    ; 1 = yes (default)

hdwtype = 0                         ; Leave this set to 0 for USB sound fobs designed for app_rpt
                                    ; or modified cmxxx sound fobs.
                                    ; 1 is for Dingotel/Sph interfaces.
                                    ; 2 is for NHC interfaces.
                                    ; 3 is for a custom interface.

; Receiver parameters
rxboost = no                        ; no = 20db attenuator inserted, yes = 20db attenuator removed
                                    ; Set to yes for additional gain if using a low-level receiver output
                                    ; CM119B devices are hard coded to rxboost 20dB attenuator removed

carrierfrom = usbinvert             ; no,usb,usbinvert
                                    ; no - no carrier detection at all
                                    ; usb - from the COR line on the USB sound fob (Active high)
                                    ; usbinvert - from the inverted COR line on the USB sound fob (Active low)
                                    ; pp - from parallel port (Active high)
                                    ; ppinvert - from the inverted parallel port (Active low)

;ctcssfrom = usbinvert               ; no,usb,usbinvert
                                    ; no - CTCSS decoding, system will be carrier squelch
                                    ; usb - CTCSS decoding using input from USB sound fob (Active high)
                                    ; usbinvert - from the inverted CTCSS line on the USB sound fob (Active low)
                                    ; pp - from parallel port (Active high)
                                    ; ppinvert - from the inverted parallel port (Active low)

deemphasis = no                     ; enable de-emphasis (input from discriminator)

plfilter = yes                      ; enable PL filter

rxondelay = 0                       ; Number of 20ms audio frames to delay after the hardware COR goes active, 
                                    ; before the signal is considered valid and COR is asserted to app_rpt. 
                                    ; If txoffdelay is also set (non-zero), then the transmitter has to be off 
                                    ; for txoffdelay AND COR has to be active for rxondelay before COR is 
                                    ; asserted to app_rpt. The default is 0. Use this ONLY on simplex nodes, 
                                    ; to eliminate "Ping Ponging". Leave commented out for repeaters or 
                                    ; other full duplex nodes.

txoffdelay = 0                      ; Number of 20ms audio frames the transmitter has to be un-keyed before a 
                                    ; hardware COR signal is considered valid, and COR is asserted to app_rpt. 
                                    ; If rxondelay is also set (non-zero), then the transmitter has to be off 
                                    ; for txoffdelay AND COR has to be active for rxondelay before COR is 
                                    ; asserted to app_rpt. The default is 0. Leave commented out for normal 
                                    ; repeaters or other full duplex nodes.
                                    ; This is useful when setting up a half-duplex link with an existing
                                    ; repeater, where you need to ignore the repeater's hangtime.

; Transmitter parameters
invertptt = no                      ; Invert PTT: no,yes
                                    ; no  - ground to transmit
                                    ; yes - open to transmit

preemphasis = no                    ; Perform standard 6db/octave pre-emphasis

; pager = no                        ; no,a,b (e.g. pager = b means "put the normal repeat audio on channel A, and the pager audio on channel B")

; duplex3 = 0                       ; duplex 3 gain setting (0 to disable)

clipledgpio = 1                     ; Enable ADC Clip Detect feature to use a GPIO output (0 to disable).
                                    ; Supports URI Clip LED by setting a GPIO (if available) high for 500mS
                                    ; when clipping detected. Value = GPIO# to use (GPIO1 recommended)

legacyaudioscaling = no             ; If yes, continue to do raw audio sample scaling and clipping, resulting in Tx audio levels increasing
                                    ; by 0.78dB and Rx audio levels increasing by 0-1.5dB. Should be set to no unless you have an existing
                                    ; node with precisely adjusted audio levels and are unable to adjust them. This parameter and associated
                                    ; scaling/clipping code will be deleted once existing installs have been able to verify their audio levels

;;; End of node-main template

#tryinclude "custom/simpleusb.conf"
#tryinclude "custom/simpleusb/*.conf"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;; Configure your nodes here ;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;
; Note: there is no need to duplicate entire settings. Only
;       place settings that are different than the template.
;
; Note: the device string is automatically found when the
;       USB setting "devstr=" and "serial=" are both empty.
;
; Note: the interface "tune" settings will be added to the
;       per-node settings (below).

[500001](node-main,hotspotradio-usb)

;;;;; Tune settings ;;;;;
devstr = 
serial = 
rxmixerset = 600
txmixaset = 700
txmixbset = 700
carrierfrom = usbinvert 
ctcssfrom = no

rxboost = no
deemphasis = yes
preemphasis = yes

rxondelay = 2
txoffdelay = 2
```

### /etc/asterisk/usbradio.conf

```
;**************************************************
;********   Template-tized usbradio.conf   ********
;**************************************************
; Note to editors: set tabs to 4 space characters. No wrap to keep comments neat.
; vim: tabstop=4
;
; USBRadio channel driver Configuration File
;
;;;;;                 New to ASL3                 ;;;;;
;;;;; The USBRadio "tune" settings have moved to  ;;;;;
;;;;; this file. The usbradio_tune_usb_500002.conf  ;;;;;
;;;;; file is no longer used.                     ;;;;;

; If you are going to use this channel driver, you MUST enable it in modules.conf
; noload => chan_usbradio.so    ; CM1xx USB Cards with Radio Interface Channel Driver (DSP)
; noload => res_usbradio.so     ; Required for both simpleusb and usbradio
; to:
; load => chan_usbradio.so      ; CM1xx USB Cards with Radio Interface Channel Driver (DSP)
; load => res_usbradio.so       ; Required for both simpleusb and usbradio

[general]
;------------------------------ JITTER BUFFER CONFIGURATION --------------------------
; jbenable = yes            ; Enables the use of a jitterbuffer on the receiving side of an
                            ; USBRADIO channel. Defaults to "no". An enabled jitterbuffer will
                            ; be used only if the sending side can create and the receiving
                            ; side can not accept jitter. The USBRADIO channel can't accept jitter,
                            ; thus an enabled jitterbuffer on the receive USBRADIO side will always
                            ; be used if the sending side can create jitter.

; jbmaxsize = 200           ; Max length of the jitterbuffer in milliseconds.

; jbresyncthreshold = 1000  ; Jump in the frame timestamps over which the jitterbuffer is
                            ; resynchronized. Useful to improve the quality of the voice, with
                            ; big jumps in/broken timestamps, usually sent from exotic devices
                            ; and programs. Defaults to 1000.

; jbimpl = fixed            ; Jitterbuffer implementation, used on the receiving side of an USBRADIO
                            ; channel. Two implementations are currently available - "fixed"
                            ; (with size always equals to jbmax-size) and "adaptive" (with
                            ; variable size, actually the new jb of IAX2). Defaults to fixed.

; jblog = no                ; Enables jitterbuffer frame logging. Defaults to "no".
;-----------------------------------------------------------------------------------

[node-main](!)
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;; Template for all your USBRadio nodes ;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

eeprom = 0                  ; EEPROM installed: 0,1
                            ; 0 = no (default)
                            ; 1 = yes

hdwtype = 0                 ; Leave this set to 0 for USB sound fobs modified using
                            ; the instructions from usbfob.pdf. Use a setting of
                            ; 1 is for Dingotel/Sph interfaces.

rxboost = yes               ; no  - 20db attenuator inserted
                            ; yes - 20db attenuator removed
                            ; Set to yes for additional gain if using a low-level receiver output
                            ; CM119B devices are hard coded to rxboost 20dB attenuator removed

rxctcssrelax = 1            ; reduce talkoff from radios w/o CTCSS TX HPF
                            ; Do not change this, leave this as a 1

rxsqhyst = 3000             ; Setting Squelch Hysteresis
                            ; 3000 is the default amount.
                            ; An amount of 500 seems good.
                            ; Then set the squelch to the highest number revealed when doing a "radio
                            ; tune rxsquelch" - running the command multiple (like 20) times in a row.

txctcssdefault = 100.0      ; default TX CTCSS frequency, any frequency permitted
rxctcssfreqs = 100.0,91.5   ; RX CTCSS frequencies list in floating point. must be in table
txctcssfreqs = 100.0,91.5   ; TX CTCSS frequencies list. any frequency permitted. will follow RX CTCSS frequency
rxctcssoverride = no        ; Set to yes to start out in carrier squelch mode

carrierfrom = dsp           ; no,usb,usbinvert,dsp,vox
                            ; no - no carrier detection at all
                            ; usb - from the COR line on the USB sound fob (Active high)
                            ; usbinvert - from the inverted COR line on the USB sound fob (Active low)
                            ; dsp - from RX noise using DSP techniques
                            ; vox - voice activated from RX audio
                            ; pp - from parallel port (Active high)
                            ; ppinvert - from the inverted parallel port (Active low)

voxhangtime = 2000          ; If carrierfrom=vox, mS to wait detecting RX audio before setting rxcarrierdetect=0
                            ; 2000 is the default but results in 2 seconds of silence added after RX unkey.
                            ; 500 seems more optimal. Lower values may result in unintended drops in RX CD.

ctcssfrom = dsp             ; no,usb,usbinvert,dsp
                            ; no - no CTCSS decoding, system will be carrier squelch
                            ; usb - from the CTCSS line on the USB sound fob (Active high)
                            ; usbinvert - from the inverted CTCSS line on the USB sound fob (Active low)
                            ; dsp - CTCSS decoding using RX audio in DSP.
                            ; rxdemod option must be set to flat for this to work.
                            ; pp - from parallel port (Active high)
                            ; ppinvert - from the inverted parallel port (Active low)

rxdemod = flat              ; input type from radio: no,speaker,flat
                            ; no - RX audio input not used
                            ; flat - Use RX audio from discriminator (before de-emphasis)
                            ; speaker - use de-emphasized audio

rxsquelchdelay = 30         ; delayline in ms carrier squelch tail eliminator

rxondelay = 0               ; Number of 20mSec intervals following the release of PTT.
                            ; Uncomment and/or adjust for simplex nodes to eliminate "Ping Ponging"
                            ; or "Relay Racing". A positive value here will instruct the usbradio
                            ; driver to ignore the COR line for a specified number of 20mSec
                            ; intervals following the release of PTT. Use this ONLY on simplex
                            ; nodes, and leave commented out for repeaters or other full duplex nodes.

txoffdelay = 0              ; Ignore the receiver for a specified number of 20 millisecond
                            ; intervals after the transmitter unkeys.
                            ; This is useful when setting up a half-duplex link with an existing
                            ; repeater, where you need to ignore the repeater's hangtime.

txboost = no                ; Add transmitter audio gain boost: no,yes

txprelim = yes              ; Audio processing on left output channel: no,yes
                            ; no  - Audio is not pre-emphasized and limited.
                            ;   (suitable for use on a microphone input)
                            ; yes - Audio is pre-emphasized and limited.
                            ;   (suitable for direct connection to an FM modulator)

txlimonly = yes             ; Audio limiting with no pre-emphasis on output channel: no,yes
                            ; no  - Audio is not limited.
                            ; yes - Audio is  limited.
                            ; Suitable for transmitters with no limiting but with pre-emphasis.

txtoctype = notone          ; Transmit tone control type: no,phase,notone
                            ; no - CTCSS tone encoding with no hang time
                            ; phase - encode CTCSS and reverse phase before unkeying TX (AKA "reverse burst")
                            ; notone - encode CTCSS and stop sending tone before unkeying TX (AKA "chicken burst")

txmixa = composite          ; Left channel output: no,voice,tone,composite,auxvoice
                            ; no - Do not output anything
                            ; voice - output voice only
                            ; tone - CTCSS tone only
                            ; composite - voice and tone
                            ; auxvoice - auxiliary voice output at headphone level for monitoring

txmixb = no                 ; Right channel output: no,voice,tone,composite, auxvoice
                            ; no - Do not output anything
                            ; voice - output voice only
                            ; tone - CTCSS tone only
                            ; composite - voice and tone
                            ; auxvoice - auxiliary voice output at headphone level for monitoring

; Audio filters
rxlpf = 0                   ; Receiver Audio Low Pass Filter 0,1 2
                            ; 0 - 3.0 kHz cutoff (Default) value for reduced noise and increased intelligibility.
                            ; 1 - 3.3 kHz cutoff for increased high end, sibilance and brightness.
                            ; 2 - 3.5 kHz cutoff for even more high end, sibilance and brightness.
rxhpf = 0                   ; Receiver Audio High Pass Filter 0,1
                            ; 0 - 300 Hz cutoff. (Default) value to reduce sub-audible signals for retransmission and in the receiver speaker.
                            ; 1 - 250 Hz cutoff for additional received and retransmitted bass response.
                            ; recommend using this filter with a CTCSS tone no higher than 186.2 Hz.
txlpf = 0                   ; Transmitter Audio Low Pass Filter 0,1
                            ; 0 - 3.0 kHz cutoff. (Default) value.
                            ; 1 - 3.3 kHz cutoff for increased high end, sibilance and brightness.
txhpf = 0                   ; Transmitter Audio High Pass Filter 0,1,2
                            ; 0 - 300 Hz cutoff. (Default) value to reduce interference between voice and sub-audible signaling tones and codes.
                            ; 1 - 250 Hz cutoff for increased bass response in transmitted audio.
                            ; 2 - 120 Hz cutoff for special applications requiring additional bass response in transmitted audio.
                            ; Not recommended due to the increased possibility of voice energy interfering with sub-audible signaling

invertptt = no              ; Invert PTT: no,yes
                            ; no  - ground to transmit
                            ; yes - open to transmit

duplex = 0                  ; Duplex 0,1
                            ; 0 - half duplex
                            ; 1 - full duplex
duplex3 = 0                 ; duplex 3 gain setting (0 to disable) ???

clipledgpio = 0             ; Enable ADC Clip Detect feature to use a GPIO output (0 to disable).
                            ; Supports URI Clip LED by setting a GPIO (if available) high for 500mS
                            ; when clipping detected. Value = GPIO# to use (GPIO1 recommended)

legacyaudioscaling = no     ; If yes, continue to do raw audio sample scaling and clipping, resulting in Tx audio levels increasing
                            ; by 0.83dB and Rx audio levels decreasing by 1.94dB. Should be set to no unless you have an existing
                            ; node with precisely adjusted audio levels and are unable to adjust them. This parameter and associated
                            ; scaling/clipping code will be deleted once existing installs have been able to verify their audio levels

;;; End of node-main template

#tryinclude "custom/usbradio.conf"
#tryinclude "custom/usbradio/*.conf"

;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;; Configure your nodes here ;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;
; Note: there is no need to duplicate entire settings. Only
;       place settings that are different than the template.
;
; Note: the device string is automatically found when the
;       USB setting "devstr=" and "serial=" are both empty.
;
; Note: the interface "tune" settings will be added to the
;       per-node settings (below).

[500001](node-main)

;;;;; ASL3 Tune settings ;;;;;
devstr=
serial=
rxmixerset=400
txmixaset=500
txmixbset=0
carrierfrom = usbinvert
ctcssfrom = no
rxvoiceadj=0.500000
txctcssadj=250
rxsquelchadj=500
rxctcssadj = 0.500000
fever = 0
txslimsp = 51000
```

### /etc/asterisk/voter.conf

```
[general]
;bindaddr = 198.51.100.15          ; specify a particular IP address to bind to (not generally used, defaults to bind to all interfaces)
port = 1667                     ; specifies the UDP port to use for incoming connections
buflen = 480                    ; specifies the receive buffer length in milliseconds.
                                ; This parameter should be set to the maximum expected network latency,
                                ; plus a little padding (100 milliseconds of padding is a good amount).
                                ; The default is 480 milliseconds, the minimum is 320 milliseconds.
                                ; Buffer length may be specified on a per-stanza and per-client basis, see below.

password = <redacted:6956a51e>
utos = y                        ; Turn on IP TOS for Ubiquiti (ToS is enable by default on the RTCM/VOTER) from the host TO the clients

;sanity = 0                     ; disable sanity checking of clients (debug use only) defaults to 1 if not specifically set to 0
;puckit = 1                     ; KLUDGE to try and fix random Garmin LVC-18 pucks that may or may not be 1 second off (defaults to 0 if not specified or set to 1)

[500001]                          ; define the 500002 instance stanza
Main = secret,transmit,master   ; master,transmit,adpcm,nodeemp,noplfilter,buflen=value,gpsid[=value],prio=value
                                ; 
                                ; master - this client is the Master Timing source (the RTCM client that is on the same LAN as the Asterisk server.)
                                ; There can only be 1 Master Timing source per ENTIRE Asterisk server.
                                ; 
                                ; secret - password unique to this client
                                ; transmit - this client is intended to have transmit audio sent to it and will have a transmitter connected to it.
                                ; adpcm - this client is to be sent audio in 8000 samples/sec, 4-bit, IMA ADPCM format, rather than default G.711 (ulaw).
                                ; nodeemp - this client is not to perform de-emphasis of the receiver audio  (This is only to be used with non-voting clients). Switches 
                                ; the hardware de-emphasis filter OUT on the client
                                ; noplfilter - this client is to not to perform hardware pl filtering of the audio. Switches the hardware PL filter OUT on the client.
                                ; buflen=value - receive buffer length override for this client only.
                                ; gpsid[=value] - This specifies a gps identity to associate with the specified client (as referred in the /etc/asterisk/gps.conf file).
                                ; prio=value - define a specific priority for this client when voting. Lower numbers are higher priority. Default is 0 if nothing specified.

plfilter = y                    ; use DSP IIR 6 pole High pass filter, 300 Hz corner with 0.5 db ripple (note clients filter PL by default already)

;txctcss = 100.0                 ; Transmit CTCSS frequency
;txctcsslevel = 62               ; Transmit CTCSS level (default of 62 if txctcss is supplied, but txctcsslevel is not set)
                                 ; Setting CTCSS level adds preemphasis. Assumes modulator input.
;txtoctype = phase               ; Transmit tone control type: none,phase,notone
                                ; none - CTCSS tone encoding with no hang time (default)
                                ; phase - encode CTCSS and reverse phase (AKA "reverse burst") before unkeying TX
                                ; notone - encode CTCSS and stop sending tone before unkeying TX (AKA "chicken burst")

;gtxgain = 3.0                  ; adjust the audio gain to all transmitters (in db voltage gain)
;hostdeemp = 1                  ; force the use of the DSP FIR Integrator providing de-emphasis at 8000 samples/sec. Used with Duplex Mode 3 setting in RTCM/VOTER

thresholds = 255,110=5          ;
; linger=6                      ; linger default is 6 if no other value specified
; streams = 198.51.100.16:1667 ; location to send voter data stream for this instance (used only with votemond Java program, which is deprecated)

; isprimary = y                 ; used in redundant server applications only. must be set on the primary server only
; primary = 198.51.100.17:1667,mypaswd  ; used in redundant server applications only. must be ONLY set on the secondary server to point to the primary

[500005]                          ; define another voting instance on this server (for another node). Three simulcast transmitters and four receivers.
                                ; NOTE: there is NO "master" in this instance, since we already have a master timing source on this server defined above 

NORTH = password_1,transmit     ; transmit/receive site
SOUTH = Password_2,transmit     ; transmit/receive site
EAST = password_3,nodeemp       ; receive-only site, bypass de-emphasis filter in RTCM
WEST = Password_4,transmit,noplfilter   ; transmit/receive site, bypass CTCSS filter in RTCM
```

### /etc/asterisk/custom/README.md

````

# ASL3 Node Menu Customization

## "/etc/asterisk/custom" directory

The "/etc/asterisk/custom" directory contains customizations to the ASL3 configuration files.
The base file and the optional customization(s) include :

| "/etc/asterisk" file | Can be customized / extended with
| -------------------- | ---------------------------------
| echolink.conf | custom/echolink.conf
| extensions.conf | custom/extensions.conf
| gps.conf | custom/gps.conf
| iax.conf | custom/iax.conf
| rpt.conf | custom/rpt.conf, custom/rpt/\*.conf
| simpleusb.conf | custom/simpleusb.conf, custom/simpleusb/\*.conf
| usbradio.conf | custom/usbradio.conf, custom/usbradio/\*.conf

## "rpt.conf" customizations

Customizations to "rpt.conf" are special.
In addition to the "custom/rpt.conf" file we also include ".conf" files in the "custom/rpt/" directory.
Each of these ".conf" files can include a comment line with the following format :

```
;MENU:keyed-gpio4:node:Assert GPIO (pin 4) when keyed
```

The ASL3 node setup menu looks for these specially formatted comment lines
to present customization options.  Each line consists of 4 fields separated by
":" characters.

| Field | Text           | Description
| :---: | :------------: | :----------
| #1    | ;MENU          | This field starts with a leading ";" (it's a comment) followed by the string "MENU"
| #2    | \<category>    | This field names the [category] to associate with the node
| #3    | \<type>        | This field name(s) the type of customization
| #4    | \<description> | This field describes the node customization

For node customizations that apply to the `/etc/asterisk/rpt.conf` file, the \<type> value is one (or more) of the following customizaton values.  Multiple \<type> values should be separated by comma (",") characters.

| \<type>    | Description
| :--------: | :----------
| node       | Updates the [#####] node settings
| events     | Updates the [events] settings
| functions  | Updates the [functions] settings
| telemetry  | Updates the [telemetry] settings
| wait-times | Updates the [wait-times] settings

Two additional \<type> values can be added to `/etc/asterisk/rpt.conf` customizations.
The values, `duplex` and `rxchannel`, mirror information that must be present in the associated templates.
If these values are included, and both must be specified, then the customization will be included in the "new" node type selection menu.

| \<type>                          | Description
| :------------------------------: | :----------
| `duplex=(0|1|2|3|4)`             | Specifies the `duplex` value **in** the template
| `rxchannel=(SimpleUSB|USBRadio)` | Specifies the `rxchannel` value **in** the template

## "simpleusb.conf" customizations

Customizations to "simpleusb.conf" are also special.
In addition to the "custom/simpleusb.conf" file we also include ".conf" files in the "custom/simpleusb/" directory.
As with the "rpt.conf" customizations, we also look for the specially formatted comment lines.
These customizations will be added for to the menu for any node using the "SimpleUSB" channel driver.

For audio interface customizations that apply to the `/etc/asterisk/simpleusb.conf` file, the \<type> value should be set to "simpleusb".

| \<type>    | Description
| :--------: | :----------
| simpleusb  | Updates the audio interface settings

## "usbradio.conf" customizations

Customizations to "usbradio.conf" are also special.
In addition to the "custom/usbradio.conf" file we also include ".conf" files in the "custom/usbradio/" directory.
As with the "rpt.conf" customizations, we also look for the specially formatted comment lines.
These customizations will be added for to the menu for any node using the "SimpleUSB" channel driver.

For audio interface customizations that apply to the `/etc/asterisk/usbradio.conf` file, the \<type> value should be set to "usbradio".

| \<type>    | Description
| :--------: | :----------
| usbradio   | Updates the audio interface settings

## Changes to the "rpt.conf" configuration file

Some changes to the "rpt.conf" file are needed in order to support these menu customizations.

1. All of the "\[####]" node stanzas must be at the end of the file.
2. Prior to the "\[####]" stanza we have added a set of "#tryinclude" statements like those shown below.  These statements will look for, and optionally include the contents of, configuration customization files that can be referenced by the node stanzas that follow after the "#tryinclude"s.

```
#tryinclude "custom/rpt.conf"
#tryinclude "custom/rpt/*.conf"
```

## Using Asterisk templates

In ASL3, the configuration of each node is typically setup with the node (e.g. [63001]) inheriting from the [node-main] category and any settings overriding those in the template.
The ASL3 node setup customization menu adds to the list of categories inherited by the node.

Without any customizations, the "rpt.conf" node configuration might look like :

```
[63001](node-main)
idrecording = |iWB6NIL
```

The **Assert GPIO (pin 4) when keyed** customization adds additional "events" to a node.  To support this customization the menu will make the following changes :

- We create a new "[events-63001]" stanza for the node.
The stanza is setup to inherit events being made available to all nodes ("[events-main]") and the new GPIO pin 4 events ("[events-keyed-gpio4]").

- We update the per-node settings ("[63001]") to reference the new event stanza.

The changes would look like :

```
[events-63001](events-main,events-keyed-file)   <--- Added

[63001](node-main)
events = events-63001                           <--- Added
idrecording = |iWB6NIL
```

For more about templates, please refer to the Asterisk [Using Templates](https://docs.asterisk.org/Fundamentals/Asterisk-Configuration/Asterisk-Configuration-Files/Templates/Using-Templates/?h=template) documentation.

## Viewing a customized node configuration

The GitHub [ASL3 menu](https://github.com/AllStarLink/asl3-menu.git) project includes some EXPERIMENTAL (still in development) code that can be used to extract the expanded configuration for a node.
Assuming that you have already cloned the GitHub repository, you can use the following commands to view a node :

```bash
cd asl3-menu
./php-backend/asl-configuration.php --command=node_show      --node=63001
./php-backend/asl-configuration.php --command=simpleusb_show --node=63001
./php-backend/asl-configuration.php --command=usbradio_show  --node=63001
```

The output will include the settings from the \[node-main] stanza, from any enabled customization stanzas, and any per-node overrides.
````

### /etc/asterisk/custom/iax/iaxclient-users.conf

```
; We use a template so we don't have to repeat code blocks.
; To add a new DVSwitch Mobile (or Zoiper) user, just repeat the lines below:
; [<callsign>](iaxclient)
; secret = <redacted:a4e363f3>
; callerid = "N0CALL"
;
; They need to authenticate with username <callsign> (the section name),
; and the password (the secret). This allows us to verify their connection/client.
;
; You can use whatever you want for the section name (username), but a callsign
; is probably a good idea. NOTE: If the user has multiple clients (ie an entry in
; this file, as well as iaxrpt-users), the section names MUST be unique. That could
; mean naming the sections something like [<callsign>-m] and [<callsign>-p].
;
; We will then override any callerid they send us, so we specify what
; callerid ("N0CALL") to use and display publicly in allmon.
;
; Don't forget to remind users to adjust their codec settings in their client to match
; your allowed codecs for the [iaxclient] section in iax.conf, otherwise they will not
; be able to connect.
;
; The stock generic user, un-comment it and change the secret (the password)
; if you want to use the same account for all users
; Be warned, whatever the user sets their CallerID Name to in their client will be
; passed and show up in the allmon dashboard (this could be undesired). You
; can force-override that by adding a callerid line as shown below.
;[iaxclient](iaxclient)
;secret = <redacted:a3700710>

; A custom user, un-comment and set the fields as necessary
;[n0call](iaxclient)                ; pull in the config from the [iaxclient] section in
;user = n0call                      ; iax.conf and then add this user's specific information
;secret = <redacted:9889887a>
;callerid = "N0CALL"                ; their client account configuration.
```

### /etc/asterisk/custom/iax/iaxrpt-users.conf

```
; We use a template so we don't have to repeat code blocks.
; To add a new PC Client user, just repeat the lines below:
; [<callsign>](iaxrpt)
; secret = <redacted:a4e363f3>
; callerid = "N0CALL" <0>
;
; They need to authenticate with username <callsign> (the section name),
; and the password (the secret). This allows us to verify their connection/client.
; So, users need to set the Username in iaxRpt to match the section name here
; ie. n0call and set the Password the same as the secret.
;
; You can use whatever you want for the section name (username), but a callsign
; is probably a good idea. NOTE: If the user has multiple clients (ie an entry in
; this file, as well as iaxclient-users), the section names MUST be unique. That could
; mean naming the sections something like [<callsign>-m] and [<callsign>-p].
;
; We will then override any callerid they send us, so we specify what
; callerid ("N0CALL") to use and display publicly in allmon.
;
; Note, the callerid number MUST be <0>. This replicates what the iaxRPT client
; sends, and if it is non-0, weird things happen! Callerid name is limited to 8 char!
;
; Don't forget to remind users to adjust their codec settings in iaxRpt to match
; your allowed codecs for the [iaxrpt] section in iax.conf, otherwise they will not
; be able to connect.
;
; The stock generic user, un-comment it and change the secret (the password)
; if you want to use the same account for all users
; Be warned, whatever the user sets their CallerID Name to in iaxRpt will be
; passed and show up in the allmon dashboard (this could be undesired). You
; can force-override that by adding a callerid line as shown below.
;[iaxrpt](iaxrpt)
;secret = <redacted:a3700710>

; A custom user, un-comment and set the fields as necessary
;[n0call](iaxrpt)                   ; pull in the config from the [iaxrpt] section in
;user = n0call                      ; iax.conf and then add this user's specific information
;secret = <redacted:db30c51a>
;callerid = "N0CALL" <0>            ; the iaxRPT client account configuration.
```

### /etc/asterisk/custom/rpt/AIOC.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;; AIOC ;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:aioc:node,duplex=1,rxchannel=USBRadio:*AIOC*

;
; default [node] settings for AIOC
;
[aioc](!)
```

### /etc/asterisk/custom/rpt/AllScan-UCI.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;; AllScan.info products ;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:allscan-uci:node,functions,duplex=3,rxchannel=SimpleUSB:*AllScan* UCI

;
; default [node] settings for AllScan UCI products
;
[allscan-uci](!)
althangtime = 200                      ; Longer squelch tail
duplex = 3                             ; Full-duplex, do not repeat Rx audio to Tx audio
hangtime = 100                         ; Squelch tail hang time (in ms)
holdofftelem = 1                       ; Hold off telemetry when signal is present on receiver or from connected nodes
linkunkeyct =                          ; Prevent courtesy tones when connected
telemdefault = 0                       ; Prevent "node X connected to node Y" messages

;
; default [function] settings for AllScan UCI products
;
[functions-allscan-uci](!)
921 = cop,21                           ; Enable Parrot Mode
922 = cop,22                           ; Disable Parrot Mode
```

### /etc/asterisk/custom/rpt/HotSpotRadios.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;; HotSpotRadios.com products ;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:hotspotradio-pihat:events,duplex=1,rxchannel=SimpleUSB:*HotSpotRadio* PiHat
;MENU:hotspotradio-usb:events,duplex=1,rxchannel=SimpleUSB:*HotSpotRadio* HSR-USB
;MENU:hotspotradio-repeater:events,duplex=2,rxchannel=SimpleUSB:*HotSpotRadio* HSR-Repeater

;
; default [events] settings for HotSpotRadio products (shared)
;
[events-hotspotradio](!)

cop,62,GPIO4:1 = c|t|RPT_RXKEYED
cop,62,GPIO4:0 = c|f|RPT_RXKEYED

;
; default [events] settings for HSR-PiHat
;
[events-hotspotradio-pihat](!,events-hotspotradio)

;
; default [events] settings for HSR-USB
;
[events-hotspotradio-usb](!,events-hotspotradio)

;
; default [events] settings for HSR-Repeater
;
[events-hotspotradio-repeater](!,events-hotspotradio)
```

### /etc/asterisk/custom/rpt/SHARI.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;; SHARI (SA818 Ham Allstar Radio Interface) ;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:shari-pihat-pizero:events,duplex=1,rxchannel=SimpleUSB:*Kits4Hams* SHARI PiHat, PiZero
;MENU:shari-pixx:events,duplex=1,rxchannel=SimpleUSB:*Kits4Hams* SHARI PiXX

;
; default [events] settings for SHARI products (shared)
;
[events-shari](!)

cop,62,GPIO4:1 = c|t|RPT_RXKEYED
cop,62,GPIO4:0 = c|f|RPT_RXKEYED

;
; default [events] settings for SHARI PiHat, PiZero
;
[events-shari-pihat-pizero](!,events-shari)

;
; default [events] settings for SHARI PiXX
;
[events-shari-pixx](!,events-shari)
```

### /etc/asterisk/custom/rpt/audio-archiving.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;; Archive Audio Frames ;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:audio-archiving:node:Archive Audio Frames (note: monitor disk usage)

[audio-archiving](!)

archivedir = /var/spool/asterisk/monitor
```

### /etc/asterisk/custom/rpt/hotspot-wait-times.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;; Hotspot Wait Times ;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:hd:wait-times:Hotspot Wait Times

;
; [wait-times] for Hotspot Wait Times
;

[wait-times-hd](wait-times_hd)
```

### /etc/asterisk/custom/rpt/keyed-gpio4.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;; Assert GPIO (pin 4) when keyed ;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:keyed-gpio4:events:Assert GPIO pin 4 when keyed (COS LED)

[events-keyed-gpio4](!)

cop,62,GPIO4:1 = c|t|RPT_RXKEYED
cop,62,GPIO4:0 = c|f|RPT_RXKEYED
```

### /etc/asterisk/custom/rpt/keyed-gpio8.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;; Assert GPIO (pin 8) when keyed ;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:keyed-gpio8:events:Assert GPIO pin 8 when keyed (COS LED)

[events-keyed-gpio8](!)

cop,62,GPIO8:1 = c|t|RPT_RXKEYED
cop,62,GPIO8:0 = c|f|RPT_RXKEYED
```

### /etc/asterisk/custom/simpleusb/AllScan-UCI.conf

```
;!
;! Automatically generated configuration file
;! Filename: simpleusb.conf (/etc/asterisk/custom/simpleusb/AllScan-UCI.conf)
;! Generator: chan_simpleusb
;! Creation Date: Sun Aug 23 08:33:51 2026
;!
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;; AllScan.info products ;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:allscan-uci:simpleusb:*AllScan* UCI

;
; default [interface] settings for AllScan UCI products
;
[allscan-uci](!)
carrierfrom = usbinvert
clipledgpio = 1
ctcssfrom = no
deemphasis = no
legacyaudioscaling = no
plfilter = no
rxboost = no
rxmixerset = 650
txmixa = voice
txmixaset = 999
txmixb = no
txmixbset = 500
```

### /etc/asterisk/custom/simpleusb/HotSpotRadios.conf

```
;!
;! Automatically generated configuration file
;! Filename: simpleusb.conf (/etc/asterisk/custom/simpleusb/HotSpotRadios.conf)
;! Generator: chan_simpleusb
;! Creation Date: Sun Aug 23 08:33:51 2026
;!


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;; HotSpotRadios.com products ;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:hotspotradio-pihat:simpleusb:*HotSpotRadio* PiHat
;MENU:hotspotradio-usb:simpleusb:*HotSpotRadio* HSR-USB
;MENU:hotspotradio-repeater:simpleusb:*HotSpotRadio* HSR-Repeater

;
; default [interface] settings for AllScan products (shared)
;
[hotspotradio-shared](!)
carrierfrom = usbinvert
ctcssfrom = no
deemphasis = no
invertptt = no
legacyaudioscaling = no
plfilter = yes
preemphasis = no
rxboost = yes
rxondelay = 0
txmixa = voice
txmixb = no
txoffdelay = 0

;
; default [interface] settings for HSR-PiHat
;
[hotspotradio-pihat](!,hotspotradio-shared)
rxmixerset = 200
txmixaset = 800
txmixbset = 0

;
; default [interface] settings for HSR-USB
;
[hotspotradio-usb](!,hotspotradio-shared)
rxmixerset = 300
txmixaset = 800
txmixbset = 0

;
; default [interface] settings for HSR-Repeater
;
[hotspotradio-repeater](!,hotspotradio-shared)
rxmixerset = 300
txmixaset = 800
txmixbset = 0
```

### /etc/asterisk/custom/simpleusb/SHARI.conf

```
;!
;! Automatically generated configuration file
;! Filename: simpleusb.conf (/etc/asterisk/custom/simpleusb/SHARI.conf)
;! Generator: chan_simpleusb
;! Creation Date: Sun Aug 23 08:33:51 2026
;!


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;; SHARI (SA818 Ham Allstar Radio Interface) ;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:shari-pihat-pizero:simpleusb:*Kits4Hams* SHARI PiHat, PiZero
;MENU:shari-pixx:simpleusb:*Kits4Hams* SHARI PiXX

;
; default [interface] settings for AllScan products (shared)
;
[shari-shared](!)
carrierfrom = usbinvert
ctcssfrom = no
deemphasis = no
legacyaudioscaling = no
plfilter = no
preemphasis = no
rxboost = no
rxondelay = 0
txmixa = voice
txmixb = no
txoffdelay = 0

;
; default [interface] settings for SHARI PiHat, PiZero
;
[shari-pihat-pizero](!,shari-shared)
rxmixerset = 650
txmixaset = 600
txmixbset = 500

;
; default [interface] settings for SHARI PiXX
;
[shari-pixx](!,shari-shared)
rxmixerset = 650
txmixaset = 600
txmixbset = 500
```

### /etc/asterisk/custom/simpleusb/clip-led-gpio1.conf

```
;!
;! Automatically generated configuration file
;! Filename: simpleusb.conf (/etc/asterisk/custom/simpleusb/clip-led-gpio1.conf)
;! Generator: chan_simpleusb
;! Creation Date: Sun Aug 23 08:33:51 2026
;!


;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;; Toggle GPIO (pin 1) when audio clipping detected  ;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:clip-led-gpio1:simpleusb:Assert GPIO (pin 1) when audio clipped

[clip-led-gpio1](!)

clipledgpio = 1              ; Enable ADC Clip Detect feature to use a GPIO output (0 to disable).
                             ; Supports URI Clip LED by setting a GPIO (if available) high for 500mS
                             ; when clipping detected. Value = GPIO# to use (GPIO1 recommended)
```

### /etc/asterisk/custom/usbradio/AIOC.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;; AIOC ;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:aioc:usbradio:*AIOC*

;
; default [node] settings for AIOC
;
[aioc](!)
carrierfrom = usbinvert
ctcssfrom = no
fever = 0
invertptt = no
legacyaudioscaling = no
rxboost = no
rxctcssadj = 0.500000
rxdemod = speaker
rxmixerset = 500
rxsqhyst = 500
rxsquelchadj = 500
rxvoiceadj = 0.500000
txctcssadj = 200
txmixaset = 500
txmixbset = 500
txprelim = no
txslimsp = 12000
```

### /etc/asterisk/custom/usbradio/clip-led-gpio1.conf

```
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;
;;;;; Toggle GPIO (pin 1) when audio clipping detected  ;;;;;
;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;

;MENU:clip-led-gpio1:usbradio:Assert GPIO (pin 1) when audio clipped

[clip-led-gpio1](!)

clipledgpio = 1              ; Enable ADC Clip Detect feature to use a GPIO output (0 to disable).
                             ; Supports URI Clip LED by setting a GPIO (if available) high for 500mS
                             ; when clipping detected. Value = GPIO# to use (GPIO1 recommended)
```

## DVSwitch

### /opt/Analog_Bridge/Analog_Bridge.ini

```
; Analog_Bridge configuration file.
;   This file should be placed in either /etc or it can be
;   supplied as a path on the Analog_Bridge command line.

; The best way to think of this file is that there are two main sections, the USRP (analog audio) and
; AMBE_AUDIO (compressed audio).  Analog_Bridge will take everything sent to the USRP port and
; encode it for transmission on the AMBE_AUDIO port.  The encoder will use the format defined in ambeMode.
; As you might expect, the reverse direction is defined too.

; Analog_Bridge supports include files. More on this later...
include = dvsm.macro
; include = asl.macro

; General Section describes settings for Analog_Bridge itself.
[GENERAL]
logLevel = 1                            ; Show messages and above 0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error, 6=Fatal

; Metadata management
exportMetadata = true                   ; Export metadata to USRP partner (transcode setups require this)
transferRootDir = /tmp			; Export database files to USRP partner
subscriberFile = /var/lib/dvswitch/subscriber_ids.csv   ; DMR ID to callsign lookup data

; General vocoder setup information
decoderFallBack = true                  ; Allow software AMBE decoding if a hardware decoder is not found
useEmulator = false                      ; Use the MD380 AMBE emulator for AMBE72 (DMR/YSFN/NXDN)
emulatorAddress = 127.0.0.1:2470        ; IP address and port of the md380 server

pcmPort = 2222				; UDP port to send to the WebProxy

; Information for xx_Bridge (Where xx is MMDVM, Quantar, HB, IPSC)
[AMBE_AUDIO]
address = 127.0.0.1                     ; IP address of xx_Bridge
txPort = 31103                          ; Transmit TLV frames to partner on this port
rxPort = 31100                          ; Listen for TLV frames from partner on this port
ambeMode = DMR                          ; DMR, DMR_IPSC, DSTAR, NXDN, P25, YSFN, YSFW (encode PCM to this format)
minTxTimeMS = 2500                      ; Analog -> Digital Minimum time in MS for hang delay (0-10000)

; The metadata below is used when ASL is the source since it does not have any concept of digital modes
gatewayDmrId = 3000001                  ; ID to use when transmitting from Analog_Bridge 7 digit ID
repeaterID = 300000011                  ; ID of source repeater 7 digit ID plus 2 digit SSID
txTg = 0                                ; TG to use for all frames sent from Analog_Bridge -> xx_Bridge
txTs = 2                                ; Slot to use for frames sent from Analog_Bridge -> xx_Bridge
colorCode = 1                           ; Color Code to assign DMR frames

; Information for USRP channel driver.  This interface uses PCM to transfer audio information
; There are two typical configurations, ASL and Transcode.  ASL (AllstarLink) is for analog clients connected
; to a digital network.  Transcode is when Analog_Bridge actually points its PCM interfaces back at itself, 
; causing a TLV <-- (pcm <--> pcm) --> TLV type of architecture.
;   When using ASL, this matches the rpt.conf ASL file with a setting like:
;   rxchannel = usrp/127.0.0.1:34001:32001
;   When Transcoding, make two ini files and set txPort equal to the other instance rxPort (crossover).  Launch
;   each instance with its own ini file.
[USRP]
address = 127.0.0.1                     ; IP address of USRP partner (Analog_Reflector, Allstar/Asterisk or another Analog_Bridge)
txPort = 32001                          ; Transmit USRP frames on this port
rxPort = 34001                          ; Listen for USRP frames on this port
usrpAudio = AUDIO_USE_GAIN              ; Digital -> Analog (AUDIO_UNITY, AUDIO_USE_GAIN, AUDIO_USE_AGC)
usrpGain = 2                         ; Gain factor when usrpAudio = AUDIO_USE_GAIN (0.0 to 5.0) (1.0 = AUDIO_UNITY)
usrpAGC = -15,8,80                    ; Set the agc threshold (db), slope (db) and decay (ms)
tlvAudio = AUDIO_USE_GAIN               ; Analog -> Digital (AUDIO_UNITY, AUDIO_USE_GAIN, AUDIO_BPF)
tlvGain = 1.1                       ; Gain factor when tlvAudio = AUDIO_USE_GAIN (0.0 to 5.0) (1.0 = AUDIO_UNITY)

[MACROS]

; Where the macros are
; xxxx=yyyy
; xxxx is the dial string to match
; yyyy is the command line to execute

; xxxx must be preceded by a *
; xxxx can be any string (alphanumeric)
; yyyy is the command to execute
; yyyy will replace xxxx in the dial string
; arguments follow the macro name with a # delimiter

; For example using macro "5678" above would look like:
; *5678#9876

; Which would invoke:
; echo 9876

; Information for DV3000 hardware decoder
;   There are two configuration modes: IP (AMBEServer) and serial (direct connect hardware)
;   Use top server and port if using AMBEServer
;   Use bottom server/port and serial = true if using the DV3000u (thumbdv)
;   Did you run AMBETest4.py before using this?
[DV3000]
; address = 127.0.0.1                 ; IP address of AMBEServer
; rxPort = 2460                       ; Port of AMBEServer
address = /dev/ttyUSB0              ; Device of DV3000U on this machine
baud = 460800                       ; Baud rate of the dongle (230400 or 460800)
serial = true                       ; Use serial=true for direct connect or serial=false for AMBEServer
```

### /opt/MMDVM_Bridge/DVSwitch.ini

```
; MMDVM_Bridge export / import configuration file.
;   This file should be placed along side of MMDVM_Bridge or you can supply
;   an absolute path in the DVSWITCH environment variable, e.g:
;   DVSWITCH=/etc/MMDVM_Bridge/DVSwitch.ini
;   before executing MMDVM_Bridge
;
; Another method to set the enviorment variable is to use the systemd unit file
; by adding:
; Environment=DVSWITCH=/etc/MMDVM_Bridge/DVSwitch.ini
; to /lib/systemd/system/mmdvm_bridge.service

; Configure the Quantar Repeater Partner
; Note that the TX and RX ports are already reversed for MMDVM_Bridge <--> Quantar_Bridge
[QUANTAR]
address = 0.0.0.0               ; Address to send IMBE TLV frames to (export)
txPort = 34103                  ; Port to send IMBE TLV frames to (export)
rxPort = 34100                  ; Port to listen for IMBE TLV frames on (import)
quantarPort = 1994              ; HDLC frames To/From the Quantar repeater
debug = 0                       ; Debug 0 = off, 1 = on (adds lots of additional messages)
logLevel = 2                    ; Logging levels, 0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error, 6=Fatal
logFilePath = /var/log/dvswitch/Quantar_Bridge.log

; Configure the DMR Partner
; Audio format is AMBE 72 bit
[DMR]
address = 127.0.0.1             ; Address to send AMBE TLV frames to (export)
txPort = 31100                  ; Port to send AMBE TLV frames to (export)
rxPort = 31103                  ; Port to listen on (import)
slot = 2                        ; Export slot
exportTG = 0                    ; Which TG to export 
hangTimerInFrames = 0		; Use 50 for 3 seconds of hang time (3000 / 60) 
talkerAlias = %callsign %location %description ; Get callsign location and description from MMDVM_Bridge.ini

; Configure the D-Star Partner
; Audio format is AMBE 48 bit (DSAMBE)
[DSTAR]
address = 127.0.0.1             ; Address to send AMBE TLV frames to (export)
txPort = 32100                  ; Port to send AMBE TLV frames to (export)
rxPort = 32103                  ; Port to listen on (import)
fallbackID = 1234567            ; In case we can not find a valid DMR id in the database, export this one
exportTG = 9                    ; Which TG to export
slot = 2                        ; Export slot
RemotePort = 54321		; Port to send Gateway commands to
message = %location %description ; Get location and description from MMDVM_Bridge.ini

; Configure the NXDN Partner
; Audio format is AMBE 72 bit
[NXDN]
address = 127.0.0.1             ; Address to send AMBE TLV frames to (export)
txPort = 33100                  ; Port to send AMBE TLV frames to (export)
rxPort = 33103                  ; Port to listen on (import)
fallbackID = 1234567            ; In case we can not find a valid DMR id in the database, export this one
nxdnFallbackID  = 12345         ; Use this ID when the input DMR ID is not found in the database
translate = 1234=4321           ; Translate NXDN TG < -- > DMR TG (bidirectional)
slot = 2                        ; Export slot
RemotePort = 6075		; Port to send Gateway commands to

; Configure the P25 Partner
; Audio format is IMBE 88 bit
[P25]
address = 127.0.0.1             ; Address to send AMBE TLV frames to (export)
txPort = 34100                  ; Port to send AMBE TLV frames to (export)
rxPort = 34103                  ; Port to listen on (import)
slot = 2                        ; Export slot
RemotePort = 6074		; Port to send Gateway commands to

; Configure the Yaesu Fusion Partner
; Audio format is AMBE 72 bit
; Audio format is IMBE 88 bit
[YSF]
address = 127.0.0.1             ; Address to send AMBE TLV frames to (export)
txPort = 35100                  ; Port to send AMBE TLV frames to (export)
rxPort = 35103                  ; Port to listen on (import)
txWidePort = 35105		; Port to send IMBE TLV frames to for YSFw (export)
fallbackID = 1234567            ; In case we can not find a valid DMR id in the database, export this one
exportTG = 9                    ; Which TG to export
slot = 2                        ; Export slot
RemotePort = 6073		; Port to send Gateway commands to

; Configure the BrandMeister connection
; Simple Terminal Feature Update
; Audio format is AMBE 72 bit
[STFU]                          ; Brandmeister Open DMR Terminal (ODMRT) Protocol
BMAddress = 3104.master.brandmeister.network   ; Brandmeister ODMRT server address
BMPort = 54006                  ; Brandmeister ODMRT port
BMPassword = <redacted:65a62beb>
Address = 127.0.0.1             ; Address to send AMBE TLV frames to (export)
txPort  = 36100                 ; Port to send AMBE TLV frames to (export)
rxPort  = 36103                 ; Port to listen on (import)
UserID  = 3000001               ; Your DMR ID
TalkerAlias = N0CALL Name City  ; Max 27 characters
StartTG = 3166                  ; Startup talk group
LogLevel = 3                    ; STFU log level (0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error)

[ASL]
address = 127.0.0.1
txPort = 30100
rxPort = 30103
```

### /opt/MMDVM_Bridge/MMDVM_Bridge.ini

```
[General]
Callsign=N0CALL
Id=3000001
Timeout=180
Duplex=0

[Info]
RXFrequency=222340000
TXFrequency=224940000
Power=1
Latitude=0.0000
Longitude=0.0000
Height=0
Location=Iceberg, North Atlantic
Description=MMDVM_Bridge
URL=https://groups.io/g/DVSwitch

[Log]
# Logging levels, 0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error, 6=Fatal
DisplayLevel=1
FileLevel=2
FilePath=/var/log/mmdvm
FileRoot=MMDVM_Bridge

[DMR Id Lookup]
File=/var/lib/mmdvm/DMRIds.dat
Time=24

[NXDN Id Lookup]
File=/var/lib/mmdvm/NXDN.csv
Time=24

[Modem]
Port=/dev/null
RSSIMappingFile=/dev/null
Trace=0
Debug=0

[D-Star]
Enable=1
Module=B

[DMR]
Enable=1
ColorCode=1
EmbeddedLCOnly=1
DumpTAData=0

[System Fusion]
Enable=1

[P25]
Enable=1
NAC=293

[NXDN]
Enable=1
RAN=1
Id=11738

[D-Star Network]
Enable=1
GatewayAddress=127.0.0.1
GatewayPort=20010
LocalPort=20011
Debug=1

[DMR Network]
Enable=1
Address=3104.master.brandmeister.network
Port=62031
Jitter=360
Local=62032
Password=<redacted:2d04a347>
# for DMR+ see https://github.com/DVSwitch/MMDVM_Bridge/blob/master/DOC/DMRplus_startup_options.md
# for XLX the syntax is: Options=XLX:4009
# Options=
Slot1=0
Slot2=1
Debug=1

[System Fusion Network]
Enable=1
LocalAddress=0.0.0.0
LocalPort=3200
GatewayAddress=127.0.0.1
GatewayPort=4200
Debug=1

[P25 Network]
Enable=1
GatewayAddress=127.0.0.1
GatewayPort=42020
LocalPort=32010
Debug=1

[NXDN Network]
Enable=1
#LocalAddress=127.0.0.1
Debug=1
LocalPort=14021
GatewayAddress=127.0.0.1
GatewayPort=14020
```

### /opt/YSFGateway/YSFGateway.ini

```
[General]
Callsign=N0CALL
Suffix=RPT
# Suffix=ND
Id=300000011
RptAddress=127.0.0.1
RptPort=3200
LocalAddress=127.0.0.1
LocalPort=4200
WiresXMakeUpper=1
WiresXCommandPassthrough=<redacted:b0e6fff1>
Daemon=0

[Info]
RXFrequency=223500000
TXFrequency=223500000
Power=1
Latitude=0.0000
Longitude=0.0000
Height=0
Location=Iceberg
Description=DVSwitch
URL=https://groups.io/g/DVSwitch

[Log]
# Logging levels, 0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error, 6=Fatal
DisplayLevel=1
FileLevel=2
FilePath=/var/log/mmdvm
FileRoot=YSFGateway

[aprs.fi]
Enable=0
# Server=noam.aprs2.net
Server=euro.aprs2.net
Port=14580
Password=<redacted:e4f522bf>
Description=APRS Description
Suffix=Y

[Network]
# Startup=Alabama-Link
InactivityTimeout=0
Revert=0
Debug=0

[YSF Network]
Enable=1
Port=42000
Hosts=/var/lib/mmdvm/YSFHosts.txt
ReloadTime=60
ParrotAddress=127.0.0.1
ParrotPort=42012
# YSF2DMRAddress=127.0.0.1
# YSF2DMRPort=42013
# YSF2NXDNAddress=127.0.0.1
# YSF2NXDNPort=42014
# YSF2P25Address=127.0.0.1
# YSF2P25Port=42015

[FCS Network]
Enable=1
Rooms=/var/lib/mmdvm/FCSRooms.txt
Port=42001

[Mobile GPS]
Enable=0
Address=127.0.0.1
Port=7834

[Remote Commands]
Enable=1
Port=6073
```

### /opt/P25Gateway/P25Gateway.ini

```
[General]
Callsign=N0CALL
RptAddress=127.0.0.1
RptPort=32010
LocalPort=42020
Daemon=0

[Id Lookup]
Name=/var/lib/mmdvm/DMRIds.dat
Time=24

[Voice]
Enabled=1
Language=en_US
Directory=./Audio

[Log]
# Logging levels, 0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error, 6=Fatal
DisplayLevel=1
FileLevel=2
FilePath=/var/log/mmdvm
FileRoot=P25Gateway

[Network]
Port=42010
HostsFile1=/var/lib/mmdvm/P25Hosts.txt
HostsFile2=/var/lib/mmdvm/private_P25Hosts.txt
ReloadTime=60
ParrotAddress=127.0.0.1
ParrotPort=42011
P252DMRAddress=127.0.0.1
P252DMRPort=42012
# Startup=10200
InactivityTimeout=0
Debug=0

[Remote Commands]
Enable=1
Port=6074
```

### /opt/NXDNGateway/NXDNGateway.ini

```
[General]
Callsign=N0CALL
Suffix=NXDN
# The next four lines are for a Kenwood repeater
# RptProtocol=Kenwood
# RptAddress=198.51.100.4
# RptPort=64000
# LocalPort=64000
# The next four lines are for an Icom repeater
# RptProtocol=Icom
# RptAddress=198.51.100.4
# RptPort=41300
# LocalPort=41300
# The next four lines are for an MMDVM
RptProtocol=Icom
RptAddress=127.0.0.1
RptPort=14021
LocalPort=14020
Debug=0
Daemon=0

[Info]
RXFrequency=223500000
TXFrequency=223500000
Power=1
Latitude=0.0000
Longitude=0.0000
Height=0
Location=Iceberg
Description=DVSwitch
URL=https://groups.io/g/DVSwitch

[Voice]
Enabled=1
Language=en_US
Directory=./Audio

[aprs.fi]
Enable=0
# Server=noam.aprs2.net
Server=euro.aprs2.net
Port=14580
Password=<redacted:e4f522bf>
Description=APRS Description
Suffix=N

[Id Lookup]
Name=/var/lib/mmdvm/NXDN.csv
Time=24

[Log]
# Logging levels, 0=No logging, 1=Debug, 2=Message, 3=Info, 4=Warning, 5=Error, 6=Fatal
DisplayLevel=1
FileLevel=2
FilePath=/var/log/mmdvm
FileRoot=NXDNGateway

[Network]
Port=14050
HostsFile1=/var/lib/mmdvm/NXDNHosts.txt
HostsFile2=/var/lib/mmdvm/private_NXDNHosts.txt
ReloadTime=60
ParrotAddress=127.0.0.1
ParrotPort=42021
NXDN2DMRAddress=127.0.0.1
NXDN2DMRPort=42022
# Startup=10200
InactivityTimeout=0
Debug=0

[Mobile GPS]
Enable=0
Address=127.0.0.1
Port=7834

[Remote Commands]
Enable=1
Port=6075
```

### /var/lib/dvswitch/dvs/var.txt

```

source /var/lib/dvswitch/dvs/func.txt
source /var/lib/dvswitch/dvs/lan/language.txt

#VARIABLES
startup_lan=73
first_time_instl=73

# ${DVS}init_config.sh
call_sign=N0CALL
dmr_id=3000001
rpt_id=300000011
rpt_id_2=300000021
rpt_id_3=300000031
rpt_id_now=
module=B
nxdn_id=11738
usrp_port=

default_dmr_server=Brandmeister

bm_name=Brandmeister
bm_master=
bm_address=3104.master.brandmeister.network
bm_password=<redacted:2d04a347>
bm_port=62031

dmrplus_name=DMRPlus
dmrplus_address=
dmrplus_password=
dmrplus_port=

tgif_name=TGIF
tgif_address=tgif.network
tgif_password=<redacted:1d148b56>
tgif_port=62031

other1_name=
other1_address=
other1_password=
other1_port=

other2_name=
other2_address=
other2_password=
other2_port=

# AMBE
ambe_server=198.51.100.18
ambe_rxport=2460
ambe_baud=460800
ambe_option=2

# ${adv}dvsm.sh
txgain_dmr=0.25
txgain_dstar=2.00
txgain_nxdn=0.35
txgain_p25=0.35
txgain_ysf=0.35

usrpGain=4.00
txgain_dmr_default=0.35
usrpGain_default=1.10

# MMDVM_Bridge Info
rx_freq=
tx_freq=
pwr=
lat=
lon=
hgt=
lctn=
desc=
url=

# ETC
cpu_temp=
```

## USRP2M17

### /opt/USRP2M17/USRP2M17.ini

```
[M17 Network]
Callsign=N0CALL
Address=0.0.0.0
Name=DISCONNECTED A
LocalPort=17010
DstPort=17000
GainAdjustdB=3
Daemon=1
Debug=0

[USRP Network]
Address=127.0.0.1
DstPort=32008
LocalPort=34008
GainAdjustdB=3
Debug=0

[Log]
DisplayLevel=0
FileLevel=0
FilePath=/var/log/usrp
FileRoot=USRP2M17
```

## Allmon3

### /etc/allmon3/allmon3.ini

```
;
; This is the master configuration file for all ASL/Asterisks node-related
; information. It is used for all server daemon processes
; (e.g. asl-statmon, asl-cmdlink) and the web interface/API.
;
; Each configuration item below is marked (R) or (O) for required or optional
; repsectively along with usage notes. The value in the table below is the
; default value for optiional items or examples for required items.
;
; NOTE: The .ini format does not support trailing comments - i.e. a comment
; after a commant. The items below are listed as they are only for
; readbility purposes. A "#" is not a comment character in .ini files, only
; a semi-colon (;).
;
; [500002]
; host = 198.51.100.5     # (R) DNS name or IP address of the Asterisk/ASL node
;
; port = 5038          # (O) port of the Asterisk manager
;
; user = admin         # (R) username of the Asterisk monitor, most
;                      #     commonly 'admin'
;
; pass = <redacted:d9d069d0>
;
; multinodes =		   # (O) this node is a server hosting multiple nodes
;                      #     and this is the "primary" record for the host.
;
; voters = n[,n,...]   # (O) List voters on this server, comma
;                      #     separate. No value disabled voters
;
; pollinterval = 1     # (O) polling interval to asterisk in seconds
;                      #     default is 1. this value can be expressed as
;                      #     a decimal fraction of a second - e.g., .5
;                      #     is 500ms, .375 is 375ms, etc.
;
; vpollinterval = 1    # (O) broadcast interval of voter data in seconds
;                      #      default is 1. this value can be expressed as
;                      #      a decimal fraction of a second - e.g., .5
;                      #      is 500ms, .375 is 375ms, etc.
;
; retryinterval = 15   # (O) seconds between retries if initial connection to
;                      #     asterisk is lost (optional, default 15)
;
; retrycount =         # (O) number of times to retry a lost asterisk
;                      #     connection before ending (default infinite)

; For a basic installation, you chould be able to uncomment the below,
; change 500002 to your node number and set the pass= as
; set in asterisk/manager.conf

[500001]
host=127.0.0.1
user=kd8pgk
pass=<redacted:10c828f3>

[500002]
host=127.0.0.1
user=kd8pgk
pass=<redacted:10c828f3>

[500003]
host=127.0.0.1
user=kd8pgk
pass=<redacted:10c828f3>
```

### /etc/allmon3/web.ini

```
;;
;; web.ini - configuration for Allmon3 web interface
;;
;;
;; This is the customziation interface for the Allmon3 web
;; interface. Only items listed below are considered customizable
;; other than items that appears in style.css and will survive
;; across updates. If you want to customize additional items
;; please make a pull request against the project for consideration
;;

[web]
; CONFIG_HEADER_TITLE is text which appears centered in the
; top nav/header bar
CONFIG_HEADER_TITLE = Allmon3 Monitoring Dashboard

; CONFIG_LOGO_IMG appears aligned left in the top-right corner
; of the page. The max height of this image should be 50px. If
; you do not want a logo to appear, leave this entry as an
; empty string "" and the ASL logo will be display. Image
; file is relative to the img/ subdirectory of Allmon3
CONFIG_HEADER_LOGO = ""

; CONFIG_MENU_SINGLE_TARGET sets the target for single menu links
; in the sidebar menus.
; Default will open external links in same window
; _blank will open external links in a new tab
;CONFIG_MENU_SINGLE_TARGET = _blank

; Location of the password table
;USERS_TABLE_LOCATION = /etc/allmon3/users

; Location of the user restrictions table
;USERS_RESTRICTIONS_LOCATION = /etc/allmon3/user-restrictions

; Link the "Home" button will open. This is useful
; for filtering back down to an intial list of nodes
; rather than "all nodes"
HOME_BUTTON_URL = index.html

; Port for the master webserver of allmon3.
; Default is 16080
;HTTP_PORT = 16080

; Starting port # for the websockets
; Default is 16700
;WS_PORT_START = 16700

; Binding address for the webserver and websockets. By default
; the services listen on all addresses on the system.
; This can specify a single IP address.
;WS_BIND_ADDR =


;;
;; In this section, list commands that are templates for the
;; systems command modal dialog. The format is:
;;
;;   command text = Command Label
;;
;; In any command text the @ will be replaced with the
;; node the command modal was selected from. For example:
;;
;;   rpt status @ = Show Node Status
;;
;; Will result in the command 'rpt status 500002' assuming
;; this command was selected from Node #500002.
;;
;; In any commant text the % will be replaecd with the
;; selected target node from the table view. For example:
;; if you clicked on node 63001 shown as connected on
;; node 500002 the following command:
;;
;;   database put denylist/@ % "Reason"
;;
;; Will result int the command modal being populated
;; as:
;;
;;  database put denylist/500002/63001 "Reason"
;;
[syscmds]
rpt stats @ = Show Node Status
rpt lstats @ = Show Link Status
iax2 show registry = Show IAX Registry
iax2 show channels = Show IAX Channels
iax2 show netstats = Show Network Status
core show uptime = Show Uptime
rpt cmd @ status 12 xxx = Say Time of Day (local only)
rpt cmd @ cop 33 xxx = Local Telemetry Output Enable
rpt cmd @ cop 34 xxx = Local Telemetry Output Disable
rpt cmd @ cop 35 xxx = Local Telemetry Output on Demand
rpt cmd @ status 11 xxx = Force ID (local only)
rpt cmd @ cop 3 xxx = Disable System
rpt cmd @ cop 2 xxx = Enable System
rpt cmd @ cop 12 xxx = Disable Linking
rpt cmd @ cop 11 xxx = Enable Linking
rpt cmd @ cop 10 xxx = Disable Autopatch
rpt cmd @ cop 9 xxx = Enable Autopatch
rpt cmd @ cop 18 xxx = Disable User Functions
rpt cmd @ cop 17 xxx = Enable User Functions
rpt cmd @ cop 4 1 = !!! Toggle Test Tone !!!
rpt cmd @ cop 14 0 = System State 0 (normal)
rpt cmd @ cop 14 1 = System State 1 (rpt only)
rpt cmd @ cop 14 2 = System State 2 (rpt off)
rpt cmd @ cop 14 3 = System State 3 (New and News)
database put allowlist/@ % &quot;Reason Here&quot; = Add Allowlist Entry
database put denylist/@ % &quot;Reason Here&quot; = Add Denylist Entry
database show allowlist/@ = Show node allowlist
database show denylist/@ = Show node denylist
database del allowlist/@ = Delete node allowlist
database del denylist/@ = Delete node denylist

;;
;; It is possible to create optional stanzas named in the
;; format [syscmds-NODE] (e.g. [syscmds-500002]) and have
;; those command templates appear only for the given
;; NODE listed. Example:
;;
;[syscmds-500002]
;rpt cmd @ cop 999 xxx = Execute function 999

;;
;; In the node-overrides section, the AllStarLink DB
;; labels for a node may be replaces with custom
;; text. The format is:
;;
;;    NODE = TEXT HERE
;;
;; This section must exist even if it's empty
;;
[node-overrides]
;500002 = Private Node

;;
;; In the voter-titles section, this is the
;; name for all voters. Otherwise the voters will
;; have an auto-generated name of "Voter NODE".
;;
;; This section must exist even if it's empty
[voter-titles]
;500002 = Voter #500002
```

## Firewall and 44Net Connect

### /etc/firewalld/firewalld.conf

```
# firewalld config file

# default zone
# The default zone used if an empty zone string is used.
# Default: public
DefaultZone=allstarlink

# Clean up on exit
# If set to no or false the firewall configuration will not get cleaned up
# on exit or stop of firewalld.
# Default: yes
CleanupOnExit=yes

# Clean up kernel modules on exit
# If set to yes or true the firewall related kernel modules will be
# unloaded on exit or stop of firewalld. This might attempt to unload
# modules not originally loaded by firewalld.
# Default: no
CleanupModulesOnExit=no

# IPv6_rpfilter
# Performs reverse path filtering (RPF) on IPv6 packets as per RFC 3704.
# Possible values:
#   - strict: Performs "strict" filtering as per RFC 3704. This check
#             verifies that the in ingress interface is the same interface
#             that would be used to send a packet reply to the source. That
#             is, ingress == egress.      
#   - loose: Performs "loose" filtering as per RFC 3704. This check only
#            verifies that there is a route back to the source through any
#            interface; even if it's not the same one on which the packet
#            arrived.
#   - strict-forward: This is almost identical to "strict", but does not perform
#                     RPF for packets targeted to the host (INPUT).
#   - loose-forward: This is almost identical to "loose", but does not perform
#                    RPF for packets targeted to the host (INPUT).
#   - no: RPF is completely disabled.
#
# The rp_filter for IPv4 is controlled using sysctl.
# Note: This feature has a performance impact. See man page FIREWALLD.CONF(5)
# for details.
# Default: strict
IPv6_rpfilter=strict

# IndividualCalls
# Do not use combined -restore calls, but individual calls. This increases the
# time that is needed to apply changes and to start the daemon, but is good for
# debugging.
# Default: no
IndividualCalls=no

# LogDenied
# Add logging rules right before reject and drop rules in the INPUT, FORWARD
# and OUTPUT chains for the default rules and also final reject and drop rules
# in zones. Possible values are: all, unicast, broadcast, multicast and off.
# Default: off
LogDenied=off

# FirewallBackend
# Selects the firewall backend implementation.
# Choices are:
#	- nftables (default)
#	- iptables (iptables, ip6tables, ebtables and ipset)
# Note: The iptables backend is deprecated. It will be removed in a future
# release.
FirewallBackend=nftables

# FlushAllOnReload
# Flush all runtime rules on a reload. In previous releases some runtime
# configuration was retained during a reload, namely; interface to zone
# assignment, and direct rules. This was confusing to users. To get the old
# behavior set this to "no".
# Default: yes
FlushAllOnReload=yes

# ReloadPolicy
# Policy during reload. By default all traffic except for established
# connections is dropped while the rules are updated. Set to "DROP", "REJECT"
# or "ACCEPT". Alternatively, specify it per table, like
# "OUTPUT:ACCEPT,INPUT:DROP,FORWARD:REJECT".
# Default: ReloadPolicy=INPUT:DROP,FORWARD:DROP,OUTPUT:DROP
ReloadPolicy=INPUT:DROP,FORWARD:DROP,OUTPUT:DROP

# RFC3964_IPv4
# As per RFC 3964, filter IPv6 traffic with 6to4 destination addresses that
# correspond to IPv4 addresses that should not be routed over the public
# internet.
# Defaults to "yes".
RFC3964_IPv4=yes

# StrictForwardPorts
# If set to yes, the generated destination NAT (DNAT) rules will NOT accept
# traffic that was DNAT'd by other entities, e.g. docker. Firewalld will be
# strict and not allow published container ports until they're explicitly
# allowed via firewalld.
# If set to no, then docker (and podman) integrates seamlessly with firewalld.
# Published container ports are implicitly allowed.
# Defaults to "no".
StrictForwardPorts=no

# NftablesFlowtable
# This may improve forwarded traffic throughput by enabling nftables flowtable.
# It is a software fastpath and avoids calling nftables rule evaluation for
# data packets. This only works for TCP and UDP traffic.
# The value is a space separated list of interfaces.
# Example value "eth0 eth1".
# Defaults to "off".
NftablesFlowtable=off

# NftablesCounters
# If set to yes, add a counter to every nftables rule. This is useful for
# debugging and comes with a small performance cost.
# Defaults to "no".
NftablesCounters=no

# NftablesTableOwner
# If set to yes, the generated nftables rule set will be owned exclusively by
# firewalld. This prevents other entities from mistakenly (or maliciously)
# modifying firewalld's rule set. If you intentionally modify firewalld's
# rules, then you will have to set this to "no".
# Defaults to "yes".
NftablesTableOwner=yes
```

### /etc/firewalld/zones/44NetConnect.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <service name="iax2"/>
  <service name="echolink"/>
  <interface name="wg0"/>
</zone>
```

### /etc/firewalld/zones/allstarlink.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>AllStarLink</short>
  <description>Firewall rules for an AllStarLink appliance/system</description>
  <service name="ssh"/>
  <service name="dhcpv6-client"/>
  <service name="echolink"/>
  <service name="http"/>
  <service name="https"/>
  <service name="cockpit"/>
  <service name="mdns"/>
  <service name="iax2"/>
  <service name="rtcm"/>
  <service name="Dashboard--8989-8989"/>
  <service name="Sysmon--9999-9999"/>
  <service name="Instamon"/>
  <service name="44Helper"/>
  <service name="custom--8991"/>
  <service name="sip"/>
  <service name="custom--sip"/>
  <service name="5160"/>
  <service name="custom--10000-20000"/>
  <service name="custom--8993-8993"/>
  <port port="10000-20000" protocol="udp"/>
  <port port="5060" protocol="udp"/>
  <port port="5160" protocol="udp"/>
  <forward/>
</zone>
```

### /etc/firewalld/zones/block.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone target="%%REJECT%%">
  <short>Block</short>
  <description>Unsolicited incoming network packets are rejected. Incoming packets that are related to outgoing network connections are accepted. Outgoing network connections are allowed.</description>
  <forward/>
</zone>
```

### /etc/firewalld/zones/dmz.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>DMZ</short>
  <description>For computers in your demilitarized zone that are publicly-accessible with limited access to your internal network. Only selected incoming connections are accepted.</description>
  <service name="ssh"/>
  <forward/>
</zone>
```

### /etc/firewalld/zones/drop.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone target="DROP">
  <short>Drop</short>
  <description>Unsolicited incoming network packets are dropped. Incoming packets that are related to outgoing network connections are accepted. Outgoing network connections are allowed.</description>
  <forward/>
</zone>
```

### /etc/firewalld/zones/external.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>External</short>
  <description>For use on external networks. You do not trust the other computers on networks to not harm your computer. Only selected incoming connections are accepted.</description>
  <service name="ssh"/>
  <masquerade/>
  <forward/>
</zone>
```

### /etc/firewalld/zones/home.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>Home</short>
  <description>For use in home areas. You mostly trust the other computers on networks to not harm your computer. Only selected incoming connections are accepted.</description>
  <service name="ssh"/>
  <service name="mdns"/>
  <service name="samba-client"/>
  <service name="dhcpv6-client"/>
  <forward/>
</zone>
```

### /etc/firewalld/zones/internal.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>Internal</short>
  <description>For use on internal networks. You mostly trust the other computers on the networks to not harm your computer. Only selected incoming connections are accepted.</description>
  <service name="ssh"/>
  <service name="mdns"/>
  <service name="samba-client"/>
  <service name="dhcpv6-client"/>
  <forward/>
</zone>
```

### /etc/firewalld/zones/nm-shared.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone target="ACCEPT">
  <short>NetworkManager Shared</short>
  <description>     This zone is used internally by NetworkManager when activating a     profile that uses connection sharing and doesn't have an explicit     firewall zone set.     Block all traffic to the local machine except ICMP, ICMPv6, DHCP     and DNS. Allow all forwarded traffic.     Note that future package updates may change the definition of the     zone unless you overwrite it with your own definition.   </description>
  <service name="dhcp"/>
  <service name="dns"/>
  <service name="ssh"/>
  <protocol value="icmp"/>
  <protocol value="ipv6-icmp"/>
  <rule priority="32767">
    <reject/>
  </rule>
</zone>
```

### /etc/firewalld/zones/public.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>Public</short>
  <description>For use in public areas. You do not trust the other computers on networks to not harm your computer. Only selected incoming connections are accepted.</description>
  <service name="ssh"/>
  <service name="dhcpv6-client"/>
  <forward/>
</zone>
```

### /etc/firewalld/zones/trusted.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone target="ACCEPT">
  <short>Trusted</short>
  <description>All network connections are accepted.</description>
  <forward/>
</zone>
```

### /etc/firewalld/zones/work.xml

```
<?xml version="1.0" encoding="utf-8"?>
<zone>
  <short>Work</short>
  <description>For use in work areas. You mostly trust the other computers on networks to not harm your computer. Only selected incoming connections are accepted.</description>
  <service name="ssh"/>
  <service name="dhcpv6-client"/>
  <forward/>
</zone>
```

### /etc/firewalld/services/44Helper.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="9997" protocol="tcp"/>
  <port port="9997" protocol="udp"/>
</service>
```

### /etc/firewalld/services/5160.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <description>Sip</description>
  <port port="5160" protocol="udp"/>
</service>
```

### /etc/firewalld/services/Dashboard--8989-8989.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="8989-8990" protocol="tcp"/>
  <port port="8989-8990" protocol="udp"/>
</service>
```

### /etc/firewalld/services/Instamon.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="8990" protocol="tcp"/>
  <port port="8990" protocol="udp"/>
</service>
```

### /etc/firewalld/services/Sysmon--9999-9999.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="9999" protocol="tcp"/>
  <port port="9999" protocol="udp"/>
</service>
```

### /etc/firewalld/services/astmgr.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>AstMgr</short>
  <description>Asterisk Management Port</description>
  <port port="5038" protocol="tcp"/>
</service>
```

### /etc/firewalld/services/custom--10000-20000.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="10000-10003" protocol="udp"/>
</service>
```

### /etc/firewalld/services/custom--8991.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="8991" protocol="tcp"/>
</service>
```

### /etc/firewalld/services/custom--8993-8993.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <description>Listen</description>
  <port port="8993" protocol="tcp"/>
  <port port="8993" protocol="udp"/>
</service>
```

### /etc/firewalld/services/custom--sip.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <port port="5060" protocol="udp"/>
</service>
```

### /etc/firewalld/services/echolink.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>echolink</short>
  <description>Echolink ports</description>
  <port port="5198-5199" protocol="udp"/>
</service>
```

### /etc/firewalld/services/iax2.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>IAX2</short>
  <description>Asterisk IAX2 ports for AllStarLink</description>
  <port port="4560-4580" protocol="udp"/>
</service>
```

### /etc/firewalld/services/rtcm.xml

```
<?xml version="1.0" encoding="utf-8"?>
<service>
  <short>RTCM</short>
  <description>RTCM/Voter port for app_rpt</description>
  <port port="1667" protocol="udp"/>
</service>
```

### /etc/wireguard/wg0.conf

```
[Interface]
# 44helper-half-begin
# Half tunnel (44helper 0.0.215, 2026-10-18): only ASL and EchoLink use the tunnel.
# To take it out: ~/remove_half_tunnel.sh  (or Remove permanent on 44helper's Full Tunnel tab)
Table = off
FwMark = 0x4444
PostUp = ip -4 route replace default dev %i table 4444 || true
PostUp = ip -4 rule add lookup main suppress_prefixlength 0 priority 1100 || true
PostUp = ip -4 rule add from 198.51.100.3 lookup 4444 priority 1101 || true
PostUp = U=$(id -u asterisk) && ip -4 rule add uidrange $U-$U lookup 4444 priority 1102 || true
PostUp = ip -4 rule add ipproto udp sport 4569 lookup 4444 priority 1103 || true
PostUp = ip -4 rule add fwmark 0x4444 lookup main priority 1099 || true
PostUp = ip -4 rule add to 198.51.100.19/9 lookup 4444 priority 1107 || true
PostUp = ip -4 rule add to 198.51.100.20/10 lookup 4444 priority 1108 || true
PostUp = sysctl -q -w net.ipv4.conf.%i.rp_filter=2 || true
PostDown = for P in 1099 1100 1101 1102 1103 1104 1105 1107 1108; do while ip -4 rule del priority $P 2>/dev/null; do :; done; done; true
PostDown = ip -4 route flush table 4444 || true
# 44helper-half-end
# 44helper-dns-begin
PostUp = resolvectl dns %i 198.51.100.21; resolvectl domain %i ~ampr.org ~44.in-addr.arpa
PreDown = resolvectl revert %i || true
# 44helper-dns-end
PrivateKey = <redacted:ba37cc6b>
Address = fe80::9be5:e28e:380a:c67e/64, 198.51.100.3/32
MTU = 1380

[Peer]
PublicKey = AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
Endpoint = 198.51.100.22:44000
PersistentKeepalive = 20
AllowedIPs = 0.0.0.0/0
```

### /etc/sysctl.d/90-44helper-halftunnel.conf

```
# 44helper half tunnel: loose return-path check on the tunnel.
net.ipv4.conf.wg0.rp_filter = 2
```

### /etc/sysctl.d/98-rpi.conf

```
kernel.printk = 3 4 1 3
vm.min_free_kbytes = 16384
net.ipv4.ping_group_range = 0 2147483647
```

## Node tools

### /etc/asl_dvs/asl_dvs.conf

```
# asl_dvs.conf — saved by ASL-DVS Node Control 2026-10-20 03:04:28

[CONFIG]
asl_node=500001
bridge_node=500002
bridge_nodes=500002,500003,1001,
port=8989
callsign=N0CALL
enabled_tabs=ASL,DMR,STFU,YSF,M17,PHONE
cpuweight_enabled=true

[ASL]
network_url=https://stats.allstarlink.org/stats/keyed
East Coast Reflector|45192
South Coast Refector|48347
DooDropInn|50241
International Radio Network|552360
HubNet uk|43845
FreeSTAR uk|40063
222 Chicago|458800
FireSide Radio Network|52879
NW AllStar Group uk|53573
ASL 674982 NETOHOLICS|674982

[ECHO]
network_url=
EchoTest|9999
ECR WB2JPQ|57780
420 Ragchew|66420
SELINK|380607
WORLD CONF|9251
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000

[DMR]
TGIF 9990 Parrot|9990
TGIF 9050 East Coast Reflector|9050
TGIF 326 Fireside|326
TGIF 23525 Ext. Freedom|23525
TGIF 31320 Int. Radio Network|31320
TGIF 28100 Louisiana Nationwide|28100
TGIF 23426 FreeSTAR UK|23426
TGIF 23526 HubNet UK|23526
TGIF 31665 The Mothership|31665
TGIF 4000 DisCon|4000

[STFU]
network_url=https://hose.brandmeister.network
BM 310997# Parrot|310997#
BM 3215714 East Coast Reflector|3215714
BM 313136 Kansas City Wide|313136
BM 91 World Wide|91
BM 3100 USA Bridge|3100
BM 31399 Ohio Link|31399
blank|000000
blank|000000
blank|000000
blank|000000

[YSF]
YSF Parrot|198.51.100.23:42000
YSF East Coast Reflector|198.51.100.24:42225|https://dvref.com/ysf/ysf-44444-ecr
YSF AmericaLink|198.51.100.25:42000|americalinkysf.radiotechnology.xyz
YSF Kansas City Wide|ysf.kansascitywide.com:42000
YSF OhioLink|198.51.100.26:42002|ysf.ke8o.net
YSF Ohio Statewide|198.51.100.27:42000
11102 US-DXLINKSYSTEM|198.51.100.28:42000
YSF KCW CW|198.51.100.29:42002
blank|000000
blank|000000

[P25]
P25 World|10100
USA|10200
Kansas City Wide Digital Network|31313
Ham Radio Crash Course|621
SkyHubLink|10294
P25 31777 DXLink|31777
blank|000000
blank|000000
blank|000000
blank|000000

[NXDN]
NXDN 10100 World|10100
NXDN 10200 USA|10200
NXDN 6749 Netaholics|6749
NXDN 15431 QuadNet|15431
NXDN 31777 DXLink|31777
NXDN 31313 Kansas City Wide|31313
NXDN 43389 South East Link|43389
blanl|000000
NXDN 31983 US Multi mode|31983
blank|000000

[DSTAR]
D-Star REF001 C A B D  01 Charlie|REF001CL|https://ref001.dstargateway.org
D-Star REF030 C B|REF030CL|https://ref030.dstargateway.org
D-Star REF038 C B A D E Ohio Wide|REF038CL|ref038.dstargateway.org
D-Star ECR XRF(XLX)237A|XLX237AL
blank|000000
D-Star XLX458 KC Wide|XLX458AL|xlx.w0fh.net
D-Star W1ABC Gateway|W1ABC BL|https://k8wgr.dstargateway.org
D-Star XLX037 A World Wide Chat|XLX037AL|http://wwchat.us/dashboard/xlx037
D-Star XLX749 B DXLink|XLX749BL|www.k2hzexlx.duckdns.org.
D-Star N8DXE Gateway|N8DXE CL

[FCS]
network_url=http://xreflector.net
FCS002-90 America-Link-WiresX|900290|https://fcs002.xreflector.net
FCS003-81 TEXAS-MRN|900381|http://fcs003.xreflector.net
FCS235-03 North-America|923503|http://fcs235.xreflector.net
FCS235-35 CQ-UK|923535
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000

[XLX]
# name|tg[|url]  (tg = D-Star tune string, e.g. XLX334AL)
XLX209 Z parrot|XLX209ZL
XLX097 A(B)CDEFGHI New England Digital Radio|XLX097BL|http://xlx097.newenglanddigitalradio.com/monitor.php
XLXDAM B Dgital-America|XLXDAMBL|digital-america.org
XLX234 Mod-A|XLX234AL|http://198.51.100.30
XLX237 Mod-A|XLX237AL|http://198.51.100.31
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000

[M17]
# name|base|module|ip[|url]  (module = A-Z or the literal @ALL wildcard;
# base+module get written into the USRP2M17.ini Name= field)
M17-KCW A|M17-KCW|A|198.51.100.32|http://m17.kansascitywide.com
M17-NET Netaholics A|M17-NET|A|198.51.100.33|netoholicsnetwork.net
M17 Project Reflector C|M17-M17|C|198.51.100.34|https://m17.openquad.net
M17-DMR FreeSTAR Network D B|M17-DMR|D|198.51.100.35|https://m17.freestar.network
M17-835 WMRA MULTIMODE-NETWORK A|M17-835|A|198.51.100.36|https://wmrasystem.com/M17
M17-097 New England Digital Radio A-Z|M17-097|A|198.51.100.37|http://m17-097.newenglanddigitalradio.com
QuadNet A B C D|URF307|A|198.51.100.38|https://xlx307.ddns.net
Lookout Mountain Amateur Radio Community A D X|M17-SEL|D|m17.lmarc.net|https://selink.lmarc.net/m17dash
CumbriaCQ.com M17|M17-002|A|urf001.cumbriacq.com|https://urf001.cumbriacq.com/urf
blank|blank|@ALL|000000
[DMR_SERVERS]
TGIF|<redacted:143d1e2f>|tgif.network:62031|https://tgif.network/activetg.php
TGIF 2|<redacted:143d1e2f>|tgif.network:62031|https://tgif.network/activetg.php
BM Canada|<redacted:2d04a347>|3104.master.brandmeister.network:62031|https://hose.brandmeister.network
System-X|<redacted:1d148b56>|usa.freestar.network:62031|https://dmr.freestar.network/dashboard
Sys-X CQ-UK|<redacted:1d148b56>|usa.freestar.network:62031|dmr.cq-uk.uk
Sys-X FreeSTAR|<redacted:1d148b56>|usa.freestar.network:62031|dmr.freestar.network/dashboard
FreeDMR|<redacted:1d148b56>|freedmr.dvswitch.org:62031|https://freedmr-lh.gb7fr.org.uk/
ADN|<redacted:1d148b56>|3102.adn.systems:62031|3102.adn.systems
AmComm|<redacted:1d148b56>|3103.amcomm.network:62031|http://3103.amcomm.network/
QRM Network|<redacted:1d148b56>|qrm.kc3ol.net:62031|https://kc3ol.net/last_heard
QuadNet|<redacted:1d148b56>|quadnet2.ddns.net:62031|https://openquad.net/last.php
DVSPh-M|<redacted:d039cb86>|198.51.100.39:55555|http://dvsph-m.dvsph.net/ipsc/
DMR SE|<redacted:1d148b56>|hotspot.cbridge.net:62031|hotspot.cbridge.net
New England DMR|<redacted:1d148b56>|nedmr.com:55555|monitor.newenglanddigitalradio.com/index.php
Ham United 1 (Day)|<redacted:1d148b56>|198.51.100.40:62031|http://hamunited.com/
Ham United 2 (Mornigs)|<redacted:1d148b56>|198.51.100.40:62031|http://hamunited.com/
AmateurWire DMR|<redacted:1d148b56>|DMR1.amateurwire.org:62030|DMR1.amateurwire.org:8081

[DMR_TGIF]
TGIF 9990 Parrot|9990
TGIF 9050 East Coast Reflector|9050
TGIF 326 Fireside|326
TGIF 23525 Ext. Freedom|23525
TGIF 31320 Int. Radio Network|31320
TGIF 28100 Louisiana Nationwide|28100
TGIF 23426 FreeSTAR UK|23426
TGIF 23526 HubNet UK|23526
TGIF 31665 The Mothership|31665
TGIF 4000 DisCon|4000

[DMR_TGIF_2]
TGIF 77511 South Coast Reflector|77511
TGIF 29332 Alaska Morning Net|29332
TGIF 31656 America Link|31656
TGIF 23566 South Wales Digital Group|23566
TGIF 3933 Black Sheep Lounge|3933
TGIF 3208773 NEDR Wolfden|3208773
TGIF 59650 Texas-DFW Linked Systems|59650
TGIF 31226 World Wide Chat|31226
TGIF 67498 Netaholics|67498
TGIF 4000 DisCon|4000

[DMR_BM_CANADA]
blank|000000
blank|000000
blank|000000
BM Atlantic Canada|30205
BM DMR Campfire|31665
BM The Canada Hub|30217
BM SaskWarn|30252
BM Atlantic NE|30207
BM Manitoba|3024
blank|000000

[DMR_SYSTEM-X]
Sys-X Parrot|9990
Sys-X CQ North West UK|69
Sys-X X Worldwide|91
Sys-X FreeSTAR Int.|23426
Sys-X W. Michigan|322
Sys-X Lackwanna County PA WIDE|31204
Sys-X Crossroads USA|3160
Sys-X M17 Project|9517
Sys-X W0CHP-PiStar-Das|3170603
Sys-X DisCon|4000

[DMR_SYS-X_CQ-UK]
TG 31777|31777
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000

[DMR_SYS-X_FREESTAR]
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000

[DMR_FREEDMR]
FreeDMR Parrot|9990
FreeDMR Worldwide|91
FreeDMR All Call|16777215
FreeDMR USA Nationwide|3100
FreeDMR Ohio|3139
FreeDMR Piedmont Triad|31379
blank|000000
blank|000000
blank|000000
FreeDMR DisCon|4000

[DMR_ADN]
ADN Parrot|9990
ADN East Coast Reflector|3109050
ADN DODROPIN Network|3167355
ADN DMR Friends|3165
ADN ARRL News Broadcast|313201
ADN Systems User|3167
blank|000000
blank|000000
blank|000000
ADN DisCon|4000

[DMR_AMCOMM]
AmComm Parrot|9990
AmComm East Coast Reflector|9050
AmComm Emergency Radio Long Island|11710
AmComm US-TEXAS-MRN|31486
AmComm Yorkshire UK|23450
AmComm U.S. Ragchew Network|6487
AmComm M17-M17 Module C|9517
AmComm Secret Squirrel|31330
AmComm Louisiana Nationwide|28100
AmComm DisCon|4000

[DMR_QRM_NETWORK]
QRM Parrot|100
QRM Fireside Radio Network|326
QRM Outlaws Radio Network|839
QRM The Scanner/SWL Junkies|1033
QRM Alabama Link|31010
QRM|31200
QRM Backyard Repeater Group|31201
QRM Skynet|37030
QRM World Wide Chat|31226
QRM DisCon|*44

[DMR_QUADNET]
QuadNet Parrot|9990
QuadNet East Coast Reflector|9050
QuadNet Secret Squirrel|31330
QuadNet Cumbria CQ|89134
QuadNet South Wales Digital|23566
QuadNet Array|320
QuadNet Tech Chat|321
QuadNet Public Safety Amatuer Radio Group|4101
QuadNet Jesus Saves|7770
QuadNet DisCon|4000

[DMR_DVSPH-M]
Echo|9990
UK Wide Multimode|23556
HubNet|23526
UK Calling|235
WW Calling|1
WW En Calling|13
RayNet UK|23531
blank|000000
blank|000000
DisCon *44|*44

[DMR_DMR_SE]
blank|000000
Wellington DMR Fl|3149803
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000

[DMR_NEW_ENGLAND_DMR]
blank|000000
TG 10 General Chat|10
TG 11 Wolf Den Wires-X Network|11
TG 3125 Massachusetts|3125
TG 3144 Rhode Island|3144
TG 3109 Connecticut|3109
TG 3133 New Hampshire|3133
TG 3150 Vermont|3150
TG 3123 Maine|3123
TG 19 NC3M Network|19

[DMR_HAM_UNITED_1_(DAY)]
HU 9050 East Coast Reflector|9050
HU 31777 DXLink|31777
HU 31665 TGIF Mothership|31665
HU 31010 Alabama Link|31010
HU 67498 Netaholics|67498
HU  31230 UFB New England|31230
HU 3100 USA (KC Wide)|3100
HU 31364 85 Rag Chew|31364
HU 44544 Woffle Group|44544
HU 31656 America Link|31656

[DMR_HAM_UNITED_2_(MORNIGS)]
HU 31483 TGIF Texas Chat|31483
HU 23426 FreeSTAR UK|23426
HU 31066|31066
HU 23503 Southern Fusion YSF|23503
HU 2359|2359
HU 1701|1701
HU 31204|31204
TG 2351|2351
blank|000000
blank|000000

[DMR_AMATEURWIRE_DMR]
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
blank|000000
1000 AmateurWireDMR|1000
```

### /etc/asl_dvs/nodelisten.conf

```
[nodetalker]
port = 8993
udp_port = 6200
node = 500001
max_listeners = 3
public_listen = false
https = true
tot_sec = 120
busy_lockout = true
kerchunk_delay_ms = 400
tune_enabled = true
tx_gain_db = -1
rx_gain_db = 1
jitter_ms = 250
tx_buffer_ms = 200
allow_wan = false
rx_hpf = true
rx_agc = true
rx_gate = 1
ptt_mode = tap
ptt_guard_sec = 120
ptt_rx_gap = true

[nodelisten]
port = 8993
udp_port = 6200
node = 500001
max_listeners = 3
public_listen = false
https = true
tot_sec = 120
busy_lockout = true
kerchunk_delay_ms = 400
tune_enabled = true
tx_gain_db = -1
rx_gain_db = 1
jitter_ms = 250
tx_buffer_ms = 200
allow_wan = false
rx_hpf = true
rx_agc = true
rx_gate = 1
ptt_mode = tap
ptt_guard_sec = 120
ptt_rx_gap = true
```

### /etc/asl_dvs/nodelisten_favorites.conf

```
# nodetalker_favorites.conf: Node Talker favorites in Node Controller's asl_dvs.conf format.
# The Connect tab lists the favorites in the order they appear here.

[CONFIG]
callsign=N0CALL
bridge_nodes=500002,500003

[DMR_SERVERS]
# name|password|address:port|network_url
TGIF|<redacted:143d1e2f>|tgif.network:62031|https://tgif.network/activetg.php
Ham United|<redacted:1d148b56>|198.51.100.40:62031|http://hamunited.com/

[ASL]
East Coast Reflector|45192|rx=-3
ASL Parrot|2002
DX Link|41604

[M17]
M17-KCW A|M17-KCW|A|
Netaholics|M17-NET|A|

[STFU]
USA Bridge|3100
BM 91 World Wide|91

[YSF]
AmericaLink|198.51.100.25:42000

[DMR_TGIF]
The Mothership|31665

[DMR_HAM_UNITED]
Woffle Group|44544

[STFU]
Ohio Link|31399

[ASL]
Alaska Morning Net|27133

[M17]
DX Link|M17-177|A|

[DMR_TGIF]
DMR TGIF 109|109
```

### /etc/asl_dvs/nodetalker.conf

```
[nodetalker]
port = 8993
udp_port = 6200
node = 500001
max_listeners = 3
public_listen = false
https = true
tot_sec = 120
busy_lockout = true
kerchunk_delay_ms = 400
tune_enabled = true
tx_gain_db = -1
rx_gain_db = 1
jitter_ms = 250
tx_buffer_ms = 200
allow_wan = false
rx_hpf = true
rx_agc = true
rx_gate = 1
ptt_mode = tap
ptt_guard_sec = 120
ptt_rx_gap = true

[nodelisten]
port = 8993
udp_port = 6200
node = 500001
max_listeners = 3
public_listen = false
https = true
tot_sec = 120
busy_lockout = true
kerchunk_delay_ms = 400
tune_enabled = true
tx_gain_db = -1
rx_gain_db = 1
jitter_ms = 250
tx_buffer_ms = 200
allow_wan = false
rx_hpf = true
rx_agc = true
rx_gate = 1
ptt_mode = tap
ptt_guard_sec = 120
ptt_rx_gap = true
```

### /etc/asl_dvs/nodetalker_favorites.conf

```
# nodetalker_favorites.conf: Node Talker favorites in Node Controller's asl_dvs.conf format.
# The Connect tab lists the favorites in the order they appear here.

[CONFIG]
callsign=N0CALL
bridge_nodes=500002,500003

[DMR_SERVERS]
# name|password|address:port|network_url
TGIF|<redacted:143d1e2f>|tgif.network:62031|https://tgif.network/activetg.php
Ham United|<redacted:1d148b56>|198.51.100.40:62031|http://hamunited.com/

[ASL]
East Coast Reflector|45192|rx=-3
ASL Parrot|2002
DX Link|41604

[M17]
M17-KCW A|M17-KCW|A|
Netaholics|M17-NET|A|

[STFU]
USA Bridge|3100
BM 91 World Wide|91

[YSF]
AmericaLink|198.51.100.25:42000

[DMR_TGIF]
The Mothership|31665

[DMR_HAM_UNITED]
Woffle Group|44544

[STFU]
Ohio Link|31399

[ASL]
Alaska Morning Net|27133

[M17]
DX Link|M17-177|A|

[DMR_TGIF]
DMR TGIF 109|109
```

### /etc/asl_dvs/instmon_channel.json

```
{
 "channel": "testing"
}
```

### /etc/asl_dvs/instmon_diskimg_schedule.json

```
{
 "dest_device": "",
 "enabled": false,
 "interval_hours": 24.0,
 "label": "auto",
 "last_run_at": null,
 "last_run_message": null,
 "last_run_status": null,
 "last_skip_at": null,
 "last_skip_message": null,
 "retention": 5,
 "shrink": false,
 "verify": false
}
```

### /etc/asl_dvs/instmon_full_update.json

```
{
 "attention": [],
 "banner": false,
 "current": "",
 "error": "",
 "in_progress": null,
 "instmon_pending": null,
 "manuals": [
  {
   "name": "ASL-DVS_Node_Talker_Manual.pdf",
   "note": "new or changed on GitHub"
  }
 ],
 "phase": "done",
 "running": false,
 "scripts": [],
 "skipped": [],
 "stopping": false,
 "updated": [
  {
   "name": "Node Talker",
   "note": "v0.6.9 -> v0.6.12"
  }
 ]
}
```

### /etc/asl_dvs/instmon_locks.json

```
{
 "sysmon": [
  "sysmon_pi02w_v6_13_76_20261020.py"
 ]
}
```

### /etc/asl_dvs/nodelisten_favorites.json

```
[
 {
  "label": "East Coast Reflector",
  "mode": "ASL",
  "num": "45192"
 },
 {
  "label": "ASL Parrot",
  "mode": "ASL",
  "num": "2002"
 },
 {
  "label": "DX Link",
  "mode": "ASL",
  "num": "41604"
 },
 {
  "label": "M17-KCW A",
  "mode": "M17",
  "module": "A",
  "num": "M17-KCW"
 },
 {
  "label": "Netaholics",
  "mode": "M17",
  "module": "A",
  "num": "M17-NET"
 },
 {
  "label": "Alaska Morning Net",
  "mode": "ASL",
  "num": "27133"
 },
 {
  "label": "DX Link",
  "mode": "M17",
  "module": "A",
  "num": "M17-177"
 }
]
```

### /etc/asl_dvs/nodelisten_tuned.json

```
{
 "bridge": "",
 "mode": "",
 "name": "",
 "target": ""
}
```

### /etc/asl_dvs/nodetalker_favorites.json

```
[
 {
  "label": "East Coast Reflector",
  "mode": "ASL",
  "num": "45192"
 },
 {
  "label": "ASL Parrot",
  "mode": "ASL",
  "num": "2002"
 },
 {
  "label": "DX Link",
  "mode": "ASL",
  "num": "41604"
 },
 {
  "label": "M17-KCW A",
  "mode": "M17",
  "module": "A",
  "num": "M17-KCW"
 },
 {
  "label": "Netaholics",
  "mode": "M17",
  "module": "A",
  "num": "M17-NET"
 },
 {
  "label": "Alaska Morning Net",
  "mode": "ASL",
  "num": "27133"
 },
 {
  "label": "DX Link",
  "mode": "M17",
  "module": "A",
  "num": "M17-177"
 }
]
```

### /etc/asl_dvs/nodetalker_tuned.json

```
{
 "bridge": "",
 "mode": "",
 "name": "",
 "target": ""
}
```

### /etc/asl_dvs/phone.json

```
{
 "activated": true,
 "active": "dvshoip",
 "dialtime": 20000,
 "listen_only": false,
 "networks": [
  {
   "allow_intl": false,
   "auth_id": "400999",
   "caller_id": "400999",
   "callsign": "N0CALL",
   "dial_format": "10",
   "dialing": "ext",
   "did": "400999",
   "e911": false,
   "email": "<redacted:c851ea4d>",
   "extension": "400999",
   "favorites": [
    {
     "name": "ECR",
     "number": "15001"
    },
    {
     "name": "Newsline center",
     "number": "90002"
    },
    {
     "name": "Blues",
     "number": "90010"
    },
    {
     "name": "Jazz",
     "number": "90024"
    },
    {
     "name": "ABC Radio OZ",
     "number": "90023"
    },
    {
     "name": "Bbc world",
     "number": "90034"
    },
    {
     "name": "Old time radio",
     "number": "90031"
    },
    {
     "name": "Top 80s",
     "number": "90009"
    },
    {
     "name": "Scifi Radio",
     "number": "90030"
    },
    {
     "name": "Ground zero radio",
     "number": "90029"
    }
   ],
   "host": "premium.hamsoverip.com",
   "id": "dvshoip",
   "incoming": "open",
   "lan_net": "198.51.100.1/24",
   "login_url": "",
   "name": "Ham Over IP",
   "node": "1001",
   "password": "<redacted:23fbf13c>",
   "pin": "0000",
   "port": "5160",
   "register": true,
   "test_number": "3194",
   "transport": "udp",
   "trusted": [],
   "type": "hoip",
   "username": "400999",
   "voicemail": "400999@default",
   "voicemail_access": "*97",
   "voicemail_pin": "000000",
   "wan_ip": ""
  },
  {
   "allow_intl": false,
   "auth_id": "400998",
   "caller_id": "400998",
   "callsign": "",
   "dial_format": "10",
   "dialing": "ext",
   "did": "400998",
   "display_name": "N0CALL",
   "dmr_id": "3000001",
   "e911": false,
   "email": "",
   "extension": "400998",
   "favorites": [
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "",
     "number": ""
    },
    {
     "name": "SE Link Sys",
     "number": "90011"
    },
    {
     "name": "ECR",
     "number": "90036"
    }
   ],
   "host": "pbx1-wv.amateurwire.org",
   "id": "dvsamateurwire",
   "incoming": "open",
   "lan_net": "",
   "login_url": "",
   "name": "AmateurWire",
   "node": "1002",
   "password": "<redacted:09e4c7a0>",
   "pin": "",
   "port": "5060",
   "register": true,
   "test_number": "",
   "transport": "udp",
   "trusted": [],
   "type": "awire",
   "username": "400998",
   "voicemail": "",
   "voicemail_access": "*97",
   "voicemail_pin": "000000",
   "wan_ip": ""
  }
 ],
 "patch_enabled": false,
 "signin_mode": "picked",
 "tone_path": "provider",
 "tot_cap_min": 30,
 "tot_phone_off": true
}
```

### /etc/sysmon/sysmon.conf

```
[server]
port = 9999
host = 0.0.0.0

[identity]
callsign = N0CALL
node = 500001
label = Travel Node

[thresholds]
cpu_warn_pct = 50
rss_warn_mb = 200
nr_warn = 3
nr_crit = 10k

[services]
pinned = __GROUP__:AllStarLink Core
	asterisk.service | ASL3 Asterisk/app_rpt | /etc/asterisk/rpt.conf | 4569 | udp
	analog_bridge.service |  | - | - | -
	mmdvm_bridge.service |  | - | - | -
	stfu.service | restart STFU And MMDVM_Bridge | - | - | -
	allmon3.service | Allmon3 web monitor | - | 8080 | tcp
	cockpit.service | ASL3 Cockpit admin UI | - | 9090 | tcp
	asl_dvs_dashboard.service | ASL+DVSwitch Dashboard | - | 8989 | tcp
	md380-emu.service |  | - | - | -
	sysmon.service | Sysmon Monitor | - | 9999 | tcp
	wifimon.service |  | - | - | -
	usrp2m17.service |  | - | - | -
	instmon.service |  | - | - | -

[asldvs]
hidden_files = acl.conf,adsi.conf,agents.conf,alarmreceiver.conf,amd.conf,app_skel.conf,aeap.conf,ari.conf,ast_debug_tools.conf,asterisk.conf,calendar.conf,ccss.conf,cdr.conf,cdr_adaptive_odbc.conf,cdr_beanstalkd.conf,cdr_custom.conf,cdr_manager.conf,cdr_odbc.conf,cdr_pgsql.conf,cdr_sqlite3_custom.conf,cdr_tds.conf,cel.conf,cel_beanstalkd.conf,cel_custom.conf,cel_odbc.conf,cel_sqlite3_custom.conf,dsp.conf,dbsep.conf,config_test.conf,codecs.conf,dnsmgr.conf,console.conf,confbridge.conf,cli_permissions.conf,cli.conf,chan_mobile.conf,cel_tds.conf,chan_dahdi.conf,chan_websocket.conf,cli_aliases.conf,enum.conf,extconfig.conf,gps.conf,func_odbc.conf,followme.conf,features.conf,geolocation.conf,festival.conf,extensions_minivm.conf,http.conf,hep.conf,logger.conf,iaxprov.conf,indications.conf,ooh323.conf,musiconhold.conf,motif.conf,minivm.conf,meetme.conf,phoneprov.conf,pjproject.conf,pjsip.conf,pjsip_notify.conf,pjsip_wizard.conf,prometheus.conf,queuerules.conf,queues.conf,res_config_mysql.conf,res_config_sqlite3.conf,res_config_odbc.conf,res_corosync.conf,res_curl.conf,res_http_media_cache.conf,res_fax.conf,res_ldap.conf,res_odbc.conf,res_parking.conf,res_pgsql.conf,res_snmp.conf,res_stun_monitor.conf,res_usbradio.conf,resolver_unbound.conf,rtp.conf,say.conf,sla.conf,smdi.conf,sorcery.conf,stasis.conf,statsd.conf,test_sorcery.conf,stir_shaken.conf,udptl.conf,voicemail.conf,websocket_client.conf,xmpp.conf,voter.conf,Analog_Reflector.ini,custom.css,menu.ini,cel_pgsql.conf,rpt_auth.conf

[radio_presets]
radio1_values = rxmixerset=600;txmixaset=700;txmixbset=700
radio1_title = DM-32
radio2_values = rxmixerset=250;txmixaset=750;txmixbset=0
radio2_title = M-5R
radio3_values = rxmixerset=300;txmixaset=125;txmixbset=1
radio3_title = AR-5RM
radio4_values = 
radio4_title = 
radio5_values = 
radio5_title = 

[radio_tune]
active_slot = 1
active_driver = simpleusb
simpleusb_values = rxmixerset=600;txmixaset=700;txmixbset=700
usbradio_values = rxmixerset=400;txmixaset=500;txmixbset=0;txctcssadj=250;rxsquelchadj=500;rxvoiceadj=0.50;rxctcssadj=0.50;txslimsp=51000
relink_nodes = 500002,500003

[ui]
enabled_tabs = overview,services,ports,journal,asldvs,reg,edit
```

### /etc/44helper/44helper.conf

```
[server]
port = 9997
host = 0.0.0.0

[identity]
callsign = 
node = 

[tunnels]
tunnel.pi.mode = pi
tunnel.pi.interface = wg0
tunnel.pi.config_path = /etc/wireguard/wg0.conf
tunnel.pi.kind = split

[router]
access_method = none
host = 
user = 
key_path = 
poll_interval_sec = 60

[nodes]
iax_conf_path = /etc/asterisk/iax.conf
rpt_conf_path = /etc/asterisk/rpt.conf
extensions_conf_path = /etc/asterisk/extensions.conf
allmon3_ini_path = /etc/allmon3/allmon3.ini
bindport_range_min = 4560
bindport_range_max = 4580
peers = 
peer_links = 

[ui]
enabled_tabs = overview,router_install,pi_install,services,ports,firewall,actions_log
```

### /etc/wifimon/wifimon.conf

```
[network_1]
ssid = N0CALL3
psk = 
priority = 1
status = known_good

[network_2]
ssid = N0CALL2
psk = 
priority = 2
status = known_good
security = Open

[network_3]
ssid = HomeWiFi-DD
psk = <redacted:db9bdb43>
priority = 4
status = unverified
security = WPA2

[network_4]
ssid = N0CALL004
psk = <redacted:590cd325>
priority = 5
status = known_good
```

### /etc/NetworkManager/conf.d/90-wifimon-powersave.conf

```
# Written by wifimon ("Keep WiFi power save off" setting). wifimon owns
# this file: turning the setting off in wifimon removes it.
[connection-wifimon-powersave]
wifi.powersave=2
```

### /etc/systemd/system.conf.d/90-asl_dvs-hwwatchdog.conf

```
# Written by wifimon: reboot the Pi if it freezes (Change settings on wifimon's page)
[Manager]
RuntimeWatchdogSec=15s
RebootWatchdogSec=2min
```

## Network and system

### /etc/os-release

```
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
VERSION_ID="13"
VERSION="13 (trixie)"
VERSION_CODENAME=trixie
DEBIAN_VERSION_FULL=13.7
ID=debian
HOME_URL="https://allstarlink.org"
SUPPORT_URL="https://community.allstarlink.org"
BUG_REPORT_URL="https://github.com/AllStarLink/asl3-pi-appliance/"
VARIANT="AllStarLink System Manager"
VARIANT_ID="AllStarLink"
```

### /etc/hostname

```
nodehost
```

### /etc/hosts

```
127.0.0.1	localhost
::1		localhost ip6-localhost ip6-loopback
ff02::1		ip6-allnodes
ff02::2		ip6-allrouters

127.0.1.1	travel
```

### /etc/resolv.conf

```
# This is /run/systemd/resolve/stub-resolv.conf managed by man:systemd-resolved(8).
# Do not edit.
#
# This file might be symlinked as /etc/resolv.conf. If you're looking at
# /etc/resolv.conf and seeing this text, you have followed the symlink.
#
# This is a dynamic resolv.conf file for connecting local clients to the
# internal DNS stub resolver of systemd-resolved. This file lists all
# configured search domains.
#
# Run "resolvectl status" to see details about the uplink DNS servers
# currently in use.
#
# Third party programs should typically not access this file directly, but only
# through the symlink at /etc/resolv.conf. To manage man:resolv.conf(5) in a
# different way, replace this symlink by a static file or a different symlink.
#
# See man:systemd-resolved.service(8) for details about the supported modes of
# operation for /etc/resolv.conf.

nameserver 127.0.0.53
options edns0 trust-ad
search hotspot
```

### /etc/dhcpcd.conf

```
# A sample configuration for dhcpcd.
# See dhcpcd.conf(5) for details.

# Allow users of this group to interact with dhcpcd via the control socket.
#controlgroup wheel

# Inform the DHCP server of our hostname for DDNS.
hostname

# Use the hardware address of the interface for the Client ID.
#clientid
# or
# Use the same DUID + IAID as set in DHCPv6 for DHCPv4 ClientID as per RFC4361.
# Some non-RFC compliant DHCP servers do not reply with this set.
# In this case, comment out duid and enable clientid above.
duid

# Persist interface configuration when dhcpcd exits.
persistent

# vendorclassid is set to blank to avoid sending the default of
# dhcpcd-<version>:<os>:<machine>:<platform>
vendorclassid

# A list of options to request from the DHCP server.
option domain_name_servers, domain_name, domain_search
option classless_static_routes
# Respect the network MTU. This is applied to DHCP routes.
option interface_mtu

# Request a hostname from the network
option host_name

# Most distributions have NTP support.
option ntp_servers

# A ServerID is required by RFC2131.
require dhcp_server_identifier

# Generate SLAAC address using the Hardware Address of the interface
#slaac hwaddr
# OR generate Stable Private IPv6 Addresses based from the DUID
slaac private
```

### /etc/NetworkManager/system-connections/N0CALL004-wifimenu-0d4dc4c5.nmconnection

```
[connection]
id=N0CALL004
uuid=0d4dc4c5-d0aa-4c00-865f-cb173528ebee
type=wifi
autoconnect-priority=1
timestamp=1791753018

[wifi]
mode=infrastructure
ssid=N0CALL004

[wifi-security]
key-mgmt=wpa-psk
psk=<redacted:590cd325>

[ipv4]
method=auto

[ipv6]
method=auto

[proxy]
```

### /etc/NetworkManager/system-connections/N0CALL2-wifimenu-3f58db75.nmconnection

```
[connection]
id=N0CALL2
uuid=3f58db75-e86a-4d9a-9728-a9537631f131
type=wifi
autoconnect-priority=3
timestamp=1791752865

[wifi]
mode=infrastructure
ssid=N0CALL2

[wifi-security]
key-mgmt=wpa-psk
psk=<redacted:590cd325>

[ipv4]
address1=198.51.100.41/24
gateway=198.51.100.2
method=manual

[ipv6]
method=auto

[proxy]
```

### /etc/NetworkManager/system-connections/N0CALL3.nmconnection

```
[connection]
id=N0CALL3
uuid=dda834c1-8c05-42e3-ad68-3b9a4bc9bddc
type=wifi
autoconnect=false
autoconnect-priority=4
interface-name=wlan0
timestamp=1791746879

[wifi]
mode=infrastructure
ssid=N0CALL3

[ipv4]
method=auto

[ipv6]
addr-gen-mode=default
method=auto

[proxy]
```

### /etc/NetworkManager/system-connections/HomeWiFi-DD.nmconnection

```
[connection]
id=HomeWiFi-DD
uuid=2db7fa27-dca4-455a-9a24-d8320e65bccd
type=wifi
autoconnect=false
autoconnect-priority=2
interface-name=wlan0
timestamp=1789506302

[wifi]
mode=infrastructure
ssid=HomeWiFi-DD

[wifi-security]
key-mgmt=wpa-psk
psk=<redacted:db9bdb43>

[ipv4]
method=auto

[ipv6]
addr-gen-mode=default
method=auto

[proxy]
```

### /etc/NetworkManager/system-connections/asl-fallback-ap.nmconnection

```
[connection]
id=asl-fallback-ap
uuid=5f238f85-9210-4356-97fa-e3ec2a33426b
type=wifi
autoconnect=false
autoconnect-priority=-999
interface-name=wlan0
zone=allstarlink

[wifi]
band=bg
channel=11
mode=ap
ssid=AllStarLink_88A29E17FCA1

[wifi-security]
key-mgmt=wpa-psk
psk=<redacted:5fa514b1>

[ipv4]
address1=198.51.100.42/29
method=shared

[ipv6]
addr-gen-mode=default
method=disabled

[proxy]
```

### /etc/NetworkManager/system-connections/asl-fallback-ap.nmconnection.GS5FX3

```
[connection]
id=asl-fallback-ap
uuid=5f238f85-9210-4356-97fa-e3ec2a33426b
type=wifi
autoconnect=false
autoconnect-priority=-999
interface-name=wlan0
zone=allstarlink

[wifi]
band=bg
channel=11
mode=ap
ssid=AllStarLink_88A29E17FCA1

[wifi-security]
key-mgmt=wpa-psk
psk=<redacted:5fa514b1>

[ipv4]
address1=198.51.100.42/29
method=shared

[ipv6]
addr-gen-mode=default
method=disabled

[proxy]
```

### /etc/NetworkManager/system-connections/asl-fallback-ap.nmconnection.IEIQX3

```
[connection]
id=asl-fallback-ap
uuid=5f238f85-9210-4356-97fa-e3ec2a33426b
type=wifi
autoconnect=false
autoconnect-priority=-999
interface-name=wlan0
zone=allstarlink

[wifi]
band=bg
channel=11
mode=ap
ssid=AllStarLink_88A29E17FCA1

[wifi-security]
key-mgmt=wpa-psk
psk=<redacted:5fa514b1>

[ipv4]
address1=198.51.100.42/29
method=shared

[ipv6]
addr-gen-mode=default
method=disabled

[proxy]
```

### /etc/systemd/journald.conf

```
#  This file is part of systemd.
#
#  systemd is free software; you can redistribute it and/or modify it under the
#  terms of the GNU Lesser General Public License as published by the Free
#  Software Foundation; either version 2.1 of the License, or (at your option)
#  any later version.
#
# Entries in this file show the compile time defaults. Local configuration
# should be created by either modifying this file (or a copy of it placed in
# /etc/ if the original file is shipped in /usr/), or by creating "drop-ins" in
# the /etc/systemd/journald.conf.d/ directory. The latter is generally
# recommended. Defaults can be restored by simply deleting the main
# configuration file and all drop-ins located in /etc/.
#
# Use 'systemd-analyze cat-config systemd/journald.conf' to display the full config.
#
# See journald.conf(5) for details.

[Journal]
#Storage=auto
#Compress=yes
#Seal=yes
#SplitMode=uid
#SyncIntervalSec=5m
#RateLimitIntervalSec=30s
#RateLimitBurst=10000
#SystemMaxUse=
#SystemKeepFree=
#SystemMaxFileSize=
#SystemMaxFiles=100
#RuntimeMaxUse=
#RuntimeKeepFree=
#RuntimeMaxFileSize=
#RuntimeMaxFiles=100
#MaxRetentionSec=0
#MaxFileSec=1month
#ForwardToSyslog=no
#ForwardToKMsg=no
#ForwardToConsole=no
#ForwardToWall=yes
#TTYPath=/dev/console
#MaxLevelStore=debug
#MaxLevelSyslog=debug
#MaxLevelKMsg=notice
#MaxLevelConsole=info
#MaxLevelWall=emerg
#MaxLevelSocket=debug
#LineMax=48K
#ReadKMsg=yes
#Audit=yes
```

## Commands

### uname -a

```
Linux nodehost 6.18.50+rpt-rpi-v8 #1 SMP PREEMPT Debian 1:6.18.50-1+rpt1 (2026-09-11) aarch64 GNU/Linux
```

### uptime

```
 12:10:57 up  6:20,  0 users,  load average: 2.10, 2.05, 1.91
```

### df -h /

```
Filesystem      Size  Used Avail Use% Mounted on
/dev/mmcblk0p2   29G  4.8G   23G  18% /
```

### free -h

```
               total        used        free      shared  buff/cache   available
Mem:           415Mi       292Mi        90Mi       588Ki        84Mi       122Mi
Swap:          414Mi       274Mi       140Mi
```

### systemctl --failed

```

```

### installed packages (radio, firewall, VPN)

```
dpkg-query: no packages found matching svxlink*
dpkg-query: no packages found matching fail2ban
dpkg-query: no packages found matching cloudflared
allmon3 1.11-1.deb13
asl3 3.18.2-2.deb13
asl3-appliance 2.2.2-1.deb13
asl3-appliance-pc 
asl3-appliance-pi 2.2.2-1.deb13
asl3-asterisk 2:22.10.1+asl3-3.10.8-1.deb13
asl3-asterisk-config 2:22.10.1+asl3-3.10.8-1.deb13
asl3-asterisk-config-custom 
asl3-asterisk-dev 
asl3-asterisk-doc 
asl3-asterisk-modules 2:22.10.1+asl3-3.10.8-1.deb13
asl3-menu 1.18-1.deb13
asl3-pi-appliance 
asl3-update-nodelist 2.1.0-1.deb13
dvswitch 1.6.0-20240701-20
dvswitch-base 1.6.0-20250507-99
dvswitch-dashboard 1.6.1-20241231-98
dvswitch-menu 1.6.2-20240701-120
dvswitch-monit 1.6.0-20240701-20
dvswitch-server 1.6.0-20260716-12
firewalld 2.3.1-1+deb13u1
nftables 1.1.3-1
wireguard 1.0.20210914-3
wireguard-dkms 
wireguard-modules 
wireguard-tools 1.0.20210914-3
```

### firewall-cmd --list-all-zones

```
44NetConnect (active)
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: wg0
  sources: 
  services: echolink iax2
  ports: 
  protocols: 
  forward: no
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

allstarlink (default, active)
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: wlan0
  sources: 
  services: 44Helper 5160 Dashboard--8989-8989 Instamon Sysmon--9999-9999 cockpit custom--10000-20000 custom--8991 custom--8993-8993 custom--sip dhcpv6-client echolink http https iax2 mdns rtcm sip ssh
  ports: 10000-20000/udp 5060/udp 5160/udp
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

block
  target: %%REJECT%%
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: 
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

dmz
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: ssh
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

drop
  target: DROP
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: 
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

external
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: ssh
  ports: 
  protocols: 
  forward: yes
  masquerade: yes
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

home
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: dhcpv6-client mdns samba-client ssh
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

internal
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: dhcpv6-client mdns samba-client ssh
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

nm-shared
  target: ACCEPT
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: dhcp dns ssh
  ports: 
  protocols: icmp ipv6-icmp
  forward: no
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 
	rule priority="32767" reject

public
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: dhcpv6-client ssh
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

trusted
  target: ACCEPT
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: 
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 

work
  target: default
  ingress-priority: 0
  egress-priority: 0
  icmp-block-inversion: no
  interfaces: 
  sources: 
  services: dhcpv6-client ssh
  ports: 
  protocols: 
  forward: yes
  masquerade: no
  forward-ports: 
  source-ports: 
  icmp-blocks: 
  rich rules: 
```

### nft list ruleset

```
table inet firewalld { # progname firewalld
	flags owner,persist

	ct helper helper-sip-tcp {
		type "sip" protocol tcp
		l3proto inet
	}

	ct helper helper-sip-udp {
		type "sip" protocol udp
		l3proto inet
	}

	chain mangle_PREROUTING {
		type filter hook prerouting priority mangle + 10; policy accept;
		jump mangle_PREROUTING_POLICIES
	}

	chain mangle_PREROUTING_POLICIES {
		iifname "wg0" jump mangle_PRE_policy_allow-host-ipv6
		iifname "wg0" jump mangle_PRE_44NetConnect
		iifname "wg0" return
		iifname "wlan0" jump mangle_PRE_policy_allow-host-ipv6
		iifname "wlan0" jump mangle_PRE_allstarlink
		iifname "wlan0" return
		jump mangle_PRE_policy_allow-host-ipv6
		jump mangle_PRE_allstarlink
		return
	}

	chain nat_PREROUTING {
		type nat hook prerouting priority dstnat + 10; policy accept;
		jump nat_PREROUTING_POLICIES
	}

	chain nat_PREROUTING_POLICIES {
		iifname "wg0" jump nat_PRE_policy_allow-host-ipv6
		iifname "wg0" jump nat_PRE_44NetConnect
		iifname "wg0" return
		iifname "wlan0" jump nat_PRE_policy_allow-host-ipv6
		iifname "wlan0" jump nat_PRE_allstarlink
		iifname "wlan0" return
		jump nat_PRE_policy_allow-host-ipv6
		jump nat_PRE_allstarlink
		return
	}

	chain nat_POSTROUTING {
		type nat hook postrouting priority srcnat + 10; policy accept;
		jump nat_POSTROUTING_POLICIES
	}

	chain nat_POSTROUTING_POLICIES {
		iifname "wg0" oifname "wg0" jump nat_POST_44NetConnect
		iifname "wg0" oifname "wg0" return
		iifname "wlan0" oifname "wg0" jump nat_POST_44NetConnect
		iifname "wlan0" oifname "wg0" return
		oifname "wg0" jump nat_POST_44NetConnect
		oifname "wg0" return
		iifname "wg0" oifname "wlan0" jump nat_POST_allstarlink
		iifname "wg0" oifname "wlan0" return
		iifname "wlan0" oifname "wlan0" jump nat_POST_allstarlink
		iifname "wlan0" oifname "wlan0" return
		oifname "wlan0" jump nat_POST_allstarlink
		oifname "wlan0" return
		iifname "wg0" jump nat_POST_allstarlink
		iifname "wg0" return
		iifname "wlan0" jump nat_POST_allstarlink
		iifname "wlan0" return
		jump nat_POST_allstarlink
		return
	}

	chain nat_OUTPUT {
		type nat hook output priority dstnat + 10; policy accept;
		jump nat_OUTPUT_POLICIES
	}

	chain nat_OUTPUT_POLICIES {
		oifname "wg0" jump nat_OUT_44NetConnect
		oifname "wg0" return
		oifname "wlan0" jump nat_OUT_allstarlink
		oifname "wlan0" return
		jump nat_OUT_allstarlink
		return
	}

	chain filter_PREROUTING {
		type filter hook prerouting priority filter + 10; policy accept;
		icmpv6 type { nd-router-advert, nd-neighbor-solicit } accept
		meta nfproto ipv6 fib saddr . mark . iif oif missing drop
	}

	chain filter_INPUT {
		type filter hook input priority filter + 10; policy accept;
		ct state { established, related } accept
		ct status dnat accept
		iifname "lo" accept
		ct state invalid drop
		jump filter_INPUT_POLICIES
		reject with icmpx admin-prohibited
	}

	chain filter_FORWARD {
		type filter hook forward priority filter + 10; policy accept;
		ct state { established, related } accept
		ct status dnat accept
		iifname "lo" accept
		ct state invalid drop
		ip6 daddr { ::/96, ::ffff:0.0.0.0/96, 2002::/24, 2002:a00::/24, 2002:7f00::/24, 2002:a9fe::/32, 2002:ac10::/28, 2002:c0a8::/32, 2002:e000::/19 } reject with icmpv6 addr-unreachable
		jump filter_FORWARD_POLICIES
		reject with icmpx admin-prohibited
	}

	chain filter_OUTPUT {
		type filter hook output priority filter + 10; policy accept;
		ct state { established, related } accept
		ct status dnat accept
		oifname "lo" accept
		ip6 daddr { ::/96, ::ffff:0.0.0.0/96, 2002::/24, 2002:a00::/24, 2002:7f00::/24, 2002:a9fe::/32, 2002:ac10::/28, 2002:c0a8::/32, 2002:e000::/19 } reject with icmpv6 addr-unreachable
		jump filter_OUTPUT_POLICIES
	}

	chain filter_INPUT_POLICIES {
		iifname "wg0" jump filter_IN_policy_allow-host-ipv6
		iifname "wg0" jump filter_IN_44NetConnect
		iifname "wg0" reject with icmpx admin-prohibited
		iifname "wlan0" jump filter_IN_policy_allow-host-ipv6
		iifname "wlan0" jump filter_IN_allstarlink
		iifname "wlan0" reject with icmpx admin-prohibited
		jump filter_IN_policy_allow-host-ipv6
		jump filter_IN_allstarlink
		reject with icmpx admin-prohibited
	}

	chain filter_FORWARD_POLICIES {
		iifname "wg0" oifname "wg0" jump filter_FWD_44NetConnect
		iifname "wg0" oifname "wg0" reject with icmpx admin-prohibited
		iifname "wg0" oifname "wlan0" jump filter_FWD_44NetConnect
		iifname "wg0" oifname "wlan0" reject with icmpx admin-prohibited
		iifname "wg0" jump filter_FWD_44NetConnect
		iifname "wg0" reject with icmpx admin-prohibited
		iifname "wlan0" oifname "wg0" jump filter_FWD_allstarlink
		iifname "wlan0" oifname "wg0" reject with icmpx admin-prohibited
		iifname "wlan0" oifname "wlan0" jump filter_FWD_allstarlink
		iifname "wlan0" oifname "wlan0" reject with icmpx admin-prohibited
		iifname "wlan0" jump filter_FWD_allstarlink
		iifname "wlan0" reject with icmpx admin-prohibited
		oifname "wg0" jump filter_FWD_allstarlink
		oifname "wg0" reject with icmpx admin-prohibited
		oifname "wlan0" jump filter_FWD_allstarlink
		oifname "wlan0" reject with icmpx admin-prohibited
		jump filter_FWD_allstarlink
		reject with icmpx admin-prohibited
	}

	chain filter_OUTPUT_POLICIES {
		oifname "wg0" jump filter_OUT_44NetConnect
		oifname "wg0" return
		oifname "wlan0" jump filter_OUT_allstarlink
		oifname "wlan0" return
		jump filter_OUT_allstarlink
		return
	}

	chain filter_IN_allstarlink {
		jump filter_IN_allstarlink_pre
		jump filter_IN_allstarlink_log
		jump filter_IN_allstarlink_deny
		jump filter_IN_allstarlink_allow
		jump filter_IN_allstarlink_post
		meta l4proto { icmp, ipv6-icmp } accept
	}

	chain filter_IN_allstarlink_pre {
	}

	chain filter_IN_allstarlink_log {
	}

	chain filter_IN_allstarlink_deny {
	}

	chain filter_IN_allstarlink_allow {
		tcp dport 22 accept
		ip6 daddr fe80::/64 udp dport 546 accept
		udp dport 5198-5199 accept
		tcp dport 80 accept
		tcp dport 443 accept
		tcp dport 9090 accept
		ip daddr 224.0.0.251 udp dport 5353 accept
		ip6 daddr ff02::fb udp dport 5353 accept
		udp dport 4560-4580 accept
		udp dport 1667 accept
		tcp dport 8989-8990 accept
		udp dport 8989-8990 accept
		tcp dport 9999 accept
		udp dport 9999 accept
		tcp dport 8990 accept
		udp dport 8990 accept
		tcp dport 9997 accept
		udp dport 9997 accept
		tcp dport 8991 accept
		tcp dport 5060 ct helper set "helper-sip-tcp"
		udp dport 5060 ct helper set "helper-sip-udp"
		tcp dport 5060 accept
		udp dport 5060 accept
		udp dport 5160 accept
		udp dport 10000-10003 accept
		tcp dport 8993 accept
		udp dport 8993 accept
		udp dport 10000-20000 accept
	}

	chain filter_IN_allstarlink_post {
	}

	chain filter_OUT_allstarlink {
		jump filter_OUT_allstarlink_pre
		jump filter_OUT_allstarlink_log
		jump filter_OUT_allstarlink_deny
		jump filter_OUT_allstarlink_allow
		jump filter_OUT_allstarlink_post
	}

	chain filter_OUT_allstarlink_pre {
	}

	chain filter_OUT_allstarlink_log {
	}

	chain filter_OUT_allstarlink_deny {
	}

	chain filter_OUT_allstarlink_allow {
	}

	chain filter_OUT_allstarlink_post {
	}

	chain nat_OUT_allstarlink {
		jump nat_OUT_allstarlink_pre
		jump nat_OUT_allstarlink_log
		jump nat_OUT_allstarlink_deny
		jump nat_OUT_allstarlink_allow
		jump nat_OUT_allstarlink_post
	}

	chain nat_OUT_allstarlink_pre {
	}

	chain nat_OUT_allstarlink_log {
	}

	chain nat_OUT_allstarlink_deny {
	}

	chain nat_OUT_allstarlink_allow {
	}

	chain nat_OUT_allstarlink_post {
	}

	chain nat_POST_allstarlink {
		jump nat_POST_allstarlink_pre
		jump nat_POST_allstarlink_log
		jump nat_POST_allstarlink_deny
		jump nat_POST_allstarlink_allow
		jump nat_POST_allstarlink_post
	}

	chain nat_POST_allstarlink_pre {
	}

	chain nat_POST_allstarlink_log {
	}

	chain nat_POST_allstarlink_deny {
	}

	chain nat_POST_allstarlink_allow {
	}

	chain nat_POST_allstarlink_post {
	}

	chain filter_FWD_allstarlink {
		jump filter_FWD_allstarlink_pre
		jump filter_FWD_allstarlink_log
		jump filter_FWD_allstarlink_deny
		jump filter_FWD_allstarlink_allow
		jump filter_FWD_allstarlink_post
	}

	chain filter_FWD_allstarlink_pre {
	}

	chain filter_FWD_allstarlink_log {
	}

	chain filter_FWD_allstarlink_deny {
	}

	chain filter_FWD_allstarlink_allow {
		oifname "wlan0" accept
	}

	chain filter_FWD_allstarlink_post {
	}

	chain nat_PRE_allstarlink {
		jump nat_PRE_allstarlink_pre
		jump nat_PRE_allstarlink_log
		jump nat_PRE_allstarlink_deny
		jump nat_PRE_allstarlink_allow
		jump nat_PRE_allstarlink_post
	}

	chain nat_PRE_allstarlink_pre {
	}

	chain nat_PRE_allstarlink_log {
	}

	chain nat_PRE_allstarlink_deny {
	}

	chain nat_PRE_allstarlink_allow {
	}

	chain nat_PRE_allstarlink_post {
	}

	chain mangle_PRE_allstarlink {
		jump mangle_PRE_allstarlink_pre
		jump mangle_PRE_allstarlink_log
		jump mangle_PRE_allstarlink_deny
		jump mangle_PRE_allstarlink_allow
		jump mangle_PRE_allstarlink_post
	}

	chain mangle_PRE_allstarlink_pre {
	}

	chain mangle_PRE_allstarlink_log {
	}

	chain mangle_PRE_allstarlink_deny {
	}

	chain mangle_PRE_allstarlink_allow {
	}

	chain mangle_PRE_allstarlink_post {
	}

	chain filter_IN_44NetConnect {
		jump filter_IN_44NetConnect_pre
		jump filter_IN_44NetConnect_log
		jump filter_IN_44NetConnect_deny
		jump filter_IN_44NetConnect_allow
		jump filter_IN_44NetConnect_post
		meta l4proto { icmp, ipv6-icmp } accept
	}

	chain filter_IN_44NetConnect_pre {
	}

	chain filter_IN_44NetConnect_log {
	}

	chain filter_IN_44NetConnect_deny {
	}

	chain filter_IN_44NetConnect_allow {
		udp dport 4560-4580 accept
		udp dport 5198-5199 accept
	}

	chain filter_IN_44NetConnect_post {
	}

	chain filter_OUT_44NetConnect {
		jump filter_OUT_44NetConnect_pre
		jump filter_OUT_44NetConnect_log
		jump filter_OUT_44NetConnect_deny
		jump filter_OUT_44NetConnect_allow
		jump filter_OUT_44NetConnect_post
	}

	chain filter_OUT_44NetConnect_pre {
	}

	chain filter_OUT_44NetConnect_log {
	}

	chain filter_OUT_44NetConnect_deny {
	}

	chain filter_OUT_44NetConnect_allow {
	}

	chain filter_OUT_44NetConnect_post {
	}

	chain nat_OUT_44NetConnect {
		jump nat_OUT_44NetConnect_pre
		jump nat_OUT_44NetConnect_log
		jump nat_OUT_44NetConnect_deny
		jump nat_OUT_44NetConnect_allow
		jump nat_OUT_44NetConnect_post
	}

	chain nat_OUT_44NetConnect_pre {
	}

	chain nat_OUT_44NetConnect_log {
	}

	chain nat_OUT_44NetConnect_deny {
	}

	chain nat_OUT_44NetConnect_allow {
	}

	chain nat_OUT_44NetConnect_post {
	}

	chain nat_POST_44NetConnect {
		jump nat_POST_44NetConnect_pre
		jump nat_POST_44NetConnect_log
		jump nat_POST_44NetConnect_deny
		jump nat_POST_44NetConnect_allow
		jump nat_POST_44NetConnect_post
	}

	chain nat_POST_44NetConnect_pre {
	}

	chain nat_POST_44NetConnect_log {
	}

	chain nat_POST_44NetConnect_deny {
	}

	chain nat_POST_44NetConnect_allow {
	}

	chain nat_POST_44NetConnect_post {
	}

	chain filter_FWD_44NetConnect {
		jump filter_FWD_44NetConnect_pre
		jump filter_FWD_44NetConnect_log
		jump filter_FWD_44NetConnect_deny
		jump filter_FWD_44NetConnect_allow
		jump filter_FWD_44NetConnect_post
	}

	chain filter_FWD_44NetConnect_pre {
	}

	chain filter_FWD_44NetConnect_log {
	}

	chain filter_FWD_44NetConnect_deny {
	}

	chain filter_FWD_44NetConnect_allow {
	}

	chain filter_FWD_44NetConnect_post {
	}

	chain nat_PRE_44NetConnect {
		jump nat_PRE_44NetConnect_pre
		jump nat_PRE_44NetConnect_log
		jump nat_PRE_44NetConnect_deny
		jump nat_PRE_44NetConnect_allow
		jump nat_PRE_44NetConnect_post
	}

	chain nat_PRE_44NetConnect_pre {
	}

	chain nat_PRE_44NetConnect_log {
	}

	chain nat_PRE_44NetConnect_deny {
	}

	chain nat_PRE_44NetConnect_allow {
	}

	chain nat_PRE_44NetConnect_post {
	}

	chain mangle_PRE_44NetConnect {
		jump mangle_PRE_44NetConnect_pre
		jump mangle_PRE_44NetConnect_log
		jump mangle_PRE_44NetConnect_deny
		jump mangle_PRE_44NetConnect_allow
		jump mangle_PRE_44NetConnect_post
	}

	chain mangle_PRE_44NetConnect_pre {
	}

	chain mangle_PRE_44NetConnect_log {
	}

	chain mangle_PRE_44NetConnect_deny {
	}

	chain mangle_PRE_44NetConnect_allow {
	}

	chain mangle_PRE_44NetConnect_post {
	}

	chain filter_IN_policy_allow-host-ipv6 {
		jump filter_IN_policy_allow-host-ipv6_pre
		jump filter_IN_policy_allow-host-ipv6_log
		jump filter_IN_policy_allow-host-ipv6_deny
		jump filter_IN_policy_allow-host-ipv6_allow
		jump filter_IN_policy_allow-host-ipv6_post
	}

	chain filter_IN_policy_allow-host-ipv6_pre {
	}

	chain filter_IN_policy_allow-host-ipv6_log {
	}

	chain filter_IN_policy_allow-host-ipv6_deny {
	}

	chain filter_IN_policy_allow-host-ipv6_allow {
		icmpv6 type nd-neighbor-advert accept
		icmpv6 type nd-neighbor-solicit accept
		icmpv6 type nd-redirect accept
		icmpv6 type nd-router-advert accept
	}

	chain filter_IN_policy_allow-host-ipv6_post {
	}

	chain nat_PRE_policy_allow-host-ipv6 {
		jump nat_PRE_policy_allow-host-ipv6_pre
		jump nat_PRE_policy_allow-host-ipv6_log
		jump nat_PRE_policy_allow-host-ipv6_deny
		jump nat_PRE_policy_allow-host-ipv6_allow
		jump nat_PRE_policy_allow-host-ipv6_post
	}

	chain nat_PRE_policy_allow-host-ipv6_pre {
	}

	chain nat_PRE_policy_allow-host-ipv6_log {
	}

	chain nat_PRE_policy_allow-host-ipv6_deny {
	}

	chain nat_PRE_policy_allow-host-ipv6_allow {
	}

	chain nat_PRE_policy_allow-host-ipv6_post {
	}

	chain mangle_PRE_policy_allow-host-ipv6 {
		jump mangle_PRE_policy_allow-host-ipv6_pre
		jump mangle_PRE_policy_allow-host-ipv6_log
		jump mangle_PRE_policy_allow-host-ipv6_deny
		jump mangle_PRE_policy_allow-host-ipv6_allow
		jump mangle_PRE_policy_allow-host-ipv6_post
	}

	chain mangle_PRE_policy_allow-host-ipv6_pre {
	}

	chain mangle_PRE_policy_allow-host-ipv6_log {
	}

	chain mangle_PRE_policy_allow-host-ipv6_deny {
	}

	chain mangle_PRE_policy_allow-host-ipv6_allow {
	}

	chain mangle_PRE_policy_allow-host-ipv6_post {
	}
}
```

### wg show

```
interface: wg0
  public key: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
  private key: (hidden)
  listening port: 41082
  fwmark: 0x4444

peer: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
  endpoint: 198.51.100.22:44000
  allowed ips: 0.0.0.0/0
  latest handshake: 1 minute, 46 seconds ago
  transfer: 92.99 MiB received, 9.86 MiB sent
  persistent keepalive: every 20 seconds
```

### ip addr

```
1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 qdisc noqueue state UNKNOWN group default qlen 1000
    link/loopback 00:00:00:xx:xx:xx brd 00:00:00:xx:xx:xx
    inet 127.0.0.1/8 scope host lo
       valid_lft forever preferred_lft forever
    inet6 ::1/128 scope host noprefixroute 
       valid_lft forever preferred_lft forever
2: wlan0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UP group default qlen 1000
    link/ether 88:a2:9e:xx:xx:xx brd ff:ff:ff:xx:xx:xx
    inet 198.51.100.43/24 brd 198.51.100.44 scope global dynamic noprefixroute wlan0
       valid_lft 4236sec preferred_lft 4236sec
    inet6 fe80::8aa2:9eff:fe61:203d/64 scope link noprefixroute 
       valid_lft forever preferred_lft forever
3: wg0: <POINTOPOINT,NOARP,UP,LOWER_UP> mtu 1380 qdisc noqueue state UNKNOWN group default qlen 1000
    link/none 
    inet 198.51.100.3/32 scope global wg0
       valid_lft forever preferred_lft forever
    inet6 fe80::9be5:e28e:380a:c67e/64 scope link 
       valid_lft forever preferred_lft forever
```

### ip rule

```
0:	from all lookup local
1099:	from all fwmark 0x4444 lookup main
1100:	from all lookup main suppress_prefixlength 0
1101:	from 198.51.100.3 lookup 4444
1102:	from all uidrange 102-102 lookup 4444
1103:	from all ipproto udp sport 4569 lookup 4444
1107:	from all to 198.51.100.19/9 lookup 4444
1108:	from all to 198.51.100.20/10 lookup 4444
32766:	from all lookup main
32767:	from all lookup default
```

### ip route show table all

```
default dev wg0 table 4444 scope link 
default via 198.51.100.2 dev wlan0 proto dhcp src 198.51.100.43 metric 600 
198.51.100.1/24 dev wlan0 proto kernel scope link src 198.51.100.43 metric 600 
local 198.51.100.3 dev wg0 table local proto kernel scope host src 198.51.100.3 
local 127.0.0.0/8 dev lo table local proto kernel scope host src 127.0.0.1 
local 127.0.0.1 dev lo table local proto kernel scope host src 127.0.0.1 
broadcast 127.255.255.255 dev lo table local proto kernel scope link src 127.0.0.1 
local 198.51.100.43 dev wlan0 table local proto kernel scope host src 198.51.100.43 
broadcast 198.51.100.44 dev wlan0 table local proto kernel scope link src 198.51.100.43 
fe80::/64 dev wg0 proto kernel metric 256 pref medium
fe80::/64 dev wlan0 proto kernel metric 1024 pref medium
local ::1 dev lo table local proto kernel metric 0 pref medium
local fe80::8aa2:9eff:fe61:203d dev wlan0 table local proto kernel metric 0 pref medium
local fe80::9be5:e28e:380a:c67e dev wg0 table local proto kernel metric 0 pref medium
multicast ff00::/8 dev wlan0 table local proto kernel metric 256 pref medium
multicast ff00::/8 dev wg0 table local proto kernel metric 256 pref medium
```

### asterisk -rx 'core show version'

```
Asterisk 22.10.1+asl3-3.10.8-1.deb13 built by builder @ allstarlink.org on a aarch64 running Linux on 2026-10-11 14:56:55 UTC
```

### asterisk -rx 'rpt localnodes'

```
                         
Node
----
500001
500002
500003
1001
1002
500004
```

### systemctl cat nodecontrol

```
# /etc/systemd/system/nodecontrol.service
[Unit]
Description=ASL-DVS Node Control Dashboard
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/nodecontrol.py
Restart=always
RestartSec=3s
WatchdogSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### systemctl cat sysmon

```
# /etc/systemd/system/sysmon.service
[Unit]
Description=ASL-DVS SYSMON
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/sysmon.py
Restart=always
RestartSec=3s
WatchdogSec=30
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### systemctl cat instmon

```
# /etc/systemd/system/instmon.service
[Unit]
Description=instmon Web Installer & Component Manager
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/instmon.py
Restart=always
RestartSec=3s
TimeoutStartSec=600
WatchdogSec=60s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### systemctl cat wifimon

```
# /etc/systemd/system/wifimon.service
[Unit]
Description=WiFi and Voltage Watchdog + Dashboard (port 8991)
After=network.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/wifimon.py
Restart=always
RestartSec=3s
WatchdogSec=60
StandardOutput=journal
StandardError=journal

Nice=-5
OOMScoreAdjust=-500

[Install]
WantedBy=multi-user.target
```

### systemctl cat 44helper

```
# /etc/systemd/system/44helper.service
[Unit]
Description=ASL-DVS-M17 44 Helper (44Net Connect / firewall / router dashboard)
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/44helper.py
Restart=always
RestartSec=3s
WatchdogSec=60
User=root
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### systemctl cat nodetalker

```
# /etc/systemd/system/nodetalker.service
[Unit]
Description=Node Talker: ASL node audio in the browser
After=network.target asterisk.service

[Service]
Type=notify
NotifyAccess=main
ExecStart=/usr/bin/python3 /usr/local/bin/asl_dvs_launch.py /usr/local/bin/nodelisten.py
Restart=always
RestartSec=3s
TimeoutStartSec=60
WatchdogSec=60s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
Alias=nodelisten.service
```

### systemctl cat asterisk

```
# /usr/lib/systemd/system/asterisk.service
[Unit]
Description=Asterisk PBX
Documentation=man:asterisk(8)
Wants=network-online.target
After=network-online.target

[Service]
Type=notify
ExecStart=/usr/sbin/asterisk -g -f -p -U asterisk
ExecReload=/usr/sbin/asterisk -rx 'core reload'
Restart=on-failure
RestartSec=5
WorkingDirectory=/var/lib/asterisk

# The following two lines are by default set to null so as to avoid
# unnecessary console output to syslog. However, if you to, you can
# further edit /etc/asterisk/logger.conf to log output to syslog.
StandardOutput=null
StandardError=null

# Allow asterisk to bind to port below 1024 (e.g. chan_voter)
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Extra settings:
# If you want to set them, you can add them to a file in the directory
# /lib/systemd/system/asterisk.service.d/ with the extension .conf.
# Example content:
#[Service]
#
# and following those two lines add directives or override existing
# directives. Some extra directives that may be useful:

# You can run a script to clean up after asterisk. An example script is
# included in contrib/scripts/asterisk_cleanup.
#ExecStopPost=/path/to/script

#Nice=0
#UMask=0002
#LimitCORE=infinity
#LimitNOFILE=

# safe_asterisk runs Asterisk in a virtual console. This allows easy
# access to the asterisk command-line without logging it. on the other
# hand, it allows anyone with physical access to the console full access
# to Asterisk. To enable this console, unrem the following lines and add
# '-c' to the ExecStart line above:
#TTYPath=/dev/tty9
#StandardInput=tty
#StandardOutput=tty
#StandardError=tty

# For more information on what these parameters mean see:
#
# http://0pointer.de/public/systemd-man/systemd.service.html
# http://0pointer.de/public/systemd-man/systemd.exec.html

[Install]
WantedBy=multi-user.target

# /run/systemd/system.control/asterisk.service.d/50-CPUWeight.conf
# This is a drop-in unit file extension, created via "systemctl set-property"
# or an equivalent operation. Do not edit.
[Service]
CPUWeight=500
```

### systemctl cat allmon3

```
# /usr/lib/systemd/system/allmon3.service
[Unit]
Description=Allmon3 daemon
After=network.target
After=asterisk.service

[Service]
Type=exec
User=allmon3
Group=allmon3
Environment="PATH=/usr/bin:/bin:/usr/sbin:/sbin"
ExecStart=allmon3
ExecReload=kill -USR1 $MAINPID

[Install]
WantedBy=multi-user.target
```

### systemctl cat analog_bridge

```
# /etc/systemd/system/analog_bridge.service
# 44helper netcheck override
[Unit]
Description=Analog_Bridge Service
# Description=Place this file in /lib/systemd/system
# Description=N4IRS 07/01/2024

After=netcheck.service

Wants=netcheck.service
[Service]
Type=simple
Restart=on-failure
RestartSec=3
RestartPreventExitStatus=252 253 254
StandardOutput=null
WorkingDirectory=/opt/Analog_Bridge
Environment=AnalogBridgeLogDir=/var/log/dvswitch
ExecStartPre = /usr/bin/sh -c 'echo "Starting Analog_Bridge: [`date +%%T.%%3N`]" >> /var/log/netcheck'
ExecStart=/opt/Analog_Bridge/Analog_Bridge /opt/Analog_Bridge/Analog_Bridge.ini
ExecStartPost= -/usr/local/sbin/update-config.sh
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process

[Install]
WantedBy=multi-user.target

# 254 matching IDs
# 253 ini parse errors
# 252 dv3000 not found, fallback not enabled

# /etc/systemd/system/analog_bridge.service.d/44helper-boot.conf
[Unit]
After=44helper-netready.service
Wants=44helper-netready.service

[Service]
Restart=on-failure
RestartSec=15

# /run/systemd/system.control/analog_bridge.service.d/50-CPUWeight.conf
# This is a drop-in unit file extension, created via "systemctl set-property"
# or an equivalent operation. Do not edit.
[Service]
CPUWeight=100
```

### systemctl cat mmdvm_bridge

```
# /etc/systemd/system/mmdvm_bridge.service
# 44helper netcheck override
[Unit]
Description=MMDVM_Bridge Service
# Description=Place this file in /lib/systemd/system
# Description=N4IRS 07/01/2024

After=netcheck.service

Wants=netcheck.service
[Service]
Type=simple
Restart=always
RestartSec=3
Restart=on-abort
StandardOutput=null
WorkingDirectory=/opt/MMDVM_Bridge
ExecStartPre = /usr/bin/sh -c 'echo "Starting MMDVM_Bridge: [`date +%%T.%%3N`]" >> /var/log/netcheck'
ExecStart=/opt/MMDVM_Bridge/MMDVM_Bridge /opt/MMDVM_Bridge/MMDVM_Bridge.ini
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/mmdvm_bridge.service.d/44helper-boot.conf
[Unit]
After=44helper-netready.service
Wants=44helper-netready.service

[Service]
Restart=on-failure
RestartSec=15

# /run/systemd/system.control/mmdvm_bridge.service.d/50-CPUWeight.conf
# This is a drop-in unit file extension, created via "systemctl set-property"
# or an equivalent operation. Do not edit.
[Service]
CPUWeight=100
```

### systemctl cat md380-emu

```
# /usr/lib/systemd/system/md380-emu.service
[Unit]
Description=MD-380 Emulator Service
# Description=Place this file in /lib/systemd/system
# Description=N4IRS 07/01/2024

[Service]
Type=simple
Restart=always
RestartSec=3
StandardOutput=null
WorkingDirectory=/opt/md380-emu
ExecStartPre = /usr/bin/sh -c 'echo "Starting md380-emu: [`date +%%T.%%3N`]" >> /var/log/netcheck'
ExecStart=/opt/md380-emu/qemu-arm-static /opt/md380-emu/md380-emu -S 2470
ExecReload=/bin/kill -HUP $MAINPID
KillMode=process

[Install]

WantedBy=multi-user.target

# /etc/systemd/system/md380-emu.service.d/44helper-boot.conf
[Unit]
After=44helper-netready.service
Wants=44helper-netready.service

[Service]
Restart=on-failure
RestartSec=15
```

### systemctl cat usrp2m17

```
# /usr/lib/systemd/system/usrp2m17.service
[Unit]
Description=USRP2M17 Service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0

[Service]
Type=simple
ExecStart=/opt/USRP2M17/USRP2M17 /opt/USRP2M17/USRP2M17.ini
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
KillMode=process
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target

# /run/systemd/system.control/usrp2m17.service.d/50-CPUWeight.conf
# This is a drop-in unit file extension, created via "systemctl set-property"
# or an equivalent operation. Do not edit.
[Service]
CPUWeight=100
```

### systemctl cat stfu

```
# /etc/systemd/system/stfu.service
[Unit]
Description=STFU Service
# Description=Place this file in /lib/systemd/system
# Description=N4IRS 07/01/2024

After=netcheck.service
Requires=netcheck.service

[Service]
Type=simple
Restart=always
RestartSec=3
RestartPreventExitStatus=255 254 253 251
StandardOutput=null
WorkingDirectory=/opt/STFU
Environment=STFU_LOG=/var/log/dvswitch
ExecStartPre = /usr/bin/sh -c 'echo "Starting STFU: [`date +%%T.%%3N`]" >> /var/log/netcheck'
ExecStart=/opt/STFU/STFU /opt/MMDVM_Bridge/DVSwitch.ini
# ExecStartPost= -/usr/local/sbin/update-config.sh
ExecReload=/bin/kill -2 $MAINPID
KillMode=process

[Install]
WantedBy=multi-user.target

# ERROR_SUCCESS               0       // ALL
# ERROR_PORT_IN_USE           251     // STFU
# ERROR_DV3000_NOT_FOUND      252     // AB
# ERROR_INI_PARSE             253     // AB, MB, STFU
# ERROR_MATCHING_IDS          254     // AB
# ERROR_FATAL_ERROR           254     // MB, STFU
# ERROR_SERVER_TIMEOUT        255     // STFU

# /etc/systemd/system/stfu.service.d/44helper-boot.conf
[Unit]
After=44helper-netready.service
Wants=44helper-netready.service

[Service]
Restart=on-failure
RestartSec=15

# /etc/systemd/system/stfu.service.d/44helper-netcheck.conf
# 44helper v0.0.93 netcheck fix -- reversible: delete this file (or use
# Revert) and daemon-reload. Drops netcheck from Requires= (so a netcheck
# failure no longer keeps this bridge down) and demotes it to Wants=,
# keeping the ordering.
[Unit]
Requires=
Requires=system.slice sysinit.target -.mount
Wants=netcheck.service
After=netcheck.service network-online.target

# /run/systemd/system.control/stfu.service.d/50-CPUWeight.conf
# This is a drop-in unit file extension, created via "systemctl set-property"
# or an equivalent operation. Do not edit.
[Service]
CPUWeight=300
```

### systemctl cat 44helper-netready

```
# /etc/systemd/system/44helper-netready.service
[Unit]
Description=44helper: wait until the network, the 44Net tunnel and DNS are ready
After=network-online.target <redacted:028f8877> nss-lookup.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=210
ExecStart=/usr/local/sbin/44helper-netready
```

### systemctl cat wg-quick@wg0

```
# /usr/lib/systemd/system/wg-quick@.service
[Unit]
Description=WireGuard via wg-quick(8) for %I
After=network-online.target nss-lookup.target
Wants=network-online.target nss-lookup.target
PartOf=wg-quick.target
Documentation=man:wg-quick(8)
Documentation=man:wg(8)
Documentation=https://www.wireguard.com/
Documentation=https://www.wireguard.com/quickstart/
Documentation=https://git.zx2c4.com/wireguard-tools/about/src/man/wg-quick.8
Documentation=https://git.zx2c4.com/wireguard-tools/about/src/man/wg.8

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/wg-quick up %i
ExecStop=/usr/bin/wg-quick down %i
ExecReload=/bin/bash -c 'exec /usr/bin/wg syncconf %i <(exec /usr/bin/wg-quick strip %i)'
Environment=WG_ENDPOINT_RESOLUTION_RETRIES=infinity

[Install]
WantedBy=multi-user.target

# /etc/systemd/system/wg-quick@wg0.service.d/44helper-boot.conf
[Unit]
StartLimitIntervalSec=0

[Service]
ExecStartPre=/usr/local/sbin/44helper-timewait
TimeoutStartSec=210
Restart=on-failure
RestartSec=20
```

### systemctl cat firewalld

```
# /usr/lib/systemd/system/firewalld.service
[Unit]
Description=firewalld - dynamic firewall daemon
Before=network-pre.target
Wants=network-pre.target
After=dbus.service
After=polkit.service
Conflicts=iptables.service ip6tables.service ebtables.service ipset.service
Documentation=man:firewalld(1)

[Service]
ExecStart=/usr/sbin/firewalld --nofork --nopid
ExecStartPost=/usr/bin/firewall-cmd --state
# don't fail ExecStartPost on RUNNING_BUT_FAILED
SuccessExitStatus=251
ExecReload=/bin/kill -HUP $MAINPID
StandardOutput=null
StandardError=null
Type=dbus
BusName=org.fedoraproject.FirewallD1
KillMode=mixed
DevicePolicy=closed
KeyringMode=private
LockPersonality=yes
MemoryDenyWriteExecute=yes
PrivateDevices=yes
ProtectClock=yes
ProtectControlGroups=yes
ProtectHome=yes
ProtectHostname=yes
ProtectKernelLogs=yes
ProtectKernelModules=no
ProtectKernelTunables=no
ProtectSystem=yes
RestrictRealtime=yes
RestrictSUIDSGID=yes
SystemCallArchitectures=native

[Install]
WantedBy=multi-user.target
Alias=dbus-org.fedoraproject.FirewallD1.service
```


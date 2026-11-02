#!/usr/bin/env python3
import http.client
import json
import os
import socket
import struct
import ssl
import time
import unittest

import test_servers as ts

PW = os.environ.get("ASL_TEST_ROOT_PASSWORD") or ""
UNIT_FILES = {
    "stfu": "/etc/systemd/system/stfu.service",
    "usrp2m17": "/etc/systemd/system/usrp2m17.service",
    "asl-zello-bridge": "/etc/systemd/system/asl-zello-bridge.service",
}
SYSMON_BADGES = [("/api/stfu", "stfu"), ("/api/m17", "usrp2m17"), ("/api/zello", "asl-zello-bridge")]
SVC_POLL_SEC = 20.0
DVS_PATH = "/opt/MMDVM_Bridge/dvswitch.sh"
READ_CAP = 262144


def skip_reason():
    if os.geteuid() != 0:
        return "authenticated tests run as root"
    if not PW:
        return "set ASL_TEST_ROOT_PASSWORD (the root account must have that password)"
    return None


def login(server):
    st, h, b = server.request("POST", "/api/login", body=json.dumps({"password": PW}),
                              headers={"Content-Type": "application/json"}, timeout=15)
    if st != 200:
        raise AssertionError(f"login to {server.key} failed: {st} {b[:120]!r}")
    return h.get("Set-Cookie", "").split(";")[0]


def get_partial(server, path, cookie):
    if server.spec["scheme"] == "https":
        conn = http.client.HTTPSConnection("127.0.0.1", server.spec["port"], timeout=5,
                                           context=ssl._create_unverified_context())
    else:
        conn = http.client.HTTPConnection("127.0.0.1", server.spec["port"], timeout=5)
    try:
        conn.request("GET", path, headers={"Cookie": cookie})
        resp = conn.getresponse()
        ctype = resp.getheader("Content-Type", "")
        try:
            body = resp.read(READ_CAP)
            complete = len(body) < READ_CAP
        except (socket.timeout, TimeoutError):
            body, complete = b"", False
        return resp.status, ctype, body, complete
    finally:
        conn.close()


def get_json(server, path, cookie):
    st, _, b = server.request("GET", path, headers={"Cookie": cookie}, timeout=15)
    return st, json.loads(b)


def stub_units(server):
    return os.path.join(server.stub_dir, "units")


def set_unit(server, unit, state):
    d = stub_units(server)
    os.makedirs(d, exist_ok=True)
    name = unit[:-len(".service")] if unit.endswith(".service") else unit
    with open(os.path.join(d, name + ".state"), "w") as f:
        f.write(state + "\n")


class UnitFiles:
    def __init__(self):
        self.created = []

    def install(self):
        for path in UNIT_FILES.values():
            if os.path.exists(path):
                raise unittest.SkipTest(f"{path} already exists; refusing to overwrite it")
        for path in UNIT_FILES.values():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("[Unit]\nDescription=ASL test fixture\n")
            self.created.append(path)

    def remove(self):
        for path in self.created:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        self.created = []


def make_case(key):
    class AuthedCase(unittest.TestCase):
        server = None
        cookie = None
        units = None

        @classmethod
        def setUpClass(cls):
            reason = skip_reason()
            if reason:
                raise unittest.SkipTest(reason)
            cls.server = ts.Server(key)
            cls.server.start()
            try:
                cls.cookie = login(cls.server)
                if key.startswith("sysmon"):
                    cls.units = UnitFiles()
                    cls.units.install()
            except BaseException:
                cls.tearDownClass()
                raise

        @classmethod
        def tearDownClass(cls):
            if cls.units:
                cls.units.remove()
            if cls.server:
                cls.server.stop()

        def routes(self, kind):
            return ts.routes_for(key)[kind]

        def test_every_protected_get_route_answers_without_error(self):
            problems = []
            checked = 0
            for path in self.routes("GET"):
                if ts.is_public(key, path):
                    continue
                checked += 1
                st, ctype, body, complete = get_partial(self.server, path, self.cookie)
                if st >= 500:
                    problems.append(f"{path} -> {st}")
                elif st == 200 and complete and "json" in ctype and body.strip():
                    try:
                        json.loads(body)
                    except ValueError:
                        problems.append(f"{path}: 200 but body is not JSON")
            self.assertGreater(checked, 0)
            self.assertEqual(problems, [], f"{len(problems)} of {checked} routes failed")

        def test_logout_revokes_the_session(self):
            posts = self.routes("POST")
            if "/api/logout" in posts:
                logout = ("/api/logout", b"{}")
            elif "/api/action" in posts:
                logout = ("/api/action", json.dumps({"action": "logout"}).encode())
            else:
                self.skipTest("build has no logout route")
            protected = [p for p in self.routes("GET") if not ts.is_public(key, p)]
            own = login(self.server)
            st = get_partial(self.server, protected[0], own)[0]
            self.assertEqual(st, 200, "session should work before logout")
            self.server.request("POST", logout[0], body=logout[1],
                                headers={"Content-Type": "application/json", "Cookie": own})
            st, _, _, _ = get_partial(self.server, protected[0], own)
            self.assertIn(st, (401, 403), "the logged-out cookie must stop working")
            st = get_partial(self.server, protected[0], self.cookie)[0]
            self.assertEqual(st, 200, "logging out one session must not end the others")

    AuthedCase.__name__ = f"Authed_{key}"
    AuthedCase.__qualname__ = f"Authed_{key}"
    return AuthedCase


class SysmonBadgeMixin:
    def check_install_badges(self):
        for route, unit in SYSMON_BADGES:
            if route not in self.routes("GET"):
                continue
            for state, want in [("active", True), ("inactive", False), ("failed", False), ("active", True)]:
                set_unit(self.server, unit, state)
                st, d = get_json(self.server, route, self.cookie)
                self.assertEqual(st, 200)
                inst = d.get("install", {})
                self.assertTrue(inst.get("service_installed"), f"{route}: unit file not seen")
                self.assertEqual(inst.get("service_active"), want,
                                 f"{route}: systemd says {state}, API says service_active={inst.get('service_active')}")


def add_sysmon_badges(cls):
    def test_install_badges_follow_systemd_state_changes(self):
        self.check_install_badges()
    cls.test_install_badges_follow_systemd_state_changes = test_install_badges_follow_systemd_state_changes
    return cls


def make_nc_case(key):
    base = make_case(key)

    class NCCase(base):
        def test_service_block_follows_systemd_within_poll_interval(self):
            set_unit(self.server, "analog_bridge.service", "active")
            self.assert_svc_becomes("ab", "active")
            set_unit(self.server, "analog_bridge.service", "inactive")
            self.assert_svc_becomes("ab", "inactive")

        def test_service_timestamp_advances_each_check(self):
            st, d = get_json(self.server, "/api/status", self.cookie)
            first = d.get("svc_at")
            self.assertIsNotNone(first, "svc_at missing from /api/status")
            deadline = time.time() + SVC_POLL_SEC
            while time.time() < deadline:
                time.sleep(1)
                st, d = get_json(self.server, "/api/status", self.cookie)
                if d.get("svc_at", 0) > first:
                    self.assertLess(time.time() - d["svc_at"], 20, "svc_at should be recent")
                    return
            self.fail(f"svc_at stayed at {first}; the service check is not refreshing it")

        def assert_svc_becomes(self, name, want):
            deadline = time.time() + SVC_POLL_SEC
            last = None
            while time.time() < deadline:
                st, d = get_json(self.server, "/api/status", self.cookie)
                last = (d.get("svc") or {}).get(name)
                if last == want:
                    return
                time.sleep(1)
            self.fail(f"svc.{name} stayed {last!r} (last HTTP {st}, keys {sorted(d)[:6]}); "
                      f"systemd state changed to {want!r} and the block did not follow "
                      f"within {SVC_POLL_SEC}s")

    NCCase.__name__ = f"Authed_{key}"
    NCCase.__qualname__ = f"Authed_{key}"
    return NCCase


def make_nc_dvs_case(key):
    class DVSCase(make_nc_case(key)):
        fixture = None
        created_dir = False

        @classmethod
        def setUpClass(cls):
            reason = skip_reason()
            if reason:
                raise unittest.SkipTest(reason)
            if os.path.exists(DVS_PATH):
                raise unittest.SkipTest(f"{DVS_PATH} already exists; refusing to overwrite it")
            d = os.path.dirname(DVS_PATH)
            cls.created_dir = not os.path.isdir(d)
            os.makedirs(d, exist_ok=True)
            with open(DVS_PATH, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(DVS_PATH, 0o755)
            cls.fixture = DVS_PATH
            cls.server = ts.Server(key)
            try:
                cls.server.start()
                cls.cookie = login(cls.server)
            except BaseException:
                cls.tearDownClass()
                raise

        @classmethod
        def tearDownClass(cls):
            if cls.server:
                cls.server.stop()
            if cls.fixture:
                try:
                    os.remove(cls.fixture)
                except FileNotFoundError:
                    pass
            if cls.created_dir:
                try:
                    os.rmdir(os.path.dirname(DVS_PATH))
                except OSError:
                    pass

        def test_service_block_follows_systemd_with_dvswitch_present(self):
            set_unit(self.server, "stfu.service", "active")
            self.assert_svc_becomes("stfu", "active")
            set_unit(self.server, "stfu.service", "inactive")
            self.assert_svc_becomes("stfu", "inactive")

    DVSCase.__name__ = f"AuthedDVS_{key}"
    DVSCase.__qualname__ = f"AuthedDVS_{key}"
    return DVSCase


def make_sysmon_case(key):
    base = make_case(key)

    class SMCase(SysmonBadgeMixin, base):
        pass

    SMCase.__name__ = f"Authed_{key}"
    SMCase.__qualname__ = f"Authed_{key}"
    add_sysmon_badges(SMCase)
    return SMCase


def make_nt_case(key):
    base = make_case(key)

    class NTCase(base):
        def test_receive_status_counts_packets_and_drops_after_silence(self):
            st, d = get_json(self.server, "/api/status", self.cookie)
            usrp = key == "noderecorder"
            if "packets" not in d or ("udp_port" not in d and not usrp):
                self.skipTest("build does not expose a node-audio UDP port in its status")
            start = d["packets"]
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                for n in range(20):
                    if usrp:
                        data = struct.pack(">4s7i", b"USRP", n, 0, 1, 0, 0, 0, 0) + os.urandom(320)
                        udp.sendto(data, ("127.0.0.1", 9995))
                    else:
                        udp.sendto(os.urandom(320), ("127.0.0.1", d["udp_port"]))
            finally:
                udp.close()
            time.sleep(0.5)
            st, d = get_json(self.server, "/api/status", self.cookie)
            self.assertEqual(d["packets"] - start, 20, "every datagram sent must be counted")
            self.assertTrue(d["receiving"], "receiving should be on right after audio")
            time.sleep(4)
            st, d = get_json(self.server, "/api/status", self.cookie)
            self.assertFalse(d["receiving"], "receiving should drop after 3 s of silence")
            self.assertGreaterEqual(d["last_rx_age"], 3.0)

    if key == "noderecorder":
        def _sched_post(self, path, body):
            hdr = {"Cookie": self.cookie, "Content-Type": "application/json", "X-Requested-With": "XMLHttpRequest"}
            st, _, b = self.server.request("POST", path, body=json.dumps(body), headers=hdr, timeout=15)
            return st, json.loads(b)

        def test_schedule_save_overlap_dry_run_and_remove(self):
            base = {"days": [1], "start": "06:00", "end": "08:00", "target": {"mode": "ASL", "num": "29332"}, "format": "ulaw"}
            ids = ("citest1", "citest2")
            try:
                st, d = self._sched_post("/api/schedule/set", {"entry": dict(base, id=ids[0], name="First")})
                self.assertTrue(d["ok"], d)
                st, d = self._sched_post("/api/schedule/set", {"entry": dict(base, id=ids[1], name="Second", start="07:00", end="09:00")})
                self.assertFalse(d["ok"], "an overlapping window must be refused")
                self.assertTrue(d.get("conflicts"), d)
                st, d = self._sched_post("/api/schedule/set", {"entry": dict(base, id=ids[1], start="25:00")})
                self.assertFalse(d["ok"], "a bad time must be refused")
                st, d = self._sched_post("/api/schedule/set", {"entry": dict(base, id=ids[1], name="Second", start="08:02", end="09:00")})
                self.assertTrue(d["ok"], "two minutes apart is allowed: " + str(d))
                st, d = get_json(self.server, "/api/schedule", self.cookie)
                self.assertEqual({e["id"] for e in d["entries"]} & set(ids), set(ids))
                self.assertTrue(d["dry_run"], "the engine is not built yet, so windows run as dry runs")
                st, d = self._sched_post("/api/schedule/dryrun", {"id": ids[0]})
                self.assertEqual([x["step"] for x in d["steps"]], ["connect", "start", "stop", "disconnect"], d)
                self.assertEqual(d["result"], "ok")
            finally:
                for i in ids:
                    self._sched_post("/api/schedule/remove", {"id": i})
            st, d = get_json(self.server, "/api/schedule", self.cookie)
            self.assertFalse({e["id"] for e in d["entries"]} & set(ids), "the test entries must be gone")

    NTCase.__name__ = f"Authed_{key}"
    NTCase.__qualname__ = f"Authed_{key}"
    return NTCase


for _key in ts.SERVERS:
    if _key.startswith("nodecontrol"):
        globals()[f"Authed_{_key}"] = make_nc_case(_key)
        globals()[f"AuthedDVS_{_key}"] = make_nc_dvs_case(_key)
    elif _key.startswith("sysmon"):
        globals()[f"Authed_{_key}"] = make_sysmon_case(_key)
    else:
        globals()[f"Authed_{_key}"] = make_nt_case(_key)


if __name__ == "__main__":
    unittest.main(verbosity=2)

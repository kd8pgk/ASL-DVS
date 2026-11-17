import email.message
import glob
import importlib.util
import json
import os
import re
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_post_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_post_under_test"] = h44
spec.loader.exec_module(h44)

h44._cfg = object()

PATHS = {
    "/api/router/config", "/api/pi_install/action", "/api/router_install/action", "/api/firewall/action", "/api/build/action",
    "/api/config/action", "/api/system_opt/action", "/api/nodes/peer_add", "/api/nodes/peer_edit", "/api/nodes/peer_remove",
    "/api/nodes/save_snippet", "/api/asl3/action", "/api/dvswitch/action", "/api/svxlink/action", "/api/m17/action", "/api/amp/action",
    "/api/cr/action", "/api/cf/action", "/api/update/action", "/api/repair/action", "/api/guard/action", "/api/quiet/action",
    "/api/update/lookup_installed", "/api/update/lookup_policy",
}


def post(path, body=None, auth=True, csrf=True, err=None, client="10.0.0.9"):
    h = object.__new__(h44.Handler)
    h.path = path
    h.headers = email.message.Message()
    h.client_address = (client, 1234)
    sent = []
    h._send = lambda status, ctype, data, extra_headers=None: sent.append((status, ctype, data))
    h._require_auth = lambda: auth
    h._check_csrf = lambda: csrf
    h._read_json_body = lambda: ((body if body is not None else {}), err)
    h.do_POST()
    return sent


class Table(unittest.TestCase):
    def test_every_route_is_still_there_and_nothing_was_added(self):
        self.assertEqual(set(h44._POST_JSON), PATHS)

    def test_the_only_route_without_a_body(self):
        self.assertEqual(h44._POST_NO_BODY, {"/api/update/lookup_installed"})


class Guards(unittest.TestCase):
    def test_no_login_means_nothing_runs(self):
        with mock.patch.object(h44, "_dispatch_build_action") as d:
            self.assertEqual(post("/api/build/action", auth=False), [])
            d.assert_not_called()

    def test_a_missing_csrf_header_is_a_403_and_nothing_runs(self):
        with mock.patch.object(h44, "_dispatch_config_action") as d:
            sent = post("/api/config/action", csrf=False)
            d.assert_not_called()
        self.assertEqual(sent[0][0], 403)

    def test_a_body_error_is_a_400_and_nothing_runs(self):
        with mock.patch.object(h44, "_dispatch_config_action") as d:
            sent = post("/api/config/action", err=b'{"message": "bad"}')
            d.assert_not_called()
        self.assertEqual((sent[0][0], sent[0][2]), (400, b'{"message": "bad"}'))

    def test_an_unknown_path_is_a_404(self):
        self.assertEqual(post("/api/nope")[0][0], 404)
        self.assertEqual(post("/api/build/action/extra")[0][0], 404)


class Dispatch(unittest.TestCase):
    def test_a_plain_action_gets_the_body_and_answers_json(self):
        with mock.patch.object(h44, "_dispatch_config_action", lambda p: {"success": True, "got": p}):
            status, ctype, data = post("/api/config/action", {"action": "x"})[0]
        self.assertEqual((status, ctype), (200, "application/json"))
        self.assertEqual(json.loads(data), {"success": True, "got": {"action": "x"}})

    def test_build_and_firewall_get_the_client_address(self):
        seen = {}
        with mock.patch.object(h44, "_dispatch_build_action", lambda p: seen.setdefault("build", dict(p)) or {}), \
                mock.patch.object(h44, "_dispatch_guarded", lambda fn, p: seen.setdefault("fw", dict(p)) or {}):
            post("/api/build/action", {"action": "a"}, client="10.1.2.3")
            post("/api/firewall/action", {"action": "b"}, client="10.1.2.4")
        self.assertEqual(seen["build"], {"action": "a", "_client_ip": "10.1.2.3"})
        self.assertEqual(seen["fw"], {"action": "b", "_client_ip": "10.1.2.4"})

    def test_other_actions_do_not_get_one(self):
        seen = {}
        with mock.patch.object(h44, "_dispatch_config_action", lambda p: seen.setdefault("p", dict(p)) or {}):
            post("/api/config/action", {"action": "a"})
        self.assertNotIn("_client_ip", seen["p"])

    def test_the_peer_routes_strip_and_share_one_function(self):
        calls = []
        with mock.patch.object(h44, "action_upsert_peer", lambda cfg, *a: calls.append(a) or {"success": True}):
            for path in ("/api/nodes/peer_add", "/api/nodes/peer_edit"):
                post(path, {"node": " 1234 ", "ip": "1.2.3.4 ", "port": " 4569", "label": " x ", "helper_url": " http://h "})
        self.assertEqual(calls, [("1234", "1.2.3.4", "4569", "x", "http://h")] * 2)

    def test_remove_and_snippet(self):
        with mock.patch.object(h44, "action_remove_peer", lambda cfg, node: {"removed": node}), \
                mock.patch.object(h44, "action_save_node_snippet", lambda cfg, scope, text: {"scope": scope, "text": text}):
            self.assertEqual(json.loads(post("/api/nodes/peer_remove", {"node": " 55 "})[0][2]), {"removed": "55"})
            self.assertEqual(json.loads(post("/api/nodes/save_snippet", {"scope": " a ", "text": " b "})[0][2]), {"scope": "a", "text": " b "})

    def test_router_config_defaults(self):
        got = {}
        with mock.patch.object(h44, "save_router_config", lambda cfg, *a: got.setdefault("a", a) and {}):
            post("/api/router/config", {})
        self.assertEqual(got["a"], ("none", "", "", "", "60"))

    def test_repair_and_guard_take_only_a_dict(self):
        got = []
        with mock.patch.object(h44, "_dispatch_repair_action", lambda p: got.append(p) or {}), \
                mock.patch.object(h44, "_dispatch_guard_action", lambda p: got.append(p) or {}):
            post("/api/repair/action", ["not", "a", "dict"])
            post("/api/guard/action", {"x": 1})
        self.assertEqual(got, [{}, {"x": 1}])

    def test_the_lookup_without_a_body_does_not_read_one(self):
        h = object.__new__(h44.Handler)
        h.path = "/api/update/lookup_installed"
        h.headers = email.message.Message()
        h.client_address = ("1.1.1.1", 1)
        sent = []
        h._send = lambda status, ctype, data, extra_headers=None: sent.append((status, ctype, data))
        h._require_auth = lambda: True
        h._check_csrf = lambda: True
        h._read_json_body = lambda: (_ for _ in ()).throw(AssertionError("must not read a body"))
        with mock.patch.object(h44, "action_update_lookup_installed", lambda: {"ok": 1}):
            h.do_POST()
        self.assertEqual(json.loads(sent[0][2]), {"ok": 1})

    def test_the_policy_lookup_uses_the_package(self):
        with mock.patch.object(h44, "action_update_lookup_policy", lambda pkg: {"pkg": pkg}):
            self.assertEqual(json.loads(post("/api/update/lookup_policy", {"pkg": "firewalld"})[0][2]), {"pkg": "firewalld"})

    def test_every_dispatch_route_reaches_its_function(self):
        names = {"/api/pi_install/action": "_dispatch_pi_install_action", "/api/router_install/action": "_dispatch_router_install_action",
                 "/api/system_opt/action": "_dispatch_system_opt_action", "/api/asl3/action": "_dispatch_asl3_action",
                 "/api/dvswitch/action": "_dispatch_dvswitch_action", "/api/svxlink/action": "_dispatch_svxlink_action",
                 "/api/m17/action": "_dispatch_m17_action", "/api/amp/action": "_dispatch_amp_action", "/api/cr/action": "_dispatch_cr_action",
                 "/api/cf/action": "_dispatch_cf_action", "/api/update/action": "_dispatch_update_action", "/api/quiet/action": "_dispatch_quiet_action"}
        for path, name in names.items():
            with mock.patch.object(h44, name, lambda p, name=name: {"via": name}), \
                    mock.patch.object(h44, "_dispatch_guarded", lambda fn, p: fn(p)):
                self.assertEqual(json.loads(post(path, {})[0][2]), {"via": name}, path)


if __name__ == "__main__":
    unittest.main()

import configparser
import email.message
import glob
import gzip
import importlib.util
import re
import sys
import unittest
from unittest import mock

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_pagegz_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_pagegz_under_test"] = h44
spec.loader.exec_module(h44)


class Base(unittest.TestCase):
    def setUp(self):
        self.cfg = configparser.ConfigParser()
        p = mock.patch.object(h44, "_cfg", self.cfg, create=True)
        p.start()
        self.addCleanup(p.stop)


class Negotiation(unittest.TestCase):
    def test_accepts_gzip(self):
        for yes in ("gzip", "gzip, deflate, br", "deflate, gzip;q=0.5", "GZIP", "x-gzip"):
            self.assertTrue(h44._accepts_gzip(yes), yes)
        for no in ("", "identity", "gzip;q=0", "gzip; q=0.0", "br, deflate", "gzipx"):
            self.assertFalse(h44._accepts_gzip(no), no)

    def test_etag_matching(self):
        self.assertTrue(h44._etag_matches('"a"', '"a"'))
        self.assertTrue(h44._etag_matches('W/"a"', '"a"'))
        self.assertTrue(h44._etag_matches('"b", "a"', '"a"'))
        self.assertTrue(h44._etag_matches("*", '"a"'))
        self.assertFalse(h44._etag_matches('"b"', '"a"'))


class Response(Base):
    def test_identity_is_the_plain_page(self):
        status, headers, body = h44._index_response("", "")
        self.assertEqual(status, 200)
        self.assertNotIn("Content-Encoding", headers)
        self.assertEqual(headers["Vary"], "Accept-Encoding")
        self.assertEqual(headers["Cache-Control"], "no-cache")
        self.assertTrue(body.startswith(b"<!DOCTYPE html>"))
        self.assertEqual(body, h44._route_index({})[2])

    def test_gzip_is_smaller_and_decodes_to_the_same_page(self):
        _s, _h, raw = h44._index_response("", "")
        status, headers, body = h44._index_response("gzip, deflate", "")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Encoding"], "gzip")
        self.assertLess(len(body), len(raw) // 3)
        self.assertEqual(gzip.decompress(body), raw)

    def test_gzip_is_built_once_per_page(self):
        h44._PAGE_GZ.update(tag="", data=b"")
        with mock.patch.object(h44.gzip, "compress", wraps=h44.gzip.compress) as comp:
            a = h44._index_response("gzip", "")[2]
            b = h44._index_response("gzip", "")[2]
        self.assertEqual(comp.call_count, 1)
        self.assertEqual(a, b)

    def test_a_matching_etag_is_a_304_with_no_body(self):
        tag = h44._index_response("", "")[1]["ETag"]
        status, headers, body = h44._index_response("gzip", tag)
        self.assertEqual((status, body), (304, b""))
        self.assertEqual(headers["ETag"], tag)

    def test_the_etag_is_the_same_for_both_encodings_and_changes_with_the_page(self):
        t1 = h44._index_response("", "")[1]["ETag"]
        self.assertEqual(h44._index_response("gzip", "")[1]["ETag"], t1)
        self.cfg.add_section("identity")
        self.cfg.set("identity", "callsign", "KD8PGK")
        t2 = h44._index_response("", "")[1]["ETag"]
        self.assertNotEqual(t1, t2)
        self.assertEqual(h44._index_response("", t1)[0], 200)
        self.assertEqual(h44._index_response("", t2)[0], 304)


class Handler(Base):
    def go(self, path="/", **headers):
        h = object.__new__(h44.Handler)
        h.path = path
        h.headers = email.message.Message()
        for k, v in headers.items():
            h.headers[k.replace("_", "-")] = v
        sent = []
        h._send = lambda status, ctype, body, extra_headers=None: sent.append((status, ctype, body, extra_headers))
        h._require_auth = lambda: True
        h.do_GET()
        return sent[0]

    def test_the_page_routes_use_the_negotiation(self):
        for path in ("/", "/index.html"):
            status, ctype, body, extra = self.go(path, Accept_Encoding="gzip")
            self.assertEqual((status, ctype), (200, "text/html; charset=utf-8"))
            self.assertEqual(extra["Content-Encoding"], "gzip")
            self.assertTrue(gzip.decompress(body).startswith(b"<!DOCTYPE html>"))
        status, _c, body, extra = self.go("/")
        self.assertNotIn("Content-Encoding", extra)
        self.assertTrue(body.startswith(b"<!DOCTYPE html>"))
        status, _c, body, _e = self.go("/", If_None_Match=extra["ETag"])
        self.assertEqual((status, body), (304, b""))

    def test_other_routes_are_not_compressed(self):
        status, ctype, body, extra = self.go("/api/version", Accept_Encoding="gzip")
        self.assertEqual(status, 200)
        self.assertIsNone(extra)
        self.assertIn(b"version", body)


if __name__ == "__main__":
    unittest.main()

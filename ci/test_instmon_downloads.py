import glob
import gzip
import importlib.util
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = tempfile.mkdtemp(prefix="instmon_dl_")
for key, sub in (("INSTMON_CONFIG_DIR", "config"), ("INSTMON_LIBRARY_DIR", "library"), ("INSTMON_SUITELOG", "run/suitelog.jsonl"),
                 ("INSTMON_SUITELOG_FLAG", "run/suitelog.on")):
    os.environ[key] = os.path.join(WORK, sub)
os.environ["INSTMON_RECORDER_STATUS_URL"] = "http://127.0.0.1:9/x"


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("instmon_dl_under_test", newest("instmon_v[0-9]*.py"))
im = importlib.util.module_from_spec(spec)
sys.modules["instmon_dl_under_test"] = im
spec.loader.exec_module(im)

URL = "https://raw.githubusercontent.com/kd8pgk/ASL-DVS/main/tool.py"


class Resp:
    def __init__(self, body, code=200, headers=None, drop_after=None):
        self.body = body
        self.code = code
        self.headers = headers or {}
        self.pos = 0
        self.drop_after = drop_after

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return URL

    def getcode(self):
        return self.code

    def read(self, n=-1):
        if self.drop_after is not None and self.pos >= self.drop_after:
            return b""
        end = len(self.body) if n < 0 else self.pos + n
        if self.drop_after is not None:
            end = min(end, self.drop_after)
        out = self.body[self.pos:end]
        self.pos += len(out)
        return out


class Net:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, req, timeout=None, context=None):
        self.requests.append({k.lower(): v for k, v in req.header_items()})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def fetch(net, limit=10 * 1024 * 1024, head=None):
    with mock.patch.object(im.urllib.request, "urlopen", net), mock.patch.object(im.time, "sleep", lambda s: None):
        return im._gh_fetch_https(URL, limit, head=head)


SOURCE = ("#!/usr/bin/env python3\nVERSION = \"1.2.3\"\n" + "x = 1\n" * 4000).encode()


class Gzip(unittest.TestCase):
    def test_asks_for_gzip_and_decodes(self):
        packed = gzip.compress(SOURCE)
        net = Net(Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}))
        self.assertEqual(fetch(net), SOURCE)
        self.assertEqual(net.requests[0]["accept-encoding"], "gzip")
        self.assertLess(len(packed), len(SOURCE) // 5)

    def test_plain_reply_still_works(self):
        net = Net(Resp(SOURCE, headers={"Content-Length": str(len(SOURCE))}))
        self.assertEqual(fetch(net), SOURCE)

    def test_unknown_encoding_refused(self):
        net = Net(Resp(b"abc", headers={"Content-Encoding": "br"}))
        with self.assertRaises(im.GhRejected) as cm:
            fetch(net)
        self.assertIn("unsupported encoding", str(cm.exception))

    def test_decompressed_size_is_limited(self):
        packed = gzip.compress(b"\0" * 5_000_000)
        net = Net(Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}))
        with self.assertRaises(im.GhRejected) as cm:
            fetch(net, limit=1_000_000)
        self.assertIn("larger than", str(cm.exception))

    def test_damaged_gzip_refused(self):
        packed = bytearray(gzip.compress(SOURCE))
        packed[len(packed) // 2] ^= 0xFF
        net = Net(Resp(bytes(packed), headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}))
        with self.assertRaises(im.GhRejected):
            fetch(net)

    def test_truncated_gzip_refused(self):
        packed = gzip.compress(SOURCE)[:-40]
        net = Net(Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}))
        with self.assertRaises(im.GhRejected):
            fetch(net)


class Resume(unittest.TestCase):
    def test_resumes_inside_the_compressed_stream(self):
        packed = gzip.compress(SOURCE)
        cut = len(packed) // 2
        net = Net(Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}, drop_after=cut),
                  Resp(packed[cut:], code=206, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed) - cut)}))
        self.assertEqual(fetch(net), SOURCE)
        self.assertEqual(net.requests[1]["range"], f"bytes={cut}-")

    def test_resume_that_returns_garbage_starts_over(self):
        packed = gzip.compress(SOURCE)
        cut = len(packed) // 2
        bad = b"\x00" * (len(packed) - cut)
        net = Net(Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}, drop_after=cut),
                  Resp(bad, code=206, headers={"Content-Encoding": "gzip", "Content-Length": str(len(bad))}),
                  Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}))
        self.assertEqual(fetch(net), SOURCE)
        self.assertNotIn("range", net.requests[2])

    def test_encoding_change_on_resume_starts_over(self):
        packed = gzip.compress(SOURCE)
        cut = len(packed) // 2
        net = Net(Resp(packed, headers={"Content-Encoding": "gzip", "Content-Length": str(len(packed))}, drop_after=cut),
                  Resp(SOURCE[cut:], code=206, headers={"Content-Length": str(len(SOURCE) - cut)}),
                  Resp(SOURCE, headers={"Content-Length": str(len(SOURCE))}))
        self.assertEqual(fetch(net), SOURCE)


class Head(unittest.TestCase):
    def test_header_peek_asks_for_a_range_without_gzip(self):
        net = Net(Resp(SOURCE[:16384], code=206, headers={"Content-Length": "16384"}))
        data = fetch(net, head=16384)
        self.assertEqual(data, SOURCE[:16384])
        self.assertEqual(net.requests[0]["range"], "bytes=0-16383")
        self.assertEqual(net.requests[0]["accept-encoding"], "identity")

    def test_peek_stops_early_when_range_is_ignored(self):
        big = SOURCE * 40
        resp = Resp(big, headers={"Content-Length": str(len(big))})
        data = fetch(Net(resp), head=16384)
        self.assertEqual(data, big[:16384])
        self.assertLess(resp.pos, 40000)

    def test_version_read_uses_the_peek(self):
        seen = {}

        def impl(url, limit, head=None):
            seen["head"] = head
            return SOURCE[:head] if head else SOURCE

        cand = {"name": "tool.py", "blob": im._git_blob_id(SOURCE), "category": "termon", "glob": "termon_v*.py"}
        with mock.patch.object(im, "_gh_fetch_impl", impl), mock.patch.dict(im._gh_version_cache, clear=True):
            self.assertEqual(im._gh_version_of(cand, []), "1.2.3")
        self.assertEqual(seen["head"], im.GITHUB_HEAD_BYTES)

    def test_every_tool_names_its_version_in_the_first_16k(self):
        for path in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "*.sh")):
            with open(path, "rb") as fh:
                raw = fh.read()
            whole = im._scan_header_text(raw.decode("utf-8"))[0]
            part = im._scan_header_text(raw[:im.GITHUB_HEAD_BYTES].decode("utf-8", "ignore"))[0]
            self.assertEqual(whole, part, os.path.basename(path))


class Slow(unittest.TestCase):
    def setUp(self):
        self.addCleanup(im._gh_rate.update, bps=im._gh_rate["bps"])
        im._gh_rate["bps"] = None
        os.environ.pop("INSTMON_SLOW_LINK", None)
        self.addCleanup(os.environ.pop, "INSTMON_SLOW_LINK", None)

    def test_unknown_rate_is_not_slow(self):
        self.assertFalse(im.gh_link_slow())

    def test_measured_rate_decides(self):
        im._gh_rate_note(10_000, 5.0)
        self.assertTrue(im.gh_link_slow())
        im._gh_rate["bps"] = None
        im._gh_rate_note(1_000_000, 2.0)
        self.assertFalse(im.gh_link_slow())

    def test_tiny_transfers_are_not_counted(self):
        im._gh_rate_note(100, 5.0)
        self.assertIsNone(im._gh_rate["bps"])

    def test_environment_forces_the_answer(self):
        os.environ["INSTMON_SLOW_LINK"] = "on"
        self.assertTrue(im.gh_link_slow())
        os.environ["INSTMON_SLOW_LINK"] = "off"
        im._gh_rate["bps"] = 10.0
        self.assertFalse(im.gh_link_slow())

    def test_a_crawling_download_gives_up(self):
        clock = {"t": 1000.0}

        class Crawl(Resp):
            def read(self, n=-1):
                clock["t"] += 10.0
                out = b"x" * 100
                self.pos += 100
                return out if self.pos < 10_000_000 else b""

        net = Net(Crawl(b"", headers={"Content-Length": "9000000"}))
        with mock.patch.object(im.time, "monotonic", lambda: clock["t"]), \
                mock.patch.object(im, "GITHUB_MAX_DOWNLOAD_SLOW_SEC", 10 ** 9):
            with self.assertRaises(im.GhRejected) as cm:
                fetch(net)
        self.assertIn("too slow", str(cm.exception))

    def test_a_slow_but_steady_download_is_allowed_past_the_old_cap(self):
        data = b"y" * 20000
        clock = {"t": 0.0}

        class Steady(Resp):
            def read(self, n=-1):
                clock["t"] += 20.0
                return super().read(min(n, 2000) if n > 0 else 2000)

        net = Net(Steady(data, headers={"Content-Length": str(len(data))}))
        with mock.patch.object(im.time, "monotonic", lambda: clock["t"]), \
                mock.patch.object(im, "GITHUB_MAX_DOWNLOAD_SEC", 60), \
                mock.patch.object(im, "GITHUB_MIN_BPS", 50):
            self.assertEqual(fetch(net), data)


class MissingTools(unittest.TestCase):
    def test_slow_link_limits_missing_tool_downloads(self):
        os.environ["INSTMON_SLOW_LINK"] = "on"
        self.addCleanup(os.environ.pop, "INSTMON_SLOW_LINK", None)
        self.assertEqual(im.SLOW_FETCH_MISSING_MAX, 2)
        events = []
        with mock.patch.object(im, "log_event", lambda m, level="info": events.append(m)), \
                mock.patch.object(im, "recorder_busy", lambda: None), \
                mock.patch.object(im, "FETCH_MISSING_MAX", 8):
            im._gh_fetch_missing([])
        self.assertTrue(any("slow" in e and "at most 2" in e for e in events))

    def test_manual_first_fetch_stops_on_a_slow_link(self):
        os.environ["INSTMON_SLOW_LINK"] = "on"
        self.addCleanup(os.environ.pop, "INSTMON_SLOW_LINK", None)
        listing = [{"name": "a.pdf", "blob": "0" * 40, "size": 10}]
        said = []
        with mock.patch.object(im, "_gh_fetch_impl", lambda url, limit, head=None: b"[]"), \
                mock.patch.object(im, "_docs_parse_listing", lambda raw: listing), \
                mock.patch.object(im, "DOCS_DIR", os.path.join(WORK, "docs")), \
                mock.patch.object(im, "_docs_mark_fetched", lambda: None), \
                mock.patch.object(im, "_docs_mark_deleted", lambda remove=None: None):
            got, same, failed = im._docs_fetch(lambda m, level: said.append(m), auto=True)
        self.assertEqual((got, failed), ([], []))
        self.assertTrue(any("slow" in m for m in said))


if __name__ == "__main__":
    unittest.main()

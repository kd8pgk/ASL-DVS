#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = open(sorted(glob.glob(os.path.join(ROOT, "nodetalker_v[0-9]*.py")))[-1], encoding="utf-8").read()
NODE = shutil.which("node")


def between(a, b):
    i = SRC.index(a)
    return SRC[i:SRC.index(b, i)]


PAGE_JS = "\n".join([
    between("function sincKernels(", "function makeResampler("),
    between("function makeUpsampler(", "const AudioCtx ="),
    "function peakDb(a) { return a > 0 ? 20 * Math.log10(a) : -120; }",
    between("let jitAdapt = true", "const CLIP_DB = -0.5;"),
])

PRELUDE = """
let jitterSec = 0.25, ups = null, pend = new Float32Array(1600), pendN = 0, peakLocal = 0, nextT = 0, draining = false;
let playing = true, listenAt = -1e9, chk = null, talking = true, sessNode = null, busNode = {}, ctx = null;
const play = {smooth: false}, RX_ACTIVE_DB = -50;
const counts = {under: [], drops: 0, seen: 0};
let wallMs = 0;
const performance = {now: () => wallMs};
function $() { return {style: {}}; }
function dbPct() { return 0; }
function rxSeen() { counts.seen++; }
function rxhCount(v) { counts.under.push(v); }
function chkDrop() {}
function makeCtx() {
  const c = {currentTime: 0, sampleRate: 8000, sources: [], gains: [],
    createBuffer(ch, n, rate) { return {duration: n / rate, length: n, data: null, copyToChannel(d) { this.data = Float32Array.from(d); }}; },
    createBufferSource() { const s = {buffer: null, started: null, stopped: null, connect() {}, start(t) { this.started = t; }, stop(t) { this.stopped = t; }}; c.sources.push(s); return s; },
    createGain() { const g = {connect() {}, gain: {ramps: [], cancelScheduledValues() {}, setTargetAtTime(v, t, k) { this.ramps.push([v, t, k]); }}}; c.gains.push(g); return g; }};
  return c;
}
function feed(vals) { for (const v of vals) { pend[pendN++] = v; const a = Math.abs(v); if (a > peakLocal) peakLocal = a; } flush(); }
function tone(f, amp, n, ph) { const o = []; for (let i = 0; i < n; i++) o.push(amp * Math.sin(2 * Math.PI * f * (i + ph) / 8000)); return o; }
function rng(seed) { let s = seed; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
"""


def run(body):
    if not NODE:
        raise unittest.SkipTest("node is not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(PRELUDE + "\n" + PAGE_JS + "\n" + body)
        path = fh.name
    try:
        r = subprocess.run([NODE, path], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


class Adapt(unittest.TestCase):
    def test_a_steady_link_settles_at_the_floor_and_a_jittery_one_at_the_cap(self):
        out = run("""
        jitterSec = 0.5;
        for (let i = 0; i < 60; i++) jitNote(i * 100);
        const steady = leadSec();
        jitReset();
        const r = rng(7); let t = 0;
        for (let i = 0; i < 60; i++) { t += 40 + r() * 220; jitNote(t); }
        const jittery = leadSec();
        jitReset();
        jitAdapt = false;
        for (let i = 0; i < 60; i++) jitNote(i * 100);
        console.log(JSON.stringify({steady, jittery, fixed: leadSec()}));
        """)
        self.assertAlmostEqual(out["steady"], 0.12, places=3)
        self.assertGreater(out["jittery"], 0.2)
        self.assertLessEqual(out["jittery"], 0.5)
        self.assertEqual(out["fixed"], 0.5)

    def test_it_starts_at_the_cap_until_it_has_seen_enough_chunks(self):
        out = run("jitterSec = 0.4; for (let i = 0; i < 10; i++) jitNote(i * 100); console.log(JSON.stringify({v: leadSec()}));")
        self.assertEqual(out["v"], 0.4)

    def test_silence_shrinks_the_buffer_without_a_gap(self):
        out = run("""
        ctx = makeCtx(); jitterSec = 0.5;
        const quiet = new Array(800).fill(0);
        let wall = 0;
        const leads = [];
        for (let i = 0; i < 120; i++) {
          ctx.currentTime = wall / 1000; wallMs = wall;
          feed(quiet);
          leads.push(nextT - ctx.currentTime);
          wall += 100;
        }
        console.log(JSON.stringify({first: leads[0], last: leads[119], under: counts.under.length}));
        """)
        self.assertAlmostEqual(out["first"], 0.6, places=2)
        self.assertLess(out["last"], 0.35)
        self.assertEqual(out["under"], 0)

    def test_speech_is_never_dropped_to_shrink_the_buffer(self):
        out = run("""
        ctx = makeCtx(); jitterSec = 0.5; plcOn = false;
        for (let i = 0; i < 40; i++) { ctx.currentTime = i * 0.1; wallMs = i * 100; feed(new Array(800).fill(0)); }
        const before = ctx.sources.length;
        for (let i = 40; i < 60; i++) { ctx.currentTime = i * 0.1; wallMs = i * 100; feed(tone(150, 0.3, 800, 0)); }
        console.log(JSON.stringify({added: ctx.sources.length - before}));
        """)
        self.assertEqual(out["added"], 20)

    def test_a_grown_estimate_pads_the_buffer_in_silence(self):
        out = run("""
        ctx = makeCtx(); jitterSec = 0.5;
        for (let i = 0; i < 40; i++) { ctx.currentTime = i * 0.1; wallMs = i * 100; feed(new Array(800).fill(0)); }
        const settled = nextT - ctx.currentTime;
        const r = rng(3); let wall = 4000;
        for (let i = 0; i < 60; i++) { wall += 40 + r() * 260; ctx.currentTime = wall / 1000; wallMs = wall; feed(new Array(800).fill(0)); }
        console.log(JSON.stringify({settled, grown: nextT - ctx.currentTime, lead: leadSec()}));
        """)
        self.assertLess(out["settled"], 0.35)
        self.assertGreater(out["lead"], 0.25)


class Plc(unittest.TestCase):
    def test_it_continues_a_voiced_sound_and_fades_out(self):
        out = run("""
        const h = new Float32Array(480);
        const wave = (i) => 0.3 * Math.sin(2 * Math.PI * 130 * i / 8000) + 0.12 * Math.sin(2 * Math.PI * 260 * i / 8000 + 0.7);
        for (let i = 0; i < 480; i++) h[i] = wave(i);
        const y = plcConceal(h, 480);
        let c = 0, a = 0, b = 0;
        for (let i = 0; i < 60; i++) { c += y[i] * wave(480 + i); a += y[i] * y[i]; b += wave(480 + i) * wave(480 + i); }
        let tail = 0; for (let i = 440; i < 480; i++) tail = Math.max(tail, Math.abs(y[i]));
        console.log(JSON.stringify({corr: c / Math.sqrt(a * b), tail, len: y.length, first: y[0], prev: h[479]}));
        """)
        self.assertGreater(out["corr"], 0.95)
        self.assertLess(out["tail"], 0.05)
        self.assertEqual(out["len"], 480)
        self.assertLess(abs(out["first"] - out["prev"]), 0.1)

    def test_it_makes_nothing_from_noise_or_silence(self):
        out = run("""
        const r = rng(11), h = new Float32Array(480), z = new Float32Array(480);
        for (let i = 0; i < 480; i++) h[i] = (r() - 0.5) * 0.4;
        console.log(JSON.stringify({noise: plcConceal(h, 480), silence: plcConceal(z, 480), short: plcConceal(new Float32Array(50), 480)}));
        """)
        self.assertEqual(out, {"noise": None, "silence": None, "short": None})

    def test_an_on_time_chunk_cancels_the_tail(self):
        out = run("""
        ctx = makeCtx(); jitterSec = 0.25; jitAdapt = false;
        ctx.currentTime = 0; feed(tone(150, 0.3, 800, 0));
        const tail = plcTail, startAt = tail.start;
        ctx.currentTime = 0.1; feed(tone(150, 0.3, 800, 800));
        console.log(JSON.stringify({stopped: tail.src.stopped, startAt, next: plcTail ? plcTail.start : null, ramps: tail.gain.gain.ramps.length}));
        """)
        self.assertEqual(out["stopped"], out["startAt"])
        self.assertEqual(out["ramps"], 0)

    def test_a_chunk_that_is_late_inside_the_tail_resumes_at_once(self):
        out = run("""
        ctx = makeCtx(); jitterSec = 0.25; jitAdapt = false;
        ctx.currentTime = 0; feed(tone(150, 0.3, 800, 0));
        const tail = plcTail, endOfChunk = tail.start;
        ctx.currentTime = endOfChunk + 0.04;
        feed(tone(150, 0.3, 800, 800));
        const last = ctx.sources[ctx.sources.length - 2];
        console.log(JSON.stringify({resumeAt: last.started - ctx.currentTime, ramps: tail.gain.gain.ramps.length, under: counts.under.length, tailStarted: tail.src.started === endOfChunk}));
        """)
        self.assertAlmostEqual(out["resumeAt"], 0.012, places=3)
        self.assertEqual(out["ramps"], 1)
        self.assertEqual(out["under"], 1)
        self.assertTrue(out["tailStarted"])

    def test_a_chunk_later_than_the_tail_reprimes_the_buffer(self):
        out = run("""
        ctx = makeCtx(); jitterSec = 0.25; jitAdapt = false;
        ctx.currentTime = 0; feed(tone(150, 0.3, 800, 0));
        const endOfChunk = plcTail.start;
        ctx.currentTime = endOfChunk + 0.3;
        feed(tone(150, 0.3, 800, 800));
        const last = ctx.sources[ctx.sources.length - 2];
        console.log(JSON.stringify({lead: last.started - ctx.currentTime}));
        """)
        self.assertAlmostEqual(out["lead"], 0.25, places=3)

    def test_it_can_be_turned_off(self):
        out = run("ctx = makeCtx(); plcOn = false; ctx.currentTime = 0; feed(tone(150, 0.3, 800, 0)); console.log(JSON.stringify({tail: plcTail}));")
        self.assertIsNone(out["tail"])

    def test_silence_makes_no_tail(self):
        out = run("ctx = makeCtx(); ctx.currentTime = 0; feed(new Array(800).fill(0)); console.log(JSON.stringify({tail: plcTail}));")
        self.assertIsNone(out["tail"])


if __name__ == "__main__":
    sys.exit(0 if unittest.main(exit=False).result.wasSuccessful() else 1)

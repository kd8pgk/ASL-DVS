import configparser
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOLDEN = os.path.join(ROOT, "ci", "golden", "h44_stepcards.json")


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_stepcards_under_test", os.environ.get("H44_UNDER_TEST") or newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_stepcards_under_test"] = h44
import builtins
import io

_real_open = builtins.open


def _open(file, *a, **k):
    if file == "/etc/passwd":
        return io.StringIO("pi:x:1000:1000:pi:/home/pi:/bin/bash\n")
    return _real_open(file, *a, **k)


builtins.open = _open
try:
    spec.loader.exec_module(h44)
finally:
    builtins.open = _real_open
h44._cfg = configparser.ConfigParser()

TABS = [
    ("asl3", "_JS_ASL3", "asl3RenderStepList", "_ASL3_SCRIPTS"),
    ("dv", "_JS_DVSWITCH", "dvRenderStepList", "_DVSWITCH_SCRIPTS"),
    ("svx", "_JS_SVXLINK", "svxRenderStepList", "_SVXLINK_SCRIPTS"),
    ("m17", "_JS_M17", "m17RenderStepList", "_M17_SCRIPTS"),
    ("amp", "_JS_AMP", "ampRenderStepList", "_AMP_SCRIPTS"),
    ("cr", "_JS_AMP", "crRenderStepList", "_CR_SCRIPTS"),
    ("cf", "_JS_CF", "cfRenderStepList", "_CF_SCRIPTS"),
]

STUBS = r"""
var window = globalThis;
var __noop = function() { return __stub; };
var __stub = new Proxy(function() {}, {get: function() { return __stub; }, apply: function() { return __stub; }, set: function() { return true; }});
var document = {getElementById: function() { return null; }, querySelectorAll: function() { return []; }, createElement: function() { return __stub; },
                addEventListener: function() {}, body: __stub, documentElement: __stub};
var navigator = {clipboard: null};
var location = {hostname: '127.0.0.1', protocol: 'http:', host: '127.0.0.1:9997'};
var setInterval = function() { return 0; };
var setTimeout = function() { return 0; };
function fetch() { return {then: function() { return {then: function() { return {catch: function() {}}; }, catch: function() {}}; }, catch: function() {}}; }
"""

DRIVER = r"""
function __states(scripts, mode, distro) {
  var steps = ((scripts || {})[mode] || {})[distro] || [];
  var st = {};
  steps.forEach(function(s, i) {
    var key = mode + '_' + distro + '_' + s.id;
    var k = i % 6;
    if (k === 1) { st[key] = {status: 'ok', output: 'done <b>&</b> "fine"'}; }
    else if (k === 2) { st[key] = {status: 'fail', output: 'bad "quote" <x>'}; }
    else if (k === 3) { st[key] = {status: 'attempted'}; }
    else if (k === 4) { st[key] = {output: 'partial output'}; }
  });
  return st;
}
var __out = [];
Object.keys(CAT).forEach(function(mode) {
  Object.keys(CAT[mode]).forEach(function(distro) {
    window['_' + PFX + 'Scripts'] = CAT;
    window['_' + PFX + 'State'] = __states(CAT, mode, distro);
    __out.push({mode: mode, distro: distro, html: FN(mode, distro)});
    window['_' + PFX + 'State'] = {};
    __out.push({mode: mode, distro: distro + ' (fresh)', html: FN(mode, distro)});
  });
});
var SYN = {install: {syn: [
  {id: 's1', num: 1, title: 'T1 <b>', cmd: 'echo "a" && b', note: 'note <x> & "y"'},
  {id: 's2', num: 2, title: 'T2', manual: true, cmd: 'by hand "x"', note: 'n'},
  {id: 's3', num: 3, title: 'T3', config_save: true, cmd: 'save', note: 'n3'},
  {id: 's4', num: 4, title: 'T4', fields: [{id: 'f1', label: 'L1 <i>', type: 'text', default: 'd"1'}, {id: 'f2', label: 'L2', type: 'password'}], cmd: 'x'},
  {id: 's5', num: 5, title: 'T5', cmd: 'plain'},
  {id: 's8', num: 8, title: 'T8', pi_action: true, button: 'Do <it>', cmd: 'pi'},
  {id: 's9', num: 9, title: 'T9', pi_action: true, cmd: 'pi2'},
  {id: 's6', num: 6, title: 'T6', manual: true, manual_block: true, cmd: 'blk <t>', note: 'nb'},
  {id: 's7', num: 7, title: 'T7', fields: [{id: 'g1', label: 'G', type: 'select', options: [['a', 'A'], ['b', 'B']], default: 'a'}, {id: 'g2', label: 'H', type: 'text', show_if: 'g1=a'}], cmd: 'y'}
], empty: []}};
window['_' + PFX + 'Scripts'] = SYN;
window['_' + PFX + 'State'] = {install_syn_s1: {status: 'ok', output: 'o'}, install_syn_s4: {status: 'fail', output: 'bad'}, install_syn_s5: {status: 'attempted'}};
__out.push({mode: 'install', distro: 'syn', html: FN('install', 'syn')});
__out.push({mode: 'install', distro: 'empty', html: FN('install', 'empty')});
console.log(JSON.stringify(__out));
"""


def render_tab(tab):
    pfx, block, fn, cat = tab
    parts = [STUBS, h44._JS_TABS]
    if block == "_JS_AMP":
        parts.append(h44._JS_AMP)
    else:
        parts.append(getattr(h44, block))
    cat_json = json.dumps(getattr(h44, cat))
    parts.append(f"var CAT = {cat_json}; var PFX = '{pfx}'; var FN = {fn};\n" + DRIVER)
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(parts))
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise AssertionError(f"{pfx}: " + r.stderr[:1000])
    return json.loads(r.stdout)


def collect():
    got = {}
    for tab in TABS:
        for item in render_tab(tab):
            got[f"{tab[0]}:{item['mode']}:{item['distro']}"] = item["html"]
    return got


def digest(html):
    return {"sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(), "length": len(html)}


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Golden(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.got = collect()
        if os.environ.get("H44_WRITE_GOLDEN") == "1":
            with open(GOLDEN, "w", encoding="utf-8") as f:
                json.dump({k: digest(v) for k, v in sorted(cls.got.items())}, f, indent=1)
                f.write("\n")
            if os.environ.get("H44_DUMP_DIR"):
                os.makedirs(os.environ["H44_DUMP_DIR"], exist_ok=True)
                for k, v in cls.got.items():
                    with open(os.path.join(os.environ["H44_DUMP_DIR"], k.replace(":", "_").replace(" ", "_") + ".html"), "w", encoding="utf-8") as f:
                        f.write(v)
        with open(GOLDEN, encoding="utf-8") as f:
            cls.want = json.load(f)

    def test_the_same_lists_are_recorded(self):
        self.assertEqual(sorted(self.got), sorted(self.want))

    def test_every_step_list_is_byte_for_byte_what_was_recorded(self):
        bad = [k for k in sorted(self.want) if digest(self.got[k]) != self.want[k]]
        self.assertEqual(bad, [])

    def test_the_lists_hold_real_cards(self):
        for key, html in self.got.items():
            if key.endswith(":install:empty"):
                self.assertIn("(no steps defined)", html, key)
            else:
                self.assertIn('class="step-card"', html, key)
            self.assertNotIn("undefined", html, key)
            self.assertNotIn("[object", html, key)

    def test_state_shows_in_the_cards(self):
        html = self.got["asl3:install:bookworm"]
        self.assertIn("step-pill done", html)
        self.assertIn("step-pill danger", html)
        self.assertIn("Running\\u2026".replace("\\u2026", "…"), html)
        self.assertIn("done &lt;b&gt;&amp;&lt;/b&gt; &quot;fine&quot;", html)
        fresh = self.got["asl3:install:bookworm (fresh)"]
        self.assertNotIn("step-pill done", fresh)
        self.assertIn("(not run yet)", fresh)


if __name__ == "__main__":
    unittest.main()

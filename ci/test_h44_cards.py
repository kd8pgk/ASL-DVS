import configparser
import glob
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


def newest(pattern):
    def key(f):
        return [int(x) for x in re.findall(r"\d+", os.path.basename(f))[:3]]
    return sorted(glob.glob(os.path.join(ROOT, pattern)), key=key)[-1]


spec = importlib.util.spec_from_file_location("h44_cards_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_cards_under_test"] = h44
spec.loader.exec_module(h44)
h44._cfg = configparser.ConfigParser()

PRELUDE = r"""
function cfgEsc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
function clickTab(id) {}
var __els = {};
function __el(id) {
  if (!__els[id]) {
    var e = {id: id, style: {}, className: '', textContent: '', _html: ''};
    Object.defineProperty(e, 'innerHTML', {configurable: true, get: function() { return this._html; }, set: function(v) {
      this._html = v;
      var re = /id="([^"]+)"/g, m;
      while ((m = re.exec(v))) { __el(m[1]); }
    }});
    __els[id] = e;
  }
  return __els[id];
}
var document = {getElementById: function(id) { return __els[id] || null; }};
function __box(id) { return __el(id); }
"""


def stages(profile="travel", mode="half", states=None):
    states = states or {}
    out = []
    for i, (sid, label) in enumerate(h44._bld_stage_defs(mode, profile)):
        out.append({"id": sid, "label": label, "state": states.get(sid, "todo"), "detail": f"detail of {sid}",
                    **({"run": {"preview": sid in h44._BLD_PREVIEWABLE, "long": sid in h44._BLD_LONG}} if sid in h44._BLD_RUNNABLE else {})})
    return out


def run_js(profile, body):
    js = h44._JS_MAGIC if profile == "magic" else h44._JS_BUILD
    fn = "magic" if profile == "magic" else "build"
    script = PRELUDE + js + "\n" + body.replace("FN", fn).replace("PFX", "mbx" if profile == "magic" else "bld")
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.js")
        with open(path, "w", encoding="utf-8") as f:
            f.write(script)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr[:1200])
    return json.loads(r.stdout)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Cards(unittest.TestCase):
    def render(self, profile, mode="half", states=None, before=""):
        data = json.dumps({"stages": stages(profile, mode, states)})
        body = f"""
__box('PFX-cards'); __el('PFX-progress');
var d = {data};
{before}
FNRenderCards(d);
var out = {{order: _PFXOrderVar(), cards: []}};
"""
        return data, body

    def test_one_card_per_stage_after_the_preflight_in_order(self):
        for profile in ("travel", "magic"):
            for mode in ("half", "split", "full", "none"):
                want = [i for i, _ in h44._bld_stage_defs(mode, profile)]
                data = json.dumps({"stages": stages(profile, mode)})
                out = run_js(profile, f"""
__box('PFX-cards'); __el('PFX-progress');
var d = {data};
FNRenderCards(d);
var ids = [], re = /id="PFX-card-([a-z_0-9]+)"/g, m;
while ((m = re.exec(__els['PFX-cards']._html))) {{ ids.push(m[1]); }}
console.log(JSON.stringify({{ids: ids, progress: __els['PFX-progress'].textContent}}));
""")
                self.assertEqual(out["ids"], want[1:], (profile, mode))
                self.assertIn("0 of " + str(len(want)) + " steps done", out["progress"])

    def test_card_numbers_start_at_two_because_the_preflight_is_step_one(self):
        data = json.dumps({"stages": stages("travel", "half")})
        out = run_js("travel", f"""
__box('bld-cards'); __el('bld-progress');
var d = {data};
buildRenderCards(d);
console.log(JSON.stringify({{first: __els['bld-main-tunnel']._html, last: __els['bld-main-reboot']._html}}));
""")
        self.assertIn('<span class="step-num">2.</span>Tunnel steps 1 to 6', out["first"])
        self.assertIn('<span class="step-num">23.</span>Reboot test', out["last"])

    def test_pills_buttons_and_the_next_marker(self):
        states = {"preflight": "done", "tunnel": "done", "asl3": "done", "iax_port": "warn", "dvs": "locked"}
        data = json.dumps({"stages": stages("travel", "half", states)})
        out = run_js("travel", f"""
__box('bld-cards'); __el('bld-progress');
var d = {data};
buildRenderCards(d);
console.log(JSON.stringify({{asl3: __els['bld-main-asl3']._html, iax: __els['bld-main-iax_port']._html, dvs: __els['bld-main-dvs']._html,
  radio: __els['bld-main-radio']._html, border: [__els['bld-card-iax_port'].style.borderColor, __els['bld-card-asl3'].style.borderColor],
  progress: __els['bld-progress'].textContent}}));
""")
        self.assertIn('step-pill done', out["asl3"])
        self.assertIn(">done<", out["asl3"])
        self.assertIn("buildRun('asl3', false, this, true)", out["asl3"])
        self.assertNotIn("Preview", out["asl3"])
        self.assertIn("step-pill attempted_unconfirmed", out["iax"])
        self.assertIn(">check<", out["iax"])
        self.assertIn("buildRun('iax_port', true, this)", out["iax"])
        self.assertIn("step-pill not_started", out["dvs"])
        self.assertIn(">waits<", out["dvs"])
        self.assertIn("<b>Next: </b>detail of dvs", out["dvs"])
        self.assertEqual(out["border"], ["", ""])
        self.assertIn("3 of 23 steps done. Next: DVSwitch.", out["progress"])

    def test_while_the_preflight_is_open_it_is_the_next_step_and_no_card_is_marked(self):
        data = json.dumps({"stages": stages("travel", "half")})
        out = run_js("travel", f"""
__box('bld-cards'); __el('bld-progress');
var d = {data};
buildRenderCards(d);
console.log(JSON.stringify({{tunnel: __els['bld-main-tunnel']._html, border: __els['bld-card-tunnel'].style.borderColor,
  progress: __els['bld-progress'].textContent}}));
""")
        self.assertNotIn("Next:", out["tunnel"])
        self.assertEqual(out["border"], "")
        self.assertIn("Next: Preflight.", out["progress"])

    def test_the_slots_for_the_radio_and_the_svxlink_details_are_in_their_cards(self):
        for profile, pfx in (("travel", "bld"), ("magic", "mbx")):
            data = json.dumps({"stages": stages(profile, "half")})
            fn = "magic" if profile == "magic" else "build"
            out = run_js(profile, f"""
__box('{pfx}-cards'); __el('{pfx}-progress');
var d = {data};
{fn}RenderCards(d);
var html = __els['{pfx}-cards']._html;
console.log(JSON.stringify({{radio: /id="{pfx}-card-radio".*?id="{pfx}-radio"/s.test(html), svx: html.indexOf('id="{pfx}-svx"') !== -1,
  svxIn: /id="{pfx}-card-svx".*?id="{pfx}-svx"/s.test(html)}}));
""")
            self.assertTrue(out["radio"], profile)
            self.assertEqual(out["svx"], profile == "magic")
            self.assertEqual(out["svxIn"], profile == "magic")

    def test_a_refresh_with_nothing_new_changes_no_card(self):
        data = json.dumps({"stages": stages("travel", "half")})
        out = run_js("travel", f"""
__box('bld-cards'); __el('bld-progress');
var d = {data};
buildRenderCards(d);
var shell = __els['bld-cards']._html;
var writes = 0;
['tunnel', 'asl3', 'reboot'].forEach(function(id) {{
  var e = __els['bld-main-' + id];
  var v = e._html;
  Object.defineProperty(e, 'innerHTML', {{get: function() {{ return v; }}, set: function(x) {{ writes += 1; v = x; }}}});
}});
buildRenderCards(d);
d.stages[2].state = 'done';
buildRenderCards(d);
console.log(JSON.stringify({{writes: writes, same: shell === __els['bld-cards']._html}}));
""")
        self.assertEqual(out["writes"], 1)
        self.assertTrue(out["same"])

    def test_a_cards_output_survives_a_refresh_and_a_mode_change(self):
        half = json.dumps({"stages": stages("travel", "half")})
        none = json.dumps({"stages": stages("travel", "none")})
        out = run_js("travel", f"""
__box('bld-cards'); __el('bld-progress');
var d = {half};
buildRenderCards(d);
var o = __els['bld-out-asl3'];
o.className = 'asl3-console shown ok'; o.textContent = 'installed fine'; o.style.display = '';
buildKeepOut('asl3');
buildRenderCards(d);
var same = __els['bld-out-asl3'].textContent;
buildRenderCards({none});
console.log(JSON.stringify({{same: same, after: __els['bld-out-asl3'].textContent, cls: __els['bld-out-asl3'].className,
  shown: __els['bld-out-asl3'].style.display === '', gone: !!__els['bld-card-half']}}));
""")
        self.assertEqual(out["same"], "installed fine")
        self.assertEqual(out["after"], "installed fine")
        self.assertIn("ok", out["cls"])
        self.assertTrue(out["shown"])

    def test_the_old_checklist_is_kept_as_a_collapsed_strip_at_the_end(self):
        html = h44._render_build_panel()
        self.assertIn('<details id="bld-strip"', html)
        self.assertNotIn("<details id=\"bld-strip\" open", html)
        self.assertGreater(html.index('id="bld-strip"'), html.index('id="bld-saves"'))
        self.assertGreater(html.index('id="bld-saves"'), html.index('id="bld-cards"'))
        self.assertGreater(html.index('id="bld-cards"'), html.index('id="bld-form-state"'))
        self.assertIn('id="bld-stages"', html)
        self.assertIn('<span class="step-num">1.</span>Preflight', html)

    def test_the_two_old_cards_are_gone_and_their_slots_live_in_the_step_cards(self):
        html = h44._render_magic_panel()
        self.assertNotIn("Radio and Node Talker</div></div>", html)
        self.assertNotIn('id="mbx-radio"', html)
        self.assertNotIn("@SVXCARD@", html)
        self.assertFalse(hasattr(h44, "_BLD_SVX_CARD"))

    def test_the_poll_writes_into_the_stage_card_and_run_the_rest_into_the_top_console(self):
        js = h44._JS_BUILD
        self.assertIn("key.replace(/^build_[a-z]+_/, '')", js)
        self.assertIn("document.getElementById('bld-out-' + stage) || document.getElementById('bld-run-out')", js)


class Words(unittest.TestCase):
    def test_the_panel_talks_about_cards_and_says_what_is_kept(self):
        html = h44._render_build_panel()
        self.assertIn("A card with a Run button", html)
        self.assertNotIn("A row with a Run button", html)
        self.assertIn("Passwords you", html)
        self.assertNotIn("It holds no", html)


class Pure(unittest.TestCase):
    def test_python_side_has_23_stages_for_a_half_tunnel_travel_node(self):
        self.assertEqual(len(h44._bld_stage_defs("half", "travel")), 23)
        self.assertEqual(len(h44._bld_stage_defs("half", "magic")), 27)


if __name__ == "__main__":
    unittest.main()

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


spec = importlib.util.spec_from_file_location("h44_dock_under_test", newest("44helper_v[0-9]*.py"))
h44 = importlib.util.module_from_spec(spec)
sys.modules["h44_dock_under_test"] = h44
spec.loader.exec_module(h44)

STUB = r"""
var __byId = {};
function Node(id) {
  this._id = ''; this.style = {}; this.children = []; this.parentNode = null; this.open = false;
  this.id = id || '';
}
Object.defineProperty(Node.prototype, 'id', {get: function() { return this._id; }, set: function(v) { this._id = v; if (v) { __byId[v] = this; } }});
Node.prototype.appendChild = function(c) {
  if (c.parentNode) { c.parentNode.removeChild(c); }
  this.children.push(c); c.parentNode = this; return c;
};
Node.prototype.removeChild = function(c) {
  this.children.splice(this.children.indexOf(c), 1); c.parentNode = null;
};
Node.prototype.insertBefore = function(c, ref) {
  if (c.parentNode) { c.parentNode.removeChild(c); }
  var i = ref ? this.children.indexOf(ref) : this.children.length;
  this.children.splice(i, 0, c); c.parentNode = this; return c;
};
Object.defineProperty(Node.prototype, 'nextSibling', {get: function() {
  if (!this.parentNode) { return null; }
  var l = this.parentNode.children; return l[l.indexOf(this) + 1] || null;
}});
var document = {getElementById: function(id) { return __byId[id] || null; },
                createElement: function() { return new Node(''); }};
var __loaded = [];
function tabFirstOpen(t) { __loaded.push(t); }
"""


def run_js(body):
    start = h44._JS_TABS.index("var _STEP_DOCKS")
    end = h44._JS_TABS.index("function clickTab(id)")
    code = STUB + h44._JS_TABS[start:end] + body
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "t.js")
        with open(path, "w") as f:
            f.write(code)
        r = subprocess.run(["node", path], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr[:1500])
    return json.loads(r.stdout)


SETUP = r"""
var homes = {}, slots = {}, dets = {};
['asl3', 'dv', 'm17', 'svx'].forEach(function(p) {
  homes[p] = new Node(p + '-panel'); var el = new Node(p + '-steps'); homes[p].appendChild(new Node(p + '-before')); homes[p].appendChild(el); homes[p].appendChild(new Node(p + '-after'));
});
['asl3', 'dvs', 'm17', 'svx'].forEach(function(st) {
  ['bld', 'mbx'].forEach(function(b) {
    dets[b + st] = new Node(b + '-det-' + st); slots[b + st] = new Node(b + '-steps-' + st);
  });
});
function where(p) { var el = __byId[p + '-steps']; return el.parentNode ? el.parentNode.id : null; }
function order(p) { return homes[p].children.map(function(c) { return c.id; }); }
"""


@unittest.skipUnless(shutil.which("node"), "node not installed")
class Dock(unittest.TestCase):
    def test_a_closed_card_leaves_every_list_at_home(self):
        out = run_js(SETUP + """
stepsDock('build');
console.log(JSON.stringify({asl3: where('asl3'), loaded: __loaded}));
""")
        self.assertEqual(out["asl3"], "asl3-panel")
        self.assertEqual(out["loaded"], [])

    def test_an_open_card_takes_its_tabs_list_and_loads_the_tab(self):
        out = run_js(SETUP + """
dets['bldasl3'].open = true;
stepsDock('build');
console.log(JSON.stringify({asl3: where('asl3'), dv: where('dv'), loaded: __loaded}));
""")
        self.assertEqual(out["asl3"], "bld-steps-asl3")
        self.assertEqual(out["dv"], "dv-panel")
        self.assertEqual(out["loaded"], ["asl3"])

    def test_each_stage_takes_its_own_tab(self):
        out = run_js(SETUP + """
['asl3', 'dvs', 'm17', 'svx'].forEach(function(st) { dets['mbx' + st].open = true; });
stepsDock('magic');
console.log(JSON.stringify({w: ['asl3', 'dv', 'm17', 'svx'].map(where), loaded: __loaded}));
""")
        self.assertEqual(out["w"], ["mbx-steps-asl3", "mbx-steps-dvs", "mbx-steps-m17", "mbx-steps-svx"])
        self.assertEqual(out["loaded"], ["asl3", "dvswitch", "m17", "svxlink"])

    def test_leaving_the_build_tab_puts_the_list_back_in_its_place(self):
        out = run_js(SETUP + """
dets['bldm17'].open = true;
stepsDock('build');
var during = where('m17');
stepsDock('');
console.log(JSON.stringify({during: during, after: where('m17'), order: order('m17')}));
""")
        self.assertEqual(out["during"], "bld-steps-m17")
        self.assertEqual(out["after"], "m17-panel")
        self.assertEqual(out["order"], ["m17-before", "m17-steps-home", "m17-steps", "m17-after"])

    def test_coming_back_takes_the_list_again_and_repeating_changes_nothing(self):
        out = run_js(SETUP + """
dets['bldsvx'].open = true;
stepsDock('build'); stepsDock(''); stepsDock('build'); stepsDock('build');
console.log(JSON.stringify({w: where('svx'), order: order('svx'), loaded: __loaded}));
""")
        self.assertEqual(out["w"], "bld-steps-svx")
        self.assertEqual(out["order"], ["svx-before", "svx-steps-home", "svx-after"])

    def test_the_other_tab_never_gets_another_build_tabs_list(self):
        out = run_js(SETUP + """
dets['bldasl3'].open = true;
stepsDock('magic');
console.log(JSON.stringify({w: where('asl3')}));
""")
        self.assertEqual(out["w"], "asl3-panel")

    def test_clickTab_docks_for_the_build_tabs_and_undocks_for_the_others(self):
        src = h44._JS_TABS
        i = src.index("function clickTab(id)")
        body = src[i:src.index("\nfunction ", i + 10)]
        self.assertIn("\n  stepsDock(id === 'build' || id === 'magic' ? id : '');", body)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Device-free tests for ui.py. No phone, no adb, no XML fixtures on disk.

Run:  python3 tests/test_ui.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "host" / "ui.py"

# A miniature dump shaped like the real thing: a clickable row with no text
# wrapping a text node that is not clickable. This is the case that made
# `tap-text` fail the first time, so it is the case worth pinning.
SAMPLE = textwrap.dedent("""\
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
 <node index="0" text="" class="android.widget.FrameLayout" package="com.android.settings"
       clickable="false" scrollable="false" bounds="[0,0][1260,2800]">
  <node index="0" text="" resource-id="com.android.settings:id/dashboard_container"
        class="android.widget.ListView" clickable="false" scrollable="true"
        bounds="[0,200][1260,2600]">
   <node index="0" text="" class="android.widget.FrameLayout" clickable="true"
         scrollable="false" bounds="[0,500][1260,714]">
    <node index="0" text="隐私" resource-id="com.android.settings:id/vlist_content"
          class="android.widget.TextView" clickable="false" scrollable="false"
          bounds="[0,500][1260,714]" />
   </node>
   <node index="1" text="" class="android.widget.FrameLayout" clickable="true"
         scrollable="false" bounds="[0,858][1260,1072]">
    <node index="0" text="电池" resource-id="com.android.settings:id/vlist_content"
          class="android.widget.TextView" clickable="false" scrollable="false"
          bounds="[0,858][1260,1072]" />
   </node>
   <node index="2" text="" class="android.widget.EditText"
         resource-id="com.android.settings:id/search_input" clickable="true"
         scrollable="false" password="false" bounds="[0,100][1260,180]" />
   <node index="3" text="" class="android.view.View" clickable="false"
         scrollable="false" bounds="[0,2700][1260,2800]" />
  </node>
 </node>
</hierarchy>
""")


def run(*args):
    r = subprocess.run([sys.executable, str(UI), *map(str, args)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


class UIParser(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.xml = Path(self.tmp.name) / "ui.xml"
        self.xml.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parse_drops_scaffolding(self):
        rc, out, err = run("parse", self.xml)
        self.assertEqual(rc, 0)
        # The bare <node> with no text/desc/id-suffix/clickable must be gone.
        self.assertNotIn("2700", out)
        self.assertIn("隐私", out)
        self.assertIn("电池", out)

    def test_parse_emits_centers_in_physical_pixels(self):
        rc, out, _ = run("parse", self.xml)
        self.assertEqual(rc, 0)
        # [0,500][1260,714] -> center (630, 607)
        self.assertIn("( 630, 607)", out)
        # [0,858][1260,1072] -> center (630, 965)
        self.assertIn("( 630, 965)", out)

    def test_parse_flags(self):
        rc, out, _ = run("parse", self.xml)
        # ListView is scrollable-only
        self.assertIn("-S-- ( 630,1400)", out)
        # the row containers are clickable-only
        self.assertIn("C--- ( 630, 607)", out)

    def test_json_shape(self):
        rc, out, _ = run("parse", self.xml, "--json")
        self.assertEqual(rc, 0)
        nodes = json.loads(out)
        self.assertGreater(len(nodes), 0)
        for n in nodes:
            for key in ("label", "center", "clickable", "id", "class"):
                self.assertIn(key, n)
            self.assertEqual(len(n["center"]), 2)

    def test_find_returns_center(self):
        rc, out, _ = run("find", self.xml, "电池")
        self.assertEqual(rc, 0)
        self.assertIn("(630,965)", out)

    def test_find_misses_cleanly(self):
        rc, out, err = run("find", self.xml, "不存在的标签")
        self.assertEqual(rc, 1)
        self.assertIn("no node matching", err)

    def test_tap_falls_back_to_text_node(self):
        """The regression that mattered: the row is clickable but textless."""
        rc, out, _ = run("tap", self.xml, "隐私")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "630 607")

    def test_tap_prefers_clickable_when_both_match(self):
        # search_input is clickable and has no text; matching on id must work.
        rc, out, _ = run("tap", self.xml, "search_input")
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(), "630 140")

    def test_tap_misses_cleanly(self):
        rc, out, err = run("tap", self.xml, "不存在")
        self.assertEqual(rc, 1)
        self.assertIn("no node matching", err)

    def test_malformed_bounds_are_skipped(self):
        bad = SAMPLE.replace('bounds="[0,500][1260,714]"', 'bounds="garbage"', 1)
        self.xml.write_text(bad, encoding="utf-8")
        rc, out, _ = run("parse", self.xml)
        # Parsing must not crash; the bad node simply loses its line.
        self.assertEqual(rc, 0)
        self.assertNotIn("garbage", out)


class Filters(unittest.TestCase):
    """Package exclusion and per-glyph merging.

    Both are borrowed from Windows-MCP, where they exist for the same reason:
    the raw accessibility tree contains things that are on screen and are not
    what the caller meant -- a keyboard's 40 keys, one node per CJK glyph.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, body: str) -> Path:
        p = self.dir / name
        p.write_text(body, encoding="utf-8")
        return p

    def run_env(self, *args, **env):
        e = {k: v for k, v in os.environ.items()
             if k not in ("PHONE_EXCLUDE_PACKAGES", "PHONE_MERGE_WORDS")}
        e.update(env)
        r = subprocess.run([sys.executable, str(UI), *map(str, args)],
                           capture_output=True, text=True, env=e)
        return r.returncode, r.stdout, r.stderr

    # -- package exclusion --------------------------------------------------
    def test_ime_is_excluded_by_default(self):
        """A keyboard is on screen and is almost never the target."""
        body = (
            '<hierarchy>'
            '<node text="搜索" package="com.example.app" class="android.widget.TextView" '
            'clickable="false" bounds="[0,0][400,100]" />'
            '<node text="q" package="com.sohu.inputmethod.sogou" '
            'class="android.widget.Button" clickable="true" bounds="[0,2000][100,2100]" />'
            '<node text="w" package="com.sohu.inputmethod.sogou" '
            'class="android.widget.Button" clickable="true" bounds="[100,2000][200,2100]" />'
            '</hierarchy>')
        xml = self.write("ui.xml", body)
        rc, out, _ = self.run_env("parse", xml)
        self.assertEqual(rc, 0)
        self.assertIn("搜索", out)
        self.assertNotIn("(  50,2050)", out, "IME keys must not reach the model")

    def test_exclude_packages_can_be_overridden(self):
        body = (
            '<hierarchy>'
            '<node text="OK" package="com.systemui" class="android.widget.Button" '
            'clickable="true" bounds="[0,0][200,100]" />'
            '</hierarchy>')
        xml = self.write("ui.xml", body)
        rc, out, _ = self.run_env("parse", xml, PHONE_EXCLUDE_PACKAGES="com.systemui")
        self.assertEqual(rc, 0)
        self.assertNotIn("OK", out)
        # An empty list means "exclude nothing", not "fall back to the default".
        rc, out, _ = self.run_env("parse", xml, PHONE_EXCLUDE_PACKAGES="")
        self.assertEqual(rc, 0)
        self.assertIn("OK", out)

    # -- per-glyph merging --------------------------------------------------
    def glyphs(self, chars, y=500, w=60, start=0):
        parts = []
        for i, ch in enumerate(chars):
            x1 = start + i * w
            parts.append(
                f'<node text="{ch}" class="android.widget.TextView" clickable="false" '
                f'bounds="[{x1},{y}][{x1 + w},{y + 80}]" />')
        return "<hierarchy>" + "".join(parts) + "</hierarchy>"

    def test_cjk_glyphs_merge_into_one_line(self):
        xml = self.write("ui.xml", self.glyphs("四个字节"))
        rc, out, _ = self.run_env("parse", xml)
        self.assertEqual(rc, 0)
        self.assertIn("四个字节", out)
        # One line, not four.
        self.assertEqual(out.count("四个字节"), 1)
        self.assertIn("1 actionable", _)

    def test_merge_can_be_disabled(self):
        xml = self.write("ui.xml", self.glyphs("四个字节"))
        rc, out, _ = self.run_env("parse", xml, PHONE_MERGE_WORDS="0")
        self.assertEqual(rc, 0)
        self.assertNotIn("四个字节", out)
        self.assertIn("4 actionable", _)

    def test_clickable_nodes_never_merge(self):
        """A target must stay its own line even if its label is one glyph."""
        body = (
            '<hierarchy>'
            '<node text="确" class="android.widget.Button" clickable="true" '
            'bounds="[0,500][60,580]" />'
            '<node text="定" class="android.widget.Button" clickable="true" '
            'bounds="[60,500][120,580]" />'
            '</hierarchy>')
        xml = self.write("ui.xml", body)
        rc, out, _ = self.run_env("parse", xml)
        self.assertEqual(rc, 0)
        self.assertIn("确", out)
        self.assertIn("定", out)
        self.assertNotIn("确定", out)

    def test_merge_keeps_two_lines_apart(self):
        """Same x, different y: two lines of text, not one run."""
        body = (
            '<hierarchy>'
            '<node text="上" class="android.widget.TextView" clickable="false" '
            'bounds="[0,500][60,580]" />'
            '<node text="下" class="android.widget.TextView" clickable="false" '
            'bounds="[0,900][60,980]" />'
            '</hierarchy>')
        xml = self.write("ui.xml", body)
        rc, out, _ = self.run_env("parse", xml)
        self.assertEqual(rc, 0)
        self.assertNotIn("上下", out)

    def test_merged_center_spans_the_run(self):
        """The merged node's centre must be tappable, i.e. inside the run."""
        xml = self.write("ui.xml", self.glyphs("四个字节", y=500, w=60, start=0))
        rc, out, _ = self.run_env("parse", xml)
        # run spans x 0..240, centre 120, y centre 540
        self.assertIn("( 120, 540)", out)

    def test_diff_uses_the_same_filters(self):
        """parse and diff disagreeing about the screen would be worse than no
        filter: a diff would report phantom changes on every call."""
        body = self.glyphs("四个字节")
        a = self.write("a.xml", body)
        b = self.write("b.xml", body)
        rc, out, _ = self.run_env("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("no change", out)


class TreeDiff(unittest.TestCase):
    """ui.py diff: the answer to "did my tap do anything".

    The failure this pins: a re-dump after every action. It is 40 lines the
    model already read, and the one line that changed is buried in it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name: str, body: str) -> Path:
        p = self.dir / name
        p.write_text(body, encoding="utf-8")
        return p

    def node(self, text: str, y1: int, y2: int, clickable: bool = False,
             cls: str = "android.widget.TextView", rid: str = "") -> str:
        return (f'<node text="{text}" class="{cls}" resource-id="{rid}" '
                f'clickable="{"true" if clickable else "false"}" '
                f'bounds="[0,{y1}][1260,{y2}]" />')

    def test_identical_dumps_report_no_change(self):
        body = f"<hierarchy>{self.node('隐私', 500, 714)}</hierarchy>"
        a = self.write("a.xml", body)
        b = self.write("b.xml", body)
        rc, out, _ = run("diff", a, b)
        self.assertEqual(rc, 0)
        # Silence would be ambiguous: "no change" and "the diff broke" look
        # the same to a model reading stdout.
        self.assertIn("no change", out)
        self.assertIn("1 nodes", out)

    def test_added_and_removed_nodes(self):
        a = self.write("a.xml",
                       f"<hierarchy>{self.node('旧条目', 500, 714)}</hierarchy>")
        b = self.write("b.xml",
                       f"<hierarchy>{self.node('新条目', 500, 714)}</hierarchy>")
        rc, out, _ = run("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("+ 新条目", out)
        self.assertIn("- 旧条目", out)

    def test_scroll_is_reported_as_moved_not_replaced(self):
        """The case that makes a naive diff useless: a list scrolls."""
        a = self.write("a.xml", f"<hierarchy>{self.node('电池', 858, 1072)}</hierarchy>")
        b = self.write("b.xml", f"<hierarchy>{self.node('电池', 400, 614)}</hierarchy>")
        rc, out, _ = run("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("~ 电池", out)
        self.assertIn("(630,965)->(630,507)", out)
        # One moved row, not one removal plus one addition.
        self.assertNotIn("+ 电池", out)
        self.assertNotIn("- 电池", out)

    def test_small_jitter_is_not_a_move(self):
        # A centre that shifts by a pixel is the same node in the same place.
        a = self.write("a.xml", f"<hierarchy>{self.node('电池', 858, 1072)}</hierarchy>")
        b = self.write("b.xml", f"<hierarchy>{self.node('电池', 860, 1072)}</hierarchy>")
        rc, out, _ = run("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("no change", out)

    def test_clickable_flag_change_is_reported(self):
        a = self.write("a.xml", f"<hierarchy>{self.node('登录', 500, 714)}</hierarchy>")
        b = self.write("b.xml",
                       f"<hierarchy>{self.node('登录', 500, 714, clickable=True)}</hierarchy>")
        rc, out, _ = run("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("! 登录", out)
        self.assertIn("clickable", out)

    def test_duplicate_rows_stay_distinct(self):
        """Two identical rows are two rows; a set-based diff would lose one."""
        one = f"<hierarchy>{self.node('项目', 500, 714)}</hierarchy>"
        two = (f"<hierarchy>{self.node('项目', 500, 714)}"
               f"{self.node('项目', 900, 1114)}</hierarchy>")
        a = self.write("a.xml", one)
        b = self.write("b.xml", two)
        rc, out, err = run("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("+ 项目", out)
        # Exactly one addition: the second row is new, the first is not.
        self.assertIn("1+", err)

    def test_json_output_is_structured(self):
        a = self.write("a.xml", f"<hierarchy>{self.node('旧', 500, 714)}</hierarchy>")
        b = self.write("b.xml", f"<hierarchy>{self.node('新', 500, 714)}</hierarchy>")
        rc, out, _ = run("diff", a, b, "--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)
        for key in ("added", "removed", "moved", "changed"):
            self.assertIn(key, data)
        self.assertEqual([n["label"] for n in data["added"]], ["新"])
        self.assertEqual([n["label"] for n in data["removed"]], ["旧"])

    def test_summary_goes_to_stderr(self):
        a = self.write("a.xml", f"<hierarchy>{self.node('旧', 500, 714)}</hierarchy>")
        b = self.write("b.xml", f"<hierarchy>{self.node('新', 500, 714)}</hierarchy>")
        rc, out, err = run("diff", a, b)
        self.assertEqual(rc, 0)
        self.assertIn("1+ 1-", err)


class EmitMode(unittest.TestCase):
    """phone.py must be able to describe work without touching a device."""

    def test_emit_prints_device_commands(self):
        import os
        env = dict(os.environ, PHONE_EMIT="1")
        phone = UI.parent / "phone.py"
        r = subprocess.run([sys.executable, str(phone), "tap", "630", "607"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("DEVICE_CMD:", r.stdout)
        self.assertIn("eyes.sh tap 630 607", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
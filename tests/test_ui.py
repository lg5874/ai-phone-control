#!/usr/bin/env python3
"""Device-free tests for ui.py. No phone, no adb, no XML fixtures on disk.

Run:  python3 tests/test_ui.py
"""
from __future__ import annotations

import json
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
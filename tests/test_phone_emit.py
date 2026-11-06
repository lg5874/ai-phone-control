#!/usr/bin/env python3
"""Device-free tests for phone.py's emit transport.

The bug these pin: in emit mode phone.py used to print a device command and
then `return 0` without parsing anything. A tap that reports success and moves
nothing is the one failure an agent cannot recover from, because the agent has
no other evidence to check. Every emit path must now either do the work from
shared storage or fail loudly.

Run:  python3 tests/test_phone_emit.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PHONE = ROOT / "host" / "phone.py"

# One clickable row wrapping a text node -- the shape that makes `tap-text`
# resolve to the child's centre rather than the row's.
SAMPLE = textwrap.dedent("""\
<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
 <node index="0" text="" class="android.widget.FrameLayout" package="com.android.settings"
       clickable="false" scrollable="false" bounds="[0,0][1260,2800]">
  <node index="0" text="" class="android.widget.FrameLayout" clickable="true"
        scrollable="false" bounds="[0,500][1260,714]">
   <node index="0" text="隐私" resource-id="com.android.settings:id/vlist_content"
         class="android.widget.TextView" clickable="false" scrollable="false"
         bounds="[0,500][1260,714]" />
  </node>
 </node>
</hierarchy>
""")


class EmitTransport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.xml = self.dir / "ui.xml"
        self.xml.write_text(SAMPLE, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def age_artifact(self, path: Path, seconds: float) -> None:
        t = time.time() - seconds
        os.utime(path, (t, t))

    def run_phone(self, *args):
        env = {**os.environ, "PHONE_EMIT": "1", "PHONE_DIR": str(self.dir)}
        return subprocess.run([sys.executable, str(PHONE), *map(str, args)],
                              capture_output=True, text=True, env=env,
                              timeout=120)

    # ---------------------------------------------------------------- ui
    def test_ui_fresh_parses_without_asking_the_device_anything(self):
        r = self.run_phone("ui")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("隐私", r.stdout)
        self.assertNotIn("DEVICE_CMD", r.stdout,
                         "a fresh tree must not emit a device command")

    def test_ui_stale_warns_but_still_serves_the_view(self):
        self.age_artifact(self.xml, 600)
        r = self.run_phone("ui")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("old", r.stderr)
        self.assertIn("隐私", r.stdout)

    def test_ui_strict_refuses_a_stale_tree(self):
        self.age_artifact(self.xml, 600)
        r = self.run_phone("ui", "--strict")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("stale", r.stderr)

    def test_ui_missing_tree_asks_for_a_dump(self):
        self.xml.unlink()
        r = self.run_phone("ui")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("has not produced", r.stderr)
        self.assertIn("eyes.sh dump", r.stdout)

    # ------------------------------------------------------------ tap-text
    def test_tap_text_hit_prints_the_tap_command(self):
        r = self.run_phone("tap-text", "隐私")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("eyes.sh tap 630 607", r.stdout,
                      "the resolved coordinates must be handed to the caller")

    def test_tap_text_miss_is_an_error_not_a_no_op(self):
        r = self.run_phone("tap-text", "no-such-label")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no node matching", r.stderr)

    def test_tap_text_refuses_to_aim_at_a_stale_tree(self):
        self.age_artifact(self.xml, 600)
        r = self.run_phone("tap-text", "隐私")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("stale", r.stderr)

    # ---------------------------------------------------------------- shot
    def test_shot_missing_artifact_fails_loudly(self):
        r = self.run_phone("shot")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("has not produced", r.stderr)

    def test_shot_existing_artifact_reports_path_and_size(self):
        (self.dir / "shot.png").write_bytes(b"\x89PNG" + b"\0" * 64)
        r = self.run_phone("shot")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("shot.png", r.stdout)
        self.assertIn("68 B", r.stdout)

    # ----------------------------------------------------------------- top
    def test_top_reads_the_probe_instead_of_echoing_a_command(self):
        (self.dir / "top.txt").write_text(
            "ActivityRecord{abc u0 com.android.settings/.Settings}\n",
            encoding="utf-8")
        r = self.run_phone("top")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("com.android.settings", r.stdout)
        self.assertNotIn("DEVICE_CMD", r.stdout)

    def test_top_without_a_probe_asks_for_one(self):
        r = self.run_phone("top")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("eyes.sh top >", r.stdout)
        self.assertIn("re-run", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)

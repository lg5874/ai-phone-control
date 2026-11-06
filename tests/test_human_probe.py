#!/usr/bin/env python3
"""Device-free tests for the touch probe in android/eyes.sh.

The probe decides one thing: may an agent touch this screen, or is a human on
it. The failure these pin was measured on a vivo_ts panel — the first version
took the *first event on the device*, so a lift (TRACKING_ID ffffffff) or a
stray SYN_REPORT counted as a human and the agent stood down while nobody was
there. Only a press counts now.

The grep patterns are read out of eyes.sh rather than copied, so this test goes
red when the shell changes shape instead of drifting quietly.

Run:  python3 tests/test_human_probe.py
"""
from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EYES = ROOT / "android" / "eyes.sh"

# Real `getevent -q` output, captured from the test device (V2403A, Android 15).
LIFT = ["0003 0039 ffffffff", "0001 0145 00000000", "0001 014a 00000000",
        "0000 0000 00000000"]
PRESS = ["0001 014a 00000001", "0001 0145 00000001", "0003 0039 00007923",
         "0003 0035 00001d54", "0003 0036 00005092", "0000 0000 00000000"]
MOVE_ONLY = ["0003 0035 00001d54", "0003 0036 00005092", "0003 0030 0000000c",
             "0000 0000 00000000"]
# A panel that reports multi-touch but no BTN_TOUCH: the tracking id is the
# only press signal there is.
MT_ONLY = ["0003 0039 0000000f", "0003 0035 00001200", "0000 0000 00000000"]
# Symbols instead of hex, which is what `getevent -l` prints.
SYMBOLS = ["EV_KEY       BTN_TOUCH    DOWN", "EV_ABS       ABS_MT_TRACKING_ID   0000002a"]


def patterns() -> tuple[str, str]:
    block = EYES.read_text(encoding="utf-8").split("human)", 1)[1].split(";;", 1)[0]
    include = re.search(r"grep -Ei '([^']+)'", block)
    exclude = re.search(r"grep -Eiv '([^']+)'", block)
    assert include and exclude, "eyes.sh human block changed shape"
    return include.group(1), exclude.group(1)


def probe(lines: list[str]) -> str:
    include, exclude = patterns()
    cmd = f"grep -Ei '{include}' | grep -Eiv '{exclude}' | head -1"
    out = subprocess.run(["sh", "-c", cmd], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, check=False)
    return out.stdout.strip()


class HumanProbe(unittest.TestCase):
    def test_a_lift_is_not_a_human(self):
        self.assertEqual(probe(LIFT), "", "a finger leaving the glass is not a "
                                          "finger on the glass")

    def test_a_press_is_a_human(self):
        self.assertTrue(probe(PRESS))

    def test_movement_without_a_press_is_not_a_human(self):
        self.assertEqual(probe(MOVE_ONLY), "",
                         "hover / noise / fingerprint noise must not stop an agent")

    def test_tracking_id_alone_counts(self):
        self.assertTrue(probe(MT_ONLY), "panels without BTN_TOUCH must still work")

    def test_symbolic_output_counts(self):
        self.assertTrue(probe(SYMBOLS), "getevent -l output must be understood too")

    def test_empty_stream_is_not_a_human(self):
        self.assertEqual(probe([]), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
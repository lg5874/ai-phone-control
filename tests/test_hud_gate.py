#!/usr/bin/env python3
"""Tests for the floating panel contract and the pause gate.

The bug this file exists to prevent is specific and embarrassing: `gate()` was
defined in v1.3 and called by *nothing*. Every action ran unguarded, and the
test suite was green the whole time because no test ever asserted that an
action consults the gate. A helper nobody calls looks exactly like a helper
that works.

So these tests check two separate things:
  1. the file format the panel reads and writes (pure functions, no device)
  2. that every action subcommand actually routes through gate()
"""
import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "host"))


class ControlFileFormat(unittest.TestCase):
    """The panel and the agent agree on one tiny format. Pin it."""

    def test_pause_is_exact_word(self):
        # Only the literal word stops the agent. Anything else must mean go,
        # because a truncated read must never freeze a run.
        def paused(body):
            return body.strip().lower() == "pause"

        self.assertTrue(paused("pause\n"))
        self.assertTrue(paused("  PAUSE  \n"))
        self.assertFalse(paused("run\n"))
        self.assertFalse(paused(""))
        self.assertFalse(paused("pau"))     # half-written
        self.assertFalse(paused("paused"))  # not the protocol word

    def test_status_roundtrip(self):
        # What `phone say` writes must parse back field by field.
        body = ("ts=1794040455621\n"
                "state=running\n"
                "task=在小红书搜索并安装\n"
                "think=当前界面是搜索框，先点输入框\n"
                "step=第 2/5 步 · 点击搜索框\n")
        fields = {}
        for line in body.split("\n"):
            if "=" in line:
                k, _, v = line.partition("=")
                fields[k] = v
        self.assertEqual(fields["state"], "running")
        self.assertEqual(fields["task"], "在小红书搜索并安装")
        self.assertIn("搜索框", fields["think"])
        self.assertTrue(fields["ts"].isdigit())


class GateIsWired(unittest.TestCase):
    """Every action must call gate(). This is the regression that mattered."""

    ACTIONS = ["cmd_tap", "cmd_tap_text", "cmd_long", "cmd_swipe",
               "cmd_key", "cmd_type"]

    def setUp(self):
        self.src = io.open(os.path.join(ROOT, "host", "phone.py"),
                           encoding="utf-8").read()

    def _body(self, name):
        """Source text of one function, from its def to the next top-level def."""
        m = re.search(rf"^def {name}\(.*?(?=^def |\Z)", self.src,
                      re.S | re.M)
        self.assertIsNotNone(m, f"{name} not found")
        return m.group(0)

    def test_every_action_calls_gate(self):
        for name in self.ACTIONS:
            body = self._body(name)
            self.assertIn("gate(a)", body,
                          f"{name} does not call gate() -- the human's pause "
                          f"button would not stop it")

    def test_gate_is_actually_defined(self):
        # Guards against deleting the helper and leaving the calls.
        self.assertIn("def gate(a)", self.src)

    def test_pause_checked_before_force(self):
        # A human who pressed pause outranks --force. If the force check came
        # first, `--force` would be a documented way to ignore the button.
        # Match the code, not the prose: the comment above the pause check
        # mentions "--force" and would otherwise win the search.
        body = self._body("gate")
        pause_at = body.index("hud_paused()")
        force_at = body.index('getattr(a, "force"')
        self.assertLess(pause_at, force_at,
                        "gate() must check pause before honouring --force")

    def test_paused_exit_code_is_distinct(self):
        self.assertIn("EXIT_PAUSED = 7", self.src)
        # It must differ from HUMAN_BUSY (4): "a finger was there" and
        # "the human said stop" are different instructions to an agent.
        self.assertNotIn("EXIT_PAUSED = 4", self.src)


class PanelSource(unittest.TestCase):
    """The APK's source must keep the two properties that make it usable."""

    def setUp(self):
        self.java = io.open(
            os.path.join(ROOT, "android", "hud", "src", "com", "lcs", "hud",
                         "HudService.java"), encoding="utf-8").read()

    def test_hidden_from_uiautomator(self):
        # Without this the agent reads its own panel as screen content and
        # taps its own pause button.
        self.assertIn("IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS",
                      self.java)

    def test_fixed_max_width(self):
        # WRAP_CONTENT let one long sentence stretch the card across the
        # screen and cover what the human was reading.
        self.assertIn("Math.min(dp(240)", self.java)

    def test_fails_open_on_unreadable_control(self):
        self.assertIn('"pause".equalsIgnoreCase(ctl)', self.java)


class Heartbeat(unittest.TestCase):
    """Liveness must be structural, not a thing the agent has to remember."""

    def setUp(self):
        self.src = io.open(os.path.join(ROOT, "host", "phone.py"),
                           encoding="utf-8").read()

    def _body(self, name):
        m = re.search(rf"^def {name}\(.*?(?=^def |\Z)", self.src, re.S | re.M)
        self.assertIsNotNone(m, f"{name} not found")
        return m.group(0)

    def test_every_action_beats(self):
        # The panel judges liveness from the newest of two clocks. If an action
        # does not beat, the card says "no update" while the agent is working --
        # a status light that cannot tell busy from dead.
        for name in GateIsWired.ACTIONS:
            self.assertIn("hud_beat(", self._body(name),
                          f"{name} does not emit a heartbeat")

    def test_beat_never_breaks_an_action(self):
        # A heartbeat is bookkeeping. If writing it fails, the tap that already
        # happened must not be reported as a failure.
        body = self._body("hud_beat")
        self.assertIn("except", body)
        self.assertIn("pass", body)
        # SystemExit must be caught too: sh() raises it (a BaseException) when
        # the device errors, and `except Exception` alone would let a failed
        # heartbeat abort an action that already worked.
        self.assertIn("SystemExit", body)

    def test_beat_skipped_in_emit_mode(self):
        # Emit mode has no shell; a heartbeat would just be noise between the
        # human and the command they asked for.
        body = self._body("hud_beat")
        self.assertIn("if EMIT", body)

    def test_beat_and_status_are_separate_files(self):
        # Different owners, different lifetimes. Sharing one file would need a
        # read-modify-write between an action and `say`.
        #
        # Both writers now go through hud_publish, which takes the file name as
        # an argument, so the name appears as a quoted literal rather than as
        # the tail of a path. Match the literal.
        beat = re.findall(r'"(hud\.\w+)"', self._body("hud_beat"))
        note = re.findall(r'"(hud\.\w+)"', self._body("hud_note"))
        self.assertIn("hud.beat", beat)
        self.assertNotIn("hud.status", beat)
        self.assertIn("hud.status", note)

    def test_pause_publishes_to_the_panel(self):
        # Pressing pause must make the card say so even if the agent never
        # calls `say` again -- that is precisely the moment it stops calling.
        body = self._body("gate")
        self.assertIn("hud_note(", body)


class PanelRendersState(unittest.TestCase):
    """`state` was written by the agent and silently ignored by the panel."""

    def setUp(self):
        self.java = io.open(
            os.path.join(ROOT, "android", "hud", "src", "com", "lcs", "hud",
                         "HudService.java"), encoding="utf-8").read()

    def test_state_is_read(self):
        self.assertIn('m.get("state")', self.java)

    def test_done_and_error_are_visible(self):
        # A finished run must not keep a green dot, and a failed one must not
        # look like a slow one.
        self.assertIn('"done".equalsIgnoreCase', self.java)
        self.assertIn('"error".equalsIgnoreCase', self.java)

    def test_liveness_uses_the_newer_clock(self):
        self.assertIn("Math.max(beatTs, statusTs)", self.java)

    def test_beat_file_is_polled(self):
        # The panel must read the beat file by name, through beatPath().
        # Asserting the old `String BEAT` constant pinned a variable that was
        # refactored away, so the test failed while the behaviour was fine --
        # and a red test for a green behaviour is how a real regression later
        # gets waved through.
        self.assertIn("beatPath()", self.java)
        self.assertIn("parseTs(read(beatPath()))", self.java)


class PanelPath(unittest.TestCase):
    """The panel's directory is not a constant, and guessing it cost a day.

    Three plausible paths were tried and two of them fail silently:
      /sdcard/lcs              -- FUSE forces drwxrws--- owned by media_rw, so
                                  a normal app uid cannot even traverse it.
                                  chmod looks like it succeeds and does nothing.
      /sdcard/Android/data/... -- writable by the app, but uncreatable from
                                  outside; root gets EPERM from the FUSE daemon.
      /data/user/0/com.lcs.hud -- correct, but from a shell (even root) only
                                  this device's own package is visible, because
                                  Android 11 gives each app a mount namespace.
    So the path must be *resolved on the device*, through the panel's pid, and
    the resolution must be a verb the host can call. These tests pin that.
    """

    def setUp(self):
        self.sh = io.open(os.path.join(ROOT, "android", "eyes.sh"),
                          encoding="utf-8").read()

    def test_huddir_exists(self):
        # The host cannot hardcode the path; it must ask.
        self.assertIn("huddir)", self.sh)

    def test_huddir_borrows_the_panel_namespace(self):
        # Only the panel's own mount namespace contains its private dir.
        block = self.sh.split("huddir)", 1)[1].split(";;", 1)[0]
        self.assertIn("pidof com.lcs.hud", block)
        self.assertIn("nsenter", block)
        self.assertIn("-m", block)

    def test_huddir_falls_back_when_panel_is_absent(self):
        # With no panel installed there is no namespace to borrow, and the
        # legacy path keeps `hud pause` usable from a plain root shell.
        block = self.sh.split("huddir)", 1)[1].split(";;", 1)[0]
        self.assertIn("REMOTE_DIR_FALLBACK", block)

    def test_status_reports_the_resolved_dir(self):
        # A silent wrong path is the whole bug. Print where we actually wrote.
        block = self.sh.split("status)", 1)[1].split(";;", 1)[0]
        self.assertIn('echo "dir=$D"', block)


class HudLiveness(unittest.TestCase):
    """A dead panel must not look like a working one.

    v1.4.0 fixed *where* to write. v1.4.1 fixes *whether anyone is reading*:
    `huddir` falls back to the legacy path when no panel process exists, so
    every write succeeded, `hud status` printed a plausible dir=, and the card
    on screen never changed because nothing was polling it.
    """

    def setUp(self):
        self.sh = io.open(os.path.join(ROOT, "android", "eyes.sh"),
                          encoding="utf-8").read()
        self.py = io.open(os.path.join(ROOT, "host", "phone.py"),
                          encoding="utf-8").read()

    def _verb_block(self, name):
        # A top-level verb of eyes.sh: the label is a line of its own, indented
        # by at most two spaces ("hud)" is flush left, "  hudpkg)" is not), and
        # the body runs until the next such label. Slicing on ";;" is wrong
        # here because a verb may contain nested `case` arms of its own --
        # hudpkg has one, and stopping at its first ";;" truncated the block
        # right after `installed`, which made the assertions vacuous instead of
        # failing. Both mistakes are the same lesson: a test that slices shell
        # by punctuation is a test that quietly stops testing.
        pat = re.compile(r"^ {0,2}" + re.escape(name) + r"\)\s*$", re.M)
        m = pat.search(self.sh)
        self.assertIsNotNone(m, f"no top-level verb {name}")
        rest = self.sh[m.end():]
        nxt = re.search(r"^ {0,2}[a-z|]+\)\s*$", rest, re.M)
        return rest[:nxt.start()] if nxt else rest

    def _hud_block(self):
        return self._verb_block("hud")

    def test_hudpkg_distinguishes_absent_from_unknown(self):
        # `pm` missing from PATH is not the same as the package being gone.
        # Conflating them turns a broken environment into a confident lie.
        block = self._verb_block("hudpkg")
        self.assertIn("pm path com.lcs.hud", block)
        self.assertIn("echo installed", block)
        self.assertIn("echo absent", block)
        self.assertIn("echo unknown", block)
        self.assertIn("command -v pm", block)

    def test_writes_are_refused_when_the_panel_is_dead(self):
        # The bug: the write "succeeds" into a directory nobody polls.
        block = self._hud_block()
        self.assertIn("panel=dead", block)
        self.assertIn("exit 1", block)

    def _refusal_guard(self):
        # The hud block has three `case "$sub" in` statements: one decides
        # which verbs may wake the panel, one decides which writes are refused,
        # one dispatches the verb. The refusal guard is the one that mentions
        # panel=dead, so locate it by that marker instead of by position --
        # position-based slicing silently grabbed the wrong case and made a
        # passing test mean nothing.
        block = self._hud_block()
        i = block.index("panel=dead")
        start = block.rindex('case "$sub" in', 0, i)
        return block[start:block.index("esac", i)]

    def test_status_still_runs_when_the_panel_is_dead(self):
        # Refusing every verb would remove the only way to find out why.
        self.assertNotIn("status)", self._refusal_guard())

    def test_pause_is_never_refused(self):
        # The host gate reads hud.ctl through this same verb. If a dead panel
        # made `pause` fail, the human would lose the off switch exactly when
        # the panel is broken.
        guard = self._refusal_guard()
        self.assertNotIn("pause)", guard)
        self.assertNotIn("run)", guard)
        self.assertIn("say|beat|publish", guard)

    def test_status_prints_liveness_before_the_path(self):
        # dir= looked right while the panel was dead. panel= must come first.
        block = self.sh.split("status)", 1)[1].split(";;", 1)[0]
        self.assertLess(block.index('echo "panel=$panel'),
                        block.index('echo "dir=$D"'))

    def test_only_writes_may_wake_the_panel(self):
        # `status` runs before every action; it must not spawn an app or wait
        # three seconds for one that will not start. Only the verbs whose
        # output a live panel actually consumes are allowed to start it.
        block = self._hud_block()
        i = block.index('case "$sub" in')
        wake_case = block[i:block.index("esac", i)]
        self.assertIn("say|beat|publish", wake_case)
        # The dispatch case must not be the thing that starts the app.
        self.assertNotIn("status)", wake_case)
        after = block[block.index("esac", i):block.index("pkg=${pkg", i)]
        self.assertIn('if [ -z "$P" ]', after)
        self.assertIn("am start", after)

    def test_host_say_reports_a_stale_card_instead_of_nothing(self):
        # hud_say used to return quietly whenever the transport worked but the
        # verb said nothing -- the exact shape of "wrote fine, nothing renders".
        m = re.search(r"^def hud_say\(.*?(?=^def |\Z)", self.py, re.S | re.M)
        self.assertIsNotNone(m)
        body = m.group(0)
        self.assertIn("eyes.sh hud on", body)
        self.assertIn("stale", body)

    def test_gate_survives_a_failed_pause_notice(self):
        # hud_publish goes through sh(), which raises SystemExit. Since v1.4.1
        # eyes.sh also refuses to publish into a dead panel, so the pause path
        # must not turn a delivered refusal into a traceback.
        m = re.search(r"^def gate\(.*?(?=^def |\Z)", self.py, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertIn("except (Exception, SystemExit)", m.group(0))


class HudPublish(unittest.TestCase):
    """Publishing prose into the panel dir must not depend on quoting."""

    def setUp(self):
        self.sh = io.open(os.path.join(ROOT, "android", "eyes.sh"),
                          encoding="utf-8").read()
        self.py = io.open(os.path.join(ROOT, "host", "phone.py"),
                          encoding="utf-8").read()

    def _sh_block(self, name):
        # Anchor on a whole-line verb label ("      publish)"), not on a bare
        # substring: v1.4.1 added `say|beat|publish)` to the wake-up case, and
        # a bare "publish)" then matched there instead, so these tests were
        # asserting things about the wrong lines while still passing.
        pat = re.compile(r"^\s+" + re.escape(name) + r"\)\s*$", re.M)
        m = pat.search(self.sh)
        self.assertIsNotNone(m, f"no verb label for {name}")
        return self.sh[m.end():self.sh.index(";;", m.end())]

    def test_publish_takes_the_body_from_a_file(self):
        # The destination is reachable only via `nsenter ... sh -c "..."`, so
        # an inline body would need three levels of quoting. One apostrophe in
        # Chinese prose truncated the status silently; a file has no quoting.
        block = self._sh_block("publish")
        self.assertIn("$OUT/$name.out", block)
        self.assertIn("cat", block)

    def test_publish_forces_a_readable_mode(self):
        # /sdcard hands out 0640 owned by the writer. cp preserves that, and a
        # root-owned 0640 file inside the panel's own directory is one the
        # panel cannot open: correct on disk, empty card on screen. Measured.
        block = self._sh_block("publish")
        self.assertIn("chmod 0644", block)

    def test_say_builds_the_card_from_argv(self):
        # argv has no escaping layer, so Chinese punctuation and quotes cost
        # nothing. This is the verb an on-device agent should use.
        block = self._sh_block("say")
        for field in ("state=", "task=", "think=", "step=", "ts="):
            self.assertIn(field, block)

    def test_host_say_delegates_to_the_device_verb(self):
        # The host must not rebuild the body itself: that would reintroduce the
        # quoting problem on the way in.
        m = re.search(r"^def hud_say\(.*?(?=^def |\Z)", self.py, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertIn("eyes.sh hud say", m.group(0))

    def test_host_paused_reads_through_the_device(self):
        # Reading hud.ctl from the host filesystem only works when the host
        # shares a filesystem with the panel, which it does not. Ask the device.
        m = re.search(r"^def hud_paused\(.*?(?=^def |\Z)", self.py, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertIn("eyes.sh hud status", m.group(0))
        self.assertIn("ctl=", m.group(0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
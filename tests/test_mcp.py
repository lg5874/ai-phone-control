#!/usr/bin/env python3
"""Device-free tests for the MCP adapter.

The failure these pin: an MCP server that answers `tools/list` but mistranslates
arguments, or that reports "the label is not on screen" as a hard error. Both
look fine in a client's UI and both make a model do the wrong thing -- the first
taps a wrong spot, the second retries forever instead of scrolling.

A fake CLI stands in for `host/phone.py`, so nothing here needs a phone.

Run:  python3 tests/test_mcp.py
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

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "adapters" / "mcp" / "phone_mcp.py"

# The fake CLI only has to be honest about argv and exit codes: those are the
# two things the adapter is responsible for. Real phone behaviour is covered by
# tests/test_phone_emit.py and tests/test_ui.py.
FAKE = textwrap.dedent("""\
#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args, ensure_ascii=False) + "\\n")
cmd = args[0]
if cmd == "ui":
    print("-- 1 actionable node")
    print("C--- ( 630, 607) 隐私 #vlist_content")
    sys.exit(0)
if cmd == "tap-text":
    if args[1] == "不存在":
        print("no node matching '不存在'", file=sys.stderr)
        sys.exit(1)
    print(f"-> {args[1]} at (630,607)")
    sys.exit(0)
print("ok")
sys.exit(0)
""")


class Client:
    """A minimal MCP client: one JSON per line in, one JSON per line out."""

    def __init__(self, env: dict):
        self.next_id = 0
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )

    def rpc(self, method: str, params: dict | None = None) -> dict:
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()
        line = self.proc.stdout.readline()
        if not line:
            raise AssertionError(f"server closed the stream on {method} "
                                 f"(stderr: {self.proc.stderr.read()!r})")
        return json.loads(line)

    def call(self, name: str, arguments: dict | None = None) -> dict:
        reply = self.rpc("tools/call", {"name": name,
                                        "arguments": arguments or {}})
        assert "result" in reply, reply
        return reply["result"]

    def text(self, name: str, arguments: dict | None = None) -> str:
        result = self.call(name, arguments)
        return result["content"][0]["text"]

    def close(self) -> None:
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        self.proc.wait(timeout=15)
        for stream in (self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except OSError:
                pass


class McpAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.log = self.dir / "argv.log"
        fake = self.dir / "fake_phone.py"
        fake.write_text(FAKE, encoding="utf-8")
        fake.chmod(0o755)
        self.env = {**os.environ, "PHONE_CLI": str(fake),
                    "FAKE_LOG": str(self.log), "PHONE_EMIT": ""}
        self.client = Client(self.env)

    def tearDown(self):
        self.client.close()
        self.tmp.cleanup()

    def argv_seen(self, index: int = -1) -> list[str]:
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return json.loads(lines[index])

    # -- protocol -----------------------------------------------------------
    def test_initialize_reports_tools_capability(self):
        reply = self.client.rpc("initialize", {"protocolVersion": "2024-11-05"})
        result = reply["result"]
        self.assertEqual(result["serverInfo"]["name"], "phone-control")
        self.assertIn("tools", result["capabilities"])
        self.assertTrue(result["protocolVersion"])

    def test_tools_list_is_complete_and_leaks_no_internals(self):
        tools = self.client.rpc("tools/list")["result"]["tools"]
        names = {t["name"] for t in tools}
        self.assertEqual(len(tools), 11)
        for expected in ("phone_ui", "phone_tap_text", "phone_tap_xy",
                         "phone_swipe", "phone_press_key", "phone_type",
                         "phone_screenshot", "phone_foreground"):
            self.assertIn(expected, names)
        for t in tools:
            self.assertNotIn("build", t, "internal argument builder leaked")
            self.assertEqual(t["inputSchema"]["type"], "object")

    def test_unknown_tool_is_a_protocol_error(self):
        reply = self.client.rpc("tools/call", {"name": "phone_fly", "arguments": {}})
        self.assertEqual(reply["error"]["code"], -32602)

    def test_unknown_method_is_reported(self):
        reply = self.client.rpc("phone/teleport")
        self.assertEqual(reply["error"]["code"], -32601)

    def test_notifications_get_no_reply(self):
        # A notification has no id; writing a reply would desync the stream.
        self.client.proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.client.proc.stdin.flush()
        self.assertEqual(self.client.rpc("ping")["result"], {})

    # -- argument mapping ---------------------------------------------------
    def test_ui_forwards_max_age_and_strict(self):
        self.client.text("phone_ui", {"max_age": 5, "strict": True})
        self.assertEqual(self.argv_seen(), ["ui", "--max-age", "5.0", "--strict"])

    def test_tap_xy_maps_to_integers(self):
        self.client.text("phone_tap_xy", {"x": 630, "y": 1400})
        self.assertEqual(self.argv_seen(), ["tap", "630", "1400"])

    def test_swipe_preset_and_explicit(self):
        self.client.text("phone_swipe", {"gesture": "down"})
        self.assertEqual(self.argv_seen(), ["swipe", "down"])
        self.client.text("phone_swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4, "ms": 250})
        self.assertEqual(self.argv_seen(), ["swipe", "1", "2", "3", "4", "250"])

    def test_screenshot_scale(self):
        self.client.text("phone_screenshot", {"scale": 540})
        self.assertEqual(self.argv_seen(), ["shot", "--scale", "540"])

    def test_long_press_defaults_to_600ms(self):
        self.client.text("phone_long_press", {"x": 10, "y": 20})
        self.assertEqual(self.argv_seen(), ["long", "10", "20", "--ms", "600"])

    # -- the exit code is the contract --------------------------------------
    def test_success_carries_exit_zero(self):
        text = self.client.text("phone_ui")
        self.assertIn("隐私", text)
        self.assertTrue(text.rstrip().endswith("[exit 0]"))
        self.assertFalse(self.client.call("phone_ui")["isError"])

    def test_not_on_screen_is_an_answer_not_an_error(self):
        result = self.client.call("phone_tap_text", {"text": "不存在"})
        self.assertIn("no node matching", result["content"][0]["text"])
        self.assertFalse(result["isError"],
                         "exit 1 means 'not on this screen'; retrying is wrong, "
                         "scrolling is right, and an error flag confuses models")

    def test_bad_arguments_exit_two(self):
        result = self.client.call("phone_swipe", {})
        self.assertTrue(result["isError"])
        self.assertIn("[exit 2]", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
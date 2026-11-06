#!/usr/bin/env python3
"""phone_mcp -- the phone CLI as an MCP server. stdio, newline JSON, stdlib only.

    python3 adapters/mcp/phone_mcp.py

An MCP client (Claude Desktop, Cline, Cherry Studio, Cursor, anything that
speaks Model Context Protocol) spawns this process, gets eleven tools, and every
tool is one `host/phone.py` invocation. Nothing is reimplemented here: the
process-per-action design, the transports (adb / exec / emit) and the exit-code
contract are the same ones the CLI has, which is why this file is 200 lines and
not a second implementation.

The client's server config supplies the environment -- PHONE_TRANSPORT,
PHONE_SERIAL, PHONE_EXEC, PHONE_EMIT, PHONE_DIR -- exactly as a shell would.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# PHONE_CLI exists for tests: point the server at a fake CLI and the protocol
# can be exercised without a phone.
CLI = Path(os.environ.get("PHONE_CLI") or ROOT / "host" / "phone.py")
VERSION = "1.2.0"
PROTO = "2024-11-05"


# ------------------------------------------------------------------ plumbing
def run(argv: list[str], timeout: float = 120.0) -> tuple[int, str]:
    """Run one CLI invocation. The exit code is the contract, so we keep it."""
    try:
        p = subprocess.run([sys.executable, str(CLI), *argv],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, f"phone {argv[0]} timed out after {timeout:.0f}s"
    out = (p.stdout or "").rstrip()
    err = (p.stderr or "").rstrip()
    text = f"{out}\n{err}".strip() if err else out
    return p.returncode, text or "(no output)"


def _obj(props: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": props,
            "required": required or [], "additionalProperties": False}


def _b_ui(a):
    argv = ["ui"]
    if a.get("max_age") is not None:
        argv += ["--max-age", str(float(a["max_age"]))]
    if a.get("strict"):
        argv.append("--strict")
    if a.get("diff"):
        argv.append("--diff")
    return argv


def _b_shot(a):
    argv = ["shot"]
    if a.get("scale"):
        argv += ["--scale", str(int(a["scale"]))]
    return argv


def _b_observe(a):
    argv = ["observe"]
    if a.get("scale"):
        argv += ["--scale", str(int(a["scale"]))]
    mode = a.get("mode")
    if mode:
        argv += ["--mode", str(mode)]
    if a.get("diff"):
        argv.append("--diff")
    return argv


def _b_swipe(a):
    gesture = a.get("gesture")
    if gesture:
        return ["swipe", gesture]
    need = ["x1", "y1", "x2", "y2"]
    missing = [k for k in need if a.get(k) is None]
    if missing:
        raise ValueError(f"swipe needs gesture, or all of {' '.join(need)}")
    argv = ["swipe"] + [str(int(a[k])) for k in need]
    if a.get("ms") is not None:
        argv.append(str(int(a["ms"])))
    return argv


TOOLS = [
    {
        "name": "phone_ui",
        "description":
            "READ the phone screen as text: one line per actionable node, "
            "`flags (x,y) label #id`. This is the cheapest observation (~2 s) "
            "and the one to use in a loop. Call it before an action to find the "
            "target and after it to prove the screen changed. exit 1 = the label "
            "is not on this screen; exit 2 = the view is stale and you must "
            "refresh first (in emit mode the output carries the DEVICE_CMD).",
        "inputSchema": _obj({
            "max_age": {"type": "number",
                        "description": "emit mode: reuse a dump newer than this "
                                       "many seconds (default 30)"},
            "strict": {"type": "boolean",
                       "description": "emit mode: exit 2 instead of warning when "
                                      "the dump is stale"},
            "diff": {"type": "boolean",
                     "description": "print only what changed since your previous "
                                    "look: one added line beats forty unchanged "
                                    "ones when you are checking an action"},
        }),
        "build": _b_ui,
    },
    {
        "name": "phone_tap_text",
        "description":
            "Tap a visible label (text or content-desc). Prefer this over "
            "coordinates: labels survive resolution and layout changes. Reports "
            "where it tapped; exit 1 with `no node matching` means nothing was "
            "tapped. Success is not evidence -- call phone_ui afterwards.",
        "inputSchema": _obj({
            "text": {"type": "string", "description": "label to tap"},
        }, ["text"]),
        "build": lambda a: ["tap-text", str(a["text"])],
    },
    {
        "name": "phone_tap_xy",
        "description":
            "Tap absolute physical pixels. Use coordinates from phone_ui / "
            "phone_observe, never from a downscaled screenshot.",
        "inputSchema": _obj({
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        }, ["x", "y"]),
        "build": lambda a: ["tap", str(int(a["x"])), str(int(a["y"]))],
    },
    {
        "name": "phone_long_press",
        "description": "Long press at absolute pixels (default 600 ms).",
        "inputSchema": _obj({
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "ms": {"type": "integer", "description": "hold duration, default 600"},
        }, ["x", "y"]),
        "build": lambda a: ["long", str(int(a["x"])), str(int(a["y"])),
                            "--ms", str(int(a.get("ms") or 600))],
    },
    {
        "name": "phone_swipe",
        "description":
            "Swipe. Either a preset (up/down/left/right, scaled from the real "
            "screen size) or explicit pixels X1 Y1 X2 Y2 [MS]. Presets survive a "
            "change of phone; explicit numbers do not.",
        "inputSchema": _obj({
            "gesture": {"type": "string", "enum": ["up", "down", "left", "right"]},
            "x1": {"type": "integer"}, "y1": {"type": "integer"},
            "x2": {"type": "integer"}, "y2": {"type": "integer"},
            "ms": {"type": "integer"},
        }),
        "build": _b_swipe,
    },
    {
        "name": "phone_press_key",
        "description":
            "Press a key by name: back, home, enter, recents, power, volume_up, "
            "delete, tab, escape, or any KEYCODE_* name.",
        "inputSchema": _obj({
            "name": {"type": "string"},
        }, ["name"]),
        "build": lambda a: ["key", str(a["name"])],
    },
    {
        "name": "phone_type",
        "description":
            "Type into the focused field. ASCII only: Android's `input text` "
            "injects key events, so CJK is silently dropped while the command "
            "still exits 0. For Chinese, paste through the clipboard and confirm "
            "with phone_ui. Spaces are escaped for you.",
        "inputSchema": _obj({
            "text": {"type": "string"},
        }, ["text"]),
        "build": lambda a: ["type", str(a["text"])],
    },
    {
        "name": "phone_screenshot",
        "description":
            "Screenshot to a file and return its path and size. Use only when "
            "text is not enough: a canvas, a video, a game, a WebView with no "
            "tree. Downscale to keep the pixels small.",
        "inputSchema": _obj({
            "scale": {"type": "integer",
                      "description": "downscale width in px, 0 = physical"},
        }),
        "build": _b_shot,
    },
    {
        "name": "phone_observe",
        "description":
            "The widest observation, and the most expensive: screenshot + tree "
            "+ foreground. Do not reach for it by reflex -- pick the mode. "
            "mode=ui is the same tree as phone_ui (no pixels, ~2 s). mode=shot "
            "is pixels only, for a canvas or a game with no tree. mode=full is "
            "both. Add diff=true to get what changed since your last diff call "
            "instead of the whole tree: after a tap the honest answer is "
            "usually one added line, not forty unchanged ones.",
        "inputSchema": _obj({
            "scale": {"type": "integer",
                      "description": "downscale width in px, 0 = physical"},
            "mode": {"type": "string", "enum": ["full", "ui", "shot"],
                     "description": "full (default) = pixels + tree; ui = tree "
                                    "only; shot = pixels only"},
            "diff": {"type": "boolean",
                     "description": "print only what changed since the previous "
                                    "diff observation"},
        }),
        "build": _b_observe,
    },
    {
        "name": "phone_foreground",
        "description": "Which app/activity is in front. Cheaper than a full "
                       "tree and the fastest way to confirm a tap opened "
                       "something. A UI signal, not a proof of progress.",
        "inputSchema": _obj({}),
        "build": lambda a: ["top"],
    },
    {
        "name": "phone_size",
        "description": "Screen geometry (physical pixels). Needed only when you "
                       "compute coordinates yourself.",
        "inputSchema": _obj({}),
        "build": lambda a: ["size"],
    },
]

BY_NAME = {t["name"]: t for t in TOOLS}

# Tool selection, Windows-MCP style: PHONE_TOOLS whitelists, PHONE_EXCLUDE_TOOLS
# blocks. Both take comma-separated tool names; PHONE_TOOLS is the final say
# when both are set. A slimmed list keeps small agents from picking the wrong
# (most expensive) tool.
def _names_from_env(var: str) -> set[str] | None:
    raw = os.environ.get(var, "").strip()
    if not raw:
        return None
    names = {n.strip() for n in raw.split(",") if n.strip()}
    unknown = names - BY_NAME.keys()
    if unknown:
        raise SystemExit(f"{var} names unknown tools: {', '.join(sorted(unknown))}"
                         f" (valid: {', '.join(sorted(BY_NAME))})")
    return names

def public(t: dict) -> dict:
    return {k: v for k, v in t.items() if k != "build"}

def effective_tools() -> list[dict]:
    # PHONE_TOOLS is the final say when set; only when it is absent does
    # PHONE_EXCLUDE_TOOLS subtract from the full set.
    allow = _names_from_env("PHONE_TOOLS")
    if allow is not None:
        return [t for t in TOOLS if t["name"] in allow]
    deny = _names_from_env("PHONE_EXCLUDE_TOOLS") or set()
    return [t for t in TOOLS if t["name"] not in deny]


def call(name: str, args: dict) -> tuple[int, str]:
    try:
        argv = BY_NAME[name]["build"](args)
    except (KeyError, TypeError, ValueError) as e:
        return 2, f"bad arguments for {name}: {e}"
    return run(argv)


# ---------------------------------------------------------------- MCP server
def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    if not CLI.exists():
        print(f"missing {CLI}; this file must live inside the repository",
              file=sys.stderr)
        return 1
    # Clients hide stderr behind a "server log" pane. Put the one line that
    # explains a silent no-op there: which transport this process will use.
    mode = ("emit" if os.environ.get("PHONE_EMIT") == "1"
            else os.environ.get("PHONE_TRANSPORT", "adb"))
    print(f"phone_mcp {VERSION}: transport={mode} cli={CLI}"
          f" tools={len(effective_tools())}/{len(TOOLS)}", file=sys.stderr)
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            send({"jsonrpc": "2.0", "id": None,
                  "error": {"code": -32700, "message": "parse error"}})
            continue
        if not isinstance(msg, dict):
            continue
        mid = msg.get("id")
        method = msg.get("method")

        if method == "initialize":
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": PROTO,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "phone-control", "version": VERSION},
            }})
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            send({"jsonrpc": "2.0", "id": mid,
                  "result": {"tools": [public(t) for t in effective_tools()]}})
        elif method == "tools/call":
            params = msg.get("params") or {}
            name = params.get("name")
            args = params.get("arguments") or {}
            if name not in BY_NAME:
                send({"jsonrpc": "2.0", "id": mid,
                      "error": {"code": -32602,
                                "message": f"unknown tool {name!r}"}})
                continue
            code, text = call(name, args)
            send({"jsonrpc": "2.0", "id": mid, "result": {
                "content": [{"type": "text",
                             "text": f"{text}\n\n[exit {code}]"}],
                # exit 1 is a valid answer ("not on screen"), not a failure
                "isError": code not in (0, 1),
            }})
        elif method == "ping":
            send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            send({"jsonrpc": "2.0", "id": mid,
                  "error": {"code": -32601,
                            "message": f"method not found: {method}"}})
    return 0


if __name__ == "__main__":
    sys.exit(main())

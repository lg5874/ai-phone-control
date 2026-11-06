#!/usr/bin/env python3
"""phone -- one-shot Android automation for LLM agents.

    phone observe            # screenshot + UI tree + foreground app
    phone ui                 # just the flattened UI tree (cheap, no pixels)
    phone tap 630 1400
    phone tap-text "登录"     # tap by visible label, no coordinates needed
    phone type "hello"
    phone swipe up
    phone key back
    phone shot               # screenshot path + size only

Every subcommand starts a process, does its work, and exits. Nothing persists.
That is the entire design. An agent pays ~0.4 s per look and 0 % CPU between
looks. See android/eyes.sh for why streaming was rejected.

TRANSPORT
    Two ways to reach the device, chosen by $PHONE_TRANSPORT:

    adb      (default) run `adb -s $PHONE_SERIAL shell ...`
    exec     run `$PHONE_EXEC '<cmd>'` -- for on-device agents, KernelSU,
             or any wrapper that already has a root shell. This is what you
             want when the agent itself lives on the phone.

SIZING
    Screenshots come back at physical resolution (1260x2800 here = 422 KB).
    `--scale` downsamples before the model sees it; coordinates stay physical,
    so a model reading a 540-wide image must not be given the raw pixel grid.
    `phone ui` avoids the problem entirely: it returns text with real coords.
"""
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI_PY = HERE / "ui.py"

REMOTE_DIR = os.environ.get("PHONE_DIR", "/sdcard/lcs")
WORK = Path(os.environ.get("PHONE_WORK", "/tmp/phone"))
TRANSPORT = os.environ.get("PHONE_TRANSPORT", "adb")
SERIAL = os.environ.get("PHONE_SERIAL", "")
EXEC_WRAP = os.environ.get("PHONE_EXEC", "su -c")
# emit mode: we cannot reach the device, so print the command and let the
# caller (an agent with its own shell tool) run it, then call us again.
EMIT = os.environ.get("PHONE_EMIT") == "1"


# --------------------------------------------------------------- transports
def sh(cmd: str, timeout: int = 60) -> str:
    """Run one command on the device. Returns stdout, raises on failure."""
    if EMIT:
        # The caller executes this and feeds the output back via --ingest.
        print(f"DEVICE_CMD: {cmd}")
        return ""

    if TRANSPORT == "adb":
        argv = ["adb"]
        if SERIAL:
            argv += ["-s", SERIAL]
        argv += ["shell", cmd]
    elif TRANSPORT == "exec":
        argv = shlex.split(EXEC_WRAP) + [cmd]
    else:
        raise SystemExit(f"PHONE_TRANSPORT={TRANSPORT!r} not one of adb|exec")

    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = (r.stderr or r.stdout or "").strip()
        raise SystemExit(f"device command failed ({r.returncode}): {err}")
    return r.stdout


def sh_ok(cmd: str, timeout: int = 60) -> str:
    """Same as sh() but tolerates a nonzero exit -- for probes."""
    try:
        return sh(cmd, timeout)
    except SystemExit:
        return ""


# ------------------------------------------------------------------ helpers
def eyes(*args: str) -> str:
    """Invoke eyes.sh on the device."""
    return sh(f"sh {REMOTE_DIR}/eyes.sh " + " ".join(shlex.quote(a) for a in args))


def pull(remote: str, local: Path) -> Path:
    local.parent.mkdir(parents=True, exist_ok=True)
    if EMIT:
        print(f"DEVICE_PULL: {remote} -> {local}")
        return local
    if TRANSPORT == "adb":
        argv = ["adb"] + (["-s", SERIAL] if SERIAL else []) + ["pull", remote, str(local)]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            raise SystemExit(f"adb pull failed: {(r.stderr or '').strip()}")
    else:
        # exec transport: the remote dir is already local to this process
        if not Path(remote).exists():
            raise SystemExit(f"cannot read {remote}")
        local.write_bytes(Path(remote).read_bytes())
    return local


def scale_image(src: Path, width: int, quality: int = 5) -> Path:
    """Downscale with ffmpeg if available, else return the original."""
    if not width:
        return src
    dst = src.with_name(f"{src.stem}_{width}.jpg")
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(src), "-vf", f"scale={width}:-1",
         "-q:v", str(quality), str(dst)],
        capture_output=True, text=True,
    )
    return dst if r.returncode == 0 and dst.exists() else src


def ui_nodes(xml_path: Path):
    """Shell out to ui.py so there is one implementation of the filter."""
    r = subprocess.run([sys.executable, str(UI_PY), "parse", str(xml_path), "--json"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return []
    import json
    return json.loads(r.stdout)


# ---------------------------------------------------------------- commands
def cmd_size(a):
    print(eyes("size").strip())
    return 0


def cmd_top(a):
    print(eyes("top").strip())
    return 0


def cmd_shot(a):
    remote = f"{REMOTE_DIR}/shot.png"
    eyes("shot", remote)
    local = pull(remote, WORK / "shot.png")
    if EMIT:
        return 0
    if a.scale:
        local = scale_image(local, a.scale)
    print(f"{local} {local.stat().st_size} B")
    return 0


def cmd_dump(a):
    remote = f"{REMOTE_DIR}/ui.xml"
    eyes("dump", remote)
    local = pull(remote, WORK / "ui.xml")
    if EMIT:
        return 0
    if a.raw:
        print(local.read_text(encoding="utf-8", errors="replace"))
        return 0
    r = subprocess.run([sys.executable, str(UI_PY), "parse", str(local), *(
        ["--json"] if a.json else [])], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return r.returncode


def fresh(path: Path, max_age: float = 30.0) -> bool:
    """True if path exists and was written recently."""
    try:
        return path.exists() and (time.time() - path.stat().st_mtime) < max_age
    except OSError:
        return False


def cmd_ui(a):
    """Text-only observation: cheapest way to see what is on screen.

    In emit mode we cannot run anything, but $REMOTE_DIR is on shared storage
    (/sdcard), which this process can read. So we parse whatever is there. If
    the file is missing we say so and print the command that would refresh it.
    """
    if EMIT:
        shared = Path(f"{REMOTE_DIR}/ui.xml")
        if not shared.exists():
            eyes("dump", f"{REMOTE_DIR}/ui.xml")
            print("# then re-run: phone ui", file=sys.stderr)
            return 0
        if not fresh(shared, a.max_age):
            print(f"# warning: {shared} is "
                  f"{time.time() - shared.stat().st_mtime:.0f}s old",
                  file=sys.stderr)
        r = subprocess.run([sys.executable, str(UI_PY), "parse", str(shared)],
                           capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode
    a.json = False
    a.raw = False
    return cmd_dump(a)


def cmd_observe(a):
    remote_png = f"{REMOTE_DIR}/shot.png"
    remote_xml = f"{REMOTE_DIR}/ui.xml"
    print(eyes("observe", REMOTE_DIR).strip())
    png = pull(remote_png, WORK / "shot.png")
    xml = pull(remote_xml, WORK / "ui.xml")
    if EMIT:
        return 0
    if a.scale:
        png = scale_image(png, a.scale)
    print(f"\n--- screenshot: {png} ({png.stat().st_size} B)")
    print("--- ui:")
    r = subprocess.run([sys.executable, str(UI_PY), "parse", str(xml)],
                       capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    return 0


def cmd_tap(a):
    print(eyes("tap", str(a.x), str(a.y)).strip())
    return 0


def cmd_tap_text(a):
    remote = f"{REMOTE_DIR}/ui.xml"
    eyes("dump", remote)
    local = pull(remote, WORK / "ui.xml")
    if EMIT:
        return 0
    nodes = ui_nodes(local)
    needle = a.text.lower()
    hits = [n for n in nodes
            if n["clickable"] and (needle in n["label"].lower()
                                   or needle in n["id"].lower())]
    if not hits:
        hits = [n for n in nodes
                if needle in n["label"].lower() or needle in n["id"].lower()]
    if not hits:
        print(f"no node matching {a.text!r}", file=sys.stderr)
        return 1
    n = hits[0]
    x, y = n["center"]
    print(f"-> {n['label'] or n['id']} at ({x},{y})")
    print(eyes("tap", str(x), str(y)).strip())
    return 0


def cmd_long(a):
    print(eyes("long", str(a.x), str(a.y), str(a.ms)).strip())
    return 0


def cmd_swipe(a):
    if len(a.args) == 1:
        # named gestures, tuned for a 1260x2800 portrait screen
        preset = {
            "up":    ("630", "2000", "630", "800", "300"),
            "down":  ("630", "800", "630", "2000", "300"),
            "left":  ("1100", "1400", "200", "1400", "300"),
            "right": ("200", "1400", "1100", "1400", "300"),
        }.get(a.args[0])
        if not preset:
            print(f"unknown preset {a.args[0]!r}", file=sys.stderr)
            return 2
        print(eyes("swipe", *preset).strip())
        return 0
    if len(a.args) < 4:
        print("swipe needs a preset, or X1 Y1 X2 Y2 [MS]", file=sys.stderr)
        return 2
    print(eyes("swipe", *[str(v) for v in a.args]).strip())
    return 0


def cmd_key(a):
    print(eyes("key", a.name).strip())
    return 0


def cmd_type(a):
    print(eyes("text", a.text).strip())
    return 0


def cmd_install(a):
    """Push eyes.sh to the device and make it runnable."""
    src = HERE.parent / "android" / "eyes.sh"
    if not src.exists():
        raise SystemExit(f"missing {src}")
    if TRANSPORT == "adb":
        argv = ["adb"] + (["-s", SERIAL] if SERIAL else []) + ["push", str(src), f"{REMOTE_DIR}/eyes.sh"]
        subprocess.run(argv, check=True, capture_output=True)
    else:
        Path(REMOTE_DIR).mkdir(parents=True, exist_ok=True)
        (Path(REMOTE_DIR) / "eyes.sh").write_bytes(src.read_bytes())
    sh(f"chmod 755 {REMOTE_DIR}/eyes.sh")
    print(f"installed {REMOTE_DIR}/eyes.sh")
    print(eyes("size").strip())
    return 0


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        prog="phone", description="one-shot Android automation for agents",
        formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("install", help="push eyes.sh to the device").set_defaults(fn=cmd_install)
    sub.add_parser("size", help="screen geometry").set_defaults(fn=cmd_size)
    sub.add_parser("top", help="foreground app").set_defaults(fn=cmd_top)
    p = sub.add_parser("ui", help="UI tree as text (cheapest observation)")
    p.add_argument("--max-age", type=float, default=30.0,
                   help="emit mode: reuse a dump newer than this many seconds")
    p.set_defaults(fn=cmd_ui)
    sub.add_parser("observe", help="screenshot + UI tree").set_defaults(fn=cmd_observe)
    sub.add_parser("shot", help="screenshot only").set_defaults(fn=cmd_shot)

    p = sub.add_parser("dump", help="raw or JSON UI tree")
    p.add_argument("--raw", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_dump)

    p = sub.add_parser("tap", help="tap absolute pixels")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.set_defaults(fn=cmd_tap)

    p = sub.add_parser("tap-text", help="tap by visible label")
    p.add_argument("text")
    p.set_defaults(fn=cmd_tap_text)

    p = sub.add_parser("long", help="long press")
    p.add_argument("x", type=int)
    p.add_argument("y", type=int)
    p.add_argument("--ms", type=int, default=600)
    p.set_defaults(fn=cmd_long)

    p = sub.add_parser("swipe", help="swipe preset or explicit")
    p.add_argument("args", nargs="+")
    p.set_defaults(fn=cmd_swipe)

    p = sub.add_parser("key", help="keyevent, e.g. back / home")
    p.add_argument("name")
    p.set_defaults(fn=cmd_key)

    p = sub.add_parser("type", help="type text into the focused field")
    p.add_argument("text")
    p.set_defaults(fn=cmd_type)

    for name in ("observe", "shot"):
        sub.choices[name].add_argument("--scale", type=int, default=0,
                                       help="downscale width in px, 0 = keep")

    a = ap.parse_args()
    if not hasattr(a, "scale"):
        a.scale = 0
    WORK.mkdir(parents=True, exist_ok=True)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
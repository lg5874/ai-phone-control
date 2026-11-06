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

# An inherited PHONE_EMIT=1 silently turns a working adb/exec setup into a
# printer: the tool emits `DEVICE_CMD: ...` and exits 0, and an agent that only
# reads exit codes concludes the phone did the thing. Measured, not imagined --
# a leftover export from an earlier shell cost a whole debugging round. Say it
# once, on stderr, where logs keep it.
if EMIT and (os.environ.get("PHONE_TRANSPORT")
             or os.environ.get("PHONE_EXEC")
             or os.environ.get("PHONE_SERIAL")):
    print("warning: PHONE_EMIT=1 overrides PHONE_TRANSPORT/PHONE_EXEC; this "
          "process prints DEVICE_CMD instead of running it", file=sys.stderr)

# Exit codes are the only contract an agent can key on without reading prose.
# 1 and 2 already existed; 3-6 exist because "the tap did nothing" and "you
# were looking at the wrong app" were indistinguishable from "all good".
EXIT_OK = 0
EXIT_NOT_FOUND = 1
EXIT_STALE = 2
EXIT_WRONG_APP = 3
EXIT_HUMAN_BUSY = 4
EXIT_AMBIGUOUS = 5
EXIT_SCREEN_OFF = 6


# --------------------------------------------------------------- transports
def sh(cmd: str, timeout: int = 60) -> str:
    """Run one command on the device. Returns stdout, raises on failure."""
    if EMIT:
        # The caller runs this itself. Whatever it produces lands in
        # $REMOTE_DIR, which we then read in place (see view()).
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


def view(remote_name: str) -> Path:
    """Local path to an artifact the device produced.

    adb: pull it into WORK. emit: the agent and the device share $REMOTE_DIR,
    so the file is readable in place -- and a fake pull that writes nothing is
    worse than no pull at all, so we fail loudly when the device has not
    produced it yet.
    """
    remote = f"{REMOTE_DIR}/{remote_name}"
    if EMIT:
        if not Path(remote).exists():
            raise SystemExit(
                f"device has not produced {remote} yet "
                f"-- run the DEVICE_CMD above, then re-run this command")
        return Path(remote)
    return pull(remote, WORK / remote_name)


def warn_stale(path: Path, max_age: float) -> None:
    """emit: say out loud how old the view is instead of implying it is live."""
    if not path.exists():
        return
    age = time.time() - path.stat().st_mtime
    if age > max_age:
        print(f"# warning: {path} is {age:.0f}s old; "
              f"refresh with: sh {REMOTE_DIR}/eyes.sh dump {path}",
              file=sys.stderr)


# ------------------------------------------------------------ safety gates
def state_probe() -> dict:
    """wake / keyguard / foreground in one device round trip."""
    out = sh_ok(f"sh {REMOTE_DIR}/eyes.sh state")
    facts = {}
    for line in out.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            facts[key.strip()] = value.strip()
    return facts


def human_now(window: float = 1.0) -> bool:
    """True if a real finger touched the panel within `window` seconds.

    `input tap` injects below the input layer, so injected taps are invisible
    to this probe by construction. What it hears is the human.
    """
    out = sh_ok(f"sh {REMOTE_DIR}/eyes.sh human {max(1, int(round(window)))}")
    return "human: yes" in out


def gate(a) -> int:
    """Pre-flight: awake? right app? human not on the glass?

    Returns EXIT_OK when clear to act. Every action command calls this first;
    that ordering is the point -- v1.1 acted first and explained afterwards.
    """
    if getattr(a, "force", False):
        return EXIT_OK
    facts = state_probe()
    wake = facts.get("wake", "")
    if wake and wake not in ("Awake", "unknown"):
        print(f"SCREEN_OFF: wakefulness={wake}; wake it first "
              f"(`phone key wakeup`, then `phone swipe up` if locked)",
              file=sys.stderr)
        return EXIT_SCREEN_OFF
    expect = (getattr(a, "expect", "") or "").strip()
    front = facts.get("top", "")
    if expect and expect.lower() not in front.lower():
        print(f"WRONG_APP: expected {expect!r}, foreground is "
              f"{front or 'unknown'!r} -- nothing was done", file=sys.stderr)
        return EXIT_WRONG_APP
    window = getattr(a, "window", 1.0)
    if window and human_now(window):
        print(f"HUMAN_BUSY: a real finger touched the screen within "
              f"{window:g}s -- standing down, the human goes first",
              file=sys.stderr)
        return EXIT_HUMAN_BUSY
    return EXIT_OK


def add_safety(p, touch: bool = True):
    """Attach the pre-flight flags to an action subcommand."""
    p.add_argument("--expect", default="",
                   help="refuse (exit 3) unless this package is in front")
    if touch:
        p.add_argument("--window", type=float, default=1.0,
                       help="seconds to listen for a human finger; 0 = skip")
    p.add_argument("--force", action="store_true",
                   help="skip every pre-flight gate")
    return p


def group_hits(hits, tol: int = 12):
    """Collapse hits that share a centre -- one target, several nodes."""
    groups = []
    for n in hits:
        x, y = n["center"]
        for g in groups:
            if abs(x - g["x"]) <= tol and abs(y - g["y"]) <= tol:
                g["nodes"].append(n)
                break
        else:
            groups.append({"x": x, "y": y, "nodes": [n]})
    return groups


def pick_target(groups, pick: str):
    """Choose one of several same-label targets when the caller insisted."""
    clickable = [g for g in groups if g["nodes"][0]["clickable"]]
    cands = clickable or groups
    if pick == "bottom":
        return max(cands, key=lambda g: g["y"])
    if pick == "top":
        return min(cands, key=lambda g: g["y"])
    if pick == "largest":
        return max(cands, key=lambda g: g["nodes"][0]["size"][0] *
                   g["nodes"][0]["size"][1])
    return cands[0]


def screen_wh() -> tuple[int, int]:
    """Preset gesture geometry. Override with PHONE_SIZE=WxH, no probing."""
    raw = os.environ.get("PHONE_SIZE", "1260x2800")
    try:
        w, _, h = raw.partition("x")
        return int(w), int(h)
    except ValueError:
        return 1260, 2800


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
    if EMIT:
        # A printed command is not a fact. Read the probe observe wrote, and ask
        # for one when it is missing or stale instead of echoing the command
        # and letting the caller believe it saw the foreground app.
        p = Path(f"{REMOTE_DIR}/top.txt")
        if not fresh(p, 30.0):
            sh(f"sh {REMOTE_DIR}/eyes.sh top > {p}")
            print("# run the DEVICE_CMD above, then re-run: phone top",
                  file=sys.stderr)
            return 2
        print(p.read_text(encoding="utf-8").strip())
        return 0
    print(eyes("top").strip())
    return 0


def cmd_shot(a):
    eyes("shot", f"{REMOTE_DIR}/shot.png")
    local = view("shot.png")
    if a.scale:
        local = scale_image(local, a.scale)
    print(f"{local} {local.stat().st_size} B")
    return 0


def cmd_dump(a):
    eyes("dump", f"{REMOTE_DIR}/ui.xml")
    local = view("ui.xml")
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

    emit mode: the agent runs the DEVICE_CMD we print, then calls us again.
    $REMOTE_DIR is shared storage, so we parse it in place. A stale tree is
    flagged loudly here, and with --strict it is an error -- an agent that
    treats a five-minute-old tree as ground truth taps the wrong thing and
    then reports success, which is the failure mode this whole file exists
    to avoid.
    """
    if EMIT:
        shared = Path(f"{REMOTE_DIR}/ui.xml")
        # A fresh tree is the whole point of this subcommand: print nothing but
        # the tree. Only ask the agent to run something when we must refresh.
        if not fresh(shared, a.max_age):
            eyes("dump", f"{REMOTE_DIR}/ui.xml")
            if a.strict:
                print(f"# stale: {shared} is "
                      f"{time.time() - shared.stat().st_mtime:.0f}s old "
                      f"(> {a.max_age:.0f}s); run the DEVICE_CMD above, "
                      f"then re-run", file=sys.stderr)
                return 2
            shared = view("ui.xml")  # missing tree -> one clean error, no trace
            warn_stale(shared, a.max_age)
        r = subprocess.run([sys.executable, str(UI_PY), "parse", str(shared)],
                           capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode
    a.json = False
    a.raw = False
    return cmd_dump(a)


def cmd_observe(a):
    print(eyes("observe", REMOTE_DIR).strip())
    png = view("shot.png")
    xml = view("ui.xml")
    if EMIT:
        warn_stale(png, 30.0)
        warn_stale(xml, 30.0)
        t = Path(f"{REMOTE_DIR}/top.txt")
        if t.exists():
            print(f"\n--- foreground: "
                  f"{t.read_text(encoding='utf-8').strip()}")
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
    remote_xml = f"{REMOTE_DIR}/ui.xml"
    if EMIT:
        # Tapping yesterday's tree taps the wrong thing. Demand a refresh
        # instead of silently aiming at coordinates that have moved.
        if not fresh(Path(remote_xml), 30.0):
            eyes("dump", remote_xml)
            print("# stale tree; run the DEVICE_CMD above, then re-run",
                  file=sys.stderr)
            return 2
        local = view("ui.xml")
    else:
        eyes("dump", remote_xml)
        local = view("ui.xml")
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
        # named gestures, scaled from PHONE_SIZE (default 1260x2800) so they
        # survive a change of phone instead of tapping off-screen
        w, h = screen_wh()
        preset = {
            "up":    (w // 2, int(h * 0.71), w // 2, int(h * 0.29), 300),
            "down":  (w // 2, int(h * 0.29), w // 2, int(h * 0.71), 300),
            "left":  (int(w * 0.87), h // 2, int(w * 0.16), h // 2, 300),
            "right": (int(w * 0.16), h // 2, int(w * 0.87), h // 2, 300),
        }.get(a.args[0])
        if preset:
            preset = tuple(str(v) for v in preset)
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
    p.add_argument("--strict", action="store_true",
                   help="emit mode: exit 2 instead of warning on a stale dump")
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
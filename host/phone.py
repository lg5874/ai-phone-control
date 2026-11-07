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
# When phone.py runs inside a proot Ubuntu, the `su` on PATH is Ubuntu's, not
# Android's: it drops into a shell whose PATH has no /system/bin, so `input`
# resolves to nothing and every tap reports "input: not found" while root was
# granted perfectly well. Point PHONE_EXEC at the platform binary when the host
# is not the phone itself:
#     PHONE_EXEC='/system/bin/su -c'
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
# 7 exists because a human pressing "pause" on the panel must stop the agent
# before it touches the glass, not after. It is distinct from HUMAN_BUSY (4):
# 4 means a finger was there a moment ago, 7 means the human said stop and is
# still holding the wheel.
EXIT_PAUSED = 7


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


def sh_probe(cmd: str, timeout: int = 60) -> str:
    """sh(), but a *transport* failure is reported as a fact, not a crash.

    The failure this exists for: run phone.py inside a proot Ubuntu with
    PHONE_EXEC=/system/bin/sh and Python raises

        FileNotFoundError: [Errno 2] No such file or directory: '/system/bin/sh'

    before the device is ever contacted. proot has no /system, so the
    interpreter that runs eyes.sh does not exist on that filesystem. The
    traceback names a missing binary and says nothing about the fix, and the
    natural reading -- "the panel is broken" -- is wrong.

    sh() still raises SystemExit on a nonzero exit (a real device error). Only
    a missing executable is turned into an empty result, because that is the
    one case where the caller should fall through to another path.
    """
    try:
        return sh(cmd, timeout)
    except FileNotFoundError:
        return ""
    except subprocess.TimeoutExpired:
        return ""


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
        # exec transport: the remote dir is already local to this process.
        # exists() returns False for a permission-denied file, which would
        # blame the producer for a reader problem -- so distinguish the two.
        src = Path(remote)
        try:
            local.write_bytes(src.read_bytes())
        except FileNotFoundError:
            raise SystemExit(f"cannot read {remote}: not produced yet")
        except PermissionError:
            raise SystemExit(
                f"cannot read {remote}: permission denied for uid {os.getuid()}. "
                f"eyes.sh writes as the device's dump/screencap user; run "
                f"`chmod 0644 {remote}` or read it through the same uid that wrote it")
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


def hud_paused() -> bool:
    """Did the human press pause on the floating panel?

    The panel keeps `hud.ctl` in its own private directory, which is reachable
    only through that process's mount namespace (Android 11+ gives every app
    its own view of /data/user/0, so even root sees just its own package from a
    shell). `eyes.sh huddir` resolves the live path -- inside the namespace
    when the panel runs, the legacy /sdcard/lcs when it does not -- and
    `eyes.sh hud status` reads through it. Going through eyes.sh instead of
    composing nsenter here keeps the namespace trick in one place, on the
    device side, where the pid and the mount table actually live.

    Fail-open on purpose: an unreadable or empty control file means "keep
    going". A gate that halts the agent because a file was mid-write, or
    because the panel app was never installed, would be a worse bug than the
    one it prevents.
    """
    try:
        out = sh_ok(f"sh {REMOTE_DIR}/eyes.sh hud status 2>/dev/null")
    except Exception:
        return False
    for line in out.splitlines():
        if line.startswith("ctl="):
            return line[4:].strip().lower() == "pause"
    return False


def hud_beat(action: str) -> None:
    """Prove the agent is alive, once per action.

    This is deliberately not the same file as hud.status. `say` is the agent
    stating intent (task/think/step) and survives several actions; a beat is a
    fact that is true for one instant. Separate files, separate owners, no
    read-modify-write race.

    Why it exists: the panel judges liveness from `ts` in hud.status, so before
    this the card read "AI 已 40s 无更新" while the agent was tapping away,
    simply because nothing refreshed `ts` unless the agent remembered to call
    `say`. A status light that lies about liveness is worse than no light --
    the human cannot tell a thinking agent from a dead one.

    Never raises. A missing heartbeat must not fail an action that worked.
    """
    if EMIT:
        # Emit mode has no shell: the caller runs commands by hand, so an
        # automatic heartbeat would just be one more line of noise between
        # them and the action they asked for. Liveness is not meaningful when
        # a human is the transport.
        return
    try:
        hud_publish("hud.beat", f"ts={int(time.time() * 1000)}\nact={action}\n")
    except (Exception, SystemExit):
        # SystemExit is a BaseException, not an Exception: sh() raises it on a
        # device error, and a plain `except Exception` would let it escape and
        # kill a tap that had already succeeded. Both are swallowed here --
        # bookkeeping must never be the reason a real action reports failure.
        pass


def hud_publish(name: str, body: str) -> None:
    """Put `body` into the panel's directory as `name`.

    The body is written to $REMOTE_DIR/<name>.out on the shared filesystem
    first, then `eyes.sh hud publish` moves it into place. Two reasons, both
    learned the hard way:

    1. The destination lives in the panel's private dir, reachable only via
       `nsenter -t <pid> -m -- sh -c "..."`. Passing prose through that string
       needs three levels of quoting (host -> device shell -> nsenter -> sh);
       one apostrophe in an agent's Chinese sentence truncated the status
       silently. A file has no quoting rules.
    2. The shared staging dir is writable by whoever is driving the phone, so
       the panel app needs no root and no storage permission of its own.
    """
    body = body if body.endswith("\n") else body + "\n"
    staged = f"{REMOTE_DIR}/{name}.out"
    sh(f"printf '%s' {shlex.quote(body)} > {staged}")
    sh(f"sh {REMOTE_DIR}/eyes.sh hud publish {name}")


def hud_say(state: str, task: str, think: str = "", step: str = "") -> None:
    """Publish a whole card in one device round trip.

    Delegates to `eyes.sh hud say`, which builds the file from argv. Going
    through the device-side verb instead of composing the body here is the
    difference between "Chinese with an apostrophe works" and "the panel shows
    half a sentence": argv has no escaping layer.

    Returns quietly when the transport itself is missing (proot with no
    /system, no adb on PATH): the caller is a status update, and a status
    update must never be the reason a working run reports failure. cmd_say
    checks the result and says so out loud.
    """
    out = sh_probe(f"sh {REMOTE_DIR}/eyes.sh hud say "
                   + " ".join(shlex.quote(x) for x in (task, think, step, state)))
    if not out and not EMIT:
        # Distinguish "the verb ran and said nothing" from "we never reached
        # the device" by asking once, cheaply. A silent no-op here is the exact
        # failure that cost a day of staring at a blank panel.
        if not sh_probe("echo alive").strip():
            raise SystemExit(
                "cannot reach the device to publish status: "
                f"PHONE_TRANSPORT={TRANSPORT} PHONE_EXEC={EXEC_WRAP!r}. "
                "Inside a proot container there is no /system/bin/sh -- "
                "set PHONE_EMIT=1 and run the printed DEVICE_CMD by hand, "
                "or run phone.py on the device side.")


def hud_note(state: str, task: str, think: str = "", step: str = "") -> None:
    """Write hud.status. Shared by `say` and by the pause path in gate().

    Atomic on the device side (temp+rename in eyes.sh): the panel polls four
    times a second and must never render a half-written line.

    The body goes through hud_publish, i.e. via a file, because the panel's
    directory is reachable only through its own mount namespace and prose
    cannot survive being re-quoted three times on the way in.
    """
    body = (f"ts={int(time.time() * 1000)}\n"
            f"state={state}\n"
            f"task={task}\n"
            f"think={think}\n"
            f"step={step}\n")
    hud_publish("hud.status", body)


def gate(a) -> int:
    """Pre-flight: paused? awake? right app? human not on the glass?

    Returns EXIT_OK when clear to act. Every action command calls this first;
    that ordering is the point -- v1.1 acted first and explained afterwards.
    """
    # Pause outranks everything, including --force. A human who pressed the
    # button has taken the phone; no flag may override that, or --force becomes
    # a documented way to ignore the button.
    if hud_paused():
        print("PAUSED: the human pressed pause on the floating panel -- "
              "nothing was done. Wait for them to press 继续.", file=sys.stderr)
        # Tell the panel too, structurally rather than by hoping the agent
        # remembers: the moment a run stops is exactly when a human is looking
        # at the card and needs it to say so. Best effort -- the refusal above
        # already stands on its own.
        try:
            hud_note("paused", "暂停中 · 人类正在接管",
                     "已收到暂停信号，我停在这里等你", "等待继续")
        except Exception:
            pass
        return EXIT_PAUSED
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


def render_tree(xml: Path, want_diff: bool = False) -> int:
    """Print the tree, or what changed since the last render_tree call.

    The baseline lives in WORK/last.xml and is refreshed on every call, so
    --diff always means "since my previous look", whichever verb produced it.
    A first --diff call has no baseline: it prints the full tree rather than
    nothing, because "no output" is indistinguishable from "nothing changed".
    """
    previous = WORK / "last.xml"
    if want_diff and previous.exists():
        r = subprocess.run([sys.executable, str(UI_PY), "diff", str(previous), str(xml)],
                           capture_output=True, text=True)
    else:
        if want_diff:
            print("# no baseline yet: showing the full tree", file=sys.stderr)
        r = subprocess.run([sys.executable, str(UI_PY), "parse", str(xml)],
                           capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    # Copy rather than move: the dump is also the artifact a human may want.
    try:
        WORK.mkdir(parents=True, exist_ok=True)
        previous.write_bytes(xml.read_bytes())
    except OSError:
        pass  # a missing baseline only costs a full dump next time
    return r.returncode


def cmd_ui(a):
    """Text-only observation: cheapest way to see what is on screen.

    emit mode: the agent runs the DEVICE_CMD we print, then calls us again.
    $REMOTE_DIR is shared storage, so we parse it in place. A stale tree is
    flagged loudly here, and with --strict it is an error -- an agent that
    treats a five-minute-old tree as ground truth taps the wrong thing and
    then reports success, which is the failure mode this whole file exists
    to avoid.
    """
    want_diff = getattr(a, "diff", False)
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
        return render_tree(shared, want_diff)
    a.json = False
    a.raw = False
    eyes("dump", f"{REMOTE_DIR}/ui.xml")
    local = view("ui.xml")
    return render_tree(local, want_diff)


def cmd_observe(a):
    """Screenshot + tree + foreground, with the cost knob the caller needs.

    A full observation is ~422 KB of PNG plus 30-40 lines of tree. Most steps
    in a loop need one or the other, not both. --mode picks; --diff replaces
    the tree with what changed since the previous observation, which after a
    tap is usually one line instead of forty.
    """
    mode = getattr(a, "mode", "full") or "full"
    if mode == "ui":
        # cmd_ui reads --max-age/--strict, which only the `ui` subcommand
        # declares. Fill the defaults in instead of requiring the caller to
        # pass flags that belong to a different verb.
        a.max_age = getattr(a, "max_age", 30.0)
        a.strict = getattr(a, "strict", False)
        return cmd_ui(a)
    if mode == "shot":
        return cmd_shot(a)

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
    return render_tree(xml, getattr(a, "diff", False))


def cmd_tap(a):
    rc = gate(a)
    if rc:
        return rc
    hud_beat("tap")
    print(eyes("tap", str(a.x), str(a.y)).strip())
    return 0


def cmd_tap_text(a):
    rc = gate(a)
    if rc:
        return rc
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
    hud_beat("tap-text")
    print(f"-> {n['label'] or n['id']} at ({x},{y})")
    print(eyes("tap", str(x), str(y)).strip())
    return 0


def cmd_long(a):
    rc = gate(a)
    if rc:
        return rc
    hud_beat("long")
    print(eyes("long", str(a.x), str(a.y), str(a.ms)).strip())
    return 0


def cmd_swipe(a):
    rc = gate(a)
    if rc:
        return rc
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
        hud_beat("swipe")
        print(eyes("swipe", *preset).strip())
        return 0
    if len(a.args) < 4:
        print("swipe needs a preset, or X1 Y1 X2 Y2 [MS]", file=sys.stderr)
        return 2
    hud_beat("swipe")
    print(eyes("swipe", *[str(v) for v in a.args]).strip())
    return 0


def cmd_key(a):
    rc = gate(a)
    if rc:
        return rc
    hud_beat("key")
    print(eyes("key", a.name).strip())
    return 0


def cmd_type(a):
    rc = gate(a)
    if rc:
        return rc
    hud_beat("type")
    print(eyes("text", a.text).strip())
    return 0


def cmd_say(a):
    """Publish what the agent is doing, for the floating panel to display.

    This is the write half of the panel: the human sees `task`, the reasoning
    in `think`, and the current `step`. Atomic on the device side (temp+rename)
    because the panel polls four times a second and must never read a
    half-written line and show garbage.

    Deliberately not gated: telling the human what you are doing is never the
    thing that steals the screen.
    """
    hud_say(a.state, a.task, a.think, a.step)
    print(f"say: {a.state} | {a.task}")
    return 0


def cmd_beat(a):
    """Emit one heartbeat by hand (actions do this automatically).

    Useful when the agent is thinking for a long time between actions: the
    panel's liveness timer is 15 s, so a slow model needs to beat to stay
    green. Actions beat on their own; thinking does not.
    """
    hud_beat(a.what)
    print(f"beat: {a.what}")
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
    p.add_argument("--diff", action="store_true",
                   help="print what changed since the previous look")
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
    p = sub.add_parser("say", help="tell the floating panel what you are doing")
    p.add_argument("task", help="one line: what this run is trying to achieve")
    p.add_argument("--think", default="",
                   help="the reasoning the human should see (2-3 lines)")
    p.add_argument("--step", default="",
                   help="progress, e.g. 'step 2/5 - tapping the search box'")
    p.add_argument("--state", default="running",
                   help="running | done | error (default: running)")
    p.set_defaults(fn=cmd_say)

    p = sub.add_parser("beat",
                       help="heartbeat only (actions do this automatically)")
    p.add_argument("what", nargs="?", default="thinking",
                   help="what you are doing right now, e.g. 'thinking'")
    p.set_defaults(fn=cmd_beat)

    for name in ("observe", "shot"):
        sub.choices[name].add_argument("--scale", type=int, default=0,
                                       help="downscale width in px, 0 = keep")

    sub.choices["observe"].add_argument(
        "--mode", choices=("full", "ui", "shot"), default="full",
        help="full = pixels + tree (default); ui = tree only; shot = pixels only")
    sub.choices["observe"].add_argument(
        "--diff", action="store_true",
        help="print what changed since the last --diff observation instead of "
             "the whole tree")

    a = ap.parse_args()
    if not hasattr(a, "scale"):
        a.scale = 0
    WORK.mkdir(parents=True, exist_ok=True)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
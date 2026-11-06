#!/usr/bin/env python3
"""agent.py -- a worked example of driving ai-phone-control from a model loop.

This is not a framework. It is the smallest loop that actually finishes a task,
written out so you can see every decision an agent has to make:

    observe -> pick a target -> act -> verify -> repeat

Two things it demonstrates that are easy to get wrong:

1.  **Verify, do not assume.** After every tap it re-reads the foreground
    activity. A tap that lands on a dead area returns exit code 0 and does
    nothing, so "the command succeeded" is not evidence of progress.

2.  **Prefer text targets over pixels.** `find(label)` searches the UI tree;
    only fall back to coordinates when the tree is empty (canvas, video, game).

Run against a device with `phone.py` configured (any transport):

    python3 examples/agent.py --task "打开设置，进入电池页面"

The interesting part is `solve()` -- everything above it is plumbing.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOST = Path(__file__).resolve().parent.parent / "host"
PHONE = HOST / "phone.py"
UI = HOST / "ui.py"

# Mirror phone.py's two placements: pulled locally (adb) or read in place on
# shared storage (emit / on-device agent).
WORK = Path(os.environ.get("PHONE_WORK", "/tmp/phone"))
REMOTE = os.environ.get("PHONE_DIR", "/sdcard/lcs")
EMIT = os.environ.get("PHONE_EMIT") == "1"


def run(*argv, timeout=180):
    """Invoke phone.py / ui.py and return stdout."""
    r = subprocess.run([sys.executable, str(argv[0]), *map(str, argv[1:])],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"{argv[0].name} {argv[1:]} failed: "
                           f"{(r.stderr or r.stdout).strip()}")
    return r.stdout


def top_of():
    """Foreground activity, or a marker when there is nothing to read yet.

    In emit mode phone.py cannot ask the device anything; it reads the probe
    `observe` left in $REMOTE_DIR. Returning the printed command here would
    look like a real answer and quietly freeze the loop's progress check.
    """
    if EMIT:
        p = Path(REMOTE) / "top.txt"
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return "(unknown)"
    return run(PHONE, "top").strip()


def observe():
    """One look. Returns (foreground, nodes)."""
    run(PHONE, "observe")
    xml = (Path(REMOTE) / "ui.xml") if EMIT else WORK / "ui.xml"
    nodes = json.loads(run(UI, "parse", xml, "--json"))
    top = top_of()
    return top, nodes


def signature(nodes):
    """Structural fingerprint: enough to notice a dialog or a list loading.

    Comparing only the foreground package misses everything that happens
    inside one activity -- a popup, a tab switch, an error toast -- and that is
    exactly when an agent stops early and calls the task done.
    """
    return tuple(sorted((n["label"], n["center"][0], n["center"][1])
                        for n in nodes))


def find(nodes, needle):
    """Best actionable node matching needle. Clickable beats merely visible."""
    n = needle.lower()
    cands = [x for x in nodes
             if n in x["label"].lower() or n in x["id"].lower()]
    if not cands:
        return None
    clickable = [x for x in cands if x["clickable"]]
    return (clickable or cands)[0]


def tap(node):
    x, y = node["center"]
    run(PHONE, "tap", x, y)


def solve(task: str, max_steps: int = 12, verbose: bool = True):
    """Naive planner: the task string names the labels to tap, in order.

    A real agent would put a model here. The contract is what matters:
    every step re-observes, and progress is judged by a *changed* observation,
    never by a zero exit code.
    """
    # "打开设置，进入电池页面" -> ["设置", "电池"]
    import re
    targets = [t for t in re.split(r"[，,、\s]+", task) if t]
    targets = [t for t in targets if not t.startswith(("打开", "进入", "点击"))]

    log = []
    top, nodes = observe()
    if verbose:
        print(f"[0] foreground: {top}")
        print(f"    {len(nodes)} actionable nodes")

    for step, want in enumerate(targets, 1):
        if step > max_steps:
            log.append(f"step limit {max_steps} reached")
            break
        node = find(nodes, want)
        if node is None:
            log.append(f"{want}: not on screen")
            if verbose:
                print(f"[{step}] {want!r} not found; visible labels: "
                      f"{[n['label'] for n in nodes if n['label']][:8]}")
            break

        before = (top, signature(nodes))
        tap(node)
        top, nodes = observe()

        moved = (top, signature(nodes)) != before
        log.append(f"{want}: tapped ({node['center'][0]},{node['center'][1]}), "
                   f"{'screen changed' if moved else 'NO CHANGE'}")
        if verbose:
            print(f"[{step}] {log[-1]}")
            print(f"    foreground: {top}")

        if not moved:
            # Tapped something inert. Not fatal, but do not loop on it.
            log.append("stopping: last tap produced no state change")
            break

    return {"task": task, "final": top, "log": log}


def main():
    ap = argparse.ArgumentParser(description="example agent loop")
    ap.add_argument("--task", required=True)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    try:
        result = solve(a.task, a.max_steps, verbose=not a.json)
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print("\n-- log")
        for line in result["log"]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
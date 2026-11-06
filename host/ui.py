#!/usr/bin/env python3
"""ui.py -- turn a uiautomator XML dump into something a model can act on.

The raw dump is 33 KB of nested nodes, most of them layout scaffolding with no
text. A model reading it wastes its whole context on empty FrameLayouts. This
flattens it to one line per *actionable* node, which is typically 15-40 lines.

    ui.py parse ui.xml                # human/LLM readable list
    ui.py parse ui.xml --json         # same, as JSON
    ui.py find ui.xml "登录"           # locate a node, print its center
    ui.py tap  ui.xml "登录"           # center coords, for piping to eyes.sh

Coordinates: bounds are "[x1,y1][x2,y2]" in physical pixels. We emit the
center, because that is what `input tap` wants.

Filtering rule -- a node earns a line if any of:
    * has text
    * has content-desc (icon buttons live here, e.g. "返回", "搜索")
    * has a resource-id ending in something button-ish
    * is clickable/checkable/long-clickable
Everything else is dropped. This is what makes the output small.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def center(bounds: str):
    m = BOUNDS_RE.match(bounds or "")
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2, x2 - x1, y2 - y1


def interesting(node) -> bool:
    a = node.attrib
    if a.get("text"):
        return True
    if a.get("content-desc"):
        return True
    for flag in ("clickable", "checkable", "long-clickable", "scrollable"):
        if a.get(flag) == "true":
            return True
    rid = a.get("resource-id", "")
    # Buttons/inputs often carry no text but a telling id suffix.
    return bool(re.search(r"(btn|button|input|edit|search|icon|tab)$", rid))


def label(node) -> str:
    a = node.attrib
    text = (a.get("text") or "").strip()
    desc = (a.get("content-desc") or "").strip()
    if text and desc and text != desc:
        return f"{text} | {desc}"
    return text or desc or ""


def walk(node, depth=0, out=None, exclude=frozenset()):
    if out is None:
        out = []
    pkg = node.attrib.get("package", "")
    if pkg and pkg in exclude:
        # Borrowed from Windows-MCP's EXCLUDE_PROCESSES. On Android the usual
        # offenders are the IME (a floating keyboard full of letter keys) and
        # the system UI (status bar, nav bar). They are on screen, they are
        # actionable, and they are almost never what the agent meant to touch.
        return out
    if interesting(node):
        c = center(node.attrib.get("bounds", ""))
        if c:
            a = node.attrib
            out.append({
                "depth": depth,
                "label": label(node),
                "class": (a.get("class") or "").split(".")[-1],
                "id": a.get("resource-id", ""),
                "package": pkg,
                "clickable": a.get("clickable") == "true",
                "scrollable": a.get("scrollable") == "true",
                "checked": a.get("checked") == "true",
                "enabled": a.get("enabled") == "true",
                "password": a.get("password") == "true",
                "center": [c[0], c[1]],
                "size": [c[2], c[3]],
            })
    for child in node:
        walk(child, depth + 1, out, exclude)
    return out


def merge_word_nodes(nodes, gap: int = 6):
    """Join adjacent single-character nodes on the same text line.

    Borrowed from Windows-MCP's MERGE_WORD_NODES. Electron and some WebViews
    report one node per glyph, so a CJK label arrives as 四 / 个 / 字 / 节
    instead of 四个字节. That is four unclickable lines in the dump, and the
    agent cannot match any of them. Merge them back into the text run they
    were before the toolkit took it apart.

    Only non-clickable, non-scrollable nodes with a single-character label are
    candidates: a clickable node is a target and must stay its own line.
    """
    out: list[dict] = []
    for n in nodes:
        merged = False
        # Try the tail of the run first, then keep absorbing: a run of four
        # glyphs is three merges, and stopping at one leaves 两个/字节.
        for prev in reversed(out):
            if not _mergeable(prev, n, gap):
                break
            prev["label"] += n["label"]
            # Keep the run's centre honest: the box now spans both nodes.
            x1 = min(prev["center"][0] - prev["size"][0] // 2,
                     n["center"][0] - n["size"][0] // 2)
            x2 = max(prev["center"][0] + prev["size"][0] // 2,
                     n["center"][0] + n["size"][0] // 2)
            prev["center"] = [(x1 + x2) // 2, prev["center"][1]]
            prev["size"] = [x2 - x1, prev["size"][1]]
            merged = True
            break
        if not merged:
            out.append(dict(n))
    return out


def _mergeable(a: dict, b: dict, gap: int) -> bool:
    if a["clickable"] or b["clickable"]:
        return False
    if a["scrollable"] or b["scrollable"]:
        return False
    # `a` may already be a merged run (四个), so it is not required to be one
    # glyph. Only the incoming node must be: two multi-character nodes side by
    # side are two words, and gluing them would invent text.
    if len(b["label"]) != 1:
        return False
    # Same line: the vertical centres must agree within half a line.
    if abs(a["center"][1] - b["center"][1]) > max(8, a["size"][1] // 2):
        return False
    # Adjacent, not two words far apart.
    right = a["center"][0] + a["size"][0] // 2
    left = b["center"][0] - b["size"][0] // 2
    return -gap <= (left - right) <= gap * 4


def load(path):
    return ET.parse(path).getroot()


# Two Windows-MCP ideas that pay off on Android. Both are opt-in except the
# package exclusion list, which defaults to the IME: a keyboard is 40 letter
# keys of noise and an agent that taps one instead of the field behind it has
# made a mess the user has to clean up.
DEFAULT_EXCLUDE = "com.android.inputmethod.latin,com.google.android.inputmethod.latin,com.sohu.inputmethod.sogou,com.iflytek.inputmethod,com.baidu.input"


def exclude_set() -> frozenset[str]:
    raw = os.environ.get("PHONE_EXCLUDE_PACKAGES", DEFAULT_EXCLUDE)
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def merge_enabled() -> bool:
    return os.environ.get("PHONE_MERGE_WORDS", "1") not in ("0", "false", "no", "off")


def nodes_from(path, merge: bool | None = None, exclude=None):
    """The one way to turn a dump into node dicts.

    Every command goes through here so the two filters cannot drift apart --
    `parse` and `diff` disagreeing about what is on screen would be worse than
    having no filter at all.
    """
    root = load(path)
    nodes = walk(root, exclude=exclude if exclude is not None else exclude_set())
    if merge if merge is not None else merge_enabled():
        nodes = merge_word_nodes(nodes)
    return nodes


def cmd_parse(args):
    nodes = nodes_from(args.xml)
    if args.json:
        print(json.dumps(nodes, ensure_ascii=False, indent=1))
        return 0
    for n in nodes:
        flags = "".join([
            "C" if n["clickable"] else "-",
            "S" if n["scrollable"] else "-",
            "X" if n["checked"] else "-",
            "P" if n["password"] else "-",
        ])
        txt = n["label"] or f"<{n['class']}>"
        rid = f" #{n['id'].split('/')[-1]}" if n["id"] else ""
        print(f"{flags} ({n['center'][0]:4d},{n['center'][1]:4d}) {txt}{rid}")
    print(f"-- {len(nodes)} actionable nodes", file=sys.stderr)
    return 0


def cmd_find(args):
    needle = args.query.lower()
    hits = [n for n in nodes_from(args.xml)
            if needle in n["label"].lower() or needle in n["id"].lower()]
    if not hits:
        print(f"no node matching {args.query!r}", file=sys.stderr)
        return 1
    for n in hits:
        print(f"({n['center'][0]},{n['center'][1]}) {n['label']} #{n['id'].split('/')[-1]}")
    return 0


def cmd_tap(args):
    needle = args.query.lower()
    nodes = nodes_from(args.xml)
    # Rows are often a clickable container with no text wrapping a text node
    # that is not clickable. So: prefer a clickable hit, but a text hit is
    # still valid -- its center lies inside the clickable parent's bounds.
    hits = [n for n in nodes
            if n["clickable"] and (needle in n["label"].lower()
                                   or needle in n["id"].lower())]
    if not hits:
        hits = [n for n in nodes
                if needle in n["label"].lower() or needle in n["id"].lower()]
    if not hits:
        print(f"no node matching {args.query!r}", file=sys.stderr)
        return 1
    n = hits[0]
    print(f"{n['center'][0]} {n['center'][1]}")
    return 0


# ------------------------------------------------------------------- diff
def key_of(n: dict) -> str:
    """Identity of a node across two dumps.

    Deliberately not the coordinates: a list that scrolls keeps its rows and
    moves them, and calling that "one node left, another arrived" is exactly
    the noise a diff is supposed to remove. Label + class + id is stable
    across a scroll and changes when the content really changed.
    """
    return f"{n['label']}\x00{n['class']}\x00{n['id']}"


def index(nodes):
    """Multiset of nodes by identity, so two identical rows stay two rows."""
    out: dict[str, list[dict]] = {}
    for n in nodes:
        out.setdefault(key_of(n), []).append(n)
    return out


def diff(old_nodes, new_nodes, move_tol: int = 8):
    """What actually changed between two observations.

    Returns (added, removed, moved, changed). A node that is present in both
    but at a new centre is "moved"; same place but different flags/label is
    "changed". This is the whole point of the subcommand: after a tap, the
    honest answer to "did anything happen" is usually "one row appeared",
    not a 40-line re-dump that the model has to re-read.
    """
    old_i, new_i = index(old_nodes), index(new_nodes)
    added, removed, moved, changed = [], [], [], []
    for k, ns in new_i.items():
        before = old_i.get(k, [])
        for i, n in enumerate(ns):
            if i >= len(before):
                added.append(n)
                continue
            o = before[i]
            dx = abs(n["center"][0] - o["center"][0])
            dy = abs(n["center"][1] - o["center"][1])
            if dx > move_tol or dy > move_tol:
                moved.append((o, n))
            elif (n["clickable"] != o["clickable"]
                  or n["checked"] != o["checked"]
                  or n["enabled"] != o["enabled"]
                  or n["label"] != o["label"]):
                changed.append((o, n))
    for k, ns in old_i.items():
        extra = len(ns) - len(new_i.get(k, []))
        for n in ns[len(ns) - extra:] if extra > 0 else []:
            removed.append(n)
    return added, removed, moved, changed


def cmd_diff(args):
    old_nodes = nodes_from(args.old)
    new_nodes = nodes_from(args.new)
    added, removed, moved, changed = diff(old_nodes, new_nodes)
    if args.json:
        print(json.dumps({
            "added": added, "removed": removed,
            "moved": [{"from": o["center"], "to": n["center"],
                       "label": n["label"]} for o, n in moved],
            "changed": [{"label": n["label"], "center": n["center"]} for _, n in changed],
        }, ensure_ascii=False, indent=1))
        return 0
    if not (added or removed or moved or changed):
        # Silence would be ambiguous: "no change" and "the diff broke" look
        # the same. Say it, and say how big the sample was.
        print(f"no change ({len(new_nodes)} nodes)")
        return 0
    for n in added:
        print(f"+ {n['label'] or '<' + n['class'] + '>'} ({n['center'][0]},{n['center'][1]})")
    for n in removed:
        print(f"- {n['label'] or '<' + n['class'] + '>'} ({n['center'][0]},{n['center'][1]})")
    for o, n in moved:
        print(f"~ {n['label'] or '<' + n['class'] + '>'} "
              f"({o['center'][0]},{o['center'][1]})->({n['center'][0]},{n['center'][1]})")
    for o, n in changed:
        was = "clickable" if o["clickable"] != n["clickable"] else "state"
        print(f"! {n['label'] or '<' + n['class'] + '>'} "
              f"({n['center'][0]},{n['center'][1]}) {was}")
    print(f"-- {len(added)}+ {len(removed)}- {len(moved)}~ {len(changed)}! "
          f"of {len(new_nodes)} nodes", file=sys.stderr)
    return 0


def main():
    ap = argparse.ArgumentParser(description="flatten uiautomator dumps")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse")
    p.add_argument("xml")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_parse)

    p = sub.add_parser("find")
    p.add_argument("xml")
    p.add_argument("query")
    p.set_defaults(fn=cmd_find)

    p = sub.add_parser("tap")
    p.add_argument("xml")
    p.add_argument("query")
    p.set_defaults(fn=cmd_tap)

    p = sub.add_parser("diff", help="what changed between two dumps")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_diff)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
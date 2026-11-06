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


def walk(node, depth=0, out=None):
    if out is None:
        out = []
    if interesting(node):
        c = center(node.attrib.get("bounds", ""))
        if c:
            a = node.attrib
            out.append({
                "depth": depth,
                "label": label(node),
                "class": (a.get("class") or "").split(".")[-1],
                "id": a.get("resource-id", ""),
                "clickable": a.get("clickable") == "true",
                "scrollable": a.get("scrollable") == "true",
                "checked": a.get("checked") == "true",
                "enabled": a.get("enabled") == "true",
                "password": a.get("password") == "true",
                "center": [c[0], c[1]],
                "size": [c[2], c[3]],
            })
    for child in node:
        walk(child, depth + 1, out)
    return out


def load(path):
    return ET.parse(path).getroot()


def cmd_parse(args):
    root = load(args.xml)
    nodes = walk(root)
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
    root = load(args.xml)
    needle = args.query.lower()
    hits = [n for n in walk(root)
            if needle in n["label"].lower() or needle in n["id"].lower()]
    if not hits:
        print(f"no node matching {args.query!r}", file=sys.stderr)
        return 1
    for n in hits:
        print(f"({n['center'][0]},{n['center'][1]}) {n['label']} #{n['id'].split('/')[-1]}")
    return 0


def cmd_tap(args):
    root = load(args.xml)
    needle = args.query.lower()
    nodes = walk(root)
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

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
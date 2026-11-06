#!/usr/bin/env python3
"""Regenerate adapters/openai-tools.json from the MCP server's tool table.

Two adapters describing the same eleven tools will drift, so one of them is
generated. Edit `adapters/mcp/phone_mcp.py`, then:

    python3 adapters/make_openai_tools.py

Why keep a checked-in JSON instead of telling people to run this: the whole
point of the file is to be pasted into someone else's framework, in a repo they
may not have cloned next to their code.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "openai-tools.json"


def load_server():
    spec = importlib.util.spec_from_file_location(
        "phone_mcp", HERE / "mcp" / "phone_mcp.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def main() -> int:
    server = load_server()
    tools = [
        {"type": "function",
         "function": {"name": t["name"],
                      "description": t["description"],
                      "parameters": t["inputSchema"]}}
        for t in server.TOOLS
    ]
    OUT.write_text(json.dumps(tools, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} ({len(tools)} tools)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
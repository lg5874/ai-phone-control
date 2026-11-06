# MCP adapter

`phone_mcp.py` exposes the CLI as a Model Context Protocol server over stdio,
standard library only, no `pip install`. Eleven tools, one `host/phone.py`
invocation each — so the transports and the exit-code contract are the core's,
not a copy.

```
phone_ui          read the screen as text (the loop tool)
phone_tap_text    tap a visible label
phone_tap_xy      tap physical pixels
phone_long_press  long press
phone_swipe       preset (up/down/left/right) or explicit pixels
phone_press_key   back / home / enter / recents / KEYCODE_*
phone_type        type ASCII into the focused field
phone_screenshot  screenshot -> path + size
phone_observe     screenshot + tree; mode=full|ui|shot, diff=true
phone_foreground  which app is in front
phone_size        screen geometry
```

## Two cost knobs worth knowing

A full observation is ~422 KB of PNG plus 30-40 lines of tree. Most steps in a
loop need one or the other, not both.

| call | cost | when |
|---|---|---|
| `phone_ui` | tree only, ~2 s | the default loop tool |
| `phone_observe {mode:"ui"}` | tree only | same as above, one verb |
| `phone_observe {mode:"shot"}` | pixels only | canvas, game, treeless WebView |
| `phone_observe {mode:"full"}` | both | first look at an unfamiliar screen |
| `phone_ui {diff:true}` | delta only | "did my tap do anything" |

`diff:true` prints what changed since your previous diff call — one added line
instead of forty unchanged ones. The first call has no baseline, so it prints
the whole tree and says so on stderr; silence would be indistinguishable from
"nothing changed". The baseline lives in `$PHONE_WORK/last.xml` and is shared by
`phone_ui` and `phone_observe`, so the two verbs agree on what "previous" means.

## Two filters, borrowed from Windows-MCP

| env | default | effect |
|---|---|---|
| `PHONE_EXCLUDE_PACKAGES` | the common IMEs | skip these packages entirely |
| `PHONE_MERGE_WORDS` | `1` (on) | join per-glyph nodes into one text run |

The IME exclusion exists because a keyboard is 40 letter keys that are on screen,
clickable, and almost never the target. Set it to an empty string to exclude
nothing.

The word merge exists because Electron and some WebViews report one node per
glyph: a CJK label arrives as `四` / `个` / `字` / `节`, four unclickable lines
that no label can match. Merging restores `四个字节` as one node whose centre
still lies inside the run, so it stays tappable. Clickable and scrollable nodes
never merge — a target must stay its own line.

Both filters are applied inside `nodes_from()`, the single path every command
takes. `parse` and `diff` disagreeing about what is on screen would be worse
than having no filter at all.

## Install

Nothing to install. Point the client at the file:

```json
{
  "mcpServers": {
    "phone": {
      "command": "python3",
      "args": ["/abs/path/to/ai-phone-control/adapters/mcp/phone_mcp.py"],
      "env": {
        "PHONE_TRANSPORT": "adb",
        "PHONE_SERIAL": "XXXXXXXX"
      }
    }
  }
}
```

The same JSON works for Claude Desktop (`claude_desktop_config.json`), Cline,
Cherry Studio, Cursor and anything else that reads the MCP server format. Only
the file's location differs:

| client | where |
|---|---|
| Claude Desktop | `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS), `%APPDATA%\Claude\` (Windows) |
| Cline / Roo | MCP settings panel, "Edit JSON" |
| Cherry Studio | Settings → MCP servers → Add → type `stdio` |
| Cursor | `~/.cursor/mcp.json` |

### Env, one row per situation

| your setup | env |
|---|---|
| laptop + USB adb | `PHONE_TRANSPORT=adb`, `PHONE_SERIAL=<serial>` |
| laptop + wireless debug | same, serial is `ip:port` |
| MCP client **on the phone**, root shell | `PHONE_TRANSPORT=exec`, `PHONE_EXEC=su -c` |
| MCP client on the phone, Shizuku only | `PHONE_TRANSPORT=exec`, `PHONE_EXEC=rish -c` |
| client cannot spawn a device shell but shares `/sdcard` | `PHONE_EMIT=1`, `PHONE_DIR=/sdcard/lcs` |

`PHONE_EMIT=1` is special: the server *prints* `DEVICE_CMD: ...` and the model
must run it with its own tool. It is the honest fallback when there is no
channel, not a mode to leave switched on — an inherited export is warned about
on stderr and in the tool output.

## Tool selection

Give a small agent eleven tools and it will sometimes pick the most expensive
one. Env vars trim the list (Windows-MCP style):

| env | effect |
|---|---|
| `PHONE_TOOLS=phone_ui,phone_tap_text` | whitelist; the final say |
| `PHONE_EXCLUDE_TOOLS=phone_screenshot` | blacklist; only used when no whitelist |

Unknown names fail fast at startup with the valid list on stderr. `tools/list`
is filtered; a direct `tools/call` to a hidden tool still works, so a client
that cached the old list does not break silently. The server log line reports
what took effect: `phone_mcp 1.2.0: transport=adb cli=… tools=2/11`.

A good minimal set for a chat-box agent:
`PHONE_TOOLS=phone_ui,phone_tap_text,phone_swipe,phone_press_key,phone_type,phone_foreground`.

## Verify the wiring before you blame the phone

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
| python3 adapters/mcp/phone_mcp.py
```

Expect two JSON lines, the second listing eleven tools (fewer if you set
`PHONE_TOOLS` / `PHONE_EXCLUDE_TOOLS`). If the client shows no
tools, check its server log: the first stderr line says
`phone_mcp 1.2.0: transport=adb cli=/…/host/phone.py tools=11/11` — that line is
the answer
to "why did nothing happen". Then, from a normal shell, make sure the CLI itself
works:

```bash
PHONE_TRANSPORT=adb PHONE_SERIAL=XXXX ./phone ui
```

## What the model sees

Every tool result ends with `[exit N]`, and `isError` is true only for codes
`2` and above — exit `1` ("the label is not on this screen") is a valid answer,
so it is *not* flagged as an error. The descriptions in the schema tell the
model to read before acting and to re-read after acting; that instruction lives
in the tool text because that is the only place a model reliably looks.

## Device-free tests

```bash
python3 tests/test_mcp.py
```

Drives the server over stdin with a fake CLI (`PHONE_CLI` env), so the protocol
is tested without a phone.

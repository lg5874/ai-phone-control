# Changelog

## v1.3.0 — observe less, see more

Four changes, all in service of one number: how much a single look costs.

**Added — `phone_observe --mode` and `--diff`**
- `--mode ui|shot|full` (default `full`). A full observation is ~422 KB of PNG
  plus 30-40 lines of tree; most steps in a loop need one or the other. `mode=ui`
  is the tree alone (same as `phone ui`), `mode=shot` is pixels alone. The
  zero-flag path is byte-identical to v1.2 — an existing client keeps working.
- `--diff` prints what changed since the previous diff call instead of the whole
  tree. After a tap the honest answer is usually one added line, not forty
  unchanged ones. The baseline lives in `$PHONE_WORK/last.xml` and is shared by
  `phone ui` and `phone observe`, so both verbs agree on "previous".
- The first `--diff` call has no baseline: it prints the full tree and says so on
  stderr. Silence would be indistinguishable from "nothing changed", which is
  the one reading that would make an agent skip a re-check.

**Added — `ui.py diff OLD NEW`**
- Reports `+` added, `-` removed, `~` moved, `!` changed, with a summary on
  stderr. Identity is label+class+id, not coordinates: a list that scrolls keeps
  its rows and moves them, and calling that "one left, another arrived" is the
  noise a diff exists to remove.
- Nodes are indexed as a multiset, so two identical rows stay two rows.
- A centre that shifts within `move_tol` (default 8 px) is not a move.

**Added — package exclusion (`PHONE_EXCLUDE_PACKAGES`)**
- Borrowed from Windows-MCP's `EXCLUDE_PROCESSES`. Defaults to the common IMEs:
  a keyboard is 40 letter keys that are on screen, clickable, and almost never
  the target. An empty string excludes nothing.
- The exclusion is by node `package`, so an IME drawn inside another app's window
  is still excluded and the app's own nodes are not.

**Added — per-glyph merge (`PHONE_MERGE_WORDS`, on by default)**
- Borrowed from Windows-MCP's `MERGE_WORD_NODES`. Electron and some WebViews
  report one node per glyph, so a CJK label arrives as `四`/`个`/`字`/`节` —
  four unclickable lines that no label can match. They are merged back into
  `四个字节`, with the centre recomputed to span the run so the result is still
  tappable.
- Clickable and scrollable nodes never merge: a target must stay its own line.
  Only single-character incoming nodes merge, so two multi-character nodes side
  by side (two words) are never glued into invented text.

**Changed — one path for both filters**
- `nodes_from()` is now the only way a dump becomes node dicts, and every command
  (`parse`, `find`, `tap`, `diff`) goes through it. `parse` and `diff` disagreeing
  about what is on screen would be worse than having no filter at all: the diff
  would report phantom changes on every call.

**Fixed — `observe --mode ui` crashed**
- Forwarding to `cmd_ui` reached for `--max-age`/`--strict`, which only the `ui`
  verb declares, and raised `AttributeError`. A model reads a traceback as "the
  tool is broken" and stops. Defaults are now filled in before the forward.

**Measured**
- Tool-list cost with `PHONE_TOOLS` trimmed to six tools: 5096 → 2811 characters
  (~1698 → ~937 tokens), 45% less, on every request.
- 73 device-free tests pass (was 46).

## v1.2.0 — any agent, and a brake before the accelerator

Two changes that belong together: the project stops being a two-shape thing
(CLI *or* Operit) and becomes a core plus optional adapters, and every action
now checks three facts before it touches the screen.

**Added — pre-flight gate (exit codes 3, 4, 6)**
- `eyes.sh state`: wakefulness, keyguard and `topResumedActivity` in one call.
- `eyes.sh human`: is a real finger on the glass?
  `input tap` injects events *below* the input device layer, so injected taps
  never appear in `/dev/input/event*` — `getevent` therefore hears humans only,
  which is what lets an agent yield instead of fighting for the screen. Only
  panels that report `ABS_MT_POSITION_X` are watched, so a sensor or AOD node
  that reports periodically is not mistaken for a person.
  A press counts, a lift does not: the first version took the first event on the
  device, and a `TRACKING_ID ffffffff` or a stray `SYN_REPORT` read as a human.
  Measured on the test panel: a human swipe → `yes` (three runs while the screen
  was being used), then `no`, `input tap`, `no` — the injected tap never reaches
  `evdev`, which is the property the whole gate depends on.
- Every action runs the gate first: `SCREEN_OFF` (6), `WRONG_APP` (3),
  `HUMAN_BUSY` (4). Flags: `--force`, `--expect <pkg>`, `--window <s>`.
- `eyes.sh pkg <name>`: installed / path / versionName / firstInstallTime —
  "the screen changed" is not "the app is on the phone".

**Changed — Operit is an adapter now, not a second half**
- `operit-package/` → `adapters/operit/`. The README no longer presents the
  project as "shell half + native half": the core is the CLI, and everything
  framework-shaped is optional and lives in `adapters/`.
- `SKILL.md`: "The other shape" → "Other agent runtimes", listing the adapters
  instead of a single platform.

**Added — adapters/**
- `adapters/mcp/phone_mcp.py`: MCP server over stdio, standard library only, 11
  tools, each one a `host/phone.py` invocation. `isError` is true only for exit
  codes ≥ 2 — exit 1 ("not on this screen") is an answer, not a failure, and
  flagging it as an error teaches a model to retry instead of scroll.
- `adapters/openai-tools.json`, generated by `adapters/make_openai_tools.py`
  from the MCP tool table, so two descriptions of the same tools cannot drift.
- `adapters/prompt-only.md`: the human-as-transport workflow, with the system
  prompt that makes a chat box obey "verify after you act".
- `adapters/README.md`: which adapter for which runtime, and the contract every
  adapter keeps.

**Added — docs/INTEGRATE.md**
- Five ways in (adb / exec / Shizuku / your own loop / no tools), a 30-second
  check for each, and a symptom→layer table taken from real failures: emit left
  on, `su` inside proot printing nothing while exiting 0, the binder error on
  `input`, stale trees, `uiautomator` idle-state errors.
- The Shizuku section is marked **unverified on this project's hardware** (the
  test device is KernelSU root) instead of being presented as measured.

**Fixed — silent degrade to emit**
- `PHONE_EMIT=1` inherited from an earlier shell turned a working adb/exec setup
  into a printer that exits 0. Measured — it cost a debugging round here.
  `phone.py` now warns on stderr when `PHONE_EMIT` overrides an explicitly
  configured transport, and the MCP server prints its transport as the first
  stderr line, which is where a client's log pane keeps it.

**Tests**
- `tests/test_mcp.py`: 13 device-free tests over a fake CLI — protocol, argument
  mapping, exit-code semantics, and no internal fields leaking into
  `tools/list`.
- `tests/test_human_probe.py`: 6 device-free tests for the touch probe, built
  from real `getevent` output. The patterns are read out of `eyes.sh`, so the
  test goes red when the shell changes shape instead of drifting.
- Total device-free suite: 41 tests.

## v1.1.0 — two shapes

The tool now ships in two forms for two different constraints, and both obey the
same rule: an action reports whether the screen changed.

**Added — native package (`operit-package/`)**
- `com.operit.phone_control.js`: one file, 11 tools (`screen`, `find`,
  `tap_text`, `tap_xy`, `swipe`, `press`, `type_text`, `screen_text`,
  `foreground`, `shot`, `wait`), built on Operit's `Tools.UI` bridge. No root,
  no adb, no `eyes.sh`, no Python.
- Same contract as the shell half: `changed` is a fingerprint of package +
  activity + node count + label length sampled every 150 ms, so "the tap did
  nothing" becomes visible instead of implied. A missing label returns
  `NOT_ON_SCREEN … nothing was tapped`.
- Swipe presets scale from `Tools.System.getDeviceInfo()`, never a constant.
- Verified against a live screen (V2403A / Android 15): tap → `changed: true`
  (signature `73/285 → 78/268`), absent label → `NOT_ON_SCREEN`, swipe up →
  `630,1930 → 630,750`, `BACK` accepted without the `KEYCODE_` prefix,
  screenshot 383012 bytes.

**Added — skill**
- `SKILL.md`: the shell half written for an agent to read — when to use it, the
  four-step loop, the real `ui` output format, exit codes 0/1/2, and four rules
  (an action is not evidence; in emit mode `DEVICE_CMD:` is an instruction; a
  stale tree may describe a screen that is gone; prefer labels over pixels).

**Added**
- `phone`: a 12-line wrapper, so every `./phone ui` in README.md and SKILL.md is
  a command you can type as written. Before this the docs assumed an alias.
- `operit-package/README.md`: install paths, the tool table, the contract, and
  the hardware verification log.

**Fixed — found while writing the package**
- `find` / `tap_text` exact matching compared the combined `"text | desc"`
  label, so an exact pin never matched a node whose text and description both
  existed. Matching now checks the raw `text`, the raw `contentDesc`, then the
  combined label.

## v1.0.1 — truth in emit mode

Everything here came from driving a real phone through `emit` (the mode where
the agent runs the device command itself) and catching commands that printed
success while doing nothing.

**Fixed — silent successes**
- `tap-text` in emit mode printed the dump command and exited 0 without parsing
  or tapping. It now resolves the label against shared storage and prints the
  `eyes.sh tap X Y` the caller must run; an unknown label exits 1.
- `shot` / `dump` / `observe` in emit mode printed nothing useful. They now
  report the artifact's path and size, and a missing artifact is an error with
  the command that would create it.
- `ui --strict` (new): a stale tree becomes exit 2 instead of a stderr warning.
  `tap-text` always refuses a tree older than 30 s rather than aiming at
  coordinates that have moved.
- `warn_stale` no longer dies with a traceback when the artifact is absent.
- `top` in emit mode echoed the command as if it were the foreground app, which
  silently froze any progress check keyed on it (the example loop stopped after
  one step and called it done). It now reads `$REMOTE_DIR/top.txt`, written by
  `eyes.sh observe`, and exits 2 asking for a fresh probe when there is none.

**Fixed — portability**
- `swipe` presets were hardcoded to 1260×2800. They now scale from
  `PHONE_SIZE=WxH` (same default), so another phone does not tap off-screen.

**Fixed — example**
- `examples/agent.py` assumed `/tmp/phone/ui.xml`, which only exists for the
  adb transport. It now reads the tree from `$PHONE_DIR` in emit mode.
- Its progress check compared only the foreground package, so anything that
  happened inside one activity (a dialog, a list loading, an error toast)
  counted as "no change" and ended the loop. It now compares a UI-tree
  signature too.

**Docs**
- v1.0.0's entry below named device commands (`ui`, `geom`, `fore`) that
  `eyes.sh` never had; corrected in place to `dump`, `size`, `top`.
- `docs/TRANSPORT.md` promised a `--ingest` flag and `DEVICE_PULL` lines that
  do not exist. Replaced with what emit actually does, plus the exit codes.

**Tests**
- 11 new device-free cases in `tests/test_phone_emit.py` (22 total), each
  pinning a way a command could previously lie about having worked.

## v1.0.0 — first release

The shape is settled: one process per command, device side stays on the device.

**Device half** — `android/eyes.sh`, 139 lines of toybox `sh`.
- `dump` dumps the accessibility tree and writes the compressed XML.
- `shot` grabs a PNG, optionally downscaled with `wm size`.
- `size` reports physical screen size and density.
- `top` reports the foreground package via `topResumedActivity`.
- `tap` / `swipe` / `key` / `text` wrap `input` with the quoting fixed
  (`input text` needs `%s` for spaces).
- Timings come from `/proc/uptime`, because toybox `date` has no `%N`.

**Host half** — `host/phone.py`, subcommand CLI.
- Three transports: `adb shell`, `su -c` on device, `nsenter` from Termux.
- `install` pushes `eyes.sh`, chmods it, and prints the screen geometry.
- `ui` parses the dump through `ui.py` and prints one line per actionable node.
- `tap-text` resolves a label to coordinates, preferring a clickable ancestor.
- `observe` returns the screenshot plus the parsed tree in one call.

**Parser** — `host/ui.py`, no device needed.
- Drops the `FrameLayout` scaffolding: 33 KB XML, ~800 nodes → 47 lines.
- Keeps only nodes with text, a `content-desc`, or clickable/scrollable bounds.
- Emits centre coordinates in physical pixels, which is what `input tap` takes.

**Tests** — 11 cases in `tests/test_ui.py`, all device-free. They run against
captured XML from a real Settings screen.

### Measured on a V2403A / Android 15 / 1260×2800 @ 560 dpi

| command | time | output |
|---|---|---|
| `screencap -p` | 400 ms | 422 KB PNG |
| `uiautomator dump --compressed` | 2.1 s | 33 KB XML |
| `input tap` | 50 ms | — |
| `phone ui` (dump + pull + parse) | ~2.3 s | 47 lines |

### Known limits

- `input tap` fails when called from a socket-spawned shell
  (`Failed transaction (2147483646)`). Keep input on the adb or root-shell side.
- Cannot run from inside proot: there is no `/system` in that mount namespace,
  and the `linker64` `NEEDED` closure for `screencap` never closes.
- `uiautomator` is the bottleneck. Cache the dump across several taps.
- No OCR fallback. If a target only exists as pixels, use `observe` and let the
  model look.

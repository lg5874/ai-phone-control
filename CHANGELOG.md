# Changelog

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

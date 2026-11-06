# Changelog

## v1.0.0 — first release

The shape is settled: one process per command, device side stays on the device.

**Device half** — `android/eyes.sh`, 139 lines of toybox `sh`.
- `ui` dumps the accessibility tree and returns the compressed XML.
- `shot` grabs a PNG, optionally downscaled with `wm size`.
- `geom` reports physical screen size and density.
- `fore` reports the foreground package via `topResumedActivity`.
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

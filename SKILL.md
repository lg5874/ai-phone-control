---
name: phone-control
description: Read and drive a real Android phone screen - UI tree as text with real coordinates, tap by visible label, swipe, press keys, type, screenshot, and report whether the screen actually changed. Use when a task needs the phone screen read, changed or verified (open an app, find and press a button, scroll a list, fill an input), when adb or an accessibility service is unavailable, or when the agent itself runs on the phone with root. 触发词：看屏幕、看下屏幕、屏幕上有什么、读屏、点一下、点按钮、点XX、帮我点、滑动、滚动、返回键、截图、界面、UI、无障碍、手机操作、打开APP、输入文字、填表、在手机上做。
---

# phone-control

Give an agent eyes and hands on an Android phone: one process per action, nothing
resident between actions, no app to install on the phone beyond a 143-line shell
script, no accessibility service, no OCR, no cloud.

中文一句话：让 agent 用真实手势操作安卓手机，看一眼就退，不驻留进程。

Requirements: `python3` on the host half (standard library only), root on the
phone (KernelSU / Magisk / `adb root`).

## Setup (once)

Work from the repository root: every command below is `./phone …` relative to it.
If you installed this as a skill by copying only `SKILL.md`, clone the repository
and run the commands there — the wrapper needs `host/phone.py` next to it.

```sh
./phone install          # pushes android/eyes.sh to /sdcard/lcs/eyes.sh
```

Then choose how the host half reaches the device shell, via environment:

| env | meaning |
|---|---|
| `PHONE_TRANSPORT=adb` (default) + `PHONE_SERIAL=<serial>` | `adb -s $PHONE_SERIAL shell ...` |
| `PHONE_TRANSPORT=exec` + `PHONE_EXEC='<wrapper>'` | an existing root shell (KernelSU, Magisk, an on-device agent) |
| `PHONE_EMIT=1` (+ `PHONE_SHARED=/sdcard/lcs`) | **no shell at all**: the tool prints the device command to run and reads the artifacts from the shared directory |

## The loop

1. **Look** — `./phone ui`
2. **Decide** — pick a label, or a coordinate from a real pixel grid
3. **Act** — `./phone tap-text "隐私"`, `./phone swipe up`, `./phone key back`, `./phone type "hi"`
4. **Verify** — `./phone top` and `./phone ui` again

Step 4 is not optional. See Rules.

## What `ui` returns

One line per actionable node: `flags (x,y) label #id`

```
C--- ( 112, 413) 显示历史
C-S- ( 630, 812) 消息列表
---- (1148, 421) 24
```

`flags` = `C`lickable, `S`crollable, `X` checked, `P`assword. Coordinates are
physical pixels of the real screen — pass them straight back to `tap`.

## Commands

| task | command |
|---|---|
| what is on screen, as text | `./phone ui [--max-age 30] [--strict]` |
| which app is in front | `./phone top` |
| screenshot only | `./phone shot [--scale 540]` |
| screenshot + UI tree | `./phone observe [--scale 540]` |
| raw UI tree | `./phone dump [--raw] [--json]` |
| tap pixels | `./phone tap 630 1400` |
| tap by visible label | `./phone tap-text "登录"` |
| long press | `./phone long 630 1400 [--ms 800]` |
| swipe preset or explicit | `./phone swipe up` / `./phone swipe 630 1900 630 700` |
| key event | `./phone key back` (home, enter, recents, …) |
| type into focused field | `./phone type "hello"` |
| screen geometry | `./phone size` |
| deploy the device half | `./phone install` |

## Exit codes

| code | meaning |
|---|---|
| 0 | the thing happened, or the observation was returned |
| 1 | target not found — the label is not on this screen, nothing was tapped |
| 2 | refused: the view is stale, or the device produced no artifact |
| 3 | wrong app — `--expect` did not match the foreground package, nothing was done |
| 4 | a real finger is on the screen (`HUMAN_BUSY`); the human goes first |
| 6 | screen off or locked — wake it before acting |

## Rules

1. **An action reporting success is not evidence.** `tap-text` returns exit 0
   because a tap was dispatched. Read `./phone top` / `./phone ui` and confirm
   the screen actually changed before you claim the step is done.
2. **In emit mode `DEVICE_CMD:` is an instruction, not a result.** With
   `PHONE_EMIT=1` the tool tells you what to run on the device. Exit 0 there
   means "here is the command", never "the phone did it".
3. **A stale tree describes a screen that may no longer exist.** `ui` warns past
   30 s (`--max-age`); `--strict` turns that warning into exit 2. Refresh before
   tapping when you were told the view is old.
4. **Prefer `tap-text` over `tap`.** Labels survive resolution and layout
   changes; pixels do not.
5. **A human outranks the agent.** A real finger on the glass makes an action
   return exit 4 and do nothing. That is the intended behaviour, not a bug:
   wait, or hand the task back. `--force` exists for the case where you are
   certain the finger is gone and the screen is yours.

## Recipes

**Open Settings → Privacy**

```sh
./phone key home
./phone ui
./phone tap-text "设置"
./phone top                      # expect com.android.settings
./phone ui
./phone tap-text "隐私"
```

**Scroll until something appears**

```sh
for i in 1 2 3 4 5; do
  ./phone swipe up
  ./phone ui | grep -q "目标文字" && break
done
```

**Read a WebView / canvas app with no accessibility tree**

```sh
./phone shot --scale 540         # then read the image
```

## Other agent runtimes

This file is the core. If your runtime is not a shell — an MCP client, a vendor
app with its own UI bridge, a chat box — the adapters live in `adapters/`:
`adapters/mcp/` (stdio MCP, 11 tools), `adapters/openai-tools.json` (function
calling schemas), `adapters/prompt-only.md` (the human is the transport), and
`adapters/operit/` (native package on Operit's `Tools.UI`, no root, for a phone
with no shell at all).

Five ways in, one per runtime, with a symptom→layer table: `docs/INTEGRATE.md`.
Every shape obeys the same rule — an action must be verified, never assumed.

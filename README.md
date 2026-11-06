# ai-phone-control

> 让 AI 直接看你的手机屏幕并操作它。不用投屏、不用 Appium、不用 OCR，
> 一条命令看一次，看一眼就退。支持 KernelSU / Magisk / `adb root`。
>
> **中文关键词**：AI 控制手机 · AI 操控安卓 · 让大模型操作手机 · 手机自动化
> 智能体 · 屏幕识别 · 无投屏 · 无障碍免安装 · 单次命令 · 无守护进程

Give an LLM agent eyes and hands on an Android phone. Two small files, no
dependencies, nothing left running.

[![release](https://img.shields.io/github/v/release/lg5874/ai-phone-control?label=release)](https://github.com/lg5874/ai-phone-control/releases)
[![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

```bash
phone ui                       # what is on screen, as text with coordinates
phone tap-text "隐私"           # tap it by label
phone type "hello"
phone key back
phone observe --scale 540      # screenshot too, downscaled
```

Works on a stock phone with root (KernelSU / Magisk / `adb root`). No
accessibility service, no Appium, no OCR, no cloud.

**Any agent runtime** — a laptop agent over adb, an on-phone agent with a root
shell, Shizuku without root, an MCP client, your own function-calling loop, or a
chat box with a human in the loop: [docs/INTEGRATE.md](docs/INTEGRATE.md), and
`adapters/` for the thin wrappers. Operit is one adapter among several, not a
requirement.

---

## The one design decision

**Every command is one process that starts, does its job, and exits.**

This is not an implementation detail, it is the whole point. An agent that
observes 200 times during a task should cost 200 × 0.4 s of phone time and
**zero** CPU in between. The obvious alternative — `screenrecord` piped into
ffmpeg into a frame extractor — is what I built first, and it is the wrong
shape:

| | streaming pipeline | one-shot |
|---|---|---|
| idle cost | one decoder core, forever | nothing |
| latency per look | ~150 ms | ~400 ms |
| orphan processes | yes, when the parent shell is reaped | none |
| crash recovery | stale `.pid`, zombie `screenrecord` | next command just works |
| code | 250 lines of pipe splicing | 130 lines of shell |

150 ms vs 400 ms does not matter. An agent thinks for seconds. Leaving a
hardware decoder pinned between thoughts does matter.

## Why this cannot live inside a proot Ubuntu

If your agent runs in Termux/proot (common on-device setups), you will try to
call `screencap` directly and it will fail. Two walls, both measured on a
V2403A / Android 15:

1. **proot's mount namespace has no `/system`.** `/system/bin/screencap` is
   simply not there. Copying the binary in does not help either — see next.

2. **Android binaries are not glibc.** Running the copied binary needs
   `linker64` plus the *transitive* `NEEDED` closure of `libgui`, `libui`,
   `libbinder`. `linker64` does run under proot, so this looks promising, and
   then the closure never closes. Measured:

   ```
   round 1: 43 missing
   round 2: 62 missing   (after staging 98 libs)
   ...
   ```

   The count *grows* each round, because `libgui` pulls in SurfaceFlinger
   internals, which pull in HIDL/AIDL service stubs, which pull in more. This
   is a package manager's job, not a shell script's.

So the split is: **observation and input run on the Android side; parsing runs
wherever you like.** The agent process is the bridge. `phone.py` is that
bridge and it speaks either `adb shell` or a bare `su -c`.

## One core, adapters that are optional

The core is the CLI plus `android/eyes.sh`. It does not know what an agent
framework is: it starts, does one thing, prints text, and exits with a code
that means something. That is the reason it works with a laptop agent, an
on-phone agent, an MCP client, and a `while` loop you wrote yourself.

Everything framework-specific lives in `adapters/` and is optional — including
the Operit package, which sits among the other adapters rather than being sold
as the second half of the project:

| you have | use | read |
|---|---|---|
| a shell + adb (laptop, CI) | the CLI, `PHONE_TRANSPORT=adb` | `docs/INTEGRATE.md#1` |
| a root shell on the phone | the CLI, `PHONE_TRANSPORT=exec` | `docs/INTEGRATE.md#2` |
| Shizuku, no root | the CLI, `PHONE_EXEC='rish -c'` | `docs/INTEGRATE.md#3` |
| an MCP client (Claude Desktop, Cline, Cherry Studio, Cursor) | `adapters/mcp/phone_mcp.py` | `adapters/mcp/README.md` |
| your own function-calling loop | `adapters/openai-tools.json` | `docs/INTEGRATE.md#4` |
| a vendor AI app with only its own UI bridge | a native package for that platform | `adapters/README.md` |
| a chat box and nothing else | a human runs the commands | `adapters/prompt-only.md` |

The rule for new adapters: under ~300 lines, no re-implementation of the
actions, and the core's exit codes. A second implementation is only acceptable
on a platform with no shell at all — the Operit package is that case
(`Tools.UI` instead of `uiautomator`). Both shapes still report whether the
screen actually changed (`changed`, a fingerprint of package + activity + node
count) instead of claiming the action worked.

`SKILL.md` is the core written as an agent skill: drop the directory into a
skills folder and the model reads when to use it, how to call it, and what exit
codes 1 and 2 mean.

## Layout

```
android/eyes.sh            the device half. toybox sh only. 143 lines.
host/phone.py              the agent half. transport + gestures. subcommand CLI.
host/ui.py                 uiautomator XML -> one line per actionable node.
examples/agent.py          the smallest loop that actually finishes a task.
tests/test_ui.py           11 device-free tests for the parser.
tests/test_phone_emit.py   11 device-free tests for the emit transport.
tests/test_mcp.py          13 device-free tests for the MCP adapter.
SKILL.md                   the core as an agent skill: when, how, exit codes.
phone                      wrapper so `./phone ui` in these docs is literal.
docs/INTEGRATE.md          five ways in, per agent runtime, plus symptom tables.
docs/NOTES.md              what I measured, including the roads that dead-ended.
docs/TRANSPORT.md          the three transports and when to use each.
docs/PUBLISH.md            description, topics, push commands.
adapters/README.md         which adapter for which agent framework.
adapters/mcp/              MCP server (stdlib, 11 tools) + client configs.
adapters/openai-tools.json function-calling schemas, generated from the MCP table.
adapters/prompt-only.md    the human-as-transport workflow, with a system prompt.
adapters/operit/           native package for Operit's UI bridge, no root (optional).
CHANGELOG.md               what each version contains.
```

`eyes.sh` uses only what every Android ships: `screencap`, `uiautomator`,
`input`, `dumpsys`, `wm`.

## Install

```bash
# on the phone, as root
cp android/eyes.sh /sdcard/lcs/ && chmod 755 /sdcard/lcs/eyes.sh

# on the host
export PHONE_TRANSPORT=adb
export PHONE_SERIAL=XXXXXXXX
./host/phone.py install        # pushes eyes.sh and prints screen geometry
```

If the agent runs *on* the phone (Termux with root, or any wrapper that has a
root shell):

```bash
export PHONE_TRANSPORT=exec
export PHONE_EXEC="su -c"
./host/phone.py install
```

### When there is no shell at all

Some sandboxes give the agent one command at a time and nothing else.
`PHONE_EMIT=1` prints the device command instead of running it; the agent runs
it with its own tool and calls back. Both sides see `$REMOTE_DIR`
(`/sdcard/lcs`), so nothing is copied and nothing is faked:

```bash
$ PHONE_EMIT=1 ./host/phone.py ui
DEVICE_CMD: sh /sdcard/lcs/eyes.sh dump /sdcard/lcs/ui.xml
# stale tree; run the DEVICE_CMD above, then re-run

$ PHONE_EMIT=1 ./host/phone.py ui        # after running it
-- 87 actionable nodes
C--- ( 630, 607) 隐私 #vlist_content

$ PHONE_EMIT=1 ./host/phone.py tap-text 隐私
-> 隐私 at (630,607)
DEVICE_CMD: sh /sdcard/lcs/eyes.sh tap 630 607
```

Exit codes are part of the contract: `0` did it, `1` label not on screen,
`2` refused because the view was stale. See `docs/TRANSPORT.md` for the table.

## The UI tree is the good observation

A screenshot is 422 KB of pixels and a model has to guess where things are.
A `uiautomator` dump is 33 KB of XML where 90 % of the nodes are empty
`FrameLayout` scaffolding. `ui.py` keeps only nodes that carry text, a
`content-desc`, or are clickable/scrollable — 47 nodes for a Settings screen:

```
-S-- ( 630,1400) <ListView> #dashboard_container
C--- ( 630,  85) <FrameLayout>
---- ( 630,  85) 应用 #vlist_content
C--- ( 630, 257) <FrameLayout>
---- ( 630, 257) 指纹、面部与密码 #vlist_content
C--- ( 630, 607) <FrameLayout>
---- ( 630, 607) 隐私 #vlist_content
```

Flags are `clickable scrollable checked password`. Coordinates are the
**center in physical pixels** — exactly what `input tap` takes. No scaling
math, no vision model.

Use `phone ui` in the loop and `phone observe` only when you need pixels (a
canvas, a video, a game, a WebView that hides its tree).

### Tapping by label

Rows are usually a clickable container with no text, wrapping a text node that
is not clickable. `tap-text` handles that: it prefers a clickable hit, and
falls back to the text node's center, which lies inside the clickable parent's
bounds anyway.

```bash
$ phone tap-text "隐私"
-> 隐私 #vlist_content at (630,607)
tap 630 607
```

## Measured costs

V2403A, Android 15, 1260×2800 @ 560 dpi:

| command | time | output |
|---|---|---|
| `screencap -p` | 400 ms | 422 KB PNG |
| `uiautomator dump --compressed` | 2.1 s | 33 KB XML |
| `input tap` | 50 ms | — |
| `input keyevent` | 40 ms | — |
| `phone ui` (dump + pull + parse) | ~2.3 s | 47 lines |

`uiautomator` dominates. If you need a tight loop, cache the dump and reuse it
for several taps before re-dumping.

## Gotchas that cost real time

- **`input tap` needs the binder context.** Called from a socket-spawned
  shell (e.g. Termux `nsenter`), it fails with
  `Failure calling service input: Failed transaction (2147483646)`. From
  `adb shell` it returns 0. Keep input on the adb/root-shell side.
- **toybox `date` has no `%N`.** `date +%s%N` yields garbage; arithmetic on it
  produces negative elapsed times. Use `/proc/uptime`.
- **`uiautomator dump /dev/tty`** prints the path, not the XML.
- **`input text` eats spaces** unless you send `%s`.
- **`input text` cannot type non-ASCII.** It injects key events, so CJK and
  accented characters are dropped: the field stays empty and the command still
  exits 0. For Chinese, go through the clipboard and paste, or an IME, and
  confirm the text in the next `ui` dump instead of trusting the exit code.
- **A changed foreground package is not proof of progress.** A tap that opens a
  dialog, loads a list, or shows an error toast leaves the package name alone.
  Compare a UI-tree signature too — `examples/agent.py` shows the check — or you
  will stop a step early and call it done.
- **`topResumedActivity`** is the only reliable foreground probe on A12+;
  `mResumedActivity` is often absent.
- **`screenrecord` dies with its parent shell.** If you must use it, `setsid`
  and a pidfile, and expect orphans.

## License

MIT. See LICENSE.
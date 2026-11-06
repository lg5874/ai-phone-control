# Integrate with your agent

> 中文一句话：不管你的 agent 是电脑上的 Claude Code、手机里的 Termux、MCP 客户端，
> 还是自己写的一个 while 循环，接法都是"让它能跑一条命令"。下面五节按你手上
> 有什么来分，不需要 Operit。

The core assumption: **an agent that can run one shell command can drive a
phone.** Everything else is a wrapper. Pick the section that matches what you
have, run the 30-second check, then write the loop.

| you have | go to |
|---|---|
| a laptop and a USB cable | [1. adb](#1-adb-from-a-laptop) |
| a root shell on the phone (Termux, KernelSU, Magisk) | [2. exec on the phone](#2-exec-an-existing-root-shell) |
| Shizuku, no root | [3. Shizuku](#3-shizuku-no-root) |
| a model with function calling | [4. your own loop](#4-your-own-loop-function-calling) |
| a chat box and nothing else | [5. no tools at all](#5-no-tools-at-all) |

## 1. adb from a laptop

```bash
git clone https://github.com/lg5874/ai-phone-control && cd ai-phone-control
export PHONE_TRANSPORT=adb
export PHONE_SERIAL=$(adb devices | awk 'NR==2{print $1}')
./phone install          # pushes android/eyes.sh to /sdcard/lcs
./phone size             # 30-second check: must print Physical size
./phone ui               # what is on screen, as text
```

`adb devices` must say `device`, not `unauthorized`. Wireless debugging works
the same way; the serial is `ip:port`.

An agent on the laptop (Claude Code, Codex CLI, Cursor, a Python script) then
just runs `./phone …` through its normal shell tool. If it speaks MCP instead,
use [adapters/mcp](../adapters/mcp/README.md) and skip this transport entirely.

## 2. exec: an existing root shell

For an agent that already lives on the phone. There is no adb in the picture;
`PHONE_EXEC` *is* the transport.

```bash
export PHONE_TRANSPORT=exec
export PHONE_EXEC="su -c"       # KernelSU / Magisk
./phone install
./phone size
```

### The check that saves an hour

`./phone size` printing **nothing** with exit 0 means your `su` is not the one
you think it is. Inside a proot Ubuntu, `/usr/bin/su` is a glibc `su`: it
succeeds, switches to root, and then runs your command in the *same* mount
namespace, where `/system/bin/wm` does not exist. Measured here:

```
$ PHONE_TRANSPORT=exec PHONE_EXEC="su -c" ./phone size
$ echo $?
0                      # and not a single line of output
```

Fix it by pointing `PHONE_EXEC` at a shell that is really on the Android side:

```bash
export PHONE_EXEC="su -c"                       # Termux with root: correct
export PHONE_EXEC="tsu -c"                      # Termux:su package
export PHONE_EXEC="nsenter -t 1 -m -p sh -c"    # root, enter init's namespaces
```

Whatever you choose, `./phone size` must print
`Physical size: 1260x2800` before anything else is worth trying.

### The binder caveat

If `./phone tap` fails with

```
Failure calling service input: Failed transaction (2147483646)
```

the shell has no binder context — `input` talks to `system_server` over binder,
and a shell spawned from a socket listener (Termux's `nsenter` bridge is the
usual offender) does not have one. Observation still works (`screencap` and
`uiautomator` do not need binder); input does not. Move the action to the adb
side, or use a wrapper that keeps binder.

## 3. Shizuku, no root

Shizuku gives an app the `shell` (uid 2000) identity, which is exactly what
`adb shell` has — and `eyes.sh` only needs `screencap`, `uiautomator`, `input`,
`dumpsys`, `wm`. So `rish` can be the transport:

```bash
# rish is the Shizuku shell client (Shizuku app -> "Use Shizuku in terminal apps")
export PHONE_TRANSPORT=exec
export PHONE_EXEC="sh /sdcard/rish -c"
./phone install
./phone size
```

Flag passing through `rish` differs between releases. If `size` prints nothing,
wrap it yourself so the contract is just `wrapper <cmd>`:

```sh
#!/system/bin/sh
# /sdcard/rish_c.sh -- make rish look like `sh -c`
exec sh /sdcard/rish -c "$*"
```

```bash
export PHONE_EXEC="sh /sdcard/rish_c.sh"
```

**Not verified on this project's hardware** (the test device is KernelSU root,
no Shizuku installed). The dependency list is verified — no root-only binary is
used — but treat this section as "should work, one command to confirm", not as
a measured result. Report back if it does.

## 4. Your own loop (function calling)

`adapters/openai-tools.json` holds the schemas; the name → argv mapping already
exists in the MCP adapter, so import it instead of writing a second one:

```python
import importlib.util

spec = importlib.util.spec_from_file_location(
    "phone_mcp", "adapters/mcp/phone_mcp.py")
mcp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mcp)

tools = mcp.TOOLS                      # or load openai-tools.json
code, text = mcp.call("phone_tap_text", {"text": "隐私"})
```

`code` is the exit code. The loop that actually finishes tasks is four steps,
and step 4 is not optional:

```python
def do(task):
    while step := plan(task):
        code, seen = mcp.call("phone_ui", {})        # look
        if code != 0:
            return f"cannot see the screen: {seen}"  # do not act blind
        code, out = mcp.call(*step)                  # act
        if code == 1:
            continue                                 # not on screen: scroll
        if code != 0:
            return f"refused ({code}): {out}"        # stale / wrong app / human
        code, after = mcp.call("phone_ui", {})       # verify
        if after == seen:
            return "the tap landed and nothing changed -- stop guessing"
```

`examples/agent.py` is that loop, 150 lines, with a real prompt. Read it before
writing your own; the part worth copying is the "nothing changed" branch.

## 5. No tools at all

A chat box cannot touch a phone. The honest way to still get work done is in
[adapters/prompt-only.md](../adapters/prompt-only.md): the model writes one
command at a time, a human pastes it and pastes the output back. It is slower
and it is not pretending otherwise.

## When it does not work: symptom → layer

| symptom | you are in the wrong layer |
|---|---|
| output contains `DEVICE_CMD:` | `PHONE_EMIT=1` is set (often inherited from an earlier shell). Unset it, or run those commands yourself on purpose |
| exit 0 and no output at all | `su` is not reaching Android — see [the check](#the-check-that-saves-an-hour) |
| `Failure calling service input: Failed transaction (2147483646)` | no binder in this shell; move input to adb |
| `no node matching` for text you can see | stale tree (`--max-age`), or the text lives inside a WebView/canvas — use `./phone shot` |
| `ERROR: could not get idle state` from `uiautomator dump` | animation or video running; retry, or stop the animation |
| `SCREEN_OFF` / `HUMAN_BUSY` from an action | that is the gate doing its job: wake the phone, or wait for the human to take their hand off |
| works from your shell, not from the agent | the agent's environment has a different `PATH` or `HOME`; give the wrapper an absolute path to `host/phone.py` |

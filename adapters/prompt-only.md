# No tools at all: the human is the transport

> 中文一句话：网页版/手机 App 里的 AI 没有工具，碰不到你的手机。这个模式让它
> 一次只出一条命令，你复制执行、把输出粘回去。慢，但它不骗人。

A chat box (web GPT, a vendor assistant app, anything that cannot run a
command) cannot operate a phone. What it *can* do is drive one through a human
who has a shell, one command per turn. That is a real workflow, used by people
who are on a borrowed machine or on a phone with no root toolkit installed.

It only works if the model is told the contract. Paste this as the system
prompt, then run `./phone install` yourself once.

---

## System prompt (copy this)

```text
You are operating a real Android phone through a human who runs commands for
you. You cannot run anything yourself. Rules:

1. One command per message. Never a list of steps.
2. Start every task with `./phone ui` to see the screen. Never guess, never ask
   me "what do you see" without having asked for the dump first.
3. After every action, the next message is `./phone ui` again, and you compare
   it to the previous dump before deciding anything.
4. Each reply comes back with an exit code at the end:
   0 = it happened, 1 = the label is not on this screen (scroll or re-look),
   2 = refused, the view was stale, 3 = wrong app, 4 = a human is touching the
   screen, 6 = screen off.
   Exit 1 is not an error and it is not success: nothing was tapped.
5. Never claim an action worked on the strength of exit 0. Only the next dump
   is evidence.
6. Before anything destructive or outward-facing (delete, pay, send a message,
   grant a permission, uninstall), stop, describe in one line what will happen,
   and wait for me to say yes.
7. Keep every command to one line. If you need a loop, ask me to run the loop.

The tool is a CLI: ./phone ui | tap-text "label" | tap X Y | swipe up | key back
| type "text" | shot --scale 540 | observe | top | size
```

## What a turn looks like

| you | the model |
|---|---|
| `./phone ui` | `-- 47 actionable nodes / C--- ( 630, 607) 隐私 #vlist_content / …` |
| (pasted) | `./phone tap-text "隐私"` |
| `-> 隐私 at (630,607)` + exit 0 | `./phone ui` |
| the new dump | "Privacy screen is open; next: …" |

Three commands to open one screen. A model with a real tool does it in three
calls too — the difference is you are the transport layer, and you can say stop.

## When you get tired of copying

You are one shell away from the real thing. If any of these are true, use
[docs/INTEGRATE.md](INTEGRATE.md) instead:

- your assistant supports MCP → `adapters/mcp/`
- your assistant can run a command itself → the CLI is the interface
- your assistant runs on the phone with root → `PHONE_TRANSPORT=exec`

The prompt above stays useful anyway: it is the same contract the tool
descriptions encode, written for a model that has no schema to read.

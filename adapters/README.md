# Adapters

> 中文一句话：核心只有一条 CLI，其他框架都是可选薄适配层。**不用 Operit
> 也能用**，仓库里那一份 Operit 包只是众多接法中的一种。

The core is `host/phone.py` + `android/eyes.sh`: thirteen commands, three
transports (`adb` / `exec` / `emit`), one exit-code contract. The core does not
know what an agent framework is, and that is deliberate — it is why it works
with any of them.

Everything in this directory is optional. Each adapter is thin, and none of them
re-implements an action unless the platform genuinely has no shell (that is the
one case where a second implementation is the honest answer, not laziness).

**If your framework is not listed here, you do not need an adapter.** If it can
run one shell command, it can drive a phone: see `docs/INTEGRATE.md`.

## Which one am I?

| where your agent runs | what it has | use | read |
|---|---|---|---|
| laptop / CI (Claude Code, Codex CLI, Cursor, a script) | a shell + USB or wireless adb | the CLI, `PHONE_TRANSPORT=adb` | `docs/INTEGRATE.md#1` |
| an MCP client (Claude Desktop, Cline, Cherry Studio, Cursor, RikkaHub, …) | MCP over stdio | `mcp/phone_mcp.py` | `mcp/README.md` |
| on the phone itself (Termux, proot, a rooted sandbox) | a shell + root | the CLI, `PHONE_TRANSPORT=exec` | `docs/INTEGRATE.md#2` |
| on the phone, root but no shell bridge | Shizuku / `rish` | the CLI, `PHONE_EXEC='rish -c'` | `docs/INTEGRATE.md#3` |
| on the phone, no shell at all (vendor AI apps) | only its own UI bridge | a native package for that platform | `operit/README.md` |
| your own loop, function calling | JSON tool schemas | `openai-tools.json` | `docs/INTEGRATE.md#4` |
| a chat box with no tools (web GPT, phone assistant apps) | a human | the prompt in `prompt-only.md` — the human is the transport | `prompt-only.md` |

## Contract every adapter keeps

1. **An action is not evidence.** Return what the screen looks like *after* the
   action, or a field that says whether it changed (`changed: true`).
2. **"Not found" is an answer, not an error.** Distinct from "the tap landed and
   nothing happened", and distinct from "I could not reach the phone".
3. **Never invent coordinates.** Observe, then act, then observe again.
4. **Say which transport you are on.** A silent switch to emit mode is how an
   agent ends up reporting success for work nobody did.

## Adding an adapter for your favourite framework

Open a PR with one directory: `adapters/<name>/` containing a `README.md` (what
it wraps, how to install, what it needs) and the adapter itself. Two rules:

- Under ~300 lines. If it grows past that, it is re-implementing the CLI, and it
  will drift.
- Map failures onto the existing exit codes rather than inventing a parallel
  vocabulary: `0` done, `1` target not on screen, `2` refused / stale, `3` wrong
  app, `4` human is using the phone, `6` screen off.

Tests for an adapter should run without a device (`tests/test_*.py` shows the
pattern: feed it a fixture, assert on the output, no phone attached).

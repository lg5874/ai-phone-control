# Transport modes

`phone.py` never assumes it can reach the device. Three modes, one env var.

## 1. `adb` — host machine with USB or wireless adb

```bash
export PHONE_TRANSPORT=adb
export PHONE_SERIAL=emulator-5554     # omit if only one device
./host/phone.py install
./host/phone.py ui
```

`install` pushes `android/eyes.sh` to `$PHONE_DIR` (default `/sdcard/lcs`)
and prints the screen geometry. Requires `adb` in `PATH`.

## 2. `exec` — agent already has a root shell on the device

This is the case when the agent runs in Termux, or in any sandbox that can
invoke `su -c '<cmd>'`. There is no adb in the picture; the shell *is* the
transport.

```bash
export PHONE_TRANSPORT=exec
export PHONE_EXEC="su -c"            # or "adb shell", or a wrapper script
./host/phone.py install
./host/phone.py ui
```

If `input tap` fails here with
`Failure calling service input: Failed transaction (2147483646)`, the shell
has no binder context — see the note at the bottom.

## 3. `emit` — no channel at all, the agent is the bridge

Some sandboxes cannot spawn a device shell. The agent has a *tool* that runs
one command at a time, and nothing else. `emit` mode prints what it would have
run, then stops:

```bash
export PHONE_EMIT=1
$ ./host/phone.py ui
DEVICE_CMD: sh /sdcard/lcs/eyes.sh dump /sdcard/lcs/ui.xml
# stale tree; run the DEVICE_CMD above, then re-run
```

The agent runs that one command with its own tool and calls us again. Both
sides already see the same `$REMOTE_DIR` (`/sdcard/lcs` by default), so there
is no copy step and no ingest flag: the artifact is readable in place.

```bash
$ ./host/phone.py ui          # fresh tree -> no DEVICE_CMD at all
-- 87 actionable nodes
C--- ( 630, 607) 隐私 #vlist_content

$ ./host/phone.py tap-text 隐私
-> 隐私 at (630,607)
DEVICE_CMD: sh /sdcard/lcs/eyes.sh tap 630 607
```

The rule in emit mode is **never report success without evidence**:

| situation | behaviour |
|---|---|
| tree fresh | parse it, print no device command |
| tree older than `--max-age` | warn on stderr; `--strict` makes it exit 2 |
| tree missing | exit non-zero and print the `DEVICE_CMD` that would create it |
| `top` with no fresh `top.txt` | exit 2 and print the command that writes one |
| `tap-text` facing a stale tree | exit 2, do not aim at moved coordinates |
| label not on screen | exit 1, name what was searched for |

`ui.py` stays device-free, so `./host/ui.py parse <file>` and
`./host/ui.py tap <file> <label>` work in every mode.

## Picking one

| situation | mode |
|---|---|
| laptop, USB cable | `adb` |
| laptop, wireless debugging | `adb` |
| Termux on the same phone, rooted | `exec` |
| sandbox with a one-command-at-a-time tool | `emit` |
| CI against an emulator | `adb` |

## The binder caveat

`input` talks to `system_server` over binder. A shell spawned from a socket
listener (Termux's `nsenter` bridge is the usual offender) has no binder
context and every `input` call fails:

```
input tap 630 1400
cmd: Failure calling service input: Failed transaction (2147483646)
```

The same command via `adb shell` returns 0. If you hit this, either move input
to the adb side, or use `sendevent` against `/dev/input/event*` (root, and
device-specific — not portable enough for this repo). `screencap` and
`uiautomator` do *not* need binder, which is why observation still works in
that situation.
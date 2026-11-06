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
run, and stops.

```bash
export PHONE_EMIT=1
$ ./host/phone.py observe --scale 540
DEVICE_CMD: sh /sdcard/lcs/eyes.sh observe /sdcard/lcs
DEVICE_PULL: /sdcard/lcs/shot.png -> /tmp/phone/shot.png
DEVICE_PULL: /sdcard/lcs/ui.xml -> /tmp/phone/ui.xml
```

The agent then runs that command with its own tool, copies the two files down,
and calls the *pure* commands which need no device at all:

```bash
$ ./host/ui.py parse /tmp/phone/ui.xml
C--- ( 630, 607) 隐私 #vlist_content
...
$ ./host/ui.py tap /tmp/phone/ui.xml 隐私
630 607
```

Then it emits the tap:

```bash
$ PHONE_EMIT=1 ./host/phone.py tap 630 607
DEVICE_CMD: sh /sdcard/lcs/eyes.sh tap 630 607
```

Two round trips per action, but the agent keeps full control and the repo
stays honest about the fact that it does not own the transport. `ui.py` is
deliberately device-free for exactly this reason.

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
# Field notes

Everything here was measured on a vivo V2403A running Android 15, from an
agent process that could not see `/system`. The measurements are the useful
part; the phone model is not.

## What "one-shot" actually means

The first version streamed the screen: `screenrecord` -> h264 -> ffmpeg ->
mjpeg -> a frame extractor that kept the newest JPEG. It produced frames in
~150 ms and looked great in a demo.

Then I measured what it cost to do nothing:

```
$ ./phone.py start && sleep 60
$ ps -A | grep -E 'screenrecord|ffmpeg'
20268  screenrecord --output-format=h264 --size 540x1200 ...
20341  ffmpeg -f h264 -i pipe:0 -q:v 4 -f image2pipe ...
```

Two processes, one of them a hardware decoder, burning a core for a minute
while nothing was being observed. An agent spends most of its time *thinking*,
not looking. That is the wrong trade.

Worse, when the parent shell was reaped, `screenrecord` died with it and left
`ffmpeg` and the extractor orphaned, still holding a stale `.pid`. The next
`start` had to guess which of the four processes were zombies.

The replacement is one command that exits:

```
$ time screencap -p /sdcard/lcs/shot.png
real 0m0.401s
```

400 ms, and then nothing at all. An agent that looks 200 times pays 80 seconds
of phone time and 0 % CPU between looks. That is the whole design.

## The proot wall, in two parts

This is the part I got wrong twice, so it is worth writing down precisely.

**Wall 1: the mount namespace.** A proot Ubuntu has no `/system`:

```
$ ls /system/bin/
ls: cannot access '/system/bin/': No such file or directory
$ /system/bin/screencap -p out.png
bash: /system/bin/screencap: No such file or directory
```

**Wall 2: not glibc.** Copy the binary somewhere visible and it still fails,
because Android binaries link against `linker64`, not `ld-linux`:

```
$ cp /system/bin/screencap /data/local/tmp/sc && /data/local/tmp/sc -h
bash: /data/local/tmp/sc: cannot execute: required file not found
```

That message means "wrong interpreter", not "missing file". Supplying
`linker64` gets further than you would expect:

```
$ ./linker64 /root/sc -h
CANNOT LINK EXECUTABLE "/root/sc": library "libcutils.so" not found
```

So I wrote a resolver: read `NEEDED` out of every staged `.so`, fetch what is
missing, repeat. It ran for a while and then this happened:

```
round 1: 43 missing
round 2: 62 missing      (98 libraries staged)
round 3: 71 missing
```

**The count grew.** `libgui` pulls in SurfaceFlinger internals; those pull in
HIDL and AIDL service stubs; those pull in more. There is no fixed point, and
each round costs a cross-system round trip. Chasing it is a package manager's
job. I stopped, deleted 55 staged libraries, and changed the architecture
instead.

The resolver survives in the history as a lesson, not as code.

## Why the UI tree beats the screenshot

A screenshot at native resolution:

```
$ screencap -p shot.png && ls -l shot.png
-rw-rw---- 1 u0_a0 media_rw 422415 shot.png      # 1260x2800
```

422 KB of pixels. A model has to *find* the button in there, and any coordinate
it produces is a guess that has to be scaled from whatever size the image was
downsampled to.

The same screen as a `uiautomator` dump:

```
$ uiautomator dump --compressed ui.xml && ls -l ui.xml
-rw-rw---- 1 u0_a0 media_rw 33076 ui.xml         # 33 KB, 90% empty nodes
```

Still too much. After filtering to nodes that carry text, a `content-desc`, or
are clickable/scrollable:

```
$ ui.py parse ui.xml
C--- ( 630, 607) 隐私 #vlist_content
C--- ( 630, 965) 电池 #vlist_content
-- 47 actionable nodes
```

47 lines, real physical-pixel centers, no vision model, no scaling math.
`uiautomator` costs 2.1 s versus `screencap`'s 0.4 s, so the text route is
slower per look — and still cheaper, because it removes the coordinate guessing
that causes failed taps and retries.

Use pixels only when the tree is empty: canvas, video, games, some WebViews.

## Tapping the row that has no text

Settings rows look like this in the dump:

```
<FrameLayout clickable="true" bounds="[0,500][1260,714]">     <- no text
  <TextView text="隐私" clickable="false" bounds="[0,500][1260,714]"/>
</FrameLayout>
```

The clickable node has no text; the text node is not clickable. Filtering for
"clickable and matching" finds nothing, which is exactly the bug `tap-text` had
on its first run:

```
$ phone tap-text "隐私"
no clickable node matching '隐私'
```

The fix is to accept a text hit too — its center lies inside the clickable
parent's bounds, so the tap lands correctly:

```
$ phone tap-text "隐私"
-> 隐私 #vlist_content at (630,607)
tap 630 607
```

This is pinned by `tests/test_ui.py::test_tap_falls_back_to_text_node`,
because it is the kind of thing that silently regresses.

## Small traps that cost real time

**`input` needs binder.** From a socket-spawned shell (Termux's `nsenter`
bridge is the usual one):

```
$ input tap 630 1400
cmd: Failure calling service input: Failed transaction (2147483646)
$ echo $?
0
```

Note the exit code: **zero**. It failed and reported success. The same command
through `adb shell` returns 0 and actually taps. `screencap` and `uiautomator`
do not need binder, so observation works even when input does not — which is
how the failure was isolated.

**toybox `date` has no `%N`.**

```
$ date +%s%N
2804861N
```

Not nanoseconds — a literal `N` glued on. Timing with it produced
`elapsed -1627ms`. `/proc/uptime` works and is what `eyes.sh` uses.

**`uiautomator dump /dev/tty`** prints the destination path, not the XML. There
is no stdout mode.

**`input text` eats spaces** unless you send `%s`.

**`topResumedActivity`** is the only reliable foreground probe on Android 12+;
`mResumedActivity` is often absent from the dump entirely.

**`screenrecord` dies with its parent shell**, so any streaming design needs
`setsid` plus pidfiles, and should expect orphans after a crash.

## What I would do differently

Start with `phone ui`, not with frames. The text tree is a better interface for
a model than an image in every case except when it is empty, and finding that
out took building the whole streaming pipeline first.
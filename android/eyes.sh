#!/system/bin/sh
# eyes.sh -- give an agent eyes and hands on an Android device.
#
# Runs as root via adb shell / KernelSU / Magisk. No dependencies beyond what
# every Android build ships: screencap, uiautomator, input, dumpsys.
#
# DESIGN: one command, one process, exit. Nothing is left running. An agent
# that drives this in a loop costs ~0.5 s per observation and nothing at all
# between observations. There is no daemon, no screenrecord, no ffmpeg.
#
# WHY NOT STREAMING
#   We tried screenrecord -> h264 -> ffmpeg -> mjpeg -> frame extractor. It
#   works, and it is the wrong shape for an agent: it pins a decoder core,
#   leaves orphan processes when the parent shell is reaped, and still needs a
#   round trip per decision. screencap is 400 ms. Take the 400 ms.
#
# WHY THIS FILE CANNOT LIVE IN A PROOT UBUNTU
#   Two hard walls, both measured:
#     1. proot has no /system in its mount namespace, so /system/bin/screencap
#        is simply absent. Copying the binary in does not help.
#     2. Android binaries are not glibc. They need linker64 plus the full
#        NEEDED closure of libgui/libui/libbinder. That closure does not
#        terminate -- staging 99 libraries still left 62 missing, and the
#        count grew each round. Linker64 runs under proot, but the library
#        graph never closes.
#   So: observation commands run on the Android side. Parsing runs wherever
#   you like. The agent process itself is the bridge.
#
# USAGE
#   eyes.sh shot [path]         screenshot, downscaled-ready PNG
#   eyes.sh dump [path]         compressed UI hierarchy (XML)
#   eyes.sh top                 foreground package + activity
#   eyes.sh tap X Y
#   eyes.sh long X Y [MS]
#   eyes.sh swipe X1 Y1 X2 Y2 [MS]
#   eyes.sh key NAME            e.g. KEYCODE_HOME, KEYCODE_BACK
#   eyes.sh text "hello world"
#   eyes.sh size                screen geometry + density
#   eyes.sh observe [dir]       shot + dump + top in one call
#
# All paths default under $OUT. Coordinates are physical pixels; run
# `eyes.sh size` first and scale your model's view accordingly.

set -u
OUT=${OUT:-/sdcard/lcs}

# Some callers (su -c from a proot container, minimal root shells) hand us a
# PATH without /system/bin, and then `wm`/`input`/`screencap` look missing.
# Put the real toolbox first rather than trusting the caller's environment.
PATH=/system/bin:/system/xbin:/vendor/bin:/sbin:$PATH
export PATH

cmd=${1:-}
[ -z "$cmd" ] && { sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }
shift 2>/dev/null || true

case "$cmd" in
  shot)
    p=${1:-$OUT/shot.png}
    mkdir -p "$(dirname "$p")" 2>/dev/null
    screencap -p "$p" || exit 1
    echo "$p $(wc -c < "$p" 2>/dev/null || echo 0)"
    ;;

  dump)
    p=${1:-$OUT/ui.xml}
    mkdir -p "$(dirname "$p")" 2>/dev/null
    # --compressed drops the empty layout nodes; 33 KB vs 47 KB, same tree.
    uiautomator dump --compressed "$p" >/dev/null 2>&1
    [ -f "$p" ] || { echo "dump failed" >&2; exit 1; }
    echo "$p $(wc -c < "$p")"
    ;;

  top)
    # topResumedActivity is the only reliable "what is in front" on A12+.
    dumpsys activity activities 2>/dev/null \
      | grep -m1 'topResumedActivity' \
      | sed 's/.*topResumedActivity=//'
    ;;

  tap)
    [ $# -ge 2 ] || { echo "tap needs X Y" >&2; exit 2; }
    input tap "$1" "$2"
    echo "tap $1 $2"
    ;;

  long)
    [ $# -ge 2 ] || { echo "long needs X Y [MS]" >&2; exit 2; }
    # input has no long-press verb; swipe in place is the documented idiom.
    input swipe "$1" "$2" "$1" "$2" "${3:-600}"
    echo "long $1 $2 ${3:-600}"
    ;;

  swipe)
    [ $# -ge 4 ] || { echo "swipe needs X1 Y1 X2 Y2 [MS]" >&2; exit 2; }
    input swipe "$1" "$2" "$3" "$4" "${5:-300}"
    echo "swipe $1 $2 $3 $4 ${5:-300}"
    ;;

  key)
    [ -n "${1:-}" ] || { echo "key needs a KEYCODE name" >&2; exit 2; }
    input keyevent "$1"
    echo "key $1"
    ;;

  text)
    [ -n "${1:-}" ] || { echo "text needs a string" >&2; exit 2; }
    # input text eats spaces unless escaped; %s is the accepted form.
    s=$(printf '%s' "$1" | sed 's/ /%s/g')
    input text "$s"
    echo "text $1"
    ;;

  size)
    wm size | sed 's/^/size: /'
    wm density | sed 's/^/density: /'
    ;;

  observe)
    d=${1:-$OUT}
    mkdir -p "$d" 2>/dev/null
    # toybox date has no %N on Android, so time the phases with SECONDS
    # granularity is too coarse. Use the shell's own clock via /proc/uptime.
    t0=$(cut -d' ' -f1 /proc/uptime)
    screencap -p "$d/shot.png"
    uiautomator dump --compressed "$d/ui.xml" >/dev/null 2>&1
    t1=$(cut -d' ' -f1 /proc/uptime)
    echo "shot $d/shot.png"
    echo "dump $d/ui.xml"
    # Write the foreground probe to a file as well as stdout: an agent in emit
    # mode has no other way to read it, and a printed command is not a fact.
    dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity \
        | sed 's/.*topResumedActivity=//' > "$d/top.txt"
    echo "top $(cat "$d/top.txt")"
    # /proc/uptime is seconds with 2 decimals; bash arithmetic needs ints
    echo "elapsed $(( ${t1%.*} - ${t0%.*} ))s"
    ;;

  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac

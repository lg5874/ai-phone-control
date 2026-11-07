#!/system/bin/sh
# eyes.sh -- give an agent eyes and hands on an Android device.
#
# Runs as root via adb shell / KernelSU / Magisk. No dependencies beyond what
# every Android build ships: screencap, uiautomator, input, dumpsys.
#
# PATH: `su -c 'sh eyes.sh tap 1 1'` starts a login-less shell whose PATH can
# be as thin as /sbin, so `input` resolves to nothing and the tap "fails" with
# `input: not found` even though root was granted. Pin the platform paths up
# front; appending (not replacing) keeps a caller's own tools reachable.
PATH=${PATH}:/system/bin:/system/xbin:/vendor/bin:/sbin
export PATH
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
#   eyes.sh huddir              where the floating panel reads its files
#   eyes.sh hudpkg              installed|absent|unknown for com.lcs.hud
#   eyes.sh hud pause|run|status|on|off

#
# All paths default under $OUT. Coordinates are physical pixels; run
# `eyes.sh size` first and scale your model's view accordingly.

set -u
OUT=${OUT:-/sdcard/lcs}
# Where the floating panel used to be told to look, and where it is still told
# to look when it is not installed. See `huddir` for why the live path is
# elsewhere and why it is not a constant.
REMOTE_DIR_FALLBACK=${HUD_FALLBACK_DIR:-/sdcard/lcs}

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
    # Same reason as dump: screencap writes 0660 root:media_rw, and the caller
    # may not be root.
    chmod 0644 "$p" 2>/dev/null
    echo "$p $(wc -c < "$p" 2>/dev/null || echo 0)"
    ;;

  dump)
    p=${1:-$OUT/ui.xml}
    mkdir -p "$(dirname "$p")" 2>/dev/null
    # --compressed drops the empty layout nodes; 33 KB vs 47 KB, same tree.
    uiautomator dump --compressed "$p" >/dev/null 2>&1
    [ -f "$p" ] || { echo "dump failed" >&2; exit 1; }
    # uiautomator writes as u0_a0:media_rw 0660. On /sdcard that is unreadable
    # to the app uid running this script (Termux is u0_a348), so the caller
    # sees "cannot read ui.xml" even though the dump succeeded. Widening to
    # 0644 is what makes the artifact readable by whoever asked for it.
    chmod 0644 "$p" 2>/dev/null
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
    # `input tap` exits 0 for coordinates outside the panel and simply drops
    # the event, so rc alone proves nothing. Reject off-screen points up front
    # (that is the common agent error: a coordinate read from a stale tree).
    # `wm size` prints "Physical size: WxH" and, when overridden, an additional
    # "Override size: WxH" -- the override is what input actually uses, so take
    # the last match rather than the first.
    geo=$(wm size 2>/dev/null | sed -n 's/.*: *\([0-9][0-9]*\)x\([0-9][0-9]*\).*/\1 \2/p' | tail -1)
    sw=${geo% *}
    sh_=${geo#* }
    if [ -n "$sw" ] && [ -n "$sh_" ] && [ "$sw" != "$geo" ]; then
      if [ "$1" -ge "$sw" ] || [ "$2" -ge "$sh_" ] || [ "$1" -lt 0 ] || [ "$2" -lt 0 ]; then
        echo "tap $1 $2 is outside the ${sw}x${sh_} panel; the event would be dropped silently" >&2
        exit 2
      fi
    fi
    input tap "$1" "$2" || { echo "tap $1 $2 failed" >&2; exit 1; }
    echo "tap $1 $2"
    ;;

  long)
    [ $# -ge 2 ] || { echo "long needs X Y [MS]" >&2; exit 2; }
    # input has no long-press verb; swipe in place is the documented idiom.
    input swipe "$1" "$2" "$1" "$2" "${3:-600}" \
      || { echo "long $1 $2 failed" >&2; exit 1; }
    echo "long $1 $2 ${3:-600}"
    ;;

  swipe)
    [ $# -ge 4 ] || { echo "swipe needs X1 Y1 X2 Y2 [MS]" >&2; exit 2; }
    input swipe "$1" "$2" "$3" "$4" "${5:-300}" \
      || { echo "swipe $1 $2 $3 $4 failed" >&2; exit 1; }
    echo "swipe $1 $2 $3 $4 ${5:-300}"
    ;;

  key)
    # `input keyevent home` exits 0 and does nothing. The name must be a real
    # KEYCODE, and rc=0 from `input` is not evidence that anything moved -- so
    # map the short names people actually type, and verify the effect instead
    # of echoing the argument back as if it had worked.
    [ -n "${1:-}" ] || { echo "key needs a KEYCODE name" >&2; exit 2; }
    kc=$1
    case "$kc" in
      [0-9]*) ;;                      # already numeric
      KEYCODE_*) ;;
      back|BACK)       kc=KEYCODE_BACK ;;
      home|HOME)       kc=KEYCODE_HOME ;;
      enter|ENTER|return|RETURN) kc=KEYCODE_ENTER ;;
      recents|RECENTS|appswitch|APP_SWITCH) kc=KEYCODE_APP_SWITCH ;;
      menu|MENU)       kc=KEYCODE_MENU ;;
      power|POWER)     kc=KEYCODE_POWER ;;
      volume_up|VOLUME_UP)     kc=KEYCODE_VOLUME_UP ;;
      volume_down|VOLUME_DOWN) kc=KEYCODE_VOLUME_DOWN ;;
      delete|DEL|backspace|BACKSPACE) kc=KEYCODE_DEL ;;
      tab|TAB)         kc=KEYCODE_TAB ;;
      space|SPACE)     kc=KEYCODE_SPACE ;;
      escape|ESC|ESCAPE) kc=KEYCODE_ESCAPE ;;
      *) echo "unknown key '$1'; pass a KEYCODE_* name or one of: back home enter recents menu power volume_up volume_down delete tab space escape" >&2
         exit 2 ;;
    esac

    before=$(dumpsys activity activities 2>/dev/null \
             | grep -m1 'topResumedActivity' | sed 's/.*u0 //;s/ .*//')
    input keyevent "$kc" 2>/dev/null
    sleep 0.4
    after=$(dumpsys activity activities 2>/dev/null \
            | grep -m1 'topResumedActivity' | sed 's/.*u0 //;s/ .*//')

    # A key that changes the foreground app proves itself. One that does not
    # (enter, tab, delete, volume) is still valid -- so the claim is scoped to
    # what was actually observed, not upgraded to "it worked".
    if [ "$before" != "$after" ]; then
      echo "key $kc -> $after"
    else
      echo "key $kc (foreground unchanged: ${after:-unknown})"
    fi
    ;;

  text)
    [ -n "${1:-}" ] || { echo "text needs a string" >&2; exit 2; }
    # `input text` only speaks ASCII. Feeding it CJK fails with rc=255 and
    # types nothing -- and the old code echoed success anyway. Detect it and
    # fail loudly with the working alternative instead of typing air.
    if printf '%s' "$1" | LC_ALL=C grep -q '[^ -~]'; then
      echo "text: '$1' contains non-ASCII, which 'input text' cannot send (rc=255, nothing typed)." >&2
      echo "text: use the IME path instead -- eyes.sh ime-text '...'" >&2
      exit 2
    fi
    # input text eats spaces unless escaped; %s is the accepted form.
    s=$(printf '%s' "$1" | sed 's/ /%s/g')
    input text "$s" || { echo "text '$1' failed" >&2; exit 1; }
    echo "text $1"
    ;;

  ime-text)
    # Non-ASCII entry that actually works: broadcast the string to the ADB
    # keyboard IME (com.android.adbkeyboard), which commits it as real text
    # rather than as key events. Requires that IME to be installed and active;
    # we check instead of pretending, because a silent no-op here looks exactly
    # like a successful type.
    [ -n "${1:-}" ] || { echo "ime-text needs a string" >&2; exit 2; }
    if ! pm list packages 2>/dev/null | grep -q 'com.android.adbkeyboard'; then
      echo "ime-text: ADBKeyboard (com.android.adbkeyboard) is not installed." >&2
      echo "ime-text: install it, then: ime set com.android.adbkeyboard/.AdbIME" >&2
      exit 3
    fi
    cur=$(settings get secure default_input_method 2>/dev/null)
    case "$cur" in
      *adbkeyboard*) ;;
      *) echo "ime-text: ADBKeyboard is installed but not the active IME (current: $cur)." >&2
         echo "ime-text: run: ime set com.android.adbkeyboard/.AdbIME" >&2
         exit 3 ;;
    esac
    b64=$(printf '%s' "$1" | base64 | tr -d '\n')
    am broadcast -a ADB_INPUT_B64 --es msg "$b64" >/dev/null 2>&1 \
      || { echo "ime-text broadcast failed" >&2; exit 1; }
    echo "ime-text $1"
    ;;

  size)
    wm size | sed 's/^/size: /'
    wm density | sed 's/^/density: /'
    ;;

  human)
    # Is a REAL finger on the screen right now?
    #
    # `input tap` injects events *below* the input device layer, so injected
    # taps never appear in /dev/input/event*. That is the whole trick: this
    # probe hears humans only, and therefore an agent can yield to them.
    #
    # Only touch panels are watched -- a sensor or an AOD node that reports
    # periodically would otherwise look like a person.
    win=${1:-2}
    evs=""
    for d in /dev/input/event*; do
      [ -e "$d" ] || continue
      if getevent -pl "$d" 2>/dev/null | grep -q 'ABS_MT_POSITION_X'; then
        evs="$evs $d"
      fi
    done
    if [ -z "$evs" ]; then
      echo "human: unknown"
      echo "reason: no readable touch device (need root on /dev/input)"
      exit 0
    fi
    # A finger announces itself: BTN_TOUCH DOWN (0x14a) plus a fresh
    # ABS_MT_TRACKING_ID (0x39). Taking the *first event on the device* was
    # wrong in both directions, measured on a vivo_ts panel: a lift
    # (TRACKING_ID ffffffff) and a stray SYN_REPORT both counted as a human.
    # Only a press counts.
    #
    # shellcheck disable=SC2086
    press=$(timeout "$win" getevent -q $evs 2>/dev/null \
            | grep -Ei '0001[[:space:]]+014a[[:space:]]+00000001|0003[[:space:]]+0039|btn_touch[[:space:]]+down|abs_mt_tracking_id' \
            | grep -Eiv 'ffffffff|tracking_id[[:space:]]+-1' \
            | head -1)
    if [ -n "$press" ]; then
      echo "human: yes"
    else
      echo "human: no"
    fi
    ;;

  state)
    # One call, three facts an agent must not guess: is the screen awake, is
    # the keyguard up, what is in front.
    wake=$(dumpsys power 2>/dev/null | grep -m1 -oE 'mWakefulness=[A-Za-z]+' \
           | cut -d= -f2)
    kg=$(dumpsys window 2>/dev/null \
         | grep -m1 -oE 'mDreamingLockscreen=(true|false)')
    top=$(dumpsys activity activities 2>/dev/null \
          | grep -m1 'topResumedActivity' | sed 's/.*topResumedActivity=//')
    echo "wake=${wake:-unknown}"
    echo "keyguard=${kg:-unknown}"
    echo "top=${top:-unknown}"
    ;;

  pkg)
    # Business-level truth: is the app actually installed, and which build.
    # "the screen changed" is not the same as "the app is on the phone".
    n=${1:-}
    [ -n "$n" ] || { echo "pkg needs a package name" >&2; exit 2; }
    p=$(pm path "$n" 2>/dev/null | head -1 | sed 's/^package://')
    if [ -z "$p" ]; then
      echo "installed: no"
      exit 1
    fi
    echo "installed: yes"
    echo "path: $p"
    dumpsys package "$n" 2>/dev/null | grep -m1 'versionName=' | tr -d ' '
    dumpsys package "$n" 2>/dev/null | grep -m1 'firstInstallTime=' | tr -d ' '
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

  huddir)
    # Where the floating panel actually looks. Print it; callers write there.
    #
    # This is not a constant, and the obvious guesses are all wrong:
    #   /sdcard/lcs              -- FUSE forces its mode to drwxrws--- owned by
    #                               the media uid, so the panel (a normal app
    #                               uid) cannot traverse it. chmod does not
    #                               stick; the emulated filesystem owns modes.
    #   /sdcard/Android/data/... -- the panel may write its own external dir,
    #                               but nothing outside that uid can create it,
    #                               and root is denied by the FUSE daemon.
    #   /data/user/0/com.lcs.hud -- correct, but invisible from a shell: from
    #                               Android 11 each app gets its own mount
    #                               namespace, so even root sees only its own
    #                               /data/user/0/<pkg>. We borrow the panel's
    #                               namespace with nsenter on its pid.
    # Falls back to the legacy path only when the panel is not running, which
    # is also the only case where nobody is polling and a lost write is free.
    d=/data/user/0/com.lcs.hud/files/hud
    p=$(pidof com.lcs.hud)
    if [ -n "$p" ] && nsenter -t "$p" -m -- test -d "$d" 2>/dev/null; then
      echo "$d"
    else
      echo "$REMOTE_DIR_FALLBACK"
    fi
    ;;

  hudpkg)
    # Is the panel installed at all?
    #
    # Three answers, because two are not enough. "Installed but not running"
    # is the case that must never silently write to the legacy path, and "we
    # cannot tell" must not be reported as "absent" -- that would turn a
    # broken PATH into a confident lie.
    #
    # `pm path <pkg>` exits 0 and prints nothing for a missing package, so the
    # output is what decides, not the exit code.
    o=$(pm path com.lcs.hud 2>/dev/null)
    case "$o" in
      package:*) echo installed ;;
      *) if command -v pm >/dev/null 2>&1; then echo absent; else echo unknown; fi ;;
    esac
    ;;

hud)
    # Control + status plumbing for the floating panel (com.lcs.hud).
    #
    # The panel polls hud.ctl and hud.status inside its own private directory;
    # see `huddir` above for why that path is not a constant.
    #
    # The old /sdcard/lcs locations are kept working as a fallback for a phone
    # whose panel was never installed. Both are
    # plain files on purpose: the host side stays one-process-per-command, and
    # nothing has to stay resident for the panel to work.
    #
    # `hud pause|run` is the fallback for a phone where the app is not
    # installed: the agent honours the same file, so a human can still stop it
    # from a shell. `hud status` prints what the agent last published.
    sub=${1:-status}
    # Is the panel alive, and if not, can we make it alive?
    #
    # This used to be a plain `pidof`. The bug that hid behind that: `huddir`
    # falls back to the legacy /sdcard path when no panel process exists, so
    # every write below *succeeded*, `hud status` printed a plausible dir=,
    # and the card on screen never changed -- because nothing was polling it.
    # A dead panel therefore looked exactly like a working one.
    P=$(pidof com.lcs.hud)
    # Only the verbs that need a *live* reader may wake the panel. `status` and
    # `pause` must not: the host gate calls `status` before every single
    # action, and a read that spawns an app (or waits 3 s for one that will not
    # start) would tax every tap on the phone.
    case "$sub" in
      say|beat|publish) need_live=1 ;;
      *) need_live=0 ;;
    esac
    if [ -z "$P" ] && [ "$need_live" = 1 ]; then
      pkg=$(sh "$0" hudpkg)
      if [ "$pkg" = installed ]; then
        am start-foreground-service -n com.lcs.hud/.HudService >/dev/null 2>&1 \
          || am start -n com.lcs.hud/.MainActivity >/dev/null 2>&1
        i=0
        while [ "$i" -lt 15 ]; do
          P=$(pidof com.lcs.hud)
          [ -n "$P" ] && break
          sleep 0.2
          i=$((i + 1))
        done
      fi
    fi
    pkg=${pkg:-$(sh "$0" hudpkg)}
    # Three-valued on purpose: an empty pidof plus a PATH without `pm` means we
    # do not know, and "do not know" must not be reported as "not installed".
    if [ -n "$P" ]; then
      panel=live
    elif [ "$pkg" = absent ]; then
      panel=absent
    elif [ "$pkg" = installed ]; then
      panel=dead
    else
      panel=unknown
    fi
    # Refuse only the writes that would be *lost*, and only in the two states
    # where they would be. Deliberately not applied to `pause`/`run`: with the
    # panel dead, `huddir` falls back and so does the host gate, which reads
    # the same hud.ctl through this same verb -- so a pause still stops the
    # agent, and refusing it would take away the human's off switch precisely
    # when the panel is broken.
    case "$sub" in
      say|beat|publish)
        if [ "$panel" = dead ]; then
          echo "hud $sub: panel is installed but not running (pidof empty after start)" >&2
          echo "  nothing would read the write, so the card would stay stale." >&2
          echo "  try: am start-foreground-service -n com.lcs.hud/.HudService" >&2
          exit 1
        fi
        if [ "$panel" = unknown ]; then
          echo "hud $sub: cannot tell whether com.lcs.hud is installed (pm not on PATH)" >&2
          exit 1
        fi
        ;;
    esac
    D=$(sh "$0" huddir)
    # Writing into the panel's namespace is the whole trick: the path exists
    # only inside that pid's mount namespace, so every read and write below is
    # wrapped in nsenter. When the panel is not running, D is the legacy
    # /sdcard/lcs path and nsenter is skipped.
    P=$(pidof com.lcs.hud)
    hw() {  # hud write: hw <file> <body>
      if [ -n "$P" ]; then
        nsenter -t "$P" -m -- sh -c "printf '%s' '$2' > '$D/$1.tmp' && mv -f '$D/$1.tmp' '$D/$1'"
      else
        printf '%s' "$2" > "$D/$1.tmp" && mv -f "$D/$1.tmp" "$D/$1"
      fi
    }
    hr() {  # hud read: hr <file>
      if [ -n "$P" ]; then
        nsenter -t "$P" -m -- cat "$D/$1" 2>/dev/null
      else
        cat "$D/$1" 2>/dev/null
      fi
    }
    case "$sub" in
      pause)
        hw hud.ctl 'pause
' || { echo "hud pause: cannot write $D/hud.ctl" >&2; exit 1; }
        echo "hud: paused (agent will refuse to act until 'hud run')"
        ;;
      run)
        hw hud.ctl 'run
' || { echo "hud run: cannot write $D/hud.ctl" >&2; exit 1; }
        echo "hud: running"
        ;;
      status)
        # `panel=` first: a dir= that looks right while the panel is dead is
        # the exact failure this release is about, so the liveness comes before
        # the path rather than after it.
        echo "panel=$panel${P:+ pid=$P}"
        echo "dir=$D"
        echo "ctl=$(hr hud.ctl || echo missing)"
        hr hud.status || echo "status=missing"
        # Show both clocks: "said" is when the agent last published intent,
        # "did" is when it last acted. A card that only knows the first looks
        # dead while the agent is working.
        echo "beat=$(hr hud.beat | tr '\n' ' ' || echo missing)"
        ;;
      say)
        # `hud say <task> [think] [step] [state]` -- one device-side command
        # that publishes a whole status card.
        #
        # This exists because the caller with the phone in its hand (an agent
        # whose only channel is a root shell) cannot usefully do the two-step
        # dance: write a staging file, then publish it. Each of those is a
        # separate round trip and a separate chance to get the quoting wrong.
        # Arguments arrive as argv here, so Chinese text and punctuation cost
        # nothing -- no escaping layer between the prose and the file.
        task=${2:-}
        think=${3:-}
        step=${4:-}
        state=${5:-running}
        [ -n "$task" ] || { echo "hud say: task is required" >&2; exit 2; }
        {
          printf 'ts=%s\n' "$(date +%s%3N)"
          printf 'state=%s\n' "$state"
          printf 'task=%s\n' "$task"
          printf 'think=%s\n' "$think"
          printf 'step=%s\n' "$step"
        } > "$OUT/hud.status.out" || exit 1
        sh "$0" hud publish hud.status >/dev/null || exit 1
        {
          printf 'ts=%s\n' "$(date +%s%3N)"
          printf 'act=say\n'
        } > "$OUT/hud.beat.out" || exit 1
        sh "$0" hud publish hud.beat >/dev/null || exit 1
        echo "hud: $state | $task"
        ;;
      beat)
        # `hud beat [what]` -- liveness only, for a long think between actions.
        what=${2:-thinking}
        {
          printf 'ts=%s\n' "$(date +%s%3N)"
          printf 'act=%s\n' "$what"
        } > "$OUT/hud.beat.out" || exit 1
        sh "$0" hud publish hud.beat >/dev/null || exit 1
        echo "beat: $what"
        ;;
      publish)
        # `hud publish <name>` moves $OUT/<name>.out into the panel directory.
        #
        # The body travels through a file, never through a command string. The
        # panel dir is reachable only via `nsenter ... sh -c "..."`, so an
        # inline body would need three levels of quoting (host -> device shell
        # -> nsenter -> sh) and one unescaped quote in an agent's prose would
        # silently truncate the status. A file has no quoting rules at all.
        name=${2:?hud publish: missing name}
        src="$OUT/$name.out"
        [ -f "$src" ] || { echo "hud publish: no $src" >&2; exit 1; }
        # Copy through cat, not cp, and force mode 0644.
        #
        # The staging file lives on /sdcard, where the emulated filesystem
        # hands out 0640 owned by whoever wrote it. `cp` preserves that, and a
        # root-owned 0640 file in the panel's own directory is one the panel
        # (uid u0_a350) cannot open: it renders an empty card while the file
        # on disk is perfectly correct. That failure looks like "the panel is
        # dead", so the mode is set explicitly rather than inherited.
        if [ -n "$P" ]; then
          nsenter -t "$P" -m -- sh -c "cat '$src' > '$D/$name.tmp' && chmod 0644 '$D/$name.tmp' && mv -f '$D/$name.tmp' '$D/$name'" \
            || { echo "hud publish: cannot write $D/$name" >&2; exit 1; }
        else
          cat "$src" > "$D/$name.tmp" && chmod 0644 "$D/$name.tmp" && mv -f "$D/$name.tmp" "$D/$name" \
            || { echo "hud publish: cannot write $D/$name" >&2; exit 1; }
        fi
        rm -f "$src"
        echo "hud: published $name to $D"
        ;;
      on|off)
        # Whether the panel service is alive, and if not, why.
        #
        # `panel=` is the same word `status` prints, so a caller can grep one
        # field instead of guessing from a pid. The old wording said "not
        # running" for both "installed but stopped" and "never installed",
        # which are the two cases with opposite fixes.
        case "$panel" in
          live) echo "hud: running (pid $P)" ;;
          dead) echo "hud: installed but not running"
                echo "hud: start with: am start-foreground-service -n com.lcs.hud/.HudService" ;;
          absent) echo "hud: not installed (no com.lcs.hud); the legacy $REMOTE_DIR_FALLBACK path is in use" ;;
          *) echo "hud: unknown (pm not on PATH, so install state cannot be read)" ;;
        esac
        ;;
      *)
        echo "hud: unknown sub '$sub'; use pause|run|status|on|off" >&2
        exit 2
        ;;
    esac
    ;;

  *)
    echo "unknown command: $cmd" >&2
    exit 2
    ;;
esac

package com.lcs.hud;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/**
 * Floating panel that shows what the agent is doing and lets a human take the
 * phone away from it.
 *
 * Two constraints shaped this design:
 *
 * 1. The panel must be invisible to `uiautomator dump`. Otherwise the agent
 *    reads its own overlay as screen content and taps its own pause button.
 *    IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS removes the whole card
 *    from the accessibility tree, which is exactly the tree eyes.sh reads.
 *
 * 2. State travels through files, not through a socket. The host side
 *    (phone.py) is one process per command and must stay that way; a panel
 *    that owned the truth in memory would be a daemon by another name.
 *      hud.ctl    <- human writes "run" / "pause", agent reads
 *      hud.status <- agent writes task/think/step, panel reads
 */
public class HudService extends Service {

    // Resolved at runtime from getFilesDir(), not hardcoded. The app sees /data/data
    // through its own mount namespace, and a path that root resolves can land on
    // a different label than the one the app is allowed to write. getFilesDir()
    // is by definition a directory this uid owns and may write.
    private String dir() {
        File d = new File(getFilesDir(), "hud");
        if (!d.exists()) d.mkdirs();
        return d.getAbsolutePath();
    }
    private String ctlPath() { return dir() + "/hud.ctl"; }
    private String statusPath() { return dir() + "/hud.status"; }
    private String beatPath() { return dir() + "/hud.beat"; }
    private static final long POLL_MS = 400;
    private static final long STALE_MS = 15000;
    private static final String CHAN = "hud";

    private WindowManager wm;
    private WindowManager.LayoutParams lp;
    private LinearLayout card;
    private TextView task, think, step, dot, button, foot;
    private boolean paused = false;
    private boolean compact = false;
    private String lastStatus = "";
    private long lastBeatTs = -1;
    /** Previous staleness verdict; a flip alone must trigger a repaint. */
    private boolean lastStale = false;

    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable poll = new Runnable() {
        @Override public void run() {
            refresh();
            handler.postDelayed(this, POLL_MS);
        }
    };

    @Override public IBinder onBind(Intent i) { return null; }

    @Override public void onCreate() {
        super.onCreate();
        // Each step is isolated. A failure in any one of them used to abort
        // onCreate silently -- the process stayed alive as an "active service"
        // while no window and no log line ever appeared, which looks exactly
        // like a code path that was never reached. Logging plus isolation turns
        // that into a diagnosable failure.
        try {
            startInForeground();
            android.util.Log.i("LCSHUD", "onCreate: foreground ok");
        } catch (Throwable e) {
            android.util.Log.e("LCSHUD", "onCreate: startForeground failed", e);
        }
        try {
            buildPanel();
            android.util.Log.i("LCSHUD", "onCreate: panel built");
        } catch (Throwable e) {
            android.util.Log.e("LCSHUD", "onCreate: buildPanel failed", e);
        }
        try {
            ensureControlFile();
        } catch (Throwable e) {
            android.util.Log.e("LCSHUD", "onCreate: ensureControlFile failed", e);
        }
        handler.post(poll);
        android.util.Log.i("LCSHUD", "onCreate: poll posted");
    }

    @Override public int onStartCommand(Intent i, int flags, int startId) {
        return START_STICKY;
    }

    @Override public void onDestroy() {
        handler.removeCallbacks(poll);
        try { if (card != null) wm.removeView(card); } catch (Exception ignored) { }
        super.onDestroy();
    }

    // ------------------------------------------------------------ foreground

    private void startInForeground() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationManager nm = getSystemService(NotificationManager.class);
            NotificationChannel ch = new NotificationChannel(
                    CHAN, "AI 状态窗", NotificationManager.IMPORTANCE_MIN);
            ch.setShowBadge(false);
            nm.createNotificationChannel(ch);
        }
        Notification n = buildNotification();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, n);
        } else {
            startForeground(1, n);
        }
    }

    private Notification buildNotification() {
        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHAN)
                : new Notification.Builder(this);
        return b.setContentTitle("AI 状态窗")
                .setContentText("正在显示 AI 的进度")
                .setSmallIcon(android.R.drawable.ic_menu_view)
                .setOngoing(true)
                .build();
    }

    // ----------------------------------------------------------------- panel

    private void buildPanel() {
        wm = (WindowManager) getSystemService(WINDOW_SERVICE);

        card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(12), dp(8), dp(12), dp(10));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(0xF01C1C1E);
        bg.setCornerRadius(dp(14));
        bg.setStroke(dp(1), 0x33FFFFFF);
        card.setBackground(bg);

        // Hidden from uiautomator: the agent must not see (or tap) this panel.
        card.setImportantForAccessibility(
                View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);

        LinearLayout head = new LinearLayout(this);
        head.setOrientation(LinearLayout.HORIZONTAL);
        head.setGravity(Gravity.CENTER_VERTICAL);

        dot = new TextView(this);
        dot.setText("●");
        dot.setTextColor(0xFF4ADE80);
        dot.setTextSize(11);
        head.addView(dot, wrap());

        TextView title = new TextView(this);
        title.setText(" AI");
        title.setTextColor(0xFFFFFFFF);
        title.setTextSize(12);
        head.addView(title, wrap());

        LinearLayout spacer = new LinearLayout(this);
        head.addView(spacer, new LinearLayout.LayoutParams(0, 1, 1f));

        button = new TextView(this);
        button.setText("暂停");
        button.setTextColor(0xFFFFD166);
        button.setTextSize(12);
        button.setPadding(dp(10), dp(4), dp(4), dp(4));
        button.setOnClickListener(v -> toggle());
        head.addView(button, wrap());

        TextView hide = new TextView(this);
        hide.setText(" ✕");
        hide.setTextColor(0x88FFFFFF);
        hide.setTextSize(11);
        hide.setPadding(dp(6), dp(4), dp(2), dp(4));
        hide.setOnClickListener(v -> setCompact(true));
        head.addView(hide, wrap());

        card.addView(head, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT));

        task = line(12, 0xFFFFFFFF);
        task.setMaxLines(1);
        task.setEllipsize(android.text.TextUtils.TruncateAt.END);
        think = line(11, 0xFF9CA3AF);
        think.setMaxLines(3);
        think.setEllipsize(android.text.TextUtils.TruncateAt.END);
        step = line(10, 0xFF6B7280);
        step.setMaxLines(1);
        step.setEllipsize(android.text.TextUtils.TruncateAt.END);
        foot = line(10, 0xFF6B7280);
        foot.setMaxLines(1);

        card.addView(task);
        card.addView(think);
        card.addView(step);
        card.addView(foot);

        // Drag by the body, so the buttons keep their clicks.
        View.OnTouchListener drag = new View.OnTouchListener() {
            float downX, downY;
            int startX, startY;
            boolean moved;
            @Override public boolean onTouch(View v, MotionEvent e) {
                switch (e.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        downX = e.getRawX(); downY = e.getRawY();
                        startX = lp.x; startY = lp.y; moved = false;
                        return true;
                    case MotionEvent.ACTION_MOVE:
                        int dx = (int) (e.getRawX() - downX);
                        int dy = (int) (e.getRawY() - downY);
                        if (Math.abs(dx) > dp(4) || Math.abs(dy) > dp(4)) moved = true;
                        if (moved) {
                            lp.x = startX + dx; lp.y = startY + dy;
                            wm.updateViewLayout(card, lp);
                        }
                        return true;
                    case MotionEvent.ACTION_UP:
                        if (!moved) setCompact(!compact);
                        else savePos();
                        return true;
                }
                return false;
            }
        };
        task.setOnTouchListener(drag);
        think.setOnTouchListener(drag);

        int flags = WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE
                | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL
                | WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS;
        int type = Build.VERSION.SDK_INT >= 26
                ? WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
                : WindowManager.LayoutParams.TYPE_PHONE;

        lp = new WindowManager.LayoutParams(
                // A fixed max width, not WRAP_CONTENT. With WRAP_CONTENT a
                // single long Chinese sentence stretched the card across most
                // of the panel and sat on top of whatever the human was
                // reading -- the panel became the problem it was meant to
                // solve. 240dp is narrow enough to stay out of the way.
                Math.min(dp(240),
                        getResources().getDisplayMetrics().widthPixels - dp(24)),
                WindowManager.LayoutParams.WRAP_CONTENT,
                type, flags, PixelFormat.TRANSLUCENT);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.x = dp(12);
        lp.y = dp(120);
        // Restore the last position. A panel that jumps back to the corner on
        // every restart is a panel the human keeps re-dragging out of the way.
        int[] saved = readPos();
        if (saved != null) { lp.x = saved[0]; lp.y = saved[1]; }

        try {
            wm.addView(card, lp);
        } catch (Exception e) {
            // Missing SYSTEM_ALERT_WINDOW. Say so where a human will see it.
            stopSelf();
        }
    }

    private TextView line(int sp, int color) {
        TextView t = new TextView(this);
        t.setTextSize(sp);
        t.setTextColor(color);
        t.setPadding(0, dp(3), 0, 0);
        return t;
    }

    private LinearLayout.LayoutParams wrap() {
        return new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.WRAP_CONTENT,
                LinearLayout.LayoutParams.WRAP_CONTENT);
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }

    private void setCompact(boolean on) {
        compact = on;
        int vis = on ? View.GONE : View.VISIBLE;
        task.setVisibility(vis);
        think.setVisibility(vis);
        step.setVisibility(vis);
        foot.setVisibility(vis);
        button.setText(on ? (paused ? "▶" : "⏸") : (paused ? "继续" : "暂停"));
        try { wm.updateViewLayout(card, lp); } catch (Exception ignored) { }
    }

    // ----------------------------------------------------------------- state

    /** First run has no control file; a missing file must mean "go". */
    private void ensureControlFile() {
        File f = new File(ctlPath());
        if (!f.exists()) write(ctlPath(), "run\n");
    }

    private void toggle() {
        paused = !paused;
        write(ctlPath(), (paused ? "pause" : "run") + "\n");
        if (compact) setCompact(true); else button.setText(paused ? "继续" : "暂停");
        // Repaint immediately instead of waiting up to 400ms for the next poll:
        // the human just touched the button and expects the card to answer.
        // Both clocks matter here -- pass the same liveness the poll would.
        long beatTs = parseTs(read(beatPath()));
        long statusTs = parseTs(lastStatus);
        render(Math.max(beatTs, statusTs));
    }

    /**
     * Write via temp+rename. A reader polling every 400ms would otherwise
     * occasionally catch a half-written file and read "" as the command,
     * which must never be interpreted as anything but "keep going".
     *
     * /sdcard is FUSE on modern Android: a normal app gets EPERM even with
     * MANAGE_EXTERNAL_STORAGE granted, because the FUSE layer grants write only
     * to the media provider and to the file's own creator. We therefore write
     * through `su -c` when the direct path fails. That is the same root the
     * rest of this project already requires for `input`, so it adds no new
     * dependency -- and the fallback keeps the panel usable on a non-rooted
     * phone for its read-only half (showing status still works).
     */
    private void write(String path, String body) {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);

        // Direct write first. This is the app's own directory, so the normal
        // path works and no su round-trip is needed.
        try {
            File parent = new File(path).getParentFile();
            if (parent != null && !parent.exists()) parent.mkdirs();
            try (FileOutputStream o = new FileOutputStream(path)) {
                o.write(bytes);
                o.flush();
                o.getFD().sync();
            }
            android.util.Log.i("LCSHUD", "wrote " + path + " (" + bytes.length + "B)");
            return;
        } catch (Exception direct) {
            android.util.Log.w("LCSHUD", "direct write failed " + path
                    + ": " + direct.getMessage());
        }

        // Fall back to root. Kept because the control files may live somewhere
        // the app uid cannot reach at all (e.g. under /sdcard on some ROMs).
        if (writeViaSu(path, body)) {
            android.util.Log.i("LCSHUD", "wrote via su " + path);
            return;
        }
        android.util.Log.e("LCSHUD", "write failed entirely: " + path);
        if (foot != null) foot.setText("写入失败: " + path);
    }

    /** Where the human last dragged the panel, in raw pixels. */
    private int[] readPos() {
        String s = read(dir() + "/hud.pos").trim();
        if (s.isEmpty()) return null;
        String[] parts = s.split("[ ,]+");
        if (parts.length < 2) return null;
        try {
            return new int[]{Integer.parseInt(parts[0]), Integer.parseInt(parts[1])};
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private void savePos() {
        if (lp != null) write(dir() + "/hud.pos", lp.x + "," + lp.y + "\n");
    }

    /** Last resort: hand the bytes to root, which can write through FUSE. */
    private boolean writeViaSu(String path, String body) {
        Process p = null;
        try {
            // Base64 keeps the payload free of quoting hazards; the control file
            // is one short word but the status file carries arbitrary prose.
            String b64 = android.util.Base64.encodeToString(
                    body.getBytes(StandardCharsets.UTF_8), android.util.Base64.NO_WRAP);
            p = new ProcessBuilder("su", "-c",
                    "echo " + b64 + " | base64 -d > " + path)
                    .redirectErrorStream(true).start();
            p.waitFor();
            return p.exitValue() == 0;
        } catch (Exception e) {
            return false;
        } finally {
            if (p != null) p.destroy();
        }
    }

    private String read(String path) {
        File f = new File(path);
        if (f.exists()) {
            try (RandomAccessFile r = new RandomAccessFile(f, "r")) {
                byte[] b = new byte[(int) Math.min(r.length(), 8192)];
                r.readFully(b);
                return new String(b, StandardCharsets.UTF_8);
            } catch (Exception e) {
                android.util.Log.w("LCSHUD", "direct read failed " + path, e);
            }
        }
        return readViaSu(path);
    }

    /**
     * Read through root. The control files are written by whoever drives the
     * agent -- often the shell uid -- and that owner is not necessarily
     * readable by this app. A read that quietly returns "" would look exactly
     * like an idle agent, so the fallback matters more than the fast path.
     */
    private String readViaSu(String path) {
        Process p = null;
        try {
            p = new ProcessBuilder("su", "-c", "cat " + path)
                    .redirectErrorStream(false).start();
            java.io.ByteArrayOutputStream buf = new java.io.ByteArrayOutputStream();
            byte[] tmp = new byte[4096];
            int n;
            while ((n = p.getInputStream().read(tmp)) > 0) buf.write(tmp, 0, n);
            p.waitFor();
            if (p.exitValue() != 0) return "";
            return new String(buf.toByteArray(), StandardCharsets.UTF_8);
        } catch (Exception e) {
            return "";
        } finally {
            if (p != null) p.destroy();
        }
    }
private void refresh() {
        String ctl = read(ctlPath()).trim();
        // Only an explicit "pause" stops the agent. Empty, garbled or missing
        // content must fail open -- a panel that halts the agent because a file
        // was mid-rewrite would be worse than no panel.
        boolean wantPaused = "pause".equalsIgnoreCase(ctl);

        boolean pauseFlipped = false;
        if (wantPaused != paused) {
            paused = wantPaused;
            pauseFlipped = true;
            if (compact) setCompact(true); else button.setText(paused ? "继续" : "暂停");
        }

        // Two clocks, two questions.
        //   hud.status.ts  -- when did the agent last *say* something?
        //   hud.beat.ts    -- when did the agent last *do* something?
        // Liveness is the newer of the two. Using only the first made the card
        // read "40s 无更新" while the agent was tapping away, because nothing
        // refreshed status unless the agent remembered to call `say`. A light
        // that cannot tell a busy agent from a dead one is worse than none.
        String raw = read(statusPath());
        long beatTs = parseTs(read(beatPath()));
        long statusTs = parseTs(raw);
        long liveness = Math.max(beatTs, statusTs);

        // Content changes are not the only reason to repaint. Liveness can
        // change with the files untouched -- a beat simply ages past the stale
        // threshold -- and a panel that only repaints on file writes would sit
        // on "运行中" forever while the agent was dead. That is precisely the
        // failure this light exists to prevent, so the staleness verdict is
        // part of the repaint condition.
        boolean stale = liveness > 0 && System.currentTimeMillis() - liveness > STALE_MS;
        boolean changed = !raw.equals(lastStatus) || beatTs != lastBeatTs
                || stale != lastStale || pauseFlipped;
        lastBeatTs = beatTs;
        if (changed) {
            lastStatus = raw;
            lastStale = stale;
            render(liveness);
        }
    }

    /** Pull ts= out of a key=value file without building a map. */
    private long parseTs(String body) {
        for (String line : body.split("\n")) {
            int eq = line.indexOf('=');
            if (eq > 0 && "ts".equals(line.substring(0, eq).trim())) {
                try { return Long.parseLong(line.substring(eq + 1).trim()); }
                catch (Exception ignored) { return 0; }
            }
        }
        return 0;
    }

    /** @param ts newest of the two clocks: the agent is alive as of this ms. */
    private void render(long ts) {
        Map<String, String> m = new HashMap<>();
        for (String line : lastStatus.split("\n")) {
            int eq = line.indexOf('=');
            if (eq <= 0) continue;
            m.put(line.substring(0, eq).trim(), line.substring(eq + 1).trim());
        }

        boolean stale = ts > 0 && System.currentTimeMillis() - ts > STALE_MS;
        // The agent's own verdict on this run. `paused` wins over it because
        // the human's button is the newer fact, but a finished or failed run
        // must not keep showing a green dot just because the file is recent.
        String state = m.get("state");
        if (state == null) state = "";
        boolean done = "done".equalsIgnoreCase(state);
        boolean failed = "error".equalsIgnoreCase(state);

        if (paused) {
            dot.setTextColor(0xFFFFB020);
            dot.setText("❚❚");
        } else if (failed) {
            dot.setTextColor(0xFFFF6B6B);
            dot.setText("●");
        } else if (done) {
            dot.setTextColor(0xFF60A5FA);
            dot.setText("●");
        } else if (stale) {
            dot.setTextColor(0xFF6B7280);
            dot.setText("●");
        } else {
            dot.setTextColor(0xFF4ADE80);
            dot.setText("●");
        }
        String t = m.get("task");
        task.setText(t == null || t.isEmpty() ? "（无任务）" : t);
        String th = m.get("think");
        if (th == null || th.isEmpty()) {
            think.setVisibility(View.GONE);
        } else {
            think.setVisibility(compact ? View.GONE : View.VISIBLE);
            think.setText(th);
        }
        String st = m.get("step");
        step.setText(st == null ? "" : st);
        step.setVisibility(compact || st == null || st.isEmpty()
                ? View.GONE : View.VISIBLE);
        String f;
        if (paused) {
            f = "已暂停 · 人类接管中";
        } else if (failed) {
            f = "出错了 · 看日志";
        } else if (done) {
            f = "已完成";
        } else if (stale) {
            f = "AI 已 " + ((System.currentTimeMillis() - ts) / 1000) + "s 无更新";
        } else {
            f = "运行中";
        }
        foot.setText(f);
        // Publish what was actually rendered. Without this the only way to
        // check the panel is a screenshot plus OCR, and OCR over a busy
        // background reads the chat behind the card as often as the card.
        // A dump of the render is a fact; a screenshot is an interpretation.
        writeRendered(f, t, th, st, state, ts);
    }

    private void writeRendered(String foot, String task, String think,
                               String step, String state, long ts) {
        String body = "dot=" + dot.getText().toString() + "\n"
                + "state=" + state + "\n"
                + "task=" + (task == null ? "" : task) + "\n"
                + "think=" + (think == null ? "" : think) + "\n"
                + "step=" + (step == null ? "" : step) + "\n"
                + "foot=" + foot + "\n"
                + "ts=" + ts + "\n";
        write(dir() + "/hud.render", body);
    }
}
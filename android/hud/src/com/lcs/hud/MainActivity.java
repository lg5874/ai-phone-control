package com.lcs.hud;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;

/**
 * Tiny launcher: ask for the overlay grant if missing, then hand off to the
 * service and get out of the way. There is deliberately no UI here -- a control
 * panel that needs its own window in front would defeat the purpose.
 */
public class MainActivity extends Activity {

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        if (Build.VERSION.SDK_INT >= 23 && !Settings.canDrawOverlays(this)) {
            try {
                startActivity(new Intent(
                        Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception ignored) {
                // Some ROMs hide that page; the service will report the miss.
            }
        }

        Intent svc = new Intent(this, HudService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(svc);
        } else {
            startService(svc);
        }
        finish();
    }
}
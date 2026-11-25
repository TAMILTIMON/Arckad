package io.github.tamiltimon.arckadd;

import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.os.Handler;
import android.os.Looper;

import org.json.JSONObject;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** 📋 Clipboard sync with the linked PC. Copy on the PC → it lands on this phone's clipboard. Copy on the phone →
 *  it goes to the PC when Arckad-D is in front (Android lets apps read the clipboard only then). Text only, only
 *  while Phone link is on, over the encrypted linked-devices connection, local network only. */
final class ClipSync {
    static final int MAX = 100_000;
    private static final String PREF = "clip_sync", LAST = "clip_last_hash";

    private ClipSync() {
    }

    static boolean on(Context c) {
        return Ui.prefs(c).getBoolean(PREF, true);
    }

    static void set(Context c, boolean v) {
        Ui.prefs(c).edit().putBoolean(PREF, v).apply();
    }

    /** Remembered as a hash, so the same text is never sent back and forth (and no clipboard text is stored). */
    private static boolean seen(Context c, String t) {
        return Ui.prefs(c).getInt(LAST, 0) == t.hashCode();
    }

    private static void remember(Context c, String t) {
        Ui.prefs(c).edit().putInt(LAST, t.hashCode()).apply();
    }

    /** The PC copied something: put it on this phone's clipboard. */
    static JSONObject fromPc(Context c, JSONObject req) {
        if (!on(c)) return new Obj().putOpt("ok", false).putOpt("reason", "clipboard sync is off on the phone");
        String t = req.optString("text", "");
        if (t.isEmpty() || t.length() > MAX) return new Obj().putOpt("ok", false).putOpt("reason", "nothing to copy");
        remember(c, t);
        Context app = c.getApplicationContext();
        CountDownLatch done = new CountDownLatch(1);
        new Handler(Looper.getMainLooper()).post(() -> {
            try {
                ClipboardManager cm = (ClipboardManager) app.getSystemService(Context.CLIPBOARD_SERVICE);
                if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("Arckad-D", t));
            } catch (Exception ignored) {
            } finally {
                done.countDown();
            }
        });
        try {
            done.await(3, TimeUnit.SECONDS);
        } catch (InterruptedException ignored) {
        }
        return new Obj().putOpt("ok", true);
    }

    /** Arckad-D is in front on the phone: if the clipboard holds new text, send it to the linked PC. */
    static void check(Context c) {
        try {
            if (!on(c) || !Ui.prefs(c).getBoolean("phone_link", false)) return;
            ClipboardManager cm = (ClipboardManager) c.getSystemService(Context.CLIPBOARD_SERVICE);
            ClipData d = cm == null ? null : cm.getPrimaryClip();
            if (d == null || d.getItemCount() == 0) return;
            CharSequence cs = d.getItemAt(0).coerceToText(c);
            String t = cs == null ? "" : cs.toString();
            if (t.trim().isEmpty() || t.length() > MAX || seen(c, t)) return;
            remember(c, t);
            ChatHub.get(c).engine.link.pushPhone(new Obj().putOpt("type", "clip").putOpt("text", t));
        } catch (Exception ignored) {                      // never let the clipboard break the app
        }
    }
}

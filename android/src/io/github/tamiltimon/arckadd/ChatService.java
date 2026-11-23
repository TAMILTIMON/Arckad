package io.github.tamiltimon.arckadd;

import android.app.Notification;
import android.app.NotificationManager;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/** Keeps chat connected while Arckad-D isn't on screen (Android stops background apps otherwise). Shows the
 *  small permanent "chat is connected" notification Android requires. Also started after the phone reboots. */
public class ChatService extends Service {
    static final String STOP = "io.github.tamiltimon.arckadd.CHAT_BG_OFF";

    static volatile boolean running;               // the service is up: start requests are ignored
    private static volatile long lastStart;

    static void ensure(Context c) {
        ChatHub hub = ChatHub.get(c);
        if (!hub.engine.active() || ChatHub.BG_OFF.equals(hub.bgMode()) || hub.safeMode()) return;
        if (running) return;
        long now = System.currentTimeMillis();
        if (now - lastStart < 10_000) return;      // safety net: never start the service in a loop
        lastStart = now;
        try {
            Intent i = new Intent(c, ChatService.class);
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
            else c.startService(i);
        } catch (Exception ignored) {                         // not allowed right now; the app starts it when opened
        }
    }

    /** Update the notification after the background mode changed. */
    static void refresh(Context c) {
        if (ChatHub.BG_OFF.equals(ChatHub.get(c).bgMode())) c.stopService(new Intent(c, ChatService.class));
        else if (running) {                          // already running: just update its notification text
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            nm.notify(1, build(c));
        } else ensure(c);
    }

    static Notification build(Context c) {
        ChatHub hub = ChatHub.get(c);
        boolean saver = ChatHub.BG_SAVER.equals(hub.bgMode());
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(c, ChatHub.CH_SERVICE)
                : new Notification.Builder(c);
        android.app.PendingIntent off = android.app.PendingIntent.getService(c, 2, new Intent(c, ChatService.class).setAction(STOP),
                android.app.PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? android.app.PendingIntent.FLAG_IMMUTABLE : 0));
        b.setSmallIcon(hub.statusIcon()).setContentTitle(saver ? "Arckad-D chat · battery saver" : "Arckad-D chat is connected")
                .setContentText(saver ? "Reachable when closed, checking in every 30 s. Tap “Turn off” to stop."
                        : "Messages arrive instantly even when the app is closed.")
                .setOngoing(true).setOnlyAlertOnce(true).setContentIntent(hub.openIntent(null, null, 1));
        if (Build.VERSION.SDK_INT >= 20) b.addAction(new Notification.Action.Builder(null, "Turn off", off).build());
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_MIN);
        return b.build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        ChatHub hub = ChatHub.get(this);
        if (intent != null && STOP.equals(intent.getAction())) {          // the notification's "Turn off" button
            hub.setBgMode(ChatHub.BG_OFF);
            if (!hub.onScreen()) hub.stopForBackground();
            stopForeground(true);
            stopSelf();
            return START_NOT_STICKY;
        }
        if (running) return START_STICKY;             // already up: nothing to do (no re-posting, no restarting)
        try {
            if (Build.VERSION.SDK_INT >= 34) startForeground(1, build(this), 512 /* FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING */);
            else startForeground(1, build(this));
        } catch (Exception e) {
            stopSelf();
            return START_NOT_STICKY;
        }
        running = true;
        hub.startEngine();                            // chat only: this must never ask to start the service again
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    /** Starts chat after the phone is switched on (only if chat is in use). */
    public static class Boot extends BroadcastReceiver {
        @Override
        public void onReceive(Context c, Intent i) {
            if (Intent.ACTION_BOOT_COMPLETED.equals(i.getAction()) || "android.intent.action.MY_PACKAGE_REPLACED".equals(i.getAction()))
                ensure(c);
        }
    }
}

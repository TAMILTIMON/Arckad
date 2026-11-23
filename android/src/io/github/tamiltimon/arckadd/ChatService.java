package io.github.tamiltimon.arckadd;

import android.app.Notification;
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

    static void ensure(Context c) {
        ChatHub hub = ChatHub.get(c);
        if (!hub.engine.active() || ChatHub.BG_OFF.equals(hub.bgMode())) return;
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
        else ensure(c);
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
        boolean saver = ChatHub.BG_SAVER.equals(hub.bgMode());
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, ChatHub.CH_SERVICE)
                : new Notification.Builder(this);
        android.app.PendingIntent off = android.app.PendingIntent.getService(this, 2, new Intent(this, ChatService.class).setAction(STOP),
                android.app.PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? android.app.PendingIntent.FLAG_IMMUTABLE : 0));
        b.setSmallIcon(hub.statusIcon()).setContentTitle(saver ? "Arckad-D chat · battery saver" : "Arckad-D chat is connected")
                .setContentText(saver ? "Reachable when closed, checking in every 30 s. Tap “Turn off” to stop."
                        : "Messages arrive instantly even when the app is closed.")
                .setOngoing(true).setContentIntent(hub.openIntent(null, null, 1));
        if (Build.VERSION.SDK_INT >= 20) b.addAction(new Notification.Action.Builder(null, "Turn off", off).build());
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_MIN);
        try {
            if (Build.VERSION.SDK_INT >= 34) startForeground(1, b.build(), 512 /* FOREGROUND_SERVICE_TYPE_REMOTE_MESSAGING */);
            else startForeground(1, b.build());
        } catch (Exception e) {
            stopSelf();
            return START_NOT_STICKY;
        }
        hub.start();
        return START_STICKY;
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

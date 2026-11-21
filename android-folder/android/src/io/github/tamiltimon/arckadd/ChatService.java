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
    static void ensure(Context c) {
        if (!ChatHub.get(c).engine.active()) return;
        try {
            Intent i = new Intent(c, ChatService.class);
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i);
            else c.startService(i);
        } catch (Exception ignored) {                         // not allowed right now; the app starts it when opened
        }
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        ChatHub hub = ChatHub.get(this);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, ChatHub.CH_SERVICE)
                : new Notification.Builder(this);
        b.setSmallIcon(hub.statusIcon()).setContentTitle("Arckad-D chat is connected")
                .setContentText("Messages and friend requests arrive even when the app is closed.")
                .setOngoing(true).setContentIntent(hub.openIntent(null, null, 1));
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

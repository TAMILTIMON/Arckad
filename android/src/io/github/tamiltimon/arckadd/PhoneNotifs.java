package io.github.tamiltimon.arckadd;

import android.app.Notification;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import org.json.JSONObject;

/** Reads the phone's notifications for the PC's 📱 Phone panel. Android only starts this after you allow
 *  "Notification access" for Arckad-D (Chat → ⋮ → 📱 Phone link). Nothing leaves the phone unless Phone link is on. */
public class PhoneNotifs extends NotificationListenerService {
    static volatile PhoneNotifs instance;

    @Override
    public void onListenerConnected() {
        instance = this;
    }

    @Override
    public void onListenerDisconnected() {
        instance = null;
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        JSONObject item = PhoneLink.describe(this, sbn);
        if (item != null) ChatHub.get(this).engine.link.pushPhone(new Obj().putOpt("type", "posted").putOpt("item", item));
    }

    @Override
    public void onNotificationRemoved(StatusBarNotification sbn) {
        if (sbn.getPackageName().equals(getPackageName())) return;
        ChatHub.get(this).engine.link.pushPhone(new Obj().putOpt("type", "removed").putOpt("item", new Obj().putOpt("key", sbn.getKey())));
    }

    static boolean worthShowing(StatusBarNotification sbn, String own) {
        Notification n = sbn.getNotification();
        return !sbn.getPackageName().equals(own) && !sbn.isOngoing() && (n.flags & Notification.FLAG_GROUP_SUMMARY) == 0;
    }
}

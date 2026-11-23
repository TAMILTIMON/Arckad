package io.github.tamiltimon.arckadd;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.AudioAttributes;
import android.net.Uri;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;

import org.json.JSONObject;

import java.io.File;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;

/** The one chat engine for the whole app (the screens and the background service share it). Turns engine
 *  events into Android notifications and tells the visible chat screen what changed. */
final class ChatHub implements ChatEngine.Ui {
    interface Listener {
        void chatChanged(String gid);

        void peopleChanged();

        void askJoin(ChatEngine.Ask ev);

        void chatEvent(String text);

        void askLink(ChatEngine.Ask ev);

        void relinked();
    }

    static final String CH_MSG = "chat-messages", CH_SERVICE = "chat-connection";
    private static ChatHub hub;
    volatile ChatEngine engine;
    final Context app;
    final CopyOnWriteArrayList<Listener> listeners = new CopyOnWriteArrayList<>();
    private final Handler main = new Handler(Looper.getMainLooper());
    private WifiManager.MulticastLock mlock;
    volatile String visibleGid;                 // the conversation on screen (no notification for it)
    volatile boolean appVisible;

    static synchronized ChatHub get(Context c) {
        if (hub == null) hub = new ChatHub(c.getApplicationContext());
        return hub;
    }

    private ChatHub(Context c) {
        app = c;
        SharedPreferences p = Ui.prefs(c);
        if (!p.contains("device_id")) p.edit().putString("device_id", UUID.randomUUID().toString().substring(0, 16)).apply();
        String name = p.getString("device_name", "");
        if (name.isEmpty()) {
            try {
                name = Settings.Global.getString(c.getContentResolver(), "device_name");
            } catch (Exception ignored) {
            }
            if (name == null || name.isEmpty()) name = Build.MODEL;
        }
        ChatEngine.version = BuildInfo.VERSION;
        if (!p.contains("chat_inst")) p.edit().putString("chat_inst", ChatCrypto.token(6)).apply();
        engine = build(p.getString("device_id", "phone"), name);
        channels();
    }

    private ChatEngine build(String deviceId, String name) {
        File dl = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        ChatEngine e = new ChatEngine(new File(app.getFilesDir(), "chat"), dl, deviceId, name, Net.OS, this);
        e.inst = Ui.prefs(app).getString("chat_inst", "phone");
        e.phone = new PhoneLink(app);                      // answers the PC's 📱 Phone panel (when switched on)
        return e;
    }

    @Override
    public void askLink(ChatEngine.Ask ev) {
        main.post(() -> {
            if (listeners.isEmpty()) {
                notify(7002, ev.name + " wants to link to your account", "Open Arckad-D to approve it.", null, "chat");
                return;
            }
            for (Listener l : listeners) {
                l.askLink(ev);
                break;
            }
        });
    }

    /** This phone became a linked account (or was unlinked): restart chat with the new identity. */
    @Override
    public void relinked(String deviceId) {
        main.post(() -> {
            ChatEngine old = engine;
            old.stop();
            Ui.prefs(app).edit().putString("device_id", deviceId).apply();
            engine = build(deviceId, old.deviceName);
            start();
            for (Listener l : listeners) l.relinked();
        });
    }

    void notifyIntent(int id, String title, String body, android.app.PendingIntent pi) {
        NotificationManager nm = (NotificationManager) app.getSystemService(Context.NOTIFICATION_SERVICE);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(app, CH_MSG) : new Notification.Builder(app);
        b.setSmallIcon(statusIcon()).setContentTitle(title).setContentText(body).setAutoCancel(true).setContentIntent(pi);
        if (Build.VERSION.SDK_INT < 26) b.setPriority(Notification.PRIORITY_HIGH);
        nm.notify(id, b.build());
    }

    // ---------- background connection: battery saver (default), always, or off
    static final String BG_SAVER = "saver", BG_ALWAYS = "always", BG_OFF = "off";
    private int visible;                                   // Arckad-D screens on show
    private final Runnable offLater = this::stopForBackground;

    String bgMode() {
        return Ui.prefs(app).getString("chat_bg", BG_SAVER);
    }

    void setBgMode(String mode) {
        Ui.prefs(app).edit().putString("chat_bg", mode).apply();
        applyPower();
        if (!BG_OFF.equals(mode)) ChatService.ensure(app);
        ChatService.refresh(app);
    }

    boolean onScreen() {
        return visible > 0;
    }

    /** MainActivity tells us when Arckad-D comes on screen or leaves it. */
    void setVisible(boolean on) {
        visible = Math.max(0, visible + (on ? 1 : -1));
        main.removeCallbacks(offLater);
        if (on) start();
        else if (BG_OFF.equals(bgMode())) main.postDelayed(offLater, 60_000);    // off: disconnect a minute later
        applyPower();
    }

    /** Full speed on screen; in the background: battery saver checks in every 30 s and lets Wi-Fi sleep. */
    void applyPower() {
        boolean full = onScreen() || BG_ALWAYS.equals(bgMode());
        engine.beaconMs = full ? 3000 : 30_000;
        engine.directMs = full ? 6000 : 60_000;
        if (full) {
            if (mlock == null) {
                try {
                    WifiManager wm = (WifiManager) app.getSystemService(Context.WIFI_SERVICE);
                    mlock = wm.createMulticastLock("arckad-chat");      // some phones drop broadcasts without it
                    mlock.setReferenceCounted(false);
                } catch (Exception ignored) {
                }
            }
            try {
                if (mlock != null && !mlock.isHeld()) mlock.acquire();
            } catch (Exception ignored) {
            }
        } else {
            try {
                if (mlock != null && mlock.isHeld()) mlock.release();         // friends reach us directly anyway
            } catch (Exception ignored) {
            }
        }
    }

    /** Background connection is off and Arckad-D left the screen: disconnect (it reconnects when opened). */
    void stopForBackground() {
        if (onScreen()) return;
        engine.stop();
        try {
            if (mlock != null && mlock.isHeld()) mlock.release();
        } catch (Exception ignored) {
        }
        app.stopService(new Intent(app, ChatService.class));
    }

    /** Start chat networking (and keep it running in the background, unless that's off) if chat is in use. */
    void start() {
        if (!engine.active()) return;
        applyPower();
        engine.start();
        if (!BG_OFF.equals(bgMode())) ChatService.ensure(app);
    }

    void addListener(Listener l) {
        if (!listeners.contains(l)) listeners.add(l);
    }

    void removeListener(Listener l) {
        listeners.remove(l);
    }

    int unreadTotal() {
        int n = engine.incoming().length();
        for (String g : engine.groups.keySet()) n += engine.unread.getOrDefault(g, 0);
        return n;
    }

    // ---------- engine events (any thread) -> screen (main thread)
    @Override
    public void changed(String gid) {
        main.post(() -> {
            for (Listener l : listeners) l.chatChanged(gid);
        });
    }

    @Override
    public void people() {
        main.post(() -> {
            for (Listener l : listeners) l.peopleChanged();
        });
    }

    @Override
    public void message(String gid, JSONObject m) {
        changed(gid);
        if (appVisible && gid.equals(visibleGid)) {
            engine.unread.put(gid, 0);
            return;
        }
        String kind = m.optString("kind");
        if ("system".equals(kind) || "edit".equals(kind) || "pin".equals(kind) || "delete".equals(kind)) return;
        if (Ui.prefs(app).getBoolean("chat_mute_" + gid, false)) return;           // muted chat: just the unread count
        if ("react".equals(kind)) {                                                 // only reactions to MY messages
            String t = m.optString("text");
            int bar = t.indexOf('|');
            JSONObject target = bar > 0 ? engine.find(gid, t.substring(0, bar)) : null;
            if (bar < 0 || t.substring(bar + 1).isEmpty() || target == null || !engine.me.equals(target.optString("from")) || engine.isLocked()) return;
            notify(gid.hashCode(), m.optString("name") + " reacted " + t.substring(bar + 1), "to “" + ChatScreen.cut40(target) + "”", gid, null);
            return;
        }
        JSONObject g = engine.groups.get(gid);
        boolean direct = g != null && "direct".equals(g.optString("kind"));
        String title = direct ? m.optString("name") : m.optString("name") + " · " + (g == null ? "Chat" : g.optString("name"));
        String body = m.optJSONObject("file") != null ? (m.optDouble("voice", 0) > 0 ? "🎤 Voice message" : "📎 " + m.optJSONObject("file").optString("name"))
                : "sticker".equals(m.optString("kind")) ? "🏷 Sticker" : m.optString("text");
        if (m.optBoolean("once")) body = "👁 One-time message";
        if (engine.isLocked()) {
            title = "🔒 New message";
            body = "Unlock the chat to read it";
        }
        notify(gid.hashCode(), title, body, gid, null);
    }

    @Override
    public void friendRequest(String pid) {
        people();
        String name = engine.incoming().optJSONObject(pid) == null ? "Someone" : engine.incoming().optJSONObject(pid).optString("name");
        notify(pid.hashCode(), name + " wants to be your friend", "Open Chat → People to accept or decline.", null, "people");
    }

    @Override
    public void askJoin(ChatEngine.Ask ev) {
        main.post(() -> {
            if (listeners.isEmpty()) {
                notify(7001, ev.name + " wants to join “" + ev.group + "”", "Open Arckad-D to let them in.", null, "chat");
                return;
            }
            for (Listener l : listeners) {
                l.askJoin(ev);
                break;
            }
        });
    }

    @Override
    public void event(String text) {
        main.post(() -> {
            if (listeners.isEmpty()) notify(text.hashCode(), "Arckad-D", text, null, "chat");
            for (Listener l : listeners) l.chatEvent(text);
        });
    }

    @Override
    public void fileSaved(File f) {
        Android.mediaScan(app, f);
    }

    // ---------- notifications
    private void channels() {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = app.getSystemService(NotificationManager.class);
        NotificationChannel msg = new NotificationChannel(CH_MSG, "Chat messages", NotificationManager.IMPORTANCE_HIGH);
        msg.setDescription("New messages, friend requests and group invitations");
        msg.setSound(Uri.parse("android.resource://" + app.getPackageName() + "/raw/arckad_chime"),
                new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_COMMUNICATION_INSTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        NotificationChannel svc = new NotificationChannel(CH_SERVICE, "Chat connection", NotificationManager.IMPORTANCE_MIN);
        svc.setDescription("Keeps chat connected in the background");
        svc.setShowBadge(false);
        nm.createNotificationChannel(msg);
        nm.createNotificationChannel(svc);
    }

    /** The one-colour status-bar icon (res/drawable/ic_stat_chat.xml); falls back to the app icon. */
    int statusIcon() {
        int id = app.getResources().getIdentifier("ic_stat_chat", "drawable", app.getPackageName());
        return id != 0 ? id : app.getApplicationInfo().icon;
    }

    PendingIntent openIntent(String gid, String page, int code) {
        Intent i = new Intent(app, MainActivity.class).setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP)
                .putExtra("tab", "chat");
        if (gid != null) i.putExtra("chat", gid);
        if (page != null) i.putExtra("chat_page", page);
        return PendingIntent.getActivity(app, code, i, PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
    }

    void notify(int id, String title, String body, String gid, String page) {
        try {
            Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(app, CH_MSG) : new Notification.Builder(app);
            b.setSmallIcon(statusIcon()).setContentTitle(title).setContentText(body).setAutoCancel(true)
                    .setContentIntent(openIntent(gid, page, id)).setStyle(new Notification.BigTextStyle().bigText(body));
            if (Build.VERSION.SDK_INT < 26) {
                b.setPriority(Notification.PRIORITY_HIGH);
                b.setSound(Uri.parse("android.resource://" + app.getPackageName() + "/raw/arckad_chime"));
            }
            app.getSystemService(NotificationManager.class).notify(id, b.build());
        } catch (SecurityException ignored) {                // notifications not allowed
        }
    }
}

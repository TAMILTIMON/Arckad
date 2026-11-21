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
    }

    static final String CH_MSG = "chat-messages", CH_SERVICE = "chat-connection";
    private static ChatHub hub;
    final ChatEngine engine;
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
        File dl = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        ChatEngine.version = BuildInfo.VERSION;
        engine = new ChatEngine(new File(c.getFilesDir(), "chat"), dl, p.getString("device_id", "phone"), name, Net.OS, this);
        channels();
    }

    /** Start chat networking (and keep it running in the background) if chat is in use. */
    void start() {
        if (!engine.active()) return;
        if (mlock == null) {
            try {
                WifiManager wm = (WifiManager) app.getSystemService(Context.WIFI_SERVICE);
                mlock = wm.createMulticastLock("arckad-chat");      // some phones drop broadcasts without it
                mlock.setReferenceCounted(false);
                mlock.acquire();
            } catch (Exception ignored) {
            }
        }
        engine.start();
        ChatService.ensure(app);
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
        if ("system".equals(m.optString("kind"))) return;
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

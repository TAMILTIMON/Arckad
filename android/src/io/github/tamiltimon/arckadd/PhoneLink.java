package io.github.tamiltimon.arckadd;

import android.Manifest;
import android.app.Notification;
import android.app.RemoteInput;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.os.BatteryManager;
import android.os.Bundle;
import android.os.Environment;
import android.provider.ContactsContract;
import android.provider.Settings;
import android.service.notification.StatusBarNotification;
import android.telephony.SmsManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.RandomAccessFile;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.Map;

/** Answers the PC's 📱 Phone panel: notifications (see, dismiss, reply), SMS (threads, read, send) and files
 *  (browse, read in pieces). Only reached over the linked-devices connection, from a local network, while
 *  "Phone link" is switched on. */
final class PhoneLink implements ChatEngine.PhoneHandler {
    private final Context c;

    PhoneLink(Context c) {
        this.c = c.getApplicationContext();
    }

    @Override
    public boolean enabled() {
        return Ui.prefs(c).getBoolean("phone_link", false);
    }

    boolean notifAllowed() {
        String on = Settings.Secure.getString(c.getContentResolver(), "enabled_notification_listeners");
        return on != null && on.contains(c.getPackageName());
    }

    boolean callsAllowed() {
        for (String p : new String[]{Manifest.permission.READ_PHONE_STATE, Manifest.permission.READ_CALL_LOG,
                Manifest.permission.ANSWER_PHONE_CALLS, Manifest.permission.CALL_PHONE})
            if (c.checkSelfPermission(p) != PackageManager.PERMISSION_GRANTED) return false;
        return true;
    }

    boolean smsAllowed() {
        return c.checkSelfPermission(Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED
                && c.checkSelfPermission(Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public JSONObject handle(String path, JSONObject req) throws Exception {
        switch (path) {
            case "/t/phone/info":
                return info();
            case "/t/phone/notifs":
                return notifs();
            case "/t/phone/dismiss":
                return dismiss(req);
            case "/t/phone/reply":
                return reply(req);
            case "/t/phone/sms/threads":
                return threads();
            case "/t/phone/sms/messages":
                return messages(req);
            case "/t/phone/sms/send":
                return send(req);
            case "/t/phone/calls":
                return calls();
            case "/t/phone/call/answer":
                return answer();
            case "/t/phone/call/end":
                return endCall();
            case "/t/phone/call/dial":
                return dial(req);
            case "/t/phone/files":
                return files(req);
            case "/t/phone/read":
                return read(req);
            default:
                return err("unknown");
        }
    }

    private static JSONObject err(String why) {
        return new Obj().putOpt("ok", false).putOpt("reason", why);
    }

    private JSONObject info() {
        Intent b = c.registerReceiver(null, new IntentFilter(Intent.ACTION_BATTERY_CHANGED));
        int level = b == null ? -1 : b.getIntExtra(BatteryManager.EXTRA_LEVEL, -1), scale = b == null ? 100 : b.getIntExtra(BatteryManager.EXTRA_SCALE, 100);
        int plugged = b == null ? 0 : b.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0);
        return new Obj().putOpt("ok", true).putOpt("battery", level < 0 ? null : level * 100 / Math.max(1, scale))
                .putOpt("charging", plugged != 0).putOpt("notif_ok", notifAllowed()).putOpt("sms_ok", smsAllowed())
                .putOpt("calls_ok", callsAllowed());
    }

    // ---------- notifications
    static JSONObject describe(Context c, StatusBarNotification sbn) {
        if (!PhoneNotifs.worthShowing(sbn, c.getPackageName())) return null;
        Notification n = sbn.getNotification();
        Bundle x = n.extras;
        CharSequence title = x.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence text = x.getCharSequence(Notification.EXTRA_BIG_TEXT);
        if (text == null) text = x.getCharSequence(Notification.EXTRA_TEXT);
        if (title == null && text == null) return null;
        String app = sbn.getPackageName();
        try {
            PackageManager pm = c.getPackageManager();
            app = pm.getApplicationLabel(pm.getApplicationInfo(sbn.getPackageName(), 0)).toString();
        } catch (Exception ignored) {
        }
        return new Obj().putOpt("key", sbn.getKey()).putOpt("app", app).putOpt("pkg", sbn.getPackageName())
                .putOpt("title", title == null ? "" : title.toString()).putOpt("text", text == null ? "" : text.toString())
                .putOpt("ts", sbn.getPostTime() / 1000.0).putOpt("reply", replyAction(n) != null);
    }

    static Notification.Action replyAction(Notification n) {
        if (n.actions == null) return null;
        for (Notification.Action a : n.actions) if (a.getRemoteInputs() != null && a.getRemoteInputs().length > 0) return a;
        return null;
    }

    private JSONObject notifs() {
        PhoneNotifs s = PhoneNotifs.instance;
        if (s == null) return err("Notification access isn't allowed on the phone (Chat → ⋮ → 📱 Phone link)");
        JSONArray out = new JSONArray();
        StatusBarNotification[] all = s.getActiveNotifications();
        if (all != null) {
            Arrays.sort(all, (p, q) -> Long.compare(q.getPostTime(), p.getPostTime()));
            for (StatusBarNotification sbn : all) {
                JSONObject d = describe(c, sbn);
                if (d != null) out.put(d);
            }
        }
        return new Obj().putOpt("ok", true).putOpt("items", out);
    }

    private JSONObject dismiss(JSONObject req) {
        PhoneNotifs s = PhoneNotifs.instance;
        if (s == null) return err("Notification access isn't allowed on the phone");
        if (req.optBoolean("all")) s.cancelAllNotifications();
        else s.cancelNotification(req.optString("key"));
        return new Obj().putOpt("ok", true);
    }

    private JSONObject reply(JSONObject req) throws Exception {
        PhoneNotifs s = PhoneNotifs.instance;
        if (s == null) return err("Notification access isn't allowed on the phone");
        StatusBarNotification[] all = s.getActiveNotifications();
        if (all != null) for (StatusBarNotification sbn : all) {
            if (!sbn.getKey().equals(req.optString("key"))) continue;
            Notification.Action a = replyAction(sbn.getNotification());
            if (a == null) return err("That app doesn't accept replies from notifications");
            Intent i = new Intent();
            Bundle results = new Bundle();
            for (RemoteInput ri : a.getRemoteInputs()) results.putCharSequence(ri.getResultKey(), req.optString("text"));
            RemoteInput.addResultsToIntent(a.getRemoteInputs(), i, results);
            a.actionIntent.send(c, 0, i);
            return new Obj().putOpt("ok", true);
        }
        return err("That notification is gone");
    }

    // ---------- SMS
    String contactName(String number) {
        if (number == null || c.checkSelfPermission(Manifest.permission.READ_CONTACTS) != PackageManager.PERMISSION_GRANTED) return null;
        Uri u = Uri.withAppendedPath(ContactsContract.PhoneLookup.CONTENT_FILTER_URI, Uri.encode(number));
        try (Cursor q = c.getContentResolver().query(u, new String[]{ContactsContract.PhoneLookup.DISPLAY_NAME}, null, null, null)) {
            if (q != null && q.moveToFirst()) return q.getString(0);
        } catch (Exception ignored) {
        }
        return null;
    }

    private JSONObject threads() {
        if (!smsAllowed()) return err("SMS isn't allowed on the phone (Chat → ⋮ → 📱 Phone link)");
        Map<Long, JSONObject> byThread = new LinkedHashMap<>();
        Map<String, String> names = new java.util.HashMap<>();
        try (Cursor q = c.getContentResolver().query(Uri.parse("content://sms"),
                new String[]{"thread_id", "address", "body", "date", "type", "read"}, null, null, "date DESC LIMIT 600")) {
            while (q != null && q.moveToNext()) {
                long tid = q.getLong(0);
                JSONObject t = byThread.get(tid);
                if (t == null) {
                    String addr = q.getString(1);
                    if (!names.containsKey(addr)) names.put(addr, contactName(addr));
                    t = new Obj().putOpt("id", tid).putOpt("address", addr).putOpt("name", names.get(addr))
                            .putOpt("snippet", q.getString(2)).putOpt("ts", q.getLong(3) / 1000.0).putOpt("unread", false);
                    byThread.put(tid, t);
                }
                if (q.getInt(4) == 1 && q.getInt(5) == 0) ChatEngine.put(t, "unread", true);
            }
        }
        JSONArray out = new JSONArray();
        for (JSONObject t : byThread.values()) out.put(t);
        return new Obj().putOpt("ok", true).putOpt("threads", out);
    }

    private JSONObject messages(JSONObject req) {
        if (!smsAllowed()) return err("SMS isn't allowed on the phone");
        java.util.List<JSONObject> list = new ArrayList<>();
        try (Cursor q = c.getContentResolver().query(Uri.parse("content://sms"), new String[]{"_id", "body", "date", "type"},
                "thread_id=?", new String[]{String.valueOf(req.optLong("thread"))}, "date DESC LIMIT 200")) {
            while (q != null && q.moveToNext())
                list.add(new Obj().putOpt("id", q.getLong(0)).putOpt("body", q.getString(1)).putOpt("ts", q.getLong(2) / 1000.0)
                        .putOpt("out", q.getInt(3) == 2));
        }
        java.util.Collections.reverse(list);
        return new Obj().putOpt("ok", true).putOpt("messages", new JSONArray(list));
    }

    @SuppressWarnings("deprecation")
    private JSONObject send(JSONObject req) {
        if (!smsAllowed()) return err("SMS isn't allowed on the phone");
        String to = req.optString("address").trim(), text = req.optString("text");
        if (to.isEmpty() || text.isEmpty()) return err("number and message needed");
        SmsManager sm = android.os.Build.VERSION.SDK_INT >= 31 ? c.getSystemService(SmsManager.class) : SmsManager.getDefault();
        ArrayList<String> parts = sm.divideMessage(text);
        sm.sendMultipartTextMessage(to, null, parts, null, null);
        return new Obj().putOpt("ok", true);
    }

    // ---------- calls (the call itself runs on the phone)
    private JSONObject callState() {
        return new Obj().putOpt("state", PhoneCalls.state).putOpt("number", PhoneCalls.number).putOpt("name", PhoneCalls.name)
                .putOpt("since", PhoneCalls.since);
    }

    private JSONObject calls() {
        if (!callsAllowed()) return err("Calls aren't allowed on the phone (Chat → ⋮ → 📱 Phone link → Allow calls)");
        JSONArray out = new JSONArray();
        try (Cursor q = c.getContentResolver().query(android.provider.CallLog.Calls.CONTENT_URI,
                new String[]{"number", "name", "date", "duration", "type"}, null, null, "date DESC LIMIT 150")) {
            while (q != null && q.moveToNext()) {
                int t = q.getInt(4);
                String kind = t == 1 ? "in" : t == 2 ? "out" : t == 3 ? "missed" : t == 5 ? "declined" : "other";
                out.put(new Obj().putOpt("number", q.getString(0)).putOpt("name", q.getString(1)).putOpt("ts", q.getLong(2) / 1000.0)
                        .putOpt("duration", q.getLong(3)).putOpt("type", kind));
            }
        }
        return new Obj().putOpt("ok", true).putOpt("items", out).putOpt("call", callState());
    }

    @SuppressWarnings({"deprecation", "MissingPermission"})
    private JSONObject answer() {
        if (!callsAllowed()) return err("Calls aren't allowed on the phone");
        android.telecom.TelecomManager tm = (android.telecom.TelecomManager) c.getSystemService(Context.TELECOM_SERVICE);
        tm.acceptRingingCall();
        return new Obj().putOpt("ok", true);
    }

    @SuppressWarnings({"deprecation", "MissingPermission"})
    private JSONObject endCall() {
        if (!callsAllowed()) return err("Calls aren't allowed on the phone");
        if (android.os.Build.VERSION.SDK_INT < 28) return err("Ending calls from the PC needs Android 9 or newer");
        android.telecom.TelecomManager tm = (android.telecom.TelecomManager) c.getSystemService(Context.TELECOM_SERVICE);
        return tm.endCall() ? new Obj().putOpt("ok", true) : err("There's no call to end");
    }

    @SuppressWarnings("MissingPermission")
    private JSONObject dial(JSONObject req) {
        if (!callsAllowed()) return err("Calls aren't allowed on the phone");
        String num = req.optString("number").replaceAll("[^0-9+*#]", "");
        if (num.isEmpty()) return err("no number");
        android.telecom.TelecomManager tm = (android.telecom.TelecomManager) c.getSystemService(Context.TELECOM_SERVICE);
        tm.placeCall(Uri.fromParts("tel", num, null), new Bundle());     // works from the background (no screen)
        return new Obj().putOpt("ok", true);
    }

    // ---------- files (shared storage only)
    private File root() {
        return Environment.getExternalStorageDirectory();
    }

    private File inside(String path) throws Exception {
        File r = root().getCanonicalFile(), f = (path == null || path.isEmpty() ? r : new File(path)).getCanonicalFile();
        if (!f.getPath().equals(r.getPath()) && !f.getPath().startsWith(r.getPath() + File.separator))
            throw new SecurityException("outside the phone's shared storage");
        return f;
    }

    private JSONObject files(JSONObject req) throws Exception {
        File dir = inside(req.optString("path", null));
        File[] kids = dir.listFiles();
        if (kids == null) return err("can't read that folder (allow file access for Arckad-D)");
        Arrays.sort(kids, (p, q) -> p.isDirectory() != q.isDirectory() ? (p.isDirectory() ? -1 : 1) : p.getName().compareToIgnoreCase(q.getName()));
        JSONArray out = new JSONArray();
        for (File k : kids) {
            if (k.getName().startsWith(".")) continue;
            out.put(new Obj().putOpt("name", k.getName()).putOpt("path", k.getPath()).putOpt("dir", k.isDirectory())
                    .putOpt("size", k.isDirectory() ? 0 : k.length()).putOpt("mtime", k.lastModified() / 1000.0));
        }
        boolean top = dir.getPath().equals(root().getCanonicalPath());
        return new Obj().putOpt("ok", true).putOpt("path", dir.getPath()).putOpt("parent", top ? null : dir.getParent()).putOpt("items", out);
    }

    private JSONObject read(JSONObject req) throws Exception {
        File f = inside(req.optString("path"));
        long off = Math.max(0, req.optLong("offset")), total = f.length();
        int size = (int) Math.min(Math.max(1, req.optLong("size", 1_000_000)), 2_000_000);
        byte[] buf = new byte[(int) Math.max(0, Math.min(size, total - off))];
        try (RandomAccessFile raf = new RandomAccessFile(f, "r")) {
            raf.seek(off);
            raf.readFully(buf);
        }
        return new Obj().putOpt("ok", true).putOpt("data", ChatCrypto.b64(buf)).putOpt("total", total)
                .putOpt("eof", off + buf.length >= total);
    }
}

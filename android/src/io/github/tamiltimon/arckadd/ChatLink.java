package io.github.tamiltimon.arckadd;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigInteger;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;

import static io.github.tamiltimon.arckadd.ChatCrypto.*;
import static io.github.tamiltimon.arckadd.ChatEngine.*;

/** Linked devices: one chat account on phone and PC (same protocol as the desktop app). The devices share
 *  the account's identity; a private twin channel pushes new messages at once and merges state regularly. */
final class ChatLink {
    final ChatEngine e;
    private JSONObject code;
    final Map<String, String[]> seenCodes = new ConcurrentHashMap<>();
    private final Map<String, Double> seenAt = new ConcurrentHashMap<>();
    private long lastSync;

    ChatLink(ChatEngine e) {
        this.e = e;
    }

    // ---------- state
    JSONObject link() {
        JSONObject l = e.contacts.optJSONObject("link");
        return l == null ? new JSONObject() : l;
    }

    byte[] key() {
        String k = link().optString("key");
        return k.isEmpty() ? null : unhex(k);
    }

    JSONObject twins() {
        JSONObject t = link().optJSONObject("twins");
        return t == null ? new JSONObject() : t;
    }

    boolean twinOnline(String inst) {
        JSONObject t = twins().optJSONObject(inst);
        return t != null && now() - t.optDouble("seen", 0) < 15;
    }

    String[] twinAddress() {
        for (Iterator<String> it = twins().keys(); it.hasNext(); ) {
            String i = it.next();
            JSONObject t = twins().optJSONObject(i);
            if (twinOnline(i) && !t.optString("ip").isEmpty() && t.optInt("port") > 0)
                return new String[]{t.optString("ip"), String.valueOf(t.optInt("port"))};
        }
        return null;
    }

    void tomb(String kind, String k) {
        JSONObject tombs = e.contacts.optJSONObject("tombs");
        if (tombs == null) {
            tombs = new JSONObject();
            put(e.contacts, "tombs", tombs);
        }
        JSONObject t = tombs.optJSONObject(kind);
        if (t == null) {
            t = new JSONObject();
            put(tombs, kind, t);
        }
        put(t, k, now());
        e.saveContacts();
    }

    static String tag(byte[] k, long bucket) {
        return hex(hm(k, "twin", bucket)).substring(0, 24);
    }

    // ---------- presence
    void beaconFields(JSONObject msg) {
        byte[] k = key();
        if (k != null) {
            put(msg, "twin", tag(k, System.currentTimeMillis() / 30_000));
            put(msg, "inst", e.inst);
        }
        if (codeActive()) put(msg, "linkcode", sha256hex("arckad-link-code|" + code.optString("code")).substring(0, 20));
    }

    void onUdp(JSONObject msg, String ip) {
        int p = msg.optInt("port");
        if (!msg.optString("linkcode").isEmpty() && p > 0) {
            seenCodes.put(msg.optString("linkcode"), new String[]{ip, String.valueOf(p)});
            seenAt.put(msg.optString("linkcode"), now());
        }
        byte[] k = key();
        String inst = cut(msg.optString("inst"), 20);
        if (k == null || msg.optString("twin").isEmpty() || inst.equals(e.inst)) return;
        long b = System.currentTimeMillis() / 30_000;
        if (!msg.optString("twin").equals(tag(k, b)) && !msg.optString("twin").equals(tag(k, b - 1))) return;
        JSONObject t = twins().optJSONObject(inst);
        if (t == null) {
            t = new Obj().putOpt("name", "linked device").putOpt("os", "");
            Obj.put(twins(), inst, t);
        }
        boolean was = twinOnline(inst);
        put(t, "ip", ip);
        put(t, "port", p);
        put(t, "seen", now());
        if (!was) {
            e.saveContacts();
            e.ui.changed(null);
            bg(() -> sync(inst));
        }
    }

    // ---------- linking
    String newCode() {
        code = new Obj().putOpt("code", String.format(java.util.Locale.ROOT, "%06d", RNG.nextInt(1_000_000)))
                .putOpt("until", now() + 600).putOpt("tries", 0).putOpt("pending", new JSONObject());
        e.start();                                   // the code needs the service (also on a phone without a profile)
        return code.optString("code");
    }

    boolean codeActive() {
        return code != null && now() < code.optDouble("until");
    }

    void stopCode() {
        code = null;
    }

    JSONObject bundle() throws Exception {
        JSONObject contacts = new JSONObject(e.contacts.toString());
        contacts.remove("link");
        contacts.remove("pin");
        contacts.remove("pin_phone");
        JSONObject groups = new JSONObject();
        for (Map.Entry<String, JSONObject> g : e.groups.entrySet()) {
            JSONObject c = new JSONObject(g.getValue().toString());
            c.remove("files");
            c.remove("hidden");
            Obj.put(groups, g.getKey(), c);
        }
        return new Obj().putOpt("device_id", e.me).putOpt("identity", e.identity()).putOpt("contacts", contacts)
                .putOpt("groups", groups).putOpt("photo", b64(e.photoBytes())).putOpt("settings", new JSONObject());
    }

    JSONObject start(JSONObject req, String ip) {
        if (!codeActive()) return err("no link code is shown on that device right now");
        BigInteger theirs = new BigInteger(req.optString("pub", "0"), 16);
        BigInteger x = dhSecret(), pub = dhPublic(x);
        byte[] shared = dhShared(req.optString("pub"), x);
        byte[] key = sha256(utf8("arckad-link-key|"), shared, fixed(theirs, 256), fixed(pub, 256));
        Obj.put(code.optJSONObject("pending"), cut(req.optString("inst"), 20), new Obj().putOpt("key", hex(key))
                .putOpt("name", cut(req.optString("name", "device"), 40)).putOpt("os", cut(req.optString("os"), 10))
                .putOpt("ip", ip).putOpt("port", req.opt("port")));
        return new Obj().putOpt("ok", true).putOpt("pub", pub.toString(16)).putOpt("inst", e.inst)
                .putOpt("name", e.deviceName).putOpt("os", e.osName).putOpt("port", e.port);
    }

    JSONObject confirm(JSONObject req, String ip) throws Exception {
        String inst = cut(req.optString("inst"), 20);
        JSONObject st = codeActive() ? code.optJSONObject("pending").optJSONObject(inst) : null;
        if (st == null) return err("the link code has expired; show a new one");
        byte[] key = unhex(st.optString("key"));
        String c = code.optString("code");
        if (!same(hex(hm(key, "link-guest", c)), req.optString("proof"))) {
            put(code, "tries", code.optInt("tries") + 1);
            if (code.optInt("tries") >= 5) code = null;
            return err("wrong code");
        }
        ChatEngine.Ask ev = new ChatEngine.Ask();
        ev.name = st.optString("name");
        ev.os = st.optString("os");
        ev.group = null;                                     // null group = a link request
        e.ui.askLink(ev);
        ev.done.await(120, TimeUnit.SECONDS);
        if (!ev.accepted) return err("not approved on the other device");
        JSONObject link = e.contacts.optJSONObject("link");
        if (link == null) {
            link = new JSONObject();
            put(e.contacts, "link", link);
        }
        if (link.optString("key").isEmpty()) put(link, "key", hex(random(32)));
        if (link.optJSONObject("twins") == null) put(link, "twins", new JSONObject());
        Obj.put(link.optJSONObject("twins"), inst, new Obj().putOpt("name", st.optString("name")).putOpt("os", st.optString("os"))
                .putOpt("ip", ip).putOpt("port", st.opt("port")).putOpt("seen", now()).putOpt("linked", now()));
        e.saveContacts();
        code = null;
        JSONObject payload = new Obj().putOpt("proof", hex(hm(key, "link-host", c))).putOpt("link_key", link.optString("key"))
                .putOpt("bundle", bundle()).putOpt("twin", new Obj().putOpt("inst", e.inst).putOpt("name", e.deviceName).putOpt("os", e.osName));
        e.ui.event("🔗 " + st.optString("name") + " is now linked to your account");
        bg(() -> {
            sleep(3000);
            sync(inst);
        });
        return new Obj().putOpt("ok", true).putOpt("sealed", b64(seal(key, utf8(payload.toString()))));
    }

    /** Background thread on the NEW device. Returns null when linked (the engine then restarts), or why not. */
    String linkWithCode(String c, String host) {
        e.linking = true;                            // run the service even on a phone with no chat profile yet
        e.start();
        String[] where = null;
        if (host != null && !host.isEmpty()) {
            for (int p : TCP_PORTS) {
                if (p == 0) continue;
                try (java.net.Socket s = new java.net.Socket()) {
                    s.connect(new java.net.InetSocketAddress(host, p), 2000);
                    where = new String[]{java.net.InetAddress.getByName(host).getHostAddress(), String.valueOf(p)};
                    break;
                } catch (Exception ignored) {
                }
            }
        } else {
            String want = sha256hex("arckad-link-code|" + c).substring(0, 20);
            long end = System.currentTimeMillis() + 8000;
            while (System.currentTimeMillis() < end && where == null) {
                Double t = seenAt.get(want);
                if (t != null && now() - t < 10) where = seenCodes.get(want);
                if (where == null) sleep(200);
            }
        }
        if (where == null) {
            e.linking = false;
            return "No device showing that link code was found. On another network, also type its IP address.";
        }
        try {
            BigInteger x = dhSecret(), pub = dhPublic(x);
            JSONObject r1 = post(where, "/t/start", new Obj().putOpt("inst", e.inst).putOpt("name", e.deviceName)
                    .putOpt("os", e.osName).putOpt("pub", pub.toString(16)).putOpt("port", e.port));
            if (!r1.optBoolean("ok")) return r1.optString("reason", "refused");
            BigInteger theirs = new BigInteger(r1.optString("pub"), 16);
            byte[] key = sha256(utf8("arckad-link-key|"), dhShared(r1.optString("pub"), x), fixed(pub, 256), fixed(theirs, 256));
            JSONObject r2 = post(where, "/t/confirm", new Obj().putOpt("inst", e.inst).putOpt("proof", hex(hm(key, "link-guest", c))));
            if (!r2.optBoolean("ok")) return r2.optString("reason", "not approved");
            JSONObject data = new JSONObject(new String(unseal(key, unb64(r2.optString("sealed"))), StandardCharsets.UTF_8));
            if (!same(hex(hm(key, "link-host", c)), data.optString("proof"))) return "the other device couldn't prove it knows the code";
            adopt(data.optJSONObject("bundle"), data.optString("link_key"), data.optJSONObject("twin"), where[0],
                    r1.optInt("port", Integer.parseInt(where[1])));
            return null;
        } catch (Exception ex) {
            return "connection problem (" + ex.getMessage() + ")";
        }
    }

    private static JSONObject post(String[] where, String path, JSONObject obj) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL("http://" + where[0] + ":" + where[1] + path).openConnection();
        c.setConnectTimeout(5000);
        c.setReadTimeout(150_000);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        byte[] body = utf8(obj.toString());
        c.setFixedLengthStreamingMode(body.length);
        try (OutputStream o = c.getOutputStream()) {
            o.write(body);
        }
        int code = c.getResponseCode();
        try (InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream()) {
            byte[] d = in == null ? new byte[0] : readStream(in, 50_000_000);
            return d.length == 0 ? new JSONObject() : new JSONObject(new String(d, StandardCharsets.UTF_8));
        }
    }

    // ---------- safety copies: a link never destroys a profile
    File safetyDir() {
        return new File(e.dir.getParentFile(), "chat-before-link");
    }

    int[] summary() {
        int groups = 0, msgs = 0;
        for (JSONObject g : e.groups.values()) if (!"direct".equals(g.optString("kind")) && !g.optBoolean("removed")) groups++;
        for (List<JSONObject> l : e.msgs.values()) msgs += l.size();
        return new int[]{e.friends().length(), groups, msgs};
    }

    boolean hasData() {
        int[] s = summary();
        return s[0] + s[1] + s[2] > 0;
    }

    void saveSafetyCopy(String reason) {
        if (!hasData()) return;
        File dest = new File(safetyDir(), new java.text.SimpleDateFormat("yyyy-MM-dd HH.mm.ss", java.util.Locale.ROOT).format(new java.util.Date()));
        File chat = new File(dest, "chat");
        chat.mkdirs();
        copyDir(e.dir, chat);
        int[] s = summary();
        writeJson(new File(dest, "info.json"), new Obj().putOpt("name", e.myName()).putOpt("friends", s[0]).putOpt("groups", s[1])
                .putOpt("messages", s[2]).putOpt("device_id", e.me).putOpt("reason", reason).putOpt("saved", now()));
    }

    private static void copyDir(File src, File dst) {
        File[] all = src.listFiles();
        if (all == null) return;
        dst.mkdirs();
        for (File f : all) {
            File t = new File(dst, f.getName());
            if (f.isDirectory()) copyDir(f, t);
            else try {
                writeFile(t, readAll(f));
            } catch (Exception ignored) {
            }
        }
    }

    List<Object[]> safetyCopies() {
        List<Object[]> out = new ArrayList<>();
        File[] all = safetyDir().listFiles();
        if (all == null) return out;
        java.util.Arrays.sort(all, (x, y) -> y.getName().compareTo(x.getName()));
        for (File d : all) {
            JSONObject info = readJson(new File(d, "info.json"));
            if (info.length() > 0 && new File(d, "chat").isDirectory()) out.add(new Object[]{d, info});
        }
        return out;
    }

    /** Bring back a saved profile; the current one is saved too. Restarts the engine as that profile. */
    void restoreSafetyCopy(File folder) {
        JSONObject info = readJson(new File(folder, "info.json"));
        saveSafetyCopy("before restoring an older profile");
        e.stop();
        File[] all = e.dir.listFiles();
        if (all != null) for (File f : all) deleteTree(f);
        copyDir(new File(folder, "chat"), e.dir);
        e.ui.relinked(info.optString("device_id", e.me));
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteTree(k);
        f.delete();
    }

    /** Become the linked account: its files replace this phone's chat data (saved first); the engine restarts. */
    void adopt(JSONObject b, String linkKey, JSONObject twin, String ip, int port) throws Exception {
        saveSafetyCopy("linked to " + twin.optString("name", "another device"));
        e.stop();
        File[] old = e.dir.listFiles();
        if (old != null) for (File f : old) if (f.getName().endsWith(".jsonl")) f.delete();
        JSONObject contacts = b.optJSONObject("contacts");
        JSONObject twinEntry = new Obj().putOpt("name", twin.optString("name", "device")).putOpt("os", twin.optString("os"))
                .putOpt("ip", ip).putOpt("port", port).putOpt("seen", now()).putOpt("linked", now());
        put(contacts, "link", new Obj().putOpt("key", linkKey).putOpt("twins", new Obj().putOpt(twin.optString("inst"), twinEntry)));
        writeJson(new File(e.dir, "contacts.json"), contacts);
        JSONObject groups = b.optJSONObject("groups");
        for (Iterator<String> it = groups.keys(); it.hasNext(); ) put(groups.optJSONObject(it.next()), "files", new JSONObject());
        writeJson(new File(e.dir, "groups.json"), new Obj().putOpt("groups", groups));
        writeJson(new File(e.dir, "identity.json"), b.optJSONObject("identity"));
        byte[] photo = unb64(b.optString("photo"));
        if (photo.length > 0) writeFile(e.photoFile(), photo);
        else e.photoFile().delete();
        e.ui.relinked(b.optString("device_id"));
    }

    // ---------- talking to the linked device
    JSONObject call(String inst, String path, JSONObject obj, int timeout) throws Exception {
        JSONObject t = twins().optJSONObject(inst);
        byte[] k = key();
        if (t == null || k == null || t.optString("ip").isEmpty() || t.optInt("port") == 0) throw new java.io.IOException("not reachable");
        byte[] body = seal(k, utf8(obj.toString()));
        HttpURLConnection c = (HttpURLConnection) new URL("http://" + t.optString("ip") + ":" + t.optInt("port") + path).openConnection();
        c.setConnectTimeout(5000);
        c.setReadTimeout(timeout);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        long ts = System.currentTimeMillis() / 1000;
        c.setRequestProperty("X-Link-From", e.inst);
        c.setRequestProperty("X-Link-Time", String.valueOf(ts));
        c.setRequestProperty("X-Link-Sig", hex(hm(k, "POST", path, ts, e.inst)));
        c.setFixedLengthStreamingMode(body.length);
        try (OutputStream o = c.getOutputStream()) {
            o.write(body);
        }
        if (c.getResponseCode() != 200) throw new SecurityException("refused (" + c.getResponseCode() + ")");
        byte[] d;
        try (InputStream in = c.getInputStream()) {
            d = readStream(in, 100_000_000);
        }
        return d.length == 0 ? new JSONObject() : new JSONObject(new String(unseal(k, d), StandardCharsets.UTF_8));
    }

    void push(String gid, JSONObject m) {
        if (key() == null || m.optBoolean("local")) return;
        bg(() -> {
            for (Iterator<String> it = twins().keys(); it.hasNext(); ) {
                String inst = it.next();
                if (!twinOnline(inst)) continue;
                try {
                    call(inst, "/t/push", new Obj().putOpt("gid", gid).putOpt("msg", m), 8000);
                } catch (Exception ignored) {
                }
            }
        });
    }

    void pushRead(String gid) {
        if (key() == null) return;
        bg(() -> {
            for (Iterator<String> it = twins().keys(); it.hasNext(); ) {
                String inst = it.next();
                if (!twinOnline(inst)) continue;
                try {
                    call(inst, "/t/read", new Obj().putOpt("gid", gid), 6000);
                } catch (Exception ignored) {
                }
            }
        });
    }

    JSONObject state() throws Exception {
        JSONObject contacts = new JSONObject(e.contacts.toString());
        for (String k : new String[]{"link", "pin", "pin_phone"}) contacts.remove(k);
        JSONObject groups = new JSONObject();
        for (Map.Entry<String, JSONObject> g : e.groups.entrySet()) {
            JSONObject c = new JSONObject(g.getValue().toString());
            c.remove("files");
            c.remove("hidden");
            Obj.put(groups, g.getKey(), c);
        }
        return new Obj().putOpt("contacts", contacts).putOpt("groups", groups).putOpt("photo_hash", e.photoHash());
    }

    private static double ts(JSONObject tombs, String kind, String k) {
        JSONObject t = tombs == null ? null : tombs.optJSONObject(kind);
        return t == null ? 0 : t.optDouble(k, 0);
    }

    void merge(JSONObject st, String twin) {
        boolean changed = false;
        JSONObject theirs = st.optJSONObject("contacts");
        if (theirs == null) theirs = new JSONObject();
        JSONObject tombs = e.contacts.optJSONObject("tombs");
        if (tombs == null) {
            tombs = new JSONObject();
            put(e.contacts, "tombs", tombs);
        }
        JSONObject tt = theirs.optJSONObject("tombs");
        if (tt != null) for (Iterator<String> it = tt.keys(); it.hasNext(); ) {
            String kind = it.next();
            JSONObject src = tt.optJSONObject(kind), dst = tombs.optJSONObject(kind);
            if (dst == null) {
                dst = new JSONObject();
                put(tombs, kind, dst);
            }
            for (Iterator<String> i2 = src.keys(); i2.hasNext(); ) {
                String k = i2.next();
                if (src.optDouble(k) > dst.optDouble(k, 0)) {
                    put(dst, k, src.optDouble(k));
                    changed = true;
                }
            }
        }
        JSONObject tp = theirs.optJSONObject("profile");
        if (tp != null && tp.optDouble("updated", 0) > e.profile.optDouble("updated", 0)) {
            for (Iterator<String> it = tp.keys(); it.hasNext(); ) {
                String k = it.next();
                put(e.profile, k, tp.opt(k));
            }
            changed = true;
            if (!st.optString("photo_hash").equals(e.photoHash())) bg(() -> fetchPhoto(twin));
        }
        for (String kind : new String[]{"friends", "incoming", "outgoing"}) {
            JSONObject mine = e.contacts.optJSONObject(kind), src = theirs.optJSONObject(kind);
            if (src == null) continue;
            for (Iterator<String> it = src.keys(); it.hasNext(); ) {
                String pid = it.next();
                JSONObject x = src.optJSONObject(pid);
                if (!mine.has(pid) || (kind.equals("friends") && x.optDouble("since", 0) > mine.optJSONObject(pid).optDouble("since", 0))) {
                    Obj.put(mine, pid, x);
                    changed = true;
                }
            }
        }
        for (String pid : list(e.friends().keys()))
            if (ts(tombs, "friend", pid) > e.friends().optJSONObject(pid).optDouble("since", 0)) {
                e.friends().remove(pid);
                changed = true;
            }
        for (String kind : new String[]{"incoming", "outgoing"}) {
            JSONObject m = e.contacts.optJSONObject(kind);
            for (String pid : list(m.keys()))
                if (e.friends().has(pid) || ts(tombs, "req", pid) > m.optJSONObject(pid).optDouble("ts", 0)) {
                    m.remove(pid);
                    changed = true;
                }
        }
        JSONObject gs = st.optJSONObject("groups");
        if (gs != null) for (Iterator<String> it = gs.keys(); it.hasNext(); ) {
            String gid = it.next();
            JSONObject g = gs.optJSONObject(gid);
            boolean direct = "direct".equals(g.optString("kind"));
            if (!direct && ts(tombs, "group", gid) > g.optDouble("created", 0)) continue;
            if (direct && ts(tombs, "purge", g.optString("peer")) > g.optDouble("created", 0)) continue;
            JSONObject mine = e.groups.get(gid);
            if (mine == null) {
                put(g, "files", new JSONObject());
                e.groups.put(gid, g);
                e.msgs.putIfAbsent(gid, java.util.Collections.synchronizedList(new ArrayList<>()));
                e.ids.putIfAbsent(gid, java.util.Collections.synchronizedSet(new HashSet<>()));
                changed = true;
                continue;
            }
            if (g.optInt("version") > mine.optInt("version") || (direct && !g.optBoolean("removed") && !g.optString("key").equals(mine.optString("key")))) {
                for (String k : new String[]{"name", "owner_only", "members", "key", "version", "past", "removed", "owner"})
                    if (g.has(k)) put(mine, k, g.opt(k));
                changed = true;
            }
            for (String k : new String[]{"pair_keys", "pending_adds"}) {
                JSONObject src = g.optJSONObject(k);
                if (src == null) continue;
                JSONObject dst = mine.optJSONObject(k);
                if (dst == null) {
                    dst = new JSONObject();
                    put(mine, k, dst);
                }
                for (Iterator<String> i2 = src.keys(); i2.hasNext(); ) {
                    String x = i2.next();
                    if (!dst.has(x)) {
                        Obj.put(dst, x, src.opt(x));
                        changed = true;
                    }
                }
            }
            if (!g.optString("owner_key").isEmpty() && mine.optString("owner_key").isEmpty()) {
                put(mine, "owner_key", g.optString("owner_key"));
                changed = true;
            }
        }
        for (String gid : new ArrayList<>(e.groups.keySet())) {
            JSONObject g = e.groups.get(gid);
            if (!"direct".equals(g.optString("kind")) && ts(tombs, "group", gid) > g.optDouble("created", 0)) {
                e.groups.remove(gid);
                changed = true;
            }
        }
        JSONObject purge = tombs.optJSONObject("purge");
        if (purge != null) for (String pid : list(purge.keys())) {
            double when = purge.optDouble(pid);
            JSONObject f = e.friends().optJSONObject(pid);
            String dgid = e.directGid(pid);
            JSONObject dg = e.groups.get(dgid);
            if ((f == null || f.optDouble("since", 0) < when) && (dg != null || f != null)
                    && (dg == null || dg.optDouble("created", 0) < when)) {
                e.purgeFriend(pid, ts(tombs, "purgefiles", pid) >= when, true);
                changed = true;
            }
        }
        if (changed) {
            e.save();
            e.saveContacts();
            e.resetTags();
            e.ui.changed(null);
            e.ui.people();
        }
    }

    private static List<String> list(Iterator<String> it) {
        List<String> l = new ArrayList<>();
        while (it.hasNext()) l.add(it.next());
        return l;
    }

    private void fetchPhoto(String inst) {
        JSONObject t = twins().optJSONObject(inst);
        if (t == null) return;
        try {
            HttpURLConnection c = (HttpURLConnection) new URL("http://" + t.optString("ip") + ":" + t.optInt("port") + "/f/photo").openConnection();
            c.setConnectTimeout(5000);
            c.setReadTimeout(8000);
            if (c.getResponseCode() == 200) {
                try (InputStream in = c.getInputStream()) {
                    writeFile(e.photoFile(), readStream(in, 2_000_000));
                }
            } else e.photoFile().delete();
            e.ui.changed(null);
        } catch (Exception ignored) {
        }
    }

    void sync(String inst) {
        if (key() == null || !twins().has(inst)) return;
        try {
            JSONObject r = call(inst, "/t/state", new Obj().putOpt("state", state()), 30_000);
            if (r.optJSONObject("state") != null) merge(r.optJSONObject("state"), inst);
            for (int round = 0; round < 20; round++) {
                JSONObject have = new JSONObject();
                for (String gid : e.groups.keySet()) {
                    JSONArray a = new JSONArray();
                    for (JSONObject m : new ArrayList<>(e.msgs.getOrDefault(gid, new ArrayList<>()))) a.put(m.optString("id"));
                    Obj.put(have, gid, a);
                }
                r = call(inst, "/t/msgs", new Obj().putOpt("have", have), 60_000);
                int got = 0;
                JSONObject ms = r.optJSONObject("msgs");
                if (ms != null) for (Iterator<String> it = ms.keys(); it.hasNext(); ) {
                    String gid = it.next();
                    JSONArray a = ms.optJSONArray(gid);
                    if (!e.groups.containsKey(gid) || a == null) continue;
                    for (int i = 0; i < a.length(); i++) {
                        JSONObject m = a.optJSONObject(i);
                        if (m != null && e.append(gid, m)) {
                            got++;
                            if (m.optJSONObject("file") != null) e.maybeDownload(gid, m);
                        }
                    }
                }
                if (got > 0) e.ui.changed(null);
                if (!r.optBoolean("more")) break;
            }
            JSONObject t = twins().optJSONObject(inst);
            if (t != null) {
                put(t, "synced", now());
                e.saveContacts();
            }
        } catch (Exception ignored) {
        }
    }

    void tick() {
        if (System.currentTimeMillis() - lastSync < 30_000 || key() == null) return;
        lastSync = System.currentTimeMillis();
        for (String inst : list(twins().keys())) if (twinOnline(inst)) bg(() -> sync(inst));
    }

    boolean unlink(String inst) {
        boolean told;
        try {
            call(inst, "/t/unlink", new JSONObject(), 6000);
            told = true;
        } catch (Exception ex) {
            told = false;
        }
        twins().remove(inst);
        if (twins().length() == 0) e.contacts.remove("link");
        e.saveContacts();
        e.ui.changed(null);
        return told;
    }

    /** This phone was unlinked: remove the shared account (it starts fresh). */
    void wipeHere() {
        saveSafetyCopy("unlinked");
        e.stop();
        File[] all = e.dir.listFiles();
        if (all != null) for (File f : all) if (f.isFile()) f.delete();
        e.ui.relinked(token(8));
    }

    // ---------- server side
    void handle(Net.Request r, String path) throws Exception {
        if (path.equals("/t/start")) {
            r.json(200, start(body(r), r.client));
            return;
        }
        if (path.equals("/t/confirm")) {
            JSONObject res = confirm(body(r), r.client);
            r.json(res.optBoolean("ok") ? 200 : 403, res);
            return;
        }
        byte[] k = key();
        String inst = r.headers.getOrDefault("x-link-from", "");
        JSONObject t = twins().optJSONObject(inst);
        long ts;
        try {
            ts = Long.parseLong(r.headers.getOrDefault("x-link-time", "0"));
        } catch (NumberFormatException ex) {
            ts = 0;
        }
        if (k == null || t == null || Math.abs(System.currentTimeMillis() / 1000 - ts) > 600
                || !same(hex(hm(k, "POST", r.path, ts, inst)), r.headers.getOrDefault("x-link-sig", ""))) {
            r.json(401, err("not linked"));
            return;
        }
        put(t, "ip", r.client);
        put(t, "seen", now());
        long n = r.length();
        byte[] raw = n > 0 ? readStream(r.body, (int) Math.min(n, 50_000_000)) : new byte[0];
        JSONObject req = raw.length > 0 ? new JSONObject(new String(unseal(k, raw), StandardCharsets.UTF_8)) : new JSONObject();
        JSONObject res = new Obj().putOpt("ok", true);
        switch (path) {
            case "/t/state":
                if (req.optJSONObject("state") != null) merge(req.optJSONObject("state"), inst);
                put(res, "state", state());
                break;
            case "/t/msgs": {
                JSONObject have = req.optJSONObject("have");
                JSONObject out = new JSONObject();
                int count = 0;
                boolean more = false;
                for (Map.Entry<String, List<JSONObject>> en : e.msgs.entrySet()) {
                    Set<String> known = new HashSet<>();
                    JSONArray a = have == null ? null : have.optJSONArray(en.getKey());
                    if (a != null) for (int i = 0; i < a.length(); i++) known.add(a.optString(i));
                    for (JSONObject m : new ArrayList<>(en.getValue())) {
                        if (m.optBoolean("local") || known.contains(m.optString("id"))) continue;
                        if (count >= 3000) {
                            more = true;
                            break;
                        }
                        JSONArray arr = out.optJSONArray(en.getKey());
                        if (arr == null) {
                            arr = new JSONArray();
                            Obj.put(out, en.getKey(), arr);
                        }
                        JSONObject c = new JSONObject(m.toString());
                        c.remove("r_sent");
                        arr.put(c);
                        count++;
                    }
                }
                put(res, "msgs", out);
                put(res, "more", more);
                break;
            }
            case "/t/push": {
                String gid = req.optString("gid");
                JSONObject m = req.optJSONObject("msg");
                if (e.groups.containsKey(gid) && m != null && !m.optString("id").isEmpty() && e.append(gid, m)) {
                    String kind = m.optString("kind");
                    if (!e.me.equals(m.optString("from")) && !kind.equals("system") && !kind.equals("delete")) {
                        e.unread.merge(gid, 1, Integer::sum);
                        e.ui.message(gid, m);
                    } else e.ui.changed(gid);
                    if (m.optJSONObject("file") != null) e.maybeDownload(gid, m);
                }
                break;
            }
            case "/t/read": {
                String gid = req.optString("gid");
                if (e.groups.containsKey(gid)) {
                    e.unread.put(gid, 0);
                    for (JSONObject m : new ArrayList<>(e.msgs.getOrDefault(gid, new ArrayList<>())))
                        if (!e.me.equals(m.optString("from"))) put(m, "r_sent", true);
                    e.rewrite(gid);
                    e.ui.changed(null);
                }
                break;
            }
            case "/t/unlink":
                r.send(200, "application/octet-stream", seal(k, utf8(res.toString())));
                bg(this::wipeHere);
                return;
            default:
                res = err("unknown");
        }
        r.send(200, "application/octet-stream", seal(k, utf8(res.toString())));
    }

    private static JSONObject body(Net.Request r) throws Exception {
        long n = r.length();
        if (n <= 0) return new JSONObject();
        return new JSONObject(new String(readStream(r.body, (int) Math.min(n, 200_000)), StandardCharsets.UTF_8));
    }
}

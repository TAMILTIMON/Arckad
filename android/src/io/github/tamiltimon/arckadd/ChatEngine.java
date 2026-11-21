package io.github.tamiltimon.arckadd;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.math.BigInteger;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static io.github.tamiltimon.arckadd.ChatCrypto.*;

/** Chat: groups, friends, messages, files. The same protocol as the desktop app (arckad-d.py), so phones and
 *  computers chat with each other. Runs the "paired" service: UDP 47830 signals and TCP 47831-47833.
 *  No Android classes here (it's tested against the desktop on a computer); the app supplies a Ui. */
final class ChatEngine {
    static final int UDP_PORT = 47830;
    static final int[] TCP_PORTS = {47831, 47832, 47833, 0};
    static final long AUTO_DOWNLOAD = 50L * 1024 * 1024;
    static final double HISTORY_DAYS = 120;
    static final String CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";

    interface Ui {
        void changed(String gid);                 // null = everything
        void people();
        void message(String gid, JSONObject m);
        void friendRequest(String pid);
        void askJoin(Ask ev);                     // group owner: let someone join?
        void event(String text);

        void fileSaved(File f);                   // so the gallery sees received photos
    }

    static final class Ask {
        final CountDownLatch done = new CountDownLatch(1);
        volatile boolean accepted;
        String name, os, group;
    }

    final File dir;                               // private storage
    final File downloads;                         // attachments go to <downloads>/Arckad-D Chat/<group>
    final String me;
    final String deviceName, osName;
    final Ui ui;
    final Object lock = new Object();

    final Map<String, JSONObject> groups = new ConcurrentHashMap<>();
    final Map<String, List<JSONObject>> msgs = new ConcurrentHashMap<>();
    final Map<String, Set<String>> ids = new ConcurrentHashMap<>();
    final Map<String, Integer> unread = new ConcurrentHashMap<>();
    final Map<String, JSONObject> online = new ConcurrentHashMap<>();   // device id -> {ip, port, seen}
    final Map<String, JSONObject> people = new ConcurrentHashMap<>();
    final Map<String, double[]> codeSeen = new ConcurrentHashMap<>();
    final Map<String, String[]> codeAddr = new ConcurrentHashMap<>();
    final Set<String> downloading = Collections.synchronizedSet(new HashSet<>());
    JSONObject contacts, profile;
    private JSONObject ident;
    private JSONObject join, fcode;
    private Net.Server server;
    private DatagramSocket udp;
    private volatile boolean running;
    private long lastBeacon, lastDirect, lastSync;
    private final Map<String, Long> answered = new ConcurrentHashMap<>();
    private Map<String, String> tagTable = new HashMap<>();
    private String tagStamp = "";
    int port;

    ChatEngine(File dir, File downloads, String deviceId, String deviceName, String osName, Ui ui) {
        this.dir = dir;
        this.downloads = downloads;
        this.me = deviceId;
        this.deviceName = deviceName;
        this.osName = osName;
        this.ui = ui;
        dir.mkdirs();
        load();
    }

    static double now() {
        return System.currentTimeMillis() / 1000.0;
    }

    // ================================================================= storage (same files as the desktop)
    private void load() {
        JSONObject g = readJson(new File(dir, "groups.json"));
        JSONObject gs = g.optJSONObject("groups");
        if (gs != null) for (Iterator<String> it = gs.keys(); it.hasNext(); ) {
            String gid = it.next();
            groups.put(gid, gs.optJSONObject(gid));
            List<JSONObject> list = new ArrayList<>();
            Set<String> set = new HashSet<>();
            File f = new File(dir, gid + ".jsonl");
            if (f.exists()) {
                try {
                    for (String line : new String(readAll(f), StandardCharsets.UTF_8).split("\n")) {
                        if (line.trim().isEmpty()) continue;
                        try {
                            JSONObject m = new JSONObject(line);
                            if (set.add(m.optString("id"))) list.add(m);
                        } catch (Exception ignored) {
                        }
                    }
                } catch (IOException ignored) {
                }
            }
            sortMsgs(list);
            msgs.put(gid, Collections.synchronizedList(list));
            ids.put(gid, Collections.synchronizedSet(set));
        }
        contacts = readJson(new File(dir, "contacts.json"));
        for (String k : new String[]{"friends", "incoming", "outgoing"})
            if (contacts.optJSONObject(k) == null) put(contacts, k, new JSONObject());
        profile = contacts.optJSONObject("profile");
        if (profile == null) {
            profile = new JSONObject();
            put(profile, "name", "");
            put(profile, "visible", true);
            put(profile, "setup", false);
            put(contacts, "profile", profile);
        }
    }

    static void sortMsgs(List<JSONObject> list) {
        Collections.sort(list, (a, b) -> {
            int c = Double.compare(a.optDouble("ts", 0), b.optDouble("ts", 0));
            return c != 0 ? c : a.optString("id").compareTo(b.optString("id"));
        });
    }

    void save() {
        synchronized (lock) {
            JSONObject all = new JSONObject();
            for (Map.Entry<String, JSONObject> e : groups.entrySet()) put(all, e.getKey(), e.getValue());
            writeJson(new File(dir, "groups.json"), new Obj().putOpt("groups", all));
        }
    }

    void saveContacts() {
        synchronized (lock) {
            writeJson(new File(dir, "contacts.json"), contacts);
        }
    }

    boolean append(String gid, JSONObject m) {
        if ("delete".equals(m.optString("kind"))) applyDelete(gid, m);
        JSONObject hg = groups.get(gid);
        if (hg != null && hg.optBoolean("hidden") && !"delete".equals(m.optString("kind")) && !"system".equals(m.optString("kind"))) {
            hg.remove("hidden");
            save();
        }
        synchronized (lock) {
            if (!groups.containsKey(gid)) return false;
            Set<String> set = ids.computeIfAbsent(gid, k -> Collections.synchronizedSet(new HashSet<>()));
            if (!set.add(m.optString("id"))) return false;
            List<JSONObject> list = msgs.computeIfAbsent(gid, k -> Collections.synchronizedList(new ArrayList<>()));
            list.add(m);
            sortMsgs(list);
            try (FileOutputStream o = new FileOutputStream(new File(dir, gid + ".jsonl"), true)) {
                o.write((m.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (IOException ignored) {
            }
            return true;
        }
    }

    // ================================================================= identity and profile
    JSONObject identity() {
        synchronized (lock) {
            if (ident == null) {
                JSONObject d = readJson(new File(dir, "identity.json"));
                if (d.optString("n").isEmpty() || d.optString("d").isEmpty()) {
                    try {
                        d = rsaGenerate();
                    } catch (Exception e) {
                        throw new IllegalStateException(e);
                    }
                    writeJson(new File(dir, "identity.json"), d);
                }
                ident = d;
            }
            return ident;
        }
    }

    String myPub() {
        return identity().optString("n");
    }

    String myName() {
        String n = profile.optString("name").trim();
        return n.isEmpty() ? deviceName : n;
    }

    File photoFile() {
        return new File(dir, "profile.jpg");
    }

    byte[] photoBytes() {
        try {
            return readAll(photoFile());
        } catch (IOException e) {
            return new byte[0];
        }
    }

    String photoHash() {
        byte[] d = photoBytes();
        return d.length == 0 ? "" : hex(sha256(d)).substring(0, 16);
    }

    /** jpeg: a ready square JPEG (the app crops and scales it), or null to keep; removePhoto to delete. */
    void setProfile(String name, byte[] jpeg, boolean removePhoto, boolean visible) {
        if (removePhoto) photoFile().delete();
        else if (jpeg != null) writeFile(photoFile(), jpeg);
        String n = name.trim();
        put(profile, "name", n.length() > 40 ? n.substring(0, 40) : n);
        put(profile, "visible", visible);
        put(profile, "setup", true);
        saveContacts();
        lastBeacon = 0;
        start();
        ui.changed(null);
    }

    File avatarFile(String pid) {
        File f = pid.equals(me) ? photoFile() : new File(new File(dir, "avatars"), pid + ".jpg");
        return f.exists() ? f : null;
    }

    // ================================================================= signatures
    static byte[] sigPayload(String gid, JSONObject m) {
        JSONObject f = m.optJSONObject("file");
        Object fileArr = f == null ? null : new Object[]{f.opt("id"), f.opt("name"), f.opt("size")};
        List<Object> parts = new ArrayList<>();
        Collections.addAll(parts, gid, m.opt("id"), m.opt("from"), pyRound(m.optDouble("ts", 0) * 1000),
                m.opt("kind"), m.optString("text", ""), fileArr, m.has("sticker") ? m.opt("sticker") : null);
        if (m.optDouble("voice", 0) != 0 || m.optBoolean("once")) {
            parts.add(Math.round(m.optDouble("voice", 0) * 10) / 10.0);
            parts.add(m.optBoolean("once"));
        }
        return utf8(pyJson(parts.toArray()));
    }

    JSONObject sign(String gid, JSONObject m) {
        put(m, "sig", rsaSign(identity(), sigPayload(gid, m)));
        return m;
    }

    String pubOf(String gid, String did) {
        JSONObject g = groups.get(gid);
        if (g == null) return null;
        JSONObject m = g.optJSONObject("members") == null ? null : g.optJSONObject("members").optJSONObject(did);
        if (m == null && g.optJSONObject("past") != null) m = g.optJSONObject("past").optJSONObject(did);
        String p = m == null ? "" : m.optString("pub");
        return p.isEmpty() ? null : p;
    }

    /** Only well-formed messages whose signature matches the sender's key are kept. */
    JSONObject clean(Object raw, String gid) {
        if (!(raw instanceof JSONObject)) return null;
        JSONObject m = (JSONObject) raw;
        String id = m.optString("id");
        if (id.isEmpty() || id.length() > 40) return null;
        String kind = m.optString("kind");
        if (!kind.equals("text") && !kind.equals("file") && !kind.equals("system") && !kind.equals("sticker") && !kind.equals("delete"))
            return null;
        JSONObject out = new JSONObject();
        put(out, "id", id);
        put(out, "from", cut(m.optString("from"), 40));
        put(out, "name", cut(m.optString("name", "?"), 40));
        put(out, "ts", m.optDouble("ts", 0));
        put(out, "kind", kind);
        put(out, "text", cut(m.optString("text", ""), 8000));
        JSONObject f = m.optJSONObject("file");
        if (kind.equals("file") || (kind.equals("sticker") && f != null)) {
            if (f == null || !(f.opt("id") instanceof String) || !(f.opt("size") instanceof Number)) return null;
            String name = new File(f.optString("name", "file").replace('\\', '/')).getName();
            JSONObject of = new JSONObject();
            put(of, "id", cut(f.optString("id"), 40));
            put(of, "name", name.isEmpty() ? "file" : cut(name, 200));
            put(of, "size", Math.max(0, f.optLong("size")));
            put(out, "file", of);
        }
        if (m.optDouble("voice", 0) != 0) put(out, "voice", Math.round(m.optDouble("voice") * 10) / 10.0);
        if (m.optBoolean("once")) put(out, "once", true);
        if (kind.equals("sticker")) put(out, "sticker", cut(m.optString("sticker"), 40));
        String pub = pubOf(gid, out.optString("from"));
        if (pub != null) {
            if (!rsaVerify(pub, sigPayload(gid, out), m.optString("sig"))) return null;   // forged or altered
            put(out, "sig", m.optString("sig"));
        } else {
            put(out, "unverified", true);
        }
        return out;
    }

    // ================================================================= state helpers
    byte[] key(String gid) {
        JSONObject g = groups.get(gid);
        return g == null || g.optString("key").isEmpty() ? null : unhex(g.optString("key"));
    }

    boolean isOwner(String gid) {
        JSONObject g = groups.get(gid);
        return g != null && me.equals(g.optString("owner"));
    }

    boolean canPost(String gid) {
        JSONObject g = groups.get(gid);
        return g != null && !g.optBoolean("removed") && (!g.optBoolean("owner_only") || me.equals(g.optString("owner")));
    }

    boolean active() {
        for (JSONObject g : groups.values()) if (!g.optBoolean("removed")) return true;
        return joinActive() || (profile.optBoolean("setup") && profile.optBoolean("visible"))
                || contacts.optJSONObject("outgoing").length() > 0 || contacts.optJSONObject("friends").length() > 0
                || fcodeActive();
    }

    boolean isOnline(String did) {
        JSONObject o = online.get(did);
        return o != null && now() - o.optDouble("seen") < 12;
    }

    List<String> onlineMembers(String gid) {
        List<String> out = new ArrayList<>();
        JSONObject g = groups.get(gid);
        if (g == null || g.optJSONObject("members") == null) return out;
        for (Iterator<String> it = g.optJSONObject("members").keys(); it.hasNext(); ) {
            String d = it.next();
            if (!d.equals(me) && isOnline(d)) out.add(d);
        }
        return out;
    }

    File filesDir(String gid) {
        JSONObject g = groups.get(gid);
        String name = g == null ? "Group" : g.optString("name", "Group");
        StringBuilder s = new StringBuilder();
        for (char c : name.toCharArray()) s.append(Character.isLetterOrDigit(c) || " -_.()".indexOf(c) >= 0 ? c : '_');
        String n = s.toString().trim();
        return new File(new File(downloads, "Arckad-D Chat"), n.isEmpty() ? "Group" : n);
    }

    JSONObject metaForMembers(JSONObject g) {
        JSONObject o = new JSONObject();
        for (String k : new String[]{"id", "name", "owner", "key", "version", "owner_only", "members", "created", "past"})
            if (g.has(k)) put(o, k, g.opt(k));
        return o;
    }

    void system(String gid, String text, boolean share) {
        boolean shared = share && isOwner(gid);
        JSONObject m = msg("system");
        put(m, "text", text);
        if (!shared) put(m, "local", true);
        else sign(gid, m);
        if (append(gid, m)) {
            ui.changed(gid);
            if (shared) deliver(gid, m);
        }
    }

    JSONObject msg(String kind) {
        JSONObject m = new JSONObject();
        put(m, "id", token(8));
        put(m, "from", me);
        put(m, "name", myName());
        put(m, "ts", now());
        put(m, "kind", kind);
        put(m, "text", "");
        return m;
    }

    // ================================================================= groups
    String createGroup(String name) {
        String gid = token(8);
        JSONObject g = new JSONObject();
        put(g, "id", gid);
        put(g, "name", cut(name, 60));
        put(g, "owner", me);
        put(g, "key", hex(random(32)));
        put(g, "version", 1);
        put(g, "owner_only", false);
        put(g, "created", now());
        put(g, "pair_keys", new JSONObject());
        put(g, "files", new JSONObject());
        JSONObject mine = new JSONObject();
        put(mine, "name", myName());
        put(mine, "os", osName);
        put(mine, "role", "owner");
        put(mine, "joined", now());
        put(mine, "pub", myPub());
        put(g, "members", new Obj().putOpt(me, mine));
        groups.put(gid, g);
        msgs.put(gid, Collections.synchronizedList(new ArrayList<>()));
        ids.put(gid, Collections.synchronizedSet(new HashSet<>()));
        save();
        system(gid, myName() + " created the group “" + name + "”", true);
        start();
        return gid;
    }

    void setOwnerOnly(String gid, boolean on) {
        JSONObject g = groups.get(gid);
        put(g, "owner_only", on);
        put(g, "version", g.optInt("version", 1) + 1);
        save();
        system(gid, on ? "Only the owner can post now" : "Everyone can post again", true);
        pushMeta(gid);
    }

    void renameGroup(String gid, String name) {
        JSONObject g = groups.get(gid);
        put(g, "name", cut(name, 60));
        put(g, "version", g.optInt("version", 1) + 1);
        save();
        system(gid, "Group renamed to “" + name + "”", true);
        pushMeta(gid);
    }

    void removeMember(String gid, String did) {
        JSONObject g = groups.get(gid);
        JSONObject m = (JSONObject) g.optJSONObject("members").remove(did);
        if (m == null) return;
        Obj.put(past(g), did, new Obj().putOpt("name", m.optString("name")).putOpt("pub", m.opt("pub")));
        Object old = g.optJSONObject("pair_keys") == null ? null : g.optJSONObject("pair_keys").remove(did);
        put(g, "key", hex(random(32)));
        put(g, "version", g.optInt("version", 1) + 1);
        save();
        system(gid, m.optString("name") + " was removed from the group", true);
        if (old != null) {
            final byte[] pk = unhex(old.toString());
            bg(() -> {
                try {
                    request(gid, did, "POST", "/c/meta", new Obj().putOpt("id", gid).putOpt("removed", true), pk, 6000);
                } catch (Exception ignored) {
                }
            });
        }
        pushMeta(gid);
    }

    private JSONObject past(JSONObject g) {
        if (g.optJSONObject("past") == null) put(g, "past", new JSONObject());
        return g.optJSONObject("past");
    }

    void leaveGroup(String gid) {
        JSONObject g = groups.get(gid);
        if (g == null) return;
        if ("direct".equals(g.optString("kind"))) {
            removeFriend(g.optString("peer"));
            return;
        }
        if (isOwner(gid)) {
            JSONObject pk = g.optJSONObject("pair_keys");
            if (pk != null) for (Iterator<String> it = pk.keys(); it.hasNext(); ) {
                String did = it.next();
                byte[] k = unhex(pk.optString(did));
                bg(() -> {
                    try {
                        request(gid, did, "POST", "/c/meta", new Obj().putOpt("id", gid).putOpt("removed", true), k, 6000);
                    } catch (Exception ignored) {
                    }
                });
            }
        } else if (!g.optBoolean("removed")) {
            String owner = g.optString("owner");
            bg(() -> {
                try {
                    request(gid, owner, "POST", "/c/leave", new JSONObject(), null, 6000);
                } catch (Exception ignored) {
                }
            });
        }
        sleep(300);
        synchronized (lock) {
            groups.remove(gid);
            msgs.remove(gid);
            ids.remove(gid);
            save();
            new File(dir, gid + ".jsonl").delete();
        }
        ui.changed(null);
    }

    void pushMeta(String gid) {
        JSONObject g = groups.get(gid);
        if (g == null || !isOwner(gid)) return;
        JSONObject meta = metaForMembers(g);
        JSONObject pk = g.optJSONObject("pair_keys");
        bg(() -> {
            if (pk != null) for (Iterator<String> it = pk.keys(); it.hasNext(); ) {
                String did = it.next();
                if (!g.optJSONObject("members").has(did)) continue;
                try {
                    request(gid, did, "POST", "/c/meta", meta, unhex(pk.optString(did)), 6000);
                } catch (Exception ignored) {
                }
            }
        });
        ui.changed(gid);
    }

    void applyMeta(String gid, JSONObject meta) {
        JSONObject g = groups.get(gid);
        if (g == null) return;
        JSONObject members = meta.optJSONObject("members");
        if (meta.optBoolean("removed") || (members != null && !members.has(me))) {
            if (!g.optBoolean("removed")) {
                put(g, "removed", true);
                put(g, "key", "");
                save();
                system(gid, "You were removed from this group (or it was deleted). The history stays here.", false);
            }
            return;
        }
        if (meta.optInt("version", 0) <= g.optInt("version", 0)) return;
        for (String k : new String[]{"name", "owner_only", "members", "key", "version", "past"})
            if (meta.has(k)) put(g, k, meta.opt(k));
        save();
        tagStamp = "";
        ui.changed(gid);
    }

    // ---------- join codes (owner shows; others type)
    String newJoinCode(String gid) {
        start();
        join = new JSONObject();
        put(join, "gid", gid);
        put(join, "code", String.format(java.util.Locale.ROOT, "%06d", RNG.nextInt(1_000_000)));
        put(join, "until", now() + 600);
        put(join, "tries", 0);
        put(join, "pending", new JSONObject());
        lastBeacon = 0;
        return join.optString("code");
    }

    boolean joinActive() {
        return join != null && now() < join.optDouble("until");
    }

    JSONObject joinInfo() {
        return joinActive() ? join : null;
    }

    void stopJoin() {
        join = null;
    }

    private JSONObject joinStart(JSONObject req, String ip) throws Exception {
        if (!joinActive()) return new Obj().putOpt("ok", false).putOpt("reason", "no join code is shown on that device right now");
        String gpub = req.optString("pub");
        BigInteger x = dhSecret();
        BigInteger pub = dhPublic(x);
        byte[] shared = dhShared(gpub, x);
        byte[] key = sha256(utf8("arckad-chat-key|"), shared, fixed(new BigInteger(gpub, 16), 256), fixed(pub, 256));
        JSONObject st = new JSONObject();
        put(st, "key", hex(key));
        put(st, "name", cut(req.optString("name", "Unknown"), 40));
        put(st, "os", cut(req.optString("os"), 10));
        put(st, "ip", ip);
        put(st, "port", req.opt("port"));
        put(st, "pub", cut(req.optString("sigpub"), 1100));
        Obj.put(join.optJSONObject("pending"), cut(req.optString("id"), 40), st);
        JSONObject g = groups.get(join.optString("gid"));
        return new Obj().putOpt("ok", true).putOpt("pub", pub.toString(16)).putOpt("group", g.optString("name"))
                .putOpt("owner", myName()).putOpt("owner_id", me).putOpt("port", port);
    }

    private JSONObject joinConfirm(JSONObject req, String ip) throws Exception {
        String did = cut(req.optString("id"), 40);
        JSONObject j = join;
        JSONObject st = joinActive() ? j.optJSONObject("pending").optJSONObject(did) : null;
        if (st == null) return new Obj().putOpt("ok", false).putOpt("reason", "the join code has expired; ask for a new one");
        byte[] key = unhex(st.optString("key"));
        String code = j.optString("code");
        if (!same(hex(hm(key, "join-guest", code)), req.optString("proof"))) {
            put(j, "tries", j.optInt("tries") + 1);
            if (j.optInt("tries") >= 5) {
                join = null;
                ui.event("Too many wrong join codes: the code was cancelled.");
            }
            return new Obj().putOpt("ok", false).putOpt("reason", "wrong code");
        }
        String gid = j.optString("gid");
        JSONObject g = groups.get(gid);
        Ask ev = new Ask();
        ev.name = st.optString("name");
        ev.os = st.optString("os");
        ev.group = g.optString("name");
        ui.askJoin(ev);
        ev.done.await(120, TimeUnit.SECONDS);
        if (!ev.accepted) return new Obj().putOpt("ok", false).putOpt("reason", "the group owner declined");
        JSONObject mem = new JSONObject();
        put(mem, "name", st.optString("name"));
        put(mem, "os", st.optString("os"));
        put(mem, "role", "member");
        put(mem, "joined", now());
        if (!st.optString("pub").isEmpty()) put(mem, "pub", st.optString("pub"));
        Obj.put(g.optJSONObject("members"), did, mem);
        if (g.optJSONObject("pair_keys") == null) put(g, "pair_keys", new JSONObject());
        Obj.put(g.optJSONObject("pair_keys"), did, hex(key));
        put(g, "version", g.optInt("version", 1) + 1);
        online.put(did, new Obj().putOpt("ip", ip).putOpt("port", st.opt("port")).putOpt("seen", now()));
        save();
        tagStamp = "";
        system(gid, st.optString("name") + " joined the group", true);
        pushMeta(gid);
        JSONObject inner = new Obj().putOpt("meta", metaForMembers(g)).putOpt("proof", hex(hm(key, "join-owner", code)));
        j.optJSONObject("pending").remove(did);
        return new Obj().putOpt("ok", true)
                .putOpt("sealed", b64(seal(key, utf8(inner.toString()))));
    }

    /** Background thread. Returns null when joined, or why not. */
    String joinWithCode(String code, String host) {
        start();
        String[] where = null;
        if (host != null && !host.isEmpty()) {
            where = reachable(host);
            if (where == null) return "Couldn't reach " + host + ".";
        } else {
            String want = sha256hex("arckad-chat-code|" + code).substring(0, 20);
            long end = System.currentTimeMillis() + 8000;
            while (System.currentTimeMillis() < end && where == null) {
                where = seenAddress(want);
                if (where == null) sleep(200);
            }
            if (where == null) return "No group showing that join code was found. Check the code and that the owner "
                    + "shows it right now. On another network, type the owner's IP address.";
        }
        try {
            BigInteger x = dhSecret();
            BigInteger pub = dhPublic(x);
            JSONObject r1 = postJson(where, "/cj/start", new Obj().putOpt("id", me).putOpt("name", myName())
                    .putOpt("os", osName).putOpt("pub", pub.toString(16)).putOpt("port", port).putOpt("sigpub", myPub()), 150_000);
            if (!r1.optBoolean("ok")) return r1.optString("reason", "refused");
            byte[] shared = dhShared(r1.optString("pub"), x);
            byte[] key = sha256(utf8("arckad-chat-key|"), shared, fixed(pub, 256), fixed(new BigInteger(r1.optString("pub"), 16), 256));
            JSONObject r2 = postJson(where, "/cj/confirm", new Obj().putOpt("id", me)
                    .putOpt("proof", hex(hm(key, "join-guest", code))), 150_000);
            if (!r2.optBoolean("ok")) return r2.optString("reason", "not approved");
            JSONObject data = new JSONObject(new String(unseal(key, unb64(r2.optString("sealed"))), StandardCharsets.UTF_8));
            if (!same(hex(hm(key, "join-owner", code)), data.optString("proof"))) return "the owner's device couldn't prove it knows the code";
            JSONObject meta = data.optJSONObject("meta");
            String gid = meta.optString("id");
            synchronized (lock) {
                JSONObject g = new JSONObject(meta.toString());
                put(g, "owner_key", hex(key));
                put(g, "files", new JSONObject());
                groups.put(gid, g);
                msgs.putIfAbsent(gid, Collections.synchronizedList(new ArrayList<>()));
                ids.putIfAbsent(gid, Collections.synchronizedSet(new HashSet<>()));
                save();
            }
            online.put(meta.optString("owner"), new Obj().putOpt("ip", where[0])
                    .putOpt("port", r1.optInt("port", Integer.parseInt(where[1]))).putOpt("seen", now()));
            tagStamp = "";
            bg(() -> syncWith(gid, meta.optString("owner")));
            ui.changed(gid);
            return null;
        } catch (Exception e) {
            return "connection problem (" + e.getMessage() + ")";
        }
    }

    private String[] seenAddress(String hash) {
        double[] t = codeSeen.get(hash);
        String[] a = codeAddr.get(hash);
        return t != null && a != null && now() - t[0] < 10 ? a : null;
    }

    private String[] reachable(String host) {
        for (int p : TCP_PORTS) {
            if (p == 0) continue;
            try (Socket s = new Socket()) {
                s.connect(new InetSocketAddress(host, p), 2000);
                return new String[]{InetAddress.getByName(host).getHostAddress(), String.valueOf(p)};
            } catch (IOException ignored) {
            }
        }
        return null;
    }

    // ================================================================= people and friends
    void sawPerson(JSONObject who, String ip, int port) {
        String pid = cut(who.optString("id"), 40);
        String name = cut(who.optString("name", "Someone"), 40), ph = cut(who.optString("ph"), 16);
        JSONObject old = people.get(pid);
        JSONObject p = new JSONObject();
        put(p, "name", name);
        put(p, "ip", ip);
        put(p, "port", port);
        put(p, "ph", ph);
        put(p, "os", cut(who.optString("os"), 10));
        put(p, "seen", now());
        put(p, "hidden", who.optBoolean("hidden"));
        people.put(pid, p);
        JSONObject f = friends().optJSONObject(pid);
        if (f != null && (!ip.equals(f.optString("ip")) || f.optInt("port") != port)) {
            put(f, "ip", ip);
            put(f, "port", port);
            saveContacts();
        }
        boolean changed = old == null || !old.optString("name").equals(name) || !old.optString("ph").equals(ph);
        if (f != null && (!f.optString("name").equals(name) || !f.optString("ph").equals(ph))) {
            put(f, "name", name);
            if (!f.optString("ph").equals(ph)) bg(() -> fetchPhoto(pid, ip, port, ph));
            for (JSONObject g : groups.values())
                if ("direct".equals(g.optString("kind")) && pid.equals(g.optString("peer"))) put(g, "name", name);
            saveContacts();
            save();
        } else if (f == null && !ph.isEmpty() && (old == null || !old.optString("ph").equals(ph))) {
            bg(() -> fetchPhoto(pid, ip, port, ph));
        }
        JSONObject out = f == null ? null : f.optJSONObject("pending_accept");
        if (out != null && now() - out.optDouble("tried", 0) > 10) {
            put(out, "tried", now());
            bg(() -> deliverAccept(pid));
        }
        if (changed) ui.people();
    }

    private void fetchPhoto(String pid, String ip, int port, String ph) {
        try {
            HttpURLConnection c = (HttpURLConnection) new URL("http://" + ip + ":" + port + "/f/photo").openConnection();
            c.setConnectTimeout(8000);
            c.setReadTimeout(8000);
            int code = c.getResponseCode();
            File folder = new File(dir, "avatars");
            folder.mkdirs();
            if (code == 200) {
                byte[] data;
                try (InputStream in = c.getInputStream()) {
                    data = readStream(in, 2_000_000);
                }
                if (data.length > 2 && (data[0] & 0xff) == 0xff && (data[1] & 0xff) == 0xd8) writeFile(new File(folder, pid + ".jpg"), data);
            } else if (code == 404) {
                new File(folder, pid + ".jpg").delete();
            }
            JSONObject f = friends().optJSONObject(pid);
            if (f != null) {
                put(f, "ph", ph);
                saveContacts();
            }
        } catch (Exception e) {
            return;
        }
        ui.people();
        ui.changed(null);
    }

    JSONObject friends() {
        return contacts.optJSONObject("friends");
    }

    JSONObject incoming() {
        return contacts.optJSONObject("incoming");
    }

    JSONObject outgoing() {
        return contacts.optJSONObject("outgoing");
    }

    List<String> peopleList() {
        List<String> out = new ArrayList<>();
        for (Map.Entry<String, JSONObject> e : people.entrySet())
            if (now() - e.getValue().optDouble("seen") < 20 && !e.getValue().optBoolean("hidden")) out.add(e.getKey());
        Collections.sort(out, (a, b) -> people.get(a).optString("name").compareToIgnoreCase(people.get(b).optString("name")));
        return out;
    }

    boolean personOnline(String pid) {
        JSONObject p = people.get(pid);
        return (p != null && now() - p.optDouble("seen") < 20) || isOnline(pid);
    }

    String relation(String pid) {
        if (friends().has(pid)) return "friend";
        if (incoming().has(pid)) return "incoming";
        if (outgoing().has(pid)) return "outgoing";
        return "none";
    }

    private String[] addressOf(String pid) {
        JSONObject p = people.get(pid);
        if (p == null || p.optString("ip").isEmpty()) p = online.get(pid);
        if (p == null || p.optString("ip").isEmpty()) p = friends().optJSONObject(pid);
        if (p == null || p.optString("ip").isEmpty() || p.optInt("port") == 0) return null;
        return new String[]{p.optString("ip"), String.valueOf(p.optInt("port"))};
    }

    private JSONObject call(String pid, String path, JSONObject obj) throws Exception {
        String[] a = addressOf(pid);
        if (a == null) throw new IOException("they're not on the network right now");
        return postJson(a, path, obj, 12_000);
    }

    private Object[] dhOffer(String to) {
        BigInteger x = dhSecret();
        String pub = dhPublic(x).toString(16);
        JSONObject o = new JSONObject();
        put(o, "id", me);
        put(o, "name", myName());
        put(o, "os", osName);
        put(o, "sigpub", myPub());
        put(o, "dh", pub);
        put(o, "dhsig", rsaSign(identity(), utf8("arckad-friend|" + me + "|" + to + "|" + pub)));
        put(o, "port", port);
        put(o, "ph", photoHash());
        return new Object[]{x, o};
    }

    static byte[] friendKey(BigInteger x, String theirHex, String mineHex) {
        byte[] shared = dhShared(theirHex, x);
        String a = mineHex.compareTo(theirHex) <= 0 ? mineHex : theirHex, b = a.equals(mineHex) ? theirHex : mineHex;
        return sha256(utf8("arckad-friend-key|"), shared, utf8(a), utf8(b));
    }

    String safetyCode(String pid) {
        JSONObject f = friends().optJSONObject(pid);
        String mine = myPub(), theirs = f == null ? "" : f.optString("sigpub");
        String a = mine.compareTo(theirs) <= 0 ? mine : theirs, b = a.equals(mine) ? theirs : mine;
        String digits = new BigInteger(sha256hex(a + "|" + b), 16).toString().substring(0, 30);
        StringBuilder s = new StringBuilder();
        for (int i = 0; i < 30; i += 5) s.append(i > 0 ? " " : "").append(digits, i, i + 5);
        return s.toString();
    }

    /** Background thread. Returns null when sent, or why not. */
    String sendRequest(String pid) {
        start();
        Object[] off = dhOffer(pid);
        JSONObject offer = (JSONObject) off[1];
        try {
            JSONObject r = call(pid, "/f/request", offer);
            if (!r.optBoolean("ok")) return r.optString("reason", "The request wasn't accepted.");
        } catch (Exception e) {
            return "Couldn't reach them (" + e.getMessage() + ").";
        }
        JSONObject p = people.get(pid);
        JSONObject o = new JSONObject();
        put(o, "name", p == null ? "?" : p.optString("name"));
        put(o, "x", ((BigInteger) off[0]).toString(16));
        put(o, "dh", offer.optString("dh"));
        put(o, "ts", now());
        Obj.put(outgoing(), pid, o);
        saveContacts();
        ui.people();
        return null;
    }

    void acceptRequest(String pid) {
        JSONObject req = (JSONObject) incoming().remove(pid);
        if (req == null) return;
        Object[] off = dhOffer(pid);
        JSONObject offer = (JSONObject) off[1];
        byte[] key = friendKey((BigInteger) off[0], req.optString("dh"), offer.optString("dh"));
        becomeFriends(pid, req.optString("name"), req.optString("os"), req.optString("sigpub"), key, req.optString("ph"));
        Obj.put(friends().optJSONObject(pid), "pending_accept", new Obj().putOpt("offer", offer).putOpt("tried", 0));
        saveContacts();
        bg(() -> deliverAccept(pid));
        ui.people();
    }

    private void deliverAccept(String pid) {
        JSONObject f = friends().optJSONObject(pid);
        if (f == null || f.optJSONObject("pending_accept") == null) return;
        try {
            JSONObject r = call(pid, "/f/accept", f.optJSONObject("pending_accept").optJSONObject("offer"));
            if (r.optBoolean("ok") || "already friends".equals(r.optString("reason"))) {
                f.remove("pending_accept");
                saveContacts();
                ui.people();
            }
        } catch (Exception ignored) {
        }
    }

    void declineRequest(String pid) {
        if (incoming().remove(pid) != null) {
            saveContacts();
            bg(() -> {
                try {
                    call(pid, "/f/decline", new Obj().putOpt("id", me));
                } catch (Exception ignored) {
                }
            });
        }
        ui.people();
    }

    void cancelRequest(String pid) {
        outgoing().remove(pid);
        saveContacts();
        bg(() -> {
            try {
                call(pid, "/f/cancel", new Obj().putOpt("id", me));
            } catch (Exception ignored) {
            }
        });
        ui.people();
    }

    String directGid(String pid) {
        String a = me.compareTo(pid) <= 0 ? me : pid, b = a.equals(me) ? pid : me;
        return "dm-" + sha256hex(a + "|" + b).substring(0, 14);
    }

    String becomeFriends(String pid, String name, String os, String sigpub, byte[] key, String ph) {
        JSONObject seen = people.get(pid);
        JSONObject f = new JSONObject();
        put(f, "name", name);
        put(f, "os", os);
        put(f, "sigpub", sigpub);
        put(f, "since", now());
        put(f, "ph", ph);
        if (seen != null) {
            put(f, "ip", seen.optString("ip"));
            put(f, "port", seen.optInt("port"));
        }
        Obj.put(friends(), pid, f);
        outgoing().remove(pid);
        incoming().remove(pid);
        String gid = directGid(pid);
        synchronized (lock) {
            JSONObject g = groups.get(gid);
            if (g == null || g.optBoolean("removed")) {
                g = new JSONObject();
                put(g, "id", gid);
                put(g, "kind", "direct");
                put(g, "peer", pid);
                put(g, "name", name);
                put(g, "owner", JSONObject.NULL);
                put(g, "key", hex(key));
                put(g, "version", 1);
                put(g, "owner_only", false);
                put(g, "created", now());
                put(g, "files", new JSONObject());
                JSONObject mine = new Obj().putOpt("name", myName()).putOpt("pub", myPub()).putOpt("os", osName).putOpt("role", "member");
                JSONObject theirs = new Obj().putOpt("name", name).putOpt("pub", sigpub).putOpt("os", os).putOpt("role", "member");
                put(g, "members", new Obj().putOpt(me, mine).putOpt(pid, theirs));
                groups.put(gid, g);
                msgs.putIfAbsent(gid, Collections.synchronizedList(new ArrayList<>()));
                ids.putIfAbsent(gid, Collections.synchronizedSet(new HashSet<>()));
            } else {
                put(g, "key", hex(key));
            }
        }
        save();
        saveContacts();
        tagStamp = "";
        start();
        if (seen != null && !seen.optString("ph").isEmpty())
            bg(() -> fetchPhoto(pid, seen.optString("ip"), seen.optInt("port"), seen.optString("ph")));
        ui.changed(gid);
        return gid;
    }

    void removeFriend(String pid) {
        String gid = directGid(pid);
        bg(() -> {
            JSONObject g = groups.get(gid);
            if (g != null && !g.optString("key").isEmpty()) {
                try {
                    request(gid, pid, "POST", "/c/unfriend", new JSONObject(), null, 6000);
                } catch (Exception ignored) {
                }
            }
            forgetFriend(pid);
        });
    }

    void forgetFriend(String pid) {
        friends().remove(pid);
        JSONObject g = groups.get(directGid(pid));
        if (g != null) {
            put(g, "removed", true);
            put(g, "key", "");
            save();
        }
        saveContacts();
        tagStamp = "";
        ui.people();
        ui.changed(null);
    }

    private JSONObject friendPost(String path, JSONObject req, String ip) throws Exception {
        String pid = cut(req.optString("id"), 40);
        if (pid.isEmpty() || pid.equals(me)) return err("bad request");
        if (path.equals("/f/request")) {
            JSONObject f = friends().optJSONObject(pid);
            if (f != null && f.optJSONObject("pending_accept") == null) return err("You're already friends.");
            String dh = req.optString("dh"), sigpub = cut(req.optString("sigpub"), 1100);
            if (!rsaVerify(sigpub, utf8("arckad-friend|" + pid + "|" + me + "|" + dh), req.optString("dhsig"))) return err("bad signature");
            JSONObject out = outgoing().optJSONObject(pid);
            if (out != null) {                                   // both asked each other: a yes from both
                byte[] key = friendKey(new BigInteger(out.optString("x"), 16), dh, out.optString("dh"));
                becomeFriends(pid, cut(req.optString("name", "?"), 40), cut(req.optString("os"), 10), sigpub, key, cut(req.optString("ph"), 16));
                return new Obj().putOpt("ok", true);
            }
            JSONObject inc = new JSONObject();
            put(inc, "name", cut(req.optString("name", "?"), 40));
            put(inc, "os", cut(req.optString("os"), 10));
            put(inc, "sigpub", sigpub);
            put(inc, "dh", dh);
            put(inc, "ph", cut(req.optString("ph"), 16));
            put(inc, "ts", now());
            Obj.put(incoming(), pid, inc);
            saveContacts();
            if (!people.containsKey(pid)) {
                JSONObject p = new Obj().putOpt("name", inc.optString("name")).putOpt("ip", ip)
                        .putOpt("port", req.opt("port")).putOpt("ph", inc.optString("ph")).putOpt("os", "").putOpt("seen", now());
                people.put(pid, p);
            }
            ui.friendRequest(pid);
            return new Obj().putOpt("ok", true);
        }
        if (path.equals("/f/accept")) {
            JSONObject out = outgoing().optJSONObject(pid);
            if (out == null) return err(friends().has(pid) ? "already friends" : "no request");
            String dh = req.optString("dh"), sigpub = cut(req.optString("sigpub"), 1100);
            if (!rsaVerify(sigpub, utf8("arckad-friend|" + pid + "|" + me + "|" + dh), req.optString("dhsig"))) return err("bad signature");
            byte[] key = friendKey(new BigInteger(out.optString("x"), 16), dh, out.optString("dh"));
            becomeFriends(pid, cut(req.optString("name", out.optString("name")), 40), cut(req.optString("os"), 10), sigpub, key, cut(req.optString("ph"), 16));
            ui.event("🤝 " + req.optString("name", "Someone") + " accepted your friend request");
            return new Obj().putOpt("ok", true);
        }
        if (path.equals("/f/decline")) {
            if (outgoing().remove(pid) != null) {
                saveContacts();
                ui.people();
            }
            return new Obj().putOpt("ok", true);
        }
        if (path.equals("/f/cancel")) {
            if (incoming().remove(pid) != null) {
                saveContacts();
                ui.people();
            }
            return new Obj().putOpt("ok", true);
        }
        return err("unknown");
    }

    // ---------- friend codes (any network, other VLANs too)
    static String normCode(String s) {
        StringBuilder b = new StringBuilder();
        for (char c : s.toUpperCase(java.util.Locale.ROOT).toCharArray()) if (Character.isLetterOrDigit(c)) b.append(c);
        return b.length() > 6 ? b.substring(0, 6) : b.toString();
    }

    String newFriendCode() {
        start();
        StringBuilder c = new StringBuilder();
        for (int i = 0; i < 6; i++) c.append(CODE_ALPHABET.charAt(RNG.nextInt(CODE_ALPHABET.length())));
        fcode = new JSONObject();
        put(fcode, "code", c.toString());
        put(fcode, "until", now() + 600);
        put(fcode, "tries", 0);
        put(fcode, "pending", new JSONObject());
        lastBeacon = 0;
        return c.toString();
    }

    boolean fcodeActive() {
        return fcode != null && now() < fcode.optDouble("until");
    }

    JSONObject fcodeInfo() {
        return fcodeActive() ? fcode : null;
    }

    void stopFriendCode() {
        fcode = null;
    }

    /** Background thread. Returns null on success (friends now), or why not. */
    String addByCode(String code, String host) {
        code = normCode(code);
        if (code.length() != 6) return "A friend code has 6 letters and numbers.";
        start();
        String[] where;
        if (host != null && !host.isEmpty()) {
            where = reachable(host);
            if (where == null) return "Couldn't reach " + host + ". Check the address, that Arckad-D is open there, "
                    + "and that both firewalls allow Arckad-D.";
        } else {
            String want = sha256hex("arckad-friend-code|" + code).substring(0, 20);
            where = null;
            long end = System.currentTimeMillis() + 8000;
            while (System.currentTimeMillis() < end && where == null) {
                where = seenAddress(want);
                if (where == null) sleep(200);
            }
            if (where == null) return "Nobody showing that code was found on this network. If your friend is on "
                    + "another network or VLAN, also type their IP address (it's shown under their code).";
        }
        try {
            Object[] off = dhOffer("code");
            JSONObject offer = (JSONObject) off[1];
            JSONObject r1 = postJson(where, "/f/codestart", offer, 20_000);
            if (!r1.optBoolean("ok")) return r1.optString("reason", "refused");
            String pid = cut(r1.optString("id"), 40), sigpub = cut(r1.optString("sigpub"), 1100);
            if (!rsaVerify(sigpub, utf8("arckad-friend|" + pid + "|code|" + r1.optString("dh")), r1.optString("dhsig")))
                return "the other device's key didn't check out";
            byte[] key = friendKey((BigInteger) off[0], r1.optString("dh"), offer.optString("dh"));
            JSONObject r2 = postJson(where, "/f/codeconfirm", new Obj().putOpt("id", me)
                    .putOpt("proof", hex(hm(key, "fcode-guest", code))), 20_000);
            if (!r2.optBoolean("ok")) return r2.optString("reason", "not confirmed");
            if (!same(hex(hm(key, "fcode-host", code)), r2.optString("proof"))) return "the other device couldn't prove it knows the code";
            JSONObject p = new Obj().putOpt("name", cut(r1.optString("name", "?"), 40)).putOpt("ip", where[0])
                    .putOpt("port", r1.optInt("port", Integer.parseInt(where[1]))).putOpt("ph", cut(r1.optString("ph"), 16))
                    .putOpt("os", cut(r1.optString("os"), 10)).putOpt("seen", now()).putOpt("hidden", true);
            people.put(pid, p);
            becomeFriends(pid, p.optString("name"), p.optString("os"), sigpub, key, p.optString("ph"));
            return null;
        } catch (Exception e) {
            return "connection problem (" + e.getMessage() + ")";
        }
    }

    private JSONObject codePost(String path, JSONObject req, String ip) throws Exception {
        if (path.equals("/f/codestart")) {
            if (!fcodeActive()) return err("That code isn't shown any more. Ask for a new one.");
            String pid = cut(req.optString("id"), 40), dh = req.optString("dh"), sigpub = cut(req.optString("sigpub"), 1100);
            if (!rsaVerify(sigpub, utf8("arckad-friend|" + pid + "|code|" + dh), req.optString("dhsig"))) return err("bad signature");
            Object[] off = dhOffer("code");
            JSONObject offer = (JSONObject) off[1];
            byte[] key = friendKey((BigInteger) off[0], dh, offer.optString("dh"));
            Obj.put(fcode.optJSONObject("pending"), pid, new Obj().putOpt("key", hex(key)).putOpt("req", req).putOpt("ip", ip));
            return new JSONObject(offer.toString()).putOpt("ok", true);
        }
        if (path.equals("/f/codeconfirm")) {
            String pid = cut(req.optString("id"), 40);
            JSONObject st = fcodeActive() ? fcode.optJSONObject("pending").optJSONObject(pid) : null;
            if (st == null) return err("That code isn't shown any more. Ask for a new one.");
            String code = fcode.optString("code");
            byte[] key = unhex(st.optString("key"));
            if (!same(hex(hm(key, "fcode-guest", code)), req.optString("proof"))) {
                put(fcode, "tries", fcode.optInt("tries") + 1);
                if (fcode.optInt("tries") >= 5) {
                    fcode = null;
                    ui.event("Too many wrong friend codes: the code was cancelled.");
                }
                return err("Wrong code.");
            }
            JSONObject r = st.optJSONObject("req");
            people.put(pid, new Obj().putOpt("name", cut(r.optString("name", "?"), 40)).putOpt("ip", st.optString("ip"))
                    .putOpt("port", r.opt("port")).putOpt("ph", cut(r.optString("ph"), 16)).putOpt("os", cut(r.optString("os"), 10))
                    .putOpt("seen", now()).putOpt("hidden", true));
            becomeFriends(pid, cut(r.optString("name", "?"), 40), cut(r.optString("os"), 10), cut(r.optString("sigpub"), 1100), key, cut(r.optString("ph"), 16));
            fcode = null;
            ui.event("🤝 You're now friends with " + r.optString("name", "someone"));
            return new Obj().putOpt("ok", true).putOpt("proof", hex(hm(key, "fcode-host", code)));
        }
        return err("unknown");
    }

    // ================================================================= talking to other devices
    private JSONObject postJson(String[] where, String path, JSONObject obj, int timeout) throws Exception {
        HttpURLConnection c = (HttpURLConnection) new URL("http://" + where[0] + ":" + where[1] + path).openConnection();
        c.setConnectTimeout(5000);
        c.setReadTimeout(timeout);
        c.setDoOutput(true);
        c.setRequestMethod("POST");
        c.setRequestProperty("Content-Type", "application/json");
        byte[] body = utf8(obj.toString());
        c.setFixedLengthStreamingMode(body.length);
        try (OutputStream o = c.getOutputStream()) {
            o.write(body);
        }
        int code = c.getResponseCode();
        byte[] data;
        try (InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream()) {
            data = in == null ? new byte[0] : readStream(in, 5_000_000);
        }
        return data.length == 0 ? new JSONObject() : new JSONObject(new String(data, StandardCharsets.UTF_8));
    }

    private String[] memberAddress(String did) {
        JSONObject o = online.get(did);
        if ((o == null || o.optString("ip").isEmpty() || o.optInt("port") == 0) && friends().has(did)) o = friends().optJSONObject(did);
        if (o == null || o.optString("ip").isEmpty() || o.optInt("port") == 0) return null;
        return new String[]{o.optString("ip"), String.valueOf(o.optInt("port"))};
    }

    private HttpURLConnection open(String gid, String did, String method, String path, byte[] key, int timeout, int bodyLen) throws IOException {
        String[] a = memberAddress(did);
        if (a == null) throw new IOException("not online");
        HttpURLConnection c = (HttpURLConnection) new URL("http://" + a[0] + ":" + a[1] + path).openConnection();
        c.setConnectTimeout(5000);
        c.setReadTimeout(timeout);
        c.setRequestMethod(method);
        long ts = System.currentTimeMillis() / 1000;
        c.setRequestProperty("X-Chat-Group", gid);
        c.setRequestProperty("X-Chat-From", me);
        c.setRequestProperty("X-Chat-Time", String.valueOf(ts));
        c.setRequestProperty("X-Chat-Sig", hex(hm(key, method, path, ts, me, gid)));
        if (bodyLen >= 0) {
            c.setDoOutput(true);
            c.setFixedLengthStreamingMode(bodyLen);
        }
        return c;
    }

    /** A signed, encrypted request to another member. pairKey: owner ↔ member private key (else the group key). */
    JSONObject request(String gid, String did, String method, String path, JSONObject obj, byte[] pairKey, int timeout) throws Exception {
        byte[] key = pairKey != null ? pairKey : key(gid);
        if (key == null) throw new IOException("no key");
        byte[] body = obj == null ? new byte[0] : seal(key, utf8(obj.toString()));
        HttpURLConnection c = open(gid, did, method, path, key, timeout, body.length);
        if (pairKey != null) c.setRequestProperty("X-Chat-Pair", "1");
        if (body.length > 0 || method.equals("POST")) try (OutputStream o = c.getOutputStream()) {
            o.write(body);
        }
        int code = c.getResponseCode();
        byte[] data;
        try (InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream()) {
            data = in == null ? new byte[0] : readStream(in, 20_000_000);
        }
        if (code != 200) {
            String reason = null;
            try {
                reason = new JSONObject(new String(unseal(key, data), StandardCharsets.UTF_8)).optString("reason", null);
            } catch (Exception e) {
                try {
                    reason = new JSONObject(new String(data, StandardCharsets.UTF_8)).optString("reason", null);
                } catch (Exception ignored) {
                }
            }
            throw new SecurityException(reason != null ? reason : "refused (" + code + ")");
        }
        return data.length == 0 ? new JSONObject() : new JSONObject(new String(unseal(key, data), StandardCharsets.UTF_8));
    }

    void pullMeta(String gid) {
        JSONObject g = groups.get(gid);
        if (g == null || g.optString("owner_key").isEmpty()) return;
        try {
            applyMeta(gid, request(gid, g.optString("owner"), "POST", "/c/getmeta", new JSONObject(), unhex(g.optString("owner_key")), 8000));
        } catch (Exception ignored) {
        }
    }

    void ensureMyPub(String gid) {
        JSONObject g = groups.get(gid);
        if (g == null || g.optBoolean("removed")) return;
        JSONObject mine = g.optJSONObject("members") == null ? null : g.optJSONObject("members").optJSONObject(me);
        if (mine == null || myPub().equals(mine.optString("pub"))) return;
        if (isOwner(gid)) {
            put(mine, "pub", myPub());
            put(g, "version", g.optInt("version", 1) + 1);
            save();
            pushMeta(gid);
        } else if (!g.optString("owner_key").isEmpty() && isOnline(g.optString("owner"))) {
            try {
                request(gid, g.optString("owner"), "POST", "/c/setpub", new Obj().putOpt("pub", myPub()), unhex(g.optString("owner_key")), 8000);
            } catch (Exception ignored) {
            }
        }
    }

    void syncWith(String gid, String did) {
        JSONObject g = groups.get(gid);
        if (g == null || g.optBoolean("removed")) return;
        double cutoff = now() - HISTORY_DAYS * 86400;
        JSONArray have = new JSONArray();
        for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>())))
            if (m.optDouble("ts", 0) > cutoff && !m.optBoolean("local")) have.put(m.optString("id"));
        JSONObject reply;
        try {
            reply = request(gid, did, "POST", "/c/sync", new Obj().putOpt("ids", have), null, 30_000);
        } catch (Exception e) {
            return;
        }
        int added = 0;
        JSONArray list = reply.optJSONArray("msgs");
        if (list != null) for (int i = 0; i < Math.min(list.length(), 2000); i++) {
            JSONObject m = clean(list.opt(i), gid);
            if (m != null && append(gid, m)) {
                if ("system".equals(m.optString("kind")) || "delete".equals(m.optString("kind"))) continue;
                added++;
                queueReceipt(gid, m.optString("from"), m.optString("id"), false);
                if (m.optJSONObject("file") != null) maybeDownload(gid, m);
            }
        }
        if (added > 0) {
            unread.merge(gid, added, Integer::sum);
            ui.changed(gid);
        }
    }

    // ================================================================= receipts (✓✓ delivered, blue ✓✓ read)
    private final Map<String, Map<String, Set<String>[]>> receiptsOut = new ConcurrentHashMap<>();
    volatile boolean sendReadReceipts = true;

    @SuppressWarnings("unchecked")
    void queueReceipt(String gid, String sender, String mid, boolean read) {
        if (sender == null || sender.isEmpty() || sender.equals(me) || (read && !sendReadReceipts)) return;
        Set<String>[] box = receiptsOut.computeIfAbsent(sender, k -> new ConcurrentHashMap<>())
                .computeIfAbsent(gid, k -> new Set[]{Collections.synchronizedSet(new HashSet<>()), Collections.synchronizedSet(new HashSet<>())});
        box[read ? 1 : 0].add(mid);
        bg(() -> {
            sleep(800);
            flushReceipts(sender);
        });
    }

    void flushReceipts(String sender) {
        Map<String, Set<String>[]> m = receiptsOut.get(sender);
        if (m == null) return;
        for (Map.Entry<String, Set<String>[]> e : m.entrySet()) {
            Set<String>[] box = e.getValue();
            List<String> d = new ArrayList<>(box[0]), r = new ArrayList<>(box[1]);
            if (d.isEmpty() && r.isEmpty()) continue;
            try {
                request(e.getKey(), sender, "POST", "/c/receipt", new Obj().putOpt("d", new JSONArray(d)).putOpt("r", new JSONArray(r)), null, 6000);
                box[0].removeAll(d);
                box[1].removeAll(r);
            } catch (Exception ignored) {
            }
        }
    }

    /** The conversation is on screen: its messages are read. */
    void markRead(String gid) {
        unread.put(gid, 0);
        boolean changed = false;
        for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>()))) {
            String k = m.optString("kind");
            if (!me.equals(m.optString("from")) && !k.equals("system") && !k.equals("delete") && !m.optBoolean("r_sent") && !m.has("deleted")) {
                put(m, "r_sent", true);
                changed = true;
                queueReceipt(gid, m.optString("from"), m.optString("id"), true);
            }
        }
        if (changed) rewrite(gid);
    }

    private void gotReceipt(String gid, String did, JSONObject req) {
        Set<String> d = new HashSet<>(), r = new HashSet<>();
        JSONArray a = req.optJSONArray("d"), b = req.optJSONArray("r");
        if (a != null) for (int i = 0; i < a.length(); i++) d.add(a.optString(i));
        if (b != null) for (int i = 0; i < b.length(); i++) r.add(b.optString(i));
        boolean changed = false;
        for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>()))) {
            if (!me.equals(m.optString("from"))) continue;
            String id = m.optString("id");
            if (d.contains(id) || r.contains(id)) changed |= addTo(m, "delivered", did);
            if (r.contains(id)) changed |= addTo(m, "read", did);
        }
        if (changed) {
            rewrite(gid);
            ui.changed(gid);
        }
    }

    private static boolean addTo(JSONObject m, String field, String did) {
        JSONArray a = m.optJSONArray(field);
        if (a == null) {
            a = new JSONArray();
            put(m, field, a);
        }
        for (int i = 0; i < a.length(); i++) if (did.equals(a.optString(i))) return false;
        a.put(did);
        return true;
    }

    void rewrite(String gid) {
        synchronized (lock) {
            StringBuilder b = new StringBuilder();
            for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>()))) b.append(m.toString()).append('\n');
            writeFile(new File(dir, gid + ".jsonl"), utf8(b.toString()));
        }
    }

    // ================================================================= deleting
    void deleteForMe(String gid, Set<String> ids) {
        for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>())))
            if (ids.contains(m.optString("id"))) {
                for (String k : new String[]{"text", "file", "sticker", "voice", "sig"}) m.remove(k);
                put(m, "deleted", "me");
            }
        rewrite(gid);
        ui.changed(gid);
    }

    int deleteForEveryone(String gid, Set<String> ids) {
        List<String> mine = new ArrayList<>();
        for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>())))
            if (ids.contains(m.optString("id")) && me.equals(m.optString("from")) && !"system".equals(m.optString("kind"))
                    && !"everyone".equals(m.optString("deleted"))) mine.add(m.optString("id"));
        if (mine.isEmpty() || !canPost(gid)) return 0;
        JSONObject m = msg("delete");
        StringBuilder joined = new StringBuilder();
        for (String id : mine) joined.append(joined.length() > 0 ? "," : "").append(id);
        put(m, "text", joined.toString());
        sign(gid, m);
        append(gid, m);
        deliver(gid, m);
        ui.changed(gid);
        return mine.size();
    }

    private void applyDelete(String gid, JSONObject dm) {
        Set<String> targets = new HashSet<>();
        for (String t : dm.optString("text").split(",")) if (!t.isEmpty()) targets.add(t);
        boolean changed = false;
        for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>()))) {
            if (!targets.contains(m.optString("id")) || !m.optString("from").equals(dm.optString("from"))
                    || "everyone".equals(m.optString("deleted"))) continue;
            JSONObject f = m.optJSONObject("file");
            if (f != null && me.equals(m.optString("from"))) {
                JSONObject g = groups.get(gid);
                if (g != null && g.optJSONObject("files") != null) g.optJSONObject("files").remove(f.optString("id"));
            }
            for (String k : new String[]{"text", "file", "sticker", "voice", "sig"}) m.remove(k);
            put(m, "deleted", "everyone");
            changed = true;
        }
        if (changed) rewrite(gid);
    }

    // ================================================================= sending
    void sendText(String gid, String text) {
        text = text.trim();
        if (text.isEmpty() || !canPost(gid)) return;
        JSONObject m = msg("text");
        put(m, "text", cut(text, 8000));
        sign(gid, m);
        append(gid, m);
        ui.changed(gid);
        deliver(gid, m);
    }

    int sendFiles(String gid, List<File> files) {
        if (!canPost(gid)) return 0;
        JSONObject g = groups.get(gid);
        if (g.optJSONObject("files") == null) put(g, "files", new JSONObject());
        int n = 0;
        for (File f : files) {
            if (!f.isFile()) continue;
            String fid = token(8);
            Obj.put(g.optJSONObject("files"), fid, f.getAbsolutePath());
            JSONObject m = msg("file");
            put(m, "file", new Obj().putOpt("id", fid).putOpt("name", f.getName()).putOpt("size", f.length()));
            sign(gid, m);
            append(gid, m);
            deliver(gid, m);
            n++;
        }
        save();
        ui.changed(gid);
        return n;
    }

    void sendSticker(String gid, String sid) {
        if (!canPost(gid)) return;
        JSONObject m = msg("sticker");
        put(m, "sticker", sid);
        sign(gid, m);
        append(gid, m);
        ui.changed(gid);
        deliver(gid, m);
    }

    void deliver(String gid, JSONObject m) {
        JSONObject g = groups.get(gid);
        Set<String> targets = new HashSet<>(onlineMembers(gid));
        if (g != null && "direct".equals(g.optString("kind")) && !g.optBoolean("removed")) targets.add(g.optString("peer"));
        bg(() -> {
            for (String did : targets) {
                try {
                    request(gid, did, "POST", "/c/msg", new Obj().putOpt("msg", m), null, 6000);
                    JSONObject o = online.get(did);
                    if (o != null) put(o, "seen", now());
                } catch (Exception ignored) {
                }
            }
        });
    }

    // ================================================================= attachments
    File localFile(String gid, String fid) {
        JSONObject g = groups.get(gid);
        String p = g == null || g.optJSONObject("files") == null ? "" : g.optJSONObject("files").optString(fid);
        File f = p.isEmpty() ? null : new File(p);
        return f != null && f.isFile() ? f : null;
    }

    void maybeDownload(String gid, JSONObject m) {
        JSONObject f = m.optJSONObject("file");
        if (f != null && f.optLong("size") <= AUTO_DOWNLOAD && localFile(gid, f.optString("id")) == null) download(gid, m);
    }

    void download(String gid, JSONObject m) {
        String fid = m.optJSONObject("file").optString("id");
        if (!downloading.add(fid)) return;
        ui.changed(gid);
        bg(() -> {
            try {
                List<String> sources = new ArrayList<>();
                sources.add(m.optString("from"));
                for (String d : onlineMembers(gid)) if (!sources.contains(d)) sources.add(d);
                for (String did : sources) if (fetchFile(gid, did, m)) return;
            } finally {
                downloading.remove(fid);
                ui.changed(gid);
            }
        });
    }

    private boolean fetchFile(String gid, String did, JSONObject m) {
        JSONObject f = m.optJSONObject("file");
        String fid = f.optString("id");
        long size = f.optLong("size");
        byte[] key = key(gid);
        if (key == null) return false;
        try {
            HttpURLConnection c = open(gid, did, "GET", "/c/file/" + fid, key, 60_000, -1);
            if (c.getResponseCode() != 200) return false;
            File folder = m.optBoolean("once") ? new File(dir, "once") : filesDir(gid);
            folder.mkdirs();
            File dest = Fs.unique(new File(folder, f.optString("name")));
            File tmp = new File(dest.getPath() + ".part");
            Stream cipher = new Stream(hm(key, "chatfile", fid));
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(hm(key, "chatfile-mac", fid), "HmacSHA256"));
            long left = size;
            byte[] buf = new byte[1 << 18];
            try (InputStream in = c.getInputStream(); FileOutputStream out = new FileOutputStream(tmp)) {
                while (left > 0) {
                    int n = in.read(buf, 0, (int) Math.min(buf.length, left));
                    if (n < 0) break;
                    mac.update(buf, 0, n);
                    out.write(cipher.apply(buf, 0, n));
                    left -= n;
                }
                byte[] tag = readStream(in, 32);
                if (left != 0 || !same(tag, mac.doFinal())) {
                    tmp.delete();
                    return false;
                }
            }
            if (!tmp.renameTo(dest)) return false;
            synchronized (lock) {
                JSONObject g = groups.get(gid);
                if (g.optJSONObject("files") == null) put(g, "files", new JSONObject());
                Obj.put(g.optJSONObject("files"), fid, dest.getAbsolutePath());
                save();
            }
            ui.fileSaved(dest);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    // ================================================================= presence: secret signals only members recognise
    JSONObject beacon() {
        JSONObject msg = new JSONObject();
        put(msg, "app", "arckad-pair");
        put(msg, "v", 1);
        put(msg, "port", port);
        put(msg, "tags", new JSONArray());
        long bucket = System.currentTimeMillis() / 30_000;
        JSONArray tags = new JSONArray();
        for (JSONObject g : groups.values())
            if (!g.optBoolean("removed") && !g.optString("key").isEmpty())
                tags.put(hex(hm(unhex(g.optString("key")), "member", me, bucket)).substring(0, 24));
        if (tags.length() > 0) put(msg, "ctags", tags);
        if (joinActive()) put(msg, "chatjoin", sha256hex("arckad-chat-code|" + join.optString("code")).substring(0, 20));
        if (fcodeActive()) put(msg, "fcode", sha256hex("arckad-friend-code|" + fcode.optString("code")).substring(0, 20));
        boolean anyone = friends().length() > 0 || outgoing().length() > 0;
        if ((profile.optBoolean("setup") && profile.optBoolean("visible")) || anyone) {
            JSONObject who = new Obj().putOpt("id", me).putOpt("name", cut(myName(), 40)).putOpt("os", osName).putOpt("ph", photoHash());
            if (!(profile.optBoolean("setup") && profile.optBoolean("visible"))) put(who, "hidden", true);
            put(msg, "who", who);
        }
        return msg;
    }

    private Map<String, String> expected() {
        long bucket = System.currentTimeMillis() / 30_000;
        StringBuilder stamp = new StringBuilder().append(bucket);
        for (JSONObject g : groups.values()) stamp.append(g.optString("id")).append(g.optString("key"))
                .append(g.optJSONObject("members") == null ? 0 : g.optJSONObject("members").length());
        if (!stamp.toString().equals(tagStamp)) {
            Map<String, String> t = new HashMap<>();
            for (JSONObject g : groups.values()) {
                if (g.optBoolean("removed") || g.optString("key").isEmpty() || g.optJSONObject("members") == null) continue;
                byte[] k = unhex(g.optString("key"));
                for (Iterator<String> it = g.optJSONObject("members").keys(); it.hasNext(); ) {
                    String did = it.next();
                    if (did.equals(me)) continue;
                    for (long b : new long[]{bucket, bucket - 1}) t.put(hex(hm(k, "member", did, b)).substring(0, 24), did);
                }
            }
            tagTable = t;
            tagStamp = stamp.toString();
        }
        return tagTable;
    }

    void onUdp(JSONObject msg, String ip) {
        if (!"arckad-pair".equals(msg.optString("app"))) return;
        int p = msg.optInt("port");
        if (!msg.optString("chatjoin").isEmpty() && p > 0) {
            codeSeen.put(msg.optString("chatjoin"), new double[]{now()});
            codeAddr.put(msg.optString("chatjoin"), new String[]{ip, String.valueOf(p)});
        }
        if (!msg.optString("fcode").isEmpty() && p > 0) {
            codeSeen.put(msg.optString("fcode"), new double[]{now()});
            codeAddr.put(msg.optString("fcode"), new String[]{ip, String.valueOf(p)});
        }
        JSONObject who = msg.optJSONObject("who");
        if (who != null && !who.optString("id").isEmpty() && !who.optString("id").equals(me) && p > 0) sawPerson(who, ip, p);
        JSONArray tags = msg.optJSONArray("ctags");
        if (tags == null || tags.length() == 0) return;
        Map<String, String> table = expected();
        Set<String> seen = new HashSet<>();
        for (int i = 0; i < tags.length(); i++) {
            String d = table.get(tags.optString(i));
            if (d != null) seen.add(d);
        }
        for (String did : seen) {
            boolean was = isOnline(did);
            online.put(did, new Obj().putOpt("ip", ip).putOpt("port", p).putOpt("seen", now()));
            if (!was) {
                ui.people();
                bg(() -> cameOnline(did));
            }
        }
        if (!seen.isEmpty() && System.currentTimeMillis() - answered.getOrDefault(ip, 0L) > 5000) {
            answered.put(ip, System.currentTimeMillis());
            sendBeacon(Collections.singleton(ip));                // answer directly so they find us quickly too
        }
    }

    private void cameOnline(String did) {
        for (Map.Entry<String, JSONObject> e : new ArrayList<>(groups.entrySet())) {
            JSONObject g = e.getValue();
            if (g.optBoolean("removed") || g.optJSONObject("members") == null || !g.optJSONObject("members").has(did)) continue;
            if (did.equals(g.optString("owner")) && !isOwner(e.getKey())) {
                pullMeta(e.getKey());
                ensureMyPub(e.getKey());
            }
            syncWith(e.getKey(), did);
        }
    }

    private Set<String> directTargets() {
        Set<String> s = new HashSet<>();
        for (JSONObject o : online.values()) if (!o.optString("ip").isEmpty()) s.add(o.optString("ip"));
        JSONObject f = friends();
        for (Iterator<String> it = f.keys(); it.hasNext(); ) {
            String ip = f.optJSONObject(it.next()).optString("ip");
            if (!ip.isEmpty()) s.add(ip);
        }
        return s;
    }

    private void sendBeacon(Set<String> targets) {
        DatagramSocket u = udp;
        if (u == null) return;
        byte[] data = utf8(beacon().toString());
        for (String t : targets) {
            try {
                u.send(new DatagramPacket(data, data.length, InetAddress.getByName(t), UDP_PORT));
            } catch (Exception ignored) {
            }
        }
    }

    private void tick() {
        long t = System.currentTimeMillis();
        if (t - lastSync < 45_000) return;
        lastSync = t;
        for (String gid : new ArrayList<>(groups.keySet())) {
            List<String> on = onlineMembers(gid);
            if (!on.isEmpty()) {
                String did = on.get(RNG.nextInt(on.size()));
                bg(() -> syncWith(gid, did));
            }
        }
    }

    // ================================================================= start / stop
    synchronized void start() {
        if (running || !active()) return;
        try {
            server = new Net.Server(TCP_PORTS, this::handle);
            port = server.port();
            DatagramSocket u = new DatagramSocket(null);
            u.setReuseAddress(true);
            u.setBroadcast(true);
            u.bind(new InetSocketAddress(UDP_PORT));
            u.setSoTimeout(500);
            udp = u;
            running = true;
            identity();
            Thread t = new Thread(this::loop, "arckad-chat");
            t.setDaemon(true);
            t.start();
        } catch (IOException e) {
            ui.event("Chat couldn't start: " + e.getMessage());
        }
    }

    synchronized void stop() {
        running = false;
        if (server != null) server.close();
        server = null;
        if (udp != null) udp.close();
        udp = null;
    }

    boolean running() {
        return running;
    }

    private void loop() {
        byte[] buf = new byte[16384];
        while (running) {
            DatagramSocket u = udp;
            if (u == null) break;
            try {
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                u.receive(p);
                String ip = p.getAddress().getHostAddress();
                try {
                    onUdp(new JSONObject(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8)), ip);
                } catch (Exception ignored) {
                }
            } catch (SocketTimeoutException ignored) {
            } catch (IOException e) {
                if (!running) break;
            }
            long t = System.currentTimeMillis();
            if (active() && t - lastBeacon > 3000) {
                lastBeacon = t;
                Set<String> targets = new HashSet<>();
                targets.add("255.255.255.255");
                for (String ip : Net.lanAddresses()) {
                    int dot = ip.lastIndexOf('.');
                    if (dot > 0 && ip.chars().filter(ch -> ch == '.').count() == 3) targets.add(ip.substring(0, dot) + ".255");
                }
                sendBeacon(targets);
            }
            if (t - lastDirect > 6000) {
                lastDirect = t;
                sendBeacon(directTargets());          // other VLANs: greet friends and members directly
                tick();
            }
        }
    }

    // ================================================================= the server side
    void handle(Net.Request r) throws Exception {
        String path = r.path;
        if (r.method.equals("GET")) {
            if (path.equals("/f/photo")) {
                byte[] d = photoBytes();
                if (d.length == 0) r.json(404, err("no photo"));
                else r.send(200, "image/jpeg", d);
                return;
            }
            if (path.startsWith("/c/file/")) {
                serveFile(r, path);
                return;
            }
            r.json(404, err("unknown"));
            return;
        }
        if (!r.method.equals("POST")) {
            r.json(404, err("unknown"));
            return;
        }
        if (path.equals("/f/codestart") || path.equals("/f/codeconfirm")) {
            JSONObject res = codePost(path, bodyJson(r), r.client);
            r.json(res.optBoolean("ok") ? 200 : 403, res);
            return;
        }
        if (path.startsWith("/f/")) {
            JSONObject res = friendPost(path, bodyJson(r), r.client);
            r.json(res.optBoolean("ok") ? 200 : 403, res);
            return;
        }
        if (path.equals("/cj/start")) {
            r.json(200, joinStart(bodyJson(r), r.client));
            return;
        }
        if (path.equals("/cj/confirm")) {
            JSONObject res = joinConfirm(bodyJson(r), r.client);
            r.json(res.optBoolean("ok") ? 200 : 403, res);
            return;
        }
        if (!path.startsWith("/c/")) {
            r.json(404, err("unknown"));
            return;
        }
        Object[] auth = auth(r);
        if (auth == null) {
            r.json(401, err("not a member"));
            return;
        }
        String gid = (String) auth[0], did = (String) auth[1];
        byte[] key = (byte[]) auth[2];
        boolean pair = (Boolean) auth[3];
        long len = r.length();
        byte[] body = len > 0 ? readStream(r.body, (int) Math.min(len, 20_000_000)) : new byte[0];
        JSONObject req = body.length > 0 ? new JSONObject(new String(unseal(key, body), StandardCharsets.UTF_8)) : new JSONObject();
        JSONObject g = groups.get(gid);
        JSONObject res;
        int code = 200;
        if (path.equals("/c/msg") && !pair) {
            JSONObject m = clean(req.opt("msg"), gid);
            if (m == null || !m.optString("from").equals(did)) {
                res = err("bad message");
                code = 400;
            } else if ("system".equals(m.optString("kind")) && !did.equals(g.optString("owner"))) {
                res = err("only the owner's device sends notices");
                code = 403;
            } else if (g.optBoolean("owner_only") && !did.equals(g.optString("owner"))) {
                res = err("only the owner can post in this group");
                code = 403;
            } else {
                if (append(gid, m)) {
                    if (!"system".equals(m.optString("kind")) && !"delete".equals(m.optString("kind"))) {
                        unread.merge(gid, 1, Integer::sum);
                        queueReceipt(gid, did, m.optString("id"), false);
                    }
                    ui.message(gid, m);
                    if (m.optJSONObject("file") != null) maybeDownload(gid, m);
                }
                res = new Obj().putOpt("ok", true);
            }
        } else if (path.equals("/c/sync") && !pair) {
            Set<String> known = new HashSet<>();
            JSONArray k = req.optJSONArray("ids");
            if (k != null) for (int i = 0; i < k.length(); i++) known.add(k.optString(i));
            double cutoff = now() - HISTORY_DAYS * 86400;
            JSONArray out = new JSONArray();
            for (JSONObject m : new ArrayList<>(msgs.getOrDefault(gid, new ArrayList<>()))) {
                if (known.contains(m.optString("id")) || m.optDouble("ts", 0) <= cutoff || m.optBoolean("local") || m.optBoolean("opened")
                        || m.has("deleted")) continue;
                if (m.optBoolean("once") && !me.equals(m.optString("from"))) continue;
                JSONObject c = new JSONObject(m.toString());
                for (String field : new String[]{"local", "opened_by", "delivered", "read", "r_sent"}) c.remove(field);
                out.put(c);
            }
            JSONArray last = new JSONArray();
            for (int i = Math.max(0, out.length() - 2000); i < out.length(); i++) last.put(out.opt(i));
            res = new Obj().putOpt("ok", true).putOpt("msgs", last);
        } else if (path.equals("/c/meta") && pair && did.equals(g.optString("owner"))) {
            applyMeta(gid, req);
            res = new Obj().putOpt("ok", true);
        } else if (path.equals("/c/getmeta") && pair && isOwner(gid)) {
            res = g.optJSONObject("members").has(did) ? metaForMembers(g) : new Obj().putOpt("id", gid).putOpt("removed", true);
        } else if (path.equals("/c/setpub") && pair && isOwner(gid) && g.optJSONObject("members").has(did)) {
            String pub = cut(req.optString("pub"), 1100);
            JSONObject m = g.optJSONObject("members").optJSONObject(did);
            if (!pub.isEmpty() && m.optString("pub").isEmpty()) {
                put(m, "pub", pub);
                put(g, "version", g.optInt("version", 1) + 1);
                save();
                pushMeta(gid);
            }
            res = new Obj().putOpt("ok", true);
        } else if (path.equals("/c/leave") && !pair && isOwner(gid)) {
            JSONObject left = (JSONObject) g.optJSONObject("members").remove(did);
            String name = left == null ? "A member" : left.optString("name", "A member");
            Obj.put(past(g), did, new Obj().putOpt("name", name).putOpt("pub", left == null ? null : left.opt("pub")));
            if (g.optJSONObject("pair_keys") != null) g.optJSONObject("pair_keys").remove(did);
            put(g, "key", hex(random(32)));
            put(g, "version", g.optInt("version", 1) + 1);
            save();
            system(gid, name + " left the group", true);
            pushMeta(gid);
            res = new Obj().putOpt("ok", true);
        } else if (path.equals("/c/unfriend") && !pair && "direct".equals(g.optString("kind")) && did.equals(g.optString("peer"))) {
            r.send(200, "application/octet-stream", seal(key, utf8("{\"ok\": true}")));
            forgetFriend(did);
            return;
        } else if (path.equals("/c/call")) {
            res = err("Calls on this phone arrive in the next Arckad-D update.");
            code = 403;
        } else if (path.equals("/c/receipt") && !pair) {
            gotReceipt(gid, did, req);
            res = new Obj().putOpt("ok", true);
        } else if (path.equals("/c/viewed")) {
            res = new Obj().putOpt("ok", true);
        } else {
            res = err("unknown request");
            code = 404;
        }
        r.send(code, "application/octet-stream", seal(key, utf8(res.toString())));
    }

    private void serveFile(Net.Request r, String path) throws Exception {
        Object[] auth = auth(r);
        if (auth == null || (Boolean) auth[3]) {
            r.json(401, err("not a member"));
            return;
        }
        String gid = (String) auth[0];
        String fid = path.substring("/c/file/".length());
        File src = localFile(gid, fid);
        if (src == null) {
            r.json(404, err("no file"));
            return;
        }
        byte[] key = (byte[]) auth[2];
        long size = src.length();
        String head = "HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\nContent-Length: " + (size + 32)
                + "\r\nConnection: close\r\n\r\n";
        r.out.write(utf8(head));
        Stream cipher = new Stream(hm(key, "chatfile", fid));
        javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
        mac.init(new javax.crypto.spec.SecretKeySpec(hm(key, "chatfile-mac", fid), "HmacSHA256"));
        byte[] buf = new byte[1 << 18];
        try (FileInputStream in = new FileInputStream(src)) {
            long left = size;
            while (left > 0) {
                int n = in.read(buf, 0, (int) Math.min(buf.length, left));
                if (n < 0) break;
                byte[] enc = cipher.apply(buf, 0, n);
                mac.update(enc);
                r.out.write(enc);
                left -= n;
            }
        }
        r.out.write(mac.doFinal());
        r.out.flush();
    }

    /** {gid, device id, key, pair?} for a correctly signed request from a member, else null. */
    private Object[] auth(Net.Request r) {
        String gid = r.headers.getOrDefault("x-chat-group", ""), did = r.headers.getOrDefault("x-chat-from", "");
        JSONObject g = groups.get(gid);
        if (g == null || g.optBoolean("removed")) return null;
        long ts;
        try {
            ts = Long.parseLong(r.headers.getOrDefault("x-chat-time", "0"));
        } catch (NumberFormatException e) {
            return null;
        }
        if (Math.abs(System.currentTimeMillis() / 1000 - ts) > 600) return null;
        byte[] key;
        boolean pair = "1".equals(r.headers.get("x-chat-pair"));
        if (pair) {
            String hexkey = null;
            if (isOwner(gid) && g.optJSONObject("pair_keys") != null) hexkey = g.optJSONObject("pair_keys").optString(did, null);
            else if (did.equals(g.optString("owner"))) hexkey = g.optString("owner_key", null);
            if (hexkey == null || hexkey.isEmpty()) return null;
            key = unhex(hexkey);
        } else {
            if (g.optJSONObject("members") == null || !g.optJSONObject("members").has(did)) return null;
            key = unhex(g.optString("key"));
        }
        String full = r.path + (r.query.isEmpty() ? "" : "?" + r.query);
        if (!same(hex(hm(key, r.method, full, ts, did, gid)), r.headers.getOrDefault("x-chat-sig", ""))) return null;
        JSONObject o = online.get(did);
        if (o != null && o.optInt("port") > 0) {
            put(o, "ip", r.client);
            put(o, "seen", now());
        }
        return new Object[]{gid, did, key, pair};
    }

    // ================================================================= small utilities
    static JSONObject err(String reason) {
        return new Obj().putOpt("ok", false).putOpt("reason", reason);
    }

    private static JSONObject bodyJson(Net.Request r) throws Exception {
        long n = r.length();
        if (n <= 0) return new JSONObject();
        return new JSONObject(new String(readStream(r.body, (int) Math.min(n, 200_000)), StandardCharsets.UTF_8));
    }

    static void put(JSONObject o, String k, Object v) {
        try {
            o.put(k, v == null ? JSONObject.NULL : v);
        } catch (Exception ignored) {
        }
    }

    static String cut(String s, int n) {
        return s == null ? "" : s.length() > n ? s.substring(0, n) : s;
    }

    static void bg(Runnable r) {
        Thread t = new Thread(r, "arckad-chat-bg");
        t.setDaemon(true);
        t.start();
    }

    static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException ignored) {
        }
    }

    static byte[] readAll(File f) throws IOException {
        try (FileInputStream in = new FileInputStream(f)) {
            return readStream(in, Integer.MAX_VALUE);
        }
    }

    static byte[] readStream(InputStream in, int max) throws IOException {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[65536];
        int n;
        while (b.size() < max && (n = in.read(buf, 0, Math.min(buf.length, max - b.size()))) > 0) b.write(buf, 0, n);
        return b.toByteArray();
    }

    static JSONObject readJson(File f) {
        try {
            return new JSONObject(new String(readAll(f), StandardCharsets.UTF_8));
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    static void writeJson(File f, JSONObject o) {
        writeFile(f, utf8(o.toString()));
    }

    static void writeFile(File f, byte[] data) {
        File tmp = new File(f.getPath() + ".tmp");
        try (FileOutputStream o = new FileOutputStream(tmp)) {
            o.write(data);
        } catch (IOException e) {
            return;
        }
        if (!tmp.renameTo(f)) {
            f.delete();
            tmp.renameTo(f);
        }
    }
}

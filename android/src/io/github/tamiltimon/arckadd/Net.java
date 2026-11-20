package io.github.tamiltimon.arckadd;

import android.content.Context;
import android.net.wifi.WifiManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.HttpURLConnection;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.security.SecureRandom;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

/**
 * Wi-Fi sharing. "Nearby" finds other Arckad-D devices (UDP 47820) and sends files to them
 * (HTTP 47821-47823, receiver must accept); "Link" serves files to any browser (HTTP 8765-8767).
 * The protocol is identical to the desktop app, so phones, Linux and Windows all talk to each other.
 */
final class Net {
    static final int UDP_PORT = 47820;
    static final int[] NEARBY_PORTS = {47821, 47822, 47823, 0};
    static final int[] LINK_PORTS = {8765, 8766, 8767, 0};
    static final String OS = "Android";
    private static final SecureRandom RNG = new SecureRandom();

    private Net() {
    }

    // ================================================================= tiny HTTP server
    static final class Request {
        String method, path, query = "", client;
        final Map<String, String> headers = new HashMap<>();
        InputStream body;
        OutputStream out;

        long length() {
            try {
                return Long.parseLong(headers.getOrDefault("content-length", "-1").trim());
            } catch (NumberFormatException e) {
                return -1;
            }
        }

        void send(int code, String type, byte[] body, String... extra) throws IOException {
            StringBuilder h = new StringBuilder("HTTP/1.1 ").append(code).append(code == 200 ? " OK" : " X").append("\r\n")
                    .append("Content-Type: ").append(type).append("\r\nContent-Length: ").append(body.length)
                    .append("\r\nConnection: close\r\nServer: Arckad-D\r\n");
            for (String e : extra) h.append(e).append("\r\n");
            h.append("\r\n");
            out.write(h.toString().getBytes(StandardCharsets.UTF_8));
            out.write(body);
            out.flush();
        }

        void json(int code, JSONObject o) throws IOException {
            send(code, "application/json", o.toString().getBytes(StandardCharsets.UTF_8));
        }

        void html(int code, String s) throws IOException {
            send(code, "text/html; charset=utf-8", s.getBytes(StandardCharsets.UTF_8), "Cache-Control: no-store");
        }
    }

    interface Handler {
        void handle(Request r) throws Exception;
    }

    static final class Server {
        final ServerSocket socket;
        final ExecutorService pool = Executors.newCachedThreadPool();
        volatile boolean running = true;

        Server(int[] ports, Handler handler) throws IOException {
            ServerSocket s = null;
            for (int p : ports) {
                try {
                    s = new ServerSocket();
                    s.setReuseAddress(true);
                    s.bind(new InetSocketAddress(p));
                    break;
                } catch (IOException e) {
                    try {
                        if (s != null) s.close();
                    } catch (IOException ignored) {
                    }
                    s = null;
                }
            }
            if (s == null) throw new IOException("no free network port");
            socket = s;
            Thread t = new Thread(() -> {
                while (running) {
                    try {
                        Socket c = socket.accept();
                        pool.execute(() -> serve(c, handler));
                    } catch (IOException e) {
                        if (!running) return;
                    }
                }
            }, "arckad-http");
            t.setDaemon(true);
            t.start();
        }

        int port() {
            return socket.getLocalPort();
        }

        void close() {
            running = false;
            try {
                socket.close();
            } catch (IOException ignored) {
            }
            pool.shutdownNow();
        }

        private static void serve(Socket c, Handler handler) {
            try (Socket s = c) {
                s.setSoTimeout(120_000);
                InputStream in = new BufferedInputStream(s.getInputStream(), 65536);
                Request r = new Request();
                String line = readLine(in);
                if (line == null) return;
                String[] parts = line.split(" ");
                if (parts.length < 2) return;
                r.method = parts[0];
                String target = parts[1];
                int q = target.indexOf('?');
                r.path = q >= 0 ? target.substring(0, q) : target;
                if (q >= 0) r.query = target.substring(q + 1);
                String h;
                while ((h = readLine(in)) != null && !h.isEmpty()) {
                    int colon = h.indexOf(':');
                    if (colon > 0) r.headers.put(h.substring(0, colon).trim().toLowerCase(Locale.ROOT), h.substring(colon + 1).trim());
                }
                r.body = in;
                r.out = s.getOutputStream();
                r.client = s.getInetAddress().getHostAddress();
                handler.handle(r);
            } catch (Exception ignored) {
            }
        }

        private static String readLine(InputStream in) throws IOException {
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            int c;
            while ((c = in.read()) != -1) {
                if (c == '\n') break;
                if (c != '\r') b.write(c);
                if (b.size() > 16384) throw new IOException("header too long");
            }
            if (c == -1 && b.size() == 0) return null;
            return b.toString("UTF-8");
        }
    }

    static List<String> segments(String path) {
        List<String> out = new ArrayList<>();
        for (String p : path.split("/")) if (!p.isEmpty()) out.add(p);
        return out;
    }

    // ================================================================= addresses
    static List<String> lanAddresses() {
        List<String> wifi = new ArrayList<>(), other = new ArrayList<>();
        try {
            for (Enumeration<NetworkInterface> e = NetworkInterface.getNetworkInterfaces(); e.hasMoreElements(); ) {
                NetworkInterface ni = e.nextElement();
                if (!ni.isUp() || ni.isLoopback()) continue;
                for (Enumeration<InetAddress> a = ni.getInetAddresses(); a.hasMoreElements(); ) {
                    InetAddress ad = a.nextElement();
                    if (!(ad instanceof Inet4Address)) continue;
                    String ip = ad.getHostAddress();
                    if (ni.getName().startsWith("wlan") || ni.getName().startsWith("ap") || ni.getName().startsWith("swlan")) wifi.add(ip);
                    else if (ad.isSiteLocalAddress()) other.add(ip);
                }
            }
        } catch (Exception ignored) {
        }
        wifi.addAll(other);
        if (wifi.isEmpty()) wifi.add("127.0.0.1");
        return wifi;
    }

    static String token(int n) {
        String abc = "abcdefghjkmnpqrstuvwxyz23456789";
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < n; i++) sb.append(abc.charAt(RNG.nextInt(abc.length())));
        return sb.toString();
    }

    static String esc(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\"", "&quot;");
    }

    // ================================================================= Nearby
    static final class Peer {
        String id, name, os, ip;
        int port;
        long seen;
    }

    static final class Incoming {
        String from, os, ip;
        final List<String> rel = new ArrayList<>();
        final List<Long> sizes = new ArrayList<>();
        final List<File> dest = new ArrayList<>();
        long total, received;
        int doneFiles;
        volatile boolean accepted;
        final CountDownLatch decided = new CountDownLatch(1);
    }

    interface NearbyUi {
        void peersChanged();

        /** Show an Accept / Decline question; call in.accepted = ...; in.decided.countDown(). */
        void askIncoming(Incoming in);

        void progress(Incoming in);

        void received(Incoming in);
    }

    interface SendProgress {
        void update(long sent, long total, String what);
    }

    static final class Nearby {
        final String id;
        final Context ctx;
        volatile NearbyUi ui;
        private final Map<String, Peer> peers = new LinkedHashMap<>();
        private final Map<String, Incoming> transfers = Collections.synchronizedMap(new HashMap<>());
        private volatile DatagramSocket udp;
        private volatile boolean scanning;
        private Server server;
        private volatile long visibleUntil;
        private long lastBeacon, lastProbe, lastExpire;
        private WifiManager.MulticastLock lock;
        String name = "Phone";

        Nearby(Context c, String id, NearbyUi ui) {
            ctx = c.getApplicationContext();
            this.id = id;
            this.ui = ui;
        }

        boolean visible() {
            return server != null && System.currentTimeMillis() < visibleUntil;
        }

        int remaining() {
            return server == null ? 0 : (int) Math.max(0, (visibleUntil - System.currentTimeMillis()) / 1000);
        }

        boolean serving() {
            return server != null;
        }

        boolean busyReceiving() {
            return !transfers.isEmpty();
        }

        synchronized void setVisible(int minutes) throws IOException {
            if (server == null) server = new Server(NEARBY_PORTS, this::handle);
            visibleUntil = System.currentTimeMillis() + Math.max(1, Math.min(10, minutes)) * 60_000L;
            ensureUdp();
            lastBeacon = 0;
        }

        /** Returns false if a transfer is still running (it closes after it finishes). */
        synchronized boolean hide(boolean force) {
            visibleUntil = 0;
            if (!transfers.isEmpty() && !force) return false;
            if (server != null) {
                send(msg("bye"), null);
                server.close();
                server = null;
            }
            maybeCloseUdp();
            return true;
        }

        synchronized void startScan() throws IOException {
            scanning = true;
            ensureUdp();
            lastProbe = 0;
        }

        synchronized void stopScan() {
            scanning = false;
            maybeCloseUdp();
        }

        List<Peer> peers() {
            synchronized (peers) {
                List<Peer> l = new ArrayList<>(peers.values());
                Collections.sort(l, (a, b) -> a.name.compareToIgnoreCase(b.name));
                return l;
            }
        }

        private void ensureUdp() throws IOException {
            if (udp != null) return;
            if (lock == null) {
                WifiManager wm = (WifiManager) ctx.getSystemService(Context.WIFI_SERVICE);
                if (wm != null) {
                    lock = wm.createMulticastLock("arckad-d");
                    lock.setReferenceCounted(false);
                }
            }
            if (lock != null) lock.acquire();
            DatagramSocket s = new DatagramSocket(null);
            s.setReuseAddress(true);
            s.setBroadcast(true);
            s.bind(new InetSocketAddress(UDP_PORT));
            s.setSoTimeout(500);
            udp = s;
            Thread t = new Thread(() -> loop(s), "arckad-udp");
            t.setDaemon(true);
            t.start();
        }

        private void maybeCloseUdp() {
            if (udp != null && !scanning && server == null) {
                DatagramSocket s = udp;
                udp = null;
                s.close();
                synchronized (peers) {
                    peers.clear();
                }
                if (lock != null && lock.isHeld()) lock.release();
            }
        }

        private JSONObject msg(String type) {
            JSONObject o = new JSONObject();
            try {
                o.put("app", "arckad-d").put("v", 1).put("type", type).put("id", id).put("name", name)
                        .put("os", OS).put("port", server == null ? 0 : server.port());
            } catch (Exception ignored) {
            }
            return o;
        }

        private void send(JSONObject o, String target) {
            DatagramSocket s = udp;
            if (s == null) return;
            byte[] data = o.toString().getBytes(StandardCharsets.UTF_8);
            List<String> targets = new ArrayList<>();
            if (target != null) targets.add(target);
            else {
                targets.add("255.255.255.255");
                for (String ip : lanAddresses()) {
                    int dot = ip.lastIndexOf('.');
                    if (dot > 0 && !ip.startsWith("127.")) targets.add(ip.substring(0, dot) + ".255");
                }
            }
            for (String t : targets) {
                try {
                    s.send(new DatagramPacket(data, data.length, InetAddress.getByName(t), UDP_PORT));
                } catch (Exception ignored) {
                }
            }
        }

        private void loop(DatagramSocket s) {
            byte[] buf = new byte[8192];
            while (udp == s) {
                DatagramPacket p = new DatagramPacket(buf, buf.length);
                try {
                    s.receive(p);
                    handleUdp(new String(p.getData(), 0, p.getLength(), StandardCharsets.UTF_8), p.getAddress().getHostAddress());
                } catch (SocketTimeoutException ignored) {
                } catch (IOException e) {
                    if (udp != s) return;
                }
                tick();
            }
        }

        private void handleUdp(String text, String ip) {
            JSONObject m;
            try {
                m = new JSONObject(text);
            } catch (Exception e) {
                return;
            }
            if (!"arckad-d".equals(m.optString("app")) || id.equals(m.optString("id"))) return;
            String type = m.optString("type"), pid = m.optString("id");
            boolean changed = false;
            if ("hello".equals(type) && m.optInt("port") > 0) {
                synchronized (peers) {
                    Peer old = peers.get(pid);
                    Peer p = new Peer();
                    p.id = pid;
                    p.name = m.optString("name", "Unknown");
                    p.os = m.optString("os", "");
                    p.ip = ip;
                    p.port = m.optInt("port");
                    p.seen = System.currentTimeMillis();
                    peers.put(pid, p);
                    changed = old == null || !old.name.equals(p.name);
                }
            } else if ("probe".equals(type) && visible()) {
                send(msg("hello"), ip);
            } else if ("bye".equals(type)) {
                synchronized (peers) {
                    changed = peers.remove(pid) != null;
                }
            }
            if (changed) ui.peersChanged();
        }

        private void tick() {
            long now = System.currentTimeMillis();
            if (visible() && now - lastBeacon > 2000) {
                lastBeacon = now;
                send(msg("hello"), null);
            }
            if (scanning && now - lastProbe > 3000) {
                lastProbe = now;
                send(msg("probe"), null);
            }
            if (now - lastExpire > 2000) {
                lastExpire = now;
                boolean gone = false;
                synchronized (peers) {
                    for (java.util.Iterator<Peer> it = peers.values().iterator(); it.hasNext(); ) {
                        if (now - it.next().seen > 8000) {
                            it.remove();
                            gone = true;
                        }
                    }
                }
                if (gone) ui.peersChanged();
            }
        }

        // ---------- receiving
        private void handle(Request r) throws Exception {
            List<String> seg = segments(r.path);
            if ("POST".equals(r.method) && seg.size() == 1 && seg.get(0).equals("offer")) {
                if (!visible()) {
                    r.json(403, new JSONObject().put("ok", false).put("reason", "not visible right now"));
                    return;
                }
                long len = r.length();
                if (len <= 0 || len > 5_000_000) {
                    r.json(413, new JSONObject().put("ok", false).put("reason", "offer too large"));
                    return;
                }
                byte[] body = new byte[(int) len];
                int n = 0;
                while (n < len) {
                    int k = r.body.read(body, n, (int) len - n);
                    if (k < 0) break;
                    n += k;
                }
                JSONObject offer = new JSONObject(new String(body, 0, n, StandardCharsets.UTF_8));
                Incoming in = new Incoming();
                in.from = offer.optString("name", "Unknown device");
                in.os = offer.optString("os", "");
                in.ip = r.client;
                JSONArray files = offer.optJSONArray("files");
                if (files == null || files.length() == 0) {
                    r.json(400, new JSONObject().put("ok", false).put("reason", "no files"));
                    return;
                }
                for (int i = 0; i < Math.min(files.length(), 20000); i++) {
                    JSONObject f = files.getJSONObject(i);
                    String rel = safeRel(f.optString("path"));
                    long size = f.optLong("size", -1);
                    if (rel == null || size < 0) {
                        r.json(400, new JSONObject().put("ok", false).put("reason", "bad file name"));
                        return;
                    }
                    in.rel.add(rel);
                    in.sizes.add(size);
                    in.total += size;
                }
                ui.askIncoming(in);
                in.decided.await(90, TimeUnit.SECONDS);
                if (!in.accepted) {
                    r.json(403, new JSONObject().put("ok", false).put("reason", "declined"));
                    return;
                }
                planDestinations(in);
                String tok = token(24);
                transfers.put(tok, in);
                r.json(200, new JSONObject().put("ok", true).put("token", tok));
                return;
            }
            if ("PUT".equals(r.method) && seg.size() == 3 && seg.get(0).equals("upload")) {
                Incoming in = transfers.get(seg.get(1));
                int i;
                try {
                    i = Integer.parseInt(seg.get(2));
                } catch (NumberFormatException e) {
                    i = -1;
                }
                if (in == null || i < 0 || i >= in.rel.size()) {
                    r.json(404, new JSONObject().put("ok", false));
                    return;
                }
                long size = in.sizes.get(i);
                if (r.length() != size) {
                    r.json(400, new JSONObject().put("ok", false).put("reason", "size mismatch"));
                    return;
                }
                File dest = in.dest.get(i);
                //noinspection ResultOfMethodCallIgnored
                dest.getParentFile().mkdirs();
                File tmp = new File(dest.getPath() + ".part");
                long left = size;
                byte[] buf = new byte[256 * 1024];
                try (OutputStream out = new FileOutputStream(tmp)) {
                    while (left > 0) {
                        int k = r.body.read(buf, 0, (int) Math.min(buf.length, left));
                        if (k < 0) break;
                        out.write(buf, 0, k);
                        left -= k;
                        in.received += k;
                    }
                }
                if (left > 0 || !tmp.renameTo(dest)) {
                    //noinspection ResultOfMethodCallIgnored
                    tmp.delete();
                    r.json(400, new JSONObject().put("ok", false).put("reason", "incomplete"));
                    return;
                }
                in.doneFiles++;
                ui.progress(in);
                r.json(200, new JSONObject().put("ok", true));
                return;
            }
            if ("POST".equals(r.method) && seg.size() == 2 && seg.get(0).equals("done")) {
                Incoming in = transfers.remove(seg.get(1));
                if (in == null) {
                    r.json(404, new JSONObject().put("ok", false));
                    return;
                }
                ui.received(in);
                r.json(200, new JSONObject().put("ok", true));
                return;
            }
            r.json(404, new JSONObject().put("ok", false));
        }

        private static String safeRel(String rel) {
            StringBuilder out = new StringBuilder();
            for (String part : rel.replace('\\', '/').split("/")) {
                if (part.isEmpty() || part.equals(".") || part.equals("..")) return null;
                StringBuilder c = new StringBuilder();
                for (char ch : part.toCharArray()) c.append("<>:\"|?*".indexOf(ch) >= 0 || ch < 32 ? '_' : ch);
                String clean = c.toString().trim();
                while (clean.endsWith(".")) clean = clean.substring(0, clean.length() - 1);
                if (clean.isEmpty()) return null;
                if (out.length() > 0) out.append('/');
                out.append(clean.length() > 200 ? clean.substring(0, 200) : clean);
            }
            return out.length() == 0 ? null : out.toString();
        }

        private static void planDestinations(Incoming in) {
            File base = Fs.received();
            Map<String, File> roots = new HashMap<>();
            List<String> claimed = new ArrayList<>();
            for (String rel : in.rel) {
                String[] parts = rel.split("/");
                File root;
                if (parts.length > 1 && roots.containsKey(parts[0])) root = roots.get(parts[0]);
                else {
                    root = Fs.unique(new File(base, parts[0]));
                    int k = 1;
                    while (claimed.contains(root.getPath())) {
                        root = Fs.unique(new File(base, parts[0].replaceFirst("(\\.[^.]+)?$", " (" + (k++) + ")$1")));
                    }
                    claimed.add(root.getPath());
                    if (parts.length > 1) roots.put(parts[0], root);
                }
                File f = root;
                for (int i = 1; i < parts.length; i++) f = new File(f, parts[i]);
                in.dest.add(f);
            }
        }

        // ---------- sending
        /** Runs on a background thread; returns null when everything was sent, else a message. */
        String sendFiles(Peer peer, List<File> items, SendProgress progress) {
            List<File> files = new ArrayList<>();
            List<String> names = new ArrayList<>();
            for (File f : items) Fs.collect(f, f.getName(), files, names);
            if (files.isEmpty()) return "There are no files to send (empty folders are skipped).";
            long total = 0;
            try {
                JSONArray arr = new JSONArray();
                for (int i = 0; i < files.size(); i++) {
                    arr.put(new JSONObject().put("path", names.get(i)).put("size", files.get(i).length()));
                    total += files.get(i).length();
                }
                JSONObject offer = new JSONObject().put("name", name).put("os", OS).put("id", id).put("files", arr);
                progress.update(0, total, "Waiting for " + peer.name + " to accept…");
                String base = "http://" + peer.ip + ":" + peer.port;
                JSONObject reply = post(base + "/offer", offer.toString().getBytes(StandardCharsets.UTF_8), 100_000);
                if (!reply.optBoolean("ok")) {
                    return "declined".equals(reply.optString("reason")) ? peer.name + " declined or didn't answer."
                            : peer.name + " couldn't receive: " + reply.optString("reason", "unknown reason") + ".";
                }
                String tok = reply.getString("token");
                long sent = 0, last = 0;
                byte[] buf = new byte[256 * 1024];
                for (int i = 0; i < files.size(); i++) {
                    File f = files.get(i);
                    long size = f.length();
                    HttpURLConnection c = (HttpURLConnection) new URL(base + "/upload/" + tok + "/" + i).openConnection();
                    c.setRequestMethod("PUT");
                    c.setDoOutput(true);
                    c.setConnectTimeout(15_000);
                    c.setReadTimeout(60_000);
                    c.setFixedLengthStreamingMode(size);
                    try (InputStream in = new FileInputStream(f); OutputStream out = c.getOutputStream()) {
                        long left = size;
                        while (left > 0) {
                            int k = in.read(buf, 0, (int) Math.min(buf.length, left));
                            if (k < 0) break;
                            out.write(buf, 0, k);
                            left -= k;
                            sent += k;
                            long now = System.currentTimeMillis();
                            if (now - last > 200) {
                                last = now;
                                progress.update(sent, total, "Sending " + names.get(i) + "…");
                            }
                        }
                    }
                    int code = c.getResponseCode();
                    c.disconnect();
                    if (code != 200) return "Sending stopped at " + names.get(i) + ".";
                }
                post(base + "/done/" + tok, new byte[0], 30_000);
                progress.update(total, total, "Done");
                return null;
            } catch (Exception e) {
                return "Couldn't reach " + peer.name + ". Check both devices are on the same Wi-Fi. (" + e.getMessage() + ")";
            }
        }

        private static JSONObject post(String url, byte[] body, int timeout) throws Exception {
            HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setConnectTimeout(15_000);
            c.setReadTimeout(timeout);
            c.setRequestProperty("Content-Type", "application/json");
            c.setFixedLengthStreamingMode(body.length);
            try (OutputStream o = c.getOutputStream()) {
                o.write(body);
            }
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            ByteArrayOutputStream b = new ByteArrayOutputStream();
            if (in != null) {
                try (InputStream s = in) {
                    Fs.pipe(s, b);
                }
            }
            c.disconnect();
            String txt = b.toString("UTF-8");
            return txt.isEmpty() ? new JSONObject() : new JSONObject(txt);
        }
    }

    // ================================================================= link sharing (any browser)
    interface LinkUi {
        void event(String client, String what);
    }

    static final class Link {
        final List<File> items = Collections.synchronizedList(new ArrayList<>());
        private Server server;
        private String tok = "";
        private volatile long expires;
        String deviceName = "Phone";
        LinkUi ui;

        boolean active() {
            return server != null && System.currentTimeMillis() < expires;
        }

        int remaining() {
            return server == null ? 0 : (int) Math.max(0, (expires - System.currentTimeMillis()) / 1000);
        }

        synchronized void start(int minutes) throws IOException {
            stop();
            tok = token(8);
            server = new Server(LINK_PORTS, this::handle);
            expires = System.currentTimeMillis() + Math.max(1, Math.min(10, minutes)) * 60_000L;
        }

        synchronized void stop() {
            if (server != null) server.close();
            server = null;
        }

        String url() {
            return "http://" + lanAddresses().get(0) + ":" + (server == null ? 0 : server.port()) + "/" + tok + "/";
        }

        private List<File> snapshot() {
            List<File> l = new ArrayList<>();
            synchronized (items) {
                for (File f : items) if (f.exists()) l.add(f);
            }
            return l;
        }

        private void handle(Request r) throws Exception {
            List<String> seg = segments(r.path);
            String page = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>";
            if (seg.isEmpty() || !seg.get(0).equals(tok)) {
                r.html(404, page + "<h1>Link not found</h1>");
                return;
            }
            if (!active()) {
                r.html(410, page + "<h1>This share has ended</h1>");
                return;
            }
            List<File> files = snapshot();
            if (seg.size() == 1) {
                if (!r.path.endsWith("/")) {
                    r.send(301, "text/plain", new byte[0], "Location: /" + tok + "/");
                    return;
                }
                if (ui != null) ui.event(r.client, "opened the share page");
                StringBuilder rows = new StringBuilder();
                for (int i = 0; i < files.size(); i++) {
                    File f = files.get(i);
                    rows.append("<li><div class=info><div class=name>").append(esc(f.getName()))
                            .append("</div><div class=meta>").append(f.isDirectory() ? "folder · ZIP" : Fs.size(f.length()))
                            .append("</div></div><a class=dl href='f/").append(i).append("'>Download</a></li>");
                }
                String all = files.size() > 1 ? "<a class=all href='all.zip'>⬇ Download everything (ZIP)</a>" : "";
                r.html(200, page + "<title>Arckad-D share</title><style>" + CSS + "</style><main><h1>Files shared from "
                        + esc(deviceName) + "</h1><p class=sub>Arckad-D Quick Share · <span class=timer>"
                        + (remaining() / 60) + " min left</span></p>" + all + "<ul>" + rows + "</ul></main>");
                return;
            }
            if (seg.get(1).equals("all.zip") && !files.isEmpty()) {
                if (ui != null) ui.event(r.client, "downloaded everything (ZIP)");
                zip(r, files, "Arckad-D share.zip");
                return;
            }
            if (seg.get(1).equals("f") && seg.size() >= 3) {
                int i;
                try {
                    i = Integer.parseInt(seg.get(2));
                } catch (NumberFormatException e) {
                    i = -1;
                }
                if (i >= 0 && i < files.size()) {
                    File f = files.get(i);
                    if (f.isDirectory()) {
                        if (ui != null) ui.event(r.client, "downloaded folder " + f.getName());
                        List<File> one = new ArrayList<>();
                        one.add(f);
                        zip(r, one, f.getName() + ".zip");
                        return;
                    }
                    if (ui != null) ui.event(r.client, "downloaded " + f.getName());
                    String head = "HTTP/1.1 200 OK\r\nContent-Type: " + Fs.mime(f.getName()) + "\r\nContent-Length: " + f.length()
                            + "\r\nContent-Disposition: attachment; filename*=UTF-8''" + URLEncoder.encode(f.getName(), "UTF-8").replace("+", "%20")
                            + "\r\nConnection: close\r\n\r\n";
                    r.out.write(head.getBytes(StandardCharsets.UTF_8));
                    try (InputStream in = new FileInputStream(f)) {
                        Fs.pipe(in, r.out);
                    }
                    r.out.flush();
                    return;
                }
            }
            r.html(404, page + "<h1>Not found</h1>");
        }

        private static void zip(Request r, List<File> items, String name) throws IOException {
            String head = "HTTP/1.1 200 OK\r\nContent-Type: application/zip\r\nContent-Disposition: attachment; filename*=UTF-8''"
                    + URLEncoder.encode(name, "UTF-8").replace("+", "%20") + "\r\nConnection: close\r\n\r\n";
            r.out.write(head.getBytes(StandardCharsets.UTF_8));
            ZipOutputStream z = new ZipOutputStream(r.out);
            z.setLevel(1);
            for (File item : items) {
                List<File> files = new ArrayList<>();
                List<String> names = new ArrayList<>();
                Fs.collect(item, item.getName(), files, names);
                for (int i = 0; i < files.size(); i++) {
                    z.putNextEntry(new ZipEntry(names.get(i)));
                    try (InputStream in = new FileInputStream(files.get(i))) {
                        Fs.pipe(in, z);
                    }
                    z.closeEntry();
                }
            }
            z.finish();
            r.out.flush();
        }

        static final String CSS = ":root{--bg:#f6f5f4;--card:#fff;--text:#1d1d1f;--muted:#6b6b6f;--accent:#5b5bd6;--line:#e3e2e0}"
                + "@media (prefers-color-scheme:dark){:root{--bg:#1e1e20;--card:#2a2a2d;--text:#f2f2f2;--muted:#a0a0a6;--accent:#8c8cff;--line:#3a3a3e}}"
                + "*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--text)}"
                + "main{max-width:720px;margin:0 auto;padding:20px 14px 40px}h1{font-size:22px;margin:0}"
                + ".sub{color:var(--muted);margin:4px 0 16px}.timer{background:var(--accent);color:#fff;border-radius:999px;padding:3px 10px}"
                + ".all{display:block;text-align:center;background:var(--accent);color:#fff;text-decoration:none;border-radius:12px;padding:13px;margin:14px 0;font-weight:600}"
                + "ul{list-style:none;padding:0;margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px}"
                + "li{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--line)}li:first-child{border-top:0}"
                + ".info{flex:1;min-width:0}.name{font-weight:600;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:13px}"
                + "a.dl{background:var(--accent);color:#fff;text-decoration:none;border-radius:9px;padding:7px 11px}";
    }
}

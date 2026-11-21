package io.github.tamiltimon.arckadd;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;
import java.util.zip.ZipOutputStream;

import static io.github.tamiltimon.arckadd.ChatCrypto.*;

/** Chat backups (.arckadprofile), the same encrypted format as the desktop app: a backup made on the phone
 *  restores on a PC and the other way round. The password key uses scrypt like the desktop. */
final class ChatBackup {
    private ChatBackup() {
    }

    // ---------- password → key (scrypt N=2^15, r=8, p=1; PBKDF2-HMAC-SHA256 for old "pbkdf2" backups)
    static byte[] pbkdf2(byte[] pw, byte[] salt, int iterations, int len) {
        try {
            javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
            mac.init(new javax.crypto.spec.SecretKeySpec(pw, "HmacSHA256"));
            byte[] out = new byte[len];
            int blocks = (len + 31) / 32;
            for (int i = 1; i <= blocks; i++) {
                mac.update(salt);
                mac.update(new byte[]{(byte) (i >>> 24), (byte) (i >>> 16), (byte) (i >>> 8), (byte) i});
                byte[] u = mac.doFinal(), t = u.clone();
                for (int k = 1; k < iterations; k++) {
                    u = mac.doFinal(u);
                    for (int j = 0; j < t.length; j++) t[j] ^= u[j];
                }
                System.arraycopy(t, 0, out, (i - 1) * 32, Math.min(32, len - (i - 1) * 32));
            }
            return out;
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    private static int r32(int a, int b) {
        return (a << b) | (a >>> (32 - b));
    }

    private static void salsa8(int[] b, int off) {
        int[] x = new int[16];
        System.arraycopy(b, off, x, 0, 16);
        for (int i = 0; i < 8; i += 2) {
            x[4] ^= r32(x[0] + x[12], 7); x[8] ^= r32(x[4] + x[0], 9); x[12] ^= r32(x[8] + x[4], 13); x[0] ^= r32(x[12] + x[8], 18);
            x[9] ^= r32(x[5] + x[1], 7); x[13] ^= r32(x[9] + x[5], 9); x[1] ^= r32(x[13] + x[9], 13); x[5] ^= r32(x[1] + x[13], 18);
            x[14] ^= r32(x[10] + x[6], 7); x[2] ^= r32(x[14] + x[10], 9); x[6] ^= r32(x[2] + x[14], 13); x[10] ^= r32(x[6] + x[2], 18);
            x[3] ^= r32(x[15] + x[11], 7); x[7] ^= r32(x[3] + x[15], 9); x[11] ^= r32(x[7] + x[3], 13); x[15] ^= r32(x[11] + x[7], 18);
            x[1] ^= r32(x[0] + x[3], 7); x[2] ^= r32(x[1] + x[0], 9); x[3] ^= r32(x[2] + x[1], 13); x[0] ^= r32(x[3] + x[2], 18);
            x[6] ^= r32(x[5] + x[4], 7); x[7] ^= r32(x[6] + x[5], 9); x[4] ^= r32(x[7] + x[6], 13); x[5] ^= r32(x[4] + x[7], 18);
            x[11] ^= r32(x[10] + x[9], 7); x[8] ^= r32(x[11] + x[10], 9); x[9] ^= r32(x[8] + x[11], 13); x[10] ^= r32(x[9] + x[8], 18);
            x[12] ^= r32(x[15] + x[14], 7); x[13] ^= r32(x[12] + x[15], 9); x[14] ^= r32(x[13] + x[12], 13); x[15] ^= r32(x[14] + x[13], 18);
        }
        for (int i = 0; i < 16; i++) b[off + i] += x[i];
    }

    private static void blockMix(int[] b, int[] y, int r) {
        int[] x = new int[16];
        System.arraycopy(b, (2 * r - 1) * 16, x, 0, 16);
        for (int i = 0; i < 2 * r; i++) {
            for (int k = 0; k < 16; k++) x[k] ^= b[i * 16 + k];
            salsa8(x, 0);
            System.arraycopy(x, 0, y, i * 16, 16);
        }
        for (int i = 0; i < r; i++) System.arraycopy(y, (2 * i) * 16, b, i * 16, 16);
        for (int i = 0; i < r; i++) System.arraycopy(y, (2 * i + 1) * 16, b, (r + i) * 16, 16);
    }

    static byte[] scrypt(byte[] pw, byte[] salt, int n, int r, int p, int len) {
        byte[] bb = pbkdf2(pw, salt, 1, p * 128 * r);
        int words = 32 * r;
        int[] x = new int[words], y = new int[words], v = new int[words * n];
        for (int part = 0; part < p; part++) {
            int base = part * 128 * r;
            for (int i = 0; i < words; i++)
                x[i] = (bb[base + i * 4] & 0xff) | (bb[base + i * 4 + 1] & 0xff) << 8 | (bb[base + i * 4 + 2] & 0xff) << 16 | (bb[base + i * 4 + 3] & 0xff) << 24;
            for (int i = 0; i < n; i++) {
                System.arraycopy(x, 0, v, i * words, words);
                blockMix(x, y, r);
            }
            for (int i = 0; i < n; i++) {
                int j = x[(2 * r - 1) * 16] & (n - 1);
                for (int k = 0; k < words; k++) x[k] ^= v[j * words + k];
                blockMix(x, y, r);
            }
            for (int i = 0; i < words; i++) {
                bb[base + i * 4] = (byte) x[i];
                bb[base + i * 4 + 1] = (byte) (x[i] >>> 8);
                bb[base + i * 4 + 2] = (byte) (x[i] >>> 16);
                bb[base + i * 4 + 3] = (byte) (x[i] >>> 24);
            }
        }
        return pbkdf2(pw, bb, 1, len);
    }

    static byte[] key(String password, String kdfLine) {
        String[] k = kdfLine.split(":");
        byte[] salt = unhex(k[1]), pw = utf8(password);
        return "scrypt".equals(k[0]) ? scrypt(pw, salt, 1 << 15, 8, 1, 32) : pbkdf2(pw, salt, 600_000, 32);
    }

    // ---------- export
    /** Writes a full .arckadprofile backup. Returns {groups, messages, files}. */
    static int[] export(ChatEngine e, OutputStream out, String password, boolean withFiles) throws Exception {
        byte[] salt = random(16);
        byte[] key = key(password, "scrypt:" + hex(salt));
        JSONObject contacts = new JSONObject(e.contacts.toString());
        contacts.remove("link");
        contacts.remove("pin_phone");
        JSONObject groups = new JSONObject(), msgs = new JSONObject();
        int nMsgs = 0;
        for (Map.Entry<String, JSONObject> g : e.groups.entrySet()) Obj.put(groups, g.getKey(), new JSONObject(g.getValue().toString()));
        for (Map.Entry<String, List<JSONObject>> m : e.msgs.entrySet()) {
            JSONArray a = new JSONArray();
            for (JSONObject x : new ArrayList<>(m.getValue())) a.put(x);
            nMsgs += a.length();
            Obj.put(msgs, m.getKey(), a);
        }
        JSONObject data = new Obj().putOpt("format", 1).putOpt("made", ChatEngine.now()).putOpt("app", ChatEngine.version)
                .putOpt("device_id", e.me).putOpt("device_name", e.myName()).putOpt("identity", e.identity())
                .putOpt("groups", groups).putOpt("msgs", msgs).putOpt("contacts", contacts)
                .putOpt("photo", b64(e.photoBytes())).putOpt("settings", new JSONObject());
        int nFiles = 0;
        try (ZipOutputStream z = new ZipOutputStream(out)) {
            z.setComment("ARCKAD-D PROFILE 1");
            put(z, "README.txt", utf8("Arckad-D profile (encrypted): identity, friends, groups and chats.\nRestore it in Arckad-D: "
                    + "Chat → Restore from a backup (phone) or ⋯ → Import a profile (PC).\n"));
            put(z, "kdf", utf8("scrypt:" + hex(salt)));
            put(z, "chat.enc", seal(key, utf8(data.toString())));
            if (withFiles) for (Map.Entry<String, JSONObject> g : e.groups.entrySet()) {
                JSONObject files = g.getValue().optJSONObject("files");
                if (files == null) continue;
                for (Iterator<String> it = files.keys(); it.hasNext(); ) {
                    String fid = it.next();
                    File f = new File(files.optString(fid));
                    if (!f.isFile()) continue;
                    z.putNextEntry(new ZipEntry("files/" + g.getKey() + "/" + fid));
                    Stream cipher = new Stream(hm(key, "backup-file", g.getKey(), fid));
                    javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
                    mac.init(new javax.crypto.spec.SecretKeySpec(hm(key, "backup-file-mac", g.getKey(), fid), "HmacSHA256"));
                    byte[] buf = new byte[1 << 18];
                    try (InputStream in = new FileInputStream(f)) {
                        int n;
                        while ((n = in.read(buf)) > 0) {
                            byte[] enc = cipher.apply(buf, 0, n);
                            mac.update(enc);
                            z.write(enc);
                        }
                    }
                    z.write(mac.doFinal());
                    z.closeEntry();
                    nFiles++;
                }
            }
        }
        return new int[]{groups.length(), nMsgs, nFiles};
    }

    private static void put(ZipOutputStream z, String name, byte[] data) throws Exception {
        ZipEntry ze = new ZipEntry(name);
        ze.setMethod(ZipEntry.STORED);
        ze.setSize(data.length);
        java.util.zip.CRC32 crc = new java.util.zip.CRC32();
        crc.update(data);
        ze.setCrc(crc.getValue());
        z.putNextEntry(ze);
        z.write(data);
        z.closeEntry();
    }

    // ---------- restore
    /** {data, key} from a backup file; throws with a readable message for a wrong password or a damaged file. */
    static Object[] read(File zipFile, String password) throws Exception {
        String kdf;
        byte[] blob;
        try (ZipFile z = new ZipFile(zipFile)) {
            ZipEntry k = z.getEntry("kdf"), c = z.getEntry("chat.enc");
            if (k == null || c == null) throw new IllegalArgumentException("This isn't an Arckad-D backup, or it's damaged.");
            try (InputStream in = z.getInputStream(k)) {
                kdf = new String(ChatEngine.readStream(in, 1000), StandardCharsets.UTF_8).trim();
            }
            try (InputStream in = z.getInputStream(c)) {
                blob = ChatEngine.readStream(in, 500_000_000);
            }
        } catch (java.util.zip.ZipException ex) {
            throw new IllegalArgumentException("This isn't an Arckad-D backup, or it's damaged.");
        }
        byte[] key = key(password, kdf);
        JSONObject data;
        try {
            data = new JSONObject(new String(unseal(key, blob), StandardCharsets.UTF_8));
        } catch (IllegalArgumentException ex) {
            throw new IllegalArgumentException("Wrong password.");
        }
        if (data.optInt("format") != 1) throw new IllegalArgumentException("This backup was made by a newer Arckad-D. Update first.");
        return new Object[]{data, key};
    }

    /** This phone becomes the backed-up account (its current profile is saved first). Restarts the engine. */
    static int[] restore(ChatEngine e, File zipFile, JSONObject data, byte[] key) throws Exception {
        e.link.saveSafetyCopy("before restoring a backup");
        e.stop();
        File[] old = e.dir.listFiles();
        if (old != null) for (File f : old) if (f.isFile()) f.delete();
        JSONObject groups = data.optJSONObject("groups"), msgs = data.optJSONObject("msgs");
        int nMsgs = 0, nFiles = 0;
        for (Iterator<String> it = groups.keys(); it.hasNext(); ) ChatEngine.put(groups.optJSONObject(it.next()), "files", new JSONObject());
        if (msgs != null) for (Iterator<String> it = msgs.keys(); it.hasNext(); ) {
            String gid = it.next();
            JSONArray a = msgs.optJSONArray(gid);
            StringBuilder b = new StringBuilder();
            for (int i = 0; i < a.length(); i++) b.append(a.optJSONObject(i).toString()).append('\n');
            nMsgs += a.length();
            ChatEngine.writeFile(new File(e.dir, gid + ".jsonl"), utf8(b.toString()));
        }
        try (ZipFile z = new ZipFile(zipFile)) {
            for (Enumeration<? extends ZipEntry> en = z.entries(); en.hasMoreElements(); ) {
                ZipEntry ze = en.nextElement();
                String[] parts = ze.getName().split("/");
                if (parts.length != 3 || !"files".equals(parts[0]) || !groups.has(parts[1])) continue;
                String gid = parts[1], fid = parts[2], name = fid;
                JSONArray a = msgs == null ? null : msgs.optJSONArray(gid);
                if (a != null) for (int i = 0; i < a.length(); i++) {
                    JSONObject f = a.optJSONObject(i).optJSONObject("file");
                    if (f != null && fid.equals(f.optString("id"))) name = new File(f.optString("name", fid)).getName();
                }
                String gname = groups.optJSONObject(gid).optString("name", "Group").replaceAll("[^\\p{L}\\p{N} ._()-]", "_").trim();
                File folder = new File(new File(e.downloads, "Arckad-D Chat"), gname.isEmpty() ? "Group" : gname);
                folder.mkdirs();
                File dest = Fs.unique(new File(folder, name));
                Stream cipher = new Stream(hm(key, "backup-file", gid, fid));
                javax.crypto.Mac mac = javax.crypto.Mac.getInstance("HmacSHA256");
                mac.init(new javax.crypto.spec.SecretKeySpec(hm(key, "backup-file-mac", gid, fid), "HmacSHA256"));
                long left = ze.getSize() - 32;
                byte[] buf = new byte[1 << 18];
                try (InputStream in = z.getInputStream(ze); FileOutputStream o = new FileOutputStream(dest)) {
                    while (left > 0) {
                        int n = in.read(buf, 0, (int) Math.min(buf.length, left));
                        if (n < 0) break;
                        mac.update(buf, 0, n);
                        o.write(cipher.apply(buf, 0, n));
                        left -= n;
                    }
                    byte[] tag = ChatEngine.readStream(in, 32);
                    if (left != 0 || !same(tag, mac.doFinal())) {
                        dest.delete();
                        continue;
                    }
                }
                Obj.put(groups.optJSONObject(gid).optJSONObject("files"), fid, dest.getAbsolutePath());
                e.ui.fileSaved(dest);
                nFiles++;
            }
        }
        JSONObject contacts = data.optJSONObject("contacts");
        if (contacts == null) contacts = new JSONObject();
        contacts.remove("link");
        ChatEngine.writeJson(new File(e.dir, "contacts.json"), contacts);
        ChatEngine.writeJson(new File(e.dir, "groups.json"), new Obj().putOpt("groups", groups));
        ChatEngine.writeJson(new File(e.dir, "identity.json"), data.optJSONObject("identity"));
        byte[] photo = unb64(data.optString("photo"));
        if (photo.length > 0) ChatEngine.writeFile(e.photoFile(), photo);
        e.ui.relinked(data.optString("device_id"));
        return new int[]{groups.length(), nMsgs, nFiles};
    }

}

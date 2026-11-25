package io.github.tamiltimon.arckadd;

import android.util.Base64;

import org.json.JSONObject;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.util.Iterator;

/** Sends a file from the phone to the linked PC (📷 scans, 📸 camera photos): in pieces, over the encrypted
 *  linked-devices connection, only on the same local network. */
final class ToPc {
    static final int CHUNK = 2 * 1024 * 1024;

    private ToPc() {
    }

    /** The linked PC that is online on this network, or null. */
    static String pc(ChatLink link) {
        JSONObject tw = link.twins();
        for (Iterator<String> it = tw.keys(); it.hasNext(); ) {
            String inst = it.next();
            JSONObject t = tw.optJSONObject(inst);
            if (t != null && link.twinOnline(inst) && ChatLink.isLocal(t.optString("ip"))
                    && !t.optString("os").toLowerCase().startsWith("android")) return inst;
        }
        return null;
    }

    /** True when the PC has the whole file. */
    static boolean send(ChatLink link, File f, String kind, String name, long takenMs) throws Exception {
        String inst = pc(link);
        if (inst == null) throw new java.io.IOException("Your PC isn't online on this Wi-Fi");
        long total = f.length();
        String id = Long.toHexString(System.nanoTime()) + Integer.toHexString(name.hashCode() & 0xffff);
        byte[] buf = new byte[CHUNK];
        long off = 0;
        try (InputStream in = new FileInputStream(f)) {
            while (off < total) {
                int n = 0, r;
                while (n < CHUNK && (r = in.read(buf, n, CHUNK - n)) > 0) n += r;
                if (n <= 0) break;
                byte[] part = n == CHUNK ? buf : java.util.Arrays.copyOf(buf, n);
                JSONObject req = new Obj().putOpt("kind", kind).putOpt("id", id).putOpt("name", name)
                        .putOpt("off", off).putOpt("total", total).putOpt("taken", takenMs)
                        .putOpt("data", Base64.encodeToString(part, Base64.NO_WRAP));
                JSONObject res = link.call(inst, "/t/phone/upload", req, 120_000);
                if (!res.optBoolean("ok")) throw new java.io.IOException(res.optString("reason", "refused"));
                off += n;
            }
        }
        return true;
    }
}

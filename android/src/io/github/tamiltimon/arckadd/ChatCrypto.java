package io.github.tamiltimon.arckadd;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Iterator;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;

/** Encryption, key exchange and signatures for chat. Byte-for-byte the same as the desktop app (arckad-d.py),
 *  so a phone and a computer can talk to each other. No Android classes here: it's tested on a computer too. */
final class ChatCrypto {
    static final SecureRandom RNG = new SecureRandom();
    /** RFC 3526 group 14 (2048-bit safe prime), same as the desktop. */
    static final BigInteger P = new BigInteger(
            "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DD"
                    + "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
                    + "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
                    + "83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
                    + "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
                    + "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16);
    private static final BigInteger E = BigInteger.valueOf(65537);
    private static final byte[] SHA256_PREFIX = unhex("3031300d060960864801650304020105000420");

    private ChatCrypto() {
    }

    // ---------- basics
    static byte[] utf8(String s) {
        return s.getBytes(StandardCharsets.UTF_8);
    }

    static String hex(byte[] b) {
        StringBuilder s = new StringBuilder(b.length * 2);
        for (byte x : b) s.append(Character.forDigit((x >> 4) & 15, 16)).append(Character.forDigit(x & 15, 16));
        return s.toString();
    }

    static byte[] unhex(String s) {
        byte[] out = new byte[s.length() / 2];
        for (int i = 0; i < out.length; i++) out[i] = (byte) Integer.parseInt(s.substring(i * 2, i * 2 + 2), 16);
        return out;
    }

    static byte[] concat(byte[]... parts) {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        for (byte[] p : parts) b.write(p, 0, p.length);
        return b.toByteArray();
    }

    static byte[] sha256(byte[]... parts) {
        try {
            MessageDigest d = MessageDigest.getInstance("SHA-256");
            for (byte[] p : parts) d.update(p);
            return d.digest();
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    static String sha256hex(String s) {
        return hex(sha256(utf8(s)));
    }

    static byte[] hmac(byte[] key, byte[] msg) {
        try {
            Mac m = Mac.getInstance("HmacSHA256");
            m.init(new SecretKeySpec(key, "HmacSHA256"));
            return m.doFinal(msg);
        } catch (Exception e) {
            throw new IllegalStateException(e);
        }
    }

    /** Like the desktop's _hm(key, *parts): the parts joined with "|" (text as UTF-8, bytes as they are). */
    static byte[] hm(byte[] key, Object... parts) {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        for (int i = 0; i < parts.length; i++) {
            if (i > 0) b.write('|');
            byte[] p = parts[i] instanceof byte[] ? (byte[]) parts[i] : utf8(String.valueOf(parts[i]));
            b.write(p, 0, p.length);
        }
        return hmac(key, b.toByteArray());
    }

    static boolean same(byte[] a, byte[] b) {
        return MessageDigest.isEqual(a, b);
    }

    static boolean same(String a, String b) {
        return a != null && b != null && MessageDigest.isEqual(utf8(a), utf8(b));
    }

    static byte[] random(int n) {
        byte[] b = new byte[n];
        RNG.nextBytes(b);
        return b;
    }

    static String token(int bytes) {
        return hex(random(bytes));
    }

    static byte[] fixed(BigInteger v, int len) {
        byte[] raw = v.toByteArray();
        byte[] out = new byte[len];
        int copy = Math.min(raw.length, len);
        System.arraycopy(raw, raw.length - copy, out, len - copy, copy);
        return out;
    }

    // ---------- the stream cipher: SHA-256(key ‖ nonce ‖ counter) keystream
    static final class Stream {
        private final MessageDigest base;
        private long counter;
        private byte[] left = new byte[0];

        Stream(byte[] key, byte[] nonce) {
            try {
                base = MessageDigest.getInstance("SHA-256");
            } catch (Exception e) {
                throw new IllegalStateException(e);
            }
            base.update(key);
            base.update(nonce);
        }

        Stream(byte[] key) {
            this(key, new byte[16]);
        }

        byte[] apply(byte[] data) {
            return apply(data, 0, data.length);
        }

        byte[] apply(byte[] data, int off, int n) {
            byte[] out = new byte[n];
            int i = 0;
            while (i < n) {
                if (left.length == 0) {
                    try {
                        MessageDigest h = (MessageDigest) base.clone();
                        byte[] c = new byte[8];
                        for (int k = 0; k < 8; k++) c[k] = (byte) (counter >>> (56 - 8 * k));
                        left = h.digest(c);
                        counter++;
                    } catch (CloneNotSupportedException e) {
                        throw new IllegalStateException(e);
                    }
                }
                int take = Math.min(left.length, n - i);
                for (int k = 0; k < take; k++) out[i + k] = (byte) (data[off + i + k] ^ left[k]);
                byte[] rest = new byte[left.length - take];
                System.arraycopy(left, take, rest, 0, rest.length);
                left = rest;
                i += take;
            }
            return out;
        }
    }

    /** Encrypt + authenticate a small message: nonce ‖ ciphertext ‖ tag. */
    static byte[] seal(byte[] key, byte[] data) {
        byte[] nonce = random(16);
        byte[] ct = new Stream(hm(key, "seal-enc", nonce), nonce).apply(data);
        byte[] tag = hmac(hm(key, "seal-mac", nonce), concat(nonce, ct));
        return concat(nonce, ct, tag);
    }

    static byte[] unseal(byte[] key, byte[] blob) {
        if (blob.length < 48) throw new IllegalArgumentException("message too short");
        byte[] nonce = java.util.Arrays.copyOfRange(blob, 0, 16);
        byte[] ct = java.util.Arrays.copyOfRange(blob, 16, blob.length - 32);
        byte[] tag = java.util.Arrays.copyOfRange(blob, blob.length - 32, blob.length);
        if (!same(tag, hmac(hm(key, "seal-mac", nonce), concat(nonce, ct))))
            throw new IllegalArgumentException("message not from the paired device");
        return new Stream(hm(key, "seal-enc", nonce), nonce).apply(ct);
    }

    // ---------- Diffie-Hellman (keys made on both sides, never sent)
    static BigInteger dhSecret() {
        return new BigInteger(320, RNG);
    }

    static BigInteger dhPublic(BigInteger x) {
        return BigInteger.valueOf(2).modPow(x, P);
    }

    static byte[] dhShared(String theirHex, BigInteger x) {
        BigInteger theirs = new BigInteger(theirHex, 16);
        if (theirs.compareTo(BigInteger.ONE) <= 0 || theirs.compareTo(P.subtract(BigInteger.ONE)) >= 0)
            throw new IllegalArgumentException("bad key");
        return fixed(theirs.modPow(x, P), 256);
    }

    // ---------- per-person signatures: RSA-2048, RSASSA-PKCS1-v1_5 with SHA-256 (same keys as the desktop)
    static JSONObject rsaGenerate() throws Exception {
        while (true) {
            BigInteger p = BigInteger.probablePrime(1024, RNG), q = BigInteger.probablePrime(1024, RNG);
            if (p.equals(q)) continue;
            BigInteger n = p.multiply(q);
            if (n.bitLength() != 2048) continue;
            BigInteger phi = p.subtract(BigInteger.ONE).multiply(q.subtract(BigInteger.ONE));
            BigInteger d;
            try {
                d = E.modInverse(phi);
            } catch (ArithmeticException e) {
                continue;
            }
            return new JSONObject().put("n", n.toString(16)).put("d", d.toString(16))
                    .put("p", p.toString(16)).put("q", q.toString(16));
        }
    }

    private static byte[] emsa(byte[] data, int k) {
        byte[] t = concat(SHA256_PREFIX, sha256(data));
        byte[] out = new byte[k];
        out[1] = 1;
        for (int i = 2; i < k - t.length - 1; i++) out[i] = (byte) 0xff;
        System.arraycopy(t, 0, out, k - t.length, t.length);
        return out;
    }

    static String rsaSign(JSONObject key, byte[] data) {
        BigInteger n = new BigInteger(key.optString("n"), 16), d = new BigInteger(key.optString("d"), 16);
        BigInteger p = new BigInteger(key.optString("p"), 16), q = new BigInteger(key.optString("q"), 16);
        int k = (n.bitLength() + 7) / 8;
        BigInteger m = new BigInteger(1, emsa(data, k));
        BigInteger sp = m.modPow(d.mod(p.subtract(BigInteger.ONE)), p);
        BigInteger sq = m.modPow(d.mod(q.subtract(BigInteger.ONE)), q);
        BigInteger s = sq.add(q.multiply(q.modInverse(p).multiply(sp.subtract(sq)).mod(p)));
        return hex(fixed(s, k));
    }

    static boolean rsaVerify(String nHex, byte[] data, String sigHex) {
        try {
            BigInteger n = new BigInteger(nHex, 16), s = new BigInteger(sigHex, 16);
            int k = (n.bitLength() + 7) / 8;
            if (s.signum() <= 0 || s.compareTo(n) >= 0) return false;
            return same(fixed(s.modPow(E, n), k), emsa(data, k));
        } catch (Exception e) {
            return false;
        }
    }

    // ---------- JSON written exactly like Python's json.dumps(..., ensure_ascii=False, separators=(",", ":"))
    static String pyJson(Object v) {
        StringBuilder b = new StringBuilder();
        pyJson(b, v);
        return b.toString();
    }

    private static void pyJson(StringBuilder b, Object v) {
        if (v == null || v == JSONObject.NULL) {
            b.append("null");
        } else if (v instanceof Boolean) {
            b.append(((Boolean) v) ? "true" : "false");
        } else if (v instanceof Integer || v instanceof Long) {
            b.append(v.toString());
        } else if (v instanceof Double || v instanceof Float) {
            double d = ((Number) v).doubleValue();
            b.append(d == Math.rint(d) && Math.abs(d) < 1e16 ? String.format(java.util.Locale.ROOT, "%.1f", d) : Double.toString(d));
        } else if (v instanceof Number) {
            b.append(v.toString());
        } else if (v instanceof JSONArray) {
            JSONArray a = (JSONArray) v;
            b.append('[');
            for (int i = 0; i < a.length(); i++) {
                if (i > 0) b.append(',');
                pyJson(b, a.opt(i));
            }
            b.append(']');
        } else if (v instanceof Object[]) {
            Object[] a = (Object[]) v;
            b.append('[');
            for (int i = 0; i < a.length; i++) {
                if (i > 0) b.append(',');
                pyJson(b, a[i]);
            }
            b.append(']');
        } else if (v instanceof JSONObject) {
            JSONObject o = (JSONObject) v;
            b.append('{');
            Iterator<String> it = o.keys();
            boolean first = true;
            while (it.hasNext()) {
                String k = it.next();
                if (!first) b.append(',');
                first = false;
                pyJson(b, k);
                b.append(':');
                pyJson(b, o.opt(k));
            }
            b.append('}');
        } else {
            String s = v.toString();
            b.append('"');
            for (int i = 0; i < s.length(); i++) {
                char c = s.charAt(i);
                switch (c) {
                    case '"': b.append("\\\""); break;
                    case '\\': b.append("\\\\"); break;
                    case '\n': b.append("\\n"); break;
                    case '\r': b.append("\\r"); break;
                    case '\t': b.append("\\t"); break;
                    case '\b': b.append("\\b"); break;
                    case '\f': b.append("\\f"); break;
                    default:
                        if (c < 0x20) b.append(String.format(java.util.Locale.ROOT, "\\u%04x", (int) c));
                        else b.append(c);
                }
            }
            b.append('"');
        }
    }

    // ---------- Base64 (standard, with padding; java.util.Base64 needs Android 8, Arckad-D supports 7)
    private static final char[] B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/".toCharArray();

    static String b64(byte[] d) {
        StringBuilder s = new StringBuilder((d.length + 2) / 3 * 4);
        for (int i = 0; i < d.length; i += 3) {
            int b = (d[i] & 0xff) << 16 | (i + 1 < d.length ? (d[i + 1] & 0xff) << 8 : 0) | (i + 2 < d.length ? d[i + 2] & 0xff : 0);
            s.append(B64[b >> 18 & 63]).append(B64[b >> 12 & 63])
                    .append(i + 1 < d.length ? B64[b >> 6 & 63] : '=').append(i + 2 < d.length ? B64[b & 63] : '=');
        }
        return s.toString();
    }

    static byte[] unb64(String s) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        int buf = 0, bits = 0;
        for (char c : s.toCharArray()) {
            int v = c >= 'A' && c <= 'Z' ? c - 'A' : c >= 'a' && c <= 'z' ? c - 'a' + 26 : c >= '0' && c <= '9' ? c - '0' + 52
                    : c == '+' ? 62 : c == '/' ? 63 : -1;
            if (v < 0) continue;
            buf = buf << 6 | v;
            bits += 6;
            if (bits >= 8) {
                bits -= 8;
                out.write(buf >> bits & 0xff);
            }
        }
        return out.toByteArray();
    }

    /** Python's round(): halves go to the even number (so both apps get the same milliseconds). */
    static long pyRound(double x) {
        return (long) Math.rint(x);
    }
}

package io.github.tamiltimon.arckadd;

import java.nio.charset.StandardCharsets;

/**
 * A small QR code encoder: byte mode, error correction level L, versions 1–6 (up to 134 bytes) –
 * plenty for a share link. Returns modules[y][x] (true = dark), or null if the text is too long.
 */
final class Qr {
    private Qr() {
    }

    // version -> {total codewords, ec codewords per block, number of blocks}   (level L)
    private static final int[][] TABLE = {{0, 0, 0}, {26, 7, 1}, {44, 10, 1}, {70, 15, 1}, {100, 20, 1},
            {134, 26, 1}, {172, 18, 2}};

    static boolean[][] encode(String text) {
        byte[] data = text.getBytes(StandardCharsets.UTF_8);
        for (int v = 1; v <= 6; v++) {
            int dataCw = TABLE[v][0] - TABLE[v][1] * TABLE[v][2];
            if (4 + 8 + data.length * 8 <= dataCw * 8) return build(v, data, dataCw);
        }
        return null;
    }

    private static boolean[][] modules, isFunc;
    private static int size;

    private static synchronized boolean[][] build(int ver, byte[] data, int dataCw) {
        // ---- bit stream: byte mode, length, data, terminator, padding
        int[] bits = new int[dataCw * 8];
        int n = 0;
        n = put(bits, n, 0b0100, 4);
        n = put(bits, n, data.length, 8);
        for (byte b : data) n = put(bits, n, b & 0xFF, 8);
        n = put(bits, n, 0, Math.min(4, bits.length - n));
        while (n % 8 != 0) n = put(bits, n, 0, 1);
        byte[] cw = new byte[dataCw];
        for (int i = 0; i < n / 8; i++) {
            int v = 0;
            for (int k = 0; k < 8; k++) v = (v << 1) | bits[i * 8 + k];
            cw[i] = (byte) v;
        }
        for (int i = n / 8, pad = 0; i < dataCw; i++, pad ^= 1) cw[i] = (byte) (pad == 0 ? 0xEC : 0x11);

        // ---- error correction, interleaved (all blocks have the same length for these versions)
        int blocks = TABLE[ver][2], ecLen = TABLE[ver][1], per = dataCw / blocks;
        byte[] div = rsDivisor(ecLen);
        byte[][] dBlocks = new byte[blocks][], eBlocks = new byte[blocks][];
        for (int b = 0; b < blocks; b++) {
            dBlocks[b] = new byte[per];
            System.arraycopy(cw, b * per, dBlocks[b], 0, per);
            eBlocks[b] = rsRemainder(dBlocks[b], div);
        }
        byte[] all = new byte[TABLE[ver][0]];
        int k = 0;
        for (int i = 0; i < per; i++) for (int b = 0; b < blocks; b++) all[k++] = dBlocks[b][i];
        for (int i = 0; i < ecLen; i++) for (int b = 0; b < blocks; b++) all[k++] = eBlocks[b][i];

        // ---- matrix
        size = ver * 4 + 17;
        modules = new boolean[size][size];
        isFunc = new boolean[size][size];
        for (int i = 0; i < size; i++) {
            setF(6, i, i % 2 == 0);
            setF(i, 6, i % 2 == 0);
        }
        finder(3, 3);
        finder(size - 4, 3);
        finder(3, size - 4);
        if (ver >= 2) {
            int p = size - 7;
            for (int dy = -2; dy <= 2; dy++)
                for (int dx = -2; dx <= 2; dx++) setF(p + dx, p + dy, Math.max(Math.abs(dx), Math.abs(dy)) != 1);
        }
        format(0);                                      // reserve the format areas
        int i = 0;
        for (int right = size - 1; right >= 1; right -= 2) {
            if (right == 6) right = 5;
            for (int vert = 0; vert < size; vert++) {
                for (int j = 0; j < 2; j++) {
                    int x = right - j;
                    boolean up = ((right + 1) & 2) == 0;
                    int y = up ? size - 1 - vert : vert;
                    if (!isFunc[y][x] && i < all.length * 8) {
                        modules[y][x] = ((all[i >>> 3] >>> (7 - (i & 7))) & 1) != 0;
                        i++;
                    }
                }
            }
        }
        int best = 0;
        long bestPen = Long.MAX_VALUE;
        for (int m = 0; m < 8; m++) {
            mask(m);
            format(m);
            long pen = penalty();
            if (pen < bestPen) {
                bestPen = pen;
                best = m;
            }
            mask(m);
        }
        mask(best);
        format(best);
        boolean[][] out = modules;
        modules = null;
        isFunc = null;
        return out;
    }

    private static int put(int[] bits, int n, int value, int len) {
        for (int i = len - 1; i >= 0; i--) bits[n++] = (value >>> i) & 1;
        return n;
    }

    private static void setF(int x, int y, boolean dark) {
        modules[y][x] = dark;
        isFunc[y][x] = true;
    }

    private static void finder(int x, int y) {
        for (int dy = -4; dy <= 4; dy++)
            for (int dx = -4; dx <= 4; dx++) {
                int d = Math.max(Math.abs(dx), Math.abs(dy)), xx = x + dx, yy = y + dy;
                if (xx >= 0 && xx < size && yy >= 0 && yy < size) setF(xx, yy, d != 2 && d != 4);
            }
    }

    private static void format(int mask) {
        int data = 1 << 3 | mask;                     // level L = 01
        int rem = data;
        for (int i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
        int bits = (data << 10 | rem) ^ 0x5412;
        for (int i = 0; i <= 5; i++) setF(8, i, bit(bits, i));
        setF(8, 7, bit(bits, 6));
        setF(8, 8, bit(bits, 7));
        setF(7, 8, bit(bits, 8));
        for (int i = 9; i < 15; i++) setF(14 - i, 8, bit(bits, i));
        for (int i = 0; i < 8; i++) setF(size - 1 - i, 8, bit(bits, i));
        for (int i = 8; i < 15; i++) setF(8, size - 15 + i, bit(bits, i));
        setF(8, size - 8, true);
    }

    private static boolean bit(int x, int i) {
        return ((x >>> i) & 1) != 0;
    }

    private static void mask(int m) {
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++) {
                if (isFunc[y][x]) continue;
                boolean inv;
                switch (m) {
                    case 0: inv = (x + y) % 2 == 0; break;
                    case 1: inv = y % 2 == 0; break;
                    case 2: inv = x % 3 == 0; break;
                    case 3: inv = (x + y) % 3 == 0; break;
                    case 4: inv = (x / 3 + y / 2) % 2 == 0; break;
                    case 5: inv = x * y % 2 + x * y % 3 == 0; break;
                    case 6: inv = (x * y % 2 + x * y % 3) % 2 == 0; break;
                    default: inv = ((x + y) % 2 + x * y % 3) % 2 == 0; break;
                }
                if (inv) modules[y][x] = !modules[y][x];
            }
    }

    /** Simplified penalty (long runs, 2×2 blocks, dark/light balance): picks a clean-looking mask. */
    private static long penalty() {
        long p = 0;
        for (int pass = 0; pass < 2; pass++)
            for (int a = 0; a < size; a++) {
                int run = 1;
                for (int b = 1; b < size; b++) {
                    boolean cur = pass == 0 ? modules[a][b] : modules[b][a];
                    boolean prev = pass == 0 ? modules[a][b - 1] : modules[b - 1][a];
                    if (cur == prev) {
                        run++;
                        if (run == 5) p += 3;
                        else if (run > 5) p++;
                    } else run = 1;
                }
            }
        int dark = 0;
        for (int y = 0; y < size; y++)
            for (int x = 0; x < size; x++) {
                if (modules[y][x]) dark++;
                if (x < size - 1 && y < size - 1) {
                    boolean c = modules[y][x];
                    if (c == modules[y][x + 1] && c == modules[y + 1][x] && c == modules[y + 1][x + 1]) p += 3;
                }
            }
        int total = size * size;
        p += (Math.abs(dark * 20 - total * 10) + total - 1) / total * 10L;
        return p;
    }

    private static byte[] rsDivisor(int degree) {
        byte[] r = new byte[degree];
        r[degree - 1] = 1;
        int root = 1;
        for (int i = 0; i < degree; i++) {
            for (int j = 0; j < r.length; j++) {
                r[j] = (byte) mul(r[j] & 0xFF, root);
                if (j + 1 < r.length) r[j] ^= r[j + 1];
            }
            root = mul(root, 0x02);
        }
        return r;
    }

    private static byte[] rsRemainder(byte[] data, byte[] div) {
        byte[] r = new byte[div.length];
        for (byte b : data) {
            int f = (b ^ r[0]) & 0xFF;
            System.arraycopy(r, 1, r, 0, r.length - 1);
            r[r.length - 1] = 0;
            for (int i = 0; i < r.length; i++) r[i] ^= (byte) mul(div[i] & 0xFF, f);
        }
        return r;
    }

    private static int mul(int x, int y) {
        int z = 0;
        for (int i = 7; i >= 0; i--) {
            z = (z << 1) ^ ((z >>> 7) * 0x11D);
            z ^= ((y >>> i) & 1) * x;
        }
        return z;
    }
}

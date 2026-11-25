package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Matrix;
import android.graphics.Paint;
import android.graphics.pdf.PdfDocument;
import android.media.ExifInterface;
import android.net.Uri;
import android.provider.MediaStore;

import java.io.File;
import java.io.FileOutputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** 📷 Scan to PC: photograph paper pages with the camera; each page is turned upright and cleaned up (white
 *  paper, dark text), the pages become one PDF, and it goes to the linked PC's scans folder. */
final class Scanner {
    static final int REQ = 7710;
    private static final List<File> pages = new ArrayList<>();
    private static File pending;
    private static boolean colour;

    private Scanner() {
    }

    static File dir(Activity a) {
        File d = new File(a.getCacheDir(), "scan");
        d.mkdirs();
        return d;
    }

    static void start(MainActivity a) {
        if (ChatHub.get(a).engine == null || ToPc.pc(ChatHub.get(a).engine.link) == null) {
            Ui.dialog(a).setTitle("📷 Scan to PC").setMessage("Your PC needs to be on, running Arckad-D, on the same Wi-Fi, "
                    + "and linked to this phone (⋮ → Linked devices).").setPositiveButton("OK", null).show();
            return;
        }
        if (pages.isEmpty()) {
            for (File f : dir(a).listFiles()) f.delete();          // a fresh scan
        }
        shoot(a);
    }

    private static void shoot(MainActivity a) {
        pending = new File(dir(a), "page-" + (pages.size() + 1) + "-" + System.currentTimeMillis() + ".jpg");
        Uri out = Provider.uriFor(pending);
        Intent i = new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT, out)
                .addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION | Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            a.startActivityForResult(i, REQ);
        } catch (Exception ex) {
            Ui.toast(a, "No camera app found");
        }
    }

    static void onResult(MainActivity a, int result) {
        if (result != Activity.RESULT_OK || pending == null || !pending.isFile() || pending.length() == 0) {
            if (!pages.isEmpty()) ask(a);
            return;
        }
        pages.add(pending);
        pending = null;
        ask(a);
    }

    private static void ask(MainActivity a) {
        int n = pages.size();
        String[] modes = {"📄 Black & white document (clean, small)", "🎨 Colour (photos, stamps, signatures)"};
        Ui.dialog(a).setTitle("📷 " + n + " page" + (n == 1 ? "" : "s") + " scanned")
                .setSingleChoiceItems(modes, colour ? 1 : 0, (d, w) -> colour = w == 1)
                .setPositiveButton("Send to PC", (d, w) -> finish(a))
                .setNeutralButton("＋ Another page", (d, w) -> shoot(a))
                .setNegativeButton("Cancel", (d, w) -> pages.clear())
                .setCancelable(false).show();
    }

    private static void finish(MainActivity a) {
        final List<File> todo = new ArrayList<>(pages);
        final boolean col = colour;
        pages.clear();
        Ui.toast(a, "📷 Making the PDF and sending it to your PC…");
        new Thread(() -> {
            String msg;
            try {
                String name = "Scan " + new SimpleDateFormat("yyyy-MM-dd HH.mm", Locale.US).format(new Date()) + ".pdf";
                File pdf = new File(dir(a), name);
                makePdf(todo, col, pdf);
                ToPc.send(ChatHub.get(a).engine.link, pdf, "scan", name, System.currentTimeMillis());
                msg = "✓ " + name + " is on your PC";
                for (File f : dir(a).listFiles()) f.delete();
            } catch (Exception ex) {
                msg = "Couldn't send the scan: " + ex.getMessage();
            }
            final String m = msg;
            a.runOnUiThread(() -> Ui.toast(a, m));
        }).start();
    }

    /** A page photo, the right way up, at most ~1800 px on its long side. */
    static Bitmap load(File f) throws Exception {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getPath(), o);
        int s = 1;
        while (Math.max(o.outWidth, o.outHeight) / (s * 2) >= 1800) s *= 2;
        o = new BitmapFactory.Options();
        o.inSampleSize = s;
        Bitmap b = BitmapFactory.decodeFile(f.getPath(), o);
        if (b == null) throw new java.io.IOException("unreadable photo");
        int rot = 0;
        switch (new ExifInterface(f.getPath()).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1)) {
            case ExifInterface.ORIENTATION_ROTATE_90: rot = 90; break;
            case ExifInterface.ORIENTATION_ROTATE_180: rot = 180; break;
            case ExifInterface.ORIENTATION_ROTATE_270: rot = 270; break;
            default: break;
        }
        float k = Math.min(1f, 1800f / Math.max(b.getWidth(), b.getHeight()));
        if (rot != 0 || k < 1f) {
            Matrix m = new Matrix();
            m.postScale(k, k);
            m.postRotate(rot);
            Bitmap r = Bitmap.createBitmap(b, 0, 0, b.getWidth(), b.getHeight(), m, true);
            if (r != b) b.recycle();
            b = r;
        }
        return b;
    }

    /** Paper becomes white and text dark: stretch from the darkest ink to the paper's brightness. */
    static Bitmap clean(Bitmap src, boolean colour) {
        int w = src.getWidth(), h = src.getHeight();
        int[] px = new int[w * h];
        src.getPixels(px, 0, w, 0, 0, w, h);
        int[] hist = new int[256];
        for (int i = 0; i < px.length; i += 3) {
            int c = px[i];
            hist[((c >> 16 & 255) * 77 + (c >> 8 & 255) * 150 + (c & 255) * 29) >> 8]++;
        }
        int total = 0;
        for (int v : hist) total += v;
        int lo = 0, hi = 255, acc = 0;
        for (int v = 0; v < 256; v++) {
            acc += hist[v];
            if (acc >= total * 0.02) { lo = v; break; }
        }
        acc = 0;
        for (int v = 255; v >= 0; v--) {
            acc += hist[v];
            if (acc >= total * 0.30) { hi = v; break; }      // the paper: the bright majority
        }
        if (hi - lo < 30) { lo = 0; hi = 255; }
        float span = hi - lo;
        for (int i = 0; i < px.length; i++) {
            int c = px[i];
            int r = c >> 16 & 255, g = c >> 8 & 255, b = c & 255;
            if (colour) {
                r = cl((r - lo) * 255f / span);
                g = cl((g - lo) * 255f / span);
                b = cl((b - lo) * 255f / span);
            } else {
                float y = ((r * 77 + g * 150 + b * 29) >> 8);
                float v = (y - lo) / span;
                v = v < 0 ? 0 : v > 1 ? 1 : v;
                v = (float) Math.pow(v, 1.6);                      // darker text, whiter paper
                r = g = b = cl(v * 255f);
            }
            px[i] = 0xff000000 | r << 16 | g << 8 | b;
        }
        Bitmap out = Bitmap.createBitmap(w, h, Bitmap.Config.ARGB_8888);
        out.setPixels(px, 0, w, 0, 0, w, h);
        return out;
    }

    private static int cl(float v) {
        return v < 0 ? 0 : v > 255 ? 255 : (int) v;
    }

    static void makePdf(List<File> photos, boolean colour, File out) throws Exception {
        PdfDocument doc = new PdfDocument();
        try {
            int no = 1;
            for (File f : photos) {
                Bitmap b = clean(load(f), colour);
                boolean land = b.getWidth() > b.getHeight();
                int pw = land ? 842 : 595, ph = land ? 595 : 842;     // A4 in points
                PdfDocument.Page page = doc.startPage(new PdfDocument.PageInfo.Builder(pw, ph, no++).create());
                Canvas cv = page.getCanvas();
                float k = Math.min(pw / (float) b.getWidth(), ph / (float) b.getHeight());
                Matrix m = new Matrix();
                m.postScale(k, k);
                m.postTranslate((pw - b.getWidth() * k) / 2, (ph - b.getHeight() * k) / 2);
                cv.drawColor(0xffffffff);
                cv.drawBitmap(b, m, new Paint(Paint.FILTER_BITMAP_FLAG));
                doc.finishPage(page);
                b.recycle();
            }
            try (OutputStream o = new FileOutputStream(out)) {
                doc.writeTo(o);
            }
        } finally {
            doc.close();
        }
    }
}

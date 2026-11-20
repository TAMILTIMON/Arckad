package io.github.tamiltimon.arckadd;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.drawable.Drawable;
import android.graphics.pdf.PdfRenderer;
import android.media.ExifInterface;
import android.media.ThumbnailUtils;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.provider.MediaStore;
import android.util.LruCache;
import android.util.Size;
import android.widget.ImageView;

import java.io.File;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Small pictures for the file list: photos, video frames, PDF first pages and app icons. */
final class Thumbs {
    private static final Handler main = new Handler(Looper.getMainLooper());
    private static final ExecutorService pool = Executors.newFixedThreadPool(3);
    private static final LruCache<String, Bitmap> cache = new LruCache<String, Bitmap>(
            (int) Math.min(48L * 1024 * 1024, Runtime.getRuntime().maxMemory() / 6)) {
        @Override
        protected int sizeOf(String k, Bitmap b) {
            return b.getByteCount();
        }
    };
    private static final Bitmap NONE = Bitmap.createBitmap(1, 1, Bitmap.Config.ALPHA_8);

    private Thumbs() {
    }

    static boolean has(Fs.Entry e) {
        return !e.dir && (e.kind.equals("Images") || e.kind.equals("Videos") || e.kind.equals("Apps")
                || e.ext.equals("pdf"));
    }

    /** Shows a thumbnail in the ImageView when ready; returns false if there is none (yet). */
    static boolean load(Context c, Fs.Entry e, ImageView view, int px) {
        final String key = e.f.getAbsolutePath() + "|" + e.mod + "|" + px;
        view.setTag(key);
        Bitmap hit = cache.get(key);
        if (hit != null) {
            if (hit == NONE) {
                view.setImageDrawable(null);
                view.setBackground(null);
                return false;
            }
            show(view, hit);
            return true;
        }
        view.setImageDrawable(null);
        view.setBackground(null);
        final Context app = c.getApplicationContext();
        pool.execute(() -> {
            if (!key.equals(view.getTag())) return;              // scrolled away already
            Bitmap b = null;
            try {
                b = make(app, e, px);
            } catch (Throwable ignored) {
            }
            cache.put(key, b != null ? b : NONE);
            final Bitmap result = b;
            main.post(() -> {
                if (key.equals(view.getTag()) && result != null) show(view, result);
            });
        });
        return false;
    }

    /** The picture covers the emoji icon underneath it. */
    private static void show(ImageView v, Bitmap b) {
        v.setBackground(Ui.round(Ui.CARD, Ui.dp(v.getContext(), 8)));
        v.setImageBitmap(b);
    }

    static Bitmap make(Context c, Fs.Entry e, int px) throws Exception {
        String path = e.f.getAbsolutePath();
        switch (e.kind) {
            case "Images":
                return decode(path, px, px);
            case "Videos":
                if (android.os.Build.VERSION.SDK_INT >= 29) {
                    return ThumbnailUtils.createVideoThumbnail(e.f, new Size(px, px), null);
                }
                //noinspection deprecation
                return ThumbnailUtils.createVideoThumbnail(path, MediaStore.Images.Thumbnails.MINI_KIND);
            case "Apps": {
                PackageManager pm = c.getPackageManager();
                PackageInfo pi = pm.getPackageArchiveInfo(path, 0);
                if (pi == null) return null;
                ApplicationInfo ai = pi.applicationInfo;
                ai.sourceDir = path;
                ai.publicSourceDir = path;
                return draw(ai.loadIcon(pm), px);
            }
            default:
                if (e.ext.equals("pdf")) return pdfPage(e.f, 0, px);
                return null;
        }
    }

    /** Decodes a photo no bigger than about w × h, upright (EXIF rotation applied). */
    static Bitmap decode(String path, int w, int h) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(path, o);
        if (o.outWidth <= 0) return null;
        int s = 1;
        while (o.outWidth / (s * 2) >= w && o.outHeight / (s * 2) >= h) s *= 2;
        o = new BitmapFactory.Options();
        o.inSampleSize = s;
        Bitmap b = BitmapFactory.decodeFile(path, o);
        if (b == null) return null;
        int deg = 0;
        try {
            int ori = new ExifInterface(path).getAttributeInt(ExifInterface.TAG_ORIENTATION, 1);
            deg = ori == 6 ? 90 : ori == 3 ? 180 : ori == 8 ? 270 : 0;
        } catch (Exception ignored) {
        }
        if (deg != 0) {
            Matrix m = new Matrix();
            m.postRotate(deg);
            b = Bitmap.createBitmap(b, 0, 0, b.getWidth(), b.getHeight(), m, true);
        }
        return b;
    }

    static Bitmap pdfPage(File f, int index, int width) throws Exception {
        try (ParcelFileDescriptor fd = ParcelFileDescriptor.open(f, ParcelFileDescriptor.MODE_READ_ONLY);
             PdfRenderer r = new PdfRenderer(fd)) {
            if (r.getPageCount() == 0) return null;
            try (PdfRenderer.Page p = r.openPage(index)) {
                int h = Math.max(1, width * p.getHeight() / Math.max(1, p.getWidth()));
                Bitmap b = Bitmap.createBitmap(width, h, Bitmap.Config.ARGB_8888);
                b.eraseColor(Color.WHITE);
                p.render(b, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                return b;
            }
        }
    }

    static Bitmap draw(Drawable d, int px) {
        Bitmap b = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(b);
        d.setBounds(0, 0, px, px);
        d.draw(c);
        return b;
    }
}

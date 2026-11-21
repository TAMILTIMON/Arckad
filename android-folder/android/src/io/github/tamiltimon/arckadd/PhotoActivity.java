package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.util.DisplayMetrics;
import android.util.LruCache;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Full-screen photo viewer: swipe between the photos of a folder, pinch / double-tap to zoom. */
public class PhotoActivity extends Activity {
    static void open(Context c, ArrayList<String> paths, int index) {
        c.startActivity(new Intent(c, PhotoActivity.class).putStringArrayListExtra("paths", paths)
                .putExtra("index", index).addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION));
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService pool = Executors.newFixedThreadPool(2);
    private final Set<Integer> loading = new HashSet<>();
    private LruCache<Integer, Bitmap> cache;
    private ArrayList<String> paths;
    private PhotoPager pager;
    private LinearLayout top, bottom;
    private TextView title, counter;
    private int maxW, maxH;

    @Override
    protected void onCreate(Bundle b) {
        Ui.apply(this);
        super.onCreate(b);
        getWindow().setStatusBarColor(Color.BLACK);
        getWindow().setNavigationBarColor(Color.BLACK);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        paths = getIntent().getStringArrayListExtra("paths");
        if (paths == null || paths.isEmpty()) {
            finish();
            return;
        }
        DisplayMetrics dm = getResources().getDisplayMetrics();
        maxW = Math.min(4096, dm.widthPixels * 2);
        maxH = Math.min(4096, dm.heightPixels * 2);
        cache = new LruCache<Integer, Bitmap>((int) Math.min(96L * 1024 * 1024, Runtime.getRuntime().maxMemory() / 3)) {
            @Override
            protected int sizeOf(Integer k, Bitmap v) {
                return v.getByteCount();
            }
        };
        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        pager = new PhotoPager(this);
        root.addView(pager, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        top = bar(Gravity.TOP);
        top.addView(icon("←", "Back", v -> finish()));
        title = Ui.text(this, "", 16, Color.WHITE, true);
        title.setSingleLine(true);
        title.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);
        top.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        counter = Ui.text(this, "", 14, 0xCCFFFFFF, false);
        counter.setPadding(Ui.dp(this, 8), 0, Ui.dp(this, 12), 0);
        top.addView(counter);
        root.addView(top, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP));

        bottom = bar(Gravity.BOTTOM);
        bottom.setGravity(Gravity.CENTER);
        bottom.addView(action("↗", "Share", v -> Android.share(this, list(current()))));
        bottom.addView(action("📂", "Open with", v -> Android.openWith(this, current())));
        bottom.addView(action("📡", "Send", v -> {
            MainActivity.queueSend(list(current()));
            startActivity(new Intent(this, MainActivity.class).putExtra("tab", "send")
                    .addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NO_ANIMATION));
            finish();
        }));
        bottom.addView(action("ℹ", "Details", v -> details()));
        bottom.addView(action("🗑", "Delete", v -> delete()));
        root.addView(bottom, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM));
        setContentView(root);

        pager.setSource(new PhotoPager.Source() {
            @Override
            public int count() {
                return paths.size();
            }

            @Override
            public Bitmap get(int i) {
                Bitmap bm = cache.get(i);
                if (bm == null) load(i);
                return bm;
            }
        }, new PhotoPager.Listener() {
            @Override
            public void onPage(int i) {
                File f = new File(paths.get(i));
                title.setText(f.getName());
                counter.setText((i + 1) + " / " + paths.size());
                load(i + 1);
                load(i - 1);
            }

            @Override
            public void onTap() {
                boolean show = top.getVisibility() != View.VISIBLE;
                top.setVisibility(show ? View.VISIBLE : View.GONE);
                bottom.setVisibility(show ? View.VISIBLE : View.GONE);
            }
        });
        pager.post(() -> pager.show(getIntent().getIntExtra("index", 0)));
    }

    private LinearLayout bar(int gravity) {
        LinearLayout l = new LinearLayout(this);
        l.setOrientation(LinearLayout.HORIZONTAL);
        l.setGravity(Gravity.CENTER_VERTICAL);
        l.setBackgroundColor(0x99000000);
        int p = Ui.dp(this, 4);
        l.setPadding(p, p, p, p);
        return l;
    }

    private TextView icon(String g, String desc, View.OnClickListener l) {
        TextView t = Ui.icon(this, g, desc, l);
        t.setTextColor(Color.WHITE);
        return t;
    }

    private View action(String g, String label, View.OnClickListener l) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        box.setBackground(Ui.ripple(this));
        box.setOnClickListener(l);
        int p = Ui.dp(this, 6);
        box.setPadding(p, p, p, p);
        TextView ic = Ui.text(this, g, 20, Color.WHITE, false);
        ic.setGravity(Gravity.CENTER);
        TextView lb = Ui.text(this, label, 11, 0xDDFFFFFF, false);
        lb.setGravity(Gravity.CENTER);
        box.addView(ic);
        box.addView(lb);
        box.setLayoutParams(new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        return box;
    }

    private File current() {
        return new File(paths.get(pager.index()));
    }

    private static ArrayList<File> list(File f) {
        ArrayList<File> l = new ArrayList<>();
        l.add(f);
        return l;
    }

    private void load(final int i) {
        if (i < 0 || i >= paths.size() || cache.get(i) != null || loading.contains(i)) return;
        loading.add(i);
        final String path = paths.get(i);
        pool.execute(() -> {
            Bitmap bm = null;
            try {
                bm = Thumbs.decode(path, maxW / 2, maxH / 2);
            } catch (Throwable ignored) {
            }
            final Bitmap result = bm;
            main.post(() -> {
                loading.remove(i);
                if (result != null) cache.put(i, result);
                pager.invalidate();
            });
        });
    }

    private void details() {
        File f = current();
        Ui.info(this, f.getName(), "Size: " + Fs.size(f.length()) + "\nModified: " + Fs.when(f.lastModified())
                + "\nFolder: " + Fs.shortPath(f.getParentFile()));
    }

    private void delete() {
        final File f = current();
        Ui.confirm(this, "Delete this photo?", f.getName() + "\n\nThis can't be undone.", "Delete", () -> {
            if (!Fs.delete(f)) {
                Ui.toast(this, "Couldn't delete it");
                return;
            }
            Android.mediaScan(this, f);
            int i = pager.index();
            paths.remove(i);
            cache.evictAll();
            loading.clear();
            if (paths.isEmpty()) {
                finish();
                return;
            }
            pager.show(Math.min(i, paths.size() - 1));
        });
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_DPAD_RIGHT || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN) {
            pager.step(1);
            return true;
        }
        if (keyCode == KeyEvent.KEYCODE_DPAD_LEFT || keyCode == KeyEvent.KEYCODE_VOLUME_UP) {
            pager.step(-1);
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public void finish() {
        super.finish();
        overridePendingTransition(0, 0);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        pool.shutdownNow();
        if (cache != null) cache.evictAll();
    }
}

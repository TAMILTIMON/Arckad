package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.pdf.PdfRenderer;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.ParcelFileDescriptor;
import android.util.LruCache;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AbsListView;
import android.widget.BaseAdapter;
import android.widget.FrameLayout;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Built-in PDF reader (Android's own PdfRenderer): scroll through pages, pinch or +/− to zoom. */
public class PdfActivity extends Activity {
    static void open(Context c, File f) {
        c.startActivity(new Intent(c, PdfActivity.class).putExtra("path", f.getAbsolutePath())
                .addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION));
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService worker = Executors.newSingleThreadExecutor();   // PdfRenderer is single-threaded
    private final Set<String> pending = new HashSet<>();
    private final List<float[]> sizes = new ArrayList<>();     // page width, height (points)
    private LruCache<String, Bitmap> cache;
    private ParcelFileDescriptor fd;
    private PdfRenderer renderer;
    private File file;
    private ListView list;
    private HorizontalScrollView hscroll;
    private TextView pageLabel;
    private ProgressBar busy;
    private float zoom = 1f;
    private int baseWidth;
    private final Adapter adapter = new Adapter();

    @Override
    protected void onCreate(Bundle b) {
        Ui.apply(this);
        super.onCreate(b);
        file = new File(getIntent().getStringExtra("path"));
        cache = new LruCache<String, Bitmap>((int) Math.min(64L * 1024 * 1024, Runtime.getRuntime().maxMemory() / 4)) {
            @Override
            protected int sizeOf(String k, Bitmap v) {
                return v.getByteCount();
            }
        };
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Ui.dark ? 0xFF2A2B30 : 0xFFE4E4E8);

        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Ui.BAR);
        bar.addView(Ui.icon(this, "←", "Back", v -> finish()));
        TextView title = Ui.text(this, file.getName(), 16, Ui.TEXT, true);
        title.setSingleLine(true);
        title.setEllipsize(android.text.TextUtils.TruncateAt.MIDDLE);
        bar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        bar.addView(Ui.icon(this, "−", "Zoom out", v -> setZoom(zoom / 1.5f)));
        bar.addView(Ui.icon(this, "+", "Zoom in", v -> setZoom(zoom * 1.5f)));
        bar.addView(Ui.icon(this, "↗", "Share", v -> {
            ArrayList<File> l = new ArrayList<>();
            l.add(file);
            Android.share(this, l);
        }));
        bar.addView(Ui.icon(this, "⋮", "Open with", v -> Android.openWith(this, file)));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 56)));

        FrameLayout area = new PinchFrame(this);
        hscroll = new HorizontalScrollView(this);
        hscroll.setFillViewport(true);
        list = new ListView(this);
        list.setDivider(null);
        list.setDividerHeight(0);
        list.setSelector(android.R.color.transparent);
        list.setAdapter(adapter);
        list.setOnScrollListener(new AbsListView.OnScrollListener() {
            @Override
            public void onScrollStateChanged(AbsListView v, int s) {
            }

            @Override
            public void onScroll(AbsListView v, int first, int visible, int total) {
                if (total > 0) pageLabel.setText((first + 1) + " / " + total);
            }
        });
        hscroll.addView(list, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        area.addView(hscroll);
        pageLabel = Ui.text(this, "", 13, Color.WHITE, true);
        pageLabel.setBackground(Ui.round(0xAA000000, Ui.dp(this, 14)));
        pageLabel.setPadding(Ui.dp(this, 12), Ui.dp(this, 5), Ui.dp(this, 12), Ui.dp(this, 5));
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL);
        lp.bottomMargin = Ui.dp(this, 16);
        area.addView(pageLabel, lp);
        busy = new ProgressBar(this);
        area.addView(busy, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER));
        root.addView(area, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(root);

        worker.execute(() -> {
            String err = null;
            List<float[]> s = new ArrayList<>();
            try {
                fd = ParcelFileDescriptor.open(file, ParcelFileDescriptor.MODE_READ_ONLY);
                renderer = new PdfRenderer(fd);
                for (int i = 0; i < renderer.getPageCount(); i++) {
                    try (PdfRenderer.Page p = renderer.openPage(i)) {
                        s.add(new float[]{p.getWidth(), p.getHeight()});
                    }
                }
            } catch (SecurityException e) {
                err = "This PDF is password-protected. Use “Open with” to read it in another app.";
            } catch (Exception e) {
                err = "This PDF can't be opened (" + e.getMessage() + ").";
            }
            final String error = err;
            main.post(() -> {
                busy.setVisibility(View.GONE);
                if (error != null) {
                    Ui.info(this, "Can't show this PDF", error);
                    return;
                }
                sizes.addAll(s);
                baseWidth = list.getWidth() > 0 ? list.getWidth() : getResources().getDisplayMetrics().widthPixels;
                adapter.notifyDataSetChanged();
                pageLabel.setText("1 / " + sizes.size());
            });
        });
    }

    private void setZoom(float z) {
        z = Math.max(1f, Math.min(4f, z));
        if (Math.abs(z - zoom) < 0.01f || sizes.isEmpty()) return;
        int first = list.getFirstVisiblePosition();
        View v = list.getChildAt(0);
        float within = v == null ? 0 : (float) -v.getTop() / Math.max(1, v.getHeight());
        float hFrac = hscroll.getScrollX() / (float) Math.max(1, pageWidth());
        zoom = z;
        ViewGroup.LayoutParams lp = list.getLayoutParams();
        lp.width = zoom > 1.001f ? pageWidth() : ViewGroup.LayoutParams.MATCH_PARENT;
        list.setLayoutParams(lp);
        adapter.notifyDataSetChanged();
        list.post(() -> {
            list.setSelectionFromTop(first, -(int) (within * pageHeight(first)));
            hscroll.scrollTo((int) (hFrac * pageWidth()), 0);
        });
    }

    private int pageWidth() {
        return (int) (baseWidth * zoom);
    }

    private int pageHeight(int i) {
        float[] s = sizes.get(i);
        return (int) (pageWidth() * s[1] / Math.max(1, s[0]));
    }

    private void render(final int i, final int w, final ImageView into) {
        final int rw = Math.min(w, 2600);                            // keep memory sensible when zoomed far in
        final String key = i + "|" + rw;
        Bitmap hit = cache.get(key);
        if (hit != null) {
            into.setImageBitmap(hit);
            return;
        }
        into.setImageDrawable(null);
        if (!pending.add(key)) return;
        worker.execute(() -> {
            Bitmap bm = null;
            if (renderer != null && Math.abs(i - list.getFirstVisiblePosition()) < 6) {
                try (PdfRenderer.Page p = renderer.openPage(i)) {
                    int h = Math.max(1, rw * p.getHeight() / Math.max(1, p.getWidth()));
                    bm = Bitmap.createBitmap(rw, h, Bitmap.Config.ARGB_8888);
                    bm.eraseColor(Color.WHITE);
                    p.render(bm, null, null, PdfRenderer.Page.RENDER_MODE_FOR_DISPLAY);
                } catch (Throwable ignored) {
                    bm = null;
                }
            }
            final Bitmap result = bm;
            main.post(() -> {
                pending.remove(key);
                if (result != null) {
                    cache.put(key, result);
                    adapter.notifyDataSetChanged();
                }
            });
        });
    }

    private final class Adapter extends BaseAdapter {
        @Override
        public int getCount() {
            return sizes.size();
        }

        @Override
        public Object getItem(int i) {
            return i;
        }

        @Override
        public long getItemId(int i) {
            return i;
        }

        @Override
        public View getView(int i, View convert, ViewGroup parent) {
            ImageView iv = convert instanceof ImageView ? (ImageView) convert : new ImageView(PdfActivity.this);
            iv.setScaleType(ImageView.ScaleType.FIT_XY);
            iv.setBackgroundColor(Color.WHITE);
            int w = pageWidth(), h = pageHeight(i);
            iv.setLayoutParams(new AbsListView.LayoutParams(w, h + Ui.dp(PdfActivity.this, 0)));
            iv.setPadding(0, 0, 0, Ui.dp(PdfActivity.this, 6));
            iv.setCropToPadding(true);
            render(i, w, iv);
            return iv;
        }
    }

    /** Lets two fingers zoom the pages (a live preview while pinching, sharp re-render after). */
    private final class PinchFrame extends FrameLayout {
        private final ScaleGestureDetector det;
        private float live = 1f;

        PinchFrame(Context c) {
            super(c);
            det = new ScaleGestureDetector(c, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
                @Override
                public boolean onScaleBegin(ScaleGestureDetector d) {
                    live = 1f;
                    hscroll.setPivotX(d.getFocusX());
                    hscroll.setPivotY(d.getFocusY());
                    return true;
                }

                @Override
                public boolean onScale(ScaleGestureDetector d) {
                    live = Math.max(1f / zoom, Math.min(4f / zoom, live * d.getScaleFactor()));
                    hscroll.setScaleX(live);
                    hscroll.setScaleY(live);
                    return true;
                }

                @Override
                public void onScaleEnd(ScaleGestureDetector d) {
                    hscroll.setScaleX(1f);
                    hscroll.setScaleY(1f);
                    setZoom(zoom * live);
                }
            });
        }

        @Override
        public boolean onInterceptTouchEvent(MotionEvent e) {
            det.onTouchEvent(e);
            return e.getPointerCount() > 1 || det.isInProgress();
        }

        @Override
        public boolean onTouchEvent(MotionEvent e) {
            det.onTouchEvent(e);
            return true;
        }
    }

    @Override
    public void finish() {
        super.finish();
        overridePendingTransition(0, 0);
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        worker.execute(() -> {
            try {
                if (renderer != null) renderer.close();
                if (fd != null) fd.close();
            } catch (Exception ignored) {
            }
        });
        worker.shutdown();
        cache.evictAll();
    }
}

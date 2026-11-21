package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Context;
import android.graphics.Typeface;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.AbsListView;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/** List rows / grid tiles for files, and what happens when you tap a file. */
final class Rows {
    private Rows() {
    }

    static final class Holder {
        TextView glyph, name, sub, check;
        ImageView thumb;
        boolean tile, header;
    }

    static View row(Context c, View convert, Fs.Entry e, String sub, boolean selectMode, boolean selected) {
        Holder h = convert != null && convert.getTag() instanceof Holder && !((Holder) convert.getTag()).tile
                && !((Holder) convert.getTag()).header ? (Holder) convert.getTag() : null;
        View v = convert;
        if (h == null) {
            h = new Holder();
            LinearLayout l = new LinearLayout(c);
            l.setOrientation(LinearLayout.HORIZONTAL);
            l.setGravity(Gravity.CENTER_VERTICAL);
            int p = Ui.dp(c, 14);
            l.setPadding(p, Ui.dp(c, 8), p, Ui.dp(c, 8));
            l.setMinimumHeight(Ui.dp(c, 64));
            FrameLayout box = new FrameLayout(c);
            h.glyph = Ui.text(c, "", 24, Ui.TEXT, false);
            h.glyph.setGravity(Gravity.CENTER);
            box.addView(h.glyph, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            h.thumb = new ImageView(c);
            h.thumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
            h.thumb.setClipToOutline(true);
            box.addView(h.thumb, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            int s = Ui.dp(c, 46);
            l.addView(box, new LinearLayout.LayoutParams(s, s));
            LinearLayout texts = new LinearLayout(c);
            texts.setOrientation(LinearLayout.VERTICAL);
            texts.setPadding(Ui.dp(c, 14), 0, Ui.dp(c, 8), 0);
            h.name = Ui.text(c, "", 15, Ui.TEXT, false);
            h.name.setSingleLine(true);
            h.name.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            h.sub = Ui.text(c, "", 12, Ui.DIM, false);
            h.sub.setSingleLine(true);
            h.sub.setEllipsize(TextUtils.TruncateAt.END);
            texts.addView(h.name);
            texts.addView(h.sub);
            l.addView(texts, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
            h.check = Ui.text(c, "", 20, Ui.ACCENT, true);
            l.addView(h.check);
            l.setTag(h);
            v = l;
        }
        fill(c, h, e, Ui.dp(c, 96));
        h.name.setText(e.name);
        h.sub.setText(sub);
        h.check.setVisibility(selectMode ? View.VISIBLE : View.GONE);
        h.check.setText(selected ? "✔" : "○");
        h.check.setTextColor(selected ? Ui.ACCENT : Ui.DIM);
        v.setBackgroundColor(selected ? Ui.SEL : 0);
        return v;
    }

    static View tile(Context c, View convert, Fs.Entry e, boolean selected) {
        Holder h = convert != null && convert.getTag() instanceof Holder && ((Holder) convert.getTag()).tile
                ? (Holder) convert.getTag() : null;
        View v = convert;
        if (h == null) {
            h = new Holder();
            h.tile = true;
            LinearLayout l = new LinearLayout(c);
            l.setOrientation(LinearLayout.VERTICAL);
            l.setGravity(Gravity.CENTER_HORIZONTAL);
            int p = Ui.dp(c, 4);
            l.setPadding(p, p, p, p);
            FrameLayout box = new FrameLayout(c);
            h.glyph = Ui.text(c, "", 40, Ui.TEXT, false);
            h.glyph.setGravity(Gravity.CENTER);
            box.addView(h.glyph, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            h.thumb = new ImageView(c);
            h.thumb.setScaleType(ImageView.ScaleType.CENTER_CROP);
            h.thumb.setClipToOutline(true);
            box.addView(h.thumb, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            h.check = Ui.text(c, "", 18, Ui.ACCENT, true);
            FrameLayout.LayoutParams cl = new FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.TOP | Gravity.END);
            box.addView(h.check, cl);
            l.addView(box, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(c, 96)));
            h.name = Ui.text(c, "", 12, Ui.TEXT, false);
            h.name.setGravity(Gravity.CENTER_HORIZONTAL);
            h.name.setMaxLines(2);
            h.name.setEllipsize(TextUtils.TruncateAt.MIDDLE);
            l.addView(h.name, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(c, 34)));
            l.setTag(h);
            v = l;
        }
        fill(c, h, e, Ui.dp(c, 160));
        h.name.setText(e.name);
        h.check.setText(selected ? "✔" : "");
        v.setBackground(selected ? Ui.round(Ui.SEL, Ui.dp(c, 10)) : null);
        return v;
    }

    static View header(Context c, View convert, String text) {
        TextView t;
        if (convert instanceof TextView && convert.getTag() instanceof Holder && ((Holder) convert.getTag()).header) {
            t = (TextView) convert;
        } else {
            t = Ui.text(c, "", 14, Ui.ACCENT, true);
            t.setPadding(Ui.dp(c, 16), Ui.dp(c, 14), Ui.dp(c, 16), Ui.dp(c, 6));
            Holder h = new Holder();
            h.header = true;
            t.setTag(h);
        }
        t.setText(text);
        t.setLayoutParams(new AbsListView.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        return t;
    }

    private static void fill(Context c, Holder h, Fs.Entry e, int px) {
        h.glyph.setText(Fs.glyph(e));
        if (Thumbs.has(e)) {
            h.thumb.setVisibility(View.VISIBLE);
            Thumbs.load(c, e, h.thumb, px);
        } else {
            h.thumb.setTag(null);
            h.thumb.setImageDrawable(null);
            h.thumb.setBackground(null);
            h.thumb.setVisibility(View.GONE);
        }
    }

    // ---------------------------------------------------------------- opening a file

    /** Photos, PDFs and text open inside Arckad-D; ZIPs offer extraction; APKs install; the rest goes to other apps. */
    static void open(Activity a, Fs.Entry e, List<Fs.Entry> siblings, Runnable afterChange) {
        if (e.kind.equals("Images")) {
            ArrayList<String> photos = new ArrayList<>();
            int index = 0;
            for (Fs.Entry s : siblings) {
                if (s.kind.equals("Images")) {
                    if (s.f.equals(e.f)) index = photos.size();
                    photos.add(s.f.getAbsolutePath());
                }
            }
            if (photos.isEmpty()) photos.add(e.f.getAbsolutePath());
            PhotoActivity.open(a, photos, index);
        } else if (e.ext.equals("pdf")) {
            PdfActivity.open(a, e.f);
        } else if (Fs.in(e.ext, Fs.TEXT)) {
            TextActivity.open(a, e.f);
        } else if (e.ext.equals("zip")) {
            Ui.dialog(a).setTitle(e.name).setItems(new String[]{"Extract here", "Open with another app"}, (d, w) -> {
                if (w == 0) extract(a, e.f, afterChange);
                else Android.openWith(a, e.f);
            }).show();
        } else if (e.kind.equals("Apps")) {
            Ui.dialog(a).setTitle(e.name)
                    .setMessage("To install this app, open it from your phone's own Files app (or your browser's downloads). "
                            + "Arckad-D doesn't install apps itself, which keeps it trusted by Google Play Protect.")
                    .setPositiveButton("OK", null)
                    .setNeutralButton("Share", (d, w) -> {
                        ArrayList<File> l = new ArrayList<>();
                        l.add(e.f);
                        Android.share(a, l);
                    }).show();
        } else {
            Android.openWith(a, e.f);
        }
    }

    static void extract(Activity a, File zip, Runnable after) {
        Ui.toast(a, "Extracting " + zip.getName() + "…");
        new Thread(() -> {
            String msg;
            try {
                File out = Fs.unzip(zip);
                Android.mediaScan(a, out);
                msg = "Extracted to " + out.getName();
            } catch (Exception ex) {
                msg = "Couldn't extract: " + ex.getMessage();
            }
            final String m = msg;
            a.runOnUiThread(() -> {
                Ui.toast(a, m);
                if (after != null) after.run();
            });
        }).start();
    }

    static String bold(String s) {
        return s;
    }

    static Typeface mono() {
        return Typeface.MONOSPACE;
    }
}

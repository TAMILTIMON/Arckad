package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.graphics.Typeface;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.ViewGroup;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;

/** Built-in viewer for text, code, CSV, JSON, subtitles… (first 512 KB). */
public class TextActivity extends Activity {
    static final int LIMIT = 512 * 1024;

    static void open(Context c, File f) {
        c.startActivity(new Intent(c, TextActivity.class).putExtra("path", f.getAbsolutePath())
                .addFlags(Intent.FLAG_ACTIVITY_NO_ANIMATION));
    }

    @Override
    protected void onCreate(Bundle b) {
        Ui.apply(this);
        super.onCreate(b);
        final File f = new File(getIntent().getStringExtra("path"));
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Ui.BG);
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setBackgroundColor(Ui.BAR);
        bar.addView(Ui.icon(this, "←", "Back", v -> finish()));
        TextView title = Ui.text(this, f.getName(), 16, Ui.TEXT, true);
        title.setSingleLine(true);
        bar.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        bar.addView(Ui.icon(this, "↗", "Share", v -> {
            ArrayList<File> l = new ArrayList<>();
            l.add(f);
            Android.share(this, l);
        }));
        bar.addView(Ui.icon(this, "⋮", "Open with", v -> Android.openWith(this, f)));
        root.addView(bar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 56)));
        ScrollView sv = new ScrollView(this);
        final TextView body = Ui.text(this, "Loading…", 13, Ui.TEXT, false);
        body.setTypeface(Typeface.MONOSPACE);
        body.setTextIsSelectable(true);
        int p = Ui.dp(this, 14);
        body.setPadding(p, p, p, p);
        sv.addView(body);
        root.addView(sv, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        setContentView(root);
        final Handler main = new Handler(Looper.getMainLooper());
        new Thread(() -> {
            String text;
            try (InputStream in = new FileInputStream(f)) {
                byte[] buf = new byte[LIMIT];
                int n = 0, r;
                while (n < LIMIT && (r = in.read(buf, n, LIMIT - n)) > 0) n += r;
                text = new String(buf, 0, n, StandardCharsets.UTF_8);
                if (f.length() > LIMIT) text += "\n\n… (only the first 512 KB is shown)";
            } catch (Exception e) {
                text = "Can't read this file: " + e.getMessage();
            }
            final String t = text;
            main.post(() -> body.setText(t));
        }).start();
    }

    @Override
    public void finish() {
        super.finish();
        overridePendingTransition(0, 0);
    }
}

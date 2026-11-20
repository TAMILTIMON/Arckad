package io.github.tamiltimon.arckadd;

import android.database.Cursor;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/** "Where was I?": files changed lately, newest first, grouped by day (from Android's own file index, so it's instant). */
final class RecentScreen implements MainActivity.Screen {
    private final MainActivity a;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final LinearLayout root;
    private final TextView bannerTitle, bannerSub;
    private final TextView openBtn;
    private final ListView list;
    private final List<Object> rows = new ArrayList<>();          // String = day header, Fs.Entry = file
    private final List<Fs.Entry> files = new ArrayList<>();
    private final Adapter adapter = new Adapter();
    private Fs.Entry last;
    private long loadedAt;

    RecentScreen(MainActivity a) {
        this.a = a;
        root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);
        LinearLayout banner = Ui.card(a);
        bannerTitle = Ui.text(a, "Looking for your latest work…", 16, Ui.TEXT, true);
        bannerSub = Ui.text(a, "", 13, Ui.DIM, false);
        bannerSub.setPadding(0, Ui.dp(a, 4), 0, Ui.dp(a, 10));
        openBtn = Ui.button(a, "Open it", true, v -> {
            if (last != null) Rows.open(a, last, files, null);
        });
        openBtn.setVisibility(View.GONE);
        banner.addView(bannerTitle);
        banner.addView(bannerSub);
        banner.addView(openBtn);
        LinearLayout.LayoutParams lp = Ui.matchWrap(a, 10);
        lp.leftMargin = lp.rightMargin = Ui.dp(a, 12);
        root.addView(banner, lp);
        list = new ListView(a);
        list.setDivider(null);
        list.setAdapter(adapter);
        list.setOnItemClickListener((p, v, pos, id) -> {
            Object o = rows.get(pos);
            if (o instanceof Fs.Entry) Rows.open(a, (Fs.Entry) o, files, null);
        });
        root.addView(list, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
    }

    @Override
    public View view() {
        return root;
    }

    @Override
    public void onShow() {
        if (System.currentTimeMillis() - loadedAt > 20_000) load();
    }

    @Override
    public void onHide() {
    }

    @Override
    public void topBar(LinearLayout bar) {
        bar.addView(a.title("Where was I?"), MainActivity.grow());
        bar.addView(Ui.icon(a, "⟳", "Refresh", v -> load()));
    }

    @Override
    public boolean back() {
        return false;
    }

    void load() {
        loadedAt = System.currentTimeMillis();
        new Thread(() -> {
            List<Fs.Entry> got = query();
            main.post(() -> show(got));
        }).start();
    }

    private List<Fs.Entry> query() {
        List<Fs.Entry> out = new ArrayList<>();
        long cutoff = System.currentTimeMillis() / 1000 - 14 * 86400L;
        Uri uri = MediaStore.Files.getContentUri("external");
        String[] cols = {MediaStore.MediaColumns.DATA};
        String where = MediaStore.MediaColumns.DATE_MODIFIED + ">=? AND " + MediaStore.MediaColumns.SIZE + ">0 AND "
                + MediaStore.MediaColumns.DATA + " NOT LIKE ?";
        String[] args = {String.valueOf(cutoff), "%/Android/%"};
        try (Cursor c = a.getContentResolver().query(uri, cols, where, args,
                MediaStore.MediaColumns.DATE_MODIFIED + " DESC")) {
            if (c != null) {
                while (c.moveToNext() && out.size() < 400) {
                    String p = c.getString(0);
                    if (p == null || p.contains("/.")) continue;
                    File f = new File(p);
                    if (f.isFile()) out.add(new Fs.Entry(f));
                }
            }
        } catch (Exception ignored) {
        }
        return out;
    }

    private void show(List<Fs.Entry> got) {
        files.clear();
        files.addAll(got);
        rows.clear();
        String day = null;
        for (Fs.Entry e : got) {
            String d = Fs.day(e.mod);
            if (!d.equals(day)) {
                rows.add(d);
                day = d;
            }
            rows.add(e);
        }
        adapter.notifyDataSetChanged();
        if (got.isEmpty()) {
            last = null;
            bannerTitle.setText("No recent files yet");
            bannerSub.setText("Files you change will appear here.");
            openBtn.setVisibility(View.GONE);
        } else {
            last = got.get(0);
            bannerTitle.setText("You were last working on " + last.name);
            bannerSub.setText("in " + Fs.shortPath(last.f.getParentFile()) + ", " + Fs.ago(last.mod));
            openBtn.setVisibility(View.VISIBLE);
        }
    }

    private final class Adapter extends BaseAdapter {
        @Override
        public int getCount() {
            return rows.size();
        }

        @Override
        public Object getItem(int i) {
            return rows.get(i);
        }

        @Override
        public long getItemId(int i) {
            return i;
        }

        @Override
        public int getViewTypeCount() {
            return 2;
        }

        @Override
        public int getItemViewType(int i) {
            return rows.get(i) instanceof String ? 0 : 1;
        }

        @Override
        public boolean isEnabled(int i) {
            return rows.get(i) instanceof Fs.Entry;
        }

        @Override
        public View getView(int i, View convert, ViewGroup parent) {
            Object o = rows.get(i);
            if (o instanceof String) return Rows.header(a, convert, (String) o);
            Fs.Entry e = (Fs.Entry) o;
            return Rows.row(a, convert, e, Fs.when(e.mod) + " · " + Fs.shortPath(e.f.getParentFile()), false, false);
        }
    }
}

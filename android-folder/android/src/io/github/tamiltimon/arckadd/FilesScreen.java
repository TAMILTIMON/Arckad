package io.github.tamiltimon.arckadd;

import android.content.SharedPreferences;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.InputMethodManager;
import android.widget.AbsListView;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.GridView;
import android.widget.HorizontalScrollView;
import android.widget.LinearLayout;
import android.widget.ListView;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.File;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Deque;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** The file browser. */
final class FilesScreen implements MainActivity.Screen {
    private final MainActivity a;
    private final SharedPreferences prefs;
    private final Handler main = new Handler(Looper.getMainLooper());
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final LinearLayout root;
    private final LinearLayout crumbs;
    private final HorizontalScrollView crumbScroll;
    private final LinearLayout searchBar;
    private final EditText searchBox;
    private final ListView list;
    private final GridView grid;
    private final TextView empty;
    private final ProgressBar busy;
    private final Adapter adapter = new Adapter();

    File cwd = Fs.root();
    private final Deque<File> history = new ArrayDeque<>();
    private final List<Fs.Entry> entries = new ArrayList<>();
    final LinkedHashSet<File> selected = new LinkedHashSet<>();
    boolean selectMode, searching, searchResults;
    private int seq;
    private Runnable pendingSearch;

    static final List<File> clip = new ArrayList<>();
    static boolean clipMove;

    FilesScreen(MainActivity a) {
        this.a = a;
        prefs = Ui.prefs(a);
        root = new LinearLayout(a);
        root.setOrientation(LinearLayout.VERTICAL);

        crumbScroll = new HorizontalScrollView(a);
        crumbScroll.setHorizontalScrollBarEnabled(false);
        crumbs = new LinearLayout(a);
        crumbs.setGravity(Gravity.CENTER_VERTICAL);
        crumbs.setPadding(Ui.dp(a, 8), 0, Ui.dp(a, 8), 0);
        crumbScroll.addView(crumbs);
        root.addView(crumbScroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(a, 48)));

        searchBar = new LinearLayout(a);
        searchBar.setPadding(Ui.dp(a, 12), 0, Ui.dp(a, 12), Ui.dp(a, 6));
        searchBox = new EditText(a);
        searchBox.setHint("Search here and in subfolders");
        searchBox.setSingleLine(true);
        searchBox.setTextColor(Ui.TEXT);
        searchBox.setHintTextColor(Ui.DIM);
        searchBox.setBackground(Ui.round(Ui.CARD, Ui.dp(a, 12)));
        searchBox.setPadding(Ui.dp(a, 14), Ui.dp(a, 10), Ui.dp(a, 14), Ui.dp(a, 10));
        searchBox.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int st, int c, int af) {
            }

            @Override
            public void onTextChanged(CharSequence s, int st, int b, int c) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                if (pendingSearch != null) main.removeCallbacks(pendingSearch);
                pendingSearch = () -> search(s.toString().trim());
                main.postDelayed(pendingSearch, 300);
            }
        });
        searchBar.addView(searchBox, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        searchBar.setVisibility(View.GONE);
        root.addView(searchBar);

        FrameLayout area = new FrameLayout(a);
        list = new ListView(a);
        list.setDivider(null);
        list.setFastScrollEnabled(true);
        list.setAdapter(adapter);
        grid = new GridView(a);
        grid.setColumnWidth(Ui.dp(a, 104));
        grid.setNumColumns(GridView.AUTO_FIT);
        grid.setStretchMode(GridView.STRETCH_COLUMN_WIDTH);
        grid.setVerticalSpacing(Ui.dp(a, 6));
        grid.setHorizontalSpacing(Ui.dp(a, 6));
        grid.setPadding(Ui.dp(a, 6), Ui.dp(a, 6), Ui.dp(a, 6), Ui.dp(a, 6));
        grid.setClipToPadding(false);
        grid.setAdapter(adapter);
        for (AbsListView v : new AbsListView[]{list, grid}) {
            v.setOnItemClickListener((p, view, pos, id) -> tap(pos));
            v.setOnItemLongClickListener((p, view, pos, id) -> {
                longPress(pos);
                return true;
            });
            area.addView(v, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
        empty = Ui.text(a, "", 15, Ui.DIM, false);
        empty.setGravity(Gravity.CENTER);
        area.addView(empty, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(a, 120), Gravity.CENTER));
        busy = new ProgressBar(a);
        busy.setVisibility(View.GONE);
        area.addView(busy, new FrameLayout.LayoutParams(Ui.dp(a, 40), Ui.dp(a, 40), Gravity.CENTER));
        root.addView(area, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        applyView();
    }

    @Override
    public View view() {
        return root;
    }

    @Override
    public void onShow() {
        reload();
    }

    @Override
    public void onHide() {
    }

    private boolean grid() {
        return prefs.getBoolean("grid", false);
    }

    private void applyView() {
        list.setVisibility(grid() ? View.GONE : View.VISIBLE);
        grid.setVisibility(grid() ? View.VISIBLE : View.GONE);
    }

    // ---------------------------------------------------------------- top bar
    @Override
    public void topBar(LinearLayout bar) {
        if (selectMode) {
            bar.addView(Ui.icon(a, "✕", "Cancel selection", v -> clearSelection()));
            bar.addView(a.title(String.valueOf(selected.size())), MainActivity.grow());
            bar.addView(Ui.icon(a, "📡", "Send nearby", v -> {
                MainActivity.queueSend(new ArrayList<>(selected));
                clearSelection();
                a.showTab("send");
            }));
            bar.addView(Ui.icon(a, "↗", "Share", v -> Android.share(a, new ArrayList<>(selected))));
            bar.addView(Ui.icon(a, "⧉", "Copy", v -> setClip(false)));
            bar.addView(Ui.icon(a, "✂", "Cut", v -> setClip(true)));
            bar.addView(Ui.icon(a, "⋮", "More", v -> selectionMenu()));
            return;
        }
        boolean atRoot = cwd.equals(Fs.root()) && !searching;
        if (!atRoot) bar.addView(Ui.icon(a, "←", "Back", v -> back()));
        bar.addView(a.title(atRoot ? "Arckad-D" : searching ? "Search" : cwd.getName()), MainActivity.grow());
        if (!searching) bar.addView(Ui.icon(a, "＋", "New folder or file", v -> newMenu()));
        bar.addView(Ui.icon(a, searching ? "✕" : "🔍", "Search", v -> toggleSearch()));
        bar.addView(Ui.icon(a, grid() ? "☰" : "▦", "List or grid", v -> {
            prefs.edit().putBoolean("grid", !grid()).apply();
            applyView();
            adapter.notifyDataSetChanged();
            a.refreshTopBar();
        }));
        bar.addView(Ui.icon(a, "⋮", "Menu", v -> mainMenu()));
    }

    // ---------------------------------------------------------------- loading
    void open(File dir, boolean push) {
        if (dir == null || !dir.isDirectory()) {
            Ui.toast(a, "That folder isn't available");
            return;
        }
        if (push && !dir.equals(cwd)) history.push(cwd);
        cwd = dir;
        if (searching) {
            searching = false;
            searchBar.setVisibility(View.GONE);
            searchBox.setText("");
        }
        searchResults = false;
        clearSelectionQuiet();
        reload();
        a.refreshTopBar();
    }

    void reload() {
        if (searchResults) return;
        crumbs();
        final int my = ++seq;
        final File dir = cwd;
        final boolean hidden = prefs.getBoolean("hidden", false);
        final String sort = prefs.getString("sort", "name");
        busy.setVisibility(View.VISIBLE);
        io.execute(() -> {
            final List<Fs.Entry> got = Fs.list(dir, hidden, sort);
            main.post(() -> {
                if (my != seq) return;
                show(got, dir.canRead() ? "This folder is empty" : "Can't open this folder");
                busy.setVisibility(View.GONE);
            });
        });
    }

    private void show(List<Fs.Entry> got, String emptyText) {
        entries.clear();
        entries.addAll(got);
        adapter.notifyDataSetChanged();
        empty.setText(entries.isEmpty() ? emptyText : "");
        empty.setVisibility(entries.isEmpty() ? View.VISIBLE : View.GONE);
    }

    private void crumbs() {
        crumbs.removeAllViews();
        List<File> chain = new ArrayList<>();
        File r = Fs.root();
        for (File f = cwd; f != null; f = f.getParentFile()) {
            chain.add(0, f);
            if (f.equals(r)) break;
        }
        for (int i = 0; i < chain.size(); i++) {
            final File f = chain.get(i);
            if (i > 0) crumbs.addView(Ui.text(a, "›", 16, Ui.DIM, false));
            boolean last = i == chain.size() - 1;
            TextView b = Ui.text(a, f.equals(r) ? "Internal storage" : f.getName(), 14, last ? Ui.ON_ACCENT : Ui.TEXT, last);
            b.setGravity(Gravity.CENTER);
            b.setPadding(Ui.dp(a, 12), Ui.dp(a, 6), Ui.dp(a, 12), Ui.dp(a, 6));
            b.setBackground(Ui.pressable(a, last ? Ui.ACCENT : Ui.LINE, 16));
            b.setOnClickListener(v -> open(f, true));
            LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
            lp.leftMargin = lp.rightMargin = Ui.dp(a, 3);
            crumbs.addView(b, lp);
        }
        crumbScroll.post(() -> crumbScroll.fullScroll(View.FOCUS_RIGHT));
    }

    // ---------------------------------------------------------------- search
    private void toggleSearch() {
        searching = !searching;
        searchBar.setVisibility(searching ? View.VISIBLE : View.GONE);
        InputMethodManager im = (InputMethodManager) a.getSystemService(MainActivity.INPUT_METHOD_SERVICE);
        if (searching) {
            searchBox.requestFocus();
            im.showSoftInput(searchBox, 0);
        } else {
            im.hideSoftInputFromWindow(searchBox.getWindowToken(), 0);
            searchBox.setText("");
            searchResults = false;
            reload();
        }
        a.refreshTopBar();
    }

    private void search(final String q) {
        if (!searching) return;
        if (q.length() < 2) {
            searchResults = false;
            reload();
            return;
        }
        searchResults = true;
        final int my = ++seq;
        final File start = cwd;
        final String[] words = q.toLowerCase(Locale.ROOT).split("\\s+");
        busy.setVisibility(View.VISIBLE);
        io.execute(() -> {
            List<Fs.Entry> found = new ArrayList<>();
            Deque<File> todo = new ArrayDeque<>();
            todo.push(start);
            while (!todo.isEmpty() && found.size() < 2000 && my == seq) {
                File[] kids = todo.pop().listFiles();
                if (kids == null) continue;
                for (File k : kids) {
                    String n = k.getName();
                    if (n.startsWith(".") || n.equals("Android")) continue;
                    if (k.isDirectory()) todo.push(k);
                    String low = n.toLowerCase(Locale.ROOT);
                    boolean ok = true;
                    for (String w : words) if (!low.contains(w)) ok = false;
                    if (ok) found.add(new Fs.Entry(k));
                }
            }
            Fs.sort(found, "name");
            main.post(() -> {
                if (my != seq) return;
                busy.setVisibility(View.GONE);
                show(found, "No matches");
            });
        });
    }

    // ---------------------------------------------------------------- taps & selection
    private void tap(int pos) {
        if (pos < 0 || pos >= entries.size()) return;
        Fs.Entry e = entries.get(pos);
        if (selectMode) {
            toggle(e.f);
            return;
        }
        if (e.dir) open(e.f, true);
        else Rows.open(a, e, entries, this::reload);
    }

    private void longPress(int pos) {
        if (pos < 0 || pos >= entries.size()) return;
        selectMode = true;
        toggle(entries.get(pos).f);
    }

    private void toggle(File f) {
        if (!selected.remove(f)) selected.add(f);
        if (selected.isEmpty()) selectMode = false;
        adapter.notifyDataSetChanged();
        a.refreshTopBar();
    }

    void clearSelection() {
        clearSelectionQuiet();
        adapter.notifyDataSetChanged();
        a.refreshTopBar();
    }

    private void clearSelectionQuiet() {
        selected.clear();
        selectMode = false;
    }

    private void selectAll() {
        for (Fs.Entry e : entries) selected.add(e.f);
        selectMode = !selected.isEmpty();
        adapter.notifyDataSetChanged();
        a.refreshTopBar();
    }

    // ---------------------------------------------------------------- actions
    private void setClip(boolean move) {
        clip.clear();
        clip.addAll(selected);
        clipMove = move;
        clearSelection();
        a.showPasteBar(clip.size() + (clip.size() == 1 ? " item" : " items") + " to " + (move ? "move" : "copy"));
        Ui.toast(a, "Open the destination folder, then tap Paste here");
    }

    void paste() {
        final List<File> items = new ArrayList<>(clip);
        final boolean move = clipMove;
        final File dest = cwd;
        clip.clear();
        a.hidePasteBar();
        Ui.toast(a, move ? "Moving…" : "Copying…");
        io.execute(() -> {
            int done = 0;
            List<String> errors = new ArrayList<>();
            for (File src : items) {
                if (move && dest.equals(src.getParentFile())) continue;
                if (src.isDirectory() && (dest.getAbsolutePath() + "/").startsWith(src.getAbsolutePath() + "/")) {
                    errors.add(src.getName() + ": can't put a folder inside itself");
                    continue;
                }
                File target = Fs.unique(new File(dest, src.getName()));
                try {
                    if (move) Fs.move(src, target);
                    else Fs.copy(src, target);
                    Android.mediaScan(a, target);
                    done++;
                } catch (Exception ex) {
                    errors.add(src.getName() + ": " + ex.getMessage());
                }
            }
            final int d = done;
            main.post(() -> {
                reload();
                Ui.toast(a, (move ? "Moved " : "Copied ") + d + (d == 1 ? " item" : " items")
                        + (errors.isEmpty() ? "" : " · " + errors.size() + " failed"));
                if (!errors.isEmpty()) Ui.info(a, "Some items failed", android.text.TextUtils.join("\n", errors));
            });
        });
    }

    private void selectionMenu() {
        final List<File> sel = new ArrayList<>(selected);
        boolean allZip = true;
        for (File f : sel) if (!Fs.ext(f.getName()).equals("zip")) allZip = false;
        List<String> labels = new ArrayList<>();
        List<Runnable> acts = new ArrayList<>();
        labels.add("Select all");
        acts.add(this::selectAll);
        if (sel.size() == 1) {
            labels.add("Rename");
            acts.add(() -> rename(sel.get(0)));
        }
        labels.add("Duplicate");
        acts.add(() -> duplicate(sel));
        labels.add("Compress to ZIP");
        acts.add(() -> compress(sel));
        if (allZip) {
            labels.add("Extract here");
            acts.add(() -> {
                clearSelection();
                for (File z : sel) Rows.extract(a, z, this::reload);
            });
        }
        labels.add("Delete");
        acts.add(() -> delete(sel));
        if (sel.size() == 1) {
            labels.add("Details");
            acts.add(() -> details(sel.get(0)));
        }
        Ui.dialog(a).setItems(labels.toArray(new String[0]), (d, w) -> acts.get(w).run()).show();
    }

    private void mainMenu() {
        String sort = prefs.getString("sort", "name");
        boolean hidden = prefs.getBoolean("hidden", false);
        String[] items = {
                (sort.equals("name") ? "✓ " : "") + "Sort by name",
                (sort.equals("date") ? "✓ " : "") + "Sort by date (newest first)",
                (sort.equals("size") ? "✓ " : "") + "Sort by size (largest first)",
                hidden ? "Hide hidden files" : "Show hidden files",
                "New folder",
                "New empty file",
                "Received files",
                "Theme: " + prefs.getString("theme", "system") + " (tap to change)",
                "Check for updates",
                "About Arckad-D " + BuildInfo.VERSION};
        Ui.dialog(a).setItems(items, (d, w) -> {
            switch (w) {
                case 0: setSort("name"); break;
                case 1: setSort("date"); break;
                case 2: setSort("size"); break;
                case 3:
                    prefs.edit().putBoolean("hidden", !hidden).apply();
                    reload();
                    break;
                case 4: newFolder(); break;
                case 5: newFile(); break;
                case 6: open(Fs.received(), true); break;
                case 7: a.cycleTheme(); break;
                case 8: Updater.check(a, true); break;
                default:
                    Ui.info(a, "Arckad-D " + BuildInfo.VERSION, "A file manager that remembers what you worked on.\n\n"
                            + "Send and receive files with Arckad-D on Linux, Windows and other phones on the same Wi-Fi.");
            }
        }).show();
    }

    private void setSort(String by) {
        prefs.edit().putString("sort", by).apply();
        reload();
    }

    private void newMenu() {
        Ui.dialog(a).setTitle("Create in " + (cwd.equals(Fs.root()) ? "Internal storage" : cwd.getName()))
                .setItems(new String[]{"📁  New folder", "📄  New empty file"}, (d, w) -> {
                    if (w == 0) newFolder();
                    else newFile();
                }).show();
    }

    private void newFile() {
        Ui.askText(a, "New empty file", "New file.txt", "Create", name -> {
            if (name.isEmpty() || name.contains("/")) return;
            File f = Fs.unique(new File(cwd, name));
            try {
                if (!f.createNewFile()) Ui.toast(a, "Couldn't create it here");
                else Android.mediaScan(a, f);
            } catch (java.io.IOException e) {
                Ui.toast(a, "Couldn't create it: " + e.getMessage());
            }
            reload();
        });
    }

    private void duplicate(final List<File> files) {
        clearSelection();
        io.execute(() -> {
            int n = 0;
            for (File src : files) {
                String name = src.getName(), stem = name, ext = "";
                int dot = name.lastIndexOf('.');
                if (dot > 0 && !src.isDirectory()) {
                    stem = name.substring(0, dot);
                    ext = name.substring(dot);
                }
                File t = Fs.unique(new File(src.getParentFile(), stem + " (copy)" + ext));
                try {
                    Fs.copy(src, t);
                    Android.mediaScan(a, t);
                    n++;
                } catch (Exception ignored) {
                }
            }
            final int done = n;
            main.post(() -> {
                reload();
                Ui.toast(a, "Duplicated " + done + (done == 1 ? " item" : " items"));
            });
        });
    }

    private void newFolder() {
        Ui.askText(a, "New folder", "New folder", "Create", name -> {
            if (name.isEmpty() || name.contains("/")) return;
            File f = Fs.unique(new File(cwd, name));
            if (!f.mkdirs()) Ui.toast(a, "Couldn't create it here");
            reload();
        });
    }

    private void rename(final File f) {
        Ui.askText(a, "Rename", f.getName(), "Rename", name -> {
            if (name.isEmpty() || name.equals(f.getName()) || name.contains("/")) return;
            File t = new File(f.getParentFile(), name);
            if (t.exists()) {
                Ui.toast(a, "That name is already used here");
                return;
            }
            if (!f.renameTo(t)) Ui.toast(a, "Couldn't rename it");
            else Android.mediaScan(a, f, t);
            clearSelection();
            reload();
        });
    }

    private void delete(final List<File> files) {
        StringBuilder names = new StringBuilder();
        for (int i = 0; i < Math.min(3, files.size()); i++) names.append(i > 0 ? ", " : "").append(files.get(i).getName());
        if (files.size() > 3) names.append("…");
        Ui.confirm(a, "Delete " + files.size() + (files.size() == 1 ? " item?" : " items?"),
                names + "\n\nPhones have no Trash, so this can't be undone.", "Delete", () -> io.execute(() -> {
                    int ok = 0;
                    for (File f : files) if (Fs.delete(f)) ok++;
                    Android.mediaScan(a, files.toArray(new File[0]));
                    final int n = ok;
                    main.post(() -> {
                        clearSelection();
                        reload();
                        Ui.toast(a, "Deleted " + n + (n == 1 ? " item" : " items"));
                    });
                }));
    }

    private void compress(final List<File> files) {
        String base = files.size() == 1 ? files.get(0).getName().replaceFirst("\\.[^.]+$", "") : "Archive";
        Ui.askText(a, "Compress to ZIP", base + ".zip", "Create", name -> {
            if (name.isEmpty()) return;
            if (!name.toLowerCase(Locale.ROOT).endsWith(".zip")) name += ".zip";
            final File out = Fs.unique(new File(cwd, name));
            clearSelection();
            Ui.toast(a, "Compressing…");
            io.execute(() -> {
                String msg;
                try {
                    Fs.zip(files, out);
                    Android.mediaScan(a, out);
                    msg = "Created " + out.getName() + " (" + Fs.size(out.length()) + ")";
                } catch (Exception ex) {
                    //noinspection ResultOfMethodCallIgnored
                    out.delete();
                    msg = "Couldn't compress: " + ex.getMessage();
                }
                final String m = msg;
                main.post(() -> {
                    Ui.toast(a, m);
                    reload();
                });
            });
        });
    }

    private void details(File f) {
        Fs.Entry e = new Fs.Entry(f);
        Ui.info(a, e.name, "Type: " + e.kind + "\n" + (e.dir ? "" : "Size: " + Fs.size(e.size) + "\n")
                + "Modified: " + Fs.when(e.mod) + "\nFolder: " + Fs.shortPath(f.getParentFile()));
    }

    // ---------------------------------------------------------------- back
    @Override
    public boolean back() {
        if (selectMode) {
            clearSelection();
            return true;
        }
        if (searching) {
            toggleSearch();
            return true;
        }
        if (!history.isEmpty()) {
            open(history.pop(), false);
            return true;
        }
        if (!cwd.equals(Fs.root()) && cwd.getParentFile() != null) {
            open(cwd.getParentFile(), false);
            return true;
        }
        return false;
    }

    // ---------------------------------------------------------------- adapter
    private final class Adapter extends BaseAdapter {
        @Override
        public int getCount() {
            return entries.size();
        }

        @Override
        public Object getItem(int i) {
            return entries.get(i);
        }

        @Override
        public long getItemId(int i) {
            return i;
        }

        @Override
        public View getView(int i, View convert, ViewGroup parent) {
            Fs.Entry e = entries.get(i);
            boolean sel = selected.contains(e.f);
            if (grid()) return Rows.tile(a, convert, e, sel);
            String sub = (e.dir ? "Folder" : Fs.size(e.size)) + " · " + Fs.when(e.mod);
            if (searchResults) sub += " · " + Fs.shortPath(e.f.getParentFile());
            return Rows.row(a, convert, e, sub, selectMode, sel);
        }
    }
}

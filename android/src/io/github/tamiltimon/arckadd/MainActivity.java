package io.github.tamiltimon.arckadd;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.io.File;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;

/** One window with four tabs: Files · Recent · Send · Receive. No animations, everything native. */
public class MainActivity extends Activity implements Net.NearbyUi {
    interface Screen {
        View view();

        void onShow();

        void onHide();

        void topBar(LinearLayout bar);

        boolean back();
    }

    static Net.Nearby nearby;
    static Net.Link link;

    static void queueSend(List<File> files) {
        synchronized (link.items) {
            for (File f : files) if (!link.items.contains(f)) link.items.add(f);
        }
    }

    private final Handler main = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    FilesScreen files;
    private RecentScreen recent;
    private ShareScreens.Send send;
    private ShareScreens.Receive receive;
    ChatScreen chat;
    private final Map<String, Screen> screens = new LinkedHashMap<>();
    private final Map<String, TextView[]> navItems = new LinkedHashMap<>();
    private Screen current;
    private String currentKey;
    private LinearLayout topBar, pasteBar, nav;
    private TextView pasteLabel;
    private FrameLayout content;
    private boolean ready;

    private final Runnable ticker = new Runnable() {
        @Override
        public void run() {
            if (nearby.serving() && !nearby.visible()) {
                if (nearby.hide(false) && receive != null) receive.line("Time is up, receiving turned off");
            }
            if (send != null) send.tick();
            if (receive != null) receive.tick();
            main.postDelayed(this, 1000);
        }
    };

    @Override
    protected void onCreate(Bundle b) {
        Ui.apply(this);
        super.onCreate(b);
        prefs = Ui.prefs(this);
        if (!prefs.contains("device_id")) prefs.edit().putString("device_id", UUID.randomUUID().toString().substring(0, 16)).apply();
        String name = prefs.getString("device_name", "");
        if (name.isEmpty()) name = deviceName();
        if (nearby == null) nearby = new Net.Nearby(this, prefs.getString("device_id", "phone"), this);
        if (link == null) link = new Net.Link();
        nearby.ui = this;
        nearby.name = name;
        link.deviceName = name;

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Ui.BG);
        topBar = new LinearLayout(this);
        topBar.setGravity(Gravity.CENTER_VERTICAL);
        topBar.setBackgroundColor(Ui.BAR);
        topBar.setPadding(Ui.dp(this, 4), 0, Ui.dp(this, 4), 0);
        root.addView(topBar, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 56)));
        content = new FrameLayout(this);
        root.addView(content, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));

        pasteBar = new LinearLayout(this);
        pasteBar.setGravity(Gravity.CENTER_VERTICAL);
        pasteBar.setBackgroundColor(Ui.CARD);
        pasteBar.setPadding(Ui.dp(this, 14), Ui.dp(this, 8), Ui.dp(this, 10), Ui.dp(this, 8));
        pasteLabel = Ui.text(this, "", 14, Ui.TEXT, false);
        pasteBar.addView(pasteLabel, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        pasteBar.addView(Ui.button(this, "Paste here", true, v -> {
            if (currentKey.equals("files")) files.paste();
            else Ui.toast(this, "Open the Files tab first");
        }));
        TextView cancel = Ui.button(this, "Cancel", false, v -> {
            FilesScreen.clip.clear();
            hidePasteBar();
        });
        LinearLayout.LayoutParams cl = new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        cl.leftMargin = Ui.dp(this, 8);
        pasteBar.addView(cancel, cl);
        pasteBar.setVisibility(FilesScreen.clip.isEmpty() ? View.GONE : View.VISIBLE);
        root.addView(pasteBar);

        nav = new LinearLayout(this);
        nav.setBackgroundColor(Ui.BAR);
        addNav("files", "📁", "Files");
        addNav("recent", "🕘", "Recent");
        addNav("send", "📤", "Send");
        addNav("receive", "📥", "Receive");
        addNav("chat", "💬", "Chat");
        root.addView(nav, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(this, 64)));
        setContentView(root);
        if (hasStorage()) start(getIntent());
        else showPermission();
    }

    private void addNav(final String key, String icon, String label) {
        LinearLayout item = new LinearLayout(this);
        item.setOrientation(LinearLayout.VERTICAL);
        item.setGravity(Gravity.CENTER);
        item.setBackground(Ui.ripple(this));
        TextView ic = Ui.text(this, icon, 20, Ui.DIM, false);
        ic.setGravity(Gravity.CENTER);
        TextView lb = Ui.text(this, label, 12, Ui.DIM, false);
        lb.setGravity(Gravity.CENTER);
        item.addView(ic);
        item.addView(lb);
        item.setOnClickListener(v -> showTab(key));
        nav.addView(item, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1));
        navItems.put(key, new TextView[]{ic, lb});
    }

    private void start(Intent intent) {
        if (ready) return;
        ready = true;
        files = new FilesScreen(this);
        recent = new RecentScreen(this);
        send = new ShareScreens.Send(this);
        receive = new ShareScreens.Receive(this);
        screens.put("files", files);
        screens.put("recent", recent);
        screens.put("send", send);
        screens.put("receive", receive);
        chat = new ChatScreen(this);
        screens.put("chat", chat);
        String tab = intent != null ? intent.getStringExtra("tab") : null;
        showTab(tab != null && screens.containsKey(tab) ? tab : "files");
        openChatFrom(intent);
        ChatHub.get(this).start();                   // chat keeps running in the background once it's in use
        main.post(ticker);
        if (System.currentTimeMillis() - prefs.getLong("update_checked", 0) > 86_400_000L) {
            main.postDelayed(() -> Updater.check(this, false), 5000);
        }
    }

    void showTab(String key) {
        if (!ready) return;
        Screen s = screens.get(key);
        if (s == null) return;
        if (current != null && current != s) current.onHide();
        current = s;
        currentKey = key;
        content.removeAllViews();
        content.addView(s.view());
        for (Map.Entry<String, TextView[]> e : navItems.entrySet()) {
            boolean on = e.getKey().equals(key);
            for (TextView t : e.getValue()) {
                t.setTextColor(on ? Ui.ACCENT : Ui.DIM);
                t.setTypeface(null, on ? android.graphics.Typeface.BOLD : android.graphics.Typeface.NORMAL);
            }
        }
        s.onShow();
        refreshTopBar();
    }

    void refreshTopBar() {
        topBar.removeAllViews();
        if (current != null) current.topBar(topBar);
        else topBar.addView(title("Arckad-D"), grow());
    }

    TextView title(String s) {
        TextView t = Ui.text(this, s, 19, Ui.TEXT, true);
        t.setSingleLine(true);
        t.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        t.setPadding(Ui.dp(this, 10), 0, Ui.dp(this, 4), 0);
        return t;
    }

    static LinearLayout.LayoutParams grow() {
        return new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1);
    }

    void showPasteBar(String text) {
        pasteLabel.setText(text);
        pasteBar.setVisibility(View.VISIBLE);
    }

    void hidePasteBar() {
        pasteBar.setVisibility(View.GONE);
    }

    void cycleTheme() {
        String t = prefs.getString("theme", "system");
        String next = t.equals("system") ? "light" : t.equals("light") ? "dark" : "system";
        prefs.edit().putString("theme", next).apply();
        Ui.toast(this, next.equals("system") ? "Theme: follow phone" : "Theme: " + next);
        recreate();
    }

    // ---------------------------------------------------------------- storage permission
    private boolean hasStorage() {
        if (Build.VERSION.SDK_INT >= 30) return Environment.isExternalStorageManager();
        return Build.VERSION.SDK_INT < 23 || checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE)
                == PackageManager.PERMISSION_GRANTED;
    }

    private void showPermission() {
        topBar.removeAllViews();
        topBar.addView(title("Arckad-D"), grow());
        ScrollView sv = new ScrollView(this);
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(this, 24);
        box.setPadding(p, p, p, p);
        TextView icon = Ui.text(this, "📂", 64, Ui.TEXT, false);
        icon.setGravity(Gravity.CENTER);
        box.addView(icon);
        TextView t = Ui.text(this, "Allow access to your files", 21, Ui.TEXT, true);
        t.setGravity(Gravity.CENTER);
        box.addView(t, Ui.matchWrap(this, 12));
        TextView d = Ui.text(this, "Arckad-D is a file manager, so Android needs you to allow it to manage all files. "
                + "Nothing leaves your phone unless you send or share it.", 15, Ui.DIM, false);
        d.setGravity(Gravity.CENTER);
        box.addView(d, Ui.matchWrap(this, 10));
        box.addView(Ui.button(this, "Allow access", true, v -> askStorage()), Ui.matchWrap(this, 24));
        sv.addView(box);
        content.removeAllViews();
        content.addView(sv);
    }

    private void askStorage() {
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception e) {
                startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            }
        } else if (Build.VERSION.SDK_INT >= 23) {
            requestPermissions(new String[]{Manifest.permission.READ_EXTERNAL_STORAGE,
                    Manifest.permission.WRITE_EXTERNAL_STORAGE}, 7);
        }
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] perms, int[] results) {
        if (hasStorage()) start(getIntent());
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!ready && hasStorage()) start(getIntent());
        else if (ready && current == files) files.reload();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        String tab = intent.getStringExtra("tab");
        if (tab != null) showTab(tab);
        openChatFrom(intent);
    }

    private void openChatFrom(Intent intent) {
        if (intent == null || chat == null || !"chat".equals(intent.getStringExtra("tab"))) return;
        chat.open(intent.getStringExtra("chat"), intent.getStringExtra("chat_page"));
    }

    void openFolder(File dir) {
        dir.mkdirs();
        showTab("files");
        files.open(dir, true);
    }

    @Override
    protected void onActivityResult(int req, int result, Intent data) {
        super.onActivityResult(req, result, data);
        if (result == RESULT_OK && chat != null && (req == ChatScreen.REQ_ATTACH || req == ChatScreen.REQ_PHOTO || req == ChatScreen.REQ_WALL))
            chat.onResult(req, data);
    }

    @Override
    public void onBackPressed() {
        if (current != null && current.back()) return;
        if (current != null && current != files) {
            showTab("files");
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        main.removeCallbacks(ticker);
        if (current != null) current.onHide();
        if (isFinishing()) {
            nearby.hide(true);
            link.stop();
        }
    }

    private String deviceName() {
        try {
            String n = Settings.Global.getString(getContentResolver(), "device_name");
            if (n != null && !n.isEmpty()) return n;
        } catch (Exception ignored) {
        }
        return Build.MODEL;
    }

    // ---------------------------------------------------------------- Nearby callbacks (from background threads)
    @Override
    public void peersChanged() {
        runOnUiThread(() -> {
            if (send != null && current == send) send.refreshPeers();
        });
    }

    @Override
    public void askIncoming(final Net.Incoming in) {
        runOnUiThread(() -> {
            int n = in.rel.size();
            StringBuilder list = new StringBuilder();
            for (int i = 0; i < Math.min(5, n); i++) list.append("•  ").append(in.rel.get(i)).append('\n');
            if (n > 5) list.append("…and ").append(n - 5).append(" more\n");
            final boolean[] answered = {false};
            final AlertDialog d = Ui.dialog(this)
                    .setTitle(in.from + " wants to send you " + n + (n == 1 ? " file" : " files"))
                    .setMessage(Fs.size(in.total) + " from " + in.from + " (" + in.os + ")\n\n" + list
                            + "\nThey will be saved in " + Fs.shortPath(Fs.received()))
                    .setCancelable(false)
                    .setPositiveButton("Accept", (di, w) -> answer(in, answered, true))
                    .setNegativeButton("Decline", (di, w) -> answer(in, answered, false))
                    .create();
            d.show();
            main.postDelayed(() -> {
                if (!answered[0]) {
                    d.dismiss();
                    answer(in, answered, false);
                }
            }, 60_000);
        });
    }

    private void answer(Net.Incoming in, boolean[] answered, boolean ok) {
        if (answered[0]) return;
        answered[0] = true;
        in.accepted = ok;
        in.decided.countDown();
        if (receive != null) receive.line((ok ? "Accepted " : "Declined ") + in.rel.size() + " from " + in.from);
    }

    @Override
    public void progress(final Net.Incoming in) {
        runOnUiThread(() -> {
            if (receive != null) receive.progress(in);
        });
    }

    @Override
    public void received(final Net.Incoming in) {
        Android.mediaScan(this, in.dest.toArray(new File[0]));
        runOnUiThread(() -> {
            int n = in.rel.size();
            String msg = "Received " + n + (n == 1 ? " file" : " files") + " from " + in.from;
            if (receive != null) {
                receive.line("✓ " + msg);
                receive.tick();
            }
            Ui.dialog(this).setTitle(msg).setMessage("Saved in " + Fs.shortPath(Fs.received()))
                    .setPositiveButton("Show files", (di, w) -> {
                        showTab("files");
                        files.open(n == 1 ? in.dest.get(0).getParentFile() : Fs.received(), true);
                    })
                    .setNegativeButton("Close", null).show();
        });
    }
}

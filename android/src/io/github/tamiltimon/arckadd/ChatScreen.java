package io.github.tamiltimon.arckadd;

import android.Manifest;
import android.app.AlertDialog;
import android.content.Intent;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.Rect;
import android.graphics.RectF;
import android.graphics.Typeface;
import android.net.Uri;
import android.os.Build;
import android.provider.OpenableColumns;
import android.provider.Settings;
import android.text.InputType;
import android.text.TextUtils;
import android.util.LruCache;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.GridView;
import android.widget.HorizontalScrollView;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Collections;
import java.util.Date;
import java.util.Iterator;
import java.util.List;
import java.util.Locale;

/** The Chat tab: chats (friends and groups), a conversation, People, your profile. The same chats as the
 *  desktop app: phones and computers talk to each other. */
final class ChatScreen implements MainActivity.Screen, ChatHub.Listener {
    static final int REQ_ATTACH = 7101, REQ_PHOTO = 7102, REQ_WALL = 7104;
    private String wallFor;                         // which chat a wallpaper picture is for (null = all chats)
    static final String[] STICKERS = {"approved", "done", "thanks", "great", "onit", "urgent", "question", "meeting",
            "lunch", "coffee", "welcome", "birthday", "noted", "later", "yes", "no"};
    private static final int[] AV_COLOURS = {0xff1c71d8, 0xff26a269, 0xffc64600, 0xff9141ac, 0xff0e8a84, 0xffa51d2d,
            0xff865e3c, 0xff3d3a9e, 0xffd63384};
    private static final LruCache<String, Bitmap> avatars = new LruCache<>(120);

    private final MainActivity a;
    private final ChatHub hub;
    private ChatEngine e;
    private final FrameLayout root;
    private String page = "list", gid;
    private LinearLayout msgBox;
    private ScrollView msgScroll;
    private EditText input;
    private byte[] pendingPhoto;
    private Runnable afterPhoto;
    private boolean askedNotif;

    ChatScreen(MainActivity a) {
        this.a = a;
        hub = ChatHub.get(a);
        e = hub.engine;
        root = new FrameLayout(a);
        EmojiText.init(a);
    }

    @Override
    public View view() {
        return root;
    }

    @Override
    public void onShow() {
        hub.addListener(this);
        hub.appVisible = true;
        hub.visibleGid = "conv".equals(page) ? gid : null;
        hub.start();
        askNotifications();
        render();
    }

    @Override
    public void onHide() {
        hub.removeListener(this);
        hub.appVisible = false;
        hub.visibleGid = null;
    }

    @Override
    public boolean back() {
        if (!"list".equals(page)) {
            show("list", null);
            return true;
        }
        return false;
    }

    void open(String chat, String pg) {
        if (chat != null && e.groups.containsKey(chat)) show("conv", chat);
        else if ("people".equals(pg)) show("people", null);
    }

    private void show(String p, String g) {
        page = p;
        gid = g;
        hub.visibleGid = "conv".equals(p) ? g : null;
        if (g != null) e.unread.put(g, 0);
        render();
        a.refreshTopBar();
    }

    // ================================================================= top bar
    @Override
    public void topBar(LinearLayout bar) {
        if ("conv".equals(page) && gid != null && e.groups.containsKey(gid)) {
            bar.addView(Ui.icon(a, "←", "Back", v -> show("list", null)));
            ImageView av = new ImageView(a);
            av.setImageBitmap(chatAvatar(gid, 36));
            bar.addView(av, new LinearLayout.LayoutParams(Ui.dp(a, 36), Ui.dp(a, 36)));
            LinearLayout t = new LinearLayout(a);
            t.setOrientation(LinearLayout.VERTICAL);
            t.setPadding(Ui.dp(a, 8), 0, 0, 0);
            TextView n = Ui.text(a, title(gid), 17, Ui.TEXT, true);
            n.setSingleLine(true);
            n.setEllipsize(TextUtils.TruncateAt.END);
            t.addView(n);
            t.addView(Ui.text(a, subtitle(gid), 12, Ui.DIM, false));
            bar.addView(t, MainActivity.grow());
            bar.addView(Ui.icon(a, "🔒", "Lock chat", v -> lockNow()));
            bar.addView(Ui.icon(a, "⋮", "More", v -> convMenu()));
        } else if ("people".equals(page)) {
            bar.addView(Ui.icon(a, "←", "Back", v -> show("list", null)));
            bar.addView(a.title("People"), MainActivity.grow());
        } else {
            ImageView me = new ImageView(a);
            me.setImageBitmap(avatar(e.myName(), e.avatarFile(e.me), 34, false));
            me.setPadding(Ui.dp(a, 8), 0, 0, 0);
            me.setOnClickListener(v -> editProfile(null));
            bar.addView(me, new LinearLayout.LayoutParams(Ui.dp(a, 42), Ui.dp(a, 34)));
            bar.addView(a.title("Chats"), MainActivity.grow());
            int req = e.incoming().length();
            bar.addView(Ui.icon(a, "🔒", "Lock chat (or set a PIN)", v -> lockNow()));
            bar.addView(Ui.icon(a, req > 0 ? "👥" + req : "👥", "People", v -> showPeople()));
            bar.addView(Ui.icon(a, "＋", "New", v -> plusMenu()));
            bar.addView(Ui.icon(a, "⋮", "More", v -> listMenu()));
        }
    }

    // ================================================================= pages
    private void render() {
        root.removeAllViews();
        if (e.isLocked()) {
            renderLocked();
            return;
        }
        if ("conv".equals(page) && gid != null && e.groups.containsKey(gid)) renderConv();
        else if ("people".equals(page)) renderPeople();
        else {
            page = "list";
            renderList();
        }
    }

    private void renderList() {
        ScrollView sc = new ScrollView(a);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        sc.addView(box);
        if (!e.profile.optBoolean("setup")) {
            LinearLayout card = Ui.card(a);
            card.addView(Ui.text(a, "Set up your profile (name and photo) so colleagues can find you and add you as a friend.", 14, Ui.TEXT, false));
            card.addView(Ui.button(a, "Set up", true, v -> editProfile(null)));
            box.addView(card, Ui.matchWrap(a, 8));
        }
        List<String> order = new ArrayList<>(e.groups.keySet());
        Collections.sort(order, (x, y) -> Double.compare(lastTs(y), lastTs(x)));
        if (order.isEmpty()) {
            TextView t = Ui.text(a, "💬\n\nChat with your colleagues\n\nAdd friends with 👥 People, or create a group with ＋.\n\n"
                    + "Private and encrypted: everything stays inside your network. Your chats from the PC appear here "
                    + "once you're friends or in the same groups.", 15, Ui.DIM, false);
            t.setGravity(Gravity.CENTER);
            t.setPadding(Ui.dp(a, 24), Ui.dp(a, 60), Ui.dp(a, 24), 0);
            box.addView(t);
        }
        for (String g : order) if (!e.groups.get(g).optBoolean("hidden")) box.addView(chatRow(g));
        root.addView(sc);
    }

    private double lastTs(String g) {
        List<JSONObject> l = e.msgs.get(g);
        if (l != null && !l.isEmpty()) return l.get(l.size() - 1).optDouble("ts", 0);
        JSONObject grp = e.groups.get(g);
        return grp == null ? 0 : grp.optDouble("created", 0);
    }

    private View chatRow(String g) {
        JSONObject grp = e.groups.get(g);
        LinearLayout row = new LinearLayout(a);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(Ui.dp(a, 12), Ui.dp(a, 10), Ui.dp(a, 12), Ui.dp(a, 10));
        row.setBackground(Ui.ripple(a));
        row.setOnClickListener(v -> show("conv", g));
        ImageView av = new ImageView(a);
        av.setImageBitmap(chatAvatar(g, 46));
        row.addView(av, new LinearLayout.LayoutParams(Ui.dp(a, 46), Ui.dp(a, 46)));
        LinearLayout t = new LinearLayout(a);
        t.setOrientation(LinearLayout.VERTICAL);
        t.setPadding(Ui.dp(a, 12), 0, 0, 0);
        LinearLayout top = new LinearLayout(a);
        TextView name = Ui.text(a, ("direct".equals(grp.optString("kind")) ? "" : "👥 ") + title(g)
                + (grp.optBoolean("removed") ? " (left)" : ""), 16, Ui.TEXT, true);
        name.setSingleLine(true);
        name.setEllipsize(TextUtils.TruncateAt.END);
        top.addView(name, MainActivity.grow());
        List<JSONObject> l = new ArrayList<>();
        for (JSONObject x : e.msgs.getOrDefault(g, new ArrayList<>()))
            if (!"delete".equals(x.optString("kind")) && !"me".equals(x.optString("deleted"))) l.add(x);
        JSONObject last = l.isEmpty() ? null : l.get(l.size() - 1);
        if (last != null) top.addView(Ui.text(a, when(last.optDouble("ts")), 12, Ui.DIM, false));
        t.addView(top);
        LinearLayout bottom = new LinearLayout(a);
        String prev;
        if (last == null) prev = "direct".equals(grp.optString("kind")) ? "Say hello 👋" : "No messages yet";
        else {
            String who = e.me.equals(last.optString("from")) && !"system".equals(last.optString("kind")) ? "You: "
                    : "direct".equals(grp.optString("kind")) || "system".equals(last.optString("kind")) ? "" : last.optString("name") + ": ";
            prev = who + preview(last);
        }
        TextView p = new TextView(a);
        p.setText(EmojiText.span(a, prev.replace('\n', ' '), Ui.dp(a, 15)));
        p.setTextColor(Ui.DIM);
        p.setTextSize(14);
        p.setSingleLine(true);
        p.setEllipsize(TextUtils.TruncateAt.END);
        bottom.addView(p, MainActivity.grow());
        int n = e.unread.getOrDefault(g, 0);
        if (n > 0) {
            TextView b = Ui.text(a, " " + n + " ", 12, Color.WHITE, true);
            b.setBackground(Ui.round(Ui.ACCENT, Ui.dp(a, 10)));
            bottom.addView(b);
        }
        t.addView(bottom);
        row.addView(t, MainActivity.grow());
        return row;
    }

    static String preview(JSONObject m) {
        if ("everyone".equals(m.optString("deleted"))) return "🚫 Message deleted";
        if (m.optBoolean("once")) return "👁 One-time message";
        if (m.optDouble("voice", 0) > 0) return "🎤 Voice message";
        if (m.optJSONObject("file") != null && !"sticker".equals(m.optString("kind"))) return "📎 " + m.optJSONObject("file").optString("name");
        if ("sticker".equals(m.optString("kind"))) return "🏷 Sticker";
        return m.optString("text");
    }

    private String when(double ts) {
        long ms = (long) (ts * 1000);
        return new SimpleDateFormat(System.currentTimeMillis() - ms < 86_400_000L ? "HH:mm" : "dd MMM", Locale.getDefault()).format(new Date(ms));
    }

    String title(String g) {
        JSONObject grp = e.groups.get(g);
        if (grp == null) return "?";
        if ("direct".equals(grp.optString("kind"))) {
            JSONObject f = e.friends().optJSONObject(grp.optString("peer"));
            if (f != null) return f.optString("name");
        }
        return grp.optString("name", "?");
    }

    private String subtitle(String g) {
        JSONObject grp = e.groups.get(g);
        if ("direct".equals(grp.optString("kind"))) {
            String pid = grp.optString("peer");
            JSONObject f = e.friends().optJSONObject(pid);
            if (grp.optBoolean("removed") || f == null) return "not friends any more";
            if (f.optJSONObject("pending_accept") != null) return "finishing… (they need to come online)";
            return e.personOnline(pid) ? "online" : "offline";
        }
        JSONObject members = grp.optJSONObject("members");
        int n = members == null ? 0 : members.length();
        return n + " member" + (n == 1 ? "" : "s") + " · " + e.onlineMembers(g).size() + " online"
                + (grp.optBoolean("owner_only") ? " · announcements" : "");
    }

    // ---------- conversation
    private void renderConv() {
        LinearLayout col = new LinearLayout(a);
        col.setOrientation(LinearLayout.VERTICAL);
        msgScroll = new ScrollView(a);
        msgBox = new LinearLayout(a);
        msgBox.setOrientation(LinearLayout.VERTICAL);
        msgBox.setPadding(Ui.dp(a, 8), Ui.dp(a, 6), Ui.dp(a, 8), Ui.dp(a, 6));
        msgScroll.addView(msgBox);
        FrameLayout wall = new FrameLayout(a);
        applyWallpaper(wall);
        wall.addView(msgScroll);
        col.addView(wall, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        String lastDay = "";
        List<JSONObject> list = new ArrayList<>(e.msgs.getOrDefault(gid, new ArrayList<>()));
        e.markRead(gid);
        List<JSONObject> vis = new ArrayList<>();
        for (JSONObject m : list) if (!"delete".equals(m.optString("kind")) && !"me".equals(m.optString("deleted"))) vis.add(m);
        list = vis;
        for (JSONObject m : list.subList(Math.max(0, list.size() - 250), list.size())) {
            String day = new SimpleDateFormat("EEEE d MMMM yyyy", Locale.getDefault()).format(new Date((long) (m.optDouble("ts") * 1000)));
            if (!day.equals(lastDay)) {
                lastDay = day;
                TextView d = Ui.text(a, day, 12, Ui.DIM, true);
                d.setGravity(Gravity.CENTER);
                d.setPadding(0, Ui.dp(a, 10), 0, Ui.dp(a, 4));
                msgBox.addView(d);
            }
            msgBox.addView(bubble(m));
        }
        if (e.canPost(gid)) col.addView(composer());
        else {
            JSONObject g = e.groups.get(gid);
            TextView ro = Ui.text(a, g.optBoolean("removed") ? ("direct".equals(g.optString("kind")) ? "You're no longer friends."
                    : "You're no longer a member of this group.") : "Only the group owner can post here.", 14, Ui.DIM, false);
            ro.setGravity(Gravity.CENTER);
            ro.setPadding(0, Ui.dp(a, 12), 0, Ui.dp(a, 12));
            col.addView(ro);
        }
        root.addView(col);
        msgScroll.post(() -> msgScroll.fullScroll(View.FOCUS_DOWN));
    }

    private View bubble(JSONObject m) {
        String kind = m.optString("kind");
        String time = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date((long) (m.optDouble("ts") * 1000)));
        if ("system".equals(kind)) {
            TextView t = Ui.text(a, m.optString("text") + " · " + time, 12, Ui.DIM, false);
            t.setGravity(Gravity.CENTER);
            t.setPadding(Ui.dp(a, 12), Ui.dp(a, 4), Ui.dp(a, 12), Ui.dp(a, 4));
            return t;
        }
        boolean mine = e.me.equals(m.optString("from"));
        JSONObject g = e.groups.get(gid);
        LinearLayout outer = new LinearLayout(a);
        outer.setGravity(mine ? Gravity.END : Gravity.START);
        outer.setPadding(mine ? Ui.dp(a, 48) : 0, Ui.dp(a, 3), mine ? 0 : Ui.dp(a, 48), Ui.dp(a, 3));
        LinearLayout b = new LinearLayout(a);
        b.setOrientation(LinearLayout.VERTICAL);
        b.setPadding(Ui.dp(a, 11), Ui.dp(a, 7), Ui.dp(a, 11), Ui.dp(a, 6));
        boolean sticker = "sticker".equals(kind);
        if (!sticker) b.setBackground(Ui.round(mine ? 0xff2f7fd8 : Ui.CARD, Ui.dp(a, 16)));
        int fg = mine && !sticker ? Color.WHITE : Ui.TEXT;
        if (!mine && !"direct".equals(g.optString("kind"))) b.addView(Ui.text(a, m.optString("name"), 12, fg, true));
        if ("everyone".equals(m.optString("deleted"))) {
            TextView t = Ui.text(a, mine ? "🚫 You deleted this message" : "🚫 This message was deleted", 14, fg, false);
            t.setTypeface(null, Typeface.ITALIC);
            b.addView(t);
        } else if (m.optBoolean("once")) {
            b.addView(Ui.text(a, mine ? "👁 One-time message (sent)" : "👁 One-time message: view it in Arckad-D on your computer "
                    + "(phones can show these in the next update)", 14, fg, false));
        } else if ("text".equals(kind)) {
            TextView t = new TextView(a);
            String text = m.optString("text");
            int only = EmojiText.onlyEmojiCount(text);
            t.setText(EmojiText.span(a, text, Ui.dp(a, only > 0 && only <= 3 ? 40 : 20)));
            t.setTextColor(fg);
            t.setTextSize(15);
            t.setTextIsSelectable(true);
            b.addView(t);
        } else if (sticker) {
            b.addView(stickerView(m));
        } else if (m.optJSONObject("file") != null) {
            b.addView(fileView(m, fg));
        }
        if (m.optBoolean("unverified")) b.addView(Ui.text(a, "⚠ not signed (sent before signatures)", 11, fg, false));
        TextView tm = Ui.text(a, time + (mine && !m.has("deleted") ? "  " + ticks(m) : ""), 11, mine && !sticker ? 0xddffffff : Ui.DIM, false);
        if (mine && read(m)) {
            android.text.SpannableString ss = new android.text.SpannableString(tm.getText());
            ss.setSpan(new android.text.style.ForegroundColorSpan(0xff4fc3f7), ss.length() - 2, ss.length(), 0);
            tm.setText(ss);
        }
        b.setOnLongClickListener(v -> {
            messageMenu(m);
            return true;
        });
        tm.setGravity(Gravity.END);
        b.addView(tm, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        outer.addView(b);
        return outer;
    }

    private List<String> others() {
        List<String> o = new ArrayList<>();
        JSONObject g = e.groups.get(gid);
        JSONObject mem = g == null ? null : g.optJSONObject("members");
        if (mem != null) for (Iterator<String> it = mem.keys(); it.hasNext(); ) {
            String d = it.next();
            if (!d.equals(e.me)) o.add(d);
        }
        return o;
    }

    private static boolean has(JSONObject m, String field, String did) {
        org.json.JSONArray arr = m.optJSONArray(field);
        if (arr != null) for (int i = 0; i < arr.length(); i++) if (did.equals(arr.optString(i))) return true;
        return false;
    }

    private boolean read(JSONObject m) {
        List<String> o = others();
        if (o.isEmpty()) return false;
        for (String d : o) if (!has(m, "read", d)) return false;
        return true;
    }

    /** ✓ sent · ✓✓ delivered · blue ✓✓ read */
    private String ticks(JSONObject m) {
        if (read(m)) return "✓✓";
        org.json.JSONArray d = m.optJSONArray("delivered"), r = m.optJSONArray("read");
        return (d != null && d.length() > 0) || (r != null && r.length() > 0) ? "✓✓" : "✓";
    }

    private void messageMenu(JSONObject m) {
        List<String> labels = new ArrayList<>();
        List<Runnable> acts = new ArrayList<>();
        if ("text".equals(m.optString("kind")) && !m.has("deleted") && !m.optBoolean("once")) {
            labels.add("Copy text");
            acts.add(() -> {
                android.content.ClipboardManager cm = (android.content.ClipboardManager) a.getSystemService(android.content.Context.CLIPBOARD_SERVICE);
                cm.setPrimaryClip(android.content.ClipData.newPlainText("message", m.optString("text")));
                Ui.toast(a, "Copied");
            });
        }
        labels.add("Delete for me");
        acts.add(() -> e.deleteForMe(gid, Collections.singleton(m.optString("id"))));
        if (e.me.equals(m.optString("from")) && !m.has("deleted") && e.canPost(gid)) {
            labels.add("Delete for everyone");
            acts.add(() -> Ui.confirm(a, "Delete for everyone?", "It shows as “This message was deleted” for everyone.", "Delete",
                    () -> e.deleteForEveryone(gid, Collections.singleton(m.optString("id")))));
        }
        labels.add("Info");
        acts.add(() -> Ui.info(a, "Message", new SimpleDateFormat("EEEE d MMMM yyyy, HH:mm:ss", Locale.getDefault())
                .format(new Date((long) (m.optDouble("ts") * 1000))) + (e.me.equals(m.optString("from"))
                ? "\n" + (read(m) ? "Read" : ticks(m).equals("✓✓") ? "Delivered" : "Sent") : "\nFrom " + m.optString("name"))));
        Ui.dialog(a).setItems(labels.toArray(new String[0]), (d, w) -> acts.get(w).run()).show();
    }

    private View stickerView(JSONObject m) {
        ImageView iv = new ImageView(a);
        Bitmap bm = null;
        if (!"custom".equals(m.optString("sticker"))) {
            try (InputStream in = a.getAssets().open("stickers/" + m.optString("sticker") + ".png")) {
                bm = BitmapFactory.decodeStream(in);
            } catch (Exception ignored) {
            }
        } else if (m.optJSONObject("file") != null) {
            File f = e.localFile(gid, m.optJSONObject("file").optString("id"));
            if (f != null) bm = decode(f, Ui.dp(a, 140));
        }
        if (bm == null) return Ui.text(a, "🏷 sticker", 14, Ui.TEXT, false);
        iv.setImageBitmap(bm);
        iv.setLayoutParams(new LinearLayout.LayoutParams(Ui.dp(a, 128), Ui.dp(a, 128)));
        return iv;
    }

    private View fileView(JSONObject m, int fg) {
        JSONObject f = m.optJSONObject("file");
        File local = e.localFile(gid, f.optString("id"));
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        String ext = Fs.ext(f.optString("name"));
        if (local != null && Fs.in(ext, new String[]{"jpg", "jpeg", "png", "gif", "webp", "bmp"})) {
            Bitmap bm = decode(local, Ui.dp(a, 240));
            if (bm != null) {
                ImageView iv = new ImageView(a);
                iv.setImageBitmap(bm);
                iv.setAdjustViewBounds(true);
                iv.setMaxWidth(Ui.dp(a, 240));
                iv.setOnClickListener(v -> Android.openWith(a, local));
                box.addView(iv);
            }
        }
        String label = (m.optDouble("voice", 0) > 0 ? "🎤 Voice message · " : "📎 ") + f.optString("name");
        TextView n = Ui.text(a, label, 14, fg, false);
        n.setSingleLine(true);
        n.setEllipsize(TextUtils.TruncateAt.MIDDLE);
        box.addView(n);
        box.addView(Ui.text(a, Fs.size(f.optLong("size")), 12, fg, false));
        if (local != null) {
            box.addView(Ui.row(a, Ui.button(a, "Open", false, v -> Android.openWith(a, local)),
                    Ui.button(a, "Share", false, v -> Android.share(a, Collections.singletonList(local)))));
        } else if (e.downloading.contains(f.optString("id"))) {
            box.addView(Ui.text(a, "Downloading…", 13, fg, false));
        } else {
            box.addView(Ui.button(a, "Download", false, v -> e.download(gid, m)));
        }
        return box;
    }

    private View composer() {
        LinearLayout c = new LinearLayout(a);
        c.setGravity(Gravity.CENTER_VERTICAL);
        c.setPadding(Ui.dp(a, 4), Ui.dp(a, 4), Ui.dp(a, 4), Ui.dp(a, 4));
        TextView emo = Ui.icon(a, "😊", "Emoji", v -> emojiPicker());
        Bitmap face = EmojiText.bitmap("🙂");
        if (face != null) emo.setText(EmojiText.span(a, "🙂", Ui.dp(a, 24)));
        c.addView(emo);
        c.addView(Ui.icon(a, "🏷", "Stickers", v -> stickerPicker()));
        c.addView(Ui.icon(a, "📎", "Attach files", v -> pickFiles()));
        input = new EditText(a);
        input.setHint("Message");
        input.setTextColor(Ui.TEXT);
        input.setHintTextColor(Ui.DIM);
        input.setMaxLines(4);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE | InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        c.addView(input, MainActivity.grow());
        TextView send = Ui.icon(a, "➤", "Send", v -> {
            String t = input.getText().toString();
            if (t.trim().isEmpty()) return;
            input.setText("");
            e.sendText(gid, t);
        });
        send.setTextColor(Ui.ACCENT);
        c.addView(send);
        return c;
    }

    private void emojiPicker() {
        final AlertDialog[] d = new AlertDialog[1];
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        LinearLayout tabs = new LinearLayout(a);
        HorizontalScrollView hs = new HorizontalScrollView(a);
        hs.addView(tabs);
        box.addView(hs);
        GridView grid = new GridView(a);
        grid.setNumColumns(GridView.AUTO_FIT);
        grid.setColumnWidth(Ui.dp(a, 44));
        box.addView(grid, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(a, 320)));
        List<Object[]> cats = EmojiText.categories(a);
        Runnable[] select = new Runnable[cats.size()];
        for (int i = 0; i < cats.size(); i++) {
            @SuppressWarnings("unchecked") final List<String> list = (List<String>) cats.get(i)[1];
            TextView t = Ui.button(a, (String) cats.get(i)[0], false, null);
            select[i] = () -> grid.setAdapter(new BaseAdapter() {
                public int getCount() {
                    return list.size();
                }

                public Object getItem(int p) {
                    return list.get(p);
                }

                public long getItemId(int p) {
                    return p;
                }

                public View getView(int p, View old, ViewGroup parent) {
                    ImageView iv = old instanceof ImageView ? (ImageView) old : new ImageView(a);
                    iv.setPadding(Ui.dp(a, 6), Ui.dp(a, 6), Ui.dp(a, 6), Ui.dp(a, 6));
                    iv.setLayoutParams(new GridView.LayoutParams(Ui.dp(a, 44), Ui.dp(a, 44)));
                    iv.setImageBitmap(EmojiText.bitmap(list.get(p)));
                    return iv;
                }
            });
            final int k = i;
            t.setOnClickListener(v -> select[k].run());
            tabs.addView(t);
        }
        grid.setOnItemClickListener((parent, v, p, id) -> {
            String em = (String) parent.getItemAtPosition(p);
            int s = Math.max(0, input.getSelectionStart());
            input.getText().insert(s, em);
            d[0].dismiss();
        });
        select[0].run();
        d[0] = Ui.dialog(a).setView(box).setNegativeButton("Close", null).show();
    }

    private void stickerPicker() {
        final AlertDialog[] d = new AlertDialog[1];
        GridView grid = new GridView(a);
        grid.setNumColumns(4);
        grid.setAdapter(new BaseAdapter() {
            public int getCount() {
                return STICKERS.length;
            }

            public Object getItem(int p) {
                return STICKERS[p];
            }

            public long getItemId(int p) {
                return p;
            }

            public View getView(int p, View old, ViewGroup parent) {
                ImageView iv = old instanceof ImageView ? (ImageView) old : new ImageView(a);
                iv.setPadding(Ui.dp(a, 6), Ui.dp(a, 6), Ui.dp(a, 6), Ui.dp(a, 6));
                iv.setLayoutParams(new GridView.LayoutParams(Ui.dp(a, 76), Ui.dp(a, 76)));
                try (InputStream in = a.getAssets().open("stickers/" + STICKERS[p] + ".png")) {
                    iv.setImageBitmap(BitmapFactory.decodeStream(in));
                } catch (Exception ignored) {
                }
                return iv;
            }
        });
        grid.setOnItemClickListener((parent, v, p, id) -> {
            e.sendSticker(gid, STICKERS[p]);
            d[0].dismiss();
        });
        d[0] = Ui.dialog(a).setTitle("Stickers").setView(grid).setNegativeButton("Close", null).show();
    }

    private void pickFiles() {
        Intent i = new Intent(Intent.ACTION_GET_CONTENT).setType("*/*").addCategory(Intent.CATEGORY_OPENABLE)
                .putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
        a.startActivityForResult(Intent.createChooser(i, "Attach files"), REQ_ATTACH);
    }

    /** Results of the file and photo pickers (forwarded by MainActivity). */
    void onResult(int req, Intent data) {
        if (data == null) return;
        List<Uri> uris = new ArrayList<>();
        if (data.getClipData() != null)
            for (int i = 0; i < data.getClipData().getItemCount(); i++) uris.add(data.getClipData().getItemAt(i).getUri());
        else if (data.getData() != null) uris.add(data.getData());
        if (req == REQ_ATTACH && gid != null) {
            final String target = gid;
            ChatEngine.bg(() -> {
                List<File> files = new ArrayList<>();
                File sent = new File(new File(a.getFilesDir(), "chat"), "sent");
                sent.mkdirs();
                for (Uri u : uris) {
                    File f = Fs.unique(new File(sent, displayName(u)));
                    try (InputStream in = a.getContentResolver().openInputStream(u); FileOutputStream out = new FileOutputStream(f)) {
                        Fs.pipe(in, out);
                        files.add(f);
                    } catch (Exception ignored) {
                    }
                }
                e.sendFiles(target, files);
            });
        } else if (req == REQ_PHOTO && !uris.isEmpty()) {
            Bitmap src = loadUpright(uris.get(0), 1600);
            if (src == null) {
                Ui.toast(a, "That photo couldn't be used");
                return;
            }
            CropView cv = new CropView(a, src);
            LinearLayout box = new LinearLayout(a);
            box.setOrientation(LinearLayout.VERTICAL);
            box.addView(cv, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, Ui.dp(a, 340)));
            box.addView(Ui.text(a, "Drag to move · pinch to zoom", 13, Ui.DIM, false));
            Ui.dialog(a).setTitle("Crop your photo").setView(box)
                    .setNeutralButton("↻ Rotate", null)
                    .setPositiveButton("Use this photo", (d, w) -> {
                        ByteArrayOutputStream out = new ByteArrayOutputStream();
                        cv.result(512).compress(Bitmap.CompressFormat.JPEG, 90, out);
                        pendingPhoto = out.toByteArray();
                        if (afterPhoto != null) afterPhoto.run();
                    }).setNegativeButton("Cancel", null).show()
                    .getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v -> cv.rotate());
        } else if (req == REQ_WALL && !uris.isEmpty()) {
            File folder = new File(new File(a.getFilesDir(), "chat"), "wallpapers");
            folder.mkdirs();
            File f = new File(folder, "wall-" + System.currentTimeMillis() + ".jpg");
            Bitmap b = loadUpright(uris.get(0), 1600);
            if (b == null) return;
            try (FileOutputStream out = new FileOutputStream(f)) {
                b.compress(Bitmap.CompressFormat.JPEG, 88, out);
            } catch (Exception ignored) {
                return;
            }
            setWallpaper(wallFor, "file:" + f.getPath());
        }
    }

    /** A picture the right way up: phones save photos sideways plus a note to rotate them (EXIF). */
    private Bitmap loadUpright(Uri u, int maxPx) {
        try {
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inJustDecodeBounds = true;
            try (InputStream in = a.getContentResolver().openInputStream(u)) {
                BitmapFactory.decodeStream(in, null, o);
            }
            int s = 1;
            while (o.outWidth / (s * 2) >= maxPx || o.outHeight / (s * 2) >= maxPx) s *= 2;
            BitmapFactory.Options o2 = new BitmapFactory.Options();
            o2.inSampleSize = s;
            Bitmap b;
            try (InputStream in = a.getContentResolver().openInputStream(u)) {
                b = BitmapFactory.decodeStream(in, null, o2);
            }
            if (b == null) return null;
            int deg = 0;
            try (InputStream in = a.getContentResolver().openInputStream(u)) {
                android.media.ExifInterface ex = new android.media.ExifInterface(in);
                int or = ex.getAttributeInt(android.media.ExifInterface.TAG_ORIENTATION, android.media.ExifInterface.ORIENTATION_NORMAL);
                deg = or == android.media.ExifInterface.ORIENTATION_ROTATE_90 ? 90 : or == android.media.ExifInterface.ORIENTATION_ROTATE_180 ? 180
                        : or == android.media.ExifInterface.ORIENTATION_ROTATE_270 ? 270 : 0;
            } catch (Exception ignored) {
            }
            if (deg != 0) {
                android.graphics.Matrix m = new android.graphics.Matrix();
                m.postRotate(deg);
                b = Bitmap.createBitmap(b, 0, 0, b.getWidth(), b.getHeight(), m, true);
            }
            return b;
        } catch (Exception e) {
            return null;
        }
    }

    // ---------- wallpaper
    private static final Object[][] WALLS = {{"none", "None", 0, ""}, {"sky", "Sky", 0xffdbeafe, "dots"},
            {"mint", "Mint", 0xffd1fae5, "waves"}, {"sand", "Sand", 0xfffef3c7, "diagonal"}, {"rose", "Rose", 0xfffce7f3, "dots"},
            {"slate", "Slate", 0xffcbd5e1, "grid"}, {"night", "Night", 0xff1e293b, "dots"}, {"forest", "Forest", 0xff14532d, "waves"}};

    private String wallpaperId(String g) {
        String per = g == null ? "" : Ui.prefs(a).getString("chat_wall_" + g, "");
        return per.isEmpty() ? Ui.prefs(a).getString("chat_wall", "none") : per;
    }

    private void setWallpaper(String g, String id) {
        Ui.prefs(a).edit().putString(g == null ? "chat_wall" : "chat_wall_" + g, id).apply();
        render();
    }

    private android.graphics.drawable.Drawable tile(Object[] w) {
        int px = Ui.dp(a, 40), colour = (Integer) w[2];
        Bitmap b = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(b);
        c.drawColor(colour);
        boolean dark = colour == 0xff1e293b || colour == 0xff14532d;
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        p.setColor(dark ? 0x1affffff : 0x12000000);
        p.setStrokeWidth(Ui.dp(a, 1.5f));
        p.setStyle(Paint.Style.STROKE);
        float u = px / 40f;
        switch ((String) w[3]) {
            case "dots":
                p.setStyle(Paint.Style.FILL);
                c.drawCircle(10 * u, 10 * u, 2.2f * u, p);
                c.drawCircle(30 * u, 30 * u, 2.2f * u, p);
                break;
            case "waves":
                android.graphics.Path path = new android.graphics.Path();
                path.moveTo(0, 20 * u);
                path.quadTo(10 * u, 12 * u, 20 * u, 20 * u);
                path.quadTo(30 * u, 28 * u, 40 * u, 20 * u);
                c.drawPath(path, p);
                break;
            case "diagonal":
                c.drawLine(0, 40 * u, 40 * u, 0, p);
                break;
            default:
                c.drawLine(0, 0, 40 * u, 0, p);
                c.drawLine(0, 0, 0, 40 * u, p);
        }
        android.graphics.drawable.BitmapDrawable d = new android.graphics.drawable.BitmapDrawable(a.getResources(), b);
        d.setTileModeXY(android.graphics.Shader.TileMode.REPEAT, android.graphics.Shader.TileMode.REPEAT);
        return d;
    }

    private void applyWallpaper(FrameLayout wall) {
        String id = wallpaperId(gid);
        if (id.startsWith("file:")) {
            Bitmap b = decode(new File(id.substring(5)), Ui.dp(a, 900));
            if (b != null) {
                ImageView iv = new ImageView(a);
                iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
                iv.setImageBitmap(b);
                wall.addView(iv, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
            }
            return;
        }
        for (Object[] w : WALLS) if (w[0].equals(id) && !"none".equals(id)) wall.setBackground(tile(w));
    }

    private void chooseWallpaper(String g) {
        String[] names = new String[WALLS.length + 1 + (g != null ? 1 : 0)];
        for (int i = 0; i < WALLS.length; i++) names[i] = (String) WALLS[i][1];
        names[WALLS.length] = "📷 Your own picture…";
        if (g != null) names[WALLS.length + 1] = "Use the general wallpaper";
        Ui.dialog(a).setTitle(g == null ? "Chat wallpaper (all chats)" : "Wallpaper for this chat").setItems(names, (d, w) -> {
            if (w < WALLS.length) setWallpaper(g, (String) WALLS[w][0]);
            else if (w == WALLS.length) {
                wallFor = g;
                a.startActivityForResult(Intent.createChooser(new Intent(Intent.ACTION_GET_CONTENT).setType("image/*"), "Choose a picture"), REQ_WALL);
            } else setWallpaper(g, "");
        }).show();
    }

    // ---------- lock
    private void lockNow() {
        if (e.hasPin()) e.lockNow();
        else pinSettings();
    }

    private void renderLocked() {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER);
        TextView t = Ui.text(a, "🔒\nChat is locked", 22, Ui.TEXT, true);
        t.setGravity(Gravity.CENTER);
        box.addView(t);
        EditText pin = new EditText(a);
        pin.setHint("PIN");
        pin.setGravity(Gravity.CENTER);
        pin.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
        pin.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(4)});
        TextView msg = Ui.text(a, "Type your 4-digit PIN", 14, Ui.DIM, false);
        msg.setGravity(Gravity.CENTER);
        pin.addTextChangedListener(new android.text.TextWatcher() {
            public void beforeTextChanged(CharSequence s, int st, int c, int af) {
            }

            public void onTextChanged(CharSequence s, int st, int b, int c) {
            }

            public void afterTextChanged(android.text.Editable s) {
                if (s.length() == 4) {
                    String err = e.unlock(s.toString());
                    if (err != null) {
                        msg.setText(err);
                        s.clear();
                    }
                }
            }
        });
        box.addView(pin, new LinearLayout.LayoutParams(Ui.dp(a, 160), ViewGroup.LayoutParams.WRAP_CONTENT));
        box.addView(msg);
        box.addView(Ui.button(a, "Forgot PIN?", false, v -> Ui.confirm(a, "Reset the chat lock?",
                "The PIN is removed and the chat history on this phone is deleted, so nobody can use “forgot PIN” to read "
                        + "your messages. Friends and groups stay.", "Reset", e::resetLockAndHistory)));
        root.addView(box, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        pin.requestFocus();
    }

    private void pinSettings() {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 20), Ui.dp(a, 8), Ui.dp(a, 20), 0);
        box.addView(Ui.text(a, "Protect your chats on this phone with a 4-digit PIN. While locked, notifications don't "
                + "show names or messages.", 13, Ui.DIM, false));
        EditText p1 = new EditText(a), p2 = new EditText(a);
        for (EditText p : new EditText[]{p1, p2}) {
            p.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_VARIATION_PASSWORD);
            p.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(4)});
            box.addView(p);
        }
        p1.setHint("New 4-digit PIN");
        p2.setHint("Type it again");
        android.app.AlertDialog.Builder b = Ui.dialog(a).setTitle("Chat lock").setView(box).setPositiveButton("Save", (d, w) -> {
            String x = p1.getText().toString();
            if (x.length() != 4 || !x.equals(p2.getText().toString())) {
                Ui.toast(a, "The two PINs must match and have 4 digits");
                return;
            }
            e.setPin(x);
            Ui.toast(a, "🔒 Chat lock is on");
        }).setNegativeButton("Cancel", null);
        if (e.hasPin()) b.setNeutralButton("Remove PIN", (d, w) -> e.removePin());
        b.show();
    }

    private String displayName(Uri u) {
        try (Cursor c = a.getContentResolver().query(u, new String[]{OpenableColumns.DISPLAY_NAME}, null, null, null)) {
            if (c != null && c.moveToFirst()) {
                String n = c.getString(0);
                if (n != null && !n.isEmpty()) return n.replace('/', '_');
            }
        } catch (Exception ignored) {
        }
        return "file";
    }

    // ---------- menus
    private void plusMenu() {
        String[] items = {"👥  Add friends", "👥  New group", "🔑  Join a group with a code", "🔗  Show my friend code",
                "🔗  Enter a friend code"};
        Ui.dialog(a).setItems(items, (d, w) -> {
            if (w == 0) showPeople();
            else if (w == 1) newGroup();
            else if (w == 2) joinGroup();
            else if (w == 3) showFriendCode();
            else enterFriendCode();
        }).show();
    }

    private void listMenu() {
        String[] items = {"Your profile (name and photo)", "Keep chat connected (battery settings)", "Notification settings",
                "Chat wallpaper", "Chat lock (PIN)", "Linked devices (phone + PC, one account)"};
        Ui.dialog(a).setItems(items, (d, w) -> {
            if (w == 5) {
                linkedDevices();
                return;
            }
            if (w == 3) {
                chooseWallpaper(null);
                return;
            }
            if (w == 4) {
                pinSettings();
                return;
            }
            if (w == 0) editProfile(null);
            else if (w == 1) {
                Ui.info(a, "Keep chat connected", "Some phones stop apps in the background to save battery. In the list "
                        + "that opens, find Arckad-D and choose “Don't optimise” (or “Unrestricted”), so messages and "
                        + "friend requests keep arriving.");
                try {
                    a.startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
                } catch (Exception ignored) {
                }
            } else {
                try {
                    a.startActivity(new Intent("android.settings.APP_NOTIFICATION_SETTINGS")
                            .putExtra("android.provider.extra.APP_PACKAGE", a.getPackageName()));
                } catch (Exception ignored) {
                }
            }
        }).show();
    }

    private void convMenu() {
        JSONObject g = e.groups.get(gid);
        if (g == null) return;
        List<String> labels = new ArrayList<>();
        List<Runnable> acts = new ArrayList<>();
        if ("direct".equals(g.optString("kind"))) {
            if (!g.optBoolean("removed")) {
                labels.add("Safety code");
                acts.add(() -> Ui.info(a, "Safety code with " + title(gid), e.safetyCode(g.optString("peer"))
                        + "\n\nOpen this on your friend's device too. If both show the same numbers, your chat is private."));
                labels.add("Remove friend");
                acts.add(() -> Ui.confirm(a, "Remove " + title(gid) + "?", "You can't message each other until one of you "
                        + "sends a new friend request. Your history stays here.", "Remove", () -> {
                    e.removeFriend(g.optString("peer"));
                    show("list", null);
                }));
            }
        } else {
            boolean owner = e.isOwner(gid);
            if (owner && !g.optBoolean("removed")) {
                labels.add("Invite people (join code)");
                acts.add(this::invite);
            }
            labels.add("Members");
            acts.add(this::members);
            if (owner) {
                labels.add(g.optBoolean("owner_only") ? "Let everyone post" : "Only I can post (announcements)");
                acts.add(() -> e.setOwnerOnly(gid, !g.optBoolean("owner_only")));
                labels.add("Rename group");
                acts.add(() -> Ui.askText(a, "Rename group", g.optString("name"), "Rename", n -> {
                    if (!n.isEmpty()) e.renameGroup(gid, n);
                }));
            }
            labels.add(owner ? "Delete group for everyone" : "Leave group");
            acts.add(() -> Ui.confirm(a, owner ? "Delete “" + g.optString("name") + "” for everyone?" : "Leave “" + g.optString("name") + "”?",
                    owner ? "All members are removed. Each keeps their own history." : "You'd need a new join code to come back.",
                    owner ? "Delete" : "Leave", () -> {
                        String target = gid;
                        show("list", null);
                        ChatEngine.bg(() -> e.leaveGroup(target));
                    }));
        }
        labels.add("Wallpaper for this chat");
        acts.add(() -> chooseWallpaper(gid));
        labels.add("Open received files");
        acts.add(() -> a.openFolder(e.filesDir(gid)));
        Ui.dialog(a).setItems(labels.toArray(new String[0]), (d, w) -> acts.get(w).run()).show();
    }

    private void members() {
        JSONObject g = e.groups.get(gid);
        JSONObject mem = g.optJSONObject("members");
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 16), Ui.dp(a, 8), Ui.dp(a, 16), 0);
        final AlertDialog[] d = new AlertDialog[1];
        for (Iterator<String> it = mem.keys(); it.hasNext(); ) {
            String did = it.next();
            JSONObject m = mem.optJSONObject(did);
            boolean on = did.equals(e.me) || e.isOnline(did);
            TextView t = Ui.text(a, (on ? "🟢 " : "⚪ ") + m.optString("name") + (did.equals(e.me) ? " (you)" : "") + "\n"
                    + ("owner".equals(m.optString("role")) ? "owner" : "member") + " · " + m.optString("os"), 15, Ui.TEXT, false);
            LinearLayout row = new LinearLayout(a);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.addView(t, MainActivity.grow());
            if (!did.equals(e.me) && !e.friends().has(did)) {
                String rel = e.relation(did);
                row.addView(Ui.button(a, "outgoing".equals(rel) ? "Sent" : "incoming".equals(rel) ? "Accept" : "Add friend", false, v -> {
                    if ("incoming".equals(e.relation(did))) {
                        e.acceptRequest(did);
                        return;
                    }
                    if (!e.people.containsKey(did)) {
                        JSONObject o = e.online.get(did);
                        e.people.put(did, new Obj().putOpt("name", m.optString("name")).putOpt("ip", o == null ? "" : o.optString("ip"))
                                .putOpt("port", o == null ? 0 : o.optInt("port")).putOpt("ph", "").putOpt("os", "").putOpt("seen", 0).putOpt("hidden", true));
                    }
                    Ui.toast(a, "Sending…");
                    ChatEngine.bg(() -> {
                        String err = e.sendRequest(did);
                        a.runOnUiThread(() -> Ui.toast(a, err == null ? "Friend request sent ✓" : err));
                    });
                }));
            }
            if (e.isOwner(gid) && !did.equals(e.me)) row.addView(Ui.button(a, "Remove", false, v -> Ui.confirm(a,
                    "Remove " + m.optString("name") + "?", "They can't read anything new in this group.", "Remove", () -> {
                        d[0].dismiss();
                        e.removeMember(gid, did);
                    })));
            box.addView(row, Ui.matchWrap(a, 6));
        }
        android.app.AlertDialog.Builder db = Ui.dialog(a).setTitle("Members of " + g.optString("name")).setView(box).setPositiveButton("Close", null);
        if (e.isOwner(gid) && !g.optBoolean("removed")) db.setNeutralButton("Add friends", (x, w) -> addFriendsToGroup());
        d[0] = db.show();
    }

    private void addFriendsToGroup() {
        JSONObject g = e.groups.get(gid);
        List<String> ids = new ArrayList<>();
        for (Iterator<String> it = e.friends().keys(); it.hasNext(); ) {
            String pid = it.next();
            if (!g.optJSONObject("members").has(pid)) ids.add(pid);
        }
        if (ids.isEmpty()) {
            Ui.info(a, "Add friends", "All your friends are already in this group (or you have no friends yet).");
            return;
        }
        String[] names = new String[ids.size()];
        boolean[] pick = new boolean[ids.size()];
        for (int i = 0; i < ids.size(); i++) names[i] = e.friends().optJSONObject(ids.get(i)).optString("name");
        Ui.dialog(a).setTitle("Add friends to " + g.optString("name")).setMultiChoiceItems(names, pick, (d, w, on) -> pick[w] = on)
                .setPositiveButton("Add", (d, w) -> {
                    List<String> chosen = new ArrayList<>();
                    for (int i = 0; i < pick.length; i++) if (pick[i]) chosen.add(ids.get(i));
                    String target = gid;
                    ChatEngine.bg(() -> {
                        int n = e.addFriendsToGroup(target, chosen);
                        a.runOnUiThread(() -> Ui.toast(a, "Added " + n + (n == 1 ? " friend" : " friends")));
                    });
                }).setNegativeButton("Cancel", null).show();
    }

    private void newGroup() {
        if (!e.profile.optBoolean("setup")) {
            editProfile(this::newGroup);
            return;
        }
        Ui.askText(a, "New group", "", "Create", n -> {
            if (n.isEmpty()) return;
            String g = e.createGroup(n);
            show("conv", g);
            invite();
        });
    }

    private void invite() {
        String code = e.newJoinCode(gid);
        TextView t = Ui.text(a, code.substring(0, 3) + " " + code.substring(3), 34, Ui.TEXT, true);
        t.setGravity(Gravity.CENTER);
        t.setLetterSpacing(0.15f);
        List<String> ips = Net.lanAddresses();
        TextView h = Ui.text(a, "Others: ＋ → Join a group with a code, and type this. You then approve them.\n"
                + "From another network they also type this phone's address: " + (ips.isEmpty() ? "?" : ips.get(0))
                + "\nValid for 10 minutes.", 13, Ui.DIM, false);
        h.setGravity(Gravity.CENTER);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 16), Ui.dp(a, 12), Ui.dp(a, 16), 0);
        box.addView(t);
        box.addView(h);
        Ui.dialog(a).setTitle("Join code for " + title(gid)).setView(box).setPositiveButton("Done", null)
                .setNegativeButton("Stop inviting", (d, w) -> e.stopJoin()).show();
    }

    private void joinGroup() {
        if (!e.profile.optBoolean("setup")) {
            editProfile(this::joinGroup);
            return;
        }
        codeDialog("Join a group", "6-digit join code", true, (code, ip) -> {
            String err = e.joinWithCode(code.replaceAll("[^0-9]", ""), ip);
            a.runOnUiThread(() -> {
                if (err == null) {
                    Ui.toast(a, "Joined ✓");
                    render();
                } else Ui.info(a, "Couldn't join", err);
            });
        });
    }

    interface CodeResult {
        void got(String code, String ip);
    }

    private void codeDialog(String title, String hint, boolean digits, CodeResult r) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 20), Ui.dp(a, 8), Ui.dp(a, 20), 0);
        EditText code = new EditText(a);
        code.setHint(hint);
        code.setInputType(digits ? InputType.TYPE_CLASS_NUMBER : InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        EditText ip = new EditText(a);
        ip.setHint("Their IP (only if on another network)");
        ip.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        box.addView(code);
        box.addView(ip);
        Ui.dialog(a).setTitle(title).setView(box).setPositiveButton("OK", (d, w) -> {
            String c = code.getText().toString(), h = ip.getText().toString().trim();
            Ui.toast(a, "Connecting…");
            ChatEngine.bg(() -> r.got(c, h.isEmpty() ? null : h));
        }).setNegativeButton("Cancel", null).show();
    }

    private void showFriendCode() {
        if (!e.profile.optBoolean("setup")) {
            editProfile(this::showFriendCode);
            return;
        }
        String code = e.newFriendCode();
        TextView t = Ui.text(a, code.substring(0, 3) + "-" + code.substring(3), 34, Ui.TEXT, true);
        t.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        t.setGravity(Gravity.CENTER);
        List<String> ips = Net.lanAddresses();
        TextView h = Ui.text(a, "Your friend chooses “Enter a friend code” and types this. From another network or VLAN "
                + "they also type this phone's address: " + (ips.isEmpty() ? "?" : ips.get(0)) + "\nValid for 10 minutes. "
                + "Anyone with the code becomes your friend, so share it only with them.", 13, Ui.DIM, false);
        h.setGravity(Gravity.CENTER);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 16), Ui.dp(a, 12), Ui.dp(a, 16), 0);
        box.addView(t);
        box.addView(h);
        Ui.dialog(a).setTitle("Your friend code").setView(box).setPositiveButton("Done", null)
                .setNegativeButton("Stop", (d, w) -> e.stopFriendCode()).show();
    }

    private void enterFriendCode() {
        if (!e.profile.optBoolean("setup")) {
            editProfile(this::enterFriendCode);
            return;
        }
        codeDialog("Enter a friend code", "ABC-123", false, (code, ip) -> {
            String err = e.addByCode(code, ip);
            a.runOnUiThread(() -> {
                if (err == null) Ui.toast(a, "🤝 You're friends now");
                else Ui.info(a, "Couldn't add the friend", err);
            });
        });
    }

    private void addWithProfileCode() {
        EditText in = new EditText(a);
        in.setHint("AR-XXXX-XXXX-XXXXX");
        in.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS);
        Ui.dialog(a).setTitle("Add with a profile code").setView(in).setPositiveButton("Send friend request", (d, w) -> {
            String code = in.getText().toString();
            Ui.toast(a, "Looking up the code…");
            ChatEngine.bg(() -> {
                String err = e.addByProfileCode(code);
                a.runOnUiThread(() -> {
                    if (err == null) Ui.info(a, "Friend request sent ✓", "You'll be friends when they accept.");
                    else Ui.info(a, "Couldn't send the request", err);
                    render();
                });
            });
        }).setNegativeButton("Cancel", null).show();
    }

    // ---------- people
    private void showPeople() {
        if (!e.profile.optBoolean("setup")) {
            editProfile(this::showPeople);
            return;
        }
        hub.start();
        show("people", null);
    }

    private void renderPeople() {
        ScrollView sc = new ScrollView(a);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 12), 0, Ui.dp(a, 12), Ui.dp(a, 12));
        sc.addView(box);
        section(box, "Your profile code (anyone can send you a friend request with it, from any network)");
        String pcode = e.profileCode();
        TextView pc = Ui.text(a, pcode == null ? "Connect to Wi-Fi to get your code" : pcode, 20, Ui.TEXT, true);
        pc.setTypeface(Typeface.MONOSPACE, Typeface.BOLD);
        pc.setTextIsSelectable(true);
        box.addView(pc);
        if (pcode != null) box.addView(Ui.row(a, Ui.button(a, "Copy", false, v -> {
            android.content.ClipboardManager cm = (android.content.ClipboardManager) a.getSystemService(android.content.Context.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(android.content.ClipData.newPlainText("profile code", pcode));
            Ui.toast(a, "Profile code copied");
        }), Ui.button(a, "Share", false, v -> a.startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND).setType("text/plain")
                .putExtra(Intent.EXTRA_TEXT, "Add me on Arckad-D: " + pcode), "Share your profile code"))),
                Ui.button(a, "Add with a code", true, v -> addWithProfileCode())));
        section(box, "Add a friend with a one-time code");
        box.addView(Ui.row(a, Ui.button(a, "Show my friend code", false, v -> showFriendCode()),
                Ui.button(a, "Enter a friend code", false, v -> enterFriendCode())));
        JSONObject inc = e.incoming();
        if (inc.length() > 0) {
            section(box, "Friend requests (" + inc.length() + ")");
            for (Iterator<String> it = inc.keys(); it.hasNext(); ) {
                String pid = it.next();
                box.addView(person(pid, inc.optJSONObject(pid).optString("name"), "wants to be your friend",
                        Ui.button(a, "Accept", true, v -> e.acceptRequest(pid)), Ui.button(a, "Decline", false, v -> e.declineRequest(pid))));
            }
        }
        section(box, "People on your network");
        List<String> found = new ArrayList<>();
        for (String pid : e.peopleList()) if (!"friend".equals(e.relation(pid))) found.add(pid);
        if (found.isEmpty()) box.addView(Ui.text(a, "Nobody else found yet. Colleagues appear here when they open "
                + "Arckad-D with their profile set up (same Wi-Fi network). On another network, use a friend code.", 13, Ui.DIM, false));
        for (String pid : found) {
            JSONObject p = e.people.get(pid);
            String rel = e.relation(pid);
            View[] btns = "outgoing".equals(rel) ? new View[]{Ui.button(a, "Cancel", false, v -> e.cancelRequest(pid))}
                    : "incoming".equals(rel) ? new View[]{Ui.button(a, "Accept", true, v -> e.acceptRequest(pid))}
                    : new View[]{Ui.button(a, "Add friend", true, v -> {
                Ui.toast(a, "Sending…");
                ChatEngine.bg(() -> {
                    String err = e.sendRequest(pid);
                    a.runOnUiThread(() -> Ui.toast(a, err == null ? "Friend request sent ✓" : err));
                });
            })};
            box.addView(person(pid, p.optString("name"), ("outgoing".equals(rel) ? "request sent · " : "") + p.optString("os")
                    + " · on your network", btns));
        }
        JSONObject fr = e.friends();
        section(box, "Friends (" + fr.length() + ")");
        if (fr.length() == 0) box.addView(Ui.text(a, "No friends yet: use Add friend above.", 13, Ui.DIM, false));
        List<String> names = new ArrayList<>();
        for (Iterator<String> it = fr.keys(); it.hasNext(); ) names.add(it.next());
        Collections.sort(names, (x, y) -> fr.optJSONObject(x).optString("name").compareToIgnoreCase(fr.optJSONObject(y).optString("name")));
        for (String pid : names) {
            JSONObject f = fr.optJSONObject(pid);
            String sub = f.optJSONObject("pending_accept") != null ? "finishing… (they need to come online)"
                    : e.personOnline(pid) ? "🟢 online" : "⚪ offline";
            box.addView(person(pid, f.optString("name"), sub, Ui.button(a, "Message", true, v -> show("conv", e.directGid(pid)))));
        }
        root.addView(sc);
    }

    private void section(LinearLayout box, String title) {
        TextView t = Ui.text(a, title, 14, Ui.ACCENT, true);
        t.setPadding(0, Ui.dp(a, 16), 0, Ui.dp(a, 6));
        box.addView(t);
    }

    private View person(String pid, String name, String sub, View... buttons) {
        LinearLayout row = new LinearLayout(a);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(0, Ui.dp(a, 6), 0, Ui.dp(a, 6));
        ImageView av = new ImageView(a);
        av.setImageBitmap(avatar(name, e.avatarFile(pid), 42, false));
        row.addView(av, new LinearLayout.LayoutParams(Ui.dp(a, 42), Ui.dp(a, 42)));
        LinearLayout t = new LinearLayout(a);
        t.setOrientation(LinearLayout.VERTICAL);
        t.setPadding(Ui.dp(a, 10), 0, 0, 0);
        t.addView(Ui.text(a, name, 15, Ui.TEXT, true));
        t.addView(Ui.text(a, sub, 12, Ui.DIM, false));
        row.addView(t, MainActivity.grow());
        for (View b : buttons) row.addView(b);
        return row;
    }

    // ---------- profile
    void editProfile(Runnable then) {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setGravity(Gravity.CENTER_HORIZONTAL);
        box.setPadding(Ui.dp(a, 20), Ui.dp(a, 12), Ui.dp(a, 20), 0);
        ImageView pic = new ImageView(a);
        EditText name = new EditText(a);
        name.setText(e.myName());
        name.setSingleLine(true);
        final boolean[] remove = {false};
        pendingPhoto = null;
        Runnable refresh = () -> {
            Bitmap b;
            if (pendingPhoto != null) b = round(BitmapFactory.decodeByteArray(pendingPhoto, 0, pendingPhoto.length), Ui.dp(a, 96));
            else b = avatar(name.getText().toString(), remove[0] ? null : e.avatarFile(e.me), 96, false);
            pic.setImageBitmap(b);
        };
        refresh.run();
        afterPhoto = () -> {
            remove[0] = false;
            refresh.run();
        };
        box.addView(pic, new LinearLayout.LayoutParams(Ui.dp(a, 96), Ui.dp(a, 96)));
        box.addView(Ui.row(a, Ui.button(a, "Choose photo", false, v -> a.startActivityForResult(
                Intent.createChooser(new Intent(Intent.ACTION_GET_CONTENT).setType("image/*"), "Choose your photo"), REQ_PHOTO)),
                Ui.button(a, "Remove photo", false, v -> {
                    pendingPhoto = null;
                    remove[0] = true;
                    refresh.run();
                })));
        box.addView(Ui.text(a, "Your name (what colleagues see):", 13, Ui.DIM, false));
        box.addView(name, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        Switch vis = new Switch(a);
        vis.setText("Let people on my network find me");
        vis.setTextColor(Ui.TEXT);
        vis.setChecked(e.profile.optBoolean("visible", true));
        box.addView(vis, Ui.matchWrap(a, 10));
        box.addView(Ui.text(a, "Your name and photo appear in colleagues' People list so they can send you a friend "
                + "request. Off: only your friends see you.", 12, Ui.DIM, false));
        Ui.dialog(a).setTitle("Your profile").setView(box).setPositiveButton("Save", (d, w) -> {
            String n = name.getText().toString().trim();
            e.setProfile(n.isEmpty() ? e.myName() : n, pendingPhoto, remove[0], vis.isChecked());
            avatars.evictAll();
            hub.start();
            a.refreshTopBar();
            render();
            if (then != null) then.run();
        }).setNegativeButton("Cancel", null).show();
    }

    // ---------- avatars: a photo, or coloured initials in a circle
    private Bitmap chatAvatar(String g, int dp) {
        JSONObject grp = e.groups.get(g);
        if (grp != null && "direct".equals(grp.optString("kind")))
            return avatar(title(g), e.avatarFile(grp.optString("peer")), dp, false);
        return avatar(title(g), null, dp, true);
    }

    Bitmap avatar(String name, File photo, int dp, boolean group) {
        int px = Ui.dp(a, dp);
        String key = name + "|" + (photo == null ? "" : photo.getPath() + photo.lastModified()) + "|" + px + group;
        Bitmap b = avatars.get(key);
        if (b != null) return b;
        if (photo != null) {
            Bitmap src = BitmapFactory.decodeFile(photo.getPath());
            if (src != null) b = round(src, px);
        }
        if (b == null) {
            b = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888);
            Canvas c = new Canvas(b);
            Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
            p.setColor(AV_COLOURS[Math.abs(name.hashCode()) % AV_COLOURS.length]);
            if (group) c.drawRoundRect(new RectF(0, 0, px, px), px * 0.26f, px * 0.26f, p);
            else c.drawCircle(px / 2f, px / 2f, px / 2f, p);
            p.setColor(Color.WHITE);
            p.setTextSize(px * 0.4f);
            p.setTypeface(Typeface.DEFAULT_BOLD);
            p.setTextAlign(Paint.Align.CENTER);
            String ini = initials(name);
            Rect r = new Rect();
            p.getTextBounds(ini, 0, ini.length(), r);
            c.drawText(ini, px / 2f, px / 2f + r.height() / 2f, p);
        }
        avatars.put(key, b);
        return b;
    }

    static String initials(String name) {
        List<String> words = new ArrayList<>();
        for (String w : name.replace("(", " ").split("\\s+")) if (!w.isEmpty() && Character.isLetterOrDigit(w.charAt(0))) words.add(w);
        if (words.isEmpty()) return "?";
        String s = words.get(0).substring(0, 1) + (words.size() > 1 ? words.get(1).substring(0, 1) : "");
        return s.toUpperCase(Locale.getDefault());
    }

    static Bitmap round(Bitmap src, int px) {
        int side = Math.min(src.getWidth(), src.getHeight());
        Bitmap sq = Bitmap.createBitmap(src, (src.getWidth() - side) / 2, (src.getHeight() - side) / 2, side, side);
        Bitmap scaled = Bitmap.createScaledBitmap(sq, px, px, true);
        Bitmap out = Bitmap.createBitmap(px, px, Bitmap.Config.ARGB_8888);
        Canvas c = new Canvas(out);
        Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
        c.drawCircle(px / 2f, px / 2f, px / 2f, p);
        p.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.SRC_IN));
        c.drawBitmap(scaled, 0, 0, p);
        return out;
    }

    private static Bitmap decode(File f, int maxPx) {
        BitmapFactory.Options o = new BitmapFactory.Options();
        o.inJustDecodeBounds = true;
        BitmapFactory.decodeFile(f.getPath(), o);
        int s = 1;
        while (o.outWidth / (s * 2) >= maxPx && o.outHeight / (s * 2) >= maxPx) s *= 2;
        o = new BitmapFactory.Options();
        o.inSampleSize = s;
        return BitmapFactory.decodeFile(f.getPath(), o);
    }

    // ================================================================= hub events
    @Override
    public void chatChanged(String g) {
        if ("conv".equals(page) && g != null && !g.equals(gid)) {
            a.refreshTopBar();
            return;
        }
        if ("conv".equals(page) && gid != null) e.unread.put(gid, 0);
        render();
        a.refreshTopBar();
    }

    @Override
    public void peopleChanged() {
        if ("people".equals(page) || "list".equals(page)) render();
        a.refreshTopBar();
    }

    @Override
    public void askJoin(ChatEngine.Ask ev) {
        Ui.dialog(a).setTitle("Let " + ev.name + " join “" + ev.group + "”?")
                .setMessage(ev.name + " (" + ev.os + ") typed the correct join code. Members can read and post in this group.")
                .setPositiveButton("Let them join", (d, w) -> {
                    ev.accepted = true;
                    ev.done.countDown();
                })
                .setNegativeButton("Decline", (d, w) -> ev.done.countDown())
                .setOnCancelListener(d -> ev.done.countDown()).show();
    }

    @Override
    public void chatEvent(String text) {
        Ui.toast(a, text);
    }

    @Override
    public void askLink(ChatEngine.Ask ev) {
        Ui.dialog(a).setTitle("Link " + ev.name + " to your account?")
                .setMessage(ev.name + " (" + ev.os + ") typed your link code. It gets your profile, friends, groups and chat "
                        + "history, and can send messages as you. Only link your own devices.")
                .setPositiveButton("Link", (d, w) -> {
                    ev.accepted = true;
                    ev.done.countDown();
                })
                .setNegativeButton("Cancel", (d, w) -> ev.done.countDown())
                .setOnCancelListener(d -> ev.done.countDown()).show();
    }

    @Override
    public void relinked() {
        e = hub.engine;
        avatars.evictAll();
        show("list", null);
    }

    private void linkedDevices() {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 20), Ui.dp(a, 8), Ui.dp(a, 20), 0);
        box.addView(Ui.text(a, "Use one chat account on your phone and PC: the same profile, friends, groups and history. "
                + "Messages arrive on both, and what you send from one shows on the other.", 13, Ui.DIM, false));
        final AlertDialog[] d = new AlertDialog[1];
        JSONObject tw = e.link.twins();
        for (Iterator<String> it = tw.keys(); it.hasNext(); ) {
            String inst = it.next();
            JSONObject t = tw.optJSONObject(inst);
            LinearLayout row = new LinearLayout(a);
            row.setGravity(Gravity.CENTER_VERTICAL);
            row.addView(Ui.text(a, (e.link.twinOnline(inst) ? "🟢 " : "⚪ ") + t.optString("name") + " (" + t.optString("os") + ")",
                    15, Ui.TEXT, false), MainActivity.grow());
            row.addView(Ui.button(a, "Unlink", false, v -> Ui.confirm(a, "Unlink " + t.optString("name") + "?",
                    "The shared chat account is removed from it and it stops receiving your messages.", "Unlink", () -> {
                        d[0].dismiss();
                        ChatEngine.bg(() -> e.link.unlink(inst));
                    })));
            box.addView(row, Ui.matchWrap(a, 6));
        }
        if (tw.length() == 0) box.addView(Ui.text(a, "No linked devices yet.", 14, Ui.DIM, false));
        d[0] = Ui.dialog(a).setTitle("Linked devices").setView(box)
                .setPositiveButton("Link a new device", (x, w) -> showLinkCode())
                .setNeutralButton("Link THIS phone", (x, w) -> linkThisPhone())
                .setNegativeButton("Close", null).show();
    }

    private void showLinkCode() {
        String code = e.link.newCode();
        TextView t = Ui.text(a, code.substring(0, 3) + " " + code.substring(3), 34, Ui.TEXT, true);
        t.setGravity(Gravity.CENTER);
        List<String> ips = Net.lanAddresses();
        TextView h = Ui.text(a, "On your PC: Chat → ⋯ → Linked devices → Link THIS device, and type this code. Then "
                + "confirm here. From another network it also needs this phone's address: " + (ips.isEmpty() ? "?" : ips.get(0))
                + "\nValid 10 minutes.", 13, Ui.DIM, false);
        h.setGravity(Gravity.CENTER);
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 16), Ui.dp(a, 12), Ui.dp(a, 16), 0);
        box.addView(t);
        box.addView(h);
        Ui.dialog(a).setTitle("Link code").setView(box).setPositiveButton("Done", null)
                .setNegativeButton("Stop", (x, w) -> e.link.stopCode()).show();
    }

    private void linkThisPhone() {
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(Ui.dp(a, 20), Ui.dp(a, 8), Ui.dp(a, 20), 0);
        box.addView(Ui.text(a, "On your PC: Chat → ⋯ → Linked devices → Link a new device. Type the code it shows. "
                + "This phone's current chat profile is replaced by that account.", 13, Ui.DIM, false));
        EditText code = new EditText(a);
        code.setHint("6-digit link code");
        code.setInputType(InputType.TYPE_CLASS_NUMBER);
        EditText ip = new EditText(a);
        ip.setHint("PC's IP (only if on another network)");
        box.addView(code);
        box.addView(ip);
        Ui.dialog(a).setTitle("Link this phone to my account").setView(box).setPositiveButton("Link", (x, w) -> {
            String c = code.getText().toString().replaceAll("[^0-9]", ""), host = ip.getText().toString().trim();
            Ui.toast(a, "Linking… confirm on the PC");
            ChatEngine.bg(() -> {
                String err = e.link.linkWithCode(c, host.isEmpty() ? null : host);
                a.runOnUiThread(() -> {
                    if (err == null) Ui.info(a, "Linked ✓", "This phone now uses your account. Your chats are copying over.");
                    else Ui.info(a, "Couldn't link", err);
                });
            });
        }).setNegativeButton("Cancel", null).show();
    }

    private void askNotifications() {
        if (askedNotif || Build.VERSION.SDK_INT < 33) return;
        askedNotif = true;
        if (a.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
            a.requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, 7103);
    }
}

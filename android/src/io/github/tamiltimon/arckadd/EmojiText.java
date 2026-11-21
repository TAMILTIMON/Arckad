package io.github.tamiltimon.arckadd;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.drawable.BitmapDrawable;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.style.ImageSpan;
import android.util.LruCache;

import org.json.JSONArray;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.Enumeration;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/** Arckad-D's own emoji (Noto Emoji by Google, Apache 2.0 — the same set as the desktop), drawn inside text,
 *  so emojis look the same on every phone and computer. */
final class EmojiText {
    private static ZipFile zip;
    private static final Set<String> keys = new HashSet<>();
    private static final LruCache<String, Bitmap> cache = new LruCache<>(400);
    static final String[] WORK = ("✅ ☑️ ✔️ ❌ 👍 👎 👌 🙏 👏 🤝 💪 📌 📎 📅 📆 ⏰ ⏳ ⚠️ ❗ ❓ 💡 📊 📈 📉 📝 ✏️ 📄 📁 📂 🗂️ 💼 🖥️ 💻 📱 ☎️ "
            + "📧 📨 🔒 🔑 🔔 🚀 🎯 🏁 ⭐ 🔥 ✨ 🎉 ☕ 🍕 🏠 🚗 ✈️ 🌐 🛠️ 🐞 🧾 💰 💳 📦 🔗 🔍 ♻️ 🟢 🟡 🔴 ➡️ ⬆️ ⬇️ 🔄").split(" ");

    private EmojiText() {
    }

    static synchronized boolean init(Context c) {
        if (zip != null) return true;
        try {
            File f = new File(c.getFilesDir(), "noto-emoji-v1.zip");
            if (!f.exists()) {
                File tmp = new File(f.getPath() + ".tmp");
                try (InputStream in = c.getAssets().open("emoji/noto-emoji.zip"); FileOutputStream out = new FileOutputStream(tmp)) {
                    Fs.pipe(in, out);
                }
                tmp.renameTo(f);
            }
            zip = new ZipFile(f);
            for (Enumeration<? extends ZipEntry> e = zip.entries(); e.hasMoreElements(); ) {
                String n = e.nextElement().getName();
                if (n.endsWith(".png")) keys.add(n.substring(0, n.length() - 4));
            }
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    static String key(String e) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < e.length(); ) {
            int cp = e.codePointAt(i);
            i += Character.charCount(cp);
            if (cp == 0xfe0f) continue;
            if (b.length() > 0) b.append('_');
            b.append(String.format(java.util.Locale.ROOT, "%04x", cp));
        }
        return b.toString();
    }

    static Bitmap bitmap(String emoji) {
        String k = key(emoji);
        Bitmap b = cache.get(k);
        if (b != null || zip == null || !keys.contains(k)) return b;
        try (InputStream in = zip.getInputStream(zip.getEntry(k + ".png"))) {
            b = BitmapFactory.decodeStream(in);
            if (b != null) cache.put(k, b);
        } catch (Exception ignored) {
        }
        return b;
    }

    /** Text with Arckad-D's emoji images (longest emoji sequence first, like the desktop). */
    static CharSequence span(Context c, String text, int px) {
        if (zip == null && !init(c)) return text;
        SpannableStringBuilder out = new SpannableStringBuilder();
        int[] cps = text.codePoints().toArray();
        int i = 0;
        while (i < cps.length) {
            int best = 0;
            if (cps[i] > 0x2000 || "#*0123456789".indexOf(cps[i]) >= 0) {
                for (int len = Math.min(10, cps.length - i); len > 0; len--) {
                    if (keys.contains(key(new String(cps, i, len)))) {
                        best = len;
                        break;
                    }
                }
            }
            if (best > 0) {
                int end = i + best;
                if (end < cps.length && cps[end] == 0xfe0f) end++;
                String e = new String(cps, i, end - i);
                Bitmap b = bitmap(e);
                int start = out.length();
                out.append(e);
                if (b != null) {
                    BitmapDrawable d = new BitmapDrawable(c.getResources(), b);
                    d.setBounds(0, 0, px, px);
                    out.setSpan(new ImageSpan(d, ImageSpan.ALIGN_BOTTOM), start, out.length(), Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
                }
                i = end;
            } else {
                out.append(new String(cps, i, 1));
                i++;
            }
        }
        return out;
    }

    /** True for a short message made only of emojis (shown big). */
    static int onlyEmojiCount(String text) {
        if (zip == null) return 0;
        String t = text.replace(" ", "");
        int n = 0;
        int[] cps = t.codePoints().toArray();
        int i = 0;
        while (i < cps.length) {
            int best = 0;
            for (int len = Math.min(10, cps.length - i); len > 0; len--)
                if (keys.contains(key(new String(cps, i, len)))) {
                    best = len;
                    break;
                }
            if (best == 0) return 0;
            i += best;
            if (i < cps.length && cps[i] == 0xfe0f) i++;
            n++;
        }
        return n;
    }

    /** Picker tabs: Work first, then every category (from the same categories.json as the desktop). */
    static List<Object[]> categories(Context c) {
        List<Object[]> tabs = new ArrayList<>();
        List<String> work = new ArrayList<>();
        for (String w : WORK) work.add(w);
        tabs.add(new Object[]{"Work", work});
        try (InputStream in = c.getAssets().open("emoji/categories.json")) {
            JSONArray a = new JSONArray(new String(ChatEngine.readStream(in, 1_000_000), "UTF-8"));
            for (int i = 0; i < a.length(); i++) {
                JSONArray t = a.getJSONArray(i);
                List<String> list = new ArrayList<>();
                JSONArray chars = t.getJSONArray(1);
                for (int k = 0; k < chars.length(); k++) list.add(chars.getString(k));
                tabs.add(new Object[]{t.getString(0), list});
            }
        } catch (Exception ignored) {
        }
        return tabs;
    }
}

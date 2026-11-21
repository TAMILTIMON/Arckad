package io.github.tamiltimon.arckadd;

import android.os.Environment;
import android.webkit.MimeTypeMap;

import java.io.BufferedInputStream;
import java.io.BufferedOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Collections;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/** File helpers: kinds, sizes, dates, listing, copy / move / delete, zip. */
final class Fs {
    private Fs() {
    }

    static final class Entry {
        final File f;
        final String name, ext, kind;
        final boolean dir;
        final long size, mod;

        Entry(File f) {
            this.f = f;
            name = f.getName();
            dir = f.isDirectory();
            ext = ext(name);
            kind = dir ? "Folder" : kindOf(ext);
            size = dir ? 0 : f.length();
            mod = f.lastModified();
        }
    }

    static String ext(String name) {
        int i = name.lastIndexOf('.');
        return i > 0 ? name.substring(i + 1).toLowerCase(Locale.ROOT) : "";
    }

    static final String[] IMAGES = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif"};
    static final String[] VIDEOS = {"mp4", "mkv", "avi", "mov", "webm", "3gp", "flv", "wmv", "m4v", "ts"};
    static final String[] AUDIO = {"mp3", "wav", "flac", "ogg", "m4a", "aac", "opus", "amr", "wma"};
    static final String[] DOCS = {"pdf", "doc", "docx", "odt", "txt", "rtf", "md", "epub", "xls", "xlsx",
            "ods", "csv", "ppt", "pptx", "odp"};
    static final String[] ARCHIVES = {"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz"};
    static final String[] TEXT = {"txt", "md", "csv", "tsv", "log", "json", "xml", "html", "htm", "css", "js",
            "py", "java", "kt", "c", "cpp", "h", "sh", "yaml", "yml", "ini", "srt", "conf", "properties"};

    static boolean in(String ext, String[] list) {
        for (String s : list) if (s.equals(ext)) return true;
        return false;
    }

    static String kindOf(String ext) {
        if (in(ext, IMAGES)) return "Images";
        if (in(ext, VIDEOS)) return "Videos";
        if (in(ext, AUDIO)) return "Audio";
        if (ext.equals("apk") || ext.equals("apks") || ext.equals("xapk")) return "Apps";
        if (in(ext, ARCHIVES)) return "Archives";
        if (in(ext, DOCS)) return "Documents";
        return "Others";
    }

    static String glyph(Entry e) {
        if (e.dir) return "📁";
        switch (e.kind) {
            case "Images": return "🖼️";
            case "Videos": return "🎬";
            case "Audio": return "🎵";
            case "Apps": return "📦";
            case "Archives": return "🗜️";
            default:
                if (e.ext.equals("pdf")) return "📕";
                if (in(e.ext, TEXT)) return "📝";
                return e.kind.equals("Documents") ? "📄" : "📎";
        }
    }

    static String mime(String name) {
        String e = ext(name);
        String m = MimeTypeMap.getSingleton().getMimeTypeFromExtension(e);
        if (m != null) return m;
        if (e.equals("apk")) return "application/vnd.android.package-archive";
        return "*/*";
    }

    static String size(long n) {
        if (n < 1024) return n + " B";
        String[] u = {"KB", "MB", "GB", "TB"};
        double d = n;
        int i = -1;
        do {
            d /= 1024;
            i++;
        } while (d >= 1024 && i < u.length - 1);
        return String.format(Locale.US, "%.1f %s", d, u[i]);
    }

    static String when(long ms) {
        Calendar now = Calendar.getInstance(), c = Calendar.getInstance();
        c.setTimeInMillis(ms);
        String hm = new SimpleDateFormat("HH:mm", Locale.getDefault()).format(new Date(ms));
        if (sameDay(now, c)) return "Today " + hm;
        Calendar y = Calendar.getInstance();
        y.add(Calendar.DAY_OF_YEAR, -1);
        if (sameDay(y, c)) return "Yesterday " + hm;
        String pat = now.get(Calendar.YEAR) == c.get(Calendar.YEAR) ? "dd MMM HH:mm" : "dd MMM yyyy";
        return new SimpleDateFormat(pat, Locale.getDefault()).format(new Date(ms));
    }

    static String day(long ms) {
        Calendar now = Calendar.getInstance(), c = Calendar.getInstance();
        c.setTimeInMillis(ms);
        if (sameDay(now, c)) return "Today";
        Calendar y = Calendar.getInstance();
        y.add(Calendar.DAY_OF_YEAR, -1);
        if (sameDay(y, c)) return "Yesterday";
        return new SimpleDateFormat("EEEE, dd MMMM", Locale.getDefault()).format(new Date(ms));
    }

    static String ago(long ms) {
        long s = Math.max(0, (System.currentTimeMillis() - ms) / 1000);
        if (s < 60) return "just now";
        long[] sizes = {86400, 3600, 60};
        String[] units = {"day", "hour", "minute"};
        for (int i = 0; i < 3; i++) {
            if (s >= sizes[i]) {
                long n = s / sizes[i];
                return n + " " + units[i] + (n > 1 ? "s" : "") + " ago";
            }
        }
        return "";
    }

    static boolean sameDay(Calendar a, Calendar b) {
        return a.get(Calendar.YEAR) == b.get(Calendar.YEAR) && a.get(Calendar.DAY_OF_YEAR) == b.get(Calendar.DAY_OF_YEAR);
    }

    static File root() {
        return Environment.getExternalStorageDirectory();
    }

    static File downloads() {
        return Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
    }

    static File received() {
        File d = new File(downloads(), "Arckad-D Received");
        //noinspection ResultOfMethodCallIgnored
        d.mkdirs();
        return d;
    }

    static String shortPath(File f) {
        String r = root().getAbsolutePath(), p = f.getAbsolutePath();
        if (p.equals(r)) return "Internal storage";
        if (p.startsWith(r + "/")) return p.substring(r.length() + 1);
        return p;
    }

    static List<Entry> list(File dir, boolean hidden, String sort) {
        List<Entry> out = new ArrayList<>();
        File[] kids = dir.listFiles();
        if (kids != null) {
            for (File k : kids) {
                if (!hidden && k.getName().startsWith(".")) continue;
                out.add(new Entry(k));
            }
        }
        sort(out, sort);
        return out;
    }

    static void sort(List<Entry> list, String by) {
        Comparator<Entry> c;
        if ("date".equals(by)) c = (a, b) -> Long.compare(b.mod, a.mod);
        else if ("size".equals(by)) c = (a, b) -> Long.compare(b.size, a.size);
        else c = (a, b) -> a.name.compareToIgnoreCase(b.name);
        Collections.sort(list, (a, b) -> a.dir != b.dir ? (a.dir ? -1 : 1) : c.compare(a, b));
    }

    static File unique(File dest) {
        if (!dest.exists()) return dest;
        String n = dest.getName(), stem = n, ext = "";
        int dot = n.lastIndexOf('.');
        if (dot > 0 && !dest.isDirectory()) {
            stem = n.substring(0, dot);
            ext = n.substring(dot);
        }
        for (int i = 1; ; i++) {
            File c = new File(dest.getParentFile(), stem + " (" + i + ")" + ext);
            if (!c.exists()) return c;
        }
    }

    static void copy(File src, File dst) throws IOException {
        if (src.isDirectory()) {
            if (!dst.mkdirs() && !dst.isDirectory()) throw new IOException("can't create " + dst.getName());
            File[] kids = src.listFiles();
            if (kids != null) for (File k : kids) copy(k, new File(dst, k.getName()));
            return;
        }
        try (InputStream in = new FileInputStream(src); OutputStream out = new FileOutputStream(dst)) {
            pipe(in, out);
        }
        //noinspection ResultOfMethodCallIgnored
        dst.setLastModified(src.lastModified());
    }

    static void move(File src, File dst) throws IOException {
        if (src.renameTo(dst)) return;
        copy(src, dst);
        delete(src);
    }

    static boolean delete(File f) {
        if (f.isDirectory()) {
            File[] kids = f.listFiles();
            if (kids != null) for (File k : kids) delete(k);
        }
        return f.delete();
    }

    static long pipe(InputStream in, OutputStream out) throws IOException {
        byte[] buf = new byte[256 * 1024];
        long total = 0;
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
            total += n;
        }
        return total;
    }

    /** Files inside the given items (folders are walked), with their names relative to the parent. */
    static void collect(File f, String rel, List<File> files, List<String> names) {
        if (f.isDirectory()) {
            File[] kids = f.listFiles();
            if (kids != null) for (File k : kids) collect(k, rel + "/" + k.getName(), files, names);
        } else if (f.isFile()) {
            files.add(f);
            names.add(rel);
        }
    }

    static void zip(List<File> items, File out) throws IOException {
        try (ZipOutputStream z = new ZipOutputStream(new BufferedOutputStream(new FileOutputStream(out)))) {
            for (File item : items) {
                List<File> files = new ArrayList<>();
                List<String> names = new ArrayList<>();
                collect(item, item.getName(), files, names);
                for (int i = 0; i < files.size(); i++) {
                    z.putNextEntry(new ZipEntry(names.get(i)));
                    try (InputStream in = new BufferedInputStream(new FileInputStream(files.get(i)))) {
                        pipe(in, z);
                    }
                    z.closeEntry();
                }
            }
        }
    }

    /** Extracts next to the zip: one top folder stays as is, loose files go into a folder named after it. */
    static File unzip(File zipFile) throws IOException {
        File parent = zipFile.getParentFile();
        File work = new File(parent, ".arckad-extract-" + System.currentTimeMillis());
        if (!work.mkdirs()) throw new IOException("can't write here");
        String base = work.getCanonicalPath() + File.separator;
        try (ZipInputStream z = new ZipInputStream(new BufferedInputStream(new FileInputStream(zipFile)))) {
            ZipEntry e;
            while ((e = z.getNextEntry()) != null) {
                File target = new File(work, e.getName());
                if (!target.getCanonicalPath().startsWith(base)) continue;       // ignore "../" tricks
                if (e.isDirectory()) {
                    //noinspection ResultOfMethodCallIgnored
                    target.mkdirs();
                    continue;
                }
                //noinspection ResultOfMethodCallIgnored
                target.getParentFile().mkdirs();
                try (OutputStream out = new BufferedOutputStream(new FileOutputStream(target))) {
                    pipe(z, out);
                }
            }
        } catch (IOException ex) {
            delete(work);
            throw ex;
        }
        String[] kids = work.list();
        if (kids == null || kids.length == 0) {
            delete(work);
            throw new IOException("the archive is empty");
        }
        File result;
        if (kids.length == 1) {
            result = unique(new File(parent, kids[0]));
            if (!new File(work, kids[0]).renameTo(result)) throw new IOException("can't move files");
            delete(work);
        } else {
            String n = zipFile.getName();
            result = unique(new File(parent, n.toLowerCase(Locale.ROOT).endsWith(".zip") ? n.substring(0, n.length() - 4) : n));
            if (!work.renameTo(result)) throw new IOException("can't move files");
        }
        return result;
    }
}

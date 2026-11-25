package io.github.tamiltimon.arckadd;

import android.content.Context;
import android.os.Environment;

import java.io.File;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** 📸 New camera photos go to the PC by themselves, while the phone and the PC are on the same Wi-Fi. The PC files
 *  them by year and month. Only photos taken after you switched this on (or the last 7 days if you ask). */
final class PhotoImport {
    private static final String ON = "photo_import", SINCE = "photo_import_since", VIDEOS = "photo_import_videos";
    private static volatile boolean busy;

    private PhotoImport() {
    }

    static boolean on(Context c) {
        return Ui.prefs(c).getBoolean(ON, false);
    }

    static void set(Context c, boolean v, long sinceMs) {
        Ui.prefs(c).edit().putBoolean(ON, v).putLong(SINCE, sinceMs).apply();
    }

    static boolean videos(Context c) {
        return Ui.prefs(c).getBoolean(VIDEOS, false);
    }

    static void setVideos(Context c, boolean v) {
        Ui.prefs(c).edit().putBoolean(VIDEOS, v).apply();
    }

    private static boolean wanted(String name, boolean vids) {
        String n = name.toLowerCase();
        if (n.startsWith(".") || n.endsWith(".pending") || n.contains(".trashed")) return false;
        return n.endsWith(".jpg") || n.endsWith(".jpeg") || n.endsWith(".heic") || n.endsWith(".heif") || n.endsWith(".png")
                || n.endsWith(".dng") || (vids && (n.endsWith(".mp4") || n.endsWith(".mov") || n.endsWith(".3gp")));
    }

    /** Called every half minute by the link: sends what's new (a few at a time). */
    static void check(Context c, ChatLink link) {
        if (busy || !on(c) || ToPc.pc(link) == null) return;
        busy = true;
        try {
            long since = Ui.prefs(c).getLong(SINCE, System.currentTimeMillis());
            boolean vids = videos(c);
            List<File> fresh = new ArrayList<>();
            File dcim = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DCIM);
            File[] roots = {new File(dcim, "Camera"), dcim};
            for (File root : roots) {
                File[] list = root.listFiles();
                if (list == null) continue;
                for (File f : list)
                    if (f.isFile() && f.lastModified() > since && wanted(f.getName(), vids) && !fresh.contains(f)) fresh.add(f);
            }
            Collections.sort(fresh, (x, y) -> Long.compare(x.lastModified(), y.lastModified()));
            int n = 0;
            for (File f : fresh) {
                if (n++ >= 25) break;                               // the rest next time
                if (System.currentTimeMillis() - f.lastModified() < 5000) break;   // still being written
                ToPc.send(link, f, "photo", f.getName(), f.lastModified());
                Ui.prefs(c).edit().putLong(SINCE, f.lastModified()).apply();
            }
        } catch (Exception ignored) {                               // tried again in half a minute
        } finally {
            busy = false;
        }
    }
}

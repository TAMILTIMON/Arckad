package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.Context;
import android.content.Intent;
import android.media.MediaScannerConnection;
import android.net.Uri;

import java.io.File;
import java.util.ArrayList;
import java.util.List;

/** Talking to the rest of Android: open with another app, share, install, rescan media. */
final class Android {
    private Android() {
    }

    static void openWith(Activity a, File f) {
        Uri u = Provider.uriFor(f);
        Intent i = new Intent(Intent.ACTION_VIEW).setDataAndType(u, Fs.mime(f.getName()))
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            a.startActivity(Intent.createChooser(i, "Open with"));
        } catch (ActivityNotFoundException e) {
            Ui.toast(a, "No app on this phone can open this kind of file.");
        }
    }

    static void share(Activity a, List<File> files) {
        if (files.isEmpty()) return;
        Intent i;
        if (files.size() == 1) {
            File f = files.get(0);
            Uri u = Provider.uriFor(f);
            i = new Intent(Intent.ACTION_SEND).setType(Fs.mime(f.getName())).putExtra(Intent.EXTRA_STREAM, u);
            i.setClipData(ClipData.newRawUri(f.getName(), u));
        } else {
            ArrayList<Uri> uris = new ArrayList<>();
            ClipData clip = null;
            for (File f : files) {
                if (!f.isFile()) continue;
                Uri u = Provider.uriFor(f);
                uris.add(u);
                if (clip == null) clip = ClipData.newRawUri(f.getName(), u);
                else clip.addItem(new ClipData.Item(u));
            }
            if (uris.isEmpty()) {
                Ui.toast(a, "Folders can't be shared this way. Compress them to ZIP first.");
                return;
            }
            i = new Intent(Intent.ACTION_SEND_MULTIPLE).setType("*/*").putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris);
            i.setClipData(clip);
        }
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
        try {
            a.startActivity(Intent.createChooser(i, "Share"));
        } catch (ActivityNotFoundException e) {
            Ui.toast(a, "No app can share this.");
        }
    }

    static void install(Activity a, File apk) {
        Intent i = new Intent(Intent.ACTION_VIEW).setDataAndType(Provider.uriFor(apk), "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        a.startActivity(i);
    }

    static void openUrl(Context c, String url) {
        try {
            c.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (ActivityNotFoundException e) {
            Ui.toast(c, "No browser found");
        }
    }

    static void mediaScan(Context c, File... files) {
        String[] p = new String[files.length];
        for (int i = 0; i < files.length; i++) p[i] = files[i].getAbsolutePath();
        MediaScannerConnection.scanFile(c.getApplicationContext(), p, null, null);
    }
}

package io.github.tamiltimon.arckadd;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.provider.Settings;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Checks this app's GitHub Releases and installs a newer APK (Android asks once to confirm). */
final class Updater {
    static final String REPO = "TAMILTIMON/Arckad";

    private Updater() {
    }

    static int[] ver(String v) {
        String[] p = v.replaceAll("[^0-9.]", "").split("\\.");
        int[] out = new int[3];
        for (int i = 0; i < 3 && i < p.length; i++) {
            try {
                out[i] = Integer.parseInt(p[i]);
            } catch (NumberFormatException ignored) {
            }
        }
        return out;
    }

    static boolean newer(String a, String b) {
        int[] x = ver(a), y = ver(b);
        for (int i = 0; i < 3; i++) if (x[i] != y[i]) return x[i] > y[i];
        return false;
    }

    static void check(final Activity a, final boolean manual) {
        if (manual) Ui.toast(a, "Checking for updates…");
        new Thread(() -> {
            String latest = null, page = null, apk = null, err = null;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL("https://api.github.com/repos/" + REPO + "/releases/latest").openConnection();
                c.setRequestProperty("Accept", "application/vnd.github+json");
                c.setRequestProperty("User-Agent", "Arckad-D-Android/" + BuildInfo.VERSION);
                c.setConnectTimeout(15000);
                c.setReadTimeout(15000);
                if (c.getResponseCode() == 200) {
                    ByteArrayOutputStream b = new ByteArrayOutputStream();
                    try (InputStream in = c.getInputStream()) {
                        Fs.pipe(in, b);
                    }
                    JSONObject rel = new JSONObject(b.toString("UTF-8"));
                    latest = rel.optString("tag_name");
                    page = rel.optString("html_url");
                    JSONArray assets = rel.optJSONArray("assets");
                    if (assets != null) for (int i = 0; i < assets.length(); i++) {
                        JSONObject as = assets.getJSONObject(i);
                        if (as.optString("name").endsWith(".apk")) apk = as.optString("browser_download_url");
                    }
                } else {
                    // GitHub's lookup limit: read the normal release page instead
                    HttpURLConnection w = (HttpURLConnection) new URL("https://github.com/" + REPO + "/releases/latest").openConnection();
                    w.setInstanceFollowRedirects(true);
                    w.getResponseCode();
                    page = w.getURL().toString();
                    latest = page.substring(page.lastIndexOf('/') + 1);
                    String v = latest.replaceFirst("^[vV]", "");
                    apk = "https://github.com/" + REPO + "/releases/download/" + latest + "/Arckad-D-" + v + ".apk";
                }
            } catch (Exception e) {
                err = e.getMessage();
            }
            final String fLatest = latest, fPage = page, fApk = apk, fErr = err;
            a.runOnUiThread(() -> {
                Ui.prefs(a).edit().putLong("update_checked", System.currentTimeMillis()).apply();
                if (fLatest == null || fLatest.isEmpty()) {
                    if (manual) Ui.toast(a, "Couldn't check for updates" + (fErr != null ? ": " + fErr : ""));
                    return;
                }
                String v = fLatest.replaceFirst("^[vV]", "");
                if (!newer(v, BuildInfo.VERSION)) {
                    if (manual) Ui.toast(a, "You're up to date (" + BuildInfo.VERSION + ")");
                    return;
                }
                Ui.dialog(a).setTitle("Arckad-D " + v + " is available")
                        .setMessage("You have " + BuildInfo.VERSION + ". Update now? Your settings stay.")
                        .setPositiveButton("Update", (d, w) -> {
                            if (fApk != null) download(a, fApk, v);
                            else Android.openUrl(a, fPage);
                        })
                        .setNeutralButton("What's new", (d, w) -> Android.openUrl(a, fPage))
                        .setNegativeButton("Later", null).show();
            });
        }).start();
    }

    private static void download(final Activity a, final String url, final String version) {
        if (Build.VERSION.SDK_INT >= 26 && !a.getPackageManager().canRequestPackageInstalls()) {
            Ui.dialog(a).setTitle("Allow updates")
                    .setMessage("Android needs your OK once: turn on “Allow from this source” for Arckad-D, then come back and tap Update again.")
                    .setPositiveButton("Open settings", (d, w) -> a.startActivity(new Intent(
                            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + a.getPackageName()))))
                    .setNegativeButton("Cancel", null).show();
            return;
        }
        LinearLayout box = new LinearLayout(a);
        box.setOrientation(LinearLayout.VERTICAL);
        int p = Ui.dp(a, 20);
        box.setPadding(p, p, p, 0);
        final ProgressBar bar = new ProgressBar(a, null, android.R.attr.progressBarStyleHorizontal);
        bar.setMax(1000);
        final TextView label = Ui.text(a, "Downloading…", 14, Ui.TEXT, false);
        box.addView(label);
        box.addView(bar);
        final boolean[] cancelled = {false};
        final AlertDialog d = Ui.dialog(a).setTitle("Updating to " + version).setView(box)
                .setNegativeButton("Cancel", (di, w) -> cancelled[0] = true).setCancelable(false).show();
        new Thread(() -> {
            File out = new File(a.getExternalCacheDir() != null ? a.getExternalCacheDir() : a.getCacheDir(), "Arckad-D-update.apk");
            String err = null;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                c.setInstanceFollowRedirects(true);
                c.setRequestProperty("User-Agent", "Arckad-D-Android/" + BuildInfo.VERSION);
                long total = c.getContentLengthLong(), done = 0, last = 0;
                byte[] buf = new byte[128 * 1024];
                try (InputStream in = c.getInputStream(); OutputStream o = new FileOutputStream(out)) {
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        if (cancelled[0]) throw new Exception("cancelled");
                        o.write(buf, 0, n);
                        done += n;
                        long now = System.currentTimeMillis();
                        if (now - last > 200) {
                            last = now;
                            final long dd = done;
                            a.runOnUiThread(() -> {
                                if (total > 0) bar.setProgress((int) (dd * 1000 / total));
                                label.setText(Fs.size(dd) + (total > 0 ? " of " + Fs.size(total) : ""));
                            });
                        }
                    }
                }
                if (total > 0 && done != total) err = "the download was incomplete";
            } catch (Exception e) {
                err = e.getMessage();
            }
            final String fErr = err;
            a.runOnUiThread(() -> {
                d.dismiss();
                if (cancelled[0]) return;
                if (fErr != null) Ui.toast(a, "Update failed: " + fErr);
                else Android.install(a, out);
            });
        }).start();
    }
}

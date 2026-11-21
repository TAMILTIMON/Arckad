package io.github.tamiltimon.arckadd;

import android.app.Activity;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
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

    /** Downloads in the browser; the person taps the finished file and chooses Update.
     *  (Arckad-D doesn't install apps itself: that needs a sensitive permission Play Protect distrusts.) */
    private static void download(final Activity a, final String url, final String version) {
        Android.openUrl(a, url);
        Ui.info(a, "Downloading Arckad-D " + version, "Your browser is downloading the update. When it finishes, "
                + "tap the downloaded file and choose Update. Your settings stay.");
    }
}

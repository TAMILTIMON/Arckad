# Arckad-D for Android (native)

Plain Android (Java, no extra libraries), built by `build-apk.sh` with the SDK tools GitHub already has.

* `src/.../MainActivity.java` – tabs: Files · Recent · Send · Receive
* `FilesScreen`, `RecentScreen`, `ShareScreens` – the four tabs
* `PhotoActivity` + `PhotoPager` – photo viewer (swipe, pinch / double-tap zoom)
* `PdfActivity` – PDF reader (Android's PdfRenderer) · `TextActivity` – text / code viewer
* `Net` – Nearby send/receive + link sharing (same protocol as the desktop app) · `Qr` – QR codes
* `Provider` – hands files to other apps safely (content:// links) · `Updater` – updates from GitHub Releases

The version comes from `APP_VERSION` in `../arckad-d.py`. `signing/debug.keystore` keeps the signature
the same, so each new APK installs as an update.

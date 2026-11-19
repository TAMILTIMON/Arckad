# Arckad-D for Android

Built automatically by GitHub (see `.github/workflows/build.yml`) into `Arckad-D-<version>.apk`.

* `main.py` – the phone screens (Kivy)
* `arckad_core.py` – files, thumbnails, and Nearby / link sharing (same protocol as the desktop app)
* `fonts/materialdesignicons-webfont.ttf` – icons (Material Design Icons, Apache 2.0 / OFL, from pictogrammers.com)
* `signing/debug.keystore` – fixed signing key, so a new APK installs as an update over the old one

The version number comes from `APP_VERSION` in `../arckad-d.py`.

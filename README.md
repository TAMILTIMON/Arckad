# Arckad-D

A file manager that remembers what you worked on. Runs on **Linux**, **Windows 10/11** and **Android**,
and they can send files to each other over Wi-Fi.

## How releases work (automatic)

1. Change the version near the top of `arckad-d.py`, for example `APP_VERSION = "3.8.0"`.
2. `git add -A && git commit -m "Arckad-D 3.8.0" && git push`
3. About 15–40 minutes later the **Releases** page has **Arckad-D 3.8.0** with:

| File | For |
|---|---|
| `Arckad-D-Setup-<version>.exe` | Windows installer |
| `Arckad-D-<version>-portable-windows.zip` | Windows, no install needed |
| `arckad-d_<version>_all.deb` | Ubuntu / Debian-based Linux |
| `Arckad-D-<version>.apk` | Android phones (64-bit) |

You don't need to draft releases yourself. Pushing again with the **same** version replaces the files in
that release; a **new** version makes a new release. Progress is on the **Actions** tab.

## Project layout

```
arckad-d.py                    desktop app (Linux + Windows)  ← APP_VERSION is here
windows/                       Windows build recipe, installer script, icon
linux/build-deb.sh             makes the .deb
android/                       Android app (main.py, arckad_core.py, buildozer.spec)
.github/workflows/build.yml    tells GitHub how to build and release everything
```

## Installing

* **Linux:** `cp arckad-d_*.deb /tmp/ && sudo apt install /tmp/arckad-d_*_all.deb`
* **Windows:** run the Setup .exe. If SmartScreen appears: *More info → Run anyway*.
* **Android:** open the .apk on the phone and allow "Install unknown apps" for your browser or Files app
  when asked. On first start, Arckad-D asks for *Allow access to manage all files*.

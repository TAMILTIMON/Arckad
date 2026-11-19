# Arckad-D

A file manager that remembers what you worked on. Runs on **Linux** (Ubuntu, Mint, Debian…) and **Windows 10/11**.

## Get the installers (built automatically by GitHub)

Every time you upload a change, GitHub builds:

| File | For |
|---|---|
| `Arckad-D-Setup-<version>.exe` | Windows installer |
| `Arckad-D-<version>-portable-windows.zip` | Windows, no install needed |
| `arckad-d_<version>_all.deb` | Ubuntu / Debian-based Linux |

**Download them:** open the repository → **Actions** tab → click the latest
**Build installers** run with a green ✓ → scroll to **Artifacts** →
download **Arckad-D-Windows** and/or **Arckad-D-Linux** (each is a .zip; unzip it).

**Build again by hand:** Actions → **Build installers** → **Run workflow**.

**Make a public download page (Release):** create a tag that starts with `v`
(Releases → *Draft a new release* → *Choose a tag* → type `v3.2.0` → *Publish*).
The installers are attached to that release automatically after a few minutes.

## Releasing a new version

1. Change `APP_VERSION = "…"` near the top of `arckad-d.py`.
2. Upload the new `arckad-d.py` (Add file → Upload files).
3. Wait about 10 minutes, then download from the Actions tab as above.

## Project layout

```
arckad-d.py                    the app (same file for Linux and Windows)
windows/arckad-d.spec          PyInstaller recipe (makes Arckad-D.exe)
windows/installer.iss          Inno Setup recipe (makes the Setup .exe)
windows/arckad-d.ico, .png     app icon
linux/build-deb.sh             makes the .deb
.github/workflows/build.yml    tells GitHub how to build everything
```

## Notes for Windows

* The first time you start the installer, Windows SmartScreen may say
  "Windows protected your PC" because the app isn't signed with a paid certificate.
  Click **More info → Run anyway**.
* The first time you use **Quick Share**, Windows asks about the firewall:
  allow Arckad-D on **Private networks**.
* PDF page previews are Linux-only for now; on Windows the preview shows the file icon and details.

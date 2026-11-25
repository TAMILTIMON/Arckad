#!/usr/bin/env bash
# Builds build/arckad-d_<version>_all.deb from arckad-d.py  (run from the project folder)
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' arckad-d.py)
PKG=build/arckad-d_${VERSION}_all
rm -rf build && mkdir -p "$PKG"/{DEBIAN,opt/arckad-d,usr/bin,usr/share/applications,usr/share/doc/arckad-d,usr/share/icons/hicolor/scalable/apps}

install -m 755 arckad-d.py "$PKG/opt/arckad-d/arckad-d.py"
mkdir -p "$PKG/opt/arckad-d/emoji"
install -m 644 emoji/noto-emoji.zip emoji/categories.json emoji/LICENSE.txt "$PKG/opt/arckad-d/emoji/"
python3 - "$PKG" <<'EOF'
import re, sys
src = open("arckad-d.py", encoding="utf-8").read()
svg = re.search(r'LOGO_SVG = """(.*?)"""', src, re.S).group(1)
open(sys.argv[1] + "/usr/share/icons/hicolor/scalable/apps/arckad-d.svg", "w").write(svg)
EOF
if [ -d branding/fonts ]; then
  # the monochrome icon font (Noto Emoji, SIL Open Font License) for the “Professional” icons
  install -d "$PKG/opt/arckad-d/fonts"
  install -m 644 branding/fonts/* "$PKG/opt/arckad-d/fonts/"
fi
if [ -f branding/logo.png ]; then
  # your own logo (branding/logo.png): the app shows it, and the menu icons are made from it
  python3 branding/make-icons.py
  install -m 644 branding/logo.png "$PKG/opt/arckad-d/logo.png"
  rm -f "$PKG/usr/share/icons/hicolor/scalable/apps/arckad-d.svg"
  for s in 16 24 32 48 64 128 256 512; do
    mkdir -p "$PKG/usr/share/icons/hicolor/${s}x${s}/apps"
    install -m 644 "branding/linux/$s.png" "$PKG/usr/share/icons/hicolor/${s}x${s}/apps/arckad-d.png"
  done
elif command -v rsvg-convert >/dev/null; then
  for s in 16 24 32 48 64 128 256 512; do
    mkdir -p "$PKG/usr/share/icons/hicolor/${s}x${s}/apps"
    rsvg-convert -w $s -h $s "$PKG/usr/share/icons/hicolor/scalable/apps/arckad-d.svg" \
      -o "$PKG/usr/share/icons/hicolor/${s}x${s}/apps/arckad-d.png"
  done
fi

cat > "$PKG/usr/bin/arckad-d" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /opt/arckad-d/arckad-d.py "$@"
EOF
chmod 755 "$PKG/usr/bin/arckad-d"

cat > "$PKG/usr/share/applications/arckad-d.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Arckad-D
GenericName=File Manager
Comment=File manager that remembers what you last worked on
Exec=arckad-d %U
Icon=arckad-d
Terminal=false
Categories=Utility;FileManager;GTK;
Keywords=files;folders;organize;recent;duplicates;search;share;arkad;
MimeType=inode/directory;
StartupWMClass=arckad-d
StartupNotify=true
EOF
echo "Arckad-D - a file manager that remembers what you worked on." > "$PKG/usr/share/doc/arckad-d/copyright"

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    for f in /home/*/.local/share/applications/arckad-d.desktop /root/.local/share/applications/arckad-d.desktop; do
        [ -f "$f" ] && grep -q 'arckad-d.py' "$f" && rm -f "$f" || true
    done
    for f in /home/*/.config/autostart/arckad-d-autosort.desktop; do
        [ -f "$f" ] && sed -i 's|^Exec=.*|Exec=arckad-d --autosort|' "$f" || true
    done
fi
exit 0
EOF
cat > "$PKG/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
pkill -f "arckad-d.py --autosort" 2>/dev/null || true
exit 0
EOF
cat > "$PKG/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    for f in /home/*/.config/autostart/arckad-d-autosort.desktop; do rm -f "$f" || true; done
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database -q /usr/share/applications || true
    command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF
chmod 755 "$PKG/DEBIAN/postinst" "$PKG/DEBIAN/prerm" "$PKG/DEBIAN/postrm"

cat > "$PKG/DEBIAN/control" <<EOF
Package: arckad-d
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0, librsvg2-common
Recommends: qrencode, python3-pypdf, poppler-utils, ffmpegthumbnailer, 7zip | p7zip-full, gir1.2-gstreamer-1.0, gstreamer1.0-plugins-good, gstreamer1.0-libav, pulseaudio-utils | pipewire-bin, gir1.2-ayatanaappindicator3-0.1, gnome-shell-extension-appindicator
Installed-Size: $(du -sk "$PKG" --exclude=DEBIAN | cut -f1)
Maintainer: Arckad-D <arckad-d@users.noreply.local>
Description: File manager that remembers what you worked on
 Arckad-D is a simple GTK file manager for Ubuntu and other Debian-based
 Linux systems. It reminds you which file you worked on last, groups your
 recent work into sessions, searches all your files instantly, previews
 images, PDFs and text, tags and notes files, compares files, finds
 duplicates, tidies cluttered folders, auto-sorts your Downloads and can
 Quick Share files with phones and laptops on the same Wi-Fi.
EOF

dpkg-deb --root-owner-group --build "$PKG" >/dev/null
rm -rf "$PKG"
echo "Built: $(ls build/*.deb)"

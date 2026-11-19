# PyInstaller recipe for the Windows build of Arckad-D.
# GitHub runs this automatically; to run it yourself (inside MSYS2 UCRT64):
#     pyinstaller --noconfirm windows/arckad-d.spec
import os

here = SPECPATH
root = os.path.dirname(here)

a = Analysis(
    [os.path.join(root, "arckad-d.py")],
    pathex=[root],
    datas=[(os.path.join(here, "arckad-d.png"), "."),
           (os.path.join(here, "arckad-d.ico"), ".")],
    hiddenimports=["gi.repository.Gtk", "gi.repository.Gdk", "gi.repository.GdkPixbuf",
                   "gi.repository.Gio", "gi.repository.GLib", "gi.repository.GObject",
                   "gi.repository.Pango", "qrcode", "winreg"],
    hooksconfig={
        "gi": {
            "icons": ["Adwaita", "hicolor"],
            "themes": ["Adwaita"],
            "languages": ["en_GB"],
            "module-versions": {"Gtk": "3.0", "Gdk": "3.0", "GdkPixbuf": "2.0"},
        },
    },
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Arckad-D",
          icon=os.path.join(here, "arckad-d.ico"), console=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="Arckad-D")

# PyInstaller recipe for the Windows build of Arckad-D.
# GitHub runs this automatically; to run it yourself (inside MSYS2 UCRT64):
#     pyinstaller --noconfirm windows/arckad-d.spec
import glob
import os
import sys

from PyInstaller.depend import bindepend

here = SPECPATH
root = os.path.dirname(here)
bindir = os.path.join(sys.prefix, "bin")          # MSYS2 UCRT64's DLL folder


def dll_closure(patterns):
    """Every DLL the GTK stack needs, found by following each DLL's own import list.
    (PyGObject loads some of them only at run time, so PyInstaller can't always see them.)"""
    todo, seen = [], {}
    for pat in patterns:
        todo += [os.path.basename(p) for p in glob.glob(os.path.join(bindir, pat))]
    while todo:
        name = todo.pop()
        path = os.path.join(bindir, name)
        if name.lower() in seen or not os.path.isfile(path):
            continue                                   # Windows' own DLLs aren't in bindir: skip them
        seen[name.lower()] = path
        try:
            imports = bindepend.get_imports(path)
        except Exception:
            imports = []
        for imp in imports:
            todo.append(os.path.basename(imp[0] if isinstance(imp, (tuple, list)) else imp))
    return sorted(seen.values())


roots = ["libgtk-3-0.dll", "libgdk-3-0.dll", "libgdk_pixbuf-2.0-0.dll", "librsvg-2-2.dll",
         "libgirepository-*.dll", "libgobject-2.0-0.dll", "libgio-2.0-0.dll", "libglib-2.0-0.dll",
         "libpango-1.0-0.dll", "libpangocairo-1.0-0.dll", "libpangowin32-1.0-0.dll", "libcairo-2.dll",
         "libcairo-gobject-2.dll", "libharfbuzz-0.dll", "libepoxy-0.dll", "libffi-*.dll"]
gtk_dlls = dll_closure(roots)
print(f"Arckad-D: bundling {len(gtk_dlls)} GTK DLLs from {bindir}")

a = Analysis(
    [os.path.join(root, "arckad-d.py")],
    pathex=[root],
    binaries=[(p, ".") for p in gtk_dlls],
    datas=([(os.path.join(here, "..", "branding", "logo.png"), ".")]
           if os.path.exists(os.path.join(here, "..", "branding", "logo.png")) else []) + [
           (os.path.join(here, "arckad-d.png"), "."),
           (os.path.join(here, "arckad-d.ico"), "."),
           (os.path.join(root, "emoji"), "emoji")],
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

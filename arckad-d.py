#!/usr/bin/env python3
"""
Arckad-D - a file manager for Ubuntu that remembers what you worked on.

Run it:                python3 arckad-d.py
Add to app menu:       python3 arckad-d.py --install
Background auto-sort:  python3 arckad-d.py --autosort   (started for you when enabled)

Uses only what Ubuntu desktop already ships with (Python 3 + GTK 3).
Optional, for richer previews:  sudo apt install poppler-utils ffmpegthumbnailer
"""
import bz2
import difflib
import gzip
import hashlib
import html as htmlmod
import json
import lzma
import mimetypes
import os
import secrets
import shutil
import signal
import socket
import sqlite3
import stat as statmod
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, OrderedDict
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk, Pango
except Exception:                       # also broken installs, not just missing GTK
    import traceback
    _err = traceback.format_exc()
    if "--selftest" in sys.argv:         # the automatic build test reads this file
        _i = sys.argv.index("--selftest")
        with open(sys.argv[_i + 1] if len(sys.argv) > _i + 1 else "selftest.txt", "w", encoding="utf-8") as _f:
            _f.write("SELFTEST FAILED while loading GTK\n" + _err)
        sys.exit(1)
    if sys.platform == "win32":
        _log = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "arckad-d-error.log")
        try:
            with open(_log, "w", encoding="utf-8") as _f:
                _f.write(_err)
        except OSError:
            pass
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, "Arckad-D couldn't start because part of it is missing or damaged.\n\n"
                                         "Please reinstall it from the Releases page.\n\nDetails were saved to:\n" + _log,
                                         "Arckad-D", 0x10)
        sys.exit(1)
    sys.exit("GTK for Python is missing or broken. Install it with:\n"
             "  sudo apt install python3-gi gir1.2-gtk-3.0\n\n" + _err)

APP_NAME = "Arckad-D"
APP_SLUG = "arckad-d"
APP_VERSION = "3.14.1"
APP_ID = "io.github.arckadd"
UPDATE_REPO = "TAMILTIMON/Arckad"                  # GitHub repository whose Releases hold the installers
IS_WIN = sys.platform == "win32"
FROZEN = bool(getattr(sys, "frozen", False))                  # built into an .exe
SCRIPT = Path(__file__).resolve()
BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", SCRIPT.parent))
INSTALLED = str(SCRIPT).startswith("/opt/arckad-d/")          # installed from the .deb package
LAUNCH_CMD = "arckad-d" if INSTALLED else f'python3 "{SCRIPT}"'
HOME = Path.home()
CONFIG_DIR = Path(GLib.get_user_config_dir()) / APP_SLUG
CACHE_DIR = Path(GLib.get_user_cache_dir()) / APP_SLUG
OLD_CONFIG_DIR = Path(GLib.get_user_config_dir()) / "fileminder"
OLD_CACHE_DIR = Path(GLib.get_user_cache_dir()) / "fileminder"
ICON_FILE = Path(GLib.get_user_data_dir()) / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_SLUG}.svg"
CONFIG_FILE = CONFIG_DIR / "config.json"
UNDO_FILE = CONFIG_DIR / "undo.json"
TAGS_FILE = CONFIG_DIR / "tags.json"
IGNORE_FILE = CONFIG_DIR / "autosort_ignore.json"
INDEX_DB = CACHE_DIR / "index.db"
INDEX_META = CACHE_DIR / "index_meta.json"
PID_FILE = CACHE_DIR / "autosort.pid"
AUTOSTART_FILE = Path(GLib.get_user_config_dir()) / "autostart" / f"{APP_SLUG}-autosort.desktop"
OLD_AUTOSTART = Path(GLib.get_user_config_dir()) / "autostart" / "fileminder-autosort.desktop"
OLD_DESKTOP = Path(GLib.get_user_data_dir()) / "applications" / "fileminder.desktop"
CLUTTER_LIMIT = 40
INDEX_MAX_AGE = 30 * 60

SKIP_DIRS = {
    ".cache", ".local", ".config", ".git", "node_modules", "snap", "__pycache__",
    ".venv", "venv", ".npm", ".cargo", ".rustup", ".mozilla", ".thunderbird", ".Trash",
    # Windows system folders inside the user folder
    "AppData", "Application Data", "Local Settings", "$Recycle.Bin", "System Volume Information",
    "NetHood", "PrintHood", "Recent", "SendTo", "Start Menu", "Templates", "Cookies",
}
CATEGORIES = {
    "Images": {"jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "heic", "tiff", "ico"},
    "Documents": {"pdf", "doc", "docx", "odt", "txt", "rtf", "md", "tex", "epub"},
    "Spreadsheets": {"xls", "xlsx", "ods", "csv", "tsv"},
    "Presentations": {"ppt", "pptx", "odp", "key"},
    "Videos": {"mp4", "mkv", "avi", "mov", "webm", "flv", "wmv"},
    "Audio": {"mp3", "wav", "flac", "ogg", "m4a", "aac"},
    "Archives": {"zip", "tar", "gz", "bz2", "xz", "7z", "rar", "tgz"},
    "Code": {"py", "js", "ts", "jsx", "tsx", "java", "c", "cpp", "h", "go", "rs", "sh",
             "html", "css", "json", "yaml", "yml", "xml", "sql", "php", "rb", "ipynb"},
    "Installers": {"deb", "rpm", "appimage", "run", "snap", "iso", "exe", "msi"},
}
ALL_KNOWN_EXTS = set().union(*CATEGORIES.values())
TEXT_EXTS = {"txt", "md", "csv", "tsv", "log", "ini", "cfg", "conf", "toml", "env",
             "rst", "tex", "srt"} | CATEGORIES["Code"]
PARTIAL_EXTS = {"crdownload", "part", "partial", "tmp", "download", "opdownload", "!ut"}
TAGS = OrderedDict([("Important", "#e01b24"), ("To do", "#ff7800"), ("Work", "#3584e4"),
                    ("Personal", "#2ec27e"), ("Later", "#9141ac"), ("Done", "#77767b")])
KINDS = ["All types", "Folder"] + list(CATEGORIES) + ["Others"]
DATE_CHOICES = [("Any time", None), ("Today", "today"), ("Last 7 days", 7),
                ("Last 30 days", 30), ("Last year", 365), ("Custom range…", "custom")]
SCOPES = ["This folder", "+ Subfolders", "Everywhere"]
THUMB_KINDS = {"Images", "Videos", "Documents", "Presentations", "Spreadsheets"}

# list columns
(C_ICON, C_NAME, C_PATH, C_ISDIR, C_SIZE, C_SIZETXT, C_MTIME, C_MTIMETXT,
 C_KIND, C_WHERE, C_TAGS, C_THUMB) = range(12)
COLUMN_TYPES = (Gio.Icon, str, str, bool, GObject.TYPE_INT64, str, float, str,
                str, str, str, GdkPixbuf.Pixbuf)


# ---------------------------------------------------------------- small helpers
def ext_of(name):
    return os.path.splitext(str(name))[1].lower().lstrip(".")


def category_of(name):
    ext = ext_of(name)
    for cat, exts in CATEGORIES.items():
        if ext in exts:
            return cat
    return "Others"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def ago(ts):
    s = int(time.time() - ts)
    if s < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= size:
            n = s // size
            return f"{n} {unit}{'s' if n > 1 else ''} ago"


def duration(seconds):
    s = int(seconds)
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= size:
            n = s // size
            return f"{n} {unit}{'s' if n > 1 else ''}"
    return f"{s} seconds"


def fmt_time(ts):
    d, now = datetime.fromtimestamp(ts), datetime.now()
    if d.date() == now.date():
        return "Today " + d.strftime("%H:%M")
    if (now.date() - d.date()).days == 1:
        return "Yesterday " + d.strftime("%H:%M")
    if d.year == now.year:
        return d.strftime("%d %b %H:%M")
    return d.strftime("%d %b %Y")


def fmt_full(ts):
    return datetime.fromtimestamp(ts).strftime("%d %b %Y, %H:%M")


def fmt_clock(ts):
    return datetime.fromtimestamp(ts).strftime("%I:%M %p").lstrip("0")


def day_label(d):
    today = date.today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %d %B" + (" %Y" if d.year != today.year else ""))


def short(path):
    p = str(path)
    h = str(HOME)
    if p == h:
        return "~"
    return "~" + p[len(h):] if p.startswith(h + os.sep) else p


def esc(text):
    return GLib.markup_escape_text(str(text))


_icon_cache = {}
FOLDER_ICON = Gio.ThemedIcon.new("folder")
ICON_STYLE = {"colour": False}          # True: Arckad-D's own file-type icons (default on Windows)

# Arckad-D's own file icons: a page with a coloured band naming the type. They don't depend on the
# system's icon theme, and read well on light and dark backgrounds.
_TYPE_COLOURS = [
    ({"pdf"}, "#D9252A"), ({"doc", "docx", "odt", "rtf"}, "#1C71D8"), ({"txt", "md", "log", "rst"}, "#5E5C64"),
    ({"epub"}, "#8F5902"), ({"exe", "msi", "deb", "rpm", "apk", "appimage", "run", "iso"}, "#3D3846"),
]
_KIND_COLOURS = {"Images": "#0E8A84", "Videos": "#C01C28", "Audio": "#7B3FA0", "Spreadsheets": "#1F8F4E",
                 "Presentations": "#D35400", "Archives": "#8A5A2B", "Code": "#2B2D42", "Installers": "#3D3846",
                 "Documents": "#1C71D8", "Others": "#6E6C76"}
_PAGE_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 61 61">
<path d="M15 4h24l15 15v39a4 4 0 0 1-4 4H15a4 4 0 0 1-4-4V8a4 4 0 0 1 4-4z" fill="#FBFAF9" stroke="#8E8C95" stroke-width="1.6"/>
<path d="M39 4v11a4 4 0 0 0 4 4h11" fill="#DEDDDA" stroke="#8E8C95" stroke-width="1.6" stroke-linejoin="round"/>
<rect x="11" y="34" width="43" height="18" fill="{colour}"/>
<text x="32.5" y="47.6" text-anchor="middle" fill="#FFFFFF" font-family="Segoe UI, Ubuntu, Cantarell, Arial, sans-serif"
 font-weight="700" font-size="{size}">{label}</text>
</svg>"""
_FOLDER_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<path d="M6 15a5 5 0 0 1 5-5h13.5l6 6H53a5 5 0 0 1 5 5v3H6z" fill="#D9930D"/>
<rect x="6" y="20" width="52" height="36" rx="5" fill="#F5B83D"/>
<path d="M6 25a5 5 0 0 1 5-5h42a5 5 0 0 1 5 5v1H6z" fill="#FFD47A"/>
</svg>"""


def _svg_icon(svg):
    return Gio.BytesIcon.new(GLib.Bytes.new(svg.encode("utf-8")))


_SIZES = {}


def icon_size(kind):
    """GTK icon sizes for the coloured icons: 32 px list rows, 64 px grid tiles."""
    if kind not in _SIZES:
        px = {"row": 32, "tile": 64}[kind]
        try:
            _SIZES[kind] = Gtk.icon_size_register(f"arckad-{kind}", px, px)
        except Exception:
            _SIZES[kind] = Gtk.IconSize.DND if kind == "row" else Gtk.IconSize.DIALOG
    return _SIZES[kind]


def colour_icons_supported():
    """The coloured icons are SVG; check this system can draw SVG (it can on Ubuntu and in the Windows build)."""
    try:
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.write(_FOLDER_SVG.encode())
        loader.close()
        return loader.get_pixbuf() is not None
    except Exception:
        return False


def colour_icon(name, is_dir):
    if is_dir:
        key = ("folder",)
        if key not in _icon_cache:
            _icon_cache[key] = _svg_icon(_FOLDER_SVG)
        return _icon_cache[key]
    ext = ext_of(name)
    colour = next((c for exts, c in _TYPE_COLOURS if ext in exts), None) or _KIND_COLOURS.get(category_of(name), "#6E6C76")
    label = (ext.upper() if ext and len(ext) <= 4 else "FILE")
    key = ("c", label, colour)
    if key not in _icon_cache:
        size = {1: 15, 2: 15, 3: 13.5, 4: 11}.get(len(label), 11)
        _icon_cache[key] = _svg_icon(_PAGE_SVG.format(colour=colour, size=size, label=esc(label)))
    return _icon_cache[key]


def icon_for(name, is_dir):
    if ICON_STYLE["colour"]:
        return colour_icon(name, is_dir)
    if is_dir:
        return FOLDER_ICON
    ext = ext_of(name)
    if ext not in _icon_cache:
        ctype, _ = Gio.content_type_guess(str(name), None)
        _icon_cache[ext] = Gio.content_type_get_icon(ctype)
    return _icon_cache[ext]


def type_description(path, is_dir=False):
    if is_dir:
        return "Folder"
    ctype, _ = Gio.content_type_guess(str(path), None)
    return Gio.content_type_get_description(ctype)


def read_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def downloads_dir():
    d = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOWNLOAD)
    return Path(d) if d else HOME / "Downloads"


def is_hidden(name, st=None):
    if name.startswith("."):
        return True
    if IS_WIN and st is not None:          # Windows "hidden" or "system" attribute
        return bool(getattr(st, "st_file_attributes", 0) & 0x6)
    return False


def walk_entries(root, hidden=False):
    """Yields (path, stat, is_dir) for everything under root, skipping junk folders."""
    for dirpath, dirnames, filenames in os.walk(root):
        keep = []
        for d in dirnames:
            if d in SKIP_DIRS:
                continue
            p = os.path.join(dirpath, d)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not hidden and is_hidden(d, st):
                continue
            keep.append(d)
            yield Path(p), st, True
        dirnames[:] = keep
        for f in filenames:
            p = os.path.join(dirpath, f)
            try:
                st = os.stat(p)
            except OSError:
                continue
            if not hidden and is_hidden(f, st):
                continue
            yield Path(p), st, False


def _lnk_target(path):
    """Reads the target path out of a Windows .lnk shortcut (no extra libraries needed)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return None
    if len(data) < 76 or data[:4] != b"\x4c\x00\x00\x00":
        return None
    flags = int.from_bytes(data[20:24], "little")
    pos = 76
    if flags & 0x01:                                   # HasLinkTargetIDList
        pos += 2 + int.from_bytes(data[pos:pos + 2], "little")
    if not flags & 0x02:                               # HasLinkInfo
        return None
    info = data[pos:]
    if len(info) < 28 or not int.from_bytes(info[8:12], "little") & 0x01:
        return None
    header = int.from_bytes(info[4:8], "little")
    if header >= 0x24 and len(info) >= 0x24:
        off = int.from_bytes(info[28:32], "little")
        end = off
        while end + 1 < len(info) and info[end:end + 2] != b"\0\0":
            end += 2
        text = info[off:end].decode("utf-16-le", "ignore")
    else:
        off = int.from_bytes(info[16:20], "little")
        end = info.find(b"\0", off)
        text = info[off:end].decode("mbcs" if IS_WIN else "latin-1", "ignore")
    return text or None


def opened_history():
    """Files the system remembers you opening, in any app."""
    if IS_WIN:
        items = []
        recent = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Recent"
        try:
            links = list(recent.glob("*.lnk"))
        except OSError:
            links = []
        for lnk in links:
            target = _lnk_target(lnk)
            if target:
                try:
                    items.append((lnk.stat().st_mtime, Path(target)))
                except OSError:
                    pass
        return items
    xbel = Path(GLib.get_user_data_dir()) / "recently-used.xbel"
    try:
        root = ET.parse(xbel).getroot()
    except (OSError, ET.ParseError):
        return []
    items = []
    for bm in root.iter("bookmark"):
        href = bm.get("href", "")
        if not href.startswith("file://"):
            continue
        path = Path(urllib.parse.unquote(href[7:]))
        stamp = bm.get("visited") or bm.get("modified") or ""
        try:
            ts = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        items.append((ts, path))
    return items


def recent_activity(days=30, limit=300):
    """Files you opened or edited lately, newest first: [(timestamp, Path), ...]."""
    cutoff = time.time() - days * 86400
    best = {}

    def add(p, ts):
        if ts >= cutoff and ts > best.get(p, 0):
            best[p] = ts
    for ts, p in opened_history():
        add(str(p), ts)
    rows = INDEX.recent(cutoff) if INDEX.fresh() else None
    if rows is None:
        for p, st, is_dir in walk_entries(HOME):
            if not is_dir:
                add(str(p), st.st_mtime)
    else:
        for p, ts in rows:
            add(p, ts)
    out = []
    for p, ts in sorted(best.items(), key=lambda kv: kv[1], reverse=True):
        if os.path.isfile(p):
            out.append((ts, Path(p)))
            if len(out) >= limit:
                break
    return out


def build_sessions(items, gap=45 * 60):
    """Groups (ts, path) items into work sessions separated by breaks longer than gap."""
    sessions, cur = [], []
    for ts, p in sorted(items):
        if cur and ts - cur[-1][0] > gap:
            sessions.append(cur)
            cur = []
        cur.append((ts, p))
    if cur:
        sessions.append(cur)
    return list(reversed(sessions))


def unique_target(dest):
    dest = Path(dest)
    if not dest.exists():
        return dest
    i = 1
    while True:
        cand = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
        if not cand.exists():
            return cand
        i += 1


# ---------------------------------------------------------------- archives: extract & compress

TAR_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tbz", ".tar.xz", ".txz", ".tar")
SINGLE_SUFFIXES = {".gz": gzip.open, ".bz2": bz2.open, ".xz": lzma.open}
TOOL_SUFFIXES = (".7z", ".rar")


class NeedPassword(Exception):
    def __init__(self, wrong=False):
        super().__init__("password needed")
        self.wrong = wrong


class ExtractError(Exception):
    pass


def archive_kind(path):
    name = os.path.basename(str(path)).lower()
    if name.endswith(".zip"):
        return "zip"
    if name.endswith(TAR_SUFFIXES):
        return "tar"
    if name.endswith(TOOL_SUFFIXES):
        return "tool"
    if os.path.splitext(name)[1] in SINGLE_SUFFIXES:
        return "single"
    return None


def archive_stem(path):
    name = os.path.basename(str(path))
    low = name.lower()
    for suf in TAR_SUFFIXES + (".zip",) + TOOL_SUFFIXES + tuple(SINGLE_SUFFIXES):
        if low.endswith(suf) and len(name) > len(suf):
            return name[:-len(suf)]
    return os.path.splitext(name)[0] or name


def archive_tool():
    """An installed 7-Zip (handles .7z, .rar and unusual .zip files)."""
    for exe in ("7z", "7zz", "7za"):
        found = shutil.which(exe)
        if found:
            return found
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            exe = os.path.join(base, "7-Zip", "7z.exe")
            if os.path.exists(exe):
                return exe
    return None


def bsdtar_tool():
    """libarchive's tar: built into Windows 10/11 (System32\\tar.exe); on Linux the 'bsdtar' command.
    It opens .7z / .rar / .zip without 7-Zip and can create .7z (but not with a password)."""
    if IS_WIN:
        exe = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        return exe if os.path.exists(exe) else None
    return shutil.which("bsdtar")


def _no_window():
    return {"creationflags": 0x08000000} if IS_WIN else {}


def _hide_on_windows(path):
    if IS_WIN:
        try:
            import ctypes
            ctypes.windll.kernel32.SetFileAttributesW(str(path), 0x2)
        except Exception:
            pass


def _replace(src, dst):
    """os.replace that waits out antivirus scanners briefly locking brand-new files (common on Windows);
    for a folder it falls back to moving the contents one by one."""
    for attempt in range(25):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == 24:
                break
            time.sleep(0.2)
    if os.path.isdir(src):
        os.makedirs(dst, exist_ok=True)
        for name in os.listdir(src):
            shutil.move(os.path.join(src, name), os.path.join(dst, name))
        shutil.rmtree(src, ignore_errors=True)
    else:
        shutil.copy2(src, dst)
        try:
            os.remove(src)
        except OSError:
            pass


def _zip_name(info):
    """ZIPs made by Windows' "Send to → Compressed folder" store names in the old DOS code page,
    not UTF-8, so non-English names came out garbled. Try UTF-8, then this computer's code page."""
    name = info.filename
    if info.flag_bits & 0x800:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8",) + ((f"cp{_oem_codepage()}",) if IS_WIN else ()):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return name


def _oem_codepage():
    try:
        import ctypes
        return ctypes.windll.kernel32.GetOEMCP()
    except Exception:
        return 437


def _inside(base, target):
    base, target = os.path.realpath(base), os.path.realpath(target)
    return target == base or target.startswith(base + os.sep)


def _extract_zip(path, out, password, progress):
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ExtractError("This isn't a valid ZIP file (it may be damaged or incomplete).")
    with zf:
        infos = zf.infolist()
        if password:
            zf.setpassword(password.encode("utf-8"))
        elif any(i.flag_bits & 0x1 for i in infos):
            raise NeedPassword()
        total, done = sum(i.file_size for i in infos) or 1, 0
        for info in infos:
            name = _zip_name(info).replace("\\", "/")
            target = os.path.join(out, *[p for p in name.split("/") if p not in ("", ".", "..")])
            if not _inside(out, target):
                continue
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            try:
                with zf.open(info) as src, open(target, "wb") as dst:
                    for chunk in iter(lambda: src.read(1 << 20), b""):
                        dst.write(chunk)
                        done += len(chunk)
                        progress(done, total)
            except NotImplementedError:
                raise                            # AES / unusual method: extract_archive retries with 7-Zip
            except RuntimeError as ex:
                if "password" in str(ex).lower() or "encrypted" in str(ex).lower():
                    raise NeedPassword(wrong=bool(password))
                raise ExtractError(str(ex))
            except zipfile.BadZipFile as ex:
                raise NeedPassword(wrong=True) if password else ExtractError(str(ex))
            mode = (info.external_attr >> 16) & 0o777
            if not IS_WIN and mode & 0o111:
                os.chmod(target, mode | 0o600)
            try:
                ts = time.mktime(info.date_time + (0, 0, -1))
                os.utime(target, (ts, ts))
            except (OverflowError, ValueError, OSError):
                pass


def _extract_tar(path, out, progress):
    try:
        tf = tarfile.open(path, "r:*")
    except (tarfile.TarError, OSError) as ex:
        raise ExtractError(f"Can't read this archive: {ex}")
    with tf:
        members = tf.getmembers()
        total, done = sum(m.size for m in members) or 1, 0
        safe_filter = getattr(tarfile, "data_filter", None)
        for m in members:
            if safe_filter is not None:
                try:
                    tf.extract(m, out, filter="data")
                except tarfile.FilterError:
                    continue                      # skips anything that would escape the folder
            else:                                 # older Python: plain files and folders only
                target = os.path.join(out, m.name)
                if not _inside(out, target):
                    continue
                if m.isdir():
                    os.makedirs(target, exist_ok=True)
                elif m.isfile():
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with tf.extractfile(m) as src, open(target, "wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
            done += m.size
            progress(done, total)


def _extract_single(path, out, progress):
    opener = SINGLE_SUFFIXES[os.path.splitext(path)[1].lower()]
    total, done = os.path.getsize(path) or 1, 0
    try:
        with opener(path, "rb") as src, open(os.path.join(out, archive_stem(path)), "wb") as dst:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                dst.write(chunk)
                done += len(chunk)
                progress(min(done, total), total)
    except (OSError, EOFError, lzma.LZMAError) as ex:
        raise ExtractError(f"Can't decompress this file: {ex}")


def _extract_tool(path, out, password):
    tool = archive_tool()
    if not tool:
        bsd = bsdtar_tool()
        if bsd and not password:
            proc = subprocess.run([bsd, "-xf", path, "-C", out], stdin=subprocess.DEVNULL,
                                  capture_output=True, text=True, errors="replace", **_no_window())
            if proc.returncode == 0:
                return
            text = (proc.stderr or proc.stdout).lower()
            if "passphrase" in text or "encrypt" in text or "password" in text:
                raise NeedPassword()
            hint = "Install 7-Zip from 7-zip.org" if IS_WIN else "Install it with:  sudo apt install 7zip"
            raise ExtractError("The built-in archive tool couldn't open it:\n" + (proc.stderr or proc.stdout).strip()[-400:]
                               + f"\n\n{hint}, which handles more archive types.")
        hint = ("Install 7-Zip from 7-zip.org" if IS_WIN else "Install it with:  sudo apt install 7zip")
        need = "Password-protected archives need" if password else "Opening .7z and .rar files needs"
        raise ExtractError(f"{need} 7-Zip. {hint}")
    proc = subprocess.run([tool, "x", "-y", f"-o{out}", f"-p{password or ''}", path],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", **_no_window())
    text = (proc.stdout + proc.stderr).lower()
    if proc.returncode != 0:
        if "password" in text or "encrypted" in text:
            raise NeedPassword(wrong=bool(password))
        raise ExtractError("7-Zip couldn't extract it:\n" + (proc.stderr or proc.stdout).strip()[-600:])


def extract_archive(path, dest_dir, password=None, progress=lambda done, total: None):
    """Extracts into dest_dir. A single top-level item lands directly in dest_dir; several items
    go into a new folder named after the archive, so files never spill everywhere.
    Returns the path of what was created."""
    kind = archive_kind(path)
    if kind is None:
        raise ExtractError("This file type isn't an archive Arckad-D can extract.")
    work = tempfile.mkdtemp(prefix=".arckad-extract-", dir=dest_dir)
    _hide_on_windows(work)
    try:
        if kind == "zip":
            try:
                _extract_zip(path, work, password, progress)
            except NotImplementedError:              # AES-encrypted or rare compression: use 7-Zip
                shutil.rmtree(work, ignore_errors=True)
                os.makedirs(work)
                _extract_tool(path, work, password)
        elif kind == "tar":
            _extract_tar(path, work, progress)
        elif kind == "single":
            _extract_single(path, work, progress)
        else:
            _extract_tool(path, work, password)
        items = os.listdir(work)
        if not items:
            raise ExtractError("The archive is empty.")
        if len(items) == 1:
            final = unique_target(Path(dest_dir) / items[0])
            _replace(os.path.join(work, items[0]), final)
            shutil.rmtree(work, ignore_errors=True)
        else:
            final = unique_target(Path(dest_dir) / archive_stem(path))
            _replace(work, final)
            if IS_WIN:
                try:
                    import ctypes
                    ctypes.windll.kernel32.SetFileAttributesW(str(final), 0x80)     # normal (not hidden)
                except Exception:
                    pass
        return final
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


# (key, extension, label, needs 7-Zip, single file only)
COMPRESS_FORMATS = [
    ("zip", ".zip", "ZIP: opens on every computer", False, False),
    ("7z", ".7z", "7Z: smallest size", True, False),
    ("tar.gz", ".tar.gz", "TAR.GZ: common on Linux, fast", False, False),
    ("tar.xz", ".tar.xz", "TAR.XZ: very small, slower", False, False),
    ("tar.bz2", ".tar.bz2", "TAR.BZ2: small, slower", False, False),
    ("tar", ".tar", "TAR: bundle only, no compression", False, False),
    ("gz", ".gz", "GZ: one file only", False, True),
    ("xz", ".xz", "XZ: one file only", False, True),
    ("bz2", ".bz2", "BZ2: one file only", False, True),
]
COMPRESS_LEVELS = [("Fast", 1), ("Normal", 6), ("Best (smallest)", 9)]
PASSWORD_FORMATS = {"zip", "7z"}


def _gather(paths):
    """[(source, name inside the archive, size, is_dir)] for files and whole folders."""
    entries = []
    for p in paths:
        if os.path.isdir(p):
            base = os.path.dirname(p.rstrip("/\\"))
            entries.append((p, os.path.relpath(p, base), 0, True))
            for fp, st, is_dir in walk_entries(p, hidden=True):
                entries.append((str(fp), os.path.relpath(fp, base), 0 if is_dir else st.st_size, is_dir))
        elif os.path.isfile(p):
            entries.append((p, os.path.basename(p), os.path.getsize(p), False))
    return entries


def can_make_7z(password=False):
    return archive_tool() is not None or (not password and bsdtar_tool() is not None)


def _bsdtar_7z(paths, out):
    args = [bsdtar_tool(), "--format", "7zip", "-cf", str(out)]
    for p in paths:
        p = str(p).rstrip("/\\")
        args += ["-C", os.path.dirname(p) or ".", os.path.basename(p)]
    proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", **_no_window())
    if proc.returncode != 0:
        raise ExtractError("Couldn't create the .7z file:\n" + (proc.stderr or proc.stdout).strip()[-400:])


def _run_7z(args):
    tool = archive_tool()
    if not tool:
        hint = "Install 7-Zip from 7-zip.org" if IS_WIN else "Install it with:  sudo apt install 7zip"
        raise ExtractError(f"This needs 7-Zip. {hint}")
    proc = subprocess.run([tool] + args, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace",
                          **_no_window())
    if proc.returncode != 0:
        raise ExtractError("7-Zip couldn't create the archive:\n" + (proc.stderr or proc.stdout).strip()[-600:])


def compress_archive(paths, dest, fmt="zip", level=6, password=None, progress=lambda done, total: None):
    """Creates an archive at dest in the chosen format. Returns its Path."""
    dest = Path(dest)
    ext = next(e for k, e, *_ in COMPRESS_FORMATS if k == fmt)
    tmp = dest.with_name(f".arckad-{secrets.token_hex(4)}{ext}")    # finished file appears in one step
    try:
        if fmt == "7z" and not password and archive_tool() is None and bsdtar_tool():
            _bsdtar_7z(paths, tmp)
        elif fmt == "7z" or (fmt == "zip" and password):
            args = ["a", "-y", "-t7z" if fmt == "7z" else "-tzip", f"-mx={level}"]
            if password:
                args.append(f"-p{password}")
                args.append("-mhe=on" if fmt == "7z" else "-mem=AES256")
            _run_7z(args + [str(tmp)] + [str(p) for p in paths])
        elif fmt == "zip":
            entries = _gather(paths)
            total, done = sum(e[2] for e in entries) or 1, 0
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=level, allowZip64=True) as zf:
                for src, arc, size, is_dir in entries:
                    arc = arc.replace(os.sep, "/")
                    zf.write(src, arc + "/" if is_dir else arc)
                    done += size
                    progress(done, total)
        elif fmt.startswith("tar"):
            total = sum(e[2] for e in _gather(paths)) or 1
            done = [0]

            def count(info):
                done[0] += info.size
                progress(min(done[0], total), total)
                return info
            comp = fmt.split(".")[1] if "." in fmt else ""
            kwargs = {"preset": level} if comp == "xz" else ({"compresslevel": level} if comp else {})
            with tarfile.open(tmp, "w:" + comp if comp else "w", **kwargs) as tf:
                for p in paths:
                    tf.add(p, arcname=os.path.basename(p.rstrip("/\\")), filter=count)
        else:                                       # gz / xz / bz2 of a single file
            if len(paths) != 1 or not os.path.isfile(paths[0]):
                raise ExtractError(f".{fmt} can only hold one file. Choose ZIP, 7Z or TAR for folders "
                                   "or several files.")
            opener = {"gz": lambda f: gzip.open(f, "wb", compresslevel=level),
                      "bz2": lambda f: bz2.open(f, "wb", compresslevel=level),
                      "xz": lambda f: lzma.open(f, "wb", preset=level)}[fmt]
            total, done = os.path.getsize(paths[0]) or 1, 0
            with open(paths[0], "rb") as src, opener(tmp) as dst:
                for chunk in iter(lambda: src.read(1 << 20), b""):
                    dst.write(chunk)
                    done += len(chunk)
                    progress(done, total)
        _replace(tmp, dest)
        return dest
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise


def compress_to_zip(paths, dest_zip, progress=lambda done, total: None):
    return compress_archive(paths, dest_zip, "zip", 6, None, progress)


# ---------------------------------------------------------------- updates from GitHub Releases
def version_tuple(v):
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:4]]
    return tuple(nums + [0] * (3 - len(nums))) if nums else (0, 0, 0)


def fetch_latest_release(timeout=15):
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                     headers={"Accept": "application/vnd.github+json",
                                              "User-Agent": f"{APP_NAME}/{APP_VERSION}"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        if ex.code not in (403, 429):          # GitHub's lookup limit reached: use the plain web page instead
            raise
    req = urllib.request.Request(f"https://github.com/{UPDATE_REPO}/releases/latest",
                                 headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        final_url = resp.geturl()                # .../releases/tag/v3.8.0
    tag = final_url.rstrip("/").rsplit("/", 1)[-1]
    if "/tag/" not in final_url or not tag:
        raise OSError("no release found")
    ver = tag.lstrip("vV")
    base = f"https://github.com/{UPDATE_REPO}/releases/download/{tag}/"
    names = [f"Arckad-D-Setup-{ver}.exe", f"arckad-d_{ver}_all.deb", f"Arckad-D-{ver}.apk"]
    return {"tag_name": tag, "html_url": final_url,
            "assets": [{"name": n, "browser_download_url": base + n} for n in names]}


def pick_asset(release, kind):
    for a in release.get("assets", []):
        name = a.get("name", "")
        if kind == "windows" and name.startswith("Arckad-D-Setup") and name.endswith(".exe"):
            return a
        if kind == "deb" and name.endswith("_all.deb"):
            return a
        if kind == "apk" and name.endswith(".apk"):
            return a
    return None


def install_kind():
    """How this copy was installed, which decides how it can update itself."""
    if IS_WIN:
        installed = FROZEN and os.path.exists(os.path.join(os.path.dirname(sys.executable), "unins000.exe"))
        return "windows" if installed else "manual"
    return "deb" if INSTALLED and shutil.which("pkexec") else "manual"


def download_asset(asset, dest, progress=lambda done, total: None, cancelled=lambda: False):
    req = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    total, done = int(asset.get("size") or 0), 0
    h = hashlib.sha256()
    tmp = str(dest) + ".part"
    with urllib.request.urlopen(req, timeout=60) as resp, open(tmp, "wb") as f:
        while True:
            if cancelled():
                raise InterruptedError
            chunk = resp.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            progress(done, total or done)
    if total and done != total:
        os.remove(tmp)
        raise OSError("the download was incomplete")
    digest = str(asset.get("digest") or "")
    if digest.startswith("sha256:") and digest[7:].lower() != h.hexdigest():
        os.remove(tmp)
        raise OSError("the download didn't match GitHub's checksum")
    os.replace(tmp, dest)
    return dest


def plan_organize(folder, by):
    plan = []
    for p in sorted(Path(folder).iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.name.startswith("."):
            continue
        sub = (datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m")
               if by == "date" else category_of(p.name))
        plan.append((p, Path(folder) / sub / p.name))
    return plan


def apply_plan(plan):
    done = []
    for src, dst in plan:
        try:
            Path(dst).parent.mkdir(exist_ok=True)
            dst = unique_target(dst)
            shutil.move(str(src), str(dst))
            TAG_STORE.moved(str(src), str(dst))
            done.append([str(src), str(dst)])
        except OSError:
            continue
    if done:
        history = read_json(UNDO_FILE, [])
        history.append({"when": time.time(), "moves": done})
        write_json(UNDO_FILE, history[-20:])
    return done


def undo_last():
    history = read_json(UNDO_FILE, [])
    if not history:
        return []
    batch = history.pop()
    restored = []
    for src, dst in reversed(batch["moves"]):
        if Path(dst).exists() and not Path(src).exists():
            shutil.move(dst, src)
            TAG_STORE.moved(dst, src)
            restored.append(src)
            try:
                Path(dst).parent.rmdir()  # only removes it if now empty
            except OSError:
                pass
    write_json(UNDO_FILE, history)
    ignore = read_json(IGNORE_FILE, []) + restored   # so auto-sort leaves them alone
    write_json(IGNORE_FILE, ignore[-500:])
    return restored


LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="front" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#6c63ff"/><stop offset="1" stop-color="#14b8a6"/>
    </linearGradient>
    <linearGradient id="back" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3f37c9"/><stop offset="1" stop-color="#0f766e"/>
    </linearGradient>
    <linearGradient id="badge" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#ffc83d"/><stop offset="1" stop-color="#ff8a00"/>
    </linearGradient>
  </defs>
  <path d="M24 62q0-22 22-22h58q11 0 18 9l12 15h76q22 0 22 22v112q0 22-22 22H46q-22 0-22-22z" fill="url(#back)"/>
  <rect x="34" y="78" width="188" height="16" rx="6" fill="#ffffff" opacity="0.85"/>
  <rect x="16" y="90" width="224" height="136" rx="24" fill="url(#front)"/>
  <path d="M58 206 90 110h28l32 96h-26l-6-20h-30l-6 20zm38-42h18l-9-30z" fill="#ffffff" fill-rule="evenodd"/>
  <circle cx="194" cy="194" r="44" fill="url(#badge)" stroke="#ffffff" stroke-width="9"/>
  <path d="M194 168v28l18 12" fill="none" stroke="#3b2a00" stroke-width="10" stroke-linecap="round" stroke-linejoin="round"/>
</svg>
"""


def ensure_logo():
    try:
        if not ICON_FILE.exists() or ICON_FILE.read_text() != LOGO_SVG:
            ICON_FILE.parent.mkdir(parents=True, exist_ok=True)
            ICON_FILE.write_text(LOGO_SVG)
    except OSError:
        return None
    return ICON_FILE


LOGO_EXTS = ("svg", "png", "jpg", "jpeg", "webp")


def custom_logo():
    """Your own logo, if you chose one (saved as ~/.config/arckad-d/logo.png / .svg / ...)."""
    for ext in LOGO_EXTS:
        p = CONFIG_DIR / f"logo.{ext}"
        if p.exists():
            return p
    return None


def logo_path():
    return custom_logo() or ensure_logo()


def logo_pixbuf(size):
    for path in (custom_logo(), ensure_logo(), BUNDLE_DIR / f"{APP_SLUG}.png"):
        if path and Path(path).exists():
            pb = load_scaled(path, size)
            if pb:
                return pb
    return None


def set_custom_logo(src):
    """Copies an image in as the app logo; src=None goes back to the built-in logo."""
    for ext in LOGO_EXTS:
        old = CONFIG_DIR / f"logo.{ext}"
        if old.exists():
            old.unlink()
    if src:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, CONFIG_DIR / f"logo.{ext_of(src)}")
    desktop = Path(GLib.get_user_data_dir()) / "applications" / f"{APP_SLUG}.desktop"
    if desktop.exists():
        install_launcher()     # point the app-menu entry at the new logo


def install_launcher():
    apps = Path(GLib.get_user_data_dir()) / "applications"
    apps.mkdir(parents=True, exist_ok=True)
    icon = custom_logo() or (APP_SLUG if INSTALLED else logo_path()) or "system-file-manager"
    desktop = apps / f"{APP_SLUG}.desktop"
    desktop.write_text(
        f"[Desktop Entry]\nType=Application\nName={APP_NAME}\n"
        "Comment=File manager that remembers what you last worked on\n"
        f"Exec={LAUNCH_CMD} %f\n"
        f"Icon={icon}\nTerminal=false\n"
        f"Categories=Utility;FileManager;GTK;\nStartupWMClass={APP_SLUG}\n")
    if OLD_DESKTOP.exists():
        OLD_DESKTOP.unlink()
    return desktop


def windows_dark_mode():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        return value == 0
    except (ImportError, OSError):
        return False


def self_command():
    """How to start this app again (as the .exe, or as python + script)."""
    return [sys.executable] if FROZEN else [sys.executable, str(SCRIPT)]


def open_default(target):
    """Opens a file, folder or web link with the system's default app."""
    if IS_WIN:
        os.startfile(target)
    else:
        uri = target if "://" in target else Gio.File.new_for_path(target).get_uri()
        Gio.AppInfo.launch_default_for_uri(uri, None)


def fix_user_launcher():
    """With the .deb installed, an old per-user menu entry (from --install) would hide the real one."""
    desktop = Path(GLib.get_user_data_dir()) / "applications" / f"{APP_SLUG}.desktop"
    if IS_WIN or not INSTALLED or not desktop.exists():
        return
    try:
        if custom_logo():
            install_launcher()        # keep the user's own logo, but launch the installed app
        else:
            desktop.unlink()
    except OSError:
        pass


def migrate_from_fileminder():
    """Carries settings, tags and notes over from the old 'fileminder' name."""
    if IS_WIN:
        return
    try:
        if OLD_CONFIG_DIR.is_dir() and not CONFIG_DIR.exists():
            shutil.copytree(OLD_CONFIG_DIR, CONFIG_DIR)
        old_pid = OLD_CACHE_DIR / "autosort.pid"
        if old_pid.exists():
            try:
                os.kill(int(old_pid.read_text()), signal.SIGTERM)
            except (OSError, ValueError):
                pass
        if OLD_AUTOSTART.exists():
            OLD_AUTOSTART.unlink()
    except OSError:
        pass


def file_hash(path, partial=False):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        if partial:
            h.update(f.read(65536))
        else:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def is_text_file(path):
    if ext_of(path) not in TEXT_EXTS:
        ctype, _ = Gio.content_type_guess(str(path), None)
        if not Gio.content_type_is_a(ctype, "text/plain"):
            return False
    try:
        with open(path, "rb") as f:
            return b"\0" not in f.read(4096)
    except OSError:
        return False


def read_text(path, max_bytes=200_000):
    with open(path, "rb") as f:
        data = f.read(max_bytes + 1)
    return data[:max_bytes].decode("utf-8", errors="replace"), len(data) > max_bytes


# ---------------------------------------------------------------- thumbnails & previews
def load_scaled(path, width, height=None):
    try:
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), width, height or width, True)
        return pb.apply_embedded_orientation() or pb
    except GLib.Error:
        return None


def cached_thumbnail(path, size):
    """Reuses the thumbnails Ubuntu's Files app already made."""
    uri = Gio.File.new_for_path(str(path)).get_uri()
    h = hashlib.md5(uri.encode()).hexdigest()
    base = Path(GLib.get_user_cache_dir()) / "thumbnails"
    for sub in ("x-large", "large", "normal"):
        t = base / sub / f"{h}.png"
        if t.exists():
            return load_scaled(t, size)
    return None


def render_pdf(path, width):
    exe = shutil.which("pdftoppm")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "page")
        try:
            subprocess.run([exe, "-png", "-f", "1", "-l", "1", "-singlefile",
                            "-scale-to", str(width * 2), str(path), out],
                           timeout=20, capture_output=True)
        except (subprocess.SubprocessError, OSError):
            return None
        return load_scaled(out + ".png", width, int(width * 1.5)) if os.path.exists(out + ".png") else None


def render_video(path, width):
    exe = shutil.which("ffmpegthumbnailer")
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "frame.png")
        try:
            subprocess.run([exe, "-i", str(path), "-o", out, "-s", str(width * 2), "-q", "6"],
                           timeout=20, capture_output=True)
        except (subprocess.SubprocessError, OSError):
            return None
        return load_scaled(out, width) if os.path.exists(out) else None


def pdf_pages(path):
    exe = shutil.which("pdfinfo")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, str(path)], timeout=10, capture_output=True, text=True).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return line.split(":", 1)[1].strip()
    return None


def thumbnail_for(path, size, render=True):
    kind = category_of(path)
    if kind == "Images":
        pb = load_scaled(path, size)
        if pb:
            return pb
    pb = cached_thumbnail(path, size)
    if pb or not render:
        return pb
    if ext_of(path) == "pdf":
        return render_pdf(path, size)
    if kind == "Videos":
        return render_video(path, size)
    return None


# ---------------------------------------------------------------- filters
def parse_exts(text):
    return {e.strip().lstrip(".").lower() for e in text.replace(",", " ").split() if e.strip(" .")}


class Filters:
    def __init__(self, query="", kind="All types", exts=(), start=None, end=None):
        self.query, self.kind, self.exts, self.start, self.end = query, kind, set(exts), start, end

    @property
    def active(self):
        return bool(self.query or self.kind != "All types" or self.exts or self.start or self.end)

    def match(self, name, is_dir, kind, mtime, note=""):
        if self.query:
            hay = name.lower() + " " + note.lower()
            if not all(w in hay for w in self.query.split()):
                return False
        if self.kind != "All types" and kind != self.kind:
            return False
        if self.exts and (is_dir or ext_of(name) not in self.exts):
            return False
        if self.start and mtime < self.start:
            return False
        if self.end and mtime >= self.end:
            return False
        return True


# ---------------------------------------------------------------- tags & notes
class TagStore:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = read_json(TAGS_FILE, {})

    def _entry(self, path):
        return self.data.get(str(path), {})

    def tags(self, path):
        return list(self._entry(path).get("tags", []))

    def note(self, path):
        return self._entry(path).get("note", "")

    def set_tags(self, path, tags):
        order = list(TAGS)
        self._update(path, tags=sorted(set(tags), key=lambda t: order.index(t) if t in order else 99))

    def set_note(self, path, note):
        self._update(path, note=note.strip())

    def _update(self, path, **changes):
        with self.lock:
            entry = dict(self.data.get(str(path), {}))
            entry.update(changes)
            entry = {k: v for k, v in entry.items() if v}
            if entry:
                self.data[str(path)] = entry
            else:
                self.data.pop(str(path), None)
            write_json(TAGS_FILE, self.data)

    def moved(self, old, new):
        old, new = str(old), str(new)
        with self.lock:
            changed = False
            for key in list(self.data):
                if key == old or key.startswith(old + os.sep):
                    self.data[new + key[len(old):]] = self.data.pop(key)
                    changed = True
            if changed:
                write_json(TAGS_FILE, self.data)

    def with_tag(self, tag):
        with self.lock:
            items = list(self.data.items())
        return [p for p, e in items if tag in e.get("tags", []) and os.path.exists(p)]

    def with_notes(self):
        with self.lock:
            items = list(self.data.items())
        return [p for p, e in items if e.get("note") and os.path.exists(p)]

    def markup(self, path):
        e = self._entry(path)
        parts = [f'<span foreground="{TAGS[t]}">●</span> {esc(t)}' for t in e.get("tags", []) if t in TAGS]
        if e.get("note"):
            parts.append("✎ note")
        return "  ".join(parts)


# ---------------------------------------------------------------- instant search index
def like_escape(s):
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class FileIndex:
    """A small SQLite list of every file in your home folder, rebuilt in the background."""

    def __init__(self):
        self.building = False
        self.listeners = []
        meta = read_json(INDEX_META, {})
        self.count = meta.get("count", 0) if INDEX_DB.exists() else 0
        self.updated = meta.get("updated", 0) if INDEX_DB.exists() else 0

    def available(self):
        return INDEX_DB.exists()

    def fresh(self, max_age=INDEX_MAX_AGE):
        return INDEX_DB.exists() and time.time() - self.updated < max_age

    def rebuild(self):
        if self.building:
            return
        self.building = True
        for cb in list(self.listeners):
            GLib.idle_add(cb)
        threading.Thread(target=self._build, daemon=True).start()

    def _build(self):
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = INDEX_DB.with_name("index.tmp")
            if tmp.exists():
                tmp.unlink()
            con = sqlite3.connect(str(tmp))
            con.execute("CREATE TABLE files (path TEXT PRIMARY KEY, lname TEXT, ext TEXT,"
                        " is_dir INTEGER, size INTEGER, mtime REAL)")
            n, batch = 0, []
            for p, st, is_dir in walk_entries(HOME):
                batch.append((str(p), p.name.lower(), "" if is_dir else ext_of(p.name),
                              int(is_dir), 0 if is_dir else st.st_size, st.st_mtime))
                n += 1
                if len(batch) >= 5000:
                    con.executemany("INSERT OR IGNORE INTO files VALUES (?,?,?,?,?,?)", batch)
                    batch = []
            if batch:
                con.executemany("INSERT OR IGNORE INTO files VALUES (?,?,?,?,?,?)", batch)
            con.execute("CREATE INDEX idx_mtime ON files(mtime)")
            con.commit()
            con.close()
            os.replace(tmp, INDEX_DB)
            self.count, self.updated = n, time.time()
            write_json(INDEX_META, {"count": n, "updated": self.updated})
        except (OSError, sqlite3.Error) as ex:
            print(f"{APP_NAME}: indexing failed:", ex, file=sys.stderr)
        finally:
            self.building = False
            for cb in list(self.listeners):
                GLib.idle_add(cb)

    def _rows(self, sql, args):
        if not INDEX_DB.exists():
            return None
        try:
            con = sqlite3.connect(f"file:{INDEX_DB}?mode=ro", uri=True)
            rows = con.execute(sql, args).fetchall()
            con.close()
            return rows
        except sqlite3.Error:
            return None

    def query(self, f, root=None, limit=5000):
        sql, args = ["SELECT path, is_dir, size, mtime FROM files WHERE 1=1"], []
        if root and str(root) != str(HOME):
            sql.append("AND path LIKE ? ESCAPE '\\'")
            args.append(like_escape(str(root).rstrip("/\\")) + like_escape(os.sep) + "%")
        for word in f.query.split():
            sql.append("AND lname LIKE ? ESCAPE '\\'")
            args.append("%" + like_escape(word) + "%")
        if f.exts:
            sql.append(f"AND is_dir=0 AND ext IN ({','.join('?' * len(f.exts))})")
            args += sorted(f.exts)
        if f.kind == "Folder":
            sql.append("AND is_dir=1")
        elif f.kind in CATEGORIES:
            exts = sorted(CATEGORIES[f.kind])
            sql.append(f"AND is_dir=0 AND ext IN ({','.join('?' * len(exts))})")
            args += exts
        elif f.kind == "Others":
            exts = sorted(ALL_KNOWN_EXTS)
            sql.append(f"AND is_dir=0 AND ext NOT IN ({','.join('?' * len(exts))})")
            args += exts
        if f.start:
            sql.append("AND mtime >= ?")
            args.append(f.start)
        if f.end:
            sql.append("AND mtime < ?")
            args.append(f.end)
        sql.append("ORDER BY mtime DESC LIMIT ?")
        args.append(limit)
        return self._rows(" ".join(sql), args)

    def recent(self, cutoff, limit=3000):
        return self._rows("SELECT path, mtime FROM files WHERE is_dir=0 AND mtime >= ? "
                          "ORDER BY mtime DESC LIMIT ?", (cutoff, limit))


migrate_from_fileminder()
TAG_STORE = TagStore()
INDEX = FileIndex()


# ---------------------------------------------------------------- auto-sort Downloads
class AutoSorter:
    """Watches a folder and moves newly arrived files into category subfolders."""

    def __init__(self, folder, delay=5, on_moved=None):
        self.folder, self.delay, self.on_moved = Path(folder), max(2, int(delay)), on_moved
        self.started = time.time()
        self.known = {p.name for p in self.folder.iterdir()} if self.folder.is_dir() else set()
        self.timer = None
        self.monitor = Gio.File.new_for_path(str(self.folder)).monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOVES, None)
        self.monitor.connect("changed", self._changed)

    def stop(self):
        self.monitor.cancel()
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def _changed(self, *_):
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add_seconds(self.delay, self._scan)

    def _scan(self):
        self.timer = None
        ignore = set(read_json(IGNORE_FILE, []))
        plan, waiting = [], False
        try:
            entries = list(self.folder.iterdir())
        except OSError:
            return False
        for p in entries:
            if p.name in self.known or p.name.startswith(".") or str(p) in ignore:
                continue
            try:
                if not p.is_file():
                    continue
                st = p.stat()
            except OSError:
                continue
            if ext_of(p.name) in PARTIAL_EXTS or st.st_mtime < self.started - 60:
                continue
            if time.time() - st.st_mtime < self.delay:      # still being written
                waiting = True
                continue
            plan.append((p, self.folder / category_of(p.name) / p.name))
        if plan:
            done = apply_plan(plan)
            if done and self.on_moved:
                self.on_moved(done)
        if waiting:
            self.timer = GLib.timeout_add_seconds(self.delay, self._scan)
        return False


def pid_alive(pid):
    if IS_WIN:
        import ctypes
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        code = ctypes.c_ulong()
        ok = kernel.GetExitCodeProcess(handle, ctypes.byref(code))
        kernel.CloseHandle(handle)
        return bool(ok) and code.value == 259                # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def service_running():
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        return None
    return pid if pid != os.getpid() and pid_alive(pid) else None


def run_autosort_service():
    if service_running():
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    cfg = read_json(CONFIG_FILE, {})
    loop = GLib.MainLoop()
    sorter = AutoSorter(downloads_dir(), cfg.get("autosort_delay", 5))
    if not IS_WIN:
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: loop.quit() or False)
    try:
        loop.run()
    finally:
        sorter.stop()
        try:
            PID_FILE.unlink()
        except OSError:
            pass


def start_service():
    extra = ({"creationflags": 0x00000008 | 0x00000200} if IS_WIN      # DETACHED_PROCESS | NEW_PROCESS_GROUP
             else {"start_new_session": True})
    subprocess.Popen(self_command() + ["--autosort"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, **extra)
    return False


def stop_service():
    pid = service_running()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


def set_autostart(on):
    if IS_WIN:                     # "Run" entry in the registry = start at login
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run",
                                 0, winreg.KEY_SET_VALUE)
            if on:
                winreg.SetValueEx(key, f"{APP_NAME} AutoSort", 0, winreg.REG_SZ,
                                  subprocess.list2cmdline(self_command() + ["--autosort"]))
            else:
                try:
                    winreg.DeleteValue(key, f"{APP_NAME} AutoSort")
                except OSError:
                    pass
            winreg.CloseKey(key)
        except (ImportError, OSError):
            pass
        return
    if on:
        AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
        AUTOSTART_FILE.write_text(
            f"[Desktop Entry]\nType=Application\nName={APP_NAME} auto-sort\n"
            "Comment=Sorts new downloads into folders\n"
            f"Exec={LAUNCH_CMD} --autosort\nTerminal=false\nNoDisplay=true\n"
            "X-GNOME-Autostart-enabled=true\n")
    elif AUTOSTART_FILE.exists():
        AUTOSTART_FILE.unlink()


# ---------------------------------------------------------------- one browsing pane (= one tab)
def make_row(path, is_dir, size, mtime):
    path = str(path)
    name = os.path.basename(path.rstrip("/\\")) or path
    return [icon_for(name, is_dir), name, path, bool(is_dir), 0 if is_dir else int(size),
            "—" if is_dir else human_size(size), float(mtime), fmt_time(mtime),
            "Folder" if is_dir else category_of(name), short(os.path.dirname(path)),
            TAG_STORE.markup(path), None]


def stat_row(path, when=None):
    st = os.stat(path)
    is_dir = statmod.S_ISDIR(st.st_mode)
    return make_row(path, is_dir, st.st_size, when if when is not None else st.st_mtime)


def is_folder_loc(loc):
    loc = str(loc)
    return bool(loc) and loc not in ("recent", "notes") and not loc.startswith("tag:")


def is_root(loc):
    return Path(loc).parent == Path(loc)


def root_label(p):
    return p.name or (p.drive or str(p) if IS_WIN else "Computer")


class FilePane(Gtk.Box):
    def __init__(self, win, location):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.location = None
        self.mode = "folder"              # folder | recent | tag | notes | search
        self.back_stack, self.fwd_stack = [], []
        self.gen = 0
        self.store = self.filter = self.sorted = None
        self.iters = {}
        self.filters = Filters()
        self.custom_range = None
        self.date_idx = 0
        self.sort = {"folder": (C_NAME, Gtk.SortType.ASCENDING),
                     "other": (C_MTIME, Gtk.SortType.DESCENDING)}
        self.pending_select = self.pending_scroll = None
        self.monitor = self.refresh_id = self.ext_timer = None
        self.view_mode = win.cfg.get("view", "list")
        self.tab_label = None
        self.busy = False
        self._build()
        self.go(location if (not is_folder_loc(location) or os.path.isdir(location)) else str(HOME),
                push=False)

    # ---------- UI
    def _build(self):
        self.row1 = Gtk.Box(spacing=4, border_width=4)
        nav = Gtk.Box()
        nav.get_style_context().add_class("linked")
        self.back_btn = self.win.icon_btn("go-previous-symbolic", "Back (Alt+Left)", lambda *_: self.go_back())
        self.fwd_btn = self.win.icon_btn("go-next-symbolic", "Forward (Alt+Right)", lambda *_: self.go_forward())
        self.up_btn = self.win.icon_btn("go-up-symbolic", "Parent folder (Alt+Up)", lambda *_: self.go_up())
        for b in (self.back_btn, self.fwd_btn, self.up_btn):
            nav.add(b)
        self.row1.add(nav)

        self.crumbs = Gtk.Box()
        self.crumb_scroll = Gtk.ScrolledWindow(hexpand=True)
        self.crumb_scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.NEVER)
        self.crumb_scroll.add(self.crumbs)
        self.path_entry = Gtk.Entry(placeholder_text="Type a folder path and press Enter")
        self.path_entry.connect("activate", self.on_path_entered)
        self.path_entry.connect("focus-out-event", lambda *_: self.path_stack.set_visible_child_name("crumbs"))
        self.path_stack = Gtk.Stack(hexpand=True)
        self.path_stack.add_named(self.crumb_scroll, "crumbs")
        self.path_stack.add_named(self.path_entry, "entry")
        self.row1.pack_start(self.path_stack, True, True, 0)
        self.row1.add(self.win.icon_btn("document-edit-symbolic", "Type a path (Ctrl+L)", lambda *_: self.edit_path()))

        views = Gtk.Box()
        views.get_style_context().add_class("linked")
        self.list_btn = Gtk.RadioButton.new(None)
        self.grid_btn = Gtk.RadioButton.new_from_widget(self.list_btn)
        for b, icon, tip in ((self.list_btn, "view-list-symbolic", "List view (Ctrl+1)"),
                             (self.grid_btn, "view-grid-symbolic", "Thumbnail grid (Ctrl+2)")):
            b.set_mode(False)
            b.set_image(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            b.set_tooltip_text(tip)
            views.add(b)
        self.grid_btn.set_active(self.view_mode == "grid")
        self.list_btn.connect("toggled", lambda b: self.set_view("list" if b.get_active() else "grid"))
        self.row1.add(views)
        new_menu = Gtk.Menu()
        for label, cb in (("New folder (Ctrl+Shift+N)", lambda: self.win.new_folder(self)),
                          ("New empty file", lambda: self.win.new_file(self))):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, cb=cb: cb())
            new_menu.append(item)
        new_menu.show_all()
        self.new_btn = Gtk.MenuButton(popup=new_menu)
        nb = Gtk.Box(spacing=4)
        nb.add(Gtk.Image.new_from_icon_name("folder-new-symbolic", Gtk.IconSize.BUTTON))
        nb.add(Gtk.Label(label="New"))
        self.new_btn.add(nb)
        self.new_btn.set_tooltip_text("Create a new folder or file here")
        self.new_btn.get_style_context().add_class("suggested-action")
        self.row1.add(self.new_btn)
        self.row1.reorder_child(self.new_btn, 1)          # right after Back / Forward / Up
        self.add(self.row1)

        # filters (wrap onto two lines when the pane is narrow)
        flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=8,
                           column_spacing=4, row_spacing=4, border_width=4, homogeneous=False)
        self.search = Gtk.SearchEntry(placeholder_text="Filter name or note (Ctrl+F)", width_chars=20)
        self.search.connect("search-changed", self.on_filters_changed)
        self.kind_combo = Gtk.ComboBoxText()
        for k in KINDS:
            self.kind_combo.append_text(k)
        self.kind_combo.set_active(0)
        self.kind_combo.set_tooltip_text("Show only one kind of file")
        self.kind_combo.connect("changed", self.on_filters_changed)
        self.ext_entry = Gtk.Entry(placeholder_text="ext: pdf, jpg", width_chars=11)
        self.ext_entry.set_tooltip_text("Only these extensions, e.g.  pdf docx  or  .png .jpg")
        self.ext_entry.connect("changed", self.on_ext_changed)
        self.date_combo = Gtk.ComboBoxText()
        for label, _ in DATE_CHOICES:
            self.date_combo.append_text(label)
        self.date_combo.set_active(0)
        self.date_combo.set_tooltip_text("Modified during this time period")
        self.date_combo.connect("changed", self.on_date_changed)
        self.range_btn = Gtk.Button()
        self.range_btn.set_tooltip_text("Change the time period")
        self.range_btn.connect("clicked", lambda *_: self.pick_range())
        self.range_btn.set_no_show_all(True)
        self.scope_combo = Gtk.ComboBoxText()
        for s in SCOPES:
            self.scope_combo.append_text(s)
        self.scope_combo.set_active(0)
        self.scope_combo.set_tooltip_text("Where to look: this folder only, every folder inside it, "
                                          "or your whole home folder (instant, uses the index)")
        self.scope_combo.connect("changed", self.on_filters_changed)
        for w in (self.search, self.kind_combo, self.ext_entry, self.date_combo, self.range_btn, self.scope_combo):
            flow.add(w)
        for child in flow.get_children():
            child.set_can_focus(False)
        self.range_btn.get_parent().set_no_show_all(True)
        self.add(flow)

        # list view
        self.tree = Gtk.TreeView(enable_search=False, rubber_banding=False)   # press-and-drag = drag files
        self.tree.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        self.tree.get_selection().connect("changed", self.on_selection_changed)
        self.tree.connect("row-activated", lambda t, p, c: self.activate_row(p))
        self.tree.connect("button-press-event", self.on_view_click)
        col = Gtk.TreeViewColumn("Name")
        icon_r = Gtk.CellRendererPixbuf()
        self.icon_renderer = icon_r
        icon_r.set_property("stock-size", icon_size("row") if ICON_STYLE["colour"] else Gtk.IconSize.LARGE_TOOLBAR)
        col.pack_start(icon_r, False)
        col.add_attribute(icon_r, "gicon", C_ICON)
        text_r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(text_r, True)
        col.add_attribute(text_r, "text", C_NAME)
        col.set_expand(True)
        col.set_resizable(True)
        col.set_min_width(180)
        col.set_sort_column_id(C_NAME)
        self.tree.append_column(col)
        tag_r = Gtk.CellRendererText()
        tag_col = Gtk.TreeViewColumn("Tags", tag_r, markup=C_TAGS)
        tag_col.set_resizable(True)
        self.tree.append_column(tag_col)
        self.col_time = self._text_col("Modified", C_MTIMETXT, C_MTIME)
        self._text_col("Size", C_SIZETXT, C_SIZE, xalign=1.0)
        self._text_col("Type", C_KIND, C_KIND)
        self.col_where = self._text_col("Location", C_WHERE, C_WHERE)
        list_scroll = Gtk.ScrolledWindow()
        list_scroll.add(self.tree)
        self.vadj = list_scroll.get_vadjustment()

        # thumbnail grid view
        self.icons = Gtk.IconView(item_width=110, column_spacing=4, row_spacing=4, margin=8)
        self.icons.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        pix_r = Gtk.CellRendererPixbuf()
        self.tile_renderer = pix_r
        pix_r.set_property("stock-size", icon_size("tile") if ICON_STYLE["colour"] else Gtk.IconSize.DIALOG)
        pix_r.set_fixed_size(100, 100)
        self.icons.pack_start(pix_r, False)
        self.icons.set_cell_data_func(pix_r, self._grid_icon)
        name_r = Gtk.CellRendererText(wrap_mode=Pango.WrapMode.WORD_CHAR, wrap_width=100,
                                      alignment=Pango.Alignment.CENTER, xalign=0.5)
        self.icons.pack_start(name_r, False)
        self.icons.set_cell_data_func(name_r, self._grid_name)
        self.icons.connect("selection-changed", self.on_selection_changed)
        self.icons.connect("item-activated", lambda v, p: self.activate_row(p))
        self.icons.connect("button-press-event", self.on_view_click)
        grid_scroll = Gtk.ScrolledWindow()
        grid_scroll.add(self.icons)
        self.gadj = grid_scroll.get_vadjustment()

        self.view_stack = Gtk.Stack(vexpand=True)
        self.view_stack.add_named(list_scroll, "list")
        self.view_stack.add_named(grid_scroll, "grid")
        self.pack_start(self.view_stack, True, True, 0)
        self.status = Gtk.Label(xalign=0, margin=5, ellipsize=Pango.EllipsizeMode.END)
        self.status.get_style_context().add_class("dim-label")
        self.add(self.status)
        self._setup_dnd()
        self.connect("map", lambda *_: self.view_stack.set_visible_child_name(self.view_mode))

    # ---------- drag and drop
    def _setup_dnd(self):
        targets = [Gtk.TargetEntry.new("text/uri-list", 0, 0)]
        actions = Gdk.DragAction.MOVE | Gdk.DragAction.COPY
        self.tree.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets, actions)
        self.tree.enable_model_drag_dest(targets, actions)
        self.icons.enable_model_drag_source(Gdk.ModifierType.BUTTON1_MASK, targets, actions)
        self.icons.enable_model_drag_dest(targets, actions)
        for view in (self.tree, self.icons):
            view.connect("drag-data-get", self.on_drag_get)
            view.connect("drag-data-received", self.on_drag_received)
            view.connect("drag-drop", self.on_drag_drop)
            view.connect("drag-begin", self.on_drag_begin)

    def on_drag_begin(self, view, context):
        n = len(self.selected_paths())
        Gtk.drag_set_icon_name(context, "folder-documents" if n > 1 else "text-x-generic", 0, 0)

    def on_drag_get(self, view, context, selection, info, time_):
        uris = [Gio.File.new_for_path(p).get_uri() for p in self.selected_paths()]
        selection.set_uris(uris)

    def drop_target(self, view, x, y):
        """The folder under the pointer, or this pane's folder."""
        if view is self.tree:
            hit = self.tree.get_dest_row_at_pos(x, y)
            if hit and hit[1] in (Gtk.TreeViewDropPosition.INTO_OR_BEFORE, Gtk.TreeViewDropPosition.INTO_OR_AFTER):
                row = self.sorted[hit[0]]
                if row[C_ISDIR]:
                    return row[C_PATH]
        else:
            hit = self.icons.get_dest_item_at_pos(x, y)
            if hit:
                row = self.sorted[hit[0]]
                if row[C_ISDIR]:
                    return row[C_PATH]
        return self.location if self.mode == "folder" else None

    def on_drag_drop(self, view, context, x, y, time_):
        view.stop_emission_by_name("drag-drop")            # sorted lists can't take rows; ask for the files instead
        view.drag_get_data(context, Gdk.Atom.intern("text/uri-list", False), time_)
        return True

    def on_drag_received(self, view, context, x, y, selection, info, time_):
        view.stop_emission_by_name("drag-data-received")      # we handle it; don't let GTK reorder rows
        dest = self.drop_target(view, x, y)
        paths = [Gio.File.new_for_uri(u).get_path() for u in (selection.get_uris() or [])]
        paths = [p for p in paths if p]
        internal = Gtk.drag_get_source_widget(context) is not None
        mods = Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_modifier_state()
        ok = self.win.handle_drop(paths, dest, internal, bool(mods & Gdk.ModifierType.CONTROL_MASK),
                                  bool(mods & Gdk.ModifierType.SHIFT_MASK))
        Gtk.drag_finish(context, ok, False, time_)

    def apply_icon_style(self):
        colour = ICON_STYLE["colour"]
        self.icon_renderer.set_property("stock-size", icon_size("row") if colour else Gtk.IconSize.LARGE_TOOLBAR)
        self.tile_renderer.set_property("stock-size", icon_size("tile") if colour else Gtk.IconSize.DIALOG)
        self.tree.columns_autosize()
        self.refresh()

    def _text_col(self, title, text_col, sort_col, xalign=0.0):
        r = Gtk.CellRendererText(xalign=xalign, ellipsize=Pango.EllipsizeMode.END)
        col = Gtk.TreeViewColumn(title, r, text=text_col)
        col.set_resizable(True)
        col.set_sort_column_id(sort_col)
        col.set_min_width(80)
        self.tree.append_column(col)
        return col

    def _grid_icon(self, layout, cell, model, it, *_):
        thumb = model[it][C_THUMB]
        if thumb is not None:
            cell.set_property("pixbuf", thumb)
        else:
            cell.set_property("gicon", model[it][C_ICON])

    def _grid_name(self, layout, cell, model, it, *_):
        name = model[it][C_NAME]
        cell.set_property("text", name if len(name) <= 34 else name[:20] + "…" + name[-12:])

    # ---------- titles
    def title(self):
        loc = self.location or ""
        if loc == "recent":
            return "Recent files"
        if loc == "notes":
            return "Files with notes"
        if loc.startswith("tag:"):
            return "Tag: " + loc[4:]
        return "Home" if Path(loc) == HOME else root_label(Path(loc))

    # ---------- navigation
    def go(self, location, push=True):
        location = str(location)
        if is_folder_loc(location) and not os.path.isdir(location):
            self.win.error(f"Folder not found: {location}")
            return
        if push and self.location and location != self.location:
            self.back_stack.append(self.location)
            self.fwd_stack.clear()
        self.location = location
        self.search.handler_block_by_func(self.on_filters_changed)
        self.search.set_text("")
        self.search.handler_unblock_by_func(self.on_filters_changed)
        self.read_filters()
        self.load_location()

    def go_back(self):
        if self.back_stack:
            self.fwd_stack.append(self.location)
            self.go(self.back_stack.pop(), push=False)

    def go_forward(self):
        if self.fwd_stack:
            self.back_stack.append(self.location)
            self.go(self.fwd_stack.pop(), push=False)

    def go_up(self):
        if is_folder_loc(self.location) and not is_root(self.location):
            self.pending_select = [self.location]
            self.go(str(Path(self.location).parent))

    def load_location(self):
        self.back_btn.set_sensitive(bool(self.back_stack))
        self.fwd_btn.set_sensitive(bool(self.fwd_stack))
        self.up_btn.set_sensitive(is_folder_loc(self.location) and not is_root(self.location))
        self.update_breadcrumb()
        self.win.pane_location_changed(self)
        if self.wants_search():
            self.start_search()
        else:
            self.load_base()

    def load_base(self):
        loc, hidden = self.location, self.win.cfg["show_hidden"]
        if loc == "recent":
            self._load("recent", lambda: [stat_row(str(p), ts) for ts, p in recent_activity()])
        elif loc == "notes":
            self._load("notes", lambda: [stat_row(p) for p in TAG_STORE.with_notes()])
        elif loc.startswith("tag:"):
            self._load("tag", lambda: [stat_row(p) for p in TAG_STORE.with_tag(loc[4:])])
        else:
            def produce():
                rows = []
                with os.scandir(loc) as it:
                    for e in it:
                        try:
                            st = e.stat()
                            if not hidden and is_hidden(e.name, st):
                                continue
                            rows.append(make_row(e.path, e.is_dir(), st.st_size, st.st_mtime))
                        except OSError:
                            continue
                return rows
            self._load("folder", produce, watch=loc)

    def update_breadcrumb(self):
        for c in self.crumbs.get_children():
            self.crumbs.remove(c)
        if not is_folder_loc(self.location):
            parts = [(self.title(), self.location)]
        else:
            path = Path(self.location)
            chain = [path] + list(path.parents)
            if path == HOME or HOME in path.parents:
                chain = chain[:chain.index(HOME) + 1]
            parts = [("Home" if p == HOME else root_label(p), str(p)) for p in reversed(chain)]
        for i, (label, target) in enumerate(parts):
            if i:
                self.crumbs.add(Gtk.Label(label="›", margin_start=1, margin_end=1))
            b = Gtk.Button(label=label, relief=Gtk.ReliefStyle.NONE)
            b.connect("clicked", lambda _b, t=target: self.go(t))
            if i == len(parts) - 1:
                b.get_child().set_markup(f"<b>{esc(label)}</b>")
            self.crumbs.add(b)
        self.crumbs.show_all()
        adj = self.crumb_scroll.get_hadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()) and False)

    def edit_path(self):
        self.path_entry.set_text(self.location if is_folder_loc(self.location) else "")
        self.path_stack.set_visible_child_name("entry")
        self.path_entry.grab_focus()

    def on_path_entered(self, entry):
        p = Path(os.path.expanduser(entry.get_text().strip()))
        self.path_stack.set_visible_child_name("crumbs")
        if p.is_dir():
            self.go(str(p))
        elif p.is_file():
            self.show_in_folder(str(p))
        else:
            self.win.error(f"No such folder: {p}")

    # ---------- filters
    def read_filters(self):
        choice = DATE_CHOICES[self.date_combo.get_active()][1]
        start = end = None
        if choice == "today":
            start = datetime.combine(date.today(), datetime.min.time()).timestamp()
        elif isinstance(choice, int):
            start = time.time() - choice * 86400
        elif choice == "custom" and self.custom_range:
            start, end = self.custom_range[0], self.custom_range[1]
        self.filters = Filters(self.search.get_text().strip().lower(), self.kind_combo.get_active_text(),
                               parse_exts(self.ext_entry.get_text()), start, end)

    def wants_search(self):
        scope = self.scope_combo.get_active()
        return self.filters.active and (scope == 2 or (scope == 1 and is_folder_loc(self.location)))

    def on_ext_changed(self, *_):
        if self.ext_timer:
            GLib.source_remove(self.ext_timer)
        self.ext_timer = GLib.timeout_add(350, self._ext_settled)

    def _ext_settled(self):
        self.ext_timer = None
        self.on_filters_changed()
        return False

    def on_date_changed(self, combo):
        idx = combo.get_active()
        if DATE_CHOICES[idx][1] == "custom":
            if not self.pick_range():
                combo.handler_block_by_func(self.on_date_changed)
                combo.set_active(self.date_idx)
                combo.handler_unblock_by_func(self.on_date_changed)
                return
        else:
            self.range_btn.hide()
            self.range_btn.get_parent().hide()
        self.date_idx = idx
        self.on_filters_changed()

    def pick_range(self):
        result = ask_date_range(self.win, self.custom_range)
        if not result:
            return False
        self.custom_range = result
        self.range_btn.set_label("📅 " + result[2])
        self.range_btn.get_parent().show()
        self.range_btn.show()
        if self.date_idx == len(DATE_CHOICES) - 1:
            self.on_filters_changed()
        return True

    def on_filters_changed(self, *_):
        self.read_filters()
        if self.wants_search():
            self.start_search()
        elif self.mode == "search":
            self.load_base()
        elif self.filter is not None:
            self.filter.refilter()
            self.update_status()

    def clear_filters(self):
        for w, h in ((self.kind_combo, self.on_filters_changed), (self.scope_combo, self.on_filters_changed)):
            w.handler_block_by_func(h)
            w.set_active(0)
            w.handler_unblock_by_func(h)
        self.date_combo.handler_block_by_func(self.on_date_changed)
        self.date_combo.set_active(0)
        self.date_combo.handler_unblock_by_func(self.on_date_changed)
        self.date_idx = 0
        self.range_btn.hide()
        self.range_btn.get_parent().hide()
        self.ext_entry.set_text("")
        self.search.set_text("")
        self.on_filters_changed()

    # ---------- loading (always off the UI thread)
    def _load(self, mode, producer, watch=None):
        self.mode = mode
        self.gen += 1
        gen = self.gen
        self.watch(watch)
        self.set_busy(True)
        if mode != "folder":
            self.set_rows([])
            self.status.set_text("Loading…")

        def work():
            try:
                rows, err = producer(), None
            except OSError as ex:
                rows, err = [], ex.strerror or str(ex)
            GLib.idle_add(self.finish_load, gen, rows, err)
        threading.Thread(target=work, daemon=True).start()

    def start_search(self):
        scope = self.scope_combo.get_active()
        root = self.location if (scope == 1 and is_folder_loc(self.location)) else None
        self.mode = "search"
        self.gen += 1
        gen, f, hidden = self.gen, self.filters, self.win.cfg["show_hidden"]
        self.watch(None)
        self.set_busy(True)
        self.set_rows([])
        where = short(root) if root else "your whole home folder"
        self.status.set_text(f"Searching {where}…")
        in_home = root is None or root == str(HOME) or root.startswith(str(HOME) + os.sep)
        use_index = INDEX.available() and in_home and not hidden

        def work():
            if use_index:
                rows = INDEX.query(f, root)
                if rows is not None:
                    out = [make_row(p, d, s, m) for p, d, s, m in rows if os.path.exists(p)]
                    note = f"instant search · index updated {ago(INDEX.updated)}"
                    GLib.idle_add(self.append_rows, gen, out, True, note)
                    if not INDEX.fresh():
                        GLib.idle_add(lambda: INDEX.rebuild() or False)
                    return
            batch, found, last = [], 0, time.time()
            for p, st, is_dir in walk_entries(Path(root) if root else HOME, hidden):
                if gen != self.gen:
                    return
                name = p.name
                kind = "Folder" if is_dir else category_of(name)
                if not f.match(name, is_dir, kind, st.st_mtime, TAG_STORE.note(p) if f.query else ""):
                    continue
                batch.append(make_row(p, is_dir, st.st_size, st.st_mtime))
                found += 1
                if len(batch) >= 200 or time.time() - last > 0.3:
                    GLib.idle_add(self.append_rows, gen, batch, False, "searching…")
                    batch, last = [], time.time()
                if found >= 5000:
                    break
            GLib.idle_add(self.append_rows, gen, batch, True, "search finished")
        threading.Thread(target=work, daemon=True).start()

    def set_busy(self, on):
        self.busy = on
        self.win.update_spinner()

    def finish_load(self, gen, rows, err):
        if gen != self.gen:
            return False
        self.set_busy(False)
        if err:
            self.set_rows([])
            self.status.set_text(f"Can't open this folder: {err}")
            return False
        self.set_rows(rows)
        if self.pending_select:
            self.select_paths(self.pending_select)
            self.pending_select = None
        if self.pending_scroll is not None:
            value, adj = self.pending_scroll, (self.gadj if self.view_mode == "grid" else self.vadj)
            GLib.idle_add(lambda: adj.set_value(value) and False)
            self.pending_scroll = None
        self.update_status()
        self.load_thumbs()
        return False

    def append_rows(self, gen, rows, done, note=""):
        if gen != self.gen or self.store is None:
            return False
        for r in rows:
            self.iters[r[C_PATH]] = self.store.append(r)
        if done:
            self.set_busy(False)
            self.load_thumbs()
        self.update_status(note)
        return False

    def set_rows(self, rows):
        self.store = Gtk.ListStore(*COLUMN_TYPES)
        self.iters = {}
        for r in rows:
            self.iters[r[C_PATH]] = self.store.append(r)
        self.filter = self.store.filter_new()
        self.filter.set_visible_func(self.visible)
        self.sorted = Gtk.TreeModelSort(model=self.filter)
        for cid in (C_NAME, C_MTIME, C_SIZE, C_KIND, C_WHERE):
            self.sorted.set_sort_func(cid, self.sort_func, cid)
        self.sorted.set_sort_column_id(*self.sort["folder" if self.mode == "folder" else "other"])
        self.sorted.connect("sort-column-changed", self.on_sort_changed)
        self.attach_model()
        self.col_where.set_visible(self.mode != "folder")
        self.col_time.set_title("Last used" if self.mode == "recent" else "Modified")
        self.win.on_selection(self)

    def attach_model(self):
        # only the visible view holds the model (avoids GTK ref-count warnings on refilter)
        grid = self.view_mode == "grid"
        self.tree.set_model(None if grid else self.sorted)
        self.icons.set_model(self.sorted if grid else None)

    def on_sort_changed(self, model):
        col, order = model.get_sort_column_id()
        if col is not None:
            self.sort["folder" if self.mode == "folder" else "other"] = (col, order)

    def sort_func(self, model, a, b, col):
        da, db = model[a][C_ISDIR], model[b][C_ISDIR]
        if da != db:   # folders first, whichever direction
            res = -1 if da else 1
            _, order = self.sorted.get_sort_column_id() if self.sorted else (None, Gtk.SortType.ASCENDING)
            return -res if order == Gtk.SortType.DESCENDING else res
        va, vb = model[a][col], model[b][col]
        if isinstance(va, str):
            va, vb = va.casefold(), vb.casefold()
        if va == vb and col != C_NAME:
            va, vb = model[a][C_NAME].casefold(), model[b][C_NAME].casefold()
        return (va > vb) - (va < vb)

    def visible(self, model, it, _data):
        if self.mode == "search":
            return True
        r = model[it]
        note = TAG_STORE.note(r[C_PATH]) if self.filters.query else ""
        return self.filters.match(r[C_NAME], r[C_ISDIR], r[C_KIND], r[C_MTIME], note)

    # ---------- thumbnails
    def load_thumbs(self):
        if self.view_mode != "grid" or self.store is None:
            return
        gen = self.gen
        paths = [r[C_PATH] for r in self.store
                 if not r[C_ISDIR] and r[C_THUMB] is None and r[C_KIND] in THUMB_KINDS][:2000]
        if not paths:
            return

        def work():
            for p in paths:
                if gen != self.gen or self.view_mode != "grid":
                    return
                pb = thumbnail_for(p, 96)
                if pb:
                    GLib.idle_add(self.set_thumb, gen, p, pb)
        threading.Thread(target=work, daemon=True).start()

    def set_thumb(self, gen, path, pb):
        if gen == self.gen and path in self.iters:
            self.store.set_value(self.iters[path], C_THUMB, pb)
        return False

    def set_view(self, mode):
        if mode == self.view_mode:
            return
        keep = self.selected_paths()
        self.view_mode = mode
        self.attach_model()
        self.view_stack.set_visible_child_name(mode)
        (self.grid_btn if mode == "grid" else self.list_btn).set_active(True)
        self.win.cfg["view"] = mode
        if keep:
            self.select_paths(keep)
        self.load_thumbs()

    # ---------- auto refresh when the folder changes on disk
    def watch(self, folder):
        if self.monitor:
            self.monitor.cancel()
            self.monitor = None
        if folder:
            try:
                self.monitor = Gio.File.new_for_path(folder).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                self.monitor.connect("changed", self.on_folder_changed)
            except GLib.Error:
                self.monitor = None

    def on_folder_changed(self, *_):
        if self.refresh_id is None:
            self.refresh_id = GLib.timeout_add(600, self.auto_refresh)

    def auto_refresh(self):
        self.refresh_id = None
        if self.mode == "folder":
            self.refresh()
        return False

    def refresh(self):
        if not self.pending_select:
            self.pending_select = self.selected_paths()
        self.pending_scroll = (self.gadj if self.view_mode == "grid" else self.vadj).get_value()
        self.load_location()

    def cleanup(self):
        self.gen += 1
        self.watch(None)

    def refresh_tags(self, paths):
        if self.mode == "tag" or self.mode == "notes":
            self.refresh()
            return
        for p in paths:
            it = self.iters.get(p)
            if it is not None:
                self.store.set_value(it, C_TAGS, TAG_STORE.markup(p))

    # ---------- selection
    def selected_paths(self):
        if self.view_mode == "grid":
            model = self.icons.get_model()
            return [model[p][C_PATH] for p in self.icons.get_selected_items()] if model else []
        model, paths = self.tree.get_selection().get_selected_rows()
        return [model[p][C_PATH] for p in paths]

    def select_paths(self, wanted):
        if self.sorted is None:
            return
        wanted = set(wanted)
        grid = self.view_mode == "grid"
        rows = [row.path for row in self.sorted if row[C_PATH] in wanted]
        sel = self.tree.get_selection()
        self.icons.unselect_all()
        sel.unselect_all()
        if not rows:
            return
        # moving the cursor resets the selection, so do it first, then select every row
        if grid:
            self.icons.set_cursor(rows[0], None, False)
            self.icons.scroll_to_path(rows[0], True, 0.3, 0.0)
        else:
            self.tree.set_cursor(rows[0], None, False)
            self.tree.scroll_to_cell(rows[0], None, True, 0.3, 0.0)
        for path in rows:
            (self.icons.select_path if grid else sel.select_path)(path)

    def on_selection_changed(self, *_):
        self.update_status()
        self.win.on_selection(self)

    def update_status(self, extra=""):
        if self.sorted is None:
            return
        n, total = len(self.sorted), len(self.store)
        text = f"{n} item{'s' if n != 1 else ''}"
        if self.mode != "search" and n != total:
            text += f" (filtered from {total})"
        sel = self.selected_paths()
        if sel:
            size = sum(self.store[self.iters[p]][C_SIZE] for p in sel if p in self.iters)
            text += f"  ·  {len(sel)} selected ({human_size(size)})"
        if self.mode == "folder":
            loose = sum(1 for r in self.store if not r[C_ISDIR])
            if loose >= CLUTTER_LIMIT:
                text += f"  ·  {loose} loose files here, try Organize"
        msg, until = getattr(self, "flash_msg", ("", 0))
        if msg and time.time() < until and msg != extra:
            text += f"  ·  {msg}"
        if extra:
            text += f"  ·  {extra}"
        self.status.set_text(text)
        if self is self.win.active:
            self.win.update_organize_hint()

    def flash(self, message):
        self.flash_msg = (message, time.time() + 6)      # stays visible through a refresh
        self.update_status()

    # ---------- actions
    def activate_row(self, tree_path):
        row = self.sorted[tree_path]
        if row[C_ISDIR]:
            self.go(row[C_PATH])
        else:
            self.win.open_file(row[C_PATH])

    def show_in_folder(self, path):
        parent = str(Path(path).parent)
        if parent == self.location and self.mode == "folder":
            self.select_paths([path])
        else:
            self.pending_select = [path]
            self.go(parent)

    def on_view_click(self, view, event):
        if event.type != Gdk.EventType.BUTTON_PRESS:
            return False
        if event.button == 2:          # middle click a folder: open in new tab
            hit = self._path_at(view, event)
            if hit is not None and self.sorted[hit][C_ISDIR]:
                self.win.new_tab(location=self.sorted[hit][C_PATH], switch=False)
                return True
            return False
        if event.button != 3:
            return False
        hit = self._path_at(view, event)
        if view is self.tree:
            sel = self.tree.get_selection()
            if hit is None:
                sel.unselect_all()
            elif not sel.path_is_selected(hit):
                sel.unselect_all()
                sel.select_path(hit)
        else:
            if hit is None:
                self.icons.unselect_all()
            elif not self.icons.path_is_selected(hit):
                self.icons.unselect_all()
                self.icons.select_path(hit)
        self.win.set_active(self)
        self.context_menu(event)
        return True

    def _path_at(self, view, event):
        if view is self.tree:
            hit = self.tree.get_path_at_pos(int(event.x), int(event.y))
            return hit[0] if hit else None
        return self.icons.get_path_at_pos(int(event.x), int(event.y))

    def context_menu(self, event):
        paths = self.selected_paths()
        win = self.win
        menu = Gtk.Menu()

        def add(label, cb, sensitive=True, parent=menu):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda *_: cb())
            item.set_sensitive(sensitive)
            parent.append(item)
            return item

        in_folder = self.mode == "folder"
        other = win.other_pane()
        if paths:
            first = paths[0]
            is_dir = os.path.isdir(first)
            add("Open", lambda: self.go(first) if is_dir else win.open_file(first))
            if is_dir:
                add("Open in new tab", lambda: win.new_tab(location=first, switch=False))
                add("Open in other pane", lambda: win.open_in_other(first), other is not None)
            else:
                add("Open with…", lambda: win.open_with(first))
            if all(archive_kind(p) for p in paths) and self.mode == "folder":
                add("Extract here", lambda: win.extract(self, paths, self.location))
                add("Extract to…", lambda: win.extract_to(self, paths))
            elif all(archive_kind(p) for p in paths):
                add("Extract next to the archive", lambda: win.extract(self, paths, None))
                add("Extract to…", lambda: win.extract_to(self, paths))
            add("Compress…", lambda: win.compress(self, paths))
            if not in_folder:
                add("Show in folder", lambda: self.show_in_folder(first))
            menu.append(Gtk.SeparatorMenuItem())
            tag_item = Gtk.MenuItem(label="Tags")
            sub = Gtk.Menu()
            common = set.intersection(*[set(TAG_STORE.tags(p)) for p in paths])
            for tag, color in TAGS.items():
                ci = Gtk.CheckMenuItem()
                lbl = Gtk.Label(xalign=0)
                lbl.set_markup(f'<span foreground="{color}">●</span>  {esc(tag)}')
                ci.add(lbl)
                ci.set_active(tag in common)
                ci.connect("toggled", lambda w, t=tag: win.toggle_tag(paths, t, w.get_active()))
                sub.append(ci)
            sub.append(Gtk.SeparatorMenuItem())
            add("Write a note…", lambda: win.edit_note(first), len(paths) == 1, parent=sub)
            tag_item.set_submenu(sub)
            menu.append(tag_item)
            add("Compare these two…", lambda: win.compare(paths[0], paths[1]), len(paths) == 2)
            add("Send to nearby Arckad-D…", lambda: win.open_share(paths, "nearby"))
            add("Share as link / QR code…", lambda: win.open_share(paths, "link"))
            menu.append(Gtk.SeparatorMenuItem())
            add("Copy (Ctrl+C)", lambda: win.set_clipboard(paths, False))
            add("Cut (Ctrl+X)", lambda: win.set_clipboard(paths, True))
            if other is not None and is_folder_loc(other.location):
                add(f"Copy to other pane ({other.title()})", lambda: win.transfer(paths, False, other.location))
                add(f"Move to other pane ({other.title()})", lambda: win.transfer(paths, True, other.location))
            if is_dir:
                add("Pin to sidebar", lambda: win.pin(first))
                for item in win.terminal_menu_items(first):
                    menu.append(item)
            add("Rename… (F2)", lambda: win.rename(self, first), len(paths) == 1)
            add("Duplicate", lambda: win.duplicate(self, paths))
            add("Send to chat 💬", lambda: win.send_to_chat(paths))
            add("Copy path", lambda: win.copy_text("\n".join(paths)))
            add("Properties (Alt+Enter)", lambda: win.properties(paths))
            menu.append(Gtk.SeparatorMenuItem())
            add("New folder… (Ctrl+Shift+N)", lambda: win.new_folder(self), in_folder)
            add("New empty file…", lambda: win.new_file(self), in_folder)
            menu.append(Gtk.SeparatorMenuItem())
            add("Move to Trash (Delete)", lambda: win.trash(self, paths))
            add("Delete permanently (Shift+Delete)", lambda: win.delete_forever(self, paths))
        else:
            add("Paste (Ctrl+V)", lambda: win.paste_into(self), in_folder and win.clipboard is not None)
            add("New folder… (Ctrl+Shift+N)", lambda: win.new_folder(self), in_folder)
            add("New empty file…", lambda: win.new_file(self), in_folder)
            for item in win.terminal_menu_items(self.location):
                item.set_sensitive(in_folder)
                menu.append(item)
            add("Properties of this folder", lambda: win.properties([self.location]), in_folder)
            menu.append(Gtk.SeparatorMenuItem())
            add("Organize this folder…", lambda: win.organize(self), in_folder)
            add("Find duplicates here…", lambda: win.duplicates(self.location), in_folder)
            add("Pin this folder", lambda: win.pin(self.location), in_folder)
            add("Clear all filters", self.clear_filters, self.filters.active)
            add("Refresh (F5)", self.refresh)
        menu.show_all()
        menu.attach_to_widget(self, None)
        menu.popup_at_pointer(event)

    def handle_key(self, key, ctrl, alt, typing):
        low = key.lower()
        if ctrl and low == "f":
            self.search.grab_focus()
        elif ctrl and low == "l":
            self.edit_path()
        elif key == "F5":
            self.refresh()
        elif key == "F4":
            sel = [p for p in self.selected_paths() if os.path.isdir(p)]
            folder = sel[0] if len(sel) == 1 else (self.location if is_folder_loc(self.location) else str(HOME))
            self.win.open_terminal(folder)
        elif (alt and key == "Left") or (key == "BackSpace" and not typing):
            self.go_back()
        elif alt and key == "Right":
            self.go_forward()
        elif alt and key == "Up":
            self.go_up()
        elif key == "Escape" and self.path_stack.get_visible_child_name() == "entry":
            self.path_stack.set_visible_child_name("crumbs")
        elif ctrl and key in ("N", "n") and bool(Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_modifier_state()
                                                       & Gdk.ModifierType.SHIFT_MASK):
            self.win.new_folder(self)
        elif ctrl and low == "a" and not typing:
            (self.icons.select_all if self.view_mode == "grid" else self.tree.get_selection().select_all)()
        elif alt and key in ("Return", "KP_Enter") and not typing:
            self.win.properties(self.selected_paths() or ([self.location] if self.mode == "folder" else []))
        elif key == "Delete" and not typing and self.selected_paths():
            if Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_modifier_state() & Gdk.ModifierType.SHIFT_MASK:
                self.win.delete_forever(self, self.selected_paths())
            else:
                self.win.trash(self, self.selected_paths())
        elif key == "F2" and not typing and len(self.selected_paths()) == 1:
            self.win.rename(self, self.selected_paths()[0])
        else:
            return False
        return True


# ---------------------------------------------------------------- date range picker
def ask_date_range(parent, initial=None):
    dlg = Gtk.Dialog(title="Choose a time period", transient_for=parent, modal=True)
    dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Apply", Gtk.ResponseType.OK)
    dlg.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
    box = dlg.get_content_area()
    box.set_spacing(10)
    box.set_border_width(12)
    box.add(Gtk.Label(label="Show files modified between these dates (both days included):", xalign=0))
    quick = Gtk.Box(spacing=4)
    quick.get_style_context().add_class("linked")
    box.add(quick)
    cals = Gtk.Box(spacing=16, homogeneous=True)
    c_from, c_to = Gtk.Calendar(), Gtk.Calendar()
    for title, cal in (("From", c_from), ("To", c_to)):
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>{title}</b>")
        col.add(lbl)
        col.add(cal)
        cals.add(col)
    box.add(cals)

    def set_cal(cal, d):
        cal.select_month(d.month - 1, d.year)
        cal.select_day(d.day)

    def get_cal(cal):
        y, m, d = cal.get_date()
        return date(y, m + 1, d)

    today = date.today()
    if initial:
        set_cal(c_from, date.fromtimestamp(initial[0]))
        set_cal(c_to, date.fromtimestamp(initial[1]) - timedelta(days=1))
    else:
        set_cal(c_from, today - timedelta(days=7))
        set_cal(c_to, today)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    last_month_end = month_start - timedelta(days=1)
    presets = [("This week", week_start, today),
               ("Last week", week_start - timedelta(days=7), week_start - timedelta(days=1)),
               ("This month", month_start, today),
               ("Last month", last_month_end.replace(day=1), last_month_end),
               ("This year", today.replace(month=1, day=1), today)]
    for label, a, b in presets:
        btn = Gtk.Button(label=label)
        btn.connect("clicked", lambda _b, a=a, b=b: (set_cal(c_from, a), set_cal(c_to, b)))
        quick.add(btn)
    dlg.show_all()
    resp = dlg.run()
    a, b = get_cal(c_from), get_cal(c_to)
    dlg.destroy()
    if resp != Gtk.ResponseType.OK:
        return None
    if a > b:
        a, b = b, a
    start = datetime.combine(a, datetime.min.time()).timestamp()
    end = datetime.combine(b + timedelta(days=1), datetime.min.time()).timestamp()
    fmt = "%d %b" if a.year == b.year == today.year else "%d %b %Y"
    label = a.strftime(fmt) if a == b else f"{a.strftime(fmt)} – {b.strftime(fmt)}"
    return (start, end, label)


# ---------------------------------------------------------------- quick preview panel
class PreviewPanel(Gtk.ScrolledWindow):
    WIDTH = 300

    def __init__(self, win):
        super().__init__()
        self.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.set_size_request(self.WIDTH + 24, -1)
        self.get_style_context().add_class("fm-preview")
        self.win = win
        self.path = None
        self.token = 0
        self.note_timer = None
        self.updating = False

        self.pages = Gtk.Stack()
        self.add(self.pages)
        empty = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin=20)
        empty.set_markup("<big>👀</big>\n\nSelect a file to preview it here.\n\n"
                         "<small>Press <b>Space</b> to show or hide this panel.</small>")
        empty.get_style_context().add_class("dim-label")
        self.pages.add_named(empty, "empty")
        self.multi = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin=20)
        self.pages.add_named(self.multi, "multi")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=12)
        self.pages.add_named(box, "file")
        self.visual = Gtk.Stack()
        self.visual.set_size_request(-1, 220)
        self.image = Gtk.Image()
        self.visual.add_named(self.image, "image")
        self.textview = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                                     left_margin=6, right_margin=6, top_margin=6)
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_size_request(-1, 260)
        text_scroll.add(self.textview)
        frame = Gtk.Frame()
        frame.add(text_scroll)
        self.visual.add_named(frame, "text")
        box.add(self.visual)

        self.name = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.name.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        box.add(self.name)
        self.info = Gtk.Grid(column_spacing=10, row_spacing=3)
        box.add(self.info)

        btns = Gtk.Box(spacing=6)
        self.open_btn = Gtk.Button(label="Open")
        self.open_btn.connect("clicked", lambda *_: self.path and self.win.open_path(self.path))
        self.reveal_btn = Gtk.Button(label="Show in folder")
        self.reveal_btn.connect("clicked", lambda *_: self.path and self.win.active.show_in_folder(self.path))
        btns.add(self.open_btn)
        btns.add(self.reveal_btn)
        box.add(btns)

        box.add(self._heading("Tags"))
        tags = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=3,
                           column_spacing=4, row_spacing=4, homogeneous=True)
        self.tag_btns = {}
        for tag, color in TAGS.items():
            b = Gtk.ToggleButton()
            lbl = Gtk.Label()
            lbl.set_markup(f'<span foreground="{color}">●</span> {esc(tag)}')
            b.add(lbl)
            b.connect("toggled", self.on_tag_toggled, tag)
            self.tag_btns[tag] = b
            tags.add(b)
        for child in tags.get_children():
            child.set_can_focus(False)
        box.add(tags)

        box.add(self._heading("Note"))
        self.note = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=6, right_margin=6,
                                 top_margin=6, bottom_margin=6)
        self.note.get_buffer().connect("changed", self.on_note_changed)
        note_scroll = Gtk.ScrolledWindow()
        note_scroll.set_size_request(-1, 90)
        note_scroll.add(self.note)
        nframe = Gtk.Frame()
        nframe.add(note_scroll)
        box.add(nframe)
        hint = Gtk.Label(xalign=0, wrap=True)
        hint.set_markup("<small>Notes save automatically, and the filter box searches them too.</small>")
        hint.get_style_context().add_class("dim-label")
        box.add(hint)

    def _heading(self, text):
        lbl = Gtk.Label(xalign=0, margin_top=6)
        lbl.set_markup(f"<b>{esc(text)}</b>")
        return lbl

    # ---------- showing things
    def show_paths(self, paths):
        if len(paths) == 1:
            self.show_file(paths[0])
            return
        self.flush_note()
        self.path = None
        self.token += 1
        if not paths:
            self.pages.set_visible_child_name("empty")
            return
        size = 0
        for p in paths:
            try:
                if os.path.isfile(p):
                    size += os.path.getsize(p)
            except OSError:
                pass
        extra = ("\n\n<small>Right-click → <b>Compare these two…</b> to see how they differ.</small>"
                 if len(paths) == 2 else "")
        self.multi.set_markup(f"<big><b>{len(paths)} items selected</b></big>\n{human_size(size)} in files{extra}")
        self.pages.set_visible_child_name("multi")

    def show_file(self, path):
        if path != self.path:
            self.flush_note()
        self.path = path
        self.token += 1
        tok = self.token
        try:
            st = os.stat(path)
        except OSError:
            self.pages.set_visible_child_name("empty")
            return
        is_dir = statmod.S_ISDIR(st.st_mode)
        name = os.path.basename(path)
        self.name.set_markup(f"<big><b>{esc(name)}</b></big>")
        rows = [("Type", type_description(path, is_dir))]
        if not is_dir:
            rows.append(("Size", f"{human_size(st.st_size)}  ({st.st_size:,} bytes)"))
        rows += [("Modified", f"{fmt_full(st.st_mtime)}\n{ago(st.st_mtime)}"),
                 ("Location", short(os.path.dirname(path)))]
        self.set_info(rows)
        self.load_tags_and_note()
        self.image.set_from_gicon(icon_for(name, is_dir), Gtk.IconSize.DIALOG)
        self.image.set_pixel_size(128)
        self.visual.set_visible_child_name("image")
        self.pages.set_visible_child_name("file")

        def work():
            kind, data, extra = self.build_preview(path, is_dir)
            GLib.idle_add(self.apply_preview, tok, kind, data, extra)
        threading.Thread(target=work, daemon=True).start()

    def build_preview(self, path, is_dir):
        extra = []
        try:
            if is_dir:
                n = len(os.listdir(path))
                return "none", None, [("Contains", f"{n} item{'s' if n != 1 else ''}")]
            kind = category_of(path)
            if kind == "Images":
                info = GdkPixbuf.Pixbuf.get_file_info(path)
                if info and info[0]:
                    extra.append(("Dimensions", f"{info[1]} × {info[2]} px"))
                return "pixbuf", load_scaled(path, self.WIDTH, 360), extra
            if ext_of(path) == "pdf":
                pages = pdf_pages(path)
                if pages:
                    extra.append(("Pages", pages))
                pb = render_pdf(path, self.WIDTH) or cached_thumbnail(path, self.WIDTH)
                if not pb and not IS_WIN and not shutil.which("pdftoppm"):
                    extra.append(("Tip", "sudo apt install poppler-utils\nto see PDF pages here"))
                return "pixbuf", pb, extra
            if kind == "Videos":
                return "pixbuf", render_video(path, self.WIDTH) or cached_thumbnail(path, self.WIDTH), extra
            if is_text_file(path):
                text, cut = read_text(path, 60_000)
                lines = len(text.splitlines())
                extra.append(("Lines", f"{lines:,}{'+' if cut else ''}"))
                return "text", text, extra
            return "pixbuf", cached_thumbnail(path, self.WIDTH), extra
        except (OSError, GLib.Error):
            return "none", None, extra

    def apply_preview(self, tok, kind, data, extra):
        if tok != self.token:
            return False
        if kind == "pixbuf" and data is not None:
            self.image.set_from_pixbuf(data)
            self.visual.set_visible_child_name("image")
        elif kind == "text":
            self.textview.get_buffer().set_text(data)
            self.visual.set_visible_child_name("text")
        if extra:
            self.add_info(extra)
        return False

    def set_info(self, rows):
        for child in self.info.get_children():
            self.info.remove(child)
        self.info_rows = 0
        self.add_info(rows)

    def add_info(self, rows):
        for key, value in rows:
            k = Gtk.Label(xalign=1, yalign=0)
            k.set_markup(f"<small>{esc(key)}</small>")
            k.get_style_context().add_class("dim-label")
            v = Gtk.Label(label=value, xalign=0, wrap=True, selectable=True)
            v.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            v.set_max_width_chars(28)
            self.info.attach(k, 0, self.info_rows, 1, 1)
            self.info.attach(v, 1, self.info_rows, 1, 1)
            self.info_rows += 1
        self.info.show_all()

    # ---------- tags & note
    def load_tags_and_note(self):
        self.updating = True
        current = TAG_STORE.tags(self.path)
        for tag, b in self.tag_btns.items():
            b.set_active(tag in current)
        self.note.get_buffer().set_text(TAG_STORE.note(self.path))
        self.updating = False

    def on_tag_toggled(self, btn, tag):
        if not self.updating and self.path:
            self.win.toggle_tag([self.path], tag, btn.get_active())

    def on_note_changed(self, buf):
        if self.updating or not self.path:
            return
        if self.note_timer:
            GLib.source_remove(self.note_timer)
        self.note_timer = GLib.timeout_add(700, self.save_note, self.path)

    def save_note(self, path):
        self.note_timer = None
        buf = self.note.get_buffer()
        text = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)
        TAG_STORE.set_note(path, text)
        self.win.on_tags_changed([path], from_preview=True)
        return False

    def flush_note(self):
        if self.note_timer and self.path:
            GLib.source_remove(self.note_timer)
            self.save_note(self.path)

    def focus_note(self):
        self.note.grab_focus()

    def tags_changed(self, paths):
        if self.path in paths:
            self.load_tags_and_note()


# ---------------------------------------------------------------- "Where was I?" timeline
class TimelineWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Where was I?", transient_for=win)
        self.set_default_size(820, 600)
        self.win = win
        self.sessions = []
        hb = Gtk.HeaderBar(show_close_button=True, title="Where was I?",
                           subtitle="Your recent work, grouped into sessions")
        self.set_titlebar(hb)
        self.range = Gtk.ComboBoxText()
        for label in ("Last 3 days", "Last 7 days", "Last 30 days"):
            self.range.append_text(label)
        self.range.set_active(1)
        self.range.connect("changed", lambda *_: self.reload())
        hb.pack_start(self.range)
        self.reopen_btn = Gtk.Button(label="Reopen last session")
        self.reopen_btn.get_style_context().add_class("suggested-action")
        self.reopen_btn.set_tooltip_text("Open the files from your most recent work session again")
        self.reopen_btn.connect("clicked", self.reopen_last)
        hb.pack_end(self.reopen_btn)
        self.spinner = Gtk.Spinner()
        hb.pack_end(self.spinner)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(box)
        self.summary = Gtk.Label(xalign=0, wrap=True, margin=12)
        box.add(self.summary)
        self.store = Gtk.TreeStore(str, str, str, str)    # markup, when, folder, path
        self.view = Gtk.TreeView(model=self.store, enable_search=False)
        r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        c = Gtk.TreeViewColumn("What", r, markup=0)
        c.set_expand(True)
        self.view.append_column(c)
        for i, title in ((1, "When"), (2, "Folder")):
            rr = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.START if i == 2 else Pango.EllipsizeMode.NONE)
            cc = Gtk.TreeViewColumn(title, rr, text=i)
            cc.set_resizable(True)
            cc.set_min_width(170 if i == 1 else 200)
            self.view.append_column(cc)
        self.view.connect("row-activated", self.on_activated)
        self.view.connect("button-press-event", self.on_click)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(self.view)
        box.pack_start(scroll, True, True, 0)
        tip = Gtk.Label(xalign=0, margin=8)
        tip.set_markup("<small>Double-click a file to open it · right-click for Show in folder</small>")
        tip.get_style_context().add_class("dim-label")
        box.add(tip)
        self.reload()

    def reload(self):
        days = (3, 7, 30)[self.range.get_active()]
        self.spinner.start()
        self.summary.set_text("Looking through your recent work…")

        def work():
            sessions = build_sessions(recent_activity(days, limit=3000))
            GLib.idle_add(self.fill, sessions)
        threading.Thread(target=work, daemon=True).start()

    def fill(self, sessions):
        self.spinner.stop()
        self.sessions = sessions
        self.store.clear()
        self.reopen_btn.set_sensitive(bool(sessions))
        if not sessions:
            self.summary.set_text("No file activity found in this period.")
            return False
        days = OrderedDict()
        for s in sessions:
            days.setdefault(date.fromtimestamp(s[-1][0]), []).append(s)
        for d, sess_list in days.items():
            n = sum(len(s) for s in sess_list)
            day_it = self.store.append(None, [f"<b>{esc(day_label(d))}</b>",
                                              f"{len(sess_list)} session{'s' if len(sess_list) > 1 else ''}",
                                              f"{n} file{'s' if n > 1 else ''}", ""])
            for s in sess_list:
                folder = Counter(str(p.parent) for _, p in s).most_common(1)[0][0]
                s_it = self.store.append(day_it, [
                    f"{len(s)} file{'s' if len(s) > 1 else ''} · mostly in <i>{esc(short(folder))}</i>",
                    f"{fmt_clock(s[0][0])} – {fmt_clock(s[-1][0])}", "", ""])
                for ts, p in sorted(s, reverse=True):
                    self.store.append(s_it, [esc(p.name), fmt_clock(ts), short(p.parent), str(p)])
        self.view.expand_row(Gtk.TreePath.new_first(), True)
        last = sessions[0]
        folder = Counter(str(p.parent) for _, p in last).most_common(1)[0][0]
        when = f"{day_label(date.fromtimestamp(last[-1][0]))}, {fmt_clock(last[0][0])} – {fmt_clock(last[-1][0])}"
        names = ", ".join(esc(p.name) for _, p in sorted(last, reverse=True)[:3])
        more = f" and {len(last) - 3} more" if len(last) > 3 else ""
        self.summary.set_markup(
            f"<big>Your last session: <b>{esc(when)}</b></big>\n"
            f"You worked on <b>{names}</b>{more}, mostly in <i>{esc(short(folder))}</i>.")
        return False

    def on_activated(self, view, path, _col):
        row = self.store[path]
        if row[3]:
            self.win.open_path(row[3])
        elif view.row_expanded(path):
            view.collapse_row(path)
        else:
            view.expand_row(path, False)

    def on_click(self, view, event):
        if event.button != 3:
            return False
        hit = view.get_path_at_pos(int(event.x), int(event.y))
        if not hit or not self.store[hit[0]][3]:
            return False
        path = self.store[hit[0]][3]
        menu = Gtk.Menu()
        for label, cb in (("Open", lambda: self.win.open_path(path)),
                          ("Show in folder", lambda: (self.win.active.show_in_folder(path), self.win.present())),
                          ("Copy path", lambda: self.win.copy_text(path))):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, cb=cb: cb())
            menu.append(item)
        menu.show_all()
        menu.attach_to_widget(view, None)
        menu.popup_at_pointer(event)
        return True

    def reopen_last(self, *_):
        if not self.sessions:
            return
        files = [str(p) for _, p in sorted(self.sessions[0], reverse=True)][:10]
        if len(files) > 4 and not self.win.confirm(
                f"Open {len(files)} files from your last session?", parent=self):
            return
        for f in files:
            self.win.open_path(f)


# ---------------------------------------------------------------- compare two files / folders
def describe_file(path):
    st = os.stat(path)
    is_dir = statmod.S_ISDIR(st.st_mode)
    d = OrderedDict()
    d["Name"] = os.path.basename(path)
    d["Folder"] = short(os.path.dirname(path))
    d["Kind"] = "Folder" if is_dir else category_of(path)
    d["File type"] = type_description(path, is_dir)
    if is_dir:
        files, size = 0, 0
        for p, s, sub_dir in walk_entries(path, hidden=True):
            if not sub_dir:
                files += 1
                size += s.st_size
            if files > 50000:
                break
        d["Contents"] = f"{files:,} files, {human_size(size)}"
    else:
        d["Size"] = f"{human_size(st.st_size)} ({st.st_size:,} bytes)"
    d["Modified"] = fmt_full(st.st_mtime)
    try:
        info = Gio.File.new_for_path(path).query_info("time::created", Gio.FileQueryInfoFlags.NONE, None)
        if info.has_attribute("time::created"):
            d["Created"] = fmt_full(info.get_attribute_uint64("time::created"))
    except GLib.Error:
        pass
    d["Permissions"] = statmod.filemode(st.st_mode)
    if not is_dir:
        if d["Kind"] == "Images":
            info = GdkPixbuf.Pixbuf.get_file_info(path)
            if info and info[0]:
                d["Dimensions"] = f"{info[1]} × {info[2]} px"
        if ext_of(path) == "pdf":
            pages = pdf_pages(path)
            if pages:
                d["Pages"] = pages
        if is_text_file(path):
            text, cut = read_text(path, 2_000_000)
            d["Lines"] = f"{len(text.splitlines()):,}{'+' if cut else ''}"
            d["Words"] = f"{len(text.split()):,}"
    d["Tags"] = ", ".join(TAG_STORE.tags(path)) or "—"
    return d, st, is_dir


class CompareWindow(Gtk.Window):
    def __init__(self, win, a, b):
        super().__init__(title="Compare", transient_for=win)
        self.set_default_size(1000, 680)
        self.win, self.a, self.b = win, a, b
        hb = Gtk.HeaderBar(show_close_button=True, title="Compare",
                           subtitle=f"{os.path.basename(a)}  ↔  {os.path.basename(b)}")
        self.set_titlebar(hb)
        swap = Gtk.Button(label="Open both")
        swap.connect("clicked", lambda *_: (win.open_path(a), win.open_path(b)))
        hb.pack_end(swap)
        self.spinner = Gtk.Spinner()
        hb.pack_end(self.spinner)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        self.add(box)
        self.verdict = Gtk.Label(xalign=0, wrap=True)
        self.verdict.set_markup("<big>Comparing…</big>")
        box.add(self.verdict)

        self.props = Gtk.ListStore(str, str, str, bool)
        view = Gtk.TreeView(model=self.props, enable_search=False)
        view.get_selection().set_mode(Gtk.SelectionMode.NONE)
        for i, title in enumerate(("", "A", "B")):
            r = Gtk.CellRendererText(wrap_mode=Pango.WrapMode.WORD_CHAR, wrap_width=380 if i else 120)
            c = Gtk.TreeViewColumn(title, r, text=i)
            if i:
                c.set_expand(True)
                c.set_cell_data_func(r, self._diff_cell, i)
            else:
                c.set_cell_data_func(r, lambda col, cell, m, it, *_: cell.set_property("weight", 700))
            view.append_column(c)
        frame = Gtk.Frame()
        frame.add(view)
        box.add(frame)

        self.book = Gtk.Notebook(vexpand=True)
        box.pack_start(self.book, True, True, 0)
        self.show_all()
        self.spinner.start()
        threading.Thread(target=self.analyze, daemon=True).start()

    def _diff_cell(self, col, cell, model, it, _i):
        differ = model[it][3]
        cell.set_property("weight", 700 if differ else 400)
        cell.set_property("foreground", "#e66100" if differ else None)
        cell.set_property("foreground-set", differ)

    def analyze(self):
        try:
            da, sa, dir_a = describe_file(self.a)
            db, sb, dir_b = describe_file(self.b)
        except OSError as ex:
            GLib.idle_add(self.verdict.set_markup, f"<big>Can't compare: {esc(ex.strerror)}</big>")
            return
        rows = []
        for key in list(OrderedDict.fromkeys(list(da) + list(db))):
            va, vb = da.get(key, "—"), db.get(key, "—")
            rows.append((key, va, vb, va != vb))
        result = {"rows": rows, "reasons": [], "pages": []}
        if dir_a and dir_b:
            self.compare_folders(result)
        elif not dir_a and not dir_b:
            self.compare_files(result, sa, sb, da, db)
        else:
            result["headline"] = "One is a folder and the other is a file, so only their details are compared."
            result["same"] = False
        GLib.idle_add(self.show_result, result)

    def compare_files(self, result, sa, sb, da, db):
        reasons = result["reasons"]
        same = False
        hash_a = hash_b = None
        if sa.st_size == sb.st_size:
            hash_a, hash_b = file_hash(self.a), file_hash(self.b)
            same = hash_a == hash_b
        elif max(sa.st_size, sb.st_size) < 500 * 1024 * 1024:
            hash_a, hash_b = file_hash(self.a), file_hash(self.b)
        if hash_a:
            result["rows"].append(("Checksum (SHA-256)", hash_a[:16] + "…", hash_b[:16] + "…", hash_a != hash_b))
        result["same"] = same
        if same:
            diffs = [k for k in ("Name", "Folder", "Modified") if da.get(k) != db.get(k)]
            result["headline"] = ("✅  <b>Same content.</b> These two are exact byte-for-byte copies"
                                  + (f" (only their {', '.join(d.lower() for d in diffs)} differ)" if diffs else "")
                                  + ". You can safely delete one of them.")
        else:
            result["headline"] = "≠  <b>Different content.</b>"
            if da["Kind"] != db["Kind"] or da["File type"] != db["File type"]:
                reasons.append(f"They are different kinds of file: {da['File type']} vs {db['File type']}.")
            if sa.st_size != sb.st_size:
                bigger = "A" if sa.st_size > sb.st_size else "B"
                reasons.append(f"{bigger} is bigger by {human_size(abs(sa.st_size - sb.st_size))}.")
            if abs(sa.st_mtime - sb.st_mtime) > 60:
                newer = "A" if sa.st_mtime > sb.st_mtime else "B"
                reasons.append(f"{newer} was changed more recently ({duration(abs(sa.st_mtime - sb.st_mtime))} later).")
        if is_text_file(self.a) and is_text_file(self.b):
            ta, _ = read_text(self.a, 2_000_000)
            tb, _ = read_text(self.b, 2_000_000)
            la, lb = ta.splitlines(), tb.splitlines()
            diff = list(difflib.unified_diff(la, lb, "A: " + da["Name"], "B: " + db["Name"], n=3, lineterm=""))
            added = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
            removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
            if not same:
                if len(la) + len(lb) < 20000:
                    ratio = difflib.SequenceMatcher(None, la, lb, autojunk=False).ratio()
                    reasons.append(f"The text is {ratio:.0%} similar: {added} line(s) only in B, {removed} only in A.")
                else:
                    reasons.append(f"{added} line(s) only in B, {removed} only in A.")
            result["pages"].append(("text", diff))
        if da["Kind"] == "Images" and db["Kind"] == "Images":
            result["pages"].append(("images", (load_scaled(self.a, 440, 440), load_scaled(self.b, 440, 440))))

    def compare_folders(self, result):
        def listing(root):
            out = {}
            for p, st, is_dir in walk_entries(root, hidden=True):
                if not is_dir:
                    out[os.path.relpath(p, root)] = (st.st_size, st.st_mtime)
                if len(out) > 50000:
                    break
            return out
        fa, fb = listing(self.a), listing(self.b)
        only_a = sorted(set(fa) - set(fb))
        only_b = sorted(set(fb) - set(fa))
        changed = sorted(k for k in set(fa) & set(fb) if fa[k][0] != fb[k][0])
        same = len(set(fa) & set(fb)) - len(changed)
        result["same"] = not (only_a or only_b or changed)
        result["headline"] = ("✅  <b>These folders contain the same files</b> (same names and sizes)."
                              if result["same"] else "≠  <b>The folders differ.</b>")
        result["reasons"] += [f"{same:,} files match", f"{len(changed):,} have different sizes",
                              f"{len(only_a):,} only in A", f"{len(only_b):,} only in B"]
        result["pages"].append(("folders", (only_a, only_b, changed)))

    def show_result(self, result):
        self.spinner.stop()
        for row in result["rows"]:
            self.props.append(list(row))
        text = f"<big>{result['headline']}</big>"
        if result["reasons"]:
            text += "\n" + "\n".join("• " + esc(r) for r in result["reasons"])
        self.verdict.set_markup(text)
        for kind, data in result["pages"]:
            if kind == "text":
                self.book.append_page(self.diff_page(data), Gtk.Label(label="Text differences"))
            elif kind == "images":
                self.book.append_page(self.image_page(*data), Gtk.Label(label="Side by side"))
            elif kind == "folders":
                self.book.append_page(self.folder_page(*data), Gtk.Label(label="File lists"))
        if not result["pages"]:
            lbl = Gtk.Label(label="These files aren't text, so their content is compared by checksum only.")
            self.book.append_page(lbl, Gtk.Label(label="Content"))
        self.book.show_all()
        return False

    def _textview(self):
        tv = Gtk.TextView(editable=False, monospace=True, cursor_visible=False, left_margin=8, top_margin=6)
        buf = tv.get_buffer()
        for name, fg, bg in (("add", "#26a269", "rgba(46,194,126,0.15)"),
                             ("del", "#c01c28", "rgba(224,27,36,0.13)"),
                             ("hunk", "#1c71d8", None), ("head", None, None)):
            tag = buf.create_tag(name)
            if fg:
                tag.set_property("foreground", fg)
            if bg:
                rgba = Gdk.RGBA()
                rgba.parse(bg)
                tag.set_property("paragraph-background-rgba", rgba)
            if name in ("hunk", "head"):
                tag.set_property("weight", 700)
        scroll = Gtk.ScrolledWindow()
        scroll.add(tv)
        return scroll, buf

    def diff_page(self, diff):
        scroll, buf = self._textview()
        if not diff:
            buf.set_text("The text in both files is identical.")
            return scroll
        for line in diff[:20000]:
            tag = ("head" if line.startswith(("+++", "---")) else "add" if line.startswith("+")
                   else "del" if line.startswith("-") else "hunk" if line.startswith("@@") else None)
            it = buf.get_end_iter()
            if tag:
                buf.insert_with_tags_by_name(it, line + "\n", tag)
            else:
                buf.insert(it, line + "\n")
        return scroll

    def image_page(self, pa, pb):
        box = Gtk.Box(spacing=12, border_width=10, homogeneous=True)
        for label, pix in (("A", pa), ("B", pb)):
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            col.add(Gtk.Label(label=label))
            col.add(Gtk.Image.new_from_pixbuf(pix) if pix else Gtk.Label(label="(can't load)"))
            box.add(col)
        return box

    def folder_page(self, only_a, only_b, changed):
        scroll, buf = self._textview()
        for title, items, tag in (("Only in A", only_a, "del"), ("Only in B", only_b, "add"),
                                  ("Different size", changed, "hunk")):
            buf.insert_with_tags_by_name(buf.get_end_iter(), f"{title} ({len(items)})\n", "head")
            for item in items[:3000]:
                buf.insert_with_tags_by_name(buf.get_end_iter(), "   " + item + "\n", tag)
            buf.insert(buf.get_end_iter(), "\n")
        return scroll


# ---------------------------------------------------------------- duplicate finder
COPY_MARKERS = ("(1)", "(2)", "(3)", " copy", "_copy", "-copy", "copy of", ".pdf.pdf")


def keep_score(path, mtime):
    name = os.path.basename(path).lower()
    marked = any(m in name for m in COPY_MARKERS)
    return (marked, len(name), mtime)


class DuplicatesWindow(Gtk.Window):
    MIN_SIZES = [("Any size", 1), ("Over 100 KB", 100 * 1024), ("Over 1 MB", 1024 ** 2), ("Over 10 MB", 10 * 1024 ** 2)]

    def __init__(self, win, folder):
        super().__init__(title="Find duplicate files", transient_for=win)
        self.set_default_size(980, 640)
        self.win = win
        self.cancel = False
        self.connect("destroy", lambda *_: setattr(self, "cancel", True))
        hb = Gtk.HeaderBar(show_close_button=True, title="Find duplicate files",
                           subtitle="Files with exactly the same content")
        self.set_titlebar(hb)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        self.add(box)

        top = Gtk.Box(spacing=8)
        top.add(Gtk.Label(label="Look in:"))
        self.chooser = Gtk.FileChooserButton(title="Choose a folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        self.chooser.set_filename(folder)
        self.chooser.set_size_request(260, -1)
        top.add(self.chooser)
        self.min_combo = Gtk.ComboBoxText()
        for label, _ in self.MIN_SIZES:
            self.min_combo.append_text(label)
        self.min_combo.set_active(0)
        top.add(self.min_combo)
        self.scan_btn = Gtk.Button(label="Scan")
        self.scan_btn.get_style_context().add_class("suggested-action")
        self.scan_btn.connect("clicked", self.start_scan)
        top.add(self.scan_btn)
        self.progress = Gtk.Label(xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.END)
        top.pack_start(self.progress, True, True, 0)
        box.add(top)

        # check, name, folder, size text, modified text, path, is_header, size
        self.store = Gtk.TreeStore(bool, str, str, str, str, str, bool, GObject.TYPE_INT64)
        self.view = Gtk.TreeView(model=self.store, enable_search=False)
        toggle = Gtk.CellRendererToggle()
        toggle.connect("toggled", self.on_toggled)
        tcol = Gtk.TreeViewColumn("Delete", toggle, active=0)
        tcol.set_cell_data_func(toggle, lambda c, cell, m, it, *_: cell.set_visible(not m[it][6]))
        self.view.append_column(tcol)
        for i, title, expand in ((1, "Name", True), (2, "Folder", True), (3, "Size", False), (4, "Modified", False)):
            r = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE if i < 3 else Pango.EllipsizeMode.NONE)
            c = Gtk.TreeViewColumn(title, r, markup=i) if i == 1 else Gtk.TreeViewColumn(title, r, text=i)
            c.set_expand(expand)
            c.set_resizable(True)
            self.view.append_column(c)
        self.view.connect("row-activated", self.on_activated)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(self.view)
        box.pack_start(scroll, True, True, 0)

        bottom = Gtk.Box(spacing=8)
        self.summary = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        self.summary.set_markup("Choose a folder and press <b>Scan</b>. In each group, the copy that looks "
                                "like the original is kept; the extra copies are ticked for deletion.")
        bottom.pack_start(self.summary, True, True, 0)
        self.trash_btn = Gtk.Button(label="Move ticked copies to Trash")
        self.trash_btn.get_style_context().add_class("destructive-action")
        self.trash_btn.set_sensitive(False)
        self.trash_btn.connect("clicked", self.trash_selected)
        bottom.add(self.trash_btn)
        box.add(bottom)
        self.show_all()

    def start_scan(self, *_):
        root = self.chooser.get_filename()
        if not root:
            return
        self.store.clear()
        self.scan_btn.set_sensitive(False)
        self.trash_btn.set_sensitive(False)
        min_size = self.MIN_SIZES[self.min_combo.get_active()][1]
        threading.Thread(target=self.scan, args=(root, min_size), daemon=True).start()

    def report(self, text):
        GLib.idle_add(self.progress.set_text, text)

    def scan(self, root, min_size):
        by_size, n, last = {}, 0, 0
        for p, st, is_dir in walk_entries(root):
            if self.cancel:
                return
            if is_dir or st.st_size < min_size or not statmod.S_ISREG(st.st_mode):
                continue
            by_size.setdefault(st.st_size, []).append((str(p), st.st_mtime))
            n += 1
            if time.time() - last > 0.25:
                self.report(f"Listing files… {n:,}")
                last = time.time()
        candidates = [g for g in by_size.values() if len(g) > 1]
        total, done, groups = sum(len(g) for g in candidates), 0, []
        for group in candidates:
            by_partial = {}
            for p, m in group:
                if self.cancel:
                    return
                try:
                    by_partial.setdefault(file_hash(p, partial=True), []).append((p, m))
                except OSError:
                    pass
                done += 1
                if time.time() - last > 0.25:
                    self.report(f"Checking contents… {done:,} / {total:,}")
                    last = time.time()
            for sub in by_partial.values():
                if len(sub) < 2:
                    continue
                by_full = {}
                for p, m in sub:
                    if self.cancel:
                        return
                    try:
                        by_full.setdefault(file_hash(p), []).append((p, m))
                    except OSError:
                        pass
                groups += [g for g in by_full.values() if len(g) > 1]
        GLib.idle_add(self.fill, groups, n)

    def fill(self, groups, scanned):
        self.scan_btn.set_sensitive(True)
        self.progress.set_text(f"Scanned {scanned:,} files.")
        groups.sort(key=lambda g: -os.path.getsize(g[0][0]) * (len(g) - 1) if os.path.exists(g[0][0]) else 0)
        wasted = 0
        for g in groups:
            try:
                size = os.path.getsize(g[0][0])
            except OSError:
                continue
            wasted += size * (len(g) - 1)
            keep = min(g, key=lambda pm: keep_score(*pm))
            head = self.store.append(None, [False, f"<b>{len(g)} copies</b> · {human_size(size)} each · "
                                                   f"{human_size(size * (len(g) - 1))} can be freed",
                                            "", "", "", "", True, 0])
            for p, m in sorted(g, key=lambda pm: keep_score(*pm)):
                is_keep = p == keep[0]
                name = esc(os.path.basename(p)) + ("  <small>(keep)</small>" if is_keep else "")
                self.store.append(head, [not is_keep, name, short(os.path.dirname(p)),
                                         human_size(size), fmt_time(m), p, False, size])
        self.view.expand_all()
        if groups:
            self.summary.set_markup(f"Found <b>{len(groups)}</b> group{'s' if len(groups) != 1 else ''} of duplicates. "
                                    f"Removing the ticked copies frees <b>{human_size(wasted)}</b>.")
        else:
            self.summary.set_markup("🎉 No duplicate files found here.")
        self.update_trash_btn()
        return False

    def on_toggled(self, cell, path):
        self.store[path][0] = not self.store[path][0]
        self.update_trash_btn()

    def ticked(self):
        out = []
        for head in self.store:
            for child in head.iterchildren():
                if child[0]:
                    out.append((child[5], child[7]))
        return out

    def update_trash_btn(self):
        t = self.ticked()
        self.trash_btn.set_sensitive(bool(t))
        self.trash_btn.set_label(f"Move {len(t)} ticked cop{'y' if len(t) == 1 else 'ies'} to Trash "
                                 f"({human_size(sum(s for _, s in t))})" if t else "Move ticked copies to Trash")

    def on_activated(self, view, path, _col):
        p = self.store[path][5]
        if p:
            self.win.open_path(p)

    def trash_selected(self, *_):
        ticked = self.ticked()
        for head in self.store:
            if all(child[0] for child in head.iterchildren()):
                self.win.error("In one group every copy is ticked. Keep at least one copy of each file.",
                               parent=self)
                return
        if not self.win.confirm(f"Move {len(ticked)} duplicate copies to Trash?\n"
                                "You can restore them from Trash in the Files app.", parent=self):
            return
        moved = 0
        for p, _ in ticked:
            try:
                Gio.File.new_for_path(p).trash(None)
                moved += 1
            except GLib.Error:
                pass
        self.progress.set_text(f"Moved {moved} copies to Trash.")
        self.start_scan()
        self.win.refresh_all()


# ---------------------------------------------------------------- Quick Share (local network)

SHARE_MINUTES = [1, 2, 5, 10]
KIND_EMOJI = {"Images": "🖼️", "Documents": "📄", "Spreadsheets": "📊", "Presentations": "📽️",
              "Videos": "🎬", "Audio": "🎵", "Archives": "🗜️", "Code": "💻", "Installers": "📦",
              "Others": "📎", "Folder": "📁"}


def lan_addresses():
    """This computer's address(es) on the local network."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))          # no traffic is actually sent
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        if IS_WIN:
            out = socket.gethostbyname_ex(socket.gethostname())[2]
        else:
            out = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=3).stdout.split()
        ips += [ip for ip in out if ip.count(".") == 3 and ip not in ips and not ip.startswith("127.")]
    except (OSError, subprocess.SubprocessError):
        pass
    return [ip for ip in ips if not ip.startswith("127.")] or ["127.0.0.1"]


def qr_pixbuf(text, size=220):
    exe = shutil.which("qrencode")
    if not exe:
        return _qr_python(text, size)
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "qr.png")
        try:
            subprocess.run([exe, "-o", out, "-s", "8", "-m", "2", text], timeout=10, capture_output=True)
        except (OSError, subprocess.SubprocessError):
            return None
        if not os.path.exists(out):
            return None
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(out, size, size, True)
        except GLib.Error:
            return None


def _qr_python(text, size):
    """QR code using the pure-Python 'qrcode' package (bundled in the Windows build)."""
    try:
        import qrcode
    except ImportError:
        return None
    try:
        qr = qrcode.QRCode(border=2, box_size=1)
        qr.add_data(text)
        qr.make(fit=True)
        matrix = qr.get_matrix()
        n = len(matrix)
        scale = max(1, size // n)
        data = bytearray()
        for row in matrix:
            line = b"".join((b"\x00\x00\x00" if cell else b"\xff\xff\xff") * scale for cell in row)
            data += line * scale
        dim = n * scale
        return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB,
                                               False, 8, dim, dim, dim * 3)
    except Exception:
        return None


PAGE_CSS = """
:root{--bg:#f6f5f4;--card:#fff;--text:#1d1d1f;--muted:#6b6b6f;--accent:#5b5bd6;--line:#e3e2e0}
@media (prefers-color-scheme:dark){:root{--bg:#1e1e20;--card:#2a2a2d;--text:#f2f2f2;--muted:#a0a0a6;--accent:#8c8cff;--line:#3a3a3e}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",Ubuntu,sans-serif;
background:var(--bg);color:var(--text)}main{max-width:720px;margin:0 auto;padding:20px 14px 40px}
header{display:flex;align-items:center;gap:12px;margin-bottom:6px}header .logo{font-size:30px}
h1{font-size:22px;margin:0}.sub{color:var(--muted);margin:2px 0 18px}
.timer{display:inline-block;background:var(--accent);color:#fff;border-radius:999px;padding:4px 12px;font-weight:600}
.all{display:block;text-align:center;background:var(--accent);color:#fff;text-decoration:none;border-radius:12px;
padding:13px;font-weight:600;margin:14px 0}
ul{list-style:none;padding:0;margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden}
li{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--line)}li:first-child{border-top:0}
.thumb{width:48px;height:48px;border-radius:8px;object-fit:cover;flex:none;background:var(--line);display:flex;
align-items:center;justify-content:center;font-size:26px}
.info{flex:1;min-width:0}.name{font-weight:600;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:13px}
.btns{display:flex;gap:6px;flex:none}.btns a{text-decoration:none;border:1px solid var(--line);color:var(--text);
border-radius:9px;padding:7px 11px;font-size:14px}.btns a.dl{background:var(--accent);border-color:var(--accent);color:#fff}
.ended{text-align:center;padding:60px 10px}.ended .big{font-size:56px}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:22px}
"""


def page_message(title, text):
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,"
            f"initial-scale=1'><title>{htmlmod.escape(title)}</title><style>{PAGE_CSS}</style></head><body><main>"
            f"<div class='ended'><div class='big'>⏱️</div><h1>{htmlmod.escape(title)}</h1>"
            f"<p class='sub'>{htmlmod.escape(text)}</p></div></main></body></html>")


def share_page(share, items):
    rows = []
    for i, p in enumerate(items):
        name = os.path.basename(p.rstrip("/\\"))
        is_dir = os.path.isdir(p)
        kind = "Folder" if is_dir else category_of(name)
        try:
            size = "folder · downloads as ZIP" if is_dir else human_size(os.path.getsize(p))
        except OSError:
            continue
        thumb = (f"<img class='thumb' loading='lazy' src='f/{i}?view=1' alt=''>" if kind == "Images"
                 else f"<div class='thumb'>{KIND_EMOJI.get(kind, '📎')}</div>")
        viewable = not is_dir and (kind in ("Images", "Videos", "Audio") or ext_of(name) in ("pdf", "txt", "md"))
        view = f"<a href='f/{i}?view=1' target='_blank'>View</a>" if viewable else ""
        rows.append(f"<li>{thumb}<div class='info'><div class='name'>{htmlmod.escape(name)}</div>"
                    f"<div class='meta'>{htmlmod.escape(size)}</div></div>"
                    f"<div class='btns'>{view}<a class='dl' href='f/{i}'>Download</a></div></li>")
    host = htmlmod.escape(socket.gethostname())
    left = share.remaining()
    all_btn = "<a class='all' href='all.zip'>⬇ Download everything (ZIP)</a>" if len(items) > 1 else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Files from {host}</title>
<style>{PAGE_CSS}</style></head><body><main>
<header><div class="logo">📂</div><div><h1>Files shared from {host}</h1></div></header>
<p class="sub">Shared with Arckad-D Quick Share · <span class="timer" id="t">--:--</span></p>
{all_btn}<ul>{''.join(rows) or '<li>No files are shared right now.</li>'}</ul>
<footer>This link only works on the same network and stops when the timer ends.</footer>
</main><script>
let left={left};const t=document.getElementById('t');
function tick(){{if(left<=0){{document.querySelector('main').innerHTML=
"<div class='ended'><div class='big'>⏱️</div><h1>This share has ended</h1><p class='sub'>Ask the sender to share again.</p></div>";return}}
t.textContent='ends in '+Math.floor(left/60)+':'+String(left%60).padStart(2,'0');left--;setTimeout(tick,1000)}}tick();
</script></body></html>"""


def make_share_handler(share):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Arckad-D"

        def log_message(self, *args):
            pass

        def _send(self, code, body, ctype="text/html; charset=utf-8"):
            data = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                self._route()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _route(self):
            url = urllib.parse.urlsplit(self.path)
            parts = [p for p in url.path.split("/") if p]
            client = self.client_address[0]
            if not parts or not secrets.compare_digest(parts[0], share.token):
                return self._send(404, page_message("Link not found", "Check the link and try again."))
            if not share.active():
                return self._send(410, page_message("This share has ended", "Ask the sender to share again."))
            if len(parts) == 1:
                if not url.path.endswith("/"):
                    self.send_response(301)
                    self.send_header("Location", f"/{share.token}/")
                    self.end_headers()
                    return
                share.event(client, "opened the share page")
                return self._send(200, share_page(share, share.snapshot()))
            items = share.snapshot()
            if parts[1] == "all.zip" and items:
                share.event(client, f"downloaded everything ({len(items)} items, ZIP)")
                return self._zip(items, "Arckad-D share.zip")
            if parts[1] == "f" and len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) < len(items):
                path = items[int(parts[2])]
                name = os.path.basename(path.rstrip("/\\"))
                if os.path.isdir(path):
                    share.event(client, f"downloaded folder {name} (ZIP)")
                    return self._zip([path], name + ".zip")
                inline = "view=1" in url.query
                if not inline:
                    share.event(client, f"downloaded {name}")
                return self._file(path, name, inline)
            return self._send(404, page_message("Not found", "That file isn't shared."))

        def _disposition(self, kind, name):
            ascii_name = name.encode("ascii", "replace").decode().replace('"', "'")
            return f'{kind}; filename="{ascii_name}"; filename*=UTF-8\'\'{urllib.parse.quote(name)}'

        def _file(self, path, name, inline):
            try:
                size = os.path.getsize(path)
                f = open(path, "rb")
            except OSError:
                return self._send(404, page_message("Not found", "That file is no longer available."))
            with f:
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", self._disposition("inline" if inline else "attachment", name))
                self.end_headers()
                shutil.copyfileobj(f, self.wfile, 1 << 20)

        def _zip(self, paths, name):
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", self._disposition("attachment", name))
            self.send_header("Connection", "close")
            self.end_headers()
            with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zf:
                for p in paths:
                    if os.path.isdir(p):
                        base = os.path.dirname(p.rstrip("/\\"))
                        for fp, st, is_dir in walk_entries(p, hidden=True):
                            if not is_dir:
                                zf.write(fp, os.path.relpath(fp, base))
                    elif os.path.exists(p):
                        zf.write(p, os.path.basename(p))
    return Handler


class QuickShare:
    PORTS = (8765, 8766, 8767, 0)

    def __init__(self, on_event=None):
        self.items = []
        self.lock = threading.Lock()
        self.server = None
        self.token = ""
        self.port = 0
        self.expires = 0
        self.on_event = on_event

    def snapshot(self):
        with self.lock:
            return [p for p in self.items if os.path.exists(p)]

    def add(self, paths):
        with self.lock:
            for p in paths:
                if p not in self.items:
                    self.items.append(p)

    def remove(self, paths):
        with self.lock:
            self.items = [p for p in self.items if p not in set(paths)]

    def active(self):
        return self.server is not None and time.time() < self.expires

    def remaining(self):
        return max(0, int(self.expires - time.time())) if self.server else 0

    def start(self, minutes):
        self.stop()
        self.token = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))
        for port in self.PORTS:
            try:
                self.server = ThreadingHTTPServer(("0.0.0.0", port), make_share_handler(self))
                break
            except OSError:
                continue
        if self.server is None:
            raise OSError("No free network port")
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.expires = time.time() + min(10, max(1, minutes)) * 60
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def extend(self, minutes):
        if self.server:
            self.expires = time.time() + min(10, max(1, minutes)) * 60

    def stop(self):
        srv, self.server = self.server, None
        if srv:
            def close():
                srv.shutdown()
                srv.server_close()
            threading.Thread(target=close, daemon=True).start()

    def url(self, ip):
        return f"http://{ip}:{self.port}/{self.token}/"

    def event(self, client, text):
        if self.on_event:
            GLib.idle_add(self.on_event, client, text)


# ---------------------------------------------------------------- Nearby: Arckad-D finds Arckad-D
NEARBY_UDP_PORT = 47820
NEARBY_TCP_PORTS = (47821, 47822, 47823, 0)
OS_NAME = "Windows" if IS_WIN else "Linux"
BAD_NAME_CHARS = set('<>:"|?*\\')


def received_dir():
    d = downloads_dir() / "Arckad-D Received"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_rel_parts(rel):
    """Cleans a relative path sent by another computer, so it can't escape the received folder."""
    clean = []
    for part in str(rel).replace("\\", "/").split("/"):
        if part in ("", ".", ".."):
            return None
        part = "".join("_" if (c in BAD_NAME_CHARS or ord(c) < 32) else c for c in part).strip().rstrip(".")
        if not part:
            return None
        clean.append(part[:200])
    return clean or None


def files_for_sending(paths):
    """[(source path, relative name, size)] — folders are sent file by file, keeping their structure."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            base = os.path.dirname(p.rstrip("/\\"))
            for fp, st, is_dir in walk_entries(p, hidden=True):
                if not is_dir:
                    out.append((str(fp), os.path.relpath(fp, base).replace(os.sep, "/"), st.st_size))
        elif os.path.isfile(p):
            out.append((p, os.path.basename(p), os.path.getsize(p)))
    return out


def plan_destinations(files):
    base = received_dir()
    roots, claimed, out = {}, set(), []
    for parts, _size in files:
        key = parts[0] if len(parts) > 1 else None
        if key is not None and key in roots:
            root = roots[key]
        else:
            root = unique_target(base / parts[0])
            while str(root) in claimed:
                root = unique_target(root.with_name(root.stem + " (1)" + root.suffix))
            claimed.add(str(root))
            if key is not None:
                roots[key] = root
        out.append(root.joinpath(*parts[1:]) if len(parts) > 1 else root)
    return out


def make_nearby_handler(nb):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Arckad-D"

        def log_message(self, *args):
            pass

        def _json(self, code, obj):
            data = json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            """Lets a sender on another network (VLAN) check this device directly by its IP."""
            try:
                if self.path.split("?")[0].rstrip("/") == "/hello" and nb.visible():
                    return self._json(200, {"app": "arckad-d", "v": 1, "type": "hello", "id": nb.id,
                                            "name": nb.name(), "os": OS_NAME, "port": nb.port})
                return self._json(403, {"ok": False, "reason": "not visible right now"})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            try:
                self._post()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_PUT(self):
            try:
                self._put()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _post(self):
            parts = [p for p in self.path.split("/") if p]
            if parts == ["offer"]:
                if not nb.visible():
                    return self._json(403, {"ok": False, "reason": "not visible right now"})
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 5_000_000:
                    return self._json(413, {"ok": False, "reason": "offer too large"})
                try:
                    offer = json.loads(self.rfile.read(length))
                except ValueError:
                    return self._json(400, {"ok": False, "reason": "bad offer"})
                files = []
                for f in (offer.get("files") or [])[:20000]:
                    rel, size = safe_rel_parts(f.get("path", "")), f.get("size")
                    if rel is None or not isinstance(size, int) or size < 0:
                        return self._json(400, {"ok": False, "reason": "bad file name"})
                    files.append((rel, size))
                if not files:
                    return self._json(400, {"ok": False, "reason": "no files"})
                req = {"from": str(offer.get("name") or "Unknown computer")[:40],
                       "os": str(offer.get("os") or "")[:10], "ip": self.client_address[0],
                       "files": files, "total": sum(s for _, s in files),
                       "event": threading.Event(), "accepted": False}
                GLib.idle_add(nb.win.ask_incoming, req)
                req["event"].wait(90)
                if not req["accepted"]:
                    return self._json(403, {"ok": False, "reason": "declined"})
                req["dest"] = plan_destinations(files)
                req["received"], req["done_files"] = 0, 0
                token = secrets.token_hex(12)
                nb.transfers[token] = req
                return self._json(200, {"ok": True, "token": token})
            if len(parts) == 2 and parts[0] == "done":
                req = nb.transfers.pop(parts[1], None)
                if not req:
                    return self._json(404, {"ok": False})
                GLib.idle_add(nb.win.on_nearby_received, req)
                return self._json(200, {"ok": True})
            return self._json(404, {"ok": False})

        def _put(self):
            parts = [p for p in self.path.split("/") if p]
            if len(parts) != 3 or parts[0] != "upload" or not parts[2].isdigit():
                return self._json(404, {"ok": False})
            req, i = nb.transfers.get(parts[1]), int(parts[2])
            if not req or i >= len(req["files"]):
                return self._json(404, {"ok": False})
            size = req["files"][i][1]
            if int(self.headers.get("Content-Length") or -1) != size:
                return self._json(400, {"ok": False, "reason": "size mismatch"})
            dest = req["dest"][i]
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            remaining = size
            with open(tmp, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(1 << 18, remaining))
                    if not chunk:
                        break
                    f.write(chunk)
                    remaining -= len(chunk)
                    req["received"] += len(chunk)
            if remaining:
                tmp.unlink()
                return self._json(400, {"ok": False, "reason": "incomplete"})
            os.replace(tmp, dest)
            req["done_files"] += 1
            GLib.idle_add(nb.win.on_nearby_progress, req)
            return self._json(200, {"ok": True})
    return Handler


class Nearby:
    def __init__(self, win):
        self.win = win
        if not win.cfg.get("device_id"):
            win.cfg["device_id"] = secrets.token_hex(8)
        self.id = win.cfg["device_id"]
        self.peers = {}
        self.lock = threading.Lock()
        self.udp = None
        self.scanning = False
        self.server = None
        self.port = 0
        self.visible_until = 0
        self.transfers = {}
        self._ips = ([], 0)
        self.last_beacon = self.last_probe = self.last_expire = self.last_manual = 0
        self.manual_busy = False

    def ui(self, method, *args):
        GLib.idle_add(lambda: getattr(self.win, method)(*args) or False)

    def manual_ips(self):
        return list(self.win.cfg.get("manual_ips", []))

    def hello_at(self, host, timeout=2.5):
        """Asks one address directly (works across VLANs / routed networks where broadcasts don't reach).
        Returns (peer, None) or (None, reason)."""
        import http.client
        reason = "no answer"
        for port in NEARBY_TCP_PORTS[:-1]:
            try:
                c = http.client.HTTPConnection(host, port, timeout=timeout)
                c.request("GET", "/hello")
                r = c.getresponse()
                data = json.loads(r.read() or b"{}")
                c.close()
            except (OSError, ValueError):
                continue
            if data.get("app") == "arckad-d" and isinstance(data.get("port"), int) and data["port"] > 0:
                if data.get("id") == self.id:
                    return None, "that's this computer"
                ip = socket.gethostbyname(host)
                peer = {"id": str(data.get("id"))[:40], "name": str(data.get("name") or host)[:40],
                        "os": str(data.get("os") or "")[:10], "ip": ip, "port": data["port"],
                        "seen": time.time(), "manual": True}
                with self.lock:
                    self.peers[peer["id"]] = peer
                return peer, None
            if r.status == 403:
                reason = "Arckad-D is there, but its Receive is turned off"
        return None, reason

    def _check_manual(self):
        try:
            changed = False
            for host in self.manual_ips():
                self._send({"type": "probe"}, host)          # if UDP gets through, it answers the normal way
                before = {k for k in self.peers}
                peer, _ = self.hello_at(host, timeout=2)
                if peer and peer["id"] not in before:
                    changed = True
            if changed:
                self.ui("on_peers_changed")
        finally:
            self.manual_busy = False

    def name(self):
        return (self.win.cfg.get("device_name") or socket.gethostname() or "My computer").strip()[:40]

    def visible(self):
        return self.server is not None and time.time() < self.visible_until

    def remaining(self):
        return max(0, int(self.visible_until - time.time())) if self.server else 0

    def ips(self):
        lst, ts = self._ips
        if time.time() - ts > 30:
            lst = lan_addresses()
            self._ips = (lst, time.time())
        return lst

    # ---------- being visible (receiving)
    def set_visible(self, minutes):
        if self.server is None:
            for port in NEARBY_TCP_PORTS:
                try:
                    self.server = ThreadingHTTPServer(("0.0.0.0", port), make_nearby_handler(self))
                    break
                except OSError:
                    continue
            if self.server is None:
                raise OSError("no free network port")
            self.server.daemon_threads = True
            self.port = self.server.server_address[1]
            threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.visible_until = time.time() + min(10, max(1, minutes)) * 60
        self._ensure_udp()
        self.last_beacon = 0

    def hide(self, force=False):
        self.visible_until = 0
        if self.transfers and not force:
            return False                   # finish receiving first; closed later by the timer
        srv, self.server = self.server, None
        if srv:
            self._send({"type": "bye"})

            def close():
                srv.shutdown()
                srv.server_close()
            threading.Thread(target=close, daemon=True).start()
        self._maybe_close_udp()
        return True

    # ---------- looking for others
    def start_scan(self):
        self.scanning = True
        self._ensure_udp()
        self.last_probe = 0

    def stop_scan(self):
        self.scanning = False
        self._maybe_close_udp()

    def peer_list(self):
        with self.lock:
            return sorted(self.peers.values(), key=lambda p: p["name"].lower())

    # ---------- UDP discovery
    def _ensure_udp(self):
        if self.udp:
            return
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", NEARBY_UDP_PORT))
        s.settimeout(0.5)
        self.udp = s
        threading.Thread(target=self._loop, args=(s,), daemon=True).start()

    def _maybe_close_udp(self):
        if self.udp and not self.scanning and self.server is None:
            s, self.udp = self.udp, None
            try:
                s.close()
            except OSError:
                pass
            with self.lock:
                self.peers.clear()

    def _send(self, msg, target=None):
        s = self.udp
        if not s:
            return
        msg = dict(msg, app="arckad-d", v=1, id=self.id, name=self.name(), os=OS_NAME, port=self.port)
        data = json.dumps(msg).encode()
        targets = {target} if target else (
            {"255.255.255.255"} | {ip.rsplit(".", 1)[0] + ".255" for ip in self.ips() if ip.count(".") == 3})
        for t in targets:
            try:
                s.sendto(data, (t, NEARBY_UDP_PORT))
            except OSError:
                pass

    def _loop(self, s):
        while self.udp is s:
            try:
                data, addr = s.recvfrom(8192)
            except socket.timeout:
                data = None
            except OSError:
                break
            if data:
                self._handle(data, addr[0])
            self._tick()

    def _handle(self, data, ip):
        try:
            msg = json.loads(data.decode("utf-8"))
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("app") != "arckad-d" or msg.get("id") == self.id:
            return
        kind, pid = msg.get("type"), str(msg.get("id"))[:40]
        changed = False
        if kind == "hello" and isinstance(msg.get("port"), int) and msg["port"] > 0:
            with self.lock:
                old = self.peers.get(pid)
                self.peers[pid] = {"id": pid, "name": str(msg.get("name") or "Unknown")[:40],
                                   "os": str(msg.get("os") or "")[:10], "ip": ip, "port": msg["port"],
                                   "seen": time.time()}
                changed = old is None or old["name"] != self.peers[pid]["name"]
        elif kind == "probe" and self.visible():
            self._send({"type": "hello"}, ip)
        elif kind == "bye":
            with self.lock:
                changed = self.peers.pop(pid, None) is not None
        if changed:
            GLib.idle_add(self.win.on_peers_changed)

    def _tick(self):
        now = time.time()
        if self.visible() and now - self.last_beacon > 2:
            self.last_beacon = now
            self._send({"type": "hello"})
        if self.scanning and now - self.last_probe > 3:
            self.last_probe = now
            self._send({"type": "probe"})
        if self.scanning and self.manual_ips() and not self.manual_busy and now - self.last_manual > 4:
            self.last_manual = now
            self.manual_busy = True
            threading.Thread(target=self._check_manual, daemon=True).start()
        if now - self.last_expire > 2:
            self.last_expire = now
            with self.lock:
                gone = [k for k, p in self.peers.items() if now - p["seen"] > (12 if p.get("manual") else 8)]
                for k in gone:
                    del self.peers[k]
            if gone:
                GLib.idle_add(self.win.on_peers_changed)

    # ---------- sending
    def send(self, peer, paths, progress, done):
        def work():
            try:
                result = self._send_files(peer, files_for_sending(paths), progress)
            except (OSError, ValueError, KeyError) as ex:
                result = (f"Couldn't reach {peer['name']}. Check that both computers are on the same Wi-Fi "
                          f"and that its firewall allows Arckad-D. ({ex})")
            GLib.idle_add(done, peer, result)
        threading.Thread(target=work, daemon=True).start()

    def _send_files(self, peer, files, progress):
        import http.client
        if not files:
            return "There are no files to send (empty folders are skipped)."
        total = sum(f[2] for f in files)
        offer = {"name": self.name(), "os": OS_NAME, "id": self.id,
                 "files": [{"path": rel, "size": size} for _, rel, size in files]}
        GLib.idle_add(progress, 0, total, f"Waiting for {peer['name']} to accept…")
        conn = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=100)
        conn.request("POST", "/offer", json.dumps(offer).encode(), {"Content-Type": "application/json"})
        resp = conn.getresponse()
        reply = json.loads(resp.read() or b"{}")
        conn.close()
        if not reply.get("ok"):
            if reply.get("reason") == "declined":
                return f"{peer['name']} declined or didn't answer."
            return f"{peer['name']} couldn't receive: {reply.get('reason', 'unknown reason')}."
        token, sent, last = reply["token"], 0, 0
        for i, (src, rel, size) in enumerate(files):
            conn = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=60)
            conn.putrequest("PUT", f"/upload/{token}/{i}")
            conn.putheader("Content-Length", str(size))
            conn.endheaders()
            remaining = size
            with open(src, "rb") as f:
                while remaining > 0:
                    chunk = f.read(min(1 << 18, remaining))
                    if not chunk:
                        break
                    conn.send(chunk)
                    remaining -= len(chunk)
                    sent += len(chunk)
                    if time.time() - last > 0.2:
                        last = time.time()
                        GLib.idle_add(progress, sent, total, f"Sending {rel}…")
            r = conn.getresponse()
            r.read()
            conn.close()
            if r.status != 200 or remaining:
                return f"Sending stopped at {rel}."
        conn = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=30)
        conn.request("POST", f"/done/{token}", b"")
        conn.getresponse().read()
        conn.close()
        GLib.idle_add(progress, total, total, "Done")
        return None


# ---------------------------------------------------------------- the Share window
class ShareWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title="Share", transient_for=win)
        self.set_default_size(600, 860)
        self.win, self.share, self.nearby = win, win.share, win.nearby
        self.sending = False
        self.connect("delete-event", lambda *_: self.hide() or True)   # keeps sharing in the background
        self.connect("map", lambda *_: self.on_mapped())
        self.connect("unmap", lambda *_: self.nearby.stop_scan())
        hb = Gtk.HeaderBar(show_close_button=True, title="Send & Receive",
                           subtitle="Share files with computers and phones on your Wi-Fi")
        self.set_titlebar(hb)
        self.tabs = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE, vhomogeneous=False)
        hb.set_custom_title(Gtk.StackSwitcher(stack=self.tabs))
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        Gtk.Window.add(self, scroll)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=14)
        scroll.add(outer)
        outer.add(self.tabs)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)          # Send tab
        recv = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)         # Receive tab
        self.tabs.add_titled(box, "send", "📤  Send")
        self.tabs.add_titled(recv, "receive", "📥  Receive")
        self.tabs.add_titled(self._paired_page(), "paired", "🔗  Paired")

        # ---- files
        head = Gtk.Box(spacing=6)
        lbl = Gtk.Label(xalign=0, hexpand=True)
        lbl.set_markup("<b>Files to send</b>")
        head.pack_start(lbl, True, True, 0)
        add_sel = Gtk.Button(label="Add selected")
        add_sel.set_tooltip_text("Add the files selected in Arckad-D")
        add_sel.connect("clicked", lambda *_: self.add_paths(self.win.active.selected_paths()))
        head.add(add_sel)
        add_files = Gtk.Button(label="Add files…")
        add_files.connect("clicked", self.on_add_files)
        head.add(add_files)
        remove = Gtk.Button(label="Remove")
        remove.connect("clicked", self.on_remove)
        head.add(remove)
        box.add(head)
        self.store = Gtk.ListStore(Gio.Icon, str, str, str)    # icon, name, size, path
        self.view = Gtk.TreeView(model=self.store, headers_visible=False)
        self.view.get_selection().set_mode(Gtk.SelectionMode.MULTIPLE)
        col = Gtk.TreeViewColumn()
        ir = Gtk.CellRendererPixbuf()
        col.pack_start(ir, False)
        col.add_attribute(ir, "gicon", 0)
        tr = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE)
        col.pack_start(tr, True)
        col.add_attribute(tr, "text", 1)
        col.set_expand(True)
        self.view.append_column(col)
        self.view.append_column(Gtk.TreeViewColumn("", Gtk.CellRendererText(xalign=1), text=2))
        fs = Gtk.ScrolledWindow()
        fs.set_size_request(-1, 120)
        fs.add(self.view)
        frame = Gtk.Frame()
        frame.add(fs)
        box.add(frame)

        # ---- how to send: tabs
        self.pages = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        switcher = Gtk.StackSwitcher(stack=self.pages, halign=Gtk.Align.CENTER, margin_top=6)
        box.add(Gtk.Label(label="Send to:", xalign=0, margin_top=4))
        box.add(switcher)
        box.add(self.pages)
        self.pages.add_titled(self._nearby_page(), "nearby", "📡  Arckad-D devices")
        self.pages.add_titled(self._link_page(), "link", "🔗  Any browser (link & QR)")

        # ---- receiving (its own tab)
        box = recv
        big = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin_top=6)
        big.set_markup("<big><b>Receive files</b></big>\nTurn this on, then send from Arckad-D on another "
                       "computer or phone. You'll be asked before anything is saved.")
        box.add(big)
        rhead = Gtk.Box(spacing=10, margin_top=6)
        rl = Gtk.Label(xalign=0, hexpand=True, wrap=True)
        rl.set_markup("<b>Let nearby devices find me</b>\n<small>Stays on for the time you choose, "
                      "then turns itself off</small>")
        rhead.pack_start(rl, True, True, 0)
        self.vis_minutes = Gtk.ComboBoxText()
        for m in SHARE_MINUTES:
            self.vis_minutes.append_text(f"{m} min")
        self.vis_minutes.set_active(SHARE_MINUTES.index(win.cfg.get("visible_minutes", 10)))
        self.vis_minutes.set_valign(Gtk.Align.CENTER)
        self.vis_minutes.connect("changed", self.on_vis_minutes)
        rhead.add(self.vis_minutes)
        self.vis_switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.vis_switch.connect("state-set", self.on_vis_switch)
        rhead.add(self.vis_switch)
        box.add(rhead)
        self.vis_state = Gtk.Label(xalign=0, wrap=True)
        box.add(self.vis_state)
        name_row = Gtk.Box(spacing=6)
        name_row.add(Gtk.Label(label="This computer's name:"))
        self.name_entry = Gtk.Entry(text=self.nearby.name(), hexpand=True)
        self.name_entry.connect("changed", self.on_name_changed)
        name_row.pack_start(self.name_entry, True, True, 0)
        open_recv = Gtk.Button(label="Open received files")
        open_recv.set_tooltip_text(short(received_dir()))
        open_recv.connect("clicked", lambda *_: self.win.open_path(str(received_dir())))
        name_row.add(open_recv)
        box.add(name_row)
        addr_row = Gtk.Box(spacing=6)
        self.addr_label = Gtk.Label(xalign=0, hexpand=True, wrap=True, selectable=True)
        addr_row.pack_start(self.addr_label, True, True, 0)
        copy_addr = Gtk.Button(label="Copy")
        copy_addr.set_tooltip_text("Copy this address, to paste into a chat or read out")
        copy_addr.connect("clicked", lambda *_: self.win.copy_text(lan_addresses()[0]))
        addr_row.add(copy_addr)
        box.add(addr_row)
        box.add(self._firewall_bar())
        box = outer

        # ---- activity (shared by both tabs)
        lbl2 = Gtk.Label(xalign=0, margin_top=6)
        lbl2.set_markup("<b>Activity</b>")
        box.add(lbl2)
        self.log = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                left_margin=6, top_margin=6)
        ls = Gtk.ScrolledWindow()
        ls.set_size_request(-1, 100)
        ls.add(self.log)
        lframe = Gtk.Frame()
        lframe.add(ls)
        box.add(lframe)
        note = Gtk.Label(xalign=0, wrap=True)
        note.set_markup("<small>🔒 Everything stays on your <b>local network</b>; nothing is uploaded to the "
                        "internet. Nobody can send you files unless you click <b>Accept</b>, and sharing "
                        "turns itself off when its timer ends.</small>")
        note.get_style_context().add_class("dim-label")
        box.add(note)
        self.refresh()
        self.refresh_peers()

    # ---------- nearby page
    def _nearby_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6)
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup("Other computers running Arckad-D on this Wi-Fi appear here when their "
                         "<b>Receive</b> switch is on. Click <b>Send</b>; they get a pop-up to accept.")
        page.add(intro)
        self.peer_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=18)
        sp = Gtk.Spinner()
        sp.start()
        placeholder.add(sp)
        ph = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        ph.set_markup("Looking for nearby devices…\n<small>On the other computer, open Arckad-D → Share and "
                      "turn on <b>Receive</b>.</small>")
        ph.get_style_context().add_class("dim-label")
        placeholder.add(ph)
        placeholder.show_all()
        self.peer_box.set_placeholder(placeholder)
        pframe = Gtk.Frame()
        pframe.add(self.peer_box)
        page.add(pframe)
        self.progress = Gtk.ProgressBar(show_text=True)
        self.progress.set_no_show_all(True)
        page.add(self.progress)

        ip_head = Gtk.Label(xalign=0, wrap=True, margin_top=6)
        ip_head.set_markup("<b>On another network or VLAN?</b>  Add its IP address (Receive must be on there).")
        page.add(ip_head)
        ip_row = Gtk.Box(spacing=6)
        self.ip_entry = Gtk.Entry(placeholder_text="IP address, e.g. 10.20.5.14", hexpand=True)
        self.ip_entry.connect("activate", lambda *_: self.add_ip())
        ip_row.pack_start(self.ip_entry, True, True, 0)
        self.ip_btn = Gtk.Button(label="Add")
        self.ip_btn.connect("clicked", lambda *_: self.add_ip())
        ip_row.add(self.ip_btn)
        page.add(ip_row)
        self.ip_status = Gtk.Label(xalign=0, wrap=True)
        self.ip_status.get_style_context().add_class("dim-label")
        page.add(self.ip_status)
        self.saved_box = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=4,
                                     column_spacing=6, row_spacing=6)
        page.add(self.saved_box)
        self.my_addr = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.my_addr.get_style_context().add_class("dim-label")
        page.add(self.my_addr)
        self.refresh_saved()
        return page

    def refresh_saved(self):
        for c in self.saved_box.get_children():
            self.saved_box.remove(c)
        for host in self.nearby.manual_ips():
            chip = Gtk.Box(spacing=2)
            chip.add(Gtk.Label(label=host))
            x = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
            x.set_relief(Gtk.ReliefStyle.NONE)
            x.set_tooltip_text(f"Forget {host}")
            x.connect("clicked", lambda _b, h=host: self.remove_ip(h))
            chip.add(x)
            self.saved_box.add(chip)
        self.saved_box.show_all()

    def remove_ip(self, host):
        self.win.cfg["manual_ips"] = [h for h in self.nearby.manual_ips() if h != host]
        write_json(CONFIG_FILE, self.win.cfg)
        self.refresh_saved()

    def add_ip(self):
        host = self.ip_entry.get_text().strip()
        if not host or " " in host:
            return
        self.ip_btn.set_sensitive(False)
        self.ip_status.set_text(f"Checking {host}…")

        def work():
            peer, reason = self.nearby.hello_at(host)
            GLib.idle_add(done, peer, reason)

        def done(peer, reason):
            self.ip_btn.set_sensitive(True)
            if peer:
                ips = self.nearby.manual_ips()
                if host not in ips:
                    self.win.cfg["manual_ips"] = ips + [host]
                    write_json(CONFIG_FILE, self.win.cfg)
                self.ip_entry.set_text("")
                self.ip_status.set_text(f"✓ Found {peer['name']} ({peer['os']}) at {host}. It's saved and appears "
                                        "above whenever its Receive is on.")
                self.refresh_saved()
                self.refresh_peers()
            else:
                self.ip_status.set_text(f"✗ No Arckad-D answered at {host} ({reason}). On that device: open Arckad-D "
                                        "and turn Receive on. The firewall must allow TCP ports 47821–47823 "
                                        "between the networks (a working ping isn't enough).")
            return False
        threading.Thread(target=work, daemon=True).start()

    def refresh_peers(self):
        for row in self.peer_box.get_children():
            self.peer_box.remove(row)
        for peer in self.nearby.peer_list():
            row = Gtk.Box(spacing=10, margin=8)
            icon = Gtk.Image.new_from_icon_name("computer-symbolic", Gtk.IconSize.DND)
            row.add(icon)
            lbl = Gtk.Label(xalign=0, hexpand=True)
            how = " · by IP" if peer.get("manual") else ""
            lbl.set_markup(f"<b>{esc(peer['name'])}</b>\n<small>{esc(peer['os'])} · {esc(peer['ip'])}{how}</small>")
            row.pack_start(lbl, True, True, 0)
            btn = Gtk.Button(label="Send")
            btn.get_style_context().add_class("suggested-action")
            btn.set_sensitive(not self.sending)
            btn.connect("clicked", lambda _b, p=peer: self.send_to(p))
            row.add(btn)
            self.peer_box.add(row)
        self.peer_box.show_all()

    def send_to(self, peer):
        paths = self.share.snapshot()
        if not paths:
            self.win.info("Add some files first (Add selected / Add files…), then click Send.")
            return
        self.sending = True
        self.refresh_peers()
        self.progress.show()
        self.progress.set_fraction(0)
        self.log_line(f"Offering {len(paths)} item{'s' if len(paths) != 1 else ''} to {peer['name']}…")
        self.nearby.send(peer, paths, self.on_send_progress, self.on_send_done)

    def on_send_progress(self, sent, total, text):
        self.progress.set_fraction(sent / total if total else 1)
        self.progress.set_text(f"{text}  {human_size(sent)} / {human_size(total)}")
        return False

    def on_send_done(self, peer, error):
        self.sending = False
        self.refresh_peers()
        if error:
            self.progress.set_text(error)
            self.log_line("⚠ " + error)
        else:
            self.progress.set_fraction(1)
            self.progress.set_text(f"Sent to {peer['name']} ✓")
            self.log_line(f"✓ Sent everything to {peer['name']}")
            self.win.active.flash(f"Sent to {peer['name']}")
        return False

    # ---------- paired devices page (private, encrypted; separate from Nearby and Quick Share)
    def _paired_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup("<big><b>Paired devices</b></big>\nPair once with a 6-digit code. After that, paired devices "
                         "find each other by themselves, even after a restart or when their IP address changes. "
                         "They're invisible to everyone else, and every file is <b>encrypted</b>.")
        page.add(intro)
        self.pair_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        ph = Gtk.Label(label="No paired devices yet. Pair one below.", margin=16)
        ph.get_style_context().add_class("dim-label")
        ph.show()
        self.pair_list.set_placeholder(ph)
        frame = Gtk.Frame()
        frame.add(self.pair_list)
        page.add(frame)
        hint = Gtk.Label(xalign=0, wrap=True)
        hint.set_markup("<small>“Send” sends the files listed on the <b>Send</b> tab.</small>")
        hint.get_style_context().add_class("dim-label")
        page.add(hint)
        self.pair_progress = Gtk.ProgressBar(show_text=True)
        self.pair_progress.set_no_show_all(True)
        page.add(self.pair_progress)

        page.add(self._firewall_bar())
        page.add(Gtk.Separator(margin_top=6))
        head = Gtk.Label(xalign=0)
        head.set_markup("<b>Pair a new device</b>")
        page.add(head)
        btns = Gtk.Box(spacing=8, homogeneous=True)
        show_code = Gtk.Button(label="Show a pairing code")
        show_code.get_style_context().add_class("suggested-action")
        show_code.connect("clicked", lambda *_: self.show_pair_code())
        enter_code = Gtk.Button(label="I have a code")
        enter_code.connect("clicked", lambda *_: self.toggle_code_entry())
        btns.add(show_code)
        btns.add(enter_code)
        page.add(btns)
        self.code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.code_label = Gtk.Label(selectable=True)
        self.code_info = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.code_box.add(self.code_label)
        self.code_box.add(self.code_info)
        cancel = Gtk.Button(label="Stop pairing", halign=Gtk.Align.CENTER)
        cancel.connect("clicked", lambda *_: self.stop_pair_code())
        self.code_box.add(cancel)
        self.code_box.set_no_show_all(True)
        page.add(self.code_box)
        self.code_entry_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        row = Gtk.Box(spacing=6)
        self.code_entry = Gtk.Entry(placeholder_text="6-digit code", max_length=6, width_chars=10)
        self.code_entry.set_input_purpose(Gtk.InputPurpose.DIGITS)
        self.code_entry.connect("activate", lambda *_: self.do_pair())
        self.code_ip = Gtk.Entry(placeholder_text="its IP (only if on another network)", hexpand=True)
        self.pair_btn = Gtk.Button(label="Pair")
        self.pair_btn.get_style_context().add_class("suggested-action")
        self.pair_btn.connect("clicked", lambda *_: self.do_pair())
        row.add(self.code_entry)
        row.pack_start(self.code_ip, True, True, 0)
        row.add(self.pair_btn)
        self.code_entry_box.add(row)
        self.pair_status = Gtk.Label(xalign=0, wrap=True)
        self.code_entry_box.add(self.pair_status)
        self.code_entry_box.set_no_show_all(True)
        page.add(self.code_entry_box)
        self.refresh_pairs()
        return page

    def toggle_code_entry(self):
        """Show / hide the code box. (It starts hidden, so its contents must be revealed too.)"""
        if self.code_entry_box.get_visible():
            self.code_entry_box.hide()
            return
        self.code_entry_box.set_no_show_all(False)
        self.code_entry_box.show_all()
        self.pair_status.set_text("Type the 6-digit code shown on the other device.")
        self.code_entry.grab_focus()

    def _firewall_bar(self):
        """Shown when a firewall is probably blocking sharing, with a one-click fix."""
        bar = Gtk.Box(spacing=8)
        lbl = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        kind = "Windows Firewall" if IS_WIN else "Ubuntu's firewall (ufw)"
        lbl.set_markup(f"🛡 <b>{kind} is on</b> and may block other devices from finding this one.")
        btn = Gtk.Button(label="Allow through firewall")
        btn.set_tooltip_text("Asks for your password once, then lets Arckad-D's sharing ports through")
        bar.pack_start(lbl, True, True, 0)
        bar.add(btn)
        bar.set_no_show_all(True)
        self.firewall_bars = getattr(self, "firewall_bars", []) + [bar]

        def clicked(_b):
            btn.set_sensitive(False)
            lbl.set_markup("🛡 Waiting for your permission…")

            def done(ok, msg):
                btn.set_sensitive(True)
                if ok:
                    for b in self.firewall_bars:
                        b.hide()
                    self.win.cfg["firewall_opened"] = True
                    write_json(CONFIG_FILE, self.win.cfg)
                    self.log_line("🛡 " + msg)
                else:
                    lbl.set_markup(f"🛡 {esc(msg)}")
                return False
            open_firewall(done)
        btn.connect("clicked", clicked)

        def check():
            blocking = firewall_blocking()
            GLib.idle_add(lambda: (bar.set_no_show_all(False), bar.show_all()) if blocking and not
                          (blocking == "ufw" and self.win.cfg.get("firewall_opened")) else None)
        threading.Thread(target=check, daemon=True).start()
        return bar

    def refresh_pairs(self):
        pr = self.win.paired
        for r in self.pair_list.get_children():
            self.pair_list.remove(r)
        for p in sorted(pr.pairs(), key=lambda x: x["name"].lower()):
            online = pr.is_online(p["id"])
            row = Gtk.Box(spacing=10, margin=8)
            icon = "phone-symbolic" if p.get("os") == "Android" else "computer-symbolic"
            row.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.DND))
            lbl = Gtk.Label(xalign=0, hexpand=True, wrap=True)
            ip = (pr.online.get(p["id"]) or {}).get("ip") or p.get("last_ip") or "?"
            state = (f"<span foreground='#2ec27e'>● Online</span> · {esc(ip)}" if online
                     else f"<span foreground='#9a9996'>● Offline</span> · last seen at {esc(ip)}")
            lbl.set_markup(f"<b>{esc(p['name'])}</b>  <small>🔒 {esc(p.get('os', ''))}</small>\n<small>{state}</small>")
            row.pack_start(lbl, True, True, 0)
            auto = Gtk.CheckButton(label="Auto-accept")
            auto.set_tooltip_text(f"Save files from {p['name']} without asking")
            auto.set_active(bool(p.get("auto_accept")))
            auto.connect("toggled", lambda b, pid=p["id"]: self.set_auto_accept(pid, b.get_active()))
            row.add(auto)
            send = Gtk.Button(label="Send")
            send.get_style_context().add_class("suggested-action")
            send.set_sensitive(online and not getattr(self, "pair_sending", False))
            send.set_tooltip_text("Send the files on the Send tab" if online else "Waiting for it to come online")
            send.connect("clicked", lambda _b, pid=p["id"]: self.send_paired(pid))
            row.add(send)
            detach = Gtk.Button(label="Detach")
            detach.connect("clicked", lambda _b, pid=p["id"], n=p["name"]: self.detach_pair(pid, n))
            row.add(detach)
            self.pair_list.add(row)
        self.pair_list.show_all()

    def set_auto_accept(self, pid, on):
        p = self.win.paired.pair(pid)
        if p:
            p["auto_accept"] = on
            self.win.paired.save()

    def show_pair_code(self):
        try:
            code = self.win.paired.new_code()
        except OSError as ex:
            self.win.error(f"Couldn't start pairing: {ex}")
            return
        self.code_label.set_markup(f"<span size='xx-large' weight='bold' letter_spacing='6000'>{code[:3]} {code[3:]}</span>")
        self.code_box.set_no_show_all(False)
        self.code_box.show_all()
        self.code_entry_box.hide()
        self._tick_code()
        GLib.timeout_add_seconds(1, self._tick_code)

    def _tick_code(self):
        pr = self.win.paired
        if not pr.code_active():
            self.code_box.hide()
            return False
        left = int(pr.code_until - time.time())
        ips = [ip for ip in lan_addresses() if not ip.startswith("127.")]
        self.code_info.set_markup(f"On the other device: <b>Paired → I have a code</b>, and type this code.\n"
                                  f"<small>Valid for {left // 60}:{left % 60:02d} · this computer is "
                                  f"{esc(ips[0] if ips else '?')} (needed only from another network)</small>")
        return True

    def stop_pair_code(self):
        self.win.paired.cancel_code()
        self.code_box.hide()

    def do_pair(self):
        code = "".join(c for c in self.code_entry.get_text() if c.isdigit())
        if len(code) != 6:
            self.pair_status.set_text("The code has 6 digits.")
            return
        host = self.code_ip.get_text().strip() or None
        self.pair_btn.set_sensitive(False)
        self.pair_status.set_text("Looking for the device showing this code…")

        def work():
            ok, msg = self.win.paired.guest_pair(code, host)
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            self.pair_btn.set_sensitive(True)
            if ok:
                self.pair_status.set_text(f"✓ Paired with {msg}. It will connect by itself from now on.")
                self.code_entry.set_text("")
                self.code_ip.set_text("")
                self.log_line(f"🔗 Paired with {msg}")
            else:
                self.pair_status.set_text(f"✗ {msg}")
            self.refresh_pairs()
            return False
        threading.Thread(target=work, daemon=True).start()

    def detach_pair(self, pid, name):
        if not self.win.confirm(f"Detach {name}?\n\nThe two devices stop connecting to each other. "
                                "To share again, pair with a new code.", parent=self):
            return

        def work():
            told = self.win.paired.detach(pid)
            GLib.idle_add(done, told)

        def done(told):
            self.log_line(f"Detached {name}" + ("" if told else " (it was offline: it detaches there when it next connects)"))
            self.refresh_pairs()
            return False
        threading.Thread(target=work, daemon=True).start()

    def send_paired(self, pid):
        paths = self.share.snapshot()
        if not paths:
            self.win.info("Add some files on the Send tab first (Add selected / Add files…), then click Send here.")
            return
        self.pair_sending = True
        self.refresh_pairs()
        self.pair_progress.show()
        self.pair_progress.set_fraction(0)
        self.win.paired.send(pid, paths, self.on_pair_progress, self.on_pair_done)

    def on_pair_progress(self, sent, total, text):
        self.pair_progress.set_fraction(sent / total if total else 1)
        self.pair_progress.set_text(f"{text}  {human_size(sent)} / {human_size(total)}")
        return False

    def on_pair_done(self, pid, error):
        self.pair_sending = False
        p = self.win.paired.pair(pid)
        name = p["name"] if p else "the paired device"
        if error:
            self.pair_progress.set_text(error)
            self.log_line("⚠ " + error)
        else:
            self.pair_progress.set_fraction(1)
            self.pair_progress.set_text(f"Sent to {name} ✓ (encrypted)")
            self.log_line(f"✓ Sent to {name} (encrypted)")
        self.refresh_pairs()
        return False

    # ---------- link page
    def _link_page(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=6)
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup("For phones or computers <b>without</b> Arckad-D: they open a link or scan a QR "
                         "code in any browser and download the files.")
        page.add(intro)
        top = Gtk.Box(spacing=10)
        t = Gtk.Label(xalign=0, hexpand=True)
        t.set_markup("<b>Share as a link</b>")
        top.pack_start(t, True, True, 0)
        self.minutes = Gtk.ComboBoxText()
        for m in SHARE_MINUTES:
            self.minutes.append_text(f"{m} min")
        self.minutes.set_active(SHARE_MINUTES.index(self.win.cfg.get("share_minutes", 10)))
        self.minutes.connect("changed", self.on_minutes_changed)
        top.add(self.minutes)
        self.switch = Gtk.Switch(valign=Gtk.Align.CENTER)
        self.switch.connect("state-set", self.on_switch)
        top.add(self.switch)
        page.add(top)
        self.state = Gtk.Label(xalign=0, wrap=True)
        page.add(self.state)
        self.link_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.qr = Gtk.Image()
        self.link_box.add(self.qr)
        self.qr_hint = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.qr_hint.get_style_context().add_class("dim-label")
        self.link_box.add(self.qr_hint)
        row = Gtk.Box(spacing=6)
        self.link = Gtk.Entry(editable=False, hexpand=True)
        row.pack_start(self.link, True, True, 0)
        copy = Gtk.Button(label="Copy link")
        copy.connect("clicked", lambda *_: self.win.copy_text(self.link.get_text()))
        row.add(copy)
        open_b = Gtk.Button(label="Open")
        open_b.set_tooltip_text("Open the share page in your own browser")
        open_b.connect("clicked", lambda *_: open_default(self.link.get_text()))
        row.add(open_b)
        self.link_box.add(row)
        self.other_ips = Gtk.Label(xalign=0, wrap=True, selectable=True)
        self.other_ips.get_style_context().add_class("dim-label")
        self.link_box.add(self.other_ips)
        self.link_box.set_no_show_all(True)
        page.add(self.link_box)
        return page

    # ---------- files
    def add_paths(self, paths):
        paths = [p for p in paths if p and os.path.exists(p)]
        if not paths:
            self.win.info("Select some files in Arckad-D first, then click “Add selected”.")
            return
        self.share.add(paths)
        self.refresh()

    def on_add_files(self, *_):
        dlg = Gtk.FileChooserNative.new("Add files", self, Gtk.FileChooserAction.OPEN, "Add", "Cancel")
        dlg.set_select_multiple(True)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.add_paths(dlg.get_filenames())
        dlg.destroy()

    def on_remove(self, *_):
        model, rows = self.view.get_selection().get_selected_rows()
        self.share.remove([model[r][3] for r in rows])
        self.refresh()

    def refresh(self):
        self.store.clear()
        for p in self.share.snapshot():
            is_dir = os.path.isdir(p)
            try:
                size = "folder" if is_dir else human_size(os.path.getsize(p))
            except OSError:
                continue
            self.store.append([icon_for(p, is_dir), os.path.basename(p.rstrip("/\\")), size, p])
        self.update_state()

    def refresh_addresses(self):
        ips = [ip for ip in lan_addresses() if not ip.startswith("127.")]
        if not ips:
            self.addr_label.set_markup("<b>This computer's IP address:</b> not connected to a network")
            self.my_addr.set_text("")
            return
        extra = f"  <small>(also {esc(', '.join(ips[1:]))})</small>" if len(ips) > 1 else ""
        self.addr_label.set_markup(f"<b>This computer's IP address:</b>  <big><b>{esc(ips[0])}</b></big>{extra}\n"
                                   "<small>On another network or VLAN, the sender types this under Send.</small>")
        self.my_addr.set_markup(f"<small>This computer is <b>{esc(ips[0])}</b>"
                                + (f" (also {esc(', '.join(ips[1:]))})" if len(ips) > 1 else "") + "</small>")

    def on_mapped(self):
        self.refresh_addresses()
        try:
            self.nearby.start_scan()
        except OSError as ex:
            self.log_line(f"⚠ Can't look for nearby devices ({ex}). Is another program using port "
                          f"{NEARBY_UDP_PORT}?")

    # ---------- link sharing on / off
    def on_minutes_changed(self, combo):
        minutes = SHARE_MINUTES[combo.get_active()]
        self.win.cfg["share_minutes"] = minutes
        if self.share.active():
            self.share.extend(minutes)
            self.log_line(f"Link timer reset to {minutes} min")
            self.update_state()

    def on_switch(self, switch, on):
        if on and not self.share.active():
            if not self.share.snapshot():
                self.win.info("Add at least one file first.")
                GLib.idle_add(lambda: switch.set_active(False) or False)
                return True
            if not self.win.start_share(SHARE_MINUTES[self.minutes.get_active()]):
                GLib.idle_add(lambda: switch.set_active(False) or False)
                return True
        elif not on and self.share.active():
            self.win.stop_share()
        switch.set_state(on)
        self.update_state()
        return True

    # ---------- receiving on / off
    def on_vis_minutes(self, combo):
        minutes = SHARE_MINUTES[combo.get_active()]
        self.win.cfg["visible_minutes"] = minutes
        if self.nearby.visible():
            self.nearby.set_visible(minutes)
            self.update_state()

    def on_vis_switch(self, switch, on):
        if on and not self.nearby.visible():
            if not self.win.start_visible(SHARE_MINUTES[self.vis_minutes.get_active()]):
                GLib.idle_add(lambda: switch.set_active(False) or False)
                return True
        elif not on and self.nearby.visible():
            self.win.stop_visible()
        switch.set_state(on)
        self.update_state()
        return True

    def on_name_changed(self, entry):
        self.win.cfg["device_name"] = entry.get_text().strip()

    @staticmethod
    def _sync_switch(switch, handler, active):
        if switch.get_active() != active:
            switch.handler_block_by_func(handler)
            switch.set_active(active)
            switch.set_state(active)
            switch.handler_unblock_by_func(handler)

    def update_state(self):
        active = self.share.active()
        self._sync_switch(self.switch, self.on_switch, active)
        n = len(self.share.snapshot())
        if active:
            left = self.share.remaining()
            self.state.set_markup(f"🟢 <b>On</b>, link ends in <b>{left // 60}:{left % 60:02d}</b> · "
                                  f"{n} item{'s' if n != 1 else ''}")
        else:
            self.state.set_markup("⚪ <b>Off</b>. Turn the switch on to get a link and QR code.")
        if active and not self.link_box.get_visible():
            ips = lan_addresses()
            url = self.share.url(ips[0])
            self.link.set_text(url)
            pb = qr_pixbuf(url)
            if pb:
                self.qr.set_from_pixbuf(pb)
                self.qr_hint.set_text("Scan with a phone camera, or open the link in any browser on the same "
                                      "network.")
            else:
                self.qr_hint.set_text("Open this link in any browser on the same network.\n"
                                      + ("" if IS_WIN else "(For a QR code: sudo apt install qrencode)"))
            others = [self.share.url(ip) for ip in ips[1:]]
            self.other_ips.set_text(("If that doesn't work, try: " + "   ".join(others)) if others else "")
            self.link_box.set_no_show_all(False)
            self.link_box.show_all()
            if not pb:
                self.qr.hide()
        elif not active and self.link_box.get_visible():
            self.link_box.hide()
            self.link_box.set_no_show_all(True)

        visible = self.nearby.visible()
        if time.time() - getattr(self, "_addr_at", 0) > 10:      # the address can change (Wi-Fi ↔ cable)
            self._addr_at = time.time()
            self.refresh_addresses()
        self._sync_switch(self.vis_switch, self.on_vis_switch, visible)
        if visible:
            left = self.nearby.remaining()
            self.vis_state.set_markup(f"🟢 Visible as <b>{esc(self.nearby.name())}</b> for "
                                      f"<b>{left // 60}:{left % 60:02d}</b>. Files you accept go to "
                                      f"<i>{esc(short(received_dir()))}</i>")
        else:
            self.vis_state.set_markup("⚪ <b>Not visible.</b> Turn on to let other Arckad-D computers send you files.")

    def log_line(self, text):
        buf = self.log.get_buffer()
        buf.insert(buf.get_end_iter(), f"{datetime.now().strftime('%H:%M:%S')}  {text}\n")
        self.log.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)


# ---------------------------------------------------------------- Paired devices (private, encrypted)
# Separate from Quick Share and Nearby: own ports, no open discovery. Two devices pair once with a
# 6-digit code (Diffie-Hellman key exchange, confirmed by the code on both sides); afterwards they find
# each other by secret beacons (works after restarts and IP changes) and every request and file is
# encrypted and authenticated with the shared key. Detach forgets the key on both sides.
import hmac as hmacmod

PAIR_UDP_PORT = 47830
PAIR_TCP_PORTS = (47831, 47832, 47833, 0)
PAIR_CODE_SECONDS = 120
DH_P = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD129024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3DC2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF", 16)                       # RFC 3526 group 14 (2048-bit safe prime)


FIREWALL_PORTS = {"udp": ["47820", "47830"], "tcp": ["47821:47823", "47831:47833", "8765:8767"]}


def firewall_blocking():
    """A firewall that probably blocks Arckad-D's sharing and hasn't been opened for it: "ufw", "windows" or None."""
    if IS_WIN:
        try:
            out = subprocess.run(["netsh", "advfirewall", "firewall", "show", "rule", "name=Arckad-D"],
                                 capture_output=True, text=True, errors="replace", timeout=8,
                                 creationflags=0x08000000).stdout
            return None if "Arckad-D" in out and "Allow" in out else "windows"
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        conf = Path("/etc/ufw/ufw.conf").read_text()
    except OSError:
        return None
    if "ENABLED=yes" not in conf.replace(" ", ""):
        return None
    try:
        rules = Path("/etc/ufw/user.rules").read_text()          # usually only root can read it
        return None if "47831" in rules else "ufw"
    except OSError:
        return "ufw"


def open_firewall(done):
    """Ask for the administrator password once and let Arckad-D's sharing through the firewall.
    Calls done(ok, message) on the main thread."""
    def work():
        try:
            if IS_WIN:
                exe = sys.executable
                script = Path(tempfile.gettempdir()) / "arckad-d-firewall.ps1"
                script.write_text(
                    "Remove-NetFirewallRule -DisplayName 'Arckad-D' -ErrorAction SilentlyContinue\n"
                    f"New-NetFirewallRule -DisplayName 'Arckad-D' -Direction Inbound -Program '{exe.replace(chr(39), chr(39) * 2)}' "
                    "-Action Allow -Profile Any | Out-Null\n", encoding="utf-8")
                arg = str(script).replace("'", "''")
                proc = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     f"$p = Start-Process powershell.exe -Verb RunAs -Wait -PassThru -WindowStyle Hidden "
                     f"-ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','\"{arg}\"'; exit $p.ExitCode"],
                    capture_output=True, text=True, errors="replace", timeout=300, creationflags=0x08000000)
                ok = proc.returncode == 0 and firewall_blocking() is None
                msg = "Arckad-D is now allowed through Windows Firewall." if ok else \
                    "Windows Firewall wasn't changed (the permission request was cancelled or failed)."
            else:
                cmds = [f"ufw allow {p}/{proto} comment Arckad-D" for proto, ports in FIREWALL_PORTS.items() for p in ports]
                proc = subprocess.run(["pkexec", "sh", "-c", " && ".join(cmds)], capture_output=True, text=True,
                                      errors="replace", timeout=300)
                ok = proc.returncode == 0
                msg = "Ubuntu's firewall now lets Arckad-D's sharing through." if ok else \
                    "The firewall wasn't changed: " + ((proc.stderr or proc.stdout).strip()[-300:] or "cancelled")
        except (OSError, subprocess.SubprocessError) as ex:
            ok, msg = False, f"Couldn't change the firewall: {ex}"
        GLib.idle_add(done, ok, msg)
    threading.Thread(target=work, daemon=True).start()


def _hm(key, *parts):
    msg = b"|".join(p if isinstance(p, bytes) else str(p).encode("utf-8") for p in parts)
    return hmacmod.new(key, msg, hashlib.sha256).digest()


class StreamCipher:
    """Counter-mode keystream from SHA-256(key ‖ nonce ‖ counter), XORed with the data."""

    def __init__(self, key, nonce=b"\0" * 16):
        self.base = hashlib.sha256(key + nonce)
        self.counter = 0
        self.left = b""

    def apply(self, data):
        n = len(data)
        need = n - len(self.left)
        blocks = []
        while need > 0:
            h = self.base.copy()
            h.update(self.counter.to_bytes(8, "big"))
            blocks.append(h.digest())
            self.counter += 1
            need -= 32
        ks = self.left + b"".join(blocks)
        self.left = ks[n:]
        return (int.from_bytes(data, "big") ^ int.from_bytes(ks[:n], "big")).to_bytes(n, "big") if n else b""


def seal(key, data):
    """Encrypt + authenticate a small message: nonce ‖ ciphertext ‖ tag."""
    nonce = secrets.token_bytes(16)
    ct = StreamCipher(_hm(key, "seal-enc", nonce), nonce).apply(data)
    return nonce + ct + _hm(_hm(key, "seal-mac", nonce), nonce + ct)


def unseal(key, blob):
    if len(blob) < 48:
        raise ValueError("message too short")
    nonce, ct, tag = blob[:16], blob[16:-32], blob[-32:]
    if not hmacmod.compare_digest(tag, _hm(_hm(key, "seal-mac", nonce), nonce + ct)):
        raise ValueError("message not from the paired device")
    return StreamCipher(_hm(key, "seal-enc", nonce), nonce).apply(ct)


def beacon_tag(key, sender_id, bucket):
    return _hm(key, "beacon", sender_id, bucket).hex()[:24]


def make_pair_handler(pr):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Arckad-D"

        def log_message(self, *args):
            pass

        def _raw(self, code, body, ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _plain(self, code, obj):
            self._raw(code, json.dumps(obj).encode(), "application/json")

        def _body(self, limit=5_000_000):
            n = int(self.headers.get("Content-Length") or 0)
            if n < 0 or n > limit:
                raise ValueError("too large")
            return self.rfile.read(n) if n else b""

        def _auth(self):
            """The paired device that signed this request, or None."""
            pid = self.headers.get("X-Pair-From", "")
            pair = pr.pair(pid)
            if not pair:
                return None
            try:
                ts = int(self.headers.get("X-Pair-Time", "0"))
            except ValueError:
                return None
            if abs(time.time() - ts) > 600:
                return None
            sig = _hm(pr.key(pid), self.command, self.path, ts).hex()
            if not hmacmod.compare_digest(sig, self.headers.get("X-Pair-Sig", "")):
                return None
            pair["ip"] = self.client_address[0]
            pr.mark_seen(pid, self.client_address[0], pair.get("port"))
            return pair

        def do_POST(self):
            try:
                self._post()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass
            except ValueError:
                self._plain(400, {"ok": False})

        def do_PUT(self):
            try:
                self._put()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            try:
                path = self.path.split("?")[0]
                if path.startswith("/c/file/") and getattr(pr.win, "chat", None):
                    return pr.win.chat.handle_get(self, path)
                self._plain(404, {"ok": False})
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _post(self):
            path = self.path.split("?")[0]
            if (path.startswith("/c/") or path.startswith("/cj/")) and getattr(pr.win, "chat", None):
                return pr.win.chat.handle_post(self, path)
            if path == "/pair/start":                     # step 1: exchange keys (needs the code to be shown)
                if not pr.code_active():
                    return self._plain(403, {"ok": False, "reason": "no pairing code is shown on that device"})
                req = json.loads(self._body(100_000))
                reply = pr.host_start(req, self.client_address[0])
                return self._plain(200 if reply.get("ok") else 403, reply)
            if path == "/pair/confirm":                   # step 2: prove both know the code, user confirms
                req = json.loads(self._body(100_000))
                reply = pr.host_confirm(req, self.client_address[0])
                return self._plain(200 if reply.get("ok") else 403, reply)
            pair = self._auth()
            if pair is None:
                return self._plain(401, {"ok": False, "reason": "not paired"})
            key = pr.key(pair["id"])
            if path == "/p/hello":
                return self._raw(200, seal(key, json.dumps({"ok": True, "name": pr.name(), "os": OS_NAME,
                                                            "port": pr.port}).encode()))
            if path == "/p/detach":
                pr.forget(pair["id"], tell=False)
                pr.ui("on_pair_event", f"{pair['name']} detached from this device")
                return self._raw(200, seal(key, b'{"ok": true}'))
            if path == "/p/offer":
                offer = json.loads(unseal(key, self._body()))
                files = []
                for f in (offer.get("files") or [])[:20000]:
                    rel, size = safe_rel_parts(f.get("path", "")), f.get("size")
                    if rel is None or not isinstance(size, int) or size < 0:
                        return self._raw(400, seal(key, b'{"ok": false, "reason": "bad file name"}'))
                    files.append((rel, size))
                if not files:
                    return self._raw(400, seal(key, b'{"ok": false, "reason": "no files"}'))
                req = {"from": pair["name"], "os": pair.get("os", ""), "ip": self.client_address[0],
                       "files": files, "total": sum(s for _, s in files), "event": threading.Event(),
                       "accepted": False, "paired": True, "pair_id": pair["id"]}
                if pair.get("auto_accept"):
                    req["accepted"] = True
                    req["event"].set()
                else:
                    pr.ui("ask_incoming", req)
                    req["event"].wait(90)
                if not req["accepted"]:
                    return self._raw(403, seal(key, b'{"ok": false, "reason": "declined"}'))
                req["dest"] = plan_destinations(files)
                req["received"], req["done_files"] = 0, 0
                token = secrets.token_hex(12)
                pr.transfers[token] = req
                return self._raw(200, seal(key, json.dumps({"ok": True, "token": token}).encode()))
            parts = [p for p in path.split("/") if p]
            if len(parts) == 3 and parts[:2] == ["p", "done"]:
                req = pr.transfers.pop(parts[2], None)
                if not req:
                    return self._raw(404, seal(key, b'{"ok": false}'))
                pr.ui("on_nearby_received", req)
                return self._raw(200, seal(key, b'{"ok": true}'))
            return self._raw(404, seal(key, b'{"ok": false}'))

        def _put(self):
            pair = self._auth()
            if pair is None:
                return self._plain(401, {"ok": False, "reason": "not paired"})
            parts = [p for p in self.path.split("/") if p]
            if len(parts) != 4 or parts[:2] != ["p", "upload"] or not parts[3].isdigit():
                return self._plain(404, {"ok": False})
            req, i = pr.transfers.get(parts[2]), int(parts[3])
            if not req or i >= len(req["files"]) or req.get("pair_id") != pair["id"]:
                return self._plain(404, {"ok": False})
            size = req["files"][i][1]
            if int(self.headers.get("Content-Length") or -1) != size + 32:
                return self._plain(400, {"ok": False, "reason": "size mismatch"})
            key = pr.key(pair["id"])
            cipher = StreamCipher(_hm(key, "file", parts[2], i))
            mac = hmacmod.new(_hm(key, "file-mac", parts[2], i), digestmod=hashlib.sha256)
            dest = req["dest"][i]
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            left = size
            with open(tmp, "wb") as f:
                while left > 0:
                    chunk = self.rfile.read(min(1 << 18, left))
                    if not chunk:
                        break
                    mac.update(chunk)
                    f.write(cipher.apply(chunk))
                    left -= len(chunk)
                    req["received"] += len(chunk)
            tag = self.rfile.read(32)
            if left or not hmacmod.compare_digest(tag, mac.digest()):
                tmp.unlink()
                return self._plain(400, {"ok": False, "reason": "file damaged or not from the paired device"})
            os.replace(tmp, dest)
            req["done_files"] += 1
            pr.ui("on_nearby_progress", req)
            return self._plain(200, {"ok": True})
    return Handler


class Paired:
    """Private, encrypted sharing between devices paired with a 6-digit code."""

    def __init__(self, win):
        self.win = win
        self.id = win.cfg["device_id"] if win.cfg.get("device_id") else None
        self.server, self.port, self.udp = None, 0, None
        self.online = {}                                   # pair id -> {"ip", "port", "seen"}
        self.transfers = {}
        self.lock = threading.Lock()
        self.code, self.code_until, self.code_tries = None, 0, 0
        self.pending = {}                                  # guest id -> pairing state (host side)
        self.last_beacon = self.last_direct = 0
        self.running = False
        self._keys = {}
        self.answered = {}
        self.code_seen = {}                                # pairing-beacon hash -> (ip, port, time)

    # ---------- stored pairs (secret keys live in the config file, which only you can read)
    def pairs(self):
        return self.win.cfg.setdefault("pairs", [])

    def pair(self, pid):
        for p in self.pairs():
            if p["id"] == pid:
                return p
        return None

    def key(self, pid):
        k = self._keys.get(pid)
        if k is None:
            p = self.pair(pid)
            k = bytes.fromhex(p["secret"]) if p else None
            if k:
                self._keys[pid] = k
        return k

    def save(self):
        with self.lock:
            write_json(CONFIG_FILE, self.win.cfg)
        if not IS_WIN:
            try:
                os.chmod(CONFIG_FILE, 0o600)
            except OSError:
                pass

    def name(self):
        return self.win.nearby.name()

    def ui(self, method, *args):
        GLib.idle_add(lambda: getattr(self.win, method)(*args) or False)

    def is_online(self, pid):
        o = self.online.get(pid)
        return bool(o) and time.time() - o["seen"] < 12

    def mark_seen(self, pid, ip, port):
        was = self.is_online(pid)
        self.online[pid] = {"ip": ip, "port": port or (self.online.get(pid) or {}).get("port"), "seen": time.time()}
        p = self.pair(pid)
        if p and (p.get("last_ip") != ip or (port and p.get("port") != port)):
            p["last_ip"] = ip
            if port:
                p["port"] = port
            self.save()
        if not was:
            self.ui("on_pairs_changed")

    # ---------- start / stop (runs while Arckad-D is open, if there are pairs or a code is shown)
    def ensure_running(self):
        if self.running:
            return
        self.id = self.win.cfg["device_id"]
        for port in PAIR_TCP_PORTS:
            try:
                self.server = ThreadingHTTPServer(("0.0.0.0", port), make_pair_handler(self))
                break
            except OSError:
                continue
        if self.server is None:
            raise OSError("no free network port")
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if hasattr(socket, "SO_REUSEPORT"):
            try:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except OSError:
                pass
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", PAIR_UDP_PORT))
        s.settimeout(0.5)
        self.udp = s
        self.running = True
        threading.Thread(target=self._loop, args=(s,), daemon=True).start()

    def stop(self):
        self.running = False
        if self.server:
            srv, self.server = self.server, None
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
        if self.udp:
            u, self.udp = self.udp, None
            try:
                u.close()
            except OSError:
                pass

    # ---------- secret beacons: only paired devices can recognise them
    def _beacon(self):
        bucket = int(time.time() // 30)
        tags = [beacon_tag(self.key(p["id"]), self.id, bucket) for p in self.pairs()]
        msg = {"app": "arckad-pair", "v": 1, "port": self.port, "tags": tags}
        if self.code_active():
            msg["pairing"] = hashlib.sha256(f"arckad-pair-code|{self.code}".encode()).hexdigest()[:20]
        chat = getattr(self.win, "chat", None)
        if chat:
            msg.update(chat.beacon_fields())
        return json.dumps(msg).encode()

    def _send_beacon(self, targets):
        data = self._beacon()
        for t in targets:
            try:
                self.udp.sendto(data, (t, PAIR_UDP_PORT))
            except (OSError, AttributeError):
                pass

    def _loop(self, s):
        while self.udp is s:
            try:
                data, addr = s.recvfrom(16384)
                self._handle_udp(data, addr[0])
            except socket.timeout:
                pass
            except OSError:
                break
            now = time.time()
            chat = getattr(self.win, "chat", None)
            if (self.pairs() or self.code_active() or (chat and chat.active())) and now - self.last_beacon > 3:
                self.last_beacon = now
                self._send_beacon({"255.255.255.255"} | {ip.rsplit(".", 1)[0] + ".255" for ip in lan_addresses()
                                                         if ip.count(".") == 3})
            if now - self.last_direct > 6:          # also knock on last known addresses (other VLANs)
                self.last_direct = now
                self._send_beacon({p["last_ip"] for p in self.pairs() if p.get("last_ip")}
                                  | (chat.direct_targets() if chat else set()))
                if chat:
                    chat.tick()
            for pid in list(self.online):
                if not self.is_online(pid) and now - self.online[pid]["seen"] < 14:
                    self.online[pid]["seen"] -= 100       # report the change only once
                    self.ui("on_pairs_changed")

    def _handle_udp(self, data, ip):
        try:
            msg = json.loads(data.decode("utf-8"))
        except ValueError:
            return
        if not isinstance(msg, dict) or msg.get("app") != "arckad-pair":
            return
        if msg.get("pairing") and msg.get("port"):
            self.code_seen[str(msg["pairing"])] = (ip, int(msg["port"]), time.time())
        chat = getattr(self.win, "chat", None)
        if chat and chat.on_udp(msg, ip) and time.time() - self.answered.get(ip, 0) > 5:
            self.answered[ip] = time.time()              # answer directly so it finds us quickly too
            self._send_beacon({ip})
        tags = set(msg.get("tags") or [])
        if not tags:
            return
        bucket = int(time.time() // 30)
        for p in self.pairs():
            key = self.key(p["id"])
            if beacon_tag(key, p["id"], bucket) in tags or beacon_tag(key, p["id"], bucket - 1) in tags:
                was = self.is_online(p["id"])
                self.mark_seen(p["id"], ip, msg.get("port"))
                if not was:
                    self._send_beacon({ip})               # answer directly so it finds us quickly too

    # ---------- pairing: host side (shows the code)
    def new_code(self):
        self.ensure_running()
        self.code = f"{secrets.randbelow(1_000_000):06d}"
        self.code_until = time.time() + PAIR_CODE_SECONDS
        self.code_tries = 0
        self.pending.clear()
        self.last_beacon = 0
        return self.code

    def code_active(self):
        return self.code is not None and time.time() < self.code_until

    def cancel_code(self):
        self.code = None

    def host_start(self, req, ip):
        try:
            gid, gpub = str(req["id"])[:40], int(req["pub"], 16)
        except (KeyError, ValueError, TypeError):
            return {"ok": False, "reason": "bad request"}
        if not 1 < gpub < DH_P - 1:
            return {"ok": False, "reason": "bad key"}
        x = secrets.randbits(320)
        pub = pow(2, x, DH_P)
        shared = pow(gpub, x, DH_P).to_bytes(256, "big")
        key = hashlib.sha256(b"arckad-pair-key|" + shared + gpub.to_bytes(256, "big") + pub.to_bytes(256, "big")).digest()
        self.pending[gid] = {"key": key, "name": str(req.get("name") or "Unknown")[:40],
                             "os": str(req.get("os") or "")[:10], "ip": ip, "port": req.get("port")}
        return {"ok": True, "id": self.id, "name": self.name(), "os": OS_NAME, "pub": format(pub, "x"), "port": self.port}

    def host_confirm(self, req, ip):
        gid = str(req.get("id", ""))[:40]
        st = self.pending.get(gid)
        if not st or not self.code_active():
            return {"ok": False, "reason": "the code has expired; show a new one"}
        expect = _hm(st["key"], "guest-proof", self.code).hex()
        if not hmacmod.compare_digest(expect, str(req.get("proof", ""))):
            self.code_tries += 1
            if self.code_tries >= 5:
                self.code = None
                self.ui("on_pair_event", "Too many wrong codes: pairing stopped. Show a new code to try again.")
            return {"ok": False, "reason": "wrong code"}
        ev = {"event": threading.Event(), "accepted": False, "name": st["name"], "os": st["os"], "code": self.code}
        self.ui("ask_pair", ev)
        ev["event"].wait(90)
        if not ev["accepted"]:
            return {"ok": False, "reason": "the other device declined"}
        self._store(gid, st["name"], st["os"], st["key"], ip, st.get("port"))
        proof = _hm(st["key"], "host-proof", self.code).hex()
        self.code = None
        self.pending.pop(gid, None)
        return {"ok": True, "proof": proof}

    def _store(self, pid, name, os_name, key, ip, port):
        self.forget(pid, tell=False, quiet=True)
        self._keys[pid] = key
        self.pairs().append({"id": pid, "name": name, "os": os_name, "secret": key.hex(),
                             "last_ip": ip, "port": port, "auto_accept": False, "since": time.time()})
        self.save()
        self.mark_seen(pid, ip, port)
        self.ui("on_pairs_changed")

    # ---------- pairing: guest side (types the code)
    def find_code_host(self, code, wait=8):
        """Where the device showing this code is: (ip, port) or None. Its beacon only carries a hash of the code."""
        want = hashlib.sha256(f"arckad-pair-code|{code}".encode()).hexdigest()[:20]
        end = time.time() + wait
        while time.time() < end:
            hit = self.code_seen.get(want)
            if hit and time.time() - hit[2] < 10:
                return hit[0], hit[1]
            time.sleep(0.2)
        return None

    @staticmethod
    def _reachable(host, port):
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            return False

    def guest_pair(self, code, host=None):
        """Runs in a background thread. Returns (True, name) or (False, reason)."""
        import http.client
        self.ensure_running()
        where = None
        if host:
            for port in PAIR_TCP_PORTS[:-1]:
                if self._reachable(host, port):
                    where = (socket.gethostbyname(host), port)
                    break
        else:
            where = self.find_code_host(code)
        if not where:
            return False, ("No device showing that code was found. Check the code and that the other device shows it "
                           "right now. If it does, a firewall is probably blocking the signal: click “Allow through "
                           "firewall” below on both devices, or type the other device's IP address in the box.")
        ip, port = where
        x = secrets.randbits(320)
        pub = pow(2, x, DH_P)

        def call(path, obj):
            c = http.client.HTTPConnection(ip, port, timeout=100)
            c.request("POST", path, json.dumps(obj).encode(), {"Content-Type": "application/json"})
            r = c.getresponse()
            data = json.loads(r.read() or b"{}")
            c.close()
            return data
        try:
            r1 = call("/pair/start", {"id": self.id, "name": self.name(), "os": OS_NAME, "pub": format(pub, "x"),
                                      "port": self.port})
            if not r1.get("ok"):
                return False, r1.get("reason", "the other device refused")
            hpub = int(r1["pub"], 16)
            if not 1 < hpub < DH_P - 1:
                return False, "bad key from the other device"
            shared = pow(hpub, x, DH_P).to_bytes(256, "big")
            key = hashlib.sha256(b"arckad-pair-key|" + shared + pub.to_bytes(256, "big") + hpub.to_bytes(256, "big")).digest()
            r2 = call("/pair/confirm", {"id": self.id, "proof": _hm(key, "guest-proof", code).hex()})
            if not r2.get("ok"):
                return False, r2.get("reason", "pairing was not confirmed")
            if not hmacmod.compare_digest(_hm(key, "host-proof", code).hex(), str(r2.get("proof", ""))):
                return False, "the other device couldn't prove it knows the code"
        except (OSError, ValueError, KeyError) as ex:
            return False, f"connection problem ({ex})"
        self._store(str(r1["id"])[:40], str(r1.get("name") or ip)[:40], str(r1.get("os") or "")[:10], key, ip,
                    r1.get("port"))
        return True, str(r1.get("name") or ip)

    # ---------- talking to a paired device
    def _request(self, pid, method, path, body=b"", timeout=30, raw_body=False):
        import http.client
        p = self.pair(pid)
        key = self.key(pid)
        o = self.online.get(pid) or {}
        ip, port = o.get("ip") or p.get("last_ip"), o.get("port") or p.get("port")
        if not ip or not port:
            raise OSError("its address isn't known yet")
        ts = int(time.time())
        headers = {"X-Pair-From": self.id, "X-Pair-Time": str(ts),
                   "X-Pair-Sig": _hm(key, method, path, ts).hex(), "Content-Length": str(len(body))}
        c = http.client.HTTPConnection(ip, port, timeout=timeout)
        c.request(method, path, body, headers)
        r = c.getresponse()
        data = r.read()
        c.close()
        if r.status == 401:
            raise PermissionError("not paired")
        return r.status, (data if raw_body else (json.loads(unseal(key, data)) if data else {}))

    def detach(self, pid):
        """Forget the pair here, and tell the other device if it's reachable."""
        told = False
        try:
            self._request(pid, "POST", "/p/detach", timeout=5)
            told = True
        except Exception:
            pass
        self.forget(pid, tell=False)
        return told

    def forget(self, pid, tell=True, quiet=False):
        before = len(self.pairs())
        self.win.cfg["pairs"] = [p for p in self.pairs() if p["id"] != pid]
        self.online.pop(pid, None)
        self._keys.pop(pid, None)
        if len(self.pairs()) != before:
            self.save()
            if not quiet:
                self.ui("on_pairs_changed")

    def send(self, pid, paths, progress, done):
        def work():
            try:
                result = self._send_files(pid, files_for_sending(paths), progress)
            except PermissionError:
                p = self.pair(pid) or {"name": "the other device"}
                self.forget(pid)
                result = f"{p['name']} is no longer paired with this device (it was detached there)."
            except (OSError, ValueError, KeyError) as ex:
                result = f"Couldn't reach the paired device. ({ex})"
            GLib.idle_add(done, pid, result)
        threading.Thread(target=work, daemon=True).start()

    def _send_files(self, pid, files, progress):
        import http.client
        if not files:
            return "There are no files to send (empty folders are skipped)."
        p = self.pair(pid)
        key = self.key(pid)
        total = sum(f[2] for f in files)
        GLib.idle_add(progress, 0, total, f"Waiting for {p['name']} to accept…")
        offer = {"files": [{"path": rel, "size": size} for _, rel, size in files]}
        status, reply = self._request(pid, "POST", "/p/offer", seal(key, json.dumps(offer).encode()), timeout=100)
        if not reply.get("ok"):
            return f"{p['name']} declined or didn't answer." if reply.get("reason") == "declined" else \
                f"{p['name']} couldn't receive: {reply.get('reason', 'unknown reason')}."
        token, sent, last = reply["token"], 0, 0
        o = self.online.get(pid) or {}
        ip, port = o.get("ip") or p.get("last_ip"), o.get("port") or p.get("port")
        for i, (src, rel, size) in enumerate(files):
            path = f"/p/upload/{token}/{i}"
            ts = int(time.time())
            c = http.client.HTTPConnection(ip, port, timeout=60)
            c.putrequest("PUT", path)
            c.putheader("Content-Length", str(size + 32))
            c.putheader("X-Pair-From", self.id)
            c.putheader("X-Pair-Time", str(ts))
            c.putheader("X-Pair-Sig", _hm(key, "PUT", path, ts).hex())
            c.endheaders()
            cipher = StreamCipher(_hm(key, "file", token, i))
            mac = hmacmod.new(_hm(key, "file-mac", token, i), digestmod=hashlib.sha256)
            left = size
            with open(src, "rb") as f:
                while left > 0:
                    chunk = f.read(min(1 << 18, left))
                    if not chunk:
                        break
                    enc = cipher.apply(chunk)
                    mac.update(enc)
                    c.send(enc)
                    left -= len(chunk)
                    sent += len(chunk)
                    if time.time() - last > 0.2:
                        last = time.time()
                        GLib.idle_add(progress, sent, total, f"Sending {rel} (encrypted)…")
            c.send(mac.digest())
            r = c.getresponse()
            r.read()
            c.close()
            if r.status != 200 or left:
                return f"Sending stopped at {rel}."
        self._request(pid, "POST", f"/p/done/{token}")
        GLib.idle_add(progress, total, total, "Done")
        return None


# ---------------------------------------------------------------- Chat groups (office messenger on the local network)
# Built on the Paired technology: same server and ports, same secret beacons, same code-confirmed key exchange.
# Each group has a shared group key (encrypts messages, signs requests). The owner also shares a private key
# with every member (from joining), and membership changes travel only under those keys, so only the owner
# can approve, remove, or switch the group to "only the owner posts". No server, no internet, no accounts:
# every member keeps the history on their own device, and members who were offline catch up automatically.
import base64

CHAT_DIR = CONFIG_DIR / "chat"
STICKER_DIR = CHAT_DIR / "stickers"
STICKER_MAX = 3 * 1024 * 1024
IMAGE_EXTS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}

# ---- per-person signatures: standard RSA-2048 (RSASSA-PKCS1-v1_5 with SHA-256), built-in Python only

def _probable_prime(n, rounds=40):
    if n < 2: return False
    for p in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37):
        if n % p == 0: return n == p
    d, s = n - 1, 0
    while d % 2 == 0: d //= 2; s += 1
    for _ in range(rounds):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1): continue
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1: break
        else: return False
    return True

def _prime(bits):
    while True:
        c = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if c % 65537 != 1 and _probable_prime(c): return c

def rsa_generate(bits=2048):
    e = 65537
    while True:
        p, q = _prime(bits // 2), _prime(bits // 2)
        if p == q: continue
        n = p * q
        if n.bit_length() != bits: continue
        phi = (p - 1) * (q - 1)
        try: d = pow(e, -1, phi)
        except ValueError: continue
        return {"n": format(n, "x"), "d": format(d, "x"), "p": format(p, "x"), "q": format(q, "x")}

_SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")

def _emsa(data, k):
    t = _SHA256_PREFIX + hashlib.sha256(data).digest()
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t

def rsa_sign(key, data):
    n, d, p, q = (int(key[x], 16) for x in ("n", "d", "p", "q"))
    k = (n.bit_length() + 7) // 8
    m = int.from_bytes(_emsa(data, k), "big")
    sp, sq = pow(m, d % (p - 1), p), pow(m, d % (q - 1), q)
    s = sq + q * ((pow(q, -1, p) * (sp - sq)) % p)
    return s.to_bytes(k, "big").hex()

def rsa_verify(n_hex, data, sig_hex):
    try:
        n = int(n_hex, 16); s = int(sig_hex, 16)
    except (TypeError, ValueError):
        return False
    k = (n.bit_length() + 7) // 8
    if not 0 < s < n: return False
    return pow(s, 65537, n).to_bytes(k, "big") == _emsa(data, k)


# ---- built-in stickers (drawn by Arckad-D, so no licensing issues)
_STICKER_SYMBOLS = {
    "check": '<path d="M52 64 l20 20 l38 -40" fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round" stroke-linejoin="round"/>',
    "cross": '<path d="M56 36 l48 48 M104 36 l-48 48" fill="none" stroke="#fff" stroke-width="13" stroke-linecap="round"/>',
    "star": '<path d="M80 22 l12 25 l27 4 l-20 19 l5 27 l-24 -13 l-24 13 l5 -27 l-20 -19 l27 -4z" fill="#fff"/>',
    "heart": '<path d="M80 92 C40 66 44 34 64 32 C74 31 79 38 80 43 C81 38 86 31 96 32 C116 34 120 66 80 92z" fill="#fff"/>',
    "clock": '<circle cx="80" cy="60" r="32" fill="none" stroke="#fff" stroke-width="9"/><path d="M80 42 v20 l13 9" fill="none" stroke="#fff" stroke-width="8" stroke-linecap="round"/>',
    "alert": '<path d="M80 26 v40" stroke="#fff" stroke-width="15" stroke-linecap="round"/><circle cx="80" cy="88" r="9" fill="#fff"/>',
    "question": '<path d="M62 46 a18 18 0 1 1 26 16 c-6 3 -8 7 -8 14" fill="none" stroke="#fff" stroke-width="11" stroke-linecap="round"/><circle cx="80" cy="92" r="8" fill="#fff"/>',
    "cup": '<path d="M52 40 h48 v26 a22 22 0 0 1 -48 0z" fill="#fff"/><path d="M100 46 h6 a10 10 0 0 1 0 20 h-7" fill="none" stroke="#fff" stroke-width="7"/><path d="M60 92 h40" stroke="#fff" stroke-width="7" stroke-linecap="round"/>',
    "party": '<circle cx="50" cy="40" r="7" fill="#fff"/><circle cx="104" cy="34" r="6" fill="#ffe066"/><circle cx="80" cy="56" r="10" fill="#fff"/><circle cx="62" cy="80" r="6" fill="#ffe066"/><circle cx="110" cy="72" r="8" fill="#fff"/><path d="M40 92 l12 -12 M120 50 l10 -6" stroke="#fff" stroke-width="5" stroke-linecap="round"/>',
    "plate": '<circle cx="80" cy="60" r="30" fill="none" stroke="#fff" stroke-width="8"/><path d="M38 34 v52 M122 34 v52" stroke="#fff" stroke-width="7" stroke-linecap="round"/>',
    "hand": '<path d="M64 92 v-34 a7 7 0 0 1 14 0 v-16 a7 7 0 0 1 14 0 v22 l8 -8 a7 7 0 0 1 10 10 l-20 26 z" fill="#fff"/>',
}
STICKERS = [  # id, words, colour, symbol
    ("approved", "APPROVED", "#26a269", "check"), ("done", "DONE!", "#2ec27e", "check"),
    ("thanks", "THANK YOU", "#9141ac", "heart"), ("great", "GREAT JOB", "#e66100", "star"),
    ("onit", "ON IT", "#1c71d8", "hand"), ("urgent", "URGENT", "#e01b24", "alert"),
    ("question", "QUESTION?", "#0e8a84", "question"), ("meeting", "MEETING", "#3d3a9e", "clock"),
    ("lunch", "LUNCH?", "#c88800", "plate"), ("coffee", "COFFEE BREAK", "#865e3c", "cup"),
    ("welcome", "WELCOME!", "#c64600", "star"), ("birthday", "HAPPY BIRTHDAY", "#d63384", "party"),
    ("noted", "NOTED", "#5e5c64", "check"), ("later", "LATER", "#77767b", "clock"),
    ("yes", "YES!", "#1f8f4e", "check"), ("no", "NO", "#a51d2d", "cross"),
]


def sticker_svg(sid):
    for i, words, colour, sym in STICKERS:
        if i == sid:
            size = 26 if len(words) <= 7 else (21 if len(words) <= 10 else (17 if len(words) <= 12 else 14))
            return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160">'
                    f'<rect x="6" y="6" width="148" height="148" rx="34" fill="{colour}"/>'
                    f'<rect x="6" y="6" width="148" height="74" rx="34" fill="#ffffff" opacity=".10"/>'
                    f'{_STICKER_SYMBOLS[sym]}'
                    f'<text x="80" y="134" text-anchor="middle" fill="#fff" font-weight="800" font-size="{size}" '
                    f'font-family="Segoe UI, Ubuntu, Cantarell, Arial, sans-serif">{esc(words)}</text></svg>')
    return None


def sticker_pixbuf(sid, px):
    svg = sticker_svg(sid)
    if not svg:
        return None
    try:
        loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
        loader.set_size(px, px)
        loader.write(svg.encode())
        loader.close()
        return loader.get_pixbuf()
    except Exception:
        return None

CHAT_AUTO_DOWNLOAD = 50 * 1024 * 1024        # attachments up to this size download by themselves
CHAT_HISTORY_DAYS = 120
EMOJI_GROUPS = [
    ("Work", "✅ ☑️ ✔️ ❌ 👍 👎 👌 🙏 👏 🤝 💪 📌 📎 📅 📆 ⏰ ⏳ ⚠️ ❗ ❓ 💡 📊 📈 📉 📝 ✏️ 📄 📁 📂 🗂️ 💼 🖥️ 💻 📱 ☎️ "
             "📧 📨 🔒 🔑 🔔 🚀 🎯 🏁 ⭐ 🔥 ✨ 🎉 ☕ 🍕 🏠 🚗 ✈️ 🌐 🛠️ 🐞 🧾 💰 💳 📦 🔗 🔍 ♻️ 🟢 🟡 🔴 ➡️ ⬆️ ⬇️ 🔄"),
    ("Smileys", "😀 😃 😄 😁 😆 😅 😂 🙂 😉 😊 😇 😍 🥰 😘 😋 😎 🤓 🤩 🥳 🤔 🤨 😐 😑 🙄 😏 😴 😌 😮 😲 😳 🥺 "
                "😢 😭 😤 😠 😡 🤯 😱 😬 🤗 🤭 🤫 😷 🤒"),
    ("People & symbols", "👋 ✌️ 🤞 ☝️ 👉 👈 🙌 🫡 👀 🧠 ❤️ 🧡 💛 💚 💙 💜 🤍 🖤 💔 💯 🎂 🎁 🏆 🥇"),
]
EMOJIS = [e for _, s in EMOJI_GROUPS for e in s.split()]


# ---- Arckad-D's own emoji images: the complete Noto Emoji set by Google (Apache License 2.0, see
# emoji/LICENSE.txt), packed in emoji/noto-emoji.zip, so emojis look the same on every computer.
# Without that file, the system's emoji font draws them instead.
def _find_emoji_dir():
    here = Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    for d in (here / "emoji", Path(__file__).resolve().parent / "emoji", Path("/opt/arckad-d/emoji")):
        if (d / "noto-emoji.zip").exists():
            return d
    return None


EMOJI_DIR = _find_emoji_dir()
_emoji_zip = None
_EMOJI_KEYS = set()
if EMOJI_DIR is not None:
    try:
        _emoji_zip = zipfile.ZipFile(EMOJI_DIR / "noto-emoji.zip")
        _EMOJI_KEYS = {n[:-4] for n in _emoji_zip.namelist()}
    except (OSError, zipfile.BadZipFile):
        _emoji_zip = None
_emoji_pix = {}
_emoji_lock = threading.Lock()


def emoji_key(e):
    return "_".join(f"{ord(c):04x}" for c in e if c != "\ufe0f")


def emoji_pixbuf(e, px):
    """Arckad-D's image for this emoji at px pixels, or None (then the system font draws it)."""
    if _emoji_zip is None:
        return None
    k = (emoji_key(e), px)
    if k not in _emoji_pix:
        pb = None
        if k[0] in _EMOJI_KEYS:
            try:
                with _emoji_lock:
                    data = _emoji_zip.read(k[0] + ".png")
                loader = GdkPixbuf.PixbufLoader.new_with_type("png")
                loader.set_size(px, px)
                loader.write(data)
                loader.close()
                pb = loader.get_pixbuf()
            except (GLib.Error, KeyError, OSError):
                pb = None
        _emoji_pix[k] = pb
    return _emoji_pix[k]


def emoji_categories():
    """[(tab name, [emoji])]: the curated Work tab first, then every category."""
    tabs = [("Work", EMOJI_GROUPS[0][1].split())]
    if EMOJI_DIR is not None:
        tabs += [(name, chars) for name, chars in read_json(EMOJI_DIR / "categories.json", [])]
    else:
        tabs += [(name, s.split()) for name, s in EMOJI_GROUPS[1:]]
    return tabs


def split_emoji(text):
    """[(is_emoji, piece)]: emojis Arckad-D has images for (including skin tones, flags and combined
    emojis like 👩‍💻), and the text between them."""
    if not _EMOJI_KEYS:
        return [(False, text)]
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        best = 0
        if ord(text[i]) > 0x2000 or text[i] in "#*0123456789":
            for L in range(min(10, n - i), 0, -1):          # longest sequence first
                if emoji_key(text[i:i + L]) in _EMOJI_KEYS:
                    best = L
                    break
        if best:
            j = i + best
            if j < n and text[j] == "\ufe0f":
                j += 1
            if buf:
                out.append((False, "".join(buf)))
                buf = []
            out.append((True, text[i:j]))
            i = j
        else:
            buf.append(text[i])
            i += 1
    if buf:
        out.append((False, "".join(buf)))
    return out


def _backup_key(password, salt, kdf="scrypt"):
    """A key from the backup password; scrypt makes guessing passwords slow and expensive."""
    if kdf == "scrypt":
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** 15, r=8, p=1, maxmem=2 ** 26, dklen=32)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 600_000, 32)


def _safe_folder_name(name):
    keep = "".join(c if c.isalnum() or c in " -_.()" else "_" for c in name).strip(" .")
    return keep or "Group"


class Chat:
    def __init__(self, win):
        self.win = win
        self.pr = win.paired
        self.groups = {}
        self.msgs = {}                   # gid -> [msg] sorted by time
        self.ids = {}                    # gid -> set(msg ids)
        self.unread = {}
        self.online = {}                 # device id -> {"ip", "port", "seen"}
        self.join = None                 # owner side: {"gid", "code", "until", "tries", "pending"}
        self.code_seen = {}
        self.downloading = set()
        self.lock = threading.RLock()
        self._tag_cache = (None, {})
        self.last_sync = 0
        self.ident = None
        self.load()
        threading.Thread(target=self.identity, daemon=True).start()     # make the signing key in the background

    # ---------- storage (plain JSON in your config folder, readable only by you)
    def load(self):
        data = read_json(CHAT_DIR / "groups.json", {})
        self.groups = data.get("groups", {}) if isinstance(data, dict) else {}
        for gid in self.groups:
            msgs = []
            try:
                with open(CHAT_DIR / f"{gid}.jsonl", encoding="utf-8") as f:
                    for line in f:
                        try:
                            msgs.append(json.loads(line))
                        except ValueError:
                            pass
            except OSError:
                pass
            msgs.sort(key=lambda m: (m.get("ts", 0), m.get("id", "")))
            self.msgs[gid] = msgs
            self.ids[gid] = {m.get("id") for m in msgs}

    def save(self):
        with self.lock:
            CHAT_DIR.mkdir(parents=True, exist_ok=True)
            write_json(CHAT_DIR / "groups.json", {"groups": self.groups})
            if not IS_WIN:
                for p in (CHAT_DIR, CHAT_DIR / "groups.json"):
                    try:
                        os.chmod(p, 0o700 if p.is_dir() else 0o600)
                    except OSError:
                        pass

    def _append(self, gid, msg):
        """Store a message once. Returns True if it was new."""
        with self.lock:
            if gid not in self.groups or msg.get("id") in self.ids.setdefault(gid, set()):
                return False
            self.ids[gid].add(msg["id"])
            lst = self.msgs.setdefault(gid, [])
            lst.append(msg)
            if len(lst) > 1 and (lst[-2].get("ts", 0), lst[-2].get("id", "")) > (msg.get("ts", 0), msg.get("id", "")):
                lst.sort(key=lambda m: (m.get("ts", 0), m.get("id", "")))
            CHAT_DIR.mkdir(parents=True, exist_ok=True)
            with open(CHAT_DIR / f"{gid}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(msg, ensure_ascii=False) + "\n")
        return True

    # ---------- small helpers
    # ---------- this device's signing key (made once, ~1 s)
    def identity(self):
        with self.lock:
            if self.ident is None:
                data = read_json(CHAT_DIR / "identity.json", {})
                if not (isinstance(data, dict) and data.get("n") and data.get("d")):
                    data = rsa_generate()
                    CHAT_DIR.mkdir(parents=True, exist_ok=True)
                    write_json(CHAT_DIR / "identity.json", data)
                    if not IS_WIN:
                        try:
                            os.chmod(CHAT_DIR / "identity.json", 0o600)
                        except OSError:
                            pass
                self.ident = data
        return self.ident

    def my_pub(self):
        return self.identity()["n"]

    @staticmethod
    def _sig_payload(gid, m):
        f = m.get("file") or {}
        return json.dumps([gid, m.get("id"), m.get("from"), int(round(float(m.get("ts", 0)) * 1000)), m.get("kind"),
                           m.get("text", ""), [f.get("id"), f.get("name"), f.get("size")] if f else None,
                           m.get("sticker")], ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    def _sign(self, gid, m):
        m["sig"] = rsa_sign(self.identity(), self._sig_payload(gid, m))
        return m

    def pub_of(self, gid, did):
        g = self.groups.get(gid) or {}
        return (g.get("members", {}).get(did) or g.get("past", {}).get(did) or {}).get("pub")

    @property
    def me(self):
        return self.win.cfg["device_id"]

    def my_name(self):
        return self.win.nearby.name()

    def key(self, gid):
        g = self.groups.get(gid)
        return bytes.fromhex(g["key"]) if g and g.get("key") else None

    def is_owner(self, gid):
        g = self.groups.get(gid)
        return bool(g) and g.get("owner") == self.me

    def can_post(self, gid):
        g = self.groups.get(gid)
        return bool(g) and not g.get("removed") and (not g.get("owner_only") or g.get("owner") == self.me)

    def active(self):
        return any(not g.get("removed") for g in self.groups.values()) or self.join_active()

    def is_online(self, did):
        o = self.online.get(did)
        return bool(o) and time.time() - o["seen"] < 12

    def online_members(self, gid):
        g = self.groups.get(gid) or {}
        return [d for d in g.get("members", {}) if d != self.me and self.is_online(d)]

    def ui(self, method, *args):
        GLib.idle_add(lambda: getattr(self.win, method)(*args) or False)

    def start(self):
        if self.active():
            self.pr.ensure_running()

    def files_dir(self, gid):
        return downloads_dir() / "Arckad-D Chat" / _safe_folder_name(self.groups.get(gid, {}).get("name", "Group"))

    def _meta_for_members(self, g):
        return {k: g[k] for k in ("id", "name", "owner", "key", "version", "owner_only", "members", "created", "past")
                if k in g}

    def _system(self, gid, text, share=True):
        """A notice in the chat ("X joined"). The owner's notices go to everyone; others stay on this device."""
        shared = share and self.is_owner(gid)
        msg = {"id": secrets.token_hex(8), "from": self.me, "name": self.my_name(), "ts": time.time(),
               "kind": "system", "text": text}
        if not shared:
            msg["local"] = True
        else:
            self._sign(gid, msg)
        if self._append(gid, msg):
            self.ui("on_chat_changed", gid)
            if shared:
                self._deliver(gid, msg)

    # ---------- groups
    def create_group(self, name):
        gid = secrets.token_hex(8)
        self.groups[gid] = {"id": gid, "name": name[:60], "owner": self.me, "key": secrets.token_bytes(32).hex(),
                            "version": 1, "owner_only": False, "created": time.time(), "pair_keys": {}, "files": {},
                            "members": {self.me: {"name": self.my_name(), "os": OS_NAME, "role": "owner",
                                                  "joined": time.time(), "pub": self.my_pub()}}}
        self.msgs[gid], self.ids[gid] = [], set()
        self.save()
        self._system(gid, f"{self.my_name()} created the group “{name}”")
        self.start()
        return gid

    def set_owner_only(self, gid, on):
        g = self.groups[gid]
        g["owner_only"], g["version"] = bool(on), g.get("version", 1) + 1
        self.save()
        self._system(gid, "Only the owner can post now" if on else "Everyone can post again")
        self.push_meta(gid)

    def rename_group(self, gid, name):
        g = self.groups[gid]
        g["name"], g["version"] = name[:60], g.get("version", 1) + 1
        self.save()
        self._system(gid, f"Group renamed to “{name}”")
        self.push_meta(gid)

    def remove_member(self, gid, did):
        """Owner only. The group gets a new key, so the removed device can't read anything new."""
        g = self.groups[gid]
        m = g["members"].pop(did, None)
        if not m:
            return
        g.setdefault("past", {})[did] = {"name": m["name"], "pub": m.get("pub")}
        old_pair = g.get("pair_keys", {}).pop(did, None)
        g["key"], g["version"] = secrets.token_bytes(32).hex(), g.get("version", 1) + 1
        self.save()
        self._system(gid, f"{m['name']} was removed from the group")
        if old_pair:
            threading.Thread(target=self._tell_removed, args=(gid, did, bytes.fromhex(old_pair)), daemon=True).start()
        self.push_meta(gid)

    def _tell_removed(self, gid, did, pair_key):
        try:
            self._request(gid, did, "POST", "/c/meta", {"id": gid, "removed": True}, pair_key=pair_key, timeout=6)
        except Exception:
            pass

    def leave_group(self, gid):
        """Member: tell the owner and stop. Owner: delete the group for everyone."""
        g = self.groups.get(gid)
        if not g:
            return
        if self.is_owner(gid):
            for did, hexkey in list(g.get("pair_keys", {}).items()):
                threading.Thread(target=self._tell_removed, args=(gid, did, bytes.fromhex(hexkey)), daemon=True).start()
        elif not g.get("removed"):
            owner = g.get("owner")
            threading.Thread(target=lambda: self._try(lambda: self._request(gid, owner, "POST", "/c/leave", {},
                                                                                 timeout=6)), daemon=True).start()
        time.sleep(0.3)
        with self.lock:
            self.groups.pop(gid, None)
            self.msgs.pop(gid, None)
            self.ids.pop(gid, None)
            self.save()
            try:
                (CHAT_DIR / f"{gid}.jsonl").unlink()
            except OSError:
                pass
        self.ui("on_chat_changed", None)

    @staticmethod
    def _try(fn):
        try:
            return fn()
        except Exception:
            return None

    def push_meta(self, gid):
        """Owner: send the current membership and settings to every member (each under its private key)."""
        g = self.groups.get(gid)
        if not g or not self.is_owner(gid):
            return
        meta = self._meta_for_members(g)

        def work():
            for did, hexkey in list(g.get("pair_keys", {}).items()):
                if did in g["members"]:
                    self._try(lambda: self._request(gid, did, "POST", "/c/meta", meta, pair_key=bytes.fromhex(hexkey),
                                                    timeout=6))
        threading.Thread(target=work, daemon=True).start()
        self.ui("on_chat_changed", gid)

    def _apply_meta(self, gid, meta):
        """Member: take the owner's membership/settings update."""
        g = self.groups.get(gid)
        if not g:
            return
        if meta.get("removed") or self.me not in (meta.get("members") or {self.me: 1}):
            if not g.get("removed"):
                g["removed"], g["key"] = True, ""
                self.save()
                self._system(gid, "You were removed from this group (or it was deleted). The history stays here.", share=False)
            return
        if int(meta.get("version", 0)) <= int(g.get("version", 0)):
            return
        for k in ("name", "owner_only", "members", "key", "version", "past"):
            if k in meta:
                g[k] = meta[k]
        self.save()
        self._tag_cache = (None, {})
        self.ui("on_chat_changed", gid)

    # ---------- joining: owner shows a code
    def new_join_code(self, gid):
        self.start()
        self.join = {"gid": gid, "code": f"{secrets.randbelow(1_000_000):06d}", "until": time.time() + 600,
                     "tries": 0, "pending": {}}
        self.pr.last_beacon = 0
        return self.join["code"]

    def join_active(self):
        return bool(self.join) and time.time() < self.join["until"]

    def stop_join(self):
        self.join = None

    def _join_start(self, req, ip):
        if not self.join_active():
            return {"ok": False, "reason": "no join code is shown on that device right now"}
        try:
            gid_, gpub = str(req["id"])[:40], int(req["pub"], 16)
        except (KeyError, ValueError, TypeError):
            return {"ok": False, "reason": "bad request"}
        if not 1 < gpub < DH_P - 1:
            return {"ok": False, "reason": "bad key"}
        x = secrets.randbits(320)
        pub = pow(2, x, DH_P)
        shared = pow(gpub, x, DH_P).to_bytes(256, "big")
        key = hashlib.sha256(b"arckad-chat-key|" + shared + gpub.to_bytes(256, "big") + pub.to_bytes(256, "big")).digest()
        self.join["pending"][gid_] = {"key": key, "name": str(req.get("name") or "Unknown")[:40],
                                      "os": str(req.get("os") or "")[:10], "ip": ip, "port": req.get("port"),
                                      "pub": str(req.get("sigpub") or "")[:1100]}
        g = self.groups[self.join["gid"]]
        return {"ok": True, "pub": format(pub, "x"), "group": g["name"], "owner": self.my_name(), "owner_id": self.me,
                "port": self.pr.port}

    def _join_confirm(self, req, ip):
        did = str(req.get("id", ""))[:40]
        j = self.join
        st = j["pending"].get(did) if self.join_active() else None
        if not st:
            return {"ok": False, "reason": "the join code has expired; ask for a new one"}
        if not hmacmod.compare_digest(_hm(st["key"], "join-guest", j["code"]).hex(), str(req.get("proof", ""))):
            j["tries"] += 1
            if j["tries"] >= 5:
                self.join = None
                self.ui("on_pair_event", "Too many wrong join codes: the code was cancelled.")
            return {"ok": False, "reason": "wrong code"}
        gid = j["gid"]
        g = self.groups[gid]
        ev = {"event": threading.Event(), "accepted": False, "name": st["name"], "os": st["os"], "group": g["name"]}
        self.ui("ask_chat_join", ev)
        ev["event"].wait(120)
        if not ev["accepted"]:
            return {"ok": False, "reason": "the group owner declined"}
        g["members"][did] = {"name": st["name"], "os": st["os"], "role": "member", "joined": time.time()}
        if st.get("pub"):
            g["members"][did]["pub"] = st["pub"]
        g.setdefault("pair_keys", {})[did] = st["key"].hex()
        g["version"] = g.get("version", 1) + 1
        self.online[did] = {"ip": ip, "port": st.get("port"), "seen": time.time()}
        self.save()
        self._tag_cache = (None, {})
        self._system(gid, f"{st['name']} joined the group")
        self.push_meta(gid)
        meta = self._meta_for_members(g)
        reply = seal(st["key"], json.dumps({"meta": meta, "proof": _hm(st["key"], "join-owner", j["code"]).hex()}).encode())
        j["pending"].pop(did, None)
        return {"ok": True, "sealed": base64.b64encode(reply).decode()}

    # ---------- joining: member types the code
    def join_with_code(self, code, host=None):
        """Background thread. Returns (True, group name) or (False, reason)."""
        import http.client
        self.pr.ensure_running()
        where = None
        if host:
            for port in PAIR_TCP_PORTS[:-1]:
                if Paired._reachable(host, port):
                    where = (socket.gethostbyname(host), port)
                    break
        else:
            want = hashlib.sha256(f"arckad-chat-code|{code}".encode()).hexdigest()[:20]
            end = time.time() + 8
            while time.time() < end and not where:
                hit = self.code_seen.get(want)
                if hit and time.time() - hit[2] < 10:
                    where = (hit[0], hit[1])
                time.sleep(0.2)
        if not where:
            return False, ("No group showing that join code was found. Check the code and that the owner shows it "
                           "right now. A firewall may be blocking it: use “Allow through firewall”, or type the "
                           "owner's IP address.")
        ip, port = where
        x = secrets.randbits(320)
        pub = pow(2, x, DH_P)

        def call(path, obj):
            c = http.client.HTTPConnection(ip, port, timeout=150)
            c.request("POST", path, json.dumps(obj).encode(), {"Content-Type": "application/json"})
            r = c.getresponse()
            data = json.loads(r.read() or b"{}")
            c.close()
            return data
        try:
            r1 = call("/cj/start", {"id": self.me, "name": self.my_name(), "os": OS_NAME, "pub": format(pub, "x"),
                                    "port": self.pr.port, "sigpub": self.my_pub()})
            if not r1.get("ok"):
                return False, r1.get("reason", "refused")
            opub = int(r1["pub"], 16)
            if not 1 < opub < DH_P - 1:
                return False, "bad key from the owner's device"
            shared = pow(opub, x, DH_P).to_bytes(256, "big")
            key = hashlib.sha256(b"arckad-chat-key|" + shared + pub.to_bytes(256, "big") + opub.to_bytes(256, "big")).digest()
            r2 = call("/cj/confirm", {"id": self.me, "proof": _hm(key, "join-guest", code).hex()})
            if not r2.get("ok"):
                return False, r2.get("reason", "not approved")
            data = json.loads(unseal(key, base64.b64decode(r2["sealed"])))
            if not hmacmod.compare_digest(_hm(key, "join-owner", code).hex(), str(data.get("proof", ""))):
                return False, "the owner's device couldn't prove it knows the code"
        except (OSError, ValueError, KeyError) as ex:
            return False, f"connection problem ({ex})"
        meta = data["meta"]
        gid = meta["id"]
        with self.lock:
            g = dict(meta, owner_key=key.hex(), files={})
            self.groups[gid] = g
            self.msgs.setdefault(gid, [])
            self.ids.setdefault(gid, set())
            self.save()
        self.online[meta["owner"]] = {"ip": ip, "port": r1.get("port") or port, "seen": time.time()}
        self._tag_cache = (None, {})
        threading.Thread(target=self.sync_with, args=(gid, meta["owner"]), daemon=True).start()
        self.ui("on_chat_changed", gid)
        return True, meta["name"]

    # ---------- presence: secret beacon tags per group (only members can recognise them)
    def beacon_fields(self):
        bucket = int(time.time() // 30)
        out = {}
        tags = [_hm(self.key(gid), "member", self.me, bucket).hex()[:24]
                for gid, g in self.groups.items() if not g.get("removed") and g.get("key")]
        if tags:
            out["ctags"] = tags
        if self.join_active():
            out["chatjoin"] = hashlib.sha256(f"arckad-chat-code|{self.join['code']}".encode()).hexdigest()[:20]
        return out

    def _expected(self):
        bucket = int(time.time() // 30)
        stamp = (bucket, tuple(sorted((gid, g.get("key"), len(g.get("members", {}))) for gid, g in self.groups.items())))
        if self._tag_cache[0] != stamp:
            table = {}
            for gid, g in self.groups.items():
                if g.get("removed") or not g.get("key"):
                    continue
                k = bytes.fromhex(g["key"])
                for did in g.get("members", {}):
                    if did != self.me:
                        for b in (bucket, bucket - 1):
                            table[_hm(k, "member", did, b).hex()[:24]] = did
            self._tag_cache = (stamp, table)
        return self._tag_cache[1]

    def on_udp(self, msg, ip):
        if msg.get("chatjoin") and msg.get("port"):
            self.code_seen[str(msg["chatjoin"])] = (ip, int(msg["port"]), time.time())
        tags = msg.get("ctags") or []
        if not tags:
            return False
        table = self._expected()
        seen = {table[t] for t in tags if t in table}
        for did in seen:
            was = self.is_online(did)
            self.online[did] = {"ip": ip, "port": msg.get("port"), "seen": time.time()}
            if not was:
                self.ui("on_chat_presence")
                threading.Thread(target=self._came_online, args=(did,), daemon=True).start()
        return bool(seen)

    def direct_targets(self):
        return {o["ip"] for o in self.online.values() if o.get("ip")}

    def ensure_my_pub(self, gid):
        """Groups made before signatures: give the owner this device's public key."""
        g = self.groups.get(gid)
        if not g or g.get("removed"):
            return
        mine = g.get("members", {}).get(self.me)
        if mine is None or mine.get("pub") == self.my_pub():
            return
        if self.is_owner(gid):
            mine["pub"] = self.my_pub()
            g["version"] = g.get("version", 1) + 1
            self.save()
            self.push_meta(gid)
        elif g.get("owner_key") and self.is_online(g["owner"]):
            self._try(lambda: self._request(gid, g["owner"], "POST", "/c/setpub", {"pub": self.my_pub()},
                                            pair_key=bytes.fromhex(g["owner_key"]), timeout=8))

    def _came_online(self, did):
        for gid, g in list(self.groups.items()):
            if g.get("removed") or did not in g.get("members", {}):
                continue
            if g.get("owner") == did and not self.is_owner(gid):
                self.pull_meta(gid)
                self.ensure_my_pub(gid)
            self.sync_with(gid, did)

    def tick(self):
        """Called every few seconds: keep histories in step with someone online."""
        now = time.time()
        if now - self.last_sync < 45:
            return
        self.last_sync = now
        for gid in list(self.groups):
            online = self.online_members(gid)
            if online:
                threading.Thread(target=self.sync_with, args=(gid, secrets.choice(online)), daemon=True).start()

    # ---------- talking to other members
    def _request(self, gid, did, method, path, obj=None, pair_key=None, timeout=20, raw=False):
        import http.client
        o = self.online.get(did) or {}
        ip, port = o.get("ip"), o.get("port")
        if not ip or not port:
            raise OSError("not online")
        key = pair_key or self.key(gid)
        body = seal(key, json.dumps(obj or {}).encode()) if obj is not None else b""
        ts = int(time.time())
        headers = {"X-Chat-Group": gid, "X-Chat-From": self.me, "X-Chat-Time": str(ts),
                   "X-Chat-Sig": _hm(key, method, path, ts, self.me, gid).hex(), "Content-Length": str(len(body))}
        if pair_key:
            headers["X-Chat-Pair"] = "1"
        c = http.client.HTTPConnection(ip, port, timeout=timeout)
        c.request(method, path, body, headers)
        r = c.getresponse()
        if raw:
            return c, r
        data = r.read()
        c.close()
        if r.status in (401, 403) and not data.startswith(b"{"):
            pass
        if r.status != 200:
            try:
                reason = json.loads(unseal(key, data)).get("reason")
            except Exception:
                try:
                    reason = json.loads(data).get("reason")
                except Exception:
                    reason = None
            raise PermissionError(reason or f"refused ({r.status})")
        return json.loads(unseal(key, data)) if data else {}

    def pull_meta(self, gid):
        g = self.groups.get(gid)
        if not g or not g.get("owner_key"):
            return
        meta = self._try(lambda: self._request(gid, g["owner"], "POST", "/c/getmeta", {},
                                               pair_key=bytes.fromhex(g["owner_key"]), timeout=8))
        if meta:
            self._apply_meta(gid, meta)

    def sync_with(self, gid, did):
        """Ask one member for the messages we don't have yet."""
        g = self.groups.get(gid)
        if not g or g.get("removed"):
            return
        cutoff = time.time() - CHAT_HISTORY_DAYS * 86400
        with self.lock:
            have = [m["id"] for m in self.msgs.get(gid, []) if m.get("ts", 0) > cutoff and not m.get("local")]
        reply = self._try(lambda: self._request(gid, did, "POST", "/c/sync", {"ids": have}, timeout=30))
        if not reply:
            return
        new = 0
        for m in reply.get("msgs", [])[:2000]:
            m = self._clean(m, gid)
            if m and self._append(gid, m):
                new += 1
                if m.get("file"):
                    self._maybe_download(gid, m)
        if new:
            self.unread[gid] = self.unread.get(gid, 0) + new
            self.ui("on_chat_changed", gid)

    def _clean(self, m, gid):
        """Only well-formed messages from current or past members get stored."""
        if not isinstance(m, dict) or not isinstance(m.get("id"), str) or len(m["id"]) > 40:
            return None
        kind = m.get("kind")
        if kind not in ("text", "file", "system", "sticker"):
            return None
        out = {"id": m["id"], "from": str(m.get("from", ""))[:40], "name": str(m.get("name", "?"))[:40],
               "ts": float(m.get("ts", 0) or 0), "kind": kind, "text": str(m.get("text", ""))[:8000]}
        f = m.get("file")
        if kind == "file" or (kind == "sticker" and f):
            f = f or {}
            if not isinstance(f.get("id"), str) or not isinstance(f.get("size"), int):
                return None
            name = os.path.basename(str(f.get("name", "file")).replace("\\", "/"))[:200] or "file"
            out["file"] = {"id": f["id"][:40], "name": name, "size": max(0, f["size"])}
        if kind == "sticker":
            out["sticker"] = str(m.get("sticker", ""))[:40]
            if out["sticker"] != "custom" and not sticker_svg(out["sticker"]):
                return None
        # who really sent it: check the sender's signature against the key the owner gave us
        pub = self.pub_of(gid, out["from"])
        if pub:
            if not rsa_verify(pub, self._sig_payload(gid, dict(out)), str(m.get("sig", ""))):
                return None                                   # forged or altered: dropped
            out["sig"] = m["sig"]
        else:
            out["unverified"] = True                          # sender from before signatures existed
        return out

    # ---------- sending
    def send_text(self, gid, text):
        text = text.strip()
        if not text or not self.can_post(gid):
            return
        msg = self._sign(gid, {"id": secrets.token_hex(8), "from": self.me, "name": self.my_name(), "ts": time.time(),
                               "kind": "text", "text": text[:8000]})
        self._append(gid, msg)
        self.ui("on_chat_changed", gid)
        self._deliver(gid, msg)

    def send_files(self, gid, paths):
        if not self.can_post(gid):
            return 0
        n = 0
        g = self.groups[gid]
        for p in paths:
            if not os.path.isfile(p):
                continue
            fid = secrets.token_hex(8)
            g.setdefault("files", {})[fid] = p
            msg = self._sign(gid, {"id": secrets.token_hex(8), "from": self.me, "name": self.my_name(),
                                   "ts": time.time(), "kind": "file", "text": "",
                                   "file": {"id": fid, "name": os.path.basename(p), "size": os.path.getsize(p)}})
            self._append(gid, msg)
            self._deliver(gid, msg)
            n += 1
        self.save()
        self.ui("on_chat_changed", gid)
        return n

    def send_sticker(self, gid, sid=None, image=None):
        """A built-in sticker (sid) or one of your own sticker images (image path)."""
        if not self.can_post(gid):
            return
        msg = {"id": secrets.token_hex(8), "from": self.me, "name": self.my_name(), "ts": time.time(),
               "kind": "sticker", "text": "", "sticker": sid or "custom"}
        if image:
            fid = secrets.token_hex(8)
            self.groups[gid].setdefault("files", {})[fid] = image
            msg["file"] = {"id": fid, "name": os.path.basename(image), "size": os.path.getsize(image)}
            self.save()
        self._sign(gid, msg)
        self._append(gid, msg)
        self.ui("on_chat_changed", gid)
        self._deliver(gid, msg)

    # ---------- your own stickers
    @staticmethod
    def my_stickers():
        try:
            return sorted(str(p) for p in STICKER_DIR.iterdir() if ext_of(p.name) in IMAGE_EXTS | {"svg"})
        except OSError:
            return []

    @staticmethod
    def add_sticker(path):
        if os.path.getsize(path) > STICKER_MAX:
            raise ValueError("Sticker images must be smaller than 3 MB.")
        if ext_of(path) not in IMAGE_EXTS | {"svg"}:
            raise ValueError("Use a PNG, JPG, GIF, WebP or SVG image.")
        STICKER_DIR.mkdir(parents=True, exist_ok=True)
        target = unique_target(STICKER_DIR / os.path.basename(path))
        shutil.copy2(path, target)
        return str(target)

    def _deliver(self, gid, msg):
        def work():
            for did in self.online_members(gid):
                self._try(lambda: self._request(gid, did, "POST", "/c/msg", {"msg": msg}, timeout=10))
        threading.Thread(target=work, daemon=True).start()

    # ---------- backup: one password-protected .arckadchat file
    def export_backup(self, dest, password, with_files=True):
        """Returns (number of groups, messages, files) written."""
        salt = secrets.token_bytes(16)
        kdf = "scrypt" if hasattr(hashlib, "scrypt") else "pbkdf2"
        key = _backup_key(password, salt, kdf)
        with self.lock:
            data = {"format": 1, "made": time.time(), "app": APP_VERSION, "device_id": self.me,
                    "device_name": self.my_name(), "identity": self.identity(),
                    "groups": json.loads(json.dumps(self.groups)), "msgs": json.loads(json.dumps(self.msgs))}
        files = []
        if with_files:
            for gid, g in data["groups"].items():
                for fid, path in (g.get("files") or {}).items():
                    if path and os.path.isfile(path):
                        files.append((gid, fid, path))
        tmp = Path(str(dest) + ".part")
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
            z.writestr("README.txt", "Arckad-D chat backup (encrypted).\nRestore it in Arckad-D: Chat → ⋯ → Restore chats "
                                     "from backup, and type its password.\n")
            z.writestr("kdf", f"{kdf}:{salt.hex()}")
            z.writestr("chat.enc", seal(key, json.dumps(data, ensure_ascii=False).encode("utf-8")))
            for gid, fid, path in files:
                cipher = StreamCipher(_hm(key, "backup-file", gid, fid))
                mac = hmacmod.new(_hm(key, "backup-file-mac", gid, fid), digestmod=hashlib.sha256)
                with open(path, "rb") as src, z.open(f"files/{gid}/{fid}", "w", force_zip64=True) as out:
                    while True:
                        chunk = src.read(1 << 18)
                        if not chunk:
                            break
                        enc = cipher.apply(chunk)
                        mac.update(enc)
                        out.write(enc)
                    out.write(mac.digest())
        os.replace(tmp, dest)
        return len(data["groups"]), sum(len(v) for v in data["msgs"].values()), len(files)

    @staticmethod
    def read_backup(path, password):
        """Decrypt a backup: (data, key). Raises ValueError for a wrong password or a damaged file."""
        try:
            with zipfile.ZipFile(path) as z:
                kdf, salt = z.read("kdf").decode().split(":")
                key = _backup_key(password, bytes.fromhex(salt), kdf)
                blob = z.read("chat.enc")
        except (zipfile.BadZipFile, KeyError, ValueError, OSError):
            raise ValueError("This isn't an Arckad-D chat backup, or the file is damaged.")
        try:
            data = json.loads(unseal(key, blob))
        except ValueError:
            raise ValueError("Wrong password.")
        if data.get("format") != 1:
            raise ValueError("This backup was made by a newer Arckad-D. Update Arckad-D first.")
        return data, key

    def restore_backup(self, path, data, key, take_identity):
        """Merge a backup into this device. take_identity: continue as the device that made the backup
        (so you stay a member of its groups). Returns (groups added, messages added, files restored)."""
        if take_identity:
            self.win.cfg["device_id"] = data["device_id"]
            write_json(CONFIG_FILE, self.win.cfg)
            with self.lock:
                self.ident = data["identity"]
                CHAT_DIR.mkdir(parents=True, exist_ok=True)
                write_json(CHAT_DIR / "identity.json", self.ident)
        added_groups = added_msgs = restored = 0
        for gid, g in data.get("groups", {}).items():
            with self.lock:
                mine = self.groups.get(gid)
                if mine is None:
                    g = dict(g, files={})
                    if self.me not in g.get("members", {}):
                        g["removed"], g["key"] = True, ""          # history only: this device isn't a member
                    self.groups[gid] = g
                    self.msgs.setdefault(gid, [])
                    self.ids.setdefault(gid, set())
                    added_groups += 1
                elif int(g.get("version", 0)) > int(mine.get("version", 0)) and self.me in g.get("members", {}):
                    for k in ("name", "owner_only", "members", "key", "version", "past", "pair_keys", "owner_key"):
                        if k in g:
                            mine[k] = g[k]
            for m in data.get("msgs", {}).get(gid, []):
                if self._append(gid, m):
                    added_msgs += 1
        try:
            with zipfile.ZipFile(path) as z:
                for name in z.namelist():
                    parts = name.split("/")
                    if len(parts) != 3 or parts[0] != "files" or parts[1] not in self.groups:
                        continue
                    gid, fid = parts[1], parts[2]
                    if self.local_file(gid, fid):
                        continue
                    fname = next((m["file"]["name"] for m in self.msgs.get(gid, [])
                                  if (m.get("file") or {}).get("id") == fid), fid)
                    folder = self.files_dir(gid)
                    folder.mkdir(parents=True, exist_ok=True)
                    dest = unique_target(folder / os.path.basename(fname))
                    cipher = StreamCipher(_hm(key, "backup-file", gid, fid))
                    mac = hmacmod.new(_hm(key, "backup-file-mac", gid, fid), digestmod=hashlib.sha256)
                    size = z.getinfo(name).file_size - 32
                    with z.open(name) as src, open(dest, "wb") as out:
                        left = size
                        while left > 0:
                            chunk = src.read(min(1 << 18, left))
                            if not chunk:
                                break
                            mac.update(chunk)
                            out.write(cipher.apply(chunk))
                            left -= len(chunk)
                        tag = src.read(32)
                    if left or not hmacmod.compare_digest(tag, mac.digest()):
                        dest.unlink()
                        continue
                    self.groups[gid].setdefault("files", {})[fid] = str(dest)
                    restored += 1
        except (zipfile.BadZipFile, OSError):
            pass
        self.save()
        self._tag_cache = (None, {})
        self.ui("on_chat_changed", None)
        return added_groups, added_msgs, restored

    # ---------- attachments
    def local_file(self, gid, fid):
        p = (self.groups.get(gid) or {}).get("files", {}).get(fid)
        return p if p and os.path.isfile(p) else None

    def _maybe_download(self, gid, msg):
        if msg["file"]["size"] <= CHAT_AUTO_DOWNLOAD and not self.local_file(gid, msg["file"]["id"]):
            self.download(gid, msg)

    def download(self, gid, msg):
        fid = msg["file"]["id"]
        if fid in self.downloading:
            return
        self.downloading.add(fid)
        threading.Thread(target=self._download, args=(gid, msg), daemon=True).start()
        self.ui("on_chat_changed", gid)

    def _download(self, gid, msg):
        fid, size = msg["file"]["id"], msg["file"]["size"]
        try:
            sources = [msg["from"]] + [d for d in self.online_members(gid) if d != msg["from"]]
            for did in sources:
                if not self.is_online(did):
                    continue
                key = self.key(gid)
                try:
                    c, r = self._request(gid, did, "GET", f"/c/file/{fid}", None, timeout=60, raw=True)
                except Exception:
                    continue
                if r.status != 200:
                    r.read()
                    c.close()
                    continue
                folder = self.files_dir(gid)
                folder.mkdir(parents=True, exist_ok=True)
                dest = unique_target(folder / msg["file"]["name"])
                tmp = dest.with_name(dest.name + ".part")
                cipher = StreamCipher(_hm(key, "chatfile", fid))
                mac = hmacmod.new(_hm(key, "chatfile-mac", fid), digestmod=hashlib.sha256)
                left = size
                with open(tmp, "wb") as f:
                    while left > 0:
                        chunk = r.read(min(1 << 18, left))
                        if not chunk:
                            break
                        mac.update(chunk)
                        f.write(cipher.apply(chunk))
                        left -= len(chunk)
                tag = r.read(32)
                c.close()
                if left or not hmacmod.compare_digest(tag, mac.digest()):
                    tmp.unlink()
                    continue
                os.replace(tmp, dest)
                with self.lock:
                    self.groups[gid].setdefault("files", {})[fid] = str(dest)
                    self.save()
                return
        finally:
            self.downloading.discard(fid)
            self.ui("on_chat_changed", gid)

    # ---------- the server side (called from the Paired server's request handler)
    def _auth(self, h):
        gid, did = h.headers.get("X-Chat-Group", ""), h.headers.get("X-Chat-From", "")
        g = self.groups.get(gid)
        if not g or g.get("removed"):
            return None, None, None
        try:
            ts = int(h.headers.get("X-Chat-Time", "0"))
        except ValueError:
            return None, None, None
        if abs(time.time() - ts) > 600:
            return None, None, None
        if h.headers.get("X-Chat-Pair") == "1":
            if g.get("owner") == self.me:
                hexkey = g.get("pair_keys", {}).get(did)
            elif did == g.get("owner"):
                hexkey = g.get("owner_key")
            else:
                hexkey = None
            if not hexkey:
                return None, None, None
            key, pair = bytes.fromhex(hexkey), True
        else:
            if did not in g.get("members", {}):
                return None, None, None
            key, pair = bytes.fromhex(g["key"]), False
        sig = _hm(key, h.command, h.path, ts, did, gid).hex()
        if not hmacmod.compare_digest(sig, h.headers.get("X-Chat-Sig", "")):
            return None, None, None
        o = self.online.get(did)
        if o and o.get("port"):                    # a request from it also proves it's online
            o["ip"], o["seen"] = h.client_address[0], time.time()
        return gid, did, (key, pair)

    def handle_post(self, h, path):
        if path == "/cj/start":
            return h._plain(200, self._join_start(json.loads(h._body(100_000)), h.client_address[0]))
        if path == "/cj/confirm":
            r = self._join_confirm(json.loads(h._body(100_000)), h.client_address[0])
            return h._plain(200 if r.get("ok") else 403, r)
        gid, did, auth = self._auth(h)
        if not gid:
            return h._plain(401, {"ok": False, "reason": "not a member"})
        key, pair = auth
        body = h._body(20_000_000)
        req = json.loads(unseal(key, body)) if body else {}
        g = self.groups[gid]

        def reply(obj, code=200):
            h._raw(code, seal(key, json.dumps(obj).encode()))
        if path == "/c/msg" and not pair:
            m = self._clean(req.get("msg"), gid)
            if not m or m["from"] != did:
                return reply({"ok": False, "reason": "bad message"}, 400)
            if m["kind"] == "system" and did != g.get("owner"):
                return reply({"ok": False, "reason": "only the owner's device sends notices"}, 403)
            if g.get("owner_only") and did != g.get("owner"):
                return reply({"ok": False, "reason": "only the owner can post in this group"}, 403)
            if self._append(gid, m):
                self.unread[gid] = self.unread.get(gid, 0) + 1
                self.ui("on_chat_message", gid, m)
                if m.get("file"):
                    self._maybe_download(gid, m)
            return reply({"ok": True})
        if path == "/c/sync" and not pair:
            known = set(req.get("ids") or [])
            cutoff = time.time() - CHAT_HISTORY_DAYS * 86400
            with self.lock:
                out = [{k: v for k, v in m.items() if k != "local"} for m in self.msgs.get(gid, [])
                       if m["id"] not in known and m.get("ts", 0) > cutoff and not m.get("local")]
            return reply({"ok": True, "msgs": out[-2000:]})
        if path == "/c/meta" and pair and did == g.get("owner"):
            self._apply_meta(gid, req)
            return reply({"ok": True})
        if path == "/c/getmeta" and pair and g.get("owner") == self.me:
            if did not in g["members"]:
                return reply({"id": gid, "removed": True})
            return reply(self._meta_for_members(g))
        if path == "/c/setpub" and pair and g.get("owner") == self.me and did in g["members"]:
            pub = str(req.get("pub") or "")[:1100]
            if pub and not g["members"][did].get("pub"):          # set once; a changed key needs re-joining
                g["members"][did]["pub"] = pub
                g["version"] = g.get("version", 1) + 1
                self.save()
                self.push_meta(gid)
            return reply({"ok": True})
        if path == "/c/leave" and not pair and g.get("owner") == self.me:
            left = g["members"].pop(did, {})
            name = left.get("name", "A member")
            g.setdefault("past", {})[did] = {"name": name, "pub": left.get("pub")}
            g.get("pair_keys", {}).pop(did, None)
            g["key"], g["version"] = secrets.token_bytes(32).hex(), g.get("version", 1) + 1
            self.save()
            self._system(gid, f"{name} left the group")
            self.push_meta(gid)
            return h._raw(200, seal(key, b'{"ok": true}'))
        return reply({"ok": False, "reason": "unknown request"}, 404)

    def handle_get(self, h, path):
        gid, did, auth = self._auth(h)
        if not gid or auth[1]:
            return h._plain(401, {"ok": False})
        parts = [p for p in path.split("/") if p]
        fid = parts[2] if len(parts) == 3 else ""
        src = self.local_file(gid, fid)
        if not src:
            return h._plain(404, {"ok": False})
        key = auth[0]
        size = os.path.getsize(src)
        h.send_response(200)
        h.send_header("Content-Type", "application/octet-stream")
        h.send_header("Content-Length", str(size + 32))
        h.end_headers()
        cipher = StreamCipher(_hm(key, "chatfile", fid))
        mac = hmacmod.new(_hm(key, "chatfile-mac", fid), digestmod=hashlib.sha256)
        with open(src, "rb") as f:
            left = size
            while left > 0:
                chunk = f.read(min(1 << 18, left))
                if not chunk:
                    break
                enc = cipher.apply(chunk)
                mac.update(enc)
                h.wfile.write(enc)
                left -= len(chunk)
        h.wfile.write(mac.digest())


# ---------------------------------------------------------------- Chat panel (right pane and its own window)
CHAT_CSS = b"""
.chat-bubble { border-radius: 14px; padding: 6px 11px; }
.chat-mine { background-color: #2f7fd8; }
.chat-mine label { color: #ffffff; }
.chat-mine button label { color: inherit; }
.chat-theirs { background-color: alpha(currentColor, 0.09); }
.chat-text, .chat-text text { background-color: transparent; }
.chat-mine .chat-text text { color: #ffffff; }
.chat-system { opacity: 0.65; }
.chat-code { font-size: 22px; font-weight: bold; letter-spacing: 4px; }
"""
_chat_css_loaded = []


def _load_chat_css():
    if not _chat_css_loaded:
        prov = Gtk.CssProvider()
        prov.load_from_data(CHAT_CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        _chat_css_loaded.append(prov)


def _gst():
    """GStreamer for the built-in camera (Linux), or None."""
    try:
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        Gst.init(None)
        if Gst.ElementFactory.find("gdkpixbufsink") and Gst.ElementFactory.find("videoconvert"):
            return Gst
    except (ImportError, ValueError):
        pass
    return None


class CameraDialog(Gtk.Dialog):
    """Live camera picture with a Take photo button (Linux, GStreamer). run() → saved photo path or None."""
    SOURCE = "v4l2src"

    def __init__(self, parent):
        super().__init__(title="Take a photo", transient_for=parent, modal=True)
        self.set_default_size(680, 560)
        self.Gst = _gst()
        self.photo = None
        self.view = Gtk.Image(vexpand=True)
        self.msg = Gtk.Label(wrap=True, margin=8)
        box = self.get_content_area()
        box.pack_start(self.view, True, True, 0)
        box.add(self.msg)
        self.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self.snap = self.add_button("📷  Take photo", Gtk.ResponseType.OK)
        self.snap.get_style_context().add_class("suggested-action")
        self.snap.set_sensitive(False)
        self.pipe = None
        self.connect("response", self.on_response)
        self.connect("destroy", lambda *_: self.stop())
        self.start()

    def start(self):
        Gst = self.Gst
        try:
            self.pipe = Gst.parse_launch(f"{self.SOURCE} ! videoconvert ! gdkpixbufsink name=sink")
        except GLib.Error as ex:
            self.msg.set_text(f"The camera couldn't start: {ex.message}")
            return
        self.sink = self.pipe.get_by_name("sink")
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self.on_error)
        self.pipe.set_state(Gst.State.PLAYING)
        self.msg.set_text("Starting the camera…")
        GLib.timeout_add(66, self.update)

    def on_error(self, bus, message):
        err, _dbg = message.parse_error()
        self.msg.set_text(f"The camera reported a problem: {err.message}\n(Is another app using it?)")
        self.snap.set_sensitive(False)
        self.stop()

    def update(self):
        if not self.pipe:
            return False
        pb = self.sink.get_property("last-pixbuf")
        if pb is not None:
            self.frame = pb
            alloc = self.view.get_allocation()
            w, h = max(alloc.width, 320), max(alloc.height, 240)
            scale = min(w / pb.get_width(), h / pb.get_height())
            self.view.set_from_pixbuf(pb.scale_simple(max(1, int(pb.get_width() * scale)),
                                                      max(1, int(pb.get_height() * scale)),
                                                      GdkPixbuf.InterpType.BILINEAR))
            if not self.snap.get_sensitive():
                self.snap.set_sensitive(True)
                self.msg.set_text("Smile 🙂 then click Take photo.")
        return True

    def on_response(self, dlg, resp):
        if resp == Gtk.ResponseType.OK and getattr(self, "frame", None) is not None:
            folder = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or str(HOME)) / "Arckad-D Camera"
            folder.mkdir(parents=True, exist_ok=True)
            path = unique_target(folder / time.strftime("Photo %Y-%m-%d %H.%M.%S.jpg"))
            self.frame.savev(str(path), "jpeg", ["quality"], ["92"])
            self.photo = str(path)
        self.stop()

    def stop(self):
        if self.pipe:
            self.pipe.set_state(self.Gst.State.NULL)
            self.pipe = None


class PhotoWatcher:
    """For the system camera app: watches where it saves photos and offers the new one to attach."""

    def __init__(self, win, folders, on_photo, minutes=5):
        self.win, self.folders, self.on_photo = win, [Path(f) for f in folders], on_photo
        self.start, self.until = time.time() - 2, time.time() + minutes * 60
        self.seen = set()
        GLib.timeout_add_seconds(2, self.tick)

    def tick(self):
        if time.time() > self.until:
            return False
        for folder in self.folders:
            try:
                for p in folder.iterdir():
                    if ext_of(p.name) in IMAGE_EXTS and p.stat().st_mtime > self.start and p not in self.seen:
                        self.seen.add(p)
                        size = p.stat().st_size
                        GLib.timeout_add(1200, self._settled, p, size)
            except OSError:
                continue
        return True

    def _settled(self, p, size):
        try:
            if p.stat().st_size != size:                       # still being written
                GLib.timeout_add(1200, self._settled, p, p.stat().st_size)
                return False
        except OSError:
            return False
        self.until = 0                                         # one photo per click
        self.on_photo(str(p))
        return False


class ChatPanel(Gtk.Box):
    def __init__(self, win, in_window=False):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=8)
        _load_chat_css()
        self.win, self.chat, self.in_window = win, win.chat, in_window
        self.gid = None
        self._combo_ids = []
        self._syncing = False
        self.set_size_request(340, -1)

        top = Gtk.Box(spacing=4)
        self.combo = Gtk.ComboBoxText(hexpand=True)
        self.combo.connect("changed", self.on_group_changed)
        top.pack_start(self.combo, True, True, 0)
        plus = Gtk.Menu()
        for label, cb in (("New group…", self.new_group), ("Join a group with a code…", self.show_join)):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda _i, cb=cb: cb())
            plus.append(it)
        plus.show_all()
        pb = Gtk.MenuButton(popup=plus)
        pb.add(Gtk.Image.new_from_icon_name("list-add-symbolic", Gtk.IconSize.BUTTON))
        pb.set_tooltip_text("New group or join one")
        top.add(pb)
        self.more_menu = Gtk.Menu()
        self.more_btn = Gtk.MenuButton(popup=self.more_menu)
        self.more_btn.add(Gtk.Image.new_from_icon_name("view-more-symbolic", Gtk.IconSize.BUTTON))
        self.more_btn.set_tooltip_text("Group: invite people, members, settings")
        self.more_btn.connect("toggled", lambda b: self.build_more_menu() if b.get_active() else None)
        top.add(self.more_btn)
        if not in_window:
            pop = Gtk.Button.new_from_icon_name("window-new-symbolic", Gtk.IconSize.BUTTON)
            pop.set_tooltip_text("Open the chat in its own window")
            pop.connect("clicked", lambda *_: win.open_chat_window())
            top.add(pop)
        self.add(top)
        self.info = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.info.get_style_context().add_class("dim-label")
        self.add(self.info)

        # join code shown by the owner
        self.code_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.code_label = Gtk.Label(selectable=True)
        self.code_label.get_style_context().add_class("chat-code")
        self.code_hint = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        stop = Gtk.Button(label="Stop inviting", halign=Gtk.Align.CENTER)
        stop.connect("clicked", lambda *_: (self.chat.stop_join(), self.code_box.hide()))
        for w in (self.code_label, self.code_hint, stop):
            self.code_box.add(w)
        self.code_box.set_no_show_all(True)
        self.add(self.code_box)

        # joining with a code
        self.join_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        jr = Gtk.Box(spacing=4)
        self.join_code = Gtk.Entry(placeholder_text="Join code", max_length=6, width_chars=8)
        self.join_code.connect("activate", lambda *_: self.do_join())
        self.join_ip = Gtk.Entry(placeholder_text="owner's IP (other network only)", hexpand=True)
        self.join_btn = Gtk.Button(label="Join")
        self.join_btn.get_style_context().add_class("suggested-action")
        self.join_btn.connect("clicked", lambda *_: self.do_join())
        jr.add(self.join_code)
        jr.pack_start(self.join_ip, True, True, 0)
        jr.add(self.join_btn)
        self.join_status = Gtk.Label(xalign=0, wrap=True)
        self.join_box.add(jr)
        self.join_box.add(self.join_status)
        self.join_box.set_no_show_all(True)
        self.add(self.join_box)

        # messages
        self.stack = Gtk.Stack()
        empty = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, valign=Gtk.Align.CENTER)
        empty.set_markup("<big>💬</big>\n\n<b>Chat with your team</b>\n\nCreate a group with <b>＋ → New group</b>, "
                         "or join one with a code from its owner.\n\n<small>Private and encrypted: it stays inside your "
                         "network and only members can read it.</small>")
        empty.set_margin_start(12)
        empty.set_margin_end(12)
        self.stack.add_named(empty, "empty")
        self.scroll = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        self.list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list.get_style_context().add_class("view")
        self.scroll.add(self.list)
        self.stack.add_named(self.scroll, "messages")
        self.pack_start(self.stack, True, True, 0)

        # composer
        comp = Gtk.Box(spacing=4)
        emo_pop = Gtk.Popover()
        tabs = Gtk.Notebook(scrollable=True)
        self._emoji_tabs = {}
        for title, chars in emoji_categories():
            sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
            sc.set_size_request(420, 260)
            self._emoji_tabs[sc] = chars
            tabs.append_page(sc, Gtk.Label(label=title))
        tabs.connect("switch-page", lambda nb, page, i: self._fill_emoji_tab(page, emo_pop))
        self._fill_emoji_tab(tabs.get_nth_page(0), emo_pop)
        tabs.show_all()
        emo_pop.add(tabs)
        self.emo_btn = Gtk.MenuButton(popover=emo_pop)
        face = emoji_pixbuf("🙂", 20)
        self.emo_btn.add(Gtk.Image.new_from_pixbuf(face) if face else Gtk.Label(label="🙂"))
        self.emo_btn.set_tooltip_text("Emoji")
        self.sticker_pop = Gtk.Popover()
        self.sticker_btn = Gtk.MenuButton(label="🏷", popover=self.sticker_pop)
        self.sticker_btn.set_tooltip_text("Stickers")
        self.sticker_btn.connect("toggled", lambda b: self.build_stickers() if b.get_active() else None)
        self.cam_btn = Gtk.Button(label="📷")
        self.cam_btn.set_tooltip_text("Take a photo with the camera and send it")
        self.cam_btn.connect("clicked", lambda *_: self.take_photo())
        self.attach_btn = Gtk.Button.new_from_icon_name("mail-attachment-symbolic", Gtk.IconSize.BUTTON)
        self.attach_btn.set_tooltip_text("Attach files (or drag files here from the file list)")
        self.attach_btn.connect("clicked", lambda *_: self.attach())
        self.entry = Gtk.Entry(hexpand=True, placeholder_text="Message")
        self.entry.connect("activate", lambda *_: self.send())
        self.send_btn = Gtk.Button.new_from_icon_name("mail-send-symbolic", Gtk.IconSize.BUTTON)
        self.send_btn.get_style_context().add_class("suggested-action")
        self.send_btn.set_tooltip_text("Send (Enter)")
        self.send_btn.connect("clicked", lambda *_: self.send())
        for w in (self.emo_btn, self.sticker_btn, self.cam_btn, self.attach_btn):
            comp.add(w)
        comp.pack_start(self.entry, True, True, 0)
        comp.add(self.send_btn)
        self.composer = comp
        self.add(comp)
        self.readonly = Gtk.Label(label="Only the group owner can post here.")
        self.readonly.get_style_context().add_class("dim-label")
        self.readonly.set_no_show_all(True)
        self.add(self.readonly)

        self.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                           Gdk.DragAction.COPY | Gdk.DragAction.MOVE)
        self.connect("drag-data-received", self.on_drop)
        self.refresh()

    # ---------- state
    def refresh(self, gid=None):
        ids = sorted(self.chat.groups, key=lambda g: self.chat.groups[g].get("name", "").lower())
        if ids != self._combo_ids or gid is None:
            self._syncing = True
            self.combo.remove_all()
            for g in ids:
                grp = self.chat.groups[g]
                n = self.chat.unread.get(g, 0) if g != self.gid else 0
                label = grp["name"] + ("  (left)" if grp.get("removed") else "") + (f"  • {n} new" if n else "")
                self.combo.append(g, label)
            self._combo_ids = ids
            if self.gid not in ids:
                self.gid = ids[0] if ids else None
            if self.gid:
                self.combo.set_active_id(self.gid)
            self._syncing = False
        if gid in (None, self.gid):
            self.show_messages()
        self.update_info()

    def on_group_changed(self, combo):
        if self._syncing:
            return
        self.gid = combo.get_active_id()
        self.show_messages()
        self.update_info()

    def update_info(self):
        g = self.chat.groups.get(self.gid) if self.gid else None
        if not g:
            self.info.set_text("")
            self.composer.set_sensitive(False)
            self.stack.set_visible_child_name("empty")
            return
        members = g.get("members", {})
        online = len(self.chat.online_members(self.gid))
        owner = members.get(g.get("owner"), {}).get("name", "?")
        you = " (you)" if g.get("owner") == self.chat.me else ""
        self.info.set_text(f"{len(members)} member{'s' if len(members) != 1 else ''} · {online} online · "
                           f"owner: {owner}{you}" + (" · announcements only" if g.get("owner_only") else ""))
        can = self.chat.can_post(self.gid)
        self.composer.set_visible(can)
        self.composer.set_sensitive(can)
        self.readonly.set_visible(not can)
        self.readonly.set_text("You're no longer a member of this group." if g.get("removed")
                               else "Only the group owner can post here.")

    def show_messages(self):
        for r in self.list.get_children():
            self.list.remove(r)
        if not self.gid:
            self.stack.set_visible_child_name("empty")
            return
        self.stack.set_visible_child_name("messages")
        self.chat.unread[self.gid] = 0
        last_day = None
        for m in self.chat.msgs.get(self.gid, [])[-300:]:
            day = time.strftime("%A %d %B %Y", time.localtime(m.get("ts", 0)))
            if day != last_day:
                last_day = day
                d = Gtk.Label(margin_top=8, margin_bottom=2)
                d.set_markup(f"<small><b>{esc(day)}</b></small>")
                d.get_style_context().add_class("dim-label")
                row = Gtk.ListBoxRow(activatable=False)
                row.add(d)
                self.list.add(row)
            self.list.add(self._row(m))
        self.list.show_all()
        GLib.idle_add(self._scroll_bottom)
        self.win.update_chat_button()

    def _scroll_bottom(self):
        adj = self.scroll.get_vadjustment()
        adj.set_value(adj.get_upper())
        return False

    def _row(self, m):
        row = Gtk.ListBoxRow(activatable=False)
        mine = m.get("from") == self.chat.me
        when = time.strftime("%H:%M", time.localtime(m.get("ts", 0)))
        if m["kind"] == "system":
            lbl = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER, margin=4)
            lbl.set_markup(f"<small>{esc(m.get('text', ''))} · {when}</small>")
            lbl.get_style_context().add_class("chat-system")
            row.add(lbl)
            return row
        outer = Gtk.Box(margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
        bubble = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        ctx = bubble.get_style_context()
        ctx.add_class("chat-bubble")
        ctx.add_class("chat-mine" if mine else "chat-theirs")
        if not mine:
            nm = Gtk.Label(xalign=0)
            nm.set_markup(f"<small><b>{esc(m.get('name', '?'))}</b></small>")
            bubble.add(nm)
        if m["kind"] == "text":
            bubble.add(self._text_widget(m.get("text", "")))
        elif m["kind"] == "sticker":
            ctx.remove_class("chat-mine")
            ctx.remove_class("chat-theirs")
            bubble.add(self._sticker_image(m))
        else:
            bubble.add(self._file_box(m))
        if m.get("unverified"):
            warn = Gtk.Label(xalign=0)
            warn.set_markup("<small>⚠ not signed (sent before signatures)</small>")
            warn.set_tooltip_text("Arckad-D can't confirm who sent this message: it came from a version without "
                                  "per-person signatures.")
            bubble.add(warn)
        tl = Gtk.Label(xalign=1)
        tl.set_markup(f"<small>{when}</small>")
        tl.set_opacity(0.75)
        bubble.add(tl)
        if mine:
            outer.pack_end(bubble, False, False, 0)
            outer.set_margin_start(40)
        else:
            outer.pack_start(bubble, False, False, 0)
            outer.set_margin_end(40)
        row.add(outer)
        return row

    def _fill_emoji_tab(self, sc, pop):
        """Build a picker tab the first time it's opened (keeps opening the picker quick)."""
        chars = self._emoji_tabs.pop(sc, None)
        if chars is None:
            return
        flow = Gtk.FlowBox(max_children_per_line=11, min_children_per_line=9, selection_mode=Gtk.SelectionMode.NONE,
                           homogeneous=True)
        for e in chars:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            pb = emoji_pixbuf(e, 28)
            b.add(Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Label(label=e))
            b.connect("clicked", lambda _b, e=e: self.insert_emoji(e, pop))
            flow.add(b)
        sc.add(flow)
        sc.show_all()

    def _text_widget(self, text):
        """Message text with Arckad-D's emoji images (same look on every computer). Selectable and copyable."""
        parts = split_emoji(text)
        if not any(is_e for is_e, _ in parts):
            t = Gtk.Label(label=text, xalign=0, wrap=True, selectable=True, max_width_chars=38)
            t.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            return t
        only = all(is_e or not piece.strip() for is_e, piece in parts)
        n = sum(1 for is_e, _ in parts if is_e)
        px = 40 if only and n <= 3 else 20                  # a short emoji-only message shows them big
        tv = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        tv.get_style_context().add_class("chat-text")
        buf = tv.get_buffer()
        plain = []
        for is_e, piece in parts:
            pb = emoji_pixbuf(piece, px) if is_e else None
            if pb:
                buf.insert_pixbuf(buf.get_end_iter(), pb)
                plain.append("\u2003" * (2 if px == 20 else 3))
            else:
                buf.insert(buf.get_end_iter(), piece)
                plain.append(piece)
        layout = tv.create_pango_layout("".join(plain))
        w = max((layout.get_pixel_size()[0] if "\n" not in "".join(plain) else
                 max(tv.create_pango_layout(line).get_pixel_size()[0] for line in "".join(plain).split("\n"))), 20)
        tv.set_size_request(min(w + 18, 300), -1)
        return tv

    def _sticker_image(self, m):
        if m.get("sticker") != "custom":
            pb = sticker_pixbuf(m.get("sticker"), 128)
            return Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Label(label="🏷")
        local = self.chat.local_file(self.gid, m["file"]["id"])
        if local:
            try:
                return Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(local, 140, 140, True))
            except GLib.Error:
                pass
        lbl = Gtk.Label(label="🏷 sticker (downloading…)" if m["file"]["id"] in self.chat.downloading else "🏷 sticker")
        return lbl

    def _file_box(self, m):
        f = m["file"]
        local = self.chat.local_file(self.gid, f["id"])
        if local and ext_of(f["name"]) in IMAGE_EXTS:            # photos show as pictures
            outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(local, 240, 240, True)
                ev = Gtk.EventBox()
                ev.add(Gtk.Image.new_from_pixbuf(pb))
                ev.set_tooltip_text("Click to open")
                ev.connect("button-press-event", lambda *_: self.win.open_file(local))
                outer.add(ev)
            except GLib.Error:
                pass
            outer.add(self._file_line(m, local))
            return outer
        return self._file_line(m, local)

    def _file_line(self, m, local):
        f = m["file"]
        box = Gtk.Box(spacing=8)
        box.add(Gtk.Image.new_from_gicon(icon_for(f["name"], False), Gtk.IconSize.DND))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        n = Gtk.Label(label=f["name"], xalign=0, ellipsize=Pango.EllipsizeMode.MIDDLE, max_width_chars=26)
        texts.add(n)
        s = Gtk.Label(xalign=0)
        s.set_markup(f"<small>{human_size(f['size'])}</small>")
        texts.add(s)
        box.pack_start(texts, True, True, 0)
        btns = Gtk.Box(spacing=2)
        if local:
            o = Gtk.Button(label="Open")
            o.connect("clicked", lambda *_: self.win.open_file(local))
            sh = Gtk.Button.new_from_icon_name("folder-open-symbolic", Gtk.IconSize.BUTTON)
            sh.set_tooltip_text("Show in folder")
            sh.connect("clicked", lambda *_: self.win.active.show_in_folder(local))
            btns.add(o)
            btns.add(sh)
        elif f["id"] in self.chat.downloading:
            btns.add(Gtk.Label(label="Downloading…"))
        else:
            d = Gtk.Button(label="Download")
            d.set_tooltip_text("Downloads from the sender (or another member who has it) while they're online")
            d.connect("clicked", lambda *_: self.chat.download(self.gid, m))
            btns.add(d)
        texts.add(btns)
        return box

    # ---------- actions
    def send(self):
        text = self.entry.get_text().strip()
        if text and self.gid:
            self.entry.set_text("")
            self.chat.send_text(self.gid, text)
            self.chat.start()

    def insert_emoji(self, e, pop):
        pos = self.entry.get_position()
        self.entry.insert_text(e, pos)
        self.entry.set_position(pos + len(e))
        pop.popdown()
        self.entry.grab_focus_without_selecting()

    def attach(self):
        if not self.gid:
            return
        dlg = Gtk.FileChooserNative(title="Attach files", transient_for=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.OPEN)
        dlg.set_select_multiple(True)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.send_paths(dlg.get_filenames())
        dlg.destroy()

    def send_paths(self, paths):
        if not self.gid or not self.chat.can_post(self.gid):
            self.win.info("Choose a group you can post in first.")
            return
        folders = [p for p in paths if os.path.isdir(p)]
        files = [p for p in paths if os.path.isfile(p)]
        n = self.chat.send_files(self.gid, files)
        if folders:
            self.win.info("Folders can't be attached. Tip: right-click the folder → Compress, then attach the ZIP.")
        return n

    def on_drop(self, widget, context, x, y, selection, info, time_):
        paths = [p for p in (Gio.File.new_for_uri(u).get_path() for u in (selection.get_uris() or [])) if p]
        if paths:
            self.send_paths(paths)

    def build_stickers(self):
        if self.sticker_pop.get_child():
            self.sticker_pop.remove(self.sticker_pop.get_child())
        nb = Gtk.Notebook()
        flow = Gtk.FlowBox(max_children_per_line=4, min_children_per_line=4, selection_mode=Gtk.SelectionMode.NONE,
                           homogeneous=True)
        for sid, words, _c, _s in STICKERS:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_pixbuf(sticker_pixbuf(sid, 72)))
            b.set_tooltip_text(words.title())
            b.connect("clicked", lambda _b, s=sid: self.send_sticker(sid=s))
            flow.add(b)
        sc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        sc.set_size_request(380, 300)
        sc.add(flow)
        nb.append_page(sc, Gtk.Label(label="Stickers"))
        mine = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=6)
        mflow = Gtk.FlowBox(max_children_per_line=4, min_children_per_line=4, selection_mode=Gtk.SelectionMode.NONE,
                            homogeneous=True)
        for path in self.chat.my_stickers():
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 72, 72, True)
            except GLib.Error:
                continue
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.add(Gtk.Image.new_from_pixbuf(pb))
            b.connect("clicked", lambda _b, pth=path: self.send_sticker(image=pth))
            mflow.add(b)
        msc = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        msc.add(mflow)
        add = Gtk.Button(label="＋ Add your own sticker image…")
        add.connect("clicked", lambda *_: self.add_sticker())
        mine.pack_start(msc, True, True, 0)
        mine.add(add)
        nb.append_page(mine, Gtk.Label(label="My stickers"))
        nb.show_all()
        self.sticker_pop.add(nb)

    def send_sticker(self, sid=None, image=None):
        self.sticker_pop.popdown()
        if self.gid and self.chat.can_post(self.gid):
            self.chat.send_sticker(self.gid, sid=sid, image=image)

    def add_sticker(self):
        dlg = Gtk.FileChooserNative(title="Choose a sticker image", transient_for=self.get_toplevel(),
                                    action=Gtk.FileChooserAction.OPEN)
        flt = Gtk.FileFilter()
        flt.set_name("Images")
        for e in sorted(IMAGE_EXTS | {"svg"}):
            flt.add_pattern(f"*.{e}")
            flt.add_pattern(f"*.{e.upper()}")
        dlg.add_filter(flt)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            try:
                self.chat.add_sticker(dlg.get_filename())
                self.build_stickers()
                self.sticker_btn.set_active(True)
            except (ValueError, OSError) as ex:
                self.win.error(str(ex))
        dlg.destroy()

    def take_photo(self):
        if not self.gid or not self.chat.can_post(self.gid):
            return
        gid = self.gid

        def got(path):
            self.confirm_photo(gid, path)
        if IS_WIN:
            pics = Path(os.environ.get("USERPROFILE", str(HOME))) / "Pictures"
            folders = [pics / "Camera Roll", pics, Path(os.environ.get("OneDrive", str(pics))) / "Pictures" / "Camera Roll"]
            try:
                os.startfile("microsoft.windows.camera:")
            except OSError:
                self.win.error("The Windows Camera app couldn't be opened.")
                return
            PhotoWatcher(self.win, folders, got)
            self.win.flash_all("Take the photo in the Camera app: Arckad-D will offer to send it.")
            return
        if (_gst() and any(Path("/dev").glob("video*"))) or (_gst() and CameraDialog.SOURCE != "v4l2src"):
            dlg = CameraDialog(self.get_toplevel())
            dlg.show_all()
            dlg.run()
            photo = dlg.photo
            dlg.destroy()
            if photo:
                self.chat.send_files(gid, [photo])
            return
        app = next((a for a in ("snapshot", "cheese", "guvcview") if shutil.which(a)), None)
        if not any(Path("/dev").glob("video*")):
            self.win.error("No camera was found on this computer.")
            return
        if not app:
            self.win.error("Taking photos needs the camera library. Install it with:\n\n"
                           "  sudo apt install gir1.2-gstreamer-1.0 gstreamer1.0-plugins-good")
            return
        subprocess.Popen([app], start_new_session=True)
        pics = Path(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or str(HOME))
        PhotoWatcher(self.win, [pics / "Camera", pics / "Webcam", pics], got)
        self.win.flash_all("Take the photo in the camera app: Arckad-D will offer to send it.")

    def confirm_photo(self, gid, path):
        d = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.NONE, text="Send this photo?")
        try:
            img = Gtk.Image.new_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 320, 240, True))
            d.get_message_area().add(img)
            img.show()
        except GLib.Error:
            pass
        d.format_secondary_text(os.path.basename(path))
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Send", Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            self.chat.send_files(gid, [path])
        d.destroy()

    # ---------- backup
    def backup(self):
        d = Gtk.Dialog(title="Back up chats", transient_for=self.get_toplevel(), modal=True)
        d.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Choose where to save…", Gtk.ResponseType.OK)
        box = d.get_content_area()
        box.set_spacing(8)
        box.set_border_width(14)
        intro = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        intro.set_markup("Saves all your groups, messages and your signing key in one file, <b>encrypted with a "
                         "password</b>. Keep the file and the password safe: without the password it can't be opened.")
        box.add(intro)
        pw1 = Gtk.Entry(visibility=False, placeholder_text="Password (at least 8 characters)")
        pw2 = Gtk.Entry(visibility=False, placeholder_text="Type it again")
        files = Gtk.CheckButton(label="Include attachments (photos and files)")
        files.set_active(True)
        err = Gtk.Label(xalign=0)
        for w in (pw1, pw2, files, err):
            box.add(w)
        d.show_all()
        while True:
            if d.run() != Gtk.ResponseType.OK:
                d.destroy()
                return
            if len(pw1.get_text()) < 8:
                err.set_markup("<span foreground='#e01b24'>Use at least 8 characters.</span>")
            elif pw1.get_text() != pw2.get_text():
                err.set_markup("<span foreground='#e01b24'>The two passwords are different.</span>")
            else:
                break
        password, with_files = pw1.get_text(), files.get_active()
        d.destroy()
        fc = Gtk.FileChooserNative(title="Save chat backup", transient_for=self.get_toplevel(),
                                   action=Gtk.FileChooserAction.SAVE)
        fc.set_do_overwrite_confirmation(True)
        fc.set_current_name(time.strftime("Arckad-D chats %Y-%m-%d.arckadchat"))
        fc.set_current_folder(str(downloads_dir()))
        if fc.run() != Gtk.ResponseType.ACCEPT:
            fc.destroy()
            return
        dest = fc.get_filename()
        fc.destroy()
        if not dest.endswith(".arckadchat"):
            dest += ".arckadchat"
        self.win.flash_all("Backing up chats…")

        def work():
            try:
                res = self.chat.export_backup(dest, password, with_files)
                GLib.idle_add(done, res, None)
            except (OSError, ValueError) as ex:
                GLib.idle_add(done, None, str(ex))

        def done(res, error):
            if error:
                self.win.error(f"The backup couldn't be saved: {error}")
            else:
                self.win.info(f"Chat backup saved ✓\n\n{dest}\n\n{res[0]} groups · {res[1]} messages · {res[2]} "
                              f"attachments · {human_size(os.path.getsize(dest))}")
            return False
        threading.Thread(target=work, daemon=True).start()

    def restore(self):
        fc = Gtk.FileChooserNative(title="Restore chats from a backup", transient_for=self.get_toplevel(),
                                   action=Gtk.FileChooserAction.OPEN)
        flt = Gtk.FileFilter()
        flt.set_name("Arckad-D chat backups")
        flt.add_pattern("*.arckadchat")
        fc.add_filter(flt)
        if fc.run() != Gtk.ResponseType.ACCEPT:
            fc.destroy()
            return
        path = fc.get_filename()
        fc.destroy()
        password = self.win.ask_text("Restore chats", "The backup's password:", "", password=True)
        if not password:
            return

        def work():
            try:
                data, key = Chat.read_backup(path, password)
                GLib.idle_add(ask, data, key)
            except ValueError as ex:
                GLib.idle_add(lambda msg=str(ex): self.win.error(msg) and False)

        def ask(data, key):
            take = False
            if data["device_id"] != self.chat.me:
                q = Gtk.MessageDialog(transient_for=self.get_toplevel(), modal=True,
                                      message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.NONE,
                                      text=f"This backup is from “{data.get('device_name', 'another device')}”")
                q.format_secondary_text(
                    "Continue as that device on this computer? Then you stay a member of its groups, and its owners "
                    "and colleagues see this computer as that device. Do this when replacing a computer; don't keep "
                    "using the old one at the same time.\n\nOr only bring back the history to read.")
                q.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Only the history", 1,
                              "Continue as that device", Gtk.ResponseType.OK)
                r = q.run()
                q.destroy()
                if r == Gtk.ResponseType.CANCEL or r == Gtk.ResponseType.DELETE_EVENT:
                    return False
                take = r == Gtk.ResponseType.OK
            threading.Thread(target=apply, args=(data, key, take), daemon=True).start()
            return False

        def apply(data, key, take):
            res = self.chat.restore_backup(path, data, key, take)
            GLib.idle_add(finished, res, take)

        def finished(res, take):
            self.refresh()
            extra = "\n\nRestart Arckad-D to finish switching to that device." if take else ""
            self.win.info(f"Chats restored ✓\n\n{res[0]} new groups · {res[1]} messages · {res[2]} attachments{extra}")
            return False
        threading.Thread(target=work, daemon=True).start()

    def new_group(self):
        name = self.win.ask_text("New group", "Group name (e.g. Accounts Team):", "")
        if name and name.strip():
            try:
                self.gid = self.chat.create_group(name.strip())
            except OSError as ex:
                self.win.error(f"Couldn't start chat sharing: {ex}")
                return
            self.refresh()
            self.invite()

    def show_join(self):
        self.join_box.set_no_show_all(False)
        self.join_box.show_all()
        self.join_status.set_text("Type the join code the group owner shows you. The owner then approves you.")
        self.join_code.grab_focus()

    def do_join(self):
        code = "".join(c for c in self.join_code.get_text() if c.isdigit())
        if len(code) != 6:
            self.join_status.set_text("The join code has 6 digits.")
            return
        host = self.join_ip.get_text().strip() or None
        self.join_btn.set_sensitive(False)
        self.join_status.set_text("Looking for the group… then waiting for the owner to approve you.")

        def work():
            ok, msg = self.chat.join_with_code(code, host)
            GLib.idle_add(done, ok, msg)

        def done(ok, msg):
            self.join_btn.set_sensitive(True)
            if ok:
                self.join_status.set_text("")
                self.join_box.hide()
                self.join_code.set_text("")
                self.join_ip.set_text("")
                gid = next((g for g, v in self.chat.groups.items() if v["name"] == msg), None)
                if gid:
                    self.gid = gid
                self.refresh()
                self.win.flash_all(f"Joined “{msg}”")
            else:
                self.join_status.set_text("✗ " + msg)
            return False
        threading.Thread(target=work, daemon=True).start()

    def invite(self):
        if not self.gid or not self.chat.is_owner(self.gid):
            return
        try:
            code = self.chat.new_join_code(self.gid)
        except OSError as ex:
            self.win.error(f"Couldn't start chat sharing: {ex}")
            return
        self.code_label.set_text(f"{code[:3]} {code[3:]}")
        self.code_box.set_no_show_all(False)
        self.code_box.show_all()
        self._tick_code()
        GLib.timeout_add_seconds(1, self._tick_code)

    def _tick_code(self):
        if not self.chat.join_active():
            self.code_box.hide()
            return False
        left = int(self.chat.join["until"] - time.time())
        name = self.chat.groups.get(self.chat.join["gid"], {}).get("name", "")
        ips = [ip for ip in lan_addresses() if not ip.startswith("127.")]
        self.code_hint.set_markup(f"<small>Join code for <b>{esc(name)}</b>. Others: <b>＋ → Join a group</b>, type "
                                  f"this code, and you approve them. Valid {left // 60}:{left % 60:02d} · this "
                                  f"computer is {esc(ips[0] if ips else '?')}</small>")
        return True

    def build_more_menu(self):
        for c in self.more_menu.get_children():
            self.more_menu.remove(c)
        g = self.chat.groups.get(self.gid) if self.gid else None
        def backup_items():
            self.more_menu.append(Gtk.SeparatorMenuItem())
            for label, cb, ok in (("Back up chats…", self.backup, bool(self.chat.groups)),
                                  ("Restore chats from a backup…", self.restore, True)):
                it = Gtk.MenuItem(label=label)
                it.set_sensitive(ok)
                it.connect("activate", lambda _i, cb=cb: cb())
                self.more_menu.append(it)
        if not g:
            it = Gtk.MenuItem(label="Create or join a group first")
            it.set_sensitive(False)
            self.more_menu.append(it)
            backup_items()
            self.more_menu.show_all()
            return
        owner = self.chat.is_owner(self.gid)

        def add(label, cb, ok=True):
            it = Gtk.MenuItem(label=label)
            it.set_sensitive(ok)
            it.connect("activate", lambda *_: cb())
            self.more_menu.append(it)
        add("Invite people (show a join code)…", self.invite, owner and not g.get("removed"))
        add("Members…", self.members_dialog)
        if owner:
            chk = Gtk.CheckMenuItem(label="Only I can post (announcements)")
            chk.set_active(bool(g.get("owner_only")))
            chk.connect("toggled", lambda c: self.chat.set_owner_only(self.gid, c.get_active()))
            self.more_menu.append(chk)
            add("Rename group…", self.rename)
        add("Open the attachments folder", lambda: (self.chat.files_dir(self.gid).mkdir(parents=True, exist_ok=True),
                                                    self.win.active.go(str(self.chat.files_dir(self.gid)))))
        backup_items()
        self.more_menu.append(Gtk.SeparatorMenuItem())
        add("Delete group for everyone…" if owner else "Leave group…", self.leave)
        self.more_menu.show_all()

    def rename(self):
        name = self.win.ask_text("Rename group", "New name:", self.chat.groups[self.gid]["name"])
        if name and name.strip():
            self.chat.rename_group(self.gid, name.strip())

    def leave(self):
        g = self.chat.groups[self.gid]
        owner = self.chat.is_owner(self.gid)
        q = (f"Delete “{g['name']}” for everyone?\n\nAll members are removed. Each keeps their own copy of the history."
             if owner else f"Leave “{g['name']}”?\n\nYou'd need a new join code from the owner to come back.")
        if self.win.confirm(q):
            self.chat.leave_group(self.gid)
            self.gid = None
            self.refresh()

    def members_dialog(self):
        g = self.chat.groups.get(self.gid)
        if not g:
            return
        dlg = Gtk.Dialog(title=f"Members of {g['name']}", transient_for=self.get_toplevel(), modal=True)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        dlg.set_default_size(420, -1)
        lb = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin=10)
        owner = self.chat.is_owner(self.gid)
        for did, m in sorted(g.get("members", {}).items(), key=lambda kv: (kv[1].get("role") != "owner", kv[1]["name"])):
            row = Gtk.Box(spacing=8, margin=6)
            on = did == self.chat.me or self.chat.is_online(did)
            dot = Gtk.Label()
            dot.set_markup(f"<span foreground='{'#2ec27e' if on else '#9a9996'}'>●</span>")
            row.add(dot)
            lbl = Gtk.Label(xalign=0, hexpand=True)
            role = "owner" if m.get("role") == "owner" else "member"
            you = " (you)" if did == self.chat.me else ""
            lbl.set_markup(f"<b>{esc(m['name'])}</b>{you}\n<small>{role} · {esc(m.get('os', ''))}</small>")
            row.pack_start(lbl, True, True, 0)
            if owner and did != self.chat.me:
                rm = Gtk.Button(label="Remove")
                rm.connect("clicked", lambda _b, d=did, n=m["name"]: (
                    self.win.confirm(f"Remove {n} from the group?") and (self.chat.remove_member(self.gid, d),
                                                                         dlg.destroy())))
                row.add(rm)
            lb.add(row)
        dlg.get_content_area().add(lb)
        dlg.connect("response", lambda d, r: d.destroy())
        dlg.show_all()


class ChatWindow(Gtk.Window):
    def __init__(self, win):
        super().__init__(title=f"{APP_NAME} Chat")
        self.set_default_size(520, 700)
        self.set_icon(win.get_icon())
        self.panel = ChatPanel(win, in_window=True)
        self.add(self.panel)
        self.connect("destroy", lambda *_: win.chat_windows.remove(self) if self in win.chat_windows else None)


# ---------------------------------------------------------------- main window
CSS = b"""
.fm-active-bar { background-color: alpha(@theme_selected_bg_color, 0.14); }
.fm-preview { border-left: 1px solid alpha(currentColor, 0.12); }
.fm-footer { padding: 6px 10px; }
"""

SHORTCUTS = """Ctrl+T  new tab          Ctrl+W  close tab
F3  dual pane on/off      F6  jump to other pane
Space  preview panel      Ctrl+1 / Ctrl+2  list / grid
Ctrl+F  filter            Ctrl+L  type a path
Ctrl+C / X / V  copy, cut, paste files
Ctrl+Shift+N  new folder  Alt+Enter  properties
F4  open a terminal / Command Prompt in this folder
F2  rename                Delete  move to Trash
Shift+Delete  delete permanently   Ctrl+A  select all
Ctrl+H  hidden files      F5  refresh
Ctrl+Shift+D  switch theme (system / light / dark)
Alt+← / Alt+→ / Alt+↑  back, forward, up
Drag files onto a folder, a tab or the sidebar to move them
   (hold Ctrl to copy; files dragged in from other apps are copied)
Middle-click a folder  open it in a new tab
Send / Receive buttons  share files with nearby Arckad-D, phones and browsers"""


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, start=None):
        super().__init__(application=app, title=APP_NAME)
        self.cfg = read_json(CONFIG_FILE, {})
        for key, default in (("pinned", []), ("show_hidden", False), ("view", "list"), ("dual", False),
                             ("preview", True), ("autosort", False), ("autosort_background", False),
                             ("autosort_delay", 5)):
            self.cfg.setdefault(key, default)
        self.cfg.setdefault("file_icons", "colour" if IS_WIN else "system")
        ICON_STYLE["colour"] = self.cfg["file_icons"] == "colour" and colour_icons_supported()
        self.set_default_size(*self.cfg.get("size", [1280, 760]))
        self.cfg.setdefault("theme", "system")
        self.active = None
        self.clipboard = None
        self.sorter = None
        self.last_file = None
        self.timeline_win = None
        self.preview_timer = None
        self.share = QuickShare(on_event=self.on_share_event)
        self.nearby = Nearby(self)
        self.paired = Paired(self)
        self.chat = Chat(self)
        self.chat_windows = []
        self.share_win = None

        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        settings = Gtk.Settings.get_default()
        self.system_theme = settings.get_property("gtk-theme-name") or "Adwaita"
        self.system_prefer_dark = settings.get_property("gtk-application-prefer-dark-theme")
        self.apply_theme(self.cfg["theme"])
        self._build_ui()
        self.watch_drives()
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_close)
        self.connect("set-focus", self.on_set_focus)

        tabs = self.cfg.get("tabs", {})
        left = [start] if start else (tabs.get("left") or [str(HOME)])
        for loc in left:
            self.new_tab(self.left_nb, loc)
        for loc in tabs.get("right") or [str(HOME)]:
            self.new_tab(self.right_nb, loc, switch=False)
        self.show_all()
        self.infobar.set_revealed(False)
        self.update_bar.set_revealed(False)
        self.latest = None
        self.right_nb.set_visible(self.cfg["dual"])
        self.dual_btn.set_active(self.cfg["dual"])
        self.preview_btn.set_active(self.cfg["preview"])
        self.preview_rev.set_reveal_child(self.cfg["preview"])
        self.set_active(self.left_nb.get_nth_page(self.left_nb.get_current_page()))

        INDEX.listeners.append(self.on_index_updated)
        if not INDEX.fresh():
            INDEX.rebuild()
        GLib.timeout_add_seconds(60, self.tick)
        self.on_index_updated()
        self.apply_autosort(startup=True)
        if self.paired.pairs() or self.chat.active():   # paired devices and chat groups reconnect by themselves
            try:
                self.paired.ensure_running()
            except OSError as ex:
                print(f"{APP_NAME}: paired sharing unavailable: {ex}", file=sys.stderr)
        self.find_last_file(show=True)
        if time.time() - self.cfg.get("update_checked", 0) > 86400:      # quietly, once a day
            GLib.timeout_add_seconds(8, lambda: self.check_updates(manual=False) or False)

    # ---------- UI construction
    def icon_btn(self, icon, tip, cb):
        b = Gtk.Button.new_from_icon_name(icon, Gtk.IconSize.BUTTON)
        b.set_tooltip_text(tip)
        b.connect("clicked", cb)
        return b

    def _menu_button(self, label, icon, items):
        menu = Gtk.Menu()
        for entry in items:
            if entry is None:
                menu.append(Gtk.SeparatorMenuItem())
                continue
            if isinstance(entry, Gtk.MenuItem):
                menu.append(entry)
                continue
            text, cb = entry
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda *_a, cb=cb: cb())
            menu.append(item)
        menu.show_all()
        btn = Gtk.MenuButton(popup=menu)
        box = Gtk.Box(spacing=4)
        if icon:
            box.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
        if label:
            box.add(Gtk.Label(label=label))
            box.add(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.BUTTON))
        btn.add(box)
        return btn

    def _build_ui(self):
        hb = Gtk.HeaderBar(show_close_button=True, title=APP_NAME)
        self.set_titlebar(hb)
        self.logo_img = Gtk.Image()
        self.logo_img.set_tooltip_text(APP_NAME)
        hb.pack_start(self.logo_img)
        self.refresh_logo()
        last_btn = Gtk.Button()
        lb = Gtk.Box(spacing=6)
        lb.add(Gtk.Image.new_from_icon_name("document-open-recent-symbolic", Gtk.IconSize.BUTTON))
        lb.add(Gtk.Label(label="Last worked file"))
        last_btn.add(lb)
        last_btn.get_style_context().add_class("suggested-action")
        last_btn.set_tooltip_text("Remind me which file I worked on last")
        last_btn.connect("clicked", lambda *_: self.find_last_file(show=True))
        hb.pack_start(last_btn)
        timeline_btn = Gtk.Button(label="Where was I?")
        timeline_btn.set_tooltip_text("See your recent work grouped into sessions")
        timeline_btn.connect("clicked", lambda *_: self.open_timeline())
        hb.pack_start(timeline_btn)

        self.hidden_item = Gtk.CheckMenuItem(label="Show hidden files (Ctrl+H)")
        self.hidden_item.set_active(self.cfg["show_hidden"])
        self.hidden_item.connect("toggled", self.on_hidden_toggled)
        self.icons_item = Gtk.CheckMenuItem(label="Colourful file icons")
        self.icons_item.set_active(ICON_STYLE["colour"])
        self.icons_item.connect("toggled", self.on_icons_toggled)
        hb.pack_end(self._menu_button(None, "open-menu-symbolic", [
            self.hidden_item, self.icons_item, None,
            ("New tab (Ctrl+T)", lambda: self.new_tab()),
            ("New folder… (Ctrl+Shift+N)", lambda: self.new_folder(self.active)),
            ("New empty file…", lambda: self.new_file(self.active)),
            ("Team chat in its own window", lambda: self.open_chat_window()),
            ("Open terminal here (F4)", lambda: self.open_terminal(self.active.location
                                                                   if is_folder_loc(self.active.location) else str(HOME))),
            ("Pin this folder to sidebar", lambda: self.pin(self.active.location)),
            None,
        ] + ([] if INSTALLED or IS_WIN else [(f"Add {APP_NAME} to app menu", self.on_install)]) + [
            ("Keyboard shortcuts", lambda: self.info(SHORTCUTS, mono=True)),
            ("Change logo…", self.choose_logo),
            ("Use the default logo", self.reset_logo),
            ("Check for updates…", lambda: self.check_updates(manual=True)),
            (f"About {APP_NAME}", self.show_about),
        ]))
        hb.pack_end(self._theme_button())
        hb.pack_end(self._menu_button("Tools", None, [
            ("Organize this folder…", lambda: self.organize(self.active)),
            ("Find duplicate files…", lambda: self.duplicates(
                self.active.location if is_folder_loc(self.active.location) else str(HOME))),
            ("Compare selected files…", self.compare_selected),
            ("Auto-sort Downloads…", self.autosort_dialog),
            ("Send files…", lambda: self.open_share(self.active.selected_paths() or None, "nearby")),
            ("Receive files…", lambda: self.open_share(None, "receive")),
            None,
            ("Update search index now", INDEX.rebuild),
        ]))
        pair = Gtk.Box()
        pair.get_style_context().add_class("linked")
        self.share_btn = Gtk.Button()
        sb = Gtk.Box(spacing=6)
        sb.add(Gtk.Image.new_from_icon_name("send-to-symbolic", Gtk.IconSize.BUTTON))
        self.share_label = Gtk.Label(label="Send")
        sb.add(self.share_label)
        self.share_btn.add(sb)
        self.share_btn.set_tooltip_text("Send the selected files to a nearby Arckad-D, or share a link / QR code")
        self.share_btn.connect("clicked", lambda *_: self.open_share(self.active.selected_paths() or None, "nearby"))
        pair.add(self.share_btn)
        self.recv_btn = Gtk.Button()
        rb = Gtk.Box(spacing=6)
        rb.add(Gtk.Image.new_from_icon_name("folder-download-symbolic", Gtk.IconSize.BUTTON))
        self.recv_label = Gtk.Label(label="Receive")
        rb.add(self.recv_label)
        self.recv_btn.add(rb)
        self.recv_btn.set_tooltip_text("Let nearby Arckad-D devices send files to this computer")
        self.recv_btn.connect("clicked", lambda *_: self.open_share(None, "receive"))
        pair.add(self.recv_btn)
        hb.pack_end(pair)
        self.undo_btn = self.icon_btn("edit-undo-symbolic", "Undo last organize / auto-sort", self.on_undo)
        self.undo_btn.set_sensitive(bool(read_json(UNDO_FILE, [])))
        hb.pack_end(self.undo_btn)
        self.organize_btn = Gtk.Button(label="Organize")
        self.organize_btn.set_tooltip_text("Sort loose files in this folder into subfolders")
        self.organize_btn.connect("clicked", lambda *_: self.organize(self.active))
        hb.pack_end(self.organize_btn)
        self.preview_btn = Gtk.ToggleButton(label="Preview")
        self.preview_btn.set_tooltip_text("Show the preview panel (Space)")
        self.preview_btn.connect("toggled", self.on_preview_toggled)
        hb.pack_end(self.preview_btn)
        self.chat_btn = Gtk.Button(label="💬 Chat")
        self.chat_btn.set_tooltip_text("Team chat: groups, messages and files")
        self.chat_btn.connect("clicked", lambda *_: self.toggle_chat())
        hb.pack_end(self.chat_btn)
        self.dual_btn = Gtk.ToggleButton(label="Dual")
        self.dual_btn.set_tooltip_text("Two folders side by side (F3)")
        self.dual_btn.connect("toggled", self.on_dual_toggled)
        hb.pack_end(self.dual_btn)
        self.spinner = Gtk.Spinner()
        hb.pack_end(self.spinner)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.add(outer)
        self.infobar = Gtk.InfoBar(show_close_button=True)
        self.infobar.set_message_type(Gtk.MessageType.INFO)
        self.info_label = Gtk.Label(xalign=0, wrap=True)
        self.infobar.get_content_area().add(self.info_label)
        self.infobar.add_button("Open", 1)
        self.infobar.add_button("Show in folder", 2)
        self.infobar.add_button("Where was I?", 3)
        self.infobar.connect("response", self.on_infobar)
        outer.add(self.infobar)
        self.update_bar = Gtk.InfoBar(show_close_button=True)
        self.update_bar.set_message_type(Gtk.MessageType.OTHER)
        self.update_label = Gtk.Label(xalign=0, wrap=True)
        self.update_bar.get_content_area().add(self.update_label)
        self.update_bar.add_button("Update now", 1)
        self.update_bar.add_button("What's new", 2)
        self.update_bar.connect("response", self.on_update_bar)
        outer.add(self.update_bar)

        main = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL)
        main.set_position(220)
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.sidebar = Gtk.ListBox()
        self.sidebar.get_style_context().add_class("navigation-sidebar")
        self.sidebar.connect("row-activated", lambda lb, row: self.sidebar_activate(row))
        self.sidebar.connect("button-press-event", self.on_sidebar_click)
        self.sidebar.drag_dest_set(Gtk.DestDefaults.ALL, [Gtk.TargetEntry.new("text/uri-list", 0, 0)],
                                   Gdk.DragAction.MOVE | Gdk.DragAction.COPY)
        self.sidebar.connect("drag-data-received", self.on_sidebar_drop)
        self.sidebar.connect("drag-motion", self.on_sidebar_motion)
        side_scroll = Gtk.ScrolledWindow(vexpand=True)
        side_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        side_scroll.add(self.sidebar)
        side.pack_start(side_scroll, True, True, 0)
        footer = Gtk.Box(spacing=4)
        footer.get_style_context().add_class("fm-footer")
        self.index_label = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        footer.pack_start(self.index_label, True, True, 0)
        footer.add(self.icon_btn("view-refresh-symbolic", "Update the search index now", lambda *_: INDEX.rebuild()))
        side.add(footer)
        main.pack1(side, False, False)

        content = Gtk.Box()
        self.dual_paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, hexpand=True)
        self.left_nb = self._notebook()
        self.right_nb = self._notebook()
        self.dual_paned.pack1(self.left_nb, True, False)
        self.dual_paned.pack2(self.right_nb, True, False)
        content.pack_start(self.dual_paned, True, True, 0)
        self.preview = PreviewPanel(self)
        self.preview_rev = Gtk.Revealer(transition_type=Gtk.RevealerTransitionType.SLIDE_LEFT)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.right_stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.right_stack.add_titled(self.preview, "preview", "Preview")
        self.chat_panel = ChatPanel(self)
        self.right_stack.add_titled(self.chat_panel, "chat", "Chat")
        sw = Gtk.StackSwitcher(stack=self.right_stack, halign=Gtk.Align.CENTER, margin_top=6)
        right.add(sw)
        right.pack_start(self.right_stack, True, True, 0)
        self.right_stack.connect("notify::visible-child-name", lambda *_: self.update_chat_button())
        self.preview_rev.add(right)
        content.add(self.preview_rev)
        main.pack2(content, True, False)
        outer.pack_start(main, True, True, 0)
        self.build_sidebar()

    def _notebook(self):
        nb = Gtk.Notebook(scrollable=True)
        add = self.icon_btn("list-add-symbolic", "New tab (Ctrl+T)", lambda *_: self.new_tab(nb))
        add.set_relief(Gtk.ReliefStyle.NONE)
        add.show()
        nb.set_action_widget(add, Gtk.PackType.END)
        nb.connect("switch-page", self.on_switch_page)
        nb.connect("page-removed", lambda *_: self.update_tab_closers())
        return nb

    # ---------- updates
    def check_updates(self, manual=True):
        if manual and self.active:
            self.active.flash("Checking for updates…")

        def work():
            try:
                rel, err = fetch_latest_release(), None
            except Exception as ex:                       # offline, private repository, GitHub busy…
                rel, err = None, str(getattr(ex, "reason", None) or ex)
            GLib.idle_add(self._got_release, rel, err, manual)
        threading.Thread(target=work, daemon=True).start()

    def _got_release(self, rel, err, manual):
        self.cfg["update_checked"] = time.time()
        if err or not rel:
            if manual:
                self.error(f"Couldn't check for updates.\n\n{err}\n\nCheck your internet connection. "
                           f"(Updates come from github.com/{UPDATE_REPO}, which must be public.)")
            return False
        latest = rel.get("tag_name", "").lstrip("vV")
        if version_tuple(latest) <= version_tuple(APP_VERSION):
            if manual:
                self.info(f"You're up to date. {APP_NAME} {APP_VERSION} is the newest version.")
            return False
        self.latest = rel
        how = {"windows": "Arckad-D closes, a small window shows the install (no questions), then Arckad-D reopens.",
               "deb": "You'll be asked for your password once."}.get(install_kind(), "")
        self.update_label.set_markup(f"<b>{APP_NAME} {esc(latest)} is available</b> (you have {APP_VERSION}). "
                                     f"{esc(how)}")
        self.update_bar.set_revealed(True)
        return False

    def on_update_bar(self, bar, resp):
        if resp == 1:
            self.start_update()
        elif resp == 2 and self.latest:
            open_default(self.latest.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/latest")
            return
        bar.set_revealed(False)

    def start_update(self):
        rel = self.latest
        if not rel:
            return
        kind = install_kind()
        asset = pick_asset(rel, kind) if kind != "manual" else None
        if asset is None:
            self.info("This copy can't update itself (it isn't installed from the installer / .deb), "
                      "so the download page will open instead.")
            open_default(rel.get("html_url") or f"https://github.com/{UPDATE_REPO}/releases/latest")
            return
        dest = Path(tempfile.gettempdir()) / asset["name"]
        dlg = Gtk.Dialog(title=f"Updating {APP_NAME}", transient_for=self, modal=True)
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        label = Gtk.Label(label=f"Downloading {asset['name']}…", xalign=0)
        bar = Gtk.ProgressBar(show_text=True)
        bar.set_size_request(380, -1)
        box.add(label)
        box.add(bar)
        state = {"cancel": False}
        dlg.connect("response", lambda *_: state.update(cancel=True))
        dlg.show_all()

        def progress(done, total):
            GLib.idle_add(lambda: (bar.set_fraction(done / total if total else 0),
                                   bar.set_text(f"{human_size(done)} of {human_size(total)}")) and False)

        def work():
            try:
                download_asset(asset, dest, progress, lambda: state["cancel"])
                GLib.idle_add(self._install_update, dlg, kind, dest, label)
            except InterruptedError:
                GLib.idle_add(dlg.destroy)
            except Exception as ex:
                msg = str(ex)
                GLib.idle_add(lambda: (dlg.destroy(), self.error(f"The update couldn't be downloaded: {msg}")) and False)
        threading.Thread(target=work, daemon=True).start()

    def _install_update(self, dlg, kind, path, label):
        if kind == "windows":
            label.set_text("Installing… Arckad-D will close and reopen by itself.")
            GLib.timeout_add(800, lambda: self._run_windows_setup(path) or False)
            return False
        label.set_text("Installing… enter your password if asked.")

        def work():
            try:
                proc = subprocess.run(["pkexec", "apt-get", "install", "-y", "--allow-downgrades", str(path)],
                                      capture_output=True, text=True)
                ok, msg = proc.returncode == 0, (proc.stderr or proc.stdout).strip()[-500:]
            except OSError as ex:
                ok, msg = False, str(ex)
            GLib.idle_add(self._deb_installed, dlg, ok, msg, path)
        threading.Thread(target=work, daemon=True).start()
        return False

    def _run_windows_setup(self, path):
        """Start the installer directly (with its progress window). The installer itself waits until this
        Arckad-D has fully closed (it watches the "ArckadD-Running" mutex), installs, and reopens Arckad-D;
        if it fails, it reopens this version, which then explains what happened."""
        log = Path(tempfile.gettempdir()) / "arckad-d-update.log"
        try:
            subprocess.Popen([str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", f"/LOG={log}"],
                             creationflags=0x00000008 | 0x00000200, close_fds=True)   # detached
        except OSError as ex:
            self.error(f"Couldn't start the installer: {ex.strerror or ex}\n\nIt was downloaded to:\n{path}\n\n"
                       "You can run it yourself.")
            return
        self.on_close()
        self.get_application().quit()
        GLib.timeout_add(1500, lambda: os._exit(0))           # make sure nothing keeps this process alive

    def show_update_failure(self, code):
        """Shown when the Windows installer stopped (Arckad-D was reopened by the update helper)."""
        reasons = {"1": "the installer couldn't start", "2": "it was cancelled before installing",
                   "3": "a problem while preparing", "4": "a problem while copying files",
                   "5": "it was cancelled while installing", "7": "a program was still using Arckad-D's files",
                   "8": "Windows needs a restart first"}
        log = Path(tempfile.gettempdir()) / "arckad-d-update.log"
        tail = ""
        try:
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = "\n".join(l for l in lines[-12:] if l.strip())
        except OSError:
            pass
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.NONE, text="The update wasn't installed")
        d.format_secondary_text(
            f"The installer stopped ({reasons.get(str(code), 'error code ' + str(code))}). Arckad-D is still on "
            f"version {APP_VERSION}.\n\nYou can try again from ☰ → Check for updates, or install the new version "
            f"yourself from the Releases page.\n\nInstaller log: {log}\n\n{tail[-1200:]}")
        d.add_buttons("Close", Gtk.ResponseType.CLOSE, "Open Releases page", Gtk.ResponseType.ACCEPT)
        if d.run() == Gtk.ResponseType.ACCEPT:
            open_default(f"https://github.com/{UPDATE_REPO}/releases/latest")
        d.destroy()
        return False

    def _deb_installed(self, dlg, ok, msg, path):
        dlg.destroy()
        self.update_bar.set_revealed(False)
        if not ok:
            self.error("The update wasn't installed (maybe the password prompt was cancelled).\n\n"
                       f"You can install it yourself with:\n  sudo apt install {path}\n\n{msg}")
            return False
        if self.confirm(f"{APP_NAME} was updated. Restart it now to use the new version?"):
            subprocess.Popen(["arckad-d"], start_new_session=True)
            self.on_close()
            self.get_application().quit()
        return False

    # ---------- light / dark theme
    THEMES = [("system", "🖥", "Follow system"), ("light", "☀", "Light"), ("dark", "🌙", "Dark")]

    def _theme_button(self):
        menu = Gtk.Menu()
        group = None
        self.theme_items = {}
        for key, icon, label in self.THEMES:
            item = Gtk.RadioMenuItem.new_with_label_from_widget(group, f"{icon}   {label}")
            group = item
            item.set_active(self.cfg["theme"] == key)
            item.connect("toggled", self.on_theme_item, key)
            self.theme_items[key] = item
            menu.append(item)
        menu.show_all()
        self.theme_btn = Gtk.MenuButton(popup=menu)
        self.theme_label = Gtk.Label()
        self.theme_btn.add(self.theme_label)
        self.update_theme_button()
        return self.theme_btn

    def on_theme_item(self, item, key):
        if item.get_active():
            self.cfg["theme"] = key
            self.apply_theme(key)
            self.update_theme_button()
            write_json(CONFIG_FILE, self.cfg)

    def update_theme_button(self):
        icon, label = {k: (i, l) for k, i, l in self.THEMES}[self.cfg["theme"]]
        self.theme_label.set_text(icon)
        self.theme_btn.set_tooltip_text(f"Theme: {label} (click to change)")

    @staticmethod
    def _theme_exists(name):
        dirs = [Path(GLib.get_user_data_dir()) / "themes", HOME / ".themes"] + \
               [Path(d) / "themes" for d in GLib.get_system_data_dirs()]
        return any((d / name / "gtk-3.0").is_dir() for d in dirs)

    def apply_theme(self, mode):
        s = Gtk.Settings.get_default()
        base = self.system_theme
        light = base[:-5] if base.lower().endswith("-dark") else base
        if light != "Adwaita" and not self._theme_exists(light):
            light = "Adwaita"          # built into GTK, always available
        if mode == "light":
            s.set_property("gtk-theme-name", light)
            s.set_property("gtk-application-prefer-dark-theme", False)
        elif mode == "dark":
            dark = light + "-dark"
            s.set_property("gtk-theme-name", dark if self._theme_exists(dark) else light)
            s.set_property("gtk-application-prefer-dark-theme", True)
        else:
            s.set_property("gtk-theme-name", base)
            s.set_property("gtk-application-prefer-dark-theme",
                           windows_dark_mode() if IS_WIN else self.system_prefer_dark)

    def cycle_theme(self):
        keys = [k for k, _, _ in self.THEMES]
        nxt = keys[(keys.index(self.cfg["theme"]) + 1) % len(keys)]
        self.theme_items[nxt].set_active(True)

    def refresh_logo(self):
        big, small = logo_pixbuf(256), logo_pixbuf(28)
        if big:
            self.set_icon(big)
        else:
            self.set_icon_name("system-file-manager")
        if small:
            self.logo_img.set_from_pixbuf(small)
        self.logo_img.set_visible(small is not None)

    def choose_logo(self):
        dlg = Gtk.FileChooserNative.new("Choose a logo image", self, Gtk.FileChooserAction.OPEN, "Use as logo", "Cancel")
        filt = Gtk.FileFilter()
        filt.set_name("Images (PNG, SVG, JPG, WebP)")
        for ext in LOGO_EXTS:
            filt.add_pattern(f"*.{ext}")
            filt.add_pattern(f"*.{ext.upper()}")
        dlg.add_filter(filt)
        dlg.set_current_folder(str(GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_PICTURES) or HOME))
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            path = dlg.get_filename()
            if ext_of(path) not in LOGO_EXTS or load_scaled(path, 64) is None:
                self.error("That file can't be used as a logo. Please pick a PNG, SVG, JPG or WebP image.")
            else:
                set_custom_logo(path)
                self.refresh_logo()
                self.active.flash("Logo changed. The dock icon updates the next time you open the app")
        dlg.destroy()

    def reset_logo(self):
        set_custom_logo(None)
        self.refresh_logo()
        self.active.flash("Back to the default Arckad-D logo")

    def show_about(self):
        dlg = Gtk.AboutDialog(transient_for=self, modal=True)
        dlg.set_program_name(APP_NAME)
        dlg.set_version(APP_VERSION)
        dlg.set_comments("A file manager that remembers what you worked on,\n"
                         "keeps folders tidy and finds anything instantly.")
        logo = logo_pixbuf(128)
        if logo:
            dlg.set_logo(logo)
        dlg.add_credit_section("Emoji", ["Noto Emoji by Google (Apache License 2.0)",
                                         "images via emoji-data by Cal Henderson (MIT)"])
        dlg.run()
        dlg.destroy()

    # ---------- tabs & panes
    def new_tab(self, nb=None, location=None, switch=True):
        nb = nb or (self.active.get_parent() if self.active else self.left_nb)
        if location is None:
            location = self.active.location if self.active and is_folder_loc(self.active.location) else str(HOME)
        pane = FilePane(self, location)
        tab = Gtk.Box(spacing=4)
        pane.tab_label = Gtk.Label(ellipsize=Pango.EllipsizeMode.END, max_width_chars=18)
        self.set_tab_text(pane)
        tab.add(pane.tab_label)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic", Gtk.IconSize.MENU)
        close.set_relief(Gtk.ReliefStyle.NONE)
        close.set_tooltip_text("Close tab (Ctrl+W)")
        close.connect("clicked", lambda *_: self.close_tab(pane))
        tab.add(close)
        pane.tab_close = close
        tab.show_all()
        idx = nb.append_page(pane, tab)
        nb.set_tab_reorderable(pane, True)
        pane.show_all()
        if switch:
            nb.set_current_page(idx)
            self.set_active(pane)
        self.update_tab_closers()
        return pane

    def set_tab_text(self, pane):
        title = pane.title()
        pane.tab_label.set_text(title)
        pane.tab_label.set_width_chars(min(len(title), 18))
        pane.tab_label.set_tooltip_text(pane.location)

    def update_tab_closers(self):
        for nb in (self.left_nb, self.right_nb):
            n = nb.get_n_pages()
            for i in range(n):
                page = nb.get_nth_page(i)
                if hasattr(page, "tab_close"):
                    page.tab_close.set_visible(n > 1)

    def close_tab(self, pane):
        nb = pane.get_parent()
        if nb.get_n_pages() <= 1:
            return
        pane.cleanup()
        nb.remove_page(nb.page_num(pane))
        if pane is self.active:
            self.set_active(nb.get_nth_page(nb.get_current_page()))

    def on_switch_page(self, nb, page, num):
        if self.active is None or self.active.get_parent() is nb:
            GLib.idle_add(lambda: self.set_active(page) or False)

    def on_set_focus(self, win, widget):
        while widget is not None and not isinstance(widget, FilePane):
            widget = widget.get_parent()
        if widget is not None:
            self.set_active(widget)

    def set_active(self, pane):
        if pane is None or pane is self.active:
            return
        if self.active is not None:
            self.active.row1.get_style_context().remove_class("fm-active-bar")
        self.active = pane
        if self.cfg["dual"]:
            pane.row1.get_style_context().add_class("fm-active-bar")
        self.sync_sidebar()
        self.update_title()
        self.update_organize_hint()
        self.on_selection(pane)

    def other_pane(self):
        if not self.cfg["dual"] or self.active is None:
            return None
        nb = self.right_nb if self.active.get_parent() is self.left_nb else self.left_nb
        return nb.get_nth_page(nb.get_current_page())

    def all_panes(self):
        for nb in (self.left_nb, self.right_nb):
            for i in range(nb.get_n_pages()):
                yield nb.get_nth_page(i)

    def pane_location_changed(self, pane):
        if pane.tab_label:
            self.set_tab_text(pane)
        if pane is self.active:
            self.sync_sidebar()
            self.update_title()

    def update_title(self):
        if self.active:
            loc = self.active.location
            self.set_title(short(loc) if is_folder_loc(loc) else self.active.title())

    def on_dual_toggled(self, btn):
        on = btn.get_active()
        self.cfg["dual"] = on
        self.right_nb.set_visible(on)
        if on:
            w = self.dual_paned.get_allocated_width()
            if w > 100:
                self.dual_paned.set_position(w // 2)
            if self.active:
                self.active.row1.get_style_context().add_class("fm-active-bar")
        else:
            if self.active and self.active.get_parent() is self.right_nb:
                self.set_active(self.left_nb.get_nth_page(self.left_nb.get_current_page()))
            for p in self.all_panes():
                p.row1.get_style_context().remove_class("fm-active-bar")

    def open_in_other(self, path):
        other = self.other_pane()
        if other:
            other.go(path)

    def update_spinner(self):
        busy = INDEX.building or any(getattr(p, "busy", False) for p in self.all_panes())
        (self.spinner.start if busy else self.spinner.stop)()

    def spin(self, on):
        self.update_spinner() if not on else self.spinner.start()

    # ---------- sidebar
    def build_sidebar(self):
        for row in self.sidebar.get_children():
            self.sidebar.remove(row)
        self._side_header("Quick access")
        self._side_row("Recent files", "document-open-recent-symbolic", "recent")
        self._side_row("Home", "user-home-symbolic", str(HOME))
        specials = [(GLib.UserDirectory.DIRECTORY_DESKTOP, "user-desktop-symbolic"),
                    (GLib.UserDirectory.DIRECTORY_DOCUMENTS, "folder-documents-symbolic"),
                    (GLib.UserDirectory.DIRECTORY_DOWNLOAD, "folder-download-symbolic"),
                    (GLib.UserDirectory.DIRECTORY_PICTURES, "folder-pictures-symbolic"),
                    (GLib.UserDirectory.DIRECTORY_MUSIC, "folder-music-symbolic"),
                    (GLib.UserDirectory.DIRECTORY_VIDEOS, "folder-videos-symbolic")]
        for kind, icon in specials:
            path = GLib.get_user_special_dir(kind)
            if path and os.path.isdir(path) and Path(path) != HOME:
                self._side_row(Path(path).name, icon, path)
        self._side_header("Tags")
        for tag, color in TAGS.items():
            self._side_row(tag, None, "tag:" + tag, dot=color)
        self._side_row("Files with notes", "accessories-text-editor-symbolic", "notes")
        pinned = [p for p in self.cfg["pinned"] if os.path.isdir(p)]
        self._side_header("Pinned")
        if not pinned:
            self._side_header("Right-click a folder → Pin to sidebar", dim=True)
        for p in pinned:
            self._side_row(Path(p).name or p, "folder-symbolic", p, pinned=True)
        self._side_header("Devices")
        if IS_WIN:
            for drive in self.windows_drives():
                label, free = self.drive_info(drive)
                self._side_row(label, "drive-harddisk-symbolic", drive, sub=free)
        else:
            self._side_row("Computer", "drive-harddisk-symbolic", "/", sub=self.drive_info("/")[1])
            for kind, obj, name, path in self.linux_devices():
                icon_widget = obj.get_symbolic_icon() if hasattr(obj, "get_symbolic_icon") else None
                if kind == "mount":
                    eject = None
                    if obj.can_eject() or obj.can_unmount():
                        eject = Gtk.Button.new_from_icon_name("media-eject-symbolic", Gtk.IconSize.MENU)
                        eject.set_relief(Gtk.ReliefStyle.NONE)
                        eject.set_tooltip_text(f"Eject “{name}” so it's safe to remove")
                        eject.connect("clicked", lambda _b, m=obj, n=name: self.eject(m, n))
                    self._side_row(name, None, path, sub=self.drive_info(path)[1], gicon=icon_widget, extra=eject)
                else:                                         # plugged in but not opened yet
                    row = self._side_row(name, None, "volume:" + name, sub="Not opened yet · click to open",
                                         gicon=icon_widget)
                    row.volume = obj
        self.sidebar.show_all()
        self.sync_sidebar()

    # ---------- drives (USB sticks, SD cards, external and extra disks)
    def watch_drives(self):
        """Rebuild the Devices list the moment a drive is plugged in, opened, ejected or removed."""
        self._drive_timer = None
        if IS_WIN:
            self._win_drives = self.windows_drives()
            GLib.timeout_add_seconds(3, self._poll_windows_drives)
            return
        self.vm = Gio.VolumeMonitor.get()
        for sig in ("mount-added", "mount-removed", "mount-changed", "volume-added", "volume-removed",
                    "volume-changed", "drive-connected", "drive-disconnected"):
            self.vm.connect(sig, self._drives_changed, sig)

    def _drives_changed(self, monitor, obj, sig):
        if sig == "mount-added" and hasattr(obj, "get_name"):
            self.active.flash(f"“{obj.get_name()}” connected: it's in the sidebar under Devices")
        if sig == "mount-removed":
            root = obj.get_root().get_path() if obj.get_root() else None
            if root:
                for pane in self.all_panes():
                    loc = pane.location or ""
                    if is_folder_loc(loc) and (loc == root or loc.startswith(root.rstrip(os.sep) + os.sep)):
                        pane.go(str(HOME))
        if self._drive_timer:
            GLib.source_remove(self._drive_timer)
        self._drive_timer = GLib.timeout_add(400, self._rebuild_after_drive_change)

    def _rebuild_after_drive_change(self):
        self._drive_timer = None
        self.build_sidebar()
        return False

    def linux_devices(self):
        """[(kind, object, name, path)]: opened drives first, then plugged-in ones not opened yet."""
        out, seen = [], set()
        vm = getattr(self, "vm", None) or Gio.VolumeMonitor.get()
        for m in vm.get_mounts():
            try:
                if m.is_shadowed():
                    continue
                root = m.get_root()
                path = root.get_path() if root else None
            except Exception:
                continue
            if not path or path == "/" or path in seen:
                continue
            seen.add(path)
            out.append(("mount", m, m.get_name(), path))
        for v in vm.get_volumes():
            try:
                if v.get_mount() is None and v.can_mount():
                    out.append(("volume", v, v.get_name(), None))
            except Exception:
                continue
        return out

    @staticmethod
    def windows_drives():
        import string
        return [f"{c}:\\" for c in string.ascii_uppercase if os.path.exists(f"{c}:\\")]

    def _poll_windows_drives(self):
        now = self.windows_drives()
        if now != self._win_drives:
            added = set(now) - set(self._win_drives)
            self._win_drives = now
            self.build_sidebar()
            if added and self.active:
                self.active.flash(f"Drive {', '.join(sorted(added))} connected: it's in the sidebar under Devices")
        return True

    @staticmethod
    def drive_info(path):
        """(label, "12.3 GB free of 32 GB") for a drive's folder."""
        label = path
        try:
            info = Gio.File.new_for_path(path).query_filesystem_info("filesystem::free,filesystem::size", None)
            free, size = info.get_attribute_uint64("filesystem::free"), info.get_attribute_uint64("filesystem::size")
            text = f"{human_size(free)} free of {human_size(size)}" if size else ""
        except GLib.Error:
            text = ""
        if IS_WIN:
            try:
                import ctypes
                buf = ctypes.create_unicode_buffer(261)
                ctypes.windll.kernel32.GetVolumeInformationW(path, buf, 261, None, None, None, None, 0)
                label = f"{buf.value} ({path[:2]})" if buf.value else f"Drive {path[:2]}"
            except Exception:
                label = f"Drive {path[:2]}"
        return label, text

    def sidebar_activate(self, row):
        key = getattr(row, "key", None)
        if not key:
            return
        volume = getattr(row, "volume", None)
        if volume is None:
            self.active.go(key)
            return
        name = volume.get_name()
        self.active.flash(f"Opening “{name}”…")
        op = Gtk.MountOperation(parent=self)          # asks for a password if the drive is encrypted

        def done(vol, res):
            try:
                vol.mount_finish(res)
            except GLib.Error as ex:
                self.error(f"Couldn't open “{name}”:\n\n{ex.message}")
                return
            mount = vol.get_mount()
            path = mount.get_root().get_path() if mount and mount.get_root() else None
            if path:
                self.active.go(path)
        volume.mount(Gio.MountMountFlags.NONE, op, None, done)

    def eject(self, mount, name):
        root = mount.get_root().get_path() if mount.get_root() else None
        for pane in self.all_panes():                     # leave the drive first, or it counts as "busy"
            loc = pane.location or ""
            if root and is_folder_loc(loc) and (loc == root or loc.startswith(root.rstrip(os.sep) + os.sep)):
                pane.go(str(HOME))
        op = Gtk.MountOperation(parent=self)

        def done(m, res):
            try:
                (m.eject_with_operation_finish if m.can_eject() else m.unmount_with_operation_finish)(res)
                self.active.flash(f"“{name}” can be safely removed now")
            except GLib.Error as ex:
                self.error(f"Couldn't eject “{name}”:\n\n{ex.message}\n\nClose any files from it that are still open, then try again.")
        if mount.can_eject():
            mount.eject_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)
        else:
            mount.unmount_with_operation(Gio.MountUnmountFlags.NONE, op, None, done)

    def _side_header(self, text, dim=False):
        row = Gtk.ListBoxRow(selectable=False, activatable=False)
        label = Gtk.Label(xalign=0, margin_start=10, margin_top=4 if dim else 10, margin_bottom=2, wrap=True)
        label.set_markup(f"<small>{esc(text)}</small>" if dim else f"<b><small>{esc(text.upper())}</small></b>")
        label.get_style_context().add_class("dim-label")
        row.add(label)
        self.sidebar.add(row)

    def _side_row(self, text, icon, key, pinned=False, dot=None, sub=None, gicon=None, extra=None):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=8, margin=5, margin_start=10)
        if dot:
            d = Gtk.Label()
            d.set_markup(f'<span foreground="{dot}" size="large">●</span>')
            box.add(d)
        elif gicon is not None:
            box.add(Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.MENU))
        else:
            box.add(Gtk.Image.new_from_icon_name(icon or "drive-removable-media-symbolic", Gtk.IconSize.MENU))
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.add(Gtk.Label(label=text, xalign=0, ellipsize=Pango.EllipsizeMode.END))
        if sub:
            s = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
            s.set_markup(f"<small>{esc(sub)}</small>")
            s.get_style_context().add_class("dim-label")
            texts.add(s)
        box.pack_start(texts, True, True, 0)
        if extra is not None:
            box.pack_end(extra, False, False, 0)
        row.add(box)
        row.key, row.pinned = key, pinned
        row.set_tooltip_text(key if is_folder_loc(key) and not key.startswith("volume:") else None)
        self.sidebar.add(row)
        return row

    def sync_sidebar(self):
        loc = self.active.location if self.active else None
        for row in self.sidebar.get_children():
            if getattr(row, "key", None) == loc:
                self.sidebar.select_row(row)
                return
        self.sidebar.unselect_all()

    def on_sidebar_click(self, lb, event):
        row = lb.get_row_at_y(int(event.y))
        if not row or not getattr(row, "key", None):
            return False
        if event.button == 2 and is_folder_loc(row.key):
            self.new_tab(location=row.key, switch=False)
            return True
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        items = [("Open in new tab", lambda: self.new_tab(location=row.key))]
        if self.cfg["dual"]:
            items.append(("Open in other pane", lambda: self.open_in_other(row.key)))
        if row.pinned:
            items.append(("Unpin", lambda: self.unpin(row.key)))
        for label, cb in items:
            item = Gtk.MenuItem(label=label)
            item.connect("activate", lambda _i, cb=cb: cb())
            menu.append(item)
        menu.show_all()
        menu.attach_to_widget(lb, None)
        menu.popup_at_pointer(event)
        return True

    def on_sidebar_motion(self, lb, context, x, y, time_):
        row = lb.get_row_at_y(y)
        if row is not None and is_folder_loc(getattr(row, "key", "") or ""):
            lb.drag_highlight_row(row)
        else:
            lb.drag_unhighlight_row()
        return False

    def on_sidebar_drop(self, lb, context, x, y, selection, info, time_):
        lb.drag_unhighlight_row()
        row = lb.get_row_at_y(y)
        dest = getattr(row, "key", None) if row else None
        if not dest or not is_folder_loc(dest):
            return
        paths = [p for p in (Gio.File.new_for_uri(u).get_path() for u in (selection.get_uris() or [])) if p]
        internal = Gtk.drag_get_source_widget(context) is not None
        mods = Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_modifier_state()
        self.handle_drop(paths, dest, internal, bool(mods & Gdk.ModifierType.CONTROL_MASK),
                         bool(mods & Gdk.ModifierType.SHIFT_MASK))

    def pin(self, path):
        if is_folder_loc(path) and path not in self.cfg["pinned"]:
            self.cfg["pinned"].append(path)
            write_json(CONFIG_FILE, self.cfg)
            self.build_sidebar()

    def unpin(self, path):
        self.cfg["pinned"] = [p for p in self.cfg["pinned"] if p != path]
        write_json(CONFIG_FILE, self.cfg)
        self.build_sidebar()

    # ---------- index
    def on_index_updated(self):
        if INDEX.building:
            self.index_label.set_markup("<small>🔍 Indexing your files for instant search…</small>")
        elif INDEX.available():
            self.index_label.set_markup(f"<small>🔍 {INDEX.count:,} files indexed\nupdated {ago(INDEX.updated)}</small>")
        else:
            self.index_label.set_markup("<small>🔍 Search index not built yet</small>")
        self.update_spinner()
        return False

    def tick(self):
        if not INDEX.fresh() and not INDEX.building:
            INDEX.rebuild()
        self.on_index_updated()
        return True

    # ---------- selection & preview
    def on_selection(self, pane):
        if pane is not self.active:
            return
        if self.preview_timer:
            GLib.source_remove(self.preview_timer)
        self.preview_timer = GLib.timeout_add(120, self._update_preview)

    def _update_preview(self):
        self.preview_timer = None
        if self.active and self.preview_rev.get_reveal_child():
            self.preview.show_paths(self.active.selected_paths())
        return False

    def on_preview_toggled(self, btn):
        self.cfg["preview"] = btn.get_active()
        self.preview_rev.set_reveal_child(btn.get_active())
        if btn.get_active():
            self._update_preview()

    def update_organize_hint(self):
        pane = self.active
        ctx = self.organize_btn.get_style_context()
        ctx.remove_class("suggested-action")
        self.organize_btn.set_sensitive(pane is not None and pane.mode == "folder")
        if pane and pane.mode == "folder" and pane.store is not None:
            if sum(1 for r in pane.store if not r[C_ISDIR]) >= CLUTTER_LIMIT:
                ctx.add_class("suggested-action")

    # ---------- tags & notes
    def toggle_tag(self, paths, tag, on):
        for p in paths:
            tags = set(TAG_STORE.tags(p))
            (tags.add if on else tags.discard)(tag)
            TAG_STORE.set_tags(p, tags)
        self.on_tags_changed(paths)

    def on_tags_changed(self, paths, from_preview=False):
        for pane in self.all_panes():
            pane.refresh_tags(paths)
        if not from_preview:
            self.preview.tags_changed(paths)

    def edit_note(self, path):
        self.preview_btn.set_active(True)
        self.active.select_paths([path])
        self.preview.show_file(path)
        GLib.timeout_add(250, lambda: self.preview.focus_note() or False)

    # ---------- "last worked file" banner
    def find_last_file(self, show):
        def work():
            items = recent_activity(days=60, limit=1)
            GLib.idle_add(self.got_last_file, items[0] if items else None, show)
        threading.Thread(target=work, daemon=True).start()

    def got_last_file(self, item, show):
        if not item:
            self.last_file = None
            self.info_label.set_text("No recently used files found yet.")
        else:
            ts, p = item
            self.last_file = str(p)
            self.info_label.set_markup(
                f"You were last working on <b>{esc(p.name)}</b>\n"
                f"<small>in {esc(short(p.parent))}, {ago(ts)}</small>")
        for resp in (1, 2):
            self.infobar.set_response_sensitive(resp, bool(self.last_file))
        if show:
            self.infobar.set_revealed(True)
        return False

    def on_infobar(self, bar, resp):
        if resp == 1 and self.last_file:
            self.open_file(self.last_file)
        elif resp == 2 and self.last_file:
            self.active.show_in_folder(self.last_file)
        elif resp == 3:
            self.open_timeline()
        bar.set_revealed(False)

    def open_timeline(self):
        if self.timeline_win is None:
            self.timeline_win = TimelineWindow(self)
            self.timeline_win.connect("destroy", lambda *_: setattr(self, "timeline_win", None))
            self.timeline_win.show_all()
        else:
            self.timeline_win.reload()
            self.timeline_win.present()

    # ---------- opening
    def open_path(self, path):
        if os.path.isdir(path):
            self.active.go(path)
            self.present()
        else:
            self.open_file(path)

    def open_file(self, path):
        gfile = Gio.File.new_for_path(path)
        try:
            open_default(path)
        except (GLib.Error, OSError):
            self.open_with(path)
            return
        try:
            Gtk.RecentManager.get_default().add_item(gfile.get_uri())
        except Exception:
            pass
        if self.active:
            self.active.flash(f"Opened {os.path.basename(path)}")

    def open_with(self, path):
        if IS_WIN:
            subprocess.Popen(["rundll32.exe", "shell32.dll,OpenAs_RunDLL", path])
            return
        gfile = Gio.File.new_for_path(path)
        dlg = Gtk.AppChooserDialog.new(self, Gtk.DialogFlags.MODAL, gfile)
        if dlg.run() == Gtk.ResponseType.OK:
            info = dlg.get_app_info()
            if info:
                info.launch([gfile], None)
                Gtk.RecentManager.get_default().add_item(gfile.get_uri())
        dlg.destroy()

    # ---------- file operations
    def copy_text(self, text):
        Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD).set_text(text, -1)
        self.active.flash("Copied to clipboard")

    def set_clipboard(self, paths, move):
        self.clipboard = (list(paths), move)
        word = "Cut" if move else "Copied"
        self.active.flash(f"{word} {len(paths)} item{'s' if len(paths) != 1 else ''}: go to a folder and press Ctrl+V")

    def paste_into(self, pane):
        if not self.clipboard or not is_folder_loc(pane.location) or pane.mode == "search":
            return
        paths, move = self.clipboard
        self.transfer(paths, move, pane.location)
        if move:
            self.clipboard = None

    def transfer(self, paths, move, dest):
        """Copies or moves items into dest, asking what to do when a name already exists."""
        self.spinner.start()
        state = {"file": None, "dir": None, "done": 0, "skipped": 0, "replaced": 0, "errors": [],
                 "cancelled": False, "count": len(paths)}

        def ask(src, dst):
            req = {"src": src, "dst": dst, "event": threading.Event(), "answer": ("cancel", None, False),
                   "more": state["count"] > 1 or os.path.isdir(src)}
            GLib.idle_add(self._ask_conflict, req)
            req["event"].wait()
            return req["answer"]

        def put(src, dst):
            if move:
                shutil.move(src, dst)
                TAG_STORE.moved(src, dst)
            elif os.path.isdir(src) and not os.path.islink(src):
                shutil.copytree(src, dst, symlinks=True)
            else:
                shutil.copy2(src, dst, follow_symlinks=False)
            state["done"] += 1

        def place(src, dest_dir):
            name = os.path.basename(src.rstrip("/\\"))
            dst = os.path.join(dest_dir, name)
            if os.path.isdir(src) and (os.path.realpath(dest_dir) + os.sep).startswith(os.path.realpath(src) + os.sep):
                state["errors"].append(f"{name}: can't put a folder inside itself")
                return
            if os.path.realpath(os.path.dirname(src)) == os.path.realpath(dest_dir):
                if move:
                    return                                    # already here: nothing to do
                put(src, str(unique_target(Path(dst))))       # copy & paste in the same folder = duplicate
                return
            if os.path.lexists(dst):
                kind = "dir" if os.path.isdir(src) and os.path.isdir(dst) else "file"
                if state[kind]:
                    action, new_name = state[kind], None
                else:
                    action, new_name, apply_all = ask(src, dst)
                    if action == "cancel":
                        raise InterruptedError
                    if apply_all:
                        state[kind] = action
                if action == "skip":
                    state["skipped"] += 1
                    return
                if action == "merge":
                    for child in sorted(os.listdir(src)):
                        place(os.path.join(src, child), dst)
                    if move:
                        try:
                            os.rmdir(src)                     # only if everything inside was moved
                        except OSError:
                            pass
                    return
                if action == "rename":
                    dst = os.path.join(dest_dir, new_name) if new_name else dst
                    if os.path.lexists(dst):
                        dst = str(unique_target(Path(dst)))
                elif action == "replace":
                    self._remove_for_replace(dst)
                    state["replaced"] += 1
            put(src, dst)

        def work():
            for src in paths:
                try:
                    place(src, dest)
                except InterruptedError:
                    state["cancelled"] = True
                    break
                except (OSError, shutil.Error) as ex:
                    state["errors"].append(f"{os.path.basename(src)}: {getattr(ex, 'strerror', None) or ex}")
            GLib.idle_add(self._transfer_done, state, move, dest)
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def _remove_for_replace(path):
        """The item being replaced goes to the Trash, so a wrong click can be undone."""
        try:
            Gio.File.new_for_path(path).trash(None)
        except GLib.Error:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.remove(path)

    def _ask_conflict(self, req):
        src, dst = req["src"], req["dst"]
        both_dirs = os.path.isdir(src) and os.path.isdir(dst)
        what = "folder" if os.path.isdir(dst) else "file"
        name = os.path.basename(dst)
        dlg = Gtk.Dialog(title="Confirm to replace files" if not both_dirs else "Merge folders",
                         transient_for=self, modal=True)
        dlg.set_default_size(720, -1)
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(16)
        head = Gtk.Label(xalign=0, wrap=True)
        head.set_markup(f"<big><b>This folder already contains a {what} “{esc(name)}”.</b></big>")
        box.add(head)
        try:
            s_src, s_dst = os.stat(src), os.stat(dst)
        except OSError:
            s_src = s_dst = None

        def card(path, st, other):
            row = Gtk.Box(spacing=12, margin_start=24)
            pb = None if os.path.isdir(path) else thumbnail_for(path, 64, render=False)
            img = Gtk.Image.new_from_pixbuf(pb) if pb else Gtk.Image.new_from_gicon(
                icon_for(os.path.basename(path), os.path.isdir(path)), Gtk.IconSize.DIALOG)
            row.add(img)
            info = Gtk.Label(xalign=0, selectable=True)
            if st is None:
                info.set_text("(can't read details)")
            else:
                if os.path.isdir(path):
                    try:
                        n = len(os.listdir(path))
                    except OSError:
                        n = 0
                    size = f"Contains: {n} item{'s' if n != 1 else ''}"
                else:
                    size = f"Size: {human_size(st.st_size)} ({st.st_size:,} bytes)"
                hints = []
                if other is not None and not os.path.isdir(path):
                    if st.st_mtime > other.st_mtime + 1:
                        hints.append("newer")
                    if st.st_size > other.st_size:
                        hints.append("larger")
                hint = f"   <i>({', '.join(hints)})</i>" if hints else ""
                info.set_markup(f"{esc(size)}\nModified: {esc(fmt_full(st.st_mtime))}{hint}\n"
                                f"<small>{esc(short(os.path.dirname(path)))}</small>")
            row.add(info)
            return row

        q1 = Gtk.Label(xalign=0)
        q1.set_text("Do you want to merge these folders? Files inside that clash will be asked about one by one."
                    if both_dirs else f"Do you want to replace the existing {what}")
        box.add(q1)
        box.add(card(dst, s_dst, s_src))
        q2 = Gtk.Label(xalign=0)
        q2.set_text("with the folder you're pasting:" if both_dirs else "with the following file?" if
                    not os.path.isdir(src) else "with the following folder?")
        box.add(q2)
        box.add(card(src, s_src, s_dst))
        rename_row = Gtk.Box(spacing=8, margin_top=4)
        rename_row.add(Gtk.Label(label="New name for Rename:"))
        entry = Gtk.Entry(text=unique_target(Path(dst)).name, hexpand=True, activates_default=True)
        rename_row.pack_start(entry, True, True, 0)
        box.add(rename_row)
        note = Gtk.Label(xalign=0, wrap=True)
        note.set_markup("<small>Replaced items go to the Trash, so you can get them back.</small>")
        note.get_style_context().add_class("dim-label")
        box.add(note)

        CANCEL, SKIP_ALL, SKIP, MAIN_ALL, MAIN, RENAME_ALL, RENAME = range(1, 8)
        main = "Merge" if both_dirs else "Replace"
        buttons = [("Cancel", CANCEL), ("Skip All", SKIP_ALL), ("Skip", SKIP), (f"{main} All", MAIN_ALL),
                   (main, MAIN), ("Rename All", RENAME_ALL), ("Rename", RENAME)]
        for label, rid in buttons:
            if not req["more"] and label.endswith(" All"):
                continue
            dlg.add_button(label, rid)
        dlg.get_widget_for_response(RENAME).get_style_context().add_class("suggested-action")
        dlg.set_default_response(RENAME)
        dlg.show_all()
        resp = dlg.run()
        new_name = entry.get_text().strip()
        dlg.destroy()
        bad = set('/\\:*?"<>|') if IS_WIN else {"/"}
        if new_name and any(c in bad for c in new_name):
            new_name = None
        verb = "merge" if both_dirs else "replace"
        req["answer"] = {
            SKIP_ALL: ("skip", None, True), SKIP: ("skip", None, False),
            MAIN_ALL: (verb, None, True), MAIN: (verb, None, False),
            RENAME_ALL: ("rename", None, True), RENAME: ("rename", new_name or None, False),
        }.get(resp, ("cancel", None, False))
        req["event"].set()
        return False

    def _transfer_done(self, state, move, dest):
        self.update_spinner()
        self.refresh_all()
        verb = "Moved" if move else "Copied"
        done = state["done"]
        msg = f"{verb} {done} item{'s' if done != 1 else ''} to {short(dest)}"
        extras = []
        if state["replaced"]:
            extras.append(f"{state['replaced']} replaced, old versions in Trash")
        if state["skipped"]:
            extras.append(f"{state['skipped']} skipped")
        if state["cancelled"]:
            extras.append("stopped")
        self.active.flash(msg + (f" ({', '.join(extras)})" if extras else ""))
        if state["errors"]:
            self.error("Some items couldn't be " + ("moved" if move else "copied") + ":\n\n"
                       + "\n".join(state["errors"][:15]))
        return False

    def handle_drop(self, paths, dest, internal, ctrl, shift):
        """Dropped files: inside Arckad-D they move (hold Ctrl to copy); from other apps they copy
        (hold Shift to move). Name clashes ask, like paste does."""
        if not paths or not dest or not os.path.isdir(dest):
            if self.active:
                self.active.flash("Drop files on a folder, or into an open folder")
            return False
        move = (internal and not ctrl) or (not internal and shift)
        if move and all(os.path.dirname(p.rstrip(os.sep)) == dest for p in paths):
            return False                                # dropped where they already are
        if any(os.path.isdir(p) and (dest + os.sep).startswith(p.rstrip(os.sep) + os.sep) for p in paths):
            self.error("A folder can't be moved or copied into itself.")
            return False
        self.transfer(paths, move, dest)
        return True

    def refresh_all(self):
        for pane in self.all_panes():
            if pane.mode in ("folder", "tag", "notes"):
                pane.refresh()

    def rename(self, pane, path):
        p = Path(path)
        new = self.ask_text("Rename", "New name:", p.name, select_stem=True)
        if not new or new == p.name:
            return
        bad = set('/\\:*?"<>|') if IS_WIN else {"/"}
        if any(c in bad for c in new):
            self.error("A name can't contain any of these characters:  " + " ".join(sorted(bad)))
            return
        target = p.with_name(new)
        if target.exists():
            self.error(f"“{new}” already exists here.")
            return
        try:
            p.rename(target)
        except OSError as ex:
            self.error(f"Couldn't rename: {ex.strerror}")
            return
        TAG_STORE.moved(str(p), str(target))
        pane.pending_select = [str(target)]
        pane.refresh()

    def trash(self, pane, paths):
        done = 0
        for p in paths:
            try:
                Gio.File.new_for_path(p).trash(None)
                done += 1
            except GLib.Error as ex:
                self.error(f"Couldn't move {os.path.basename(p)} to Trash: {ex.message}")
                break
        pane.refresh()
        pane.flash(f"Moved {done} item{'s' if done != 1 else ''} to Trash (restore from Trash in the Files app)")

    def new_file(self, pane):
        if pane.mode != "folder":
            self.info("Open a normal folder first, then create the new file there.")
            return
        name = self.ask_text("New empty file", "File name (include the type, e.g. notes.txt):", "New file.txt",
                             select_stem=True)
        if not name:
            return
        bad = set('/\\:*?"<>|') if IS_WIN else {"/"}
        if any(c in bad for c in name):
            self.error("A name can't contain any of these characters:  " + " ".join(sorted(bad)))
            return
        target = unique_target(Path(pane.location) / name)
        try:
            with open(target, "x"):
                pass
        except OSError as ex:
            self.error(f"Couldn't create the file: {ex.strerror}")
            return
        pane.pending_select = [str(target)]
        pane.refresh()

    def duplicate(self, pane, paths):
        def work():
            made, errors = [], []
            for src in paths:
                p = Path(src)
                stem, suffix = (p.name, "") if p.is_dir() else (p.stem, p.suffix)
                target = unique_target(p.with_name(f"{stem} (copy){suffix}"))
                try:
                    if p.is_dir():
                        shutil.copytree(src, target, symlinks=True)
                    else:
                        shutil.copy2(src, target)
                    made.append(str(target))
                except (OSError, shutil.Error) as ex:
                    errors.append(f"{p.name}: {getattr(ex, 'strerror', None) or ex}")
            GLib.idle_add(done, made, errors)

        def done(made, errors):
            self.update_spinner()
            pane.pending_select = made
            pane.refresh()
            pane.flash(f"Duplicated {len(made)} item{'s' if len(made) != 1 else ''}")
            if errors:
                self.error("Some items couldn't be duplicated:\n\n" + "\n".join(errors[:10]))
            return False
        self.spinner.start()
        threading.Thread(target=work, daemon=True).start()

    def delete_forever(self, pane, paths):
        n = len(paths)
        names = ", ".join(os.path.basename(p) for p in paths[:3]) + ("…" if n > 3 else "")
        if not self.confirm(f"Delete {n} item{'s' if n != 1 else ''} permanently?\n\n{names}\n\n"
                            "They will NOT go to the Trash and can't be restored."):
            return
        errors = []
        for p in paths:
            try:
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
            except OSError as ex:
                errors.append(f"{os.path.basename(p)}: {ex.strerror}")
        pane.refresh()
        pane.flash(f"Deleted {n - len(errors)} item{'s' if n - len(errors) != 1 else ''} permanently")
        if errors:
            self.error("Some items couldn't be deleted:\n\n" + "\n".join(errors[:10]))

    @staticmethod
    def terminal_choices():
        """[(label, kind)] of terminals on this computer."""
        if IS_WIN:
            out = []
            if shutil.which("wt.exe") or shutil.which("wt"):
                out.append(("Windows Terminal", "wt"))
            out.append(("Command Prompt (cmd)", "cmd"))
            out.append(("PowerShell", "powershell"))
            return out
        return [("Terminal", "linux")]

    def open_terminal(self, folder, kind=None):
        """A terminal window in this folder (Windows: Windows Terminal, Command Prompt or PowerShell)."""
        folder = folder if folder and os.path.isdir(folder) else str(HOME)
        try:
            if IS_WIN:
                kind = kind or self.terminal_choices()[0][1]
                new_console = 0x00000010
                if kind == "wt":
                    subprocess.Popen([shutil.which("wt.exe") or shutil.which("wt"), "-d", folder])
                elif kind == "powershell":
                    ps = shutil.which("pwsh.exe") or shutil.which("powershell.exe") or "powershell.exe"
                    subprocess.Popen([ps, "-NoExit", "-NoLogo"], cwd=folder, creationflags=new_console)
                else:
                    comspec = os.environ.get("ComSpec", "cmd.exe")
                    subprocess.Popen([comspec, "/K"], cwd=folder, creationflags=new_console)
                return
            for cmd in (["x-terminal-emulator"], ["gnome-terminal", f"--working-directory={folder}"],
                        ["kgx", f"--working-directory={folder}"], ["konsole", "--workdir", folder],
                        ["xfce4-terminal", f"--working-directory={folder}"], ["mate-terminal", f"--working-directory={folder}"],
                        ["tilix", "-w", folder], ["xterm"]):
                if shutil.which(cmd[0]):
                    subprocess.Popen(cmd, cwd=folder, start_new_session=True)
                    return
            self.error("No terminal app was found on this computer.")
        except OSError as ex:
            self.error(f"Couldn't open a terminal: {ex.strerror or ex}")

    def terminal_menu_items(self, folder):
        """Menu entries: one on Linux, Windows Terminal / Command Prompt / PowerShell on Windows."""
        items = []
        for label, kind in self.terminal_choices():
            text = f"Open {label} here" + ("  (F4)" if kind == self.terminal_choices()[0][1] else "")
            item = Gtk.MenuItem(label=text)
            item.connect("activate", lambda _i, k=kind: self.open_terminal(folder, k))
            items.append(item)
        return items

    def properties(self, paths):
        paths = [p for p in paths if p and os.path.exists(p)]
        if not paths:
            return
        dlg = Gtk.Dialog(title="Properties", transient_for=self, modal=False)
        dlg.add_button("Close", Gtk.ResponseType.CLOSE)
        dlg.connect("response", lambda d, r: d.destroy())
        dlg.set_default_size(460, -1)
        grid = Gtk.Grid(column_spacing=14, row_spacing=7, border_width=16)
        dlg.get_content_area().add(grid)
        rows = []
        first = paths[0]
        if len(paths) == 1:
            st = os.stat(first)
            is_dir = os.path.isdir(first)
            rows += [("Name", os.path.basename(first.rstrip(os.sep)) or first),
                     ("Type", type_description(first, is_dir)),
                     ("Location", os.path.dirname(first.rstrip(os.sep)) or first)]
            rows.append(("Size", "counting…" if is_dir else f"{human_size(st.st_size)} ({st.st_size:,} bytes)"))
            if is_dir:
                rows.append(("Contains", "counting…"))
            rows.append(("Modified", fmt_full(st.st_mtime)))
            rows.append(("Accessed", fmt_full(st.st_atime)))
            try:
                info = Gio.File.new_for_path(first).query_info("time::created", Gio.FileQueryInfoFlags.NONE, None)
                if info.has_attribute("time::created"):
                    rows.append(("Created", fmt_full(info.get_attribute_uint64("time::created"))))
            except GLib.Error:
                pass
            if not IS_WIN:
                try:
                    import grp
                    import pwd
                    rows.append(("Permissions", statmod.filemode(st.st_mode)))
                    rows.append(("Owner", f"{pwd.getpwuid(st.st_uid).pw_name} (group {grp.getgrgid(st.st_gid).gr_name})"))
                except (ImportError, KeyError):
                    rows.append(("Permissions", statmod.filemode(st.st_mode)))
            if is_dir:
                label, free = self.drive_info(first)
                if free:
                    rows.append(("Drive space", free))
        else:
            rows += [("Selected", f"{len(paths)} items"), ("Location", os.path.dirname(first)),
                     ("Size", "counting…"), ("Contains", "counting…")]
        values = {}
        for i, (k, v) in enumerate(rows):
            kl = Gtk.Label(xalign=1, yalign=0)
            kl.set_markup(f"<b>{esc(k)}</b>")
            vl = Gtk.Label(label=v, xalign=0, wrap=True, selectable=True, width_chars=34, max_width_chars=48)
            vl.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            grid.attach(kl, 0, i, 1, 1)
            grid.attach(vl, 1, i, 1, 1)
            values[k] = vl
        dlg.show_all()
        if "counting…" in [v for _, v in rows]:
            def work():
                files = folders = size = 0
                for p in paths:
                    if os.path.isdir(p) and not os.path.islink(p):
                        for _q, s, d in walk_entries(p, hidden=True):
                            if d:
                                folders += 1
                            else:
                                files += 1
                                size += s.st_size
                    else:
                        files += 1
                        size += os.path.getsize(p)
                GLib.idle_add(show, files, folders, size)

            def show(files, folders, size):
                if "Size" in values:
                    values["Size"].set_text(f"{human_size(size)} ({size:,} bytes)")
                if "Contains" in values:
                    values["Contains"].set_text(f"{files:,} file{'s' if files != 1 else ''}, "
                                                f"{folders:,} folder{'s' if folders != 1 else ''}")
                return False
            threading.Thread(target=work, daemon=True).start()

    def new_folder(self, pane):
        if pane.mode != "folder":
            self.info("Open a normal folder first, then create the new folder there.")
            return
        name = self.ask_text("New folder", "Folder name:", "New Folder")
        if not name:
            return
        target = unique_target(Path(pane.location) / name)
        try:
            target.mkdir()
        except OSError as ex:
            self.error(f"Couldn't create folder: {ex.strerror}")
            return
        pane.pending_select = [str(target)]
        pane.refresh()

    def on_icons_toggled(self, item):
        want = item.get_active()
        if want and not colour_icons_supported():
            self.error("This system can't draw the colourful icons (its SVG image support is missing).")
            item.set_active(False)
            return
        self.cfg["file_icons"] = "colour" if want else "system"
        write_json(CONFIG_FILE, self.cfg)
        ICON_STYLE["colour"] = want
        _icon_cache.clear()
        for pane in self.all_panes():
            pane.apply_icon_style()

    def on_hidden_toggled(self, item):
        self.cfg["show_hidden"] = item.get_active()
        write_json(CONFIG_FILE, self.cfg)
        for pane in self.all_panes():
            pane.refresh()

    def on_install(self):
        path = install_launcher()
        self.info(f"{APP_NAME} is now in your app menu.\nSearch for “{APP_NAME}” in Activities.\n\n({short(path)})")

    # ---------- archives
    def extract_to(self, pane, paths):
        dlg = Gtk.FileChooserNative.new("Extract to…", self, Gtk.FileChooserAction.SELECT_FOLDER, "Extract here", "Cancel")
        start = pane.location if is_folder_loc(pane.location) else os.path.dirname(paths[0])
        dlg.set_current_folder(start)
        if dlg.run() == Gtk.ResponseType.ACCEPT:
            self.extract(pane, paths, dlg.get_filename())
        dlg.destroy()

    def extract(self, pane, paths, dest_dir):
        """Extracts the archives one after another; dest_dir None = next to each archive."""
        queue = [(p, dest_dir or os.path.dirname(p)) for p in paths]
        results = []
        self._extract_next(pane, queue, results, None)

    def _extract_next(self, pane, queue, results, password):
        if not queue:
            self.update_spinner()
            if results:
                if len(results) == 1:
                    pane.flash(f"Extracted to {short(results[0])}")
                else:
                    pane.flash(f"Extracted {len(results)} archives")
                if pane.mode == "folder" and any(str(r.parent) == pane.location for r in results):
                    pane.pending_select = [str(r) for r in results]
                    pane.refresh()
            return
        archive, dest = queue[0]
        name = os.path.basename(archive)
        self.spinner.start()
        pane.flash(f"Extracting {name}…")
        last = [0.0]

        def progress(done, total):
            if time.time() - last[0] > 0.25:
                last[0] = time.time()
                GLib.idle_add(pane.flash, f"Extracting {name}… {int(done * 100 / total)}%")

        def work():
            try:
                outcome = ("ok", extract_archive(archive, dest, password, progress))
            except NeedPassword as ex:
                outcome = ("password", ex.wrong)
            except ExtractError as ex:
                outcome = ("error", str(ex))
            except OSError as ex:
                outcome = ("error", f"{ex.strerror or ex} ({getattr(ex, 'filename', '') or name})")
            GLib.idle_add(finish, outcome)

        def finish(outcome):
            kind, value = outcome
            if kind == "ok":
                results.append(Path(value))
                self._extract_next(pane, queue[1:], results, None)
            elif kind == "password":
                pw = self.ask_password(name, wrong=value)
                if pw is None:
                    pane.flash(f"Skipped {name}")
                    self._extract_next(pane, queue[1:], results, None)
                else:
                    self._extract_next(pane, queue, results, pw)
            else:
                self.update_spinner()
                self.error(f"Couldn't extract {name}.\n\n{value}")
                self._extract_next(pane, queue[1:], results, None)
            return False
        threading.Thread(target=work, daemon=True).start()

    def ask_password(self, name, wrong=False):
        dlg = Gtk.Dialog(title="Password needed", transient_for=self, modal=True)
        dlg.add_buttons("Skip", Gtk.ResponseType.CANCEL, "Extract", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        msg = Gtk.Label(xalign=0, wrap=True)
        msg.set_markup(("<b>That password didn't work.</b> " if wrong else "")
                       + f"“{esc(name)}” is protected. Enter its password:")
        box.add(msg)
        entry = Gtk.Entry(visibility=False, activates_default=True, width_chars=32)
        box.add(entry)
        dlg.show_all()
        resp = dlg.run()
        pw = entry.get_text()
        dlg.destroy()
        return pw if resp == Gtk.ResponseType.OK and pw else None

    def compress(self, pane, paths):
        folder = pane.location if pane.mode == "folder" else os.path.dirname(paths[0])
        single_file = len(paths) == 1 and os.path.isfile(paths[0])
        base = os.path.basename(paths[0].rstrip("/\\")) if len(paths) == 1 else "Archive"
        if single_file:
            base = os.path.splitext(base)[0] or base
        has_7z = can_make_7z()
        total = sum(e[2] for e in _gather(paths))

        dlg = Gtk.Dialog(title="Compress", transient_for=self, modal=True)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Create", Gtk.ResponseType.OK)
        ok = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        dlg.set_default_response(Gtk.ResponseType.OK)
        grid = Gtk.Grid(column_spacing=12, row_spacing=10, border_width=16)
        dlg.get_content_area().add(grid)
        n = len(paths)
        summary = Gtk.Label(xalign=0, wrap=True)
        summary.set_markup(f"<b>{n} item{'s' if n != 1 else ''}</b> · {human_size(total)} before compressing")
        grid.attach(summary, 0, 0, 2, 1)

        grid.attach(Gtk.Label(label="Name:", xalign=1), 0, 1, 1, 1)
        name_entry = Gtk.Entry(hexpand=True, activates_default=True, width_chars=36)
        grid.attach(name_entry, 1, 1, 1, 1)

        grid.attach(Gtk.Label(label="Format:", xalign=1), 0, 2, 1, 1)
        store = Gtk.ListStore(str, str, bool)          # key, label, usable
        for key, ext, label, needs_7z, single in COMPRESS_FORMATS:
            usable = (has_7z or not needs_7z) and (single_file or not single)
            note = "" if usable else ("  (install 7-Zip)" if needs_7z and not has_7z else "  (one file only)")
            store.append([key, label + note, usable])
        fmt_combo = Gtk.ComboBox(model=store)
        cell = Gtk.CellRendererText()
        fmt_combo.pack_start(cell, True)
        fmt_combo.add_attribute(cell, "text", 1)
        fmt_combo.add_attribute(cell, "sensitive", 2)
        grid.attach(fmt_combo, 1, 2, 1, 1)

        grid.attach(Gtk.Label(label="Compression:", xalign=1), 0, 3, 1, 1)
        level_combo = Gtk.ComboBoxText()
        for label, _ in COMPRESS_LEVELS:
            level_combo.append_text(label)
        level_combo.set_active(self.cfg.get("compress_level", 1))
        grid.attach(level_combo, 1, 3, 1, 1)

        grid.attach(Gtk.Label(label="Password:", xalign=1), 0, 4, 1, 1)
        pw_box = Gtk.Box(spacing=6)
        pw_entry = Gtk.Entry(visibility=False, hexpand=True, placeholder_text="optional", activates_default=True)
        pw_box.pack_start(pw_entry, True, True, 0)
        show = Gtk.CheckButton(label="Show")
        show.connect("toggled", lambda b: pw_entry.set_visibility(b.get_active()))
        pw_box.add(show)
        grid.attach(pw_box, 1, 4, 1, 1)
        hint = Gtk.Label(xalign=0, wrap=True, max_width_chars=50)
        hint.get_style_context().add_class("dim-label")
        grid.attach(hint, 1, 5, 1, 1)

        def ext_of_fmt(key):
            return next(e for k, e, *_ in COMPRESS_FORMATS if k == key)

        def current_key():
            it = fmt_combo.get_active_iter()
            return store[it][0] if it else "zip"

        def strip_ext(text):
            low = text.lower()
            for _k, e, *_ in sorted(COMPRESS_FORMATS, key=lambda f: -len(f[1])):
                if low.endswith(e):
                    return text[:-len(e)]
            return text

        def on_format(*_):
            it = fmt_combo.get_active_iter()
            if it is not None and not store[it][2]:            # not usable: fall back to ZIP
                fmt_combo.set_active(0)
                return
            key = current_key()
            name_entry.set_text(strip_ext(name_entry.get_text() or base) + ext_of_fmt(key))
            can_pw = key in PASSWORD_FORMATS and archive_tool() is not None
            pw_box.set_sensitive(can_pw)
            if not can_pw:
                pw_entry.set_text("")
            if key in PASSWORD_FORMATS and archive_tool() is None:
                hint.set_markup("<small>Passwords need 7-Zip installed"
                                + (" (7-zip.org)." if IS_WIN else ":  sudo apt install 7zip") + "</small>")
            elif key in PASSWORD_FORMATS:
                hint.set_markup("<small>With a password, the archive is encrypted with AES-256.</small>")
            else:
                hint.set_markup("<small>Passwords are available for ZIP and 7Z.</small>")
        fmt_combo.connect("changed", on_format)
        keys = [f[0] for f in COMPRESS_FORMATS]
        last = self.cfg.get("compress_format", "zip")
        idx = keys.index(last) if last in keys else 0
        fmt_combo.set_active(idx if store[idx][2] else 0)
        name_entry.set_text(base + ext_of_fmt(current_key()))
        on_format()
        dlg.show_all()
        name_entry.grab_focus()
        name_entry.select_region(0, len(strip_ext(name_entry.get_text())))
        resp = dlg.run()
        key, name = current_key(), name_entry.get_text().strip()
        level = COMPRESS_LEVELS[level_combo.get_active()][1]
        password = pw_entry.get_text() or None
        self.cfg["compress_format"], self.cfg["compress_level"] = key, level_combo.get_active()
        dlg.destroy()
        if resp != Gtk.ResponseType.OK or not name:
            return
        if not name.lower().endswith(ext_of_fmt(key)):
            name = strip_ext(name) + ext_of_fmt(key)
        target = unique_target(Path(folder) / name)
        self.spinner.start()
        pane.flash(f"Compressing to {target.name}…")
        last_t = [0.0]

        def progress(done, total_):
            if time.time() - last_t[0] > 0.25:
                last_t[0] = time.time()
                GLib.idle_add(pane.flash, f"Compressing… {int(done * 100 / total_)}%")

        def work():
            try:
                result, err = compress_archive(paths, target, key, level, password, progress), None
            except ExtractError as ex:
                result, err = None, str(ex)
            except OSError as ex:
                result, err = None, ex.strerror or str(ex)
            GLib.idle_add(done, result, err)

        def done(result, err):
            self.update_spinner()
            if err:
                self.error(f"Couldn't create {target.name}.\n\n{err}")
            else:
                size = result.stat().st_size
                saved = f", {int((1 - size / total) * 100)}% smaller" if total and size < total else ""
                pane.flash(f"Created {result.name} ({human_size(size)}{saved})")
                if pane.mode == "folder" and str(result.parent) == pane.location:
                    pane.pending_select = [str(result)]
                    pane.refresh()
            return False
        threading.Thread(target=work, daemon=True).start()

    # ---------- compare & duplicates
    def compare_selected(self):
        sel = self.active.selected_paths()
        other = self.other_pane()
        if len(sel) == 2:
            self.compare(*sel)
        elif len(sel) == 1 and other and len(other.selected_paths()) == 1:
            self.compare(sel[0], other.selected_paths()[0])
        else:
            self.info("Select two files (or two folders) to compare.\n\n"
                      "Tip: Ctrl+click to select two items, or turn on Dual pane and "
                      "select one item on each side.")

    def compare(self, a, b):
        if os.path.isdir(a) != os.path.isdir(b):
            self.info("Pick two files or two folders, not one of each.")
            return
        CompareWindow(self, a, b)

    def duplicates(self, folder):
        DuplicatesWindow(self, folder)

    # ---------- organize & undo
    def organize(self, pane):
        if pane is None or pane.mode != "folder":
            self.info("Open a normal folder first (for example Downloads), then click Organize.")
            return
        folder = Path(pane.location)
        dlg = Gtk.Dialog(title="Organize folder", transient_for=self, modal=True)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Move files", Gtk.ResponseType.OK)
        ok = dlg.get_widget_for_response(Gtk.ResponseType.OK)
        ok.get_style_context().add_class("suggested-action")
        w, h = self.get_size()
        dlg.set_default_size(max(640, int(w * 0.75)), max(420, int(h * 0.8)))
        dlg.set_resizable(True)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        intro = Gtk.Label(xalign=0, wrap=True)
        intro.set_markup(f"Sort the loose files in <b>{esc(folder.name or str(folder))}</b> into subfolders. "
                         "Folders that are already there stay untouched.")
        box.add(intro)
        by_type = Gtk.RadioButton.new_with_label(None, "By type (Images, Documents, Code, …)")
        by_date = Gtk.RadioButton.new_with_label_from_widget(by_type, "By month (2026-11, 2026-10, …)")
        box.add(by_type)
        box.add(by_date)
        store = Gtk.ListStore(str, str)
        view = Gtk.TreeView(model=store)
        file_col = Gtk.TreeViewColumn("File", Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.MIDDLE), text=0)
        file_col.set_expand(True)
        file_col.set_resizable(True)
        file_col.set_min_width(200)
        view.append_column(file_col)
        dest_col = Gtk.TreeViewColumn("Goes into", Gtk.CellRendererText(), text=1)
        dest_col.set_resizable(True)
        dest_col.set_min_width(140)
        view.append_column(dest_col)
        view.set_tooltip_column(0)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        summary = Gtk.Label(xalign=0, wrap=True)
        box.add(summary)
        holder = [[]]

        def refresh_plan(*_):
            store.clear()
            plan = plan_organize(folder, "date" if by_date.get_active() else "type")
            for src, dst in plan:
                store.append([src.name, dst.parent.name + "/"])
            holder[0] = plan
            summary.set_text(f"{len(plan)} files will be moved. Nothing is deleted, and you can Undo."
                             if plan else "There are no loose files to organize here.")
            ok.set_sensitive(bool(plan))
        by_type.connect("toggled", refresh_plan)
        refresh_plan()
        dlg.show_all()
        resp = dlg.run()
        dlg.destroy()
        if resp == Gtk.ResponseType.OK and holder[0]:
            moved = apply_plan(holder[0])
            self.undo_btn.set_sensitive(True)
            pane.refresh()
            pane.flash(f"Organized {len(moved)} files. Click Undo (↶) to put them back")

    def on_undo(self, *_):
        restored = undo_last()
        self.undo_btn.set_sensitive(bool(read_json(UNDO_FILE, [])))
        self.refresh_all()
        self.active.flash(f"Undo: restored {len(restored)} files")

    # ---------- Quick Share
    def open_share(self, paths=None, page=None):
        if self.share_win is None:
            self.share_win = ShareWindow(self)
            self.share_win.show_all()
            self.share_win.progress.hide()
            self.share_win.update_state()
        if paths:
            self.share_win.add_paths(paths)
        if page == "receive":
            self.share_win.tabs.set_visible_child_name("receive")
        elif page:
            self.share_win.tabs.set_visible_child_name("send")
            self.share_win.pages.set_visible_child_name(page)
        self.share_win.present()

    # ---------- Nearby (Arckad-D to Arckad-D)
    def start_visible(self, minutes):
        try:
            self.nearby.set_visible(minutes)
        except OSError as ex:
            self.error(f"Couldn't turn on receiving: {ex}")
            return False
        if self.share_win:
            self.share_win.log_line(f"Visible to nearby devices as “{self.nearby.name()}”")
            if IS_WIN:
                self.share_win.log_line("If Windows asks about the firewall, allow Arckad-D on Private networks.")
            elif self.firewall_on():
                self.share_win.log_line("⚠ Ubuntu's firewall is on. If others can't see you, run:  "
                                        "sudo ufw allow 47820/udp && sudo ufw allow 47821:47823/tcp")
        GLib.timeout_add_seconds(1, self.visible_tick)
        self.update_share_button()
        return True

    def stop_visible(self, expired=False):
        closed = self.nearby.hide()
        if self.share_win:
            self.share_win.log_line("Receiving turned off (time is up)" if expired else "Receiving turned off"
                                    + ("" if closed else ", after the current transfer finishes"))
            self.share_win.update_state()
        self.update_share_button()

    def visible_tick(self):
        nb = self.nearby
        if nb.server is None:
            self.update_share_button()
            return False
        if not nb.visible():
            if nb.visible_until:               # timer ran out
                self.stop_visible(expired=True)
            elif not nb.transfers:
                nb.hide()
            if nb.server is None:
                self.update_share_button()
                return False
        self.update_share_button()
        if self.share_win and self.share_win.get_visible():
            self.share_win.update_state()
        return True

    # ---------- chat
    def toggle_chat(self):
        showing = self.preview_rev.get_reveal_child() and self.right_stack.get_visible_child_name() == "chat"
        if showing:
            self.right_stack.set_visible_child_name("preview")
            self.preview_btn.set_active(False)
        else:
            self.right_stack.set_visible_child_name("chat")
            self.preview_btn.set_active(True)
            self.chat_panel.refresh()
            self.chat_panel.entry.grab_focus()

    def open_chat_window(self):
        if self.chat_windows:
            self.chat_windows[0].present()
            return
        w = ChatWindow(self)
        self.chat_windows.append(w)
        w.show_all()
        if self.right_stack.get_visible_child_name() == "chat":
            self.right_stack.set_visible_child_name("preview")

    def chat_panels(self):
        return [self.chat_panel] + [w.panel for w in self.chat_windows]

    def on_chat_changed(self, gid):
        for p in self.chat_panels():
            p.refresh(gid)
        self.update_chat_button()
        return False

    def on_chat_presence(self):
        for p in self.chat_panels():
            p.update_info()
        return False

    def on_chat_message(self, gid, msg):
        self.on_chat_changed(gid)
        visible = any(p.gid == gid and p.get_mapped() for p in self.chat_panels())
        if visible and (self.is_active() or any(w.is_active() for w in self.chat_windows)):
            self.chat.unread[gid] = 0
            self.update_chat_button()
            return False
        g = self.chat.groups.get(gid, {})
        body = f"📎 {msg['file']['name']}" if msg["kind"] == "file" else (msg.get("text") or "")
        try:
            n = Gio.Notification.new(f"{msg.get('name', '?')} · {g.get('name', 'Chat')}")
            n.set_body(body[:200])
            self.get_application().send_notification(f"chat-{gid}", n)
        except Exception:
            pass
        return False

    def update_chat_button(self):
        total = sum(n for g, n in self.chat.unread.items() if g in self.chat.groups)
        self.chat_btn.set_label(f"💬 Chat ({total})" if total else "💬 Chat")
        return False

    def flash_all(self, text):
        if self.active:
            self.active.flash(text)

    def send_to_chat(self, paths):
        if not self.chat.groups:
            self.toggle_chat() if self.right_stack.get_visible_child_name() != "chat" else None
            self.info("Create or join a chat group first (Chat → ＋).")
            return
        panel = self.chat_windows[0].panel if self.chat_windows else self.chat_panel
        if panel is self.chat_panel and not (self.preview_rev.get_reveal_child()
                                             and self.right_stack.get_visible_child_name() == "chat"):
            self.toggle_chat()
        n = panel.send_paths(paths)
        if n:
            self.flash_all(f"Sent {n} file{'s' if n != 1 else ''} to “{self.chat.groups[panel.gid]['name']}”")

    def ask_chat_join(self, ev):
        d = Gtk.MessageDialog(transient_for=self, modal=False, message_type=Gtk.MessageType.QUESTION,
                              text=f"Let {ev['name']} join “{ev['group']}”?")
        d.format_secondary_text(f"{ev['name']} ({ev['os']}) typed the correct join code. Members can read and post "
                                "messages and files in this group. You can remove them later.")
        d.add_buttons("Decline", Gtk.ResponseType.REJECT, "Let them join", Gtk.ResponseType.ACCEPT)
        d.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_style_context().add_class("suggested-action")
        d.set_keep_above(True)

        def respond(dlg, resp):
            if not ev["event"].is_set():
                ev["accepted"] = resp == Gtk.ResponseType.ACCEPT
                ev["event"].set()
            dlg.destroy()
        d.connect("response", respond)
        GLib.timeout_add_seconds(110, lambda: (d.response(Gtk.ResponseType.REJECT) if not ev["event"].is_set() else None)
                                 and False)
        d.show_all()
        d.present()
        return False

    def on_pairs_changed(self):
        if self.share_win:
            self.share_win.refresh_pairs()
        return False

    def on_pair_event(self, text):
        if self.share_win:
            self.share_win.log_line(text)
            self.share_win.refresh_pairs()
        if self.active:
            self.active.flash(text)
        return False

    def ask_pair(self, ev):
        d = Gtk.MessageDialog(transient_for=self, modal=False, message_type=Gtk.MessageType.QUESTION,
                              text=f"Pair with {ev['name']}?")
        d.format_secondary_text(f"{ev['name']} ({ev['os']}) typed the correct code {ev['code'][:3]} {ev['code'][3:]}.\n\n"
                                "Paired devices connect to each other automatically and can send each other files "
                                "(you're still asked before files are saved, unless you turn on Auto-accept).")
        d.add_buttons("Cancel", Gtk.ResponseType.REJECT, "Pair", Gtk.ResponseType.ACCEPT)
        d.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_style_context().add_class("suggested-action")
        d.set_keep_above(True)

        def respond(dlg, resp):
            if not ev["event"].is_set():
                ev["accepted"] = resp == Gtk.ResponseType.ACCEPT
                ev["event"].set()
                if ev["accepted"]:
                    self.on_pair_event(f"🔗 Paired with {ev['name']}")
            dlg.destroy()
        d.connect("response", respond)
        GLib.timeout_add_seconds(80, lambda: (d.response(Gtk.ResponseType.REJECT) if not ev["event"].is_set() else None) and False)
        d.show_all()
        d.present()
        self.present()
        return False

    def on_peers_changed(self):
        if self.share_win:
            self.share_win.refresh_peers()
        return False

    def ask_incoming(self, req):
        names = ["/".join(parts) for parts, _ in req["files"]]
        listing = "\n".join("•  " + n for n in names[:6])
        if len(names) > 6:
            listing += f"\n…and {len(names) - 6} more"
        n = len(names)
        d = Gtk.MessageDialog(transient_for=self, modal=False, message_type=Gtk.MessageType.QUESTION,
                              text=f"{req['from']} wants to send you {n} file{'s' if n != 1 else ''}")
        d.format_secondary_text(f"{human_size(req['total'])} from {req['from']} ({req['os']}, {req['ip']})\n\n"
                                f"{listing}\n\nThey will be saved in {short(received_dir())}")
        d.add_buttons("Decline", Gtk.ResponseType.REJECT, "Accept", Gtk.ResponseType.ACCEPT)
        d.get_widget_for_response(Gtk.ResponseType.ACCEPT).get_style_context().add_class("suggested-action")
        d.set_keep_above(True)
        always = None
        if req.get("paired"):
            d.set_property("text", f"🔗 {req['from']} (paired) wants to send you {n} file{'s' if n != 1 else ''}")
            always = Gtk.CheckButton(label=f"Always accept files from {req['from']}")
            always.set_margin_start(12)
            d.get_message_area().add(always)
            always.show()

        def respond(dlg, resp):
            if not req["event"].is_set():
                req["accepted"] = resp == Gtk.ResponseType.ACCEPT
                if req["accepted"] and always is not None and always.get_active():
                    p = self.paired.pair(req.get("pair_id"))
                    if p:
                        p["auto_accept"] = True
                        self.paired.save()
                        self.on_pairs_changed()
                req["event"].set()
                if self.share_win:
                    verb = "Accepted" if req["accepted"] else "Declined"
                    self.share_win.log_line(f"{verb} {n} file{'s' if n != 1 else ''} from {req['from']}")
            dlg.destroy()

        def give_up():
            if not req["event"].is_set():
                d.response(Gtk.ResponseType.REJECT)
            return False
        d.connect("response", respond)
        GLib.timeout_add_seconds(60, give_up)
        d.show_all()
        d.present()
        return False

    def on_nearby_progress(self, req):
        if self.share_win:
            self.share_win.vis_state.set_markup(
                f"⬇ Receiving from <b>{esc(req['from'])}</b>: {req['done_files']} / {len(req['files'])} files "
                f"({human_size(req['received'])} of {human_size(req['total'])})")
        return False

    def on_nearby_received(self, req):
        n = len(req["files"])
        msg = f"Received {n} file{'s' if n != 1 else ''} from {req['from']}"
        if self.share_win:
            self.share_win.log_line("✓ " + msg)
            self.share_win.update_state()
        if self.active:
            self.active.flash(msg)
        target = req["dest"][0] if n == 1 else received_dir()
        d = Gtk.MessageDialog(transient_for=self, modal=False, message_type=Gtk.MessageType.INFO,
                              text=msg)
        d.format_secondary_text(f"Saved in {short(received_dir())}")
        d.add_buttons("Close", Gtk.ResponseType.CLOSE, "Show files", Gtk.ResponseType.ACCEPT)

        def respond(dlg, resp):
            dlg.destroy()
            if resp == Gtk.ResponseType.ACCEPT:
                self.present()
                if n == 1:
                    self.active.show_in_folder(str(target))
                else:
                    self.active.go(str(received_dir()))
        d.connect("response", respond)
        d.show_all()
        return False

    @staticmethod
    def firewall_on():
        if IS_WIN:
            return False
        try:
            return "ENABLED=yes" in Path("/etc/ufw/ufw.conf").read_text()
        except OSError:
            return False

    def start_share(self, minutes):
        try:
            self.share.start(minutes)
        except OSError as ex:
            self.error(f"Couldn't start sharing: {ex}")
            return False
        self.share_win.log_line(f"Sharing started on port {self.share.port}")
        if IS_WIN:
            self.share_win.log_line("If Windows asks about the firewall, allow Arckad-D on Private networks.")
        if self.firewall_on():
            self.share_win.log_line("⚠ Ubuntu's firewall (ufw) is on. If other devices can't connect, run:  "
                                    "sudo ufw allow 8765:8767/tcp")
        self.share_win.tabs.set_visible_child_name("send")
        self.share_win.pages.set_visible_child_name("link")
        GLib.timeout_add_seconds(1, self.share_tick)
        self.update_share_button()
        return True

    def stop_share(self, expired=False):
        self.share.stop()
        if self.share_win:
            self.share_win.log_line("Time is up, sharing turned off" if expired else "Sharing turned off")
            self.share_win.update_state()
        self.update_share_button()
        if expired and self.active:
            self.active.flash("Quick Share ended (time is up)")

    def share_tick(self):
        if self.share.server is None:
            self.update_share_button()
            return False
        if not self.share.active():
            self.stop_share(expired=True)
            return False
        self.update_share_button()
        if self.share_win and self.share_win.get_visible():
            self.share_win.update_state()
        return True

    def update_share_button(self):
        ctx = self.share_btn.get_style_context()
        if self.share.active():
            left = self.share.remaining()
            self.share_label.set_text(f"Link {left // 60}:{left % 60:02d}")
            ctx.add_class("suggested-action")
        else:
            self.share_label.set_text("Send")
            ctx.remove_class("suggested-action")
        rctx = self.recv_btn.get_style_context()
        if self.nearby.visible():
            left = self.nearby.remaining()
            self.recv_label.set_text(f"Receiving {left // 60}:{left % 60:02d}")
            rctx.add_class("suggested-action")
        else:
            self.recv_label.set_text("Receive")
            rctx.remove_class("suggested-action")

    def on_share_event(self, client, text):
        if self.share_win:
            self.share_win.log_line(f"{client} {text}")
        return False

    # ---------- auto-sort Downloads
    def autosort_dialog(self):
        dlg = Gtk.Dialog(title="Auto-sort Downloads", transient_for=self, modal=True)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "Save", Gtk.ResponseType.OK)
        dlg.get_widget_for_response(Gtk.ResponseType.OK).get_style_context().add_class("suggested-action")
        box = dlg.get_content_area()
        box.set_spacing(10)
        box.set_border_width(14)
        intro = Gtk.Label(xalign=0, wrap=True, max_width_chars=60)
        intro.set_markup(f"New files that arrive in <b>{esc(short(downloads_dir()))}</b> are moved into "
                         "Images/, Documents/, Installers/ and so on, inside the same folder. "
                         "Files still downloading are left alone, files already there are not touched, "
                         "and Undo (↶) puts sorted files back.")
        box.add(intro)
        enable = Gtk.CheckButton(label="Auto-sort new downloads")
        enable.set_active(self.cfg["autosort"])
        box.add(enable)
        only_open = Gtk.RadioButton.new_with_label(None, f"Only while {APP_NAME} is open")
        always = Gtk.RadioButton.new_with_label_from_widget(only_open, "Always, in the background (starts when you log in)")
        always.set_active(self.cfg["autosort_background"])
        delay_box = Gtk.Box(spacing=8)
        delay_box.add(Gtk.Label(label="Wait after a download finishes:"))
        delay = Gtk.SpinButton.new_with_range(3, 120, 1)
        delay.set_value(self.cfg["autosort_delay"])
        delay_box.add(delay)
        delay_box.add(Gtk.Label(label="seconds"))
        opts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_start=24)
        for w in (only_open, always, delay_box):
            opts.add(w)
        box.add(opts)
        enable.connect("toggled", lambda b: opts.set_sensitive(b.get_active()))
        opts.set_sensitive(enable.get_active())
        dlg.show_all()
        resp = dlg.run()
        if resp == Gtk.ResponseType.OK:
            self.cfg["autosort"] = enable.get_active()
            self.cfg["autosort_background"] = always.get_active()
            self.cfg["autosort_delay"] = int(delay.get_value())
            write_json(CONFIG_FILE, self.cfg)
            self.apply_autosort()
            state = ("on (in the background)" if self.cfg["autosort_background"] else "on (while open)") \
                if self.cfg["autosort"] else "off"
            self.active.flash(f"Auto-sort Downloads is {state}")
        dlg.destroy()

    def apply_autosort(self, startup=False):
        if self.sorter:
            self.sorter.stop()
            self.sorter = None
        on, bg = self.cfg["autosort"], self.cfg["autosort_background"]
        set_autostart(on and bg)
        if on and bg:
            if not service_running():
                start_service()
            elif not startup:          # restart so a new delay setting takes effect
                stop_service()
                GLib.timeout_add(800, start_service)
            return
        stop_service()
        if on and downloads_dir().is_dir():
            self.sorter = AutoSorter(downloads_dir(), self.cfg["autosort_delay"], on_moved=self.on_autosorted)

    def on_autosorted(self, moved):
        self.undo_btn.set_sensitive(True)
        names = ", ".join(f"{os.path.basename(s)} → {Path(d).parent.name}/" for s, d in moved[:3])
        more = f" and {len(moved) - 3} more" if len(moved) > 3 else ""
        self.active.flash(f"Auto-sorted {names}{more}")

    # ---------- dialogs
    def error(self, msg, parent=None):
        d = Gtk.MessageDialog(transient_for=parent or self, modal=True, message_type=Gtk.MessageType.WARNING,
                              buttons=Gtk.ButtonsType.OK, text=msg)
        d.run()
        d.destroy()

    def info(self, msg, mono=False):
        d = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                              buttons=Gtk.ButtonsType.OK)
        if mono:
            d.set_markup(f"<tt>{esc(msg)}</tt>")
        else:
            d.set_property("text", msg)
        d.run()
        d.destroy()

    def confirm(self, msg, parent=None):
        d = Gtk.MessageDialog(transient_for=parent or self, modal=True, message_type=Gtk.MessageType.QUESTION,
                              buttons=Gtk.ButtonsType.OK_CANCEL, text=msg)
        ok = d.run() == Gtk.ResponseType.OK
        d.destroy()
        return ok

    def ask_text(self, title, label, text, select_stem=False, password=False):
        dlg = Gtk.Dialog(title=title, transient_for=self, modal=True)
        dlg.add_buttons("Cancel", Gtk.ResponseType.CANCEL, "OK", Gtk.ResponseType.OK)
        dlg.set_default_response(Gtk.ResponseType.OK)
        box = dlg.get_content_area()
        box.set_spacing(8)
        box.set_border_width(12)
        box.add(Gtk.Label(label=label, xalign=0))
        entry = Gtk.Entry(text=text, activates_default=True, width_chars=44, visibility=not password)
        box.add(entry)
        dlg.show_all()
        stem = os.path.splitext(text)[0] if select_stem and not text.startswith(".") else text
        entry.select_region(0, len(stem))
        resp = dlg.run()
        value = entry.get_text().strip()
        dlg.destroy()
        return value if resp == Gtk.ResponseType.OK and value else None

    # ---------- keyboard
    def on_key(self, _w, event):
        key = Gdk.keyval_name(event.keyval) or ""
        low = key.lower()
        ctrl = bool(event.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(event.state & Gdk.ModifierType.MOD1_MASK)
        shift = bool(event.state & Gdk.ModifierType.SHIFT_MASK)
        typing = isinstance(self.get_focus(), (Gtk.Entry, Gtk.TextView))
        pane = self.active
        if ctrl and low == "t":
            self.new_tab()
        elif ctrl and low == "w":
            self.close_tab(pane)
        elif ctrl and low == "h":
            self.hidden_item.set_active(not self.hidden_item.get_active())
        elif ctrl and shift and low == "d":
            self.cycle_theme()
        elif key == "F3":
            self.dual_btn.set_active(not self.dual_btn.get_active())
        elif key == "F6" and self.other_pane():
            other = self.other_pane()
            (other.icons if other.view_mode == "grid" else other.tree).grab_focus()
        elif key == "space" and not typing:
            self.preview_btn.set_active(not self.preview_btn.get_active())
        elif ctrl and key in ("1", "KP_1"):
            pane.set_view("list")
        elif ctrl and key in ("2", "KP_2"):
            pane.set_view("grid")
        elif ctrl and low == "c" and not typing and pane.selected_paths():
            self.set_clipboard(pane.selected_paths(), False)
        elif ctrl and low == "x" and not typing and pane.selected_paths():
            self.set_clipboard(pane.selected_paths(), True)
        elif ctrl and low == "v" and not typing and self.clipboard:
            self.paste_into(pane)
        elif pane.handle_key(key, ctrl, alt, typing):
            pass
        else:
            return False
        return True

    def on_close(self, *_):
        self.preview.flush_note()
        self.cfg["size"] = list(self.get_size())
        self.cfg["tabs"] = {side: [nb.get_nth_page(i).location for i in range(nb.get_n_pages())]
                            for side, nb in (("left", self.left_nb), ("right", self.right_nb))}
        write_json(CONFIG_FILE, self.cfg)
        if self.sorter:
            self.sorter.stop()
        self.share.stop()
        self.paired.stop()
        self.nearby.scanning = False
        self.nearby.hide(force=True)
        return False


def show_crash(text):
    log = CACHE_DIR / "error.log"
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        log.write_text(text)
    except OSError:
        pass
    print(text, file=sys.stderr)
    try:
        d = Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE,
                              text=f"{APP_NAME} couldn't start")
        d.format_secondary_text(f"The error was saved to {log}\n\n{text[-1500:]}")
        d.run()
        d.destroy()
    except Exception:
        pass


def selftest(out):
    """Used by the automatic Windows build to check that everything got bundled."""
    lines = [f"python {sys.version.split()[0]}", f"platform {sys.platform}",
             f"gtk {Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"]
    checks = {
        "logo": logo_pixbuf(64) is not None,
        "qr code": qr_pixbuf("https://example.com/test") is not None,
        "folder icon": Gtk.IconTheme.get_default().has_icon("folder"),
        "svg loader": load_scaled(ensure_logo(), 32) is not None if ensure_logo() else False,
    }
    win = Gtk.Window()
    win.add(Gtk.Label(label=APP_NAME))
    for name, ok in checks.items():
        lines.append(f"{name}: {'ok' if ok else 'MISSING'}")
    lines.append("SELFTEST OK" if checks["logo"] and checks["folder icon"] else "SELFTEST FAILED")
    Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if lines[-1] == "SELFTEST OK" else 1


def main():
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        sys.exit(selftest(sys.argv[i + 1] if len(sys.argv) > i + 1 else "selftest.txt"))
    if IS_WIN and "--install" in sys.argv:
        return
    if INSTALLED and "--install" in sys.argv:
        print(f"{APP_NAME} is installed from the .deb package and is already in your app menu.")
        return
    if "--install" in sys.argv:
        print(f"Added to app menu: {install_launcher()}")
        print(f"Search for '{APP_NAME}' in Activities.")
        return
    if "--autosort" in sys.argv:
        run_autosort_service()
        return
    if IS_WIN:
        try:
            import ctypes
            global _RUN_MUTEX
            _RUN_MUTEX = ctypes.windll.kernel32.CreateMutexW(None, False, "ArckadD-Running")   # updates wait for it
        except Exception:
            pass
    failed = None
    if "--update-failed" in sys.argv:
        i = sys.argv.index("--update-failed")
        failed = sys.argv[i + 1] if len(sys.argv) > i + 1 else "?"
    start = next((os.path.abspath(os.path.expanduser(a)) for a in sys.argv[1:]
                  if os.path.isdir(os.path.expanduser(a))), None)
    fix_user_launcher()
    GLib.set_prgname(APP_SLUG)
    GLib.set_application_name(APP_NAME)
    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)

    def activate(a):
        try:
            win = MainWindow(a, start)
            win.present()
            if failed:
                GLib.timeout_add(800, lambda: win.show_update_failure(failed) or False)
        except Exception:
            import traceback
            show_crash(traceback.format_exc())
            a.quit()
    app.connect("activate", activate)
    app.run([sys.argv[0]])


if __name__ == "__main__":
    main()

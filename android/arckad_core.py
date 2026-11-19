"""
Arckad-D for Android: everything that isn't the screen.
Files, thumbnails, and the Nearby / link sharing that talks to Arckad-D on Linux and Windows.
The network protocol here must stay the same as in ../arckad-d.py.
"""
import hashlib
import html as htmlmod
import json
import mimetypes
import os
import secrets
import shutil
import socket
import threading
import time
import urllib.parse
import zipfile
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ON_ANDROID = "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ

CATEGORIES = {
    "Images": {"jpg", "jpeg", "png", "gif", "bmp", "svg", "webp", "heic", "heif", "tiff"},
    "Documents": {"pdf", "doc", "docx", "odt", "txt", "rtf", "md", "epub"},
    "Spreadsheets": {"xls", "xlsx", "ods", "csv", "tsv"},
    "Presentations": {"ppt", "pptx", "odp", "key"},
    "Videos": {"mp4", "mkv", "avi", "mov", "webm", "3gp", "flv", "wmv"},
    "Audio": {"mp3", "wav", "flac", "ogg", "m4a", "aac", "opus", "amr"},
    "Archives": {"zip", "tar", "gz", "bz2", "xz", "7z", "rar", "tgz"},
    "Code": {"py", "js", "ts", "java", "kt", "c", "cpp", "h", "html", "css", "json", "xml", "sh", "yaml", "yml"},
    "Apps": {"apk", "apks", "xapk", "aab"},
}
KINDS = ["All types", "Folders"] + list(CATEGORIES) + ["Others"]
TEXT_EXTS = {"txt", "md", "csv", "tsv", "log", "json", "xml", "html", "css", "js", "py", "java", "kt",
             "c", "cpp", "h", "sh", "yaml", "yml", "ini", "srt"}
SKIP_DIRS = {"Android", ".thumbnails", ".trash", ".Trash", "node_modules", ".git", "__pycache__", "LOST.DIR"}
SHARE_MINUTES = [1, 2, 5, 10]
NEARBY_UDP_PORT = 47820
NEARBY_TCP_PORTS = (47821, 47822, 47823, 0)
SHARE_PORTS = (8765, 8766, 8767, 0)
OS_NAME = "Android" if ON_ANDROID else "Linux"
BAD_NAME_CHARS = set('<>:"|?*\\')


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


def fmt_time(ts):
    d, now = datetime.fromtimestamp(ts), datetime.now()
    if d.date() == now.date():
        return "Today " + d.strftime("%H:%M")
    if (now.date() - d.date()).days == 1:
        return "Yesterday " + d.strftime("%H:%M")
    if d.year == now.year:
        return d.strftime("%d %b %H:%M")
    return d.strftime("%d %b %Y")


def day_label(d):
    today = date.today()
    if d == today:
        return "Today"
    if d == today - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%A, %d %B" + (" %Y" if d.year != today.year else ""))


def ago(ts):
    s = int(time.time() - ts)
    if s < 60:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if s >= size:
            n = s // size
            return f"{n} {unit}{'s' if n > 1 else ''} ago"


def storage_root():
    if ON_ANDROID:
        for p in ("/storage/emulated/0", "/sdcard"):
            if os.path.isdir(p):
                return p
    return str(Path.home())


def downloads_dir():
    return os.path.join(storage_root(), "Download") if ON_ANDROID else str(Path.home() / "Downloads")


def received_dir():
    d = os.path.join(downloads_dir(), "Arckad-D Received")
    os.makedirs(d, exist_ok=True)
    return d


def short(path):
    root = storage_root()
    p = str(path)
    if p == root:
        return "Internal storage" if ON_ANDROID else "Home"
    if p.startswith(root + os.sep):
        rel = p[len(root) + 1:]
        return rel if ON_ANDROID else "~/" + rel
    return p


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


def is_hidden(name):
    return name.startswith(".")


# ---------------------------------------------------------------- listing & searching
def entry(path, st=None):
    st = st or os.stat(path)
    is_dir = os.path.isdir(path)
    name = os.path.basename(path.rstrip("/")) or path
    return {"name": name, "path": path, "is_dir": is_dir, "size": 0 if is_dir else st.st_size,
            "mtime": st.st_mtime, "kind": "Folders" if is_dir else category_of(name)}


def list_dir(folder, hidden=False):
    out = []
    with os.scandir(folder) as it:
        for e in it:
            if not hidden and is_hidden(e.name):
                continue
            try:
                out.append(entry(e.path, e.stat()))
            except OSError:
                continue
    return out


def sort_entries(items, by="name"):
    if by == "date":
        key = lambda e: (not e["is_dir"], -e["mtime"])
    elif by == "size":
        key = lambda e: (not e["is_dir"], -e["size"], e["name"].lower())
    else:
        key = lambda e: (not e["is_dir"], e["name"].lower())
    return sorted(items, key=key)


def walk(root, hidden=False):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and (hidden or not is_hidden(d))]
        for name in dirnames + filenames:
            if not hidden and is_hidden(name):
                continue
            p = os.path.join(dirpath, name)
            try:
                yield entry(p)
            except OSError:
                continue


def matches(e, query="", kind="All types"):
    if query and not all(w in e["name"].lower() for w in query.lower().split()):
        return False
    return kind == "All types" or e["kind"] == kind


def recent_files(days=14, limit=400):
    cutoff = time.time() - days * 86400
    found = [e for e in walk(storage_root()) if not e["is_dir"] and e["mtime"] >= cutoff]
    found.sort(key=lambda e: -e["mtime"])
    return found[:limit]


def copy_or_move(paths, dest, move):
    """Pastes into dest; a name that already exists gets ' (1)' added. Returns (done, errors)."""
    done, errors = 0, []
    for src in paths:
        name = os.path.basename(src.rstrip("/"))
        if os.path.isdir(src) and (dest + os.sep).startswith(src.rstrip("/") + os.sep):
            errors.append(f"{name}: can't put a folder inside itself")
            continue
        if move and os.path.dirname(src) == dest:
            continue
        target = str(unique_target(Path(dest) / name))
        try:
            if move:
                shutil.move(src, target)
            elif os.path.isdir(src):
                shutil.copytree(src, target)
            else:
                shutil.copy2(src, target)
            done += 1
        except (OSError, shutil.Error) as ex:
            errors.append(f"{name}: {getattr(ex, 'strerror', None) or ex}")
    return done, errors


def delete_paths(paths):
    errors = []
    for p in paths:
        try:
            if os.path.isdir(p) and not os.path.islink(p):
                shutil.rmtree(p)
            else:
                os.remove(p)
        except OSError as ex:
            errors.append(f"{os.path.basename(p)}: {ex.strerror}")
    return errors


def read_text(path, max_bytes=60_000):
    with open(path, "rb") as f:
        data = f.read(max_bytes)
    if b"\0" in data[:4096]:
        return None
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- thumbnails
def thumbnail(path, cache_dir, size=192):
    """Small PNG copy of a picture, cached; returns its path or None."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = hashlib.md5(f"{path}|{st.st_mtime}|{st.st_size}|{size}".encode()).hexdigest()
    out = os.path.join(cache_dir, key + ".png")
    if os.path.exists(out):
        return out
    try:
        from PIL import Image, ImageOps
        with Image.open(path) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((size, size))
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            os.makedirs(cache_dir, exist_ok=True)
            im.save(out, "PNG")
        return out
    except Exception:
        return None


class ThumbWorker:
    """Makes thumbnails one by one in the background."""

    def __init__(self, cache_dir, on_ready):
        self.cache_dir, self.on_ready = cache_dir, on_ready
        self.queue, self.lock, self.busy = [], threading.Lock(), False
        self.known = {}

    def request(self, path):
        if path in self.known:
            return self.known[path]
        with self.lock:
            if path not in self.queue:
                self.queue.append(path)
            if not self.busy:
                self.busy = True
                threading.Thread(target=self._run, daemon=True).start()
        return None

    def clear_queue(self):
        with self.lock:
            self.queue.clear()

    def _run(self):
        while True:
            with self.lock:
                if not self.queue:
                    self.busy = False
                    return
                path = self.queue.pop(0)
            thumb = thumbnail(path, self.cache_dir)
            self.known[path] = thumb or ""
            if thumb:
                self.on_ready(path, thumb)


# ---------------------------------------------------------------- network helpers
def lan_addresses():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")] or ["127.0.0.1"]


def safe_rel_parts(rel):
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
    out = []
    for p in paths:
        if os.path.isdir(p):
            base = os.path.dirname(p.rstrip("/"))
            for e in walk(p, hidden=True):
                if not e["is_dir"]:
                    out.append((e["path"], os.path.relpath(e["path"], base).replace(os.sep, "/"), e["size"]))
        elif os.path.isfile(p):
            out.append((p, os.path.basename(p), os.path.getsize(p)))
    return out


def plan_destinations(files):
    base = Path(received_dir())
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


def _json_reply(handler, code, obj):
    data = json.dumps(obj).encode()
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def make_nearby_handler(nb):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Arckad-D"

        def log_message(self, *args):
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
                    return _json_reply(self, 403, {"ok": False, "reason": "not visible right now"})
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > 5_000_000:
                    return _json_reply(self, 413, {"ok": False, "reason": "offer too large"})
                try:
                    offer = json.loads(self.rfile.read(length))
                except ValueError:
                    return _json_reply(self, 400, {"ok": False, "reason": "bad offer"})
                files = []
                for f in (offer.get("files") or [])[:20000]:
                    rel, size = safe_rel_parts(f.get("path", "")), f.get("size")
                    if rel is None or not isinstance(size, int) or size < 0:
                        return _json_reply(self, 400, {"ok": False, "reason": "bad file name"})
                    files.append((rel, size))
                if not files:
                    return _json_reply(self, 400, {"ok": False, "reason": "no files"})
                req = {"from": str(offer.get("name") or "Unknown device")[:40],
                       "os": str(offer.get("os") or "")[:10], "ip": self.client_address[0],
                       "files": files, "total": sum(s for _, s in files),
                       "event": threading.Event(), "accepted": False}
                nb.ui("ask_incoming", req)
                req["event"].wait(90)
                if not req["accepted"]:
                    return _json_reply(self, 403, {"ok": False, "reason": "declined"})
                req["dest"] = plan_destinations(files)
                req["received"], req["done_files"] = 0, 0
                token = secrets.token_hex(12)
                nb.transfers[token] = req
                return _json_reply(self, 200, {"ok": True, "token": token})
            if len(parts) == 2 and parts[0] == "done":
                req = nb.transfers.pop(parts[1], None)
                if not req:
                    return _json_reply(self, 404, {"ok": False})
                nb.ui("on_received", req)
                return _json_reply(self, 200, {"ok": True})
            return _json_reply(self, 404, {"ok": False})

        def _put(self):
            parts = [p for p in self.path.split("/") if p]
            if len(parts) != 3 or parts[0] != "upload" or not parts[2].isdigit():
                return _json_reply(self, 404, {"ok": False})
            req, i = nb.transfers.get(parts[1]), int(parts[2])
            if not req or i >= len(req["files"]):
                return _json_reply(self, 404, {"ok": False})
            size = req["files"][i][1]
            if int(self.headers.get("Content-Length") or -1) != size:
                return _json_reply(self, 400, {"ok": False, "reason": "size mismatch"})
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
                return _json_reply(self, 400, {"ok": False, "reason": "incomplete"})
            os.replace(tmp, dest)
            req["done_files"] += 1
            nb.ui("on_progress", req)
            return _json_reply(self, 200, {"ok": True})
    return Handler


class Nearby:
    """Find other Arckad-D devices (UDP) and send / receive files (HTTP). Same protocol as the desktop app."""

    def __init__(self, device_id, get_name, ui):
        self.id, self.get_name, self.ui = device_id, get_name, ui
        self.peers, self.lock = {}, threading.Lock()
        self.udp, self.scanning, self.server, self.port = None, False, None, 0
        self.visible_until, self.transfers = 0, {}
        self._ips = ([], 0)
        self.last_beacon = self.last_probe = self.last_expire = 0

    def name(self):
        return (self.get_name() or "My phone").strip()[:40]

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
            return False
        srv, self.server = self.server, None
        if srv:
            self._send({"type": "bye"})
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()
        self._maybe_close_udp()
        return True

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
            self.ui("on_peers_changed")

    def _tick(self):
        now = time.time()
        if self.visible() and now - self.last_beacon > 2:
            self.last_beacon = now
            self._send({"type": "hello"})
        if self.scanning and now - self.last_probe > 3:
            self.last_probe = now
            self._send({"type": "probe"})
        if now - self.last_expire > 2:
            self.last_expire = now
            with self.lock:
                gone = [k for k, p in self.peers.items() if now - p["seen"] > 8]
                for k in gone:
                    del self.peers[k]
            if gone:
                self.ui("on_peers_changed")

    def send(self, peer, paths, progress, done):
        def work():
            try:
                result = self._send_files(peer, files_for_sending(paths), progress)
            except (OSError, ValueError, KeyError) as ex:
                result = (f"Couldn't reach {peer['name']}. Check both devices are on the same Wi-Fi. ({ex})")
            done(peer, result)
        threading.Thread(target=work, daemon=True).start()

    def _send_files(self, peer, files, progress):
        import http.client
        if not files:
            return "There are no files to send (empty folders are skipped)."
        total = sum(f[2] for f in files)
        offer = {"name": self.name(), "os": OS_NAME, "id": self.id,
                 "files": [{"path": rel, "size": size} for _, rel, size in files]}
        progress(0, total, f"Waiting for {peer['name']} to accept…")
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
                        progress(sent, total, f"Sending {rel}…")
            r = conn.getresponse()
            r.read()
            conn.close()
            if r.status != 200 or remaining:
                return f"Sending stopped at {rel}."
        conn = http.client.HTTPConnection(peer["ip"], peer["port"], timeout=30)
        conn.request("POST", f"/done/{token}", b"")
        conn.getresponse().read()
        conn.close()
        progress(total, total, "Done")
        return None


# ---------------------------------------------------------------- share as link (any browser)
PAGE_CSS = """
:root{--bg:#f6f5f4;--card:#fff;--text:#1d1d1f;--muted:#6b6b6f;--accent:#5b5bd6;--line:#e3e2e0}
@media (prefers-color-scheme:dark){:root{--bg:#1e1e20;--card:#2a2a2d;--text:#f2f2f2;--muted:#a0a0a6;--accent:#8c8cff;--line:#3a3a3e}}
*{box-sizing:border-box}body{margin:0;font-family:system-ui,sans-serif;background:var(--bg);color:var(--text)}
main{max-width:720px;margin:0 auto;padding:20px 14px 40px}h1{font-size:22px;margin:0}
.sub{color:var(--muted);margin:4px 0 16px}.timer{background:var(--accent);color:#fff;border-radius:999px;padding:3px 10px}
.all{display:block;text-align:center;background:var(--accent);color:#fff;text-decoration:none;border-radius:12px;padding:13px;margin:14px 0;font-weight:600}
ul{list-style:none;padding:0;margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px}
li{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--line)}li:first-child{border-top:0}
.info{flex:1;min-width:0}.name{font-weight:600;overflow-wrap:anywhere}.meta{color:var(--muted);font-size:13px}
a.dl{background:var(--accent);color:#fff;text-decoration:none;border-radius:9px;padding:7px 11px}
"""


def make_share_handler(share):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Arckad-D"

        def log_message(self, *args):
            pass

        def _html(self, code, body):
            data = body.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
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
            page = "<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            if not parts or not secrets.compare_digest(parts[0], share.token):
                return self._html(404, page + "<main><h1>Link not found</h1></main>")
            if not share.active():
                return self._html(410, page + "<main><h1>This share has ended</h1></main>")
            items = share.snapshot()
            client = self.client_address[0]
            if len(parts) == 1:
                share.event(client, "opened the share page")
                rows = "".join(
                    f"<li><div class=info><div class=name>{htmlmod.escape(os.path.basename(p))}</div>"
                    f"<div class=meta>{'folder · ZIP' if os.path.isdir(p) else human_size(os.path.getsize(p))}</div></div>"
                    f"<a class=dl href='f/{i}'>Download</a></li>" for i, p in enumerate(items))
                all_btn = "<a class=all href='all.zip'>⬇ Download everything (ZIP)</a>" if len(items) > 1 else ""
                body = (f"{page}<title>Arckad-D share</title><style>{PAGE_CSS}</style><main><h1>Files shared from "
                        f"{htmlmod.escape(share.device_name())}</h1><p class=sub>Arckad-D Quick Share · "
                        f"<span class=timer>{share.remaining() // 60} min left</span></p>{all_btn}<ul>{rows}</ul></main>")
                return self._html(200, body)
            if parts[1] == "all.zip" and items:
                share.event(client, "downloaded everything (ZIP)")
                return self._zip(items, "Arckad-D share.zip")
            if parts[1] == "f" and len(parts) >= 3 and parts[2].isdigit() and int(parts[2]) < len(items):
                path = items[int(parts[2])]
                name = os.path.basename(path.rstrip("/"))
                if os.path.isdir(path):
                    share.event(client, f"downloaded folder {name}")
                    return self._zip([path], name + ".zip")
                share.event(client, f"downloaded {name}")
                size = os.path.getsize(path)
                self.send_response(200)
                self.send_header("Content-Type", mimetypes.guess_type(name)[0] or "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}")
                self.end_headers()
                with open(path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile, 1 << 20)
                return
            return self._html(404, page + "<main><h1>Not found</h1></main>")

        def _zip(self, paths, name):
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(name)}")
            self.send_header("Connection", "close")
            self.end_headers()
            with zipfile.ZipFile(self.wfile, "w", zipfile.ZIP_DEFLATED, compresslevel=1, allowZip64=True) as zf:
                for p in paths:
                    if os.path.isdir(p):
                        base = os.path.dirname(p.rstrip("/"))
                        for e in walk(p, hidden=True):
                            if not e["is_dir"]:
                                zf.write(e["path"], os.path.relpath(e["path"], base))
                    elif os.path.exists(p):
                        zf.write(p, os.path.basename(p))
    return Handler


class LinkShare:
    def __init__(self, device_name, ui):
        self.device_name, self.ui = device_name, ui
        self.items, self.server, self.token, self.port, self.expires = [], None, "", 0, 0

    def snapshot(self):
        return [p for p in self.items if os.path.exists(p)]

    def active(self):
        return self.server is not None and time.time() < self.expires

    def remaining(self):
        return max(0, int(self.expires - time.time())) if self.server else 0

    def start(self, minutes):
        self.stop()
        self.token = "".join(secrets.choice("abcdefghjkmnpqrstuvwxyz23456789") for _ in range(8))
        for port in SHARE_PORTS:
            try:
                self.server = ThreadingHTTPServer(("0.0.0.0", port), make_share_handler(self))
                break
            except OSError:
                continue
        if self.server is None:
            raise OSError("no free network port")
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.expires = time.time() + min(10, max(1, minutes)) * 60
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def stop(self):
        srv, self.server = self.server, None
        if srv:
            threading.Thread(target=lambda: (srv.shutdown(), srv.server_close()), daemon=True).start()

    def url(self):
        return f"http://{lan_addresses()[0]}:{self.port}/{self.token}/"

    def event(self, client, text):
        self.ui("on_share_event", client, text)


def qr_matrix(text):
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(border=2, box_size=1)
    qr.add_data(text)
    qr.make(fit=True)
    return qr.get_matrix()


# ---------------------------------------------------------------- updates from GitHub Releases
UPDATE_REPO = "TAMILTIMON/Arckad"


def version_tuple(v):
    import re
    nums = [int(x) for x in re.findall(r"\d+", str(v))[:4]]
    return tuple(nums + [0] * (3 - len(nums))) if nums else (0, 0, 0)


def fetch_latest_release(app_version, timeout=15):
    """Newest release: (version, page url, apk url or None)."""
    import urllib.error
    import urllib.request
    agent = {"User-Agent": f"Arckad-D-Android/{app_version}"}
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{UPDATE_REPO}/releases/latest",
                                     headers=dict(agent, Accept="application/vnd.github+json"))
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            rel = json.loads(resp.read().decode("utf-8"))
        apk = next((a["browser_download_url"] for a in rel.get("assets", []) if a.get("name", "").endswith(".apk")), None)
        return rel.get("tag_name", "").lstrip("vV"), rel.get("html_url"), apk
    except urllib.error.HTTPError as ex:
        if ex.code not in (403, 429):
            raise
    with urllib.request.urlopen(urllib.request.Request(
            f"https://github.com/{UPDATE_REPO}/releases/latest", headers=agent), timeout=timeout) as resp:
        page = resp.geturl()
    tag = page.rstrip("/").rsplit("/", 1)[-1]
    ver = tag.lstrip("vV")
    return ver, page, f"https://github.com/{UPDATE_REPO}/releases/download/{tag}/Arckad-D-{ver}.apk"


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)

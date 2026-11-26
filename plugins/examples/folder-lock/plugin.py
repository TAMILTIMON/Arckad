"""Folder lock: a password on any single folder, not just the private vault.

How it works: the folder is renamed with a " (locked)" tag and its own permissions are removed (chmod 0 on Linux,
an access-denied rule on Windows), so nothing — not even Arckad-D itself — can open or list it without the
password. This blocks access; it does not encrypt the folder's contents. For documents that need real encryption,
use Arckad-D's own Private vault instead.

The password is never stored. Only a salted hash of it is kept, in this plugin's own data folder, so Arckad-D can
tell a correct password from a wrong one.
"""
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time

SUFFIX = " (locked)"
ITERATIONS = 200_000


def setup(arckad):
    arckad.add_file_action("🔒 Lock this folder…", lock_folder, when=can_lock, icon="🔒")
    arckad.add_file_action("🔓 Unlock this folder…", unlock_folder, when=lambda paths: is_locked(arckad, paths),
                           icon="🔓")
    arckad.add_settings(build_settings)


# ---------- recognising folders ----------
def can_lock(paths):
    return len(paths) == 1 and os.path.isdir(paths[0]) and not os.path.basename(paths[0]).endswith(SUFFIX)


def is_locked(arckad, paths):
    if len(paths) != 1 or not os.path.isdir(paths[0]) or not os.path.basename(paths[0]).endswith(SUFFIX):
        return False
    return _key_for(paths[0]) in _load(arckad)


# ---------- the record of locked folders (never the password itself) ----------
def _load(arckad):
    path = arckad.data_dir / "locks.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(arckad, locks):
    tmp = arckad.data_dir / "locks.json.tmp"
    tmp.write_text(json.dumps(locks, indent=1), encoding="utf-8")
    os.replace(tmp, arckad.data_dir / "locks.json")


def _key_for(path):
    return hashlib.sha256(os.path.realpath(path).encode()).hexdigest()[:24]


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS).hex()


# ---------- the OS-level block: this is what stops access, not just the renaming ----------
def _deny_access(path):
    """Removes this folder's own permissions. Returns what to pass back to _restore_access."""
    if sys.platform == "win32":
        user = os.environ.get("USERNAME", "")
        try:
            subprocess.run(["icacls", path, "/inheritance:r", "/deny", f"{user}:(OI)(CI)F"],
                           capture_output=True, timeout=15, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return "icacls"
        except (OSError, subprocess.SubprocessError):
            return None
    try:
        mode = os.stat(path).st_mode & 0o777
        os.chmod(path, 0)
        return mode
    except OSError:
        return None


def _restore_access(path, saved):
    if saved is None:
        return
    if sys.platform == "win32":
        user = os.environ.get("USERNAME", "")
        try:
            subprocess.run(["icacls", path, "/reset"], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError):
            pass
        return
    try:
        os.chmod(path, saved)
    except OSError:
        pass


# ---------- locking ----------
def lock_folder(arckad, paths):
    path = paths[0]
    name = os.path.basename(path)
    pw = arckad.ask("Lock “" + name + "”", "Create a password for this folder:")
    if not pw:
        return
    if len(pw) < 4:
        return arckad.error("Use at least 4 characters.")
    again = arckad.ask("Lock “" + name + "”", "Type the password again to confirm:")
    if again != pw:
        return arckad.error("The two passwords didn't match. Nothing was locked.")

    salt = secrets.token_hex(16)
    record = {"name": name, "salt": salt, "hash": _hash(pw, salt), "fails": 0, "wait_until": 0}
    try:
        new_path = arckad.rename(path, name + SUFFIX)
        saved = _deny_access(new_path)
    except OSError as ex:
        return arckad.error(f"Couldn't lock it: {ex}")
    record["perm"] = saved if isinstance(saved, int) else None
    locks = _load(arckad)
    locks[_key_for(new_path)] = record
    _save(arckad, locks)
    arckad.play("vault")
    arckad.notify(f"🔒 “{name}” is locked. Right-click it and choose Unlock to open it again.")
    arckad.refresh()


# ---------- unlocking ----------
def unlock_folder(arckad, paths):
    path = paths[0]
    key = _key_for(path)
    locks = _load(arckad)
    record = locks.get(key)
    if record is None:
        return arckad.error("This folder wasn't locked by Folder lock.")
    now = time.time()
    if record.get("wait_until", 0) > now:
        wait = int(record["wait_until"] - now)
        return arckad.error(f"Too many wrong tries. Wait {wait} seconds and try again.")
    pw = arckad.ask("Unlock “" + record["name"] + "”", "Password:")
    if pw is None:
        return
    if _hash(pw, record["salt"]) != record["hash"]:
        record["fails"] = record.get("fails", 0) + 1
        if record["fails"] >= 5:
            record["wait_until"] = now + 60
            record["fails"] = 0
        locks[key] = record
        _save(arckad, locks)
        return arckad.error("That password isn't right.")

    _restore_access(path, record.get("perm", 0o755))
    try:
        new_path = arckad.rename(path, record["name"])
    except OSError as ex:
        return arckad.error(f"Unlocked, but couldn't restore the name: {ex}")
    locks.pop(key, None)
    _save(arckad, locks)
    arckad.play("vault")
    arckad.notify(f"🔓 “{record['name']}” is unlocked.")
    arckad.open_folder(os.path.dirname(new_path), select=[new_path])


def build_settings(arckad, box):
    Gtk = arckad.Gtk
    locks = _load(arckad)
    box.add(Gtk.Label(label="Folder lock", xalign=0))
    note = Gtk.Label(wrap=True, xalign=0)
    note.set_markup("<small>Locking blocks access (it removes the folder's own permissions); it does not encrypt "
                    "the contents. For documents that need real encryption, use the Private vault instead.</small>")
    box.add(note)
    n = len(locks)
    box.add(Gtk.Label(label=f"{n} folder{'s' if n != 1 else ''} currently locked by this plugin.", xalign=0))

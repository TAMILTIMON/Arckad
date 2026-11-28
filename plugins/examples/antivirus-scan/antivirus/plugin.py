"""Antivirus Scanner plugin for Arckad-D with centered threat alert dialogs."""

import hashlib
import os
import shutil
import subprocess

# Standard EICAR test signature SHA-256 + suspicious executable extensions
EICAR_SHA256 = "275a021bbfb6489e54d471899f7db9d1663fc695ec2fe2a2c4538aabf651fd0f"
DANGEROUS_EXTS = {
    ".exe", ".scr", ".pif", ".bat", ".cmd", ".vbs", ".vbe",
    ".js", ".jse", ".wsf", ".wsh", ".ps1", ".hta", ".msi", ".dll"
}
SUSPICIOUS_DOUBLE_EXTS = (
    ".pdf.exe", ".doc.exe", ".docx.exe", ".jpg.exe", ".png.exe",
    ".mp4.exe", ".zip.exe", ".txt.exe", ".pdf.scr", ".pdf.bat"
)


def setup(arckad):
    arckad.config.setdefault("auto_scan_downloads", True)
    arckad.config.setdefault("center_popup_on_clean", False)

    arckad.add_file_action("Scan for threats", scan_paths, icon="🛡️")
    arckad.add_tool("Scan current folder for threats", scan_current_folder, icon="🛡️")
    arckad.add_page("Antivirus", build_page, icon="🛡️")
    arckad.add_settings(build_settings)

    arckad.on("download_finished", _on_download_finished)


def _on_download_finished(arckad, path):
    if arckad.config.get("auto_scan_downloads", True):
        arckad.log("Auto-scanning download:", path)
        scan_paths(arckad, [path], silent_clean=True)


def scan_current_folder(arckad):
    folder = arckad.current_folder()
    if not folder:
        arckad.notify("No folder is currently open.")
        return
    scan_paths(arckad, [folder], silent_clean=False)


def scan_paths(arckad, paths, silent_clean=False):
    """Runs antivirus scan in background and pops up a centered modal on threats."""
    if not paths:
        return

    arckad.notify(f"Scanning {len(paths)} item(s) for threats...")

    def _work():
        threats = []
        scanned_count = 0

        for target in paths:
            if os.path.isdir(target):
                for root, _dirs, files in os.walk(target):
                    for fname in files:
                        fpath = os.path.join(root, fname)
                        scanned_count += 1
                        hit = _inspect_file(arckad.platform, fpath)
                        if hit:
                            threats.append(hit)
            elif os.path.isfile(target):
                scanned_count += 1
                hit = _inspect_file(arckad.platform, target)
                if hit:
                    threats.append(hit)

        return {"scanned": scanned_count, "threats": threats}

    def _done(result):
        threats = result["threats"]
        scanned = result["scanned"]
        arckad._last_av_report = result

        if threats:
            for t in threats:
                arckad.log("THREAT DETECTED:", t["path"], t["threat"])
            show_center_threat_dialog(arckad, threats)
        else:
            if not silent_clean or arckad.config.get("center_popup_on_clean", False):
                arckad.notify(f"Clean: {scanned} file(s) scanned, 0 threats found.")

    arckad.run_in_background(_work, done=_done)


# ---------------------------------------------------------------------------
# Scanner Engine (ClamAV / Windows Defender / Heuristic & Hash Check)
# ---------------------------------------------------------------------------

def _run_cmd(cmd, timeout=20):
    try:
        kwargs = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "timeout": timeout,
        }
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
        proc = subprocess.run(cmd, **kwargs)
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return -1, "", str(exc)


def _inspect_file(platform, fpath):
    name_lower = os.path.basename(fpath).lower()

    # 1. Double-extension masquerading check (e.g., invoice.pdf.exe)
    if name_lower.endswith(SUSPICIOUS_DOUBLE_EXTS):
        return {
            "path": fpath,
            "threat": "Heuristic.DoubleExtension.Masquerade",
            "engine": "Arckad Heuristic",
        }

    # 2. SHA-256 check (catches EICAR test files immediately)
    try:
        h = hashlib.sha256()
        with open(fpath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() == EICAR_SHA256:
            return {
                "path": fpath,
                "threat": "EICAR-Test-Signature",
                "engine": "Hash Engine",
            }
    except Exception:
        pass

    # 3. Native AV Engine (ClamAV on Linux, Windows Defender on Windows)
    if platform == "linux" and shutil.which("clamscan"):
        rc, out, _ = _run_cmd(["clamscan", "--no-summary", "--infected", fpath])
        if rc == 1 and "FOUND" in out:
            sig = out.strip().split(":")[-1].replace("FOUND", "").strip()
            return {"path": fpath, "threat": sig or "Malware.Detected", "engine": "ClamAV"}

    elif platform == "windows":
        defender = os.path.join(
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            "Windows Defender",
            "MpCmdRun.exe",
        )
        if os.path.isfile(defender):
            rc, out, _ = _run_cmd([defender, "-Scan", "-ScanType", "3", "-File", fpath])
            if rc == 2 or "found" in out.lower():
                return {"path": fpath, "threat": "Threat.WindowsDefender", "engine": "Windows Defender"}

    return None


# ---------------------------------------------------------------------------
# Centered Threat Modal Popup
# ---------------------------------------------------------------------------

def show_center_threat_dialog(arckad, threats):
    """Pops up a centered modal dialog on top of the active Arckad-D window."""
    Gtk = arckad.Gtk

    # Find active toplevel window so the dialog centers directly over Arckad-D
    parent = None
    for win in Gtk.Window.list_toplevels():
        if win.is_active() or win.get_visible():
            parent = win
            break

    count = len(threats)
    dialog = Gtk.MessageDialog(
        transient_for=parent,
        modal=True,
        destroy_with_parent=True,
        message_type=Gtk.MessageType.ERROR,
        buttons=Gtk.ButtonsType.NONE,
        text=f"🛡️ {count} Security Threat(s) Detected!",
    )
    dialog.set_position(Gtk.WindowPosition.CENTER_ON_PARENT if parent else Gtk.WindowPosition.CENTER)

    lines = []
    for t in threats[:8]:
        fname = os.path.basename(t["path"])
        lines.append(f"• {fname}\n   Threat: {t['threat']} ({t['engine']})\n   Location: {t['path']}")
    if count > 8:
        lines.append(f"...and {count - 8} more threat(s).")

    dialog.format_secondary_text("\n\n".join(lines))

    btn_quarantine = dialog.add_button("Quarantine / Delete Threats", Gtk.ResponseType.ACCEPT)
    btn_quarantine.get_style_context().add_class("destructive-action")
    dialog.add_button("Ignore", Gtk.ResponseType.CANCEL)

    dialog.show_all()
    response = dialog.run()
    dialog.destroy()

    if response == Gtk.ResponseType.ACCEPT:
        quarantine_dir = os.path.join(arckad.data_dir, "quarantine")
        os.makedirs(quarantine_dir, exist_ok=True)
        moved = 0
        for t in threats:
            src = t["path"]
            if os.path.exists(src):
                try:
                    dst = os.path.join(quarantine_dir, os.path.basename(src) + ".quarantined")
                    shutil.move(src, dst)
                    moved += 1
                except Exception as exc:
                    arckad.log("Quarantine failed:", src, exc)
        arckad.refresh()
        arckad.notify(f"Quarantined {moved} infected file(s) safely.")


# ---------------------------------------------------------------------------
# Sidebar Page & Settings UI
# ---------------------------------------------------------------------------

def build_page(arckad, box):
    Gtk = arckad.Gtk

    title = Gtk.Label(xalign=0)
    title.set_markup("<span size='x-large' weight='bold'>🛡️ Antivirus &amp; Threat Center</span>")
    box.pack_start(title, False, False, 6)

    engine = "ClamAV + Heuristics" if shutil.which("clamscan") else "Windows Defender / Heuristics"
    status_lbl = Gtk.Label(label=f"Active Engine: {engine}", xalign=0)
    status_lbl.get_style_context().add_class("dim-label")
    box.pack_start(status_lbl, False, False, 4)

    btn_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
    scan_btn = Gtk.Button(label="Scan Open Folder")
    scan_btn.get_style_context().add_class("suggested-action")
    scan_btn.connect("clicked", lambda *_: scan_current_folder(arckad))

    test_btn = Gtk.Button(label="Test Center Threat Popup")
    test_btn.connect(
        "clicked",
        lambda *_: show_center_threat_dialog(
            arckad,
            [{"path": "/tmp/sample_invoice.pdf.exe", "threat": "EICAR-Test-Signature", "engine": "Test Mode"}],
        ),
    )

    btn_row.pack_start(scan_btn, False, False, 0)
    btn_row.pack_start(test_btn, False, False, 0)
    box.pack_start(btn_row, False, False, 8)


def build_settings(arckad, box):
    Gtk = arckad.Gtk

    chk_dl = Gtk.CheckButton(label="Automatically scan downloaded files")
    chk_dl.set_active(bool(arckad.config.get("auto_scan_downloads", True)))

    save_btn = Gtk.Button(label="Save Settings")
    save_btn.get_style_context().add_class("suggested-action")

    def _save(_btn):
        arckad.config["auto_scan_downloads"] = chk_dl.get_active()
        arckad.save_config()
        arckad.notify("Antivirus settings saved.")

    save_btn.connect("clicked", _save)
    box.pack_start(chk_dl, False, False, 6)
    box.pack_start(save_btn, False, False, 6)
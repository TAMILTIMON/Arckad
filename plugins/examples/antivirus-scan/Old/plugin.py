"""Antivirus scan: right-click a file or folder to scan it with whatever antivirus is already on the PC.

Windows: Windows Defender's own command-line scanner (MpCmdRun.exe), already built into Windows — nothing to
install. Linux: ClamAV's clamscan, if it's installed (sudo apt install clamav, then sudo freshclam once to get
virus definitions).
"""
import glob
import os
import shutil
import subprocess
import sys


def setup(arckad):
    arckad.add_file_action("🛡 Scan for viruses", scan_selected, icon="🛡")
    arckad.add_tool("Scan this folder for viruses", scan_current_folder, icon="🛡")
    arckad.add_settings(build_settings)
    if arckad.config.get("scan_downloads"):
        arckad.on("download_finished", scan_download)


# ---------- finding the scanner ----------
def _defender_path():
    bases = [os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Windows Defender"),
             os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "Microsoft", "Windows Defender",
                          "Platform", "*")]
    found = []
    for base in bases:
        found += glob.glob(os.path.join(base, "MpCmdRun.exe"))
    return sorted(found, reverse=True)[0] if found else None     # the newest Platform version, if several


def find_scanner():
    if sys.platform == "win32":
        exe = _defender_path()
        return ("defender", exe) if exe else (None, None)
    exe = shutil.which("clamscan")
    return ("clamav", exe) if exe else (None, None)


# ---------- running it ----------
def _run_defender(exe, path):
    r = subprocess.run([exe, "-Scan", "-ScanType", "3", "-File", path, "-DisableRemediation"],
                       capture_output=True, text=True, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (r.stdout or "") + (r.stderr or "")
    threats = [ln.strip() for ln in out.splitlines() if "threat" in ln.lower() and ":" in ln]
    return r.returncode == 0, threats, out


def _run_clamav(exe, path):
    r = subprocess.run([exe, "-r", "--no-summary", path], capture_output=True, text=True, timeout=1800)
    out = (r.stdout or "") + (r.stderr or "")
    threats = [ln.strip() for ln in out.splitlines() if ln.strip().endswith("FOUND")]
    return r.returncode in (0, 1), threats, out        # clamscan: 1 = finished, found something


def scan_paths(arckad, paths, quiet=False):
    kind, exe = find_scanner()
    if not exe:
        if quiet:
            return arckad.log("no scanner installed; skipped the automatic scan")
        return offer_install(arckad, lambda: scan_paths(arckad, paths, quiet))
    if not quiet:
        arckad.notify(f"🛡 Scanning {len(paths)} item{'s' if len(paths) != 1 else ''}…")

    def work():
        all_threats, problems = [], []
        for p in paths:
            try:
                ran, threats = (lambda t: (t[0], t[1]))(_run_defender(exe, p) if kind == "defender"
                                                        else _run_clamav(exe, p))
                if not ran:
                    problems.append(p)
                all_threats += threats
            except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as ex:
                arckad.log("scan failed for", p, ":", ex)
                problems.append(p)
        return all_threats, problems

    def done(result):
        threats, problems = result
        if threats:
            arckad.error("⚠ Possible threats found:\n\n" + "\n".join(threats[:15]) +
                         ("\n\n(and more)" if len(threats) > 15 else ""))
        elif quiet:
            pass                                               # a clean automatic scan stays quiet
        elif problems:
            arckad.notify(f"🛡 Scanned, but {len(problems)} item(s) couldn't be checked (see the plugin log).")
        else:
            arckad.notify("🛡 No threats found.")
    arckad.run_in_background(work, done)


def scan_selected(arckad, paths):
    scan_paths(arckad, paths)


def scan_current_folder(arckad):
    folder = arckad.current_folder()
    if not folder:
        return arckad.error("Open a folder first.")
    scan_paths(arckad, [folder])


def scan_download(arckad, path):
    if os.path.exists(path):
        scan_paths(arckad, [path], quiet=True)


def offer_install(arckad, then):
    """No scanner found: install it with one password prompt, the same way Arckad-D installs its own optional
    features, then run the scan that was waiting on it."""
    if sys.platform == "win32":
        return arckad.error("Windows Defender wasn't found on this PC (it may be turned off in Windows Security).")
    arckad.install_system_software(
        "ClamAV", "It checks files for known viruses. (After installing, Arckad-D also needs the virus database — "
                  "run “sudo freshclam” once in a terminal, the first time only.)",
        linux_packages=["clamav"], done=lambda ok, msg: ok and then())


def build_settings(arckad, box):
    Gtk = arckad.Gtk
    kind, exe = find_scanner()
    box.add(Gtk.Label(label="Antivirus scan", xalign=0))
    status = Gtk.Label(xalign=0, wrap=True)
    status.set_markup(f"Using: <b>{'Windows Defender' if kind == 'defender' else 'ClamAV' if kind == 'clamav' else 'not found'}</b>"
                      + (f"\n<small>{exe}</small>" if exe else
                         "\n<small>Install ClamAV, or make sure Windows Defender is on.</small>"))
    box.add(status)
    if not exe and sys.platform != "win32":
        install_btn = Gtk.Button(label="⬇ Install ClamAV…")
        install_btn.connect("clicked", lambda *_: offer_install(arckad, lambda: None))
        box.add(install_btn)
    auto = Gtk.CheckButton(label="Automatically scan every download")
    auto.set_active(bool(arckad.config.get("scan_downloads")))

    def toggled(b):
        arckad.config["scan_downloads"] = b.get_active()
        arckad.save_config()
        arckad.notify("This takes effect the next time Arckad-D starts.")
    auto.connect("toggled", toggled)
    box.add(auto)

# Writing plugins for Arckad-D

A plugin adds a feature to Arckad-D: an item in the right-click menu, a tool, a page of its own, a preview for a
file type, or something that happens by itself. Plugins work on Ubuntu and Windows, and you don't need anything
special to write one: a text editor is enough.

## 1. A plugin is a folder

```
invoice-renamer/
├── plugin.json     what the plugin is (required)
├── plugin.py       what it does (required)
├── icon.png        its picture in the Plugins window (optional, square, e.g. 128×128)
└── plugin.sig      the owner's signature (added when the owner signs it)
```

Quickest start: in Arckad-D open **☰ → Plugins → Create a plugin…**, or run `arckad-d --new-plugin my-plugin`.
You can also copy [`plugins/template`](plugins/template).

## 2. plugin.json

```json
{
  "id": "invoice-renamer",
  "name": "Invoice renamer",
  "version": "1.0.0",
  "author": "Your name",
  "description": "Renames invoice PDFs to Date - Company - Amount.pdf",
  "arckad": ">=3.65",
  "platforms": ["linux", "windows"],
  "api": 1
}
```

| Field | Meaning |
|---|---|
| `id` | Unique name: small letters, digits and `-` (2–41 characters). Never change it after publishing. |
| `name` | What people see. |
| `version` | `1.0`, `1.2.3`… Raise it for every update (the catalogue offers updates when it's higher). |
| `author`, `description` | Shown in the Plugins window and the catalogue. |
| `arckad` | Which Arckad-D versions it works with: `>=3.65`, `>=3.65,<4`, `==3.65.0`. |
| `platforms` | `linux`, `windows`, or both. |
| `api` | The plugin API it was written for (now `1`). |

## 3. plugin.py

It needs one function, `setup(arckad)`, which runs when Arckad-D starts (or when the plugin is switched on).
In it, the plugin says **where it appears**. Everything goes through the `arckad` object: plugins never use
Arckad-D's own code, so Arckad-D updates don't break them.

```python
def setup(arckad):
    arckad.add_file_action("Rename as invoice", rename_invoices,
                           when=lambda paths: all(p.lower().endswith(".pdf") for p in paths))


def rename_invoices(arckad, paths):
    for p in paths:
        arckad.rename(p, "2026-11-25 - Acme - 1200.pdf")     # your own logic here
    arckad.notify(f"Renamed {len(paths)} invoices")
```

### Where a plugin can appear

| Call | Where it shows | Your function gets |
|---|---|---|
| `arckad.add_file_action(label, run, when=None, icon="🧩")` | Right-click menu, in the plugins group. `when(paths)` decides if it shows. | `run(arckad, paths)` |
| `arckad.add_tool(label, run, icon="🧩")` | Tools → 🧩 Plugins, and the command palette (Ctrl+K) | `run(arckad)` |
| `arckad.add_page(title, build, icon="🧩")` | Its own page; the sidebar lists it under **PLUGINS** | `build(arckad, box)`: add widgets to the `Gtk.Box` (runs each time the page opens) |
| `arckad.add_preview(["dwg", "dxf"], build)` | The preview panel, for those file types | `build(arckad, path)` → return a Gtk widget |
| `arckad.add_settings(build)` | A **Settings** button in the Plugins window | `build(arckad, box)`; keep values in `arckad.config` |
| `arckad.on(event, fn)` | Nowhere: it runs by itself | see the events below |

Events: `startup`, `folder_opened(path)`, `download_finished(path)`, `files_trashed(paths)`, `drive_added(path)`.
Each `fn` gets `arckad` first, e.g. `def saved(arckad, path): …`.

### What a plugin can ask Arckad-D to do

| Call | Does |
|---|---|
| `arckad.notify(text)` / `arckad.error(text)` | A message in Arckad-D / an error box |
| `arckad.ask(title, prompt, default="")` | Asks for a line of text (`None` if cancelled) |
| `arckad.confirm(text)` | Yes / no |
| `arckad.selected_paths()` / `arckad.current_folder()` | What's selected / the open folder |
| `arckad.open_folder(path, select=None)` | Shows a folder (and selects files in it) |
| `arckad.rename(path, new_name)` | Renames, keeping the file's history and tags; returns the new path |
| `arckad.make_folder(path)` | Makes a folder (and any missing parents) |
| `arckad.copy_to(paths, folder)` / `arckad.move_to(paths, folder)` | Copies / moves, like Ctrl+C / Ctrl+X then Ctrl+V |
| `arckad.refresh()` | Re-reads the folders on screen |
| `arckad.run_in_background(work, done=None)` | `work()` off the main thread, then `done(result)` back on it (for slow jobs) |
| `arckad.install_system_software(label, reason, win_id=None, linux_packages=None, done=None)` | Installs something your plugin needs, using the PC's own installer — the same mechanism Arckad-D uses for its own optional features (winget on Windows, apt via one password prompt on Linux). Always asks first, never silent. `done(ok, msg)` runs when it finishes. |
| `arckad.config` / `arckad.save_config()` | The plugin's own settings (a dict, saved for it) |
| `arckad.data_dir` | A folder where the plugin may keep its own files |
| `arckad.play(name)` | One of Arckad-D's animations: `new_folder`, `zip`, `plane`, `download`… |
| `arckad.log(...)` | Writes to the plugin's log (`plugin.log` in its data folder) |
| `arckad.Gtk`, `arckad.Gdk`, `arckad.GLib`, `arckad.Pango` | GTK, for building pages, previews and settings |
| `arckad.platform`, `arckad.version`, `arckad.id`, `arckad.name` | `linux`/`windows`, Arckad-D's version, the plugin's id and name |

Build pages with plain GTK widgets (labels, buttons, lists, entries): they take the user's theme automatically.

## 4. Safety

* Everything a plugin does runs **guarded**: if it raises an error, the user sees a short message and the details
  go to the plugin's log. After three errors the plugin is switched off. Arckad-D itself keeps working.
* **Owner-signed plugins (✓)** install with one click, from the catalogue or a file. Signing proves the plugin is
  exactly what the owner checked: changing any file breaks the signature.
* **Community plugins** (not signed) only run when the user switches on *Allow community plugins*, after a warning.
  A plugin runs with the user's permissions, so only install plugins from people you trust.

## 5. Try, check, share

1. **Try it:** ☰ → Plugins → tick **Developer mode** and choose the folder that holds your plugin folders.
   Arckad-D loads them from there (switch it off and on in the list to reload after edits).
2. **Check it:** ☰ → Plugins → **Check a plugin…**, or `arckad-d --check-plugin my-plugin`. It lists any problems and
   what the plugin adds.
3. **Share it:** send the folder (zipped) to the owner. Once checked, the owner signs it
   (`arckad-d --sign-plugin my-plugin`, on the owner's PC only), which makes `my-plugin-1.0.0.zip` and a catalogue
   entry. Putting the zip in `plugins/` and the entry in `plugins/catalog.json` publishes it to everyone.
   Users can also install a zip directly: ☰ → Plugins → **Install from a file…**

## 6. The catalogue

`plugins/catalog.json` in the Arckad-D repository:

```json
{
  "format": 1,
  "plugins": [
    {
      "id": "invoice-renamer", "name": "Invoice renamer", "version": "1.0.0", "author": "TAMILTIMON",
      "description": "Renames invoice PDFs to Date - Company - Amount.pdf",
      "arckad": ">=3.65", "platforms": ["linux", "windows"],
      "download": "https://raw.githubusercontent.com/TAMILTIMON/Arckad/main/plugins/invoice-renamer-1.0.0.zip"
    }
  ]
}
```

Arckad-D installs from the catalogue only plugins signed by the owner, and offers an **Update** when a newer
version appears. No new Arckad-D release is needed to publish or update a plugin.

"""My plugin for Arckad-D. The format is explained in PLUGINS.md."""


def setup(arckad):
    # 1. a right-click item, only for PDF files
    arckad.add_file_action("Count the selected PDFs", count_pdfs,
                           when=lambda paths: all(p.lower().endswith(".pdf") for p in paths))
    # 2. a Tools menu item (also in the command palette, Ctrl+K)
    arckad.add_tool("Say hello", say_hello)
    # 3. its own page, in the sidebar under PLUGINS
    arckad.add_page("My plugin", build_page)
    # 4. something that happens by itself
    arckad.on("download_finished", lambda arckad, path: arckad.log("downloaded", path))


def count_pdfs(arckad, paths):
    arckad.notify(f"{len(paths)} PDF file(s) selected")


def say_hello(arckad):
    name = arckad.ask("Hello", "What's your name?", "")
    if name:
        arckad.notify(f"Hello, {name}!")


def build_page(arckad, box):
    Gtk = arckad.Gtk
    box.add(Gtk.Label(label="This page belongs to My plugin.", xalign=0))
    button = Gtk.Button(label="Show the current folder")
    button.connect("clicked", lambda *_: arckad.notify(arckad.current_folder() or "no folder"))
    box.add(button)

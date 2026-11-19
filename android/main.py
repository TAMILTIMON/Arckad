"""
Arckad-D for Android.
Files · Recent ("Where was I?") · Send · Receive — works with Arckad-D on Linux and Windows.
"""
__version__ = "3.7.0"          # GitHub replaces this with APP_VERSION from arckad-d.py when it builds

import os
import secrets
import threading
import time
from datetime import date

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.graphics.texture import Texture
from kivy.lang import Builder
from kivy.metrics import dp, sp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.modalview import ModalView
from kivy.uix.progressbar import ProgressBar
from kivy.uix.recycleview import RecycleView
from kivy.uix.recycleview.views import RecycleDataViewBehavior
from kivy.uix.screenmanager import NoTransition, Screen, ScreenManager
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.switch import Switch
from kivy.uix.textinput import TextInput
from kivy.utils import escape_markup, platform

import arckad_core as core

HERE = os.path.dirname(os.path.abspath(__file__))
ICON_FONT = os.path.join(HERE, "fonts", "materialdesignicons-webfont.ttf")
I = {k: chr(v) for k, v in {
    "folder": 0xF024B, "file": 0xF0224, "Images": 0xF021F, "Videos": 0xF022B, "Audio": 0xF0223,
    "pdf": 0xF0226, "Archives": 0xF06EB, "Apps": 0xF0032, "Code": 0xF022E, "Documents": 0xF0219,
    "Spreadsheets": 0xF021B, "Presentations": 0xF0227, "back": 0xF004D, "search": 0xF0349,
    "menu": 0xF01D9, "night": 0xF0594, "sun": 0xF05A8, "send": 0xF048A, "receive": 0xF01DA,
    "recent": 0xF02DA, "check": 0xF0133, "uncheck": 0xF0130, "close": 0xF0156, "share": 0xF0497,
    "delete": 0xF01B4, "rename": 0xF03EB, "copy": 0xF018F, "cut": 0xF0190, "paste": 0xF0192,
    "open": 0xF03CC, "up": 0xF005D, "grid": 0xF0570, "list": 0xF0572, "phone": 0xF011C,
    "laptop": 0xF0322, "monitor": 0xF0379, "qr": 0xF0432, "files": 0xF0770, "home": 0xF02DC,
    "info": 0xF02FD, "theme": 0xF050E, "wifi": 0xF05A9, "selectall": 0xF0486, "refresh": 0xF0450,
}.items()}

THEMES = {
    "light": dict(bg=(0.965, 0.961, 0.957, 1), card=(1, 1, 1, 1), text=(0.11, 0.11, 0.12, 1),
                  muted=(0.42, 0.42, 0.45, 1), accent=(0.36, 0.36, 0.84, 1), line=(0.88, 0.88, 0.87, 1),
                  bar=(1, 1, 1, 1), sel=(0.36, 0.36, 0.84, 0.16)),
    "dark": dict(bg=(0.10, 0.10, 0.11, 1), card=(0.16, 0.16, 0.17, 1), text=(0.95, 0.95, 0.96, 1),
                 muted=(0.64, 0.64, 0.68, 1), accent=(0.56, 0.56, 1, 1), line=(0.24, 0.24, 0.26, 1),
                 bar=(0.13, 0.13, 0.14, 1), sel=(0.56, 0.56, 1, 0.20)),
}

# ---------------------------------------------------------------- Android bridges
if platform == "android":
    from jnius import autoclass, cast
    from android.permissions import Permission, request_permissions   # noqa: F401
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Intent = autoclass("android.content.Intent")
    Uri = autoclass("android.net.Uri")
    JFile = autoclass("java.io.File")
    Build = autoclass("android.os.Build")
    VERSION = autoclass("android.os.Build$VERSION")
    Environment = autoclass("android.os.Environment")
    Settings = autoclass("android.provider.Settings")
    StrictMode = autoclass("android.os.StrictMode")
    VmPolicyBuilder = autoclass("android.os.StrictMode$VmPolicy$Builder")
    StrictMode.setVmPolicy(VmPolicyBuilder().build())      # lets other apps open our file:// links


def activity():
    return PythonActivity.mActivity


def has_storage_access():
    if platform != "android":
        return True
    if VERSION.SDK_INT >= 30:
        return bool(Environment.isExternalStorageManager())
    from android.permissions import check_permission
    return check_permission(Permission.WRITE_EXTERNAL_STORAGE)


def ask_storage_access():
    if platform != "android":
        return
    if VERSION.SDK_INT >= 30:
        try:
            intent = Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION,
                            Uri.parse("package:" + activity().getPackageName()))
            activity().startActivity(intent)
        except Exception:
            activity().startActivity(Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION))
    else:
        request_permissions([Permission.READ_EXTERNAL_STORAGE, Permission.WRITE_EXTERNAL_STORAGE])


def device_name():
    if platform == "android":
        try:
            name = Settings.Global.getString(activity().getContentResolver(), "device_name")
            if name:
                return name
        except Exception:
            pass
        return str(Build.MODEL)
    import socket
    return socket.gethostname()


def system_dark():
    if platform == "android":
        try:
            return (activity().getResources().getConfiguration().uiMode & 0x30) == 0x20
        except Exception:
            return False
    return False


def open_with(path):
    if platform != "android":
        import subprocess
        subprocess.Popen(["xdg-open", path])
        return
    import mimetypes
    mime = mimetypes.guess_type(path)[0] or "*/*"
    intent = Intent(Intent.ACTION_VIEW)
    intent.setDataAndType(Uri.fromFile(JFile(path)), mime)
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK)
    activity().startActivity(Intent.createChooser(intent, "Open with"))


def share_files(paths):
    if platform != "android" or not paths:
        return
    ArrayList = autoclass("java.util.ArrayList")
    uris = ArrayList()
    for p in paths:
        uris.add(Uri.fromFile(JFile(p)))
    intent = Intent(Intent.ACTION_SEND_MULTIPLE)
    intent.setType("*/*")
    intent.putParcelableArrayListExtra(Intent.EXTRA_STREAM, uris)
    intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    activity().startActivity(Intent.createChooser(intent, "Share"))


def media_scan(paths):
    if platform != "android":
        return
    try:
        Scanner = autoclass("android.media.MediaScannerConnection")
        Scanner.scanFile(activity(), [str(p) for p in paths], None, None)
    except Exception:
        pass


class MulticastLock:
    """Android drops Wi-Fi broadcast packets unless an app holds this lock."""
    lock = None

    @classmethod
    def acquire(cls):
        if platform != "android" or cls.lock:
            return
        try:
            Context = autoclass("android.content.Context")
            wm = cast("android.net.wifi.WifiManager", activity().getSystemService(Context.WIFI_SERVICE))
            cls.lock = wm.createMulticastLock("arckad-d")
            cls.lock.setReferenceCounted(False)
            cls.lock.acquire()
        except Exception:
            cls.lock = None

    @classmethod
    def release(cls):
        if cls.lock:
            try:
                cls.lock.release()
            except Exception:
                pass
            cls.lock = None


def tamil_font():
    for p in ("/system/fonts/NotoSansTamil-Regular.ttf", "/system/fonts/NotoSansTamilUI-Regular.ttf",
              "/system/fonts/NotoSansTamil-VF.ttf", "/system/fonts/NotoSansTamilUI-VF.ttf",
              "/usr/share/fonts/truetype/noto/NotoSansTamil-Regular.ttf"):
        if os.path.exists(p):
            return p
    return None


TAMIL_FONT = tamil_font()


def rich(text):
    """Markup that shows Tamil letters in a Tamil font (Kivy's default font has none)."""
    out, run, in_tamil = [], [], False
    for ch in text + "\0":
        tamil = "\u0B80" <= ch <= "\u0BFF"
        if (tamil != in_tamil or ch == "\0") and run:
            piece = escape_markup("".join(run))
            out.append(f"[font={TAMIL_FONT}]{piece}[/font]" if in_tamil and TAMIL_FONT else piece)
            run = []
        in_tamil = tamil
        if ch != "\0":
            run.append(ch)
    return "".join(out)


def icon_for(e):
    if e["is_dir"]:
        return I["folder"]
    if core.ext_of(e["name"]) == "pdf":
        return I["pdf"]
    return I.get(e["kind"], I["file"])


# ---------------------------------------------------------------- reusable widgets
KV = """
#:import dp kivy.metrics.dp
#:import sp kivy.metrics.sp

<Lbl@Label>:
    color: app.c_text
    font_size: sp(15)
    halign: "left"
    valign: "middle"
    text_size: self.width, None
    size_hint_y: None
    height: self.texture_size[1] + dp(4)
    markup: True

<Muted@Lbl>:
    color: app.c_muted
    font_size: sp(13)

<Heading@Lbl>:
    font_size: sp(17)
    bold: True

<IconButton>:
    font_name: app.icon_font
    font_size: sp(24)
    color: app.c_text
    size_hint: None, None
    size: dp(46), dp(46)
    canvas.before:
        Color:
            rgba: app.c_sel if self.state == "down" else (0, 0, 0, 0)
        Ellipse:
            pos: self.pos
            size: self.size

<Btn>:
    color: (1, 1, 1, 1) if self.primary else app.c_text
    font_size: sp(15)
    bold: self.primary
    size_hint_y: None
    height: dp(46)
    padding: dp(16), 0
    canvas.before:
        Color:
            rgba: (app.c_accent if self.primary else app.c_line) if self.state == "normal" else app.c_muted
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(12)]

<Card>:
    orientation: "vertical"
    size_hint_y: None
    height: self.minimum_height
    padding: dp(14)
    spacing: dp(8)
    canvas.before:
        Color:
            rgba: app.c_card
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(14)]

<Input@TextInput>:
    size_hint_y: None
    height: dp(46)
    multiline: False
    font_size: sp(15)
    padding: dp(12), dp(12)
    background_normal: ""
    background_active: ""
    background_color: app.c_card
    foreground_color: app.c_text
    hint_text_color: app.c_muted
    cursor_color: app.c_accent

<FileRow>:
    size_hint_y: None
    height: dp(64)
    padding: dp(14), dp(6)
    spacing: dp(14)
    canvas.before:
        Color:
            rgba: app.c_sel if self.selected else (0, 0, 0, 0)
        Rectangle:
            pos: self.pos
            size: self.size
        Color:
            rgba: app.c_line
        Rectangle:
            pos: self.x + dp(72), self.y
            size: self.width - dp(72), dp(1)
    RelativeLayout:
        size_hint: None, None
        size: dp(44), dp(44)
        pos_hint: {"center_y": .5}
        Label:
            text: root.icon
            font_name: app.icon_font
            font_size: sp(30)
            color: app.c_accent if root.is_dir else app.c_muted
            opacity: 0 if root.thumb else 1
        Image:
            source: root.thumb
            opacity: 1 if root.thumb else 0
            fit_mode: "cover"
    BoxLayout:
        orientation: "vertical"
        padding: 0, dp(6)
        Label:
            text: root.name
            markup: True
            color: app.c_text
            font_size: sp(15)
            halign: "left"
            valign: "middle"
            text_size: self.size
            shorten: True
            shorten_from: "center"
        Label:
            text: root.sub
            color: app.c_muted
            font_size: sp(12)
            halign: "left"
            valign: "middle"
            text_size: self.size
            shorten: True
    Label:
        size_hint_x: None
        width: dp(30) if app.select_mode else 0
        opacity: 1 if app.select_mode else 0
        text: app.icons["check"] if root.selected else app.icons["uncheck"]
        font_name: app.icon_font
        font_size: sp(22)
        color: app.c_accent if root.selected else app.c_muted

<FileTile>:
    orientation: "vertical"
    size_hint_y: None
    height: dp(150)
    padding: dp(6)
    spacing: dp(4)
    canvas.before:
        Color:
            rgba: app.c_sel if self.selected else (0, 0, 0, 0)
        RoundedRectangle:
            pos: self.pos
            size: self.size
            radius: [dp(10)]
    RelativeLayout:
        Label:
            text: root.icon
            font_name: app.icon_font
            font_size: sp(48)
            color: app.c_accent if root.is_dir else app.c_muted
            opacity: 0 if root.thumb else 1
        Image:
            source: root.thumb
            opacity: 1 if root.thumb else 0
            fit_mode: "cover"
        Label:
            text: app.icons["check"] if root.selected else ""
            font_name: app.icon_font
            font_size: sp(22)
            color: app.c_accent
            size_hint: None, None
            size: dp(26), dp(26)
            pos_hint: {"right": 1, "top": 1}
    Label:
        text: root.name
        markup: True
        color: app.c_text
        font_size: sp(12)
        size_hint_y: None
        height: dp(34)
        halign: "center"
        valign: "top"
        text_size: self.width, self.height
        shorten: True
        shorten_from: "center"
        max_lines: 2

<HeaderRow>:
    size_hint_y: None
    height: dp(40)
    padding: dp(16), 0
    Label:
        text: root.name
        bold: True
        color: app.c_accent
        font_size: sp(14)
        halign: "left"
        valign: "middle"
        text_size: self.size

<NavButton>:
    orientation: "vertical"
    padding: 0, dp(6)
    Label:
        text: root.icon
        font_name: app.icon_font
        font_size: sp(24)
        color: app.c_accent if root.active else app.c_muted
    Label:
        text: root.text
        font_size: sp(12)
        bold: root.active
        color: app.c_accent if root.active else app.c_muted
        size_hint_y: None
        height: dp(18)
"""


class IconButton(ButtonBehavior, Label):
    pass


class Btn(ButtonBehavior, Label):
    primary = BooleanProperty(False)


class Card(BoxLayout):
    pass


class NavButton(ButtonBehavior, BoxLayout):
    icon = StringProperty("")
    text = StringProperty("")
    active = BooleanProperty(False)


def bg(widget, attr="c_bg"):
    """Paints a widget's background with a theme colour that follows light/dark changes."""
    app = App.get_running_app()
    with widget.canvas.before:
        col = Color(rgba=getattr(app, attr))
        rect = Rectangle(pos=widget.pos, size=widget.size)
    widget.bind(pos=lambda w, v: setattr(rect, "pos", v), size=lambda w, v: setattr(rect, "size", v))
    app.bind(**{attr: lambda a, v: setattr(col, "rgba", v)})


class LongPressMixin:
    """Tap = open, long-press = select (like the Files app on phones)."""
    _lp_event = None
    _lp_fired = False

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos) and not touch.is_mouse_scrolling:
            self._lp_fired = False
            self._lp_touch = touch
            self._lp_event = Clock.schedule_once(lambda dt: self._long(), 0.5)
            touch.ud[f"lp{id(self)}"] = True
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if touch.ud.get(f"lp{id(self)}") and (abs(touch.dx) > dp(6) or abs(touch.dy) > dp(6)):
            self._cancel_lp()
            touch.ud[f"lp{id(self)}"] = False
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch.ud.get(f"lp{id(self)}") and self.collide_point(*touch.pos):
            self._cancel_lp()
            if not self._lp_fired:
                App.get_running_app().on_item_tap(self.index)
            return True
        self._cancel_lp()
        return super().on_touch_up(touch)

    def _cancel_lp(self):
        if self._lp_event:
            self._lp_event.cancel()
            self._lp_event = None

    def _long(self):
        self._lp_event = None
        self._lp_fired = True
        App.get_running_app().on_item_long(self.index)


class FileView(RecycleDataViewBehavior):
    index = NumericProperty(0)
    path = StringProperty("")
    name = StringProperty("")
    sub = StringProperty("")
    icon = StringProperty("")
    thumb = StringProperty("")
    is_dir = BooleanProperty(False)
    selected = BooleanProperty(False)

    def refresh_view_attrs(self, rv, index, data):
        self.index = index
        return super().refresh_view_attrs(rv, index, data)


class FileRow(LongPressMixin, FileView, BoxLayout):
    pass


class FileTile(LongPressMixin, FileView, BoxLayout):
    pass


class HeaderRow(RecycleDataViewBehavior, BoxLayout):
    index = NumericProperty(0)
    name = StringProperty("")
    path = StringProperty("")
    sub = StringProperty("")
    icon = StringProperty("")
    thumb = StringProperty("")
    is_dir = BooleanProperty(False)
    selected = BooleanProperty(False)


def make_rv(grid=False):
    rv = RecycleView(bar_width=dp(4), scroll_type=["bars", "content"])
    if grid:
        from kivy.uix.recyclegridlayout import RecycleGridLayout
        layout = RecycleGridLayout(cols=3, default_size=(None, dp(150)), default_size_hint=(1, None),
                                   size_hint_y=None, padding=dp(6), spacing=dp(6))
        rv.bind(width=lambda w, v: setattr(layout, "cols", max(3, int(v / dp(115)))))
    else:
        from kivy.uix.recycleboxlayout import RecycleBoxLayout
        layout = RecycleBoxLayout(orientation="vertical", default_size=(None, dp(64)),
                                  default_size_hint=(1, None), size_hint_y=None)
    layout.bind(minimum_height=layout.setter("height"))
    rv.add_widget(layout)
    rv.viewclass = "FileTile" if grid else "FileRow"
    return rv


def scroll_box(spacing=dp(12), padding=dp(14)):
    sv = ScrollView(do_scroll_x=False, bar_width=dp(4))
    box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=spacing, padding=padding)
    box.bind(minimum_height=box.setter("height"))
    sv.add_widget(box)
    return sv, box


def btn_row(*buttons):
    row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
    for b in buttons:
        row.add_widget(b)
    return row


# ---------------------------------------------------------------- screens
class FilesScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="files", **kw)
        self.app = app
        root = BoxLayout(orientation="vertical")
        bg(root)
        crumbs_sv = ScrollView(do_scroll_y=False, size_hint_y=None, height=dp(44), bar_width=0)
        self.crumbs = BoxLayout(size_hint_x=None, padding=(dp(8), 0), spacing=dp(2))
        self.crumbs.bind(minimum_width=self.crumbs.setter("width"))
        crumbs_sv.add_widget(self.crumbs)
        self.crumbs_sv = crumbs_sv
        root.add_widget(crumbs_sv)
        self.search_row = BoxLayout(size_hint_y=None, height=0, opacity=0, spacing=dp(8), padding=(dp(10), 0))
        self.search = TextInput(hint_text="Search here and in subfolders", multiline=False)
        self._style_input(self.search)
        self.search.bind(text=lambda *a: self.app.schedule_search())
        self.kind = Spinner(text="All types", values=core.KINDS, size_hint_x=None, width=dp(130))
        self.kind.bind(text=lambda *a: self.app.schedule_search())
        self.search_row.add_widget(self.search)
        self.search_row.add_widget(self.kind)
        root.add_widget(self.search_row)
        self.holder = BoxLayout()
        self.rv_list, self.rv_grid = make_rv(False), make_rv(True)
        self.holder.add_widget(self.rv_list)
        root.add_widget(self.holder)
        self.empty = Label(text="", color=app.c_muted, size_hint_y=None, height=0)
        app.bind(c_muted=lambda a, v: setattr(self.empty, "color", v))
        root.add_widget(self.empty)
        self.add_widget(root)

    @staticmethod
    def _style_input(ti):
        app = App.get_running_app()
        ti.size_hint_y, ti.height, ti.font_size = None, dp(44), sp(15)
        ti.padding = (dp(12), dp(12))
        ti.background_normal = ti.background_active = ""

        def paint(*_):
            ti.background_color, ti.foreground_color = app.c_card, app.c_text
            ti.hint_text_color, ti.cursor_color = app.c_muted, app.c_accent
        paint()
        app.bind(c_card=paint, c_text=paint)
        ti.pos_hint = {"center_y": .5}

    def current_rv(self):
        return self.rv_grid if self.app.grid else self.rv_list

    def set_grid(self, grid):
        self.holder.clear_widgets()
        self.holder.add_widget(self.rv_grid if grid else self.rv_list)

    def show_search(self, show):
        self.search_row.height = dp(56) if show else 0
        self.search_row.opacity = 1 if show else 0
        self.search_row.disabled = not show
        if show:
            Clock.schedule_once(lambda dt: setattr(self.search, "focus", True), 0.1)
        else:
            self.search.text = ""
            self.kind.text = "All types"

    def set_crumbs(self, path):
        self.crumbs.clear_widgets()
        root = core.storage_root()
        parts = [(core.short(root), root)]
        if path != root and path.startswith(root + os.sep):
            acc = root
            for piece in path[len(root) + 1:].split(os.sep):
                acc = os.path.join(acc, piece)
                parts.append((piece, acc))
        elif path != root:
            parts = [(path, path)]
        for i, (label, target) in enumerate(parts):
            if i:
                self.crumbs.add_widget(Label(text="›", color=self.app.c_muted, size_hint_x=None, width=dp(14)))
            b = Btn(text=rich(label), markup=True, size_hint_x=None, height=dp(34), pos_hint={"center_y": .5})
            b.bind(texture_size=lambda w, v: setattr(w, "width", v[0] + dp(24)))
            b.primary = i == len(parts) - 1
            b.bind(on_release=lambda _b, t=target: self.app.open_folder(t))
            self.crumbs.add_widget(b)
        Clock.schedule_once(lambda dt: setattr(self.crumbs_sv, "scroll_x", 1), 0.05)


class PreviewScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="preview", **kw)
        self.app = app
        self.sv, self.box = scroll_box()
        bg(self.sv)
        self.add_widget(self.sv)

    def show(self, e):
        app, box = self.app, self.box
        box.clear_widgets()
        path = e["path"]
        if e["kind"] == "Images":
            img = Image(source=path, size_hint_y=None, height=dp(320), fit_mode="contain")
            box.add_widget(img)
        else:
            text = None
            if core.ext_of(path) in core.TEXT_EXTS:
                try:
                    text = core.read_text(path)
                except OSError:
                    text = None
            if text is not None:
                card = Card()
                lbl = Label(text=escape_markup(text[:20000]), markup=True, color=app.c_text, font_size=sp(12),
                            size_hint_y=None, halign="left", valign="top", font_name="RobotoMono-Regular")
                lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                         texture_size=lambda w, v: setattr(w, "height", min(v[1], dp(4000))))
                card.add_widget(lbl)
                box.add_widget(card)
            else:
                box.add_widget(Label(text=icon_for(e), font_name=ICON_FONT, font_size=sp(96),
                                     color=app.c_accent, size_hint_y=None, height=dp(150)))
        info = Card()
        info.add_widget(self._title(e["name"]))
        lines = [f"Type: {e['kind']}", f"Size: {core.human_size(e['size'])}",
                 f"Modified: {core.fmt_time(e['mtime'])} ({core.ago(e['mtime'])})",
                 f"Folder: {core.short(os.path.dirname(path))}"]
        for line in lines:
            info.add_widget(self._muted(line))
        box.add_widget(info)
        b1, b2 = Btn(text="Open with…", primary=True), Btn(text="Share")
        b1.bind(on_release=lambda *_: app.safe(open_with, path))
        b2.bind(on_release=lambda *_: app.safe(share_files, [path]))
        box.add_widget(btn_row(b1, b2))
        b3, b4, b5 = Btn(text="Send nearby"), Btn(text="Rename"), Btn(text="Delete")
        b3.bind(on_release=lambda *_: app.send_paths([path]))
        b4.bind(on_release=lambda *_: app.rename(path))
        b5.bind(on_release=lambda *_: app.delete([path], back=True))
        box.add_widget(btn_row(b3, b4, b5))
        self.sv.scroll_y = 1

    def _title(self, text):
        lbl = Label(text=rich(text), markup=True, bold=True, font_size=sp(17), color=self.app.c_text,
                    size_hint_y=None, halign="left")
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                 texture_size=lambda w, v: setattr(w, "height", v[1]))
        return lbl

    def _muted(self, text):
        lbl = Label(text=rich(text), markup=True, font_size=sp(13), color=self.app.c_muted,
                    size_hint_y=None, halign="left")
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                 texture_size=lambda w, v: setattr(w, "height", v[1] + dp(2)))
        return lbl


class RecentScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="recent", **kw)
        self.app = app
        root = BoxLayout(orientation="vertical", spacing=dp(8))
        bg(root)
        self.banner = Card(padding=dp(16))
        self.banner_title = Label(text="Looking for your latest work…", markup=True, bold=True,
                                  font_size=sp(16), size_hint_y=None, halign="left")
        self.banner_sub = Label(text="", markup=True, font_size=sp(13), size_hint_y=None, halign="left")
        for lbl, attr in ((self.banner_title, "c_text"), (self.banner_sub, "c_muted")):
            lbl.color = getattr(app, attr)
            app.bind(**{attr: lambda a, v, l=lbl: setattr(l, "color", v)})
            lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                     texture_size=lambda w, v: setattr(w, "height", v[1] + dp(2)))
            self.banner.add_widget(lbl)
        self.banner_btn = Btn(text="Open it", primary=True)
        self.banner_btn.bind(on_release=lambda *_: app.open_last())
        self.banner.add_widget(self.banner_btn)
        wrap = BoxLayout(size_hint_y=None, padding=(dp(12), dp(10), dp(12), 0))
        wrap.add_widget(self.banner)
        self.banner.bind(height=lambda w, v: setattr(wrap, "height", v + dp(10)))
        root.add_widget(wrap)
        self.rv = make_rv(False)
        root.add_widget(self.rv)
        self.add_widget(root)


class SendScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="send", **kw)
        self.app = app
        self.sv, box = scroll_box()
        bg(self.sv)
        self.add_widget(self.sv)
        self.files_card = Card()
        box.add_widget(self.files_card)
        devices = Card()
        devices.add_widget(self._lbl("[b]Send to nearby Arckad-D[/b]", 16))
        devices.add_widget(self._lbl("Phones and computers running Arckad-D on this Wi-Fi with "
                                     "[b]Receive[/b] turned on appear here.", 13, muted=True))
        self.peers_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.peers_box.bind(minimum_height=self.peers_box.setter("height"))
        devices.add_widget(self.peers_box)
        self.progress = ProgressBar(max=1, value=0, size_hint_y=None, height=0, opacity=0)
        devices.add_widget(self.progress)
        self.progress_lbl = self._lbl("", 13, muted=True)
        devices.add_widget(self.progress_lbl)
        box.add_widget(devices)
        link = Card()
        link.add_widget(self._lbl("[b]Share as a link[/b]  (any phone or browser)", 16))
        row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        self.link_minutes = Spinner(text="10 min", values=[f"{m} min" for m in core.SHARE_MINUTES],
                                    size_hint_x=None, width=dp(100))
        self.link_state = self._lbl("Off", 14, muted=True)
        row.add_widget(self.link_state)
        row.add_widget(self.link_minutes)
        self.link_switch = Switch(size_hint_x=None, width=dp(84))
        self.link_switch.bind(active=lambda w, v: app.toggle_link(v))
        row.add_widget(self.link_switch)
        link.add_widget(row)
        self.qr = Image(size_hint_y=None, height=0, opacity=0, fit_mode="contain")
        link.add_widget(self.qr)
        self.url_lbl = self._lbl("", 14)
        link.add_widget(self.url_lbl)
        self.copy_btn = Btn(text="Copy link", opacity=0, disabled=True)
        self.copy_btn.bind(on_release=lambda *_: app.copy_link())
        link.add_widget(self.copy_btn)
        box.add_widget(link)
        self.refresh_files()

    def _lbl(self, text, size, muted=False):
        app = self.app
        lbl = Label(text=text, markup=True, font_size=sp(size), size_hint_y=None, halign="left",
                    color=app.c_muted if muted else app.c_text)
        attr = "c_muted" if muted else "c_text"
        app.bind(**{attr: lambda a, v: setattr(lbl, "color", v)})
        lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                 texture_size=lambda w, v: setattr(w, "height", v[1] + dp(4)))
        return lbl

    def refresh_files(self):
        app, card = self.app, self.files_card
        card.clear_widgets()
        items = app.link.items
        card.add_widget(self._lbl("[b]Files to send[/b]", 16))
        if not items:
            card.add_widget(self._lbl("Nothing chosen yet. Go to [b]Files[/b], long-press to select, "
                                      "then tap the [b]Send[/b] icon at the top.", 13, muted=True))
        for p in items[:6]:
            size = "folder" if os.path.isdir(p) else core.human_size(os.path.getsize(p)) if os.path.exists(p) else "?"
            card.add_widget(self._lbl(f"• {rich(os.path.basename(p))}  [color=888888]{size}[/color]", 14))
        if len(items) > 6:
            card.add_widget(self._lbl(f"…and {len(items) - 6} more", 13, muted=True))
        b1, b2 = Btn(text="Choose files", primary=not items), Btn(text="Clear")
        b1.bind(on_release=lambda *_: app.choose_files_to_send())
        b2.bind(on_release=lambda *_: app.clear_send())
        card.add_widget(btn_row(b1, b2) if items else btn_row(b1))

    def refresh_peers(self):
        app = self.app
        self.peers_box.clear_widgets()
        peers = app.nearby.peer_list()
        if not peers:
            self.peers_box.add_widget(self._lbl("Looking for nearby devices…", 14, muted=True))
        for peer in peers:
            row = BoxLayout(size_hint_y=None, height=dp(56), spacing=dp(10))
            icon = I["phone"] if peer["os"] == "Android" else (I["monitor"] if peer["os"] == "Windows" else I["laptop"])
            row.add_widget(Label(text=icon, font_name=ICON_FONT, font_size=sp(28), color=app.c_accent,
                                 size_hint_x=None, width=dp(40)))
            row.add_widget(self._lbl(f"[b]{rich(peer['name'])}[/b]\n[size=12sp]{peer['os']} · {peer['ip']}[/size]", 15))
            b = Btn(text="Send", primary=True, size_hint_x=None, width=dp(90), disabled=app.sending)
            b.bind(on_release=lambda _b, p=peer: app.send_to(p))
            row.add_widget(b)
            self.peers_box.add_widget(row)


class ReceiveScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="receive", **kw)
        self.app = app
        self.sv, box = scroll_box()
        bg(self.sv)
        self.add_widget(self.sv)
        mk = SendScreen._lbl
        card = Card()
        card.add_widget(Label(text=I["receive"], font_name=ICON_FONT, font_size=sp(54), color=app.c_accent,
                              size_hint_y=None, height=dp(70)))
        card.add_widget(mk(self, "[b]Receive files[/b]", 18))
        card.add_widget(mk(self, "Turn this on, then send from Arckad-D on a computer or another phone. "
                                 "You'll be asked before anything is saved.", 13, muted=True))
        row = BoxLayout(size_hint_y=None, height=dp(50), spacing=dp(10))
        row.add_widget(mk(self, "[b]Let nearby devices find me[/b]", 15))
        self.minutes = Spinner(text="10 min", values=[f"{m} min" for m in core.SHARE_MINUTES],
                               size_hint_x=None, width=dp(100))
        row.add_widget(self.minutes)
        self.switch = Switch(size_hint_x=None, width=dp(84))
        self.switch.bind(active=lambda w, v: app.toggle_receive(v))
        row.add_widget(self.switch)
        card.add_widget(row)
        self.state = mk(self, "Off", 14, muted=True)
        card.add_widget(self.state)
        box.add_widget(card)
        card2 = Card()
        card2.add_widget(mk(self, "[b]This phone's name[/b]", 15))
        self.name_input = TextInput(text=app.cfg.get("device_name") or device_name(), multiline=False)
        FilesScreen._style_input(self.name_input)
        self.name_input.bind(text=lambda w, v: app.set_cfg("device_name", v.strip()))
        card2.add_widget(self.name_input)
        open_btn = Btn(text="Open received files")
        open_btn.bind(on_release=lambda *_: app.open_folder(core.received_dir(), switch_tab=True))
        card2.add_widget(open_btn)
        box.add_widget(card2)
        card3 = Card()
        card3.add_widget(mk(self, "[b]Activity[/b]", 15))
        self.log = mk(self, "", 13, muted=True)
        card3.add_widget(self.log)
        box.add_widget(card3)


class PermissionScreen(Screen):
    def __init__(self, app, **kw):
        super().__init__(name="permission", **kw)
        sv, box = scroll_box(padding=dp(28))
        bg(sv)
        box.add_widget(Label(text=I["files"], font_name=ICON_FONT, font_size=sp(80), color=app.c_accent,
                             size_hint_y=None, height=dp(120)))
        box.add_widget(SendScreen._lbl(_Shim(app), "[b]Allow access to your files[/b]", 20))
        box.add_widget(SendScreen._lbl(_Shim(app), "Arckad-D is a file manager, so Android needs you to turn on "
                                       "[b]Allow access to manage all files[/b] for it. Your files never "
                                       "leave the phone unless you send or share them.", 14, muted=True))
        b = Btn(text="Open settings", primary=True)
        b.bind(on_release=lambda *_: ask_storage_access())
        box.add_widget(b)
        b2 = Btn(text="I've allowed it")
        b2.bind(on_release=lambda *_: app.check_permission())
        box.add_widget(b2)
        self.add_widget(sv)


class _Shim:
    def __init__(self, app):
        self.app = app


# ---------------------------------------------------------------- the app
class ArckadApp(App):
    c_bg = ListProperty(THEMES["light"]["bg"])
    c_card = ListProperty(THEMES["light"]["card"])
    c_text = ListProperty(THEMES["light"]["text"])
    c_muted = ListProperty(THEMES["light"]["muted"])
    c_accent = ListProperty(THEMES["light"]["accent"])
    c_line = ListProperty(THEMES["light"]["line"])
    c_bar = ListProperty(THEMES["light"]["bar"])
    c_sel = ListProperty(THEMES["light"]["sel"])
    select_mode = BooleanProperty(False)
    grid = BooleanProperty(False)
    icon_font = StringProperty(ICON_FONT)
    icons = ObjectProperty(I)

    def build(self):
        self.title = "Arckad-D"
        self.cfg_path = os.path.join(self.user_data_dir, "config.json")
        self.cfg = core.load_json(self.cfg_path, {})
        if not self.cfg.get("device_id"):
            self.set_cfg("device_id", secrets.token_hex(8))
        self.apply_theme(self.cfg.get("theme", "system"))
        self.grid = bool(self.cfg.get("grid", False))
        Builder.load_string(KV)
        self.cwd = core.storage_root()
        self.history = []
        self.entries, self.selected = [], set()
        self.mode = "folder"            # folder | search
        self.clipboard = None           # (paths, move)
        self.sort_by = self.cfg.get("sort", "name")
        self.show_hidden = bool(self.cfg.get("hidden", False))
        self.search_on = False
        self.search_gen = 0
        self.search_ev = None
        self.sending = False
        self.recent_items = []
        self.preview_entry = None
        self.thumbs = core.ThumbWorker(os.path.join(self.user_data_dir, "thumbs"),
                                       lambda p, t: Clock.schedule_once(lambda dt: self.thumb_ready(p, t)))
        self.nearby = core.Nearby(self.cfg["device_id"], lambda: self.cfg.get("device_name") or device_name(),
                                  self.ui)
        self.link = core.LinkShare(lambda: self.cfg.get("device_name") or device_name(), self.ui)

        root = FloatLayout()
        main = BoxLayout(orientation="vertical")
        self.topbar = BoxLayout(size_hint_y=None, height=dp(56), padding=(dp(4), 0), spacing=dp(2))
        bg(self.topbar, "c_bar")
        main.add_widget(self.topbar)
        self.sm = ScreenManager(transition=NoTransition())
        self.files_screen = FilesScreen(self)
        self.preview_screen = PreviewScreen(self)
        self.recent_screen = RecentScreen(self)
        self.send_screen = SendScreen(self)
        self.receive_screen = ReceiveScreen(self)
        for s in (self.files_screen, self.recent_screen, self.send_screen, self.receive_screen,
                  self.preview_screen, PermissionScreen(self)):
            self.sm.add_widget(s)
        main.add_widget(self.sm)
        self.pastebar = BoxLayout(size_hint_y=None, height=0, opacity=0, padding=(dp(12), dp(6)), spacing=dp(8))
        bg(self.pastebar, "c_card")
        main.add_widget(self.pastebar)
        self.nav = BoxLayout(size_hint_y=None, height=dp(62))
        bg(self.nav, "c_bar")
        self.nav_buttons = {}
        for key, icon, text in (("files", I["files"], "Files"), ("recent", I["recent"], "Recent"),
                                ("send", I["send"], "Send"), ("receive", I["receive"], "Receive")):
            b = NavButton(icon=icon, text=text)
            b.bind(on_release=lambda _b, k=key: self.go_tab(k))
            self.nav_buttons[key] = b
            self.nav.add_widget(b)
        main.add_widget(self.nav)
        root.add_widget(main)
        self.toast_lbl = Label(text="", size_hint=(None, None), opacity=0, color=(1, 1, 1, 1),
                               font_size=sp(14), pos_hint={"center_x": .5, "y": .1}, padding=(dp(16), dp(10)))
        self.toast_lbl.bind(texture_size=lambda w, v: setattr(w, "size", v))
        with self.toast_lbl.canvas.before:
            self._toast_col = Color(0.15, 0.15, 0.17, 0)
            self._toast_bg = RoundedRectangle(radius=[dp(18)])
        self.toast_lbl.bind(pos=self._place_toast, size=self._place_toast)
        root.add_widget(self.toast_lbl)
        Window.bind(on_keyboard=self.on_key)
        Clock.schedule_interval(self.tick, 1)
        Clock.schedule_once(lambda dt: self.start(), 0)
        return root

    # ---------- startup & settings
    def start(self):
        if not has_storage_access():
            self.sm.current = "permission"
            self.set_tab(None)
            self.update_topbar()
            return
        self.go_tab("files")
        self.open_folder(self.cwd, push=False)
        self.load_recent()

    def check_permission(self):
        if has_storage_access():
            self.start()
        else:
            self.toast("Not allowed yet. Turn on the switch in Settings, then come back.")

    def on_resume(self):
        if self.sm.current == "permission" and has_storage_access():
            self.start()

    def set_cfg(self, key, value):
        self.cfg[key] = value
        core.save_json(self.cfg_path, self.cfg)

    def apply_theme(self, mode):
        self.theme_mode = mode
        dark = system_dark() if mode == "system" else mode == "dark"
        for k, v in THEMES["dark" if dark else "light"].items():
            setattr(self, "c_" + k, v)
        Window.clearcolor = self.c_bg

    def cycle_theme(self):
        order = ["system", "light", "dark"]
        mode = order[(order.index(self.theme_mode) + 1) % 3]
        self.set_cfg("theme", mode)
        self.apply_theme(mode)
        self.toast({"system": "Theme: follow phone", "light": "Theme: light", "dark": "Theme: dark"}[mode])
        self.update_topbar()

    def ui(self, method, *args):
        """Lets background threads call into the screen safely."""
        Clock.schedule_once(lambda dt: getattr(self, method)(*args))

    def safe(self, fn, *args):
        try:
            fn(*args)
        except Exception as ex:
            self.toast(f"Couldn't do that: {ex}")

    def toast(self, text, seconds=2.6):
        from kivy.animation import Animation
        Animation.cancel_all(self.toast_lbl)
        Animation.cancel_all(self._toast_col)
        self.toast_lbl.text = text
        self.toast_lbl.opacity = 1
        self._toast_col.a = 0.94
        anim = Animation(duration=seconds) + Animation(opacity=0, duration=0.4)
        anim.start(self.toast_lbl)
        (Animation(duration=seconds) + Animation(a=0, duration=0.4)).start(self._toast_col)

    def _place_toast(self, *_):
        self._toast_bg.pos, self._toast_bg.size = self.toast_lbl.pos, self.toast_lbl.size

    # ---------- top bar
    def update_topbar(self):
        bar = self.topbar
        bar.clear_widgets()
        screen = self.sm.current

        def icon_btn(name, cb):
            b = IconButton(text=I[name])
            b.bind(on_release=lambda *_: cb())
            bar.add_widget(b)

        def title(text):
            lbl = Label(text=text, markup=True, bold=True, font_size=sp(19), color=self.c_text,
                        halign="left", valign="middle", shorten=True)
            lbl.bind(size=lambda w, v: setattr(w, "text_size", v))
            bar.add_widget(lbl)
        if screen == "files" and self.select_mode:
            icon_btn("close", self.clear_selection)
            title(str(len(self.selected)))
            icon_btn("send", lambda: self.send_paths(sorted(self.selected)))
            icon_btn("share", lambda: self.safe(share_files, sorted(self.selected)))
            icon_btn("copy", lambda: self.set_clipboard(False))
            icon_btn("cut", lambda: self.set_clipboard(True))
            icon_btn("menu", self.selection_menu)
            return
        if screen == "preview":
            icon_btn("back", self.back)
            title(rich(self.preview_entry["name"]) if self.preview_entry else "")
            return
        if screen == "files":
            if self.cwd != core.storage_root() or self.mode == "search":
                icon_btn("back", self.back)
            title(rich(os.path.basename(self.cwd) or "Files") if self.cwd != core.storage_root() else "Arckad-D")
            icon_btn("search", self.toggle_search)
            icon_btn("list" if self.grid else "grid", self.toggle_grid)
            icon_btn("menu", self.main_menu)
            return
        names = {"recent": "Where was I?", "send": "Send", "receive": "Receive", "permission": "Arckad-D"}
        title(names.get(screen, "Arckad-D"))
        if screen == "recent":
            icon_btn("refresh", self.load_recent)
        icon_btn("theme", self.cycle_theme)

    # ---------- tabs
    def set_tab(self, key):
        for k, b in self.nav_buttons.items():
            b.active = k == key

    def go_tab(self, key):
        if self.sm.current == "permission":
            return
        self.sm.current = key
        self.set_tab(key)
        if key == "send":
            try:
                MulticastLock.acquire()
                self.nearby.start_scan()
            except OSError as ex:
                self.toast(f"Can't look for nearby devices: {ex}")
            self.send_screen.refresh_files()
            self.send_screen.refresh_peers()
        else:
            self.nearby.stop_scan()
            if not self.nearby.server:
                MulticastLock.release()
        if key == "recent" and not self.recent_items:
            self.load_recent()
        self.update_topbar()

    # ---------- folders, listing, search
    def open_folder(self, path, push=True, switch_tab=False):
        if not os.path.isdir(path):
            self.toast("That folder isn't available.")
            return
        if push and path != self.cwd:
            self.history.append(self.cwd)
        self.cwd = path
        self.mode = "folder"
        self.selected.clear()
        self.select_mode = False
        if self.search_on:
            self.search_on = False
            self.files_screen.show_search(False)
        self.files_screen.set_crumbs(path)
        if switch_tab:
            self.go_tab("files")
        self.thumbs.clear_queue()
        self.files_screen.empty.text = "Loading…"
        threading.Thread(target=self._list, args=(path, self.search_gen), daemon=True).start()
        self.update_topbar()

    def _list(self, path, gen):
        try:
            items = core.sort_entries(core.list_dir(path, self.show_hidden), self.sort_by)
            err = None
        except OSError as ex:
            items, err = [], ex.strerror or str(ex)
        Clock.schedule_once(lambda dt: self.show_entries(items, err, gen))

    def show_entries(self, items, err=None, gen=None):
        if gen is not None and gen != self.search_gen:
            return
        self.entries = items
        kind = self.files_screen.kind.text if self.search_on else "All types"
        if kind != "All types" and self.mode == "folder":
            self.entries = [e for e in items if e["kind"] == kind]
        self.refresh_rv()
        fs = self.files_screen
        if err:
            fs.empty.text = f"Can't open this folder: {err}"
        elif not self.entries:
            fs.empty.text = "Nothing here" if self.mode == "folder" else "No matches"
        else:
            fs.empty.text = ""
        fs.empty.height = dp(48) if fs.empty.text else 0

    def entry_data(self, e):
        thumb = ""
        if e["kind"] == "Images":
            thumb = self.thumbs.request(e["path"]) or ""
        sub = ("Folder" if e["is_dir"] else core.human_size(e["size"])) + " · " + core.fmt_time(e["mtime"])
        if self.mode == "search":
            sub += " · " + core.short(os.path.dirname(e["path"]))
        return {"name": rich(e["name"]), "path": e["path"], "sub": sub, "icon": icon_for(e),
                "thumb": thumb, "is_dir": e["is_dir"], "selected": e["path"] in self.selected}

    def refresh_rv(self):
        rv = self.files_screen.current_rv()
        rv.data = [self.entry_data(e) for e in self.entries]

    def thumb_ready(self, path, thumb):
        for rv in (self.files_screen.current_rv(), self.recent_screen.rv):
            changed = False
            for d in rv.data:
                if d.get("path") == path and d.get("thumb") != thumb:
                    d["thumb"] = thumb
                    changed = True
            if changed:
                rv.refresh_from_data()

    def toggle_grid(self):
        self.grid = not self.grid
        self.set_cfg("grid", self.grid)
        self.files_screen.set_grid(self.grid)
        self.refresh_rv()
        self.update_topbar()

    def toggle_search(self):
        self.search_on = not self.search_on
        self.files_screen.show_search(self.search_on)
        if not self.search_on:
            self.mode = "folder"
            self.open_folder(self.cwd, push=False)

    def schedule_search(self):
        if self.search_ev:
            self.search_ev.cancel()
        self.search_ev = Clock.schedule_once(lambda dt: self.run_search(), 0.35)

    def run_search(self):
        if not self.search_on:
            return
        q, kind = self.files_screen.search.text.strip(), self.files_screen.kind.text
        self.search_gen += 1
        gen = self.search_gen
        if not q and kind == "All types":
            self.mode = "folder"
            self.open_folder(self.cwd, push=False)
            self.search_on = True
            self.files_screen.show_search(True)
            return
        if not q:                                        # only a type filter: this folder
            self.mode = "folder"
            threading.Thread(target=self._list, args=(self.cwd, gen), daemon=True).start()
            return
        self.mode = "search"
        self.files_screen.empty.text = "Searching…"
        root = self.cwd

        def work():
            found, last = [], time.time()
            for e in core.walk(root, self.show_hidden):
                if gen != self.search_gen:
                    return
                if core.matches(e, q, kind):
                    found.append(e)
                    if time.time() - last > 0.4:
                        last = time.time()
                        batch = list(found)
                        Clock.schedule_once(lambda dt, b=batch: self.show_entries(b, None, gen))
                    if len(found) >= 3000:
                        break
            Clock.schedule_once(lambda dt: self.show_entries(found, None, gen))
        threading.Thread(target=work, daemon=True).start()
        self.update_topbar()

    # ---------- taps
    def item_list(self):
        if self.sm.current == "recent":
            return self.recent_items
        return self.entries

    def on_item_tap(self, index):
        items = self.item_list()
        if index >= len(items) or items[index] is None:
            return
        e = items[index]
        if self.select_mode and self.sm.current == "files":
            self.toggle_select(e["path"])
            return
        if e["is_dir"]:
            self.open_folder(e["path"], switch_tab=self.sm.current != "files")
        else:
            self.preview(e)

    def on_item_long(self, index):
        items = self.item_list()
        if self.sm.current != "files" or index >= len(items):
            return
        self.select_mode = True
        self.toggle_select(items[index]["path"])

    def toggle_select(self, path):
        if path in self.selected:
            self.selected.discard(path)
        else:
            self.selected.add(path)
        if not self.selected:
            self.select_mode = False
        rv = self.files_screen.current_rv()
        for d in rv.data:
            d["selected"] = d["path"] in self.selected
        rv.refresh_from_data()
        self.update_topbar()

    def select_all(self):
        self.selected = {e["path"] for e in self.entries}
        rv = self.files_screen.current_rv()
        for d in rv.data:
            d["selected"] = True
        rv.refresh_from_data()
        self.update_topbar()

    def clear_selection(self):
        self.selected.clear()
        self.select_mode = False
        rv = self.files_screen.current_rv()
        for d in rv.data:
            d["selected"] = False
        rv.refresh_from_data()
        self.update_topbar()

    def preview(self, e):
        self.preview_entry = e
        self.preview_screen.show(e)
        self.sm.current = "preview"
        self.update_topbar()

    def back(self):
        if self.sm.current == "preview":
            self.sm.current = "files" if self.nav_buttons["files"].active else "recent"
            self.update_topbar()
            return True
        if self.sm.current == "files":
            if self.select_mode:
                self.clear_selection()
                return True
            if self.search_on:
                self.toggle_search()
                return True
            if self.history:
                self.open_folder(self.history.pop(), push=False)
                return True
            if self.cwd != core.storage_root():
                self.open_folder(os.path.dirname(self.cwd), push=False)
                return True
            return False
        self.go_tab("files")
        return True

    def on_key(self, window, key, *args):
        if key == 27:                    # Android back button
            return self.back()
        return False

    # ---------- file actions
    def set_clipboard(self, move):
        self.clipboard = (sorted(self.selected), move)
        n = len(self.clipboard[0])
        self.clear_selection()
        bar = self.pastebar
        bar.clear_widgets()
        lbl = Label(text=f"{n} item{'s' if n != 1 else ''} to {'move' if move else 'copy'}", color=self.c_text,
                    halign="left", valign="middle")
        lbl.bind(size=lambda w, v: setattr(w, "text_size", v))
        bar.add_widget(lbl)
        b1, b2 = Btn(text="Paste here", primary=True, size_hint_x=None, width=dp(120)), \
            Btn(text="Cancel", size_hint_x=None, width=dp(90))
        b1.bind(on_release=lambda *_: self.paste())
        b2.bind(on_release=lambda *_: self.hide_pastebar())
        bar.add_widget(b1)
        bar.add_widget(b2)
        bar.height, bar.opacity = dp(58), 1
        self.toast("Open the destination folder, then tap Paste here")

    def hide_pastebar(self):
        self.clipboard = None
        self.pastebar.height, self.pastebar.opacity = 0, 0
        self.pastebar.clear_widgets()

    def paste(self):
        if not self.clipboard:
            return
        paths, move = self.clipboard
        dest = self.cwd
        self.hide_pastebar()
        self.toast("Copying…" if not move else "Moving…")

        def work():
            done, errors = core.copy_or_move(paths, dest, move)
            media_scan([os.path.join(dest, os.path.basename(p)) for p in paths])
            Clock.schedule_once(lambda dt: self._after_paste(done, errors, move))
        threading.Thread(target=work, daemon=True).start()

    def _after_paste(self, done, errors, move):
        self.open_folder(self.cwd, push=False)
        self.toast(f"{'Moved' if move else 'Copied'} {done} item{'s' if done != 1 else ''}"
                   + (f" · {len(errors)} failed" if errors else ""))

    def selection_menu(self):
        paths = sorted(self.selected)
        items = [("Select all", self.select_all, True),
                 ("Rename", lambda: self.rename(paths[0]), len(paths) == 1),
                 ("Delete", lambda: self.delete(paths), True),
                 ("Details", lambda: self.preview(core.entry(paths[0])) if paths else None, len(paths) == 1)]
        self.menu("Selected items", items)

    def main_menu(self):
        items = [("Sort by name", lambda: self.set_sort("name"), self.sort_by != "name"),
                 ("Sort by date (newest first)", lambda: self.set_sort("date"), self.sort_by != "date"),
                 ("Sort by size (largest first)", lambda: self.set_sort("size"), self.sort_by != "size"),
                 ("Hide hidden files" if self.show_hidden else "Show hidden files", self.toggle_hidden, True),
                 ("New folder", self.new_folder, True),
                 ("Received files", lambda: self.open_folder(core.received_dir()), True),
                 ("Theme: follow phone / light / dark", self.cycle_theme, True),
                 (f"About Arckad-D {__version__}", lambda: self.toast(f"Arckad-D {__version__} for Android"), True)]
        self.menu("Arckad-D", items)

    def menu(self, title, items):
        view = ModalView(size_hint=(.86, None), background="", background_color=(0, 0, 0, 0),
                         overlay_color=(0, 0, 0, .45))
        card = Card(padding=dp(10), spacing=dp(4))
        card.add_widget(Label(text=f"[b]{title}[/b]", markup=True, color=self.c_text, size_hint_y=None,
                              height=dp(40), font_size=sp(16)))
        for label, cb, enabled in items:
            b = Btn(text=label, disabled=not enabled)
            b.bind(on_release=lambda _b, cb=cb: (view.dismiss(), cb()))
            card.add_widget(b)
        view.add_widget(card)
        card.bind(height=lambda w, v: setattr(view, "height", v))
        view.open()

    def set_sort(self, by):
        self.sort_by = by
        self.set_cfg("sort", by)
        self.open_folder(self.cwd, push=False)

    def toggle_hidden(self):
        self.show_hidden = not self.show_hidden
        self.set_cfg("hidden", self.show_hidden)
        self.open_folder(self.cwd, push=False)

    def ask_text(self, title, initial, on_ok, ok_text="OK"):
        view = ModalView(size_hint=(.88, None), height=dp(200), background="", background_color=(0, 0, 0, 0),
                         overlay_color=(0, 0, 0, .45), auto_dismiss=True)
        card = Card(padding=dp(16), spacing=dp(12))
        card.add_widget(Label(text=f"[b]{title}[/b]", markup=True, color=self.c_text, size_hint_y=None,
                              height=dp(30), font_size=sp(16)))
        ti = TextInput(text=initial, multiline=False)
        FilesScreen._style_input(ti)
        card.add_widget(ti)
        b1, b2 = Btn(text="Cancel"), Btn(text=ok_text, primary=True)
        b1.bind(on_release=lambda *_: view.dismiss())
        b2.bind(on_release=lambda *_: (view.dismiss(), on_ok(ti.text.strip())))
        card.add_widget(btn_row(b1, b2))
        view.add_widget(card)
        view.open()
        Clock.schedule_once(lambda dt: setattr(ti, "focus", True), 0.2)

    def confirm(self, title, text, ok_text, on_ok):
        view = ModalView(size_hint=(.88, None), height=dp(220), background="", background_color=(0, 0, 0, 0),
                         overlay_color=(0, 0, 0, .45))
        card = Card(padding=dp(16), spacing=dp(12))
        card.add_widget(Label(text=f"[b]{title}[/b]", markup=True, color=self.c_text, size_hint_y=None,
                              height=dp(30), font_size=sp(16)))
        msg = Label(text=text, markup=True, color=self.c_muted, size_hint_y=None, halign="left")
        msg.bind(width=lambda w, v: setattr(w, "text_size", (v, None)),
                 texture_size=lambda w, v: setattr(w, "height", v[1]))
        card.add_widget(msg)
        b1, b2 = Btn(text="Cancel"), Btn(text=ok_text, primary=True)
        b1.bind(on_release=lambda *_: view.dismiss())
        b2.bind(on_release=lambda *_: (view.dismiss(), on_ok()))
        card.add_widget(btn_row(b1, b2))
        view.add_widget(card)
        card.bind(height=lambda w, v: setattr(view, "height", v))
        view.open()
        return view

    def rename(self, path):
        def do(new):
            if not new or new == os.path.basename(path) or "/" in new:
                return
            target = os.path.join(os.path.dirname(path), new)
            if os.path.exists(target):
                self.toast("That name is already used here.")
                return
            try:
                os.rename(path, target)
            except OSError as ex:
                self.toast(f"Couldn't rename: {ex.strerror}")
                return
            self.clear_selection()
            if self.sm.current == "preview":
                self.preview(core.entry(target))
            self.open_folder(self.cwd, push=False)
        self.ask_text("Rename", os.path.basename(path), do, "Rename")

    def delete(self, paths, back=False):
        n = len(paths)
        names = ", ".join(rich(os.path.basename(p)) for p in paths[:3]) + ("…" if n > 3 else "")

        def do():
            errors = core.delete_paths(paths)
            media_scan(paths)
            self.toast(f"Deleted {n - len(errors)} item{'s' if n != 1 else ''}"
                       + (f" · {len(errors)} failed" if errors else ""))
            self.clear_selection()
            if back:
                self.back()
            self.open_folder(self.cwd, push=False)
        self.confirm("Delete permanently?", f"{names}\n\nPhones have no Trash, so this can't be undone.",
                     "Delete", do)

    def new_folder(self):
        def do(name):
            if not name or "/" in name:
                return
            target = core.unique_target(os.path.join(self.cwd, name))
            try:
                os.makedirs(target)
            except OSError as ex:
                self.toast(f"Couldn't create it: {ex.strerror}")
            self.open_folder(self.cwd, push=False)
        self.ask_text("New folder", "New folder", do, "Create")

    # ---------- recent / where was I
    def load_recent(self):
        self.recent_screen.banner_title.text = "Looking for your latest work…"

        def work():
            items = core.recent_files()
            Clock.schedule_once(lambda dt: self.show_recent(items))
        threading.Thread(target=work, daemon=True).start()

    def show_recent(self, items):
        rs = self.recent_screen
        if items:
            last = items[0]
            rs.banner_title.text = f"You were last working on [color={self._hex(self.c_accent)}]{rich(last['name'])}[/color]"
            rs.banner_sub.text = f"in {rich(core.short(os.path.dirname(last['path'])))}, {core.ago(last['mtime'])}"
            rs.banner_btn.opacity, rs.banner_btn.disabled = 1, False
            self.last_entry = last
        else:
            rs.banner_title.text = "No recent files yet"
            rs.banner_sub.text = "Files you change will appear here."
            rs.banner_btn.opacity, rs.banner_btn.disabled = 0, True
        data, flat, current = [], [], None
        for e in items:
            d = date.fromtimestamp(e["mtime"])
            if d != current:
                current = d
                data.append({"viewclass": "HeaderRow", "name": core.day_label(d)})
                flat.append(None)
            row = self.entry_data(e)
            row["viewclass"] = "FileRow"
            row["sub"] = core.fmt_time(e["mtime"]) + " · " + core.short(os.path.dirname(e["path"]))
            data.append(row)
            flat.append(e)
        self.recent_items = flat
        rs.rv.data = data

    @staticmethod
    def _hex(c):
        return "".join(f"{int(x * 255):02x}" for x in c[:3])

    def open_last(self):
        e = getattr(self, "last_entry", None)
        if e:
            self.preview(e)

    # ---------- send
    def send_paths(self, paths):
        for p in paths:
            if p not in self.link.items:
                self.link.items.append(p)
        self.clear_selection()
        self.go_tab("send")

    def choose_files_to_send(self):
        self.go_tab("files")
        self.toast("Long-press files to select them, then tap the Send icon")

    def clear_send(self):
        self.link.items.clear()
        self.send_screen.refresh_files()

    def on_peers_changed(self):
        if self.sm.current == "send":
            self.send_screen.refresh_peers()

    def send_to(self, peer):
        paths = self.link.snapshot()
        if not paths:
            self.toast("Choose some files first")
            return
        self.sending = True
        ss = self.send_screen
        ss.refresh_peers()
        ss.progress.height, ss.progress.opacity, ss.progress.value = dp(10), 1, 0
        ss.progress_lbl.text = f"Offering {len(paths)} item{'s' if len(paths) != 1 else ''} to {rich(peer['name'])}…"

        def progress(sent, total, text):
            Clock.schedule_once(lambda dt: self._send_progress(sent, total, text))

        def done(peer_, error):
            Clock.schedule_once(lambda dt: self._send_done(peer_, error))
        self.nearby.send(peer, paths, progress, done)

    def _send_progress(self, sent, total, text):
        ss = self.send_screen
        ss.progress.value = sent / total if total else 1
        ss.progress_lbl.text = f"{rich(text)}  {core.human_size(sent)} / {core.human_size(total)}"

    def _send_done(self, peer, error):
        self.sending = False
        ss = self.send_screen
        ss.refresh_peers()
        if error:
            ss.progress_lbl.text = error
        else:
            ss.progress.value = 1
            ss.progress_lbl.text = f"Sent to {rich(peer['name'])} ✓"
            self.toast(f"Sent to {peer['name']}")

    def toggle_link(self, on):
        ss = self.send_screen
        if on and not self.link.active():
            if not self.link.snapshot():
                self.toast("Choose some files first")
                Clock.schedule_once(lambda dt: setattr(ss.link_switch, "active", False))
                return
            try:
                self.link.start(int(ss.link_minutes.text.split()[0]))
            except OSError as ex:
                self.toast(f"Couldn't start sharing: {ex}")
                Clock.schedule_once(lambda dt: setattr(ss.link_switch, "active", False))
                return
            url = self.link.url()
            ss.url_lbl.text = f"[b]{url}[/b]\nOpen this in any browser on the same Wi-Fi, or scan the code."
            tex = self.qr_texture(url)
            if tex:
                ss.qr.texture = tex
                ss.qr.height, ss.qr.opacity = dp(230), 1
            ss.copy_btn.opacity, ss.copy_btn.disabled = 1, False
        elif not on and self.link.server:
            self.link.stop()
            ss.url_lbl.text = ""
            ss.qr.height, ss.qr.opacity = 0, 0
            ss.copy_btn.opacity, ss.copy_btn.disabled = 0, True
        self.update_states()

    @staticmethod
    def qr_texture(text):
        m = core.qr_matrix(text)
        if not m:
            return None
        n, scale = len(m), 8
        buf = bytearray()
        for row in reversed(m):                    # Kivy textures start at the bottom
            line = b"".join((b"\x00\x00\x00" if c else b"\xff\xff\xff") * scale for c in row)
            buf += line * scale
        tex = Texture.create(size=(n * scale, n * scale), colorfmt="rgb")
        tex.blit_buffer(bytes(buf), colorfmt="rgb", bufferfmt="ubyte")
        tex.mag_filter = "nearest"
        return tex

    def copy_link(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(self.link.url())
        self.toast("Link copied")

    def on_share_event(self, client, text):
        self.log_line(f"{client} {text}")

    # ---------- receive
    def toggle_receive(self, on):
        rs = self.receive_screen
        if on and not self.nearby.visible():
            try:
                MulticastLock.acquire()
                self.nearby.set_visible(int(rs.minutes.text.split()[0]))
                self.log_line(f"Visible as “{self.nearby.name()}”")
            except OSError as ex:
                self.toast(f"Couldn't turn on receiving: {ex}")
                Clock.schedule_once(lambda dt: setattr(rs.switch, "active", False))
                return
        elif not on and self.nearby.server:
            self.nearby.hide()
            self.log_line("Receiving turned off")
            if self.sm.current != "send":
                MulticastLock.release()
        self.update_states()

    def ask_incoming(self, req):
        names = ["/".join(parts) for parts, _ in req["files"]]
        n = len(names)
        listing = "\n".join("• " + rich(x) for x in names[:5]) + (f"\n…and {n - 5} more" if n > 5 else "")
        answered = {"done": False}

        def answer(ok):
            if answered["done"]:
                return
            answered["done"] = True
            req["accepted"] = ok
            req["event"].set()
            self.log_line(("Accepted" if ok else "Declined") + f" {n} file{'s' if n != 1 else ''} from {req['from']}")

        view = self.confirm(f"{req['from']} wants to send you {n} file{'s' if n != 1 else ''}",
                            f"{core.human_size(req['total'])} from {rich(req['from'])} ({req['os']})\n\n{listing}",
                            "Accept", lambda: answer(True))
        view.bind(on_dismiss=lambda *_: Clock.schedule_once(lambda dt: answer(False), 0.1))
        Clock.schedule_once(lambda dt: (answer(False), view.dismiss()) if not answered["done"] else None, 60)

    def on_progress(self, req):
        self.receive_screen.state.text = (f"Receiving from [b]{rich(req['from'])}[/b]: {req['done_files']} / "
                                          f"{len(req['files'])} files ({core.human_size(req['received'])})")

    def on_received(self, req):
        n = len(req["files"])
        media_scan(req["dest"])
        msg = f"Received {n} file{'s' if n != 1 else ''} from {req['from']}"
        self.log_line("✓ " + msg)
        self.toast(msg)
        self.update_states()

    def log_line(self, text):
        lbl = self.receive_screen.log
        lines = (lbl.text.split("\n") if lbl.text else [])[-14:]
        lines.append(f"{time.strftime('%H:%M')}  {rich(text)}")
        lbl.text = "\n".join(lines)

    # ---------- timers
    def tick(self, dt):
        if self.nearby.server and not self.nearby.visible():
            if self.nearby.visible_until or not self.nearby.transfers:
                self.nearby.hide()
                self.log_line("Time is up, receiving turned off")
        if self.link.server and not self.link.active():
            self.link.stop()
            self.toast("Link sharing ended")
            ss = self.send_screen
            ss.link_switch.active = False
        self.update_states()

    def update_states(self):
        rs, ss = self.receive_screen, self.send_screen
        if self.nearby.visible():
            left = self.nearby.remaining()
            if not self.nearby.transfers:
                rs.state.text = (f"[b]On[/b] · visible as “{rich(self.nearby.name())}” for {left // 60}:{left % 60:02d}\n"
                                 f"Files go to {core.short(core.received_dir())}")
            if not rs.switch.active:
                rs.switch.active = True
        else:
            rs.state.text = "[b]Off[/b] · other devices can't see this phone"
            if rs.switch.active and not self.nearby.server:
                rs.switch.active = False
        if self.link.active():
            left = self.link.remaining()
            ss.link_state.text = f"[b]On[/b] · {left // 60}:{left % 60:02d} left"
        else:
            ss.link_state.text = "Off"

    def on_stop(self):
        self.nearby.scanning = False
        self.nearby.hide(force=True)
        self.link.stop()
        MulticastLock.release()

    def on_pause(self):
        return True


if __name__ == "__main__":
    ArckadApp().run()

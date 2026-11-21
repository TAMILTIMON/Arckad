#!/usr/bin/env python3
"""Makes every app icon from ONE picture: branding/logo.png (square, at least 512 x 512, transparent background).

Run automatically by the builds; run it yourself to preview:  python3 branding/make-icons.py
Creates: windows/arckad-d.ico + windows/arckad-d.png (Windows program and installer),
         android/res/mipmap-*/ic_launcher.png (Android launcher), branding/linux/<size>.png (Ubuntu menu).
Without branding/logo.png it does nothing, and the built-in logo is used."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(HERE, "logo.png")


def main():
    if not os.path.exists(SRC):
        print("branding/logo.png not found: keeping the built-in logo.")
        return 0
    try:
        from PIL import Image
    except ImportError:
        print("Pillow is needed: pip install pillow  (or: sudo apt install python3-pil)")
        return 1
    img = Image.open(SRC).convert("RGBA")
    w, h = img.size
    if w != h:                                   # centre it on a transparent square
        side = max(w, h)
        sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        sq.paste(img, ((side - w) // 2, (side - h) // 2))
        img = sq
    if img.size[0] < 256:
        print(f"Warning: branding/logo.png is only {img.size[0]} px; use 512 px or more for sharp icons.")

    def size(s):
        return img.resize((s, s), Image.LANCZOS)
    os.makedirs(os.path.join(ROOT, "windows"), exist_ok=True)
    size(256).save(os.path.join(ROOT, "windows", "arckad-d.png"))
    size(256).save(os.path.join(ROOT, "windows", "arckad-d.ico"),
                   sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    for folder, s in (("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)):
        d = os.path.join(ROOT, "android", "res", f"mipmap-{folder}")
        os.makedirs(d, exist_ok=True)
        size(s).save(os.path.join(d, "ic_launcher.png"))
    lin = os.path.join(HERE, "linux")
    os.makedirs(lin, exist_ok=True)
    for s in (16, 24, 32, 48, 64, 128, 256, 512):
        size(s).save(os.path.join(lin, f"{s}.png"))
    print("Icons made from branding/logo.png for Windows, Android and Ubuntu.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

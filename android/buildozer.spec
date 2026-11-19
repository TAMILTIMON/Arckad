[app]
title = Arckad-D
package.name = arckadd
package.domain = io.github.tamiltimon
source.dir = .
source.include_exts = py,png,ttf,json
source.exclude_dirs = bin,.buildozer,signing
version.regex = __version__ = ["'](.*)["']
version.filename = %(source.dir)s/main.py
requirements = python3,kivy,pillow,pyjnius,android,qrcode
icon.filename = %(source.dir)s/icon.png
presplash.filename = %(source.dir)s/presplash.png
presplash.color = #F6F5F4
orientation = portrait
fullscreen = 0
android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CHANGE_WIFI_MULTICAST_STATE, READ_EXTERNAL_STORAGE, WRITE_EXTERNAL_STORAGE, MANAGE_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.accept_sdk_license = True
android.allow_backup = True
android.debug_artifact = apk

[buildozer]
log_level = 2
warn_on_root = 0

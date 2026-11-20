#!/usr/bin/env bash
# Builds Arckad-D-<version>.apk with the Android SDK tools that GitHub's machines already have
# (no Gradle, no downloads). Run from anywhere:  bash android/build-apk.sh
set -euo pipefail
cd "$(dirname "$0")"
VERSION=$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' ../arckad-d.py)
IFS=. read -r MA MI PA <<< "$VERSION"
CODE=$((2000000000 + ${MA:-0} * 10000 + ${MI:-0} * 100 + ${PA:-0}))
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-}}"
# newest *stable* versions (skip previews such as "android-37.2-beta3" or "37.0.0-rc1")
BT=$(ls -d "$SDK"/build-tools/* | grep -E '/[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | tail -1)
PLATFORM=$(ls -d "$SDK"/platforms/android-* | grep -E '/android-[0-9]+$' | sort -V | tail -1)
JAR="$PLATFORM/android.jar"
echo "Arckad-D $VERSION (code $CODE) · build-tools $(basename "$BT") · $(basename "$PLATFORM")"

rm -rf build && mkdir -p build/classes build/dex
sed -i "s/static final String VERSION = \".*\";/static final String VERSION = \"$VERSION\";/" \
    src/io/github/tamiltimon/arckadd/BuildInfo.java

"$BT/aapt2" compile --dir res -o build/res.zip
"$BT/aapt2" link -I "$JAR" --manifest AndroidManifest.xml -o build/base.apk build/res.zip \
    --min-sdk-version 24 --target-sdk-version 34 --version-code "$CODE" --version-name "$VERSION" --auto-add-overlay
# Java's own library (for lambdas) + Android's classes on the class path
javac -encoding UTF-8 --release 8 -classpath "$JAR" -nowarn -Xlint:none \
    -d build/classes $(find src -name '*.java')
"$BT/d8" --release --min-api 24 --lib "$JAR" --output build/dex $(find build/classes -name '*.class')
cp build/base.apk build/unsigned.apk
(cd build/dex && zip -q ../unsigned.apk classes.dex)
"$BT/zipalign" -f -p 4 build/unsigned.apk build/aligned.apk
# Sign with the private release key from GitHub's secret storage when it's set up
# (secrets ANDROID_KEYSTORE_B64, ANDROID_KEYSTORE_PASSWORD, ANDROID_KEY_ALIAS); otherwise the test key.
if [ -n "${ANDROID_KEYSTORE_B64:-}" ]; then
    echo "$ANDROID_KEYSTORE_B64" | base64 -d > build/release.jks
    "$BT/apksigner" sign --ks build/release.jks --ks-pass env:ANDROID_KEYSTORE_PASSWORD \
        --key-pass env:ANDROID_KEYSTORE_PASSWORD --ks-key-alias "${ANDROID_KEY_ALIAS:-arckad}" \
        --out "build/Arckad-D-$VERSION.apk" build/aligned.apk
    rm -f build/release.jks
    echo "Signed with the release key"
else
    echo "::warning::No release key set up: signing with the public test key (Play Protect may warn)"
    "$BT/apksigner" sign --ks signing/debug.keystore --ks-pass pass:android --key-pass pass:android \
        --ks-key-alias androiddebugkey --out "build/Arckad-D-$VERSION.apk" build/aligned.apk
fi
"$BT/apksigner" verify "build/Arckad-D-$VERSION.apk"
ls -la "build/Arckad-D-$VERSION.apk"

#!/bin/sh
# Build the floating status panel with plain SDK tools -- no Gradle.
#
# Architecture note, learned the hard way: this machine is aarch64, and
# Google's official build-tools zips ship x86-64 native binaries. `aapt2` from
# that zip dies with "required file not found" (wrong ELF machine), which looks
# exactly like a missing dependency. Debian's android-sdk packages are built
# for the host arch, so we use those for aapt2/zipalign and the *jar* forms of
# d8/apksigner, which are portable Java. Only android.jar is taken from the
# Google download, since it is pure class files.
set -e

HERE=$(cd "$(dirname "$0")" && pwd)
JAR=${ANDROID_JAR:-/root/sdk/android-34/android.jar}
R8_JAR=${R8_JAR:-/root/sdk/android-14/lib/d8.jar}
SIGNER_JAR=${SIGNER_JAR:-/root/sdk/android-14/lib/apksigner.jar}
OUT="$HERE/build"
KEYSTORE=${KEYSTORE:-$HERE/debug.keystore}
KS_PASS=${KS_PASS:-android}

for f in "$JAR" "$R8_JAR" "$SIGNER_JAR"; do
  [ -f "$f" ] || { echo "missing $f" >&2; exit 1; }
done
command -v aapt2 >/dev/null || { echo "aapt2 not on PATH" >&2; exit 1; }
command -v zipalign >/dev/null || { echo "zipalign not on PATH" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/res"

echo "== 1/7 aapt2 compile resources"
# -o must be a directory here; Debian's aapt2 rejects a file path.
aapt2 compile --dir "$HERE/res" -o "$OUT/res"

echo "== 2/7 aapt2 link (emits R.java + base.apk)"
aapt2 link \
  -o "$OUT/base.apk" \
  -I "$JAR" \
  --manifest "$HERE/AndroidManifest.xml" \
  --java "$OUT/classes" \
  --min-sdk-version 26 \
  --target-sdk-version 34 \
  "$OUT"/res/*.flat

echo "== 3/7 javac"
# android.jar goes on -classpath only. Putting it on -bootclasspath hides
# java.lang.invoke.LambdaMetafactory, which javac needs to compile the
# `v -> toggle()` listeners -- the error reads "cannot find symbol metafactory"
# and looks like a typo rather than a classpath problem.
javac -nowarn -encoding UTF-8 \
  -source 8 -target 8 \
  -classpath "$JAR" \
  -d "$OUT/classes" \
  $(find "$HERE/src" -name '*.java') \
  $(find "$OUT/classes" -name 'R.java') 2>&1 | grep -v 'bootstrap class path' || true

if [ ! -f "$OUT/classes/com/lcs/hud/HudService.class" ]; then
  echo "javac produced no classes -- refusing to ship an empty apk" >&2
  exit 1
fi

echo "== 4/7 d8 -> dex"
java -cp "$R8_JAR" com.android.tools.r8.D8 \
  --release --min-api 26 --lib "$JAR" \
  --output "$OUT/dex" \
  $(find "$OUT/classes" -name '*.class')

echo "== 5/7 package dex into the apk"
cp "$OUT/base.apk" "$OUT/unsigned.apk"
(cd "$OUT/dex" && zip -q -X "$OUT/unsigned.apk" classes.dex)

echo "== 6/7 zipalign"
zipalign -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"

echo "== 7/7 sign"
if [ ! -f "$KEYSTORE" ]; then
  echo "   generating debug keystore"
  keytool -genkeypair \
    -keystore "$KEYSTORE" -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -alias hud -keyalg RSA -keysize 2048 -validity 10000 \
    -dname "CN=LCS HUD, O=lcs, C=CN" >/dev/null 2>&1
fi

java -jar "$SIGNER_JAR" sign \
  --ks "$KEYSTORE" --ks-pass "pass:$KS_PASS" --key-pass "pass:$KS_PASS" \
  --min-sdk-version 26 \
  --out "$OUT/hud.apk" "$OUT/aligned.apk"

java -jar "$SIGNER_JAR" verify --min-sdk-version 26 "$OUT/hud.apk"

echo
echo "built: $OUT/hud.apk"
ls -l "$OUT/hud.apk"
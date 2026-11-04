#!/bin/bash
# Build the current sources, then install the resulting Debian package with APT.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ne 0 ]; then
    echo "Kullanım: $0"
    exit 1
fi

for command in python3 dpkg-deb apt sha256sum; do
    if ! command -v "$command" >/dev/null 2>&1; then
        echo "❌ Gerekli komut bulunamadı: $command" >&2
        exit 1
    fi
done
if [ "$EUID" -ne 0 ] && ! command -v sudo >/dev/null 2>&1; then
    echo "❌ Kurulum için sudo gerekli. Root oturumunda da çalıştırabilirsiniz." >&2
    exit 1
fi

# A fresh directory prevents an earlier release from being installed on failure.
mkdir -p "$SCRIPT_DIR/dist"
BUILD_OUTPUT="$(mktemp -d "$SCRIPT_DIR/dist/.build.XXXXXX")"
trap 'rm -rf -- "$BUILD_OUTPUT"' EXIT

echo "==> Güncel kaynaklardan Debian paketi oluşturuluyor..."
bash "$SCRIPT_DIR/packaging/build_deb.sh" "$BUILD_OUTPUT"

shopt -s nullglob
packages=("$BUILD_OUTPUT"/sourcedock_*_all.deb)
if [ "${#packages[@]}" -ne 1 ]; then
    echo "❌ Tam olarak bir SourceDock paketi oluşturulmalı; kurulum yapılmadı." >&2
    exit 1
fi

PACKAGE_NAME="$(basename "${packages[0]}")"
(
    cd "$BUILD_OUTPUT"
    sha256sum -c "$PACKAGE_NAME.sha256"
)
mv -- "$BUILD_OUTPUT/$PACKAGE_NAME" "$SCRIPT_DIR/dist/$PACKAGE_NAME"
mv -- "$BUILD_OUTPUT/$PACKAGE_NAME.sha256" "$SCRIPT_DIR/dist/$PACKAGE_NAME.sha256"

echo "==> Paket kuruluyor: $PACKAGE_NAME"
# --reinstall also applies source changes when the version has not changed.
# Leave APT's confirmation prompt enabled so dependency changes remain visible.
if [ "$EUID" -eq 0 ]; then
    apt install --reinstall "$SCRIPT_DIR/dist/$PACKAGE_NAME"
else
    sudo apt install --reinstall "$SCRIPT_DIR/dist/$PACKAGE_NAME"
fi

echo "✅ SourceDock paketi oluşturuldu ve kuruldu. Çalıştırmak için: sourcedock"

#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE="sourcedock"
VERSION="$(PYTHONPATH="$PROJECT_DIR" python3 -c 'from sourcedock.constants import APP_VERSION; print(APP_VERSION)')"
EXTENSION_UUID="sourcedock-menu@aliafacan.dev"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf -- "$BUILD_DIR"' EXIT
DEB_ROOT="$BUILD_DIR/${PACKAGE}_${VERSION}_all"
OUTPUT_DIR="${1:-$SCRIPT_DIR}"

echo "⚡ SourceDock .deb Paketi Hazırlanıyor (v$VERSION)..."

# 1. Dizin hiyerarşisi
mkdir -p "$DEB_ROOT/DEBIAN"
mkdir -p "$DEB_ROOT/usr/lib/$PACKAGE"
mkdir -p "$DEB_ROOT/usr/bin"
mkdir -p "$DEB_ROOT/usr/share/applications"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/64x64/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$DEB_ROOT/usr/share/gnome-shell/extensions/$EXTENSION_UUID"
mkdir -p "$DEB_ROOT/usr/share/metainfo"
mkdir -p "$DEB_ROOT/usr/share/doc/$PACKAGE"

# 2. Kaynak dosyaları kopyala
echo "==> Uygulama kaynak dosyaları kopyalanıyor..."
cp "$PROJECT_DIR/main.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/run.sh" ] && cp "$PROJECT_DIR/run.sh" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/constants.py" ] && cp "$PROJECT_DIR/constants.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/i18n.py" ] && cp "$PROJECT_DIR/i18n.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/preferences.py" ] && cp "$PROJECT_DIR/preferences.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/theme.py" ] && cp "$PROJECT_DIR/theme.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/applications.py" ] && cp "$PROJECT_DIR/applications.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/store.py" ] && cp "$PROJECT_DIR/store.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/backend.py" ] && cp "$PROJECT_DIR/backend.py" "$DEB_ROOT/usr/lib/$PACKAGE/"
[ -f "$PROJECT_DIR/ui.py" ] && cp "$PROJECT_DIR/ui.py" "$DEB_ROOT/usr/lib/$PACKAGE/"

# sourcedock/ paket modülleri
cp -r "$PROJECT_DIR/sourcedock" "$DEB_ROOT/usr/lib/$PACKAGE/"
find "$DEB_ROOT/usr/lib/$PACKAGE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$DEB_ROOT/usr/lib/$PACKAGE" -type f -name "*.pyc" -delete 2>/dev/null || true

# assets dizini
if [ -d "$PROJECT_DIR/assets" ]; then
    cp -r "$PROJECT_DIR/assets" "$DEB_ROOT/usr/lib/$PACKAGE/"
fi
cp "$PROJECT_DIR/LICENSE" "$DEB_ROOT/usr/share/doc/$PACKAGE/copyright"
cp "$SCRIPT_DIR/dev.aliafacan.SourceDock.metainfo.xml" "$DEB_ROOT/usr/share/metainfo/"

if [ -d "$PROJECT_DIR/sourcedock/desktop/extension" ]; then
    cp -r "$PROJECT_DIR/sourcedock/desktop/extension/." "$DEB_ROOT/usr/share/gnome-shell/extensions/$EXTENSION_UUID/"
fi

# 3. /usr/bin/sourcedock başlatıcı betiği
cat > "$DEB_ROOT/usr/bin/$PACKAGE" <<'LAUNCHER'
#!/bin/bash
exec /usr/bin/python3 /usr/lib/sourcedock/main.py "$@"
LAUNCHER
chmod 755 "$DEB_ROOT/usr/bin/$PACKAGE"

# Preserve the old terminal command during the package rename.
cat > "$DEB_ROOT/usr/bin/voltapp" <<'LEGACY_LAUNCHER'
#!/bin/bash
exec /usr/bin/sourcedock "$@"
LEGACY_LAUNCHER
chmod 755 "$DEB_ROOT/usr/bin/voltapp"

# 4. Masaüstü kısayolu & İkonlar
if [ -f "$SCRIPT_DIR/sourcedock.desktop" ]; then
    cp "$SCRIPT_DIR/sourcedock.desktop" "$DEB_ROOT/usr/share/applications/"
elif [ -f "$PROJECT_DIR/packaging/sourcedock.desktop" ]; then
    cp "$PROJECT_DIR/packaging/sourcedock.desktop" "$DEB_ROOT/usr/share/applications/"
fi

# Keep old MIME associations working without showing a duplicate menu entry.
cat > "$DEB_ROOT/usr/share/applications/voltapp.desktop" <<'LEGACY_DESKTOP'
[Desktop Entry]
Name=SourceDock
NoDisplay=true
Exec=/usr/bin/sourcedock %F
Icon=sourcedock
Terminal=false
Type=Application
MimeType=application/vnd.debian.binary-package;application/x-deb;application/x-debian-package;application/x-rpm;application/x-redhat-package-manager;application/x-appimage;application/vnd.appimage;application/vnd.flatpak;application/vnd.flatpak.ref;application/vnd.flatpak.repo;
LEGACY_DESKTOP

# Vektörel SVG ikon
if [ -f "$PROJECT_DIR/assets/sourcedock.svg" ]; then
    cp "$PROJECT_DIR/assets/sourcedock.svg" "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/sourcedock.svg"
fi

# PNG ikonlar
[ -f "$PROJECT_DIR/assets/sourcedock_48.png" ] && cp "$PROJECT_DIR/assets/sourcedock_48.png" "$DEB_ROOT/usr/share/icons/hicolor/48x48/apps/sourcedock.png"
[ -f "$PROJECT_DIR/assets/sourcedock_64.png" ] && cp "$PROJECT_DIR/assets/sourcedock_64.png" "$DEB_ROOT/usr/share/icons/hicolor/64x64/apps/sourcedock.png"
[ -f "$PROJECT_DIR/assets/sourcedock_128.png" ] && cp "$PROJECT_DIR/assets/sourcedock_128.png" "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps/sourcedock.png"
[ -f "$PROJECT_DIR/assets/sourcedock.png" ] && [ ! -f "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps/sourcedock.png" ] && cp "$PROJECT_DIR/assets/sourcedock.png" "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps/sourcedock.png"

# 5. DEBIAN/control
INSTALLED_SIZE="$(du -sk "$DEB_ROOT/usr" | awk '{print $1}')"
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Replaces: voltapp
Breaks: voltapp (<< 1.3.0)
Provides: voltapp
Section: utils
Priority: optional
Architecture: all
Installed-Size: $INSTALLED_SIZE
Depends: python3 (>= 3.10), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0
Suggests: flatpak, snapd, gnome-shell, fwupd
Maintainer: Ali Afacan <aliafacan.dev@gmail.com>
Homepage: https://github.com/aliafacan/SourceDock
Description: Linux application and package manager
 SourceDock is a modern, modular, and distro-agnostic Linux software management
 tool. It unifies APT/DNF/Pacman/Zypper native packages, Flatpak, Snap,
 AppImage, and portable software with standalone mini-installer preview,
 smart version detection, and dual-language (TR/EN) support.
EOF

# 6. DEBIAN/postinst
cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = "configure" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
    update-mime-database /usr/share/mime 2>/dev/null || true
    echo "SourceDock GNOME Shell right-click integration installed: sourcedock-menu@aliafacan.dev"
    echo "Enable it with: gnome-extensions enable sourcedock-menu@aliafacan.dev"
fi
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postinst"

# 7. DEBIAN/postrm
cat > "$DEB_ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
    update-mime-database /usr/share/mime 2>/dev/null || true
fi
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postrm"

# 8. İzinleri standartlaştır
echo "==> İzinler ayarlanıyor..."
find "$DEB_ROOT" -type d -exec chmod 755 {} +
find "$DEB_ROOT" -type f -exec chmod 644 {} +
find "$DEB_ROOT/usr/bin" -type f -exec chmod 755 {} +
chmod 755 "$DEB_ROOT/DEBIAN/postinst" "$DEB_ROOT/DEBIAN/postrm"
chmod 755 "$DEB_ROOT/DEBIAN"
chmod 644 "$DEB_ROOT/DEBIAN/control"

# 9. Paket oluşturma
mkdir -p "$OUTPUT_DIR"
DEB_OUT="$OUTPUT_DIR/${PACKAGE}_${VERSION}_all.deb"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DEB_ROOT/usr/share/applications/sourcedock.desktop"
fi
if command -v appstreamcli >/dev/null 2>&1; then
    appstreamcli validate --no-net "$DEB_ROOT/usr/share/metainfo/dev.aliafacan.SourceDock.metainfo.xml"
fi
echo "==> dpkg-deb çalıştırılıyor..."
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_OUT"
(
    cd "$OUTPUT_DIR"
    sha256sum "${PACKAGE}_${VERSION}_all.deb" > "${PACKAGE}_${VERSION}_all.deb.sha256"
)
if command -v lintian >/dev/null 2>&1; then
    lintian "$DEB_OUT"
fi

# 10. Temizlik & Bilgi
rm -rf "$BUILD_DIR"

echo "✅ Başarılı! .deb paketi oluşturuldu:"
echo "   $DEB_OUT"
ls -lh "$DEB_OUT"

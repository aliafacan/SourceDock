#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE="voltapp"
VERSION="$(grep -E '^APP_VERSION\s*=' "$PROJECT_DIR/voltapp/constants.py" 2>/dev/null | head -n1 | sed -E 's/.*"([^"]+)".*/\1/')"
[ -z "$VERSION" ] && VERSION="1.1.0"
BUILD_DIR="$(mktemp -d)"
DEB_ROOT="$BUILD_DIR/${PACKAGE}_${VERSION}_all"
OUTPUT_DIR="${1:-$SCRIPT_DIR}"

echo "⚡ VoltApp .deb Paketi Hazırlanıyor (v$VERSION)..."

# 1. Dizin hiyerarşisi
mkdir -p "$DEB_ROOT/DEBIAN"
mkdir -p "$DEB_ROOT/usr/lib/$PACKAGE"
mkdir -p "$DEB_ROOT/usr/bin"
mkdir -p "$DEB_ROOT/usr/share/applications"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/64x64/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps"

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

# voltapp/ paket modülleri
cp -r "$PROJECT_DIR/voltapp" "$DEB_ROOT/usr/lib/$PACKAGE/"
find "$DEB_ROOT/usr/lib/$PACKAGE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$DEB_ROOT/usr/lib/$PACKAGE" -type f -name "*.pyc" -delete 2>/dev/null || true

# assets dizini
if [ -d "$PROJECT_DIR/assets" ]; then
    cp -r "$PROJECT_DIR/assets" "$DEB_ROOT/usr/lib/$PACKAGE/"
fi

# 3. /usr/bin/voltapp başlatıcı betiği
cat > "$DEB_ROOT/usr/bin/$PACKAGE" <<'LAUNCHER'
#!/bin/bash
exec /usr/bin/python3 /usr/lib/voltapp/main.py "$@"
LAUNCHER
chmod 755 "$DEB_ROOT/usr/bin/$PACKAGE"

# 4. Masaüstü kısayolu & İkonlar
if [ -f "$SCRIPT_DIR/voltapp.desktop" ]; then
    cp "$SCRIPT_DIR/voltapp.desktop" "$DEB_ROOT/usr/share/applications/"
elif [ -f "$PROJECT_DIR/packaging/voltapp.desktop" ]; then
    cp "$PROJECT_DIR/packaging/voltapp.desktop" "$DEB_ROOT/usr/share/applications/"
fi

# Vektörel SVG ikon
if [ -f "$PROJECT_DIR/assets/voltapp.svg" ]; then
    cp "$PROJECT_DIR/assets/voltapp.svg" "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/voltapp.svg"
fi

# PNG ikonlar
[ -f "$PROJECT_DIR/assets/voltapp_48.png" ] && cp "$PROJECT_DIR/assets/voltapp_48.png" "$DEB_ROOT/usr/share/icons/hicolor/48x48/apps/voltapp.png"
[ -f "$PROJECT_DIR/assets/voltapp_64.png" ] && cp "$PROJECT_DIR/assets/voltapp_64.png" "$DEB_ROOT/usr/share/icons/hicolor/64x64/apps/voltapp.png"
[ -f "$PROJECT_DIR/assets/voltapp_128.png" ] && cp "$PROJECT_DIR/assets/voltapp_128.png" "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps/voltapp.png"
[ -f "$PROJECT_DIR/assets/voltapp.png" ] && [ ! -f "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps/voltapp.png" ] && cp "$PROJECT_DIR/assets/voltapp.png" "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps/voltapp.png"

# 5. DEBIAN/control
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0
Recommends: flatpak, snapd
Maintainer: Ali Afacan <aliafacan.dev@gmail.com>
Homepage: https://github.com/aliafacan/VoltApp
Description: VoltApp - Lightning-fast Unified Package and Application Manager
 VoltApp is a modern, modular, and distro-agnostic Linux software management
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
echo "==> dpkg-deb çalıştırılıyor..."
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_OUT"

# 10. Temizlik & Bilgi
rm -rf "$BUILD_DIR"

echo "✅ Başarılı! .deb paketi oluşturuldu:"
echo "   $DEB_OUT"
ls -lh "$DEB_OUT"

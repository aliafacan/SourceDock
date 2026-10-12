#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PACKAGE="zorin-app-manager"
VERSION="0.2.0"
BUILD_DIR="$(mktemp -d)"
DEB_ROOT="$BUILD_DIR/${PACKAGE}_${VERSION}_all"

echo "==> Paket dizini hazırlanıyor..."

# Directory structure
mkdir -p "$DEB_ROOT/DEBIAN"
mkdir -p "$DEB_ROOT/usr/lib/$PACKAGE"
mkdir -p "$DEB_ROOT/usr/bin"
mkdir -p "$DEB_ROOT/usr/share/applications"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/48x48/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/128x128/apps"
mkdir -p "$DEB_ROOT/usr/share/icons/hicolor/256x256/apps"

# Python source files
echo "==> Kaynak dosyalar kopyalanıyor..."
for f in main.py ui.py applications.py store.py backend.py constants.py i18n.py preferences.py theme.py; do
    [ -f "$PROJECT_DIR/$f" ] && cp "$PROJECT_DIR/$f" "$DEB_ROOT/usr/lib/$PACKAGE/"
done

# Launcher script
cat > "$DEB_ROOT/usr/bin/$PACKAGE" <<'LAUNCHER'
#!/bin/bash
exec /usr/bin/python3 /usr/lib/zorin-app-manager/main.py "$@"
LAUNCHER
chmod 755 "$DEB_ROOT/usr/bin/$PACKAGE"

# Desktop file & SVG icon
cp "$SCRIPT_DIR/$PACKAGE.desktop" "$DEB_ROOT/usr/share/applications/"
cp "$SCRIPT_DIR/$PACKAGE.svg"     "$DEB_ROOT/usr/share/icons/hicolor/scalable/apps/"

# PNG icon generation via Python + librsvg
echo "==> İkonlar oluşturuluyor..."
/usr/bin/python3 - "$SCRIPT_DIR/$PACKAGE.svg" "$DEB_ROOT" "$PACKAGE" <<'PYEOF'
import sys, gi
gi.require_version('Rsvg', '2.0')
from gi.repository import Rsvg
import cairo

svg_path, deb_root, pkg = sys.argv[1], sys.argv[2], sys.argv[3]
handle = Rsvg.Handle.new_from_file(svg_path)

for size in [48, 128, 256]:
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, size, size)
    ctx = cairo.Context(surface)
    vp = Rsvg.Rectangle()
    vp.x, vp.y, vp.width, vp.height = 0, 0, size, size
    handle.render_document(ctx, vp)
    out = f"{deb_root}/usr/share/icons/hicolor/{size}x{size}/apps/{pkg}.png"
    surface.write_to_png(out)
    print(f"   {size}x{size} OK")
PYEOF

# DEBIAN/control
cat > "$DEB_ROOT/DEBIAN/control" <<EOF
Package: $PACKAGE
Version: $VERSION
Section: admin
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, python3-gi-cairo, gir1.2-gtk-3.0, gir1.2-gdkpixbuf-2.0
Recommends: flatpak, snapd
Maintainer: Ali Afacan <aafacan1425@gmail.com>
Description: Zorin OS Uygulama Yöneticisi
 APT, Flatpak, Snap ve AppImage için birleşik uygulama yöneticisi.
EOF

# DEBIAN/postinst
cat > "$DEB_ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = "configure" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postinst"

# DEBIAN/postrm
cat > "$DEB_ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/bash
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor 2>/dev/null || true
fi
EOF
chmod 755 "$DEB_ROOT/DEBIAN/postrm"

# Build
echo "==> .deb oluşturuluyor..."
DEB_OUT="$SCRIPT_DIR/${PACKAGE}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$DEB_ROOT" "$DEB_OUT"

rm -rf "$BUILD_DIR"

echo ""
echo "✓ Paket hazır: $DEB_OUT"
echo ""
echo "Kurmak için:"
echo "  sudo dpkg -i $DEB_OUT"

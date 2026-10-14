#!/bin/bash
# ⚡ SourceDock — Kurulum Betiği (Global System Installer)
set -e

if [ "$EUID" -ne 0 ]; then
    echo "❌ Hata: Kurulum için root (yönetici) yetkisi gereklidir."
    echo "👉 Lütfen şu şekilde çalıştırın: sudo ./install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB="/usr/lib/sourcedock"
INSTALL_BIN="/usr/bin/sourcedock"
INSTALL_DESKTOP="/usr/share/applications/sourcedock.desktop"
LEGACY_BIN="/usr/bin/voltapp"
LEGACY_DESKTOP="/usr/share/applications/voltapp.desktop"
EXTENSION_UUID="sourcedock-menu@aliafacan.dev"
INSTALL_EXTENSION="/usr/share/gnome-shell/extensions/$EXTENSION_UUID"
if command -v dpkg-query >/dev/null 2>&1 && { [ "$(dpkg-query -W -f='${db:Status-Status}' sourcedock 2>/dev/null || true)" = "installed" ] || [ "$(dpkg-query -W -f='${db:Status-Status}' voltapp 2>/dev/null || true)" = "installed" ]; }; then
    echo "SourceDock is managed by APT. Build a .deb and install it with apt instead of overwriting package-owned files."
    exit 1
fi
if [ -L "$INSTALL_LIB" ] || [ -L "$INSTALL_EXTENSION" ]; then
    echo "Refusing to install through a symbolic link."
    exit 1
fi

echo "=========================================================="
echo "⚡ SourceDock Sistem Kurulumu Başlatılıyor..."
echo "=========================================================="

# 1. Bağımlılık kontrolü
echo "==> Bağımlılıklar denetleniyor..."
if ! command -v python3 &>/dev/null; then
    echo "❌ Hata: python3 bulunamadı. Lütfen Python 3 yükleyin."
    exit 1
fi

python3 -c "import gi; gi.require_version('Gtk', '3.0'); from gi.repository import Gtk" 2>/dev/null || {
    echo "⚠️  Uyarı: GTK 3 Python bağlamaları (python3-gi / gir1.2-gtk-3.0) eksik olabilir."
    echo "   Ubuntu/Debian için: sudo apt install python3-gi gir1.2-gtk-3.0"
}

# 2. Dizinleri oluştur
echo "==> Sistem dizinleri hazırlanıyor..."
mkdir -p "$INSTALL_LIB"
mkdir -p /usr/bin
mkdir -p /usr/share/applications
mkdir -p /usr/share/icons/hicolor/scalable/apps
mkdir -p /usr/share/icons/hicolor/48x48/apps
mkdir -p /usr/share/icons/hicolor/64x64/apps
mkdir -p /usr/share/icons/hicolor/128x128/apps
mkdir -p "$INSTALL_EXTENSION"

# 3. Dosyaları kopyala
echo "==> Dosyalar kopyalanıyor ($INSTALL_LIB)..."
rm -rf "$INSTALL_LIB/sourcedock" "$INSTALL_LIB/assets"
cp "$SCRIPT_DIR/main.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/run.sh" ] && cp "$SCRIPT_DIR/run.sh" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/constants.py" ] && cp "$SCRIPT_DIR/constants.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/i18n.py" ] && cp "$SCRIPT_DIR/i18n.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/preferences.py" ] && cp "$SCRIPT_DIR/preferences.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/theme.py" ] && cp "$SCRIPT_DIR/theme.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/applications.py" ] && cp "$SCRIPT_DIR/applications.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/store.py" ] && cp "$SCRIPT_DIR/store.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/backend.py" ] && cp "$SCRIPT_DIR/backend.py" "$INSTALL_LIB/"
[ -f "$SCRIPT_DIR/ui.py" ] && cp "$SCRIPT_DIR/ui.py" "$INSTALL_LIB/"

cp -r "$SCRIPT_DIR/sourcedock" "$INSTALL_LIB/"
find "$INSTALL_LIB" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_LIB" -type f -name "*.pyc" -delete 2>/dev/null || true

if [ -d "$SCRIPT_DIR/assets" ]; then
    cp -r "$SCRIPT_DIR/assets" "$INSTALL_LIB/"
fi

if [ -d "$SCRIPT_DIR/sourcedock/desktop/extension" ]; then
    echo "==> Ubuntu/Zorin uygulama menüsü sağ tık entegrasyonu kuruluyor..."
    cp -r "$SCRIPT_DIR/sourcedock/desktop/extension/." "$INSTALL_EXTENSION/"
fi

# 4. /usr/bin/sourcedock başlatıcı
cat > "$INSTALL_BIN" <<'LAUNCHER'
#!/bin/bash
exec /usr/bin/python3 /usr/lib/sourcedock/main.py "$@"
LAUNCHER
chmod 755 "$INSTALL_BIN"

# Keep existing scripts, MIME handlers and user muscle memory working.
cat > "$LEGACY_BIN" <<'LAUNCHER'
#!/bin/bash
exec /usr/bin/sourcedock "$@"
LAUNCHER
chmod 755 "$LEGACY_BIN"

# 5. Masaüstü kısayolu & İkonlar
if [ -f "$SCRIPT_DIR/packaging/sourcedock.desktop" ]; then
    cp "$SCRIPT_DIR/packaging/sourcedock.desktop" "$INSTALL_DESKTOP"
fi
cat > "$LEGACY_DESKTOP" <<'DESKTOP'
[Desktop Entry]
Name=SourceDock
NoDisplay=true
Exec=/usr/bin/sourcedock %F
Icon=sourcedock
Terminal=false
Type=Application
MimeType=application/vnd.debian.binary-package;application/x-deb;application/x-debian-package;application/x-rpm;application/x-redhat-package-manager;application/x-appimage;application/vnd.appimage;application/vnd.flatpak;application/vnd.flatpak.ref;application/vnd.flatpak.repo;
DESKTOP

[ -f "$SCRIPT_DIR/assets/sourcedock.svg" ] && cp "$SCRIPT_DIR/assets/sourcedock.svg" /usr/share/icons/hicolor/scalable/apps/sourcedock.svg
[ -f "$SCRIPT_DIR/assets/sourcedock_48.png" ] && cp "$SCRIPT_DIR/assets/sourcedock_48.png" /usr/share/icons/hicolor/48x48/apps/sourcedock.png
[ -f "$SCRIPT_DIR/assets/sourcedock_64.png" ] && cp "$SCRIPT_DIR/assets/sourcedock_64.png" /usr/share/icons/hicolor/64x64/apps/sourcedock.png
[ -f "$SCRIPT_DIR/assets/sourcedock_128.png" ] && cp "$SCRIPT_DIR/assets/sourcedock_128.png" /usr/share/icons/hicolor/128x128/apps/sourcedock.png
[ -f "$SCRIPT_DIR/assets/sourcedock.png" ] && [ ! -f /usr/share/icons/hicolor/128x128/apps/sourcedock.png ] && cp "$SCRIPT_DIR/assets/sourcedock.png" /usr/share/icons/hicolor/128x128/apps/sourcedock.png

# İzinleri ayarla
find "$INSTALL_LIB" -type d -exec chmod 755 {} +
find "$INSTALL_LIB" -type f -exec chmod 644 {} +
chmod 755 "$INSTALL_LIB/main.py"
touch "$INSTALL_LIB/.sourcedock-manual-install"
[ -f "$INSTALL_LIB/run.sh" ] && chmod 755 "$INSTALL_LIB/run.sh"
if [ -d "$INSTALL_EXTENSION" ]; then
    find "$INSTALL_EXTENSION" -type d -exec chmod 755 {} +
    find "$INSTALL_EXTENSION" -type f -exec chmod 644 {} +
fi

# 6. Sistem veritabanlarını yenile
echo "==> Masaüstü ve ikon önbelleği güncelleniyor..."
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
update-mime-database /usr/share/mime 2>/dev/null || true

if [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != "root" ] && command -v gnome-extensions &>/dev/null; then
    TARGET_UID="$(id -u "$SUDO_USER" 2>/dev/null || true)"
    if [ -n "$TARGET_UID" ] && [ -S "/run/user/$TARGET_UID/bus" ] && command -v runuser &>/dev/null; then
        runuser -u "$SUDO_USER" -- env \
            XDG_RUNTIME_DIR="/run/user/$TARGET_UID" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$TARGET_UID/bus" \
            gnome-extensions enable "$EXTENSION_UUID" 2>/dev/null || true
    fi
fi

echo "=========================================================="
echo "⚡ SourceDock başarıyla kuruldu!"
echo "   Terminalden çalıştırmak için : sourcedock"
echo "   Belirli paket kurmak için    : sourcedock /yol/paket.deb"
echo "   Uygulama menüsünden          : 'SourceDock' olarak aratabilirsiniz."
echo "   Sağ tık entegrasyonu         : $EXTENSION_UUID"
echo "   Görünmüyorsa oturumu kapatıp açın ve 'gnome-extensions enable $EXTENSION_UUID' çalıştırın."
echo "=========================================================="


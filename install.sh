#!/bin/bash
# ⚡ VoltApp — Kurulum Betiği (Global System Installer)
set -e

if [ "$EUID" -ne 0 ]; then
    echo "❌ Hata: Kurulum için root (yönetici) yetkisi gereklidir."
    echo "👉 Lütfen şu şekilde çalıştırın: sudo ./install.sh"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB="/usr/lib/voltapp"
INSTALL_BIN="/usr/bin/voltapp"
INSTALL_DESKTOP="/usr/share/applications/voltapp.desktop"

echo "=========================================================="
echo "⚡ VoltApp Sistem Kurulumu Başlatılıyor..."
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

# 3. Dosyaları kopyala
echo "==> Dosyalar kopyalanıyor ($INSTALL_LIB)..."
rm -rf "$INSTALL_LIB"/*
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

cp -r "$SCRIPT_DIR/voltapp" "$INSTALL_LIB/"
find "$INSTALL_LIB" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$INSTALL_LIB" -type f -name "*.pyc" -delete 2>/dev/null || true

if [ -d "$SCRIPT_DIR/assets" ]; then
    cp -r "$SCRIPT_DIR/assets" "$INSTALL_LIB/"
fi

# 4. /usr/bin/voltapp başlatıcı
cat > "$INSTALL_BIN" <<'LAUNCHER'
#!/bin/bash
exec /usr/bin/python3 /usr/lib/voltapp/main.py "$@"
LAUNCHER
chmod 755 "$INSTALL_BIN"

# 5. Masaüstü kısayolu & İkonlar
if [ -f "$SCRIPT_DIR/packaging/voltapp.desktop" ]; then
    cp "$SCRIPT_DIR/packaging/voltapp.desktop" "$INSTALL_DESKTOP"
fi

[ -f "$SCRIPT_DIR/assets/voltapp.svg" ] && cp "$SCRIPT_DIR/assets/voltapp.svg" /usr/share/icons/hicolor/scalable/apps/voltapp.svg
[ -f "$SCRIPT_DIR/assets/voltapp_48.png" ] && cp "$SCRIPT_DIR/assets/voltapp_48.png" /usr/share/icons/hicolor/48x48/apps/voltapp.png
[ -f "$SCRIPT_DIR/assets/voltapp_64.png" ] && cp "$SCRIPT_DIR/assets/voltapp_64.png" /usr/share/icons/hicolor/64x64/apps/voltapp.png
[ -f "$SCRIPT_DIR/assets/voltapp_128.png" ] && cp "$SCRIPT_DIR/assets/voltapp_128.png" /usr/share/icons/hicolor/128x128/apps/voltapp.png
[ -f "$SCRIPT_DIR/assets/voltapp.png" ] && [ ! -f /usr/share/icons/hicolor/128x128/apps/voltapp.png ] && cp "$SCRIPT_DIR/assets/voltapp.png" /usr/share/icons/hicolor/128x128/apps/voltapp.png

# İzinleri ayarla
find "$INSTALL_LIB" -type d -exec chmod 755 {} +
find "$INSTALL_LIB" -type f -exec chmod 644 {} +
chmod 755 "$INSTALL_LIB/main.py"
[ -f "$INSTALL_LIB/run.sh" ] && chmod 755 "$INSTALL_LIB/run.sh"

# 6. Sistem veritabanlarını yenile
echo "==> Masaüstü ve ikon önbelleği güncelleniyor..."
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
update-mime-database /usr/share/mime 2>/dev/null || true

echo "=========================================================="
echo "⚡ VoltApp başarıyla kuruldu!"
echo "   Terminalden çalıştırmak için : voltapp"
echo "   Belirli paket kurmak için    : voltapp /yol/paket.deb"
echo "   Uygulama menüsünden          : 'VoltApp' olarak aratabilirsiniz."
echo "=========================================================="


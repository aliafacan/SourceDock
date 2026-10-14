#!/bin/bash
# ⚡ SourceDock — Sistemden Kaldırma Betiği (Uninstaller)
set -e

if [ "$EUID" -ne 0 ]; then
    echo "❌ Hata: Kaldırma işlemi için root (yönetici) yetkisi gereklidir."
    echo "👉 Lütfen şu şekilde çalıştırın: sudo ./uninstall.sh"
    exit 1
fi

if command -v dpkg-query >/dev/null 2>&1 && [ "$(dpkg-query -W -f='${db:Status-Status}' sourcedock 2>/dev/null || true)" = "installed" ]; then
    exec apt-get remove -- sourcedock
fi
if command -v dpkg-query >/dev/null 2>&1 && [ "$(dpkg-query -W -f='${db:Status-Status}' voltapp 2>/dev/null || true)" = "installed" ]; then
    exec apt-get remove -- voltapp
fi
if [ -f /usr/lib/voltapp/.voltapp-manual-install ]; then
    echo "Legacy VoltApp manual installation detected; removing its compatibility files."
    rm -rf /usr/lib/voltapp
    rm -f /usr/bin/voltapp /usr/share/applications/voltapp.desktop
    rm -rf /usr/share/gnome-shell/extensions/voltapp-menu@aliafacan.dev
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
    gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
    update-mime-database -q /usr/share/mime 2>/dev/null || true
    echo "✓ Legacy VoltApp manual installation removed."
    exit 0
fi
if [ -L /usr/lib/sourcedock ] || [ ! -f /usr/lib/sourcedock/.sourcedock-manual-install ]; then
    echo "No verified manual installation was found. Use APT for a .deb installation."
    exit 1
fi

echo "=========================================================="
echo "⚡ SourceDock Sistemden Kaldırılıyor..."
echo "=========================================================="

rm -rf /usr/lib/sourcedock
rm -f /usr/bin/sourcedock /usr/bin/voltapp
rm -f /usr/share/applications/sourcedock.desktop /usr/share/applications/voltapp.desktop
rm -f /usr/share/icons/hicolor/scalable/apps/sourcedock.svg
rm -f /usr/share/icons/hicolor/48x48/apps/sourcedock.png
rm -f /usr/share/icons/hicolor/64x64/apps/sourcedock.png
rm -f /usr/share/icons/hicolor/128x128/apps/sourcedock.png
rm -rf /usr/share/gnome-shell/extensions/sourcedock-menu@aliafacan.dev

echo "==> Önbellekler yenileniyor..."
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
update-mime-database /usr/share/mime 2>/dev/null || true

echo "=========================================================="
echo "✓ SourceDock sisteminizden başarıyla kaldırıldı."
echo "=========================================================="


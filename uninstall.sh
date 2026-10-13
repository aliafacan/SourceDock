#!/bin/bash
# ⚡ VoltApp — Sistemden Kaldırma Betiği (Uninstaller)
set -e

if [ "$EUID" -ne 0 ]; then
    echo "❌ Hata: Kaldırma işlemi için root (yönetici) yetkisi gereklidir."
    echo "👉 Lütfen şu şekilde çalıştırın: sudo ./uninstall.sh"
    exit 1
fi

echo "=========================================================="
echo "⚡ VoltApp Sistemden Kaldırılıyor..."
echo "=========================================================="

rm -rf /usr/lib/voltapp
rm -f /usr/bin/voltapp
rm -f /usr/share/applications/voltapp.desktop
rm -f /usr/share/icons/hicolor/scalable/apps/voltapp.svg
rm -f /usr/share/icons/hicolor/48x48/apps/voltapp.png
rm -f /usr/share/icons/hicolor/64x64/apps/voltapp.png
rm -f /usr/share/icons/hicolor/128x128/apps/voltapp.png

echo "==> Önbellekler yenileniyor..."
update-desktop-database -q /usr/share/applications 2>/dev/null || true
gtk-update-icon-cache -q -f -t /usr/share/icons/hicolor 2>/dev/null || true
update-mime-database /usr/share/mime 2>/dev/null || true

echo "=========================================================="
echo "✓ VoltApp sisteminizden başarıyla kaldırıldı."
echo "=========================================================="


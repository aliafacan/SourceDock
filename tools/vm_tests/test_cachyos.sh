#!/usr/bin/env bash
# tools/vm_tests/test_cachyos.sh
# CachyOS / Arch Linux (KDE Plasma / Pacman) Test Script
set -e

echo "=== [CachyOS / Arch] SourceDock Test Suite Başlatılıyor ==="

# 1. Bağımlılık kontrolü ve kurulum
echo "--> [1/5] Bağımlılıklar denetleniyor/kuruluyor..."
sudo pacman -Sy --noconfirm --needed \
    python \
    python-gobject \
    gtk3 \
    gtk4 \
    libadwaita \
    flatpak \
    polkit \
    desktop-file-utils \
    appstream \
    xorg-server-xvfb \
    python-pytest

# 2. Ortam bilgileri
echo "--> [2/5] Sistem Bilgileri:"
echo "    Dağıtım: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "    Masaüstü: ${XDG_CURRENT_DESKTOP:-Bilinmiyor}"
echo "    Oturum Tipi: ${XDG_SESSION_TYPE:-Headless}"
echo "    Pacman: $(pacman -V | head -n 1)"
echo "    Flatpak: $(flatpak --version 2>/dev/null || echo 'Yok')"

# 3. Python Kod Doğrulama & Birim Testleri
echo "--> [3/5] Python sözdizimi ve derleme testi..."
python3 -m compileall -q main.py sourcedock tests tools

echo "--> [3.1/5] Birim testleri koşturuluyor..."
if command -v pytest &>/dev/null; then
    pytest tests/ -v -k "not test_live_audit_hook"
else
    python3 -m unittest discover -s tests -p "test_*.py"
fi

# 4. Masaüstü & AppStream Doğrulama
echo "--> [4/5] Masaüstü entegrasyon dosyaları kontrol ediliyor..."
if [ -f "packaging/sourcedock.desktop" ]; then
    desktop-file-validate packaging/sourcedock.desktop && echo "    desktop-file: GEÇTİ"
fi

# 5. UI Başlatma / Smoke Testi
echo "--> [5/5] UI duman (smoke) testi yapılıyor (10 sn)..."
if [ -n "$DISPLAY" ] || [ -n "$WAYLAND_DISPLAY" ]; then
    timeout 10s python3 main.py || [ $? -eq 124 ]
    echo "    KDE altında UI başarıyla başlatıldı ve kapatıldı."
else
    echo "    Grafik ortam bulunamadı, Xvfb ile deneniyor..."
    xvfb-run -a timeout 10s python3 main.py || [ $? -eq 124 ]
    echo "    UI (Xvfb) başarıyla başlatıldı ve kapatıldı."
fi

echo "=== [CachyOS / Arch] Tüm testler tamamlandı! ==="


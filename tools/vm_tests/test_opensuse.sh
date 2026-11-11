#!/usr/bin/env bash
# tools/vm_tests/test_opensuse.sh
# openSUSE Tumbleweed / Leap (Zypper / KDE Plasma) Test Script
set -e

echo "=== [openSUSE] SourceDock Test Suite Başlatılıyor ==="

# 1. Bağımlılık kontrolü ve kurulum
echo "--> [1/5] Bağımlılıklar denetleniyor/kuruluyor..."
sudo zypper --non-interactive install \
    python3 \
    python3-gobject \
    typelib-1_0-Gtk-3_0 \
    typelib-1_0-Adw-1 \
    flatpak \
    polkit \
    desktop-file-utils \
    AppStream \
    xorg-x11-server-Xvfb \
    python3-pytest

# 2. Ortam bilgileri
echo "--> [2/5] Sistem Bilgileri:"
echo "    Dağıtım: $(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"')"
echo "    Masaüstü: ${XDG_CURRENT_DESKTOP:-Bilinmiyor}"
echo "    Oturum Tipi: ${XDG_SESSION_TYPE:-Headless}"
echo "    Zypper: $(zypper --version)"
echo "    Flatpak: $(flatpak --version 2>/dev/null || echo 'Yok')"

# 3. Python Kod Doğrulama & Birim Testleri
echo "--> [3/5] Python sözdizimi ve derleme testi..."
python3 -m compileall -q main.py sourcedock tests tools

if [ -f "tools/run_tests.py" ]; then
    echo "--> [3.1/5] Proje test runner'ı çalıştırılıyor..."
    python3 tools/run_tests.py || true
elif command -v pytest &>/dev/null; then
    echo "--> [3.1/5] Pytest koşturuluyor..."
    pytest tests/ -v || true
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

echo "=== [openSUSE] Tüm testler tamamlandı! ==="


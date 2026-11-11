#!/usr/bin/env bash
# tools/vm_tests/serve_bundle.sh
# Ana makinede çalıştırılır: Projeyi paketler ve VM'lerin çekebileceği bir HTTP sunucusu açar.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$ROOT_DIR/dist/vm_transfer"

mkdir -p "$DIST_DIR"

echo "=== SourceDock VM Transfer Paketi Hazırlanıyor ==="
BUNDLE_ZIP="$DIST_DIR/sourcedock_test_bundle.zip"

# Git repository durumunu temiz arşivle (veya doğrudan klasörü zip'le)
if command -v git &>/dev/null && [ -d "$ROOT_DIR/.git" ]; then
    echo "Git arşivi oluşturuluyor..."
    (cd "$ROOT_DIR" && git archive --format=zip HEAD -o "$BUNDLE_ZIP")
    # tools/vm_tests scriptlerini de içine ekle
    (cd "$ROOT_DIR" && zip -u "$BUNDLE_ZIP" tools/vm_tests/*.sh)
else
    echo "Dizin doğrudan sıkıştırılıyor..."
    (cd "$ROOT_DIR" && zip -r -q "$BUNDLE_ZIP" . -x "*.git*" "*__pycache__*" "*.pytest_cache*")
fi

# Ana makinenin yerel IP adresini bul
LOCAL_IP=$(hostname -I | awk '{print $1}')
PORT=8888

echo ""
echo "================================================================="
echo " Paketlenmiş dosya hazır: $BUNDLE_ZIP"
echo " HTTP Sunucusu başlatılıyor..."
echo " VM içinden çekmek için şu komutu çalıştırabilirsin:"
echo ""
echo "   curl -O http://${LOCAL_IP}:${PORT}/sourcedock_test_bundle.zip"
echo "   unzip sourcedock_test_bundle.zip -d sourcedock"
echo "   cd sourcedock"
echo "   bash tools/vm_tests/test_<dagitim>.sh"
echo "================================================================="
echo ""

cd "$DIST_DIR"
python3 -m http.server "$PORT"


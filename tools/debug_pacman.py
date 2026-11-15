#!/usr/bin/env python3
import sys
import os
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sourcedock.core.runner import CommandRunner
from sourcedock.backend.scanner import DesktopEntryScanner
from sourcedock.backend.pacman import PacmanProvider

def main():
    print("=== Pacman / CachyOS Teşhis Başlatılıyor ===")
    runner = CommandRunner()
    scanner = DesktopEntryScanner(runner)
    provider = PacmanProvider(runner, scanner)

    desktop_entries = scanner.list_entries(
        ["/usr/share/applications", os.path.expanduser("~/.local/share/applications")]
    )
    print(f"1. Bulunan toplam .desktop dosyası: {len(desktop_entries)}")

    paths = [e.path for e in desktop_entries if e.visible]
    print(f"2. Görünür .desktop dosyası: {len(paths)}")

    if paths:
        sample = paths[0]
        res = runner.run(["pacman", "-Qo", sample])
        print(f"3. Örnek pacman -Qo '{sample}' sonucu:")
        print(f"   Exit code: {res.returncode}")
        print(f"   Stdout: {res.stdout.strip()}")
        print(f"   Stderr: {res.stderr.strip()}")

    apps = provider.list_applications()
    print(f"4. Sonuç: PacmanProvider tarafından döndürülen uygulama sayısı: {len(apps)}")

if __name__ == "__main__":
    main()


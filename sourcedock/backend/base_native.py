#!/usr/bin/env python3
"""Yerel paket yöneticileri (APT, DNF, Pacman, Zypper) için ortak soyutlama tabanı."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from sourcedock.core.models import (
    PackageInfo,
    StoreResult,
    UnifiedApplication,
)

if TYPE_CHECKING:
    from sourcedock.core.runner import CommandRunner
    from sourcedock.backend.scanner import DesktopEntryScanner


class BaseNativeProvider(ABC):
    """Tüm yerel Linux paket yöneticisi sağlayıcılarının uygulaması gereken ortak arayüz."""

    source: str = "native"
    display_name: str = "Native"

    def __init__(self, runner: CommandRunner, scanner: DesktopEntryScanner | None = None):
        self.runner = runner
        self.scanner = scanner
        self._hidden_upgradable: set[str] = set()

    @abstractmethod
    def is_available(self) -> bool:
        """Paket yöneticisi araçlarının sistemde mevcut olup olmadığını döndürür."""
        pass

    @abstractmethod
    def list_applications(self) -> list[UnifiedApplication]:
        """Yerel paket yöneticisiyle kurulmuş grafik (masaüstü) uygulamalarını listeler."""
        pass

    @abstractmethod
    def list_all_packages(self) -> list[PackageInfo]:
        """Sistemde kurulu tüm paketleri (kütüphaneler, CLI araçları dahil) listeler."""
        pass

    @abstractmethod
    def search_store(self, query: str) -> list[StoreResult]:
        """Uzak repolardan paket araması yapar."""
        pass

    @abstractmethod
    def install_command(self, package: str) -> list[str]:
        """Paket kurulum komutunu döndürür."""
        pass

    @abstractmethod
    def update_command(self, package: str) -> list[str]:
        """Tek bir paketi güncelleme komutunu döndürür."""
        pass

    @abstractmethod
    def update_all_command(self) -> list[str]:
        """Tüm sistemi güncelleme komutunu döndürür."""
        pass

    @abstractmethod
    def remove_command(self, package: str, purge: bool = False) -> list[str]:
        """Paket kaldırma komutunu döndürür."""
        pass

    @abstractmethod
    def refresh_cache_command(self) -> list[str]:
        """Repo metaverilerini yenileme komutunu döndürür."""
        pass

    def get_lock_holders(self) -> list[tuple[str, str]]:
        """Veritabanı kilidini tutan işlem listesini (pid, komut) döndürür."""
        return []

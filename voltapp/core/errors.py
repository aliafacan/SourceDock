#!/usr/bin/env python3
"""VoltApp hata ve istisna sınıfları."""

from __future__ import annotations


class BackendError(RuntimeError):
    """Genel VoltApp arka uç veya komut hatası."""


class AuthRequiredError(BackendError):
    """Ayrıcalıklı (sudo) işlem için parola gerekiyor."""

    def __init__(self, message: str, password_failed: bool = False):
        super().__init__(message)
        self.password_failed = password_failed


class SnapClassicRequiredError(BackendError):
    """Snap kurulumu için --classic bayrağı gerekiyor."""

    def __init__(self, message: str, package_name: str = ""):
        super().__init__(message)
        self.package_name = package_name

#!/usr/bin/env python3
"""Geriye dönük uyumluluk için re-export."""

from sourcedock.core.errors import AuthRequiredError, BackendError, SnapClassicRequiredError

__all__ = ["AuthRequiredError", "BackendError", "SnapClassicRequiredError"]

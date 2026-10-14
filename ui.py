#!/usr/bin/env python3
"""Geriye dönük uyumluluk için ui re-export."""

from sourcedock.ui.window import MainWindow as AppManagerWindow
from sourcedock.ui.components.progress import OperationProgressWindow
from sourcedock.ui.components.dialogs import AppDetailDialog

__all__ = ["AppManagerWindow", "OperationProgressWindow", "AppDetailDialog"]

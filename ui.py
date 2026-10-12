#!/usr/bin/env python3
"""Geriye dönük uyumluluk için ui re-export."""

from voltapp.ui.window import MainWindow as AppManagerWindow
from voltapp.ui.components.progress import OperationProgressWindow
from voltapp.ui.components.dialogs import AppDetailDialog

__all__ = ["AppManagerWindow", "OperationProgressWindow", "AppDetailDialog"]

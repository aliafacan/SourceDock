#!/bin/bash
# VS Code snap terminalinden çalıştırıldığında snap kütüphanelerini devre dışı bırakır.
cd "$(dirname "$0")"
exec env \
  GTK_PATH="" \
  GTK3_MODULES="" \
  GTK_EXE_PREFIX="" \
  GTK_IM_MODULE_FILE="" \
  GDK_PIXBUF_MODULEDIR="" \
  GDK_PIXBUF_MODULE_FILE="" \
  GIO_MODULE_DIR="" \
  python3 main.py "$@"

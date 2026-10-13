#!/bin/bash
# VS Code snap terminalinden çalıştırıldığında snap kütüphanelerini devre dışı bırakır.
cd "$(dirname "$0")"

# Snap GTK ve XDG ortam değişkenlerini temizle
unset GTK_PATH GTK3_MODULES GTK_EXE_PREFIX GTK_IM_MODULE_FILE \
      GDK_PIXBUF_MODULEDIR GDK_PIXBUF_MODULE_FILE GIO_MODULE_DIR \
      GSETTINGS_SCHEMA_DIR LOCPATH

[ -n "$XDG_DATA_HOME" ] && [[ "$XDG_DATA_HOME" == *"/snap/"* ]] && unset XDG_DATA_HOME
[ -n "$XDG_CONFIG_HOME" ] && [[ "$XDG_CONFIG_HOME" == *"/snap/"* ]] && unset XDG_CONFIG_HOME
[ -n "$XDG_CACHE_HOME" ] && [[ "$XDG_CACHE_HOME" == *"/snap/"* ]] && unset XDG_CACHE_HOME

# LD_LIBRARY_PATH içindeki snap yollarını filtrele
if [ -n "$LD_LIBRARY_PATH" ]; then
    CLEAN_LD=""
    IFS=':' read -ra ADDR <<< "$LD_LIBRARY_PATH"
    for i in "${ADDR[@]}"; do
        if [[ "$i" != *"/snap/"* ]]; then
            CLEAN_LD="${CLEAN_LD:+$CLEAN_LD:}$i"
        fi
    done
    export LD_LIBRARY_PATH="$CLEAN_LD"
fi

exec python3 main.py "$@"

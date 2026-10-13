#!/usr/bin/env python3
"""GTK CSS temaları."""


def get_theme_css(theme_name: str, scale: str = "100") -> str:
    scale_fonts = {
        "90": "9.5pt",
        "100": "10.5pt",
        "110": "11.5pt",
        "125": "13.0pt",
    }
    font_size = scale_fonts.get(scale, "10.5pt")

    palettes = {
        "dark": {
            "window_bg": "#1a1e24",
            "surface": "#222730",
            "surface_alt": "#2b323d",
            "surface_soft": "#1e232b",
            "card_bg": "#252c36",
            "card_hover": "#303947",
            "text": "#e8f1f7",
            "muted": "#9fb0bc",
            "border": "#36414e",
            "accent": "#f5b759",  # Canlı Volt elektrik sarısı
            "accent_secondary": "#63b3ed",
            "success": "#59d38c",
            "accent_text": "#11141a",  # Sarı üzerinde yüksek kontrastlı koyu metin
            "danger": "#ff7f7f",
            "danger_text": "#2f0e0e",
            "input_bg": "#14171c",
            "input_border": "#434f5e",
        },
        "light": {
            "window_bg": "#f4f7fb",
            "surface": "#ffffff",
            "surface_alt": "#e8eff7",
            "surface_soft": "#f8faff",
            "card_bg": "#edf3f9",
            "card_hover": "#dbe7f3",
            "text": "#173041",
            "muted": "#5f7483",
            "border": "#c8d6e3",
            "accent": "#e0af68",  # Amber elektrik
            "accent_secondary": "#3b82f6",
            "success": "#41b86f",
            "accent_text": "#1a1e24",
            "danger": "#ff9d9d",
            "danger_text": "#4b1616",
            "input_bg": "#ffffff",
            "input_border": "#9fb6c8",
        },
    }
    colors = palettes.get(theme_name, palettes["dark"])
    return f"""
* {{
    font-size: {font_size};
}}

/* Pencereler ve Diyaloglar */
window,
dialog,
messagedialog,
.icon-settings-window {{
    background-color: {colors['window_bg']};
    color: {colors['text']};
}}

window box,
dialog box,
messagedialog box {{
    color: {colors['text']};
}}

/* Pencere Başlık Çubuğu (Titlebar / HeaderBar) */
headerbar,
.titlebar {{
    background-color: {colors['surface']};
    color: {colors['text']};
    border-bottom: 1px solid {colors['border']};
}}

headerbar label,
.titlebar label,
headerbar label.title,
.titlebar label.title {{
    color: {colors['text']};
    font-weight: bold;
}}

headerbar label.subtitle,
.titlebar label.subtitle {{
    color: {colors['muted']};
}}

/* Diyalog İçerik ve Buton Alanları */
dialog > box,
dialog content-area {{
    background-color: {colors['window_bg']};
    color: {colors['text']};
}}

dialog .dialog-action-area,
dialog .action-area,
messagedialog .dialog-action-area,
messagedialog .action-area {{
    background-color: {colors['surface_soft']};
    border-top: 1px solid {colors['border']};
    padding: 10px;
}}

/* Sağ Tık Menüleri ve Açılır Menüler (Gtk.Menu, Gtk.MenuItem) */
menu,
.menu {{
    background-color: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: 8px;
    padding: 6px;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.15);
}}

menu menuitem,
.menu menuitem {{
    background: transparent;
    color: {colors['text']};
    padding: 6px 14px;
    border-radius: 6px;
    min-height: 26px;
}}

menu menuitem:hover,
.menu menuitem:hover {{
    background-color: {colors['surface_alt']};
    color: {colors['text']};
}}

menu menuitem:selected,
.menu menuitem:selected {{
    background-color: {colors['accent']};
    color: {colors['accent_text']};
}}

menu menuitem label,
.menu menuitem label {{
    color: inherit;
}}

menu separator,
.menu separator {{
    background-color: {colors['border']};
    min-height: 1px;
    margin: 4px 0;
}}

/* Popover */
popover,
.popover {{
    background-color: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: 8px;
    padding: 8px;
}}

/* Etiketler ve Ayırıcılar */
separator {{
    background-color: {colors['border']};
}}

label {{
    color: {colors['text']};
}}

.dim-label {{
    color: {colors['muted']};
}}

/* Butonlar */
button {{
    background: {colors['surface_alt']};
    color: {colors['text']};
    border-radius: 12px;
    border: 1px solid {colors['border']};
    box-shadow: none;
    padding: 8px 16px;
}}

button label {{
    color: inherit;
}}

button:hover {{
    background: {colors['surface']};
}}

button.suggested-action,
button.suggested-action label,
button.suggested-action image,
button.suggested-action box {{
    background-color: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
    font-weight: bold;
}}

button.suggested-action:hover,
button.suggested-action:hover label {{
    background-color: shade({colors['accent']}, 1.12);
    color: {colors['accent_text']};
}}

button.destructive-action,
button.destructive-action label {{
    background-color: {colors['danger']};
    color: {colors['danger_text']};
    border-color: {colors['danger']};
    font-weight: bold;
}}

button.outline-accent,
button.outline-accent label {{
    background: transparent;
    color: {colors['accent']};
    border-color: {colors['accent']};
    font-weight: bold;
}}

button.outline-danger,
button.outline-danger label {{
    background: transparent;
    color: {colors['danger']};
    border-color: {colors['danger']};
}}

button.header-action {{
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 0;
    min-width: 0;
}}

button.filter-chip {{
    border-radius: 999px;
    padding: 5px 12px;
    min-height: 0;
}}

button.filter-chip label {{
    color: {colors['muted']};
}}

button.filter-chip:hover label {{
    color: {colors['text']};
}}

button.filter-chip:checked,
button.filter-chip:checked label {{
    background-color: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
    font-weight: bold;
}}

button.compact-action {{
    padding: 7px 14px;
    min-height: 0;
    min-width: 0;
}}

/* Girdi Alanları */
entry {{
    background: {colors['input_bg']};
    color: {colors['text']};
    border-radius: 10px;
    border: 1px solid {colors['input_border']};
    padding: 6px 10px;
}}

entry:focus {{
    border-color: {colors['accent']};
}}

/* Açılır Seçim Kutuları (ComboBox) */
combobox,
combobox box.linked,
combobox box {{
    background: transparent;
    box-shadow: none;
    border: none;
}}

combobox button.combo,
combobox button {{
    background: {colors['input_bg']};
    color: {colors['text']};
    border-radius: 10px;
    border: 1px solid {colors['input_border']};
    padding: 6px 12px;
}}

combobox button.combo:hover,
combobox button:hover {{
    background: {colors['surface']};
}}

combobox arrow {{
    color: {colors['muted']};
}}

/* Tablolar ve Ağaç Görünümleri (Gtk.TreeView) */
treeview.view,
treeview {{
    background: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
}}

treeview header button,
treeview header button box,
treeview header button label,
treeview header button image {{
    background: {colors['surface_soft']};
    color: {colors['text']};
    box-shadow: none;
}}

treeview header button {{
    border-radius: 10px 10px 0 0;
    border: 1px solid {colors['border']};
    padding: 8px 12px;
}}

treeview header button:hover {{
    background: {colors['surface_alt']};
}}

treeview.view row {{
    min-height: 44px;
    padding: 2px 4px;
}}

treeview.view:selected,
treeview.view:selected:focus,
treeview.view row:selected {{
    background: {colors['accent']};
    color: {colors['accent_text']};
}}

/* Çerçeveler ve Kaydırma Alanları */
frame {{
    border-color: {colors['border']};
}}

scrolledwindow {{
    background-color: {colors['window_bg']};
    color: {colors['text']};
}}

/* Sekmeler (Gtk.Notebook) */
notebook > header.top {{
    background: transparent;
    border: none;
    padding-bottom: 4px;
}}

notebook > header.top tabs {{
    background: transparent;
    border: none;
    margin-right: 8px;
}}

notebook > header.top tab {{
    background: {colors['surface_alt']};
    border: 1px solid {colors['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 14px;
    margin-right: 3px;
    color: {colors['muted']};
}}

notebook > header.top tab:checked {{
    background: {colors['surface']};
    color: {colors['text']};
}}

notebook > stack {{
    background: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: 0 8px 8px 8px;
    padding: 18px;
}}

notebook > stack scrolledwindow,
notebook > stack scrolledwindow > viewport {{
    background: transparent;
}}

/* Diğer Bileşenler */
listbox {{
    background: transparent;
}}

listbox row {{
    background-color: {colors['card_bg']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: 8px;
    padding: 8px 12px;
    margin-bottom: 6px;
}}

listbox row label {{
    color: {colors['text']};
}}

listbox row:hover {{
    background-color: {colors['card_hover']};
}}

expander.diagnostics-expander {{
    color: {colors['text']};
}}

.action-bar {{
    background: transparent;
    border-top: 1px solid {colors['border']};
    padding-top: 12px;
}}

progressbar trough {{
    background: {colors['surface_alt']};
    border-radius: 999px;
    min-height: 8px;
}}

progressbar progress,
progressbar progress.pulse {{
    background: {colors['accent']};
    border-radius: 999px;
    min-height: 8px;
}}

textview,
textview text {{
    background: {colors['surface']};
    color: {colors['text']};
}}

infobar {{
    border-radius: 8px;
    padding: 6px;
}}
"""

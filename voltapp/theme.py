#!/usr/bin/env python3
"""GTK CSS temaları."""


def get_theme_css(theme_name: str) -> str:
    palettes = {
        "dark": {
            "window_bg": "#1f262d",
            "surface": "#26313a",
            "surface_alt": "#2d3944",
            "surface_soft": "#222c34",
            "card_bg": "#2c3d4c",
            "card_hover": "#364e61",
            "text": "#e8f1f7",
            "muted": "#9fb0bc",
            "border": "#364651",
            "accent": "#63b3ed",
            "success": "#59d38c",
            "accent_text": "#081723",
            "danger": "#ff7f7f",
            "danger_text": "#2f0e0e",
            "input_bg": "#182026",
            "input_border": "#4c5d69",
        },
        "light": {
            "window_bg": "#f3f7fb",
            "surface": "#ffffff",
            "surface_alt": "#edf4fa",
            "surface_soft": "#f7fbff",
            "card_bg": "#edf4fa",
            "card_hover": "#d9ebf7",
            "text": "#173041",
            "muted": "#5f7483",
            "border": "#cfdae4",
            "accent": "#5bb8f0",
            "success": "#41b86f",
            "accent_text": "#103041",
            "danger": "#ff9d9d",
            "danger_text": "#4b1616",
            "input_bg": "#ffffff",
            "input_border": "#9fb6c8",
        },
    }
    colors = palettes.get(theme_name, palettes["dark"])
    return f"""
window.icon-settings-window,
window.icon-settings-window separator,
window.icon-settings-window menu,
window.icon-settings-window treeview,
window.icon-settings-window scrolledwindow {{
    background-color: {colors['window_bg']};
    color: {colors['text']};
}}

window.icon-settings-window notebook > stack scrolledwindow,
window.icon-settings-window notebook > stack scrolledwindow > viewport {{
    background: transparent;
}}

window.icon-settings-window box {{
    color: {colors['text']};
}}

window.icon-settings-window label {{
    color: {colors['text']};
}}

window.icon-settings-window menu menuitem {{
    color: {colors['text']};
}}

window.icon-settings-window .dim-label {{
    color: {colors['muted']};
}}

window.icon-settings-window button {{
    background: {colors['surface_alt']};
    color: {colors['text']};
    border-radius: 12px;
    border: 1px solid {colors['border']};
    box-shadow: none;
    padding: 8px 16px;
}}

window.icon-settings-window button:hover {{
    background: {colors['surface']};
}}

window.icon-settings-window button.suggested-action {{
    background: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
}}

window.icon-settings-window button.suggested-action:hover {{
    background: shade({colors['accent']}, 1.08);
}}

window.icon-settings-window button.destructive-action {{
    background: {colors['danger']};
    color: {colors['danger_text']};
    border-color: {colors['danger']};
}}

window.icon-settings-window button.outline-accent {{
    background: transparent;
    color: {colors['accent']};
    border-color: {colors['accent']};
}}

window.icon-settings-window button.outline-danger {{
    background: transparent;
    color: {colors['danger']};
    border-color: {colors['danger']};
}}

window.icon-settings-window entry {{
    background: {colors['input_bg']};
    color: {colors['text']};
    border-radius: 10px;
    border: 1px solid {colors['input_border']};
}}

window.icon-settings-window combobox,
window.icon-settings-window combobox button,
window.icon-settings-window combobox box.linked,
window.icon-settings-window combobox box {{
    background: transparent;
    box-shadow: none;
    border: none;
}}

window.icon-settings-window combobox button.combo,
window.icon-settings-window combobox button {{
    background: {colors['input_bg']};
    color: {colors['text']};
    border-radius: 10px;
    border: 1px solid {colors['input_border']};
    padding: 6px 12px;
}}

window.icon-settings-window combobox button.combo:hover,
window.icon-settings-window combobox button:hover {{
    background: {colors['surface']};
}}

window.icon-settings-window combobox arrow {{
    color: {colors['muted']};
}}

window.icon-settings-window treeview.view {{
    background: {colors['surface']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
}}

window.icon-settings-window treeview header button,
window.icon-settings-window treeview header button box,
window.icon-settings-window treeview header button label,
window.icon-settings-window treeview header button image {{
    background: {colors['surface_soft']};
    color: {colors['text']};
    box-shadow: none;
}}

window.icon-settings-window treeview header button {{
    border-radius: 10px 10px 0 0;
    border: 1px solid {colors['border']};
    padding: 8px 12px;
}}

window.icon-settings-window treeview header button:hover {{
    background: {colors['surface_alt']};
}}

window.icon-settings-window treeview.view row {{
    min-height: 44px;
    padding: 2px 4px;
}}

window.icon-settings-window treeview.view:selected,
window.icon-settings-window treeview.view:selected:focus {{
    background: {colors['accent']};
    color: {colors['accent_text']};
}}

window.icon-settings-window frame {{
    border-color: {colors['border']};
}}

window.icon-settings-window notebook > header.top {{
    background: transparent;
    border: none;
    padding-bottom: 4px;
}}

window.icon-settings-window notebook > header.top tabs {{
    background: transparent;
    border: none;
    margin-right: 8px;
}}

window.icon-settings-window notebook > header.top tab {{
    background: {colors['surface_alt']};
    border: 1px solid {colors['border']};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 14px;
    margin-right: 3px;
    color: {colors['muted']};
}}

window.icon-settings-window notebook > header.top tab:checked {{
    background: {colors['surface']};
    color: {colors['text']};
}}

window.icon-settings-window notebook > stack {{
    background: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: 0 8px 8px 8px;
    padding: 18px;
}}

window.icon-settings-window button.header-action {{
    border-radius: 8px;
    padding: 6px 14px;
    min-height: 0;
    min-width: 0;
}}

window.icon-settings-window button.filter-chip {{
    border-radius: 999px;
    padding: 5px 12px;
    min-height: 0;
}}

window.icon-settings-window button.filter-chip:checked {{
    background: {colors['accent']};
    color: {colors['accent_text']};
    border-color: {colors['accent']};
}}

window.icon-settings-window button.compact-action {{
    padding: 7px 14px;
    min-height: 0;
    min-width: 0;
}}

window.icon-settings-window listbox {{
    background: transparent;
}}

window.icon-settings-window expander.diagnostics-expander {{
    color: {colors['text']};
}}

window.icon-settings-window .action-bar {{
    background: transparent;
    border-top: 1px solid {colors['border']};
    padding-top: 12px;
}}

window.icon-settings-window progressbar trough {{
    background: {colors['surface_alt']};
    border-radius: 999px;
    min-height: 8px;
}}

window.icon-settings-window progressbar progress,
window.icon-settings-window progressbar progress.pulse {{
    background: {colors['accent']};
    border-radius: 999px;
    min-height: 8px;
}}

window.icon-settings-window textview,
window.icon-settings-window textview text {{
    background: {colors['surface']};
    color: {colors['text']};
}}
"""

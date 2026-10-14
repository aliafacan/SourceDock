"""Central GTK 3 design tokens with system, light and dark theme support."""

PALETTES = {
    "dark": {
        "background": "#202223",
        "surface": "#282b2c",
        "surface_hover": "#343738",
        "sidebar": "#191b1c",
        "border": "#414546",
        "text": "#f0f2f3",
        "muted": "#b0b7ba",
        "accent": "#f3ce45",
        "accent_text": "#20210e",
        "success": "#77d5a1",
        "warning": "#eac46a",
        "danger": "#ff9393",
        "focus": "#87c4ec",
        "selection": "#3a4b56",
    },
    "light": {
        "background": "#f6f7f8",
        "surface": "#ffffff",
        "surface_hover": "#edf0f2",
        "sidebar": "#edf0f2",
        "border": "#d2d8dc",
        "text": "#22272a",
        "muted": "#59656c",
        "accent": "#f0cd40",
        "accent_text": "#29270d",
        "success": "#21764b",
        "warning": "#805800",
        "danger": "#b62e3b",
        "focus": "#146dac",
        "selection": "#dbeaf4",
    },
}


def resolve_theme(theme_name: str) -> str:
    if theme_name in PALETTES:
        return theme_name
    try:
        from gi.repository import Gio, Gtk

        source = Gio.SettingsSchemaSource.get_default()
        schema = source.lookup("org.gnome.desktop.interface", True) if source else None
        if schema and schema.has_key("color-scheme"):
            value = Gio.Settings.new_full(schema, None, None).get_string("color-scheme")
            if value in ("prefer-dark", "prefer-light"):
                return "dark" if value == "prefer-dark" else "light"
        settings = Gtk.Settings.get_default()
        return "dark" if settings and settings.get_property("gtk-application-prefer-dark-theme") else "light"
    except (ImportError, RuntimeError):
        return "light"


def get_theme_css(theme_name: str, scale: str = "100") -> str:
    colors = PALETTES[resolve_theme(theme_name)]
    font = {"90": "9.5pt", "100": "10.5pt", "110": "11.5pt", "125": "13pt"}.get(scale, "10.5pt")
    tokens = "\n".join(f"@define-color {key} {value};" for key, value in colors.items())
    return (
        tokens
        + f"""
* {{ font-size: {font}; }}
window, dialog, messagedialog, .icon-settings-window {{ background: @background; color: @text; }}
label, window box, dialog box {{ color: @text; }}
.dim-label, .dim-label label {{ color: @muted; opacity: 1; }}
.error-text {{ color: @danger; }}
.success-text {{ color: @success; }}
.warning-text {{ color: @warning; }}
.brand-title {{ font-size: 16pt; font-weight: bold; }}
.state-title {{ font-size: 14pt; font-weight: bold; }}
.page-title {{ font-size: 16pt; font-weight: bold; }}
.summary-card {{ background: @surface; border: 1px solid @border; border-radius: 8px; }}
.summary-count {{ font-size: 17pt; font-weight: bold; }}
.card-action {{ color: @focus; font-weight: bold; }}
headerbar, .titlebar {{ background: @surface; color: @text; border-bottom: 1px solid @border; box-shadow: none; }}
headerbar label.title {{ font-weight: bold; }}
headerbar label.subtitle {{ color: @muted; }}
button {{ background: @surface; color: @text; border: 1px solid @border; border-radius: 6px;
          padding: 6px 12px; box-shadow: none; min-height: 22px; }}
button label, button image {{ color: inherit; }}
button:hover {{ background: @surface_hover; }}
button:disabled, button:disabled label, button:disabled image {{ color: @muted; opacity: 0.55; }}
button:focus, entry:focus, checkbutton:focus, row:focus {{ outline: 2px solid @focus; outline-offset: 2px; }}
button.suggested-action {{ background: @accent; border-color: @accent; color: @accent_text; font-weight: bold; }}
button.suggested-action:hover {{ background: shade(@accent, 1.07); }}
button.destructive-action, button.outline-danger {{ color: @danger; border-color: @danger; }}
button.icon-button {{ min-width: 22px; min-height: 22px; padding: 6px; }}
button.flat {{ border-color: transparent; background: transparent; }}
.sidebar {{ background: @sidebar; padding: 12px 8px; border-right: 1px solid @border; }}
.sidebar button.nav-button {{ border-color: transparent; background: transparent; padding: 10px 12px; border-radius: 6px; }}
.sidebar button.nav-button:hover {{ background: @surface_hover; }}
.sidebar button.nav-active {{ background: @selection; font-weight: bold; }}
.page-content > stack {{ background: @background; border: none; border-radius: 0; padding: 20px; }}
button.filter-chip {{ border-radius: 6px; padding: 4px 9px; min-height: 20px; }}
button.filter-chip:checked {{ background: @selection; color: @text; border-color: @focus; }}
entry {{ background: @surface; color: @text; border-radius: 6px; border: 1px solid @border; padding: 7px 10px; }}
entry:focus {{ border-color: @focus; }}
combobox, combobox box {{ background: transparent; }}
combobox button {{ background: @surface; padding: 5px 8px; }}
scrolledwindow, viewport {{ background: transparent; }}
treeview, treeview.view {{ background: @surface; color: @text; border: none; }}
treeview header button {{ background: @background; border: none; border-bottom: 1px solid @border;
                         border-radius: 0; padding: 8px; font-weight: bold; }}
treeview header button label {{ color: @muted; }}
treeview.view:selected, treeview.view:selected:focus {{ background: @selection; color: @text; }}
treeview.view row {{ min-height: 40px; padding: 4px; }}
listbox, flowbox {{ background: transparent; }}
flowboxchild {{ padding: 0; }}
listbox row {{ background: transparent; border-bottom: 1px solid @border; border-radius: 0; padding: 12px; }}
listbox row:hover {{ background: @surface_hover; }}
.app-card {{ background: @surface; border: 1px solid @border; border-radius: 8px; padding: 16px; }}
.app-card:hover {{ background: @surface_hover; }}
.app-name {{ font-weight: bold; font-size: 12pt; }}
.source-badge {{ color: @muted; font-size: 9pt; }}
.action-bar {{ border-top: 1px solid @border; padding-top: 12px; }}
.dialog-action-area, dialog .action-area {{ padding: 12px; border-top: 1px solid @border; background: @surface; }}
menu, .menu, popover {{ background: @surface; color: @text; border: 1px solid @border; border-radius: 6px; padding: 6px; }}
menuitem {{ padding: 8px 12px; color: @text; }}
menuitem:hover, menuitem:selected {{ background: @selection; }}
menuitem label {{ color: inherit; }}
separator {{ background: @border; min-height: 1px; }}
textview, textview text {{ background: @surface; color: @text; }}
progressbar trough {{ background: @surface_hover; border-radius: 4px; min-height: 6px; }}
progressbar progress {{ background: @accent; border-radius: 4px; min-height: 6px; }}
infobar {{ padding: 8px; background: @surface; }}
tooltip {{ background: @surface; color: @text; border: 1px solid @border; }}
"""
    )

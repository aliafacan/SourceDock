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
        "selection": "#364650",
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


def system_reduced_motion() -> bool:
    """Report whether the desktop asks for reduced motion.

    GTK 3 has no portable reduced-motion portal; ``gtk-enable-animations`` is
    the supported signal and is flipped off by GNOME's accessibility toggle.
    """
    try:
        from gi.repository import Gtk

        settings = Gtk.Settings.get_default()
        if settings is None:
            return False
        return not bool(settings.get_property("gtk-enable-animations"))
    except (ImportError, RuntimeError, TypeError):
        return False


def get_theme_css(theme_name: str, scale: str = "100", reduced_motion: bool = False) -> str:
    colors = PALETTES[resolve_theme(theme_name)]
    font = {"90": "9.5pt", "100": "10.5pt", "110": "11.5pt", "125": "13pt"}.get(scale, "10.5pt")
    tokens = "\n".join(f"@define-color {key} {value};" for key, value in colors.items())
    motion = (
        "\n* { transition-duration: 0s !important; animation-duration: 0s !important; }"
        if reduced_motion
        else ""
    )
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
.summary-card {{ background: @surface; border: 1px solid @border; border-radius: 10px; }}
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
button.suggested-action:disabled, button.suggested-action:disabled label {{ background: @surface; border-color: @border; color: @muted; }}
button.destructive-action, button.outline-danger {{ color: @danger; border-color: @danger; }}
button.icon-button {{ min-width: 22px; min-height: 22px; padding: 6px; }}
button.flat {{ border-color: transparent; background: transparent; }}
.sidebar {{ background: @sidebar; padding: 12px 8px; border-right: 1px solid @border; }}
.sidebar button.sidebar-brand-button {{ border-color: transparent; background: transparent; padding: 0; border-radius: 6px; }}
.sidebar button.sidebar-brand-button:hover {{ background: @surface_hover; }}
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
treeview.data-table.view row:nth-child(even) {{ background-color: @surface; }}
treeview.data-table.view row:nth-child(odd) {{ background-color: shade(@surface, 0.96); }}
treeview.data-table.view row:not(:selected) {{ border-bottom: 1px solid alpha(@border, 0.55); }}
treeview.data-table.view row:hover {{ background-color: @surface_hover; }}
treeview header button {{ background: @background; border: none; border-bottom: 1px solid @border;
                         border-radius: 0; padding: 8px; font-weight: bold; }}
treeview header button label {{ color: @muted; }}
treeview.view:selected, treeview.view:selected:focus {{ background: @selection; color: @text; }}
treeview.view row {{ min-height: 40px; padding: 4px; }}
treeview.view row:focus {{ outline: 2px solid @focus; outline-offset: -2px; }}
treeview.data-table.view check {{ min-width: 14px; min-height: 14px; border: 1px solid @border; border-radius: 2px; background: @surface; }}
treeview.data-table.view check:checked {{ background: @accent; color: @accent_text; border-color: @accent; }}
treeview.data-table.view check:hover {{ border-color: @focus; }}
checkbutton check {{ min-width: 14px; min-height: 14px; border: 1px solid @border; border-radius: 2px; background: @surface; color: @text; }}
checkbutton check:checked {{ background: @accent; color: @accent_text; border-color: @accent; }}
checkbutton check:indeterminate {{ background: @selection; color: @text; border-color: @focus; }}
checkbutton:disabled check {{ background: @background; border-color: @border; color: @muted; }}
checkbutton check:hover {{ border-color: @focus; }}
checkbutton label {{ color: @text; }}
listbox, flowbox {{ background: transparent; }}
flowboxchild {{ padding: 0; }}
listbox row {{ background: transparent; border-bottom: 1px solid @border; border-radius: 0; padding: 12px; }}
listbox row:hover {{ background: @surface_hover; }}
.app-card {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 16px; }}
.app-card:hover {{ background: @surface_hover; }}
.app-name {{ font-weight: bold; font-size: 12pt; }}
.source-badge {{ color: @muted; font-size: 9pt; }}
.package-badge {{ background: @selection; color: @text; border-radius: 4px; padding: 2px 6px; font-weight: bold; }}
.package-status-success {{ background: alpha(@success, 0.16); color: @success; border-radius: 4px; padding: 2px 6px; font-weight: bold; }}
.package-status-warning {{ background: alpha(@warning, 0.16); color: @warning; border-radius: 4px; padding: 2px 6px; font-weight: bold; }}
.package-status-danger {{ background: alpha(@danger, 0.16); color: @danger; border-radius: 4px; padding: 2px 6px; font-weight: bold; }}
.package-version-change {{ color: @focus; font-weight: bold; }}
.package-version-change.downgrade {{ color: @warning; }}
.empty-state {{ padding: 24px; }}
.section-title {{ font-weight: bold; font-size: 12pt; }}
.danger-banner {{ background: alpha(@danger, 0.12); border: 1px solid @danger; border-radius: 6px; padding: 10px; }}
.diagnostics-list {{ background: @surface; color: @text; border: 1px solid @border; border-radius: 6px; padding: 4px; }}
.diagnostics-list row {{ background: @surface; color: @text; border-bottom: 1px solid alpha(@border, 0.55); padding: 6px 4px; }}
.diagnostics-list row:last-child {{ border-bottom: none; }}
.diagnostics-list row label {{ color: @text; }}
.updates-status-panel {{ border: 1px solid @border; border-radius: 6px; padding: 8px 10px; }}
.updates-status-panel.updates-status-notice {{ background: alpha(@focus, 0.08); border-color: alpha(@focus, 0.35); }}
.updates-status-panel.updates-status-error {{ background: alpha(@danger, 0.09); border-color: alpha(@danger, 0.38); }}
.updates-status-panel.updates-status-notice image {{ color: @focus; }}
.updates-status-panel.updates-status-error image {{ color: @danger; }}
.secondary-action {{ background: @surface; border-color: @border; color: @text; }}
.help-card {{ background: @surface; border: 1px solid @border; border-radius: 6px; padding: 12px; }}
.action-bar {{ border-top: 1px solid @border; padding-top: 12px; }}
.dialog-action-area, dialog .action-area {{ padding: 12px; border-top: 1px solid @border; background: @surface; }}
menu, .menu, popover {{ background: @surface; color: @text; border: 1px solid @border; border-radius: 6px; padding: 6px; }}
menuitem {{ padding: 8px 12px; color: @text; }}
menuitem:hover, menuitem:selected {{ background: @selection; }}
menuitem label {{ color: inherit; }}
separator {{ background: @border; min-height: 1px; }}
.context-menu {{ background: @surface; border: 1px solid @border; border-radius: 6px; padding: 1px; }}
.context-menu button {{ border-color: transparent; background: transparent; border-radius: 4px; padding: 7px 10px; min-height: 22px; }}
.context-menu button:hover {{ background: @selection; }}
textview, textview text {{ background: @surface; color: @text; }}
progressbar trough {{ background: @surface_hover; border-radius: 4px; min-height: 6px; }}
progressbar progress {{ background: @accent; border-radius: 4px; min-height: 6px; }}
infobar {{ padding: 8px; background: @surface; }}
tooltip {{ background: @surface; color: @text; border: 1px solid @border; }}
.toast-box {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 10px 14px;
              box-shadow: 0 2px 8px alpha(@text, 0.16); }}
.toast-box.toast-success {{ border-color: @success; }}
.toast-box.toast-warning {{ border-color: @warning; }}
.toast-box.toast-danger, .toast-box.toast-error {{ border-color: @danger; }}
.toast-label {{ color: @text; }}
.toast-icon-success {{ color: @success; }}
.toast-icon-warning {{ color: @warning; }}
.toast-icon-danger, .toast-icon-error {{ color: @danger; }}
.toast-icon-info {{ color: @focus; }}
.toast-close-btn {{ border-color: transparent; background: transparent; }}
.toast-close-btn:hover {{ background: @surface_hover; }}
button, listbox row, .app-card, treeview.view row, .filter-chip {{ transition: background-color 150ms ease-out, color 150ms ease-out, border-color 150ms ease-out; }}
"""
        + motion
    )

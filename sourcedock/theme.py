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
    permission_font = {"90": "8.5pt", "100": "9.5pt", "110": "10.5pt", "125": "12pt"}.get(scale, "9.5pt")
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
.summary-card-active {{ background: alpha(@focus, 0.16); border-radius: 10px; }}
.summary-card-active .summary-card {{ border-color: @focus; }}
.updates-group-row {{ background: @surface; }}
.summary-count {{ font-size: 17pt; font-weight: bold; }}
.card-action {{ color: @focus; font-weight: bold; }}
headerbar, .titlebar {{ background: @surface; color: @text; border-bottom: 1px solid @border; box-shadow: none; }}
headerbar label.title {{ font-weight: bold; }}
headerbar label.subtitle {{ color: @muted; }}
headerbar button.titlebutton {{ 
    background-color: @surface;
    background-image: none;
    color: @text;
    border: 1px solid @border;
    box-shadow: none; 
    padding: 3px;
    margin: 0 2px;
    min-width: 28px;
    min-height: 28px;
    border-radius: 6px;
}}
headerbar button.titlebutton image {{ color: @text; -gtk-icon-transform: scale(1.2); }}
headerbar button.titlebutton:hover {{ background-color: @surface_hover; border-color: @focus; }}
headerbar button.titlebutton.close:hover {{ background-color: @danger; border-color: @danger; color: #ffffff; }}
headerbar button.titlebutton.close:hover image {{ color: #ffffff; }}
button:not(.titlebutton) {{ background: @surface; color: @text; border: 1px solid @border; border-radius: 6px;
          padding: 6px 12px; box-shadow: none; min-height: 22px; }}
button:not(.titlebutton) label, button:not(.titlebutton) image {{ color: inherit; }}
button:not(.titlebutton):hover {{ background: @surface_hover; }}
button:not(.titlebutton):disabled, button:not(.titlebutton):disabled label, button:not(.titlebutton):disabled image {{ color: @muted; opacity: 0.55; }}
button:focus, entry:focus, checkbutton:focus, row:focus {{ outline: 2px solid @focus; outline-offset: 2px; }}
button.suggested-action {{ background: @accent; border-color: @accent; color: @accent_text; font-weight: bold; }}
button.suggested-action:hover {{ background: shade(@accent, 1.07); }}
button.suggested-action label, button.suggested-action image,
button.suggested-action box {{ color: @accent_text; }}
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
.permissions-dialog, .permissions-dialog * {{ font-size: {permission_font}; }}
.permissions-dialog .permission-app-title {{ font-weight: bold; }}
.permissions-dialog .permissions-heading {{ border-bottom: 1px solid @border; padding-bottom: 16px; }}
.permissions-dialog .permissions-tabs {{ background: @background; border: 0; }}
.permissions-dialog .permissions-tabs header {{ background: transparent; border: 0; padding: 0 0 8px 0; box-shadow: none; }}
.permissions-dialog .permissions-tabs header tabs {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 3px; }}
.permissions-dialog .permissions-tabs tab {{ padding: 8px 14px; margin: 0 2px; border: 1px solid transparent; border-radius: 7px; background: transparent; box-shadow: none; }}
.permissions-dialog .permissions-tabs tab:hover {{ background: @surface_hover; box-shadow: none; }}
.permissions-dialog .permissions-tabs tab:checked {{ background: @selection; border-color: alpha(@focus, 0.35); box-shadow: none; }}
.permissions-dialog .permissions-tabs tab label {{ color: @muted; }}
.permissions-dialog .permissions-tabs tab image {{ color: @muted; }}
.permissions-dialog .permissions-tabs tab:checked label, .permissions-dialog .permissions-tabs tab:checked image {{ color: @text; font-weight: bold; }}
.permissions-dialog .permissions-tabs stack {{ background: @background; }}
.permissions-dialog .permissions-tabs scrolledwindow, .permissions-dialog .permissions-tabs viewport,
.permissions-dialog .permissions-tabs list {{ background: @background; }}
.permissions-dialog list.permission-list {{ background: @surface; border: 1px solid @border; border-radius: 9px; }}
.permissions-dialog list.permission-list row.permission-row {{ background: @surface; border: 0; border-bottom: 1px solid @border; border-radius: 0; padding: 0; margin: 0; }}
.permissions-dialog list.permission-list row.permission-row:last-child {{ border-bottom: 0; }}
.permissions-dialog .permission-row:hover {{ background: @surface_hover; }}
.permissions-dialog .permission-section-title {{ font-weight: bold; }}
.permissions-dialog .permission-info {{ background: alpha(@focus, 0.07); border: 1px solid alpha(@focus, 0.25); border-radius: 9px; padding: 16px; }}
.permissions-dialog .permission-status {{ padding-top: 12px; }}
.permissions-dialog .permission-status image {{ color: @focus; }}
.permissions-dialog switch {{ background: @border; border: 1px solid @border; border-radius: 16px; }}
.permissions-dialog switch:checked {{ background: @accent; border-color: shade(@accent, 0.9); }}
.permissions-dialog switch slider {{ background: #ffffff; border: 1px solid @border; border-radius: 50%; }}
.permissions-dialog switch:checked slider {{ background: #ffffff; border-color: shade(@accent, 0.85); }}
.permissions-dialog .action-area {{ background: @background; padding: 12px 4px; }}
notebook {{ background: @background; border: none; }}
notebook header {{ background: transparent; border: none; padding: 0 0 8px 0; box-shadow: none; }}
notebook header tabs {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 3px; }}
notebook tab {{ background: transparent; color: @muted; border: 1px solid transparent; border-radius: 7px; padding: 7px 14px; margin: 0 2px; box-shadow: none; }}
notebook tab:hover {{ background: @surface_hover; color: @text; box-shadow: none; }}
notebook tab:checked {{ background: @selection; color: @text; border-color: alpha(@focus, 0.35); font-weight: bold; box-shadow: none; }}
notebook tab:focus, notebook tab:checked:focus {{ outline: none; box-shadow: none; }}
notebook tab label {{ color: inherit; }}
notebook stack, notebook > stack {{ background: @background; }}
stackswitcher, .help-tabs {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 3px; }}
stackswitcher button:not(.titlebutton), .help-tabs button:not(.titlebutton) {{ background: transparent; border: 1px solid transparent; border-radius: 7px; box-shadow: none; color: @muted; padding: 6px 12px; margin: 0 2px; }}
stackswitcher button:not(.titlebutton):hover, .help-tabs button:not(.titlebutton):hover {{ background: @surface_hover; color: @text; }}
stackswitcher button:not(.titlebutton):checked, .help-tabs button:not(.titlebutton):checked {{ background: @selection; border-color: alpha(@focus, 0.35); color: @text; font-weight: bold; box-shadow: none; }}
stackswitcher button:not(.titlebutton):focus, .help-tabs button:not(.titlebutton):focus {{ outline: none; box-shadow: none; }}
switch {{ background: @border; border: 1px solid @border; border-radius: 16px; min-width: 44px; min-height: 24px; }}
switch:checked {{ background: @accent; border-color: shade(@accent, 0.9); }}
switch slider {{ background: #ffffff; border: 1px solid @border; border-radius: 50%; }}
switch:checked slider {{ background: #ffffff; border: 1px solid shade(@accent, 0.85); }}
expander title {{ color: @text; padding: 4px 2px; border-radius: 6px; }}
expander title:hover {{ background: @surface_hover; }}
frame > border {{ border-color: @border; }}
/* GTK's PlacesSidebar otherwise keeps the system theme's pale selection while
   our global label rule supplies light text in a dark file chooser. */
filechooser placessidebar row:selected,
filechooser placessidebar row:selected:hover,
filechooser placessidebar row:selected:backdrop {{ background: @selection; color: @text; }}
filechooser placessidebar row:selected label,
filechooser placessidebar row:selected image {{ color: @text; opacity: 1; }}
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
.local-installer-dialog .installer-heading {{ background: @surface; border-bottom: 1px solid @border; padding: 10px 16px; }}
.local-installer-dialog .installer-tabs {{ background: @surface; border: 1px solid @border; border-radius: 8px; margin: 8px 14px 0; padding: 2px; }}
.local-installer-dialog .installer-tabs button {{ background: transparent; border: none; border-radius: 6px; box-shadow: none; color: @muted; min-width: 115px; padding: 5px 14px; }}
.local-installer-dialog .installer-tabs button:checked {{ background: @selection; color: @text; }}
.local-installer-dialog .installer-tabs button:hover {{ color: @text; }}
.local-installer-dialog .installer-tabs button:focus {{ outline: none; box-shadow: none; }}
.local-installer-dialog .installer-icon-frame {{ background: @selection; border-radius: 10px; padding: 7px; }}
.local-installer-dialog .installer-progress-card,
.local-installer-dialog .installer-result-card {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 10px; }}
.local-installer-dialog .installer-preview-card {{ background: transparent; padding: 0; }}
.local-installer-dialog .installer-overview-description {{ color: @text; padding: 1px 0 4px; }}
.local-installer-dialog .installer-fact {{ background: @surface; border: 1px solid @border; border-radius: 9px; padding: 9px 11px; }}
.local-installer-dialog .installer-fact-label {{ color: @muted; font-size: 9pt; }}
.local-installer-dialog .installer-fact-value {{ color: @text; font-weight: 600; }}
.local-installer-dialog .installer-details-card {{ background: @surface; border: 1px solid @border; border-radius: 10px; padding: 10px 12px; }}
.local-installer-dialog .installer-section-title {{ color: @text; font-weight: bold; }}
.local-installer-dialog .installer-detail-row {{ border-bottom: 1px solid @border; padding: 2px 0 6px; }}
.local-installer-dialog .installer-detail-row:last-child {{ border-bottom: none; padding-bottom: 0; }}
.local-installer-dialog .installer-dependency-section {{ border-bottom: 1px solid @border; padding-bottom: 5px; }}
.local-installer-dialog .installer-dependency-toggle {{ background: transparent; border: none; box-shadow: none; color: @text; padding: 5px 2px; }}
.local-installer-dialog .installer-dependency-toggle:hover {{ background: @surface_hover; border-radius: 5px; }}
.local-installer-dialog .installer-dependency-toggle:focus {{ outline: none; box-shadow: none; }}
.local-installer-dialog .installer-dependency-toggle image {{ color: @focus; }}
.local-installer-dialog .installer-secondary-action {{ background: @surface; border: 1px solid @border; color: @text; border-radius: 7px; }}
.local-installer-dialog .installer-secondary-action:hover {{ background: @surface_hover; }}
.local-installer-dialog .installer-status-note {{ background: alpha(@success, 0.10); border-radius: 6px; padding: 7px 10px; }}
.local-installer-dialog .installer-status-note.caution {{ background: alpha(@warning, 0.10); }}
.local-installer-dialog .installer-security-note {{ background: alpha(@warning, 0.10); border-radius: 6px; padding: 8px 10px; color: @text; }}
.local-installer-dialog .installer-options-card {{ background: @surface; border-top: 1px solid @border; padding: 8px 16px; }}
.local-installer-dialog .installer-options-card checkbutton {{ padding: 1px 0; }}
.local-installer-dialog .installer-trust {{ margin-top: 4px; border-top: 1px solid @border; padding-top: 6px; font-weight: bold; }}
.local-installer-dialog .installer-actions {{ background: @background; border-top: 1px solid @border; padding: 8px 16px; }}
.local-installer-dialog .installer-actions button {{ min-height: 34px; min-width: 108px; }}
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
menu, .menu, popover {{ background: @surface; color: @text; border: 1px solid @border; border-radius: 8px; padding: 6px; }}
popover scrolledwindow, popover viewport, popover list {{ background: @surface; color: @text; }}
popover list row {{ background: @surface; color: @text; border-bottom: 1px solid alpha(@border, 0.5); padding: 2px 4px; }}
popover list row:hover {{ background: @surface_hover; }}
popover list row button {{ color: @text; padding: 6px 8px; }}
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

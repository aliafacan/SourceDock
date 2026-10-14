import {Extension} from 'resource:///org/gnome/shell/extensions/extension.js';
import {AppMenu} from 'resource:///org/gnome/shell/ui/appMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import GLib from 'gi://GLib';
import Gio from 'gi://Gio';

export default class SourceDockMenuExtension extends Extension {
    enable() {
        this._origSetApp = AppMenu.prototype.setApp;
        this._origOpen = AppMenu.prototype.open;
        this._enabled = true;
        this._menus = new Set();
        const extension = this;
        const originalSetApp = this._origSetApp;
        const originalOpen = this._origOpen;

        this._patchedSetApp = function(app) {
            originalSetApp.call(this, app);
            if (extension._enabled)
                extension._addActions(this, app);
        };
        this._patchedOpen = function(...args) {
            if (extension._enabled && this._app && !this._sourcedockMenuItems?.length)
                extension._addActions(this, this._app);
            return originalOpen.apply(this, args);
        };
        AppMenu.prototype.setApp = this._patchedSetApp;
        AppMenu.prototype.open = this._patchedOpen;
    }

    _addActions(menu, app) {
            this._menus.add(menu);

            if (menu._sourcedockMenuItems && Array.isArray(menu._sourcedockMenuItems)) {
                menu._sourcedockMenuItems.forEach(item => {
                    try { item.destroy(); } catch (_) {}
                });
            }
            menu._sourcedockMenuItems = [];

            if (!app) return;

            const appId = app.get_id ? app.get_id() : (app.id || '');
            if (!appId) return;

            const locale = GLib.getenv('LANG') || 'en';
            const isTr = locale.toLowerCase().startsWith('tr');
            const sourcedockCmd = GLib.find_program_in_path('sourcedock') || '/usr/bin/sourcedock';

            const detailsLabel = isTr ? 'SourceDock ile ayrıntıları göster' : 'Show Details with SourceDock';
            const uninstallLabel = isTr ? 'SourceDock ile kaldır' : 'Uninstall with SourceDock';

            const sep = new PopupMenu.PopupSeparatorMenuItem();
            menu.addMenuItem(sep);
            menu._sourcedockMenuItems.push(sep);

            const detailsItem = menu.addAction(detailsLabel, () => {
                try {
                    Gio.Subprocess.new([sourcedockCmd, '--details', appId], Gio.SubprocessFlags.NONE);
                } catch (e) {
                    log(`SourceDock details error: ${e.message}`);
                }
                if (Main.overview && Main.overview.visible) {
                    Main.overview.hide();
                }
            });
            menu._sourcedockMenuItems.push(detailsItem);

            const uninstallItem = menu.addAction(uninstallLabel, () => {
                try {
                    Gio.Subprocess.new([sourcedockCmd, '--uninstall', appId], Gio.SubprocessFlags.NONE);
                } catch (e) {
                    log(`SourceDock uninstall error: ${e.message}`);
                }
                if (Main.overview && Main.overview.visible) {
                    Main.overview.hide();
                }
            });
            menu._sourcedockMenuItems.push(uninstallItem);
    }

    disable() {
        this._enabled = false;
        if (this._origSetApp) {
            if (AppMenu.prototype.setApp === this._patchedSetApp)
                AppMenu.prototype.setApp = this._origSetApp;
            if (AppMenu.prototype.open === this._patchedOpen)
                AppMenu.prototype.open = this._origOpen;
        }
        for (const menu of this._menus ?? []) {
            for (const item of menu._sourcedockMenuItems ?? []) {
                try { item.destroy(); } catch (_) {}
            }
            menu._sourcedockMenuItems = [];
        }
        this._menus?.clear();
    }
}


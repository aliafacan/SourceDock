# SourceDock UI implementation specification

Date: 2026-10-14. GTK 3 and the existing provider interfaces remain the technical base.

## Audit

Existing: native provider modules, desktop application scanning, local installer,
TR/EN translations, application details, package listing, progress windows and tests.
Missing: persistent navigation, a dedicated updates center, compact layouts,
system theme support, common loading/error/empty states and durable operation results.
Confirmed risks: unrestricted portable deletion, archive prefix-path checks,
AppImage metadata inspection executing the file, blocking streaming reads and
external package processes exposed to pause/terminate controls.
Unverified: clean-install behavior on other distributions and remote CI/release status.

## Screen map

Wide windows: a 220px sidebar, page title and search in a header, then the active
screen. Navigation: Discover, Installed, Updates, Packages (advanced), Operations.
Bottom actions: Install Local File, Settings, Help. Compact windows collapse the
sidebar to accessible icon buttons. Content scrolls rather than clipping actions.

Discover uses real provider results, readable application items, category/source
filters and an explicit no-results state. Source alternatives require exact identity
or explicit user selection. Installed defaults to desktop applications; the package
list remains separate. Updates groups applications, system packages, firmware and
runtimes without inventing sizes. Details exposes known metadata and unknown trust
status. The standalone installer keeps its independent entry point and confirmation.

## Visual system

Neutral charcoal or white surfaces, readable text, thin borders, restrained electric
yellow for the principal action, green for success, red for destructive actions.
System font; 4/8/12/16/24/32 spacing; symbolic GTK icons; visible keyboard focus.
Repeated application items use a 10px corner radius (within the 10-14px spec). Screen
sections are unframed. Loading uses a spinner, never fabricated progress. Theme supports
System, Light and Dark, with 90/100/110/125 percent scale. Interactive surfaces use
150ms transitions that collapse to instant when the desktop requests reduced motion.

## Implementation order

1. Security boundaries and adversarial regression tests.
2. Theme tokens, common components and responsive navigation.
3. Discover, installed applications, details and the unified updates center.
4. Installer, operation results, settings, translations and keyboard behavior.
5. Package validation, screenshots, compatibility and release documentation.

## References

GNOME Software's information hierarchy and category browsing:
https://apps.gnome.org/Software/

Discover's multiple software sources and navigation:
https://apps.kde.org/discover/

Warehouse's explicit Flatpak data management:
https://github.com/flattool/warehouse

Pamac's distinction between application discovery and package management:
https://wiki.manjaro.org/index.php?title=Pamac

Artwork, branding and layouts are not copied. Validation must include real window
construction, dark/light TR/EN screenshots and compact sizes; tests must never
install or remove host packages.

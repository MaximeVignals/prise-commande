import flet as ft

if __package__:
    from . import ui
    from .catalogue import load_catalogue
    from .import_screen import show_import_screen
    from .context import AppContext
    from . import view_cart, view_catalogue, view_orders, view_admin, view_catalogues, view_photos, view_backup
    from . import shell
else:
    import ui
    from catalogue import load_catalogue
    from import_screen import show_import_screen
    from context import AppContext
    import view_cart
    import view_catalogue
    import view_orders
    import view_admin
    import view_catalogues
    import view_photos
    import view_backup
    import shell


# --- APPLICATION PRINCIPALE FLET ---


def reset_page(page):
    """Repart d'un écran vide : main() peut être relancé sur la même page (import au premier
    lancement, restauration, reprise Android). Sans ça, l'ancien écran reste et tout apparaît en double."""
    while len(page.views) > 1:
        page.views.pop()
    page.controls.clear()
    page.overlay.clear()
    page.appbar = page.drawer = None


def main(page: ft.Page):
    reset_page(page)
    page.title = "Prise de Commande"
    ui.configure_page(page)

    excel_items = load_catalogue()

    if not excel_items:
        show_import_screen(page)
        return

    ctx = AppContext(page, excel_items)
    page.data = {"ctx": ctx}  # les tests retrouvent le contexte via page.data["ctx"]
    ctx.main = main  # partagé avec view_backup (relance après restauration)

    view_cart.install(ctx)
    view_catalogue.install(ctx)
    view_orders.install(ctx)
    view_admin.install(ctx)
    view_catalogues.install(ctx)
    view_photos.install(ctx)
    view_backup.install(ctx)
    shell.install(ctx)


# Démarrage de l'application
if __name__ == "__main__":
    ft.run(main)

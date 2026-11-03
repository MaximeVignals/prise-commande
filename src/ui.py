"""Shared Material 3 presentation primitives; no catalogue or order logic lives here."""

from dataclasses import dataclass

import flet as ft

if __package__:
    from .text import fold
else:
    from text import fold


SPACE = 16
RADIUS = 20
PRIMARY = ft.Colors.PRIMARY
INK = ft.Colors.ON_SURFACE
MUTED = ft.Colors.ON_SURFACE_VARIANT
SURFACE = ft.Colors.SURFACE
PANEL = ft.Colors.SURFACE_CONTAINER_LOW
LINE = ft.Colors.OUTLINE_VARIANT


@dataclass(frozen=True)
class WindowLayout:
    """Logical window dimensions, never physical pixels or a device model.

    Short windows (landscape, keyboard, split screen) keep the chrome compact.
    Two usable panes require the expanded Material window class.
    """

    width: float = 390
    height: float = 800

    @property
    def size_class(self):
        return "compact" if self.width < 600 else "medium" if self.width < 840 else "expanded"

    @property
    def dual_pane(self):
        return self.size_class == "expanded" and self.height >= 480

    @property
    def short(self):
        return self.height < 560

    @property
    def margin(self):
        return 12 if self.width < 600 else 24


def make_theme(dark=False):
    scheme = ft.ColorScheme(
        primary="#A9C7FF" if dark else "#175BB5",
        on_primary="#002E68" if dark else "#FFFFFF",
        primary_container="#153D71" if dark else "#DFEBFF",
        on_primary_container="#D9E7FF" if dark else "#123D73",
        secondary="#BAC7DB" if dark else "#53647C",
        surface="#10141B" if dark else "#F7F9FD",
        on_surface="#E5E9F2" if dark else "#192333",
        on_surface_variant="#BAC4D4" if dark else "#536174",
        surface_container_lowest="#0C1017" if dark else "#FFFFFF",
        surface_container_low="#191F29" if dark else "#FFFFFF",
        surface_container="#202734" if dark else "#EEF2F8",
        surface_container_high="#293241" if dark else "#E6ECF5",
        surface_container_highest="#333D4E" if dark else "#DEE6F1",
        outline="#8793A6" if dark else "#77869B",
        outline_variant="#364254" if dark else "#DCE3EE",
        error="#FFB4AB" if dark else "#B3261E",
        on_error="#690005" if dark else "#FFFFFF",
    )
    button_style = ft.ButtonStyle(
        shape=ft.RoundedRectangleBorder(radius=14),
        padding=ft.Padding.symmetric(horizontal=20, vertical=14),
        text_style=ft.TextStyle(size=14, weight=ft.FontWeight.W_600),
        elevation=0,
    )
    return ft.Theme(
        use_material3=True,
        color_scheme_seed="#1E6FD9",
        color_scheme=scheme,
        scaffold_bgcolor=scheme.surface,
        font_family="Roboto",
        visual_density=ft.VisualDensity.STANDARD,
        button_theme=ft.ButtonTheme(style=button_style),
        filled_button_theme=ft.FilledButtonTheme(style=button_style),
        outlined_button_theme=ft.OutlinedButtonTheme(style=button_style),
        text_button_theme=ft.TextButtonTheme(style=button_style),
        icon_button_theme=ft.IconButtonTheme(style=ft.ButtonStyle(
            padding=12, shape=ft.RoundedRectangleBorder(radius=14),
        )),
        appbar_theme=ft.AppBarTheme(bgcolor=SURFACE, color=INK, elevation=0,
                                   center_title=False, toolbar_height=64),
        dialog_theme=ft.DialogTheme(
            bgcolor=PANEL, shape=ft.RoundedRectangleBorder(radius=24),
            title_text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_600),
            inset_padding=ft.Padding.symmetric(horizontal=16, vertical=24),
        ),
        navigation_bar_theme=ft.NavigationBarTheme(
            bgcolor=PANEL, elevation=0, indicator_color=ft.Colors.PRIMARY_CONTAINER,
            label_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.W_600, color=scheme.on_surface),
        ),
        list_tile_theme=ft.ListTileTheme(
            shape=ft.RoundedRectangleBorder(radius=16),
            selected_tile_color=ft.Colors.PRIMARY_CONTAINER,
            selected_color=ft.Colors.ON_PRIMARY_CONTAINER,
            min_height=56,
        ),
        text_theme=ft.TextTheme(
            body_large=ft.TextStyle(size=16, color=scheme.on_surface),
            body_medium=ft.TextStyle(size=14, height=1.35, color=scheme.on_surface),
            body_small=ft.TextStyle(size=12, height=1.35, color=scheme.on_surface_variant),
            title_medium=ft.TextStyle(size=16, weight=ft.FontWeight.W_600, color=scheme.on_surface),
        ),
    )


def configure_page(page):
    page.theme = make_theme()
    page.dark_theme = make_theme(dark=True)
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.padding = 0
    page.bgcolor = SURFACE


def field(**kwargs):
    return ft.TextField(
        border=input_border(), filled=True, fill_color=PANEL,
        content_padding=ft.Padding.symmetric(horizontal=14, vertical=12 if kwargs.get("dense") else 16),
        **kwargs,
    )


def text(value="", **kwargs):
    # Explicit semantic foreground also covers text outside Material widgets.
    kwargs.setdefault("color", INK)
    return ft.Text(value, **kwargs)


def button(**kwargs):
    kwargs.setdefault("style", ft.ButtonStyle(
        bgcolor={ft.ControlState.DEFAULT: PRIMARY,
                 ft.ControlState.DISABLED: ft.Colors.SURFACE_CONTAINER_HIGH},
        color={ft.ControlState.DEFAULT: ft.Colors.ON_PRIMARY,
               ft.ControlState.DISABLED: MUTED},
        shape=ft.RoundedRectangleBorder(radius=14), elevation=0,
        padding=ft.Padding.symmetric(horizontal=20, vertical=14),
    ))
    return ft.Button(**kwargs)


def dropdown(**kwargs):
    return ft.Dropdown(
        border=input_border(), filled=True, fill_color=PANEL,
        content_padding=ft.Padding.symmetric(horizontal=14, vertical=16),
        **kwargs,
    )


def input_border():
    return {
        ft.ControlState.DEFAULT: ft.OutlineInputBorder(
            border_radius=ft.BorderRadius.all(14), side=ft.BorderSide(1, LINE)),
        ft.ControlState.FOCUSED: ft.OutlineInputBorder(
            border_radius=ft.BorderRadius.all(14), side=ft.BorderSide(2, PRIMARY)),
        ft.ControlState.ERROR: ft.OutlineInputBorder(
            border_radius=ft.BorderRadius.all(14), side=ft.BorderSide(1, ft.Colors.ERROR)),
    }


def card(content, **kwargs):
    kwargs.setdefault("padding", SPACE)
    kwargs.setdefault("border_radius", RADIUS)
    return ft.Container(
        content=content, bgcolor=PANEL,
        border=ft.Border.all(1, LINE), **kwargs,
    )


def item_card(content):
    """Repeated data rows need less padding than a standalone summary card."""
    return card(content, padding=ft.Padding.symmetric(horizontal=12, vertical=8), border_radius=14)


def heading(title, subtitle=None, icon=None, trailing=None):
    controls = []
    if icon:
        controls.append(ft.Container(
            content=ft.Icon(icon, color=PRIMARY, size=22), padding=12,
            bgcolor=ft.Colors.PRIMARY_CONTAINER, border_radius=16,
        ))
    controls.append(ft.Column([
        ft.Text(title, size=22, weight=ft.FontWeight.W_600, color=INK),
        *([ft.Text(subtitle, size=13, color=MUTED)] if subtitle else []),
    ], spacing=3, expand=True, tight=True))
    if trailing:
        controls.append(trailing)
    return ft.Row(controls, spacing=12)


def empty(icon, title, description, action=None):
    """Scrollable at small heights and large system font sizes."""
    return ft.Container(
        alignment=ft.Alignment.CENTER, padding=20,
        content=ft.Column([
            ft.Container(content=ft.Icon(icon, size=32, color=PRIMARY),
                         padding=20, bgcolor=ft.Colors.PRIMARY_CONTAINER, border_radius=24),
            text(title, size=22, weight=ft.FontWeight.W_600, text_align=ft.TextAlign.CENTER),
            ft.Text(description, color=MUTED, text_align=ft.TextAlign.CENTER),
            *([action] if action else []),
        ], tight=True, spacing=16, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
    )


def get_category_icon(category_name):
    cat_lower = fold(category_name)
    for words, icon in [
        (["ecran", "moniteur"], ft.Icons.MONITOR),
        (["unite", "pc", "ordinateur", "portable"], ft.Icons.LAPTOP_OUTLINED),
        (["serveur", "baie", "nas"], ft.Icons.DNS_OUTLINED),
        (["clavier", "souris"], ft.Icons.KEYBOARD_OUTLINED),
        (["imprimante", "scanner", "copieur"], ft.Icons.PRINT_OUTLINED),
        (["reseau", "onduleur", "switch"], ft.Icons.CABLE),
        (["tablette", "smartphone"], ft.Icons.TABLET_ANDROID),
        (["radio", "imagerie", "capteur", "camera"], ft.Icons.PHOTO_CAMERA_OUTLINED),
        (["papeterie", "cheques"], ft.Icons.DESCRIPTION_OUTLINED),
    ]:
        if any(word in cat_lower for word in words):
            return icon
    return ft.Icons.INVENTORY_2_OUTLINED

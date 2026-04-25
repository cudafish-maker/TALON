"""
Shared two-column label row widget used across multiple screens.

Import ``InfoRow`` from here instead of defining a local ``_InfoRow`` in each
screen, so colour-API changes only need to be made once.

Colour API: ``theme_text_color = "Custom"`` + ``text_color`` is the correct
KivyMD approach for setting a custom label colour — it is not overridden by the
theme manager, unlike setting ``label.color`` directly.
"""
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel


class InfoRow(MDBoxLayout):
    """Two-column info display row: label (left) + value (right).

    Parameters
    ----------
    label:       Left-column heading text (Secondary colour, smaller).
    value:       Right-column value text.
    value_color: Optional RGBA tuple for a custom value text colour.
                 Uses ``theme_text_color="Custom"`` so the KivyMD theme manager
                 cannot override it.
    """

    def __init__(
        self,
        label: str,
        value: str,
        value_color: tuple | None = None,
        **kwargs,
    ):
        super().__init__(
            orientation="horizontal",
            adaptive_height=True,
            spacing="8dp",
            padding=("0dp", "2dp"),
            **kwargs,
        )
        self.add_widget(MDLabel(
            text=label,
            font_style="Label",
            role="medium",
            theme_text_color="Secondary",
            size_hint_x=0.38,
            adaptive_height=True,
        ))
        val = MDLabel(
            text=value,
            font_style="Body",
            role="medium",
            adaptive_height=True,
            size_hint_x=0.62,
        )
        if value_color is not None:
            val.theme_text_color = "Custom"
            val.text_color = value_color
        self.add_widget(val)

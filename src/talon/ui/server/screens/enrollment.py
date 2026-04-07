# talon/ui/server/screens/enrollment.py
# Enrollment token generator panel.
#
# New operators cannot join the network without an enrollment token.
# The server operator generates a single-use token here and gives it
# to the new operator in person (or over a trusted out-of-band channel).
# The token is 32 hex characters, valid until used.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  ENROLLMENT                     │
#   ├─────────────────────────────────┤
#   │  Generate a one-time enrollment │
#   │  token for a new operator.      │
#   │                                 │
#   │  Callsign:  [_____________]     │
#   │                                 │
#   │       [GENERATE TOKEN]          │
#   │                                 │
#   │  ┌─────────────────────────┐   │
#   │  │  a3f9...c142  [COPY]    │   │
#   │  │  For: WOLF-3            │   │
#   │  └─────────────────────────┘   │
#   ├─────────────────────────────────┤
#   │  PENDING TOKENS (unused)        │
#   │  a3f9...  WOLF-3  generated 12m │
#   └─────────────────────────────────┘

import time

from kivy.core.clipboard import Clipboard
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField


class EnrollmentPanel(MDBoxLayout):
    """Enrollment token generator for new operators."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._last_token = None
        self._last_callsign = None

    def refresh(self, talon_server):
        self._talon = talon_server
        self.clear_widgets()
        self._build()

    def _build(self):
        from kivymd.uix.divider import MDDivider

        # Header
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDLabel(
                text="ENROLLMENT",
                font_style="Label",
                role="large",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        self.add_widget(header)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Server destination hash display
        dest_hash = ""
        if self._talon and self._talon.link_manager:
            raw = self._talon.link_manager.get_destination_hash()
            if raw:
                dest_hash = raw.hex()

        if dest_hash:
            hash_row = MDBoxLayout(
                size_hint_y=None,
                height="36dp",
                padding=["16dp", "4dp"],
                spacing="8dp",
                md_bg_color="#0a0e14",
            )
            hash_row.add_widget(
                MDLabel(
                    text=f"SERVER HASH: [font=RobotoMono]{dest_hash}[/font]",
                    markup=True,
                    font_style="Body",
                    role="small",
                    theme_text_color="Custom",
                    text_color="#00e5a0",
                )
            )
            hash_row.add_widget(
                MDIconButton(
                    icon="content-copy",
                    theme_icon_color="Custom",
                    icon_color="#8a9bb0",
                    size_hint_x=None,
                    on_release=lambda x, h=dest_hash: self._copy_token(h),
                )
            )
            self.add_widget(hash_row)

        # Instruction text
        self.add_widget(
            MDLabel(
                text=(
                    "Generate a one-time token for a new operator.\n"
                    "Deliver the token AND server hash in person or over a trusted channel."
                ),
                font_style="Body",
                role="small",
                theme_text_color="Custom",
                text_color="#8a9bb0",
                size_hint_y=None,
                height="40dp",
                padding=["16dp", "4dp"],
            )
        )

        # Form
        form = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["16dp", "8dp"],
            spacing="12dp",
        )
        form.bind(minimum_height=form.setter("height"))

        self._callsign_field = MDTextField(
            hint_text="New operator callsign (e.g. WOLF-3)",
            mode="outlined",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        )
        if self._last_callsign:
            self._callsign_field.text = self._last_callsign

        form.add_widget(self._callsign_field)

        form.add_widget(
            MDButton(
                MDButtonText(
                    text="GENERATE TOKEN",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                ),
                style="elevated",
                md_bg_color="#00e5a0",
                size_hint_x=None,
                pos_hint={"center_x": 0.5},
                on_release=lambda x: self._generate(),
            )
        )

        # Token display (shown after generation)
        if self._last_token:
            form.add_widget(self._token_display_card(self._last_token, self._last_callsign or "?"))

        self.add_widget(form)
        self.add_widget(MDDivider(color="#1e2d3d"))

        # Pending tokens list (from database)
        pending_tokens = []
        if self._talon:
            pending_tokens = self._talon.get_pending_tokens()

        pending_hdr = MDBoxLayout(
            size_hint_y=None,
            height="32dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0a0e14",
        )
        pending_hdr.add_widget(
            MDLabel(
                text=f"PENDING TOKENS ({len(pending_tokens)} unused)",
                font_style="Label",
                role="small",
                theme_text_color="Custom",
                text_color="#8a9bb0",
            )
        )
        self.add_widget(pending_hdr)

        scroll = MDScrollView(size_hint_y=1)
        rows = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing="1dp",
        )
        rows.bind(minimum_height=rows.setter("height"))

        if not pending_tokens:
            rows.add_widget(
                MDLabel(
                    text="No pending tokens.",
                    halign="center",
                    font_style="Body",
                    role="small",
                    theme_text_color="Custom",
                    text_color="#3d4f63",
                    size_hint_y=None,
                    height="32dp",
                )
            )
        else:
            for info in pending_tokens:
                rows.add_widget(self._pending_row(info["token"], info))

        scroll.add_widget(rows)
        self.add_widget(scroll)

    def _generate(self):
        """Generate a new enrollment token for the given callsign."""
        callsign = self._callsign_field.text.strip().upper()
        if not callsign:
            return

        if not self._talon:
            return

        token = self._talon.create_enrollment_token(callsign)

        self._last_token = token
        self._last_callsign = callsign

        # Rebuild with the new token shown
        self.clear_widgets()
        self._build()

    def _token_display_card(self, token: str, callsign: str) -> MDBoxLayout:
        """Large, copyable token display card shown after generation."""
        card = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["12dp", "12dp"],
            spacing="8dp",
            md_bg_color="#0f1520",
        )
        card.bind(minimum_height=card.setter("height"))

        card.add_widget(
            MDLabel(
                text=f"Token for: [b]{callsign}[/b]",
                markup=True,
                font_style="Body",
                role="small",
                theme_text_color="Custom",
                text_color="#8a9bb0",
                size_hint_y=None,
                height="20dp",
            )
        )

        # Token in monospace font, large and readable
        token_row = MDBoxLayout(
            size_hint_y=None,
            height="40dp",
            spacing="8dp",
        )
        token_label = MDLabel(
            text=f"[font=RobotoMono]{token}[/font]",
            markup=True,
            font_style="Body",
            role="large",
            bold=True,
            theme_text_color="Custom",
            text_color="#00e5a0",
        )
        copy_btn = MDIconButton(
            icon="content-copy",
            theme_icon_color="Custom",
            icon_color="#8a9bb0",
            size_hint_x=None,
            on_release=lambda x: self._copy_token(token),
        )
        token_row.add_widget(token_label)
        token_row.add_widget(copy_btn)
        card.add_widget(token_row)

        card.add_widget(
            MDLabel(
                text="Give this token to the operator. It is single-use.",
                font_style="Body",
                role="small",
                theme_text_color="Custom",
                text_color="#3d4f63",
                size_hint_y=None,
                height="20dp",
            )
        )

        return card

    def _pending_row(self, token: str, info: dict) -> MDBoxLayout:
        """One row per pending (unused) token in the history list."""
        callsign = info.get("callsign", "?")
        generated_at = info.get("generated_at", 0)
        ago_secs = time.time() - generated_at
        if ago_secs < 3600:
            ago_str = f"{int(ago_secs / 60)}m ago"
        else:
            ago_str = f"{ago_secs / 3600:.1f}h ago"

        # Show abbreviated token
        token_short = f"{token[:8]}...{token[-4:]}"

        row = MDBoxLayout(
            size_hint_y=None,
            height="36dp",
            padding=["16dp", "4dp"],
            spacing="8dp",
            md_bg_color="#151d2b",
        )
        row.add_widget(
            MDLabel(
                text=f"[font=RobotoMono]{token_short}[/font]",
                markup=True,
                font_style="Body",
                role="small",
                theme_text_color="Custom",
                text_color="#8a9bb0",
                size_hint_x=None,
                width="120dp",
            )
        )
        row.add_widget(
            MDLabel(
                text=callsign,
                font_style="Body",
                role="small",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        row.add_widget(
            MDLabel(
                text=ago_str,
                font_style="Body",
                role="small",
                theme_text_color="Custom",
                text_color="#3d4f63",
                halign="right",
                size_hint_x=None,
                width="64dp",
            )
        )
        row.add_widget(
            MDIconButton(
                icon="content-copy",
                theme_icon_color="Custom",
                icon_color="#3d4f63",
                size_hint_x=None,
                on_release=lambda x, t=token: self._copy_token(t),
            )
        )
        return row

    def _copy_token(self, token: str):
        """Copy a token to the clipboard."""
        Clipboard.copy(token)
        from kivymd.uix.snackbar import MDSnackbar

        MDSnackbar(
            MDLabel(
                text="Token copied to clipboard.",
                theme_text_color="Custom",
                text_color="#00e5a0",
            )
        ).open()

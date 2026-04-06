# talon/ui/screens/sitreps.py
# SITREP panel — shown in the context panel on the right (desktop)
# or the bottom half (mobile).
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  SITREPS         [+ NEW]        │  ← header
#   ├─────────────────────────────────┤
#   │  ● FLASH   Alpha / 14:32        │  ← list items
#   │    Contact report — grid 4521   │
#   ├─────────────────────────────────┤
#   │  ● PRIORITY  Bravo / 13:10      │
#   │    CASEVAC required             │
#   └─────────────────────────────────┘
#
# Tapping a SITREP opens it in a detail view (same panel).
# The detail view shows all entries (append-only log).
# A compose area at the bottom lets operators add new entries.

import time

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import IconLeftWidget, MDList, TwoLineIconListItem
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from talon.models.sitrep import (
    append_entry,
    create_sitrep,
)
from talon.ui.theme import IMPORTANCE_COLORS


class SITREPPanel(MDBoxLayout):
    """Context panel content for the SITREPs section.

    Shows a scrollable list of SITREPs. Tapping one loads the
    detail view. The [+ NEW] button opens the compose dialog.

    Call refresh(talon_client) after attaching to the layout to
    populate the list from the local cache.
    """

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._sitreps = []  # List of SITREP dataclass objects
        self._active_sitrep = None  # Currently open SITREP
        self._compose_dialog = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Initial build
    # ------------------------------------------------------------------

    def _build_ui(self):
        """Construct the panel widgets programmatically."""
        # Header row
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )

        title = MDLabel(
            text="SITREPS",
            font_style="Button",
            bold=True,
            theme_text_color="Custom",
            text_color="#e8edf4",
        )

        new_btn = MDIconButton(
            icon="plus",
            theme_icon_color="Custom",
            icon_color="#00e5a0",
            on_release=lambda x: self.open_compose_dialog(),
        )

        header.add_widget(title)
        header.add_widget(new_btn)
        self.add_widget(header)

        # Divider
        from kivymd.uix.divider import MDDivider

        self.add_widget(MDDivider(color="#1e2d3d"))

        # Scrollable list
        scroll = MDScrollView(size_hint_y=1)
        self._list = MDList(md_bg_color="#0f1520")
        scroll.add_widget(self._list)
        self.add_widget(scroll)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def refresh(self, talon_client):
        """Load SITREPs from the local cache and populate the list.

        Args:
            talon_client: Running TalonClient instance.
        """
        self._talon = talon_client
        self._sitreps = []
        self._list.clear_widgets()

        if not talon_client or not talon_client.cache:
            self._show_empty("No connection.")
            return

        try:
            self._sitreps = talon_client.cache.get_all("sitreps") or []
        except Exception:
            self._show_empty("Could not load SITREPs.")
            return

        if not self._sitreps:
            self._show_empty("No SITREPs yet.")
            return

        # Sort newest first
        self._sitreps.sort(key=lambda s: s.created_at, reverse=True)

        for sitrep in self._sitreps:
            self._add_list_item(sitrep)

    def _add_list_item(self, sitrep):
        """Append one SITREP to the list."""
        importance_color = IMPORTANCE_COLORS.get(sitrep.importance, "#4a9eff")

        # Format timestamp
        ts = time.strftime("%H:%M", time.localtime(sitrep.created_at))
        secondary = f"{sitrep.created_by} · {ts}"

        item = TwoLineIconListItem(
            text=f"[color={importance_color}]{sitrep.importance}[/color]",
            secondary_text=secondary,
            markup=True,
            on_release=lambda x, s=sitrep: self.open_sitrep(s),
            md_bg_color="#151d2b",
        )

        icon = IconLeftWidget(
            icon="circle",
            theme_icon_color="Custom",
            icon_color=importance_color,
        )
        item.add_widget(icon)
        self._list.add_widget(item)

    def _show_empty(self, message: str):
        """Show a placeholder message when the list is empty."""
        self._list.add_widget(
            MDLabel(
                text=message,
                halign="center",
                theme_text_color="Custom",
                text_color="#3d4f63",
                padding=["16dp", "32dp"],
            )
        )

    # ------------------------------------------------------------------
    # Detail view
    # ------------------------------------------------------------------

    def open_sitrep(self, sitrep):
        """Replace the list with the SITREP detail view.

        Args:
            sitrep: SITREP dataclass object.
        """
        self._active_sitrep = sitrep
        self.clear_widgets()
        self._build_detail_view(sitrep)

    def _build_detail_view(self, sitrep):
        """Construct the detail view for a single SITREP."""
        importance_color = IMPORTANCE_COLORS.get(sitrep.importance, "#4a9eff")

        # Header with back button
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["8dp", "8dp"],
            md_bg_color="#0f1520",
        )

        back_btn = MDIconButton(
            icon="arrow-left",
            theme_icon_color="Custom",
            icon_color="#8a9bb0",
            on_release=lambda x: self._back_to_list(),
        )

        importance_label = MDLabel(
            text=f"[b][color={importance_color}]{sitrep.importance}[/color][/b]  SITREP",
            markup=True,
            theme_text_color="Custom",
            text_color="#e8edf4",
            font_style="Button",
        )

        header.add_widget(back_btn)
        header.add_widget(importance_label)
        self.add_widget(header)

        # Meta info
        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(sitrep.created_at))
        meta = MDLabel(
            text=f"Created by {sitrep.created_by} at {ts}",
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_y=None,
            height="24dp",
            padding=["16dp", 0],
        )
        self.add_widget(meta)

        from kivymd.uix.divider import MDDivider

        self.add_widget(MDDivider(color="#1e2d3d"))

        # Entries (append-only log)
        scroll = MDScrollView(size_hint_y=1)
        entries_list = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["16dp", "8dp"],
            spacing="8dp",
        )
        entries_list.bind(minimum_height=entries_list.setter("height"))

        entries = []
        if self._talon and self._talon.cache:
            try:
                entries = self._talon.cache.get_sitrep_entries(sitrep.id) or []
            except Exception:
                pass

        for entry in entries:
            entry_ts = time.strftime("%H:%M", time.localtime(entry.created_at))
            entry_box = MDBoxLayout(
                orientation="vertical",
                size_hint_y=None,
                padding=["12dp", "8dp"],
                spacing="4dp",
                md_bg_color="#151d2b",
            )
            entry_box.bind(minimum_height=entry_box.setter("height"))

            author_label = MDLabel(
                text=f"[b]{entry.author}[/b]  [color=#8a9bb0]{entry_ts}[/color]",
                markup=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
                font_style="Caption",
                size_hint_y=None,
                height="20dp",
            )
            content_label = MDLabel(
                text=entry.content,
                theme_text_color="Custom",
                text_color="#e8edf4",
                size_hint_y=None,
            )
            content_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))

            entry_box.add_widget(author_label)
            entry_box.add_widget(content_label)
            entries_list.add_widget(entry_box)

        if not entries:
            entries_list.add_widget(
                MDLabel(
                    text="No entries yet.",
                    theme_text_color="Custom",
                    text_color="#3d4f63",
                    size_hint_y=None,
                    height="32dp",
                )
            )

        scroll.add_widget(entries_list)
        self.add_widget(scroll)

        self.add_widget(MDDivider(color="#1e2d3d"))

        # Append entry input
        append_box = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            padding=["8dp", "4dp"],
            spacing="8dp",
            md_bg_color="#0f1520",
        )

        entry_field = MDTextField(
            hint_text="Append entry...",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
        )

        send_btn = MDIconButton(
            icon="send",
            theme_icon_color="Custom",
            icon_color="#00e5a0",
            on_release=lambda x: self._append_entry(entry_field, sitrep),
        )

        append_box.add_widget(entry_field)
        append_box.add_widget(send_btn)
        self.add_widget(append_box)

    def _back_to_list(self):
        """Return to the SITREP list view."""
        self._active_sitrep = None
        self.clear_widgets()
        self._build_ui()
        if self._talon:
            self.refresh(self._talon)

    def _append_entry(self, field, sitrep):
        """Submit a new entry to the SITREP."""
        content = field.text.strip()
        if not content:
            return

        if not self._talon:
            return

        callsign = ""
        if self._talon.cache:
            try:
                callsign = self._talon.cache.get_my_callsign() or ""
            except Exception:
                pass

        # Create the entry in the local model
        updated_sitrep = append_entry(sitrep, callsign, content)

        # Queue for sync
        if self._talon.sync:
            self._talon.sync.queue_change("sitreps", "update", updated_sitrep)

        field.text = ""
        # Refresh detail view to show the new entry
        self.open_sitrep(updated_sitrep)

    # ------------------------------------------------------------------
    # New SITREP compose dialog
    # ------------------------------------------------------------------

    def open_compose_dialog(self):
        """Open the new SITREP dialog."""
        if self._compose_dialog:
            self._compose_dialog.dismiss()

        content = _SITREPComposeContent()
        self._compose_dialog = MDDialog(
            title="New SITREP",
            type="custom",
            content_cls=content,
            buttons=[
                MDRaisedButton(
                    text="CANCEL",
                    md_bg_color="#1c2637",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._compose_dialog.dismiss(),
                ),
                MDRaisedButton(
                    text="CREATE",
                    md_bg_color="#00e5a0",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                    on_release=lambda x: self._submit_new_sitrep(content),
                ),
            ],
        )
        self._compose_dialog.open()

    def _submit_new_sitrep(self, content_widget):
        """Create a new SITREP from the compose dialog."""
        if not self._talon:
            return

        callsign = ""
        if self._talon.cache:
            try:
                callsign = self._talon.cache.get_my_callsign() or ""
            except Exception:
                pass

        importance = content_widget.selected_importance
        initial_entry = content_widget.ids.entry_field.text.strip()

        if not initial_entry:
            return

        # Create SITREP and first entry
        sitrep = create_sitrep(callsign, importance=importance)
        sitrep = append_entry(sitrep, callsign, initial_entry)

        # Queue for sync
        if self._talon.sync:
            self._talon.sync.queue_change("sitreps", "insert", sitrep)

        self._compose_dialog.dismiss()

        # Refresh list
        if self._talon.cache:
            try:
                self._talon.cache.save_sitrep(sitrep)
            except Exception:
                pass

        self._back_to_list()


class _SITREPComposeContent(MDBoxLayout):
    """Content widget for the new SITREP dialog."""

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            spacing="12dp",
            padding=["8dp", "8dp"],
            **kwargs,
        )
        self.bind(minimum_height=self.setter("height"))
        self.selected_importance = "ROUTINE"
        self._build()

    def _build(self):
        # Importance selector
        importance_label = MDLabel(
            text="Importance",
            font_style="Caption",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_y=None,
            height="20dp",
        )
        self.add_widget(importance_label)

        importance_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="40dp",
            spacing="8dp",
        )

        for level in ("ROUTINE", "PRIORITY", "FLASH"):
            color = IMPORTANCE_COLORS.get(level, "#4a9eff")
            btn = MDRaisedButton(
                text=level,
                md_bg_color=color if self.selected_importance == level else "#1c2637",
                theme_text_color="Custom",
                text_color="#0a0e14" if self.selected_importance == level else "#8a9bb0",
                on_release=lambda x, lv=level: self._select_importance(lv),
            )
            importance_row.add_widget(btn)

        self.add_widget(importance_row)

        # First entry field
        self.add_widget(
            MDTextField(
                id="entry_field",
                hint_text="Initial entry (what happened?)",
                mode="rectangle",
                multiline=True,
                fill_color_normal="#151d2b",
                fill_color_focus="#151d2b",
                line_color_focus="#00e5a0",
                size_hint_y=None,
                height="80dp",
            )
        )

    def _select_importance(self, level: str):
        self.selected_importance = level
        # Rebuild to update button colours
        self.clear_widgets()
        self._build()

# talon/ui/screens/missions.py
# Missions panel — mission list with objectives and notes.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  MISSIONS           [+ NEW]     │
#   ├─────────────────────────────────┤
#   │  Operation Eagle    ACTIVE      │
#   │  3 objectives · Alpha           │
#   ├─────────────────────────────────┤
#   │  MSR Tampa          PLANNING    │
#   │  1 objective · Bravo            │
#   └─────────────────────────────────┘
#
# Detail view shows objectives (assignee can update status)
# and a notes log (append-only, like SITREPs).

import time

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.button import MDRaisedButton, MDIconButton
from kivymd.uix.list import MDList, TwoLineIconListItem, IconLeftWidget
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField
from kivymd.uix.dialog import MDDialog

from talon.models.mission import (
    create_mission, add_objective, append_note,
    can_update_objective, can_abort_mission,
)
from talon.db.models import Objective


STATUS_COLORS = {
    "PLANNING":   "#8a9bb0",
    "ACTIVE":     "#00e5a0",
    "COMPLETED":  "#4a9eff",
    "ABORTED":    "#ff3b3b",
    "PAUSED":     "#f5a623",
}

OBJ_STATUS_COLORS = {
    "PENDING":     "#8a9bb0",
    "IN_PROGRESS": "#f5a623",
    "COMPLETE":    "#00e5a0",
    "CANCELLED":   "#ff3b3b",
}


class MissionsPanel(MDBoxLayout):
    """Context panel for the Missions section."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._missions = []
        self._dialog = None
        self._build_ui()

    def _build_ui(self):
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["16dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(MDLabel(
            text="MISSIONS",
            font_style="Button",
            bold=True,
            theme_text_color="Custom",
            text_color="#e8edf4",
        ))
        header.add_widget(MDIconButton(
            icon="plus",
            theme_icon_color="Custom",
            icon_color="#00e5a0",
            on_release=lambda x: self.open_create_dialog(),
        ))
        self.add_widget(header)

        from kivymd.uix.divider import MDDivider
        self.add_widget(MDDivider(color="#1e2d3d"))

        scroll = MDScrollView(size_hint_y=1)
        self._list = MDList(md_bg_color="#0f1520")
        scroll.add_widget(self._list)
        self.add_widget(scroll)

    def refresh(self, talon_client):
        self._talon = talon_client
        self._missions = []
        self._list.clear_widgets()

        if not talon_client or not talon_client.cache:
            return

        try:
            self._missions = talon_client.cache.get_all("missions") or []
        except Exception:
            return

        # Active first, then planning, then completed/aborted
        priority = {"ACTIVE": 0, "PLANNING": 1, "PAUSED": 2,
                    "COMPLETED": 3, "ABORTED": 4}
        self._missions.sort(key=lambda m: priority.get(m.status, 9))

        for mission in self._missions:
            self._add_list_item(mission)

    def _add_list_item(self, mission):
        color = STATUS_COLORS.get(mission.status, "#8a9bb0")
        item = TwoLineIconListItem(
            text=f"{mission.name}  [color={color}]{mission.status}[/color]",
            secondary_text=f"Created by {mission.created_by}",
            markup=True,
            on_release=lambda x, m=mission: self.open_mission_detail(m),
            md_bg_color="#151d2b",
        )
        icon = IconLeftWidget(
            icon="flag-outline",
            theme_icon_color="Custom",
            icon_color=color,
        )
        item.add_widget(icon)
        self._list.add_widget(item)

    def open_mission_detail(self, mission):
        self.clear_widgets()
        self._build_detail(mission)

    def _build_detail(self, mission):
        color = STATUS_COLORS.get(mission.status, "#8a9bb0")

        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["8dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(MDIconButton(
            icon="arrow-left",
            theme_icon_color="Custom",
            icon_color="#8a9bb0",
            on_release=lambda x: self._back_to_list(),
        ))
        header.add_widget(MDLabel(
            text=f"{mission.name}  [color={color}]{mission.status}[/color]",
            markup=True,
            font_style="Button",
            bold=True,
            theme_text_color="Custom",
            text_color="#e8edf4",
        ))
        self.add_widget(header)

        from kivymd.uix.divider import MDDivider
        self.add_widget(MDDivider(color="#1e2d3d"))

        scroll = MDScrollView(size_hint_y=1)
        content = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["16dp", "12dp"],
            spacing="12dp",
        )
        content.bind(minimum_height=content.setter("height"))

        # Objectives section
        content.add_widget(MDLabel(
            text="OBJECTIVES",
            font_style="Overline",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_y=None,
            height="20dp",
        ))

        objectives = []
        if self._talon and self._talon.cache:
            try:
                objectives = self._talon.cache.get_objectives(mission.id) or []
            except Exception:
                pass

        callsign = self._get_my_callsign()

        for obj in objectives:
            obj_color = OBJ_STATUS_COLORS.get(obj.status, "#8a9bb0")
            obj_row = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height="40dp",
                padding=["8dp", "4dp"],
                spacing="8dp",
                md_bg_color="#151d2b",
            )
            obj_row.add_widget(MDLabel(
                text=f"[color={obj_color}]●[/color]  {obj.description}",
                markup=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
                font_style="Body2",
            ))
            if obj.assigned_to:
                obj_row.add_widget(MDLabel(
                    text=obj.assigned_to,
                    font_style="Caption",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    size_hint_x=None,
                    width="80dp",
                    halign="right",
                ))

            # Status toggle for assigned operator
            if can_update_objective(callsign, obj, "operator"):
                next_status = {
                    "PENDING": "IN_PROGRESS",
                    "IN_PROGRESS": "COMPLETE",
                    "COMPLETE": "PENDING",
                }.get(obj.status, "IN_PROGRESS")

                obj_row.add_widget(MDIconButton(
                    icon="chevron-right",
                    theme_icon_color="Custom",
                    icon_color="#8a9bb0",
                    size_hint_x=None,
                    on_release=lambda x, o=obj, s=next_status: self._update_obj_status(o, s),
                ))

            content.add_widget(obj_row)

        if not objectives:
            content.add_widget(MDLabel(
                text="No objectives.",
                theme_text_color="Custom",
                text_color="#3d4f63",
                size_hint_y=None,
                height="28dp",
            ))

        content.add_widget(MDDivider(color="#1e2d3d"))

        # Notes log
        content.add_widget(MDLabel(
            text="NOTES LOG",
            font_style="Overline",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_y=None,
            height="20dp",
        ))

        notes = []
        if self._talon and self._talon.cache:
            try:
                notes = self._talon.cache.get_mission_notes(mission.id) or []
            except Exception:
                pass

        for note in notes:
            ts = time.strftime("%H:%M", time.localtime(note.created_at))
            note_box = MDBoxLayout(
                orientation="vertical",
                size_hint_y=None,
                padding=["8dp", "4dp"],
                spacing="2dp",
                md_bg_color="#151d2b",
            )
            note_box.bind(minimum_height=note_box.setter("height"))
            note_box.add_widget(MDLabel(
                text=f"[b]{note.author}[/b]  [color=#8a9bb0]{ts}[/color]",
                markup=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
                font_style="Caption",
                size_hint_y=None,
                height="20dp",
            ))
            note_label = MDLabel(
                text=note.content,
                theme_text_color="Custom",
                text_color="#e8edf4",
                size_hint_y=None,
            )
            note_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
            note_box.add_widget(note_label)
            content.add_widget(note_box)

        scroll.add_widget(content)
        self.add_widget(scroll)

        self.add_widget(MDDivider(color="#1e2d3d"))

        # Append note input
        note_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            padding=["8dp", "4dp"],
            spacing="8dp",
            md_bg_color="#0f1520",
        )
        note_field = MDTextField(
            hint_text="Add note...",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
        )
        note_row.add_widget(note_field)
        note_row.add_widget(MDIconButton(
            icon="send",
            theme_icon_color="Custom",
            icon_color="#00e5a0",
            on_release=lambda x: self._append_note(note_field, mission),
        ))
        self.add_widget(note_row)

    def _update_obj_status(self, obj, new_status):
        obj.status = new_status
        if self._talon and self._talon.sync:
            self._talon.sync.queue_change("objectives", "update", obj)
        if self._talon and self._talon.cache:
            try:
                self._talon.cache.save_objective(obj)
            except Exception:
                pass

    def _append_note(self, field, mission):
        content = field.text.strip()
        if not content:
            return
        callsign = self._get_my_callsign()
        updated = append_note(mission, callsign, content)
        if self._talon and self._talon.sync:
            self._talon.sync.queue_change("missions", "update", updated)
        field.text = ""

    def _back_to_list(self):
        self.clear_widgets()
        self._build_ui()
        if self._talon:
            self.refresh(self._talon)

    def open_create_dialog(self):
        content = _MissionCreateContent()
        self._dialog = MDDialog(
            title="New Mission",
            type="custom",
            content_cls=content,
            buttons=[
                MDRaisedButton(
                    text="CANCEL",
                    md_bg_color="#1c2637",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._dialog.dismiss(),
                ),
                MDRaisedButton(
                    text="CREATE",
                    md_bg_color="#00e5a0",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                    on_release=lambda x: self._submit_new_mission(content),
                ),
            ],
        )
        self._dialog.open()

    def _submit_new_mission(self, content):
        name = content.ids.name_field.text.strip()
        if not name:
            return
        callsign = self._get_my_callsign()
        mission = create_mission(name, callsign)
        if self._talon:
            if self._talon.sync:
                self._talon.sync.queue_change("missions", "insert", mission)
            if self._talon.cache:
                try:
                    self._talon.cache.save_mission(mission)
                except Exception:
                    pass
        self._dialog.dismiss()
        self._back_to_list()

    def _get_my_callsign(self) -> str:
        if not self._talon or not self._talon.cache:
            return ""
        try:
            return self._talon.cache.get_my_callsign() or ""
        except Exception:
            return ""


class _MissionCreateContent(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            spacing="12dp",
            padding=["8dp", "8dp"],
            **kwargs,
        )
        self.bind(minimum_height=self.setter("height"))
        self.add_widget(MDTextField(
            id="name_field",
            hint_text="Mission name",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        ))
        self.add_widget(MDTextField(
            id="desc_field",
            hint_text="Description (optional)",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        ))

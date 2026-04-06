# talon/ui/screens/chat.py
# Chat panel — channel list and message view.
#
# Layout (list view):
#   ┌─────────────────────────────────┐
#   │  CHAT               [+ NEW CH]  │
#   ├─────────────────────────────────┤
#   │  # General          3 unread    │
#   ├─────────────────────────────────┤
#   │  @ Alpha → Bravo    1 unread    │
#   └─────────────────────────────────┘
#
# Message view:
#   ┌─────────────────────────────────┐
#   │  ← General                      │
#   ├─────────────────────────────────┤
#   │  Alpha  14:30                   │
#   │  Checkpoint secured             │
#   │  Bravo  14:31                   │
#   │  Copy. Moving to Phase 2.       │
#   ├─────────────────────────────────┤
#   │  [Type a message...    ] [send] │
#   └─────────────────────────────────┘

import time

from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDIconButton
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogContentContainer,
    MDDialogHeadlineText,
)
from kivymd.uix.label import MDLabel
from kivymd.uix.list import IconLeftWidget, MDList, OneLineIconListItem
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from talon.models.chat import (
    can_send_message,
    create_channel,
    create_message,
)


class ChatPanel(MDBoxLayout):
    """Context panel for the Chat section."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._channels = []
        self._active_channel = None
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
        header.add_widget(
            MDLabel(
                text="CHAT",
                font_style="Label",
                role="large",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        header.add_widget(
            MDIconButton(
                icon="plus",
                theme_icon_color="Custom",
                icon_color="#00e5a0",
                on_release=lambda x: self.open_new_channel_dialog(),
            )
        )
        self.add_widget(header)

        from kivymd.uix.divider import MDDivider

        self.add_widget(MDDivider(color="#1e2d3d"))

        scroll = MDScrollView(size_hint_y=1)
        self._list = MDList(md_bg_color="#0f1520")
        scroll.add_widget(self._list)
        self.add_widget(scroll)

    def refresh(self, talon_client):
        self._talon = talon_client
        self._channels = []
        self._list.clear_widgets()

        if not talon_client or not talon_client.cache:
            return

        try:
            self._channels = talon_client.cache.get_all("channels") or []
        except Exception:
            return

        for channel in self._channels:
            self._add_channel_item(channel)

    def _add_channel_item(self, channel):
        # Icon differs by channel type
        is_dm = channel.type == "DIRECT"
        icon = "account" if is_dm else "pound"

        item = OneLineIconListItem(
            text=channel.name,
            on_release=lambda x, ch=channel: self.open_channel(ch),
            md_bg_color="#151d2b",
        )
        item.add_widget(
            IconLeftWidget(
                icon=icon,
                theme_icon_color="Custom",
                icon_color="#8a9bb0",
            )
        )
        self._list.add_widget(item)

    def open_channel(self, channel):
        self._active_channel = channel
        self.clear_widgets()
        self._build_message_view(channel)

    def _build_message_view(self, channel):
        # Header
        header = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="52dp",
            padding=["8dp", "8dp"],
            md_bg_color="#0f1520",
        )
        header.add_widget(
            MDIconButton(
                icon="arrow-left",
                theme_icon_color="Custom",
                icon_color="#8a9bb0",
                on_release=lambda x: self._back_to_channels(),
            )
        )
        header.add_widget(
            MDLabel(
                text=channel.name,
                font_style="Label",
                role="large",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        self.add_widget(header)

        from kivymd.uix.divider import MDDivider

        self.add_widget(MDDivider(color="#1e2d3d"))

        # Messages scroll area
        scroll = MDScrollView(size_hint_y=1)
        self._msg_container = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["12dp", "8dp"],
            spacing="8dp",
        )
        self._msg_container.bind(minimum_height=self._msg_container.setter("height"))

        self._load_messages(channel)

        scroll.add_widget(self._msg_container)
        self.add_widget(scroll)
        self._scroll_view = scroll

        self.add_widget(MDDivider(color="#1e2d3d"))

        # Message input
        input_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="56dp",
            padding=["8dp", "4dp"],
            spacing="8dp",
            md_bg_color="#0f1520",
        )
        self._msg_field = MDTextField(
            hint_text="Message...",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            on_text_validate=lambda x: self._send_message(),
        )
        input_row.add_widget(self._msg_field)
        input_row.add_widget(
            MDIconButton(
                icon="send",
                theme_icon_color="Custom",
                icon_color="#00e5a0",
                on_release=lambda x: self._send_message(),
            )
        )
        self.add_widget(input_row)

        # Scroll to bottom after layout
        from kivy.clock import Clock

        Clock.schedule_once(lambda dt: setattr(scroll, "scroll_y", 0), 0.2)

    def _load_messages(self, channel):
        self._msg_container.clear_widgets()
        messages = []

        if self._talon and self._talon.cache:
            try:
                messages = self._talon.cache.get_messages(channel.id) or []
            except Exception:
                pass

        if not messages:
            self._msg_container.add_widget(
                MDLabel(
                    text="No messages yet.",
                    theme_text_color="Custom",
                    text_color="#3d4f63",
                    size_hint_y=None,
                    height="32dp",
                    halign="center",
                )
            )
            return

        prev_sender = None
        for msg in messages:
            ts = time.strftime("%H:%M", time.localtime(msg.created_at))
            show_header = msg.sender != prev_sender
            prev_sender = msg.sender

            msg_box = MDBoxLayout(
                orientation="vertical",
                size_hint_y=None,
                padding=["4dp", "2dp"],
                spacing="2dp",
            )
            msg_box.bind(minimum_height=msg_box.setter("height"))

            if show_header:
                msg_box.add_widget(
                    MDLabel(
                        text=f"[b]{msg.sender}[/b]  [color=#3d4f63]{ts}[/color]",
                        markup=True,
                        font_style="Body",
                        role="small",
                        theme_text_color="Custom",
                        text_color="#8a9bb0",
                        size_hint_y=None,
                        height="18dp",
                    )
                )

            body_label = MDLabel(
                text=msg.body,
                theme_text_color="Custom",
                text_color="#e8edf4",
                size_hint_y=None,
            )
            body_label.bind(texture_size=lambda inst, val: setattr(inst, "height", val[1]))
            msg_box.add_widget(body_label)
            self._msg_container.add_widget(msg_box)

    def _send_message(self):
        body = self._msg_field.text.strip()
        if not body or not self._active_channel:
            return

        callsign = self._get_my_callsign()
        members = []
        if self._talon and self._talon.cache:
            try:
                members = self._talon.cache.get_channel_members(self._active_channel.id) or []
            except Exception:
                pass

        if not can_send_message(callsign, members):
            return

        msg = create_message(self._active_channel.id, callsign, body)

        if self._talon:
            if self._talon.sync:
                self._talon.sync.queue_change("messages", "insert", msg)
            if self._talon.cache:
                try:
                    self._talon.cache.save_message(msg)
                except Exception:
                    pass

        self._msg_field.text = ""
        self._load_messages(self._active_channel)

        from kivy.clock import Clock

        if hasattr(self, "_scroll_view"):
            Clock.schedule_once(lambda dt: setattr(self._scroll_view, "scroll_y", 0), 0.1)

    def _back_to_channels(self):
        self._active_channel = None
        self.clear_widgets()
        self._build_ui()
        if self._talon:
            self.refresh(self._talon)

    def open_new_channel_dialog(self):
        content = _NewChannelContent()
        self._dialog = MDDialog(
            MDDialogHeadlineText(text="New Channel"),
            MDDialogContentContainer(content),
            MDDialogButtonContainer(
                MDButton(
                    style="elevated",
                    text="CANCEL",
                    md_bg_color="#1c2637",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    on_release=lambda x: self._dialog.dismiss(),
                ),
                MDButton(
                    style="elevated",
                    text="CREATE",
                    md_bg_color="#00e5a0",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                    on_release=lambda x: self._submit_new_channel(content),
                ),
            ),
        )
        self._dialog.open()

    def _submit_new_channel(self, content):
        name = content.name_field.text.strip()
        if not name:
            return
        callsign = self._get_my_callsign()
        channel = create_channel(name, callsign, channel_type="GROUP")
        if self._talon:
            if self._talon.sync:
                self._talon.sync.queue_change("channels", "insert", channel)
            if self._talon.cache:
                try:
                    self._talon.cache.save_channel(channel)
                except Exception:
                    pass
        self._dialog.dismiss()
        self._back_to_channels()

    def _get_my_callsign(self) -> str:
        if not self._talon or not self._talon.cache:
            return ""
        try:
            return self._talon.cache.get_my_callsign() or ""
        except Exception:
            return ""


class _NewChannelContent(MDBoxLayout):
    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            spacing="12dp",
            padding=["8dp", "8dp"],
            **kwargs,
        )
        self.bind(minimum_height=self.setter("height"))
        self.name_field = MDTextField(
            hint_text="Channel name",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        )
        self.add_widget(self.name_field)

# talon/ui/screens/documents.py
# Documents panel — browse and view shared documents.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  DOCUMENTS          [+ UPLOAD]  │
#   ├─────────────────────────────────┤
#   │  [PDF] Map Overlay      ALL     │
#   │        Alpha · 2.4 MB           │
#   ├─────────────────────────────────┤
#   │  [IMG] AO Satellite  RESTRICTED │
#   │        Bravo · 8.1 MB           │
#   └─────────────────────────────────┘
#
# Documents can only be viewed if access_level permits.
# Upload queues the file for broadband sync (not LoRa).

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
from kivymd.uix.list import IconLeftWidget, MDList, TwoLineIconListItem
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from talon.models.document import (
    can_view_document,
    create_document,
    validate_document,
)

ACCESS_COLORS = {
    "ALL": "#00e5a0",
    "RESTRICTED": "#f5a623",
}

# Icon per file type
FILE_ICONS = {
    "pdf": "file-pdf-box",
    "image": "file-image",
    "png": "file-image",
    "jpg": "file-image",
    "jpeg": "file-image",
    "text": "file-document",
    "txt": "file-document",
}


def _file_icon(file_type: str) -> str:
    return FILE_ICONS.get((file_type or "").lower(), "file-outline")


def _format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


class DocumentsPanel(MDBoxLayout):
    """Context panel for the Documents section."""

    def __init__(self, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self._talon = None
        self._documents = []
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
                text="DOCUMENTS",
                font_style="Label",
                role="large",
                bold=True,
                theme_text_color="Custom",
                text_color="#e8edf4",
            )
        )
        header.add_widget(
            MDIconButton(
                icon="upload",
                theme_icon_color="Custom",
                icon_color="#00e5a0",
                on_release=lambda x: self.open_upload_dialog(),
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
        self._documents = []
        self._list.clear_widgets()

        if not talon_client or not talon_client.cache:
            return

        callsign = self._get_my_callsign()

        try:
            all_docs = talon_client.cache.get_all("documents") or []
        except Exception:
            return

        # Filter to docs this operator can see
        self._documents = [d for d in all_docs if can_view_document(d, callsign, "operator")]
        self._documents.sort(key=lambda d: d.uploaded_at, reverse=True)

        for doc in self._documents:
            self._add_list_item(doc)

    def _add_list_item(self, doc):
        access_color = ACCESS_COLORS.get(doc.access_level, "#8a9bb0")
        size_str = _format_size(doc.file_size) if doc.file_size else ""
        secondary = f"{doc.uploaded_by} · {size_str}"

        item = TwoLineIconListItem(
            text=f"{doc.title}  [color={access_color}]{doc.access_level}[/color]",
            secondary_text=secondary,
            markup=True,
            on_release=lambda x, d=doc: self.open_document_detail(d),
            md_bg_color="#151d2b",
        )
        icon = IconLeftWidget(
            icon=_file_icon(doc.file_type),
            theme_icon_color="Custom",
            icon_color="#8a9bb0",
        )
        item.add_widget(icon)
        self._list.add_widget(item)

    def open_document_detail(self, doc):
        self.clear_widgets()
        self._build_detail(doc)

    def _build_detail(self, doc):
        access_color = ACCESS_COLORS.get(doc.access_level, "#8a9bb0")

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
                on_release=lambda x: self._back_to_list(),
            )
        )
        header.add_widget(
            MDLabel(
                text=doc.title,
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

        details = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=["16dp", "12dp"],
            spacing="8dp",
        )
        details.bind(minimum_height=details.setter("height"))

        def row(label, value, color=None):
            r = MDBoxLayout(
                orientation="horizontal",
                size_hint_y=None,
                height="24dp",
            )
            r.add_widget(
                MDLabel(
                    text=label,
                    font_style="Body",
                    role="small",
                    theme_text_color="Custom",
                    text_color="#8a9bb0",
                    size_hint_x=0.4,
                )
            )
            r.add_widget(
                MDLabel(
                    text=value,
                    font_style="Body",
                    role="small",
                    theme_text_color="Custom",
                    text_color=color or "#e8edf4",
                    size_hint_x=0.6,
                )
            )
            return r

        ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(doc.uploaded_at)) if doc.uploaded_at else "Unknown"

        details.add_widget(row("Type", doc.file_type or "Unknown"))
        details.add_widget(row("Size", _format_size(doc.file_size) if doc.file_size else "Unknown"))
        details.add_widget(row("Access", doc.access_level, access_color))
        details.add_widget(row("Uploaded by", doc.uploaded_by))
        details.add_widget(row("Uploaded at", ts))

        if doc.tags:
            tags_str = ", ".join(doc.tags) if isinstance(doc.tags, list) else str(doc.tags)
            details.add_widget(row("Tags", tags_str))

        self.add_widget(details)

        # Open / view button — launches the file with the system viewer
        open_btn = MDButton(
            style="elevated",
            text="OPEN DOCUMENT",
            md_bg_color="#00e5a0",
            theme_text_color="Custom",
            text_color="#0a0e14",
            size_hint_x=None,
            pos_hint={"center_x": 0.5},
            on_release=lambda x: self._open_file(doc),
        )
        self.add_widget(open_btn)

    def _open_file(self, doc):
        """Open the document with the OS default viewer."""
        from talon.platform import open_file

        open_file(doc.file_path)

    def _back_to_list(self):
        self.clear_widgets()
        self._build_ui()
        if self._talon:
            self.refresh(self._talon)

    def open_upload_dialog(self):
        """Open file chooser and queue upload."""
        content = _UploadContent()
        self._dialog = MDDialog(
            MDDialogHeadlineText(text="Upload Document"),
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
                    text="QUEUE UPLOAD",
                    md_bg_color="#00e5a0",
                    theme_text_color="Custom",
                    text_color="#0a0e14",
                    on_release=lambda x: self._submit_upload(content),
                ),
            ),
        )
        self._dialog.open()

    def _submit_upload(self, content):
        title = content.title_field.text.strip()
        file_path = content.path_field.text.strip()
        access = content.selected_access

        if not title or not file_path:
            return

        import os

        if not os.path.isfile(file_path):
            return

        file_size = os.path.getsize(file_path)
        file_type = os.path.splitext(file_path)[1].lstrip(".").lower() or "unknown"
        callsign = self._get_my_callsign()

        doc = create_document(
            title,
            callsign,
            file_path,
            file_size=file_size,
            mime_type=file_type,
            access=access,
        )

        errors = validate_document(doc)
        if errors:
            return  # TODO: show errors in dialog

        if self._talon:
            # Documents are broadband-only — queued for next broadband sync
            if self._talon.sync:
                self._talon.sync.queue_change("documents", "insert", doc)
            if self._talon.cache:
                try:
                    self._talon.cache.save_document(doc)
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


class _UploadContent(MDBoxLayout):
    ACCESS_LEVELS = ["ALL", "RESTRICTED"]

    def __init__(self, **kwargs):
        super().__init__(
            orientation="vertical",
            size_hint_y=None,
            spacing="12dp",
            padding=["8dp", "8dp"],
            **kwargs,
        )
        self.bind(minimum_height=self.setter("height"))
        self.selected_access = "ALL"
        self._build()

    def _build(self):
        self.title_field = MDTextField(
            hint_text="Document title",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        )
        self.add_widget(self.title_field)
        self.path_field = MDTextField(
            hint_text="File path",
            mode="rectangle",
            fill_color_normal="#151d2b",
            fill_color_focus="#151d2b",
            line_color_focus="#00e5a0",
            size_hint_y=None,
            height="48dp",
        )
        self.add_widget(self.path_field)

        access_label = MDLabel(
            text="Access level",
            font_style="Body",
            role="small",
            theme_text_color="Custom",
            text_color="#8a9bb0",
            size_hint_y=None,
            height="20dp",
        )
        self.add_widget(access_label)

        row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height="40dp",
            spacing="8dp",
        )
        for level in self.ACCESS_LEVELS:
            color = ACCESS_COLORS.get(level, "#8a9bb0")
            row.add_widget(
                MDButton(
                    style="elevated",
                    text=level,
                    md_bg_color=color if level == self.selected_access else "#1c2637",
                    theme_text_color="Custom",
                    text_color="#0a0e14" if level == self.selected_access else "#8a9bb0",
                    on_release=lambda x, lv=level: self._select_access(lv),
                )
            )
        self.add_widget(row)

    def _select_access(self, level):
        self.selected_access = level
        self.clear_widgets()
        self._build()

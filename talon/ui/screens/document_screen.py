"""
Document screen — shared tactical document repository.

Phase 1:  Server operators can upload, browse, download, and delete documents
          directly on the server machine.
Phase 2:  Client upload / download over Reticulum sync (deferred).

Mode guards
-----------
Upload    : server mode only in Phase 1; shows informational message on client.
Delete    : server mode only; button hidden for clients.
Download  : works in both modes (Phase 1: reads local disk; Phase 2: from sync cache).
"""
import datetime
import pathlib

from kivy.app import App
from kivy.metrics import dp
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.modalview import ModalView
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDButton, MDButtonText, MDIconButton
from kivymd.uix.dialog import (
    MDDialog,
    MDDialogButtonContainer,
    MDDialogHeadlineText,
    MDDialogSupportingText,
)
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField, MDTextFieldHintText

from talon.constants import DOCUMENT_WARN_EXTENSIONS
from talon.documents import (
    DocumentBlockedExtension,
    DocumentError,
    DocumentFilenameInvalid,
    DocumentIntegrityError,
    DocumentSizeExceeded,
    delete_document,
    download_document,
    list_documents,
    upload_document,
)
from talon.ui.theme import COLOR_ACCENT, COLOR_DANGER, COLOR_PRIMARY, COLOR_TEXT_SECONDARY
from talon.utils.logging import get_logger

_log = get_logger("ui.documents")

# ---------------------------------------------------------------------------
# MIME → icon mapping
# ---------------------------------------------------------------------------

def _mime_icon(mime_type: str) -> str:
    if mime_type == "application/pdf":
        return "file-pdf-box"
    if mime_type.startswith("image/"):
        return "file-image-outline"
    if mime_type.startswith("video/"):
        return "file-video-outline"
    if mime_type.startswith("audio/"):
        return "file-music-outline"
    if mime_type in ("application/zip", "application/x-tar",
                     "application/gzip", "application/x-7z-compressed"):
        return "folder-zip-outline"
    if "spreadsheet" in mime_type or "excel" in mime_type:
        return "file-excel-outline"
    if "presentation" in mime_type or "powerpoint" in mime_type:
        return "file-powerpoint-outline"
    if "word" in mime_type or "document" in mime_type:
        return "file-word-outline"
    return "file-document-outline"


def _fmt_size(size_bytes: int) -> str:
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / 1024 / 1024:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


# ---------------------------------------------------------------------------
# Document list row
# ---------------------------------------------------------------------------

class _DocumentRow(MDBoxLayout):
    """One row in the document list.

    Layout (horizontal, 64dp tall):
      [mime icon]  [filename (bold) + type/size + uploader]  [OPEN button]
    """

    def __init__(self, doc, callsign: str, screen: "DocumentScreen", **kwargs):
        super().__init__(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(64),
            spacing=dp(8),
            padding=(dp(4), dp(4)),
            **kwargs,
        )
        self._doc = doc
        self._screen = screen

        # Mime icon
        self.add_widget(MDIconButton(
            icon=_mime_icon(doc.mime_type),
            size_hint=(None, None),
            size=(dp(40), dp(40)),
            theme_icon_color="Custom",
            icon_color=COLOR_PRIMARY,
        ))

        # Info column
        info = MDBoxLayout(orientation="vertical", spacing=dp(2))
        info.add_widget(MDLabel(
            text=doc.filename,
            font_style="Body",
            role="medium",
            bold=True,
            adaptive_height=True,
        ))
        ts = datetime.datetime.fromtimestamp(doc.uploaded_at).strftime("%Y-%m-%d %H:%M")
        info.add_widget(MDLabel(
            text=f"{doc.mime_type}  ·  {_fmt_size(doc.size_bytes)}  ·  {callsign}  ·  {ts}",
            font_style="Label",
            role="small",
            theme_text_color="Secondary",
            adaptive_height=True,
        ))
        self.add_widget(info)

        # Open button
        open_btn = MDButton(MDButtonText(text="OPEN"), style="text",
                            size_hint=(None, None), size=(dp(72), dp(36)))
        open_btn.bind(on_release=lambda _: screen._open_detail_dialog(doc))
        self.add_widget(open_btn)


# ---------------------------------------------------------------------------
# Main screen
# ---------------------------------------------------------------------------

class DocumentScreen(MDScreen):
    """Shared document repository screen."""

    def on_pre_enter(self) -> None:
        App.get_running_app().clear_badge("documents")
        self._load_documents()

    def on_back_pressed(self) -> None:
        self.manager.current = "main"

    def on_refresh_pressed(self) -> None:
        self._load_documents()

    def on_upload_pressed(self) -> None:
        app = App.get_running_app()
        if app.mode != "server":
            self._show_info_dialog(
                "Upload Unavailable",
                "Document upload from client mode will be available in a future update "
                "when Reticulum sync is wired.",
            )
            return
        self._open_file_chooser()

    # ------------------------------------------------------------------
    # Document list
    # ------------------------------------------------------------------

    def _load_documents(self) -> None:
        app = App.get_running_app()
        lst = self.ids.document_list
        lst.clear_widgets()
        if app.conn is None:
            lst.add_widget(MDLabel(
                text="Database not available.",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(48),
                halign="center",
            ))
            return
        try:
            docs = list_documents(app.conn)
            if not docs:
                lst.add_widget(MDLabel(
                    text="No documents uploaded yet.",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(48),
                    halign="center",
                ))
                return
            # Build a callsign lookup to avoid one query per row
            callsigns = _load_callsigns(app.conn)
            for doc in docs:
                callsign = callsigns.get(doc.uploaded_by, f"id={doc.uploaded_by}")
                lst.add_widget(_DocumentRow(doc=doc, callsign=callsign, screen=self))
        except Exception as exc:
            _log.error("Failed to load documents: %s", exc)

    # ------------------------------------------------------------------
    # Upload flow (two modals: file chooser → detail/confirm)
    # ------------------------------------------------------------------

    def _open_file_chooser(self) -> None:
        """Open a file chooser modal. User selects a file, then CONFIRM opens the detail modal."""
        modal = ModalView(size_hint=(0.85, 0.85), auto_dismiss=False)
        outer = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        chooser = FileChooserListView(size_hint=(1, 1))
        outer.add_widget(chooser)

        btn_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        confirm_btn = MDButton(MDButtonText(text="SELECT"), style="filled")

        def _on_confirm(_):
            if not chooser.selection:
                return
            modal.dismiss()
            self._open_upload_detail(chooser.selection[0])

        confirm_btn.bind(on_release=_on_confirm)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(confirm_btn)
        outer.add_widget(btn_row)
        modal.add_widget(outer)
        modal.open()

    def _open_upload_detail(self, file_path: str) -> None:
        """Second upload modal: filename preview + optional description + UPLOAD."""
        import os
        raw_filename = os.path.basename(file_path)
        try:
            size_bytes = os.path.getsize(file_path)
        except OSError:
            size_bytes = 0

        modal = ModalView(size_hint=(0.65, None), height=dp(360), auto_dismiss=False)
        content = MDBoxLayout(
            orientation="vertical",
            padding=dp(24),
            spacing=dp(12),
        )

        content.add_widget(MDLabel(
            text="Upload Document",
            font_style="Title",
            role="medium",
            size_hint_y=None,
            height=dp(32),
        ))
        content.add_widget(MDLabel(
            text=raw_filename,
            font_style="Body",
            role="medium",
            bold=True,
            size_hint_y=None,
            height=dp(24),
        ))
        content.add_widget(MDLabel(
            text=_fmt_size(size_bytes),
            font_style="Label",
            role="small",
            theme_text_color="Secondary",
            size_hint_y=None,
            height=dp(20),
        ))

        desc_field = MDTextField(
            MDTextFieldHintText(text="Description (optional)"),
            mode="outlined",
            size_hint_y=None,
            height=dp(48),
        )
        content.add_widget(desc_field)

        status_lbl = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=COLOR_DANGER,
            font_style="Label",
            role="small",
            size_hint_y=None,
            height=dp(20),
        )
        content.add_widget(status_lbl)

        btn_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        upload_btn = MDButton(MDButtonText(text="UPLOAD"), style="filled")
        upload_btn.bind(on_release=lambda _: self._do_upload(
            modal, status_lbl, file_path, desc_field.text.strip()
        ))
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(upload_btn)
        content.add_widget(btn_row)

        modal.add_widget(content)
        modal.open()

    def _do_upload(
        self,
        modal: ModalView,
        status_lbl: MDLabel,
        file_path: str,
        description: str,
    ) -> None:
        app = App.get_running_app()
        if app.conn is None or app.db_key is None:
            status_lbl.text = "Database not available."
            return
        from talon.constants import MAX_DOCUMENT_SIZE_BYTES
        if pathlib.Path(file_path).stat().st_size > MAX_DOCUMENT_SIZE_BYTES:
            status_lbl.text = f"File too large (max {MAX_DOCUMENT_SIZE_BYTES // 1024 // 1024} MB)."
            return

        try:
            file_data = pathlib.Path(file_path).read_bytes()
        except OSError as exc:
            status_lbl.text = f"Cannot read file: {exc}"
            return

        from talon.config import get_document_storage_path
        storage_root = get_document_storage_path(app.cfg)

        try:
            import os
            operator_id = app.require_local_operator_id(
                allow_server_sentinel=(app.mode == "server")
            )
            doc = upload_document(
                app.conn,
                app.db_key,
                storage_root,
                raw_filename=os.path.basename(file_path),
                file_data=file_data,
                uploaded_by=operator_id,
                description=description,
            )
            app.net_notify_change("documents", doc.id)
        except DocumentSizeExceeded:
            from talon.constants import MAX_DOCUMENT_SIZE_BYTES
            status_lbl.text = f"File too large (max {MAX_DOCUMENT_SIZE_BYTES // 1024 // 1024} MB)."
            return
        except DocumentFilenameInvalid as exc:
            status_lbl.text = f"Invalid filename: {exc}"
            return
        except DocumentBlockedExtension as exc:
            status_lbl.text = f"File type not allowed: {exc}"
            return
        except DocumentError as exc:
            status_lbl.text = f"Upload failed: {exc}"
            return
        except Exception as exc:
            _log.error("Unexpected upload error: %s", exc)
            status_lbl.text = "Upload failed (unexpected error)."
            return

        modal.dismiss()
        self._load_documents()

    # ------------------------------------------------------------------
    # Detail dialog (OPEN button)
    # ------------------------------------------------------------------

    def _open_detail_dialog(self, doc) -> None:
        app = App.get_running_app()
        callsigns = _load_callsigns(app.conn) if app.conn else {}
        callsign = callsigns.get(doc.uploaded_by, f"id={doc.uploaded_by}")
        ts = datetime.datetime.fromtimestamp(doc.uploaded_at).strftime("%Y-%m-%d %H:%M")

        modal = ModalView(size_hint=(0.65, None), height=dp(360), auto_dismiss=False)
        content = MDBoxLayout(
            orientation="vertical",
            padding=dp(24),
            spacing=dp(8),
        )

        content.add_widget(MDLabel(
            text=doc.filename,
            font_style="Title",
            role="medium",
            bold=True,
            size_hint_y=None,
            height=dp(32),
        ))

        for label, value in [
            ("Type",        doc.mime_type),
            ("Size",        _fmt_size(doc.size_bytes)),
            ("Uploaded by", callsign),
            ("Date",        ts),
            ("Hash",        doc.sha256_hash[:24] + "…"),
        ]:
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
            row.add_widget(MDLabel(
                text=label,
                font_style="Label",
                role="small",
                theme_text_color="Secondary",
                size_hint_x=None,
                width=dp(100),
            ))
            row.add_widget(MDLabel(
                text=value,
                font_style="Body",
                role="small",
                adaptive_height=True,
            ))
            content.add_widget(row)

        if doc.description:
            content.add_widget(MDLabel(
                text=doc.description,
                font_style="Body",
                role="small",
                theme_text_color="Secondary",
                size_hint_y=None,
                height=dp(24),
            ))

        btn_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(44),
            spacing=dp(8),
        )
        close_btn = MDButton(MDButtonText(text="CLOSE"), style="text")
        close_btn.bind(on_release=lambda _: modal.dismiss())
        btn_row.add_widget(close_btn)

        dl_btn = MDButton(MDButtonText(text="DOWNLOAD"), style="outlined")
        dl_btn.bind(on_release=lambda _: self._do_download(modal, doc))
        btn_row.add_widget(dl_btn)

        if app.mode == "server":
            del_btn = MDButton(MDButtonText(text="DELETE"), style="filled")
            del_btn.bind(on_release=lambda _: (modal.dismiss(), self._confirm_delete(doc)))
            btn_row.add_widget(del_btn)

        content.add_widget(btn_row)
        modal.add_widget(content)
        modal.open()

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def _do_download(self, detail_modal: ModalView, doc) -> None:
        """Prompt for a save path, then decrypt and write the file."""
        app = App.get_running_app()
        if app.conn is None or app.db_key is None:
            return

        from talon.config import get_document_storage_path
        storage_root = get_document_storage_path(app.cfg)

        try:
            operator_id = app.require_local_operator_id(
                allow_server_sentinel=(app.mode == "server")
            )
            _, plaintext = download_document(
                app.conn,
                app.db_key,
                storage_root,
                doc.id,
                downloader_id=operator_id,
            )
        except DocumentIntegrityError as exc:
            detail_modal.dismiss()
            self._show_error_dialog("Integrity Check Failed", str(exc))
            return
        except DocumentError as exc:
            detail_modal.dismiss()
            self._show_error_dialog("Download Failed", str(exc))
            return
        except Exception as exc:
            detail_modal.dismiss()
            self._show_error_dialog("Download Failed", str(exc))
            return

        # Check for macro-capable extensions and warn before saving
        suffix = pathlib.Path(doc.filename).suffix.lower()
        if suffix in DOCUMENT_WARN_EXTENSIONS:
            self._warn_macro_then_save(detail_modal, doc.filename, plaintext)
        else:
            detail_modal.dismiss()
            self._open_save_dialog(doc.filename, plaintext)

    def _warn_macro_then_save(
        self, detail_modal: ModalView, filename: str, plaintext: bytes
    ) -> None:
        """Show a macro-risk warning dialog before allowing the save."""
        warn = ModalView(size_hint=(0.55, None), height=dp(220), auto_dismiss=False)
        content = MDBoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        content.add_widget(MDLabel(
            text="Security Warning",
            font_style="Title",
            role="medium",
            theme_text_color="Custom",
            text_color=COLOR_ACCENT,
            size_hint_y=None,
            height=dp(32),
        ))
        content.add_widget(MDLabel(
            text=(
                f"{filename!r} is a document type that can contain macros or "
                "embedded scripts. Only open it if you trust the source."
            ),
            font_style="Body",
            role="small",
            adaptive_height=True,
        ))
        btn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(44), spacing=dp(8))
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: warn.dismiss())
        save_btn = MDButton(MDButtonText(text="SAVE ANYWAY"), style="filled")

        def _save(_):
            warn.dismiss()
            detail_modal.dismiss()
            self._open_save_dialog(filename, plaintext)

        save_btn.bind(on_release=_save)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(save_btn)
        content.add_widget(btn_row)
        warn.add_widget(content)
        warn.open()

    def _open_save_dialog(self, filename: str, plaintext: bytes) -> None:
        """Open a file chooser to pick the save directory, then write the file."""
        modal = ModalView(size_hint=(0.85, 0.85), auto_dismiss=False)
        outer = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        outer.add_widget(MDLabel(
            text=f"Save as: {filename}",
            font_style="Body",
            role="medium",
            size_hint_y=None,
            height=dp(28),
        ))

        chooser = FileChooserListView(size_hint=(1, 1), dirselect=True)
        outer.add_widget(chooser)

        status_lbl = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=COLOR_DANGER,
            font_style="Label",
            role="small",
            size_hint_y=None,
            height=dp(20),
        )
        outer.add_widget(status_lbl)

        btn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(44), spacing=dp(8))
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        save_btn = MDButton(MDButtonText(text="SAVE HERE"), style="filled")

        def _do_save(_):
            import os
            save_dir = chooser.path
            dest = pathlib.Path(save_dir) / filename
            try:
                dest.write_bytes(plaintext)
                modal.dismiss()
                _log.info("Document saved to %s", dest)
            except OSError as exc:
                status_lbl.text = f"Save failed: {exc}"

        save_btn.bind(on_release=_do_save)
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(save_btn)
        outer.add_widget(btn_row)

        modal.add_widget(outer)
        modal.open()

    # ------------------------------------------------------------------
    # Delete (server only)
    # ------------------------------------------------------------------

    def _confirm_delete(self, doc) -> None:
        modal = ModalView(size_hint=(0.5, None), height=dp(180), auto_dismiss=False)
        content = MDBoxLayout(orientation="vertical", padding=dp(24), spacing=dp(12))
        content.add_widget(MDLabel(
            text="Delete Document?",
            font_style="Title",
            role="medium",
            size_hint_y=None,
            height=dp(32),
        ))
        content.add_widget(MDLabel(
            text=f"{doc.filename}\n\nThis cannot be undone.",
            font_style="Body",
            role="small",
            adaptive_height=True,
        ))
        btn_row = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                              height=dp(44), spacing=dp(8))
        cancel_btn = MDButton(MDButtonText(text="CANCEL"), style="text")
        cancel_btn.bind(on_release=lambda _: modal.dismiss())
        del_btn = MDButton(MDButtonText(text="DELETE"), style="filled")
        del_btn.bind(on_release=lambda _: self._do_delete(modal, doc))
        btn_row.add_widget(cancel_btn)
        btn_row.add_widget(del_btn)
        content.add_widget(btn_row)
        modal.add_widget(content)
        modal.open()

    def _do_delete(self, modal: ModalView, doc) -> None:
        modal.dismiss()
        app = App.get_running_app()
        if app.conn is None:
            return
        from talon.config import get_document_storage_path
        storage_root = get_document_storage_path(app.cfg)
        try:
            delete_document(app.conn, storage_root, doc.id)
            app.net_notify_delete("documents", doc.id)
            self._load_documents()
        except Exception as exc:
            _log.error("Delete failed: %s", exc)
            self._show_error_dialog("Delete Failed", str(exc))

    # ------------------------------------------------------------------
    # Generic dialogs
    # ------------------------------------------------------------------

    def _show_info_dialog(self, title: str, message: str) -> None:
        dialog = MDDialog(
            MDDialogHeadlineText(text=title),
            MDDialogSupportingText(text=message),
            MDDialogButtonContainer(
                MDButton(MDButtonText(text="OK"), style="text",
                         on_release=lambda _: dialog.dismiss()),
            ),
        )
        dialog.open()

    def _show_error_dialog(self, title: str, message: str) -> None:
        dialog = MDDialog(
            MDDialogHeadlineText(text=title),
            MDDialogSupportingText(text=message),
            MDDialogButtonContainer(
                MDButton(MDButtonText(text="OK"), style="text",
                         on_release=lambda _: dialog.dismiss()),
            ),
        )
        dialog.open()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_callsigns(conn) -> dict[int, str]:
    """Return {operator_id: callsign} for all operators."""
    try:
        rows = conn.execute("SELECT id, callsign FROM operators").fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}

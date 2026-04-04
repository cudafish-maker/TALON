# talon/models/document.py
# Business logic for Documents (shared files).
#
# Documents let operators share files (images, PDFs, maps, overlays)
# with the team. They are stored on the server and synced to clients
# over broadband connections only (too large for LoRa).
#
# Rules:
# - Any operator can upload documents
# - Access levels control who can view: ALL, MISSION (specific mission),
#   or PRIVATE (uploader + server only)
# - Only the uploader or server operator can delete a document
# - Documents are NOT synced over RNode (broadband only)

from talon.db.models import Document


def create_document(name: str, created_by: str, file_path: str,
                    file_size: int = 0, mime_type: str = "",
                    access: str = "ALL",
                    tags: list = None) -> Document:
    """Create a new document record.

    Args:
        name: Display name for the file.
        created_by: Callsign of the operator who uploaded it.
        file_path: Where the file is stored on disk (relative to doc dir).
        file_size: Size in bytes (used for sync estimates).
        mime_type: MIME type (e.g., "image/png", "application/pdf").
        access: Access level — ALL or RESTRICTED.
        tags: Optional list of tags for categorization.

    Returns:
        A new Document object ready to be saved.
    """
    return Document(
        title=name,
        uploaded_by=created_by,
        file_path=file_path,
        file_size=file_size,
        file_type=mime_type,
        access_level=access,
        tags=tags or [],
    )


def validate_document(doc: Document) -> list:
    """Check that a document has all required fields.

    Args:
        doc: The Document to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors = []
    if not doc.title:
        errors.append("Document name is required")
    if not doc.uploaded_by:
        errors.append("Uploader callsign is required")
    if not doc.file_path:
        errors.append("File path is required")
    return errors


def can_view_document(doc: Document, operator_callsign: str,
                      operator_role: str,
                      operator_missions: list = None) -> bool:
    """Check if an operator is allowed to view a document.

    Args:
        doc: The document to check.
        operator_callsign: Who wants to view it.
        operator_role: The viewer's role.
        operator_missions: List of mission IDs the operator is assigned to.

    Returns:
        True if the operator has access.
    """
    # Server can see everything
    if operator_role == "server":
        return True
    # ALL — anyone can view
    if doc.access_level == "ALL":
        return True
    # RESTRICTED — only the uploader and server
    if doc.access_level == "RESTRICTED":
        return operator_callsign == doc.uploaded_by
    return False


def can_delete_document(operator_callsign: str, doc: Document,
                        operator_role: str) -> bool:
    """Check if an operator can delete a document.

    Allowed for the uploader or the server operator.
    """
    if operator_role == "server":
        return True
    return operator_callsign == doc.uploaded_by

# talon/models/asset.py
# Business logic for Assets.
#
# Assets are anything worth tracking on the map: operators, safe houses,
# supply caches, rally points, vehicles, or custom categories.
#
# Verification rules:
# - When one operator creates an asset, it starts as UNVERIFIED
# - A second operator OR the server can verify it (physical confirmation)
# - The creating operator CANNOT verify their own asset
# - Verified assets show as solid icons on the map
# - Unverified assets show as dashed/transparent icons

from talon.db.models import Asset
from talon.constants import VerificationStatus


def can_verify(asset: Asset, verifier_callsign: str, verifier_role: str) -> bool:
    """Check if an operator can verify an asset.

    Args:
        asset: The asset to be verified.
        verifier_callsign: Who is trying to verify it.
        verifier_role: The verifier's role ("operator" or "server").

    Returns:
        True if the verification is allowed.
    """
    # Already verified — nothing to do
    if asset.verification == VerificationStatus.VERIFIED.name.lower():
        return False
    # Server can verify anything
    if verifier_role == "server":
        return True
    # Operator cannot verify their own asset
    return verifier_callsign != asset.created_by


def verify_asset(asset: Asset, verifier_callsign: str) -> Asset:
    """Mark an asset as verified.

    Call can_verify() first to check permissions.

    Args:
        asset: The asset to verify.
        verifier_callsign: Who is confirming this asset.

    Returns:
        The updated asset with verification status changed.
    """
    asset.verification = "verified"
    asset.verified_by = verifier_callsign
    asset.version += 1
    asset.sync_state = "pending"
    return asset


def validate_asset(asset: Asset) -> list:
    """Check that an asset has all required fields.

    Args:
        asset: The Asset to validate.

    Returns:
        List of error messages. Empty list means valid.
    """
    errors = []
    if not asset.name:
        errors.append("Asset name is required")
    if not asset.category:
        errors.append("Asset category is required")
    if not asset.created_by:
        errors.append("Creator callsign is required")
    return errors

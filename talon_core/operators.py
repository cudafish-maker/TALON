"""
Operator profile and skills management.

Provides read and write access to the operators table for profile and
skills fields.  Enrollment (token lifecycle, lease renewal) lives in
talon/server/enrollment.py.  Revocation lives in talon/server/revocation.py.

The SERVER sentinel (id=1, callsign='SERVER') is excluded from list_operators()
by default and should never be modified through this module.
"""
import json
import typing

from talon_core.db.connection import Connection
from talon_core.db.models import Operator
from talon_core.utils.logging import get_logger

_log = get_logger("operators")

# Sentinel operator record seeded by migration 0002.
# Server flows must opt in explicitly when they want to attribute work to the
# server sentinel instead of a real enrolled operator row.
SERVER_OPERATOR_ID: int = 1

# Query reused by both get_operator and list_operators.
_SELECT = (
    "SELECT id, callsign, rns_hash, skills, profile, "
    "enrolled_at, lease_expires_at, revoked FROM operators"
)


def get_operator(conn: Connection, operator_id: int) -> typing.Optional[Operator]:
    """Return the Operator for operator_id, or None if not found."""
    row = conn.execute(
        f"{_SELECT} WHERE id = ?", (operator_id,)
    ).fetchone()
    return _row_to_operator(row) if row else None


def list_operators(
    conn: Connection,
    include_sentinel: bool = False,
) -> list[Operator]:
    """Return all operators ordered newest-first.

    The SERVER sentinel (id=1) is excluded unless include_sentinel=True.
    """
    rows = conn.execute(
        f"{_SELECT} ORDER BY enrolled_at DESC"
    ).fetchall()
    result = []
    for row in rows:
        if row[0] == 1 and not include_sentinel:
            continue
        result.append(_row_to_operator(row))
    return result


class LocalOperatorResolutionError(RuntimeError):
    """Raised when the local operator id cannot be resolved safely."""


def resolve_local_operator_id(
    conn: Connection,
    *,
    mode: typing.Literal["server", "client"],
    current_operator_id: typing.Optional[int] = None,
    allow_server_sentinel: bool = False,
) -> typing.Optional[int]:
    """Resolve the local operator id for the current runtime mode.

    Resolution order:
      1. Explicit in-memory operator id, when it is not the server sentinel.
      2. Client-only: the persisted ``meta.my_operator_id`` value.
      3. Client-only: infer a single non-revoked, non-sentinel operator row
         for older databases that predate ``my_operator_id``.

    The server sentinel is returned only when ``allow_server_sentinel=True``.
    Client mode never infers or accepts the server sentinel implicitly.
    """
    operator_id = _normalise_operator_id(current_operator_id)
    if mode == "server":
        if operator_id is not None and operator_id != SERVER_OPERATOR_ID:
            return operator_id
        return SERVER_OPERATOR_ID if allow_server_sentinel else None

    if operator_id is not None and operator_id != SERVER_OPERATOR_ID:
        return operator_id

    meta_operator_id = _load_meta_operator_id(conn)
    if meta_operator_id is not None and meta_operator_id != SERVER_OPERATOR_ID:
        return meta_operator_id

    return _infer_client_operator_id(conn)


def require_local_operator_id(
    conn: Connection,
    *,
    mode: typing.Literal["server", "client"],
    current_operator_id: typing.Optional[int] = None,
    allow_server_sentinel: bool = False,
) -> int:
    """Resolve the local operator id or raise a descriptive error."""
    operator_id = resolve_local_operator_id(
        conn,
        mode=mode,
        current_operator_id=current_operator_id,
        allow_server_sentinel=allow_server_sentinel,
    )
    if operator_id is None:
        if mode == "server":
            raise LocalOperatorResolutionError(
                "Local server operator id is unavailable."
            )
        raise LocalOperatorResolutionError(
            "Local client operator id is unavailable. Re-enroll this client."
        )
    return operator_id


def update_operator_skills(
    conn: Connection,
    operator_id: int,
    skills: list[str],
) -> None:
    """Replace an operator's skills list.

    Skills are stored as a JSON array of lowercase strings.
    Raises ValueError if the operator does not exist.
    """
    normalised = [s.strip().lower() for s in skills if s.strip()]
    cursor = conn.execute(
        "UPDATE operators SET skills = ?, version = version + 1 WHERE id = ?",
        (json.dumps(normalised), operator_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError(f"Operator {operator_id} not found.")
    conn.commit()
    _log.info("Skills updated: operator_id=%s count=%d", operator_id, len(normalised))


def update_operator_profile(
    conn: Connection,
    operator_id: int,
    profile: dict,
) -> None:
    """Replace an operator's profile dict.

    Raises ValueError if the operator does not exist.
    """
    cursor = conn.execute(
        "UPDATE operators SET profile = ?, version = version + 1 WHERE id = ?",
        (json.dumps(profile), operator_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError(f"Operator {operator_id} not found.")
    conn.commit()
    _log.info("Profile updated: operator_id=%s", operator_id)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _row_to_operator(row) -> Operator:
    try:
        skills = json.loads(row[3]) if row[3] else []
    except (json.JSONDecodeError, TypeError):
        skills = []
    try:
        profile = json.loads(row[4]) if row[4] else {}
    except (json.JSONDecodeError, TypeError):
        profile = {}
    return Operator(
        id=row[0],
        callsign=row[1],
        rns_hash=row[2],
        skills=skills,
        profile=profile,
        enrolled_at=row[5],
        lease_expires_at=row[6],
        revoked=bool(row[7]),
    )


def _normalise_operator_id(value: typing.Optional[typing.Any]) -> typing.Optional[int]:
    if value is None:
        return None
    try:
        operator_id = int(value)
    except (TypeError, ValueError):
        return None
    return operator_id if operator_id > 0 else None


def _load_meta_operator_id(conn: Connection) -> typing.Optional[int]:
    row = conn.execute(
        "SELECT value FROM meta WHERE key = 'my_operator_id'"
    ).fetchone()
    if not row:
        return None
    return _normalise_operator_id(str(row[0]).strip())


def _infer_client_operator_id(conn: Connection) -> typing.Optional[int]:
    rows = conn.execute(
        "SELECT id FROM operators WHERE id != ? AND revoked = 0 "
        "ORDER BY enrolled_at ASC LIMIT 2",
        (SERVER_OPERATOR_ID,),
    ).fetchall()
    if len(rows) == 1:
        return int(rows[0][0])
    return None

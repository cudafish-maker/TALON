# talon/db/models.py
# Data model classes for T.A.L.O.N.
#
# These are Python dataclasses that represent the records stored in
# the database. They make it easy to pass structured data around
# the application instead of raw dictionaries or tuples.
#
# Each model maps to a database table in database.py.

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional


def new_id() -> str:
    """Generate a new unique ID for a record.

    Uses UUID4 — a random 128-bit identifier. The chance of two
    IDs colliding is effectively zero, even across millions of records
    created by different clients that haven't synced yet.
    """
    return str(uuid.uuid4())


def now() -> float:
    """Get the current time as a Unix timestamp (seconds since 1970).

    Used for all timestamps throughout T.A.L.O.N. to keep times
    consistent and easy to compare.
    """
    return time.time()


@dataclass
class Operator:
    """A person using T.A.L.O.N. — either a field operator or server operator."""

    id: str = field(default_factory=new_id)
    callsign: str = ""
    reticulum_identity: str = ""
    role: str = "operator"  # "operator" or "server"
    status: str = "active"  # active / soft_locked / revoked
    skills: list = field(default_factory=list)
    custom_skills: list = field(default_factory=list)
    bio: str = ""
    enrolled_at: float = field(default_factory=now)
    last_sync: Optional[float] = None
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Asset:
    """A tracked item: person, location, vehicle, or supply cache."""

    id: str = field(default_factory=new_id)
    name: str = ""
    category: str = "CUSTOM"
    custom_category: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: str = "active"  # active / inactive / compromised
    verification: str = "unverified"
    verified_by: Optional[str] = None
    created_by: str = ""
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    notes: str = ""
    version: int = 1
    sync_state: str = "pending"


@dataclass
class AssetCategoryCustom:
    """A custom asset category created by an operator."""

    id: str = field(default_factory=new_id)
    name: str = ""
    created_by: str = ""
    created_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class SITREP:
    """A situation report — the core information sharing tool."""

    id: str = field(default_factory=new_id)
    type: str = "freeform"  # "predefined" or "freeform"
    template_name: Optional[str] = None
    importance: str = "ROUTINE"
    created_by: str = ""
    created_at: float = field(default_factory=now)
    deleted: bool = False
    delete_reason: Optional[str] = None
    version: int = 1
    sync_state: str = "pending"


@dataclass
class SITREPEntry:
    """A single entry in a SITREP. Append-only — cannot be edited or deleted."""

    id: str = field(default_factory=new_id)
    sitrep_id: str = ""
    author: str = ""
    content: str = ""
    created_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Mission:
    """An operation with objectives, assigned operators, and linked resources."""

    id: str = field(default_factory=new_id)
    name: str = ""
    description: str = ""
    status: str = "PLANNING"  # PLANNING / ACTIVE / COMPLETE / ABORTED
    priority: str = "ROUTINE"
    created_by: str = ""
    created_at: float = field(default_factory=now)
    updated_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Objective:
    """A single objective within a mission."""

    id: str = field(default_factory=new_id)
    mission_id: str = ""
    description: str = ""
    status: str = "PENDING"  # PENDING / IN_PROGRESS / COMPLETE / FAILED
    assigned_to: Optional[str] = None
    updated_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class MissionNote:
    """An append-only note on a mission."""

    id: str = field(default_factory=new_id)
    mission_id: str = ""
    author: str = ""
    content: str = ""
    created_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Waypoint:
    """A named GPS location used in routes."""

    id: str = field(default_factory=new_id)
    name: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    type: str = "CHECKPOINT"
    notes: str = ""
    created_by: str = ""
    created_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Route:
    """An ordered sequence of waypoints forming a path."""

    id: str = field(default_factory=new_id)
    name: str = ""
    distance: Optional[float] = None  # Meters, auto-calculated
    status: str = "PLANNED"  # PLANNED / ACTIVE / COMPLETED
    mission_id: Optional[str] = None
    created_by: str = ""
    created_at: float = field(default_factory=now)
    notes: str = ""
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Zone:
    """A polygon area on the map (AO, danger zone, etc.)."""

    id: str = field(default_factory=new_id)
    name: str = ""
    type: str = "AO"
    boundary: list = field(default_factory=list)  # List of [lat, lon] pairs
    color: str = "#00e5a0"
    active: bool = True
    created_by: str = ""
    created_at: float = field(default_factory=now)
    notes: str = ""
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Channel:
    """A chat channel — group, mission-specific, custom, or direct message."""

    id: str = field(default_factory=new_id)
    name: str = ""
    type: str = "CUSTOM"  # GENERAL / MISSION / CUSTOM / DIRECT
    created_by: Optional[str] = None
    created_at: float = field(default_factory=now)
    mission_id: Optional[str] = None
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Message:
    """A single chat message in a channel."""

    id: str = field(default_factory=new_id)
    channel_id: str = ""
    sender: str = ""
    type: str = "TEXT"  # TEXT / LOCATION / ALERT / FILE
    body: str = ""
    created_at: float = field(default_factory=now)
    edited: bool = False
    version: int = 1
    sync_state: str = "pending"


@dataclass
class Document:
    """An uploaded file (manual, map, reference material)."""

    id: str = field(default_factory=new_id)
    title: str = ""
    category: str = "Manual"
    file_type: str = ""
    file_path: str = ""
    file_size: int = 0
    tags: list = field(default_factory=list)
    access_level: str = "ALL"  # ALL or RESTRICTED
    uploaded_by: str = ""
    uploaded_at: float = field(default_factory=now)
    version: int = 1
    sync_state: str = "pending"


@dataclass
class AuditEntry:
    """A single entry in the audit log (server only)."""

    id: str = field(default_factory=new_id)
    event_type: str = ""
    timestamp: float = field(default_factory=now)
    client_callsign: Optional[str] = None
    details: str = ""
    transport: Optional[str] = None

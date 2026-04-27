"""
Dataclasses mirroring database rows.

These are plain data containers — no ORM, no active record pattern.
Query and persistence logic lives in the feature modules that use them.
"""
from __future__ import annotations

import dataclasses
import typing


@dataclasses.dataclass
class Operator:
    id: int
    callsign: str
    rns_hash: str
    skills: list[str]       # deserialized from JSON
    profile: dict            # deserialized from JSON
    enrolled_at: int         # Unix timestamp
    lease_expires_at: int
    revoked: bool


@dataclasses.dataclass
class Asset:
    id: int
    category: str
    label: str
    description: str
    lat: typing.Optional[float]
    lon: typing.Optional[float]
    verified: bool
    created_by: int          # operator id
    confirmed_by: typing.Optional[int]
    created_at: int
    version: int
    mission_id: typing.Optional[int] = None  # set when requested/allocated to a mission
    deletion_requested: bool = False          # client has flagged this for server-side deletion


@dataclasses.dataclass
class Sitrep:
    id: int
    level: str               # one of SITREP_LEVELS
    template: str
    body: bytes              # decrypted plaintext (field-encrypted at rest)
    author_id: int
    mission_id: typing.Optional[int]
    asset_id: typing.Optional[int]
    created_at: int
    version: int


@dataclasses.dataclass
class Mission:
    id: int
    title: str
    description: str
    status: str              # "pending_approval" | "active" | "rejected" | "completed" | "aborted"
    created_by: int
    created_at: int
    version: int
    # Extended fields — migrations 0013/0014; all default to empty so older code paths still work
    mission_type: str = ""
    priority: str = "ROUTINE"
    lead_coordinator: str = ""
    organization: str = ""
    activation_time: str = ""
    operation_window: str = ""
    max_duration: str = ""
    staging_area: str = ""
    demob_point: str = ""
    standdown_criteria: str = ""
    phases: list = dataclasses.field(default_factory=list)        # JSON array of phase dicts
    constraints: list = dataclasses.field(default_factory=list)   # JSON array of constraint strings
    support_medical: str = ""
    support_logistics: str = ""
    support_comms: str = ""
    support_equipment: str = ""
    custom_resources: list = dataclasses.field(default_factory=list)  # JSON array of resource dicts
    objectives: list = dataclasses.field(default_factory=list)    # JSON array of objective dicts
    key_locations: dict = dataclasses.field(default_factory=dict) # JSON object


@dataclasses.dataclass
class Waypoint:
    id: int
    mission_id: int
    sequence: int
    label: str
    lat: float
    lon: float
    version: int


@dataclasses.dataclass
class Zone:
    id: int
    label: str
    zone_type: str           # AO, DANGER, RESTRICTED, FRIENDLY, OBJECTIVE, custom
    polygon: list[list[float]]  # [[lat, lon], ...]
    mission_id: typing.Optional[int]
    created_by: int
    created_at: int
    version: int


@dataclasses.dataclass
class Document:
    id: int
    filename: str       # sanitized original name — display only
    mime_type: str      # verified MIME type
    size_bytes: int     # plaintext file size
    file_path: str      # opaque internal name: "{id}_{uuid4}.bin"
    sha256_hash: str    # hex SHA-256 of plaintext (integrity verification)
    description: str    # optional operator-supplied note
    uploaded_by: int    # FK → operators.id
    uploaded_at: int    # Unix timestamp
    version: int


@dataclasses.dataclass
class Channel:
    id: int
    name: str
    mission_id: typing.Optional[int]
    is_dm: bool
    version: int
    group_type: str = "squad"   # 'emergency'|'allhands'|'mission'|'squad'|'direct'


@dataclasses.dataclass
class Message:
    id: int
    channel_id: int
    sender_id: int
    body: bytes              # decrypted (field-encrypted for DMs)
    sent_at: int
    version: int
    is_urgent: bool = False
    grid_ref: typing.Optional[str] = None


@dataclasses.dataclass
class EnrollmentToken:
    token: str
    created_at: int
    expires_at: int
    used_at: typing.Optional[int]
    operator_id: typing.Optional[int]


@dataclasses.dataclass
class AuditEntry:
    id: int
    event: str
    payload: dict            # decrypted from field-encrypted JSON
    occurred_at: int

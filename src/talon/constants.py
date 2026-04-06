# talon/constants.py
# Central location for all enumerations, status codes, and constants
# used throughout T.A.L.O.N. Both server and client import from here
# to ensure they always agree on the same values.

from enum import Enum, auto


# --- SITREP Importance Levels ---
# Controls how urgently notifications are displayed.
# Listed from least urgent to most urgent.
class SITREPImportance(Enum):
    ROUTINE = auto()  # Subtle badge on SITREP tab
    PRIORITY = auto()  # Visible banner, subtle visual pulse
    IMMEDIATE = auto()  # Persistent banner, persistent pulse
    FLASH = auto()  # Overlay popup, screen flash, audio IF enabled
    FLASH_OVERRIDE = auto()  # Full screen takeover, audio IF enabled


# --- Asset Categories ---
# Built-in asset types. Operators can also create custom categories.
class AssetCategory(Enum):
    OPERATOR = auto()  # A person on the team
    SAFE_HOUSE = auto()  # Secure location
    CACHE_FOOD = auto()  # Food supply cache
    CACHE_AMMO = auto()  # Ammunition cache
    RALLY_POINT = auto()  # Pre-arranged meeting location
    VEHICLE = auto()  # Car, truck, boat, etc.
    CUSTOM = auto()  # Operator-defined category


# --- Asset Verification Status ---
# An asset starts as UNVERIFIED when created by a single operator.
# It becomes VERIFIED when a second operator or the server confirms it.
class VerificationStatus(Enum):
    UNVERIFIED = auto()  # Only one operator has reported this asset
    VERIFIED = auto()  # A second operator or server has confirmed


# --- Client Connection Status ---
# How the server sees each connected client.
class ClientStatus(Enum):
    ONLINE = auto()  # Connected and responding to heartbeats
    STALE = auto()  # Missed heartbeats, may have lost connection
    SOFT_LOCKED = auto()  # Lease expired (>24hrs without sync)
    REVOKED = auto()  # Compromised or lost — identity burned


# --- Mission Status ---
class MissionStatus(Enum):
    PLANNING = auto()  # Being set up, not yet active
    ACTIVE = auto()  # Currently in progress
    COMPLETE = auto()  # Successfully finished
    ABORTED = auto()  # Cancelled (server operator only)


# --- Objective Status ---
class ObjectiveStatus(Enum):
    PENDING = auto()  # Not yet started
    IN_PROGRESS = auto()  # Currently being worked
    COMPLETE = auto()  # Done
    FAILED = auto()  # Could not be completed


# --- Route Status ---
class RouteStatus(Enum):
    PLANNED = auto()  # Route is planned but not yet in use
    ACTIVE = auto()  # Currently being traveled
    COMPLETED = auto()  # Route has been completed


# --- Zone Types ---
# What a marked area on the map represents.
class ZoneType(Enum):
    AO = auto()  # Area of Operations — the overall working area
    DANGER = auto()  # Dangerous area, avoid or use caution
    RESTRICTED = auto()  # Do not enter without authorization
    FRIENDLY = auto()  # Friendly/safe territory
    OBJECTIVE = auto()  # Target area for a mission
    CUSTOM = auto()  # Operator-defined zone type


# --- Chat Channel Types ---
class ChannelType(Enum):
    GENERAL = auto()  # Default channel, all operators auto-joined
    MISSION = auto()  # Auto-created per mission, assigned operators only
    CUSTOM = auto()  # Operator-created channel
    DIRECT = auto()  # 1-to-1 private message


# --- Chat Message Types ---
class MessageType(Enum):
    TEXT = auto()  # Normal text message
    LOCATION = auto()  # Shares sender's current GPS position
    ALERT = auto()  # System-generated (lease expiry, revocation, etc.)
    FILE = auto()  # Reference to an attached document


# --- Document Access Levels ---
class DocumentAccess(Enum):
    ALL = auto()  # Every operator can download
    RESTRICTED = auto()  # Server operator defines who can access


# --- Transport Types ---
# Which network interface is being used for communication.
class TransportType(Enum):
    YGGDRASIL = auto()  # High bandwidth, encrypted mesh
    I2P = auto()  # Anonymous overlay network
    TCP = auto()  # Direct internet (WARNING: exposes IP)
    RNODE = auto()  # LoRa radio (low bandwidth, no internet)


# --- Sync States ---
# Tracks whether a record has been synced with the server.
class SyncState(Enum):
    PENDING = auto()  # Created/modified locally, not yet synced
    SYNCED = auto()  # Successfully synced with server
    CONFLICT = auto()  # Server has a different version


# --- Audit Event Types ---
# What kind of event is being logged.
class AuditEvent(Enum):
    CLIENT_CONNECT = auto()
    CLIENT_DISCONNECT = auto()
    CLIENT_SYNC = auto()
    CLIENT_STALE = auto()
    CLIENT_SOFT_LOCK = auto()
    CLIENT_REAUTH_REQUEST = auto()
    CLIENT_REAUTH_APPROVED = auto()
    CLIENT_REAUTH_DENIED = auto()
    CLIENT_REVOKED = auto()
    CLIENT_ENROLLED = auto()
    GROUP_KEY_ROTATED = auto()
    SITREP_CREATED = auto()
    SITREP_APPENDED = auto()
    SITREP_DELETED = auto()
    ASSET_CREATED = auto()
    ASSET_VERIFIED = auto()
    ASSET_UPDATED = auto()
    MISSION_CREATED = auto()
    MISSION_UPDATED = auto()
    MISSION_ABORTED = auto()
    MESSAGE_SENT = auto()
    MESSAGE_DELETED = auto()
    CHANNEL_CREATED = auto()
    CHANNEL_DELETED = auto()
    DOCUMENT_UPLOADED = auto()
    DOCUMENT_DELETED = auto()


# --- Waypoint Types ---
class WaypointType(Enum):
    CHECKPOINT = auto()  # Intermediate point along a route
    RALLY = auto()  # Pre-arranged meeting point
    EXTRACT = auto()  # Extraction/pickup point
    INSERT = auto()  # Insertion/drop-off point
    RESUPPLY = auto()  # Resupply point
    CUSTOM = auto()  # Operator-defined type


# --- Default Channels ---
# These channels are created automatically and cannot be deleted.
DEFAULT_CHANNELS = {
    "general": "All operators — main communication channel",
    "sitrep-feed": "Auto-posts when SITREPs are created or appended",
    "alerts": "System notifications (joins, revocations, lease events)",
}


# --- Operator Skills ---
# Built-in skill list. Operators can also add custom skills.
DEFAULT_SKILLS = [
    "Medical / First Aid",
    "Communications / Radio",
    "Navigation / Land Nav",
    "Mechanics / Vehicle Repair",
    "Demolitions / Breaching",
    "Reconnaissance",
    "Marksmanship",
    "Drone Operation",
    "SIGINT / Electronic Warfare",
    "Logistics / Supply",
    "Language",
    "Construction / Field Engineering",
    "K9 Handler",
    "Pilot",
    "Cybersecurity / INFOSEC",
]

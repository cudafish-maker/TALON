from typing import Final

APP_VERSION: Final = "0.1.0"
APP_NAME: Final = "TALON"

# SITREP importance levels — ordered lowest to highest
SITREP_LEVELS: Final = (
    "ROUTINE",
    "PRIORITY",
    "IMMEDIATE",
    "FLASH",
    "FLASH_OVERRIDE",
)

# Heartbeat intervals (seconds)
HEARTBEAT_BROADBAND_S: Final = 60
HEARTBEAT_LORA_S: Final = 120

# Lease duration before soft-lock (24 hours)
LEASE_DURATION_S: Final = 86400

# Operator map pings remain operationally visible for one day by default.
OPERATOR_LOCATION_PING_TTL_S: Final = 86400

# Transport interface priority (highest first).
# WARNING: TCP exposes the operator's IP address. When TCP is active,
# the UI must display a warning and recommend using a VPN.
TRANSPORT_PRIORITY: Final = ("yggdrasil", "i2p", "tcp", "rnode")

# Database schema version
DB_SCHEMA_VERSION: Final = 22

# ---------------------------------------------------------------------------
# Reticulum network aspects
# ---------------------------------------------------------------------------

# Used by ServerNetHandler to create the server's sync destination.
# Destination hash = hash(identity, APP_NAME, RNS_SERVER_ASPECT).
RNS_APP_NAME: Final = "talon"
RNS_SERVER_ASPECT: Final = "server"

# Predefined operator skills (displayed as toggleable checkboxes in profile editor)
PREDEFINED_SKILLS: Final = (
    "medic",
    "comms",
    "logistics",
    "intelligence",
    "recon",
    "navigation",
    "engineering",
    "security",
)

# Asset categories (predefined)
ASSET_CATEGORIES: Final = (
    "person",
    "safe_house",
    "cache",
    "rally_point",
    "vehicle",
)

# Default chat channels
DEFAULT_CHANNELS: Final = ("#flash", "#general", "#sitrep-feed", "#alerts")

# Enrollment token expiry (seconds) — 60 minutes
ENROLLMENT_TOKEN_EXPIRY_S: Final = 3600

# ---------------------------------------------------------------------------
# Document management
# ---------------------------------------------------------------------------

# Hard cap on upload size (50 MB)
MAX_DOCUMENT_SIZE_BYTES: Final = 50 * 1024 * 1024

# Extensions whose content can carry macros / scripts — warn operator on download
DOCUMENT_WARN_EXTENSIONS: Final = frozenset({
    ".doc", ".docx", ".docm",
    ".xls", ".xlsx", ".xlsm", ".xlsb",
    ".ppt", ".pptx", ".pptm",
    ".odt", ".ods", ".odp",
    ".rtf",
})

# Extensions that are directly executable or script-interpretable — reject on upload
DOCUMENT_BLOCKED_EXTENSIONS: Final = frozenset({
    ".exe", ".com", ".msi", ".bat", ".cmd",
    ".sh", ".bash", ".zsh", ".fish",
    ".py", ".pyw", ".pyc",
    ".rb", ".pl", ".php",
    ".js", ".mjs", ".cjs", ".ts",
    ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".wsf", ".wsc",
    ".jar", ".class",
    ".elf", ".so", ".dll",
    ".apk", ".ipa",
    ".scr", ".pif", ".lnk",
})

# MIME types to block regardless of declared extension (magic-bytes detection)
DOCUMENT_BLOCKED_MIMES: Final = frozenset({
    "application/x-executable",
    "application/x-elf",
    "application/x-msdos-program",
    "application/x-msdownload",
    "text/x-shellscript",
    "application/x-sh",
    "application/java-archive",
})

# Extensions/MIME types permitted for new document uploads. Existing stored
# documents remain downloadable through the integrity-checked read path.
DOCUMENT_ALLOWED_EXTENSIONS: Final = frozenset({
    ".pdf",
    ".txt", ".md", ".markdown", ".csv", ".json", ".geojson",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
})

DOCUMENT_ALLOWED_MIMES: Final = frozenset({
    "application/pdf",
    "application/json",
    "application/geo+json",
    "text/plain",
    "text/markdown",
    "text/csv",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/bmp",
    "image/webp",
})

# ---------------------------------------------------------------------------
# Argon2id KDF parameters — balanced for mobile
ARGON2_TIME_COST: Final = 3
ARGON2_MEMORY_COST: Final = 65536  # 64 MB
ARGON2_PARALLELISM: Final = 1
ARGON2_HASH_LEN: Final = 32  # 256-bit key
ARGON2_SALT_LEN: Final = 32  # 256-bit salt

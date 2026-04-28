"""Public TALON core facade.

This package is the extraction boundary for the future ``talon-core`` project.
Facade symbols are loaded lazily so lower-level ``talon_core`` modules can be
imported without also importing the session runtime.
"""

__all__ = [
    "CorePaths",
    "CoreSessionError",
    "CoreUnlockResult",
    "DashboardSummary",
    "DocumentCommandResult",
    "DocumentDownloadResult",
    "DocumentListItem",
    "ChatCommandResult",
    "EnrollmentTokenResult",
    "RecordCommandResult",
    "ReticulumConfigError",
    "ReticulumConfigSaveResult",
    "ReticulumConfigStatus",
    "ReticulumConfigValidation",
    "SyncStatus",
    "TalonCoreSession",
]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module 'talon_core' has no attribute {name!r}")
    if name.startswith("ReticulumConfig"):
        from talon_core.network import rns_config as _rns_config

        return getattr(_rns_config, name)
    from talon_core import session as _session

    return getattr(_session, name)

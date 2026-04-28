# TALON Bug Index

This file tracks active cross-project issues. Resolved issues move to
[archive/fixed_bugs.md](archive/fixed_bugs.md). Platform-specific details should
also be reflected in the relevant project wiki.

## Summary

| Status | Count |
|--------|-------|
| Open | 1 |
| Fixed/archive | See [archive/fixed_bugs.md](archive/fixed_bugs.md) |

## Recent Security Remediation

- 2026-04-28: Reticulum security review remediation completed for C-1, H-1,
  H-2, M-1, M-2, M-3, L-1, L-2, and L-3. H-3 remains an accepted release risk:
  authenticated active operators intentionally have full shared dataset
  visibility. Detailed state is recorded in
  [talon-core/security.md](talon-core/security.md),
  [talon-core/reticulum.md](talon-core/reticulum.md), and
  [talon-core/sync_protocol.md](talon-core/sync_protocol.md).

## Open Issues

### BUG-085: Documents screen is registered but not reachable from the desktop dashboard

- Severity: Medium
- Status: Open
- Project: `talon-desktop`
- Tracking doc: [talon-desktop/documents.md](talon-desktop/documents.md)
- Legacy source: [archive/legacy/document_management.md](archive/legacy/document_management.md)
- Files: `talon/app.py`, `talon/ui/screens/main_screen.py`,
  `talon/ui/screens/document_screen.py`, `talon/ui/widgets/nav_rail.py`

`DocumentScreen` is registered as the `documents` screen and the document
backend supports server upload/delete plus client on-demand fetch/cache. The
current programmatic desktop dashboard exposes quick navigation for missions,
SITREPs, and chat, but no visible control calls `navigate_to("documents")`.

Impact: document repository workflows exist but are hidden from operators in the
current desktop UI.

Required fix: the legacy Kivy desktop needs a visible Documents control for any
near-term Kivy release. The PySide6 desktop rewrite must include Documents in
the first complete navigation shell.

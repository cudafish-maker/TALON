# talon/client/__init__.py
# Client-side package for T.A.L.O.N.
#
# The client runs on operator devices (Linux, Windows, Android).
# It connects to the server over Reticulum and provides the
# operator's UI for situational awareness and coordination.
#
# Key responsibilities:
#   - Connect to the server (auto-detect best transport)
#   - Cache all synced data locally in an encrypted database
#   - Display the tactical map with assets, routes, and zones
#   - Handle SITREPs, missions, chat, and documents
#   - Send heartbeats so the server knows we're alive
#   - Fall back to cached data when offline
#   - Shred local data if the lease expires (soft-lock)

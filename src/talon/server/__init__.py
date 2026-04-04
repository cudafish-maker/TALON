# talon/server/__init__.py
# Server-side package for T.A.L.O.N.
#
# The server is the central coordination point. It:
#   - Acts as the Reticulum propagation node and transport node
#   - Stores the authoritative copy of all data
#   - Manages client enrollment, leases, and revocation
#   - Runs the sync engine that pushes/pulls delta updates
#   - Serves pre-cached map tiles to clients
#   - Logs all significant actions to the audit trail
#   - Provides the server operator's UI for monitoring and control

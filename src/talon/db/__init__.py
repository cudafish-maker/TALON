# talon/db/__init__.py
# Database subsystem for T.A.L.O.N.
# Uses SQLCipher — an encrypted version of SQLite.
# All data at rest is encrypted. The database cannot be opened
# without the correct key (derived from the operator's passphrase
# and lease token).

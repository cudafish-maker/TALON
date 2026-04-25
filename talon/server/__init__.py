# SERVER-EXCLUSIVE PACKAGE
# Nothing in this package is imported outside of server mode.
# In talon/app.py all imports from talon.server.* are deferred behind:
#   if self.mode == "server":
#       from talon.server.xxx import ...
# Buildozer excludes this package from client APKs via source.exclude_patterns.

# talon/ui/widgets/__init__.py
# Register custom widgets with Kivy's Factory so they can be used in KV files
# by name (e.g., <MapWidget>, <StatusBar>).

from talon.ui.widgets.map_widget import MapWidget
from talon.ui.widgets.status_bar import StatusBar

__all__ = ["MapWidget", "StatusBar"]

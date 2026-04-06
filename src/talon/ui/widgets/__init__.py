# talon/ui/widgets/__init__.py
# Register custom widgets with Kivy's Factory so they can be used in KV files
# by name (e.g., MapWidget:, StatusBar:).
#
# Kivy's WidgetMetaclass auto-registers classes under their __name__. The map
# widget's real class is TalonMapWidget with a `MapWidget = TalonMapWidget`
# Python alias, which Kivy cannot see — so we must register the alias name
# with Factory explicitly.

from kivy.factory import Factory

from talon.ui.widgets.map_widget import MapWidget, TalonMapWidget
from talon.ui.widgets.status_bar import StatusBar

Factory.register("MapWidget", cls=TalonMapWidget)

__all__ = ["MapWidget", "StatusBar"]

# tests/conftest.py
# Shared fixtures and Kivy/KivyMD mock infrastructure for UI tests.
#
# Kivy and KivyMD are not installed in the test environment (they
# require a display server), so we mock the full import tree before
# any UI module is loaded.

import sys
import types
from unittest.mock import MagicMock


def _make_mock_module(name, attrs=None):
    """Create a mock module and register it in sys.modules."""
    mod = types.ModuleType(name)
    if attrs:
        for k, v in attrs.items():
            setattr(mod, k, v)
    sys.modules[name] = mod
    return mod


def install_kivy_mocks():
    """Install mock Kivy and KivyMD modules into sys.modules.

    This must be called before importing any talon.ui module.
    Provides enough structure for the UI source to import cleanly
    without a real display server.
    """
    if "kivy" in sys.modules:
        return  # Already mocked or real

    # --- Kivy core ---
    _make_mock_module("kivy")
    _make_mock_module("kivy.lang", {"Builder": MagicMock()})
    _make_mock_module("kivy.metrics", {"dp": lambda x: x})
    _make_mock_module("kivy.clock", {"Clock": MagicMock()})
    _make_mock_module("kivy.app", {"App": MagicMock()})
    _make_mock_module("kivy.uix", {})
    _MockCanvas = type(
        "_MockCanvas",
        (),
        {
            "__enter__": lambda self: self,
            "__exit__": lambda self, *a: None,
            "clear": lambda self: None,
            "before": MagicMock(),
        },
    )
    _make_mock_module(
        "kivy.uix.widget",
        {
            "Widget": type(
                "Widget",
                (),
                {
                    "__init__": lambda self, **kw: None,
                    "canvas": _MockCanvas(),
                    "pos": (0, 0),
                    "size": (800, 600),
                    "bind": lambda self, **kw: None,
                },
            )
        },
    )

    # Kivy properties — need to act as descriptors that store values
    class FakeProperty:
        """A minimal Kivy property mock that stores a default."""

        def __init__(self, default=None):
            self.default = default

        def __set_name__(self, owner, name):
            self.name = name

        def __get__(self, obj, objtype=None):
            if obj is None:
                return self
            return obj.__dict__.get(f"_prop_{self.name}", self.default)

        def __set__(self, obj, value):
            obj.__dict__[f"_prop_{self.name}"] = value

    _make_mock_module(
        "kivy.properties",
        {
            "StringProperty": lambda default="": FakeProperty(default),
            "BooleanProperty": lambda default=False: FakeProperty(default),
            "NumericProperty": lambda default=0: FakeProperty(default),
            "ListProperty": lambda default=None: FakeProperty(default or []),
            "ObjectProperty": lambda default=None, **kw: FakeProperty(default),
        },
    )

    # Window mock
    window_mock = MagicMock()
    window_mock.width = 1920
    window_mock.height = 1080
    _make_mock_module("kivy.core", {})
    _make_mock_module("kivy.core.window", {"Window": window_mock})
    _make_mock_module("kivy.core.clipboard", {"Clipboard": MagicMock()})

    # Kivy graphics
    _make_mock_module(
        "kivy.graphics",
        {
            "Color": MagicMock(),
            "Rectangle": MagicMock(),
            "Line": MagicMock(),
            "Ellipse": MagicMock(),
        },
    )

    # --- KivyMD ---
    _make_mock_module("kivymd", {})
    _make_mock_module(
        "kivymd.app",
        {
            "MDApp": type(
                "MDApp",
                (),
                {
                    "__init__": lambda self, **kw: None,
                    "theme_cls": MagicMock(),
                },
            )
        },
    )
    _make_mock_module("kivymd.uix", {})
    _make_mock_module(
        "kivymd.uix.screen",
        {
            "MDScreen": type(
                "MDScreen",
                (),
                {
                    "__init__": lambda self, **kw: None,
                },
            )
        },
    )
    _make_mock_module("kivymd.uix.screenmanager", {"MDScreenManager": MagicMock})
    _make_mock_module(
        "kivymd.uix.boxlayout",
        {
            "MDBoxLayout": type(
                "MDBoxLayout",
                (),
                {
                    "__init__": lambda self, **kw: None,
                    "add_widget": lambda self, w: None,
                    "clear_widgets": lambda self: None,
                    "bind": lambda self, **kw: None,
                    "setter": lambda self, attr: lambda *a: None,
                },
            )
        },
    )
    _make_mock_module(
        "kivymd.uix.label",
        {
            "MDLabel": type(
                "MDLabel",
                (),
                {
                    "__init__": lambda self, **kw: None,
                    "bind": lambda self, **kw: None,
                },
            )
        },
    )
    _make_mock_module(
        "kivymd.uix.button",
        {
            "MDRaisedButton": MagicMock,
            "MDFlatButton": MagicMock,
            "MDIconButton": MagicMock,
        },
    )
    _make_mock_module("kivymd.uix.textfield", {"MDTextField": MagicMock})
    _make_mock_module("kivymd.uix.scrollview", {"MDScrollView": MagicMock})
    _make_mock_module("kivymd.uix.dialog", {"MDDialog": MagicMock})
    _make_mock_module(
        "kivymd.uix.list",
        {
            "MDList": MagicMock,
            "TwoLineIconListItem": MagicMock,
            "OneLineIconListItem": MagicMock,
            "IconLeftWidget": MagicMock,
        },
    )
    _make_mock_module(
        "kivymd.uix.selectioncontrol",
        {
            "MDRadioButton": MagicMock,
            "MDCheckbox": MagicMock,
        },
    )
    _make_mock_module("kivymd.uix.divider", {"MDDivider": MagicMock})
    _make_mock_module("kivymd.uix.snackbar", {"MDSnackbar": MagicMock})
    _make_mock_module(
        "kivymd.uix.navigationrail",
        {
            "MDNavigationRail": MagicMock,
            "MDNavigationRailItem": MagicMock,
        },
    )
    _make_mock_module(
        "kivymd.uix.bottomnavigation",
        {
            "MDBottomNavigation": MagicMock,
            "MDBottomNavigationItem": MagicMock,
        },
    )

    # kivy_garden.mapview — not available
    _make_mock_module("kivy_garden", {})
    _make_mock_module("kivy_garden.mapview", {})
    # Leave MapView import to fail naturally so MAPVIEW_AVAILABLE = False
    if "kivy_garden.mapview" in sys.modules:
        del sys.modules["kivy_garden.mapview"]


def install_backend_mocks():
    """Mock unavailable backend dependencies (sqlcipher3)."""
    if "sqlcipher3" not in sys.modules:
        # Mock sqlcipher3 so talon.db.database can import without the C lib.
        # The existing backend tests already work because they import models
        # directly; UI tests cascade through TalonClient → ClientCache → database.
        mock_sqlite = MagicMock()
        mock_sqlite.Connection = MagicMock
        _make_mock_module(
            "sqlcipher3",
            {
                "connect": MagicMock(),
                "Connection": MagicMock,
            },
        )


# Auto-install mocks when conftest loads (before any test collection)
install_backend_mocks()
install_kivy_mocks()

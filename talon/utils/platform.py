from kivy.utils import platform as _kp

IS_ANDROID: bool = _kp == "android"
IS_DESKTOP: bool = _kp in ("linux", "win", "macosx")

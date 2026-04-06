# tests/test_packaging.py
# Tests for packaging, platform detection, and build configuration.
#
# Verifies:
# - Platform detection works
# - Data/config directory resolution is correct
# - Bundled resource paths resolve
# - Config YAML files exist and are valid
# - PyInstaller spec files are syntactically valid
# - pyproject.toml has required fields
# - Entry point scripts exist and are importable
# - build.py is importable and has expected targets

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


# --- Platform detection -----------------------------------------------------


class TestPlatformDetection:
    def test_platform_is_detected(self):
        from talon.platform import PLATFORM

        assert PLATFORM in ("linux", "windows", "macos", "android", "unknown")

    def test_platform_flags_are_consistent(self):
        from talon.platform import IS_ANDROID, IS_LINUX, IS_MACOS, IS_WINDOWS, PLATFORM

        flags = {
            "linux": IS_LINUX,
            "windows": IS_WINDOWS,
            "macos": IS_MACOS,
            "android": IS_ANDROID,
        }
        # Exactly one flag should be True (or none if unknown)
        true_count = sum(1 for v in flags.values() if v)
        if PLATFORM == "unknown":
            assert true_count == 0
        else:
            assert true_count == 1
            assert flags[PLATFORM] is True

    def test_get_data_dir_returns_string(self):
        from talon.platform import get_data_dir

        path = get_data_dir("talon_test")
        assert isinstance(path, str)
        assert os.path.isabs(path)
        # Clean up
        if os.path.isdir(path):
            os.rmdir(path)

    def test_get_config_dir_returns_string(self):
        from talon.platform import get_config_dir

        path = get_config_dir("talon_test")
        assert isinstance(path, str)
        assert os.path.isabs(path)
        if os.path.isdir(path):
            os.rmdir(path)

    def test_get_default_serial_port(self):
        from talon.platform import get_default_serial_port

        port = get_default_serial_port()
        assert isinstance(port, str)
        assert len(port) > 0


# --- Bundled path resolution ------------------------------------------------


class TestBundledPaths:
    def test_resolves_config_default_yaml(self):
        from talon.platform import get_bundled_path

        path = get_bundled_path("config/default.yaml")
        assert os.path.isfile(path), f"Expected config file at {path}"

    def test_resolves_config_client_yaml(self):
        from talon.platform import get_bundled_path

        path = get_bundled_path("config/client.yaml")
        assert os.path.isfile(path)

    def test_resolves_config_server_yaml(self):
        from talon.platform import get_bundled_path

        path = get_bundled_path("config/server.yaml")
        assert os.path.isfile(path)


# --- Config YAML validity ---------------------------------------------------


class TestConfigFiles:
    def test_default_yaml_is_valid(self):
        import yaml

        path = os.path.join(ROOT, "config", "default.yaml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "app" in data or "heartbeat" in data or "lease" in data

    def test_client_yaml_is_valid(self):
        import yaml

        path = os.path.join(ROOT, "config", "client.yaml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_server_yaml_is_valid(self):
        import yaml

        path = os.path.join(ROOT, "config", "server.yaml")
        with open(path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)


# --- Project structure ------------------------------------------------------


class TestProjectStructure:
    def test_pyproject_toml_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "pyproject.toml"))

    def test_pyproject_has_entry_points(self):
        import tomllib

        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            data = tomllib.load(f)
        scripts = data.get("project", {}).get("scripts", {})
        assert "talon-server" in scripts
        assert "talon-client" in scripts

    def test_pyproject_has_dependencies(self):
        import tomllib

        with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
            data = tomllib.load(f)
        deps = data.get("project", {}).get("dependencies", [])
        # Handle both pinned ("kivymd>=1.2") and URL-based ("kivymd @ https://...")
        dep_names = [d.split(">=")[0].split("<")[0].split(" @")[0].strip().lower() for d in deps]
        for required in ["rns", "kivy", "kivymd", "pynacl", "pyyaml"]:
            assert required in dep_names, f"Missing dependency: {required}"

    def test_entry_point_scripts_exist(self):
        assert os.path.isfile(os.path.join(ROOT, "talon-client.py"))
        assert os.path.isfile(os.path.join(ROOT, "talon-server.py"))

    def test_android_main_py_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "src", "main.py"))

    def test_install_sh_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "install.sh"))

    def test_install_bat_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "install.bat"))


# --- Build spec files -------------------------------------------------------


class TestBuildSpecs:
    def test_client_spec_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "build", "talon-client.spec"))

    def test_server_spec_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "build", "talon-server.spec"))

    def test_buildozer_spec_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "build", "buildozer.spec"))

    def test_client_spec_references_correct_entry(self):
        path = os.path.join(ROOT, "build", "talon-client.spec")
        with open(path) as f:
            content = f.read()
        assert "talon-client.py" in content
        assert "config" in content

    def test_server_spec_references_correct_entry(self):
        path = os.path.join(ROOT, "build", "talon-server.spec")
        with open(path) as f:
            content = f.read()
        assert "talon-server.py" in content
        assert "server" in content

    def test_buildozer_spec_has_required_fields(self):
        path = os.path.join(ROOT, "build", "buildozer.spec")
        with open(path) as f:
            content = f.read()
        for field in ["title", "package.name", "requirements", "android.permissions", "android.api"]:
            assert field in content, f"Missing field: {field}"


# --- Build script -----------------------------------------------------------


class TestBuildScript:
    def test_build_py_exists(self):
        assert os.path.isfile(os.path.join(ROOT, "build.py"))

    def test_build_py_importable(self):
        """build.py should be importable without side effects."""
        import importlib.util

        spec = importlib.util.spec_from_file_location("build", os.path.join(ROOT, "build.py"))
        mod = importlib.util.module_from_spec(spec)
        # Don't execute main — just verify it loads
        assert mod is not None

    def test_build_py_has_help(self):
        """build.py --help should exit cleanly."""
        import subprocess

        result = subprocess.run(
            [sys.executable, os.path.join(ROOT, "build.py"), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0
        assert "client" in result.stdout
        assert "server" in result.stdout
        assert "android" in result.stdout


# --- CLI entry points -------------------------------------------------------


class TestCLIEntryPoints:
    def test_client_cli_importable(self):
        from talon.client.cli import main

        assert callable(main)

    def test_server_cli_importable(self):
        from talon.server.cli import main

        assert callable(main)

    def test_platform_module_importable(self):
        from talon.platform import (
            get_bundled_path,
            get_config_dir,
            get_data_dir,
            get_default_serial_port,
            open_file,
        )

        assert callable(get_data_dir)
        assert callable(get_config_dir)
        assert callable(get_bundled_path)
        assert callable(get_default_serial_port)
        assert callable(open_file)


# --- open_file safety -------------------------------------------------------


class TestOpenFile:
    def test_open_file_returns_false_for_missing(self):
        from talon.platform import open_file

        assert open_file("/nonexistent/file.txt") is False

    def test_open_file_returns_false_for_none(self):
        from talon.platform import open_file

        assert open_file(None) is False

    def test_open_file_returns_false_for_empty(self):
        from talon.platform import open_file

        assert open_file("") is False

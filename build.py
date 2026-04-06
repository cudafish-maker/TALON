#!/usr/bin/env python3
# build.py — Unified build script for T.A.L.O.N.
#
# Builds distributable packages for Linux, Windows, and Android.
# Automatically installs build dependencies if missing.
#
# Usage:
#   python build.py client          Build desktop client (current OS)
#   python build.py server          Build desktop server (current OS)
#   python build.py android         Build Android APK
#   python build.py all             Build client + server for current OS
#   python build.py --clean         Remove previous build artifacts
#
# The script auto-detects the host OS and selects the correct toolchain:
#   Linux/macOS  → PyInstaller (desktop), Buildozer (Android)
#   Windows      → PyInstaller (desktop only)

import argparse
import os
import platform
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD_DIR = os.path.join(ROOT, "build")
DIST_DIR = os.path.join(ROOT, "dist")

# ANSI colors (disabled on Windows unless terminal supports them)
if sys.platform == "win32":
    try:
        os.system("")  # enable ANSI on Windows 10+
    except Exception:
        pass

GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"


def info(msg):
    print(f"{CYAN}[BUILD]{RESET} {msg}")


def ok(msg):
    print(f"{GREEN}[  OK ]{RESET} {msg}")


def warn(msg):
    print(f"{YELLOW}[WARN]{RESET} {msg}")


def fail(msg):
    print(f"{RED}[FAIL]{RESET} {msg}")
    sys.exit(1)


# -------------------------------------------------------------------
# Dependency checks
# -------------------------------------------------------------------

def ensure_pyinstaller():
    """Ensure PyInstaller is installed, install it if not."""
    try:
        import PyInstaller  # noqa: F401
        ok("PyInstaller found")
    except ImportError:
        info("Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0", "-q"]
        )
        ok("PyInstaller installed")


def ensure_buildozer():
    """Ensure Buildozer is installed, install it if not."""
    if shutil.which("buildozer"):
        ok("Buildozer found")
        return

    try:
        import buildozer  # noqa: F401
        ok("Buildozer found")
    except ImportError:
        info("Installing Buildozer...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "buildozer>=1.5", "-q"]
        )
        ok("Buildozer installed")

    # Buildozer also needs Cython for some recipes
    try:
        import Cython  # noqa: F401
    except ImportError:
        info("Installing Cython (needed by Buildozer)...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "cython", "-q"]
        )


# -------------------------------------------------------------------
# Clean
# -------------------------------------------------------------------

def clean():
    """Remove previous build artifacts."""
    for d in [DIST_DIR, os.path.join(BUILD_DIR, "linux"),
              os.path.join(BUILD_DIR, "windows")]:
        if os.path.isdir(d):
            info(f"Removing {os.path.relpath(d, ROOT)}/")
            shutil.rmtree(d)

    # PyInstaller work dirs
    for name in ["talon-client", "talon-server"]:
        work = os.path.join(ROOT, name)
        if os.path.isdir(work):
            shutil.rmtree(work)

    ok("Build artifacts cleaned")


# -------------------------------------------------------------------
# Desktop builds (PyInstaller)
# -------------------------------------------------------------------

def _run_pyinstaller(spec_name: str):
    """Run PyInstaller with the given spec file.

    Args:
        spec_name: Filename of the .spec file in build/.
    """
    spec_path = os.path.join(BUILD_DIR, spec_name)
    if not os.path.isfile(spec_path):
        fail(f"Spec file not found: {spec_path}")

    info(f"Building {spec_name.replace('.spec', '')}...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--distpath", DIST_DIR,
        "--workpath", os.path.join(BUILD_DIR, "work"),
        "--noconfirm",
        spec_path,
    ]
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        fail(f"PyInstaller failed for {spec_name}")

    # Determine output directory
    app_name = spec_name.replace(".spec", "")
    output = os.path.join(DIST_DIR, app_name)

    # Copy config files into the output bundle
    config_dest = os.path.join(output, "config")
    os.makedirs(config_dest, exist_ok=True)
    for yaml_file in ["default.yaml", "client.yaml", "server.yaml"]:
        src = os.path.join(ROOT, "config", yaml_file)
        if os.path.isfile(src):
            shutil.copy2(src, config_dest)

    ok(f"Built → {os.path.relpath(output, ROOT)}/")
    return output


def build_client_desktop():
    """Build the desktop client binary."""
    ensure_pyinstaller()
    return _run_pyinstaller("talon-client.spec")


def build_server_desktop():
    """Build the desktop server binary."""
    ensure_pyinstaller()
    return _run_pyinstaller("talon-server.spec")


# -------------------------------------------------------------------
# Android build (Buildozer)
# -------------------------------------------------------------------

def build_android():
    """Build the Android APK using Buildozer."""
    if sys.platform == "win32":
        fail("Android builds are not supported on Windows. Use Linux or WSL.")

    ensure_buildozer()

    # Ensure the Android main.py entry point exists
    main_py = os.path.join(ROOT, "src", "main.py")
    if not os.path.isfile(main_py):
        fail(f"Android entry point missing: {main_py}\n"
             f"  This file should import and launch the Kivy app.")

    spec = os.path.join(BUILD_DIR, "buildozer.spec")
    if not os.path.isfile(spec):
        fail(f"Buildozer spec not found: {spec}")

    info("Building Android APK (this may take a while on first build)...")
    info("Buildozer will download the Android SDK/NDK if not cached.")

    # Buildozer expects to be run from the directory containing the spec
    # We copy the spec to the project root temporarily
    root_spec = os.path.join(ROOT, "buildozer.spec")
    shutil.copy2(spec, root_spec)

    try:
        result = subprocess.run(
            ["buildozer", "-v", "android", "debug"],
            cwd=ROOT,
        )
        if result.returncode != 0:
            fail("Buildozer build failed — check output above")
    finally:
        # Clean up the copied spec
        if os.path.isfile(root_spec):
            os.unlink(root_spec)

    # Find the output APK
    bin_dir = os.path.join(ROOT, "bin")
    if os.path.isdir(bin_dir):
        apks = [f for f in os.listdir(bin_dir) if f.endswith(".apk")]
        if apks:
            # Move to dist/
            os.makedirs(DIST_DIR, exist_ok=True)
            for apk in apks:
                src = os.path.join(bin_dir, apk)
                dst = os.path.join(DIST_DIR, apk)
                shutil.move(src, dst)
                ok(f"APK → {os.path.relpath(dst, ROOT)}")
            return

    warn("APK not found in bin/ — check Buildozer output")


# -------------------------------------------------------------------
# Summary
# -------------------------------------------------------------------

def print_summary(outputs):
    """Print a summary of what was built."""
    print()
    print("=" * 50)
    print(f"  {GREEN}T.A.L.O.N. build complete{RESET}")
    print("=" * 50)
    print()

    if not outputs:
        warn("No outputs produced")
        return

    for label, path in outputs:
        if path and os.path.exists(path):
            print(f"  {label}:")
            print(f"    {os.path.relpath(path, ROOT)}/")
            print()

    # Platform-specific run instructions
    if sys.platform == "win32":
        print("  Run the client:")
        print("    dist\\talon-client\\talon-client.exe")
        print()
        print("  Run the server:")
        print("    dist\\talon-server\\talon-server.exe")
    else:
        print("  Run the client:")
        print("    ./dist/talon-client/talon-client")
        print()
        print("  Run the server:")
        print("    ./dist/talon-server/talon-server")
    print()


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="T.A.L.O.N. build system — package for Linux, Windows, or Android",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  python build.py client          Build desktop client
  python build.py server          Build desktop server
  python build.py all             Build client + server
  python build.py android         Build Android APK
  python build.py --clean         Remove build artifacts
  python build.py --clean all     Clean then build everything
""",
    )
    parser.add_argument(
        "target",
        nargs="?",
        choices=["client", "server", "android", "all"],
        help="What to build",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove previous build artifacts before building",
    )
    args = parser.parse_args()

    if args.clean:
        clean()

    if not args.target:
        if not args.clean:
            parser.print_help()
        return

    host = platform.system().lower()
    info(f"Host platform: {host}")
    info(f"Python: {sys.version.split()[0]}")
    print()

    outputs = []

    if args.target in ("client", "all"):
        path = build_client_desktop()
        outputs.append(("Desktop client", path))

    if args.target in ("server", "all"):
        path = build_server_desktop()
        outputs.append(("Desktop server", path))

    if args.target == "android":
        build_android()
        outputs.append(("Android APK", os.path.join(DIST_DIR)))

    print_summary(outputs)


if __name__ == "__main__":
    main()

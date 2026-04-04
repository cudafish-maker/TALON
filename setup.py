# setup.py
# This file tells Python how to install T.A.L.O.N. as a package.
# Think of it as an instruction manual for the installer.
# Run "pip install ." from the talon/ directory to install.

from setuptools import setup, find_packages

setup(
    # The name of the software package
    name="talon",

    # Current version number (major.minor.patch)
    # 0.1.0 = first development release
    version="0.1.0",

    # What this software does (shown on PyPI and package managers)
    description="T.A.L.O.N. — Tactical Awareness & Linked Operations Network",

    # Who built it
    author="cudanet",

    # Where to find the actual source code
    # All Python code lives inside the "src" folder
    package_dir={"": "src"},

    # Automatically discover all Python packages inside "src"
    # This finds talon/, server/, client/ and all their subfolders
    packages=find_packages(where="src"),

    # Minimum Python version required to run this software
    python_requires=">=3.12",

    # These create command-line shortcuts after installation:
    # typing "talon-server" in a terminal launches the server
    # typing "talon-client" in a terminal launches the client
    entry_points={
        "console_scripts": [
            "talon-server=server.main:main",
            "talon-client=client.main:main",
        ],
    },
)

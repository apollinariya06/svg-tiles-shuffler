#!/usr/bin/env python3
"""
SVG Tile Shuffler -- one-command installer and launcher.

Usage:
    python install_and_run.py              Install (if needed) and run the app
    python install_and_run.py --install    Force reinstall requirements
"""

import subprocess
import sys
from pathlib import Path

# Minimum Python version required
MIN_PYTHON = (3, 10)

# Resolve paths relative to this script (works from any working directory)
SCRIPT_DIR = Path(__file__).parent.resolve()
VENV_DIR = SCRIPT_DIR / "venv"
REQUIREMENTS = SCRIPT_DIR / "requirements.txt"
APP = SCRIPT_DIR / "UI_app.py"

# Platform-specific paths inside the venv
BIN = "Scripts" if sys.platform == "win32" else "bin"
VENV_PYTHON = VENV_DIR / BIN / ("python.exe" if sys.platform == "win32" else "python")
VENV_PIP = VENV_DIR / BIN / ("pip.exe" if sys.platform == "win32" else "pip")


def check_python_version():
    if sys.version_info < MIN_PYTHON:
        print(f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required.")
        print(f"       You are running Python {sys.version_info.major}.{sys.version_info.minor}.")
        sys.exit(1)


def create_venv():
    """Create the virtual environment if it doesn't exist."""
    if VENV_PYTHON.exists():
        print(f"Virtual environment found at {VENV_DIR}")
        return False  # already exists

    print(f"Creating virtual environment in {VENV_DIR} ...")
    subprocess.run(
        [sys.executable, "-m", "venv", str(VENV_DIR)],
        check=True,
    )
    print("Virtual environment created.")
    return True  # freshly created


def install_requirements(force=False):
    """Install or update requirements in the venv."""
    if not REQUIREMENTS.exists():
        print(f"WARNING: {REQUIREMENTS} not found, skipping install.")
        return

    # Check if install is needed: fresh venv, --install flag, or requirements changed
    marker = VENV_DIR / ".installed"
    if marker.exists() and not force:
        if marker.stat().st_mtime >= REQUIREMENTS.stat().st_mtime:
            print("Requirements already installed (up to date).")
            return

    print("Upgrading pip...")
    subprocess.run(
        [str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )

    print("Installing requirements...")
    subprocess.run(
        [str(VENV_PIP), "install", "-r", str(REQUIREMENTS)],
        check=True,
    )

    # Write marker so we don't reinstall every time
    marker.write_text(REQUIREMENTS.read_text())
    print("Requirements installed successfully.")


def run_app():
    """Launch the Qt application using the venv Python."""
    print("Starting SVG Tile Shuffler...")
    subprocess.run(
        [str(VENV_PYTHON), str(APP)],
        cwd=str(SCRIPT_DIR),
    )


if __name__ == "__main__":
    check_python_version()

    force_install = "--install" in sys.argv

    venv_is_new = create_venv()
    install_requirements(force=venv_is_new or force_install)
    run_app()

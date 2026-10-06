"""Pytest configuration.

Adds the component directory to sys.path so HA-free modules (cover_logic,
dongle_supervisor) can be imported directly without executing the package
__init__.py, which imports Home Assistant.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "custom_components" / "enoceanbt"))

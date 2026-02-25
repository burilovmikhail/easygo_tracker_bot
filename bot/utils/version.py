"""Utility to read version from pyproject.toml"""
import tomllib
from pathlib import Path
from functools import lru_cache


@lru_cache(maxsize=1)
def get_version() -> str:
    """
    Read version from pyproject.toml.
    Returns the version string or 'unknown' if not found.
    Cached to avoid repeated file reads.
    """
    try:
        # Get path to pyproject.toml (two levels up from this file)
        project_root = Path(__file__).parent.parent.parent
        pyproject_path = project_root / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            data = tomllib.load(f)
            return data.get("project", {}).get("version", "unknown")
    except Exception:
        return "unknown"

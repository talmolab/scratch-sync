"""uv package manager CLI interactions."""

import shutil
import subprocess


def find_uv() -> str | None:
    """Find uv binary in PATH."""
    return shutil.which("uv")


def get_uv_version() -> str | None:
    """Get the uv version string."""
    binary = find_uv()
    if not binary:
        return None

    try:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Output is like "uv 0.5.14 (..."
            version_line = result.stdout.strip().split("\n")[0]
            # Extract just the version number
            parts = version_line.split()
            if len(parts) >= 2:
                return parts[1]  # e.g., "0.5.14"
            return version_line
    except Exception:
        pass
    return None

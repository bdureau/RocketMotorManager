"""Rocket Motor Manager - entry point.

Usage:  python main.py [file.rmm.xml | file.eng | file.csv | image.png]

Copyright (c) 2026 Boris du Reau. All rights reserved.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the project packages importable whatever the working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    """Start the application and return its exit code."""
    from application.app import RocketMotorManagerApp

    return RocketMotorManagerApp(sys.argv).run()


if __name__ == "__main__":
    sys.exit(main())

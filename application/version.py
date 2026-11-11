"""Application identity and version information.

Single source of truth for the application name, version and copyright,
used by the UI (About dialog, window titles), the XML writer, the ENG
writer comments and the PyInstaller build scripts.
"""

from localization import N_

APP_NAME = "Rocket Motor Manager"
APP_ID = "RocketMotorManager"
APP_VERSION = "1.0.0"
APP_AUTHOR = "Boris du Reau"
APP_COPYRIGHT = "Copyright (c) 2026 Boris du Reau. All rights reserved."
APP_DESCRIPTION = N_(
    "Design, edit, convert, analyse and archive rocket motor thrust data "
    "(RASP .ENG format compatible with OpenRocket and RockSim)."
)

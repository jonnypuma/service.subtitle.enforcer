# -*- coding: utf-8 -*-
"""Script entry point for Subtitle Enforcer rules management."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from resources.lib.ui import run_rules_action, run_rules_menu


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("add_show", "manage_shows", "set_title"):
        run_rules_action(arg)
    else:
        run_rules_menu()

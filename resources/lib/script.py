# -*- coding: utf-8 -*-
"""Script entry point for Subtitle Enforcer rules management."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import default


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if arg in ("add_show", "manage_shows", "set_title"):
        default.run_rules_action(arg)
    else:
        default.run_rules_menu()

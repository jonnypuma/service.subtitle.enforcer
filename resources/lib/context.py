# -*- coding: utf-8 -*-
"""Context menu: set the subtitle language for this show or movie."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from resources.lib.ui import set_rule_for_context


if __name__ == "__main__":
    set_rule_for_context()

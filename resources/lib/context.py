# -*- coding: utf-8 -*-
"""Context menu: set the subtitle language for this show or movie."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import default


if __name__ == "__main__":
    default.set_rule_for_context()

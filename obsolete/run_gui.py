#!/usr/bin/env python3
"""Q-Rock Simulator — GUI 진입점"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.gui.main_window import main

if __name__ == '__main__':
    main()
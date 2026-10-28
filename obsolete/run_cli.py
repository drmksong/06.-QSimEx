#!/usr/bin/env python3
"""Q-Rock Simulator — CLI 진입점"""

import sys
import os

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.cli.commands import main

if __name__ == '__main__':
    main()
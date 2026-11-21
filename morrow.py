#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Morrow - Terminal Vocabulary System
Author: Morrow Team
License: MIT
"""

import sys
import os

# 将项目根目录置入导入搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from morrow.cli import main

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Morrow - Terminal Vocabulary System
Author: Morrow Team
License: MIT
"""

import sys

if __name__ == "__main__":
    if sys.version_info < (3, 10):
        sys.exit("Morrow requires Python 3.10 or later.")
    try:
        from morrow.cli import main
    except ModuleNotFoundError as exc:
        if exc.name not in {"rich", "websockets"}:
            raise
        sys.exit(f'Missing dependency: {exc.name}. Run "{sys.executable}" -m pip install -r requirements.txt')

    main()

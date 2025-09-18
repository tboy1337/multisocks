#!/usr/bin/env python3
"""
Entry point for running the package directly with `python -m multisocks`
"""

from multisocks.cli import main

__all__ = ["main"]

if __name__ == "__main__":  # pylint: disable=used-before-assignment
    main()

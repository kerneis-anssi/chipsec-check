#!/usr/bin/env python3
"""UEFI configuration policy analyzer - thin entry point."""

import sys

from uefi_policy.cli import main

if __name__ == "__main__":
    sys.exit(main())

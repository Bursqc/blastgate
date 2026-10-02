"""Entry point of the packaged app (PyInstaller). From source use: python -m blastgate"""
import sys

from blastgate.__main__ import main

if __name__ == "__main__":
    sys.exit(main())

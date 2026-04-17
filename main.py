"""
WwiseTagExplorer — Dynamic Tag-based Wwise Resource Navigator
Entry point. Run with: C:\Python311\python.exe main.py
"""

import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.getLogger("autobahn").setLevel(logging.CRITICAL)
logging.getLogger("txaio").setLevel(logging.CRITICAL)

import customtkinter as ctk
from ui.main_window import MainWindow


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    app = MainWindow()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()


if __name__ == "__main__":
    main()

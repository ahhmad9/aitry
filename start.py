"""
Overlord Agent — Bootstrap Launcher
====================================
Double-click this file (or run: python start.py) to launch the GUI.

If customtkinter is not installed yet, this script installs it first,
then re-launches the GUI automatically.
"""
import subprocess
import sys
import os

def ensure_customtkinter():
    try:
        import customtkinter  # noqa
        return True
    except ImportError:
        print("Installing customtkinter (needed for GUI)...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "customtkinter", "--quiet"],
            check=False
        )
        if result.returncode != 0:
            print("ERROR: Could not install customtkinter.")
            print("Please run:  pip install customtkinter")
            input("Press Enter to exit...")
            sys.exit(1)
        return False

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    already_installed = ensure_customtkinter()

    if not already_installed:
        # Re-launch so the fresh import works in a clean interpreter state
        os.execv(sys.executable, [sys.executable, __file__])
    else:
        # Import and run the GUI
        from gui import OverlordGUI
        app = OverlordGUI()
        app.mainloop()

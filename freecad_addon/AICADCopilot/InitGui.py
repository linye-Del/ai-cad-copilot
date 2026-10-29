"""Register the Workbench and start the live bridge after GUI initialization."""

import inspect as _inspect
import os as _os
import sys as _sys

try:
    _addon_dir = _os.path.dirname(_os.path.abspath(__file__))
except NameError:
    _addon_dir = _os.path.dirname(_os.path.abspath(_inspect.getfile(_inspect.currentframe())))
_mod_dir = _os.path.dirname(_addon_dir)
if _mod_dir not in _sys.path:
    _sys.path.insert(0, _mod_dir)

import FreeCAD as App
import FreeCADGui as Gui

from AICADCopilot.Workbench import AICADCopilotWorkbench


Gui.addWorkbench(AICADCopilotWorkbench())

try:
    from PySide import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide2 import QtCore


def _start():
    try:
        from AICADCopilot.Workbench import start_services
        start_services()
        Gui.activateWorkbench("AICADCopilotWorkbench")
    except Exception as exc:
        App.Console.PrintError("AI CAD Copilot failed to start: %s\n" % exc)


QtCore.QTimer.singleShot(0, _start)

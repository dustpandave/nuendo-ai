"""macOS UI automation (System Events via osascript).

Used for the things the MIDI Remote API can't do: typing a position into the
transport, driving the import file dialog, and clicking arbitrary menu items.
Requires Accessibility permission for the app that launches the MCP server
(Claude Desktop / Terminal): System Settings > Privacy & Security > Accessibility.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

DELAY = float(os.environ.get("NUENDO_UI_DELAY", "0.6"))


class AutomationError(RuntimeError):
    pass


def _q(s: str) -> str:
    """Quote a Python string as an AppleScript string literal."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def osascript(script: str, timeout: float = 20) -> str:
    if sys.platform != "darwin":
        raise AutomationError("UI automation is only available on macOS")
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        err = r.stderr.strip()
        if "not allowed assistive access" in err or "-1719" in err or "-25211" in err:
            err += (" — grant Accessibility permission to the app running the MCP server "
                    "(System Settings > Privacy & Security > Accessibility).")
        raise AutomationError(err)
    return r.stdout.strip()


_process_name: str | None = os.environ.get("NUENDO_PROCESS")


def process_name() -> str:
    global _process_name
    if _process_name:
        return _process_name
    out = osascript('tell application "System Events" to get name of every process '
                    'whose name starts with "Nuendo"')
    names = [n.strip() for n in out.split(",") if n.strip()]
    if not names:
        raise AutomationError("Nuendo is not running")
    _process_name = names[0]
    return _process_name


def focus() -> None:
    osascript(f'tell application "System Events" to set frontmost of process {_q(process_name())} to true')
    time.sleep(0.15)


def keystroke(text: str) -> None:
    osascript(f'tell application "System Events" to keystroke {_q(text)}')


KEY_CODES = {"return": 36, "enter": 76, "escape": 53, "tab": 48, "delete": 51,
             "left": 123, "right": 124, "down": 125, "up": 126, "space": 49}


def key(name_or_char: str, modifiers: list[str] | None = None) -> None:
    mods = ""
    if modifiers:
        mods = " using {" + ", ".join(f"{m.lower()} down" for m in modifiers) + "}"
    k = name_or_char.lower()
    if k in KEY_CODES:
        osascript(f'tell application "System Events" to key code {KEY_CODES[k]}{mods}')
    else:
        osascript(f'tell application "System Events" to keystroke {_q(name_or_char)}{mods}')


# ------------------------------------------------------------------- menus
def _menu_ref(path: list[str]) -> str:
    """['File', 'Import', 'Audio File...'] -> AppleScript object reference."""
    if not path:
        raise ValueError("empty menu path")
    ref = f"menu bar item {_q(path[0])} of menu bar 1 of process {_q(process_name())}"
    for item in path[1:]:
        ref = f"menu item {_q(item)} of menu 1 of {ref}"
    return ref


def click_menu(path: list[str]) -> None:
    focus()
    osascript(f'tell application "System Events" to click {_menu_ref(path)}')


def list_menu(path: list[str]) -> list[str]:
    """Item names under a menu (top-level names if path is empty)."""
    if not path:
        out = osascript(f'tell application "System Events" to get name of every menu bar item '
                        f'of menu bar 1 of process {_q(process_name())}')
    else:
        out = osascript(f'tell application "System Events" to get name of every menu item '
                        f'of menu 1 of {_menu_ref(path)}')
    return [s.strip() for s in out.split(", ") if s.strip() and s.strip() != "missing value"]


# ------------------------------------------------------------ composite ops
def type_into_focused_field(text: str) -> None:
    keystroke(text)
    time.sleep(0.05)
    key("return")


def choose_file_in_open_dialog(path: str) -> None:
    """Assumes a standard macOS open panel is frontmost."""
    time.sleep(DELAY)
    key("g", ["command", "shift"])      # Go to folder
    time.sleep(DELAY / 2)
    keystroke(path)
    time.sleep(DELAY / 2)
    key("return")                        # go there (selects the file)
    time.sleep(DELAY)
    key("return")                        # Open

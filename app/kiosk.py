"""The board in its own locked-down browser window (D120).

`python run.py --tavle` opens the board in kiosk mode – full screen, no
address bar, tabs or menus – with its own browser profile (so it never shares
a login with the admin browser), on the second screen. It opens /tavle, which
marks that browser as «the board»: from then on the app only ever shows it
the board (see the middleware in main.py).

Uses the browser already on the PC (Edge first, then Chrome). If none is
found, the app still starts and says how to open the board by hand.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

CANDIDATES = [
    ("edge", r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
    ("edge", r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ("chrome", r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    ("chrome", r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]
PATH_NAMES = [("edge", "msedge"), ("chrome", "chrome"), ("chrome", "google-chrome"),
              ("chrome", "chromium"), ("chrome", "chromium-browser")]


def find_browser() -> tuple[str, str] | None:
    """(kind, path) of Edge or Chrome, or None."""
    for kind, raw in CANDIDATES:
        path = os.path.expandvars(raw)
        if "%" not in path and Path(path).is_file():
            return kind, path
    for kind, name in PATH_NAMES:
        found = shutil.which(name)
        if found:
            return kind, found
    return None


def command(kind: str, path: str, url: str, profile: Path, x: int) -> list[str]:
    common = [f"--user-data-dir={profile}", f"--window-position={x},0", "--no-first-run",
              "--disable-session-crashed-bubble", "--disable-infobars"]
    if kind == "edge":
        return [path, "--kiosk", url, "--edge-kiosk-type=fullscreen", *common]
    return [path, "--kiosk", f"--app={url}", *common]


def open_board(url: str, profile: Path, x: int) -> str:
    """Start the kiosk window; returns a line for the console."""
    found = find_browser()
    if found is None:
        return (f"Fant ikke Edge eller Chrome for tavlen. Åpne {url} i et eget nettleservindu på "
                "storskjermen i stedet.")
    profile.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(command(*found, url, profile, x), close_fds=True)
    except OSError as error:
        return f"Kunne ikke åpne tavlen ({error}). Åpne {url} på storskjermen i stedet."
    return f"Tavlen åpnet i kiosk-modus ({found[0]}) – lukk med Alt+F4."

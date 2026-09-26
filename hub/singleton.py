"""Una sola finestra dell'hub per volta.

Senza questo, cliccare due volte sull'eseguibile apre due hub che si
contendono lo stesso state.json e consumano il doppio delle richieste a
GitHub. Qui invece il secondo avvio porta in primo piano la finestra gia'
aperta e si chiude.

Usa un mutex con nome di Windows, che il sistema rilascia da solo se il
processo muore male: nessun file di lock da ripulire a mano.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from . import APP_TITLE

MUTEX_NAME = "Local\\Sici29Hub-istanza-unica"
ERROR_ALREADY_EXISTS = 183

_handle = None


def acquire() -> bool:
    """True se siamo la prima istanza, False se ce n'e' gia' una."""
    global _handle
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        _handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
        return kernel32.GetLastError() != ERROR_ALREADY_EXISTS
    except Exception:
        # Su una piattaforma senza mutex meglio far partire l'hub che bloccarlo.
        return True


def release() -> None:
    global _handle
    if _handle:
        try:
            ctypes.windll.kernel32.ReleaseMutex(_handle)
            ctypes.windll.kernel32.CloseHandle(_handle)
        except Exception:
            pass
        _handle = None


def focus_existing() -> bool:
    """Porta in primo piano la finestra dell'hub gia' aperta."""
    try:
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = wintypes.HWND
        hwnd = user32.FindWindowW(None, APP_TITLE)
        if not hwnd:
            return False
        SW_RESTORE = 9
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False

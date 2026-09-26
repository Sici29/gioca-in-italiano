"""Notifiche di Windows per gli aggiornamenti trovati.

Usa l'API di sistema tramite PowerShell, senza dipendenze aggiuntive. Non e'
garantito che funzioni ovunque (serve un AppUserModelID riconosciuto), quindi
qualsiasi errore viene ignorato: la segnalazione vera resta quella dentro
l'hub, questa e' un di piu'.
"""

from __future__ import annotations

import subprocess
import threading

# Powershell e' gia' presente su Windows e questo AppID esiste sempre.
_APP_ID = "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe"

_SCRIPT = """
$ErrorActionPreference = 'Stop'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] | Out-Null
$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml(@"
<toast><visual><binding template="ToastGeneric">
<text>%TITLE%</text><text>%BODY%</text>
</binding></visual></toast>
"@)
$toast = New-Object Windows.UI.Notifications.ToastNotification $xml
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('%APPID%').Show($toast)
"""


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _send(title: str, body: str) -> None:
    script = (
        _SCRIPT.replace("%TITLE%", _escape(title))
        .replace("%BODY%", _escape(body))
        .replace("%APPID%", _APP_ID)
    )
    try:
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        pass


def toast(title: str, body: str) -> None:
    """Mostra una notifica senza bloccare l'hub."""
    threading.Thread(target=_send, args=(title, body), daemon=True).start()


def updates_found(projects: list[dict]) -> None:
    """Notifica riassuntiva per le traduzioni aggiornate."""
    if not projects:
        return
    if len(projects) == 1:
        p = projects[0]
        latest = (p.get("latest") or {}).get("tag", "")
        toast(
            "Aggiornamento disponibile",
            f"{p.get('title', '')} {latest}".strip(),
        )
    else:
        nomi = ", ".join(p.get("title", "") for p in projects[:3])
        extra = f" e altre {len(projects) - 3}" if len(projects) > 3 else ""
        toast(f"{len(projects)} traduzioni da aggiornare", f"{nomi}{extra}")

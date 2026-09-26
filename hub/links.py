"""Costruzione dei link verso GitHub per bug e proposte.

I pulsanti dell'hub non aprono un modulo vuoto: precompilano la segnalazione
con la versione della traduzione, quella dell'hub e i dati di Windows. Sono
esattamente le informazioni che altrimenti andrebbero chieste a chi segnala,
e che quasi mai arrivano al primo giro.
"""

from __future__ import annotations

import platform
from urllib.parse import quote

from . import __version__, config


def _compose(base: str, title: str, body: str, labels: str = "") -> str:
    url = f"{base}?title={quote(title)}&body={quote(body)}"
    if labels:
        url += f"&labels={quote(labels)}"
    return url


def _environment(project: dict | None = None) -> str:
    righe = [
        "",
        "---",
        "_Dati raccolti automaticamente dall'hub:_",
        "",
        f"- Hub: {__version__}",
        f"- Windows: {platform.version()} ({platform.machine()})",
    ]
    if project:
        latest = project.get("latest") or {}
        righe += [
            f"- Traduzione: {project.get('title', '')} ({project.get('repo', '')})",
            f"- Versione installata: {project.get('installed_tag') or 'nessuna'}",
            f"- Ultima disponibile: {latest.get('tag') or '-'}",
        ]
        if project.get("installed_game"):
            righe.append(
                f"- Gioco rilevato: si', via {project.get('game_source', '?')}"
            )
        else:
            righe.append("- Gioco rilevato: no")
    return "\n".join(righe)


def bug_report(project: dict) -> str:
    """Segnalazione di un problema su una traduzione specifica."""
    repo = project.get("repo", "")
    base = f"https://github.com/{config.GITHUB_USER}/{repo}/issues/new"
    title = f"[Bug] {project.get('title', repo)}: "
    body = (
        "**Cosa succede**\n\n\n"
        "**Cosa ti aspettavi**\n\n\n"
        "**Come riprodurlo**\n\n1. \n2. \n3. \n\n"
        "**Screenshot o log** (se ne hai)\n\n"
        + _environment(project)
    )
    return _compose(base, title, body, "bug")


def suggest_translation() -> str:
    """Proposta di un gioco da tradurre.

    Le proposte finiscono sul repo profilo: e' l'unico non legato a un singolo
    gioco, ed e' il posto naturale per raccoglierle tutte insieme.
    """
    base = f"https://github.com/{config.GITHUB_USER}/{config.SUGGESTIONS_REPO}/issues/new"
    title = f"{config.PROPOSAL_PREFIX} "
    body = (
        "**Gioco**\n\n\n"
        "**Dove si trova** (Steam, Epic, GOG, altro)\n\n\n"
        "**Perche' servirebbe** (quanto e' diffuso, esiste gia' una traduzione, "
        "quanto testo ha)\n\n\n"
        "**Link alla pagina del gioco**\n\n"
        + _environment()
    )
    return _compose(base, title, body, "proposta")


def releases(repo: str) -> str:
    return f"https://github.com/{config.GITHUB_USER}/{repo}/releases"


def issues(repo: str) -> str:
    return f"https://github.com/{config.GITHUB_USER}/{repo}/issues"

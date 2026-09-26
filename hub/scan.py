"""Rilevamento dei giochi installati sul PC.

Serve al filtro "mostra solo i giochi che ho": l'hub incrocia questa lista con
il catalogo delle traduzioni e mostra solo cio' che e' davvero installato.

Fonti, in ordine di affidabilita':
  - Steam   : appmanifest_*.acf nelle librerie dichiarate in libraryfolders.vdf
              (da' l'AppID esatto, quindi l'abbinamento e' certo)
  - Epic    : i manifest .item in ProgramData
  - GOG     : le chiavi di registro di GOG Galaxy
  - registro: l'elenco programmi installati di Windows, che pesca anche i
              giochi fuori dagli store (e' cosi' che si trova Star Citizen,
              installato dal launcher RSI)

Tutto e' avvolto in try/except: su un PC senza Steam, o senza permessi su una
chiave, la scansione deve degradare in silenzio, non far fallire l'hub.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

try:
    import winreg
except ImportError:  # non-Windows, utile solo per i test
    winreg = None  # type: ignore

# Giochi che non compaiono in nessuno store e nemmeno nel registro con un
# percorso utile. Star Citizen e' il caso tipico: il registro elenca solo
# "RSI Launcher" senza cartella, il file di configurazione del launcher e'
# cifrato, e la cartella di installazione la sceglie l'utente (su questo PC
# era "D:\Robert Space Industries", con "Robert" al singolare). L'unico modo
# affidabile e' cercare la cartella del gioco sui dischi.
STANDALONE = (
    {
        "name": "Star Citizen",
        "folder": "starcitizen",
        # L'eseguibile sta dentro la sottocartella del canale (LIVE, PTU...).
        "exe": ("Bin64", "StarCitizen.exe"),
        "nested": True,
        "source": "RSI Launcher",
    },
)

# Quanto in profondita' scendere dalla radice di ogni disco. Tre livelli
# bastano per i percorsi normali e tengono la ricerca sotto i due secondi.
MAX_DEPTH = 3

# Cartelle in cui non ha senso entrare: sono enormi, di sistema, o gia'
# coperte dagli store.
SKIP_DIRS = {
    "windows", "$recycle.bin", "system volume information", "appdata",
    "programdata", "node_modules", "steamapps", "onedrive", "perflogs",
    "recovery", "boot", "msocache", "temp", "tmp", ".git",
}

SOURCE_STEAM = "Steam"
SOURCE_EPIC = "Epic Games"
SOURCE_GOG = "GOG"
SOURCE_SYSTEM = "Windows"

# Voci dell'elenco programmi che non sono giochi e sporcherebbero i confronti.
_REGISTRY_NOISE = re.compile(
    r"(?i)\b(redistributable|runtime|driver|sdk|framework|visual c\+\+|"
    r"directx|\.net|update for|hotfix|python|nvidia|amd software|realtek)\b"
)


def norm(name: str) -> str:
    """Chiave di confronto: solo lettere e numeri, minuscole."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").casefold()).strip()


# --- Steam -------------------------------------------------------------------


def steam_root() -> Path | None:
    if winreg is None:
        return None
    for hive, key in (
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                for value in ("SteamPath", "InstallPath"):
                    try:
                        path = Path(winreg.QueryValueEx(handle, value)[0])
                        if path.exists():
                            return path
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def steam_libraries() -> list[Path]:
    """Tutte le cartelle libreria, comprese quelle su altri dischi."""
    root = steam_root()
    if not root:
        return []

    libraries = [root]
    vdf = root / "steamapps" / "libraryfolders.vdf"
    try:
        text = vdf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return libraries

    # Il formato KeyValues di Valve si legge bene con una regex: cerchiamo
    # solo le righe "path" "<cartella>".
    for match in re.finditer(r'"path"\s+"([^"]+)"', text):
        candidate = Path(match.group(1).replace("\\\\", "\\"))
        if candidate.exists() and candidate not in libraries:
            libraries.append(candidate)
    return libraries


def steam_games() -> list[dict]:
    games: list[dict] = []
    seen: set[int] = set()

    for library in steam_libraries():
        apps = library / "steamapps"
        try:
            manifests = list(apps.glob("appmanifest_*.acf"))
        except OSError:
            continue

        for manifest in manifests:
            try:
                text = manifest.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            appid = _vdf_value(text, "appid")
            name = _vdf_value(text, "name")
            installdir = _vdf_value(text, "installdir")
            if not appid or not name:
                continue
            try:
                appid_int = int(appid)
            except ValueError:
                continue
            if appid_int in seen:
                continue
            seen.add(appid_int)

            path = apps / "common" / installdir if installdir else apps
            # Il buildid e' il numero esatto della build installata: e' quello
            # che permette di dire se una traduzione e' allineata al gioco.
            # LastUpdated dice *quando* il gioco e' stato aggiornato l'ultima
            # volta, utile quando il buildid manca dalle due parti.
            games.append(
                {
                    "name": name,
                    "appid": appid_int,
                    "path": str(path),
                    "source": SOURCE_STEAM,
                    "build": _intero(_vdf_value(text, "buildid")),
                    "updated": _intero(_vdf_value(text, "LastUpdated")),
                }
            )
    return games


def _vdf_value(text: str, key: str) -> str | None:
    match = re.search(rf'"{key}"\s+"([^"]*)"', text, re.IGNORECASE)
    return match.group(1) if match else None


def _intero(valore: str | None) -> int | None:
    try:
        return int(valore) if valore else None
    except (TypeError, ValueError):
        return None


# --- Epic --------------------------------------------------------------------


def epic_games() -> list[dict]:
    folder = Path(r"C:\ProgramData\Epic\EpicGamesLauncher\Data\Manifests")
    games: list[dict] = []
    try:
        items = list(folder.glob("*.item"))
    except OSError:
        return games

    for item in items:
        try:
            data = json.loads(item.read_text(encoding="utf-8", errors="ignore"))
        except (OSError, ValueError):
            continue
        name = data.get("DisplayName")
        if not name:
            continue
        games.append(
            {
                "name": name,
                "appid": None,
                "path": data.get("InstallLocation") or "",
                "source": SOURCE_EPIC,
            }
        )
    return games


# --- GOG ---------------------------------------------------------------------


def gog_games() -> list[dict]:
    if winreg is None:
        return []
    games: list[dict] = []
    for hive, key in (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"),
    ):
        try:
            with winreg.OpenKey(hive, key) as root:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, sub) as handle:
                            name = _reg_value(handle, "gameName")
                            path = _reg_value(handle, "path")
                    except OSError:
                        continue
                    if name:
                        games.append(
                            {
                                "name": name,
                                "appid": None,
                                "path": path or "",
                                "source": SOURCE_GOG,
                            }
                        )
        except OSError:
            continue
    return games


# --- elenco programmi di Windows ---------------------------------------------


def registry_games() -> list[dict]:
    """Programmi installati, filtrati dal rumore.

    E' la rete di sicurezza per i giochi che non stanno in nessuno store:
    Star Citizen, per esempio, si installa dal launcher RSI e comparirebbe
    solo qui.
    """
    if winreg is None:
        return []

    keys = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )

    found: list[dict] = []
    seen: set[str] = set()

    for hive, key in keys:
        try:
            with winreg.OpenKey(hive, key) as root:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(root, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(root, sub) as handle:
                            name = _reg_value(handle, "DisplayName")
                            if not name or _REGISTRY_NOISE.search(name):
                                continue
                            if _reg_value(handle, "SystemComponent") == 1:
                                continue
                            path = _reg_value(handle, "InstallLocation") or ""
                    except OSError:
                        continue

                    key_name = norm(name)
                    if not key_name or key_name in seen:
                        continue
                    seen.add(key_name)
                    found.append(
                        {
                            "name": name,
                            "appid": None,
                            "path": path,
                            "source": SOURCE_SYSTEM,
                        }
                    )
        except OSError:
            continue
    return found


def _reg_value(handle, name: str):
    try:
        return winreg.QueryValueEx(handle, name)[0]
    except OSError:
        return None


# --- come si avvia un gioco --------------------------------------------------


def _launcher_rsi_dal_registro():
    """Dove Windows sa che sta il launcher RSI.

    La voce di disinstallazione ha InstallLocation vuoto (verificato), ma il
    percorso del programma di disinstallazione c'e', e il launcher sta nella
    stessa cartella.
    """
    if winreg is None:
        return
    chiavi = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    )
    for hive, chiave in chiavi:
        try:
            with winreg.OpenKey(hive, chiave) as radice:
                indice = 0
                while True:
                    try:
                        sotto = winreg.EnumKey(radice, indice)
                    except OSError:
                        break
                    indice += 1
                    try:
                        with winreg.OpenKey(radice, sotto) as voce:
                            nome = str(_reg_value(voce, "DisplayName") or "")
                            if not nome.lower().startswith("rsi launcher"):
                                continue
                            for campo in ("UninstallString", "DisplayIcon"):
                                valore = str(_reg_value(voce, campo) or "").strip()
                                if valore.startswith('"'):
                                    percorso = valore.split('"')[1]
                                else:
                                    percorso = valore.split(",")[0]
                                if percorso:
                                    yield Path(percorso).parent / "RSI Launcher.exe"
                    except OSError:
                        continue
        except OSError:
            continue


def launcher_rsi(cartella_gioco: str | Path | None = None) -> Path | None:
    """Il launcher di Star Citizen, che e' da dove il gioco si avvia.

    Star Citizen non parte da solo: chiede l'accesso all'account RSI, e
    quello lo fa il launcher. Si cerca risalendo dalla cartella del gioco
    (LIVE, poi StarCitizen, poi la cartella che contiene anche "RSI
    Launcher"), poi nel registro, poi nel posto predefinito.
    """
    candidati: list[Path] = []
    if cartella_gioco:
        partenza = Path(cartella_gioco)
        for cartella in (partenza, *partenza.parents):
            candidati.append(cartella / "RSI Launcher" / "RSI Launcher.exe")
    candidati.extend(_launcher_rsi_dal_registro())
    programmi = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidati.append(
        Path(programmi) / "Roberts Space Industries" / "RSI Launcher" / "RSI Launcher.exe"
    )
    for candidato in candidati:
        try:
            if candidato.is_file():
                return candidato
        except OSError:
            continue
    return None


# --- giochi fuori dagli store ------------------------------------------------


def _verifica(voce: dict, cartella: Path) -> str | None:
    """Conferma che in quella cartella ci sia davvero il gioco.

    Torna il percorso da mostrare all'utente, cioe' quello del canale
    (`...\StarCitizen\LIVE`), non quello della cartella contenitore.
    """
    try:
        if voce.get("nested"):
            for canale in sorted(cartella.iterdir()):
                if canale.is_dir() and (canale / Path(*voce["exe"])).exists():
                    return str(canale)
            return None
        return str(cartella) if (cartella / Path(*voce["exe"])).exists() else None
    except OSError:
        return None


def _cerca_cartelle(radice: Path, nomi: set[str], profondita: int, trovate: dict) -> None:
    if profondita < 0:
        return
    try:
        voci = list(radice.iterdir())
    except (OSError, PermissionError):
        return
    for voce in voci:
        try:
            if not voce.is_dir():
                continue
        except OSError:
            continue
        nome = voce.name.lower()
        if nome in nomi:
            trovate.setdefault(nome, []).append(voce)
            continue
        if nome in SKIP_DIRS or nome.startswith("$"):
            continue
        _cerca_cartelle(voce, nomi, profondita - 1, trovate)


# Dove ogni gioco fuori dagli store scrive la propria versione. Steam ha il
# buildid nel suo manifest e non serve niente di tutto questo; per gli altri
# tocca sapere dove guardare, uno per uno.
VERSIONE_SU_DISCO = {
    # Il launcher RSI lascia un JSON nella cartella del canale. "Version" e'
    # la versione piena (4.10.193.11644), "Branch" quella che la gente usa
    # per dire che patch sta giocando (sc-alpha-4.10.0).
    "Star Citizen": {
        "file": "build_manifest.id",
        "chiavi": ("Data", "Version"),
        "ramo": ("Data", "Branch"),
    },
}


def _dentro(dati, percorso: tuple) -> str:
    for chiave in percorso:
        if not isinstance(dati, dict):
            return ""
        dati = dati.get(chiave)
    return str(dati) if isinstance(dati, (str, int)) else ""


def versione_standalone(voce: dict, cartella: str) -> dict:
    """Versione del gioco letta dai suoi file, se sappiamo dove guardare.

    Torna un dizionario da fondere nel record del gioco: vuoto se il gioco non
    e' fra quelli noti o se il file non c'e'. Non si inventa niente: senza una
    versione certa e' meglio non dire nulla che dire una cosa sbagliata.
    """
    regole = VERSIONE_SU_DISCO.get(voce.get("name", ""))
    if not regole:
        return {}
    try:
        testo = (Path(cartella) / regole["file"]).read_text(
            encoding="utf-8", errors="ignore"
        )
        dati = json.loads(testo)
    except (OSError, ValueError):
        return {}

    fuori = {}
    versione = _dentro(dati, regole["chiavi"])
    ramo = _dentro(dati, regole.get("ramo", ()))
    if versione:
        fuori["version"] = versione
    if ramo:
        fuori["branch"] = ramo
    return fuori


def standalone_games(known: dict | None = None) -> tuple[list[dict], dict]:
    """Giochi installati fuori dagli store.

    `known` sono i percorsi gia' trovati in passato: se esistono ancora, si
    evita di riscandire i dischi. La ricerca vera costa un paio di secondi e
    va fatta una volta sola, non a ogni aggiornamento del catalogo.

    Torna (giochi trovati, percorsi da ricordare).
    """
    known = known or {}
    giochi: list[dict] = []
    memoria: dict[str, str] = {}
    da_cercare = []

    for voce in STANDALONE:
        salvato = known.get(voce["name"])
        if salvato and Path(salvato).exists():
            giochi.append(
                {
                    "name": voce["name"],
                    "appid": None,
                    "path": salvato,
                    "source": voce["source"],
                    **versione_standalone(voce, salvato),
                }
            )
            memoria[voce["name"]] = salvato
        else:
            da_cercare.append(voce)

    if not da_cercare:
        return giochi, memoria

    nomi = {v["folder"] for v in da_cercare}
    trovate: dict[str, list[Path]] = {}
    for lettera in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        radice = Path(f"{lettera}:/")
        try:
            if not radice.exists():
                continue
        except OSError:
            continue
        _cerca_cartelle(radice, nomi, MAX_DEPTH, trovate)

    for voce in da_cercare:
        for cartella in trovate.get(voce["folder"], []):
            percorso = _verifica(voce, cartella)
            if percorso:
                giochi.append(
                    {
                        "name": voce["name"],
                        "appid": None,
                        "path": percorso,
                        "source": voce["source"],
                        **versione_standalone(voce, percorso),
                    }
                )
                memoria[voce["name"]] = percorso
                break

    return giochi, memoria


# --- scansione completa ------------------------------------------------------


def scan(known_paths: dict | None = None) -> dict:
    """Tutto cio' che risulta installato, pronto per l'abbinamento."""
    games: list[dict] = []
    for collect in (steam_games, epic_games, gog_games, registry_games):
        try:
            games.extend(collect())
        except Exception:
            continue

    # I giochi fuori dagli store vanno per ultimi ma prima dell'indice per
    # nome, cosi' vincono sulla voce generica del launcher nel registro.
    memoria: dict[str, str] = {}
    try:
        extra, memoria = standalone_games(known_paths)
        games.extend(extra)
    except Exception:
        pass

    by_appid = {g["appid"]: g for g in games if g.get("appid")}
    by_name: dict[str, dict] = {}
    for game in games:
        key = norm(game["name"])
        if key and _forza(game) > _forza(by_name.get(key)):
            by_name[key] = game

    return {
        "games": games,
        "by_appid": by_appid,
        "by_name": by_name,
        "count": len(games),
        "sources": sorted({g["source"] for g in games}),
        "known_paths": memoria,
    }


def _forza(game: dict | None) -> int:
    """Quanto vale un record, quando lo stesso gioco arriva da piu' fonti.

    Steam ne sa piu' di tutti: da' AppID e numero di build, che sono quello
    che serve per dire se una traduzione e' allineata al gioco. Il registro di
    Windows vede gli stessi giochi ma senza nessuno dei due, e prima
    sovrascriveva la voce di Steam solo perche' arrivava dopo - cosi' il
    buildid spariva e il confronto fra versioni non si poteva fare.
    """
    if not game:
        return -1
    punti = 0
    if game.get("path"):
        punti += 1
    if game.get("appid"):
        punti += 2
    if game.get("build") or game.get("version"):
        punti += 2
    if game.get("source") == SOURCE_STEAM:
        punti += 1
    return punti


def match(result: dict, title: str, appid: int | None) -> dict | None:
    """Trova il gioco installato che corrisponde a una traduzione.

    L'AppID e' la via certa; il nome e' il ripiego per i giochi fuori Steam.
    """
    if appid and appid in result["by_appid"]:
        return result["by_appid"][appid]

    key = norm(title)
    if not key:
        return None
    if key in result["by_name"]:
        return result["by_name"][key]

    # Ultimo tentativo: il nome del gioco contenuto in quello del programma
    # installato ("Star Citizen" dentro "RSI Launcher - Star Citizen").
    for name_key, game in result["by_name"].items():
        if len(key) >= 6 and (key in name_key or name_key in key):
            return game
    return None

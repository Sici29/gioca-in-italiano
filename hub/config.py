"""Configurazione e, soprattutto, le REGOLE DI RICONOSCIMENTO dei repo.

Qui si decide che cosa l'hub considera "una traduzione". Se un domani
cambi convenzione di nomi, si tocca solo questo file.
"""

from __future__ import annotations

import re

# --- Account GitHub sorgente -------------------------------------------------

GITHUB_USER = "Sici29"

# --- Link vari ---------------------------------------------------------------

BMC_URL = "https://buymeacoffee.com/sici29"
PROFILE_URL = f"https://github.com/{GITHUB_USER}"

# Dove finiscono le proposte di nuove traduzioni. Il repo profilo e' l'unico
# non legato a un singolo gioco, quindi e' il posto giusto per raccoglierle.
SUGGESTIONS_REPO = GITHUB_USER

# --- Riconoscimento dei repo di traduzione -----------------------------------
#
# Un repo entra nell'hub se supera gli ESCLUSI e poi soddisfa ALMENO UNO dei
# tre criteri, in ordine di autorita':
#
#   1. contiene hub.json nella root  -> segnale definitivo, porta i metadati
#   2. ha uno dei topic riconosciuti
#   3. il nome segue una delle convenzioni note
#
# Il criterio 1 e' quello da preferire per i repo futuri: basta committare un
# hub.json e la traduzione compare nell'hub, comunque si chiami il repo.

MARKER_FILE = "hub.json"

RECOGNISED_TOPICS = {
    "italian-translation",
    "traduzione-italiana",
    "italian-localization",
    "fan-translation",
}

NAME_PATTERNS = (
    re.compile(r"-italian-translation$", re.I),
    re.compile(r"-traduzione-italiana$", re.I),
    re.compile(r"^traduzione-", re.I),
)

# Repo da non mostrare mai: il repo-profilo (README della pagina GitHub) e
# qualunque nome aggiunto a mano dalle impostazioni dell'hub.
ALWAYS_EXCLUDE = {GITHUB_USER.lower(), f"{GITHUB_USER.lower()}.github.io", ".github"}


def looks_like_translation(repo: dict, has_marker: bool) -> bool:
    """True se il repo va mostrato nell'hub.

    `repo` e' il dizionario grezzo dell'API GitHub, `has_marker` dice se
    hub.json esiste nella root (lo verifica il chiamante, via raw.github, che
    non consuma rate limit).
    """
    name = (repo.get("name") or "").strip()
    if not name or name.lower() in ALWAYS_EXCLUDE:
        return False
    if repo.get("fork") or repo.get("archived") or repo.get("private"):
        return False
    if repo.get("disabled"):
        return False

    if has_marker:
        return True
    if RECOGNISED_TOPICS.intersection(repo.get("topics") or []):
        return True
    return any(p.search(name) for p in NAME_PATTERNS)


def pretty_game_name(repo_name: str) -> str:
    """Nome leggibile ricavato dal repo, usato se hub.json non lo specifica.

    "ARK-Survival-Ascended-Italian-Translation" -> "ARK Survival Ascended"
    """
    base = repo_name
    for pat in NAME_PATTERNS:
        base = pat.sub("", base)
    base = base.replace("-", " ").replace("_", " ").strip()
    if not base:
        base = repo_name
    # Le sigle tutte maiuscole restano tali (ARK, NTE, SC), il resto va in Title
    words = []
    for w in base.split():
        words.append(w if (w.isupper() and len(w) <= 4) else w.capitalize())
    return " ".join(words)


# --- Aggiornamenti -----------------------------------------------------------

# Ogni quanto l'hub ricontrolla GitHub da solo, mentre e' aperto.
AUTO_REFRESH_MINUTES = 30

# Senza autenticazione GitHub concede 60 richieste all'ora per IP, e un
# controllo completo ne usa 6 (l'elenco dei repo piu' una per ogni traduzione).
# Gli ETag riducono i dati trasferiti ma non le richieste: anche un 304 pesa
# sul limite, verificato sul campo. Da qui le due misure di risparmio.
MIN_REFRESH_SECONDS = 600
RATE_RESERVE = 8

# --- Catalogo pre-generato ---------------------------------------------------
#
# Il modo per non toccare affatto quel limite: una GitHub Action rigenera
# periodicamente un catalog.json con dentro tutto (repo, release, copertine) e
# l'hub lo scarica da raw.githubusercontent, che sta fuori dall'API e non ha
# quel tetto. Un solo file invece di sei chiamate, uguale per tutti gli utenti.
# Se il file manca o e' vecchio, si torna automaticamente all'API.

# Repo che ospita catalog.json: e' lo stesso dove vive l'hub, cosi' la Action
# che lo genera e il file che produce stanno insieme, senza check-out incrociati.
# Da qui arrivano anche gli aggiornamenti dell'hub (le sue release) e il sito.
# Se rinomini il repo, cambia questo nome.
FEED_REPO = "gioca-in-italiano"
FEED_BRANCH = "HEAD"
FEED_PATH = "catalog.json"
FEED_MAX_AGE_HOURS = 36
FEED_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{FEED_REPO}/{FEED_BRANCH}/{FEED_PATH}"

# Il sito pubblico, su GitHub Pages dello stesso repo: una pagina per ogni
# traduzione, rigenerata dalla stessa Action del catalogo (tools/genera_sito.py).
SITO_URL = f"https://{GITHUB_USER.lower()}.github.io/{FEED_REPO}/"

# Il repo dell'hub non e' una traduzione, qualunque topic gli si dia.
ALWAYS_EXCLUDE.add(FEED_REPO.lower())

# --- Copertine dei giochi che su Steam non esistono --------------------------
#
# Per questi non c'e' nessun catalogo da interrogare: l'unica fonte ufficiale
# e' il sito dell'editore. Sono URL pubblici dei loro CDN, usati come si usano
# quelli di Steam: l'immagine resta dell'editore e viene solo mostrata.
#
# Sono quasi sempre marchi su fondo trasparente, non copertine: l'hub se ne
# accorge da solo e li compone sullo sfondo che genera, ridipinti in chiaro.
#
# Un cover_url scritto nel hub.json del repo ha comunque la precedenza.
NON_STEAM_COVERS = {
    "star citizen": "https://cdn.robertsspaceindustries.com/static/images/thumbnail/starcitizen.png",
}


def official_cover(game_name: str) -> str | None:
    """Copertina ufficiale nota per un gioco fuori da Steam."""
    chiave = re.sub(r"[^a-z0-9]+", " ", (game_name or "").casefold()).strip()
    return NON_STEAM_COVERS.get(chiave)


# Quanto resta valida la cache delle copertine prima di riprovare Steam.
COVER_TTL_DAYS = 14

# Formato della card: le capsule orizzontali di Steam sono le uniche presenti
# per ogni gioco (le verticali 600x900 esistono solo per i titoli gia' usciti),
# quindi normalizziamo tutto a questo rapporto per avere una griglia coerente.
COVER_SIZE = (460, 215)


# Etichetta delle issue che l'hub mostra come proposte di traduzione.
# I voti sono le reazioni di GitHub sull'issue: nessun server da mantenere.
PROPOSAL_LABEL = "proposta"

# Il titolo con cui nasce ogni proposta, dall'hub o dal modulo su GitHub.
# E' questo, e non l'etichetta, a dire che un'issue e' una proposta: GitHub
# toglie in silenzio le etichette alle issue aperte da chi non ha i permessi
# di scrittura sul repo, cioe' da tutti tranne l'autore. Filtrando per
# etichetta, nessuna proposta della comunita' sarebbe mai comparsa.
PROPOSAL_PREFIX = "[Proposta]"


# --- Come si guidano gli installer delle traduzioni --------------------------
#
# Tutti gli installer hanno, oltre al menu, una modalita' a comandi che non fa
# domande: l'hub li guida da li', senza finestra. Il nucleo e' lo stesso per
# tutti - install, restore, check - ma le opzioni in piu' cambiano, e
# un'opzione che l'installer non conosce lo fa uscire con un errore. Per
# questo stanno scritte una per una, ricavate dal sorgente di ciascuno.
#
# Un repo puo' dichiarare le proprie nel hub.json, alla voce "installer", con
# la stessa forma di queste: hanno la precedenza.
#
# La cartella del gioco NON si passa: ogni installer ha il suo modo di
# trovarla e conosce il proprio gioco meglio dell'hub, sottocartelle
# comprese. La si aggiunge solo se l'utente l'ha scelta a mano.

INSTALLER_COMANDI = {
    "install": ["install"],
    "restore": ["restore"],
    "check": ["check"],
}

INSTALLER_PER_REPO = {
    # --no-update-check: l'hub ha appena scaricato l'ultima versione, e il
    # controllo su GitHub sarebbe solo un'altra occasione di fallire.
    "Aniimo-Italian-Translation": {
        "install": ["install", "--no-update-check"],
        "check": ["check", "--no-update-check"],
        "backup": ["backup-dir"],
    },
    "ARK-Survival-Ascended-Italian-Translation": {
        "install": ["install", "--no-update-check"],
    },
    # NTE e Fatekeeper chiamano "verify" il loro controllo dei file.
    "NTE-Italian-Translation": {"check": ["verify"]},
    "Fatekeeper-Italian-Translation": {"check": ["verify"]},
}


def installer_profilo(repo: str, dichiarato: dict | None = None) -> dict:
    """I comandi con cui guidare l'installer di una traduzione.

    Prima quello che dichiara il hub.json del repo, poi quello che l'hub sa
    di quel repo, poi il nucleo comune. Solo liste di stringhe: un valore di
    forma diversa viene ignorato invece di arrivare alla riga di comando.
    """
    profilo = {k: list(v) for k, v in INSTALLER_COMANDI.items()}
    profilo.update(INSTALLER_PER_REPO.get(repo, {}))
    for azione, argomenti in (dichiarato or {}).items():
        if isinstance(argomenti, list) and all(isinstance(a, str) for a in argomenti):
            profilo[str(azione)] = list(argomenti)
    return profilo


# --- Accesso a GitHub --------------------------------------------------------
#
# CHI DEVE LEGGERE QUESTA PARTE: solo l'autore dell'hub, una volta sola.
# Chi scarica l'exe non registra niente e non vede nessuna di queste cose:
# trova l'accesso a un clic gia' pronto, perche' le credenziali finiscono
# dentro l'eseguibile.
#
# ATTENZIONE, NON SCRIVERE IL SECRET QUI SE IL REPO E' PUBBLICO.
# GitHub fa secret scanning sui repository pubblici e i client secret OAuth
# li REVOCA da solo appena li vede in un commit: il secret smetterebbe di
# funzionare da un momento all'altro, per tutti.
#
# Il posto giusto e' hub/credenziali.py, che non e' versionato (sta nel
# .gitignore) e viene incluso nell'eseguibile come qualsiasi altro modulo:
#
#     python tools/imposta_credenziali.py      <- lo scrive dagli appunti
#
# I due valori qui sotto restano come ripiego per chi compila da un repo
# privato, e come valore predefinito (vuoto) per tutti gli altri.
#
# Perche' il secret sta qui dentro. GitHub richiede il client_secret anche per
# le app native, perche' non distingue client pubblici da confidenziali. Nella
# sua guida alle buone pratiche scrive pero' che per un'app pubblica, che il
# secret non puo' comunque proteggerlo, e' preferibile l'authorization code
# con PKCE rispetto al device flow. E' la strada che seguiamo: PKCE lega il
# codice di autorizzazione a questa singola sessione, quindi un secret estratto
# dall'eseguibile non basta a farsi dare un token.
#
# Un secret compromesso si revoca e si rigenera dalla stessa pagina.
#
# Finche' restano vuoti l'hub funziona per intero: stelle, voti e proposte
# passano dal browser invece che dalla finestra.
OAUTH_CLIENT_ID = ""
OAUTH_CLIENT_SECRET = ""

# Se hub/credenziali.py esiste, i suoi valori hanno la precedenza. E' il file
# non versionato che tools/imposta_credenziali.py scrive: e' cosi' che le
# credenziali entrano nell'eseguibile senza passare dal repository.
try:  # pragma: no cover - dipende da un file generato a mano
    from .credenziali import (  # type: ignore  # noqa: F401
        OAUTH_CLIENT_ID,
        OAUTH_CLIENT_SECRET,
    )
except ImportError:
    pass

# Porta di ascolto per il ritorno dal browser. Se occupata se ne prende una
# libera: GitHub non pretende che coincida con quella registrata.
OAUTH_CALLBACK_PORT = 47823

# Come si presenta l'applicazione OAuth su GitHub e nella schermata di
# autorizzazione che vede l'utente.
OAUTH_APP_NAME = "Gioca in Italiano"
OAUTH_APP_NOTE = (
    "Hub delle traduzioni italiane di Sici29. "
    "Serve solo per stelle, voti e proposte senza uscire dall'applicazione."
)

# GitHub accetta le redirect su loopback e non pretende che la porta coincida
# con quella registrata: registriamo l'indirizzo senza porta, l'hub ne usera'
# una libera al momento dell'accesso.
OAUTH_CALLBACK_URL = "http://127.0.0.1/callback"


def oauth_register_url() -> str:
    """Pagina di GitHub per creare l'app, col modulo GIA' COMPILATO.

    Il modulo "New OAuth App" accetta i propri campi come parametri nella
    query: arrivando da questo link nome, sito e callback sono gia' dentro e
    resta solo da premere "Register application". Se un domani GitHub
    smettesse di accettarli, i campi risultano vuoti e l'hub mostra comunque i
    valori da copiare a mano: il link continua a portare nel posto giusto.
    """
    from urllib.parse import urlencode

    return "https://github.com/settings/applications/new?" + urlencode(
        {
            "oauth_application[name]": OAUTH_APP_NAME,
            "oauth_application[url]": PROFILE_URL,
            "oauth_application[callback_url]": OAUTH_CALLBACK_URL,
            "oauth_application[description]": OAUTH_APP_NOTE,
        }
    )

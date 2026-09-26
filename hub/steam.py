"""Recupero delle copertine dal database di Steam.

Girando in un'app desktop non esiste il problema CORS che avrebbe un sito web,
quindi possiamo interrogare direttamente gli endpoint pubblici dello store:
niente account, niente chiave API, niente registrazione.

Trovare l'immagine giusta richiede pero' piu' di un tentativo, perche' Steam
serve gli asset in due modi diversi a seconda di quanto e' recente il gioco:

  - titoli vecchi   -> /steam/apps/<id>/header.jpg, URL prevedibile
  - titoli recenti  -> /store_item_assets/steam/apps/<id>/<hash>/header.jpg

L'hash non e' indovinabile e cambia per ogni singolo asset, quindi per i
titoli recenti va letto da una fonte che lo contenga gia': l'API appdetails
oppure, quando anche quella non risponde, il meta tag og:image della pagina
dello store, che finora e' risultata la fonte piu' affidabile in assoluto.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Iterator

import requests

TIMEOUT = 25
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Sici29-Hub"

STORE_SEARCH = "https://store.steampowered.com/api/storesearch/"
DETAILS = "https://store.steampowered.com/api/appdetails"
STORE_PAGE = "https://store.steampowered.com/app/{appid}/"
CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/{appid}/{asset}"

# Supera il controllo eta' delle pagine store dei giochi PEGI 18.
AGE_COOKIES = {
    "birthtime": "631152001",
    "lastagecheckage": "1-January-1990",
    "wants_mature_content": "1",
}

# Un asset mancante a volte non torna 404 ma un segnaposto minuscolo: sotto
# questa soglia non e' una copertina.
MIN_IMAGE_BYTES = 2000

# Punteggio minimo perche' un risultato di ricerca sia considerato lo stesso
# gioco. Serve a non agganciare titoli che si somigliano soltanto.
MIN_SCORE = 10

# requests.Session non e' garantita thread-safe e il catalogo lavora in
# parallelo: una sessione per thread.
_local = threading.local()

# Le schede non cambiano durante un aggiornamento e vengono chieste piu' volte.
_MISSING = object()
_DETAILS_CACHE: dict[int, dict | None] = {}
_CACHE_LOCK = threading.Lock()

# Lo store API e' rate limited: teniamo le chiamate a distanza di sicurezza.
_THROTTLE_LOCK = threading.Lock()
_last_call = 0.0
_MIN_INTERVAL = 0.32


def _session() -> requests.Session:
    sess = getattr(_local, "session", None)
    if sess is None:
        sess = requests.Session()
        sess.headers.update({"User-Agent": UA, "Accept-Language": "it,en"})
        sess.cookies.update(AGE_COOKIES)
        _local.session = sess
    return sess


def _throttle() -> None:
    global _last_call
    with _THROTTLE_LOCK:
        wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _key(name: str) -> str:
    """Nome ridotto all'osso per il confronto: via punteggiatura e maiuscole."""
    return re.sub(r"[^a-z0-9]+", " ", (name or "").casefold()).strip()


def clean_name(name: str) -> str:
    """Toglie dal nome le parti che nessuno store riconosce."""
    out = re.sub(r"\[[^\]]*\]|\([^)]*\)", " ", name or "")
    out = re.sub(r"[_\-–—:]+", " ", out)
    return re.sub(r"\s+", " ", out).strip()


# --- ricerca -----------------------------------------------------------------


def _score(candidate: str, query: str) -> float:
    """Quanto un risultato somiglia a cio' che cercavamo.

    Cercare "Star Citizen" su Steam restituisce "Citizen Sleeper 2", che non
    c'entra nulla: contano le parole in comune, e ogni parola di troppo nel
    titolo trovato abbassa il punteggio.
    """
    q, n = _key(query), _key(candidate)
    if not q or not n:
        return -1.0
    q_words = set(q.split())
    n_words = n.split()
    shared = sum(1 for w in n_words if w in q_words)

    score = 0.0
    if n == q:
        score += 120.0
    elif n.startswith(q) or q.startswith(n):
        score += 70.0
    score += (shared / max(len(q_words), 1)) * 40.0
    score -= max(0, len(n_words) - len(q_words)) * 6.0
    return score


def search_appid(name: str) -> int | None:
    """AppID Steam a partire dal nome del gioco, o None se non c'e' un match.

    Volutamente prudente: meglio nessuna copertina (e quindi quella generata)
    che la copertina di un altro gioco.
    """
    query = clean_name(name)
    if not query:
        return None

    _throttle()
    try:
        resp = _session().get(
            STORE_SEARCH,
            params={"term": query, "cc": "us", "l": "en"},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        items = resp.json().get("items") or []
    except (requests.RequestException, ValueError, AttributeError):
        return None

    best, best_score = None, MIN_SCORE
    for item in items:
        if item.get("type") and item["type"] != "app":
            continue
        appid = _as_int(item.get("id"))
        if appid is None:
            continue
        score = _score(str(item.get("name", "")), query)
        if score > best_score:
            best, best_score = appid, score
    return best


def app_details(appid: int) -> dict | None:
    with _CACHE_LOCK:
        cached = _DETAILS_CACHE.get(appid, _MISSING)
    if cached is not _MISSING:
        return cached

    _throttle()
    try:
        resp = _session().get(
            DETAILS, params={"appids": str(appid), "l": "italian"}, timeout=TIMEOUT
        )
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return None  # errore di rete: non lo mettiamo in cache, si ritenta

    entry = (payload or {}).get(str(appid))
    if entry is None and isinstance(payload, dict) and len(payload) == 1:
        # A volte Steam risponde intestando la scheda a un altro numero: per
        # ARK arriva sotto 4558490, per NTE sotto l'ID di un suo DLC. Conta
        # l'AppID scritto dentro la scheda, non l'etichetta.
        unica = next(iter(payload.values()))
        if isinstance(unica, dict) and str((unica.get("data") or {}).get("steam_appid")) == str(appid):
            entry = unica
    entry = entry if isinstance(entry, dict) else {}
    data = entry.get("data") if entry.get("success") else None
    result = data if isinstance(data, dict) else None
    with _CACHE_LOCK:
        _DETAILS_CACHE[appid] = result
    return result


def verify_appid(appid: int, name: str) -> bool | None:
    """Conferma che l'AppID corrisponda davvero al gioco.

    Serve contro gli AppID sbagliati scritti a mano nel hub.json: e' bastato
    un numero errato per far comparire la copertina di "King Krieg" al posto
    di quella di "Fatekeeper". Torna None quando la scheda non e' consultabile
    (capita con i titoli molto recenti): in quel caso si concede il beneficio
    del dubbio e si usa comunque l'AppID dichiarato.
    """
    details = app_details(appid)
    if not details:
        return None
    store_name = str(details.get("name", ""))
    if not store_name:
        return None
    return _score(store_name, name) >= 40


def store_page_image(appid: int) -> str | None:
    """Immagine grande letta dal meta og:image della pagina dello store.

    E' l'ultima risorsa ma anche la piu' solida: funziona pure sui giochi per
    cui appdetails risponde success=false, dove tutto il resto fallisce.
    """
    _throttle()
    try:
        resp = _session().get(STORE_PAGE.format(appid=appid), timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        match = re.search(
            r'<meta\s+property="og:image"\s+content="([^"]+)"', resp.text
        )
    except requests.RequestException:
        return None
    if not match:
        return None
    url = match.group(1).replace("&amp;", "&")
    return url if url.startswith("http") else None


# --- immagini ----------------------------------------------------------------


def cover_candidates(appid: int) -> Iterator[str]:
    """URL da provare, in ordine di preferenza.

    header.jpg e' nativamente 460x215, cioe' esattamente il formato delle card
    dell'hub: quando c'e' e' la scelta migliore perche' non va ritagliato. La
    verticale 600x900 sta in fondo perche' ritagliata in orizzontale rende
    male, ma meglio lei che niente.
    """
    yield CDN.format(appid=appid, asset="header.jpg")

    details = app_details(appid)
    if details:
        for field in ("header_image", "capsule_image", "capsule_imagev5"):
            url = details.get(field)
            if isinstance(url, str) and url.startswith("http"):
                yield url

    yield CDN.format(appid=appid, asset="capsule_616x353.jpg")

    page_image = store_page_image(appid)
    if page_image:
        yield page_image

    yield CDN.format(appid=appid, asset="library_hero.jpg")
    yield CDN.format(appid=appid, asset="library_600x900.jpg")


def download(url: str) -> bytes | None:
    try:
        resp = _session().get(url, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if resp.status_code != 200:
        return None
    if not resp.headers.get("Content-Type", "").startswith("image/"):
        return None
    if len(resp.content) < MIN_IMAGE_BYTES:
        return None  # segnaposto, non artwork
    return resp.content


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

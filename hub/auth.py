"""Accesso a GitHub.

Due metodi, in ordine di comodita' per chi usa l'hub:

1. **Un clic** (authorization code + PKCE). Il browser si apre gia' sulla
   pagina "Authorize" di GitHub, dove l'utente e' quasi sempre gia' collegato:
   preme il pulsante verde e torna qui autenticato. Niente da ricopiare.

2. **Codice da ricopiare** (device flow), come ripiego quando il primo non e'
   utilizzabile: manca il client secret, la porta locale e' bloccata, o il
   browser non torna indietro.

Perche' il primo puo' avere il secret dentro l'eseguibile. GitHub lo esige
anche dalle app native, perche' non distingue client pubblici da confidenziali;
nella sua guida alle buone pratiche scrive pero' che, per un'app pubblica che
non puo' comunque proteggerlo, e' preferibile l'authorization code con PKCE al
device flow. E' PKCE a reggere la sicurezza: il codice di autorizzazione vale
solo per chi conosce il code_verifier, che nasce e muore dentro la singola
sessione e non viaggia mai in chiaro. Un secret estratto dal binario, da solo,
non basta a farsi dare un token.

La password non passa mai dall'applicazione: si digita solo su github.com.

Il token viene cifrato con DPAPI di Windows, che lega la cifratura all'account
Windows: se qualcuno copia il file su un altro PC, non e' leggibile.
"""

from __future__ import annotations

import base64
import ctypes
import hashlib
import http.server
import json
import os
import re
import time
import urllib.parse
import webbrowser
from ctypes import wintypes

import requests

from . import __version__, config, paths

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"

# public_repo: aprire issue, mettere reazioni e stelle sui repo pubblici.
# user:follow: seguire l'autore. Volutamente il minimo: nessun accesso ai
# repo privati, nessuna scrittura di codice, nessun dato personale.
SCOPE = "public_repo user:follow"

TIMEOUT = 20
UA = f"Sici29-Hub/{__version__}"

TOKEN_FILE = "account.bin"
CREDS_FILE = "oauth.bin"


# --- cifratura con DPAPI -----------------------------------------------------


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _Blob:
    buf = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))


def _read(blob: _Blob) -> bytes:
    out = ctypes.string_at(blob.pbData, blob.cbData)
    ctypes.windll.kernel32.LocalFree(blob.pbData)
    return out


def _protect(data: bytes) -> bytes | None:
    try:
        out = _Blob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(_blob(data)), None, None, None, None, 0, ctypes.byref(out)
        )
        return _read(out) if ok else None
    except Exception:
        return None


def _unprotect(data: bytes) -> bytes | None:
    try:
        out = _Blob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(_blob(data)), None, None, None, None, 0, ctypes.byref(out)
        )
        return _read(out) if ok else None
    except Exception:
        return None


# --- token su disco ----------------------------------------------------------


def _token_path():
    return paths.data_dir() / TOKEN_FILE


def save_token(token: str, login: str = "") -> bool:
    payload = json.dumps({"token": token, "login": login}).encode("utf-8")
    blob = _protect(payload)
    if blob is None:
        return False
    try:
        _token_path().write_bytes(base64.b64encode(blob))
        return True
    except OSError:
        return False


def load_account() -> dict | None:
    path = _token_path()
    if not path.exists():
        return None
    try:
        blob = base64.b64decode(path.read_bytes())
    except (OSError, ValueError):
        return None
    raw = _unprotect(blob)
    if not raw:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("token") else None


def clear_token() -> None:
    try:
        _token_path().unlink(missing_ok=True)
    except OSError:
        pass


# --- credenziali dell'applicazione OAuth -------------------------------------
#
# Due provenienze possibili, in quest'ordine:
#
#   1. il file cifrato nella cartella dati, scritto dalla procedura guidata
#   2. i valori compilati in config.py, cioe' dentro l'eseguibile distribuito
#
# La prima serve all'autore per attivare l'accesso senza aprire un editor e
# senza ricompilare; la seconda e' come le credenziali arrivano a chi scarica
# l'hub, che quindi non deve registrare nulla.

# Formati noti: Client ID delle vecchie app OAuth (20 esadecimali), delle nuove
# ("Ov23li..."), delle GitHub App ("Iv1.<16 esadecimali>" o "Iv23li..."). Il
# secret e' 40 esadecimali. Servono solo a capire se l'autore ha invertito i
# due campi e a intercettare un incolla sbagliato: non sono un controllo di
# validita', quello lo fa GitHub.
_ID_RE = re.compile(r"^(?:[OI]v[0-9A-Za-z.]{6,60}|[0-9a-f]{20})$")
_SECRET_RE = re.compile(r"^[0-9a-f]{40}$")

# None = non ancora letto da disco. Evita una CryptUnprotectData per ogni
# richiesta a GitHub.
_creds_cache: tuple[str, str] | None = None


def _creds_path():
    return paths.data_dir() / CREDS_FILE


def _stored() -> tuple[str, str]:
    """Credenziali salvate dalla procedura guidata, ("", "") se non ci sono."""
    global _creds_cache
    if _creds_cache is None:
        _creds_cache = ("", "")
        path = _creds_path()
        if path.exists():
            try:
                raw = _unprotect(base64.b64decode(path.read_bytes()))
                dati = json.loads(raw.decode("utf-8")) if raw else {}
                if isinstance(dati, dict):
                    _creds_cache = (
                        str(dati.get("client_id") or ""),
                        str(dati.get("client_secret") or ""),
                    )
            except (OSError, ValueError, AttributeError):
                pass
    return _creds_cache


def stored_credentials() -> tuple[str, str]:
    """Le credenziali salvate dalla procedura guidata, ("", "") se non ci sono.

    GitHub mostra il client secret **una volta sola**: se non e' finito subito
    in config.py, la copia cifrata qui e' l'unica rimasta. Serve a rileggerla
    invece di dover rigenerare il secret.
    """
    return _stored()


def save_credentials(cid: str, secret: str) -> bool:
    """Salva le credenziali cifrate con DPAPI. Le ordina se sono invertite."""
    global _creds_cache
    coppia = sort_credentials(cid, secret)
    if coppia is None:
        return False
    payload = json.dumps(
        {"client_id": coppia[0], "client_secret": coppia[1]}
    ).encode("utf-8")
    blob = _protect(payload)
    if blob is None:
        return False
    try:
        _creds_path().write_bytes(base64.b64encode(blob))
    except OSError:
        return False
    _creds_cache = coppia
    return True


def forget_credentials() -> None:
    global _creds_cache
    try:
        _creds_path().unlink(missing_ok=True)
    except OSError:
        pass
    _creds_cache = None


def sort_credentials(a: str, b: str) -> tuple[str, str] | None:
    """(client_id, client_secret) rimessi nell'ordine giusto.

    Le due stringhe su GitHub stanno una sotto l'altra e si copiano con due
    pulsanti quasi identici: invertirle e' l'errore piu' probabile, e riesce
    naturale correggerlo al posto di chi incolla. None se una delle due manca.
    """
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return None
    if _SECRET_RE.match(a) and _ID_RE.match(b):
        return b, a
    return a, b


def credentials() -> tuple[str, str]:
    salvate = _stored()
    if salvate[0]:
        return salvate
    return config.OAUTH_CLIENT_ID.strip(), config.OAUTH_CLIENT_SECRET.strip()


def client_id() -> str:
    return credentials()[0]


def client_secret() -> str:
    return credentials()[1]


def credentials_source() -> str:
    """Da dove arrivano: "file" (procedura guidata), "app" (exe) o "" (niente)."""
    if _stored()[0]:
        return "file"
    if config.OAUTH_CLIENT_ID.strip():
        return "app"
    return ""


def probe_client_id(cid: str) -> tuple[bool, str]:
    """Verifica che il Client ID esista, senza disturbare l'utente.

    Si chiede a GitHub un codice per il device flow: e' l'unica richiesta che
    accetta il solo client_id e che quindi distingue un ID valido da uno
    sbagliato prima di aprire il browser. Se il device flow e' disattivato sul
    profilo dell'app, GitHub lo dice esplicitamente: e' comunque la prova che
    l'ID esiste. Nel dubbio (rete giu', risposta inattesa) si concede il
    beneficio: meglio provare l'accesso vero che bloccare l'autore.
    """
    cid = (cid or "").strip()
    if not cid:
        return False, "Manca il Client ID."
    try:
        resp = requests.post(
            DEVICE_CODE_URL,
            data={"client_id": cid, "scope": SCOPE},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=TIMEOUT,
        )
        stato = resp.status_code
        dati = resp.json() if resp.content else {}
    except (requests.RequestException, ValueError):
        return True, ""

    bocciato = "GitHub non riconosce questo Client ID: ricontrollalo."

    # Su un ID inesistente GitHub risponde 404 con {"error": "Not Found"}
    # (maiuscole comprese: verificato sul campo, non e' un dettaglio su cui
    # fidarsi della documentazione).
    if stato == 404:
        return False, bocciato
    if not isinstance(dati, dict):
        return True, ""
    if dati.get("device_code") or dati.get("error") == "device_flow_disabled":
        return True, ""
    if str(dati.get("error") or "").casefold().replace(" ", "_") in (
        "not_found",
        "invalid_client",
        "unauthorized_client",
    ):
        return False, bocciato
    return True, ""


# --- device flow -------------------------------------------------------------


class AuthError(Exception):
    pass


def configured() -> bool:
    """Senza Client ID l'accesso non e' proponibile all'utente."""
    return bool(client_id())


def one_click() -> bool:
    """True se e' disponibile l'accesso con un clic: serve anche il secret."""
    cid, secret = credentials()
    return bool(cid and secret)


def start() -> dict:
    """Chiede a GitHub il codice da mostrare all'utente."""
    if not configured():
        raise AuthError(
            "Accesso non configurato: manca l'ID dell'applicazione OAuth."
        )
    try:
        resp = requests.post(
            DEVICE_CODE_URL,
            data={"client_id": client_id(), "scope": SCOPE},
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise AuthError(f"GitHub non risponde: {exc}") from exc

    if "device_code" not in data:
        raise AuthError(data.get("error_description") or "Risposta inattesa da GitHub.")
    return data


def poll(device_code: str, interval: int = 5, expires_in: int = 900, stop=None) -> str:
    """Aspetta che l'utente autorizzi, poi restituisce il token.

    `stop` e' una funzione che, se torna True, interrompe l'attesa (serve per
    annullare dalla finestra senza lasciare un thread appeso).
    """
    deadline = time.monotonic() + max(60, expires_in)
    wait = max(5, interval)

    while time.monotonic() < deadline:
        if stop and stop():
            raise AuthError("Accesso annullato.")
        time.sleep(wait)
        try:
            resp = requests.post(
                TOKEN_URL,
                data={
                    "client_id": client_id(),
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
                headers={"Accept": "application/json", "User-Agent": UA},
                timeout=TIMEOUT,
            )
            data = resp.json()
        except (requests.RequestException, ValueError):
            continue

        if data.get("access_token"):
            return data["access_token"]

        error = data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            wait = int(data.get("interval") or wait) + 1
            continue
        if error == "expired_token":
            raise AuthError("Codice scaduto: riprova.")
        if error == "access_denied":
            raise AuthError("Accesso rifiutato su GitHub.")
        if error:
            raise AuthError(data.get("error_description") or error)

    raise AuthError("Tempo scaduto: nessuna autorizzazione ricevuta.")


def whoami(token: str) -> dict | None:
    try:
        resp = requests.get(
            USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": UA,
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except (requests.RequestException, ValueError):
        return None


# --- accesso con un clic: authorization code + PKCE --------------------------

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
CALLBACK_PATH = "/callback"

# Quanto si aspetta che l'utente autorizzi prima di rinunciare.
WEB_FLOW_TIMEOUT = 300


def _pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge). Solo S256: GitHub rifiuta "plain"."""
    verifier = base64.urlsafe_b64encode(os.urandom(64)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


_PAGINA = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><title>{titolo}</title><style>
  body {{ margin:0; min-height:100vh; display:grid; place-items:center;
         background:#0b1015; color:#e7eef6;
         font-family:"Segoe UI Variable Text","Segoe UI",system-ui,sans-serif; }}
  .box {{ text-align:center; padding:40px 48px; background:#141c25;
          border:1px solid #253140; border-radius:14px; max-width:420px; }}
  .segno {{ width:54px; height:54px; margin:0 auto 18px; border-radius:50%;
            display:grid; place-items:center; background:{sfondo};
            color:{inchiostro}; font-size:28px; font-weight:700; }}
  h1 {{ margin:0 0 8px; font-size:20px; font-weight:600; }}
  p {{ margin:0; color:#8a9aac; font-size:14px; line-height:1.6; }}
</style></head><body><div class="box">
  <div class="segno">{simbolo}</div><h1>{titolo}</h1><p>{testo}</p>
</div></body></html>"""


def _pagina(ok: bool, testo: str) -> bytes:
    return _PAGINA.format(
        titolo="Fatto" if ok else "Accesso non riuscito",
        simbolo="&#10003;" if ok else "!",
        sfondo="#ffb020" if ok else "#ff5c5c",
        inchiostro="#1a1204" if ok else "#2b0505",
        testo=testo,
    ).encode("utf-8")


class _Ricevitore(http.server.BaseHTTPRequestHandler):
    """Raccoglie il ritorno dal browser, una volta sola."""

    esito: dict = {}
    atteso_state = ""

    def do_GET(self):  # noqa: N802
        parti = urllib.parse.urlparse(self.path)
        if parti.path != CALLBACK_PATH:
            self.send_error(404)
            return

        query = urllib.parse.parse_qs(parti.query)
        state = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        errore = (query.get("error_description") or query.get("error") or [""])[0]

        if errore:
            _Ricevitore.esito = {"errore": errore}
            corpo = _pagina(False, "Puoi chiudere questa scheda e riprovare dall'hub.")
        elif not state or state != _Ricevitore.atteso_state:
            # Senza questo controllo un sito qualunque potrebbe far arrivare
            # qui un codice che non abbiamo chiesto noi.
            _Ricevitore.esito = {"errore": "Risposta non attesa (state non valido)."}
            corpo = _pagina(False, "La risposta non corrisponde alla richiesta dell'hub.")
        elif not code:
            _Ricevitore.esito = {"errore": "GitHub non ha restituito il codice."}
            corpo = _pagina(False, "Puoi chiudere questa scheda e riprovare.")
        else:
            _Ricevitore.esito = {"code": code}
            corpo = _pagina(True, "Puoi chiudere questa scheda: l'hub e' gia' collegato.")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def log_message(self, *args):
        """Niente righe di log sulla console."""


def web_flow(on_open=None, stop=None) -> str:
    """Accesso con un clic. Restituisce il token o solleva AuthError."""
    if not configured():
        raise AuthError("Accesso non configurato: mancano le credenziali OAuth.")
    if not client_secret():
        raise AuthError("Manca il client secret.")

    verifier, challenge = _pkce()
    state = base64.urlsafe_b64encode(os.urandom(24)).decode("ascii").rstrip("=")

    # Si ascolta solo su 127.0.0.1: nessun'altra macchina puo' raggiungerci.
    # Se la porta preferita e' occupata se ne prende una qualsiasi libera,
    # tanto GitHub non pretende che coincida con quella registrata.
    server = None
    for porta in (config.OAUTH_CALLBACK_PORT, 0):
        try:
            server = http.server.HTTPServer(("127.0.0.1", porta), _Ricevitore)
            break
        except OSError:
            continue
    if server is None:
        raise AuthError("Nessuna porta locale disponibile per il ritorno dal browser.")

    redirect = f"http://127.0.0.1:{server.server_address[1]}{CALLBACK_PATH}"

    _Ricevitore.esito = {}
    _Ricevitore.atteso_state = state
    server.timeout = 1

    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": client_id(),
            "redirect_uri": redirect,
            "scope": SCOPE,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )

    try:
        if on_open:
            on_open(url)
        webbrowser.open(url)

        scadenza = time.monotonic() + WEB_FLOW_TIMEOUT
        while not _Ricevitore.esito:
            if stop and stop():
                raise AuthError("Accesso annullato.")
            if time.monotonic() > scadenza:
                raise AuthError("Tempo scaduto: nessuna autorizzazione ricevuta.")
            server.handle_request()
    finally:
        try:
            server.server_close()
        except OSError:
            pass

    esito = _Ricevitore.esito
    _Ricevitore.esito = {}
    _Ricevitore.atteso_state = ""

    if esito.get("errore"):
        raise AuthError(esito["errore"])
    return _scambia_codice(esito["code"], redirect, verifier)


def _scambia_codice(code: str, redirect: str, verifier: str) -> str:
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id(),
                "client_secret": client_secret(),
                "code": code,
                "redirect_uri": redirect,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json", "User-Agent": UA},
            timeout=TIMEOUT,
        )
        dati = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise AuthError(f"Scambio del codice non riuscito: {exc}") from exc

    if dati.get("access_token"):
        return dati["access_token"]
    raise AuthError(
        dati.get("error_description") or "GitHub non ha restituito il token."
    )

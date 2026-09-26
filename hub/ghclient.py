"""Client GitHub con cache ETag.

Attenzione a cosa fa davvero l'ETag qui: risparmia dati trasferiti, NON
richieste. Misurato sul campo, una risposta `304` consuma il limite esattamente
come una `200`, al contrario di quanto dice la documentazione storica di
GitHub. Il vero risparmio sul limite di 60 chiamate/ora sta altrove: nella
cache su disco (che permette di mostrare qualcosa anche a quota esaurita),
nell'intervallo minimo fra due controlli e nella lettura di hub.json da
raw.githubusercontent, che sta fuori dall'API.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from typing import Any

import requests

from . import __version__, config, paths

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
UA = f"Sici29-Hub/{__version__} (+{config.PROFILE_URL})"

TIMEOUT = 20


class RateLimited(Exception):
    def __init__(self, reset_ts: int = 0):
        self.reset_ts = reset_ts
        super().__init__("Limite di richieste GitHub raggiunto")


class GitHubClient:
    def __init__(self, user: str = config.GITHUB_USER) -> None:
        self.user = user
        self.session = requests.Session()
        self.session.headers.update(
            {"User-Agent": UA, "Accept": "application/vnd.github+json"}
        )
        self.token = ""
        self._cache_path = paths.cache_dir() / "github.json"
        # Il catalogo costruisce i progetti su piu' thread e ognuno scrive
        # qui: senza lock un thread poteva inserire una voce mentre un altro
        # stava serializzando il dizionario, e json.dump falliva con
        # "dictionary changed size during iteration". L'eccezione faceva
        # sparire dalla griglia, a caso, la traduzione del thread perdente.
        self._cache_lock = threading.RLock()
        self._cache = self._load_cache()
        self.rate_remaining: int | None = None
        self.rate_reset: int = 0

        # Un token revocato - dall'utente su GitHub, o da GitHub stesso - fa
        # rispondere 401 a TUTTO, anche agli endpoint pubblici che senza
        # token funzionerebbero. Prima l'hub lo rimandava a ogni avvio e
        # mostrava l'errore finche' non si premeva "Riprova". Adesso ogni
        # risposta passa di qui: al primo 401 il token viene messo da parte,
        # e chi usa l'hub continua senza accorgersene.
        self.token_revocato = False
        self.session.hooks["response"].append(self._controlla_revoca)

    def _controlla_revoca(self, resp, *args, **kwargs):
        if resp.status_code == 401 and "Authorization" in resp.request.headers:
            self.token_revocato = True
            self.session.headers.pop("Authorization", None)
            self.token = ""
        return resp

    def authorize(self, token: str) -> None:
        """Usa il token dell'utente: alza il limite da 60 a 5.000 richieste/ora
        e abilita la scrittura (proposte e voti)."""
        self.token = token or ""
        if self.token:
            self.session.headers["Authorization"] = f"Bearer {self.token}"
        else:
            self.session.headers.pop("Authorization", None)

    # -- scrittura (richiede l'accesso) --------------------------------------

    def create_issue(self, repo: str, title: str, body: str, labels: list[str]) -> dict:
        """Apre una issue: e' cosi' che nasce una proposta di traduzione."""
        resp = self.session.post(
            f"{API}/repos/{self.user}/{repo}/issues",
            json={"title": title, "body": body, "labels": labels},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def add_reaction(self, repo: str, number: int, content: str = "+1") -> dict:
        """Mette una reazione su una issue: e' il voto."""
        resp = self.session.post(
            f"{API}/repos/{self.user}/{repo}/issues/{number}/reactions",
            json={"content": content},
            timeout=TIMEOUT,
        )
        # 200 significa che il voto c'era gia': non e' un errore.
        if resp.status_code not in (200, 201):
            resp.raise_for_status()
        return resp.json()

    def starred_repos(self) -> set[str]:
        """I repo gia' stellati dall'utente.

        Una richiesta sola per tutti: chiederlo repo per repo costerebbe una
        chiamata a testa.
        """
        if not self.token:
            return set()
        try:
            resp = self.session.get(
                f"{API}/user/starred?per_page=100", timeout=TIMEOUT
            )
            if resp.status_code != 200:
                return set()
            return {
                r.get("name", "")
                for r in resp.json()
                if isinstance(r, dict) and (r.get("owner") or {}).get("login") == self.user
            }
        except (requests.RequestException, ValueError):
            return set()

    def set_star(self, repo: str, attiva: bool) -> bool:
        metodo = self.session.put if attiva else self.session.delete
        resp = metodo(f"{API}/user/starred/{self.user}/{repo}", timeout=TIMEOUT)
        return resp.status_code in (204, 304)

    def is_following(self, chi: str) -> bool:
        if not self.token:
            return False
        try:
            resp = self.session.get(f"{API}/user/following/{chi}", timeout=TIMEOUT)
            return resp.status_code == 204
        except requests.RequestException:
            return False

    def set_following(self, chi: str, attiva: bool) -> bool:
        metodo = self.session.put if attiva else self.session.delete
        resp = metodo(f"{API}/user/following/{chi}", timeout=TIMEOUT)
        return resp.status_code in (204, 304)

    def remove_reaction(self, repo: str, number: int, reaction_id: int) -> bool:
        resp = self.session.delete(
            f"{API}/repos/{self.user}/{repo}/issues/{number}/reactions/{reaction_id}",
            timeout=TIMEOUT,
        )
        return resp.status_code in (204, 404)

    # -- cache ---------------------------------------------------------------

    def _load_cache(self) -> dict[str, Any]:
        try:
            with open(self._cache_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_cache(self) -> None:
        """Scrive la cache in modo atomico e sotto lock.

        Il lock protegge la serializzazione dalle scritture degli altri
        thread; il file temporaneo evita di lasciare un JSON troncato se
        l'hub viene chiuso a meta' scrittura.
        """
        with self._cache_lock:
            try:
                snapshot = json.dumps(self._cache)
            except (TypeError, ValueError):
                return
            try:
                fd, tmp = tempfile.mkstemp(
                    dir=str(self._cache_path.parent), suffix=".tmp"
                )
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    fh.write(snapshot)
                os.replace(tmp, self._cache_path)
            except OSError:
                try:
                    os.unlink(tmp)
                except (OSError, UnboundLocalError, NameError):
                    pass

    # -- richieste -----------------------------------------------------------

    def get_json(self, url: str) -> Any:
        with self._cache_lock:
            entry = self._cache.get(url) or {}
        headers = {}
        if entry.get("etag"):
            headers["If-None-Match"] = entry["etag"]

        try:
            resp = self.session.get(url, headers=headers, timeout=TIMEOUT)
        except requests.RequestException:
            if "data" in entry:
                return entry["data"]
            raise

        remaining = resp.headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                self.rate_remaining = int(remaining)
                self.rate_reset = int(resp.headers.get("X-RateLimit-Reset", 0))
            except ValueError:
                pass

        if resp.status_code == 401 and "Authorization" in resp.request.headers:
            # Il gancio ha gia' tolto il token: la seconda richiesta parte
            # senza, ed e' quella che conta.
            return self.get_json(url)

        if resp.status_code == 304 and "data" in entry:
            return entry["data"]

        if resp.status_code == 403 and self.rate_remaining == 0:
            if "data" in entry:
                return entry["data"]
            raise RateLimited(self.rate_reset)

        resp.raise_for_status()
        data = resp.json()
        with self._cache_lock:
            self._cache[url] = {
                "etag": resp.headers.get("ETag", ""),
                "data": data,
                "ts": int(time.time()),
            }
        self._save_cache()
        return data

    # -- endpoint usati dall'hub ---------------------------------------------

    def list_repos(self) -> list[dict]:
        url = f"{API}/users/{self.user}/repos?per_page=100&sort=updated"
        data = self.get_json(url)
        return data if isinstance(data, list) else []

    def list_releases(self, repo: str, limit: int = 30) -> list[dict]:
        url = f"{API}/repos/{self.user}/{repo}/releases?per_page={limit}"
        try:
            data = self.get_json(url)
        except requests.HTTPError:
            return []
        return data if isinstance(data, list) else []

    def list_issues(self, repo: str, labels: str = "", limit: int = 50) -> list[dict]:
        """Issue aperte, usate come bacheca delle proposte di traduzione.

        Le reazioni arrivano gia' nella risposta, quindi i voti non costano
        una richiesta in piu'.
        """
        url = (
            f"{API}/repos/{self.user}/{repo}/issues"
            f"?state=open&per_page={limit}&sort=created&direction=desc"
        )
        if labels:
            url += f"&labels={labels}"
        try:
            data = self.get_json(url)
        except requests.HTTPError:
            return []
        if not isinstance(data, list):
            return []
        # Le pull request compaiono fra le issue: non sono proposte.
        return [i for i in data if isinstance(i, dict) and "pull_request" not in i]

    def fetch_marker(self, repo: str, branch: str = "HEAD") -> dict | None:
        """Legge hub.json dal repo via raw.githubusercontent.

        Non passa dall'API, quindi non consuma rate limit: possiamo provarci
        su tutti i repo dell'account senza pensarci.
        """
        url = f"{RAW}/{self.user}/{repo}/{branch}/{config.MARKER_FILE}"
        try:
            # Senza Authorization: e' un file pubblico su un host diverso
            # dall'API, il token non c'entra nulla e non va spedito in giro.
            resp = self.session.get(
                url, timeout=TIMEOUT, headers={"Authorization": None}
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

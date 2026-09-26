"""Ponte fra l'interfaccia (HTML/JS) e il Python che fa il lavoro.

Ogni metodo pubblico di Api e' chiamabile dal JS come `pywebview.api.<nome>()`.
Le operazioni lunghe non bloccano mai la finestra: partono su un thread e
mandano eventi alla UI con `_emit`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import requests

from . import (
    __version__,
    auth,
    catalog,
    config,
    covers,
    installer,
    journal,
    links,
    notify,
    paths,
    scan,
    state,
)
from .ghclient import GitHubClient


def autore() -> bool:
    """True se chi sta usando l'hub e' chi lo pubblica, non chi lo scarica.

    La procedura di attivazione dell'accesso non ha senso per gli utenti: a
    loro le credenziali arrivano dentro l'eseguibile, e vedersi proporre di
    registrare un'applicazione su GitHub sarebbe solo confusione. Quindi resta
    nascosta, e si apre in tre modi, tutti fuori dalla portata di un utente
    normale:

      - l'hub gira dai sorgenti (`python -m hub`): li' c'e' solo l'autore;
      - lo si avvia con `--setup`;
      - dalle impostazioni, cinque clic sul numero di versione (lato JS).

    In piu', se le credenziali arrivano dal file cifrato, vuol dire che su
    questo PC la procedura e' gia' stata fatta: la sezione resta visibile.
    """
    if not getattr(sys, "frozen", False):
        return True
    return "--setup" in sys.argv


class Api:
    def __init__(self) -> None:
        self._window = None
        self._client = GitHubClient()
        # L'ultimo catalogo riuscito, se c'e': la finestra lo mostra subito,
        # e resta a disposizione se GitHub non risponde.
        self._catalog: dict = catalog.carica_ultimo() or {"projects": [], "error": ""}
        self._lock = threading.Lock()
        self._busy = False
        self._last_refresh = 0.0
        # Quando GitHub e' stato interrogato davvero l'ultima volta. Un
        # ridisegno locale non lo tocca: "ultimo controllo 2 minuti fa"
        # dopo un'installazione sarebbe una bugia.
        self._checked_at = self._catalog.get("checked_at") or ""
        self._tentativi = 0
        self._stop = threading.Event()
        # La finestra ha chiesto i suoi dati: da qui in poi puo' ricevere
        # eventi, per esempio "apri la scheda" dopo il clic su una notifica.
        self._pronto = threading.Event()
        self._account: dict | None = None
        self._login_stop = threading.Event()
        self._update_checked = False
        self._hub_update: dict | None = None
        self._cancelling: set[str] = set()
        # Traduzioni con un'operazione in corso: installare e ripristinare
        # lo stesso gioco nello stesso momento lascerebbe i file a meta'.
        self._occupati: set[str] = set()
        self._starred: set[str] = set()
        self._following = False
        self.log = journal.setup()

        # Se l'utente si era gia' collegato, il token torna dal disco cifrato.
        saved = auth.load_account()
        if saved:
            self._account = saved
            self._client.authorize(saved["token"])

    # -- comunicazione verso la UI -------------------------------------------

    def _emit(self, event: str, payload=None) -> None:
        if not self._window:
            return
        try:
            data = json.dumps({"event": event, "payload": payload}, ensure_ascii=False)
            self._window.evaluate_js(f"window.hubEvent({data})")
        except Exception:
            # La finestra puo' essere gia' chiusa: non e' un errore.
            pass

    def _status(self, text: str, kind: str = "info") -> None:
        self._emit("status", {"text": text, "kind": kind})

    # -- avvio ---------------------------------------------------------------

    def bootstrap(self) -> dict:
        """Dati immediati per disegnare la finestra, poi il resto arriva dopo."""
        local = state.load()
        self.refresh(silent=True)
        self._pronto.set()
        return {
            "version": __version__,
            "user": config.GITHUB_USER,
            "bmc_url": config.BMC_URL,
            "profile_url": config.PROFILE_URL,
            "suggest_url": links.suggest_translation(),
            "settings": local["settings"],
            "auth": self.auth_state(),
            "voted": sorted(local.get("voted", {}).keys()),
            # La griglia si disegna da qui, senza aspettare la rete; il
            # controllo vero e' gia' partito e la aggiornera' fra poco.
            "catalogo": self._pacchetto() if self._catalog.get("projects") else None,
        }

    # -- accesso a GitHub ----------------------------------------------------

    def auth_state(self) -> dict:
        """Com'e' messo l'accesso, per decidere cosa mostrare nella finestra."""
        return {
            "configured": auth.configured(),
            "one_click": auth.one_click(),
            "source": auth.credentials_source(),
            # Il Client ID non e' un segreto: viaggia in chiaro nell'URL di
            # autorizzazione. Serve alle impostazioni per dire *quale*
            # applicazione e' attiva. Il secret non esce mai da Python.
            "client_id": auth.client_id(),
            "autore": autore(),
            "logged_in": bool(self._account),
            "login": (self._account or {}).get("login", ""),
            "starred": sorted(self._starred),
            "following": self._following,
        }

    def _load_social(self) -> None:
        """Stelle gia' messe e stato del "segui".

        Due richieste in tutto, non una per repo, e solo da collegati: senza
        token queste informazioni non esistono nemmeno.
        """
        if not self._account:
            self._starred = set()
            self._following = False
            return
        try:
            self._starred = self._client.starred_repos()
            self._following = self._client.is_following(config.GITHUB_USER)
        except Exception:
            self.log.debug("stato social non recuperabile")

    def _sessione_scaduta(self) -> bool:
        """Se GitHub ha rifiutato il token, scollega l'utente e lo dice.

        Il client se ne accorge da solo al primo 401 e continua senza token;
        qui si mette in pari il resto dell'hub - file del token, pulsante di
        accesso, stelle - che altrimenti crederebbe di essere ancora collegato.
        """
        if not self._client.token_revocato:
            return False
        self._client.token_revocato = False
        if not self._account:
            return True
        auth.clear_token()
        self._account = None
        self._starred = set()
        self._following = False
        self.log.info("GitHub ha rifiutato il token salvato: scollegato")
        self._emit("auth", {"ok": True, "login": ""})
        self._status(
            "La sessione GitHub era scaduta e ti ho scollegato. "
            "Puoi ricollegarti quando vuoi.",
            "info",
        )
        return True

    def _non_riuscita(self, azione: str, exc: Exception | None = None) -> dict:
        """Un'azione verso GitHub e' fallita: il perche' in parole normali.

        Prima qui finiva il testo dell'eccezione ("Non riuscito: 401 Client
        Error: Unauthorized for url..."). A chi usa l'hub serve sapere solo
        se deve ricollegarsi o riprovare; il resto va nel registro.
        """
        if exc is not None:
            self.log.warning("%s non riuscita: %s", azione, exc)
        if self._sessione_scaduta():
            return {"ok": False, "error": "La sessione GitHub è scaduta: ricollegati e riprova."}
        if isinstance(exc, requests.ConnectionError) or isinstance(exc, requests.Timeout):
            return {"ok": False, "error": "Nessuna connessione a GitHub: riprova fra poco."}
        return {"ok": False, "error": "GitHub non ha accettato la richiesta: riprova fra poco."}

    def toggle_star(self, repo: str) -> dict:
        """Mette o toglie la stella a una traduzione."""
        if not self._account:
            return {"ok": False, "error": "Devi collegarti a GitHub per mettere una stella."}
        attiva = repo not in self._starred
        try:
            if not self._client.set_star(repo, attiva):
                return self._non_riuscita("stella")
        except Exception as exc:
            return self._non_riuscita("stella", exc)

        if attiva:
            self._starred.add(repo)
        else:
            self._starred.discard(repo)
        self.log.info("stella %s su %s", "messa" if attiva else "tolta", repo)
        self._status(
            "Grazie per la stella!" if attiva else "Stella tolta.",
            "ok" if attiva else "info",
        )
        return {"ok": True, "starred": attiva}

    def toggle_follow(self) -> dict:
        """Segue o smette di seguire l'autore delle traduzioni."""
        if not self._account:
            return {"ok": False, "error": "Devi collegarti a GitHub per seguire."}
        attiva = not self._following
        try:
            if not self._client.set_following(config.GITHUB_USER, attiva):
                return self._non_riuscita("segui")
        except Exception as exc:
            return self._non_riuscita("segui", exc)

        self._following = attiva
        self.log.info("follow %s", "attivato" if attiva else "tolto")
        self._status(
            f"Ora segui {config.GITHUB_USER}." if attiva else "Non lo segui piu'.",
            "ok" if attiva else "info",
        )
        return {"ok": True, "following": attiva}

    def _accesso_riuscito(self, token: str) -> None:
        profile = auth.whoami(token) or {}
        login = profile.get("login", "")
        auth.save_token(token, login)
        self._account = {"token": token, "login": login}
        self._client.authorize(token)
        self.log.info("collegato come %s", login or "?")
        self._emit("auth", {"ok": True, "login": login})
        self._status(f"Collegato come {login}.", "ok")
        # Da autenticati il limite passa a 5.000 richieste/ora.
        self.refresh(force=True, silent=True)

    def login_start(self) -> dict:
        """Avvia l'accesso.

        Con le credenziali complete si usa l'accesso con un clic: il browser
        si apre gia' sulla pagina "Authorize" e l'utente preme un pulsante.
        Senza client secret si ripiega sul device flow, che chiede di
        ricopiare un codice.
        """
        self._login_stop.clear()

        if auth.one_click():
            def un_clic() -> None:
                try:
                    token = auth.web_flow(stop=self._login_stop.is_set)
                except auth.AuthError as exc:
                    self.log.info("accesso non riuscito: %s", exc)
                    self._emit("auth", {"ok": False, "error": str(exc)})
                    return
                self._accesso_riuscito(token)

            threading.Thread(target=un_clic, daemon=True).start()
            return {"ok": True, "mode": "browser"}

        try:
            data = auth.start()
        except auth.AuthError as exc:
            return {"ok": False, "error": str(exc)}

        def wait() -> None:
            try:
                token = auth.poll(
                    data["device_code"],
                    interval=int(data.get("interval") or 5),
                    expires_in=int(data.get("expires_in") or 900),
                    stop=self._login_stop.is_set,
                )
            except auth.AuthError as exc:
                self._emit("auth", {"ok": False, "error": str(exc)})
                return
            self._accesso_riuscito(token)

        threading.Thread(target=wait, daemon=True).start()
        return {
            "ok": True,
            "mode": "code",
            "user_code": data.get("user_code", ""),
            "url": data.get("verification_uri", "https://github.com/login/device"),
        }

    def login_cancel(self) -> bool:
        self._login_stop.set()
        return True

    def logout(self) -> bool:
        auth.clear_token()
        self._account = None
        self._client.authorize("")
        self._emit("auth", {"ok": True, "login": ""})
        self._status("Disconnesso.", "info")
        return True

    # -- attivazione dell'accesso con un clic --------------------------------
    #
    # Perche' esiste questa parte. Per usare OAuth qualcuno deve registrare
    # un'applicazione su GitHub: non c'e' modo di aggirarlo, GitHub non
    # concede client anonimi. Ma a farlo e' l'autore dell'hub, una volta, e
    # chi scarica l'exe non lo fa mai, perche' si ritrova le credenziali
    # dentro il binario.
    #
    # Quella registrazione, pero', non deve costare l'apertura di un editor,
    # una ricompilazione e la fiducia che il copia-incolla sia andato bene:
    # da qui il modulo GitHub precompilato, i due campi che si correggono da
    # soli se invertiti, il controllo del Client ID prima di aprire il
    # browser e il salvataggio cifrato nella cartella dati.

    def oauth_setup(self) -> dict:
        """Tutto quello che serve alla procedura guidata."""
        cid = auth.client_id()
        return {
            "register_url": config.oauth_register_url(),
            "app_name": config.OAUTH_APP_NAME,
            "homepage": config.PROFILE_URL,
            "callback": config.OAUTH_CALLBACK_URL,
            "source": auth.credentials_source(),
            "one_click": auth.one_click(),
            # Il Client ID non e' un segreto (viaggia nell'URL di
            # autorizzazione): si puo' mostrare per far vedere qual e' attivo.
            # Il secret no, e non torna mai alla finestra.
            "client_id": cid,
        }

    def oauth_register(self) -> bool:
        """Apre su GitHub il modulo di registrazione gia' compilato."""
        self.log.info("apro il modulo di registrazione OAuth")
        webbrowser.open(config.oauth_register_url())
        return True

    def oauth_save(self, client_id: str, client_secret: str) -> dict:
        """Salva le credenziali e dice se si puo' provare l'accesso subito."""
        coppia = auth.sort_credentials(client_id, client_secret)
        if coppia is None:
            return {"ok": False, "error": "Servono entrambe le stringhe."}

        cid, secret = coppia
        valido, perche = auth.probe_client_id(cid)
        if not valido:
            return {"ok": False, "error": perche}

        if not auth.save_credentials(cid, secret):
            return {
                "ok": False,
                "error": "Non riesco a salvare le credenziali sul disco.",
            }

        self.log.info("credenziali OAuth salvate (client_id %s)", cid[:8] + "...")
        self._emit("auth", {"ok": True, "setup": True, "state": self.auth_state()})
        return {"ok": True, "one_click": auth.one_click()}

    def oauth_config_snippet(self) -> dict:
        """Le due righe per config.py, ricavate dalle credenziali salvate.

        GitHub il client secret lo mostra una volta sola. Senza questo, chi
        avesse chiuso la finestra senza copiarlo dovrebbe rigenerarlo.
        Se le credenziali arrivano dall'eseguibile non c'e' niente da dare:
        sono gia' in config.py.
        """
        cid, secret = auth.stored_credentials()
        if not (cid and secret):
            return {
                "ok": False,
                "error": "Nessuna credenziale salvata su questo PC.",
            }
        righe = (f'OAUTH_CLIENT_ID = "{cid}"\n'
                 f'OAUTH_CLIENT_SECRET = "{secret}"')
        return {"ok": True, "testo": righe}

    def oauth_forget(self) -> dict:
        """Dimentica le credenziali salvate qui; quelle dell'exe restano."""
        auth.forget_credentials()
        if self._account:
            self.logout()
        self.log.info("credenziali OAuth rimosse")
        self._emit("auth", {"ok": True, "setup": True, "state": self.auth_state()})
        self._status("Credenziali rimosse.", "info")
        return {"ok": True, "source": auth.credentials_source()}

    # -- proposte della comunita' --------------------------------------------

    def create_proposal(self, title: str, body: str) -> dict:
        """Apre una proposta di traduzione senza uscire dall'hub."""
        title = (title or "").strip()
        if not title:
            return {"ok": False, "error": "Serve il nome del gioco."}
        if not self._account:
            return {"ok": False, "error": "Devi collegarti a GitHub per proporre."}

        try:
            issue = self._client.create_issue(
                config.SUGGESTIONS_REPO,
                f"{config.PROPOSAL_PREFIX} {title}",
                (body or "").strip() or "_Nessun dettaglio._",
                [config.PROPOSAL_LABEL],
            )
        except Exception as exc:
            return self._non_riuscita("proposta", exc)

        self._status("Proposta inviata.", "ok")
        self.refresh(force=True, silent=True)
        return {"ok": True, "url": issue.get("html_url", "")}

    def toggle_vote(self, number: int) -> dict:
        """Aggiunge o toglie il voto (la reazione) su una proposta."""
        if not self._account:
            return {"ok": False, "error": "Devi collegarti a GitHub per votare."}

        local = state.load()
        voted = local.setdefault("voted", {})
        key = str(number)

        try:
            if key in voted:
                self._client.remove_reaction(
                    config.SUGGESTIONS_REPO, int(number), int(voted[key])
                )
                voted.pop(key, None)
                result = {"ok": True, "voted": False}
            else:
                reaction = self._client.add_reaction(
                    config.SUGGESTIONS_REPO, int(number)
                )
                voted[key] = reaction.get("id", 0)
                result = {"ok": True, "voted": True}
        except Exception as exc:
            return self._non_riuscita("voto", exc)

        state.save(local)
        self.refresh(force=True, silent=True)
        return result

    # -- catalogo ------------------------------------------------------------

    # Dopo quanto si riprova quando GitHub non risponde. All'accensione del PC
    # la rete arriva spesso qualche secondo dopo l'hub: il primo tentativo e'
    # ravvicinato per coprire quel caso, gli altri si allargano per non
    # insistere su una connessione che davvero non c'e'.
    ATTESE_RIPROVA = (15, 60, 300)

    def _riprova_da_solo(self) -> None:
        if self._tentativi >= len(self.ATTESE_RIPROVA):
            return
        attesa = self.ATTESE_RIPROVA[self._tentativi]
        self._tentativi += 1
        self.log.info("GitHub non raggiungibile: riprovo fra %d secondi", attesa)

        def dopo() -> None:
            if not self._stop.wait(attesa):
                self.refresh(force=True, silent=True)

        threading.Thread(target=dopo, daemon=True).start()

    def _pacchetto(self, errore: str = "") -> dict:
        """Quello che la finestra riceve per disegnare il catalogo."""
        progetti = self._catalog.get("projects") or []
        # La cartella scelta a mano cambia fuori dal catalogo: la si rilegge
        # qui, che e' il solo punto da cui passa tutto quello che la finestra
        # riceve.
        scelte = state.load().get("cartelle_scelte", {})
        for progetto in progetti:
            progetto["cartella_scelta"] = scelte.get(progetto.get("repo"), "")
        return {
            "projects": progetti,
            "summary": catalog.summary(progetti),
            "library": self._catalog.get("library", {}),
            "proposals": self._catalog.get("proposals", []),
            "error": errore or self._catalog.get("error", ""),
            "rate_remaining": self._catalog.get("rate_remaining"),
            "checked_at": self._checked_at,
            "hub_update": self._hub_update,
            "source": self._catalog.get("source", ""),
            "auth": self.auth_state(),
        }

    def ridisegna(self) -> None:
        """Rimanda alla finestra il catalogo che ha gia', con lo stato locale
        ricalcolato.

        Serve dopo un'installazione o una rimozione: cambia solo cosa c'e' sul
        disco, non cosa c'e' su GitHub. Chiedere un giro completo sarebbe
        inutile e per giunta verrebbe rimandato dal freno dei dieci minuti -
        ed e' cosi' che una traduzione appena installata continuava a mostrare
        "Installa" finche' non si riapriva l'hub.
        """
        progetti = self._catalog.get("projects") or []
        if not progetti:
            return
        catalog.ricalcola_stato(progetti)
        self._emit("catalog", self._pacchetto())

    def refresh(self, force: bool = False, silent: bool = False) -> bool:
        """Ricostruisce il catalogo su un thread separato.

        Senza `force` si risparmia: un controllo completo costa 6 delle 60
        richieste all'ora concesse da GitHub senza autenticazione, e gli ETag
        non aiutano perche' anche una risposta 304 pesa sul limite. Quindi non
        si ricontrolla se l'ultimo giro riuscito e' recente, e ci si ferma
        quando le richieste rimaste stanno per finire.
        """
        if not force and self._catalog.get("projects"):
            if time.time() - self._last_refresh < config.MIN_REFRESH_SECONDS:
                return False
            remaining = self._client.rate_remaining
            if remaining is not None and remaining < config.RATE_RESERVE:
                self._status(
                    "Controllo rimandato: richieste a GitHub quasi esaurite, "
                    "si azzerano entro un'ora.",
                    "warn",
                )
                return False

        with self._lock:
            if self._busy:
                return False
            self._busy = True

        def work() -> None:
            try:
                if not silent:
                    self._status("Controllo aggiornamenti su GitHub...", "loading")
                self._emit("loading", True)

                if force:
                    # Client nuovo per ripartire da zero con la cache, ma con
                    # lo stesso accesso: prima "Controlla" scollegava di fatto
                    # l'utente, che tornava a 60 richieste l'ora senza saperlo.
                    self._client = GitHubClient()
                    if self._account:
                        self._client.authorize(self._account.get("token", ""))

                primo_avvio = not state.load()["seen"]

                result = catalog.build(
                    self._client, check_update=not self._update_checked
                )
                self._sessione_scaduta()

                # GitHub non ha risposto per niente: la griglia resta com'era
                # e cambia solo l'avviso in cima. Prima veniva svuotata, con
                # un messaggio che parlava di "dati salvati" che non esistevano.
                if result.get("error") and not result["projects"] and self._catalog.get("projects"):
                    self.log.info("controllo non riuscito (%s): resta il catalogo precedente",
                                  result["error"])
                    self._emit("catalog", self._pacchetto(result["error"]))
                    if result["error"] == "rete":
                        self._riprova_da_solo()
                    return

                # Risposta parziale: chi non si e' riusciti a ricontrollare
                # resta com'era, invece di sparire dalla griglia.
                result = catalog.unisci_mancanti(result, self._catalog)

                # Al primissimo avvio ogni traduzione risulterebbe "nuova":
                # cinque badge arancioni che non dicono nulla. Si segna tutto
                # come gia' visto, cosi' d'ora in poi il badge segnala davvero
                # qualcosa che non c'era prima.
                if primo_avvio and result["projects"]:
                    local = state.load()
                    for progetto in result["projects"]:
                        ultima = progetto.get("latest") or {}
                        if ultima.get("tag"):
                            local["seen"][progetto["repo"]] = ultima["tag"]
                            progetto["novita"] = None
                    state.save(local)
                    self.log.info("primo avvio: %d traduzioni segnate come viste", len(result["projects"]))
                self._update_checked = True
                if not result.get("error"):
                    self._tentativi = 0
                self._catalog = result
                self._last_refresh = time.time()
                self._checked_at = datetime.now(timezone.utc).isoformat()
                if not result.get("error"):
                    catalog.salva_ultimo(result, self._checked_at)

                # Percorsi dei giochi trovati su disco: memorizzati per non
                # rifare la ricerca al prossimo avvio.
                nuovi = result.get("known_paths") or {}
                if nuovi:
                    local = state.load()
                    if local.get("game_paths") != nuovi:
                        local["game_paths"] = nuovi
                        state.save(local)
                        self.log.info("percorsi giochi memorizzati: %s", nuovi)
                self._hub_update = result.get("hub_update")
                self.log.info(
                    "catalogo da %s: %d traduzioni, richieste rimaste %s",
                    result.get("source") or "?",
                    len(result["projects"]),
                    result.get("rate_remaining"),
                )

                self._load_social()
                pacchetto = self._pacchetto()
                summary = pacchetto["summary"]
                self._emit("catalog", pacchetto)

                if result.get("error") == "rate_limit":
                    self._status(
                        "GitHub chiede una pausa: riprovo da solo fra qualche minuto.",
                        "warn",
                    )
                elif result.get("error"):
                    # Niente messaggio a comparsa: c'e' gia' l'avviso fisso in
                    # pagina, e intanto si riprova da soli.
                    self._riprova_da_solo()
                elif summary["updates"]:
                    self._status(
                        f"{summary['updates']} traduzioni da aggiornare.", "update"
                    )
                elif not silent:
                    self._status("Tutto aggiornato.", "ok")
                if not result.get("error"):
                    self._notifica(result["projects"])
            except Exception as exc:
                self.log.exception("aggiornamento catalogo fallito")
                self._emit("error", {"message": str(exc), "trace": traceback.format_exc()})
            finally:
                self._emit("loading", False)
                with self._lock:
                    self._busy = False

        threading.Thread(target=work, daemon=True).start()
        return True

    def start_auto_refresh(self) -> None:
        """Ricontrolla da solo a intervalli regolari, finche' l'hub e' aperto."""

        def loop() -> None:
            while not self._stop.wait(config.AUTO_REFRESH_MINUTES * 60):
                if state.load()["settings"].get("auto_refresh", True):
                    self.refresh(silent=True)

        threading.Thread(target=loop, daemon=True).start()

    def shutdown(self) -> None:
        self._stop.set()

    # -- notifiche di Windows ------------------------------------------------

    @staticmethod
    def _copertina(repo: str) -> Path | None:
        percorso = covers.percorso(repo)
        return percorso if percorso.exists() else None

    def _notifica(self, progetti: list[dict]) -> None:
        """Annuncia con una notifica di Windows solo cio' che non e' gia' stato detto."""
        try:
            local = state.load()
            if not local["settings"].get("notify", True):
                return
            registro = local["notifiche"]
            notifiche, inviate = notify.da_notificare(
                progetti, self._hub_update, registro.get("inviate", {}), copertina=self._copertina
            )
            if not notifiche and inviate == registro.get("inviate"):
                return
            ora = time.time()
            gettoni = dict(registro.get("gettoni", {}))
            for n in notifiche:
                for gettone, repo in n.gettoni.items():
                    gettoni[gettone] = {"repo": repo, "ts": ora}
            registro["inviate"] = inviate
            registro["gettoni"] = notify.pota_gettoni(gettoni, ora)
            # Prima si salva, poi si mostra: se l'hub si chiude a meta', il
            # pulsante "Aggiorna" deve trovare il suo gettone.
            state.save(local)
            for n in notifiche:
                notify.mostra(n)
                self.log.info("notifica: %s", n.titolo)
        except Exception:
            self.log.exception("notifica non riuscita")

    def gestisci_link(self, link: str) -> None:
        """Un clic su una notifica.

        Apre la scheda del gioco. Se il pulsante era "Aggiorna", e il suo
        gettone e' uno di quelli messi dall'hub, fa anche partire
        l'aggiornamento: un link giocainitaliano: scritto da altri apre al
        massimo una scheda.
        """
        richiesta = notify.leggi_link(link)
        self.log.info("link dalla notifica: %s", richiesta)
        if not richiesta or richiesta["azione"] == "apri":
            return
        repo = richiesta["repo"]
        self._emit("apri", {"repo": repo})
        if richiesta["azione"] != "aggiorna":
            return

        local = state.load()
        gettoni = local["notifiche"].get("gettoni", {})
        valido = notify.usa_gettone(gettoni, richiesta.get("gettone", ""), repo)
        local["notifiche"]["gettoni"] = gettoni
        state.save(local)
        progetto = self._project(repo)
        if valido and progetto and progetto.get("status") == catalog.STATUS_UPDATE:
            self.install(repo)
        elif not valido:
            self.log.info("aggiornamento di %s senza gettone valido: apro solo la scheda", repo)

    def ascolta_notifiche(self, link_iniziale: str | None = None) -> None:
        """Raccoglie i clic sulle notifiche.

        Quello che ha fatto partire l'hub, e quelli arrivati mentre era gia'
        aperto: in quel caso il secondo avvio lascia il link in un file e si
        chiude (vedi notify.lascia_richiesta).
        """

        def ciclo() -> None:
            if link_iniziale:
                # Prima la finestra deve disegnare la griglia, o non c'e'
                # nessuna scheda da aprire.
                self._pronto.wait(60)
                time.sleep(1.0)
                self.gestisci_link(link_iniziale)
            while not self._stop.wait(1.0):
                link = notify.prendi_richiesta()
                if link:
                    self.gestisci_link(link)

        threading.Thread(target=ciclo, daemon=True).start()

    def prova_notifica(self) -> bool:
        """Il pulsante "Prova" delle impostazioni."""
        notify.mostra(notify.prova(self._catalog.get("projects") or [], copertina=self._copertina))
        return True

    def _project(self, repo: str) -> dict | None:
        for p in self._catalog.get("projects", []):
            if p["repo"] == repo:
                return p
        return None

    # -- installazione -------------------------------------------------------

    def install(self, repo: str) -> bool:
        project = self._project(repo)
        if not project:
            return False
        latest = project.get("latest") or {}
        asset = latest.get("download")
        if not asset or not asset.get("url"):
            self._status("Questa release non ha un file da scaricare.", "warn")
            return False

        if repo in self._occupati:
            self._status("Su questa traduzione c'è già un'operazione in corso.", "info")
            return False
        self._occupati.add(repo)
        self._cancelling.discard(repo)

        def work() -> None:
            inizio = time.monotonic()
            try:
                self._emit("install", {"repo": repo, "phase": "download", "percent": 0})

                def progress(info: dict) -> None:
                    trascorso = max(time.monotonic() - inizio, 0.001)
                    velocita = info["done"] / trascorso
                    mancante = max(info["total"] - info["done"], 0)
                    self._emit(
                        "install",
                        {
                            "repo": repo,
                            "phase": "download",
                            "percent": info["percent"],
                            "done": info["done"],
                            "total": info["total"],
                            "speed": velocita,
                            "eta": (mancante / velocita) if velocita > 0 else 0,
                        },
                    )

                path = self._installer_di(project, progress)

                # L'installer gira senza finestra: quello che scrive arriva
                # qui riga per riga e la finestra dell'hub lo mostra al posto
                # della console nera.
                self._emit("install", {"repo": repo, "phase": "run", "percent": 100})
                riassunto = self._esegui_installer(project, "install", path)

                if riassunto["ok"]:
                    local = state.load()
                    local["installed"][repo] = {
                        "tag": latest.get("tag", ""),
                        "installed_at": datetime.now(timezone.utc).isoformat(),
                        "asset": asset["name"],
                    }
                    local["seen"][repo] = latest.get("tag", "")
                    state.save(local)
                    self.log.info("%s installata (%s)", repo, latest.get("tag", ""))
                    self._status(
                        f"{project['title']}: {riassunto['messaggio']}",
                        "warn" if riassunto["parziale"] else "ok",
                    )
                    self._emit("install", {"repo": repo, "phase": "done", "esito": riassunto})
                    # Prima la finestra, che deve cambiare subito; il giro su
                    # GitHub e' un di piu' e puo' benissimo essere rimandato.
                    self.ridisegna()
                    self.refresh(silent=True)
                else:
                    self._status(riassunto["messaggio"], "error")
                    self._emit("install", {"repo": repo, "phase": "error", "esito": riassunto})
            except installer.Cancelled:
                self.log.info("download di %s annullato", repo)
                self._status("Scaricamento annullato.", "info")
                self._emit("install", {"repo": repo, "phase": "cancelled"})
            except installer.DownloadError as exc:
                # Il messaggio e' per l'utente; la causa vera va nel registro.
                self.log.warning(
                    "download di %s non riuscito: %r", repo, exc.__cause__ or exc
                )
                self._status(str(exc), "error")
                self._emit("install", {"repo": repo, "phase": "error"})
            except Exception:
                self.log.exception("installazione di %s fallita", repo)
                self._status(
                    "L’installazione non è riuscita. Riprova; se succede ancora, "
                    "segnalalo dai dettagli della traduzione.",
                    "error",
                )
                self._emit("install", {"repo": repo, "phase": "error"})
            finally:
                self._cancelling.discard(repo)
                self._occupati.discard(repo)

        threading.Thread(target=work, daemon=True).start()
        return True

    # -- l'installer guidato dall'hub ----------------------------------------

    def _installer_di(self, project: dict, on_progress=None) -> Path:
        """L'installer dell'ultima versione: quello gia' scaricato se e' lui."""
        latest = project.get("latest") or {}
        asset = latest.get("download") or {}
        if not asset.get("url"):
            raise installer.DownloadError("Questa versione non ha un file da scaricare.")
        tag = latest.get("tag", "")
        pronto = installer.gia_scaricato(asset["name"], tag, asset.get("size") or 0)
        if pronto:
            return pronto
        percorso = installer.download(
            asset["url"],
            asset["name"],
            on_progress,
            should_stop=lambda: project["repo"] in self._cancelling,
            tag=tag,
        )
        self.log.info("scaricato %s per %s", asset["name"], project["repo"])
        return percorso

    def _argomenti(self, project: dict, azione: str) -> list[str] | None:
        """Gli argomenti per quell'azione, cartella scelta a mano compresa."""
        profilo = project.get("installer") or config.installer_profilo(project["repo"])
        argomenti = profilo.get(azione)
        if not argomenti:
            return None
        argomenti = list(argomenti)
        # La cartella si passa solo se l'ha scelta l'utente: altrimenti ogni
        # installer la trova da se', e conosce il suo gioco meglio dell'hub.
        scelta = state.load().get("cartelle_scelte", {}).get(project["repo"])
        if scelta and azione in ("install", "restore", "check"):
            argomenti += ["--game-dir", scelta]
        return argomenti

    def _esegui_installer(self, project: dict, azione: str, percorso: Path) -> dict:
        repo = project["repo"]
        argomenti = self._argomenti(project, azione) or []
        self.log.info("installer di %s: %s %s", repo, percorso.name, " ".join(argomenti))

        def riga(testo: str) -> None:
            self._emit("installer", {"repo": repo, "azione": azione, "riga": testo})

        esito = installer.esegui(percorso, argomenti, on_riga=riga)
        # Tutto quello che l'installer ha scritto finisce nel registro: e' la
        # prima cosa da leggere quando qualcuno segnala un problema.
        for testo in esito["righe"]:
            self.log.info("  | %s", testo)
        riassunto = installer.riassumi(esito)
        self.log.info(
            "installer di %s (%s): codice %s, %s",
            repo, azione, esito["codice"], riassunto["messaggio"],
        )
        return riassunto

    def azione_installer(self, repo: str, azione: str) -> bool:
        """Le voci del menu dell'installer, eseguite dentro l'hub.

        check: controlla la traduzione (o l'integrita' dei file, a seconda
        dell'installer); restore: rimette i file originali del gioco; backup:
        apre la cartella dei backup; completo: apre l'installer nella sua
        finestra, col suo menu, per tutto quello che qui non c'e'.
        """
        project = self._project(repo)
        if not project or azione not in ("check", "restore", "backup", "completo"):
            return False
        if azione != "completo" and not self._argomenti(project, azione):
            self._status("Questo installer non ha questa funzione.", "info")
            return False
        if repo in self._occupati:
            self._status("Su questa traduzione c'è già un'operazione in corso.", "info")
            return False
        self._occupati.add(repo)

        def work() -> None:
            try:
                self._emit("installer", {"repo": repo, "azione": azione, "fase": "inizio"})
                percorso = self._installer_di(project)

                if azione == "completo":
                    # Nella sua finestra: da li' l'utente puo' fare qualunque
                    # cosa, e l'hub non puo' sapere cosa. Lo stato installato
                    # resta com'era.
                    installer.run(percorso)
                    self._emit("installer", {"repo": repo, "azione": azione, "fase": "fine",
                                             "esito": {"ok": True, "messaggio": ""}})
                    return

                riassunto = self._esegui_installer(project, azione, percorso)
                if azione == "restore" and riassunto["ok"]:
                    local = state.load()
                    local["installed"].pop(repo, None)
                    state.save(local)
                    self._status(f"{project['title']}: file originali ripristinati.", "ok")
                    self.ridisegna()
                elif not riassunto["ok"]:
                    self._status(riassunto["messaggio"], "error")
                self._emit("installer", {"repo": repo, "azione": azione, "fase": "fine",
                                         "esito": riassunto})
            except installer.DownloadError as exc:
                self.log.warning("%s di %s: %r", azione, repo, exc.__cause__ or exc)
                self._status(str(exc), "error")
                self._emit("installer", {"repo": repo, "azione": azione, "fase": "fine",
                                         "esito": {"ok": False, "messaggio": str(exc)}})
            except Exception:
                self.log.exception("%s di %s fallito", azione, repo)
                messaggio = "Qualcosa è andato storto. Riprova; se succede ancora, segnalalo."
                self._status(messaggio, "error")
                self._emit("installer", {"repo": repo, "azione": azione, "fase": "fine",
                                         "esito": {"ok": False, "messaggio": messaggio}})
            finally:
                self._occupati.discard(repo)

        threading.Thread(target=work, daemon=True).start()
        return True

    def scegli_cartella_gioco(self, repo: str) -> dict:
        """Per quando l'installer non trova il gioco da solo."""
        if not self._window or not self._project(repo):
            return {"ok": False}
        try:
            import webview

            scelta = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        except Exception:
            return {"ok": False}
        if not scelta:
            return {"ok": False}
        cartella = str(scelta[0])
        local = state.load()
        local["cartelle_scelte"][repo] = cartella
        state.save(local)
        self.log.info("cartella scelta a mano per %s: %s", repo, cartella)
        self._status("Cartella del gioco salvata: la userò da ora in poi.", "ok")
        self.ridisegna()
        return {"ok": True, "cartella": cartella}

    def dimentica_cartella_gioco(self, repo: str) -> bool:
        local = state.load()
        if local["cartelle_scelte"].pop(repo, None) is None:
            return False
        state.save(local)
        self._status("Torno a cercare il gioco da solo.", "info")
        self.ridisegna()
        return True

    def avvia_gioco(self, repo: str) -> dict:
        """Fa partire il gioco dal posto giusto.

        Da Steam per i giochi Steam - overlay, cloud e aggiornamenti restano
        cosa sua - e dal launcher RSI per Star Citizen, che chiede l'accesso
        all'account prima di partire.
        """
        project = self._project(repo) or {}
        avvio = project.get("avvio") or ""
        try:
            if avvio.startswith("steam:"):
                os.startfile(f"steam://rungameid/{avvio.split(':', 1)[1]}")
            elif avvio == "rsi":
                exe = scan.launcher_rsi(project.get("game_path"))
                if not exe:
                    return {"ok": False, "error": "Non trovo il launcher RSI."}
                subprocess.Popen([str(exe)], cwd=str(exe.parent))
            else:
                return {"ok": False, "error": "Questo gioco non si può avviare dall’hub."}
        except OSError as exc:
            self.log.warning("avvio di %s non riuscito: %s", repo, exc)
            return {"ok": False, "error": "Non sono riuscito ad avviare il gioco."}
        self.log.info("avvio %s (%s)", repo, avvio)
        self._status(f"Avvio {project.get('title', '')}…", "info")
        return {"ok": True}

    def cancel_install(self, repo: str) -> bool:
        """Interrompe un download in corso."""
        self._cancelling.add(repo)
        return True

    def forget_install(self, repo: str) -> bool:
        """Dimentica la versione installata, senza toccare i file del gioco."""
        local = state.load()
        if local["installed"].pop(repo, None) is not None:
            state.save(local)
            self.ridisegna()
            return True
        return False

    # -- copertine -----------------------------------------------------------

    def pick_cover(self, repo: str) -> bool:
        """Scelta manuale della copertina, per i giochi fuori da Steam."""
        if not self._window:
            return False
        try:
            import webview

            result = self._window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Immagini (*.jpg;*.jpeg;*.png;*.webp;*.bmp)",),
            )
        except Exception:
            return False
        if not result:
            return False

        local = state.load()
        local["custom_covers"][repo] = str(result[0])
        state.save(local)
        self._status("Copertina aggiornata.", "ok")
        self.refresh(silent=True)
        return True

    def reset_cover(self, repo: str) -> bool:
        local = state.load()
        local["custom_covers"].pop(repo, None)
        state.save(local)
        index = covers.load_index()
        index.pop(repo, None)
        covers.save_index(index)
        self.refresh(silent=True)
        return True

    # -- stato e impostazioni ------------------------------------------------

    def mark_seen(self, repo: str | None = None) -> bool:
        """Azzera i badge NOVITA', per una traduzione o per tutte."""
        local = state.load()
        for project in self._catalog.get("projects", []):
            if repo and project["repo"] != repo:
                continue
            latest = project.get("latest") or {}
            if latest.get("tag"):
                local["seen"][project["repo"]] = latest["tag"]
        state.save(local)
        self.refresh(silent=True)
        return True

    def set_setting(self, key: str, value) -> bool:
        local = state.load()
        local["settings"][key] = value
        state.save(local)
        return True

    def hide_repo(self, repo: str) -> bool:
        local = state.load()
        hidden = set(local["settings"].get("hidden_repos", []))
        hidden.add(repo)
        local["settings"]["hidden_repos"] = sorted(hidden)
        state.save(local)
        self.refresh(silent=True)
        return True

    # -- aggiornamento dell'hub stesso ---------------------------------------

    def download_hub_update(self) -> bool:
        """Scarica la nuova versione e la mostra in Esplora risorse.

        Non si sostituisce l'eseguibile da soli mentre e' in esecuzione: e'
        proprio il caso in cui un errore lascerebbe l'utente senza hub.
        """
        update = self._hub_update or {}
        asset = update.get("asset")
        if not asset or not asset.get("url"):
            # Nessun eseguibile allegato: si apre la pagina della release.
            if update.get("url"):
                webbrowser.open(update["url"])
                return True
            return False

        def work() -> None:
            try:
                self._emit("hubupdate", {"phase": "download", "percent": 0})

                def progress(info: dict) -> None:
                    self._emit(
                        "hubupdate", {"phase": "download", "percent": info["percent"]}
                    )

                path = installer.download(asset["url"], asset["name"], progress)
                self.log.info("nuova versione scaricata in %s", path)
                installer.reveal(path)
                self._emit("hubupdate", {"phase": "done", "path": str(path)})
                self._status(
                    f"Scaricata la versione {update.get('version', '')}: "
                    "chiudi l'hub e sostituisci il file.",
                    "ok",
                )
            except Exception:
                self.log.exception("scaricamento aggiornamento fallito")
                self._status("Non sono riuscito a scaricare la nuova versione: riprova fra poco.", "error")
                self._emit("hubupdate", {"phase": "error"})

        threading.Thread(target=work, daemon=True).start()
        return True

    # -- collegamenti e cartelle ---------------------------------------------

    def open_external(self, url: str) -> bool:
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            return False
        webbrowser.open(url)
        return True

    def open_game_folder(self, repo: str) -> bool:
        project = self._project(repo)
        if not project or not project.get("game_path"):
            return False
        installer.reveal(project["game_path"])
        return True

    def clear_cover_cache(self) -> bool:
        """Svuota le copertine: utile quando una e' sbagliata o vecchia."""
        tolte = covers.clear_cache()
        self.log.info("cache copertine svuotata (%d file)", tolte)
        self._status(
            f"{tolte} copertine rimosse, le riscarico." if tolte else "Cache gia' vuota.",
            "ok",
        )
        self.refresh(force=True, silent=True)
        return True

    def hidden_repos(self) -> list[str]:
        return list(state.load()["settings"].get("hidden_repos", []))

    def unhide_repo(self, repo: str) -> bool:
        local = state.load()
        nascosti = [r for r in local["settings"].get("hidden_repos", []) if r != repo]
        local["settings"]["hidden_repos"] = nascosti
        state.save(local)
        self.refresh(force=True, silent=True)
        return True

    def open_data_folder(self) -> bool:
        installer.reveal(paths.data_dir())
        return True

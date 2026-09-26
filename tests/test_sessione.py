"""Un token revocato non deve rompere l'avvio.

Il caso reale: GitHub aveva revocato il token salvato. L'hub lo rimandava a
ogni avvio, riceveva 401 anche sugli endpoint pubblici - che senza token
funzionano benissimo - e mostrava "401 Client Error: Unauthorized for url"
finche' non si premeva Riprova. Il quale funzionava solo per caso, perche'
ricreava il client dimenticandosi del token.

Qui GitHub e' simulato a livello di trasporto, sotto a requests: cosi' passano
anche i ganci sulle risposte, che sono proprio il meccanismo da provare.
"""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from hub import api, catalog, ghclient


class FintoGitHub(requests.adapters.BaseAdapter):
    """Risponde come GitHub: 401 a un token sbagliato, dati a tutto il resto."""

    def __init__(self, token_valido: str = ""):
        super().__init__()
        self.token_valido = token_valido
        self.autorizzazioni = []

    def send(self, request, **kwargs):
        chi = request.headers.get("Authorization", "")
        self.autorizzazioni.append(chi)

        risposta = requests.Response()
        risposta.request = request
        risposta.url = request.url
        risposta.headers["Content-Type"] = "application/json"
        if chi and chi != f"Bearer {self.token_valido}":
            risposta.status_code = 401
            risposta._content = b'{"message": "Bad credentials"}'
        else:
            risposta.status_code = 200
            risposta._content = b'[{"name": "Aniimo-Italian-Translation"}]'
        return risposta

    def close(self):
        pass


class ClientConTokenRevocato(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cartella = Path(self.tmp.name)
        patch = mock.patch.object(ghclient.paths, "cache_dir", lambda: cartella)
        patch.start()
        self.addCleanup(patch.stop)

        self.github = FintoGitHub(token_valido="buono")
        self.client = ghclient.GitHubClient()
        self.client.session.mount("https://", self.github)

    def test_con_token_revocato_i_dati_arrivano_lo_stesso(self):
        self.client.authorize("revocato")
        dati = self.client.get_json("https://api.github.com/users/Sici29/repos")
        self.assertEqual(dati[0]["name"], "Aniimo-Italian-Translation")

    def test_la_seconda_richiesta_parte_senza_token(self):
        self.client.authorize("revocato")
        self.client.get_json("https://api.github.com/users/Sici29/repos")
        self.assertEqual(self.github.autorizzazioni, ["Bearer revocato", ""])

    def test_il_token_viene_messo_da_parte_una_volta_per_tutte(self):
        # Dopo il primo 401 il token non deve piu' partire: altrimenti ogni
        # richiesta costerebbe un 401 e un secondo tentativo.
        self.client.authorize("revocato")
        self.client.get_json("https://api.github.com/users/Sici29/repos")
        self.client.get_json("https://api.github.com/repos/Sici29/X/releases")
        self.assertEqual(self.github.autorizzazioni[-1], "")
        self.assertEqual(self.client.token, "")
        self.assertTrue(self.client.token_revocato)

    def test_un_token_buono_resta_dov_e(self):
        self.client.authorize("buono")
        self.client.get_json("https://api.github.com/users/Sici29/repos")
        self.assertEqual(self.github.autorizzazioni, ["Bearer buono"])
        self.assertFalse(self.client.token_revocato)

    def test_senza_token_un_401_non_fa_ripartire_niente(self):
        # Niente token, niente da togliere: il 401 va trattato come errore
        # vero, senza ripetere la richiesta all'infinito.
        github = FintoGitHub()
        github.send = mock.Mock(side_effect=self._sempre_401)
        self.client.session.mount("https://", github)
        with self.assertRaises(requests.HTTPError):
            self.client.get_json("https://api.github.com/users/Sici29/repos")
        self.assertEqual(github.send.call_count, 1)

    @staticmethod
    def _sempre_401(request, **kwargs):
        risposta = requests.Response()
        risposta.request = request
        risposta.url = request.url
        risposta.status_code = 401
        risposta._content = b"{}"
        return risposta


class L_HubSiScollegaDaSolo(unittest.TestCase):
    """Il lato applicazione: il token revocato va dimenticato, una volta."""

    def _api(self, collegato=True):
        finta = api.Api.__new__(api.Api)
        finta._client = mock.Mock(token_revocato=True)
        finta._account = {"token": "revocato", "login": "Sici29"} if collegato else None
        finta._starred = {"Aniimo-Italian-Translation"}
        finta._following = True
        finta.log = mock.Mock()
        finta._emit = mock.Mock()
        finta._status = mock.Mock()
        return finta

    def test_scollega_cancella_il_token_e_avvisa(self):
        finta = self._api()
        with mock.patch.object(api.auth, "clear_token") as cancella:
            self.assertTrue(finta._sessione_scaduta())
        cancella.assert_called_once()
        self.assertIsNone(finta._account)
        self.assertEqual(finta._starred, set())
        self.assertFalse(finta._following)
        finta._emit.assert_called_once_with("auth", {"ok": True, "login": ""})
        # Un messaggio solo, informativo: non e' un errore di chi usa l'hub.
        testo, tipo = finta._status.call_args.args
        self.assertEqual(tipo, "info")
        self.assertIn("ricollegarti", testo)

    def test_la_seconda_volta_non_ripete_niente(self):
        finta = self._api()
        with mock.patch.object(api.auth, "clear_token"):
            finta._sessione_scaduta()
            finta._sessione_scaduta()
        self.assertEqual(finta._status.call_count, 1)

    def test_con_token_valido_non_fa_niente(self):
        finta = self._api()
        finta._client.token_revocato = False
        with mock.patch.object(api.auth, "clear_token") as cancella:
            self.assertFalse(finta._sessione_scaduta())
        cancella.assert_not_called()
        self.assertIsNotNone(finta._account)


class MessaggiPerLePersone(unittest.TestCase):
    """Alla finestra non devono arrivare eccezioni, URL o codici HTTP."""

    def test_il_catalogo_manda_un_codice_non_un_eccezione(self):
        client = mock.Mock()
        errore = requests.HTTPError(
            "401 Client Error: Unauthorized for url: https://api.github.com/users/Sici29/repos"
        )
        with mock.patch.object(catalog, "discover", side_effect=errore), \
             mock.patch.object(catalog.feed, "load", return_value=None, create=True):
            risultato = catalog.build(
                client, fetch_covers=False, scan_library=False, use_feed=False
            )
        self.assertEqual(risultato["error"], "rete")

    def test_le_azioni_social_non_mostrano_l_eccezione(self):
        finta = api.Api.__new__(api.Api)
        finta._client = mock.Mock(token_revocato=False)
        finta._account = None
        finta.log = mock.Mock()
        esito = finta._non_riuscita(
            "stella", requests.HTTPError("500 Server Error: for url: https://api.github.com/x")
        )
        self.assertFalse(esito["ok"])
        self.assertNotIn("http", esito["error"].lower())
        self.assertNotIn("500", esito["error"])

    def test_senza_rete_lo_dice_con_parole_normali(self):
        finta = api.Api.__new__(api.Api)
        finta._client = mock.Mock(token_revocato=False)
        finta._account = None
        finta.log = mock.Mock()
        esito = finta._non_riuscita("voto", requests.ConnectionError("Max retries exceeded"))
        self.assertIn("connessione", esito["error"].lower())
        self.assertNotIn("retries", esito["error"])


class RiprovaDaSolo(unittest.TestCase):
    """GitHub non risponde all'avvio: l'hub riprova senza chiedere niente."""

    def _api(self):
        finta = api.Api.__new__(api.Api)
        finta._tentativi = 0
        finta.log = mock.Mock()
        finta._stop = mock.Mock()
        finta._stop.wait = mock.Mock(return_value=False)
        finta.refresh = mock.Mock()
        return finta

    def test_riprova_con_attese_crescenti_e_poi_smette(self):
        finta = self._api()
        with mock.patch.object(api.threading, "Thread") as filo:
            filo.side_effect = lambda target, daemon: mock.Mock(start=target)
            for _ in range(5):
                finta._riprova_da_solo()

        attese = [c.args[0] for c in finta._stop.wait.call_args_list]
        self.assertEqual(attese, list(api.Api.ATTESE_RIPROVA))
        # Dopo l'ultimo tentativo non insiste: la connessione davvero non c'e'.
        self.assertEqual(finta.refresh.call_count, len(api.Api.ATTESE_RIPROVA))

    def test_se_l_hub_si_chiude_non_riprova(self):
        finta = self._api()
        finta._stop.wait = mock.Mock(return_value=True)  # chiusura durante l'attesa
        with mock.patch.object(api.threading, "Thread") as filo:
            filo.side_effect = lambda target, daemon: mock.Mock(start=target)
            finta._riprova_da_solo()
        finta.refresh.assert_not_called()


if __name__ == "__main__":
    unittest.main()

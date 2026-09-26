"""Accesso con un clic: authorization code + PKCE su loopback.

Si simula GitHub per intero: il "browser" chiama da solo l'indirizzo di
ritorno, e lo scambio del codice e' finto. Nessuna rete, nessun account.
"""

import base64
import hashlib
import threading
import unittest
import urllib.parse
import urllib.request
from unittest import mock

from hub import auth, config


class Pkce(unittest.TestCase):
    def test_challenge_e_lo_sha256_del_verifier(self):
        verifier, challenge = auth._pkce()
        atteso = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        self.assertEqual(challenge, atteso)

    def test_lunghezza_ammessa_dalla_rfc(self):
        verifier, _ = auth._pkce()
        self.assertGreaterEqual(len(verifier), 43)
        self.assertLessEqual(len(verifier), 128)

    def test_senza_riempimento_base64(self):
        # Il padding "=" non e' ammesso in base64url per PKCE.
        verifier, challenge = auth._pkce()
        self.assertNotIn("=", verifier)
        self.assertNotIn("=", challenge)

    def test_ogni_sessione_ha_il_suo(self):
        self.assertNotEqual(auth._pkce()[0], auth._pkce()[0])


class Disponibilita(unittest.TestCase):
    """Con `_creds_cache` vuota si guarda solo config: vedi test_credenziali."""

    def setUp(self):
        patch = mock.patch.object(auth, "_creds_cache", ("", ""))
        patch.start()
        self.addCleanup(patch.stop)

    def test_serve_anche_il_secret(self):
        with mock.patch.object(config, "OAUTH_CLIENT_ID", "abc"), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", ""):
            self.assertTrue(auth.configured())
            self.assertFalse(auth.one_click())

        with mock.patch.object(config, "OAUTH_CLIENT_ID", "abc"), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", "xyz"):
            self.assertTrue(auth.one_click())

    def test_senza_credenziali_non_parte(self):
        with mock.patch.object(config, "OAUTH_CLIENT_ID", ""):
            with self.assertRaises(auth.AuthError):
                auth.web_flow()


class RitornoDalBrowser(unittest.TestCase):
    """Il pezzo delicato: l'hub apre una porta locale e aspetta GitHub."""

    def setUp(self):
        for patch in (
            mock.patch.object(auth, "_creds_cache", ("", "")),
            mock.patch.object(config, "OAUTH_CLIENT_ID", "id-di-prova"),
            mock.patch.object(config, "OAUTH_CLIENT_SECRET", "segreto"),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def _finto_browser(self, code="codice-buono", state=None, errore=None):
        """Sostituisce il browser: chiama subito l'indirizzo di ritorno."""

        def apri(url):
            parametri = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            redirect = parametri["redirect_uri"][0]
            vero_state = parametri["state"][0]

            risposta = {"state": state if state is not None else vero_state}
            if errore:
                risposta["error"] = errore
            else:
                risposta["code"] = code

            def chiama():
                try:
                    urllib.request.urlopen(
                        f"{redirect}?{urllib.parse.urlencode(risposta)}", timeout=5
                    ).read()
                except Exception:
                    pass

            threading.Thread(target=chiama, daemon=True).start()
            return True

        return apri

    def _finto_scambio(self, payload):
        risposta = mock.Mock()
        risposta.json = mock.Mock(return_value=payload)
        return mock.Mock(return_value=risposta)

    def test_percorso_completo_restituisce_il_token(self):
        with mock.patch.object(auth.webbrowser, "open", self._finto_browser()), \
             mock.patch.object(
                 auth.requests, "post",
                 self._finto_scambio({"access_token": "token-finale"})
             ) as post:
            self.assertEqual(auth.web_flow(), "token-finale")

        # Lo scambio deve portare il code_verifier: e' PKCE a rendere
        # inutile un client secret rubato dall'eseguibile.
        inviato = post.call_args.kwargs["data"]
        self.assertIn("code_verifier", inviato)
        self.assertEqual(inviato["code"], "codice-buono")
        self.assertTrue(inviato["redirect_uri"].startswith("http://127.0.0.1:"))

    def test_challenge_s256_nell_url_di_autorizzazione(self):
        visti = {}

        def apri(url):
            visti.update(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
            return self._finto_browser()(url)

        with mock.patch.object(auth.webbrowser, "open", apri), \
             mock.patch.object(
                 auth.requests, "post", self._finto_scambio({"access_token": "t"})
             ):
            auth.web_flow()

        self.assertEqual(visti["code_challenge_method"][0], "S256")
        self.assertIn("code_challenge", visti)
        self.assertEqual(visti["scope"][0], auth.SCOPE)

    def test_state_sbagliato_viene_rifiutato(self):
        # Senza questo controllo un sito qualunque potrebbe far arrivare
        # all'hub un codice di autorizzazione non richiesto da lui.
        with mock.patch.object(
            auth.webbrowser, "open", self._finto_browser(state="state-di-un-altro")
        ), mock.patch.object(auth, "WEB_FLOW_TIMEOUT", 10):
            with self.assertRaises(auth.AuthError) as ctx:
                auth.web_flow()
        self.assertIn("state", str(ctx.exception).lower())

    def test_rifiuto_dell_utente_viene_riportato(self):
        with mock.patch.object(
            auth.webbrowser, "open", self._finto_browser(errore="access_denied")
        ), mock.patch.object(auth, "WEB_FLOW_TIMEOUT", 10):
            with self.assertRaises(auth.AuthError):
                auth.web_flow()

    def test_annullamento_dalla_finestra(self):
        with mock.patch.object(auth.webbrowser, "open", lambda url: True), \
             mock.patch.object(auth, "WEB_FLOW_TIMEOUT", 30):
            with self.assertRaises(auth.AuthError) as ctx:
                auth.web_flow(stop=lambda: True)
        self.assertIn("annullat", str(ctx.exception).lower())

    def test_errore_di_github_nello_scambio(self):
        with mock.patch.object(auth.webbrowser, "open", self._finto_browser()), \
             mock.patch.object(
                 auth.requests, "post",
                 self._finto_scambio({"error_description": "codice scaduto"})
             ):
            with self.assertRaises(auth.AuthError) as ctx:
                auth.web_flow()
        self.assertIn("scaduto", str(ctx.exception))

    def test_la_porta_viene_chiusa_dopo(self):
        # Due accessi di fila non devono scontrarsi sulla stessa porta.
        for _ in range(2):
            with mock.patch.object(auth.webbrowser, "open", self._finto_browser()), \
                 mock.patch.object(
                     auth.requests, "post", self._finto_scambio({"access_token": "t"})
                 ):
                self.assertEqual(auth.web_flow(), "t")


if __name__ == "__main__":
    unittest.main()

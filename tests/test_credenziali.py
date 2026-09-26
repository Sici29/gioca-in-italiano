"""Credenziali OAuth: da dove arrivano e come si attivano.

La procedura guidata esiste per non far aprire un editor a chi pubblica l'hub.
Questi test coprono le tre cose che la rendono affidabile: l'ordine di
precedenza fra file cifrato e valori compilati nell'eseguibile, la correzione
dei due campi invertiti, e il controllo del Client ID prima di aprire il
browser.

Niente rete: la richiesta a GitHub e' sempre finta.
"""

import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path
from unittest import mock

from hub import api, auth, config


class Ordinamento(unittest.TestCase):
    """Client ID e secret invertiti: l'hub li rimette a posto da solo."""

    ID = "Ov23liABCDEFGHIJKLMN"
    SECRET = "a" * 40

    def test_ordine_giusto_resta_tale(self):
        self.assertEqual(
            auth.sort_credentials(self.ID, self.SECRET), (self.ID, self.SECRET)
        )

    def test_invertiti_vengono_scambiati(self):
        self.assertEqual(
            auth.sort_credentials(self.SECRET, self.ID), (self.ID, self.SECRET)
        )

    def test_vecchio_formato_a_20_esadecimali(self):
        vecchio = "0123456789abcdef0123"
        self.assertEqual(
            auth.sort_credentials(self.SECRET, vecchio), (vecchio, self.SECRET)
        )

    def test_spazi_dal_copia_incolla_vengono_tolti(self):
        self.assertEqual(
            auth.sort_credentials(f"  {self.ID}\n", f"\t{self.SECRET} "),
            (self.ID, self.SECRET),
        )

    def test_senza_una_delle_due_non_si_procede(self):
        self.assertIsNone(auth.sort_credentials(self.ID, ""))
        self.assertIsNone(auth.sort_credentials("", self.SECRET))
        self.assertIsNone(auth.sort_credentials(None, None))

    def test_formati_ignoti_restano_come_scritti(self):
        # Se GitHub cambiasse formato, meglio provarci che rifiutare a priori.
        self.assertEqual(auth.sort_credentials("boh", "mah"), ("boh", "mah"))


class Precedenza(unittest.TestCase):
    """Il file cifrato vince sui valori compilati nell'eseguibile."""

    def test_senza_file_valgono_quelli_dell_eseguibile(self):
        with mock.patch.object(auth, "_creds_cache", ("", "")), \
             mock.patch.object(config, "OAUTH_CLIENT_ID", "id-exe"), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", "segreto-exe"):
            self.assertEqual(auth.credentials(), ("id-exe", "segreto-exe"))
            self.assertEqual(auth.credentials_source(), "app")
            self.assertTrue(auth.one_click())

    def test_il_file_ha_la_precedenza(self):
        with mock.patch.object(auth, "_creds_cache", ("id-file", "segreto-file")), \
             mock.patch.object(config, "OAUTH_CLIENT_ID", "id-exe"), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", "segreto-exe"):
            self.assertEqual(auth.credentials(), ("id-file", "segreto-file"))
            self.assertEqual(auth.credentials_source(), "file")

    def test_senza_niente_l_accesso_non_e_proponibile(self):
        with mock.patch.object(auth, "_creds_cache", ("", "")), \
             mock.patch.object(config, "OAUTH_CLIENT_ID", ""), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", ""):
            self.assertEqual(auth.credentials_source(), "")
            self.assertFalse(auth.configured())
            self.assertFalse(auth.one_click())

    def test_spazi_nei_valori_compilati_non_contano(self):
        # Un ritorno a capo incollato in config.py non deve far credere che
        # ci siano credenziali quando non ci sono.
        with mock.patch.object(auth, "_creds_cache", ("", "")), \
             mock.patch.object(config, "OAUTH_CLIENT_ID", "  id  "), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", "\n"):
            self.assertEqual(auth.credentials(), ("id", ""))
            self.assertFalse(auth.one_click())


# DPAPI e' di Windows: su Linux (dove gira la Action) non c'e' niente da
# cifrare, e simularlo proverebbe solo che il finto funziona. Tutto il resto
# dei test resta indipendente dal sistema.
@unittest.skipUnless(sys.platform == "win32", "DPAPI esiste solo su Windows")
class SuDisco(unittest.TestCase):
    """Giro completo su disco, con la cifratura vera di Windows."""

    ID = "Ov23liQWERTYUIOPASDF"
    SECRET = "b" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cartella = Path(self.tmp.name)
        patch = mock.patch.object(auth.paths, "data_dir", lambda: cartella)
        patch.start()
        self.addCleanup(patch.stop)
        # Si parte sempre da "niente salvato", qualunque cosa ci sia sul PC.
        auth._creds_cache = None
        self.addCleanup(setattr, auth, "_creds_cache", None)

    def test_salva_rilegge_dimentica(self):
        self.assertTrue(auth.save_credentials(self.ID, self.SECRET))
        auth._creds_cache = None  # forza la rilettura da disco
        self.assertEqual(auth._stored(), (self.ID, self.SECRET))
        self.assertEqual(auth.credentials_source(), "file")

        auth.forget_credentials()
        self.assertEqual(auth._stored(), ("", ""))

    def test_il_file_non_contiene_le_stringhe_in_chiaro(self):
        auth.save_credentials(self.ID, self.SECRET)
        grezzo = (Path(self.tmp.name) / auth.CREDS_FILE).read_bytes()
        self.assertNotIn(self.ID.encode(), grezzo)
        self.assertNotIn(self.SECRET.encode(), grezzo)

    def test_salva_anche_se_incollate_al_contrario(self):
        self.assertTrue(auth.save_credentials(self.SECRET, self.ID))
        self.assertEqual(auth._stored(), (self.ID, self.SECRET))

    def test_incomplete_non_si_salvano(self):
        self.assertFalse(auth.save_credentials(self.ID, ""))
        self.assertFalse((Path(self.tmp.name) / auth.CREDS_FILE).exists())

    def test_file_illeggibile_non_fa_esplodere_niente(self):
        (Path(self.tmp.name) / auth.CREDS_FILE).write_bytes(b"non e' base64 ***")
        auth._creds_cache = None
        self.assertEqual(auth._stored(), ("", ""))

    def test_le_righe_per_config_si_rileggono_dal_file(self):
        # GitHub mostra il secret una volta sola: se non e' finito subito in
        # config.py, questa e' l'unica copia rimasta.
        auth.save_credentials(self.ID, self.SECRET)
        r = api.Api.oauth_config_snippet(None)
        self.assertTrue(r["ok"])
        self.assertIn(f'OAUTH_CLIENT_ID = "{self.ID}"', r["testo"])
        self.assertIn(f'OAUTH_CLIENT_SECRET = "{self.SECRET}"', r["testo"])

    def test_senza_file_non_c_e_niente_da_copiare(self):
        r = api.Api.oauth_config_snippet(None)
        self.assertFalse(r["ok"])

    def test_dimenticare_senza_aver_salvato_e_innocuo(self):
        auth.forget_credentials()
        self.assertEqual(auth._stored(), ("", ""))


class ControlloClientId(unittest.TestCase):
    """Verifica del Client ID prima di aprire il browser."""

    def _risposta(self, payload, stato=200):
        finta = mock.Mock()
        finta.status_code = stato
        finta.content = b"{}"
        finta.json = mock.Mock(return_value=payload)
        return mock.Mock(return_value=finta)

    def test_id_valido(self):
        with mock.patch.object(
            auth.requests, "post", self._risposta({"device_code": "xyz"})
        ):
            self.assertEqual(auth.probe_client_id("Ov23li000"), (True, ""))

    def test_device_flow_spento_prova_comunque_che_esiste(self):
        # E' la risposta piu' probabile: la casella "Enable Device Flow" e'
        # disattivata per default sulle app nuove. Non e' un errore nostro.
        with mock.patch.object(
            auth.requests, "post", self._risposta({"error": "device_flow_disabled"})
        ):
            ok, _ = auth.probe_client_id("Ov23li000")
        self.assertTrue(ok)

    def test_id_inesistente_viene_bocciato(self):
        # Risposta reale di GitHub, verificata sul campo: 404 e "Not Found"
        # con la F maiuscola. Il confronto non deve dipendere da quella F.
        with mock.patch.object(
            auth.requests, "post", self._risposta({"error": "Not Found"}, stato=404)
        ):
            ok, perche = auth.probe_client_id("sbagliato")
        self.assertFalse(ok)
        self.assertIn("Client ID", perche)

    def test_bocciato_anche_se_arrivasse_con_stato_200(self):
        for testo in ("Not Found", "not found", "invalid_client"):
            with self.subTest(testo=testo):
                with mock.patch.object(
                    auth.requests, "post", self._risposta({"error": testo})
                ):
                    self.assertFalse(auth.probe_client_id("sbagliato")[0])

    def test_id_vuoto(self):
        ok, perche = auth.probe_client_id("   ")
        self.assertFalse(ok)
        self.assertIn("Client ID", perche)

    def test_rete_giu_concede_il_beneficio_del_dubbio(self):
        # Bloccare l'attivazione perche' la rete e' caduta sarebbe il modo
        # peggiore di fallire: si prova l'accesso vero e si vede.
        with mock.patch.object(
            auth.requests, "post", mock.Mock(side_effect=auth.requests.RequestException)
        ):
            self.assertEqual(auth.probe_client_id("Ov23li000"), (True, ""))

    def test_risposta_incomprensibile_non_blocca(self):
        with mock.patch.object(auth.requests, "post", self._risposta(["strano"])):
            self.assertEqual(auth.probe_client_id("Ov23li000"), (True, ""))


class ChiVedeLAttivazione(unittest.TestCase):
    """La procedura non deve comparire a chi scarica l'hub."""

    def test_dai_sorgenti_e_sempre_l_autore(self):
        with mock.patch.object(sys, "frozen", False, create=True):
            self.assertTrue(api.autore())

    def test_nell_eseguibile_e_nascosta(self):
        with mock.patch.object(sys, "frozen", True, create=True),              mock.patch.object(sys, "argv", ["Sici29Hub.exe"]):
            self.assertFalse(api.autore())

    def test_nell_eseguibile_si_apre_con_setup(self):
        with mock.patch.object(sys, "frozen", True, create=True),              mock.patch.object(sys, "argv", ["Sici29Hub.exe", "--setup"]):
            self.assertTrue(api.autore())


class ModuloPrecompilato(unittest.TestCase):
    """Il link che apre su GitHub il modulo con i campi gia' dentro."""

    def setUp(self):
        self.url = config.oauth_register_url()
        parti = urllib.parse.urlparse(self.url)
        self.host = parti.netloc
        self.percorso = parti.path
        self.campi = urllib.parse.parse_qs(parti.query)

    def test_punta_alla_pagina_giusta_di_github(self):
        self.assertEqual(self.host, "github.com")
        self.assertEqual(self.percorso, "/settings/applications/new")

    def test_porta_nome_sito_e_callback(self):
        self.assertEqual(
            self.campi["oauth_application[name]"][0], config.OAUTH_APP_NAME
        )
        self.assertEqual(
            self.campi["oauth_application[url]"][0], config.PROFILE_URL
        )
        self.assertEqual(
            self.campi["oauth_application[callback_url]"][0],
            config.OAUTH_CALLBACK_URL,
        )

    def test_la_callback_registrata_e_su_loopback(self):
        # Deve restare senza porta: GitHub non pretende che coincida con
        # quella usata davvero, e l'hub ne prende una libera.
        self.assertEqual(config.OAUTH_CALLBACK_URL, "http://127.0.0.1/callback")
        self.assertTrue(
            config.OAUTH_CALLBACK_URL.startswith("http://127.0.0.1/")
        )


class FlussoUsaLeCredenzialiSalvate(unittest.TestCase):
    """Il pezzo che conta: dopo la procedura guidata l'accesso funziona."""

    def test_il_web_flow_prende_quelle_del_file_non_quelle_dell_exe(self):
        visti = {}

        def apri(url):
            visti.update(urllib.parse.parse_qs(urllib.parse.urlparse(url).query))
            raise KeyboardInterrupt  # basta l'URL, non serve completare

        with mock.patch.object(auth, "_creds_cache", ("id-del-file", "segreto")), \
             mock.patch.object(config, "OAUTH_CLIENT_ID", "id-dell-exe"), \
             mock.patch.object(config, "OAUTH_CLIENT_SECRET", "altro"), \
             mock.patch.object(auth.webbrowser, "open", apri), \
             mock.patch.object(auth, "WEB_FLOW_TIMEOUT", 2):
            with self.assertRaises(KeyboardInterrupt):
                auth.web_flow()

        self.assertEqual(visti["client_id"][0], "id-del-file")

    def test_il_device_flow_pure(self):
        with mock.patch.object(auth, "_creds_cache", ("id-del-file", "")), \
             mock.patch.object(config, "OAUTH_CLIENT_ID", "id-dell-exe"), \
             mock.patch.object(
                 auth.requests, "post",
                 mock.Mock(return_value=mock.Mock(
                     raise_for_status=mock.Mock(),
                     json=mock.Mock(return_value={"device_code": "x"}),
                 ))
             ) as post:
            auth.start()
        self.assertEqual(post.call_args.kwargs["data"]["client_id"], "id-del-file")


if __name__ == "__main__":
    unittest.main()

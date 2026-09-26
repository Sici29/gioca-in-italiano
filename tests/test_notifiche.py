"""Notifiche di Windows: cosa si annuncia, come appare, cosa fanno i pulsanti.

Nascono da tre difetti visti sul PC dell'autore: le notifiche comparivano a
nome di "Windows PowerShell", erano due righe di testo nudo, e la stessa
tornava ogni mezz'ora finche' l'aggiornamento restava da fare.
"""

import os
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from hub import api, notify, state


def progetto(repo, titolo, status="aggiornato", tag="v2", novita=None, note=""):
    return {
        "repo": repo,
        "title": titolo,
        "status": status,
        "novita": novita,
        "latest": {"tag": tag, "body": note},
    }


class CartellaDatiFinta(unittest.TestCase):
    """Stato, gettoni e richieste finiscono in una cartella usa e getta."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        precedente = os.environ.get("LOCALAPPDATA")
        os.environ["LOCALAPPDATA"] = self.tmp.name

        def ripristina():
            if precedente is None:
                os.environ.pop("LOCALAPPDATA", None)
            else:
                os.environ["LOCALAPPDATA"] = precedente

        self.addCleanup(ripristina)


class CosaSiAnnuncia(unittest.TestCase):
    def test_un_aggiornamento_una_notifica_con_il_pulsante(self):
        p = progetto("Aniimo-IT", "Aniimo", status="aggiornamento", tag="v1.1",
                     note="# Aniimo 1.1\n\n- **Supporto alla build 3603741**:\n- altro")
        notifiche, inviate = notify.da_notificare([p], None, {}, nuovo_gettone=lambda: "abc")
        self.assertEqual(len(notifiche), 1)
        n = notifiche[0]
        self.assertIn("Aniimo", n.titolo)
        self.assertEqual(n.testo, "Versione v1.1 · Supporto alla build 3603741")
        self.assertEqual(n.pulsanti[0], ("Aggiorna", "giocainitaliano:aggiorna/Aniimo-IT?t=abc"))
        self.assertEqual(n.gettoni, {"abc": "Aniimo-IT"})
        self.assertEqual(inviate, {"Aniimo-IT": "v1.1"})

    def test_la_stessa_versione_non_si_ripete(self):
        # Il difetto di prima: a ogni controllo, cioe' ogni mezz'ora.
        p = progetto("A", "Aniimo", status="aggiornamento", tag="v1.1")
        notifiche, _ = notify.da_notificare([p], None, {"A": "v1.1"})
        self.assertEqual(notifiche, [])

    def test_una_versione_ancora_piu_nuova_si_annuncia(self):
        p = progetto("A", "Aniimo", status="aggiornamento", tag="v1.2")
        notifiche, inviate = notify.da_notificare([p], None, {"A": "v1.1"})
        self.assertEqual(len(notifiche), 1)
        self.assertEqual(inviate["A"], "v1.2")

    def test_piu_aggiornamenti_una_notifica_sola(self):
        progetti = [progetto(r, r.title(), status="aggiornamento") for r in ("a", "b", "c")]
        notifiche, inviate = notify.da_notificare(progetti, None, {})
        self.assertEqual(len(notifiche), 1)
        self.assertEqual(notifiche[0].titolo, "3 traduzioni da aggiornare")
        self.assertEqual(notifiche[0].testo, "A, B e C")
        self.assertEqual(set(inviate), {"a", "b", "c"})

    def test_una_traduzione_nuova_si_annuncia_una_volta(self):
        p = progetto("NTE", "Neverness to Everness", status="non_installato", novita="nuova")
        notifiche, inviate = notify.da_notificare([p], None, {})
        self.assertEqual(notifiche[0].titolo, "Nuova traduzione: Neverness to Everness")
        self.assertEqual(notify.da_notificare([p], None, inviate)[0], [])

    def test_la_nuova_versione_dell_hub(self):
        aggiornamento = {"available": True, "version": "v1.1.0"}
        notifiche, inviate = notify.da_notificare([], aggiornamento, {})
        self.assertIn("v1.1.0", notifiche[0].titolo)
        self.assertEqual(notify.da_notificare([], aggiornamento, inviate)[0], [])
        self.assertEqual(notify.da_notificare([], {"available": False}, {})[0], [])

    def test_mai_piu_di_tre_alla_volta(self):
        progetti = [progetto(f"n{i}", f"Nuova {i}", status="non_installato", novita="nuova") for i in range(2)]
        progetti += [progetto(f"u{i}", f"Upd {i}", status="aggiornamento") for i in range(2)]
        notifiche, _ = notify.da_notificare(progetti, {"available": True, "version": "v2"}, {})
        self.assertLessEqual(len(notifiche), notify.MAX_PER_CONTROLLO)

    def test_la_copertina_solo_se_il_file_c_e(self):
        with tempfile.TemporaryDirectory() as cartella:
            copertina = Path(cartella) / "A.jpg"
            copertina.write_bytes(b"jpg")
            p = progetto("A", "Aniimo", status="aggiornamento")
            con = notify.da_notificare([p], None, {}, copertina=lambda r: copertina)[0][0]
            senza = notify.da_notificare([p], None, {}, copertina=lambda r: Path(cartella) / "no.jpg")[0][0]
        self.assertEqual(con.immagine, str(copertina))
        self.assertEqual(senza.immagine, "")


class CosaCambia(unittest.TestCase):
    def test_salta_il_titolo_e_prende_il_primo_punto(self):
        note = "# Release 1.0\n\nAggiornamento completo.\n\n- **Nuova build** supportata\n- altro"
        self.assertEqual(notify.cosa_cambia(note), "Nuova build supportata")

    def test_senza_punti_la_prima_riga(self):
        self.assertEqual(notify.cosa_cambia("Prima release completa."), "Prima release completa.")

    def test_toglie_codice_e_link(self):
        self.assertEqual(
            notify.cosa_cambia("- build `3603741` e [note](https://x.y)"), "build 3603741 e note"
        )

    def test_accorcia(self):
        self.assertTrue(notify.cosa_cambia("- " + "parola " * 40, limite=30).endswith("…"))

    def test_note_vuote(self):
        self.assertEqual(notify.cosa_cambia(""), "")


class ComeAppare(unittest.TestCase):
    def test_xml_valido_con_copertina_e_pulsanti(self):
        n = notify.Notifica(
            titolo='Aniimo & "amici" <v2>',
            testo="Versione v2",
            # Un percorso completo sul sistema che fa girare i test: "C:\..."
            # su Linux sarebbe relativo.
            immagine=str(Path(tempfile.gettempdir()) / "covers" / "Aniimo.jpg"),
            apri="giocainitaliano:mostra/Aniimo",
            pulsanti=[("Aggiorna", "giocainitaliano:aggiorna/Aniimo?t=a&b"), ("Più tardi", "chiudi")],
        )
        radice = ET.fromstring(notify.xml(n))
        self.assertEqual(radice.get("activationType"), "protocol")
        self.assertEqual(radice.get("launch"), "giocainitaliano:mostra/Aniimo")
        testi = [t.text for t in radice.iter("text")]
        self.assertEqual(testi[0], 'Aniimo & "amici" <v2>')
        immagine = next(radice.iter("image"))
        self.assertEqual(immagine.get("placement"), "hero")
        self.assertTrue(immagine.get("src").startswith("file:///"))
        azioni = list(radice.iter("action"))
        self.assertEqual(azioni[0].get("arguments"), "giocainitaliano:aggiorna/Aniimo?t=a&b")
        self.assertEqual(azioni[1].get("activationType"), "system")

    def test_un_percorso_relativo_non_rompe_la_notifica(self):
        radice = ET.fromstring(notify.xml(notify.Notifica(titolo="Ciao", immagine="covers/a.jpg")))
        self.assertIsNone(next(radice.iter("image"), None))

    def test_senza_immagine_ne_pulsanti(self):
        radice = ET.fromstring(notify.xml(notify.Notifica(titolo="Ciao")))
        self.assertIsNone(next(radice.iter("image"), None))
        self.assertIsNone(next(radice.iter("actions"), None))


class Link(unittest.TestCase):
    def test_i_tre_link(self):
        self.assertEqual(notify.leggi_link("giocainitaliano:apri"), {"azione": "apri"})
        self.assertEqual(
            notify.leggi_link("giocainitaliano:mostra/Aniimo-Italian-Translation"),
            {"azione": "mostra", "repo": "Aniimo-Italian-Translation", "gettone": ""},
        )
        self.assertEqual(
            notify.leggi_link(notify.link_aggiorna("SC-Italian-Translation", "x_y-1")),
            {"azione": "aggiorna", "repo": "SC-Italian-Translation", "gettone": "x_y-1"},
        )

    def test_forme_che_windows_puo_passare(self):
        self.assertEqual(notify.leggi_link("GiocaInItaliano://mostra/A/")["repo"], "A")

    def test_link_estranei_o_strani(self):
        for link in ("https://example.com", "giocainitaliano:installa/A", "giocainitaliano:mostra/..%2F..%2Fx y",
                     "giocainitaliano:mostra/", "", None):
            with self.subTest(link=link):
                self.assertIsNone(notify.leggi_link(link))


class Gettoni(unittest.TestCase):
    def test_vale_una_volta_sola_e_per_quel_repo(self):
        ora = time.time()
        gettoni = {"abc": {"repo": "A", "ts": ora}}
        self.assertFalse(notify.usa_gettone(gettoni, "abc", "B", ora))
        self.assertTrue(notify.usa_gettone(gettoni, "abc", "A", ora))
        self.assertFalse(notify.usa_gettone(gettoni, "abc", "A", ora))

    def test_senza_gettone_o_scaduto(self):
        ora = time.time()
        self.assertFalse(notify.usa_gettone({}, "", "A", ora))
        vecchio = {"x": {"repo": "A", "ts": ora - notify.DURATA_GETTONE - 10}}
        self.assertFalse(notify.usa_gettone(vecchio, "x", "A", ora))

    def test_potatura(self):
        ora = time.time()
        gettoni = {f"g{i}": {"repo": "A", "ts": ora - i} for i in range(notify.MAX_GETTONI + 10)}
        gettoni["vecchio"] = {"repo": "A", "ts": ora - notify.DURATA_GETTONE - 1}
        potati = notify.pota_gettoni(gettoni, ora)
        self.assertEqual(len(potati), notify.MAX_GETTONI)
        self.assertNotIn("vecchio", potati)
        self.assertIn("g0", potati)


class RichiestaAlPrimoHub(CartellaDatiFinta):
    def test_andata_e_ritorno(self):
        notify.lascia_richiesta("giocainitaliano:mostra/A")
        self.assertEqual(notify.prendi_richiesta(), "giocainitaliano:mostra/A")
        # Presa una volta, non c'e' piu'.
        self.assertIsNone(notify.prendi_richiesta())

    def test_una_richiesta_dimenticata_non_vale(self):
        notify.lascia_richiesta("giocainitaliano:mostra/A")
        dopo = time.time() + notify.ETA_MASSIMA_RICHIESTA + 5
        self.assertIsNone(notify.prendi_richiesta(ora=dopo))


class Registrazione(CartellaDatiFinta):
    def registro_finto(self, errore=False):
        scritture = {}

        class Chiave:
            def __init__(self, nome):
                self.nome = nome

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def crea(radice, nome):
            if errore:
                raise OSError("accesso negato")
            return Chiave(nome)

        def scrivi(chiave, valore, _, tipo, dato):
            scritture[(chiave.nome, valore)] = dato

        reg = mock.Mock(HKEY_CURRENT_USER="HKCU", REG_SZ=1, CreateKey=crea, SetValueEx=scrivi)
        return reg, scritture

    def test_nome_e_icona_dell_hub(self):
        reg, scritture = self.registro_finto()
        self.assertTrue(notify.registra(None, reg=reg))
        chiave = rf"Software\Classes\AppUserModelId\{notify.AUMID}"
        self.assertEqual(scritture[(chiave, "DisplayName")], "Gioca in Italiano")
        self.assertTrue(Path(scritture[(chiave, "IconUri")]).exists())
        # Dai sorgenti niente link: non c'e' un eseguibile da far partire.
        self.assertFalse(any("giocainitaliano" in k[0] for k in scritture))

    def test_il_link_punta_all_eseguibile(self):
        reg, scritture = self.registro_finto()
        notify.registra(r"C:\Giochi\GiocaInItaliano.exe", reg=reg)
        comando = scritture[(r"Software\Classes\giocainitaliano\shell\open\command", "")]
        self.assertEqual(comando, r'"C:\Giochi\GiocaInItaliano.exe" "%1"')
        self.assertEqual(scritture[(r"Software\Classes\giocainitaliano", "URL Protocol")], "")

    def test_se_il_registro_rifiuta_si_ripiega(self):
        reg, _ = self.registro_finto(errore=True)
        self.assertFalse(notify.registra(None, reg=reg))


class DentroLHub(CartellaDatiFinta):
    def _api(self, progetti):
        finta = api.Api.__new__(api.Api)
        finta._catalog = {"projects": progetti, "error": ""}
        finta._hub_update = None
        finta.log = mock.Mock()
        finta._emit = mock.Mock()
        finta.install = mock.Mock()
        return finta

    def test_una_volta_sola_anche_dopo_tanti_controlli(self):
        p = progetto("A", "Aniimo", status="aggiornamento", tag="v3")
        finta = self._api([p])
        with mock.patch.object(notify, "mostra") as mostra, \
             mock.patch.object(api.covers, "percorso", return_value=Path(self.tmp.name) / "no.jpg"):
            for _ in range(5):
                finta._notifica([p])
        self.assertEqual(mostra.call_count, 1)

    def test_spente_dalle_impostazioni(self):
        local = state.load()
        local["settings"]["notify"] = False
        state.save(local)
        finta = self._api([progetto("A", "Aniimo", status="aggiornamento")])
        with mock.patch.object(notify, "mostra") as mostra:
            finta._notifica(finta._catalog["projects"])
        mostra.assert_not_called()

    def test_il_pulsante_aggiorna_fa_partire_l_aggiornamento(self):
        p = progetto("A", "Aniimo", status="aggiornamento", tag="v3")
        finta = self._api([p])
        with mock.patch.object(notify, "mostra") as mostra, \
             mock.patch.object(api.covers, "percorso", return_value=Path(self.tmp.name) / "no.jpg"):
            finta._notifica([p])
        link = dict(mostra.call_args[0][0].pulsanti)["Aggiorna"]
        finta.gestisci_link(link)
        finta._emit.assert_called_with("apri", {"repo": "A"})
        finta.install.assert_called_once_with("A")
        # Lo stesso link una seconda volta: il gettone e' gia' stato usato.
        finta.gestisci_link(link)
        finta.install.assert_called_once()

    def test_un_link_scritto_da_altri_apre_solo_la_scheda(self):
        finta = self._api([progetto("A", "Aniimo", status="aggiornamento")])
        finta.gestisci_link("giocainitaliano:aggiorna/A?t=inventato")
        finta._emit.assert_called_with("apri", {"repo": "A"})
        finta.install.assert_not_called()


if __name__ == "__main__":
    unittest.main()

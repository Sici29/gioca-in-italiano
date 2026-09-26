"""L'installer delle traduzioni guidato dall'hub, senza la sua finestra.

Gli installer veri sono eseguibili da 40 MB che toccano i file dei giochi:
qui al loro posto gira Python stesso, con un piccolo script che si comporta
come loro - scrive righe con il fine riga di Windows, barre di avanzamento,
colori, o si ferma ad aspettare una risposta. E' abbastanza per provare le
parti che contano: che le righe arrivino tutte, che niente resti appeso, che
il riassunto dica la cosa giusta.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hub import api, catalog, config, installer, scan

PYTHON = Path(sys.executable)


def _script(codice: str) -> list[str]:
    return ["-c", codice]


class Esecuzione(unittest.TestCase):
    def test_le_righe_di_windows_arrivano_tutte(self):
        # Il caso che ha fatto sparire tutto: ogni riga finisce con \r\n, e
        # tenere "l'ultimo pezzo dopo \r" lasciava solo "\n".
        esito = installer.esegui(PYTHON, _script(
            "import sys; sys.stdout.buffer.write(b'Creo backup...\\r\\nPatch installata.\\r\\n')"
        ))
        self.assertEqual(esito["righe"], ["Creo backup...", "Patch installata."])
        self.assertEqual(esito["codice"], 0)

    def test_di_una_barra_di_avanzamento_resta_l_ultimo_stato(self):
        esito = installer.esegui(PYTHON, _script(
            "import sys; sys.stdout.buffer.write(b'Patch  10%\\rPatch  60%\\rPatch 100%\\r\\n')"
        ))
        self.assertEqual(esito["righe"], ["Patch 100%"])

    def test_i_colori_non_arrivano_alla_finestra(self):
        esito = installer.esegui(PYTHON, _script(
            "import sys; sys.stdout.buffer.write(b'\\x1b[1;32mFatto\\x1b[0m\\n')"
        ))
        self.assertEqual(esito["righe"], ["Fatto"])

    def test_accenti_in_utf8_e_nella_codifica_di_windows(self):
        esito = installer.esegui(PYTHON, _script(
            "import sys; sys.stdout.buffer.write('gi\\u00e0 fatto\\n'.encode('utf-8'));"
            "sys.stdout.buffer.write('s\\u00ec\\n'.encode('cp1252'))"
        ))
        self.assertEqual(esito["righe"], ["già fatto", "sì"])

    def test_le_righe_vuote_non_contano(self):
        esito = installer.esegui(PYTHON, _script("print(); print('uno'); print('   '); print('due')"))
        self.assertEqual(esito["righe"], ["uno", "due"])

    def test_ogni_riga_arriva_anche_alla_finestra(self):
        viste = []
        installer.esegui(PYTHON, _script("print('a'); print('b')"), on_riga=viste.append)
        self.assertEqual(viste, ["a", "b"])

    def test_una_domanda_non_lo_lascia_appeso(self):
        # L'ingresso e' chiuso: input() riceve "fine dell'input" e l'installer
        # esce con un errore invece di aspettare per sempre.
        esito = installer.esegui(PYTHON, _script("input('Percorso: ')"), tempo_massimo=30)
        self.assertNotEqual(esito["codice"], 0)
        self.assertFalse(esito["scaduto"])

    def test_oltre_il_tempo_massimo_viene_fermato(self):
        esito = installer.esegui(
            PYTHON, _script("import time; print('parto', flush=True); time.sleep(30)"),
            tempo_massimo=1,
        )
        self.assertTrue(esito["scaduto"])
        self.assertIn("parto", esito["righe"])

    def test_il_codice_d_uscita_arriva(self):
        self.assertEqual(installer.esegui(PYTHON, _script("raise SystemExit(2)"))["codice"], 2)

    def test_un_installer_bloccato_dall_antivirus(self):
        with self.assertRaises(installer.DownloadError) as ctx:
            installer.esegui(Path(tempfile.gettempdir()) / "non-esiste-davvero.exe", [])
        self.assertIn("antivirus", str(ctx.exception))


class Riassunto(unittest.TestCase):
    """Da quello che scrive l'installer, quello che serve a una persona."""

    def _r(self, codice, righe, scaduto=False):
        return installer.riassumi({"codice": codice, "righe": righe, "scaduto": scaduto})

    def test_installazione_riuscita(self):
        r = self._r(0, [
            "Cartella gioco: D:/X", "Creo backup...", "Backup: C:/b",
            "✓ Traduzione 100% compatibile applicata con successo!",
            "Patch installata.", "Lingua da selezionare in gioco: Inglese",
            'Statistiche: {"en": 1}',
        ])
        self.assertTrue(r["ok"])
        self.assertFalse(r["parziale"])
        self.assertEqual(r["messaggio"], "Traduzione 100% compatibile applicata con successo!")
        # E' la cosa che la gente sbaglia: senza, vede ancora l'inglese.
        self.assertEqual(r["consiglio"], "Lingua da selezionare in gioco: Inglese")

    def test_la_diagnostica_resta_fuori(self):
        r = self._r(0, [
            "Cartella gioco: D:/X", 'Statistiche: {"en": 1}',
            "Digest locale (diagnostico): 1850fd03", "Risorse Lua: D:/X/lua",
            "Build già testate: 1, 2", "Stringhe: 112207", "=" * 20, "Fatto.",
        ])
        self.assertEqual(r["righe"], ["Cartella gioco: D:/X", "Fatto."])

    def test_gioco_aperto(self):
        r = self._r(2, ["Chiudi prima gioco/launcher: Aniimo.exe"])
        self.assertFalse(r["ok"])
        self.assertEqual(r["messaggio"], "Chiudi il gioco e il suo launcher, poi riprova.")

    def test_errore_dell_installer(self):
        r = self._r(1, ["Cartella gioco: X", "Errore: Non trovo i file del gioco"])
        self.assertEqual(r["messaggio"], "Non trovo i file del gioco")

    def test_opzioni_che_l_installer_non_conosce(self):
        # E' un problema del profilo nell'hub, non dell'utente: gli si dice
        # dove trovare l'installer completo invece di mostrargli argparse.
        r = self._r(2, ["usage: x.exe [-h]", "x.exe: error: unrecognized arguments: --boh"])
        self.assertIn("installer completo", r["messaggio"])
        self.assertNotIn("usage", r["messaggio"])

    def test_riuscita_ma_parziale(self):
        r = self._r(0, ["ATTENZIONE: NUOVA VERSIONE RILEVATA CON FALLBACK INGLESE", "Patch installata."])
        self.assertTrue(r["ok"])
        self.assertTrue(r["parziale"])

    def test_fermato_per_tempo(self):
        r = self._r(-9, [], scaduto=True)
        self.assertFalse(r["ok"])
        self.assertIn("15 minuti", r["messaggio"])

    def test_nessuna_riga(self):
        self.assertEqual(self._r(0, [])["messaggio"], "Fatto.")
        self.assertIn("errore", self._r(1, [])["messaggio"])


class Profili(unittest.TestCase):
    """Ogni installer vuole le sue opzioni: una che non conosce lo fa fallire."""

    def test_il_nucleo_comune(self):
        p = config.installer_profilo("Repo-Sconosciuto")
        self.assertEqual(p["install"], ["install"])
        self.assertEqual(p["restore"], ["restore"])
        self.assertEqual(p["check"], ["check"])
        self.assertNotIn("backup", p)

    def test_quelli_ricavati_dal_sorgente(self):
        self.assertEqual(config.installer_profilo("Aniimo-Italian-Translation")["install"],
                         ["install", "--no-update-check"])
        self.assertEqual(config.installer_profilo("Aniimo-Italian-Translation")["backup"],
                         ["backup-dir"])
        self.assertEqual(config.installer_profilo("NTE-Italian-Translation")["check"], ["verify"])
        # SC non conosce --no-update-check: passarglielo lo farebbe uscire.
        self.assertNotIn("--no-update-check",
                         config.installer_profilo("SC-Italian-Translation")["install"])

    def test_il_hub_json_ha_la_precedenza(self):
        p = config.installer_profilo("NTE-Italian-Translation", {"check": ["check", "--full"]})
        self.assertEqual(p["check"], ["check", "--full"])

    def test_valori_strani_nel_hub_json_non_arrivano_alla_riga_di_comando(self):
        p = config.installer_profilo("X", {"install": "rm -rf", "check": [1, 2], "restore": None})
        self.assertEqual(p["install"], ["install"])
        self.assertEqual(p["check"], ["check"])
        self.assertEqual(p["restore"], ["restore"])


class CartellaSceltaAMano(unittest.TestCase):
    def _api(self, scelta=None):
        finta = api.Api.__new__(api.Api)
        locale = {"cartelle_scelte": {"R": scelta} if scelta else {}}
        patch = mock.patch.object(api.state, "load", return_value=locale)
        patch.start()
        self.addCleanup(patch.stop)
        return finta

    def test_senza_scelta_l_installer_la_trova_da_se(self):
        finta = self._api()
        self.assertEqual(finta._argomenti({"repo": "R"}, "install"), ["install"])

    def test_con_la_scelta_si_passa(self):
        finta = self._api(r"E:\Giochi\Aniimo")
        self.assertEqual(finta._argomenti({"repo": "R"}, "install"),
                         ["install", "--game-dir", r"E:\Giochi\Aniimo"])

    def test_non_ai_comandi_che_non_la_conoscono(self):
        # backup-dir di Aniimo non ha --game-dir: aggiungerla lo farebbe uscire.
        finta = self._api(r"E:\Giochi\Aniimo")
        progetto = {"repo": "R", "installer": {"backup": ["backup-dir"]}}
        self.assertEqual(finta._argomenti(progetto, "backup"), ["backup-dir"])

    def test_azione_che_l_installer_non_ha(self):
        finta = self._api()
        self.assertIsNone(finta._argomenti({"repo": "R", "installer": {}}, "backup"))


class Avvio(unittest.TestCase):
    def test_da_steam(self):
        gioco = {"source": scan.SOURCE_STEAM, "appid": 4126040, "path": "D:/X"}
        self.assertEqual(catalog.come_si_avvia(gioco, "Aniimo"), "steam:4126040")

    def test_star_citizen_dal_suo_launcher(self):
        gioco = {"source": "RSI Launcher", "appid": None, "path": "D:/RSI/StarCitizen/LIVE"}
        with mock.patch.object(scan, "launcher_rsi", return_value=Path("D:/RSI/RSI Launcher/RSI Launcher.exe")):
            self.assertEqual(catalog.come_si_avvia(gioco, "Star Citizen"), "rsi")
        with mock.patch.object(scan, "launcher_rsi", return_value=None):
            self.assertEqual(catalog.come_si_avvia(gioco, "Star Citizen"), "")

    def test_il_resto_non_si_indovina(self):
        self.assertEqual(catalog.come_si_avvia({"source": "Windows", "path": "C:/X"}, "Boh"), "")
        self.assertEqual(catalog.come_si_avvia(None, "Aniimo"), "")

    def test_steam_riceve_l_ordine_giusto(self):
        finta = api.Api.__new__(api.Api)
        finta._catalog = {"projects": [{"repo": "R", "title": "Aniimo", "avvio": "steam:4126040"}]}
        finta.log = mock.Mock()
        finta._status = mock.Mock()
        with mock.patch.object(api.os, "startfile", create=True) as apri:
            self.assertTrue(finta.avvia_gioco("R")["ok"])
        apri.assert_called_once_with("steam://rungameid/4126040")

    def test_un_gioco_senza_avvio(self):
        finta = api.Api.__new__(api.Api)
        finta._catalog = {"projects": [{"repo": "R", "title": "X", "avvio": ""}]}
        self.assertFalse(finta.avvia_gioco("R")["ok"])


class LauncherRsi(unittest.TestCase):
    def test_si_trova_risalendo_dalla_cartella_del_gioco(self):
        with tempfile.TemporaryDirectory() as radice:
            live = Path(radice) / "Robert Space Industries" / "StarCitizen" / "LIVE"
            live.mkdir(parents=True)
            launcher = Path(radice) / "Robert Space Industries" / "RSI Launcher" / "RSI Launcher.exe"
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"MZ")
            with mock.patch.object(scan, "_launcher_rsi_dal_registro", return_value=iter(())):
                self.assertEqual(scan.launcher_rsi(live), launcher)


class ProposteDellaComunita(unittest.TestCase):
    """Il difetto grave: GitHub toglie le etichette a chi non ha i permessi."""

    def test_si_riconoscono_dal_titolo_anche_senza_etichetta(self):
        self.assertTrue(catalog.e_una_proposta({"title": "[Proposta] Elden Ring", "labels": []}))

    def test_maiuscole_e_spazi_non_contano(self):
        self.assertTrue(catalog.e_una_proposta({"title": "  [proposta] X", "labels": []}))

    def test_l_etichetta_vale_ancora(self):
        self.assertTrue(catalog.e_una_proposta({"title": "Elden Ring", "labels": [{"name": "Proposta"}]}))

    def test_le_altre_issue_restano_fuori(self):
        self.assertFalse(catalog.e_una_proposta({"title": "Bug nel sito", "labels": [{"name": "bug"}]}))

    def test_la_bacheca_non_filtra_piu_per_etichetta(self):
        client = mock.Mock()
        client.list_issues.return_value = [
            {"number": 1, "title": "[Proposta] Elden Ring", "labels": [], "reactions": {"+1": 5}},
            {"number": 2, "title": "Domanda sul sito", "labels": [], "reactions": {}},
        ]
        proposte = catalog.fetch_proposals(client)
        self.assertEqual([p["number"] for p in proposte], [1])
        client.list_issues.assert_called_once_with(config.SUGGESTIONS_REPO)


if __name__ == "__main__":
    unittest.main()

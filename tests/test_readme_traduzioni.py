"""Il riquadro di Gioca in Italiano nei README delle traduzioni.

Sono README scritti a mano, ognuno a modo suo: il riquadro deve finire sotto il
titolo e i badge senza toccare il resto, e rilanciare lo strumento deve solo
aggiornarlo, mai duplicarlo.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import readme_traduzioni as rt  # noqa: E402

ALTRI = [("Neverness to Everness", "neverness-to-everness"), ("Star Citizen", "star-citizen")]

CON_BADGE = """# NTE - Traduzione Italiana

[![Release](https://img.shields.io/x)](https://github.com/x)
[![Licenza](https://img.shields.io/y)](LICENSE)

Traduzione italiana amatoriale completa.

## Installazione
"""

SOLO_TITOLO = """# Aniimo — Traduzione italiana

## Release client Steam

Testo.
"""


class Riquadro(unittest.TestCase):
    def test_porta_alle_altre_traduzioni_e_all_app(self):
        testo = rt.blocco(ALTRI)
        self.assertIn(f"[Neverness to Everness]({rt.SITO}neverness-to-everness/)", testo)
        self.assertIn(" e [Star Citizen]", testo)
        self.assertIn(rt.SCARICA, testo)
        self.assertIn(f"{rt.SITO}#proponi", testo)
        self.assertIn(f"{rt.SITO}img/banner.jpg", testo)
        self.assertTrue(testo.startswith(rt.INIZIO) and testo.endswith(rt.FINE))

    def test_senza_altre_traduzioni(self):
        self.assertNotIn("scoprire", rt.blocco([]))


class Inserimento(unittest.TestCase):
    def test_sotto_titolo_e_badge(self):
        nuovo = rt.inserisci(CON_BADGE, rt.blocco(ALTRI))
        righe = nuovo.split("\n")
        self.assertEqual(righe[0], "# NTE - Traduzione Italiana")
        self.assertTrue(righe[3].startswith("[![Licenza]"))
        self.assertEqual(righe[4], "")
        self.assertEqual(righe[5], rt.INIZIO)
        fine = righe.index(rt.FINE)
        self.assertEqual(righe[fine + 1], "")
        self.assertEqual(righe[fine + 2], "Traduzione italiana amatoriale completa.")

    def test_sotto_il_solo_titolo(self):
        nuovo = rt.inserisci(SOLO_TITOLO, rt.blocco(ALTRI))
        righe = nuovo.split("\n")
        self.assertEqual(righe[:3], ["# Aniimo — Traduzione italiana", "", rt.INIZIO])
        self.assertIn("## Release client Steam", nuovo)
        self.assertTrue(nuovo.endswith("Testo.\n"))

    def test_rilanciato_non_cambia_niente(self):
        una = rt.inserisci(CON_BADGE, rt.blocco(ALTRI))
        self.assertEqual(rt.inserisci(una, rt.blocco(ALTRI)), una)
        self.assertEqual(una.count(rt.INIZIO), 1)

    def test_una_traduzione_nuova_aggiorna_l_elenco(self):
        prima = rt.inserisci(CON_BADGE, rt.blocco(ALTRI))
        dopo = rt.inserisci(prima, rt.blocco(ALTRI + [("Fatekeeper", "fatekeeper")]))
        self.assertIn("[Fatekeeper]", dopo)
        self.assertEqual(dopo.count(rt.INIZIO), 1)
        # Il resto del README non si muove.
        self.assertEqual(dopo.split(rt.FINE)[1], prima.split(rt.FINE)[1])

    def test_rispetta_gli_a_capo_di_windows(self):
        crlf = CON_BADGE.replace("\n", "\r\n")
        nuovo = rt.inserisci(crlf, rt.blocco(ALTRI))
        self.assertNotIn("\r\r", nuovo)
        self.assertEqual(nuovo.count("\n"), nuovo.count("\r\n"))

    def test_senza_titolo_va_in_cima(self):
        nuovo = rt.inserisci("Solo testo.\n", rt.blocco([]))
        self.assertTrue(nuovo.startswith(rt.INIZIO))
        self.assertTrue(nuovo.endswith("Solo testo.\n"))


if __name__ == "__main__":
    unittest.main()

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


def _cento():
    # Gioco 0 e' uscito il 1 gennaio 2026, Gioco 99 il 10 aprile.
    tutte = [
        (f"Gioco{i}-Italian-Translation", f"Gioco {i}", f"gioco-{i}", f"2026-{1 + i // 31:02d}-{1 + i % 31:02d}T10:00:00Z")
        for i in range(100)
    ]
    return tutte + [("Vecchio-Italian-Translation", "Vecchio", "vecchio", "2025-06-01T10:00:00Z")]


class PiuRecenti(unittest.TestCase):
    """Con cento traduzioni il riquadro ne nomina cinque, le ultime uscite."""

    def test_le_cinque_piu_recenti_in_ordine(self):
        altri, totale = rt.da_mostrare(_cento(), "Vecchio-Italian-Translation")
        self.assertEqual([n for n, _ in altri], ["Gioco 99", "Gioco 98", "Gioco 97", "Gioco 96", "Gioco 95"])
        self.assertEqual(totale, 100)

    def test_non_nomina_se_stessa(self):
        altri, totale = rt.da_mostrare(_cento(), "Gioco99-Italian-Translation")
        self.assertNotIn("Gioco 99", [n for n, _ in altri])
        self.assertEqual(altri[0][0], "Gioco 98")
        self.assertEqual(totale, 100)

    def test_a_pari_data_ordine_di_nome(self):
        tutte = [
            ("B", "Beta", "beta", "2026-05-01T00:00:00Z"),
            ("A", "Alfa", "alfa", "2026-05-01T00:00:00Z"),
            ("C", "Gamma", "gamma", "2026-09-01T00:00:00Z"),
        ]
        altri, _ = rt.da_mostrare(tutte, "X")
        self.assertEqual([n for n, _ in altri], ["Gamma", "Alfa", "Beta"])

    def test_se_sono_di_piu_porta_al_sito(self):
        altri, totale = rt.da_mostrare(_cento(), "Vecchio-Italian-Translation")
        testo = rt.blocco(altri, totale)
        self.assertIn("le altre 100. Le più recenti:", testo)
        self.assertIn(f"[Guardale tutte]({rt.SITO}#giochi)", testo)
        self.assertEqual(testo.count(rt.SITO + "gioco-"), 5)

    def test_se_ci_stanno_tutte_niente_rimando(self):
        altri, totale = rt.da_mostrare(_cento()[:4], "X")
        self.assertNotIn("Guardale tutte", rt.blocco(altri, totale))


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

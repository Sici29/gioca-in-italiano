"""Copertine: risoluzione, normalizzazione e cache su disco.

Ordine delle fonti, dalla piu' autorevole:
  1. copertina scelta a mano dall'utente nell'hub
  2. cover_url dichiarato nel hub.json del repo
  3. AppID Steam dichiarato nel hub.json
  4. AppID trovato cercando il nome del gioco su Steam
  5. copertina generata (per i giochi che su Steam non ci sono, es. Star Citizen)

Qualunque immagine arrivi, viene normalizzata a 460x215 cosi' la griglia
resta coerente anche mescolando fonti diverse.
"""

from __future__ import annotations

import base64
import colorsys
import hashlib
import json
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from . import config, paths, steam

INDEX_NAME = "index.json"

# Ambra dell'hub: la tinta di ripiego quando dalla copertina non si ricava
# niente di utile (immagini in bianco e nero, o non ancora scaricate).
_TINTA_PREDEFINITA = "#ffb020"

# Font di sistema Windows, in ordine di preferenza per la copertina generata.
_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\bahnschrift.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\seguisb.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
)


# --- indice della cache ------------------------------------------------------


def _index_path() -> Path:
    return paths.covers_dir() / INDEX_NAME


def load_index() -> dict:
    try:
        with open(_index_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_index(index: dict) -> None:
    try:
        with open(_index_path(), "w", encoding="utf-8") as fh:
            json.dump(index, fh, indent=2)
    except OSError:
        pass


# Il catalogo risolve le copertine in parallelo: senza lock l'ultimo thread a
# salvare cancellerebbe le voci scritte dagli altri.
_INDEX_LOCK = threading.Lock()


def _record(repo: str, info: dict) -> dict:
    """Aggiorna una sola voce dell'indice, rileggendolo sotto lock."""
    with _INDEX_LOCK:
        index = load_index()
        index[repo] = info
        save_index(index)
    return info


def percorso(repo: str) -> Path:
    """Dove sta su disco la copertina di una traduzione."""
    return _cover_file(repo)


def _cover_file(repo: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in repo)
    return paths.covers_dir() / f"{safe}.jpg"


# --- normalizzazione ---------------------------------------------------------


def transparency_ratio(raw: bytes) -> float:
    """Quanta parte dell'immagine e' trasparente, da 0 a 1.

    Serve a distinguere una copertina da un logo: i siti ufficiali spesso
    pubblicano solo il marchio su fondo trasparente, e quello va trattato in
    modo diverso (vedi generate_cover).
    """
    from io import BytesIO

    try:
        img = Image.open(BytesIO(raw))
        img.load()
        if img.mode not in ("RGBA", "LA", "PA") and "transparency" not in img.info:
            return 0.0
        alpha = img.convert("RGBA").split()[3]
        histogram = alpha.histogram()
        total = sum(histogram) or 1
        # Consideriamo trasparente tutto cio' che e' sotto meta' opacita'.
        return sum(histogram[:128]) / total
    except Exception:
        return 0.0


def _normalise(raw: bytes, dest: Path) -> bool:
    """Porta qualunque immagine a 460x215 ritagliando al centro."""
    from io import BytesIO

    try:
        img = Image.open(BytesIO(raw))
        img.load()
    except Exception:
        return False

    try:
        # La trasparenza va fusa su un fondo scuro, non semplicemente buttata:
        # convertire RGBA in RGB rende neri i pixel trasparenti, ed e' cosi'
        # che il logo nero di Star Citizen finiva nero su nero.
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            backdrop = Image.new("RGBA", img.size, (11, 16, 21, 255))
            img = Image.alpha_composite(backdrop, img.convert("RGBA")).convert("RGB")
        elif img.mode != "RGB":
            img = img.convert("RGB")

        w, h = img.size
        # Per le verticali (600x900) il soggetto e' in alto: ritagliamo da li'
        # invece che dal centro geometrico, altrimenti si perde il logo.
        centering = (0.5, 0.35) if h > w else (0.5, 0.5)
        img = ImageOps.fit(img, config.COVER_SIZE, Image.LANCZOS, centering=centering)
        img.save(dest, "JPEG", quality=88, optimize=True)
        return True
    except Exception:
        return False


# --- copertina generata ------------------------------------------------------


def _font(size: int):
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


# Palette scelte a mano invece di una tinta qualsiasi presa dal giro dei
# colori: lasciare libera la tonalita' produceva anche verdi acidi e senapi
# che sembravano un errore di caricamento. Sono tutte scure e profonde, cosi'
# la copertina generata sta in griglia accanto a quelle vere di Steam senza
# stonare. (alto, basso, bagliore)
_PALETTES = (
    ((34, 40, 92), (11, 13, 32), (92, 118, 255)),    # indaco
    ((12, 60, 72), (6, 20, 30), (58, 190, 200)),     # petrolio
    ((62, 28, 66), (20, 10, 28), (186, 96, 220)),    # prugna
    ((16, 48, 92), (7, 16, 38), (70, 140, 255)),     # oceano
    ((84, 36, 26), (24, 12, 12), (240, 128, 72)),    # brace
    ((40, 48, 64), (14, 18, 26), (120, 150, 190)),   # ardesia
    ((18, 58, 48), (7, 22, 20), (64, 196, 150)),     # bosco
)


def _palette_for(name: str):
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return _PALETTES[digest[0] % len(_PALETTES)]


def _paste_logo(base: Image.Image, raw: bytes) -> tuple[Image.Image, bool]:
    """Disegna un marchio su fondo trasparente sopra la copertina generata.

    I siti ufficiali pubblicano spesso solo il logo, quasi sempre scuro perche'
    pensato per fondi chiari: usato com'e' sparirebbe. Qui si tiene solo la
    forma (il canale alfa) e la si ridipinge in chiaro.
    """
    from io import BytesIO

    try:
        logo = Image.open(BytesIO(raw))
        logo.load()
        alpha = logo.convert("RGBA").split()[3]

        # Via il bordo trasparente, altrimenti il marchio resta minuscolo
        # in mezzo a una tela enorme.
        box = alpha.getbbox()
        if not box:
            return base, False
        alpha = alpha.crop(box)

        w, h = base.size
        scale = min((w * 0.44) / alpha.width, (h * 0.66) / alpha.height)
        size = (max(1, int(alpha.width * scale)), max(1, int(alpha.height * scale)))
        alpha = alpha.resize(size, Image.LANCZOS)

        ink = Image.new("RGBA", size, (237, 244, 250, 255))
        ink.putalpha(alpha)

        canvas = base.convert("RGBA")
        canvas.alpha_composite(ink, (28, max(0, (h - size[1]) // 2 - 10)))
        return canvas.convert("RGB"), True
    except Exception:
        return base, False


def generate_cover(name: str, dest: Path, logo_raw: bytes | None = None) -> bool:
    """Copertina disegnata al volo, per i giochi che su Steam non ci sono.

    Deve sembrare una scelta, non un ripiego: sfumatura verticale profonda,
    un bagliore diagonale che da' volume, una trama tecnica appena accennata
    e il tricolore come firma della traduzione. La palette deriva dal nome,
    quindi lo stesso gioco ha sempre la stessa copertina.

    Con `logo_raw` il marchio ufficiale prende il posto del titolo scritto.
    """
    w, h = config.COVER_SIZE
    top, bottom, glow = _palette_for(name)

    try:
        base = Image.new("RGB", (w, h))
        draw = ImageDraw.Draw(base)

        for y in range(h):
            t = (y / max(h - 1, 1)) ** 0.85
            draw.line(
                [(0, y), (w, y)],
                fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)),
            )

        # Bagliore in alto a sinistra: disegnato piccolo, sfocato e poi
        # ingrandito. La sfocatura e' indispensabile, altrimenti l'ellisse
        # lascia un bordo netto che sembra un ritaglio male.
        small = Image.new("L", (96, 48), 0)
        sd = ImageDraw.Draw(small)
        sd.ellipse([-30, -36, 62, 40], fill=180)
        small = small.filter(ImageFilter.GaussianBlur(13))
        mask = small.resize((w, h), Image.BICUBIC).point(lambda v: int(v * 0.42))
        base = Image.composite(Image.new("RGB", (w, h), glow), base, mask)

        # Trama diagonale, quasi invisibile ma toglie la sensazione di piatto.
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        for x in range(-h, w + h, 26):
            od.line([(x, 0), (x + h, h)], fill=(255, 255, 255, 9), width=1)
        base = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")

        # Velatura scura in basso, cosi' il testo resta leggibile.
        shade = Image.new("L", (1, h), 0)
        for y in range(h):
            t = max(0.0, (y - h * 0.45) / (h * 0.55))
            shade.putpixel((0, y), int(165 * t * t))
        base = Image.composite(
            Image.new("RGB", (w, h), (0, 0, 0)), base, shade.resize((w, h))
        )
        # Se abbiamo il marchio ufficiale lo usiamo al posto del titolo scritto.
        drew_logo = False
        if logo_raw:
            base, drew_logo = _paste_logo(base, logo_raw)
        draw = ImageDraw.Draw(base)

        if not drew_logo:
            # Titolo: si rimpicciolisce finche' non entra nella larghezza utile.
            label = name.upper()
            size = 42
            font = _font(size)
            while size > 15:
                font = _font(size)
                if draw.textlength(label, font=font) <= w - 56:
                    break
                size -= 2

            draw.text((28, h - 78), label, font=font, fill=(247, 250, 253))

        sub = _font(13)
        draw.text((30, h - 34), "TRADUZIONE ITALIANA", font=sub, fill=(255, 255, 255))

        # Firma tricolore, in basso accanto alla dicitura.
        base_x = 30 + int(draw.textlength("TRADUZIONE ITALIANA", font=sub)) + 14
        for i, colour in enumerate(((0, 140, 69), (238, 240, 235), (205, 33, 42))):
            draw.rectangle(
                [base_x + i * 9, h - 30, base_x + 6 + i * 9, h - 24], fill=colour
            )

        base.save(dest, "JPEG", quality=92, optimize=True)
        return True
    except Exception:
        return False


# --- risoluzione -------------------------------------------------------------


def ensure_cover(
    repo: str,
    game_name: str,
    appid: int | None = None,
    cover_url: str | None = None,
    custom_path: str | None = None,
    allow_search: bool = True,
    force: bool = False,
) -> tuple[Path | None, dict]:
    """Restituisce (percorso copertina, info su come e' stata ottenuta).

    `allow_search=False` vieta la ricerca per nome su Steam: si usa quando il
    hub.json dichiara esplicitamente "steam_appid": null, cioe' "questo gioco
    su Steam non c'e'" (il caso di Star Citizen).
    """
    entry = load_index().get(repo) or {}
    dest = _cover_file(repo)
    now = int(time.time())

    # Copertina scelta a mano: vince sempre e non scade.
    if custom_path:
        src = Path(custom_path)
        if src.exists():
            try:
                if _normalise(src.read_bytes(), dest):
                    return dest, _record(
                        repo, {"source": "custom", "origin": str(src), "ts": now}
                    )
            except OSError:
                pass

    fresh = (
        dest.exists()
        and entry.get("ts")
        and (now - float(entry["ts"])) < config.COVER_TTL_DAYS * 86400
    )
    # Anche una copertina generata viene ritentata su Steam alla scadenza:
    # nel frattempo il gioco potrebbe essere uscito.
    if fresh and not force:
        return dest, entry

    # 2. URL esplicito nel hub.json
    logo_raw: bytes | None = None
    logo_origine = ""
    cover_url_morto = False
    if cover_url:
        raw = steam.download(cover_url)
        if not raw:
            # Un link che non risponde piu' va detto, altrimenti resta li' per
            # mesi e la copertina non arriva mai senza che nessuno sappia perche'.
            cover_url_morto = True
        if raw:
            if transparency_ratio(raw) > 0.25:
                # E' un marchio su fondo trasparente, non una copertina: lo
                # teniamo da parte e lo comporremo sullo sfondo generato. E'
                # il caso di Star Citizen, il cui sito ufficiale pubblica il
                # logo e nient'altro.
                logo_raw = raw
                logo_origine = cover_url
            elif _normalise(raw, dest):
                return dest, _record(
                    repo, {"source": "hub.json", "origin": cover_url, "ts": now}
                )

    # 3/4. Steam: AppID dichiarato, oppure cercato per nome se concesso
    resolved = appid
    mismatch = False
    if resolved is not None and steam.verify_appid(resolved, game_name) is False:
        # L'AppID scritto nel hub.json punta a un altro gioco: lo scartiamo.
        mismatch = True
        resolved = None
    if resolved is None and allow_search:
        resolved = steam.search_appid(game_name)
    if resolved:
        for url in steam.cover_candidates(resolved):
            raw = steam.download(url)
            if raw and _normalise(raw, dest):
                return dest, _record(
                    repo,
                    {
                        "source": "steam",
                        "appid": resolved,
                        "origin": url,
                        "ts": now,
                        "appid_mismatch": mismatch,
                        "cover_url_morto": cover_url_morto,
                    },
                )

    # 4-bis. Nessun riscontro su Steam: proviamo la fonte ufficiale nota per
    # i giochi che su Steam non ci sono proprio (Star Citizen e simili).
    if logo_raw is None:
        ufficiale = config.official_cover(game_name)
        if ufficiale:
            raw = steam.download(ufficiale)
            if raw:
                if transparency_ratio(raw) > 0.25:
                    logo_raw = raw
                    logo_origine = ufficiale
                elif _normalise(raw, dest):
                    return dest, _record(
                        repo,
                        {
                            "source": "sito ufficiale",
                            "origin": ufficiale,
                            "ts": now,
                            "appid_mismatch": mismatch,
                            "cover_url_morto": cover_url_morto,
                        },
                    )

    # 5. Ripiego generato, con il marchio ufficiale se lo abbiamo
    if generate_cover(game_name, dest, logo_raw=logo_raw):
        return dest, _record(
            repo,
            {
                "source": "logo ufficiale" if logo_raw else "generata",
                # L'origine deve essere quella vera del marchio usato, non il
                # cover_url del hub.json che poteva anche non aver risposto.
                "origin": logo_origine,
                "ts": now,
                "appid_mismatch": mismatch,
                "cover_url_morto": cover_url_morto,
            },
        )

    return (dest if dest.exists() else None), entry


# --- tinta dominante ---------------------------------------------------------
#
# Ogni copertina cede il suo colore all'interfaccia: bordo e alone della card,
# sfondo del pannello dei dettagli. E' il dettaglio che fa sembrare la griglia
# fatta su misura per quei giochi invece che un elenco con delle immagini
# dentro, e non costa niente perche' Pillow c'e' gia'.

# Dove finisce il colore estratto: abbastanza acceso da vedersi sul grafite,
# abbastanza scuro da non bucare lo schermo.
_SATURAZIONE_MINIMA = 0.55
_LUMINOSITA_TINTA = 0.74

_TINTE: dict[tuple[str, float], str] = {}


def _in_banda(r: int, g: int, b: int) -> str:
    """Riporta un colore qualsiasi nella banda che l'interfaccia sa reggere."""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    s = max(s, _SATURAZIONE_MINIMA)
    rr, gg, bb = colorsys.hsv_to_rgb(h, s, _LUMINOSITA_TINTA)
    return "#%02x%02x%02x" % (round(rr * 255), round(gg * 255), round(bb * 255))


def tinta(path: Path | None) -> str:
    """Colore dominante della copertina, in esadecimale.

    Non e' la media dei pixel: farebbe un fango grigio su qualunque immagine.
    Si raggruppano i colori simili, si buttano neri, bianchi e grigi - che non
    sono una tinta - e fra i restanti vince quello che occupa piu' spazio
    *ed* e' piu' vivo. Se non ne resta nessuno (copertina in bianco e nero),
    si torna all'ambra dell'hub, che e' sempre una risposta giusta.
    """
    if not path:
        return _TINTA_PREDEFINITA
    try:
        chiave = (str(path), path.stat().st_mtime)
    except OSError:
        return _TINTA_PREDEFINITA
    if chiave in _TINTE:
        return _TINTE[chiave]

    colore = _TINTA_PREDEFINITA
    try:
        img = Image.open(path)
        img.load()
        img = img.convert("RGB").resize((48, 24), Image.BILINEAR)
        ridotta = img.quantize(colors=8, method=Image.MEDIANCUT).convert("RGB")

        migliore = -1.0
        for quanti, rgb in ridotta.getcolors(48 * 24) or []:
            _, s, v = colorsys.rgb_to_hsv(*[c / 255 for c in rgb])
            if v < 0.12 or s < 0.15:
                continue  # nero, bianco o grigio: non e' una tinta
            # La radice smorza l'area: un colore che copre mezza immagine conta
            # piu' di uno raro, ma non dieci volte tanto, altrimenti vincerebbe
            # sempre il cielo di sfondo.
            punteggio = (quanti ** 0.5) * (0.35 + s) * (0.4 + min(v, 0.9))
            if punteggio > migliore:
                migliore, colore = punteggio, _in_banda(*rgb)
    except Exception:
        colore = _TINTA_PREDEFINITA

    # La cache tiene solo l'ultima manciata: le copertine sono poche e il
    # dizionario non deve crescere a ogni ricontrollo.
    if len(_TINTE) > 64:
        _TINTE.clear()
    _TINTE[chiave] = colore
    return colore


def data_uri(path: Path | None) -> str:
    """L'immagine viaggia verso la UI come data URI: niente problemi di
    protocollo file:// dentro la webview."""
    if not path or not path.exists():
        return ""
    try:
        raw = path.read_bytes()
    except OSError:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii")


def clear_cache() -> int:
    """Cancella copertine e indice. Torna quante immagini sono state tolte."""
    tolte = 0
    with _INDEX_LOCK:
        for file in paths.covers_dir().glob("*.jpg"):
            try:
                file.unlink()
                tolte += 1
            except OSError:
                pass
        try:
            _index_path().unlink(missing_ok=True)
        except OSError:
            pass
    return tolte

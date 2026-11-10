"""Sestavljanje povezav do arhivskih strani Matricula Online.

Logika je združljiva s prejšnjo delujočo različico programa:
- Borovnica -> ljubljanska nadškofija
- ostale župnije -> mariborska nadškofija
- številka slike se prenese v parameter pg.

Opomba: to je obstoječe pravilo aplikacije, ne splošna geografska
preslikava vseh slovenskih župnij.
"""

import re

MATRICULA_BASE = "https://data.matricula-online.eu/sl/slovenia"


def matricula_url(podatki):
    """Vrne neposredno povezavo do knjige in slike ali None, če ni podatkov."""
    if not isinstance(podatki, dict):
        return None

    # Enaka normalizacija kot v prvotni delujoči različici: ime župnije
    # je bilo v URL-ju zapisano z malimi črkami, ime knjige pa nespremenjeno.
    zupnija = str(podatki.get("zupnija") or "").strip().lower()
    knjiga = str(podatki.get("knjiga") or "").strip()
    if not zupnija or not knjiga:
        return None

    # Ohranimo izvorno pravilo stare različice, da se ne spremeni cilj URL-ja.
    nadskofija = "ljubljana" if "borovnica" in zupnija else "maribor"
    url = f"{MATRICULA_BASE}/{nadskofija}/{zupnija}/{knjiga}/"

    # Polje slika vsebuje številko skena, ki jo je uporabljala stara različica.
    slika = str(podatki.get("slika") or "").strip()
    slika_stevilka = "".join(re.findall(r"\d", slika))
    if slika_stevilka:
        url += f"?pg={slika_stevilka}"
    return url

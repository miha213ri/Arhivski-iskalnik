"""Izvoz ene zgrajene osebe v GEDCOM 5.5.1.

Podatki se izvozijo kot posamezni INDI, FAM in SOUR zapisi. Neznanih
podatkov ne ugibamo; neprepoznani datumi ostanejo v besedilu vira.
"""

from datetime import datetime
import re
import unicodedata

from .arhivske_povezave import matricula_url


GEDCOM_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

MONTHS = {
    "jan": "JAN", "januar": "JAN", "january": "JAN", "januarii": "JAN",
    "feb": "FEB", "februar": "FEB", "february": "FEB", "februarii": "FEB",
    "mar": "MAR", "marec": "MAR", "march": "MAR", "martii": "MAR",
    "apr": "APR", "april": "APR", "aprilis": "APR",
    "maj": "MAY", "may": "MAY", "maii": "MAY",
    "jun": "JUN", "junij": "JUN", "june": "JUN", "junii": "JUN",
    "jul": "JUL", "julij": "JUL", "july": "JUL", "julii": "JUL",
    "avg": "AUG", "avgust": "AUG", "aug": "AUG", "august": "AUG", "augusti": "AUG",
    "sep": "SEP", "september": "SEP", "septembris": "SEP",
    "okt": "OCT", "oktober": "OCT", "oct": "OCT", "october": "OCT", "octobris": "OCT",
    "nov": "NOV", "november": "NOV", "novembris": "NOV",
    "dec": "DEC", "december": "DEC", "decembris": "DEC",
}


class GedcomExportError(ValueError):
    """Napaka pri pripravi GEDCOM izvoza."""


def _text(value):
    if value is None:
        return ""
    value = str(value).replace("\x00", " ")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(part.strip() for part in value.split("\n")).strip()


def _ged_escape(value):
    """GEDCOM uporablja @@ za dobesedni znak @ v besedilnih vrednostih."""
    return _text(value).replace("@", "@@")


def _split_long(value, max_len=210):
    """Razdeli dolgo besedilo po besedah brez izgube vsebine."""
    value = _ged_escape(value)
    pieces = []
    for paragraph in value.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            pieces.append("")
            continue
        while len(paragraph) > max_len:
            cut = paragraph.rfind(" ", 0, max_len + 1)
            if cut <= 0:
                cut = max_len
            pieces.append(paragraph[:cut])
            paragraph = paragraph[cut:].lstrip()
        pieces.append(paragraph)
    return pieces


def _add(lines, level, tag, value=None):
    """Doda GEDCOM vrstico in po potrebi CONT vrstice."""
    if value is None:
        lines.append(f"{level} {tag}")
        return
    chunks = _split_long(value)
    if not chunks:
        return
    lines.append(f"{level} {tag} {chunks[0]}" if chunks[0] else f"{level} {tag}")
    for chunk in chunks[1:]:
        lines.append(f"{level + 1} CONT {chunk}" if chunk else f"{level + 1} CONT")


def _add_pointer(lines, level, tag, pointer):
    """Doda referenco; znaka @ pri kazalcih se ne escapata."""
    lines.append(f"{level} {tag} @{pointer}@")


def _first(*values):
    for value in values:
        value = _text(value)
        if value:
            return value
    return ""


def _person_name(record, kind):
    if not record:
        return "", ""
    if kind == "krsti":
        given = _first(record.get("ime_otroka"))
        surname = _first(record.get("priimek_otroka"), record.get("priimek_oceta"), record.get("alt_priimek_oceta"))
    elif kind == "mrtvi":
        given = _first(record.get("ime_pokojnika"))
        surname = _first(record.get("priimek_pokojnika"))
    else:
        given = surname = ""
    return given, surname


def _marriage_party(record, role):
    if role == "groom":
        return _first(record.get("ime_zenina")), _first(record.get("priimek_zenina"))
    if role == "bride":
        return _first(record.get("ime_neveste")), _first(record.get("priimek_neveste"))
    return "", ""


def suggest_marriage_role(bundle):
    """Vrne 'groom' ali 'bride' samo ob natančnem ujemanju imena; sicer None."""
    marriage = bundle.get("poroke") or {}
    if not marriage:
        return None

    candidates = []
    for kind in ("krsti", "mrtvi"):
        row = bundle.get(kind) or {}
        given, surname = _person_name(row, kind)
        if given or surname:
            candidates.append(_norm_name(f"{given} {surname}"))

    groom = _norm_name(f"{_first(marriage.get('ime_zenina'))} {_first(marriage.get('priimek_zenina'))}")
    bride = _norm_name(f"{_first(marriage.get('ime_neveste'))} {_first(marriage.get('priimek_neveste'))}")
    groom_match = any(candidate and candidate == groom for candidate in candidates)
    bride_match = any(candidate and candidate == bride for candidate in candidates)
    if groom_match and not bride_match:
        return "groom"
    if bride_match and not groom_match:
        return "bride"
    return None


def _norm_name(value):
    value = unicodedata.normalize("NFKD", _text(value).casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _ged_date(value):
    """Pretvori samo prepoznavne datume; sicer vrne prazen niz."""
    raw = _text(value)
    if not raw:
        return ""

    # Leto ali datum ISO / številčni datum.
    match = re.fullmatch(r"(\d{4})", raw)
    if match and int(match.group(1)) > 0:
        return str(int(match.group(1)))

    patterns = (
        r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})",
        r"(\d{1,2})[. /-]+(\d{1,2})[. /-]+(\d{4})",
    )
    for index, pattern in enumerate(patterns):
        match = re.fullmatch(pattern, raw)
        if match:
            if index == 0:
                year, month, day = map(int, match.groups())
            else:
                day, month, year = map(int, match.groups())
            try:
                datetime(year, month, day)
            except ValueError:
                return ""
            return f"{day} {GEDCOM_MONTHS[month - 1]} {year}"

    cleaned = re.sub(r"[,]+", " ", raw.casefold())
    cleaned = re.sub(r"[.]+", " ", cleaned)
    tokens = cleaned.split()
    if len(tokens) == 3:
        # d month yyyy
        if tokens[1] in MONTHS and tokens[0].isdigit() and tokens[2].isdigit():
            day, year = int(tokens[0]), int(tokens[2])
            if 1000 <= year <= 2999:
                try:
                    datetime(year, list(GEDCOM_MONTHS).index(MONTHS[tokens[1]]) + 1, day)
                except ValueError:
                    pass
                else:
                    return f"{day} {MONTHS[tokens[1]]} {year}"
        # month d yyyy
        if tokens[0] in MONTHS and tokens[1].isdigit() and tokens[2].isdigit():
            day, year = int(tokens[1]), int(tokens[2])
            if 1000 <= year <= 2999:
                try:
                    datetime(year, list(GEDCOM_MONTHS).index(MONTHS[tokens[0]]) + 1, day)
                except ValueError:
                    pass
                else:
                    return f"{day} {MONTHS[tokens[0]]} {year}"
    if len(tokens) == 2 and tokens[0] in MONTHS and tokens[1].isdigit():
        year = int(tokens[1])
        if 1000 <= year <= 2999:
            return f"{MONTHS[tokens[0]]} {year}"
    return ""


def _name_value(given, surname):
    given = _text(given).replace("/", "-")
    surname = _text(surname).replace("/", "-")
    if surname:
        return f"{given} /{surname}/".strip()
    return given or "Neznano ime"


def _event_date(lines, level, value, raw_note_target=None):
    converted = _ged_date(value)
    if converted:
        _add(lines, level, "DATE", converted)
    elif _text(value) and raw_note_target is not None:
        raw_note_target.append(f"Datum v izvornem zapisu: {_text(value)}")


def _source_page(row):
    parts = []
    if _text(row.get("knjiga")):
        parts.append(f"Knjiga: {_text(row.get('knjiga'))}")
    if _text(row.get("slika")):
        parts.append(f"Slika: {_text(row.get('slika'))}")
    if _text(row.get("vpis_st_knjige")):
        parts.append(f"Vpis št.: {_text(row.get('vpis_st_knjige'))}")
    if _text(row.get("vpis_st_na_strani")):
        parts.append(f"Stran/vpis: {_text(row.get('vpis_st_na_strani'))}")
    url = matricula_url(row)
    if url:
        parts.append(f"URL: {url}")
    return "; ".join(parts)


def _source_title(label, row):
    parish = _text(row.get("zupnija"))
    book = _text(row.get("knjiga"))
    suffix = " – ".join(part for part in (parish, book) if part)
    return f"{label}: {suffix}" if suffix else label


def _source_text(row):
    fields = []
    # Izvoz vseh napolnjenih stolpcev pomeni, da ob spremembi sheme ne izgubimo
    # novih ali še nepoznanih arhivskih polj.
    for key, raw_value in row.items():
        value = _text(raw_value)
        if value:
            fields.append(f"{key.replace('_', ' ').capitalize()}: {value}")
    return "\n".join(fields)


def build_gedcom(bundle, marriage_role=None):
    """Zgradi GEDCOM 5.5.1 besedilo za eno zgrajeno osebo.

    marriage_role: 'groom', 'bride' ali None (vloga ni določena).
    bundle: slovar z ključi oseba, krsti, poroke, mrtvi.
    """
    bundle = bundle or {}
    baptism = bundle.get("krsti") or None
    marriage = bundle.get("poroke") or None
    death = bundle.get("mrtvi") or None
    if marriage_role not in (None, "groom", "bride"):
        raise GedcomExportError("Vloga pri poroki mora biti 'groom', 'bride' ali None.")

    given, surname = _person_name(baptism, "krsti") if baptism else ("", "")
    if death:
        death_given, death_surname = _person_name(death, "mrtvi")
        # Povežena zapisa se dopolnjujeta: manjkajoč del imena lahko
        # prevzamemo iz drugega zapisa, ne prepisujemo pa obstoječega podatka.
        given = given or death_given
        surname = surname or death_surname
    if not (given or surname) and marriage and marriage_role:
        given, surname = _marriage_party(marriage, marriage_role)
    if not (given or surname):
        raise GedcomExportError(
            "Iz povezanih zapisov ni mogoče določiti imena osebe. "
            "Ker je na voljo samo poročni zapis, moraš izbrati ženina ali nevesto."
        )

    # Determinirani identifikatorji omogočajo pregledne in ponovljive povezave.
    main_id = "I1"
    lines = []
    _add(lines, 0, "HEAD")
    _add(lines, 1, "SOUR", "ARHIVSKI_ISKALNIK")
    _add(lines, 2, "NAME", "Arhivski iskalnik")
    _add(lines, 2, "VERS", "1.0.5")
    _add(lines, 1, "DEST", "ANY")
    today = datetime.now()
    _add(lines, 1, "DATE", f"{today.day} {GEDCOM_MONTHS[today.month - 1]} {today.year}")
    _add_pointer(lines, 1, "SUBM", "SUBM")
    _add(lines, 1, "GEDC")
    _add(lines, 2, "VERS", "5.5.1")
    _add(lines, 2, "FORM", "LINEAGE-LINKED")
    _add(lines, 1, "CHAR", "UTF-8")
    _add(lines, 1, "LANG", "Slovenian")
    _add(lines, 0, "@SUBM@ SUBM")
    _add(lines, 1, "NAME", "Arhivski iskalnik")

    source_ids = {}
    source_rows = (("krsti", baptism, "Krstna matična knjiga"),
                   ("poroke", marriage, "Poročna matična knjiga"),
                   ("mrtvi", death, "Mrliška matična knjiga"))
    for idx, (key, row, label) in enumerate(source_rows, start=1):
        if row:
            source_ids[key] = f"S{idx}"

    main_lines = []
    _add(main_lines, 0, f"@{main_id}@ INDI")
    _add(main_lines, 1, "NAME", _name_value(given, surname))

    # Spol določimo samo, če je vloga pri poroki izrecno potrjena.
    sex = "M" if marriage and marriage_role == "groom" else "F" if marriage and marriage_role == "bride" else "U"
    _add(main_lines, 1, "SEX", sex)

    # Če sta krst in smrt povezana, morebitno drugače zapisano ime ohranimo kot alias.
    if baptism and death:
        death_name = _person_name(death, "mrtvi")
        if any(death_name) and _norm_name(" ".join(death_name)) != _norm_name(f"{given} {surname}"):
            _add(main_lines, 1, "NAME", _name_value(*death_name))
            _add(main_lines, 2, "TYPE", "also known as")

    if baptism:
        birth_notes = []
        birth_date = baptism.get("datum_rojstva")
        # Župnija krstne knjige je kraj vpisa/krsta, ne nujno kraj rojstva.
        # BIRT zato dobi datum rojstva, lokacije pa ne ugibamo.
        if _ged_date(birth_date):
            _add(main_lines, 1, "BIRT")
            _event_date(main_lines, 2, birth_date, birth_notes)
            if "krsti" in source_ids:
                _add_pointer(main_lines, 2, "SOUR", source_ids["krsti"])
                page = _source_page(baptism)
                if page:
                    _add(main_lines, 3, "PAGE", page)
            for note in birth_notes:
                _add(main_lines, 2, "NOTE", note)

        baptism_notes = []
        baptism_date = baptism.get("datum_krsta")
        if _ged_date(baptism_date) or _text(baptism.get("zupnija")):
            _add(main_lines, 1, "CHR")
            _event_date(main_lines, 2, baptism_date, baptism_notes)
            if _text(baptism.get("zupnija")):
                _add(main_lines, 2, "PLAC", baptism.get("zupnija"))
            if "krsti" in source_ids:
                _add_pointer(main_lines, 2, "SOUR", source_ids["krsti"])
                page = _source_page(baptism)
                if page:
                    _add(main_lines, 3, "PAGE", page)
            for note in baptism_notes:
                _add(main_lines, 2, "NOTE", note)

    if death:
        death_notes = []
        death_date = death.get("datum_smrti")
        # Župnija mrliške knjige sama po sebi ne dokazuje kraja smrti.
        if _ged_date(death_date) or _text(death.get("vzrok_smrti")):
            deat_assertion = "Y" if not _ged_date(death_date) else None
            _add(main_lines, 1, "DEAT", deat_assertion)
            _event_date(main_lines, 2, death_date, death_notes)
            if _text(death.get("vzrok_smrti")):
                _add(main_lines, 2, "CAUS", death.get("vzrok_smrti"))
            if "mrtvi" in source_ids:
                _add_pointer(main_lines, 2, "SOUR", source_ids["mrtvi"])
                page = _source_page(death)
                if page:
                    _add(main_lines, 3, "PAGE", page)
            for note in death_notes:
                _add(main_lines, 2, "NOTE", note)

        burial_date = death.get("datum_pokopa")
        if _ged_date(burial_date):
            _add(main_lines, 1, "BURI")
            _add(main_lines, 2, "DATE", _ged_date(burial_date))
            if "mrtvi" in source_ids:
                _add_pointer(main_lines, 2, "SOUR", source_ids["mrtvi"])
                page = _source_page(death)
                if page:
                    _add(main_lines, 3, "PAGE", page)

    # Glavna oseba je povezana tudi z vsakim virom, če določen datum ni bil
    # pretvorljiv v standardni GEDCOM DATE in zato ni bilo mogoče ustvariti dogodka.
    for source_key, source_id in source_ids.items():
        if source_key == "krsti" and baptism:
            already = any(f"SOUR @{source_id}@" in line for line in main_lines)
        elif source_key == "poroke" and marriage and marriage_role is not None:
            already = True  # Poročni vir je vezan na družinski MARR dogodek.
        elif source_key == "poroke" and marriage:
            already = any(f"SOUR @{source_id}@" in line for line in main_lines)
        elif source_key == "mrtvi" and death:
            already = any(f"SOUR @{source_id}@" in line for line in main_lines)
        else:
            already = False
        if not already:
            _add_pointer(main_lines, 1, "SOUR", source_id)
            row = bundle.get(source_key) or {}
            page = _source_page(row)
            if page:
                _add(main_lines, 2, "PAGE", page)

    # Starši iz krstnega zapisa: zgradimo družino samo iz izrecno zapisanih imen.
    parent_family_lines = []
    father_name = mother_name = ""
    if baptism:
        father_name = _name_value(baptism.get("ime_oceta"), _first(baptism.get("priimek_oceta"), baptism.get("alt_priimek_oceta"))) if _first(baptism.get("ime_oceta"), baptism.get("priimek_oceta")) else ""
        mother_name = _name_value(baptism.get("ime_matere"), _first(baptism.get("priimek_matere"))) if _first(baptism.get("ime_matere"), baptism.get("priimek_matere")) else ""
    parent_family_exists = bool(father_name or mother_name)
    if parent_family_exists:
        parent_family_lines = ["0 @F1@ FAM"]
        if father_name:
            parent_family_lines.append("1 HUSB @I2@")
        if mother_name:
            parent_family_lines.append("1 WIFE @I3@")
        parent_family_lines.append("1 CHIL @I1@")
        # Krstni vir dokazuje tudi razmerje med otrokom in navedenimi starši.
        if "krsti" in source_ids:
            _add_pointer(parent_family_lines, 1, "SOUR", source_ids["krsti"])
            page = _source_page(baptism)
            if page:
                _add(parent_family_lines, 2, "PAGE", page)
        _add_pointer(main_lines, 1, "FAMC", "F1")

    # Poročni zapis je družinska povezava le, kadar sta vloga osebe in partner
    # določljiva. Sicer ga ohranimo kot dogodek/virovni dokaz brez izmišljene vezi.
    spouse_lines = []
    spouse_family_lines = []
    if marriage:
        groom_given = _first(marriage.get("ime_zenina"))
        groom_surname = _first(marriage.get("priimek_zenina"))
        bride_given = _first(marriage.get("ime_neveste"))
        bride_surname = _first(marriage.get("priimek_neveste"))
        groom_name = _name_value(groom_given, groom_surname)
        bride_name = _name_value(bride_given, bride_surname)

        spouse_given, spouse_surname = (bride_given, bride_surname) if marriage_role == "groom" else (groom_given, groom_surname)
        if marriage_role and (spouse_given or spouse_surname):
            spouse_id = "I4"
            spouse_name = _name_value(spouse_given, spouse_surname)
            spouse_sex = "F" if marriage_role == "groom" else "M"
            if marriage_role == "groom":
                spouse_family_lines = ["0 @F2@ FAM", "1 HUSB @I1@", f"1 WIFE @{spouse_id}@"]
            else:
                spouse_family_lines = ["0 @F2@ FAM", f"1 HUSB @{spouse_id}@", "1 WIFE @I1@"]
            spouse_lines.append(f"0 @{spouse_id}@ INDI")
            _add(spouse_lines, 1, "NAME", spouse_name)
            _add(spouse_lines, 1, "SEX", spouse_sex)
            _add_pointer(spouse_lines, 1, "FAMS", "F2")
            _add_pointer(main_lines, 1, "FAMS", "F2")
            spouse_family_lines.append("1 MARR")
            converted_date = _ged_date(marriage.get("datum_poroke"))
            if converted_date:
                _add(spouse_family_lines, 2, "DATE", converted_date)
            elif _text(marriage.get("datum_poroke")):
                _add(spouse_family_lines, 2, "NOTE", f"Datum v izvornem zapisu: {_text(marriage.get('datum_poroke'))}")
            if _text(marriage.get("zupnija")):
                _add(spouse_family_lines, 2, "PLAC", marriage.get("zupnija"))
            if "poroke" in source_ids:
                _add_pointer(spouse_family_lines, 2, "SOUR", source_ids["poroke"])
                page = _source_page(marriage)
                if page:
                    _add(spouse_family_lines, 3, "PAGE", page)
        else:
            _add(main_lines, 1, "EVEN")
            _add(main_lines, 2, "TYPE", "Church marriage record – role or spouse not identified")
            converted_date = _ged_date(marriage.get("datum_poroke"))
            if converted_date:
                _add(main_lines, 2, "DATE", converted_date)
            elif _text(marriage.get("datum_poroke")):
                _add(main_lines, 2, "NOTE", f"Datum v izvornem zapisu: {_text(marriage.get('datum_poroke'))}")
            if _text(marriage.get("zupnija")):
                _add(main_lines, 2, "PLAC", marriage.get("zupnija"))
            _add(main_lines, 2, "NOTE", f"Ženin: {groom_name}; nevesta: {bride_name}")
            if "poroke" in source_ids:
                _add_pointer(main_lines, 2, "SOUR", source_ids["poroke"])
                page = _source_page(marriage)
                if page:
                    _add(main_lines, 3, "PAGE", page)

    # Opombe iz kartoteke zgrajene osebe.
    person_record = bundle.get("oseba") or {}
    if _text(person_record.get("opombe")):
        _add(main_lines, 1, "NOTE", person_record.get("opombe"))

    lines.extend(main_lines)

    # Starša kot samostojne INDI zapise. Nepoznani starš se ne izmišlja.
    if father_name:
        lines.append("0 @I2@ INDI")
        _add(lines, 1, "NAME", father_name)
        _add(lines, 1, "SEX", "M")
        _add_pointer(lines, 1, "FAMS", "F1")
    if mother_name:
        lines.append("0 @I3@ INDI")
        _add(lines, 1, "NAME", mother_name)
        _add(lines, 1, "SEX", "F")
        _add_pointer(lines, 1, "FAMS", "F1")
    if parent_family_exists:
        lines.extend(parent_family_lines)
    if spouse_lines:
        lines.extend(spouse_lines)
    if spouse_family_lines:
        lines.extend(spouse_family_lines)

    # Virni zapisi vsebujejo izvor, lokacijo skena in prepis/ostale pomembne podatke.
    for key, row, label in source_rows:
        if not row:
            continue
        source_id = source_ids[key]
        lines.append(f"0 @{source_id}@ SOUR")
        _add(lines, 1, "TITL", _source_title(label, row))
        _add(lines, 1, "PUBL", "Matricula Online – digitalni arhiv matičnih knjig")
        page = _source_page(row)
        if page:
            _add(lines, 1, "NOTE", page)
        text = _source_text(row)
        if text:
            _add(lines, 1, "TEXT", text)

    lines.append("0 TRLR")
    # Ne dodajamo praznih vrstic med zapise; CRLF je najširše združljiv.
    return "\r\n".join(lines) + "\r\n"


def export_gedcom(bundle, filepath, marriage_role=None):
    """Zapiše GEDCOM v UTF-8 z BOM, primerno za slovenske znake v večini orodij."""
    content = build_gedcom(bundle, marriage_role=marriage_role)
    with open(filepath, "w", encoding="utf-8-sig", newline="") as handle:
        handle.write(content)
    return filepath

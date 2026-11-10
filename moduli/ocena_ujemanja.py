"""Razložljiva ocena podobnosti zapisov z ločeno logiko za osebo in družino.

Ocena je hevristična podpora pri raziskovanju, ne statistično potrjena verjetnost.
"""

from difflib import SequenceMatcher
import re
import unicodedata

from .nastavitve_ujemanja import DEFAULT_RULES


WEIGHTS = DEFAULT_RULES["weights"]["manual"]


def _norm(value):
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _year(value):
    match = re.search(r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def _date_key(value):
    """Vrne (leto, mesec, dan); pri nepopolnem datumu ohrani samo znane dele."""
    text = str(value or "").strip()
    if not text:
        return None
    match = re.search(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)", text)
    if match:
        return tuple(map(int, match.groups()))
    match = re.search(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](\d{4})(?!\d)", text)
    if match:
        day, month, year = map(int, match.groups())
        return year, month, day
    year = _year(text)
    return (year, None, None) if year else None


def _compare_dates(left, right):
    """-1: left pred right, 0: enako/isto znano leto, 1: left za right, None: neznano."""
    a, b = _date_key(left), _date_key(right)
    if not a or not b:
        return None
    for index in range(3):
        if a[index] is None or b[index] is None:
            # Če se znano leto razlikuje, lahko še vedno določimo smer.
            if index == 0 and a[0] != b[0]:
                return -1 if a[0] < b[0] else 1
            return 0
        if a[index] != b[index]:
            return -1 if a[index] < b[index] else 1
    return 0


def _same_complete_date(left, right):
    a, b = _date_key(left), _date_key(right)
    return bool(a and b and all(part is not None for part in a + b) and a == b)


def _similarity(a, b):
    left, right = _norm(a), _norm(b)
    if not left or not right:
        return None
    if left == right:
        return 1.0
    ratio = SequenceMatcher(None, left, right).ratio()
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if left_tokens and right_tokens:
        ratio = max(ratio, len(left_tokens & right_tokens) / len(left_tokens | right_tokens))
    return ratio


def _best_pair(values):
    """Najde najboljše ujemanje med različnimi izvornimi knjigami."""
    pairs = []
    for index, (label_a, value_a) in enumerate(values):
        for label_b, value_b in values[index + 1:]:
            if label_a.split(" – ", 1)[0] == label_b.split(" – ", 1)[0]:
                continue
            score = _similarity(value_a, value_b)
            if score is not None:
                pairs.append((score, label_a, value_a, label_b, value_b))
    return max(pairs, key=lambda item: item[0]) if pairs else None


def _age_years(value):
    text = _norm(value)
    if not text:
        return None
    years = re.search(r"(\d+)\s*(?:let|leta|leto|l|years|year|y)\b", text)
    months = re.search(r"(\d+)\s*(?:mesec|mesecev|meseci|m|months|month)\b", text)
    days = re.search(r"(\d+)\s*(?:dan|dni|days|day|d)\b", text)
    if years or months or days:
        return (int(years.group(1)) if years else 0) + (int(months.group(1)) / 12 if months else 0) + (int(days.group(1)) / 365 if days else 0)
    numbers = re.findall(r"\d+", text)
    if len(numbers) == 1:
        return float(numbers[0])
    return None


def _age_match(expected, observed):
    if expected is None or observed is None:
        return None
    difference = abs(float(expected) - float(observed))
    if difference <= 2:
        return 1.0
    if difference <= 5:
        return 0.75
    if difference <= 10:
        return 0.4
    if difference <= 15:
        return 0.15
    return 0.0


def _participant_for_death(poroke, mrtvi):
    if not poroke or not mrtvi:
        return None
    death_name = mrtvi.get("ime_pokojnika")
    death_surname = mrtvi.get("priimek_pokojnika")
    choices = []
    for role, name_key, surname_key, age_key in (
        ("ženin", "ime_zenina", "priimek_zenina", "starost_zenina"),
        ("nevesta", "ime_neveste", "priimek_neveste", "starost_neveste"),
    ):
        name_score = _similarity(death_name, poroke.get(name_key)) or 0.0
        surname_values = [poroke.get(surname_key)]
        if role == "nevesta":
            # Pri smrti je nevesta pogosto vpisana s poročnim priimkom ženina.
            surname_values.append(poroke.get("priimek_zenina"))
        surname_score = max((_similarity(death_surname, val) or 0.0 for val in surname_values), default=0.0)
        choices.append((name_score * 0.55 + surname_score * 0.45, role, age_key))
    score, role, age_key = max(choices)
    return (role, age_key) if score >= 0.45 else None


def _participant_for_baptism(poroke, krsti):
    """Pri načinu ista oseba poišče ženina/nevesto, ki ustreza krščencu."""
    if not poroke or not krsti:
        return None
    choices = (
        ("ženin", "ime_zenina", "priimek_zenina", "naslov_zenina"),
        ("nevesta", "ime_neveste", "priimek_neveste", "naslov_neveste"),
    )
    baptism_name = krsti.get("ime_otroka")
    baptism_surnames = [
        krsti.get("priimek_otroka"),
        krsti.get("priimek_oceta"),
        krsti.get("alt_priimek_oceta"),
    ]
    if not _norm(krsti.get("ime_oceta")) and not _norm(krsti.get("priimek_oceta")):
        baptism_surnames.extend((krsti.get("priimek_matere"), krsti.get("alt_priimek_matere")))
    baptism_address = krsti.get("naslov")
    ranked = []
    for role, name_key, surname_key, address_key in choices:
        name_score = _similarity(baptism_name, poroke.get(name_key)) or 0.0
        surname_score = max(
            (_similarity(value, poroke.get(surname_key)) or 0.0 for value in baptism_surnames if _norm(value)),
            default=0.0,
        )
        address_score = _similarity(baptism_address, poroke.get(address_key)) or 0.0
        score = name_score * 0.60 + surname_score * 0.30 + address_score * 0.10
        ranked.append((score, role, name_key, surname_key, address_key))
    score, role, name_key, surname_key, address_key = max(ranked)
    return (role, name_key, surname_key, address_key) if score >= 0.45 else None


def _name_values(krsti, poroke, mrtvi, kind):
    values = []
    if kind == "surname":
        if krsti:
            for key in ("priimek_otroka", "priimek_oceta", "alt_priimek_oceta", "priimek_matere", "alt_priimek_matere"):
                if krsti.get(key):
                    values.append((f"Krsti – {key}", krsti[key]))
        if mrtvi and mrtvi.get("priimek_pokojnika"):
            values.append(("Mrliška knjiga", mrtvi["priimek_pokojnika"]))
        if poroke:
            for role, key in (("Ženin", "priimek_zenina"), ("Nevesta", "priimek_neveste")):
                if poroke.get(key):
                    values.append((f"Poroka – {role}", poroke[key]))
            if poroke.get("priimek_zenina"):
                values.append(("Poroka – poročni priimek neveste", poroke["priimek_zenina"]))
    else:
        if krsti and krsti.get("ime_otroka"):
            values.append(("Krsti", krsti["ime_otroka"]))
        if mrtvi and mrtvi.get("ime_pokojnika"):
            values.append(("Mrliška knjiga", mrtvi["ime_pokojnika"]))
        if poroke:
            for role, key in (("Ženin", "ime_zenina"), ("Nevesta", "ime_neveste")):
                if poroke.get(key):
                    values.append((f"Poroka – {role}", poroke[key]))
    return values


def _address_values(krsti, poroke, mrtvi):
    values = []
    if krsti and krsti.get("naslov"):
        values.append(("Krsti", krsti["naslov"]))
    if mrtvi and mrtvi.get("naslov"):
        values.append(("Mrliška knjiga", mrtvi["naslov"]))
    if poroke:
        for role, key in (("Ženin", "naslov_zenina"), ("Nevesta", "naslov_neveste")):
            if poroke.get(key):
                values.append((f"Poroka – {role}", poroke[key]))
    return values


def _weighted_pair_signal(pairs):
    """Povpreči samo semantično pravilne pare oseb/podatkov."""
    scored = []
    for label_a, value_a, label_b, value_b, weight in pairs:
        score = _similarity(value_a, value_b)
        if score is not None and weight > 0:
            scored.append((score, label_a, value_a, label_b, value_b, weight))
    if not scored:
        return None, "Ni dovolj podatkov za ta primerjalni kriterij."
    denominator = sum(item[5] for item in scored)
    result = sum(item[0] * item[5] for item in scored) / denominator
    details = "; ".join(
        f"{a}: {va} ↔ {b}: {vb} ({score:.0%})"
        for score, a, va, b, vb, _weight in scored
    )
    return result, details


def _relationship_signal(krsti, poroke, mrtvi, relation_type, kind, settings):
    krsti, poroke, mrtvi = krsti or {}, poroke or {}, mrtvi or {}
    pairs = []
    participant = _participant_for_death(poroke, mrtvi)
    if relation_type == "same_person" and participant is None:
        baptism_participant = _participant_for_baptism(poroke, krsti)
        if baptism_participant:
            participant = (baptism_participant[0], "")
    participant_fields = {
        "ženin": ("ime_zenina", "priimek_zenina", "naslov_zenina"),
        "nevesta": ("ime_neveste", "priimek_neveste", "naslov_neveste"),
    }
    groom_factor = float(settings.get("groom_address_factor", 1.0))
    bride_factor = float(settings.get("bride_address_factor", 0.55))

    if relation_type == "parents_child":
        if kind == "given":
            pairs.extend((
                ("Krst – oče", krsti.get("ime_oceta"), "Poroka – ženin", poroke.get("ime_zenina"), 1.0),
                ("Krst – mati", krsti.get("ime_matere"), "Poroka – nevesta", poroke.get("ime_neveste"), 1.0),
            ))
            if participant:
                role, _age_key = participant
                name_key = participant_fields[role][0]
                pairs.append(("Mrliški zapis", mrtvi.get("ime_pokojnika"), f"Poroka – {role}", poroke.get(name_key), 1.2))
        elif kind == "surname":
            father_present = bool(_norm(krsti.get("ime_oceta")) or _norm(krsti.get("priimek_oceta")))
            if father_present and settings.get("use_father_surname", True):
                pairs.append((
                    "Krst – priimek očeta/otroka",
                    krsti.get("priimek_otroka") or krsti.get("priimek_oceta") or krsti.get("alt_priimek_oceta"),
                    "Poroka – priimek ženina", poroke.get("priimek_zenina"), 2.0,
                ))
            if settings.get("use_mother_surname_when_father_missing", True):
                mother_weight = 2.0 if not father_present else float(settings.get("mother_surname_weight_if_father_present", 0.35))
                pairs.append((
                    "Krst – priimek matere", krsti.get("priimek_matere") or krsti.get("alt_priimek_matere"),
                    "Poroka – priimek neveste", poroke.get("priimek_neveste") or poroke.get("priimek_zenina"), mother_weight,
                ))
            if participant:
                role, _age_key = participant
                surname_key = participant_fields[role][1]
                surname_options = [poroke.get(surname_key)]
                if role == "nevesta":
                    surname_options.append(poroke.get("priimek_zenina"))
                for option_index, surname_option in enumerate(surname_options):
                    if surname_option:
                        pairs.append(("Mrliški zapis", mrtvi.get("priimek_pokojnika"), f"Poroka – {role} {'maiden' if option_index == 0 else 'poročeni'} priimek", surname_option, 1.2))
        elif kind == "address":
            if krsti.get("naslov") and poroke.get("naslov_zenina"):
                pairs.append(("Krst – naslov družine", krsti.get("naslov"), "Poroka – naslov ženina", poroke.get("naslov_zenina"), groom_factor))
            if krsti.get("naslov") and poroke.get("naslov_neveste"):
                pairs.append(("Krst – naslov družine", krsti.get("naslov"), "Poroka – naslov neveste", poroke.get("naslov_neveste"), bride_factor))
            if mrtvi.get("naslov") and poroke.get("naslov_zenina"):
                pairs.append(("Smrt – naslov", mrtvi.get("naslov"), "Poroka – naslov ženina", poroke.get("naslov_zenina"), groom_factor))
            if mrtvi.get("naslov") and poroke.get("naslov_neveste"):
                pairs.append(("Smrt – naslov", mrtvi.get("naslov"), "Poroka – naslov neveste", poroke.get("naslov_neveste"), bride_factor))
    else:
        if kind == "given":
            if krsti.get("ime_otroka") and mrtvi.get("ime_pokojnika"):
                pairs.append(("Krst – oseba", krsti.get("ime_otroka"), "Mrliška knjiga", mrtvi.get("ime_pokojnika"), 1.5))
            if participant:
                role, _age_key = participant
                name_key = participant_fields[role][0]
                pairs.append(("Mrliški zapis", mrtvi.get("ime_pokojnika"), f"Poroka – {role}", poroke.get(name_key), 1.5))
                if krsti.get("ime_otroka"):
                    pairs.append(("Krst – oseba", krsti.get("ime_otroka"), f"Poroka – {role}", poroke.get(name_key), 1.0))
            elif poroke and krsti.get("ime_otroka"):
                for role, keys in participant_fields.items():
                    pairs.append(("Krst – oseba", krsti.get("ime_otroka"), f"Poroka – {role}", poroke.get(keys[0]), 0.75))
        elif kind == "surname":
            baptism_surname = (
                krsti.get("priimek_otroka") or krsti.get("priimek_oceta") or krsti.get("alt_priimek_oceta")
                or krsti.get("priimek_matere") or krsti.get("alt_priimek_matere")
            )
            if baptism_surname and mrtvi.get("priimek_pokojnika"):
                pairs.append(("Krst – oseba", baptism_surname, "Mrliška knjiga", mrtvi.get("priimek_pokojnika"), 1.5))
            if participant:
                role, _age_key = participant
                surname_key = participant_fields[role][1]
                options = [poroke.get(surname_key)]
                if role == "nevesta":
                    options.append(poroke.get("priimek_zenina"))
                for option_index, surname_option in enumerate(options):
                    if not surname_option:
                        continue
                    if mrtvi.get("priimek_pokojnika"):
                        pairs.append(("Mrliški zapis", mrtvi.get("priimek_pokojnika"), f"Poroka – {role} priimek {option_index + 1}", surname_option, 1.5))
                    if baptism_surname:
                        pairs.append(("Krst – oseba", baptism_surname, f"Poroka – {role} priimek {option_index + 1}", surname_option, 1.0))
        elif kind == "address":
            if krsti.get("naslov") and mrtvi.get("naslov"):
                pairs.append(("Krst – naslov", krsti.get("naslov"), "Mrliška knjiga – naslov", mrtvi.get("naslov"), 1.5))
            if participant:
                role, _age_key = participant
                address_key = participant_fields[role][2]
                factor = groom_factor if role == "ženin" else bride_factor
                if mrtvi.get("naslov"):
                    pairs.append(("Smrt – naslov", mrtvi.get("naslov"), f"Poroka – naslov {role}", poroke.get(address_key), factor))
                if krsti.get("naslov"):
                    pairs.append(("Krst – naslov", krsti.get("naslov"), f"Poroka – naslov {role}", poroke.get(address_key), factor))

    return _weighted_pair_signal(pairs)


def _parish_values(krsti, poroke, mrtvi):
    return [
        (label, record.get("zupnija"))
        for label, record in (("Krsti", krsti), ("Poroka", poroke), ("Mrliška knjiga", mrtvi))
        if record and record.get("zupnija")
    ]


def _family_factor(krsti, poroke, mrtvi):
    death_family = _norm((mrtvi or {}).get("zakonec_starsi"))
    if not death_family:
        return None, "Mrliški zapis ne vsebuje podatka o zakoncu oziroma starših."
    values = []
    if krsti:
        for label, value in (
            ("oče", f"{krsti.get('ime_oceta') or ''} {krsti.get('priimek_oceta') or ''}".strip()),
            ("mati", f"{krsti.get('ime_matere') or ''} {krsti.get('priimek_matere') or ''}".strip()),
        ):
            score = _similarity(value, death_family)
            if score is not None:
                values.append((score, label, value))
    if poroke:
        for role, name_key, surname_key in (
            ("ženin", "ime_zenina", "priimek_zenina"),
            ("nevesta", "ime_neveste", "priimek_neveste"),
        ):
            value = f"{poroke.get(name_key) or ''} {poroke.get(surname_key) or ''}".strip()
            score = _similarity(value, death_family)
            if score is not None:
                values.append((score, f"zakonec iz poroke ({role})", value))
    if not values:
        return None, "Ni dovolj podatkov o starših ali zakoncu za primerjavo."
    score, label, value = max(values)
    return score, f"Ujemanje {label}: '{value}' z navedbo v mrliškem zapisu ({score:.0%})."


def preveri_kronologijo(krsti=None, poroke=None, mrtvi=None, relation_type="parents_child", settings=None):
    """Preveri časovne odnose ob upoštevanju pomena izbranih zapisov.

    parents_child: poroka je poroka staršev; krstni zapis je njun otrok.
    same_person: vsi razpoložljivi dogodki se nanašajo na isto osebo.
    """
    krsti, poroke, mrtvi = krsti or {}, poroke or {}, mrtvi or {}
    settings = settings or DEFAULT_RULES
    strict = bool(settings.get("strict_chronology", True))
    allow_same = bool(settings.get("allow_same_day_birth_death", True))
    allow_premarital = bool(settings.get("allow_child_birth_before_marriage", True))
    conflicts, notes = [], []
    birth = krsti.get("datum_rojstva") or krsti.get("datum_krsta")
    marriage = (poroke or {}).get("datum_poroke")
    death = mrtvi.get("datum_smrti") or mrtvi.get("datum_pokopa")

    if relation_type == "same_person":
        ordered = (("rojstvo", birth, "poroka", marriage), ("rojstvo", birth, "smrt", death), ("poroka", marriage, "smrt", death))
        for earlier_label, earlier_value, later_label, later_value in ordered:
            relation = _compare_dates(earlier_value, later_value)
            if relation == 1:
                conflicts.append(f"{earlier_label} je časovno za dogodkom {later_label}.")
        if birth and death and _same_complete_date(birth, death) and not allow_same:
            conflicts.append("rojstvo in smrt sta na isti datum, ta izjema pa je izključena v nastavitvah.")
        if birth and marriage and _compare_dates(birth, marriage) == -1:
            notes.append("rojstvo je pred poroko")
        if marriage and death and _compare_dates(marriage, death) == -1:
            notes.append("poroka je pred smrtjo")
        if birth and death and _compare_dates(birth, death) == -1:
            notes.append("rojstvo je pred smrtjo")
        if not any((birth, marriage, death)):
            notes.append("letnice niso na voljo")
    else:
        # Poroka odrasle osebe in njena smrt sta isti osebi; krst je otrok.
        if marriage and death and _compare_dates(marriage, death) == 1:
            conflicts.append("poroka je po smrti osebe, ki jo povezujemo s poročnim zapisom.")
        if marriage and birth and _compare_dates(birth, marriage) == -1:
            if allow_premarital:
                notes.append("otrok je rojen pred poroko staršev; zgodovinsko mogoče, vendar preveri")
            else:
                conflicts.append("rojstvo otroka je pred poroko staršev; ta izjema je v nastavitvah izključena.")
        elif marriage and birth and _compare_dates(birth, marriage) == 1:
            notes.append("poroka staršev je pred rojstvom otroka")
        if not any((birth, marriage, death)):
            notes.append("letnice niso na voljo")

    hard_conflicts = conflicts if strict else []
    return {
        "valid": not bool(hard_conflicts),
        "hard_conflicts": hard_conflicts,
        "conflicts": conflicts,
        "notes": notes,
        "detail": " ".join(conflicts + notes) or "Ni časovnega protislovja med razpoložljivimi datumi.",
    }


def _age_factor(krsti, poroke, mrtvi, relation_type="parents_child"):
    """Starost primerja samo takrat, ko se starost in datum nanašata na isto osebo."""
    poroke, mrtvi, krsti = poroke or {}, mrtvi or {}, krsti or {}
    death_year = _year(mrtvi.get("datum_smrti") or mrtvi.get("datum_pokopa"))
    marriage_year = _year(poroke.get("datum_poroke"))
    birth_year = _year(krsti.get("datum_rojstva") or krsti.get("datum_krsta"))
    death_age = _age_years(mrtvi.get("starost"))
    checks = []

    # Starost ob poroki in smrti se nanaša na istega odraslega, ne na krščenca/otroka.
    participant = _participant_for_death(poroke, mrtvi)
    if participant and death_year and marriage_year:
        _role, age_key = participant
        marriage_age = _age_years(poroke.get(age_key))
        if death_age is not None and marriage_age is not None:
            estimated_birth_death = death_year - death_age
            estimated_birth_marriage = marriage_year - marriage_age
            difference = abs(estimated_birth_death - estimated_birth_marriage)
            checks.append((
                _age_match(0, difference),
                f"Ocenjeni letnici rojstva iz starosti ob poroki in smrti se razlikujeta za približno {difference:.1f} let.",
            ))

    # V načinu ista oseba je lahko krstni zapis njen lastni rojstni zapis.
    # V načinu starši–otrok se otrokovo rojstvo NE primerja s starostjo staršev ob poroki.
    if relation_type == "same_person" and birth_year:
        if death_year and death_age is not None:
            expected_death_age = death_year - birth_year
            checks.append((
                _age_match(expected_death_age, death_age),
                f"Iz rojstva in smrti izhaja približno {expected_death_age} let; v mrliškem zapisu je {death_age:.1f} let.",
            ))
        if marriage_year and participant:
            _role, age_key = participant
            marriage_age = _age_years(poroke.get(age_key))
            if marriage_age is not None:
                expected_marriage_age = marriage_year - birth_year
                if expected_marriage_age >= 0:
                    checks.append((
                        _age_match(expected_marriage_age, marriage_age),
                        f"Iz rojstva in poroke izhaja približno {expected_marriage_age} let; v poročnem zapisu je {marriage_age:.1f} let.",
                    ))

    scores = [score for score, _detail in checks if score is not None]
    if not scores:
        return None, "Ni dovolj primerljivih starosti; starosti staršev ne primerjam z rojstvom otroka."
    return sum(scores) / len(scores), " ".join(detail for _score, detail in checks)


def _chronology_score(check):
    if check["hard_conflicts"]:
        return 0.0
    if any("pred poroko staršev" in note for note in check["notes"]):
        return 0.45
    if any("letnice niso" in note for note in check["notes"]):
        return None
    if check["notes"]:
        return 1.0
    return None


def oceni_ujemanje(krsti=None, poroke=None, mrtvi=None, settings=None, relation_type="parents_child"):
    """Vrne oceno, pokritost, razlago dokazov in morebitna trda časovna protislovja."""
    krsti, poroke, mrtvi = krsti or {}, poroke or {}, mrtvi or {}
    settings = settings or DEFAULT_RULES
    weights = settings.get("weights", {}).get("manual", WEIGHTS)
    signals = []

    for label, kind in (("Priimek", "surname"), ("Ime", "given"), ("Naslov", "address")):
        value, detail = _relationship_signal(krsti, poroke, mrtvi, relation_type, kind, settings)
        if value is not None:
            signals.append((label, value, detail))

    parish_pair = _best_pair(_parish_values(krsti, poroke, mrtvi))
    if parish_pair:
        value, label_a, value_a, label_b, value_b = parish_pair
        signals.append(("Župnija", value, f"{label_a}: {value_a} ↔ {label_b}: {value_b} ({value:.0%} podobnosti)."))

    age_score, age_detail = _age_factor(krsti, poroke, mrtvi, relation_type)
    if age_score is not None:
        signals.append(("Starost in letnice", age_score, age_detail))

    family_score, family_detail = _family_factor(krsti, poroke, mrtvi)
    if family_score is not None:
        signals.append(("Družinski podatki", family_score, family_detail))

    chronology = preveri_kronologijo(krsti, poroke, mrtvi, relation_type, settings)
    chronology_value = _chronology_score(chronology)
    if chronology_value is not None:
        signals.append(("Kronologija", chronology_value, chronology["detail"]))

    available_weight = sum(max(0, float(weights.get(label, 0))) for label, _value, _detail in signals)
    total_weight = sum(max(0, float(value)) for value in weights.values()) or 1
    if available_weight:
        score = round(sum(float(weights.get(label, 0)) * value for label, value, _detail in signals) / available_weight * 100)
    else:
        score = None
    coverage = round(available_weight / total_weight * 100)

    if chronology["hard_conflicts"]:
        label = "Časovno protislovje – preveri ali zavrni"
        score = 0
    elif score is None:
        label = "Premalo podatkov"
    elif coverage < 60:
        label = "Omejena ocena – premalo neodvisnih podatkov"
    elif score >= 85:
        label = "Zelo dobro ujemanje"
    elif score >= 70:
        label = "Dobro ujemanje"
    elif score >= 50:
        label = "Delno ujemanje – preveri"
    else:
        label = "Šibko ujemanje"

    return {
        "score": score,
        "coverage": coverage,
        "label": label,
        "signals": signals,
        "hard_conflicts": chronology["hard_conflicts"],
        "chronology": chronology,
        "relation_type": relation_type,
        "note": "Hevristična ocena podobnosti, ne statistično potrjena verjetnost identitete.",
    }

"""Hevristično iskanje morebitnih povezav med zapisi iste župnije.

Vrste povezav so ločene:
- same_person: krst/rojstvo, poroka in smrt iste osebe;
- parents_child: poroka staršev in krst njunega otroka.

Rezultati so predlogi za človeški pregled, ne potrjene identitete.
"""

import re
from collections import defaultdict

from .nastavitve_ujemanja import DEFAULT_RULES
from .ujemanje_pomocno import (
    _address_note, _address_similarity, _age_similarity, _age_years, _date_order,
    _name_similarity, _surname_similarity, _weighted_score, _year, norm, similarity,
)
from .ujemanje_osebe import _death_baptism_match


def _chronology_death_marriage(death, marriage, settings):
    death_date = death.get("datum_smrti") or death.get("datum_pokopa")
    marriage_date = marriage.get("datum_poroke")
    if not death_date or not marriage_date:
        return None, "manjka letnica poroke ali smrti", False
    order = _date_order(marriage_date, death_date)
    if order == 1:
        text = "poroka je po smrti osebe – časovno protislovje"
        return 0.0, text, bool(settings.get("strict_chronology", True))
    if order == 0:
        return 0.8, "poroka in smrt sta v istem znanem letu/datumu; preveri natančnost prepisa", False
    return 1.0, "poroka je pred smrtjo osebe", False


def _chronology_marriage_baptism(marriage, baptism, settings):
    marriage_date = marriage.get("datum_poroke")
    birth_date = baptism.get("datum_rojstva") or baptism.get("datum_krsta")
    if not marriage_date or not birth_date:
        return None, "manjka letnica poroke ali rojstva/krsta", False
    order = _date_order(birth_date, marriage_date)
    if order == -1:
        if settings.get("allow_child_birth_before_marriage", True):
            return 0.40, "otrok je rojen pred poroko staršev; zgodovinsko mogoče, vendar preveri", False
        return 0.0, "rojstvo otroka je pred poroko staršev – izjema je izključena v nastavitvah", bool(settings.get("strict_chronology", True))
    birth_year = _year(birth_date)
    marriage_year = _year(marriage_date)
    if order == 1 and birth_year and marriage_year:
        gap = birth_year - marriage_year
        if gap <= 30:
            return 1.0, "poroka staršev je pred rojstvom otroka", False
        return 0.45, f"med poroko in rojstvom otroka je {gap} let; preveri povezavo", False
    return 0.8, "poroka in rojstvo sta v istem znanem letu ali sta časovno združljiva", False


def _death_marriage_match(death, marriage, settings):
    weights = settings.get("weights", DEFAULT_RULES["weights"])["death_marriage"]
    candidates = []
    participants = (
        ("ženin", "ime_zenina", "priimek_zenina", "starost_zenina"),
        ("nevesta", "ime_neveste", "priimek_neveste", "starost_neveste"),
    )
    for side, name_key, surname_key, age_key in participants:
        name_score = _name_similarity(death.get("ime_pokojnika"), marriage.get(name_key))
        surname_options = [marriage.get(surname_key)]
        if side == "nevesta":
            surname_options.append(marriage.get("priimek_zenina"))
        surname_score, surname_note = _surname_similarity([death.get("priimek_pokojnika")], surname_options)
        if name_score < float(settings.get("minimum_name_similarity", 0.55)):
            continue
        if surname_score < float(settings.get("minimum_surname_similarity", 0.50)):
            continue

        chronology_score, chronology_note, hard_conflict = _chronology_death_marriage(death, marriage, settings)
        if hard_conflict:
            continue

        groom_addr = _address_similarity(death.get("naslov"), marriage.get("naslov_zenina"))
        bride_addr = _address_similarity(death.get("naslov"), marriage.get("naslov_neveste"))
        groom_factor = float(settings.get("groom_address_factor", 1.0))
        bride_factor = float(settings.get("bride_address_factor", 0.55))
        address_score = max(groom_addr * groom_factor, bride_addr * bride_factor)
        death_year = _year(death.get("datum_smrti") or death.get("datum_pokopa"))
        marriage_year = _year(marriage.get("datum_poroke"))
        death_age = _age_years(death.get("starost"))
        marriage_age = _age_years(marriage.get(age_key))
        age_score = None
        if death_year and marriage_year and death_age is not None and marriage_age is not None:
            delta_birth = abs((death_year - death_age) - (marriage_year - marriage_age))
            age_score = _age_similarity(0, delta_birth)
        factors = {
            "name": name_score,
            "surname": surname_score,
            "groom_address": groom_addr * groom_factor,
            "bride_address": bride_addr * bride_factor,
            "chronology": chronology_score,
            "age": age_score,
        }
        result = _weighted_score(factors, weights)
        if not result:
            continue
        score, factor_reasons = result
        reasons = [
            f"pokojnik se ujema kot {side}",
            surname_note,
            f"naslov ženina: {groom_addr:.0%}; naslov neveste: {bride_addr:.0%} (utež naslova neveste je nižja zaradi možne selitve)",
            chronology_note,
            *factor_reasons,
        ]
        candidates.append({"score": score, "side": side, "reasons": reasons, "address_score": address_score})
    return max(candidates, key=lambda item: item["score"]) if candidates else None


def _parent_surname_factor(marriage, baptism, settings):
    father_present = bool(norm(baptism.get("ime_oceta")) or norm(baptism.get("priimek_oceta")))
    mother_present = bool(norm(baptism.get("ime_matere")) or norm(baptism.get("priimek_matere")))
    father_score = mother_score = None
    reasons = []

    if father_present and settings.get("use_father_surname", True):
        child_father_surname = [
            baptism.get("priimek_otroka"), baptism.get("priimek_oceta"),
            baptism.get("alt_priimek_oceta"),
        ]
        father_score, father_note = _surname_similarity(
            child_father_surname, [marriage.get("priimek_zenina")]
        )
        reasons.append("prednostni očetov priimek: " + father_note)

    if mother_present and settings.get("use_mother_surname_when_father_missing", True):
        mother_names = [baptism.get("priimek_matere"), baptism.get("alt_priimek_matere")]
        bride_names = [marriage.get("priimek_neveste"), marriage.get("priimek_zenina")]
        mother_score, mother_note = _surname_similarity(mother_names, bride_names)
        if father_present:
            mother_score *= float(settings.get("mother_surname_weight_if_father_present", 0.35))
            reasons.append("materin priimek je podporni dokaz, ker je oče vpisan: " + mother_note)
        else:
            reasons.append("oče ni vpisan; materin priimek je primarni dokaz: " + mother_note)

    if father_score is None and mother_score is None:
        reasons.append("priimek staršev/otroka ni na voljo")
    return father_score, mother_score, reasons


def _marriage_baptism_match(marriage, baptism, settings):
    weights = settings.get("weights", DEFAULT_RULES["weights"])["marriage_baptism"]
    father_present = bool(norm(baptism.get("ime_oceta")) or norm(baptism.get("priimek_oceta")))
    mother_present = bool(norm(baptism.get("ime_matere")) or norm(baptism.get("priimek_matere")))

    father_name = _name_similarity(baptism.get("ime_oceta"), marriage.get("ime_zenina")) if father_present else None
    mother_name = _name_similarity(baptism.get("ime_matere"), marriage.get("ime_neveste")) if mother_present else None
    name_scores = [value for value in (father_name, mother_name) if value is not None]
    minimum_name = float(settings.get("minimum_name_similarity", 0.55))
    if not name_scores or max(name_scores) < minimum_name:
        return None

    father_surname_score, mother_surname_score, surname_reasons = _parent_surname_factor(
        marriage, baptism, settings
    )
    father_address = _address_similarity(baptism.get("naslov"), marriage.get("naslov_zenina"))
    mother_address = _address_similarity(baptism.get("naslov"), marriage.get("naslov_neveste"))
    chronology_score, chronology_note, hard_conflict = _chronology_marriage_baptism(marriage, baptism, settings)
    if hard_conflict:
        return None

    groom_weight = float(settings.get("groom_address_factor", 1.0))
    bride_weight = float(settings.get("bride_address_factor", 0.55))
    factors = {
        "father_name": father_name,
        "mother_name": mother_name,
        "father_surname": father_surname_score,
        "mother_surname": mother_surname_score,
        "groom_address": father_address * groom_weight,
        "bride_address": mother_address * bride_weight,
        "chronology": chronology_score,
    }
    result = _weighted_score(factors, weights)
    if not result:
        return None
    score, factor_reasons = result
    reasons = []
    if father_name is not None:
        reasons.append(f"ime očeta ↔ ženina: {father_name:.0%}")
    if mother_name is not None:
        reasons.append(f"ime matere ↔ neveste: {mother_name:.0%}")
    reasons.extend(surname_reasons)
    reasons.append(f"naslov krsta ↔ naslov ženina: {father_address:.0%}")
    reasons.append(f"naslov krsta ↔ naslov neveste: {mother_address:.0%}; nižja utež zaradi možne selitve")
    reasons.append(chronology_note)
    reasons.extend(factor_reasons)
    return {"score": score, "reasons": reasons, "address_score": max(father_address * groom_weight, mother_address * bride_weight)}




def _initial(value):
    parts = norm(value).split()
    return parts[0][0] if parts else ""


def _address_keys(value):
    common = {"ulica", "cesta", "trg", "naselje", "vas", "mesto", "pri", "na", "ob", "sv", "sveti", "st", "hisa", "hisna"}
    keys = set()
    for token in norm(value).split():
        if token.isdigit():
            keys.add(f"house:{token}")
        elif len(token) >= 4 and token not in common:
            keys.add(f"addr:{token}")
    return keys


def _record_keys(record, fields, address_fields=()):
    keys = {_initial(record.get(field)) for field in fields}
    keys.discard("")
    for field in address_fields:
        keys.update(_address_keys(record.get(field)))
    return keys


def _build_initial_index(records, fields, address_fields=()):
    index = defaultdict(list)
    for record in records:
        for key in _record_keys(record, fields, address_fields):
            index[key].append(record)
    return index


def _indexed_candidates(index, record, fields, address_fields=()):
    found = {}
    for key in _record_keys(record, fields, address_fields):
        for candidate in index.get(key, []):
            found[candidate.get("id", id(candidate))] = candidate
    return list(found.values())


def _person_label(record, kind):
    if not record:
        return "/"
    if kind == "mrtvi":
        name = f"{record.get('ime_pokojnika') or ''} {record.get('priimek_pokojnika') or ''}".strip()
        return name or f"ID {record.get('id')}"
    if kind == "poroke":
        groom = f"{record.get('ime_zenina') or ''} {record.get('priimek_zenina') or ''}".strip()
        bride = f"{record.get('ime_neveste') or ''} {record.get('priimek_neveste') or ''}".strip()
        return f"{groom} × {bride}".strip(" ×")
    name = f"{record.get('ime_otroka') or ''} {record.get('priimek_otroka') or record.get('priimek_oceta') or ''}".strip()
    parents = f"starša: {record.get('ime_oceta') or ''} {record.get('priimek_oceta') or ''} / {record.get('ime_matere') or ''} {record.get('priimek_matere') or ''}".strip()
    return f"{name} ({parents})" if name else f"ID {record.get('id')}"


def find_possible_merges(records, minimum_score=None, maximum_results=1000, settings=None):
    """Išče od mrliških zapisov naprej, z upoštevanjem nastavljivih pravil."""
    rules = dict(DEFAULT_RULES)
    if settings:
        rules.update(settings)
    threshold = int(minimum_score if minimum_score is not None else rules.get("minimum_score", 55))
    deaths = records.get("mrtvi", [])
    marriages = records.get("poroke", [])
    baptisms = records.get("krsti", [])
    matches, paired_marriage_ids = [], set()

    marriage_index = _build_initial_index(
        marriages,
        ("ime_zenina", "priimek_zenina", "ime_neveste", "priimek_neveste"),
        ("naslov_zenina", "naslov_neveste"),
    )
    parent_index = _build_initial_index(
        baptisms,
        ("ime_oceta", "priimek_oceta", "alt_priimek_oceta", "ime_matere", "priimek_matere", "alt_priimek_matere"),
        ("naslov",),
    )
    child_index = _build_initial_index(
        baptisms, ("ime_otroka", "priimek_otroka", "priimek_oceta", "alt_priimek_oceta", "priimek_matere", "alt_priimek_matere"), ("naslov",)
    )

    # 1. Mrliški zapis je izhodiščni zapis; iščemo poroko istega odraslega.
    for death in deaths:
        marriage_candidates = _indexed_candidates(
            marriage_index, death, ("ime_pokojnika", "priimek_pokojnika"), ("naslov",)
        )
        death_matches = []
        for marriage in marriage_candidates:
            match = _death_marriage_match(death, marriage, rules)
            if match and match["score"] >= threshold:
                death_matches.append((marriage, match))
        death_matches.sort(key=lambda item: item[1]["score"], reverse=True)

        if death_matches:
            for marriage, death_match in death_matches:
                paired_marriage_ids.add(marriage.get("id"))
                has_baptism_chain = False

                # A. Poroka staršev → krst njunega otroka.
                family_candidates = _indexed_candidates(
                    parent_index,
                    marriage,
                    ("ime_zenina", "priimek_zenina", "ime_neveste", "priimek_neveste"),
                    ("naslov_zenina", "naslov_neveste"),
                )
                for baptism in family_candidates:
                    match = _marriage_baptism_match(marriage, baptism, rules)
                    if not match or match["score"] < threshold:
                        continue
                    has_baptism_chain = True
                    combined = round(death_match["score"] * 0.55 + match["score"] * 0.45)
                    matches.append({
                        "score": combined, "krsti": baptism, "poroke": marriage, "mrtvi": death,
                        "relation_type": "parents_child",
                        "reasons": [
                            f"smrt–poroka ({death_match['score']}/100; pokojnik se ujema kot {death_match['side']})",
                            *death_match["reasons"],
                            f"poroka–krst staršev in otroka ({match['score']}/100)",
                            *match["reasons"],
                        ],
                    })

                # B. Krst/rojstvo → poroka → smrt iste osebe.
                # To je drugačen odnos: otrok v krstni knjigi je odrasla oseba,
                # ki se je pozneje poročila in umrla, ne otrok poročnega para.
                person_baptisms = _indexed_candidates(
                    child_index,
                    death,
                    ("ime_pokojnika", "priimek_pokojnika"),
                    ("naslov",),
                )
                for baptism in person_baptisms:
                    match = _death_baptism_match(
                        death, baptism, rules,
                        marriage=marriage,
                        marriage_side=death_match.get("side"),
                    )
                    if not match or match["score"] < threshold:
                        continue
                    has_baptism_chain = True
                    combined = round(death_match["score"] * 0.45 + match["score"] * 0.55)
                    matches.append({
                        "score": combined, "krsti": baptism, "poroke": marriage, "mrtvi": death,
                        "relation_type": "same_person",
                        "reasons": [
                            f"krst–poroka–smrt iste osebe ({combined}/100; poročna vloga: {death_match['side']})",
                            *death_match["reasons"],
                            *match["reasons"],
                        ],
                    })

                if not has_baptism_chain:
                    matches.append({
                        "score": death_match["score"], "krsti": None, "poroke": marriage, "mrtvi": death,
                        "relation_type": "same_person",
                        "reasons": [
                            f"smrt–poroka iste osebe ({death_match['score']}/100; pokojnik se ujema kot {death_match['side']})",
                            *death_match["reasons"],
                            "V izbrani župniji ni bil najden dovolj prepričljiv krstni zapis.",
                        ],
                    })
        else:
            # 2. Rezervna pot: krst iste osebe, ko poroka ni znana ali je ni.
            candidates = _indexed_candidates(child_index, death, ("ime_pokojnika", "priimek_pokojnika"), ("naslov",))
            for baptism in candidates:
                match = _death_baptism_match(death, baptism, rules)
                if match and match["score"] >= threshold:
                    matches.append({
                        "score": match["score"], "krsti": baptism, "poroke": None, "mrtvi": death,
                        "relation_type": "same_person",
                        "reasons": ["smrt–krst iste osebe (brez povezanega poročnega zapisa)", *match["reasons"]],
                    })

    # 3. Dodatno najdi pare poroka staršev → krst otroka, tudi brez mrliškega vpisa.
    for marriage in marriages:
        if marriage.get("id") in paired_marriage_ids:
            continue
        candidates = _indexed_candidates(
            parent_index,
            marriage,
            ("ime_zenina", "priimek_zenina", "ime_neveste", "priimek_neveste"),
            ("naslov_zenina", "naslov_neveste"),
        )
        for baptism in candidates:
            match = _marriage_baptism_match(marriage, baptism, rules)
            if match and match["score"] >= threshold:
                matches.append({
                    "score": match["score"], "krsti": baptism, "poroke": marriage, "mrtvi": None,
                    "relation_type": "parents_child",
                    "reasons": [
                        f"poroka staršev–krst otroka ({match['score']}/100)",
                        *match["reasons"],
                        "Ustreznega mrliškega zapisa v tej župniji ni bilo mogoče najti.",
                    ],
                })

    unique = {}
    for item in matches:
        key = (
            item["mrtvi"].get("id") if item["mrtvi"] else None,
            item["poroke"].get("id") if item["poroke"] else None,
            item["krsti"].get("id") if item["krsti"] else None,
            item.get("relation_type"),
        )
        if key not in unique or item["score"] > unique[key]["score"]:
            unique[key] = item
    results = sorted(unique.values(), key=lambda item: item["score"], reverse=True)
    return results[:maximum_results]


def result_labels(candidate):
    return (
        _person_label(candidate.get("mrtvi"), "mrtvi"),
        _person_label(candidate.get("poroke"), "poroke"),
        _person_label(candidate.get("krsti"), "krsti"),
        " | ".join(candidate.get("reasons", [])[:6]),
    )

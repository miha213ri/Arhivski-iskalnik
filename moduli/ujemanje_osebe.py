"""Logika za povezavo krstnega zapisa in smrti iste osebe."""

from .nastavitve_ujemanja import DEFAULT_RULES
from .ujemanje_pomocno import (
    _address_similarity, _age_similarity, _age_years, _date_order,
    _name_similarity, _same_complete_date, _surname_similarity, _weighted_score, _year, norm,
)


def _death_baptism_match(death, baptism, settings, marriage=None, marriage_side=None):
    """Poveže krst in smrt iste osebe; po želji preveri tudi njeno poroko."""
    weights = settings.get("weights", DEFAULT_RULES["weights"])["death_baptism"]
    death_name_score = _name_similarity(death.get("ime_pokojnika"), baptism.get("ime_otroka"))
    father_present = bool(norm(baptism.get("ime_oceta")) or norm(baptism.get("priimek_oceta")))
    if father_present:
        surname_values = [
            baptism.get("priimek_otroka"), baptism.get("priimek_oceta"),
            baptism.get("alt_priimek_oceta"),
        ]
        surname_reason = "priimek primerjan prednostno po očetu"
    elif settings.get("use_mother_surname_when_father_missing", True):
        surname_values = [baptism.get("priimek_matere"), baptism.get("alt_priimek_matere")]
        surname_reason = "oče ni vpisan; priimek primerjan po materi"
    else:
        surname_values = []
        surname_reason = "oče ni vpisan, uporaba materinega priimka je izključena"

    death_surname_score, death_surname_note = _surname_similarity(
        [death.get("priimek_pokojnika")], surname_values
    )
    minimum_name = float(settings.get("minimum_name_similarity", 0.55))
    minimum_surname = float(settings.get("minimum_surname_similarity", 0.50))
    if death_name_score < minimum_name:
        return None
    # Če je na voljo poroka, je lahko pokojna nevesta vpisana s poročnim
    # priimkom. V tem primeru rojstnega priimka ne primerjamo neposredno
    # s priimkom ob smrti, temveč ga preverimo prek poročnega zapisa.
    if marriage is None and death_surname_score < minimum_surname:
        return None

    birth_date = baptism.get("datum_rojstva") or baptism.get("datum_krsta")
    death_date = death.get("datum_smrti") or death.get("datum_pokopa")
    if not birth_date or not death_date:
        chronology_score = None
        chronology_note = "manjka letnica rojstva ali smrti"
    else:
        order = _date_order(birth_date, death_date)
        same_day_disallowed = (
            _same_complete_date(birth_date, death_date)
            and not settings.get("allow_same_day_birth_death", True)
        )
        if order == 1 or same_day_disallowed:
            if order == 1:
                chronology_note = "rojstvo je po smrti iste osebe – časovno protislovje"
            else:
                chronology_note = "rojstvo in smrt sta na isti datum, vendar ta izjema ni dovoljena v nastavitvah"
            if settings.get("strict_chronology", True):
                return None
            chronology_score = 0.0
        else:
            chronology_score = 1.0
            chronology_note = "rojstvo je pred smrtjo ali na isti dovoljeni datum"

    name_scores = [death_name_score]
    surname_scores = [death_surname_score] if marriage is None else []
    address_scores = []
    age_scores = []
    reasons = [
        f"ime pokojnika ↔ krščenca: {death_name_score:.0%}",
        surname_reason + "; " + death_surname_note,
    ]

    if death.get("naslov") and baptism.get("naslov"):
        address_scores.append(_address_similarity(death.get("naslov"), baptism.get("naslov")))
        reasons.append(
            f"naslov ob smrti ↔ krstu: {address_scores[-1]:.0%}"
        )

    birth_year, death_year = _year(birth_date), _year(death_date)
    death_age = _age_years(death.get("starost"))
    if birth_year and death_year and death_age is not None:
        age_scores.append(_age_similarity(death_year - birth_year, death_age))

    # Če je na voljo poroka, preverimo, ali je krstni zapis rojstni zapis
    # prav tistega ženina/neveste, ki ga povezujemo z mrliško knjigo.
    if marriage:
        side = marriage_side or "ženin"
        party = {
            "ženin": ("ime_zenina", "priimek_zenina", "naslov_zenina", "starost_zenina"),
            "nevesta": ("ime_neveste", "priimek_neveste", "naslov_neveste", "starost_neveste"),
        }.get(side)
        if not party:
            return None
        name_key, surname_key, address_key, age_key = party
        marriage_name_score = _name_similarity(baptism.get("ime_otroka"), marriage.get(name_key))
        marriage_surname_score, marriage_surname_note = _surname_similarity(
            surname_values, [marriage.get(surname_key)]
        )
        if marriage_name_score < minimum_name or marriage_surname_score < minimum_surname:
            return None
        name_scores.append(marriage_name_score)
        surname_scores.append(marriage_surname_score)
        if death_surname_score >= minimum_surname:
            surname_scores.append(death_surname_score)
        reasons.extend((
            f"krstno ime ↔ {side}: {marriage_name_score:.0%}",
            f"rojstni priimek ↔ priimek {side}: {marriage_surname_note}",
        ))

        marriage_date = marriage.get("datum_poroke")
        if birth_date and marriage_date:
            birth_to_marriage = _date_order(birth_date, marriage_date)
            if birth_to_marriage == 1:
                message = "rojstvo osebe je po njeni poroki – časovno protislovje"
                if settings.get("strict_chronology", True):
                    return None
                chronology_score = 0.0
                reasons.append(message)
            elif birth_to_marriage == -1:
                reasons.append("rojstvo osebe je pred njeno poroko")
            else:
                reasons.append("rojstvo in poroka sta v istem znanem letu ali sta časovno združljiva")
        elif not marriage_date:
            reasons.append("datum poroke ni na voljo")

        groom_factor = float(settings.get("groom_address_factor", 1.0))
        bride_factor = float(settings.get("bride_address_factor", 0.55))
        address_factor = groom_factor if side == "ženin" else bride_factor
        if baptism.get("naslov") and marriage.get(address_key):
            marriage_address_score = _address_similarity(baptism.get("naslov"), marriage.get(address_key))
            address_scores.append(marriage_address_score * address_factor)
            reasons.append(
                f"naslov ob krstu ↔ naslov {side}: {marriage_address_score:.0%} "
                f"(utež {address_factor:.2f})"
            )

        marriage_year = _year(marriage_date)
        marriage_age = _age_years(marriage.get(age_key))
        if birth_year and marriage_year and marriage_age is not None:
            age_scores.append(_age_similarity(marriage_year - birth_year, marriage_age))
            reasons.append(
                f"starost ob poroki: iz rojstva približno {marriage_year - birth_year} let; "
                f"v poročnem zapisu {marriage_age:.1f} let"
            )

    name_score = sum(name_scores) / len(name_scores)
    surname_score = sum(surname_scores) / len(surname_scores)
    address_score = sum(address_scores) / len(address_scores) if address_scores else None
    age_score = sum(age_scores) / len(age_scores) if age_scores else None
    factors = {
        "name": name_score,
        "surname": surname_score,
        "address": address_score,
        "chronology": chronology_score,
        "age": age_score,
    }
    result = _weighted_score(factors, weights)
    if not result:
        return None
    score, factor_reasons = result
    reasons.extend((chronology_note, *factor_reasons))
    if not marriage:
        reasons.append("poročnega zapisa ni bilo mogoče povezati; preveri neporočeno osebo ali manjkajoči vpis")
    return {"score": score, "reasons": reasons}


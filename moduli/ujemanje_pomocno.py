"""Skupne normalizacijske in primerjalne funkcije za arhivske zapise."""

import re
import unicodedata
from difflib import SequenceMatcher


def norm(value):
    text = str(value or "").casefold().strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def similarity(left, right):
    a, b = norm(left), norm(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    tokens_a, tokens_b = set(a.split()), set(b.split())
    token_score = len(tokens_a & tokens_b) / max(len(tokens_a | tokens_b), 1)
    return max(token_score, SequenceMatcher(None, a, b).ratio())


def _name_similarity(left, right):
    a, b = norm(left), norm(right)
    if not a or not b:
        return 0.0
    best = similarity(a, b)
    for part_a in a.split():
        for part_b in b.split():
            best = max(best, similarity(part_a, part_b))
    return best


def _surname_similarity(left_values, right_values):
    left = [value for value in left_values if norm(value)]
    right = [value for value in right_values if norm(value)]
    if not left or not right:
        return 0.0, "priimek manjka"
    score, value_a, value_b = max(
        ((similarity(a, b), a, b) for a in left for b in right),
        key=lambda item: item[0],
    )
    if score >= 0.98:
        note = f"priimek se ujema ({value_a} = {value_b})"
    elif score >= 0.80:
        note = f"priimek je zelo podoben ({value_a} / {value_b})"
    else:
        note = f"priimka se slabše ujemata ({value_a} / {value_b})"
    return score, note


def _address_similarity(left, right):
    a, b = norm(left), norm(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    numbers_a = set(re.findall(r"\b\d+[a-z]?\b", a))
    numbers_b = set(re.findall(r"\b\d+[a-z]?\b", b))
    words_a, words_b = set(a.split()) - numbers_a, set(b.split()) - numbers_b
    shared_words = len(words_a & words_b) / max(len(words_a | words_b), 1)
    ratio = SequenceMatcher(None, a, b).ratio()
    if numbers_a and numbers_b:
        if numbers_a == numbers_b and shared_words >= 0.5:
            return max(0.98, ratio)
        if numbers_a.isdisjoint(numbers_b):
            return min(0.45, max(shared_words * 0.45, ratio * 0.35))
    if a in b or b in a:
        return max(0.85, ratio)
    return max(shared_words, ratio * 0.85)


def _address_note(score, label):
    if score >= 0.90:
        return label
    if score >= 0.60:
        return "naslova sta delno podobna; preveri ulico in hišno številko"
    if score > 0:
        return "naslova se razlikujeta oziroma se hišni številki ne ujemata"
    return "naslov manjka ali ga ni mogoče primerjati"


def _year(value):
    match = re.search(r"(?<!\d)(1[5-9]\d{2}|20\d{2})(?!\d)", str(value or ""))
    return int(match.group(1)) if match else None


def _date_key(value):
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


def _date_order(left, right):
    """-1: left prej right, 0: enako/isto znano leto, 1: left pozneje."""
    a, b = _date_key(left), _date_key(right)
    if not a or not b:
        return None
    for index in range(3):
        if a[index] is None or b[index] is None:
            if index == 0 and a[0] != b[0]:
                return -1 if a[0] < b[0] else 1
            return 0
        if a[index] != b[index]:
            return -1 if a[index] < b[index] else 1
    return 0


def _same_complete_date(left, right):
    a, b = _date_key(left), _date_key(right)
    return bool(a and b and all(part is not None for part in a + b) and a == b)


def _age_years(value):
    text = norm(value)
    if not text:
        return None
    match = re.search(r"(\d{1,3})\s*(?:l|let|leto|leta|years?|yrs?)\b", text)
    if match:
        value = int(match.group(1))
        return value if value <= 110 else None
    # Nekateri prepisi shranijo starost skupaj s stanovskim zapisom,
    # npr. "23 / Witwer". Če je v polju samo ena številka, jo lahko
    # varno uporabimo kot starost; več številk je dvoumnih.
    numbers = re.findall(r"(?<!\d)\d{1,3}(?!\d)", text)
    if len(numbers) == 1:
        value = int(numbers[0])
        return value if value <= 110 else None
    return None


def _age_similarity(expected, observed):
    if expected is None or observed is None:
        return None
    difference = abs(float(expected) - float(observed))
    if difference <= 2:
        return 1.0
    if difference <= 5:
        return 0.8
    if difference <= 10:
        return 0.5
    if difference <= 15:
        return 0.2
    return 0.0


def _weighted_score(factors, weights):
    active = [(key, value, max(0.0, float(weights.get(key, 0)))) for key, value in factors.items() if value is not None]
    active = [(key, value, weight) for key, value, weight in active if weight > 0]
    denominator = sum(weight for _key, _value, weight in active)
    if not denominator:
        return None
    score = round(sum(value * weight for _key, value, weight in active) / denominator * 100)
    reasons = [f"{key}: {value:.0%}" for key, value, _weight in active]
    return score, reasons



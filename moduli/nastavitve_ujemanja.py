"""Uporabniške nastavitve meril za samodejno povezovanje zapisov in prikaz primerjalnika."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox


SETTINGS_PATH = Path(__file__).resolve().parent.parent / "pravila_ujemanja.json"

DEFAULT_RULES = {
    "minimum_score": 55,
    "minimum_name_similarity": 0.55,
    "minimum_surname_similarity": 0.50,
    "strict_chronology": True,
    "allow_same_day_birth_death": True,
    # Zunajzakonski oziroma predporočni otrok je zgodovinsko mogoč.
    # Če je možnost vključena, kandidat ostane, vendar dobi opozorilo in nižjo oceno.
    "allow_child_birth_before_marriage": True,
    "use_father_surname": True,
    "use_mother_surname_when_father_missing": True,
    "mother_surname_weight_if_father_present": 0.35,
    "groom_address_factor": 1.0,
    "bride_address_factor": 0.55,
    "weights": {
        "death_marriage": {
            "name": 25, "surname": 25, "groom_address": 15,
            "bride_address": 5, "chronology": 15, "age": 15,
        },
        "marriage_baptism": {
            "father_name": 20, "mother_name": 20, "father_surname": 18,
            "mother_surname": 18, "groom_address": 12,
            "bride_address": 5, "chronology": 18,
        },
        "death_baptism": {
            "name": 30, "surname": 25, "address": 20,
            "chronology": 15, "age": 10,
        },
        "manual": {
            "Priimek": 24, "Ime": 20, "Starost in letnice": 18,
            "Naslov": 16, "Družinski podatki": 12,
            "Kronologija": 8, "Župnija": 2,
        },
    },
    "hidden_fields": {},
}

WEIGHT_LABELS = {
    "death_marriage": (
        ("name", "Ime pokojnika ↔ ime pri poroki"),
        ("surname", "Priimek (upošteva poročni priimek neveste)"),
        ("groom_address", "Naslov ženina"),
        ("bride_address", "Naslov neveste (lahko se spremeni)"),
        ("chronology", "Časovno zaporedje poroka → smrt"),
        ("age", "Skladnost starosti ob poroki in smrti"),
    ),
    "marriage_baptism": (
        ("father_name", "Ime očeta ↔ ime ženina"),
        ("mother_name", "Ime matere ↔ ime neveste"),
        ("father_surname", "Priimek otroka/očeta ↔ priimek ženina"),
        ("mother_surname", "Priimek matere ↔ priimek neveste"),
        ("groom_address", "Naslov krsta ↔ naslov ženina"),
        ("bride_address", "Naslov krsta ↔ naslov neveste"),
        ("chronology", "Časovno zaporedje poroka staršev → rojstvo otroka"),
    ),
    "death_baptism": (
        ("name", "Ime pokojnika ↔ ime otroka"),
        ("surname", "Priimek pokojnika ↔ priimek iz krstnega zapisa"),
        ("address", "Ujemanje naslova"),
        ("chronology", "Rojstvo → poroka → smrt (ista oseba)"),
        ("age", "Starost ob poroki in smrti iste osebe"),
    ),
    "manual": (
        ("Priimek", "Priimek"),
        ("Ime", "Ime"),
        ("Starost in letnice", "Starost in letnice"),
        ("Naslov", "Naslov"),
        ("Družinski podatki", "Družinski podatki"),
        ("Kronologija", "Kronologija"),
        ("Župnija", "Župnija"),
    ),
}


def _merge_defaults(data):
    result = copy.deepcopy(DEFAULT_RULES)
    if not isinstance(data, dict):
        return result
    for key, value in data.items():
        if key == "weights" and isinstance(value, dict):
            for group, group_values in value.items():
                if group in result["weights"] and isinstance(group_values, dict):
                    result["weights"][group].update(group_values)
        elif key == "hidden_fields" and isinstance(value, dict):
            result[key] = {
                str(table): list(fields)
                for table, fields in value.items()
                if isinstance(fields, (list, tuple, set))
            }
        elif key in result:
            result[key] = value
    return result


def load_rule_settings():
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as handle:
            return _merge_defaults(json.load(handle))
    except (OSError, json.JSONDecodeError, TypeError):
        return copy.deepcopy(DEFAULT_RULES)


def save_rule_settings(settings):
    """Shrani nastavitve atomsko; ob napaki ohrani prejšnjo datoteko."""
    temp_path = SETTINGS_PATH.with_suffix(".json.tmp")
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        payload = _merge_defaults(settings)
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        temp_path.replace(SETTINGS_PATH)
        return True, str(SETTINGS_PATH)
    except (OSError, TypeError, ValueError) as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return False, str(exc)


class NastavitveUjemanjaDialog(tk.Toplevel):
    """Dialog za prag, časovna pravila in prilagodljive uteži algoritma."""

    def __init__(self, parent, settings=None, on_saved=None):
        super().__init__(parent)
        self.title("Nastavitve meril za iskanje morebitnih združitev")
        self.geometry("820x690")
        self.minsize(700, 580)
        self.transient(parent)
        self.grab_set()
        self.settings = _merge_defaults(settings or load_rule_settings())
        self.on_saved = on_saved
        self._vars = {}
        self._weight_vars = {}
        self._build()

    def _build(self):
        ttk.Label(
            self,
            text="Pravila določajo, katere zapise program predlaga. Ne potrjujejo identitete.",
            font=("Arial", 10, "bold"),
            wraplength=770,
        ).pack(fill="x", padx=12, pady=(12, 6))

        book = ttk.Notebook(self)
        book.pack(fill="both", expand=True, padx=10, pady=6)
        self._build_general_tab(book)
        self._build_weight_tab(book, "death_marriage", "Smrt – poroka")
        self._build_weight_tab(book, "marriage_baptism", "Poroka – krst otroka")
        self._build_weight_tab(book, "death_baptism", "Ista oseba – krst / poroka / smrt")
        self._build_weight_tab(book, "manual", "Ročni primerjalnik")

        bottom = ttk.Frame(self, padding=10)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="Obnovi priporočene vrednosti", command=self._restore_defaults).pack(side="left")
        ttk.Button(bottom, text="Prekliči", command=self.destroy).pack(side="right", padx=4)
        tk.Button(
            bottom, text="💾 SHRANI MERILA", command=self._save,
            bg="#16834A", fg="white", activebackground="#11683A",
            activeforeground="white", font=("Arial", 9, "bold"),
            relief="flat", padx=12, pady=6,
        ).pack(side="right", padx=4)

    def _build_general_tab(self, book):
        frame = ttk.Frame(book, padding=14)
        book.add(frame, text="Splošno in kronologija")
        general = ttk.LabelFrame(frame, text="Prag in stroga pravila", padding=10)
        general.pack(fill="x", pady=6)

        self._vars["minimum_score"] = tk.IntVar(value=int(self.settings["minimum_score"]))
        self._add_spin(general, 0, "Najnižja ocena kandidata (0–100):", self._vars["minimum_score"], 0, 100)

        bool_items = (
            ("strict_chronology", "Časovna protislovja pri isti osebi izloči iz predlogov"),
            ("allow_same_day_birth_death", "Dovoli rojstvo in smrt na isti datum (npr. umrl dojenček)"),
            ("allow_child_birth_before_marriage", "Dovoli otroka, rojenega pred poroko staršev, vendar ga označi kot izjemo"),
            ("use_father_surname", "Pri priimku otroka daj prednost priimku očeta"),
            ("use_mother_surname_when_father_missing", "Če oče ni vpisan, uporabi priimek matere kot primarni dokaz"),
        )
        for row, (key, label) in enumerate(bool_items, start=1):
            variable = tk.BooleanVar(value=bool(self.settings.get(key, True)))
            self._vars[key] = variable
            ttk.Checkbutton(general, text=label, variable=variable).grid(
                row=row, column=0, columnspan=2, sticky="w", pady=4
            )

        extra = ttk.LabelFrame(frame, text="Občutljivost primerjave", padding=10)
        extra.pack(fill="x", pady=8)
        self._vars["minimum_name_similarity"] = tk.DoubleVar(value=float(self.settings["minimum_name_similarity"]))
        self._add_spin(extra, 0, "Najmanjše ujemanje imena (0–1):", self._vars["minimum_name_similarity"], 0, 1, increment=0.05)
        self._vars["minimum_surname_similarity"] = tk.DoubleVar(value=float(self.settings["minimum_surname_similarity"]))
        self._add_spin(extra, 1, "Najmanjše ujemanje priimka (0–1):", self._vars["minimum_surname_similarity"], 0, 1, increment=0.05)
        self._vars["groom_address_factor"] = tk.DoubleVar(value=float(self.settings["groom_address_factor"]))
        self._add_spin(extra, 2, "Vpliv naslova ženina (0–1):", self._vars["groom_address_factor"], 0, 1, increment=0.05)
        self._vars["bride_address_factor"] = tk.DoubleVar(value=float(self.settings["bride_address_factor"]))
        self._add_spin(extra, 3, "Vpliv naslova neveste (0–1):", self._vars["bride_address_factor"], 0, 1, increment=0.05)
        self._vars["mother_surname_weight_if_father_present"] = tk.DoubleVar(
            value=float(self.settings["mother_surname_weight_if_father_present"])
        )
        self._add_spin(
            extra, 4, "Vpliv materinega priimka, ko je oče vpisan (0–1):",
            self._vars["mother_surname_weight_if_father_present"], 0, 1, increment=0.05,
        )

        ttk.Label(
            frame,
            text=(
                "Pomembna razlika: pri povezavi ISTE OSEBE velja rojstvo ≤ poroka ≤ smrt. "
                "Pri povezavi STARŠA → OTROK je poroka staršev običajno pred rojstvom otroka. "
                "Predporočni otrok je zgodovinsko mogoč, zato ga privzeto ne zavrnemo, ampak ga posebej označimo."
            ),
            wraplength=750, justify="left", foreground="#705000",
        ).pack(fill="x", pady=8)

    @staticmethod
    def _add_spin(parent, row, label, variable, minimum, maximum, increment=1):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=5)
        spin = tk.Spinbox(
            parent, from_=minimum, to=maximum, increment=increment,
            textvariable=variable, width=8, justify="right",
        )
        spin.grid(row=row, column=1, sticky="w", padx=8, pady=5)

    def _build_weight_tab(self, book, group, title):
        frame = ttk.Frame(book, padding=14)
        book.add(frame, text=title)
        ttk.Label(
            frame,
            text="Uteži določajo relativno pomembnost dokazov. Uteži ni treba sešteti na 100; program jih normalizira.",
            wraplength=730,
        ).pack(fill="x", pady=(0, 10))
        box = ttk.LabelFrame(frame, text="Uteži posameznih dokazov (0–100)", padding=10)
        box.pack(fill="x", anchor="n")
        self._weight_vars[group] = {}
        values = self.settings["weights"].get(group, {})
        for row, (key, label) in enumerate(WEIGHT_LABELS[group]):
            variable = tk.IntVar(value=int(values.get(key, 0)))
            self._weight_vars[group][key] = variable
            self._add_spin(box, row, label, variable, 0, 100)
        if group == "marriage_baptism":
            ttk.Label(
                frame,
                text=(
                    "Priimek po očetu je primarni dokaz. Priimek matere je podporni dokaz; "
                    "če oče ni naveden, lahko priimek matere postane primarni dokaz. "
                    "Naslov neveste ima manjšo utež, ker se je lahko po poroki preselila."
                ),
                foreground="#705000", wraplength=730, justify="left",
            ).pack(fill="x", pady=12)
        elif group == "death_marriage":
            ttk.Label(
                frame,
                text="Poroka mora biti pred smrtjo iste osebe. Naslov ženina ima privzeto večjo utež; naslov neveste se je lahko po poroki spremenil.",
                foreground="#705000", wraplength=730, justify="left",
            ).pack(fill="x", pady=12)

    def _restore_defaults(self):
        defaults = copy.deepcopy(DEFAULT_RULES)
        for key, variable in self._vars.items():
            variable.set(defaults[key])
        for group, variables in self._weight_vars.items():
            for key, variable in variables.items():
                variable.set(defaults["weights"][group][key])

    def _save(self):
        data = copy.deepcopy(self.settings)
        try:
            for key, variable in self._vars.items():
                value = variable.get()
                if key in (
                    "minimum_name_similarity", "minimum_surname_similarity",
                    "groom_address_factor", "bride_address_factor",
                    "mother_surname_weight_if_father_present",
                ):
                    value = max(0.0, min(1.0, float(value)))
                elif key == "minimum_score":
                    value = max(0, min(100, int(value)))
                data[key] = value
            for group, variables in self._weight_vars.items():
                data["weights"][group] = {
                    key: max(0, min(100, int(variable.get())))
                    for key, variable in variables.items()
                }
        except (ValueError, tk.TclError) as exc:
            messagebox.showerror("Neveljavne vrednosti", f"Preveri vpisane uteži in pragove.\n{exc}", parent=self)
            return

        ok, message = save_rule_settings(data)
        if not ok:
            messagebox.showerror("Napaka shranjevanja", message, parent=self)
            return
        self.settings = data
        if self.on_saved:
            self.on_saved(data)
        messagebox.showinfo("Merila shranjena", f"Nastavitve ujemanja so shranjene.\n{SETTINGS_PATH.name}", parent=self)
        self.destroy()


class PoljaPrimerjalnikaDialog(tk.Toplevel):
    """Uporabniku omogoči skriti ali ponovno prikazati vsako polje posameznega zapisa."""

    TABLE_LABELS = {"krsti": "Krstni zapis", "poroke": "Poročni zapis", "mrtvi": "Mrliški zapis"}

    def __init__(self, parent, records, settings, on_saved=None):
        super().__init__(parent)
        self.title("Izbira podatkov v primerjalniku")
        self.geometry("780x650")
        self.minsize(600, 500)
        self.transient(parent)
        self.grab_set()
        self.records = records
        self.settings = _merge_defaults(settings)
        self.on_saved = on_saved
        self.vars = {table: {} for table in self.TABLE_LABELS}
        self._build()

    @staticmethod
    def _field_title(key):
        labels = {
            "id": "ID zapisa", "zupnija": "Župnija", "knjiga": "Knjiga",
            "slika": "Matricula – številka slike", "vpis_st_knjige": "Vpisna številka",
            "datum_rojstva": "Datum rojstva", "datum_krsta": "Datum krsta",
            "ime_otroka": "Ime otroka", "priimek_otroka": "Priimek otroka",
            "ime_oceta": "Ime očeta", "priimek_oceta": "Priimek očeta",
            "alt_priimek_oceta": "Drugi priimek očeta", "ime_matere": "Ime matere",
            "priimek_matere": "Priimek matere", "alt_priimek_matere": "Drugi priimek matere",
            "naslov": "Naslov", "datum_poroke": "Datum poroke",
            "ime_zenina": "Ime ženina", "priimek_zenina": "Priimek ženina",
            "starost_zenina": "Starost ženina", "stan_zenina": "Stan ženina",
            "naslov_zenina": "Naslov ženina", "ime_neveste": "Ime neveste",
            "priimek_neveste": "Priimek neveste", "starost_neveste": "Starost neveste",
            "stan_neveste": "Stan neveste", "naslov_neveste": "Naslov neveste",
            "datum_smrti": "Datum smrti", "datum_pokopa": "Datum pokopa",
            "ime_pokojnika": "Ime pokojnika", "priimek_pokojnika": "Priimek pokojnika",
            "starost": "Starost", "zakonec_starsi": "Zakonec / starši",
            "vzrok_smrti": "Vzrok smrti", "opombe": "Opombe", "surovi_tekst": "Surovi prepis",
        }
        return labels.get(key, key.replace("_", " ").capitalize())

    def _build(self):
        ttk.Label(
            self,
            text="Privzeto so prikazana vsa polja. Odkljukaj samo tista, ki jih želiš skriti; pozneje jih lahko znova vključiš.",
            wraplength=730,
        ).pack(fill="x", padx=12, pady=10)
        book = ttk.Notebook(self)
        book.pack(fill="both", expand=True, padx=10, pady=5)
        hidden = self.settings.get("hidden_fields", {})
        for table, title in self.TABLE_LABELS.items():
            frame = ttk.Frame(book)
            book.add(frame, text=title)
            canvas = tk.Canvas(frame, highlightthickness=0)
            scroll = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
            inner = ttk.Frame(canvas, padding=8)
            inner.bind("<Configure>", lambda _event, c=canvas: c.configure(scrollregion=c.bbox("all")))
            canvas.create_window((0, 0), window=inner, anchor="nw")
            canvas.configure(yscrollcommand=scroll.set)
            canvas.pack(side="left", fill="both", expand=True)
            scroll.pack(side="right", fill="y")
            record = self.records.get(table) or {}
            keys = list(record.keys())
            if not keys:
                ttk.Label(inner, text="Zapis za to knjigo ni izbran.", foreground="gray").pack(anchor="w")
                continue
            hidden_keys = set(hidden.get(table, []))
            for key in keys:
                variable = tk.BooleanVar(value=key not in hidden_keys)
                self.vars[table][key] = variable
                ttk.Checkbutton(inner, text=self._field_title(key), variable=variable).pack(anchor="w", pady=2)
        buttons = ttk.Frame(self, padding=10)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Prikaži vsa polja", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(buttons, text="Skrij vsa polja", command=lambda: self._set_all(False)).pack(side="left", padx=5)
        ttk.Button(buttons, text="Prekliči", command=self.destroy).pack(side="right", padx=4)
        tk.Button(
            buttons, text="💾 SHRANI PRIKAZ", command=self._save,
            bg="#16834A", fg="white", activebackground="#11683A",
            activeforeground="white", font=("Arial", 9, "bold"), relief="flat", padx=12, pady=6,
        ).pack(side="right", padx=4)

    def _set_all(self, value):
        for table_vars in self.vars.values():
            for variable in table_vars.values():
                variable.set(value)

    def _save(self):
        data = copy.deepcopy(self.settings)
        saved_hidden = dict(data.get("hidden_fields", {}))
        for table, variables in self.vars.items():
            # Če v tej primerjavi zapis za tabelo ni izbran, ohrani prejšnjo
            # uporabnikovo nastavitev za to tabelo.
            if self.records.get(table):
                saved_hidden[table] = [
                    key for key, variable in variables.items() if not variable.get()
                ]
        data["hidden_fields"] = saved_hidden
        ok, message = save_rule_settings(data)
        if not ok:
            messagebox.showerror("Napaka shranjevanja", message, parent=self)
            return
        if self.on_saved:
            self.on_saved(data)
        self.destroy()

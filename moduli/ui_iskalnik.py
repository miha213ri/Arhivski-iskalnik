"""Uporabniški vmesnik za iskanje in povezovanje arhivskih zapisov."""

import tkinter as tk
from tkinter import ttk, messagebox

from .nastavitve import NastavitveBazeDialog
from .glavna_baza import GlavnaBaza
from .ui_iskalnik_podrobnosti import IskalnikPodrobnostiMixin
from .ui_iskalnik_izvoz import IskalnikIzvozMixin
from .ui_mozne_zdruzevanj import MorebitneZdruzitveUI


class IskalnikUI(IskalnikPodrobnostiMixin, IskalnikIzvozMixin):
    def __init__(self, parent_frame, db_slovar, settings, on_settings_changed=None):
        self.frame = parent_frame
        self.db_slovar = db_slovar
        self.settings = settings or {}
        self.on_settings_changed = on_settings_changed

        self.limit = 100
        self.zadnji_pogoji = {}
        self.napredni_pogoji_lista = []
        self.page_offsets = {"krsti": 0, "poroke": 0, "mrtvi": 0}
        self.page_totals = {"krsti": 0, "poroke": 0, "mrtvi": 0}
        self.primerjalnik_idji = {"krsti": None, "poroke": None, "mrtvi": None}
        self.primerjalnik_tip_povezave = None
        self.trenutni_kliknjen_iid = None

        self.build_ui()

    def build_ui(self):
        search_frame = ttk.LabelFrame(self.frame, text=" Osnovno iskanje (potrdi z ENTER) ", padding=10)
        search_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(search_frame, text="Ime:").grid(row=0, column=0, sticky="w", padx=5)
        self.ent_ime = ttk.Entry(search_frame, width=17)
        self.ent_ime.grid(row=0, column=1, padx=5, pady=5)
        self.ent_ime.bind("<Return>", lambda _event: self.sprozi_novo_iskanje())

        ttk.Label(search_frame, text="Priimek:").grid(row=0, column=2, sticky="w", padx=5)
        self.ent_priimek = ttk.Entry(search_frame, width=17)
        self.ent_priimek.grid(row=0, column=3, padx=5, pady=5)
        self.ent_priimek.bind("<Return>", lambda _event: self.sprozi_novo_iskanje())

        ttk.Label(search_frame, text="Letnica:").grid(row=0, column=4, sticky="w", padx=5)
        self.ent_letnica = ttk.Entry(search_frame, width=9)
        self.ent_letnica.grid(row=0, column=5, padx=5, pady=5)
        self.ent_letnica.bind("<Return>", lambda _event: self.sprozi_novo_iskanje())

        self.btn_iskanje = tk.Button(
            search_frame, text="🔍 PAMETNO ISKANJE", command=self.sprozi_novo_iskanje,
            bg="#7136A8", fg="white", activebackground="#572B83", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=10, pady=5,
        )
        self.btn_iskanje.grid(row=0, column=6, padx=8)
        self.btn_primerjalnik = tk.Button(
            search_frame, text="⚖ PRIMERJALNIK (0)", command=self.odpri_primerjalnik,
            bg="#E58A16", fg="white", activebackground="#B96B0E", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=10, pady=5,
        )
        self.btn_primerjalnik.grid(row=0, column=7, padx=8)
        ttk.Button(search_frame, text="📊 Statistika", command=self.prikazi_statistiko).grid(row=0, column=8, padx=5)
        self.btn_settings = ttk.Button(
            search_frame, text="⚙ Nastavitve", command=self.open_db_settings
        )
        self.btn_settings.grid(row=0, column=9, padx=5)

        adv_frame = ttk.LabelFrame(self.frame, text=" Napredno iskanje ", padding=10)
        adv_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(adv_frame, text="Knjiga:").grid(row=0, column=0, padx=2)
        self.cb_knjiga = ttk.Combobox(
            adv_frame,
            values=["VSE", "KRSTI", "POROKE", "MRTVI"],
            width=9,
            state="readonly",
        )
        self.cb_knjiga.current(0)
        self.cb_knjiga.grid(row=0, column=1, padx=2)
        self.cb_knjiga.bind("<<ComboboxSelected>>", self.osvezi_napredna_polja)

        ttk.Label(adv_frame, text="Logika:").grid(row=0, column=2, padx=2)
        self.cb_logika = ttk.Combobox(
            adv_frame,
            values=["AND", "OR", "AND NOT"],
            width=9,
            state="readonly",
        )
        self.cb_logika.current(0)
        self.cb_logika.grid(row=0, column=3, padx=2)

        ttk.Label(adv_frame, text="Polje:").grid(row=0, column=4, padx=2)
        self.cb_polje = ttk.Combobox(adv_frame, width=19, state="readonly")
        self.cb_polje.grid(row=0, column=5, padx=2)

        ttk.Label(adv_frame, text="Vrednost:").grid(row=0, column=6, padx=2)
        self.ent_napredno = ttk.Entry(adv_frame, width=22)
        self.ent_napredno.grid(row=0, column=7, padx=2)
        self.ent_napredno.bind("<Return>", lambda _event: self.dodaj_napredni_pogoj())
        ttk.Button(adv_frame, text="➕ Dodaj pogoj", command=self.dodaj_napredni_pogoj).grid(row=0, column=8, padx=8)

        self.list_pogoji = tk.Listbox(adv_frame, height=3, width=75)
        self.list_pogoji.grid(row=1, column=0, columnspan=8, pady=5, sticky="we")
        controls = ttk.Frame(adv_frame)
        controls.grid(row=1, column=8, sticky="n", pady=5)
        ttk.Button(controls, text="Uredi izbran", command=self.uredi_napredni_pogoj).pack(fill="x", pady=2)
        ttk.Button(controls, text="Odstrani izbran", command=self.odstrani_napredni_pogoj).pack(fill="x", pady=2)
        ttk.Button(controls, text="Počisti vse", command=self.pocisti_napredne_pogoje).pack(fill="x", pady=2)
        self.osvezi_napredna_polja()

        self.res_notebook = ttk.Notebook(self.frame)
        self.res_notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self.tab_krsti = ttk.Frame(self.res_notebook)
        self.res_notebook.add(self.tab_krsti, text=" Krstne knjige ")
        self.tree_krsti = self.ustvari_tabelo(
            self.tab_krsti,
            ("idx", "datum", "ime", "priimek", "oce", "mati_ime", "mati_priimek", "naslov", "opombe", "vir"),
        )

        self.tab_poroke = ttk.Frame(self.res_notebook)
        self.res_notebook.add(self.tab_poroke, text=" Poročne knjige ")
        self.tree_poroke = self.ustvari_tabelo(
            self.tab_poroke,
            ("idx", "datum", "ime_zenina", "priimek_zenina", "starost_z", "ime_neveste", "priimek_neveste", "starost_n", "opombe", "vir"),
        )

        self.tab_mrtvi = ttk.Frame(self.res_notebook)
        self.res_notebook.add(self.tab_mrtvi, text=" Mrliške knjige ")
        self.tree_mrtvi = self.ustvari_tabelo(
            self.tab_mrtvi,
            ("idx", "datum_smrti", "ime", "priimek", "starost", "starsi_zakonec", "vzrok_smrti", "naslov", "opombe", "vir"),
        )

        self.tab_mozne_zdruzitve = ttk.Frame(self.res_notebook)
        self.res_notebook.add(self.tab_mozne_zdruzitve, text=" Morebitne združitve ")
        self.mozne_zdruzitve_ui = MorebitneZdruzitveUI(
            self.tab_mozne_zdruzitve,
            settings_getter=lambda: self.settings,
            connected_getter=lambda: bool(getattr(self.db_slovar, "initialized", False)),
            on_use_candidate=self.prenesi_kandidata_v_primerjalnik,
        )

        self._tab_to_table = {
            str(self.tab_krsti): "krsti",
            str(self.tab_poroke): "poroke",
            str(self.tab_mrtvi): "mrtvi",
        }
        self.res_notebook.bind("<<NotebookTabChanged>>", self.on_result_tab_changed)

        page_frame = ttk.Frame(self.frame)
        page_frame.pack(fill="x", pady=5)
        self.btn_prejsnja = ttk.Button(page_frame, text="◀ Prejšnja stran", command=self.prejsnja_stran)
        self.btn_prejsnja.pack(side="left", padx=10)
        self.lbl_stran = ttk.Label(page_frame, text="Stran 1", font=("Arial", 9, "bold"))
        self.lbl_stran.pack(side="left", padx=20)
        self.btn_naslednja = ttk.Button(page_frame, text="Naslednja stran ▶", command=self.naslednja_stran)
        self.btn_naslednja.pack(side="left")
        self.btn_prejsnja.configure(state="disabled")
        self.btn_naslednja.configure(state="disabled")
        self.lbl_stran.configure(text="Krsti – stran 1 (0 zadetkov)")
        self.btn_export_all = tk.Button(
            page_frame, text="📊 IZVOZI VSE ZADETKE V EXCEL",
            command=self.izvozi_vse_knjige_excel, bg="#16834A", fg="white",
            activebackground="#11683A", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=10, pady=4,
        )
        self.btn_export_all.pack(side="right", padx=10)
        self.btn_export_all.configure(state="disabled")

        self.context_menu = tk.Menu(self.frame, tearoff=0)
        self.context_menu.add_command(
            label="🔗 Dodaj zapis v primerjalnik",
            command=self.dodaj_v_primerjalnik,
        )

    def ustvari_tabelo(self, parent, columns):
        """Ustvari tabelo rezultatov z navpičnim in vodoravnim drsnikom."""
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True)
        tree = ttk.Treeview(container, columns=columns, show="headings", selectmode="browse")

        labels = {
            "idx": "Vpis št.", "datum": "Datum", "datum_smrti": "Datum smrti",
            "ime": "Ime", "priimek": "Priimek", "oce": "Oče",
            "mati_ime": "Mati – ime", "mati_priimek": "Mati – priimek",
            "naslov": "Naslov", "opombe": "Opombe", "vir": "Vir",
            "ime_zenina": "Ženin – ime", "priimek_zenina": "Ženin – priimek",
            "starost_z": "Starost ženina", "ime_neveste": "Nevesta – ime",
            "priimek_neveste": "Nevesta – priimek", "starost_n": "Starost neveste",
            "starost": "Starost", "starsi_zakonec": "Zakonec / starši",
            "vzrok_smrti": "Vzrok smrti",
        }
        widths = {
            "idx": 75, "datum": 105, "datum_smrti": 105, "ime": 130,
            "priimek": 130, "oce": 130, "mati_ime": 130, "mati_priimek": 130,
            "naslov": 170, "opombe": 220, "vir": 260,
            "ime_zenina": 125, "priimek_zenina": 125, "starost_z": 90,
            "ime_neveste": 125, "priimek_neveste": 125, "starost_n": 90,
            "starost": 90, "starsi_zakonec": 190, "vzrok_smrti": 180,
        }
        for column in columns:
            tree.heading(column, text=labels.get(column, column.replace("_", " ").title()))
            tree.column(column, width=widths.get(column, 120), minwidth=60, stretch=True)

        vertical = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(container, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        container.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        tree.bind("<Double-1>", self.on_row_double_click)
        tree.bind("<Button-3>", self.on_right_click)
        return tree

    def osvezi_napredna_polja(self, event=None):
        knjiga = self.cb_knjiga.get()
        splosna = ["Župnija", "Kraj/Naslov", "Knjiga", "Letnica", "Opombe", "Surovi tekst"]
        if knjiga == "KRSTI":
            polja = splosna + [
                "ime_otroka", "ime_oceta", "priimek_oceta", "ime_matere",
                "priimek_matere", "poklic_oceta", "izvor_oceta", "botri", "babica", "duhovnik",
            ]
        elif knjiga == "POROKE":
            polja = splosna + [
                "ime_zenina", "priimek_zenina", "ime_neveste", "priimek_neveste",
                "stan_zenina", "stan_neveste", "price", "duhovnik",
            ]
        elif knjiga == "MRTVI":
            polja = splosna + [
                "ime_pokojnika", "priimek_pokojnika", "vzrok_smrti",
                "zakonec_starsi", "stan_pokojnika", "duhovnik", "starost",
            ]
        else:
            polja = splosna
        self.cb_polje.configure(values=polja)
        if polja:
            self.cb_polje.current(0)

    @staticmethod
    def _opis_pogoja(pogoj):
        return "[{knjiga}] {logika} '{polje}' vsebuje '{vrednost}'".format(**pogoj)

    def dodaj_napredni_pogoj(self):
        pogoj = {
            "knjiga": self.cb_knjiga.get(),
            "logika": self.cb_logika.get(),
            "polje": self.cb_polje.get(),
            "vrednost": self.ent_napredno.get().strip(),
        }
        if not pogoj["vrednost"]:
            messagebox.showwarning("Pozor", "Vnesite vrednost za iskanje.", parent=self.frame)
            return
        self.napredni_pogoji_lista.append(pogoj)
        self.list_pogoji.insert(tk.END, self._opis_pogoja(pogoj))
        self.ent_napredno.delete(0, tk.END)

    def uredi_napredni_pogoj(self):
        selected = self.list_pogoji.curselection()
        if not selected:
            return
        index = selected[0]
        pogoj = self.napredni_pogoji_lista[index]
        self.cb_knjiga.set(pogoj["knjiga"])
        self.osvezi_napredna_polja()
        self.cb_logika.set(pogoj["logika"])
        self.cb_polje.set(pogoj["polje"])
        self.ent_napredno.delete(0, tk.END)
        self.ent_napredno.insert(0, pogoj["vrednost"])
        self.list_pogoji.delete(index)
        del self.napredni_pogoji_lista[index]

    def odstrani_napredni_pogoj(self):
        selected = self.list_pogoji.curselection()
        if selected:
            index = selected[0]
            self.list_pogoji.delete(index)
            del self.napredni_pogoji_lista[index]

    def pocisti_napredne_pogoje(self):
        self.list_pogoji.delete(0, tk.END)
        self.napredni_pogoji_lista.clear()



    def open_db_settings(self):
        NastavitveBazeDialog(self.frame, self.on_settings_saved)

    def on_settings_saved(self, new_settings):
        self.settings = new_settings
        if self.on_settings_changed:
            self.on_settings_changed(new_settings)

    def _require_connection(self):
        """Prepreči samodejno povezovanje ob kliku, dokler uporabnik ne potrdi povezave."""
        if not getattr(self.db_slovar, "initialized", False):
            messagebox.showwarning(
                "Povezava ni vzpostavljena",
                "Najprej odpri Nastavitve povezave, preveri podatke in klikni "
                "'Poveži z bazo'.",
                parent=self.frame,
            )
            return False
        return True

    def prikazi_statistiko(self):
        if not self._require_connection():
            return
        baza = GlavnaBaza(self.settings.get("LiveDB", {}))
        uspeh, podatki = baza.get_statistika()
        if uspeh:
            msg = (
                f"Unikatne župnije: {podatki.get('zupnije')}\n"
                f"Število krstov: {podatki.get('krsti')}\n"
                f"Število porok: {podatki.get('poroke')}\n"
                f"Število mrliških zapisov: {podatki.get('mrtvi')}\n"
                f"Zgrajene osebe: {podatki.get('zgrajene_osebe')}"
            )
            messagebox.showinfo("Statistika glavne baze", msg, parent=self.frame)
        else:
            messagebox.showerror("Napaka baze", f"Ni se mogoče povezati:\n{podatki}", parent=self.frame)

    def pridobi_variacije_iz_slovarja(self, iskalni_niz, tip):
        """Vsebino iz polja vedno pošlje v MySQL; slovar samo razširi sinonime."""
        raw_value = str(iskalni_niz or "").strip()
        if not raw_value:
            return []
        try:
            terms = self.db_slovar.get_search_terms(raw_value, tip)
            return terms if terms else [raw_value]
        except Exception:
            # Osnovno iskanje po MySQL mora delovati tudi, če je slovar nedosegljiv.
            return [raw_value]

    def sprozi_novo_iskanje(self):
        if not self._require_connection():
            return
        self.page_offsets = {"krsti": 0, "poroke": 0, "mrtvi": 0}
        name = self.ent_ime.get().strip()
        surname = self.ent_priimek.get().strip()
        year = self.ent_letnica.get().strip()

        if not any((name, surname, year, self.napredni_pogoji_lista)):
            messagebox.showwarning(
                "Manjkajoči iskalni pogoj",
                "Vnesi ime, priimek, letnico ali dodaj napredni pogoj.",
                parent=self.frame,
            )
            return

        names = self.pridobi_variacije_iz_slovarja(name, "ime") if name else []
        surnames = self.pridobi_variacije_iz_slovarja(surname, "priimek") if surname else []
        self.zadnji_pogoji = {
            "imena": names,
            "priimki": surnames,
            "letnica": year,
            "napredno": [dict(item) for item in self.napredni_pogoji_lista],
        }
        self.izvedi_iskanje()

    def izvedi_iskanje(self):
        # Vsaka sprememba pogojev sproži svežo SQL-poizvedbo v glavni MySQL-bazi;
        # rezultati se ne filtrirajo iz lokalno prenesenega seznama.
        baza = GlavnaBaza(self.settings.get("LiveDB", {}))
        uspeh, rezultati = baza.pametno_iskanje(
            self.zadnji_pogoji.get("imena", []),
            self.zadnji_pogoji.get("priimki", []),
            self.zadnji_pogoji.get("letnica", ""),
            napredni_pogoji=self.zadnji_pogoji.get("napredno", []),
            limit=self.limit,
            offset=self.page_offsets,
        )

        for tree in (self.tree_krsti, self.tree_poroke, self.tree_mrtvi):
            for item in tree.get_children():
                tree.delete(item)

        if not uspeh:
            self.page_totals = {"krsti": 0, "poroke": 0, "mrtvi": 0}
            self.btn_export_all.configure(state="disabled")
            messagebox.showerror("Napaka pri iskanju", str(rezultati), parent=self.frame)
            return

        totals = {table: rezultati.get(table, {}).get("total", 0) for table in ("krsti", "poroke", "mrtvi")}
        self.page_totals = totals
        self.res_notebook.tab(self.tab_krsti, text=f" Krstne knjige ({totals['krsti']}) ")
        self.res_notebook.tab(self.tab_poroke, text=f" Poročne knjige ({totals['poroke']}) ")
        self.res_notebook.tab(self.tab_mrtvi, text=f" Mrliške knjige ({totals['mrtvi']}) ")

        for row in rezultati.get("krsti", {}).get("data", []):
            self.tree_krsti.insert(
                "", "end", iid=f"krsti_{row.get('id')}",
                values=(row.get("idx", ""), row.get("datum", ""), row.get("ime", ""),
                        row.get("priimek", ""), row.get("oce", ""), row.get("mati_ime", ""),
                        row.get("mati_priimek", ""), row.get("naslov", ""), row.get("opombe", ""), row.get("vir", "")),
            )
        for row in rezultati.get("poroke", {}).get("data", []):
            self.tree_poroke.insert(
                "", "end", iid=f"poroke_{row.get('id')}",
                values=(row.get("idx", ""), row.get("datum", ""), row.get("ime_zenina", ""),
                        row.get("priimek_zenina", ""), row.get("starost_z", ""), row.get("ime_neveste", ""),
                        row.get("priimek_neveste", ""), row.get("starost_n", ""), row.get("opombe", ""), row.get("vir", "")),
            )
        for row in rezultati.get("mrtvi", {}).get("data", []):
            self.tree_mrtvi.insert(
                "", "end", iid=f"mrtvi_{row.get('id')}",
                values=(row.get("idx", ""), row.get("datum_smrti", ""), row.get("ime_pokojnika", ""),
                        row.get("priimek_pokojnika", ""), row.get("starost", ""), row.get("zakonec_starsi", ""),
                        row.get("vzrok_smrti", ""), row.get("naslov", ""), row.get("opombe", ""), row.get("vir", "")),
            )

        self.posodobi_paginacijo()

    def aktivna_knjiga(self):
        """Vrne knjigo ali None, če je izbran zavihek morebitnih združitev."""
        selected = self.res_notebook.select()
        return self._tab_to_table.get(selected)

    def on_result_tab_changed(self, _event=None):
        self.posodobi_paginacijo()

    def posodobi_paginacijo(self):
        tabela = self.aktivna_knjiga()
        if tabela is None:
            self.lbl_stran.configure(text="Morebitne združitve – brez paginacije")
            self.btn_prejsnja.configure(state="disabled")
            self.btn_naslednja.configure(state="disabled")
            self.btn_export_all.configure(state="disabled")
            return
        offset = self.page_offsets[tabela]
        total = self.page_totals[tabela]
        stran = offset // self.limit + 1
        strani = max(1, (total + self.limit - 1) // self.limit)
        oznake = {"krsti": "Krsti", "poroke": "Poroke", "mrtvi": "Mrliški"}
        self.lbl_stran.configure(text=f"{oznake[tabela]} – stran {stran}/{strani} ({total} zadetkov)")
        self.btn_prejsnja.configure(state="normal" if offset > 0 else "disabled")
        self.btn_naslednja.configure(
            state="normal" if offset + self.limit < total else "disabled"
        )
        self.btn_export_all.configure(state="normal" if self.zadnji_pogoji else "disabled")

    def prejsnja_stran(self):
        tabela = self.aktivna_knjiga()
        if tabela is None:
            return
        if self.page_offsets[tabela] >= self.limit:
            self.page_offsets[tabela] -= self.limit
            self.izvedi_iskanje()

    def naslednja_stran(self):
        tabela = self.aktivna_knjiga()
        if tabela is None:
            return
        if self.zadnji_pogoji and self.page_offsets[tabela] + self.limit < self.page_totals[tabela]:
            self.page_offsets[tabela] += self.limit
            self.izvedi_iskanje()


    def osvezi_seznam_zupnij(self):
        """Po uspešni MySQL prijavi osveži izbiro za avtomatsko povezovanje."""
        if hasattr(self, "mozne_zdruzitve_ui"):
            self.mozne_zdruzitve_ui.refresh_parishes()

    def prenesi_kandidata_v_primerjalnik(self, candidate):
        """Prenese predlog v obstoječi ročni primerjalnik – brez samodejnega shranjevanja."""
        self.primerjalnik_idji = {
            "krsti": str(candidate["krsti"].get("id")) if candidate.get("krsti") else None,
            "poroke": str(candidate["poroke"].get("id")) if candidate.get("poroke") else None,
            "mrtvi": str(candidate["mrtvi"].get("id")) if candidate.get("mrtvi") else None,
        }
        self.primerjalnik_tip_povezave = candidate.get("relation_type") or (
            "parents_child" if candidate.get("poroke") and candidate.get("krsti") else "same_person"
        )
        count = sum(value is not None for value in self.primerjalnik_idji.values())
        self.btn_primerjalnik.configure(text=f"⚖ PRIMERJALNIK ({count})")
        self.odpri_primerjalnik()

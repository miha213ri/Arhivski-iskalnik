"""Podrobnosti arhivskih zapisov in ročni primerjalnik z vsemi izvornimi polji."""

import json
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox

from .glavna_baza import GlavnaBaza
from .arhivske_povezave import matricula_url
from .ocena_ujemanja import oceni_ujemanje
from .nastavitve_ujemanja import (
    load_rule_settings,
    NastavitveUjemanjaDialog,
    PoljaPrimerjalnikaDialog,
)


class IskalnikPodrobnostiMixin:
    def on_row_double_click(self, event):
        if not self._require_connection():
            return
        tree = event.widget
        iid = tree.identify_row(event.y)
        if not iid or "_" not in iid:
            return
        tabela, record_id = iid.split("_", 1)
        baza = GlavnaBaza(self.settings.get("LiveDB", {}))
        uspeh, podatki = baza.get_podrobnosti(tabela, record_id)
        if uspeh and podatki:
            self.prikazi_podrobnosti_okno(tabela, podatki)
        elif uspeh:
            messagebox.showwarning("Zapis ni najden", "Izbrani zapis ne obstaja več.", parent=self.frame)
        else:
            messagebox.showerror("Napaka", f"Ne morem naložiti podrobnosti:\n{podatki}", parent=self.frame)

    def on_right_click(self, event):
        tree = event.widget
        iid = tree.identify_row(event.y)
        if not iid:
            return
        tree.selection_set(iid)
        self.trenutni_kliknjen_iid = iid
        self.context_menu.tk_popup(event.x_root, event.y_root)

    def dodaj_v_primerjalnik(self):
        if not self.trenutni_kliknjen_iid:
            return
        tabela, record_id = self.trenutni_kliknjen_iid.split("_", 1)
        if tabela not in self.primerjalnik_idji:
            return
        self.primerjalnik_idji[tabela] = record_id
        if self.primerjalnik_idji.get("krsti") and self.primerjalnik_idji.get("poroke"):
            if not getattr(self, "primerjalnik_tip_povezave", None):
                self.primerjalnik_tip_povezave = "parents_child"
        stevilo = sum(value is not None for value in self.primerjalnik_idji.values())
        self.btn_primerjalnik.configure(text=f"⚖ PRIMERJALNIK ({stevilo})")

    def odpri_primerjalnik(self):
        if not self._require_connection():
            return
        win = tk.Toplevel(self.frame)
        win.title("Primerjalnik – preverjanje in potrditev osebe")
        win.geometry("1200x820")
        win.minsize(900, 650)
        win.transient(self.frame.winfo_toplevel())

        baza = GlavnaBaza(self.settings.get("LiveDB", {}))
        records = {}
        read_errors = []
        for table in ("krsti", "poroke", "mrtvi"):
            record_id = self.primerjalnik_idji.get(table)
            if not record_id:
                records[table] = None
                continue
            success, data = baza.get_podrobnosti(table, record_id)
            records[table] = dict(data) if success and data else None
            if not success:
                read_errors.append(f"{table}: {data}")

        rules = load_rule_settings()
        initial_relation = getattr(self, "primerjalnik_tip_povezave", None)
        if initial_relation not in ("same_person", "parents_child"):
            initial_relation = "parents_child" if records.get("krsti") and records.get("poroke") else "same_person"
        relation_labels = {
            "Starši iz poroke → otrok iz krsta": "parents_child",
            "Krst/rojstvo → poroka → smrt iste osebe": "same_person",
        }
        relation_by_value = {value: key for key, value in relation_labels.items()}
        relation_var = tk.StringVar(value=relation_by_value[initial_relation])

        heading = ttk.Frame(win, padding=(12, 10, 12, 4))
        heading.pack(fill="x")
        ttk.Label(
            heading,
            text="Primerjava zapisov – ocena je pomoč pri odločanju, ne dokaz identitete.",
            font=("Arial", 12, "bold"),
        ).pack(anchor="w")
        relation_row = ttk.Frame(heading)
        relation_row.pack(fill="x", pady=(7, 0))
        ttk.Label(relation_row, text="Vrsta razmerja:").pack(side="left", padx=(0, 7))
        relation_combo = ttk.Combobox(
            relation_row, textvariable=relation_var, values=list(relation_labels),
            state="readonly", width=43,
        )
        relation_combo.pack(side="left")
        ttk.Label(
            relation_row,
            text="Izberi pravilno razlago: krst otroka zakoncev ali rojstni zapis iste osebe.",
            foreground="#705000",
        ).pack(side="left", padx=10)

        score_frame = ttk.LabelFrame(win, text="Ocena ujemanja izbranih zapisov", padding=8)
        score_frame.pack(fill="x", padx=12, pady=7)

        panels = ttk.Frame(win)
        panels.pack(fill="both", expand=True, padx=12, pady=5)
        notebook = ttk.Notebook(panels)
        notebook.pack(fill="both", expand=True)

        def current_relation():
            return relation_labels.get(relation_var.get(), "parents_child")

        def refresh_score():
            for child in score_frame.winfo_children():
                child.destroy()
            relation_type = current_relation()
            score = oceni_ujemanje(
                krsti=records.get("krsti"),
                poroke=records.get("poroke"),
                mrtvi=records.get("mrtvi"),
                settings=rules,
                relation_type=relation_type,
            )
            if score["hard_conflicts"]:
                score_text = f"0/100 – ČASOVNO PROTISLOVJE – preveri zapise"
                score_color = "#A43B35"
            elif score["score"] is None:
                score_text = "Ocene ni mogoče izračunati – premalo primerljivih podatkov."
                score_color = "#686868"
            else:
                score_text = (
                    f"{score['score']}/100 – {score['label']}  "
                    f"(pokritost razpoložljivih dokazov: {score['coverage']} %)"
                )
                if score["score"] >= 85 and score["coverage"] >= 60:
                    score_color = "#237A45"
                elif score["score"] >= 65:
                    score_color = "#B87518"
                else:
                    score_color = "#A43B35"
            tk.Label(
                score_frame, text=score_text, bg=score_color, fg="white",
                font=("Arial", 11, "bold"), padx=10, pady=7,
            ).pack(fill="x", pady=(0, 6))
            if score["hard_conflicts"]:
                conflict_text = "\n".join("• " + item for item in score["hard_conflicts"])
                ttk.Label(
                    score_frame, text="ČASOVNA OPOZORILA:\n" + conflict_text,
                    foreground="#A43B35", justify="left", wraplength=1320,
                ).pack(anchor="w", pady=(0, 5))
            details = "\n".join(f"• {name}: {detail}" for name, _value, detail in score["signals"])
            if not details:
                details = "Ni dovolj podatkov za primerjavo imen, priimkov, naslovov, starosti ali kronologije."
            ttk.Label(score_frame, text=details, justify="left", wraplength=1320).pack(anchor="w")
            ttk.Label(
                score_frame,
                text=(
                    score["note"] + " " +
                    ("Način primerjave: ista oseba." if relation_type == "same_person" else "Način primerjave: poroka staršev in krst otroka.")
                ),
                foreground="#7A4A00", wraplength=1320,
            ).pack(anchor="w", pady=(5, 0))
            return score

        def render_record_tabs():
            for tab_id in notebook.tabs():
                notebook.forget(tab_id)
            table_titles = {
                "krsti": "ROJSTVO / KRST",
                "poroke": "POROKA",
                "mrtvi": "SMRT",
            }
            hidden = set()
            for table in ("krsti", "poroke", "mrtvi"):
                frame = ttk.Frame(notebook, padding=8)
                notebook.add(frame, text=table_titles[table])
                record = records.get(table)
                if not record:
                    ttk.Label(frame, text="Zapis ni izbran.", foreground="gray").pack(pady=24)
                    continue
                url = matricula_url(record)
                linkbar = ttk.Frame(frame)
                linkbar.pack(fill="x", pady=(0, 8))
                ttk.Label(
                    linkbar,
                    text=f"Zapis ID {record.get('id', '/')}  |  {record.get('zupnija', '')}  |  knjiga {record.get('knjiga', '')}",
                    font=("Arial", 10, "bold"),
                ).pack(side="left", padx=(0, 12))
                if url:
                    tk.Button(
                        linkbar, text="🌐 ODPRE MATRICULO NA TOČNI STRANI",
                        command=lambda target=url: webbrowser.open(target),
                        bg="#2868A6", fg="white", activebackground="#1D4F80",
                        activeforeground="white", font=("Arial", 9, "bold"),
                        relief="flat", padx=9, pady=5,
                    ).pack(side="left", padx=3)
                    ttk.Button(
                        linkbar, text="Kopiraj povezavo",
                        command=lambda target=url: self._kopiraj_povezavo(win, target),
                    ).pack(side="left", padx=3)
                else:
                    ttk.Label(linkbar, text="Matricula povezava ni na voljo.", foreground="#9A4A00").pack(side="left")

                body = ttk.Frame(frame)
                body.pack(fill="both", expand=True)
                text = tk.Text(body, wrap="word", font=("Consolas", 10), padx=10, pady=9)
                yscroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
                xscroll = ttk.Scrollbar(body, orient="horizontal", command=text.xview)
                text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
                text.grid(row=0, column=0, sticky="nsew")
                yscroll.grid(row=0, column=1, sticky="ns")
                xscroll.grid(row=1, column=0, sticky="ew")
                body.rowconfigure(0, weight=1)
                body.columnconfigure(0, weight=1)
                text.tag_configure("field", font=("Arial", 10, "bold"), foreground="#174A7E")
                text.tag_configure("section", font=("Arial", 10, "bold"), foreground="#1976D2")
                hidden_fields = set(rules.get("hidden_fields", {}).get(table, []))
                text.insert(tk.END, f"VSI PODATKI IZ TABELE {table.upper()}\n\n", "section")
                for key, value in record.items():
                    if key in hidden_fields:
                        continue
                    label = PoljaPrimerjalnikaDialog._field_title(key)
                    if isinstance(value, (dict, list, tuple)):
                        value = json.dumps(value, ensure_ascii=False, indent=2, default=str)
                    display_value = "/" if value is None or value == "" else str(value)
                    text.insert(tk.END, f"{label}: ", "field")
                    text.insert(tk.END, display_value + "\n")
                text.configure(state="disabled")

        def open_field_settings():
            PoljaPrimerjalnikaDialog(
                win, records, rules,
                on_saved=lambda new_rules: apply_rules(new_rules, rerender=True),
            )

        def apply_rules(new_rules, rerender=False):
            nonlocal rules
            rules = new_rules
            if rerender:
                render_record_tabs()
            refresh_score()

        def open_rule_settings():
            NastavitveUjemanjaDialog(
                win, rules,
                on_saved=lambda new_rules: apply_rules(new_rules, rerender=False),
            )

        action_row = ttk.Frame(heading)
        action_row.pack(fill="x", pady=(7, 0))
        tk.Button(
            action_row, text="⚙ NASTAVITVE MERIL UJEMANJA", command=open_rule_settings,
            bg="#606B78", fg="white", activebackground="#46515E", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=9, pady=5,
        ).pack(side="left", padx=(0, 5))
        tk.Button(
            action_row, text="☑ IZBIRA PRIKAZANIH POLJ", command=open_field_settings,
            bg="#2868A6", fg="white", activebackground="#1D4F80", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=9, pady=5,
        ).pack(side="left")

        relation_combo.bind("<<ComboboxSelected>>", lambda _event: refresh_score())
        render_record_tabs()
        refresh_score()

        if read_errors:
            ttk.Label(win, text="Napake pri branju: " + "; ".join(read_errors), foreground="red", wraplength=1350).pack(fill="x", padx=12)

        bottom = ttk.Frame(win, padding=10)
        bottom.pack(fill="x", side="bottom")
        ttk.Label(bottom, text="Zaključna ugotovitev / opomba za bazo:").pack()
        ent_opomba = ttk.Entry(bottom, width=105)
        ent_opomba.pack(pady=5)

        def shrani_osebo():
            chosen = self.primerjalnik_idji
            if current_relation() == "parents_child":
                messagebox.showwarning(
                    "To ni ena oseba",
                    "Izbrana primerjava predstavlja POROKO STARŠEV → KRST OTROKA. "
                    "To sta družinska povezava in zapis otroka, ne trije dogodki iste osebe.\n\n"
                    "Shranjevanje v 'Zgrajene osebe' bi napačno pripisalo poroko staršev otroku. "
                    "Primerjalnik ostane odprt. Za trajno shranjevanje te povezave je primerna "
                    "ločena evidenca družinskih povezav.",
                    parent=win,
                )
                return
            if not any(chosen.values()):
                messagebox.showwarning("Pozor", "Izbran ni noben zapis!", parent=win)
                return
            score = oceni_ujemanje(
                krsti=records.get("krsti"), poroke=records.get("poroke"), mrtvi=records.get("mrtvi"),
                settings=rules, relation_type=current_relation(),
            )
            if score["hard_conflicts"]:
                conflict = "\n".join(score["hard_conflicts"])
                proceed = messagebox.askyesno(
                    "Časovno protislovje",
                    "Zapisi vsebujejo časovno protislovje. Ali kljub temu želiš ročno shraniti povezavo?\n\n" + conflict,
                    parent=win,
                )
                if not proceed:
                    return
            success, msg = baza.shrani_zgrajeno_osebo(
                chosen["krsti"], chosen["poroke"], chosen["mrtvi"], ent_opomba.get()
            )
            if success:
                messagebox.showinfo("Uspeh", msg, parent=win)
                self.primerjalnik_idji = {"krsti": None, "poroke": None, "mrtvi": None}
                self.primerjalnik_tip_povezave = None
                self.trenutni_kliknjen_iid = None
                self.btn_primerjalnik.configure(text="⚖ PRIMERJALNIK (0)")
                win.destroy()
            else:
                messagebox.showerror("Napaka", msg, parent=win)

        buttons = ttk.Frame(bottom)
        buttons.pack(pady=8)
        tk.Button(
            buttons, text="💾 POTRDI UJEMANJE IN SHRANI", command=shrani_osebo,
            bg="#16834A", fg="white", activebackground="#11683A", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=12, pady=6,
        ).pack(side="left", padx=5)
        tk.Button(
            buttons, text="Počisti primerjalnik", command=lambda: self._pocisti_primerjalnik(win),
            bg="#777777", fg="white", activebackground="#555555", activeforeground="white",
            relief="flat", padx=10, pady=6,
        ).pack(side="left", padx=5)

    def _pocisti_primerjalnik(self, window=None):
        self.primerjalnik_idji = {"krsti": None, "poroke": None, "mrtvi": None}
        self.primerjalnik_tip_povezave = None
        self.trenutni_kliknjen_iid = None
        self.btn_primerjalnik.configure(text="⚖ PRIMERJALNIK (0)")
        if window and window.winfo_exists():
            window.destroy()

    def prikazi_podrobnosti_okno(self, tabela, podatki):
        """Ohrani obstoječi samostojni prikaz zapisa iz glavnih rezultatov."""
        win = tk.Toplevel(self.frame)
        win.title(f"Podrobnosti zapisa – {tabela.upper()}")
        win.geometry("1200x850")
        win.minsize(850, 600)

        canvas = tk.Canvas(win, background="#f5f5f5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        scrollable = tk.Frame(canvas, background="#f5f5f5", padx=18, pady=18)
        canvas_window = canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        def configure_inner(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def configure_canvas(event):
            canvas.itemconfigure(canvas_window, width=event.width)

        scrollable.bind("<Configure>", configure_inner)
        canvas.bind("<Configure>", configure_canvas)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        matricula_frame = ttk.LabelFrame(scrollable, text="Matricula Online", padding=8)
        matricula_frame.pack(fill="x", pady=(0, 12))
        url = matricula_url(podatki)
        if url:
            ttk.Label(
                matricula_frame,
                text="Povezava ohranja prvotno določanje nadškofije in številko skena iz polja 'slika'.",
                wraplength=900,
            ).pack(anchor="w", padx=5, pady=(0, 5))
            ttk.Button(
                matricula_frame, text="🌐 Odpri arhivsko knjigo točno na tej sliki",
                command=lambda target=url: webbrowser.open(target),
            ).pack(side="left", padx=5)
            ttk.Button(
                matricula_frame, text="Kopiraj povezavo",
                command=lambda target=url: self._kopiraj_povezavo(win, target),
            ).pack(side="left", padx=5)
        else:
            ttk.Label(
                matricula_frame, text="Povezave ni mogoče sestaviti: manjka podatek o župniji ali knjigi.",
                foreground="#9a4a00",
            ).pack(anchor="w", padx=5)

        def add_grid_row(parent, field_values, row_index):
            for column_index, (label, value) in enumerate(field_values.items()):
                card = tk.Frame(parent, background="white", bd=1, relief="solid", padx=9, pady=7)
                card.grid(row=row_index, column=column_index, sticky="nsew", padx=4, pady=4)
                tk.Label(card, text=label, font=("Arial", 10, "bold"), foreground="#666666", background="white").pack(anchor="w")
                tk.Label(
                    card, text=str(value) if value not in (None, "") else "/",
                    font=("Arial", 11), foreground="#111111", background="white",
                    wraplength=260, justify="left", anchor="w",
                ).pack(anchor="w", fill="x")
                parent.columnconfigure(column_index, weight=1)

        grid = tk.Frame(scrollable, background="#f5f5f5")
        grid.pack(fill="x", expand=True)
        add_grid_row(grid, {
            "ID zapisa": podatki.get("id", ""), "Vpis št.": podatki.get("vpis_st_knjige", ""),
            "Župnija": podatki.get("zupnija", ""), "Knjiga": podatki.get("knjiga", ""),
            "Stran": podatki.get("vpis_st_na_strani", ""),
        }, 0)
        if tabela == "krsti":
            add_grid_row(grid, {
                "Ime otroka": podatki.get("ime_otroka"),
                "Priimek (očetov)": f"{podatki.get('priimek_oceta') or ''} {podatki.get('alt_priimek_oceta') or ''}".strip(),
                "Datum rojstva": podatki.get("datum_rojstva"), "Datum krsta": podatki.get("datum_krsta"),
            }, 1)
            add_grid_row(grid, {
                "Oče – ime": podatki.get("ime_oceta"),
                "Mati – ime in priimek": f"{podatki.get('ime_matere') or ''} {podatki.get('priimek_matere') or ''}".strip(),
                "Naslov / hiša": podatki.get("naslov"), "Izvor očeta": podatki.get("izvor_oceta"),
            }, 2)
            add_grid_row(grid, {
                "Poklic očeta": podatki.get("poklic_oceta"), "Botri": podatki.get("botri"),
                "Babica": podatki.get("babica"), "Duhovnik": podatki.get("duhovnik"),
            }, 3)
        elif tabela == "poroke":
            ttk.Label(scrollable, text="PODATKI O ŽENINU IN NEVESTI", font=("Arial", 11, "bold")).pack(anchor="w", pady=(12, 0))
            grid_poroke = tk.Frame(scrollable, background="#f5f5f5")
            grid_poroke.pack(fill="x", expand=True)
            add_grid_row(grid_poroke, {
                "Ženin – ime in priimek": f"{podatki.get('ime_zenina') or ''} {podatki.get('priimek_zenina') or ''}".strip(),
                "Starost ženina": podatki.get("starost_zenina"), "Stan ženina": podatki.get("stan_zenina"),
                "Naslov ženina": podatki.get("naslov_zenina"),
            }, 0)
            add_grid_row(grid_poroke, {
                "Nevesta – ime in priimek": f"{podatki.get('ime_neveste') or ''} {podatki.get('priimek_neveste') or ''}".strip(),
                "Starost neveste": podatki.get("starost_neveste"), "Stan neveste": podatki.get("stan_neveste"),
                "Naslov neveste": podatki.get("naslov_neveste"),
            }, 1)
            add_grid_row(grid_poroke, {
                "Datum poroke": podatki.get("datum_poroke"), "Priče": podatki.get("price"),
                "Duhovnik": podatki.get("duhovnik"),
                "Izvor": f"Ž: {podatki.get('izvor_zenina') or ''} | N: {podatki.get('izvor_neveste') or ''}",
            }, 2)
        elif tabela == "mrtvi":
            add_grid_row(grid, {
                "Ime pokojnika": podatki.get("ime_pokojnika"), "Priimek pokojnika": podatki.get("priimek_pokojnika"),
                "Datum smrti": podatki.get("datum_smrti"), "Datum pokopa": podatki.get("datum_pokopa"),
            }, 1)
            add_grid_row(grid, {
                "Starost": podatki.get("starost"), "Stan pokojnika": podatki.get("stan_pokojnika"),
                "Vzrok smrti": podatki.get("vzrok_smrti"), "Naslov": podatki.get("naslov"),
            }, 2)
            add_grid_row(grid, {
                "Zakonec / starši": podatki.get("zakonec_starsi"), "Izvor pokojnika": podatki.get("izvor_pokojnika"),
                "Duhovnik": podatki.get("duhovnik"),
            }, 3)
        ttk.Separator(scrollable, orient="horizontal").pack(fill="x", pady=14)
        ttk.Label(scrollable, text="OPOMBE", font=("Arial", 11, "bold")).pack(anchor="w")
        txt_opombe = tk.Text(scrollable, wrap="word", font=("Arial", 11), height=5, padx=8, pady=8)
        txt_opombe.pack(fill="x", pady=(4, 12))
        txt_opombe.insert(tk.END, podatki.get("opombe") or "/")
        txt_opombe.configure(state="disabled")
        ttk.Label(scrollable, text="SUROVI TEKST (iz slike)", font=("Arial", 11, "bold")).pack(anchor="w")
        txt_surovi = tk.Text(scrollable, wrap="word", font=("Arial", 10), height=8, padx=8, pady=8)
        txt_surovi.pack(fill="x", pady=(4, 10))
        txt_surovi.insert(tk.END, podatki.get("surovi_tekst") or "/")
        txt_surovi.configure(state="disabled")

    @staticmethod
    def _kopiraj_povezavo(parent, url):
        try:
            parent.clipboard_clear()
            parent.clipboard_append(url)
            messagebox.showinfo("Povezava kopirana", "Povezava do Matricule je kopirana v odložišče.", parent=parent)
        except tk.TclError as exc:
            messagebox.showerror("Napaka", f"Povezave ni bilo mogoče kopirati:\n{exc}", parent=parent)

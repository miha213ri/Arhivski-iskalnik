"""Uporabniški vmesnik za slovarje kanoničnih imen, priimkov in krajev."""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog


class UrejevalnikDialog(tk.Toplevel):
    def __init__(self, parent, db, dict_type, entity_id, on_close_callback):
        super().__init__(parent)
        self.db = db
        self.dict_type = dict_type
        self.entity_id = entity_id
        self.on_close = on_close_callback

        self.title("Urejanje vnosa" if entity_id else "Nov standardni vnos")
        self.geometry("560x590")
        self.minsize(480, 480)
        self.transient(parent)
        self.grab_set()

        frame_top = ttk.LabelFrame(self, text=" Standardna oblika ", padding=10)
        frame_top.pack(fill="x", padx=10, pady=10)

        ttk.Label(frame_top, text="Kanonično ime / priimek / kraj:").grid(row=0, column=0, sticky="w")
        self.ent_kanon = ttk.Entry(frame_top, width=38)
        self.ent_kanon.grid(row=0, column=1, padx=5, sticky="ew")

        ttk.Label(frame_top, text="Spol / dodatni tip (opcijsko):").grid(row=1, column=0, sticky="w", pady=5)
        self.ent_spol = ttk.Entry(frame_top, width=38)
        self.ent_spol.grid(row=1, column=1, padx=5, pady=5, sticky="ew")

        ttk.Label(frame_top, text="Opombe:").grid(row=2, column=0, sticky="w", pady=5)
        self.ent_opombe = ttk.Entry(frame_top, width=38)
        self.ent_opombe.grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        frame_top.columnconfigure(1, weight=1)

        if self.entity_id:
            row = self.db.get_canonical_by_id(self.entity_id)
            if row:
                self.ent_kanon.insert(0, row["naziv"] or "")
                self.ent_spol.insert(0, row["spol_tip"] or "")
                self.ent_opombe.insert(0, row["opombe"] or "")

        ttk.Button(frame_top, text="Shrani standardno obliko", command=self.shrani_kanonicno).grid(
            row=3, column=0, columnspan=2, pady=10
        )

        self.frame_var = ttk.LabelFrame(self, text=" Zgodovinske variacije izvirnih zapisov ", padding=10)
        self.frame_var.pack(fill="both", expand=True, padx=10, pady=5)
        if self.entity_id:
            self.build_variations_ui()
        else:
            ttk.Label(
                self.frame_var,
                text="Najprej shrani standardno obliko, nato lahko dodajaš variacije.",
                foreground="gray",
            ).pack(pady=40)

    def shrani_kanonicno(self):
        naziv = self.ent_kanon.get().strip()
        spol = self.ent_spol.get().strip()
        opombe = self.ent_opombe.get().strip()
        if not naziv:
            messagebox.showwarning("Manjkajoč podatek", "Kanonična oblika ne sme biti prazna.", parent=self)
            return
        try:
            if self.entity_id:
                self.db.uredi_kanonicno_entiteto(self.entity_id, naziv, spol, opombe)
            else:
                self.entity_id = self.db.dodaj_kanonicno_entiteto(self.dict_type, naziv, spol, opombe)
                for widget in self.frame_var.winfo_children():
                    widget.destroy()
                self.build_variations_ui()
            self.on_close()
            messagebox.showinfo("Uspeh", "Standardna oblika je shranjena.", parent=self)
        except Exception as exc:
            messagebox.showerror("Napaka pri shranjevanju", str(exc), parent=self)

    def build_variations_ui(self):
        self.tree_var = ttk.Treeview(
            self.frame_var,
            columns=("id", "izvirno", "norm", "zaupanje"),
            show="headings",
            height=10,
        )
        headings = {
            "id": ("ID", 45),
            "izvirno": ("Izvirni zapis", 180),
            "norm": ("Iskalni niz", 180),
            "zaupanje": ("Zaupanje", 90),
        }
        for column, (heading, width) in headings.items():
            self.tree_var.heading(column, text=heading)
            self.tree_var.column(column, width=width, minwidth=45, stretch=column != "id")
        self.tree_var.pack(fill="both", expand=True)

        controls = ttk.Frame(self.frame_var)
        controls.pack(fill="x", pady=10)
        self.ent_nova_var = ttk.Entry(controls, width=28)
        self.ent_nova_var.pack(side="left", padx=5)
        self.ent_nova_var.bind("<Return>", lambda _event: self.dodaj_var())
        ttk.Button(controls, text="Dodaj", command=self.dodaj_var).pack(side="left")
        ttk.Button(controls, text="Odstrani označeno", command=self.odstrani_var).pack(side="right")
        self.osvezi_variacije()

    def osvezi_variacije(self):
        for item in self.tree_var.get_children():
            self.tree_var.delete(item)
        for variant in self.db.get_variants_for_entity(self.entity_id):
            self.tree_var.insert("", "end", values=variant)

    def dodaj_var(self):
        original = self.ent_nova_var.get().strip()
        if not original:
            return
        ok, msg = self.db.dodaj_variacijo(self.entity_id, original)
        if ok:
            self.ent_nova_var.delete(0, tk.END)
            self.osvezi_variacije()
            self.on_close()
        else:
            messagebox.showwarning("Variacije ni mogoče dodati", msg, parent=self)

    def odstrani_var(self):
        selected = self.tree_var.selection()
        if not selected:
            return
        values = self.tree_var.item(selected[0], "values")
        variant_id = values[0]
        if not messagebox.askyesno("Potrditev", "Res želiš odstraniti izbrano variacijo?", parent=self):
            return
        try:
            removed = self.db.odstrani_preslikavo(self.entity_id, variant_id)
            if removed:
                self.osvezi_variacije()
                self.on_close()
        except Exception as exc:
            messagebox.showerror("Napaka", str(exc), parent=self)


class SlovarjiUI:
    def __init__(self, parent_notebook, db_instance):
        self.notebook = parent_notebook
        self.db = db_instance
        self.trees = {}
        self.vsi_podatki = {}
        self.connected = False
        self.loaded_types = set()
        self.loading_types = set()
        self._load_queue = queue.Queue()
        self._load_generation = 0
        self._tab_to_type = {}
        self._render_tokens = {"ime": 0, "priimek": 0, "kraj": 0}
        self.max_prikazanih_vnosov = 500
        self.render_chunk_size = 125
        self._visible_counts = {"ime": self.max_prikazanih_vnosov,
                                "priimek": self.max_prikazanih_vnosov,
                                "kraj": self.max_prikazanih_vnosov}

        self.tab_imena = ttk.Frame(self.notebook)
        self.tab_priimki = ttk.Frame(self.notebook)
        self.tab_kraji = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_imena, text=" 📖 Imena ")
        self.notebook.add(self.tab_priimki, text=" 📖 Priimki ")
        self.notebook.add(self.tab_kraji, text=" 📖 Kraji ")

        self.build_tab(self.tab_imena, "ime")
        self.build_tab(self.tab_priimki, "priimek")
        self.build_tab(self.tab_kraji, "kraj")
        self._tab_to_type = {
            str(self.tab_imena): "ime",
            str(self.tab_priimki): "priimek",
            str(self.tab_kraji): "kraj",
        }
        self.notebook.bind("<<NotebookTabChanged>>", self._on_notebook_tab_changed, add="+")
        self.notebook.after(120, self._poll_load_queue)

    def build_tab(self, parent_frame, dict_type):
        titles = {"ime": "Upravljanje imen", "priimek": "Upravljanje priimkov", "kraj": "Upravljanje krajev"}
        top = ttk.Frame(parent_frame)
        top.pack(fill="x", padx=10, pady=10)
        ttk.Label(top, text=titles[dict_type], font=("Arial", 12, "bold")).pack(side="left")
        ttk.Button(
            top,
            text="📥 Uvozi JSON",
            command=lambda current_type=dict_type: self.run_json_import(current_type),
        ).pack(side="right", padx=5)
        tk.Button(
            top,
            text="📤 Izvozi Excel",
            bg="#16834A",
            fg="white",
            activebackground="#11683A",
            activeforeground="white",
            command=lambda current_type=dict_type: self.export_excel(current_type),
        ).pack(side="right", padx=5)
        tk.Button(
            top,
            text="📤 Izvozi JSON",
            bg="#2868A6",
            fg="white",
            activebackground="#1D4F80",
            activeforeground="white",
            command=lambda current_type=dict_type: self.export_json(current_type),
        ).pack(side="right", padx=5)

        content = ttk.PanedWindow(parent_frame, orient=tk.HORIZONTAL)
        content.pack(fill="both", expand=True, padx=10, pady=5)

        left = ttk.LabelFrame(content, text=" Standardni vnosi ", padding=5)
        content.add(left, weight=1)
        search_frame = ttk.Frame(left)
        search_frame.pack(fill="x", padx=5, pady=5)
        ttk.Label(search_frame, text="🔍 Išči:").pack(side="left", padx=(0, 5))
        search_var = tk.StringVar()
        search_var.trace_add("write", lambda *_args, current_type=dict_type: self.filter_entities(current_type))
        search_entry = ttk.Entry(search_frame, textvariable=search_var)
        search_entry.pack(side="left", fill="x", expand=True)
        load_status = ttk.Label(
            left,
            text="Povezava ni vzpostavljena. Najprej izberi 'Poveži z bazo'.",
            foreground="#8A5A00",
        )
        load_status.pack(fill="x", padx=5, pady=(0, 4))

        tree_entities = ttk.Treeview(left, columns=("id", "ime", "spol"), show="headings", selectmode="browse")
        tree_entities.heading("id", text="ID")
        tree_entities.heading("ime", text="Kanonična oblika")
        tree_entities.heading("spol", text="Spol / tip")
        tree_entities.column("id", width=55, stretch=False)
        tree_entities.column("ime", width=190, stretch=True)
        tree_entities.column("spol", width=100, stretch=True)
        scroll_left = ttk.Scrollbar(left, orient="vertical", command=tree_entities.yview)
        tree_entities.configure(yscrollcommand=scroll_left.set)
        tree_entities.pack(side="left", fill="both", expand=True, padx=(5, 0), pady=5)
        scroll_left.pack(side="right", fill="y", pady=5)
        tree_entities.bind("<<TreeviewSelect>>", lambda _event, current_type=dict_type: self.on_entity_select(current_type))

        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=5)
        ttk.Button(buttons, text="+ Nov vnos", command=lambda: self.open_editor(dict_type, None)).pack(side="left", padx=5)
        ttk.Button(buttons, text="✏ Uredi izbrano", command=lambda: self.uredi_izbrano(dict_type)).pack(side="left")
        more_button = ttk.Button(
            buttons, text="Naloži naslednjih 500", state="disabled",
            command=lambda current_type=dict_type: self.show_more_entities(current_type),
        )
        more_button.pack(side="right", padx=5)

        right = ttk.LabelFrame(content, text=" Zgodovinske variacije izbranega vnosa ", padding=5)
        content.add(right, weight=2)
        tree_var = ttk.Treeview(right, columns=("id", "izvirno", "norm", "zaupanje"), show="headings")
        for column, label, width in (
            ("id", "ID", 45),
            ("izvirno", "Izvirni zapis", 180),
            ("norm", "Iskalni niz", 180),
            ("zaupanje", "Stopnja zaupanja", 120),
        ):
            tree_var.heading(column, text=label)
            tree_var.column(column, width=width, minwidth=45, stretch=column != "id")
        tree_var.pack(fill="both", expand=True, padx=5, pady=5)

        self.trees[dict_type] = {
            "entities": tree_entities,
            "variants": tree_var,
            "search_var": search_var,
            "status": load_status,
            "more_button": more_button,
        }

    def set_connected(self, connected):
        """Označi stanje povezave; posamezen slovar se naloži šele ob odprtju zavihka."""
        self.connected = bool(connected and getattr(self.db, "initialized", False))
        self._load_generation += 1
        self.loading_types.clear()
        if not self.connected:
            self.clear_loaded_data()
            return
        for dict_type in ("ime", "priimek", "kraj"):
            self.loaded_types.discard(dict_type)
            self.vsi_podatki[dict_type] = []
            self.trees[dict_type]["status"].configure(
                text="Povezava je pripravljena. Šifrant se naloži ob odprtju tega zavihka.",
                foreground="#2868A6",
            )
            self.filter_entities(dict_type)
        self._on_notebook_tab_changed()

    def set_loaded_data(self, data_by_type):
        """Združljivostna metoda za starejši način nalaganja vseh slovarjev."""
        self.connected = True
        for dict_type in ("ime", "priimek", "kraj"):
            self.vsi_podatki[dict_type] = data_by_type.get(dict_type, [])
            self.loaded_types.add(dict_type)
            self.filter_entities(dict_type)

    def clear_loaded_data(self):
        """Po spremembi povezave odstrani prikaz podatkov stare baze."""
        self.connected = False
        self._load_generation += 1
        self.loaded_types.clear()
        self.loading_types.clear()
        for dict_type in ("ime", "priimek", "kraj"):
            self.vsi_podatki[dict_type] = []
            self.filter_entities(dict_type)
            self.trees[dict_type]["status"].configure(
                text="Povezava ni vzpostavljena. Najprej izberi 'Poveži z bazo'.",
                foreground="#8A5A00",
            )

    def _on_notebook_tab_changed(self, _event=None):
        selected = self.notebook.select()
        dict_type = self._tab_to_type.get(selected)
        if dict_type:
            self.load_entities(dict_type)

    def load_entities(self, dict_type, force=False):
        """Naloži samo izbrani slovar v delovni niti."""
        # Menjava zavihka pred povezavo ne sme sprožiti modalnega opozorila.
        # Uporabnik lahko najprej pregleda program; nalaganje se izvede po povezavi.
        if not self.connected or not getattr(self.db, "initialized", False):
            self.trees[dict_type]["status"].configure(
                text="Najprej vzpostavi povezavo z MySQL. Šifrant se bo naložil ob vrnitvi na ta zavihek.",
                foreground="#8A5A00",
            )
            return
        if dict_type in self.loading_types:
            return
        if dict_type in self.loaded_types and not force:
            return

        self.loading_types.add(dict_type)
        generation = self._load_generation
        labels = {"ime": "imen", "priimek": "priimkov", "kraj": "krajev"}
        self.trees[dict_type]["status"].configure(
            text=f"⏳ Nalagam šifrant {labels[dict_type]} iz MySQL. Prosimo, počakaj ...",
            foreground="#805500",
        )

        def worker():
            try:
                rows = self.db.get_canonical_list(dict_type)
                self._load_queue.put(("loaded", dict_type, rows, generation))
            except Exception as exc:
                self._load_queue.put(("error", dict_type, str(exc), generation))

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"dictionary-loader-{dict_type}",
        ).start()

    def _poll_load_queue(self):
        if not self.notebook.winfo_exists():
            return
        try:
            while True:
                kind, dict_type, payload, generation = self._load_queue.get_nowait()
                if generation != self._load_generation or not self.connected:
                    continue
                self.loading_types.discard(dict_type)
                if kind == "loaded":
                    self.vsi_podatki[dict_type] = payload
                    self.loaded_types.add(dict_type)
                    self.filter_entities(dict_type)
                    labels = {"ime": "imen", "priimek": "priimkov", "kraj": "krajev"}
                    self.trees[dict_type]["status"].configure(
                        text=f"Naložen šifrant {labels[dict_type]}: {len(payload)} vnosov.",
                        foreground="#16834A",
                    )
                else:
                    self.trees[dict_type]["status"].configure(
                        text=f"Napaka pri nalaganju šifranta: {payload}",
                        foreground="#B42318",
                    )
        except queue.Empty:
            pass
        self.notebook.after(120, self._poll_load_queue)

    def _require_connection(self):
        if not self.connected or not getattr(self.db, "initialized", False):
            messagebox.showwarning(
                "Brez povezave",
                "Najprej shrani nastavitve in klikni 'Poveži z bazo'.",
                parent=self.notebook,
            )
            return False
        return True

    def refresh_entities(self, dict_type):
        if not self._require_connection():
            return
        self.loaded_types.discard(dict_type)
        self.load_entities(dict_type, force=True)

    def filter_entities(self, dict_type, preserve_limit=False):
        """Filtrira lokalno in vstavi vnose v Treeview po manjših paketih.

        Omejitev števila vidnih vrstic prepreči, da bi zelo veliki slovarji
        blokirali glavno okno. Iskanje se še vedno izvede nad celotnim seznamom.
        """
        tree = self.trees[dict_type]["entities"]
        token = self._render_tokens[dict_type] + 1
        self._render_tokens[dict_type] = token
        for item in tree.get_children():
            tree.delete(item)
        self._pocisti_variacije(dict_type)

        if dict_type not in self.loaded_types:
            self.trees[dict_type]["more_button"].configure(state="disabled")
            return

        query = self.trees[dict_type]["search_var"].get().casefold().strip()
        if not preserve_limit:
            self._visible_counts[dict_type] = self.max_prikazanih_vnosov
        all_rows = self.vsi_podatki.get(dict_type, [])
        if query:
            matches = [row for row in all_rows if query in str(row[1] or "").casefold()]
        else:
            matches = all_rows
        visible_count = min(self._visible_counts[dict_type], len(matches))
        visible_rows = matches[:visible_count]
        more_button = self.trees[dict_type]["more_button"]
        more_button.configure(state="normal" if visible_count < len(matches) else "disabled")
        status = self.trees[dict_type]["status"]
        status.configure(
            text=f"Najdenih: {len(matches)}. Pripravljam prikaz 0/{len(visible_rows)} ...",
            foreground="#2868A6",
        )

        def insert_chunk(start=0):
            if token != self._render_tokens[dict_type] or not tree.winfo_exists():
                return
            end = min(start + self.render_chunk_size, len(visible_rows))
            for row in visible_rows[start:end]:
                tree.insert("", "end", values=row)
            if end < len(visible_rows):
                status.configure(
                    text=f"Prikazujem {end}/{len(visible_rows)} vnosov (najdenih skupaj {len(matches)}).",
                    foreground="#2868A6",
                )
                self.notebook.after(1, lambda: insert_chunk(end))
                return
            suffix = (
                " Klikni 'Naloži naslednjih 500' za nadaljevanje."
                if len(matches) > len(visible_rows) else ""
            )
            status.configure(
                text=f"Najdenih: {len(matches)}; prikazanih: {len(visible_rows)}.{suffix}",
                foreground="#16834A",
            )

        insert_chunk()

    def show_more_entities(self, dict_type):
        """Prikaže naslednji paket, ne da bi omejil dejansko iskanje po celotnem slovarju."""
        self._visible_counts[dict_type] += self.max_prikazanih_vnosov
        self.filter_entities(dict_type, preserve_limit=True)

    def _pocisti_variacije(self, dict_type):
        tree = self.trees[dict_type]["variants"]
        for item in tree.get_children():
            tree.delete(item)

    def on_entity_select(self, dict_type):
        if not self.connected or not getattr(self.db, "initialized", False):
            return
        tree_entities = self.trees[dict_type]["entities"]
        tree_variants = self.trees[dict_type]["variants"]
        self._pocisti_variacije(dict_type)
        selected = tree_entities.selection()
        if not selected:
            return
        entity_id = tree_entities.item(selected[0], "values")[0]
        try:
            for variant in self.db.get_variants_for_entity(entity_id):
                tree_variants.insert("", "end", values=variant)
        except Exception as exc:
            messagebox.showerror("Napaka slovarja", str(exc), parent=self.notebook)

    def open_editor(self, dict_type, entity_id):
        if not self._require_connection():
            return
        UrejevalnikDialog(
            self.notebook,
            self.db,
            dict_type,
            entity_id,
            lambda: self.on_editor_closed(dict_type),
        )

    def uredi_izbrano(self, dict_type):
        tree = self.trees[dict_type]["entities"]
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("Pozor", "Izberi vnos na levi strani za urejanje.", parent=self.notebook)
            return
        entity_id = tree.item(selected[0], "values")[0]
        self.open_editor(dict_type, entity_id)

    def on_editor_closed(self, dict_type):
        self.refresh_entities(dict_type)

    def run_json_import(self, dict_type):
        if not self._require_connection():
            return
        filepath = filedialog.askopenfilename(
            parent=self.notebook,
            title="Izberi JSON slovar",
            filetypes=[("JSON datoteke", "*.json"), ("Vse datoteke", "*.*")],
        )
        if not filepath:
            return
        success, msg = self.db.import_json_dictionary(filepath, dict_type)
        if success:
            messagebox.showinfo("Uvoz uspešen", msg, parent=self.notebook)
            self.refresh_entities(dict_type)
        else:
            messagebox.showerror("Napaka pri uvozu", msg, parent=self.notebook)


    def export_json(self, dict_type):
        if not self._require_connection():
            return
        filepath = filedialog.asksaveasfilename(
            parent=self.notebook,
            title="Izvozi slovar v JSON",
            defaultextension=".json",
            initialfile=f"slovar_{dict_type}.json",
            filetypes=[("JSON datoteke", "*.json")],
        )
        if not filepath:
            return
        try:
            canonical, variants = self.db.export_json_dictionary(filepath, dict_type)
            messagebox.showinfo(
                "Izvoz končan",
                f"Izvoženih kanoničnih oblik: {canonical}\nIzvoženih variacij: {variants}\n\n{filepath}",
                parent=self.notebook,
            )
        except Exception as exc:
            messagebox.showerror("Napaka pri izvozu JSON", str(exc), parent=self.notebook)

    def export_excel(self, dict_type):
        if not self._require_connection():
            return
        filepath = filedialog.asksaveasfilename(
            parent=self.notebook,
            title="Izvozi slovar v Excel",
            defaultextension=".xlsx",
            initialfile=f"slovar_{dict_type}.xlsx",
            filetypes=[("Excel datoteke", "*.xlsx")],
        )
        if not filepath:
            return
        try:
            from .izvoz_excel import write_workbook

            canonical, variants = self.db.get_dictionary_export_data(dict_type)
            write_workbook(
                filepath,
                [
                    (
                        "Kanonične oblike",
                        ("ID", "Kanonična oblika", "Spol / tip", "Opombe"),
                        canonical,
                    ),
                    (
                        "Variacije",
                        ("ID variacije", "ID kanonične oblike", "Kanonična oblika", "Izvirni zapis", "Iskalni niz", "Zaupanje"),
                        variants,
                    ),
                ],
            )
            messagebox.showinfo(
                "Izvoz končan",
                f"Izvoženih kanoničnih oblik: {len(canonical)}\nIzvoženih variacij: {len(variants)}\n\n{filepath}",
                parent=self.notebook,
            )
        except Exception as exc:
            messagebox.showerror("Napaka pri izvozu Excel", str(exc), parent=self.notebook)

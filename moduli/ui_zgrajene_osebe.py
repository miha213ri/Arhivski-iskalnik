"""Seznam in podrobni prikaz zgrajenih oseb, vključno z GEDCOM izvozom."""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import webbrowser

from .glavna_baza import GlavnaBaza
from .arhivske_povezave import matricula_url
from .gedcom_export import export_gedcom, suggest_marriage_role, GedcomExportError


FIELD_LABELS = {
    "id": "ID zapisa",
    "zupnija": "Župnija",
    "knjiga": "Knjiga",
    "slika": "Slika / sken",
    "vpis_st_knjige": "Vpisna številka v knjigi",
    "vpis_st_na_strani": "Številka vpisa na strani",
    "datum_rojstva": "Datum rojstva",
    "datum_krsta": "Datum krsta",
    "ime_otroka": "Ime otroka",
    "priimek_otroka": "Priimek otroka",
    "ime_oceta": "Ime očeta",
    "priimek_oceta": "Priimek očeta",
    "alt_priimek_oceta": "Drugi priimek očeta",
    "ime_matere": "Ime matere",
    "priimek_matere": "Priimek matere",
    "alt_priimek_matere": "Drugi priimek matere",
    "naslov": "Naslov",
    "izvor_oceta": "Izvor očeta",
    "poklic_oceta": "Poklic očeta",
    "botri": "Botri",
    "babica": "Babica",
    "duhovnik": "Duhovnik",
    "datum_poroke": "Datum poroke",
    "ime_zenina": "Ime ženina",
    "priimek_zenina": "Priimek ženina",
    "starost_zenina": "Starost ženina",
    "stan_zenina": "Stan ženina",
    "naslov_zenina": "Naslov ženina",
    "izvor_zenina": "Izvor ženina",
    "ime_neveste": "Ime neveste",
    "priimek_neveste": "Priimek neveste",
    "starost_neveste": "Starost neveste",
    "stan_neveste": "Stan neveste",
    "naslov_neveste": "Naslov neveste",
    "izvor_neveste": "Izvor neveste",
    "price": "Priče",
    "datum_smrti": "Datum smrti",
    "datum_pokopa": "Datum pokopa",
    "ime_pokojnika": "Ime pokojnika",
    "priimek_pokojnika": "Priimek pokojnika",
    "starost": "Starost",
    "stan_pokojnika": "Stan pokojnika",
    "vzrok_smrti": "Vzrok smrti",
    "zakonec_starsi": "Zakonec / starši",
    "izvor_pokojnika": "Izvor pokojnika",
    "opombe": "Opombe",
    "surovi_tekst": "Surovi prepis iz slike",
    "ustvarjeno": "Ustvarjeno",
    "krst_id": "ID krstnega zapisa",
    "poroka_id": "ID poročnega zapisa",
    "smrt_id": "ID mrliškega zapisa",
}


class ZgrajeneOsebeUI:
    def __init__(self, parent_frame, settings):
        self.frame = parent_frame
        self.settings = settings or {}
        self.connected = False
        self.build_ui()

    def _baza(self):
        return GlavnaBaza(self.settings.get("LiveDB", {}))

    def build_ui(self):
        top_frame = ttk.Frame(self.frame)
        top_frame.pack(fill="x", padx=10, pady=10)
        ttk.Label(
            top_frame,
            text="Zgrajene osebe (povezani zapisi iz krstnih, poročnih in mrliških knjig)",
            font=("Arial", 13, "bold"),
        ).pack(side="left")
        self.connection_status = ttk.Label(
            self.frame,
            text="Povezava ni vzpostavljena. Program lahko uporabljaš; za podatke se najprej poveži z MySQL.",
            foreground="#8A5A00",
        )
        self.connection_status.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Button(top_frame, text="Odpri izbrano", command=self.odpri_izbrano).pack(side="right", padx=(5, 0))
        ttk.Button(top_frame, text="🔄 Osveži seznam", command=self.osvezi_tabelo).pack(side="right")

        columns = ("id", "ime_priimek", "rojstvo", "poroka", "smrt", "opombe", "ustvarjeno")
        self.tree = ttk.Treeview(self.frame, columns=columns, show="headings", height=20, selectmode="browse")
        headings = {
            "id": "ID", "ime_priimek": "Ime in priimek", "rojstvo": "Datum rojstva",
            "poroka": "Datum poroke", "smrt": "Datum smrti", "opombe": "Opomba / sklep",
            "ustvarjeno": "Ustvarjeno",
        }
        widths = {
            "id": 55, "ime_priimek": 220, "rojstvo": 110, "poroka": 110,
            "smrt": 110, "opombe": 320, "ustvarjeno": 150,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=55,
                             stretch=column in ("ime_priimek", "opombe"))

        scroll_y = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(self.frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        scroll_y.pack(side="right", fill="y", pady=(0, 10))
        scroll_x.pack(side="bottom", fill="x", padx=10)
        self.tree.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 0))
        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Return>", self.on_return)

    def set_connected(self, connected, settings=None):
        """Posodobi stanje povezave; pri vklopu ne sproži počasnega branja samodejno."""
        if settings is not None:
            self.settings = settings or {}
        self.connected = bool(connected)
        if self.connected:
            self.connection_status.configure(
                text="Povezano z MySQL. Za prikaz zgrajenih oseb klikni 'Osveži seznam'.",
                foreground="#16834A",
            )
        else:
            self.connection_status.configure(
                text="Povezava ni vzpostavljena. Najprej shrani nastavitve in poveži program z MySQL.",
                foreground="#8A5A00",
            )
            for item in self.tree.get_children():
                self.tree.delete(item)

    def osvezi_tabelo(self):
        if not self.connected:
            self.connection_status.configure(
                text="Ni povezave z MySQL. Uporabi gumb 'Poveži z bazo' na vrhu programa.",
                foreground="#B42318",
            )
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

        uspeh, data = self._baza().get_zgrajene_osebe()
        if not uspeh:
            messagebox.showerror("Napaka", f"Napaka pri branju zgrajenih oseb:\n{data}", parent=self.frame)
            return

        for row in data:
            if row.get("ime_otroka"):
                ime_priimek = f"{row.get('ime_otroka') or ''} {row.get('priimek_oceta') or ''}".strip()
            elif row.get("ime_pokojnika"):
                ime_priimek = f"{row.get('ime_pokojnika') or ''} {row.get('priimek_pokojnika') or ''}".strip()
            elif row.get("ime_zenina") or row.get("ime_neveste"):
                # Samo za seznam: ne sklepamo, katera poročna oseba je nosilec povezave.
                ime_priimek = (
                    f"{row.get('ime_zenina') or ''} {row.get('priimek_zenina') or ''}".strip()
                    or f"{row.get('ime_neveste') or ''} {row.get('priimek_neveste') or ''}".strip()
                )
            else:
                ime_priimek = "(brez imena)"

            self.tree.insert(
                "", "end", iid=str(row.get("id")),
                values=(
                    row.get("id", ""), ime_priimek,
                    row.get("datum_rojstva") or "/", row.get("datum_poroke") or "/",
                    row.get("datum_smrti") or "/", row.get("opombe") or "",
                    str(row.get("ustvarjeno") or "")[:16],
                ),
            )

    def on_double_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.odpri_osebo(row_id)

    def on_return(self, _event=None):
        self.odpri_izbrano()
        return "break"

    def odpri_izbrano(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Izberi osebo", "Najprej izberi osebo v seznamu.", parent=self.frame)
            return
        self.odpri_osebo(selected[0])

    def odpri_osebo(self, oseba_id):
        if not self.connected:
            messagebox.showwarning(
                "Brez povezave", "Najprej vzpostavi povezavo z MySQL.", parent=self.frame
            )
            return
        uspeh, bundle = self._baza().get_zgrajena_oseba_podrobnosti(oseba_id)
        if not uspeh:
            messagebox.showerror("Napaka", f"Podrobnosti osebe niso dosegljive:\n{bundle}", parent=self.frame)
            return
        self.prikazi_podrobnosti(bundle)

    def prikazi_podrobnosti(self, bundle):
        oseba = bundle.get("oseba") or {}
        win = tk.Toplevel(self.frame)
        win.title(f"Zgrajena oseba – ID {oseba.get('id', '')}")
        win.geometry("1250x850")
        win.minsize(900, 620)

        # Zgornje kontrole ostanejo vidne; podatki se pomikajo znotraj platna.
        top = ttk.Frame(win, padding=(12, 10))
        top.pack(fill="x")
        ttk.Label(
            top,
            text=f"Zgrajena oseba ID {oseba.get('id', '')}",
            font=("Arial", 15, "bold"),
        ).pack(side="left")
        ttk.Button(
            top,
            text="📤 Izvozi osebo v GEDCOM (.ged)",
            command=lambda current=bundle: self.izvozi_gedcom(win, current),
        ).pack(side="right", padx=(5, 0))
        tk.Button(
            top,
            text="⚠ RAZDRUŽI OSEBO",
            command=lambda current_id=oseba.get("id"): self.razdruzi_osebo(win, current_id),
            bg="#A83232",
            fg="white",
            activebackground="#812424",
            activeforeground="white",
            font=("Arial", 9, "bold"),
            relief="flat",
            padx=10,
            pady=5,
        ).pack(side="right", padx=(5, 0))

        canvas = tk.Canvas(win, highlightthickness=0, background="#f4f5f7")
        scroll_y = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        content = ttk.Frame(canvas, padding=14)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        canvas.configure(yscrollcommand=scroll_y.set)
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))
        canvas.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")

        meta = ttk.LabelFrame(content, text="Podatki o povezavi", padding=10)
        meta.pack(fill="x", pady=(0, 12))
        ttk.Label(meta, text=f"ID zgrajene osebe: {oseba.get('id', '/')}").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        ttk.Label(meta, text=f"Ustvarjeno: {oseba.get('ustvarjeno', '/')}").grid(row=0, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(meta, text=f"Krst ID: {oseba.get('krst_id') or '/'}").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        ttk.Label(meta, text=f"Poroka ID: {oseba.get('poroka_id') or '/'}").grid(row=1, column=1, sticky="w", padx=6, pady=3)
        ttk.Label(meta, text=f"Smrt ID: {oseba.get('smrt_id') or '/'}").grid(row=1, column=2, sticky="w", padx=6, pady=3)
        ttk.Label(meta, text="Zaključna ugotovitev / opomba:", font=("Arial", 9, "bold")).grid(row=2, column=0, sticky="nw", padx=6, pady=3)
        note = tk.Text(meta, height=3, wrap="word", width=100)
        note.grid(row=2, column=1, columnspan=2, sticky="ew", padx=6, pady=3)
        note.insert("1.0", oseba.get("opombe") or "/")
        note.configure(state="disabled")
        meta.columnconfigure(1, weight=1)

        sections = (
            ("krsti", "KRSTNI ZAPIS"),
            ("poroke", "POROČNI ZAPIS"),
            ("mrtvi", "MRLIŠKI ZAPIS"),
        )
        for key, title in sections:
            record = bundle.get(key)
            section = ttk.LabelFrame(content, text=title, padding=10)
            section.pack(fill="x", expand=True, pady=7)
            if not record:
                ttk.Label(section, text="S tem zapisom ni povezan noben vnos.", foreground="gray").pack(anchor="w")
                continue

            url = matricula_url(record)
            link_frame = ttk.Frame(section)
            link_frame.pack(fill="x", pady=(0, 8))
            if url:
                ttk.Button(
                    link_frame,
                    text="🌐 Odpri Matriculo – točno na pripadajoči sliki",
                    command=lambda target=url: webbrowser.open(target),
                ).pack(side="left")
                ttk.Button(
                    link_frame,
                    text="Kopiraj povezavo",
                    command=lambda target=url, parent=win: self._copy_url(parent, target),
                ).pack(side="left", padx=6)
                ttk.Label(link_frame, text=url, foreground="#245b8f", wraplength=900).pack(side="left", padx=8)
            else:
                ttk.Label(
                    link_frame,
                    text="Povezava do Matricule ni na voljo – v zapisu manjka župnija ali knjiga.",
                    foreground="#9a4a00",
                ).pack(side="left")

            self._prikazi_vsa_polja(section, record)

        ttk.Label(
            content,
            text="Opomba: izvoženi GEDCOM ohrani izvorne zapise in povezave do Matricule kot citate virov. Datumi, ki jih ni mogoče varno pretvoriti, ostanejo zapisani v podatkih vira.",
            wraplength=1100,
            foreground="#555555",
        ).pack(anchor="w", pady=(10, 5))


    def razdruzi_osebo(self, window, oseba_id):
        """Odstrani samo povezavo med zapisi; izvornih matičnih vnosov ne briše."""
        confirmed = messagebox.askyesno(
            "Potrditev razdružitve",
            "Ali res želiš razdružiti to osebo?\n\n"
            "Izbrisana bo samo povezava v seznamu zgrajenih oseb. "
            "Krstni, poročni in mrliški zapisi v glavni bazi ostanejo nedotaknjeni.",
            parent=window,
        )
        if not confirmed:
            return
        success, result = self._baza().razdruzi_osebo(oseba_id)
        if not success:
            messagebox.showerror("Razdružitev ni uspela", str(result), parent=window)
            return
        messagebox.showinfo("Oseba razdružena", result, parent=window)
        window.destroy()
        self.osvezi_tabelo()

    def _prikazi_vsa_polja(self, parent, record):
        """Prikaže vsa polja vrnjenega MySQL-zapisa, ne le vnaprej izbranih."""
        grid = ttk.Frame(parent)
        grid.pack(fill="x", expand=True)
        grid.columnconfigure(1, weight=1)

        row_index = 0
        for key, value in record.items():
            if value is None or value == "":
                continue
            label = FIELD_LABELS.get(key, key.replace("_", " ").capitalize())
            ttk.Label(grid, text=f"{label}:", font=("Arial", 9, "bold"), width=27).grid(
                row=row_index, column=0, sticky="nw", padx=(4, 12), pady=3
            )
            rendered = str(value)
            if key in ("surovi_tekst", "opombe") and len(rendered) > 180:
                text = tk.Text(grid, height=min(10, max(3, rendered.count("\n") + 2)), wrap="word")
                text.grid(row=row_index, column=1, sticky="ew", padx=4, pady=3)
                text.insert("1.0", rendered)
                text.configure(state="disabled")
            else:
                ttk.Label(grid, text=rendered, wraplength=930, justify="left").grid(
                    row=row_index, column=1, sticky="w", padx=4, pady=3
                )
            row_index += 1

    @staticmethod
    def _copy_url(parent, url):
        try:
            parent.clipboard_clear()
            parent.clipboard_append(url)
            messagebox.showinfo("Povezava kopirana", "Povezava do Matricule je kopirana v odložišče.", parent=parent)
        except tk.TclError as exc:
            messagebox.showerror("Napaka", str(exc), parent=parent)

    def _izberi_vlogo_pri_poroki(self, parent, bundle):
        marriage = bundle.get("poroke") or {}
        if not marriage:
            return None

        suggestion = suggest_marriage_role(bundle)
        initial = suggestion or "unknown"
        dialog = tk.Toplevel(parent)
        dialog.title("Vloga osebe pri poroki")
        dialog.transient(parent)
        dialog.grab_set()
        dialog.resizable(False, False)
        ttk.Label(
            dialog,
            text=(
                "Poročni zapis vsebuje ženina in nevesto. Katera od teh oseb je oseba, "
                "ki jo izvažaš?"
            ),
            wraplength=470,
            justify="left",
        ).pack(anchor="w", padx=14, pady=(14, 8))
        if suggestion:
            suggestion_text = "Samodejni predlog na podlagi natančnega ujemanja imena: " + (
                "ženin" if suggestion == "groom" else "nevesta"
            )
        else:
            suggestion_text = "Samodejnega ujemanja ni – izberi pravilno vlogo ali pusti nedoločeno."
        ttk.Label(dialog, text=suggestion_text, wraplength=470).pack(anchor="w", padx=14, pady=(0, 8))

        choice = tk.StringVar(value=initial)
        options = [
            ("groom", f"Ženin: {marriage.get('ime_zenina') or ''} {marriage.get('priimek_zenina') or ''}".strip()),
            ("bride", f"Nevesta: {marriage.get('ime_neveste') or ''} {marriage.get('priimek_neveste') or ''}".strip()),
        ]
        # Če krstnega ali mrliškega zapisa ni, izbira osebe ne sme ostati nedoločena.
        if bundle.get("krsti") or bundle.get("mrtvi"):
            options.append(("unknown", "Vloga ni določena (poroka se izvozi kot vir/dogodek)"))
        for value, label in options:
            ttk.Radiobutton(dialog, text=label, variable=choice, value=value).pack(anchor="w", padx=18, pady=3)

        result = {"value": None, "cancelled": True}
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=14, pady=14)

        def accept():
            result["value"] = None if choice.get() == "unknown" else choice.get()
            result["cancelled"] = False
            dialog.destroy()

        ttk.Button(buttons, text="Nadaljuj", command=accept).pack(side="right", padx=(5, 0))
        ttk.Button(buttons, text="Prekliči", command=dialog.destroy).pack(side="right")
        dialog.protocol("WM_DELETE_WINDOW", dialog.destroy)
        parent.wait_window(dialog)
        if result["cancelled"]:
            return "__CANCEL__"
        return result["value"]

    def izvozi_gedcom(self, parent, bundle):
        marriage = bundle.get("poroke") or None
        marriage_role = self._izberi_vlogo_pri_poroki(parent, bundle) if marriage else None
        if marriage_role == "__CANCEL__":
            return

        baptism = bundle.get("krsti") or {}
        death = bundle.get("mrtvi") or {}
        given = baptism.get("ime_otroka") or death.get("ime_pokojnika")
        surname = baptism.get("priimek_otroka") or baptism.get("priimek_oceta") or death.get("priimek_pokojnika")
        if not (given or surname) and marriage and marriage_role:
            prefix = "ime_zenina" if marriage_role == "groom" else "ime_neveste"
            surname_key = "priimek_zenina" if marriage_role == "groom" else "priimek_neveste"
            given = marriage.get(prefix)
            surname = marriage.get(surname_key)
        suggested_name = " ".join(str(v).strip() for v in (given, surname) if v).strip() or "oseba"
        safe_name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in suggested_name).strip().replace(" ", "_")
        filepath = filedialog.asksaveasfilename(
            parent=parent,
            title="Izvozi zgrajeno osebo v GEDCOM",
            defaultextension=".ged",
            initialfile=f"{safe_name or 'oseba'}.ged",
            filetypes=[("GEDCOM datoteka", "*.ged"), ("Vse datoteke", "*.*")],
        )
        if not filepath:
            return

        try:
            export_gedcom(bundle, filepath, marriage_role=marriage_role)
        except (OSError, GedcomExportError, ValueError) as exc:
            messagebox.showerror("GEDCOM izvoz ni uspel", str(exc), parent=parent)
            return
        messagebox.showinfo(
            "GEDCOM izvoz končan",
            f"Oseba je izvožena v datoteko:\n{filepath}\n\nFormat: GEDCOM 5.5.1 (UTF-8).",
            parent=parent,
        )

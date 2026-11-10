"""Zavihek za samodejno predlaganje povezav med zapisi iste župnije."""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .glavna_baza import GlavnaBaza
from .iskanje_moznih_zdruzevanj import find_possible_merges, result_labels
from .nastavitve_ujemanja import load_rule_settings, NastavitveUjemanjaDialog


class MorebitneZdruzitveUI:
    """Predlaga verige mrliški → poročni → krstni zapis znotraj ene župnije."""

    def __init__(self, parent, settings_getter, connected_getter, on_use_candidate):
        self.frame = parent
        self.settings_getter = settings_getter
        self.connected_getter = connected_getter
        self.on_use_candidate = on_use_candidate
        self._queue = queue.Queue()
        self._busy = False
        self._parishes = []
        self.results = []
        self.rules = load_rule_settings()
        self._render_token = 0
        self._build_ui()
        self.frame.winfo_toplevel().after(120, self._poll_queue)

    def _build_ui(self):
        top = ttk.LabelFrame(
            self.frame,
            text=" Samodejno iskanje morebitnih povezav znotraj iste župnije ",
            padding=10,
        )
        top.pack(fill="x", padx=10, pady=8)

        ttk.Label(top, text="Župnija:").pack(side="left", padx=(0, 6))
        self.combo_parish = ttk.Combobox(top, width=34, state="readonly")
        self.combo_parish.pack(side="left", padx=4)

        self.btn_refresh = tk.Button(
            top, text="↻ OSVEŽI ŽUPNIJE", command=self.refresh_parishes,
            bg="#2868A6", fg="white", activebackground="#1D4F80",
            activeforeground="white", font=("Arial", 9, "bold"), relief="flat",
            padx=9, pady=5,
        )
        self.btn_refresh.pack(side="left", padx=5)
        self.btn_scan = tk.Button(
            top, text="🔎 IŠČI MOREBITNE ZDRUŽITVE", command=self.run_scan,
            bg="#16834A", fg="white", activebackground="#11683A",
            activeforeground="white", font=("Arial", 9, "bold"), relief="flat",
            padx=10, pady=5,
        )
        self.btn_scan.pack(side="left", padx=5)

        ttk.Label(
            self.frame,
            text=(
                "Program primerja samo zapise iz izbrane župnije. Najprej išče pokojnika v poročni knjigi, "
                "nato starša in naslov poveže s krstnimi zapisi. Ocena 0–100 je hevristična podobnost, "
                "ne statistična verjetnost. Rezultati so predlogi za ročni pregled, ne potrjene osebe."
            ),
            foreground="#765000",
            wraplength=1150,
            justify="left",
        ).pack(fill="x", padx=14, pady=(0, 6))

        self.lbl_status = ttk.Label(
            self.frame,
            text="Najprej osveži seznam župnij. Nato izberi župnijo in sproži iskanje.",
            font=("Arial", 9, "bold"),
        )
        self.lbl_status.pack(fill="x", padx=12, pady=(0, 5))

        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        columns = ("score", "dead", "marriage", "baptism", "reasons")
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "score": ("Ocena", 75),
            "dead": ("Mrliški zapis", 230),
            "marriage": ("Poročni zapis", 260),
            "baptism": ("Krstni zapis / starša", 330),
            "reasons": ("Razlogi za predlog", 450),
        }
        for key, (label, width) in headings.items():
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, minwidth=90, stretch=key in ("baptism", "reasons"))
        yscroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self.open_selected_comparator)

        bottom = ttk.Frame(self.frame, padding=(10, 5))
        bottom.pack(fill="x")
        tk.Button(
            bottom, text="📄 PODROBNOSTI IZBRANE POVEZAVE / PRIMERJALNIK",
            command=self.open_selected_comparator, bg="#2868A6", fg="white",
            activebackground="#1D4F80", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=10, pady=5,
        ).pack(side="left", padx=4)
        tk.Button(
            bottom, text="⚖ ODPREI V PRIMERJALNIK",
            command=self.open_selected_comparator, bg="#E58A16", fg="white",
            activebackground="#B96B0E", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=10, pady=5,
        ).pack(side="left", padx=4)
        tk.Button(
            bottom, text="⚙ NASTAVITVE MERIL",
            command=self.open_rule_settings, bg="#606B78", fg="white",
            activebackground="#46515E", activeforeground="white",
            font=("Arial", 9, "bold"), relief="flat", padx=10, pady=5,
        ).pack(side="right", padx=4)

    def _require_connection(self):
        if self.connected_getter():
            return True
        messagebox.showwarning(
            "MySQL povezava ni vzpostavljena",
            "Najprej se poveži z MySQL z gumbom 'Poveži z bazo'.",
            parent=self.frame,
        )
        return False

    def _set_busy(self, busy, message=None):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.btn_refresh.configure(state=state)
        self.btn_scan.configure(state=state)
        if message:
            self.lbl_status.configure(text=message)

    def refresh_parishes(self):
        if self._busy:
            return
        if not self._require_connection():
            return
        self._set_busy(True, "⏳ Nalagam seznam župnij iz MySQL. Počakaj ...")
        config = dict(self.settings_getter().get("LiveDB", {}))

        def worker():
            success, result = GlavnaBaza(config).get_zupnije()
            self._queue.put(("parishes", success, result))

        threading.Thread(target=worker, daemon=True, name="parish-list-loader").start()

    def open_rule_settings(self):
        def saved(new_rules):
            self.rules = new_rules
            self.lbl_status.configure(
                text=f"Merila so shranjena. Najnižja ocena predloga: {self.rules.get('minimum_score', 55)}/100."
            )
        NastavitveUjemanjaDialog(self.frame.winfo_toplevel(), self.rules, saved)

    def run_scan(self):
        if self._busy:
            return
        if not self._require_connection():
            return
        parish = self.combo_parish.get().strip()
        if not parish:
            messagebox.showwarning("Izberi župnijo", "Izberi župnijo, v kateri naj poiščem povezave.", parent=self.frame)
            return
        self._set_busy(
            True,
            f"⏳ Iščem znotraj župnije {parish}. Najprej primerjam mrliške in poročne, nato še krstne zapise. Počakaj ...",
        )
        self._clear_results()
        config = dict(self.settings_getter().get("LiveDB", {}))
        rules = dict(self.rules)

        def worker():
            success, records = GlavnaBaza(config).get_podatke_za_mozne_zdruzitve(parish)
            if not success:
                self._queue.put(("scan_error", records))
                return
            candidates = find_possible_merges(records, settings=rules)
            counts = {key: len(records.get(key, [])) for key in ("mrtvi", "poroke", "krsti")}
            self._queue.put(("scan_success", parish, counts, candidates))

        threading.Thread(target=worker, daemon=True, name="possible-merges-scan").start()

    def _clear_results(self):
        self._render_token += 1
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.results = []

    def _render_results(self, candidates):
        self._clear_results()
        self.results = candidates
        token = self._render_token
        chunk_size = 100

        def add_chunk(start=0):
            if token != self._render_token or not self.frame.winfo_exists():
                return
            end = min(start + chunk_size, len(candidates))
            for index in range(start, end):
                item = candidates[index]
                dead, marriage, baptism, reasons = result_labels(item)
                self.tree.insert(
                    "", "end", iid=str(index),
                    values=(f"{item['score']}/100", dead, marriage, baptism, reasons),
                )
            if end < len(candidates):
                self.lbl_status.configure(text=f"Prikazujem predloge: {end}/{len(candidates)} ...")
                self.frame.after(1, lambda: add_chunk(end))
            else:
                self.lbl_status.configure(
                    text=f"Najdenih predlogov: {len(candidates)}. Vsak predlog preveri v izvirnih knjigah pred združitvijo."
                )

        add_chunk()

    def _selected_candidate(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("Ni izbire", "Najprej označi predlog v tabeli.", parent=self.frame)
            return None
        try:
            return self.results[int(selected[0])]
        except (ValueError, IndexError):
            return None

    def open_selected_comparator(self, _event=None):
        """Oba gumba in dvoklik odprejo isti primerjalnik za izbrani predlog."""
        candidate = self._selected_candidate()
        if candidate is None:
            return
        self.on_use_candidate(candidate)

    def use_selected_candidate(self):
        """Združljivostno ime za obstoječe klice; odpre isti primerjalnik."""
        self.open_selected_comparator()

    def open_selected_details(self, _event=None):
        """Staro ime dogodka; podrobnosti se odpirajo v ročnem primerjalniku."""
        self.open_selected_comparator()

    def _poll_queue(self):
        if not self.frame.winfo_exists():
            return
        try:
            while True:
                message = self._queue.get_nowait()
                kind = message[0]
                if kind == "parishes":
                    _, success, result = message
                    self._set_busy(False)
                    if not success:
                        self.lbl_status.configure(text="Seznama župnij ni bilo mogoče naložiti.")
                        messagebox.showerror("Napaka baze", str(result), parent=self.frame)
                        continue
                    self._parishes = result
                    self.combo_parish.configure(values=result)
                    if result and not self.combo_parish.get():
                        self.combo_parish.current(0)
                    self.lbl_status.configure(text=f"Naloženih župnij: {len(result)}. Primerjave so vedno omejene na eno izbrano župnijo.")
                elif kind == "scan_error":
                    self._set_busy(False, "Iskanje ni uspelo.")
                    messagebox.showerror("Napaka pri iskanju združitev", str(message[1]), parent=self.frame)
                elif kind == "scan_success":
                    _, parish, counts, candidates = message
                    self._set_busy(
                        False,
                        f"Župnija {parish}: pregledanih {counts['mrtvi']} mrliških, "
                        f"{counts['poroke']} poročnih in {counts['krsti']} krstnih zapisov. "
                        f"Predlogov: {len(candidates)}.",
                    )
                    self._render_results(candidates)
        except queue.Empty:
            pass
        self.frame.after(120, self._poll_queue)

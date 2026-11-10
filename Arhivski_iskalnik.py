"""Glavni zaganjalnik aplikacije Arhivski iskalnik.

Aplikacija se ob zagonu ne povezuje na MySQL. Uporabnik najprej dobi
uporabniški vmesnik, nato po potrebi nastavi in preveri povezavo.
"""

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from moduli.nastavitve import NastavitveBazeDialog, load_settings
from moduli.baza_slovar_mysql import SlovarjiDB
from moduli.ui_slovarji import SlovarjiUI
from moduli.ui_iskalnik import IskalnikUI
from moduli.ui_zgrajene_osebe import ZgrajeneOsebeUI


APP_VERSION = "1.0.9"
class ArhivskiIskalnikApp:
    def __init__(self, root):
        self.root = root
        self.root.title(f"Arhivski iskalnik in povezovalnik – v{APP_VERSION}")
        self.root.geometry("1280x900")
        self.root.minsize(1000, 700)

        # Branje lokalnega JSON besedila nastavitev ne potrebuje povezave.
        self.settings = load_settings()
        # Konstruktor SlovarjiDB je od te različice naprej povsem brez omrežnih klicev.
        self.db = SlovarjiDB(self.settings.get("LiveDB", {}))
        self._queue = queue.Queue()
        self._connecting = False
        self._connected = False
        self._dictionary_data = {}

        self.create_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self.zapri_program)
        self.root.after(100, self._poll_connection_queue)

    def create_widgets(self):
        self.toolbar = ttk.Frame(self.root, padding=(10, 8))
        self.toolbar.pack(fill="x")

        self.lbl_connection = ttk.Label(
            self.toolbar,
            text="● Povezava ni vzpostavljena – program je pripravljen",
            foreground="#8A5A00",
            font=("Arial", 9, "bold"),
        )
        self.lbl_connection.pack(side="left", padx=(0, 12))

        self.btn_settings = tk.Button(
            self.toolbar,
            text="⚙ NASTAVITVE POVEZAVE",
            command=self.open_settings,
            bg="#2868A6", fg="white", activebackground="#1D4F80",
            activeforeground="white", font=("Arial", 9, "bold"),
            relief="flat", padx=10, pady=6,
        )
        self.btn_settings.pack(side="right", padx=4)

        self.btn_connect = tk.Button(
            self.toolbar,
            text="🔌 POVEŽI Z BAZO",
            command=self.connect_and_load,
            bg="#16834A", fg="white", activebackground="#11683A",
            activeforeground="white", font=("Arial", 9, "bold"),
            relief="flat", padx=10, pady=6,
        )
        self.btn_connect.pack(side="right", padx=4)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.tab_iskalnik = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_iskalnik, text=" 🔍 Hibridni iskalnik in povezovanje ")
        self.iskalnik_ui = IskalnikUI(
            self.tab_iskalnik,
            self.db,
            self.settings,
            self.on_settings_changed,
        )

        # Konstruktor ne izvaja SELECT-ov; slovarji se napolnijo šele po povezavi.
        self.slovarji_ui = SlovarjiUI(self.notebook, self.db)

        self.tab_osebe = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_osebe, text=" 🌳 Zgrajene osebe ")
        self.osebe_ui = ZgrajeneOsebeUI(self.tab_osebe, self.settings)

        progress_frame = ttk.Frame(self.root, padding=(12, 4, 12, 10))
        progress_frame.pack(fill="x")
        self.lbl_progress = ttk.Label(progress_frame, text="Pripravljen. MySQL povezava še ni vzpostavljena.")
        self.lbl_progress.pack(anchor="w", pady=(0, 3))
        # Ne uporabljamo utripajočega nedoločenega progress bara. Statusno
        # sporočilo jasno pove, kaj se nalaga in da mora uporabnik počakati.
        self.lbl_progress.configure(
            font=("Arial", 9, "bold"),
            foreground="#805500",
            wraplength=1180,
        )

    def open_settings(self):
        NastavitveBazeDialog(self.root, self.on_settings_changed)

    def on_settings_changed(self, new_settings):
        """Posodobi konfiguracijo brez povezovanja ali nalaganja podatkov."""
        if self._connecting:
            messagebox.showwarning(
                "Povezovanje poteka",
                "Počakaj, da se trenutni poskus povezave konča, nato spremeni nastavitve.",
                parent=self.root,
            )
            return

        self.settings = new_settings or load_settings()
        self.db.update_config(self.settings.get("LiveDB", {}))
        self._connected = False
        self._dictionary_data = {}
        if hasattr(self, "iskalnik_ui"):
            self.iskalnik_ui.settings = self.settings
        if hasattr(self, "slovarji_ui"):
            self.slovarji_ui.clear_loaded_data()
        if hasattr(self, "osebe_ui"):
            self.osebe_ui.set_connected(False, self.settings)

        self.lbl_connection.configure(
            text="● Nastavitve so shranjene – povezava še ni vzpostavljena",
            foreground="#8A5A00",
        )
        self.lbl_progress.configure(
            text="Nastavitve so shranjene. Poveži se, ko želiš uporabljati podatke iz MySQL."
        )

    def connect_and_load(self):
        """V delovni niti vzpostavi povezavo in pripravi tabele slovarjev.

        Veliki seznami imen, priimkov in krajev se naložijo šele ob odprtju
        posameznega zavihka, ne med vzpostavljanjem povezave.
        """
        if self._connecting:
            return

        self.db.update_config(self.settings.get("LiveDB", {}))
        self._connecting = True
        self.btn_connect.configure(state="disabled", text="POVEZOVANJE ...")
        self.btn_settings.configure(state="disabled")
        self.iskalnik_ui.btn_settings.configure(state="disabled")
        self.lbl_connection.configure(
            text="● Povezovanje z MySQL ...",
            foreground="#2868A6",
        )
        self.lbl_progress.configure(
            text=(
                "⏳ Prosim počakaj. Povezujem se z MySQL in preverjam strukturo slovarjev. "
                "Stare podatke prenesem samo ob prvem zagonu; programa ne zapiraj."
            ),
            foreground="#805500",
        )

        config = dict(self.settings.get("LiveDB", {}))

        def worker():
            try:
                self.db.update_config(config)
                # Status se pošilja v glavno nit; omrežje in morebitna
                # migracija ostaneta v delovni niti, zato UI ne zamrzne.
                self.db.initialize(
                    progress_callback=lambda message: self._queue.put(("status", message))
                )
                self._queue.put(("status", "Povezava uspešna. Seznami šifrantov se bodo naložili šele ob odprtju posameznega zavihka."))
                self._queue.put(("success", None))
            except Exception as exc:
                self._queue.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="mysql-dictionary-loader").start()

    def _poll_connection_queue(self):
        if not self.root.winfo_exists():
            return

        try:
            while True:
                message = self._queue.get_nowait()
                kind = message[0]

                if kind == "status":
                    self.lbl_progress.configure(
                        text=f"⏳ {message[1]}  Prosimo, počakaj ...",
                        foreground="#805500",
                    )

                elif kind == "success":
                    self._finish_connection(success=True)
                    self.slovarji_ui.set_connected(True)
                    self.osebe_ui.set_connected(True, self.settings)
                    self.lbl_connection.configure(
                        text="● MySQL povezava uspešna",
                        foreground="#16834A",
                    )
                    self.lbl_progress.configure(
                        text=(
                            "Povezava je pripravljena. Imena, priimki in kraji se naložijo "
                            "posamično, šele ko odpreš njihov zavihek."
                        ),
                        foreground="#16834A",
                    )
                    self.iskalnik_ui.osvezi_seznam_zupnij()

                elif kind == "error":
                    error_text = message[1]
                    self.db.initialized = False
                    self.slovarji_ui.clear_loaded_data()
                    self.osebe_ui.set_connected(False, self.settings)
                    self._finish_connection(success=False)
                    self.lbl_connection.configure(
                        text="● Povezava ni uspela – program ostaja odprt",
                        foreground="#B42318",
                    )
                    self.lbl_progress.configure(
                        text="Preveri host, uporabnika, geslo, ime baze in MySQL strežnik. Podatki šifrantov se naložijo šele, ko odpreš njihov zavihek."
                    )
                    messagebox.showerror(
                        "Povezava z MySQL ni uspela",
                        "Program je ostal odprt. Popravi nastavitve in poskusi znova.\n\n"
                        f"Podrobnosti napake:\n{error_text}",
                        parent=self.root,
                    )
        except queue.Empty:
            pass

        self.root.after(100, self._poll_connection_queue)

    def _finish_connection(self, success):
        self._connecting = False
        self._connected = bool(success)
        self.btn_connect.configure(
            state="normal",
            text="🔄 OSVEŽI POVEZAVO" if success else "🔌 POVEŽI Z BAZO",
        )
        self.btn_settings.configure(state="normal")
        self.iskalnik_ui.btn_settings.configure(state="normal")

    def zapri_program(self):
        try:
            self.db.close()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    try:
        app = ArhivskiIskalnikApp(root)
        root.mainloop()
    except Exception as exc:
        messagebox.showerror("Napaka pri zagonu", str(exc))
        try:
            root.destroy()
        except Exception:
            pass

"""Nastavitve povezave z glavno MySQL-bazo."""

import json
import os
import tempfile
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk


PROJECT_DIR = Path(__file__).resolve().parent.parent
SETTINGS_FILE = PROJECT_DIR / "iskalnik_settings.txt"


def _settings_candidates():
    """Prebere tudi staro lokacijo glede na delovno mapo ali mapo moduli."""
    candidates = (
        SETTINGS_FILE,
        Path.cwd() / "iskalnik_settings.txt",
        Path(__file__).resolve().parent / "iskalnik_settings.txt",
        PROJECT_DIR.parent / "iskalnik_settings.txt",
    )
    unique = []
    seen = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key not in seen:
            unique.append(candidate)
            seen.add(key)
    return unique


def privzete_nastavitve():
    return {
        "LiveDB": {
            "host": "localhost",
            "user": "root",
            "password": "",
            "database": "maticne_knjige_db",
            "port": 3306,
        }
    }


def load_settings():
    """Naloži nastavitve iz znane lokacije in po potrebi prenese staro datoteko."""
    settings = privzete_nastavitve()
    source_path = None
    for candidate in _settings_candidates():
        if not candidate.is_file():
            continue
        try:
            with candidate.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and isinstance(data.get("LiveDB"), dict):
                settings["LiveDB"].update(data["LiveDB"])
                source_path = candidate
                break
        except (OSError, json.JSONDecodeError, TypeError):
            # Neveljavno datoteko preskoči; naslednja znana lokacija je lahko pravilna.
            continue

    try:
        settings["LiveDB"]["port"] = int(settings["LiveDB"].get("port", 3306))
    except (TypeError, ValueError):
        settings["LiveDB"]["port"] = 3306

    # Če so bile nastavitve najdene v stari lokaciji, jih prenese v mapo programa.
    if source_path and source_path.resolve() != SETTINGS_FILE.resolve():
        save_settings(settings)
    return settings


def save_settings(settings_dict):
    """Varno shrani nastavitve z atomskim preimenovanjem začasne datoteke."""
    temp_path = None
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=str(SETTINGS_FILE.parent),
            delete=False,
            suffix=".tmp",
        ) as handle:
            json.dump(settings_dict, handle, ensure_ascii=False, indent=4)
            temp_path = Path(handle.name)
        os.replace(str(temp_path), str(SETTINGS_FILE))
        return True
    except (OSError, TypeError, ValueError):
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass
        return False


def test_mysql_connection(db_config, timeout=5):
    """Preveri samo prijavo in SELECT 1; ne ustvarja tabel ali spreminja baze."""
    try:
        import pymysql
    except ImportError:
        return False, "Manjka PyMySQL. Namesti ga z: python -m pip install PyMySQL"

    connection = None
    try:
        connection = pymysql.connect(
            host=str(db_config.get("host", "localhost")).strip(),
            user=str(db_config.get("user", "")).strip(),
            password=str(db_config.get("password", "")),
            database=str(db_config.get("database", "")).strip(),
            port=int(db_config.get("port", 3306)),
            charset="utf8mb4",
            connect_timeout=timeout,
            read_timeout=timeout,
            write_timeout=timeout,
            autocommit=True,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return True, "Povezava z MySQL je uspešna. Strežnik je odgovoril na SELECT 1."
    except Exception as exc:
        return False, str(exc)
    finally:
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


class NastavitveBazeDialog(tk.Toplevel):
    """Nastavitve povezave, ki jih je mogoče preveriti brez blokiranja GUI-ja."""

    def __init__(self, parent, on_save_callback):
        super().__init__(parent)
        self.title("Nastavitve povezave z glavno bazo (MySQL)")
        self.geometry("500x430")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.on_save_callback = on_save_callback
        self.settings = load_settings()
        self.db_config = self.settings["LiveDB"]
        self._test_queue = queue.Queue()
        self._test_running = False

        fields = (
            ("Host / IP strežnika:", "host", False),
            ("Uporabniško ime:", "user", False),
            ("Geslo:", "password", True),
            ("Ime baze:", "database", False),
            ("Vrata (port):", "port", False),
        )
        form = ttk.Frame(self, padding=(18, 14))
        form.pack(fill="x")
        self.entries = {}
        for row, (label, key, hidden) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
            entry = ttk.Entry(form, width=38, show="*" if hidden else "")
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            entry.insert(0, str(self.db_config.get(key, "")))
            self.entries[key] = entry
        form.columnconfigure(1, weight=1)

        self.lbl_test = ttk.Label(self, text="Povezava še ni preverjena.", wraplength=455)
        self.lbl_test.pack(fill="x", padx=18, pady=(3, 8))

        controls = ttk.Frame(self, padding=(12, 8))
        controls.pack(fill="x", side="bottom")
        self.btn_test = tk.Button(
            controls,
            text="🔌 PREVERI POVEZAVO",
            command=self.preveri_povezavo,
            bg="#2868A6", fg="white", activebackground="#1D4F80",
            activeforeground="white", font=("Arial", 9, "bold"),
            relief="flat", padx=12, pady=7,
        )
        self.btn_test.pack(side="left", padx=5)
        self.btn_save = tk.Button(
            controls, text="💾 SHRANI NASTAVITVE", command=self.save_and_close,
            bg="#16834A", fg="white", activebackground="#11683A",
            activeforeground="white", font=("Arial", 9, "bold"),
            relief="flat", padx=12, pady=7,
        )
        self.btn_save.pack(side="left", padx=5)
        self.btn_cancel = ttk.Button(controls, text="Prekliči", command=self._close_dialog)
        self.btn_cancel.pack(side="right", padx=5)
        self.protocol("WM_DELETE_WINDOW", self._close_dialog)

    def _collect_config(self):
        host = self.entries["host"].get().strip()
        user = self.entries["user"].get().strip()
        database = self.entries["database"].get().strip()
        password = self.entries["password"].get()
        try:
            port = int(self.entries["port"].get().strip())
        except ValueError:
            raise ValueError("Port mora biti celo število med 1 in 65535.")
        if not host or not user or not database:
            raise ValueError("Host, uporabniško ime in ime baze ne smejo biti prazni.")
        if not 1 <= port <= 65535:
            raise ValueError("Port mora biti med 1 in 65535.")
        return {
            "host": host,
            "user": user,
            "password": password,
            "database": database,
            "port": port,
        }

    def preveri_povezavo(self):
        if self._test_running:
            return
        try:
            config = self._collect_config()
        except ValueError as exc:
            messagebox.showerror("Neveljavne nastavitve", str(exc), parent=self)
            return

        self._test_running = True
        self.btn_test.configure(state="disabled", text="PREVERJAM ...")
        self.btn_save.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        self.lbl_test.configure(text="Preverjam prijavo na MySQL strežnik ...")

        def worker():
            self._test_queue.put(test_mysql_connection(config))

        threading.Thread(target=worker, daemon=True, name="mysql-connection-test").start()
        self.after(100, self._poll_test_result)

    def _poll_test_result(self):
        if not self.winfo_exists():
            return
        try:
            success, message = self._test_queue.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_test_result)
            return

        self._test_running = False
        self.btn_test.configure(state="normal", text="🔌 PREVERI POVEZAVO")
        self.btn_save.configure(state="normal")
        self.btn_cancel.configure(state="normal")
        self.lbl_test.configure(
            text=("✓ " if success else "✕ Napaka: ") + message,
            foreground="#16834A" if success else "#B42318",
        )

    def _close_dialog(self):
        if self._test_running:
            messagebox.showinfo(
                "Preverjanje poteka",
                "Počakaj, da se preverjanje povezave zaključi.",
                parent=self,
            )
            return
        self.destroy()

    def save_and_close(self):
        try:
            config = self._collect_config()
        except ValueError as exc:
            messagebox.showerror("Neveljavne nastavitve", str(exc), parent=self)
            return

        self.settings["LiveDB"] = config
        if not save_settings(self.settings):
            messagebox.showerror("Napaka", "Nastavitev ni bilo mogoče shraniti.", parent=self)
            return

        # Shrani konfiguracijo, vendar se tukaj NE povezuje na MySQL.
        if self.on_save_callback:
            self.on_save_callback(self.settings)
        messagebox.showinfo(
            "Shranjeno",
            "Nastavitve so shranjene. Povezava še ni vzpostavljena. "
            "Za nalaganje podatkov uporabi gumb 'Poveži z bazo'.",
            parent=self,
        )
        self.destroy()

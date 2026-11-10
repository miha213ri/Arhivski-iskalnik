"""SQLite-podatkovna baza kanoničnih imen, priimkov in krajev."""

import json
import sqlite3
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_DIR / "slovarji.db"
ALLOWED_TYPES = {"ime", "priimek", "kraj"}


class SandboxDB:
    def __init__(self, db_path=None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), timeout=15, check_same_thread=False)
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.ustvari_tabele()

    def ustvari_tabele(self):
        with self.conn:
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS kanonicne_oblike (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tip TEXT NOT NULL,
                    naziv TEXT NOT NULL,
                    spol_tip TEXT DEFAULT '',
                    opombe TEXT DEFAULT ''
                )"""
            )
            self.conn.execute(
                """CREATE TABLE IF NOT EXISTS variacije (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kanonicna_id INTEGER NOT NULL,
                    izvirni_zapis TEXT NOT NULL,
                    iskalni_niz TEXT DEFAULT '',
                    stopnja_zaupanja TEXT DEFAULT 'high',
                    FOREIGN KEY(kanonicna_id) REFERENCES kanonicne_oblike(id)
                        ON DELETE CASCADE
                )"""
            )
            # Varna nadgradnja obstoječe datoteke slovarji.db.
            existing_columns = {
                row[1] for row in self.conn.execute("PRAGMA table_info(kanonicne_oblike)").fetchall()
            }
            if "opombe" not in existing_columns:
                self.conn.execute("ALTER TABLE kanonicne_oblike ADD COLUMN opombe TEXT DEFAULT ''")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_kanonicne_tip_naziv ON kanonicne_oblike(tip, naziv)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_variacije_kanonicna ON variacije(kanonicna_id)"
            )

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def get_canonical_list(self, tip):
        if tip not in ALLOWED_TYPES:
            raise ValueError("Neznan tip slovarja.")
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, naziv, spol_tip FROM kanonicne_oblike WHERE tip=? ORDER BY naziv COLLATE NOCASE",
            (tip,),
        )
        return cur.fetchall()

    def get_variants_for_entity(self, entity_id):
        cur = self.conn.cursor()
        cur.execute(
            """SELECT id, izvirni_zapis, iskalni_niz, stopnja_zaupanja
               FROM variacije WHERE kanonicna_id=? ORDER BY izvirni_zapis COLLATE NOCASE""",
            (entity_id,),
        )
        return cur.fetchall()

    def get_canonical_notes(self, entity_id):
        cur = self.conn.cursor()
        cur.execute("SELECT opombe FROM kanonicne_oblike WHERE id=?", (entity_id,))
        row = cur.fetchone()
        return row[0] if row else ""

    def dodaj_kanonicno_entiteto(self, tip, naziv, spol_tip="", opombe=""):
        if tip not in ALLOWED_TYPES:
            raise ValueError("Neznan tip slovarja.")
        naziv = str(naziv).strip()
        if not naziv:
            raise ValueError("Kanonično ime ne sme biti prazno.")
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO kanonicne_oblike (tip, naziv, spol_tip, opombe) VALUES (?, ?, ?, ?)",
            (tip, naziv, spol_tip, opombe),
        )
        self.conn.commit()
        return cur.lastrowid

    def uredi_kanonicno_entiteto(self, entity_id, naziv, spol_tip, opombe=""):
        naziv = str(naziv).strip()
        if not naziv:
            raise ValueError("Kanonično ime ne sme biti prazno.")
        cur = self.conn.cursor()
        cur.execute(
            "UPDATE kanonicne_oblike SET naziv=?, spol_tip=?, opombe=? WHERE id=?",
            (naziv, spol_tip, opombe, entity_id),
        )
        self.conn.commit()

    def dodaj_variacijo(self, entity_id, izvirni_zapis, iskalni_niz="", zaupanje="high"):
        izvirni_zapis = str(izvirni_zapis).strip()
        if not izvirni_zapis:
            return False, "Izvirni zapis ne sme biti prazen."
        if not iskalni_niz:
            iskalni_niz = izvirni_zapis.casefold()
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id FROM variacije WHERE kanonicna_id=? AND izvirni_zapis=?",
            (entity_id, izvirni_zapis),
        )
        if cur.fetchone():
            return False, "Variacija že obstaja."
        try:
            cur.execute(
                """INSERT INTO variacije
                   (kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja)
                   VALUES (?, ?, ?, ?)""",
                (entity_id, izvirni_zapis, iskalni_niz, zaupanje),
            )
            self.conn.commit()
            return True, "Dodano."
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            return False, str(exc)

    def odstrani_preslikavo(self, entity_id, var_id):
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM variacije WHERE id=? AND kanonicna_id=?",
            (var_id, entity_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def import_json_dictionary(self, filepath, dict_type):
        """Uvozi staro seznamno ali relacijsko shemo JSON; ob napaki razveljavi uvoz."""
        if dict_type not in ALLOWED_TYPES:
            return False, "Neznan tip slovarja."

        try:
            with open(filepath, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)

            cur = self.conn.cursor()
            cur.execute("BEGIN")
            count_kanon = 0
            count_var = 0

            if isinstance(data, dict) and data.get("schema_version") == "2.0" and isinstance(data.get("tables"), dict):
                tables = data["tables"]
                canonical_items = tables.get("canonical_names", [])
                variant_items = tables.get("variants", [])
                mappings = tables.get("variant_mappings", [])
                if not all(isinstance(value, list) for value in (canonical_items, variant_items, mappings)):
                    raise ValueError("Neveljavna struktura tabel v JSON datoteki.")

                can_names = {}
                for item in canonical_items:
                    if not isinstance(item, dict) or "canonical_name_id" not in item:
                        continue
                    can_names[str(item["canonical_name_id"])] = item

                variants = {}
                for item in variant_items:
                    if not isinstance(item, dict) or "variant_id" not in item:
                        continue
                    variants[str(item["variant_id"])] = item

                id_map = {}
                for can_id, can_data in can_names.items():
                    naziv = str(can_data.get("name", "")).strip()
                    opombe = str(can_data.get("notes", "")).strip()
                    if not naziv:
                        continue
                    cur.execute(
                        "SELECT id FROM kanonicne_oblike WHERE tip=? AND naziv=?",
                        (dict_type, naziv),
                    )
                    row = cur.fetchone()
                    if row:
                        local_id = row[0]
                        if opombe:
                            cur.execute(
                                "UPDATE kanonicne_oblike SET opombe=? WHERE id=?",
                                (opombe, local_id),
                            )
                    else:
                        cur.execute(
                            "INSERT INTO kanonicne_oblike (tip, naziv, spol_tip, opombe) VALUES (?, ?, ?, ?)",
                            (dict_type, naziv, "", opombe),
                        )
                        local_id = cur.lastrowid
                        count_kanon += 1
                    id_map[can_id] = local_id

                for mapping in mappings:
                    if not isinstance(mapping, dict):
                        continue
                    can_id = str(mapping.get("canonical_name_id", ""))
                    var_id = str(mapping.get("variant_id", ""))
                    if can_id not in id_map or var_id not in variants:
                        continue
                    variant = variants[var_id]
                    izvirno = str(variant.get("written_form", "")).strip()
                    if not izvirno:
                        continue
                    iskalno = str(variant.get("normalized_form") or izvirno.casefold()).strip()
                    confidence = str(mapping.get("confidence", "high"))
                    cur.execute(
                        "SELECT id FROM variacije WHERE kanonicna_id=? AND izvirni_zapis=?",
                        (id_map[can_id], izvirno),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            """INSERT INTO variacije
                               (kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja)
                               VALUES (?, ?, ?, ?)""",
                            (id_map[can_id], izvirno, iskalno, confidence),
                        )
                        count_var += 1

                self.conn.commit()
                return True, f"Uvoženo: {count_kanon} glavnih vnosov in {count_var} variacij."

            if not isinstance(data, list):
                raise ValueError("JSON mora biti seznam vnosov ali podpirana relacijska shema 2.0.")

            for item in data:
                if not isinstance(item, dict):
                    continue
                kanon = str(item.get("kanonicna_oblika", "")).strip()
                spol = str(item.get("spol_tip", "")).strip()
                opombe = str(item.get("opombe", item.get("notes", ""))).strip()
                var_list = item.get("variacije", [])
                if not kanon:
                    continue
                if not isinstance(var_list, list):
                    raise ValueError(f"Variacije pri vnosu '{kanon}' niso seznam.")

                cur.execute(
                    "SELECT id FROM kanonicne_oblike WHERE tip=? AND naziv=?",
                    (dict_type, kanon),
                )
                row = cur.fetchone()
                if row:
                    kanon_id = row[0]
                else:
                    cur.execute(
                        "INSERT INTO kanonicne_oblike (tip, naziv, spol_tip, opombe) VALUES (?, ?, ?, ?)",
                        (dict_type, kanon, spol, opombe),
                    )
                    kanon_id = cur.lastrowid
                    count_kanon += 1

                for variant in var_list:
                    if not isinstance(variant, dict):
                        continue
                    izvirno = str(variant.get("izvirni_zapis", "")).strip()
                    if not izvirno:
                        continue
                    iskalno = str(variant.get("iskalni_niz", "")).strip() or izvirno.casefold()
                    zaupanje = str(variant.get("zaupanje", "high")).strip() or "high"
                    cur.execute(
                        "SELECT id FROM variacije WHERE kanonicna_id=? AND izvirni_zapis=?",
                        (kanon_id, izvirno),
                    )
                    if not cur.fetchone():
                        cur.execute(
                            """INSERT INTO variacije
                               (kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja)
                               VALUES (?, ?, ?, ?)""",
                            (kanon_id, izvirno, iskalno, zaupanje),
                        )
                        count_var += 1

            self.conn.commit()
            return True, f"Uvoz uspešen: {count_kanon} glavnih vnosov in {count_var} variacij."
        except (OSError, json.JSONDecodeError, sqlite3.Error, TypeError, ValueError, KeyError) as exc:
            self.conn.rollback()
            return False, str(exc)

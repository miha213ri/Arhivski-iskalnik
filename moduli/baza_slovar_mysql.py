"""Slovarji imen, priimkov in krajev v isti MySQL-bazi kot matične knjige.

Staro datoteko slovarji.db (SQLite) prebere in prenese v MySQL, vendar je ne izbriše.
"""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

try:
    import pymysql
except ImportError:  # pragma: no cover - odvisno od namestitve
    pymysql = None


PROJECT_DIR = Path(__file__).resolve().parent.parent
LEGACY_DB_CANDIDATES = (PROJECT_DIR / "slovarji.db", Path.cwd() / "slovarji.db")
ALLOWED_TYPES = {"ime", "priimek", "kraj"}
CANONICAL_TABLE = "arhivski_kanonicne_oblike"
VARIANT_TABLE = "arhivski_variacije"
MIGRATION_TABLE = "arhivski_migracije"


class SlovarjiDB:
    """Dostop do slovarjev prek iste povezave in sheme kot glavna MySQL-baza."""

    def __init__(self, db_config, legacy_db_path=None):
        # Konstruktor namenoma NE vzpostavi povezave. Aplikacija se mora
        # najprej odpreti, uporabnik pa sam izbere in preveri MySQL nastavitve.
        self.config = dict(db_config or {})
        self.legacy_db_path = Path(legacy_db_path) if legacy_db_path else None
        self.initialized = False
        self._initializing = False

    def initialize(self, progress_callback=None):
        """Pripravi slovarje; statusne informacije pošilja klicatelju.

        Klicatelj naj metodo zažene v delovni niti. Običajni ponovni zagoni
        preskočijo že izvedeno migracijo stare datoteke slovarji.db.
        """
        if self.initialized:
            return 0, 0
        if self._initializing:
            raise RuntimeError("Priprava slovarjev že poteka.")
        self._initializing = True
        try:
            self._report(progress_callback, "Preverjam strukturo slovarjev v MySQL ...")
            self.ensure_schema()
            migrated = self.migrate_legacy_sqlite(progress_callback=progress_callback)
            self.initialized = True
            self._report(progress_callback, "Slovarji v MySQL so pripravljeni.")
            return migrated
        except Exception:
            self.initialized = False
            raise
        finally:
            self._initializing = False

    @staticmethod
    def _report(callback, message):
        if callback:
            try:
                callback(str(message))
            except Exception:
                # Napaka v prikazu statusa ne sme prekiniti migracije.
                pass

    def _ensure_initialized(self):
        """Zaščitni mehanizem za operacije, sprožene po zagonu aplikacije."""
        if not self.initialized:
            self.initialize()

    def get_connection(self):
        if pymysql is None:
            raise RuntimeError("Manjka PyMySQL. Namesti ga z: python -m pip install PyMySQL")
        return pymysql.connect(
            host=self.config.get("host", "localhost"),
            user=self.config.get("user", "root"),
            password=self.config.get("password", ""),
            database=self.config.get("database", "maticne_knjige_db"),
            port=int(self.config.get("port", 3306)),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.Cursor,
            connect_timeout=8,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
        )

    def update_config(self, db_config):
        """Shrani novo konfiguracijo brez omrežnega klica.

        Povezava se vzpostavi šele, ko uporabnik izrecno izbere povezovanje.
        """
        self.config = dict(db_config or {})
        self.initialized = False

    def ensure_schema(self):
        """Ustvari namenski tabeli; drugih tabel v glavni bazi ne spreminja."""
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""CREATE TABLE IF NOT EXISTS `{CANONICAL_TABLE}` (
                        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        tip VARCHAR(20) NOT NULL,
                        naziv VARCHAR(255) NOT NULL,
                        spol_tip VARCHAR(120) DEFAULT '',
                        opombe TEXT,
                        ustvarjeno TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_arhiv_tip_naziv (tip, naziv(160)),
                        INDEX idx_arhiv_tip (tip)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                )
                cursor.execute(
                    f"""CREATE TABLE IF NOT EXISTS `{VARIANT_TABLE}` (
                        id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
                        kanonicna_id BIGINT NOT NULL,
                        izvirni_zapis VARCHAR(255) NOT NULL,
                        iskalni_niz VARCHAR(255) DEFAULT '',
                        stopnja_zaupanja VARCHAR(30) DEFAULT 'high',
                        ustvarjeno TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY uq_arhiv_variacija (kanonicna_id, izvirni_zapis(170)),
                        INDEX idx_arhiv_variacija_iskalni (iskalni_niz(100)),
                        CONSTRAINT fk_arhiv_variacija_kanonicna
                            FOREIGN KEY (kanonicna_id)
                            REFERENCES `{CANONICAL_TABLE}`(id) ON DELETE CASCADE
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                )
                cursor.execute(
                    f"""CREATE TABLE IF NOT EXISTS `{MIGRATION_TABLE}` (
                        migration_key CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL PRIMARY KEY,
                        fingerprint VARCHAR(255) NOT NULL,
                        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                )
            conn.commit()

    def migrate_legacy_sqlite(self, progress_callback=None):
        """Hitro in idempotentno prenese star SQLite slovar v MySQL.

        Uporabi označevalno tabelo, zato enake datoteke ob naslednjih zagonih
        ne obdeluje znova. Prenos uporablja paketne INSERT poizvedbe.
        """
        candidates = [self.legacy_db_path] if self.legacy_db_path else list(LEGACY_DB_CANDIDATES)
        legacy_path = next((path for path in candidates if path and path.is_file()), None)
        if not legacy_path:
            self._report(progress_callback, "Stare datoteke slovarji.db ni – uporabljam podatke iz MySQL.")
            return 0, 0

        stat = legacy_path.stat()
        migration_key = hashlib.sha256(
            str(legacy_path.resolve()).encode("utf-8")
        ).hexdigest()
        fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
        self._report(progress_callback, "Preverjam, ali je treba prenesti star lokalni slovar ...")
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT fingerprint FROM `{MIGRATION_TABLE}` WHERE migration_key=%s",
                    (migration_key,),
                )
                marker = cursor.fetchone()
        if marker and marker[0] == fingerprint:
            self._report(progress_callback, "Stari slovar je že prenesen – ponovni prenos je preskočen.")
            return 0, 0

        self._report(
            progress_callback,
            "Prvi prenos ali sprememba slovarji.db: prenašam stare vnose. "
            "To se po uspešnem zaključku ob naslednjih zagonih preskoči ...",
        )
        sqlite_conn = sqlite3.connect(str(legacy_path))
        sqlite_conn.row_factory = sqlite3.Row
        try:
            tables = {
                row[0]
                for row in sqlite_conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            if not {"kanonicne_oblike", "variacije"}.issubset(tables):
                return 0, 0
            canonical_columns = {
                row[1] for row in sqlite_conn.execute("PRAGMA table_info(kanonicne_oblike)")
            }
            note_expr = "opombe" if "opombe" in canonical_columns else "'' AS opombe"
            canonical_rows = sqlite_conn.execute(
                f"SELECT id, tip, naziv, spol_tip, {note_expr} FROM kanonicne_oblike ORDER BY id"
            ).fetchall()
            variant_rows = sqlite_conn.execute(
                "SELECT id, kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja "
                "FROM variacije ORDER BY id"
            ).fetchall()

            canonical_payload = [
                (row["tip"], str(row["naziv"]).strip(), row["spol_tip"] or "", row["opombe"] or "")
                for row in canonical_rows
                if row["tip"] in ALLOWED_TYPES and str(row["naziv"] or "").strip()
            ]
            variant_rows = [
                row for row in variant_rows
                if str(row["izvirni_zapis"] or "").strip()
            ]
            count_canonical = 0
            count_variants = 0

            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    if canonical_payload:
                        cursor.executemany(
                            f"INSERT IGNORE INTO `{CANONICAL_TABLE}` (tip, naziv, spol_tip, opombe) "
                            "VALUES (%s, %s, %s, %s)",
                            canonical_payload,
                        )
                        count_canonical = max(cursor.rowcount, 0)

                    cursor.execute(
                        f"SELECT id, tip, naziv FROM `{CANONICAL_TABLE}` "
                        "WHERE tip IN (%s, %s, %s)",
                        ("ime", "priimek", "kraj"),
                    )
                    new_ids = {(row[1], row[2]): row[0] for row in cursor.fetchall()}
                    old_to_new = {}
                    for row in canonical_rows:
                        new_id = new_ids.get((row["tip"], str(row["naziv"] or "").strip()))
                        if new_id:
                            old_to_new[row["id"]] = new_id

                    variant_payload = []
                    for row in variant_rows:
                        new_id = old_to_new.get(row["kanonicna_id"])
                        written = str(row["izvirni_zapis"] or "").strip()
                        if not new_id or not written:
                            continue
                        variant_payload.append((
                            new_id, written, row["iskalni_niz"] or written.casefold(),
                            row["stopnja_zaupanja"] or "high",
                        ))
                    # Paket 500 vrstic omeji velikost posamezne SQL poizvedbe.
                    for start in range(0, len(variant_payload), 500):
                        batch = variant_payload[start:start + 500]
                        cursor.executemany(
                            f"INSERT IGNORE INTO `{VARIANT_TABLE}` "
                            "(kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja) "
                            "VALUES (%s, %s, %s, %s)",
                            batch,
                        )
                        count_variants += max(cursor.rowcount, 0)
                        self._report(
                            progress_callback,
                            f"Prenašam zgodovinske variante: {min(start + len(batch), len(variant_payload))} "
                            f"/ {len(variant_payload)} ...",
                        )

                    cursor.execute(
                        f"INSERT INTO `{MIGRATION_TABLE}` (migration_key, fingerprint) "
                        "VALUES (%s, %s) ON DUPLICATE KEY UPDATE fingerprint=VALUES(fingerprint), "
                        "completed_at=CURRENT_TIMESTAMP",
                        (migration_key, fingerprint),
                    )
                conn.commit()
            self._report(
                progress_callback,
                f"Prenos zaključen: {count_canonical} novih kanoničnih oblik in "
                f"{count_variants} novih variacij.",
            )
            return count_canonical, count_variants
        finally:
            sqlite_conn.close()

    @staticmethod
    def _validate_type(tip):
        if tip not in ALLOWED_TYPES:
            raise ValueError("Neznan tip slovarja.")

    def get_canonical_list(self, tip):
        self._ensure_initialized()
        self._validate_type(tip)
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, naziv, spol_tip FROM `{CANONICAL_TABLE}` "
                    "WHERE tip=%s ORDER BY naziv",
                    (tip,),
                )
                return cursor.fetchall()

    def get_canonical_by_id(self, entity_id):
        """Vrne eno kanonično obliko brez prenosa celotnega slovarja."""
        self._ensure_initialized()
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, tip, naziv, spol_tip, opombe FROM `{CANONICAL_TABLE}` WHERE id=%s",
                    (int(entity_id),),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                return dict(zip(("id", "tip", "naziv", "spol_tip", "opombe"), row))

    def get_all_canonical_lists(self):
        """Naloži vse tri slovarje z eno MySQL povezavo namesto treh."""
        self._ensure_initialized()
        data = {kind: [] for kind in ALLOWED_TYPES}
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, tip, naziv, spol_tip FROM `{CANONICAL_TABLE}` "
                    "WHERE tip IN (%s, %s, %s) ORDER BY tip, naziv",
                    ("ime", "priimek", "kraj"),
                )
                for entity_id, kind, name, gender_type in cursor.fetchall():
                    if kind in data:
                        data[kind].append((entity_id, name, gender_type))
        return data

    def get_variants_for_entity(self, entity_id):
        self._ensure_initialized()
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, izvirni_zapis, iskalni_niz, stopnja_zaupanja "
                    f"FROM `{VARIANT_TABLE}` WHERE kanonicna_id=%s "
                    "ORDER BY izvirni_zapis",
                    (int(entity_id),),
                )
                return cursor.fetchall()

    def get_canonical_notes(self, entity_id):
        self._ensure_initialized()
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT opombe FROM `{CANONICAL_TABLE}` WHERE id=%s",
                    (int(entity_id),),
                )
                row = cursor.fetchone()
                return row[0] if row else ""

    def get_search_terms(self, value, tip):
        self._ensure_initialized()
        """Vrne vnos, kanonično obliko in variante ob natančnem ujemanju s slovarjem."""
        self._validate_type(tip)
        value = str(value or "").strip()
        if not value:
            return []
        terms = [value]
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""SELECT DISTINCT c.id, c.naziv
                        FROM `{CANONICAL_TABLE}` c
                        LEFT JOIN `{VARIANT_TABLE}` v ON v.kanonicna_id=c.id
                        WHERE c.tip=%s AND (
                            LOWER(c.naziv)=LOWER(%s) OR
                            LOWER(v.izvirni_zapis)=LOWER(%s) OR
                            LOWER(v.iskalni_niz)=LOWER(%s)
                        )""",
                    (tip, value, value, value),
                )
                entities = cursor.fetchall()
                for entity_id, canonical in entities:
                    if canonical and canonical not in terms:
                        terms.append(canonical)
                    cursor.execute(
                        f"SELECT izvirni_zapis, iskalni_niz FROM `{VARIANT_TABLE}` WHERE kanonicna_id=%s",
                        (entity_id,),
                    )
                    for written, normalized in cursor.fetchall():
                        for candidate in (written, normalized):
                            if candidate and candidate not in terms:
                                terms.append(candidate)
        return terms

    def dodaj_kanonicno_entiteto(self, tip, naziv, spol_tip="", opombe=""):
        self._ensure_initialized()
        self._validate_type(tip)
        naziv = str(naziv or "").strip()
        if not naziv:
            raise ValueError("Kanonično ime ne sme biti prazno.")
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"INSERT INTO `{CANONICAL_TABLE}` (tip, naziv, spol_tip, opombe) VALUES (%s, %s, %s, %s)",
                    (tip, naziv, spol_tip or "", opombe or ""),
                )
                entity_id = cursor.lastrowid
            conn.commit()
            return entity_id

    def uredi_kanonicno_entiteto(self, entity_id, naziv, spol_tip="", opombe=""):
        self._ensure_initialized()
        naziv = str(naziv or "").strip()
        if not naziv:
            raise ValueError("Kanonično ime ne sme biti prazno.")
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"UPDATE `{CANONICAL_TABLE}` SET naziv=%s, spol_tip=%s, opombe=%s WHERE id=%s",
                    (naziv, spol_tip or "", opombe or "", int(entity_id)),
                )
                if cursor.rowcount == 0:
                    cursor.execute(f"SELECT id FROM `{CANONICAL_TABLE}` WHERE id=%s", (int(entity_id),))
                    if not cursor.fetchone():
                        raise ValueError("Izbrani slovarski vnos ne obstaja več.")
            conn.commit()

    def dodaj_variacijo(self, entity_id, izvirni_zapis, iskalni_niz="", zaupanje="high"):
        self._ensure_initialized()
        written = str(izvirni_zapis or "").strip()
        if not written:
            return False, "Izvirni zapis ne sme biti prazen."
        try:
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        f"INSERT INTO `{VARIANT_TABLE}` "
                        "(kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja) "
                        "VALUES (%s, %s, %s, %s)",
                        (int(entity_id), written, str(iskalni_niz or written.casefold()), str(zaupanje or "high")),
                    )
                conn.commit()
            return True, "Variacija je dodana."
        except Exception as exc:
            args = getattr(exc, "args", ())
            if args and args[0] == 1062:
                return False, "Variacija že obstaja pri tej kanonični obliki."
            return False, str(exc)

    def odstrani_preslikavo(self, entity_id, var_id):
        self._ensure_initialized()
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"DELETE FROM `{VARIANT_TABLE}` WHERE id=%s AND kanonicna_id=%s",
                    (int(var_id), int(entity_id)),
                )
                removed = cursor.rowcount > 0
            conn.commit()
            return removed

    def get_dictionary_export_data(self, dict_type):
        self._ensure_initialized()
        self._validate_type(dict_type)
        with closing(self.get_connection()) as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"SELECT id, naziv, spol_tip, opombe FROM `{CANONICAL_TABLE}` "
                    "WHERE tip=%s ORDER BY naziv",
                    (dict_type,),
                )
                canonical = cursor.fetchall()
                cursor.execute(
                    f"""SELECT v.id, v.kanonicna_id, c.naziv, v.izvirni_zapis,
                               v.iskalni_niz, v.stopnja_zaupanja
                        FROM `{VARIANT_TABLE}` v
                        JOIN `{CANONICAL_TABLE}` c ON c.id=v.kanonicna_id
                        WHERE c.tip=%s
                        ORDER BY c.naziv, v.izvirni_zapis""",
                    (dict_type,),
                )
                variants = cursor.fetchall()
        return canonical, variants

    def export_json_dictionary(self, filepath, dict_type):
        canonical, variants = self.get_dictionary_export_data(dict_type)
        canonical_items = [
            {"canonical_name_id": row[0], "name": row[1], "gender_type": row[2] or "", "notes": row[3] or ""}
            for row in canonical
        ]
        variant_items = [
            {"variant_id": row[0], "written_form": row[3], "normalized_form": row[4] or row[3]}
            for row in variants
        ]
        mappings = [
            {"canonical_name_id": row[1], "variant_id": row[0], "confidence": row[5] or "high"}
            for row in variants
        ]
        payload = {
            "schema_version": "2.0",
            "dictionary_type": dict_type,
            "tables": {
                "canonical_names": canonical_items,
                "variants": variant_items,
                "variant_mappings": mappings,
            },
        }
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        return len(canonical), len(variants)

    def import_json_dictionary(self, filepath, dict_type):
        self._ensure_initialized()
        self._validate_type(dict_type)
        try:
            with open(filepath, "r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            if isinstance(data, dict) and data.get("schema_version") == "2.0":
                tables = data.get("tables") or {}
                canonical_rows = tables.get("canonical_names") or []
                variant_rows = tables.get("variants") or []
                mappings = tables.get("variant_mappings") or []
                variant_by_id = {str(item.get("variant_id")): item for item in variant_rows}
                old_to_new = {}
                with closing(self.get_connection()) as conn:
                    with conn.cursor() as cursor:
                        for item in canonical_rows:
                            name = str(item.get("name", "")).strip()
                            if not name:
                                continue
                            cursor.execute(
                                f"INSERT INTO `{CANONICAL_TABLE}` (tip, naziv, spol_tip, opombe) VALUES (%s, %s, %s, %s) "
                                "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id), "
                                "spol_tip=IF(VALUES(spol_tip)<>'', VALUES(spol_tip), spol_tip), "
                                "opombe=IF(VALUES(opombe)<>'', VALUES(opombe), opombe)",
                                (dict_type, name, str(item.get("gender_type", item.get("spol_tip", ""))), str(item.get("notes", ""))),
                            )
                            old_to_new[str(item.get("canonical_name_id"))] = cursor.lastrowid
                        count_variants = 0
                        for mapping in mappings:
                            new_entity = old_to_new.get(str(mapping.get("canonical_name_id")))
                            variant = variant_by_id.get(str(mapping.get("variant_id")))
                            if not new_entity or not variant:
                                continue
                            written = str(variant.get("written_form", "")).strip()
                            if not written:
                                continue
                            cursor.execute(
                                f"INSERT IGNORE INTO `{VARIANT_TABLE}` "
                                "(kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja) VALUES (%s, %s, %s, %s)",
                                (new_entity, written, variant.get("normalized_form") or written.casefold(), mapping.get("confidence") or "high"),
                            )
                            count_variants += max(cursor.rowcount, 0)
                    conn.commit()
                return True, f"Uvoz JSON: {len(old_to_new)} kanoničnih oblik in {count_variants} variacij."

            if not isinstance(data, list):
                raise ValueError("JSON mora biti seznam ali relacijska struktura 2.0.")
            count_canonical = 0
            count_variants = 0
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    for item in data:
                        if not isinstance(item, dict):
                            continue
                        name = str(item.get("kanonicna_oblika", "")).strip()
                        if not name:
                            continue
                        cursor.execute(
                            f"INSERT INTO `{CANONICAL_TABLE}` (tip, naziv, spol_tip, opombe) VALUES (%s, %s, %s, %s) "
                            "ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)",
                            (dict_type, name, item.get("spol_tip", ""), item.get("opombe", "")),
                        )
                        entity_id = cursor.lastrowid
                        count_canonical += max(cursor.rowcount, 0)
                        for variant in item.get("variacije", []) or []:
                            if not isinstance(variant, dict):
                                continue
                            written = str(variant.get("izvirni_zapis", "")).strip()
                            if not written:
                                continue
                            cursor.execute(
                                f"INSERT IGNORE INTO `{VARIANT_TABLE}` "
                                "(kanonicna_id, izvirni_zapis, iskalni_niz, stopnja_zaupanja) VALUES (%s, %s, %s, %s)",
                                (entity_id, written, variant.get("iskalni_niz") or written.casefold(), variant.get("zaupanje") or "high"),
                            )
                            count_variants += max(cursor.rowcount, 0)
                conn.commit()
            return True, f"Uvoz JSON: {count_canonical} kanoničnih oblik in {count_variants} variacij."
        except Exception as exc:
            return False, str(exc)

    def close(self):
        """Povezave se odpirajo po posameznih operacijah; resetira stanje ob zapiranju."""
        self.initialized = False
        return None

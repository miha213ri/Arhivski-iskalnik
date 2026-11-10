"""Dostop do glavne MySQL-baze matičnih knjig."""

from contextlib import closing
try:
    import pymysql
except ImportError:  # Aplikacijo lahko odpremo tudi pred namestitvijo gonilnika.
    pymysql = None


TABLES = {"krsti", "poroke", "mrtvi"}


class GlavnaBaza:
    def __init__(self, db_config):
        self.config = dict(db_config or {})

    def get_connection(self):
        if pymysql is None:
            raise RuntimeError(
                "Manjka paket PyMySQL. Namesti ga z ukazom: "
                "python -m pip install PyMySQL"
            )
        return pymysql.connect(
            host=self.config.get("host", "localhost"),
            user=self.config.get("user", "root"),
            password=self.config.get("password", ""),
            database=self.config.get("database", "maticne_knjige_db"),
            port=int(self.config.get("port", 3306)),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=8,
            read_timeout=30,
            write_timeout=30,
            autocommit=False,
        )

    def preveri_in_ustvari_tabele(self):
        """Ustvari tabelo povezav, če še ne obstaja; napake vrne klicatelju."""
        try:
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """CREATE TABLE IF NOT EXISTS zgrajene_osebe (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            krst_id INT DEFAULT NULL,
                            poroka_id INT DEFAULT NULL,
                            smrt_id INT DEFAULT NULL,
                            opombe TEXT,
                            ustvarjeno TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_zgrajene_krst (krst_id),
                            INDEX idx_zgrajene_poroka (poroka_id),
                            INDEX idx_zgrajene_smrt (smrt_id)
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"""
                    )
                conn.commit()
            return True, "Tabela zgrajene_osebe je pripravljena."
        except Exception as exc:
            return False, str(exc)

    def shrani_zgrajeno_osebo(self, krst_id, poroka_id, smrt_id, opombe):
        """Shrani povezave do izbranih zapisov. Vse ID-je pretvori v cela števila."""
        if not any((krst_id, poroka_id, smrt_id)):
            return False, "Izbran ni noben zapis."
        try:
            def as_id(value):
                return int(value) if value not in (None, "") else None

            ids = (as_id(krst_id), as_id(poroka_id), as_id(smrt_id))
            ok, msg = self.preveri_in_ustvari_tabele()
            if not ok:
                return False, msg

            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO zgrajene_osebe (krst_id, poroka_id, smrt_id, opombe)
                           VALUES (%s, %s, %s, %s)""",
                        (*ids, str(opombe or "").strip()),
                    )
                conn.commit()
            return True, "Zgrajena oseba je uspešno shranjena v bazo."
        except (TypeError, ValueError) as exc:
            return False, f"Neveljaven ID zapisa: {exc}"
        except Exception as exc:
            return False, str(exc)

    def razdruzi_osebo(self, oseba_id):
        """Odstrani samo povezovalni zapis; izvornih krstnih/poročnih/mrliških zapisov ne briše."""
        try:
            oseba_id = int(oseba_id)
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("DELETE FROM zgrajene_osebe WHERE id = %s", (oseba_id,))
                    removed = cursor.rowcount > 0
                conn.commit()
            if removed:
                return True, "Povezava zgrajene osebe je odstranjena. Izvorni zapisi so ostali nespremenjeni."
            return False, "Zgrajena oseba ne obstaja več."
        except (TypeError, ValueError) as exc:
            return False, f"Neveljaven ID zgrajene osebe: {exc}"
        except Exception as exc:
            return False, str(exc)

    def get_zgrajene_osebe(self):
        """Pridobi povezane zapise z osnovnimi podatki iz vseh treh knjig."""
        ok, msg = self.preveri_in_ustvari_tabele()
        if not ok:
            return False, msg
        try:
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT z.id, z.opombe, z.ustvarjeno,
                                  k.ime_otroka, k.priimek_oceta, k.datum_rojstva,
                                  p.ime_zenina, p.priimek_zenina,
                                  p.ime_neveste, p.priimek_neveste, p.datum_poroke,
                                  m.ime_pokojnika, m.priimek_pokojnika, m.datum_smrti
                           FROM zgrajene_osebe z
                           LEFT JOIN krsti k ON z.krst_id = k.id
                           LEFT JOIN poroke p ON z.poroka_id = p.id
                           LEFT JOIN mrtvi m ON z.smrt_id = m.id
                           ORDER BY z.id DESC"""
                    )
                    return True, cursor.fetchall()
        except Exception as exc:
            return False, str(exc)

    def get_zgrajena_oseba_podrobnosti(self, oseba_id):
        """Vrne celoten zapis zgrajene osebe in vse povezane izvorne zapise."""
        try:
            oseba_id = int(oseba_id)
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM zgrajene_osebe WHERE id = %s",
                        (oseba_id,),
                    )
                    oseba = cursor.fetchone()
                    if not oseba:
                        return False, "Zgrajena oseba ne obstaja več."

                    rezultat = {"oseba": oseba, "krsti": None, "poroke": None, "mrtvi": None}
                    for tabela, fk in (
                        ("krsti", "krst_id"),
                        ("poroke", "poroka_id"),
                        ("mrtvi", "smrt_id"),
                    ):
                        record_id = oseba.get(fk)
                        if record_id is not None:
                            cursor.execute(
                                f"SELECT * FROM `{tabela}` WHERE id = %s",
                                (record_id,),
                            )
                            rezultat[tabela] = cursor.fetchone()
                    return True, rezultat
        except (TypeError, ValueError) as exc:
            return False, f"Neveljaven ID zgrajene osebe: {exc}"
        except Exception as exc:
            return False, str(exc)

    def _map_field(self, polje, tabela):
        """Preslika izbiro iz uporabniškega vmesnika v dovoljeno SQL-polje."""
        if tabela not in TABLES:
            return None

        common = {
            "Župnija": "zupnija",
            "Knjiga": "knjiga",
            "Opombe": "opombe",
            "Surovi tekst": "surovi_tekst",
        }
        if polje in common:
            return common[polje]

        if polje == "Kraj/Naslov":
            return {
                "krsti": "naslov",
                "poroke": "CONCAT(IFNULL(naslov_zenina, ''), ' ', IFNULL(naslov_neveste, ''))",
                "mrtvi": "naslov",
            }[tabela]

        if polje == "Letnica":
            return {
                "krsti": "CONCAT(IFNULL(datum_rojstva, ''), ' ', IFNULL(datum_krsta, ''))",
                "poroke": "datum_poroke",
                "mrtvi": "CONCAT(IFNULL(datum_smrti, ''), ' ', IFNULL(datum_pokopa, ''))",
            }[tabela]

        allowed_columns = {
            "krsti": {
                "ime_otroka", "ime_oceta", "priimek_oceta", "alt_priimek_oceta",
                "ime_matere", "priimek_matere", "alt_priimek_matere", "poklic_oceta",
                "izvor_oceta", "botri", "babica", "duhovnik", "vpis_st_knjige",
            },
            "poroke": {
                "ime_zenina", "priimek_zenina", "ime_neveste", "priimek_neveste",
                "stan_zenina", "stan_neveste", "price", "duhovnik", "vpis_st_knjige",
            },
            "mrtvi": {
                "ime_pokojnika", "priimek_pokojnika", "vzrok_smrti", "zakonec_starsi",
                "stan_pokojnika", "duhovnik", "starost", "vpis_st_knjige",
            },
        }
        return polje if polje in allowed_columns[tabela] else None

    @staticmethod
    def _like_group(fields, values):
        """Vrne OR-skupino LIKE pogojev in pripadajoče parametre."""
        expressions = []
        params = []
        for value in values:
            expressions.append("(" + " OR ".join(f"{field} LIKE %s" for field in fields) + ")")
            params.extend([f"%{value}%"] * len(fields))
        return "(" + " OR ".join(expressions) + ")", params

    def _build_where(self, tabela, imena_variacije, priimki_variacije, letnica, napredni_pogoji):
        """Sestavi pravilno oklepajene pogoje; ne uporablja nevarnega '1=1 OR ...'."""
        basic = []

        # Osnovno polje "Ime" pri krstih pomeni izključno ime otroka.
        # Imena staršev so ločena polja v naprednem iskanju; če bi jih
        # vključili tukaj, bi iskanje npr. "Marija" vračalo otroke, katerih
        # mati se imenuje Marija, čeprav se otrok imenuje drugače.
        name_fields = {
            "krsti": ["ime_otroka"],
            "poroke": ["ime_zenina", "ime_neveste"],
            "mrtvi": ["ime_pokojnika"],
        }[tabela]
        surname_fields = {
            "krsti": ["priimek_oceta", "alt_priimek_oceta", "priimek_matere", "alt_priimek_matere"],
            "poroke": ["priimek_zenina", "priimek_neveste"],
            "mrtvi": ["priimek_pokojnika"],
        }[tabela]

        if imena_variacije:
            expr, params = self._like_group(name_fields, imena_variacije)
            basic.append((expr, params))
        if priimki_variacije:
            expr, params = self._like_group(surname_fields, priimki_variacije)
            basic.append((expr, params))
        if letnica:
            year_fields = {
                "krsti": ["datum_rojstva", "datum_krsta"],
                "poroke": ["datum_poroke"],
                "mrtvi": ["datum_smrti", "datum_pokopa"],
            }[tabela]
            year_expr = "(" + " OR ".join(f"{field} LIKE %s" for field in year_fields) + ")"
            basic.append((year_expr, [f"%{letnica}%"] * len(year_fields)))

        clauses = []
        for expression, params in basic:
            clauses.append(("AND", expression, params))

        for condition in napredni_pogoji or []:
            if not isinstance(condition, dict):
                continue
            target = condition.get("knjiga")
            if target not in ("VSE", tabela.upper()):
                continue
            column = self._map_field(condition.get("polje"), tabela)
            value = str(condition.get("vrednost", "")).strip()
            if not column or not value:
                continue

            logic = condition.get("logika", "AND")
            connector = "OR" if logic == "OR" else "AND"
            if logic == "AND NOT":
                expression = f"NOT ({column} LIKE %s)"
            elif logic in ("AND", "OR"):
                expression = f"{column} LIKE %s"
            else:
                # Neznana vrednost iz stare/neveljavne nastavitve ne sme vplivati na SQL.
                connector = "AND"
                expression = f"{column} LIKE %s"
            clauses.append((connector, expression, [f"%{value}%"]))

        if not clauses:
            # Če je uporabnik določil pogoje za drugo knjigo, naj preostali
            # zavihki ne pokažejo vseh zapisov. Brez kakršnegakoli pogoja
            # pa je ohranjeno vedenje prikaza vseh zapisov.
            if napredni_pogoji:
                return "0=1", []
            return "1=1", []

        where_sql = ""
        parameters = []
        for index, (connector, expression, params) in enumerate(clauses):
            if index == 0:
                where_sql = f"({expression})"
            else:
                where_sql = f"({where_sql} {connector} ({expression}))"
            parameters.extend(params)
        return where_sql, parameters

    def get_statistika(self):
        ok, msg = self.preveri_in_ustvari_tabele()
        if not ok:
            return False, msg
        try:
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    stats = {}
                    for table in ("krsti", "poroke", "mrtvi", "zgrajene_osebe"):
                        cursor.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
                        stats[table] = cursor.fetchone()["cnt"]

                    cursor.execute(
                        """SELECT COUNT(DISTINCT z) AS cnt FROM (
                               SELECT zupnija AS z FROM krsti WHERE zupnija IS NOT NULL AND zupnija <> ''
                               UNION
                               SELECT zupnija AS z FROM poroke WHERE zupnija IS NOT NULL AND zupnija <> ''
                               UNION
                               SELECT zupnija AS z FROM mrtvi WHERE zupnija IS NOT NULL AND zupnija <> ''
                           ) AS vse_zupnije"""
                    )
                    stats["zupnije"] = cursor.fetchone()["cnt"]
                    return True, stats
        except Exception as exc:
            return False, str(exc)


    def get_zupnije(self):
        """Vrne seznam župnij, ki se pojavljajo v katerikoli matični knjigi."""
        try:
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """SELECT zupnija FROM (
                               SELECT TRIM(zupnija) AS zupnija FROM krsti
                               UNION
                               SELECT TRIM(zupnija) AS zupnija FROM poroke
                               UNION
                               SELECT TRIM(zupnija) AS zupnija FROM mrtvi
                           ) AS vse
                           WHERE zupnija IS NOT NULL AND zupnija <> ''
                           ORDER BY zupnija"""
                    )
                    return True, [row["zupnija"] for row in cursor.fetchall()]
        except Exception as exc:
            return False, str(exc)

    def get_podatke_za_mozne_zdruzitve(self, zupnija):
        """Vrne samo polja, potrebna za primerjavo treh knjig v eni župniji."""
        if not str(zupnija or "").strip():
            return False, "Najprej izberi župnijo."

        select_by_table = {
            "mrtvi": """SELECT id, zupnija, knjiga, slika, vpis_st_knjige,
                                  datum_smrti, datum_pokopa, ime_pokojnika,
                                  priimek_pokojnika, starost, zakonec_starsi,
                                  naslov, opombe
                           FROM mrtvi WHERE TRIM(zupnija)=%s ORDER BY id""",
            "poroke": """SELECT id, zupnija, knjiga, slika, vpis_st_knjige,
                                   datum_poroke, ime_zenina, priimek_zenina,
                                   starost_zenina, ime_neveste, priimek_neveste,
                                   starost_neveste, naslov_zenina, naslov_neveste,
                                   opombe
                            FROM poroke WHERE TRIM(zupnija)=%s ORDER BY id""",
            "krsti": """SELECT id, zupnija, knjiga, slika, vpis_st_knjige,
                                  datum_rojstva, datum_krsta, ime_otroka,
                                  ime_oceta, priimek_oceta, alt_priimek_oceta,
                                  ime_matere, priimek_matere, alt_priimek_matere,
                                  naslov, opombe
                           FROM krsti WHERE TRIM(zupnija)=%s ORDER BY id""",
        }
        try:
            records = {}
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    for table, sql in select_by_table.items():
                        cursor.execute(sql, (str(zupnija).strip(),))
                        records[table] = cursor.fetchall()
            return True, records
        except Exception as exc:
            return False, str(exc)

    def get_podrobnosti(self, tabela, record_id):
        if tabela not in TABLES:
            return False, "Neveljavno ime tabele."
        try:
            record_id = int(record_id)
            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(f"SELECT * FROM `{tabela}` WHERE id = %s", (record_id,))
                    return True, cursor.fetchone()
        except (TypeError, ValueError) as exc:
            return False, f"Neveljaven ID zapisa: {exc}"
        except Exception as exc:
            return False, str(exc)

    def pametno_iskanje(
        self,
        imena_variacije,
        priimki_variacije,
        letnica,
        napredni_pogoji=None,
        limit=100,
        offset=0,
    ):
        """Išče po vseh treh knjigah in vrne rezultate ter skupno število zadetkov."""
        try:
            limit = max(1, min(int(limit), 500))
            if isinstance(offset, dict):
                offsets = {table: max(0, int(offset.get(table, 0))) for table in ("krsti", "poroke", "mrtvi")}
            else:
                shared_offset = max(0, int(offset))
                offsets = {table: shared_offset for table in ("krsti", "poroke", "mrtvi")}
            imena_variacije = [str(v).strip() for v in (imena_variacije or []) if str(v).strip()]
            priimki_variacije = [str(v).strip() for v in (priimki_variacije or []) if str(v).strip()]
            letnica = str(letnica or "").strip()

            with closing(self.get_connection()) as conn:
                with conn.cursor() as cursor:
                    results = {}
                    select_sql = {
                        "krsti": """SELECT id, vpis_st_knjige AS idx, datum_rojstva AS datum,
                                          ime_otroka AS ime, priimek_oceta AS priimek,
                                          ime_oceta AS oce, ime_matere AS mati_ime,
                                          priimek_matere AS mati_priimek, naslov, opombe,
                                          CONCAT(IFNULL(zupnija, ''), ' | Knj: ', IFNULL(knjiga, ''),
                                                 ' | Sl: ', IFNULL(slika, '')) AS vir
                                   FROM krsti""",
                        "poroke": """SELECT id, vpis_st_knjige AS idx, datum_poroke AS datum,
                                           ime_zenina, priimek_zenina, starost_zenina AS starost_z,
                                           ime_neveste, priimek_neveste, starost_neveste AS starost_n,
                                           opombe,
                                           CONCAT(IFNULL(zupnija, ''), ' | Knj: ', IFNULL(knjiga, ''),
                                                  ' | Sl: ', IFNULL(slika, '')) AS vir
                                    FROM poroke""",
                        "mrtvi": """SELECT id, vpis_st_knjige AS idx, datum_smrti,
                                          ime_pokojnika, priimek_pokojnika, starost,
                                          zakonec_starsi, vzrok_smrti, naslov, opombe,
                                          CONCAT(IFNULL(zupnija, ''), ' | Knj: ', IFNULL(knjiga, ''),
                                                 ' | Sl: ', IFNULL(slika, '')) AS vir
                                   FROM mrtvi""",
                    }

                    for table in ("krsti", "poroke", "mrtvi"):
                        where_sql, params = self._build_where(
                            table,
                            imena_variacije,
                            priimki_variacije,
                            letnica,
                            napredni_pogoji,
                        )
                        cursor.execute(
                            f"{select_sql[table]} WHERE {where_sql} ORDER BY id DESC LIMIT %s OFFSET %s",
                            tuple(params + [limit, offsets[table]]),
                        )
                        rows = cursor.fetchall()
                        cursor.execute(
                            f"SELECT COUNT(*) AS total FROM `{table}` WHERE {where_sql}",
                            tuple(params),
                        )
                        total = cursor.fetchone()["total"]
                        results[table] = {"data": rows, "total": total}

                    return True, results
        except Exception as exc:
            return False, str(exc)

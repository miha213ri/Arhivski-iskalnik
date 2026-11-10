"""Excel izvoz rezultatov iskanja; iz MySQL prebere vse strani aktivnega filtra."""

import tkinter as tk
from tkinter import filedialog, messagebox

from .glavna_baza import GlavnaBaza
from .izvoz_excel import write_workbook


EXPORT_COLUMNS = {
    "krsti": (
        ("id", "ID"), ("idx", "Vpisna številka"), ("datum", "Datum"),
        ("ime", "Ime otroka"), ("priimek", "Priimek"), ("oce", "Ime očeta"),
        ("mati_ime", "Ime matere"), ("mati_priimek", "Priimek matere"),
        ("naslov", "Naslov"), ("opombe", "Opombe"), ("vir", "Arhivski vir"),
    ),
    "poroke": (
        ("id", "ID"), ("idx", "Vpisna številka"), ("datum", "Datum poroke"),
        ("ime_zenina", "Ime ženina"), ("priimek_zenina", "Priimek ženina"),
        ("starost_z", "Starost ženina"), ("ime_neveste", "Ime neveste"),
        ("priimek_neveste", "Priimek neveste"), ("starost_n", "Starost neveste"),
        ("opombe", "Opombe"), ("vir", "Arhivski vir"),
    ),
    "mrtvi": (
        ("id", "ID"), ("idx", "Vpisna številka"), ("datum_smrti", "Datum smrti"),
        ("ime_pokojnika", "Ime pokojnika"), ("priimek_pokojnika", "Priimek pokojnika"),
        ("starost", "Starost"), ("zakonec_starsi", "Zakonec / starši"),
        ("vzrok_smrti", "Vzrok smrti"), ("naslov", "Naslov"),
        ("opombe", "Opombe"), ("vir", "Arhivski vir"),
    ),
}


class IskalnikIzvozMixin:
    def izvozi_vse_knjige_excel(self):
        """Izvozi vse zadetke vseh treh knjig za trenutno izvedene iskalne pogoje."""
        if not self._require_connection():
            return
        if not self.zadnji_pogoji:
            messagebox.showwarning("Ni rezultatov", "Najprej izvedi iskanje.", parent=self.frame)
            return

        totals = dict(self.page_totals)
        if not any(totals.values()):
            messagebox.showinfo("Ni zadetkov", "Trenutni iskalni pogoji nimajo zadetkov za izvoz.", parent=self.frame)
            return

        filepath = filedialog.asksaveasfilename(
            parent=self.frame,
            title="Izvozi vse zadetke v Excel",
            defaultextension=".xlsx",
            initialfile="arhivski_iskalnik_rezultati.xlsx",
            filetypes=[("Excel datoteke", "*.xlsx")],
        )
        if not filepath:
            return

        all_rows = {table: [] for table in ("krsti", "poroke", "mrtvi")}
        offsets = {table: 0 for table in all_rows}
        batch_size = 500
        baza = GlavnaBaza(self.settings.get("LiveDB", {}))

        try:
            while any(offsets[table] < totals[table] for table in all_rows):
                success, result = baza.pametno_iskanje(
                    self.zadnji_pogoji.get("imena", []),
                    self.zadnji_pogoji.get("priimki", []),
                    self.zadnji_pogoji.get("letnica", ""),
                    napredni_pogoji=self.zadnji_pogoji.get("napredno", []),
                    limit=batch_size,
                    offset=offsets,
                )
                if not success:
                    raise RuntimeError(str(result))

                for table in all_rows:
                    page = result.get(table, {}).get("data", [])
                    all_rows[table].extend(page)
                    if offsets[table] < totals[table]:
                        offsets[table] += batch_size

            sheets = []
            for table, title in (("krsti", "Krstne knjige"), ("poroke", "Poročne knjige"), ("mrtvi", "Mrliške knjige")):
                columns = EXPORT_COLUMNS[table]
                headers = [label for _key, label in columns]
                rows = ([row.get(key) for key, _label in columns] for row in all_rows[table])
                sheets.append((title, headers, rows))

            write_workbook(filepath, sheets)
            count_text = "\n".join(
                f"{title}: {len(all_rows[table]):,}".replace(",", ".")
                for table, title in (("krsti", "Krstni zapisi"), ("poroke", "Poročni zapisi"), ("mrtvi", "Mrliški zapisi"))
            )
            messagebox.showinfo(
                "Izvoz zaključen",
                f"Izvoženi so vsi zadetki trenutnega iskanja:\n{count_text}\n\nDatoteka: {filepath}",
                parent=self.frame,
            )
        except Exception as exc:
            messagebox.showerror("Napaka pri izvozu", str(exc), parent=self.frame)

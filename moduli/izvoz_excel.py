"""Skupne funkcije za izvoz podatkov v .xlsx."""

from datetime import date, datetime


def _safe_cell(value):
    """Ohrani izvorno besedilo in prepreči, da bi ga Excel razlagal kot formulo."""
    if value is None:
        return ""
    if isinstance(value, (date, datetime, int, float, bool)):
        return value
    text = str(value)
    if text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def write_workbook(filepath, sheets):
    """Zapiše enega ali več listov; sheets: [(ime, glave, vrstice), ...]."""
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter
    except ImportError as exc:
        raise RuntimeError(
            "Za izvoz v Excel manjka openpyxl. Namesti ga z: "
            "python -m pip install openpyxl"
        ) from exc

    workbook = Workbook(write_only=False)
    default_sheet = workbook.active
    workbook.remove(default_sheet)

    for sheet_name, headers, rows in sheets:
        worksheet = workbook.create_sheet(str(sheet_name)[:31])
        worksheet.freeze_panes = "A2"
        worksheet.auto_filter.ref = "A1:A1"
        worksheet.append([_safe_cell(value) for value in headers])
        for cell in worksheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="24476B")
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        worksheet.row_dimensions[1].height = 28

        widths = [min(max(len(str(value or "")) + 2, 12), 45) for value in headers]
        count = 0
        for row in rows:
            if count >= 1_048_575:
                raise ValueError(
                    f"List '{sheet_name}' presega omejitev Excela 1.048.576 vrstic. "
                    "Razdeli izvoz na več datotek ali oži iskalne pogoje."
                )
            worksheet.append([_safe_cell(value) for value in row])
            count += 1
            for index, value in enumerate(row):
                if index < len(widths):
                    widths[index] = min(max(widths[index], min(len(str(value or "")) + 2, 45)), 45)
        if headers:
            worksheet.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, count + 1)}"
        for index, width in enumerate(widths, start=1):
            worksheet.column_dimensions[get_column_letter(index)].width = width

    if not workbook.sheetnames:
        workbook.create_sheet("Podatki")
    workbook.save(filepath)
    return filepath

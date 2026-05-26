from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape


CellValue = str | int | float | None


@dataclass(frozen=True)
class Worksheet:
    name: str
    rows: list[list[CellValue]]
    widths: list[float]
    freeze_top_row: bool = True
    auto_filter: bool = True


def column_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def cell_ref(row_index: int, column_index: int) -> str:
    return f"{column_name(column_index)}{row_index}"


def safe_sheet_name(name: str, existing: set[str]) -> str:
    cleaned = re.sub(r"[\[\]:*?/\\]", " ", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    suffix = 1
    while candidate in existing:
        marker = f" {suffix}"
        candidate = f"{cleaned[:31 - len(marker)]}{marker}"
        suffix += 1
    existing.add(candidate)
    return candidate


def is_number(value: CellValue) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def style_index(row_index: int, value: CellValue) -> int:
    if row_index == 1:
        return 1
    if is_number(value):
        return 2
    return 0


def worksheet_xml(sheet: Worksheet) -> str:
    max_columns = max((len(row) for row in sheet.rows), default=1)
    max_rows = max(len(sheet.rows), 1)
    dimension = f"A1:{cell_ref(max_rows, max_columns)}"
    col_xml = []
    for index in range(1, max_columns + 1):
        width = sheet.widths[index - 1] if index <= len(sheet.widths) else 16
        col_xml.append(f'<col min="{index}" max="{index}" width="{width:.1f}" customWidth="1"/>')

    pane_xml = ""
    if sheet.freeze_top_row:
        pane_xml = (
            '<sheetViews><sheetView workbookViewId="0">'
            '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
            "</sheetView></sheetViews>"
        )
    else:
        pane_xml = '<sheetViews><sheetView workbookViewId="0"/></sheetViews>'

    rows_xml = []
    for row_index, row in enumerate(sheet.rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            ref = cell_ref(row_index, column_index)
            style = style_index(row_index, value)
            style_attr = f' s="{style}"' if style else ""
            if value is None or value == "":
                cells.append(f'<c r="{ref}"{style_attr}/>')
            elif is_number(value):
                cells.append(f'<c r="{ref}"{style_attr}><v>{value}</v></c>')
            else:
                text = escape(str(value), {'"': "&quot;"})
                cells.append(f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>')
        rows_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    auto_filter_xml = f'<autoFilter ref="{dimension}"/>' if sheet.auto_filter and sheet.rows else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<dimension ref=\"{dimension}\"/>"
        f"{pane_xml}"
        f"<cols>{''.join(col_xml)}</cols>"
        f"<sheetData>{''.join(rows_xml)}</sheetData>"
        f"{auto_filter_xml}"
        "</worksheet>"
    )


def workbook_xml(sheets: list[Worksheet]) -> str:
    sheet_entries = []
    for index, sheet in enumerate(sheets, start=1):
        sheet_entries.append(
            f'<sheet name="{escape(sheet.name)}" sheetId="{index}" r:id="rId{index}"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(sheet_entries)}</sheets>"
        "</workbook>"
    )


def workbook_rels_xml(sheets: list[Worksheet]) -> str:
    rels = []
    for index in range(1, len(sheets) + 1):
        rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
    rels.append(
        f'<Relationship Id="rId{len(sheets) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rels)}"
        "</Relationships>"
    )


def root_rels_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def content_types_xml(sheets: list[Worksheet]) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for index in range(1, len(sheets) + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f"{''.join(overrides)}"
        "</Types>"
    )


def styles_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Calibri"/></font>'
        '</fonts>'
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF404040"/><bgColor indexed="64"/></patternFill></fill>'
        '</fills>'
        '<borders count="2">'
        '<border><left/><right/><top/><bottom/><diagonal/></border>'
        '<border><left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/><diagonal/></border>'
        '</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="3">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1"/>'
        '<xf numFmtId="3" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def write_xlsx(path: Path, worksheets: list[Worksheet]) -> None:
    existing: set[str] = set()
    safe_sheets = [
        Worksheet(
            name=safe_sheet_name(sheet.name, existing),
            rows=sheet.rows,
            widths=sheet.widths,
            freeze_top_row=sheet.freeze_top_row,
            auto_filter=sheet.auto_filter,
        )
        for sheet in worksheets
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(safe_sheets))
        archive.writestr("_rels/.rels", root_rels_xml())
        archive.writestr("xl/workbook.xml", workbook_xml(safe_sheets))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(safe_sheets))
        archive.writestr("xl/styles.xml", styles_xml())
        for index, sheet in enumerate(safe_sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", worksheet_xml(sheet))

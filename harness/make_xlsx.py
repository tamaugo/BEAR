#!/usr/bin/env python3
"""
Converts the pipeline's pipe-delimited text output into a .xlsx workbook.

Usage:
  python3 make_xlsx.py <input.txt> <output.xlsx>

--- Why this script exists ---

Agent 3 is an LLM. It can only write text. A .xlsx file is a binary ZIP of
XML documents, which no language model can emit reliably. So the split is:
Agent 3 writes a plain pipe-delimited text file, and this script turns that
file into a spreadsheet deterministically.

That split is deliberate and this script is deliberately dumb. It makes NO
judgement calls — it does not clean part names, infer missing prices, guess
at a URL, drop rows it dislikes, or reorder anything. Every transformation
rule in this pipeline lives in Agent 3's prompt, exactly one place. If you
find yourself wanting to add "smart" behaviour here, it belongs in Agent 3
instead.

--- Dependencies: none, and that is the point ---

Standard library only. No pip install, no venv, no requirements file.

This matters because the machine this pipeline runs on has Homebrew's
Python, which is PEP 668 "externally managed": `pip3 install openpyxl`
refuses outright. Every workaround — a venv, --break-system-packages,
pipx — adds a moving part that has to be activated from the BEAR launcher
and recreated by hand on any new machine, for a tool one person maintains
alone. So this script writes the .xlsx itself.

An .xlsx is just a ZIP archive of XML documents, and `zipfile` plus
careful string building covers everything this pipeline needs: a bold
frozen header, column widths, numeric prices, clickable URLs. The rest of
the harness already follows this rule — see ebay_browse_lookup.py.

--- Input format ---

One row per line, exactly 4 pipe-separated fields:

    part info | price | url | image

Real examples:

    MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Off Side Front Bumper Bracket \
GS1D500T1 | 44.99 | https://www.ebay.co.uk/itm/123456789 | img_2225_OSF.JPEG
    FAILED - Agent 2 - No eBay Listing Found | | | img_2240.JPEG

Failure rows have empty price and url fields but ALWAYS carry an image
field, so a failed part is still traceable back to its photograph.

Leading and trailing whitespace is stripped from every field. Completely
blank lines are skipped (they are spacing, not rows).

A line that does not have exactly 4 fields is NOT silently dropped. It is
written into the sheet with the whole raw line in the part info column and
a MALFORMED marker in front of it, and a warning is printed to stderr. A
bad row must be visible in the output, never lost.

--- Output format ---

Column A = part info    B = price    C = url    D = image

Header row is bold and frozen. Price is written as a real NUMBER wherever
the text parses as one, so the sheet can sum and sort it; anything that
does not parse (an empty failure-row price, a value with a currency symbol
or thousands separator) is left as text, unchanged and visible. URLs that
look like http(s) links are made clickable.
"""

import io
import os
import re
import sys
import zipfile

HEADERS = ["part info", "price", "url", "image"]
FIELD_COUNT = len(HEADERS)

# Column widths in Excel's own unit (roughly one character of the default
# font, plus padding). part info is long, url is medium, price and image
# are narrow. These are the same numbers the openpyxl version used, so the
# sheet looks identical to the one the pipeline produced before.
COLUMN_WIDTHS = [70, 10, 46, 22]

MALFORMED_PREFIX = "MALFORMED ROW"

SHEET_NAME = "Parts"

# Indices into the <cellXfs> list built by styles_xml(). A cell picks its
# formatting with s="<index>", so these two must stay in step.
STYLE_DEFAULT = 0
STYLE_BOLD = 1
STYLE_NUMBER = 2   # 0.00
STYLE_LINK = 3     # blue + underlined
STYLE_HINT = 4     # possible-match rows: italic grey on light yellow
STYLE_HINT_LINK = 5

# Rows whose part info starts with this are eBay image-search suggestions placed
# directly under the unpriced photo they belong to (BEAR 0.2). Not BEAR prices.
HINT_PREFIX = "\u21b3 POSSIBLE MATCH"

# XML namespaces. Spelled out once here rather than inline, because a typo
# in one of these produces a file that opens as empty rather than one that
# fails loudly.
NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL_DOC = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_REL_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"

XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'


# --------------------------------------------------------------------------
# Text hygiene
#
# Everything below assumes its input is safe to drop straight into XML.
# clean() guarantees that, and the escape helpers guarantee the rest. Both
# halves are needed: escaping does not save you from a 0x01 byte, because
# there is no escape sequence for a character XML simply forbids.
# --------------------------------------------------------------------------

# The control characters XML 1.0 does not allow at all: 0x00-0x08, 0x0B,
# 0x0C and 0x0E-0x1F. Tab (0x09), newline (0x0A) and carriage return
# (0x0D) are legal and are left alone. U+FFFE and U+FFFF are noncharacters
# and are also rejected by strict XML parsers, so they go too.
#
# This is the same set openpyxl removed before writing a cell. A stray
# control byte from a photo filename or a copy-pasted eBay title is the
# one thing that would otherwise abort a whole run, so it is stripped
# rather than allowed to fail the job.
ILLEGAL_CHARACTERS_RE = re.compile(r"[\000-\010\013\014\016-\037\uFFFE\uFFFF]")


def clean(text: str) -> str:
    """Strip surrounding whitespace and drop XLSX-illegal control
    characters. Nothing else about the text is touched — no case changes,
    no punctuation fixing, no truncation."""
    return ILLEGAL_CHARACTERS_RE.sub("", text).strip()


def escape_text(text: str) -> str:
    """Escape a string for use as XML element content.

    & must be replaced FIRST or it would double-escape the ampersands the
    later replacements introduce. eBay part titles contain & routinely
    ("B&Q", "Nuts & Bolts") and eBay URLs contain it in query strings, so
    getting this wrong corrupts real files, not hypothetical ones."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_attr(text: str) -> str:
    """Escape a string for use inside a double-quoted XML attribute.

    Same as escape_text plus the double quote, which would otherwise close
    the attribute early. Used for hyperlink targets and the sheet name."""
    return escape_text(text).replace('"', "&quot;")


# --------------------------------------------------------------------------
# Input parsing
# --------------------------------------------------------------------------

def parse_price(text: str):
    """Return a float when the price text is a plain number, otherwise the
    text unchanged.

    Intentionally strict: only what float() accepts is treated as a number.
    "44.99" becomes a number; "", "£44.99" and "1,299.00" stay as text and
    stay visible in the sheet. Guessing at currency symbols or separators
    would be a judgement call, and those do not belong in this script.

    The one extra rejection is non-finite values. float() happily accepts
    "nan", "inf" and "Infinity", but there is no way to write those into a
    spreadsheet cell — the file would be structurally corrupt. They are
    treated as unparseable and kept as text, which is both honest and
    visible."""
    try:
        value = float(text)
    except ValueError:
        return text
    if value != value or value in (float("inf"), float("-inf")):
        return text
    return value


def parse_line(raw: str):
    """Turn one input line into a (fields, malformed) pair.

    A well-formed line gives its 4 stripped fields and malformed=False. A
    line with any other number of fields gives the raw line, marked, in the
    part info column with the rest blank, and malformed=True — so it lands
    in the sheet where a human will see it."""
    fields = [clean(f) for f in raw.split("|")]
    if len(fields) == FIELD_COUNT:
        return fields, False

    marker = (
        f"{MALFORMED_PREFIX} (expected {FIELD_COUNT} fields, "
        f"got {len(fields)}): {clean(raw)}"
    )
    return [marker, "", "", ""], True


def read_rows(path: str):
    """Read the input file into a list of (line_number, fields, malformed)."""
    rows = []
    try:
        with open(path, encoding="utf-8") as f:
            for line_number, raw in enumerate(f, start=1):
                raw = raw.rstrip("\n").rstrip("\r")
                if not raw.strip():
                    continue
                fields, malformed = parse_line(raw)
                rows.append((line_number, fields, malformed))
    except UnicodeDecodeError as e:
        raise SystemExit(
            f"Could not read '{path}' as UTF-8 text: {e}\n"
            "The input must be the plain text file Agent 3 wrote. If this is "
            "already a .xlsx or another binary file, you have the arguments "
            "the wrong way round."
        )
    return rows


# --------------------------------------------------------------------------
# XLSX parts
#
# A .xlsx is a ZIP of XML documents wired together by "relationship" files.
# The minimum set that Excel, Numbers and LibreOffice all accept is:
#
#   [Content_Types].xml               declares the MIME type of every part
#   _rels/.rels                       package -> workbook
#   xl/workbook.xml                   the sheet list
#   xl/_rels/workbook.xml.rels        workbook -> sheet, workbook -> styles
#   xl/worksheets/sheet1.xml          the actual cells
#   xl/styles.xml                     fonts and number formats
#   xl/worksheets/_rels/sheet1.xml.rels   hyperlink targets (only if any)
#
# Strings are written INLINE (t="inlineStr") rather than through a shared
# strings table. A shared table is smaller for repetitive data, but it
# means maintaining an index that has to agree with every cell that points
# into it — a whole class of off-by-one corruption for no benefit at this
# scale, where a run is tens of rows.
# --------------------------------------------------------------------------

def content_types_xml() -> str:
    return (
        f"{XML_DECL}"
        f'<Types xmlns="{NS_CONTENT_TYPES}">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )


def package_rels_xml() -> str:
    return (
        f"{XML_DECL}"
        f'<Relationships xmlns="{NS_REL_PKG}">'
        f'<Relationship Id="rId1" Type="{NS_REL_DOC}/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def workbook_xml() -> str:
    return (
        f"{XML_DECL}"
        f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL_DOC}">'
        f'<sheets><sheet name="{escape_attr(SHEET_NAME)}" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )


def workbook_rels_xml() -> str:
    return (
        f"{XML_DECL}"
        f'<Relationships xmlns="{NS_REL_PKG}">'
        f'<Relationship Id="rId1" Type="{NS_REL_DOC}/worksheet" Target="worksheets/sheet1.xml"/>'
        f'<Relationship Id="rId2" Type="{NS_REL_DOC}/styles" Target="styles.xml"/>'
        "</Relationships>"
    )


def styles_xml() -> str:
    """Four cell formats, in the order the STYLE_* constants name them.

    Colours are given as explicit RGB rather than theme references, because
    a theme reference needs an xl/theme/theme1.xml part that this file
    deliberately does not ship. Two fills and one border are present
    because Excel expects those lists to exist and to start with the
    standard "none"/"gray125" pair, even when nothing uses them."""
    return (
        f"{XML_DECL}"
        f'<styleSheet xmlns="{NS_MAIN}">'
        '<numFmts count="1"><numFmt numFmtId="164" formatCode="0.00"/></numFmts>'
        '<fonts count="4">'
        '<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
        '<font><b/><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
        '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/><family val="2"/></font>'
        '<font><i/><sz val="11"/><color rgb="FF595959"/><name val="Calibri"/><family val="2"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill>'
        "</fills>"
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="6">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        '<xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        '<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def column_letter(index: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA. Only ever called with 1..4 here, but
    written generally so it cannot quietly break if a column is added."""
    letters = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def text_cell(ref: str, text: str, style: int = STYLE_DEFAULT) -> str:
    """An inline-string cell. xml:space="preserve" is always set so that
    internal runs of spaces survive a round trip through a parser that
    would otherwise be free to collapse them."""
    style_attr = f' s="{style}"' if style else ""
    return (
        f'<c r="{ref}"{style_attr} t="inlineStr">'
        f'<is><t xml:space="preserve">{escape_text(text)}</t></is></c>'
    )


def number_cell(ref: str, value: float, style: int = STYLE_NUMBER) -> str:
    """A real numeric cell: no t= attribute (the default cell type is
    numeric) and a bare <v>. repr() gives Python's shortest round-tripping
    form, so 44.99 is written as 44.99 rather than 44.990000000000002."""
    return f'<c r="{ref}" s="{style}"><v>{value!r}</v></c>'


def is_http_url(text: str) -> bool:
    return text.startswith("http://") or text.startswith("https://")


def build_sheet(rows: list):
    """Build sheet1.xml.

    Returns (sheet_xml, hyperlinks) where hyperlinks is a list of
    (cell_ref, relationship_id, target) that the caller turns into
    xl/worksheets/_rels/sheet1.xml.rels.

    Element order inside <worksheet> is fixed by the schema and Excel does
    enforce it: dimension, sheetViews, cols, sheetData, then hyperlinks.
    Moving <hyperlinks> above <sheetData> produces a file Excel refuses.
    """
    parts = [
        XML_DECL,
        f'<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL_DOC}">',
    ]

    last_row = len(rows) + 1  # +1 for the header
    parts.append(
        f'<dimension ref="A1:{column_letter(FIELD_COUNT)}{last_row}"/>'
    )

    # Freeze the header. ySplit="1" puts the split below row 1;
    # topLeftCell="A2" makes row 2 the first scrolling row.
    parts.append(
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/>'
        "</sheetView></sheetViews>"
    )

    # Column widths. customWidth="1" is what stops Excel from ignoring the
    # width and auto-sizing instead.
    parts.append("<cols>")
    for index, width in enumerate(COLUMN_WIDTHS, start=1):
        parts.append(
            f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        )
    parts.append("</cols>")

    parts.append("<sheetData>")

    parts.append('<row r="1">')
    for index, header in enumerate(HEADERS, start=1):
        parts.append(text_cell(f"{column_letter(index)}1", header, STYLE_BOLD))
    parts.append("</row>")

    hyperlinks = []

    for offset, (_line_number, fields, _malformed) in enumerate(rows):
        row_number = offset + 2
        part_info, price, url, image = fields

        parts.append(f'<row r="{row_number}">')

        if part_info.startswith(HINT_PREFIX):
            # Suggestion row: every cell shaded, price shown as text ("listed at"),
            # never as a BEAR sell price.
            parts.append(text_cell(f"A{row_number}", part_info, STYLE_HINT))
            parts.append(text_cell(f"B{row_number}", price, STYLE_HINT))
            if is_http_url(url):
                ref = f"C{row_number}"
                rel_id = f"rId{len(hyperlinks) + 1}"
                hyperlinks.append((ref, rel_id, url))
                parts.append(text_cell(ref, url, STYLE_HINT_LINK))
            else:
                parts.append(text_cell(f"C{row_number}", url, STYLE_HINT))
            parts.append(text_cell(f"D{row_number}", image, STYLE_HINT))
            parts.append("</row>")
            continue

        # Column A — part info, or the MALFORMED marker plus the raw line.
        if part_info:
            parts.append(text_cell(f"A{row_number}", part_info))

        # Column B — a number where float() accepts it, text otherwise.
        # Empty prices (failure rows) produce no cell at all, which is how
        # a spreadsheet spells "blank"; writing an empty string instead
        # would make the cell non-empty to COUNTA and friends.
        price_value = parse_price(price)
        if isinstance(price_value, float):
            parts.append(number_cell(f"B{row_number}", price_value))
        elif price_value:
            parts.append(text_cell(f"B{row_number}", price_value))

        # Column C — url, blue and underlined and clickable when it is one.
        if url:
            if is_http_url(url):
                ref = f"C{row_number}"
                rel_id = f"rId{len(hyperlinks) + 1}"
                hyperlinks.append((ref, rel_id, url))
                parts.append(text_cell(ref, url, STYLE_LINK))
            else:
                parts.append(text_cell(f"C{row_number}", url))

        # Column D — image filename.
        if image:
            parts.append(text_cell(f"D{row_number}", image))

        parts.append("</row>")

    parts.append("</sheetData>")

    if hyperlinks:
        parts.append("<hyperlinks>")
        for ref, rel_id, _target in hyperlinks:
            parts.append(f'<hyperlink ref="{ref}" r:id="{rel_id}"/>')
        parts.append("</hyperlinks>")

    parts.append("</worksheet>")
    return "".join(parts), hyperlinks


def sheet_rels_xml(hyperlinks: list) -> str:
    """One external relationship per hyperlink.

    This is the relationship form of hyperlink rather than a HYPERLINK()
    formula. A formula cell has to carry a cached result as well as the
    formula text, and a reader that does not recalculate on open shows a
    blank cell — a silently empty url column is exactly the failure this
    pipeline cannot afford. The relationship form stores the URL as data,
    displays the url text itself, and needs no recalculation.
    """
    parts = [XML_DECL, f'<Relationships xmlns="{NS_REL_PKG}">']
    for _ref, rel_id, target in hyperlinks:
        parts.append(
            f'<Relationship Id="{rel_id}" Type="{NS_REL_DOC}/hyperlink" '
            f'Target="{escape_attr(target)}" TargetMode="External"/>'
        )
    parts.append("</Relationships>")
    return "".join(parts)


def build_xlsx_bytes(rows: list) -> bytes:
    """Assemble the whole archive in memory.

    In memory rather than straight to disk so that a failure part-way
    through cannot leave a half-written .xlsx sitting where the pipeline
    expects a good one. The file on disk is written in a single call or
    not at all.

    [Content_Types].xml is written first: it is what a reader looks for to
    identify the package, and some are picky about finding it at the front
    of the archive rather than hunting the central directory for it.
    """
    sheet, hyperlinks = build_sheet(rows)

    members = [
        ("[Content_Types].xml", content_types_xml()),
        ("_rels/.rels", package_rels_xml()),
        ("xl/workbook.xml", workbook_xml()),
        ("xl/_rels/workbook.xml.rels", workbook_rels_xml()),
        ("xl/styles.xml", styles_xml()),
        ("xl/worksheets/sheet1.xml", sheet),
    ]
    if hyperlinks:
        members.append(
            ("xl/worksheets/_rels/sheet1.xml.rels", sheet_rels_xml(hyperlinks))
        )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, xml in members:
            archive.writestr(name, xml.encode("utf-8"))
    return buffer.getvalue()


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage:\n"
            "  python3 make_xlsx.py <input.txt> <output.xlsx>\n\n"
            "  <input.txt>   pipe-delimited text from Agent 3, one row per line:\n"
            "                  part info | price | url | image\n"
            "  <output.xlsx> spreadsheet to write (overwritten if it exists)"
        )

    input_path, output_path = sys.argv[1], sys.argv[2]

    if not os.path.exists(input_path):
        raise SystemExit(f"Input file not found: {input_path}")
    if not os.path.isfile(input_path):
        raise SystemExit(f"Input path is not a file: {input_path}")

    rows = read_rows(input_path)
    if not rows:
        raise SystemExit(
            f"Input file '{input_path}' contains no rows — nothing to convert."
        )

    malformed = [line_number for line_number, _fields, bad in rows if bad]
    for line_number in malformed:
        print(
            f"WARNING: line {line_number} does not have {FIELD_COUNT} fields. "
            f"Written to the sheet marked {MALFORMED_PREFIX}, not dropped.",
            file=sys.stderr,
        )

    data = build_xlsx_bytes(rows)
    try:
        with open(output_path, "wb") as f:
            f.write(data)
    except OSError as e:
        raise SystemExit(f"Could not write '{output_path}': {e}")

    print(
        f"Wrote {output_path} — {len(rows)} row(s)"
        + (f", {len(malformed)} malformed" if malformed else "")
    )


if __name__ == "__main__":
    main()

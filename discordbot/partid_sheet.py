"""The #part-id spreadsheet /sheet posts: one row per card, the first part at the top, the last at the bottom.

  date & time         when the photo was posted (UK time), a real date so it sorts
  the numbers         the card's answer (blank if there is none)
  who got the info    jev option 1/2/3 (nothing picked = jev option 1), or human (typed with ✏️)
  location            near side rear / near side front / off side rear / off side front, blank if none picked

Standard library only, like harness/make_xlsx.py: an .xlsx is a zip of XML files.
"""
import io, zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:   # no time zone data: the server's own time
    UK = None

HEADER = ("date & time", "the numbers", "who got the info", "location")
WIDTHS = (21, 40, 18, 18)


def who(card):
    if card.get("answer") is None:
        return ""
    if card.get("how") == "typed":
        return "human"
    return f"jev option {card.get('choice') or 1}"


def row(card):
    """(posted datetime in UK time, number, who, location) for one card."""
    when = datetime.fromtimestamp(card["posted"], timezone.utc).astimezone(UK).replace(tzinfo=None)
    return when, card.get("answer") or "", who(card), card.get("location") or ""


def xlsx(cards):
    """The .xlsx bytes for these cards, in the order given."""
    rows = [cell_row(1, HEADER, header=True)]
    rows += [cell_row(r, row(c)) for r, c in enumerate(cards, 2)]
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(WIDTHS, 1))
    sheet = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<worksheet xmlns="{NS}">'
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
             'state="frozen"/></sheetView></sheetViews>'
             f'<cols>{cols}</cols><sheetData>{"".join(rows)}</sheetData></worksheet>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", PACKAGE_RELS)
        z.writestr("xl/workbook.xml", WORKBOOK)
        z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        z.writestr("xl/styles.xml", STYLES)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def cell_row(r, values, header=False):
    cells = []
    for col, v in zip("ABCD", values):
        ref = f"{col}{r}"
        if isinstance(v, datetime):   # Excel's date number: days since 30/12/1899
            cells.append(f'<c r="{ref}" s="2"><v>{(v - datetime(1899, 12, 30)).total_seconds() / 86400:.8f}</v></c>')
        elif v:
            style = ' s="1"' if header else ""
            cells.append(f'<c r="{ref}"{style} t="inlineStr"><is><t xml:space="preserve">{text(v)}</t></is></c>')
    return f'<row r="{r}">{"".join(cells)}</row>'


def text(v):
    """Escaped for XML, without the control characters XML can't hold."""
    return escape("".join(ch for ch in str(v) if ch in "\t\n" or ord(ch) >= 32))


NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>')
PACKAGE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
WORKBOOK = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<workbook xmlns="{NS}" xmlns:r="{REL}">'
    '<sheets><sheet name="part-id" sheetId="1" r:id="rId1"/></sheets></workbook>')
WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    f'<Relationship Id="rId1" Type="{REL}/worksheet" Target="worksheets/sheet1.xml"/>'
    f'<Relationship Id="rId2" Type="{REL}/styles" Target="styles.xml"/></Relationships>')
# Styles: 0 plain, 1 bold (the header), 2 date & time
STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{NS}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy hh:mm:ss"/></numFmts>'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')

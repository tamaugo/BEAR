"""The #part-id spreadsheet /sheet posts: one row per card, the first part at the top, the last at the bottom.

  date & time         when the photo was posted (UK time), a real date so it sorts
  the numbers         the card's answer, or NO PART NUMBER (🚫 on the card, or Agent 1 found none)
  ebay ID Category:   the eBay category ID the number's listings are filed under (as in the main sheet),
                      blank if eBay has no listing with that number
  who got the info    jev option 1/2/3 (nothing picked = jev option 1), human (typed with ✏️ or marked 🚫),
                      or agent 1 (it found no number and nobody changed that)
  location            near side rear / near side front / off side rear / off side front, blank if none picked
  photo               the photo's name, a link to it in #part-id

A NO PART NUMBER part has up to 3 shaded rows directly under it: the eBay photo search's look-alike
listings for that same photo ("↳ POSSIBLE MATCH k (check by eye) - title - listed £x", each with its
own eBay category, the listing linked in the photo column), like the possible-match rows /run puts under an unpriced photo. Never a BEAR price.

Standard library only, like harness/make_xlsx.py: an .xlsx is a zip of XML files.
"""
import io, zipfile
from datetime import datetime, timezone
from typing import NamedTuple
from xml.sax.saxutils import escape

try:
    from zoneinfo import ZoneInfo
    UK = ZoneInfo("Europe/London")
except Exception:   # no time zone data: the server's own time
    UK = None

HEADER = ("date & time", "the numbers", "ebay ID Category:", "who got the info", "location", "photo")
WIDTHS = (21, 60, 18, 20, 18, 24)
NO_NUMBER = "NO PART NUMBER"
MATCH = "\u21b3 POSSIBLE MATCH"


class Link(NamedTuple):
    url: str
    text: str


def who(card):
    if card.get("how") == "none":
        return "human" if card.get("by") else "agent 1"
    if card.get("answer") is None:
        return ""
    if card.get("how") == "typed":
        return "human"
    return f"jev option {card.get('choice') or 1}"


def row(card):
    """(posted datetime in UK time, number, eBay category, who, location, photo link) for one card."""
    when = datetime.fromtimestamp(card["posted"], timezone.utc).astimezone(UK).replace(tzinfo=None)
    number = NO_NUMBER if card.get("how") == "none" else card.get("answer") or ""
    name = card.get("photo_name") or ""
    photo = Link(card["message"], name or "photo") if card.get("message") else name
    category = "" if card.get("how") == "none" else (card.get("categories") or {}).get(card.get("answer")) or ""
    return when, number, category, who(card), card.get("location") or "", photo


def match_rows(card):
    """The shaded look-alike rows under a NO PART NUMBER part: ("", text, category, who, "", listing link)."""
    if card.get("how") != "none":
        return []
    found = card.get("matches")
    if found is None:
        return [("", f"{MATCH} - eBay photo search failed, search the photo by hand", "", "", "", "")]
    if not found:
        return [("", f"{MATCH} - none found by eBay photo search", "", "", "", "")]
    return [("", f"{MATCH} {k} (check by eye) - {' '.join(str(m.get('title') or '').split())} - "
                 f"listed \u00a3{float(m.get('price') or 0):.2f}", m.get("category") or "", "eBay photo search", "",
             Link(m["url"], "eBay listing") if m.get("url") else "")
            for k, m in enumerate(found, 1)]


def xlsx(cards):
    """The .xlsx bytes for these cards, in the order given, each NO PART NUMBER part's look-alikes under it."""
    lines = []   # (values, shaded)
    for c in cards:
        lines += [(row(c), False), *[(m, True) for m in match_rows(c)]]
    rows = [cell_row(1, HEADER, header=True)]
    rows += [cell_row(r, values, shaded=shaded) for r, (values, shaded) in enumerate(lines, 2)]
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


def cell_row(r, values, header=False, shaded=False):
    cells = []
    for col, v in zip("ABCDEF", values):
        ref = f"{col}{r}"
        if isinstance(v, datetime):   # Excel's date number: days since 30/12/1899
            cells.append(f'<c r="{ref}" s="2"><v>{(v - datetime(1899, 12, 30)).total_seconds() / 86400:.8f}</v></c>')
        elif isinstance(v, Link) and len(v.url) < 250:   # a formula's text can't be longer than 255
            f = f'HYPERLINK("{v.url.replace(chr(34), chr(34) * 2)}","{v.text.replace(chr(34), chr(34) * 2)}")'
            cells.append(f'<c r="{ref}" s="{5 if shaded else 4}" t="str"><f>{text(f)}</f><v>{text(v.text)}</v></c>')
        elif isinstance(v, Link):
            cells.append(f'<c r="{ref}" s="{3 if shaded else 0}" t="inlineStr"><is><t>{text(v.url)}</t></is></c>')
        elif v or shaded:   # shaded rows are shaded all the way across
            style = ' s="1"' if header else ' s="3"' if shaded else ""
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
# Styles: 0 plain, 1 bold (the header), 2 date & time, 3 a look-alike row (italic grey on light yellow, as
# /run's possible-match rows), 4 a link, 5 a link on a look-alike row
STYLES = (
    f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<styleSheet xmlns="{NS}">'
    '<numFmts count="1"><numFmt numFmtId="164" formatCode="dd/mm/yyyy hh:mm:ss"/></numFmts>'
    '<fonts count="4"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font>'
    '<font><i/><sz val="11"/><color rgb="FF595959"/><name val="Calibri"/></font>'
    '<font><u/><sz val="11"/><color rgb="FF0563C1"/><name val="Calibri"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FFFFF2CC"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="6"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="0" fontId="2" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="0" fontId="3" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')

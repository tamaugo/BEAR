#!/usr/bin/env python3
"""
Deterministic post-validator + repairer for Agent 3's 4-field pipe-delimited output.

Agent 3 (agents/agent3_instructions_v4_jev_tuned.md) is an LLM and, on live A/B runs,
occasionally slips on STRUCTURE rather than content: a row lands out of numeric order,
a row-shift cascade points a row at the wrong photo, a price misses its .99/19.99 rule,
or a failure row keeps stray price/url text. These are exactly the kind of mistakes a
deterministic script can catch and fix with total confidence -- no model call, no
judgement about part correctness, just re-applying the prompt's own mechanical rules.

This script does NOT re-judge anything semantic (is this the right part, is this price
sane for the part). It only enforces the *shape* the prompt already specifies.

Usage:
    python3 tools/agent3_validator.py <agent3_output_file> <agent2_input_lines_file> [backup_path]

Exit codes:
    0 -- no unrepairable issues found (repairs may still have been applied and saved).
    2 -- at least one issue could not be safely repaired; see the report for detail.
"""

import os
import re
import sys
import tempfile

# The four failure strings the v4 prompt defines verbatim (agent3_instructions section
# "Input" + "Absolute rules"). Anything claiming to be a failure row that isn't exactly
# one of these -- or the NO PART NUMBER shape below -- is not something we can trust
# enough to silently clean up, so it gets marked instead of repaired.
FAILURE_PATTERNS = {
    "FAILED - Agent 1 - Could Not Produce Clear Part Number",
    "FAILED - Agent 2 - No eBay Listing Found",
    "FAILED - Agent 2 - eBay Lookup Unavailable",
    "FAILED - Agent 3 - Malformed Input Line",
}

# `NO PART NUMBER - <vehicle> - <location>`, with vehicle and/or location optionally
# omitted (both, either, or neither -- the prompt allows all four shapes). We don't try
# to validate the vehicle/location text itself; we only need to recognise the row as a
# genuine "no part number" row so its price/url fields get the same empty-field rule as
# a failure row.
NO_PART_NUMBER_RE = re.compile(r"^NO PART NUMBER( - .+)?$")

PRICE_FLOOR = 19.99


class Row:
    """One line of Agent 3's output, tracked through validation and repair."""

    def __init__(self, raw, index):
        self.raw = raw
        self.index = index  # arrival order, used to keep sort stable on ties
        self.parse_error = False
        self.fields = None  # [part_info, price, url, image] once parsed
        self.repairs = []  # human-readable notes: silently-applied fixes
        self.marks = []  # human-readable notes: could not repair, must flag

    def rebuild_raw(self):
        """Reconstruct the output line from (possibly repaired) fields."""
        if self.parse_error:
            return self.raw
        return join_fields(self.fields)


def parse_output_line(line, index):
    """Rule 1: split into exactly 4 fields on the pipe delimiter. A bad split is left
    untouched (not repaired) but still counted -- guessing at field boundaries risks
    corrupting data worse than the original mistake.

    We split on bare '|' and strip whitespace from each piece rather than literally on
    ' | ': the prompt's own failure-row example (`FAILED - ... Found | | | file.JPEG`)
    writes an empty field as nothing between two separators, which makes consecutive
    empty fields share a single space (`| | |`, not `|  |  |`). Splitting on the
    3-character ' | ' token eats across that shared space and undercounts fields on
    every failure/no-part-number row -- confirmed against tests/fixtures/agent3_v4_
    expected_output.md, where literal ' | ' splitting misparses every failure line.
    """
    row = Row(line, index)
    fields = [piece.strip() for piece in line.split("|")]
    if len(fields) != 4:
        row.parse_error = True
        row.marks.append(
            f"malformed line: split on ' | ' gave {len(fields)} fields, expected 4"
        )
        return row
    row.fields = fields
    return row


def join_fields(fields):
    """Rebuild a 4-field line the way the v4 prompt actually writes one.

    Plain " | ".join(fields) is wrong here: an empty field between two separators
    should leave a *single* space between the two pipes ("| | |", as in every
    failure-row example in the prompt and fixture), but joining with the 3-char
    " | " token produces a double space for each empty field ("|  |  |"). Instead,
    emit a literal "|" token between every pair of fields, only emit a field's own
    text when it's non-empty, and join everything with single spaces -- this is
    the construction that actually reproduces "text | | | filename".
    """
    tokens = []
    for i, field in enumerate(fields):
        if i > 0:
            tokens.append("|")
        if field:
            tokens.append(field)
    return " ".join(tokens)


def normalize_partnum(text):
    """Part numbers are written with hyphens/spaces stripped and uppercased -- the
    exact transform the v4 prompt's "Part number" section specifies for the output,
    so applying it to the input side too lets us compare like with like."""
    return re.sub(r"[-\s]+", "", text).upper()


def parse_input_file(path):
    """Read the Agent-2-lines file Agent 3 processed (argv[2]). Returns:
        index: dict filename -> list of {"part_number_norm": str|None, "is_failed": bool}
        line_count: number of non-empty lines (for the count-parity check)
    One filename can legitimately appear more than once (two parts, one photo), hence
    the list rather than a single record per filename."""
    index = {}
    line_count = 0
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line.strip():
                continue
            line_count += 1
            fields = line.split(" | ")
            filename = fields[0].strip()
            if len(fields) < 2:
                # No ' | ' at all (Agent 3's own malformed-input case). No usable
                # part-number field, but the filename slot still needs registering
                # so it counts as "claimed" and doesn't look like an orphan.
                index.setdefault(filename, []).append(
                    {"part_number_norm": None, "is_failed": False}
                )
                continue
            is_failed = fields[1].strip() == "FAILED"
            part_number_norm = None if is_failed else normalize_partnum(fields[1].strip())
            index.setdefault(filename, []).append(
                {"part_number_norm": part_number_norm, "is_failed": is_failed}
            )
    return index, line_count


def extract_image_number(filename):
    """Rule 2a: sort key is the first run of digits in the filename; None (sorts
    first) when there are no digits at all, matching the prompt's row-order rule."""
    match = re.search(r"\d+", filename)
    return int(match.group()) if match else None


def extract_trailing_partnumber(part_info):
    """The part number is always the last token of the part-info field (prompt:
    "It is the last thing in the part info field"), written as one uppercase
    alnum run with no hyphens or spaces. Anything else in that position means we
    can't identify a part number to cross-check -- return None rather than guess."""
    text = part_info.rstrip()
    if not text:
        return None
    last_token = text.rsplit(None, 1)[-1]
    return last_token if re.fullmatch(r"[A-Z0-9]+", last_token) else None


def is_known_failure_shape(part_info):
    return part_info in FAILURE_PATTERNS or NO_PART_NUMBER_RE.match(part_info) is not None


def looks_like_failure_shape(part_info):
    """Starts like a failure/no-part-number row but didn't match the known-good
    patterns above -- e.g. a reworded failure reason. Never repaired (rule 3b)."""
    return part_info.startswith("FAILED - ") or part_info.startswith("NO PART NUMBER")


def fix_price(raw_price):
    """Rules 2c/2d combined: normalize format, then apply the prompt's own price
    rules (round up to the next .99, then floor at 19.99, floor applied last) so
    the repaired value is always what Agent 3 was supposed to produce, not just a
    reformatted version of what it wrote.

    Returns (new_value, repaired, mark_reason). mark_reason is set (and new_value
    is the untouched original) when the field can't be parsed as a number at all.
    """
    raw_price = raw_price.strip()
    if raw_price == "":
        return "", False, None  # empty price is valid on failure/no-part-number rows

    match = re.search(r"\d+(?:\.\d+)?", raw_price)
    if not match:
        return raw_price, False, f"price unparseable: {raw_price!r}"

    value = float(match.group())
    whole = int(value)
    candidate = whole + 0.99
    if candidate < value - 1e-9:  # e.g. value=27.995 -> whole+.99 not yet >= value
        candidate += 1.0
    if candidate < PRICE_FLOOR:
        candidate = PRICE_FLOOR
    new_value = f"{candidate:.2f}"

    repaired = new_value != raw_price
    return new_value, repaired, None


def repair_row_order(rows):
    """Rule 2a: stable-sort all successfully-parsed rows by image number ascending;
    parse-error rows have no trustworthy field 4, so they're anchored at the end
    (still in their own arrival order) rather than guessed at."""
    def sort_key(row):
        if row.parse_error:
            return (1, 0)
        image_num = extract_image_number(row.fields[3])
        return (0, -1 if image_num is None else image_num)

    original_order = list(rows)
    rows.sort(key=sort_key)  # stable: ties keep arrival order automatically
    if rows != original_order:
        for row in rows:
            row.repairs.append("row order: resorted by image number ascending")
        return True
    return False


def repair_image_field_remap(rows, input_filenames, input_index):
    """Rule 2b: the row-shift cascade repair.

    Signature of a row-shift: one input filename is claimed (as field 4) by two
    output rows, while another input filename is claimed by none (an "orphan").
    That happens when Agent 3 drops or duplicates a row and every row after it
    silently inherits the previous row's image reference. We resolve it only when
    exactly one of the duplicate-claiming rows has a part number that uniquely
    matches the orphan's input record -- if that match isn't unique, remapping
    would be a guess, so we leave it for the mark pass instead.
    """
    claim_counts = {}
    for row in rows:
        if row.parse_error:
            continue
        claim_counts[row.fields[3]] = claim_counts.get(row.fields[3], 0) + 1

    orphans = [fn for fn in input_filenames if fn not in claim_counts]
    duplicated = [fn for fn, count in claim_counts.items() if count > 1]

    for filename in duplicated:
        claimants = [
            row for row in rows
            if not row.parse_error
            and row.fields[3] == filename
            and not is_known_failure_shape(row.fields[0])
        ]
        for orphan in list(orphans):
            orphan_partnums = {
                rec["part_number_norm"] for rec in input_index.get(orphan, [])
                if not rec["is_failed"]
            }
            matching_claimants = [
                row for row in claimants
                if extract_trailing_partnumber(row.fields[0]) in orphan_partnums
                and extract_trailing_partnumber(row.fields[0]) is not None
            ]
            if len(matching_claimants) == 1:
                row = matching_claimants[0]
                old = row.fields[3]
                row.fields[3] = orphan
                row.repairs.append(f"image field remap (row-shift cascade): {old!r} -> {orphan!r}")
                orphans.remove(orphan)
                break


def validate_rows(rows, input_index, input_filenames):
    """Rules 2c/2d/2e (repair) and 3b/3c/3d/3e (mark) for every successfully-parsed
    row. Row order and image remap have already run by the time this is called."""
    for row in rows:
        if row.parse_error:
            continue
        part_info, price, url, image = row.fields

        if is_known_failure_shape(part_info):
            # Rule 2e: failure / no-part-number rows must carry no price or url.
            if price != "" or url != "":
                row.fields[1] = ""
                row.fields[2] = ""
                row.repairs.append("cleared stray price/url on failure/no-part-number row")
            continue

        if looks_like_failure_shape(part_info):
            # Rule 3b: starts like a failure row but doesn't match a known pattern
            # exactly -- never guess at what it was supposed to say.
            row.marks.append(f"unrecognised failure/no-part-number pattern: {part_info!r}")
            continue

        # Success row: price, url, and part-number cross-check against the input.
        new_price, repaired, mark_reason = fix_price(price)
        if mark_reason:
            row.marks.append(mark_reason)
        elif repaired:
            row.fields[1] = new_price
            row.repairs.append(f"price normalized: {price!r} -> {new_price!r}")

        if url != "" and not url.startswith("http"):
            row.marks.append(f"url does not start with http: {url!r}")

        part_number = extract_trailing_partnumber(part_info)
        records = input_index.get(image)
        if records is None:
            row.marks.append(
                f"image {image!r} not found in input file and could not be "
                "unambiguously remapped"
            )
            continue
        input_partnums = {rec["part_number_norm"] for rec in records if not rec["is_failed"]}
        if part_number is None or part_number not in input_partnums:
            row.marks.append(
                f"part number {part_number!r} not found among input records for "
                f"{image!r} (invented or changed number)"
            )


def write_backup(output_path, backup_path):
    with open(output_path, encoding="utf-8") as f:
        original = f.read()
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(original)


def write_repaired_file(output_path, rows):
    """Atomic write: build the new content in a tempfile in the same directory, then
    os.replace it over the original. Avoids ever leaving a half-written output file
    if the process is interrupted mid-write."""
    directory = os.path.dirname(os.path.abspath(output_path)) or "."
    content = "\n".join(row.rebuild_raw() for row in rows) + "\n"
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".agent3_validator_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, output_path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def build_report(rows, file_level_marks):
    total = len(rows)
    marked = [r for r in rows if r.marks]
    repaired_only = [r for r in rows if r.repairs and not r.marks]
    clean_pass = [r for r in rows if not r.repairs and not r.marks]

    lines = [
        "Agent 3 output validation report",
        f"  total lines : {total}",
        f"  pass        : {len(clean_pass)}",
        f"  repaired    : {len(repaired_only)}",
        f"  marked      : {len(marked)}",
        "",
    ]
    if file_level_marks:
        lines.append("File-level issues:")
        for note in file_level_marks:
            lines.append(f"  - {note}")
        lines.append("")
    for row in rows:
        if not row.repairs and not row.marks:
            continue
        label = row.fields[3] if row.fields else row.raw[:60]
        lines.append(f"Line (image={label!r}):")
        for note in row.repairs:
            lines.append(f"  [repaired] {note}")
        for note in row.marks:
            lines.append(f"  [MARKED]   {note}")
    return "\n".join(lines)


def run_validator(output_path, input_path, backup_path=None):
    """Core entry point, callable directly from tests without going through argv/exit."""
    if backup_path:
        write_backup(output_path, backup_path)

    with open(output_path, encoding="utf-8") as f:
        output_lines = [line.rstrip("\n") for line in f if line.strip()]

    input_index, input_line_count = parse_input_file(input_path)
    input_filenames = set(input_index.keys())

    rows = [parse_output_line(line, i) for i, line in enumerate(output_lines)]

    file_level_marks = []
    if len(output_lines) < input_line_count:
        file_level_marks.append(
            f"line count deficit: {len(output_lines)} output lines vs "
            f"{input_line_count} input lines -- rows may have been lost"
        )

    reordered = repair_row_order(rows)
    repair_image_field_remap(rows, input_filenames, input_index)
    validate_rows(rows, input_index, input_filenames)

    any_repairs = reordered or any(r.repairs for r in rows)
    any_marks = bool(file_level_marks) or any(r.marks for r in rows)

    if any_repairs:
        write_repaired_file(output_path, rows)

    report = build_report(rows, file_level_marks)
    return report, any_marks


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    output_path = sys.argv[1]
    input_path = sys.argv[2]
    backup_path = sys.argv[3] if len(sys.argv) > 3 else None

    report, any_marks = run_validator(output_path, input_path, backup_path)
    print(report)
    return 2 if any_marks else 0


if __name__ == "__main__":
    sys.exit(main())

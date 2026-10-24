#!/usr/bin/env python3
"""
Self-asserting test suite for tools/agent3_validator.py.

Stdlib-only, no network, no external fixtures required beyond what each test builds
itself in a tempdir. Each test writes an Agent-3-shaped output file and an Agent-2-
shaped input file, runs the validator's core entry point directly (run_validator, not
subprocess -- faster and gives direct access to the report string / exit signal), and
asserts on the resulting report, exit signal, and (where relevant) the repaired file
contents on disk.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent3_validator import run_validator  # noqa: E402

FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} {detail}")
        FAILURES.append(name)


def write(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def with_tempdir(fn):
    """Run fn(tmpdir) inside a fresh temp directory, always cleaned up."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fn(tmpdir)


# ---------------------------------------------------------------------------
# 1. Sorted pass-through: correct file in, no repairs, no marks, exit clean.
# ---------------------------------------------------------------------------
def test_sorted_pass_through(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 10.00 | http://a\n"
                       "img_2.jpg | BBB222 | Part B | 10.00 | http://b\n")
    write(output_path,
          "VEH - Part A AAA111 | 19.99 | http://a | img_1.jpg\n"
          "VEH - Part B BBB222 | 19.99 | http://b | img_2.jpg\n")
    original = read(output_path)
    report, any_marks = run_validator(output_path, input_path)
    check("sorted pass-through: no marks", any_marks is False, report)
    check("sorted pass-through: pass count 2", "pass        : 2" in report, report)
    check("sorted pass-through: file untouched", read(output_path) == original)


# ---------------------------------------------------------------------------
# 2. Out-of-order repair: rows sorted by image number ascending.
# ---------------------------------------------------------------------------
def test_out_of_order_repair(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 10.00 | http://a\n"
                       "img_2.jpg | BBB222 | Part B | 10.00 | http://b\n")
    write(output_path,
          "VEH - Part B BBB222 | 19.99 | http://b | img_2.jpg\n"
          "VEH - Part A AAA111 | 19.99 | http://a | img_1.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    lines = [l for l in read(output_path).splitlines() if l.strip()]
    check("out-of-order: repaired, no marks", any_marks is False, report)
    check("out-of-order: img_1 now first", lines[0].endswith("img_1.jpg"), lines)
    check("out-of-order: img_2 now second", lines[1].endswith("img_2.jpg"), lines)
    check("out-of-order: repaired count 2", "repaired    : 2" in report, report)


# ---------------------------------------------------------------------------
# 3. Price floor repair: below 19.99 -> 19.99.
# ---------------------------------------------------------------------------
def test_price_floor_repair(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 5.00 | http://a\n")
    write(output_path, "VEH - Part A AAA111 | 5.00 | http://a | img_1.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    out = read(output_path)
    check("price floor: repaired to 19.99", "| 19.99 | " in out, out)
    check("price floor: no marks", any_marks is False, report)


# ---------------------------------------------------------------------------
# 4. Price format repair: '19.9' -> floors/normalizes to '19.99'.
# ---------------------------------------------------------------------------
def test_price_format_repair(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 19.90 | http://a\n")
    write(output_path, "VEH - Part A AAA111 | 19.9 | http://a | img_1.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    out = read(output_path)
    check("price format: '19.9' -> '19.99'", "| 19.99 | " in out, out)
    check("price format: no marks", any_marks is False, report)


# ---------------------------------------------------------------------------
# 5. Rounding repair: 25.00 -> 25.99 (round up to next .99, never down).
# ---------------------------------------------------------------------------
def test_price_rounding_repair(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 25.00 | http://a\n")
    write(output_path, "VEH - Part A AAA111 | 25.00 | http://a | img_1.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    out = read(output_path)
    check("rounding: 25.00 -> 25.99", "| 25.99 | " in out, out)
    check("rounding: no marks", any_marks is False, report)


# ---------------------------------------------------------------------------
# 6. Row-shift remap repair: a duplicated image claim + one orphan input
#    filename, resolved via the unique part-number match.
# ---------------------------------------------------------------------------
def test_row_shift_remap_repair(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path,
          "img_1.jpg | AAA111 | Part A | 10.00 | http://a\n"
          "img_2.jpg | BBB222 | Part B | 10.00 | http://b\n"
          "img_3.jpg | CCC333 | Part C | 10.00 | http://c\n")
    # img_2.jpg's row wrongly claims img_3.jpg (a row-shift cascade); img_3.jpg's own
    # row still correctly claims img_3.jpg too, so img_3.jpg is duplicated and img_2.jpg
    # (the true home of BBB222) is an orphan -- exactly the row-shift signature.
    write(output_path,
          "VEH - Part A AAA111 | 19.99 | http://a | img_1.jpg\n"
          "VEH - Part B BBB222 | 19.99 | http://b | img_3.jpg\n"
          "VEH - Part C CCC333 | 19.99 | http://c | img_3.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    out = read(output_path)
    check("row-shift: BBB222 remapped to img_2.jpg",
          "Part B BBB222 | 19.99 | http://b | img_2.jpg" in out, out)
    check("row-shift: CCC333 stays on img_3.jpg",
          "Part C CCC333 | 19.99 | http://c | img_3.jpg" in out, out)
    check("row-shift: no marks", any_marks is False, report)


# ---------------------------------------------------------------------------
# 7. Failure-row cleanup repair: stray price/url cleared on a known pattern.
# ---------------------------------------------------------------------------
def test_failure_row_cleanup_repair(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | FAILED | Agent 1 | Could Not Produce Clear Part Number\n")
    write(output_path,
          "FAILED - Agent 1 - Could Not Produce Clear Part Number | 9.99 | http://x | img_1.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    out = read(output_path)
    check("failure cleanup: price/url cleared",
          "Number | | | img_1.jpg" in out, out)
    check("failure cleanup: no marks", any_marks is False, report)


# ---------------------------------------------------------------------------
# 8. Unparseable price: marked, not repaired, file left untouched.
# ---------------------------------------------------------------------------
def test_unparseable_price_mark(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 10.00 | http://a\n")
    write(output_path, "VEH - Part A AAA111 | ask seller | http://a | img_1.jpg\n")
    original = read(output_path)
    report, any_marks = run_validator(output_path, input_path)
    check("unparseable price: marked", any_marks is True, report)
    check("unparseable price: reported in report", "unparseable" in report, report)
    check("unparseable price: file untouched", read(output_path) == original)


# ---------------------------------------------------------------------------
# 9. Count-mismatch mark: fewer output lines than input lines.
# ---------------------------------------------------------------------------
def test_count_mismatch_mark(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path,
          "img_1.jpg | AAA111 | Part A | 10.00 | http://a\n"
          "img_2.jpg | BBB222 | Part B | 10.00 | http://b\n")
    write(output_path, "VEH - Part A AAA111 | 19.99 | http://a | img_1.jpg\n")
    report, any_marks = run_validator(output_path, input_path)
    check("count mismatch: marked", any_marks is True, report)
    check("count mismatch: reported", "line count deficit" in report, report)


# ---------------------------------------------------------------------------
# 10. Invented part-number mark: output number doesn't match the input's.
# ---------------------------------------------------------------------------
def test_invented_part_number_mark(tmpdir):
    input_path = os.path.join(tmpdir, "input.md")
    output_path = os.path.join(tmpdir, "output.md")
    write(input_path, "img_1.jpg | AAA111 | Part A | 10.00 | http://a\n")
    write(output_path, "VEH - Part A ZZZ999 | 19.99 | http://a | img_1.jpg\n")
    original = read(output_path)
    report, any_marks = run_validator(output_path, input_path)
    check("invented part number: marked", any_marks is True, report)
    check("invented part number: reported", "invented or changed number" in report, report)
    check("invented part number: file untouched", read(output_path) == original)


TESTS = [
    test_sorted_pass_through,
    test_out_of_order_repair,
    test_price_floor_repair,
    test_price_format_repair,
    test_price_rounding_repair,
    test_row_shift_remap_repair,
    test_failure_row_cleanup_repair,
    test_unparseable_price_mark,
    test_count_mismatch_mark,
    test_invented_part_number_mark,
]


def main():
    for test in TESTS:
        with_tempdir(test)
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILED: {', '.join(FAILURES)}")
        return 1
    print(f"All {len(TESTS)} test groups passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

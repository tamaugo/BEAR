# Expected Agent 3 v3 output for `agent3_dummy_input.md`

Lines 1-10 are verbatim from the first successful live Agent 2 run (2026-09-03, real eBay.co.uk data).
Lines 11-15 are synthetic, each targeting an edge case that run did not exercise.

Format: `- filename | - Cleaned Part Name PARTNUMBER | price`
The leading `- ` is a markdown bullet required by the destination Google Sheet.
The second `- ` is the vehicle slot — empty during the demo, filled at job start later.

## Expected output — 15 lines in, 15 lines out

```
- img_001.jpg | FAILED | Agent 1 | Could Not Produce Clear Part Number
- img_002.jpg | - Front Right Driver Side Door Card Puddle Light 926323Z500 | 19.99
- img_002.jpg | - Front Left Door Card Puddle Light 926313Z000 | 19.99
- img_003.jpg | FAILED | Agent 1 | Could Not Produce Clear Part Number
- img_004.jpg | - Front Left Passenger Side Seat Belt Buckle 888303Z000 | 19.99
- img_005.jpg | - Driver Side Front Seat Control Motor 885813S000 | 25.99
- img_006.jpg | - Front Left Passenger Side Window Control Switch 935753Z200 | 19.99
- img_007.jpg | - Front Right Seat Control Motor 885833S500 | 27.99
- img_008.jpg | - Rear Left Side Window Switch 935803Z000 | 19.99
- img_009.jpg | - Rear Number Plate Light 92501C1000 | 24.99
- img_010.jpg | - Rear Tailgate Strut Gas Spring 8115002D00 | 100.99
- img_011.jpg | FAILED | Agent 2 | eBay Lookup Unavailable
- img_012.jpg | FAILED | Agent 2 | No eBay Listing Found
- img_013.jpg | - Some Part 4567899999 | 19.99
- img_014.jpg | FAILED | Agent 3 | Malformed Input Line
```

## What each line tests

| Line | Tests |
|---|---|
| 1, 4 | Agent 1 failure pass-through, agent tag intact |
| 2, 3 | **Two lines sharing `img_002.jpg`** — complementary left/right pair. Two separate output lines, never merged |
| 2 | Strip `HYUNDAI I40` + year `2012` + the title's own number; ALL-CAPS converted; **location words moved to the front** |
| 3 | Strip `Hyundai / i40` including the stray slash left behind |
| 5 | Strip a year **range** (`2011 - 2017`); title number is unhyphenated (`888303Z000`) and must still be removed |
| 6 | Strip engine size and fuel (`1.7 CRDI`), leading year (`2016`), trailing `OEM`. Also tests the word-order exception: `Front` belongs to `Front Seat` and must NOT be moved |
| 7 | Strip trailing year `2017` |
| 8 | Strip generation code `VF`, `Diesel`, `1.7`, power figure `100kW` — the hardest line in the set |
| 9 | Strip `FACELIFT` and open-ended year `2015-ON`. **This was the only miss on the first run** — `Facelift` survived, so v3 now names generation/facelift words explicitly |
| 10 | **Cross-manufacturer case.** Title says KIA Stonic, job is a Hyundai i40. Stripping the vehicle removes the conflict entirely, no cross-reference list needed. Price already `.99` — leave alone |
| 11 | **Location word moved to the front** (`Rear`), matching Tamaugo's worked example. **eBay title containing `\|` characters** — must be replaced with spaces or the row gains extra columns. Also strips `Genuine`. Price 100.00 → 100.99 crossing into three digits |
| 12 | The `eBay Lookup Unavailable` string — passes through, must NOT become `No eBay Listing Found` |
| 13 | `No eBay Listing Found` pass-through |
| 14 | Price exactly at the floor and already `.99` — left as 19.99, not bumped |
| 15 | Malformed line — becomes an Agent 3 failure, never silently dropped |

## Price working

| Raw | Round up to `.99` | Floor applied | Final |
|---|---|---|---|
| 12.49 | 12.99 | below 19.99 | **19.99** |
| 14.90 | 14.99 | below 19.99 | **19.99** |
| 18.97 | 18.99 | below 19.99 | **19.99** |
| 25.00 | 25.99 | above | **25.99** |
| 27.89 | 27.99 | above | **27.99** |
| 24.99 | 24.99 (already) | above | **24.99** |
| 100.00 | 100.99 | above | **100.99** |
| 19.99 | 19.99 (already) | at floor | **19.99** |

Six of the eleven priced lines land on the floor. That is a real property of this batch — cheap trim and switch components — not an artefact of the test data. Worth knowing before the floor value is ever changed.

## First run result (2026-09-04)

14 of 15 lines matched exactly on the first attempt. The single miss was line 9, where `Facelift` was not stripped; v3 was amended to name generation and facelift words explicitly. Lines 2, 7 and 11 above have since been updated for the location-leads word-order rule, so this fixture no longer reflects that run — it is the target for the next one.

## Judgement calls to check on the first run

These are the lines where a model could reasonably differ. If output varies from the above, decide whether the rule needs tightening or the expectation adjusting:

- **Line 8** — is `VF` a generation code (strip) or part of the component name (keep)? v3 says strip when unsure.
- **Line 13** — `Some Part` is a placeholder name; a model may object to it rather than pass it through.
- **Line 11** — whether `Rear` survives as part of the component name after the pipes are collapsed.

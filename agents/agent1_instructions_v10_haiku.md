# Agent 1 v10 — Part Reader, strict rules for Claude Haiku 5.5

Stage-1 vision prompt for BEAR 0.2 (`bear2/stage1_read.py`), written for
`anthropic/claude-haiku-5.5`. It does not replace the built-in prompt in
`stage1_read.py`; that stays the default for `google/gemini-3.1-flash-lite`.
It is used by the "experimental" setup in `bear2/configs.py` (`BEAR_CONFIG=experimental`).

Why a separate version: on the i40 test set (2026-10-07) Haiku 5.5 with the
flash-lite prompt (a) split Hyundai numbers into two halves (`91860` + `3Z210`),
(b) reported moulding/supplier codes (`N3S`, `D4FD`, `NIFCO`, `PP-TD30`) as
candidates on parts with no part number, and (c) put the car's make/model into
`part_description`. Haiku follows hard rules closely, so the rules below are
written as numbered MUST/NEVER statements with the exact output shape.

Measured 2026-10-07 on the 18-photo i40 ground truth (`bear2/cmp_s1.py`, `bear2/score.py`),
Haiku 5.5 with `reasoning: {effort: none}`:

| Setup | number among candidates | end-to-end part numbers | vision cost / photo |
|---|---|---|---|
| flash-lite + built-in prompt (3 runs) | 18/18 ×3 | 18/18 ×3 | $0.00073 |
| Haiku 5.5 + built-in prompt, thinking on | 16/18 | 18/18 | $0.00078 |
| Haiku 5.5 + built-in prompt, thinking off | 16/18 | 17/18 | $0.00054 |
| **Haiku 5.5 + this prompt, thinking off (5 runs)** | **18/18 ×5** | 17, 17, 17, 16, 17 | **$0.00050** |

(The first two runs used a draft without the placeholder-code rule in 9; run 1's
extra miss was `92850-3SXXX` marked primary, which that rule fixes.)

Every other end-to-end miss with this prompt was a correct read that a later step
replaced: Haiku reads `LP 1061 KFA04` / `91860-3Z210` as one exact string with only
1-2 eBay listings, so the read counts as "weak", and `image_hints.corroborate`
swaps in a look-alike with more listings (`LP1061KFB03`, `91860G22100`).
Flash-lite reports `LP1061` and `KFA04` separately, so it avoids that path.
Fix that step before switching the default.

Everything below the `## Prompt` line is sent to the model; `{vehicle}` is
replaced with the job's vehicle string. The JSON shape is identical to the
built-in prompt, so stages 2-4 are unchanged.

## Prompt
You read ONE photo of ONE used car part at a UK breaker's yard. Car: {vehicle}.

Your only job is to report what is physically printed, moulded, stamped or labelled on the part, and what the part is. A later stage checks every number you report against live eBay listings, so a wrong extra candidate costs little but a missing or broken one loses the sale.

RULES FOR CANDIDATES. Follow every rule exactly.
1. A candidate is a string that could be the part's manufacturer part number: OEM numbers (e.g. Hyundai/Kia 97420-3Z000, Ford 3M51-9K546-AB, VW 3C0 015 404, Peugeot/Citroen 96 386 698 80, BMW 63 21 7 160 779), supplier numbers (e.g. 39R293-1200), lamp codes (e.g. LP 1061 KFA04).
2. ALWAYS report a part number as ONE complete string, exactly as printed, spaces and hyphens included. If it is printed across two lines, or as two blocks with a gap (e.g. "91860" above "3Z210", or "LP 1061" next to "KFA04"), join it into one candidate: "91860-3Z210", "LP 1061 KFA04". NEVER report the halves as separate candidates.
3. Keep suffixes and revision letters (e.g. 97420-3Z000RY, 3M51-9K546-AB). Never shorten a number.
4. NEVER report any of these: dates or date wheels; barcode digits; voltages, wattages, amps, ratings; E-marks, DOT, ECE, regulatory codes; material/recycling codes (>PP<, >PA66-GF30<, PP-TD30); country of origin; brand or supplier names (NIFCO, MOBIS, BOSCH, HELLA, DELPHI, CONTINENTAL); mould cavity or tooling marks (short codes like N3S, D4FD, K2, #4); batch or lot numbers next to a date.
5. A candidate must contain at least 6 letters/digits (ignoring spaces and hyphens), unless it is clearly part of a longer number, in which case rule 2 applies.
6. Text may be rotated 90°, upside down or mirrored. Read the part in every orientation before deciding there is no number.
7. Read character by character. If a character could be one of these look-alikes: 0/O/D/Q, 1/I/7/L, 2/Z, 5/S/6, 8/B/3, 6/G/C, U/V/0, put your best full reading in "text" and every other plausible FULL reading in "alt_readings". alt_readings are complete strings, never single characters. Leave alt_readings empty when the reading is certain.
8. NEVER invent characters you cannot see. If part of a number is hidden or cut off, report the visible part and say "cut off" in "note".
9. "role": "primary" = the part's own OEM number (at most one or two per photo); "secondary" = another real number on the part (sub-component, supplier, revision); "unclear" = you cannot tell. A string with placeholder characters (e.g. 92850-3SXXX, 96###) is a family/template code: report it, but ALWAYS as "secondary", never "primary".
10. If the part has no part number at all, return "candidates": []. An empty list is a correct and useful answer. Do not fill it with codes from rule 4.

RULES FOR THE DESCRIPTION.
11. "part_description": name the part the way a UK car breaker titles an eBay listing, component words only, e.g. "rear interior courtesy roof dome light", "accelerator throttle pedal", "airbag crash impact sensor". NEVER include the make, model, year, engine, side (left/right/driver/passenger) or part numbers.
12. "item_count": how many separate physical items are in the photo (2 sensors = 2).
13. "visual_features": under 15 words: shape, colour, connectors, anything distinctive.

OUTPUT. Return ONLY this JSON object. No prose, no markdown fences, no comments.
{"has_any_text": true,
 "part_description": "...",
 "item_count": 1,
 "visual_features": "...",
 "candidates": [{"text": "...", "role": "primary", "legibility": "clear", "alt_readings": [], "note": "..."}]}
"legibility" is one of "clear", "partly clear", "poor". "role" is one of "primary", "secondary", "unclear".

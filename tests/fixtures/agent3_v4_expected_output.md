# Expected Agent 3 v4 output for `agent3_v4_dummy_input.md` (Jev fork, 2026-09-28)
#
# Hand-derived line by line from agents/agent3_instructionsv4.md's rules.
# Correction (2026-09-28, after the first A/B sweep): line 11 originally read
# `Rear Tailgate Strut Gas Spring`, carried over from the v3-era fixture. That
# was WRONG under v4 — v4 removed the seller-location fallback ("no code means
# no location in the output") and strips title location words on every line,
# so `Rear` must go. The corrected line expects `Tailgate Strut Gas Spring`.
# First-sweep scores are ~1 line low per model because of this.

```
FAILED - Agent 1 - Could Not Produce Clear Part Number | | | img_001.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Door Card Puddle Light 926323Z500 | 19.99 | https://www.ebay.co.uk/itm/111111111111 | img_002.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Door Card Puddle Light 926313Z000 | 19.99 | https://www.ebay.co.uk/itm/222222222222 | img_002.jpg
FAILED - Agent 1 - Could Not Produce Clear Part Number | | | img_003.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Seat Belt Buckle 888303Z000 | 19.99 | https://www.ebay.co.uk/itm/333333333333 | img_004.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Front Seat Control Motor 885813S000 | 25.99 | https://www.ebay.co.uk/itm/444444444444 | img_005.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Window Control Switch 935753Z200 | 19.99 | https://www.ebay.co.uk/itm/555555555555 | img_006.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Front Seat Control Motor 885833S500 | 27.99 | https://www.ebay.co.uk/itm/666666666666 | img_007.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Window Switch 935803Z000 | 19.99 | https://www.ebay.co.uk/itm/777777777777 | img_008.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Rear Number Plate Light 92501C1000 | 24.99 | https://www.ebay.co.uk/itm/888888888888 | img_009.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Tailgate Strut Gas Spring 8115002D00 | 100.99 | https://www.ebay.co.uk/itm/999999999999 | img_010.jpg
FAILED - Agent 2 - eBay Lookup Unavailable | | | img_011.jpg
FAILED - Agent 2 - No eBay Listing Found | | | img_012.jpg
MAZDA 6 MK2 2008 SEDAN 2.5 PETROL - Some Part 4567899999 | 19.99 | https://www.ebay.co.uk/itm/101010101010 | img_013.jpg
FAILED - Agent 3 - Malformed Input Line | | | img_014.jpg this line is malformed and has no pipes
```

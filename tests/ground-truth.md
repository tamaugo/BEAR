# Ground truth — the 9 test photographs

Test vehicle: **Hyundai i40 MK1 Sedan, 2015, 1.7 Diesel.**

Filenames are included here because the original truth table did not have them, which made
verifying a run unnecessarily manual.

| Photo | Correct part number(s) | Notes |
|---|---|---|
| `IMG_0739.JPEG` | `92501-2G000` (confirmed) / `92501-C1000` (listed) | **The one genuinely ambiguous entry.** `92501-2G000` is the number physically confirmed on the part — a Kia licence plate light with `92501-2G000` marked over in pen, which is what caused the ambiguity. `Correct numbers.docx` lists `92501-C1000` first, which is known to be backwards for this entry and was never corrected in that file. Agent 1 reads `92501-C1000`. |
| `IMG_0753.JPEG` | `93580-3Z000` | Confirmed by multiple independent UK eBay sellers as a genuine i40 part. |
| `IMG_0761.JPEG` | `88583-3S500` | Same. |
| `IMG_0770.JPEG` | `93575-3Z200` | Same. |
| `IMG_0774.JPEG` | `88581-3S000` | Same. |
| `IMG_0785.JPEG` | `88830-3Z000` | Physically marked `888303Z000RY` — `RY` is a batch/colour suffix. Suffix-stripping confirmed correct against real listings. |
| `IMG_0790.JPEG` | `1137328786` | **Accepted failure.** Non-standard format; Agent 1 fails it cleanly rather than guessing. Within tolerance for the demo. |
| `IMG_0808.JPEG` | `92631-3Z000` **and** `92632-3Z500` | **Complementary pair** — one photograph, two parts (left and right). Must produce two separate output lines sharing this filename. This is the case that breaks naive one-line-per-image logic. |
| `test_image.jpg` | `AB123456C` | Synthetic test image, not a real part. Was previously an accepted failure; Agent 1 now reads it correctly. No eBay listing exists, so Agent 2 correctly returns `No eBay Listing Found`. |

## Accuracy baseline

Agent 1 scores **8/9** on this set. The single miss is `IMG_0790`. The stated tolerance for the
demo phase is roughly 80%, so this is comfortably inside it — do not re-litigate `IMG_0790` without
genuinely new evidence.

## Two real-world complications this set exposes

**Cross-manufacturer part sharing.** `92501-C1000` returns listings for a **Kia Stonic** on one run
and a **Hyundai Tucson** on another — both legitimate, because manufacturers share parts across
platforms. Agent 3 strips the vehicle from the listing title, which defuses this without needing a
hardcoded cross-reference list.

**Part location is not reliably knowable.** `88583-3S500` and `88581-3S000` are different seat
control motors, but their eBay listings both describe the right-hand side. Location currently comes
only from seller-written text. Some physical parts carry a drawn location marker that Agent 1
ignores, correctly, because it is not a part number. Fixing this properly means changing what
Agent 1 reads — a pipeline-contract change, not a formatting one. Open design question.

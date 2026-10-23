"""Discord BEAR: renaming a folder's photos to SKU-1, SKU-2 ... and zipping them for Discord.
Separate from BEAR: it never reads 💸 flags and BEAR never sees these files. Kept free of
discord.py so it can be tested offline (tests/test_discord_offline.py); bot.py does the Discord side.

Messages are the same shapes as in folders.py.
"""
import re, zipfile
from datetime import datetime
from pathlib import PurePath

SKU = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
# Any photo, not only the ones BEAR reads: renaming doesn't open them.
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif", ".bmp", ".tif", ".tiff", ".avif")
# A zip entry costs its file plus two headers holding the name (local + central directory);
# the zip ends with a 22-byte record. SPARE covers anything Discord adds to the upload.
ENTRY_BYTES, END_BYTES, SPARE = 76, 22, 64 * 1024


def is_image(att):
    ext = PurePath(att.filename).suffix.lower()
    return ext in IMAGE_EXT or (getattr(att, "content_type", None) or "").startswith("image/")


def all_photos(messages):
    """([(message, attachment)] for every photo people posted, oldest first, in the order Discord
    shows them within a message; how many other files were left out). Reactions don't matter."""
    picks, other = [], 0
    for msg in messages:
        if msg.author.bot:
            continue
        for att in msg.attachments:
            if is_image(att):
                picks.append((msg, att))
            else:
                other += 1
    return picks, other


def new_name(sku, i, filename):
    """MYSKU-1.jpg: the SKU, the photo's number from the start of the folder, its own extension."""
    ext = PurePath(filename).suffix.lower() or ".jpg"
    return f"{sku}-{i}{ext}"


def zip_name(sku, n):
    """MYSKU-1.zip, MYSKU-2.zip ... always numbered, even when there is only one."""
    return f"{sku}-{n}.zip"


def plan_zips(files, limit):
    """Split [(name, bytes)] in order into zips that each fit Discord's upload limit.
    Returns ([[index, ...] per zip], [index of each photo too big for any zip])."""
    room = limit - END_BYTES - SPARE
    zips, too_big, cur, used = [], [], [], 0
    for i, (name, size) in enumerate(files):
        cost = size + ENTRY_BYTES + 2 * len(name.encode())
        if cost > room:
            too_big.append(i)
            continue
        if cur and used + cost > room:
            zips.append(cur)
            cur, used = [], 0
        cur.append(i)
        used += cost
    if cur:
        zips.append(cur)
    return zips, too_big


def write_zip(path, files):
    """Write [(file on disk, name in the zip)] as a zip. Stored, not compressed: photos are already
    compressed, so squeezing them only costs CPU. zipfile copies each file in chunks, so memory
    stays small whatever the photo sizes."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        for src, arc in files:
            z.write(src, arc)


def log_line(channel, folder, sku, outcome, photos=0, zips=0, where=""):
    """One line of renames.log (tab separated): when, channel, folder, SKU, what happened, photos,
    zips, where the job's files are."""
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    return "\t".join(str(x) for x in (stamp, channel, folder or "-", sku or "-", outcome, photos, zips, where)) + "\n"

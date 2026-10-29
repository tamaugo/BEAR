#!/usr/bin/env python3
"""Lay out the Discord server for BEAR in one go (discordbot/FRONTEND.md §2). Safe to run again:
it finds what's already there and only adds what's missing, then updates the pinned guide.

    🐻 BEAR     #how-to-bear (guide, pinned; read-only)   #bear-errors (the error channel; read-only)
               #update-log (what changed in each update; read-only)
               #part-id (post a part-number photo, pick 1/2/3 or type your own; for testing)
    🚗 Cars     one channel per car, the topic is the car  (text-only messages are deleted here)
    🗄️ Done     finished cars, dragged here by hand         (read-only, commands refused)

Needs DISCORD_TOKEN and DISCORD_GUILD_ID in .env, and the bot invited with Manage Channels and
Manage Roles (the setup invite link in discordbot/SETUP.md). Prints the IDs the bot needs;
with --write-env it also puts them in .env (ERROR_CHANNEL_ID, CARS_CATEGORY_ID, UPDATE_CHANNEL_ID,
PART_ID_CHANNEL_ID).

usage: .venv/bin/python discordbot/setup_server.py [--write-env]
"""
import asyncio, os, re, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
sys.path.insert(0, str(HERE))
import jev_client  # noqa: E402
import discord  # noqa: E402
import look  # noqa: E402

ENV = jev_client.ENV_FILE
BEAR_CAT, CARS_CAT, DONE_CAT = "🐻 BEAR", "🚗 Cars", "🗄️ Done"
GUIDE_CH, ERRORS_CH, UPDATES_CH, PART_ID_CH = "how-to-bear", "bear-errors", "update-log", "part-id"
GUIDE_TITLE = look.guide()["embeds"][0]["title"]
O = discord.PermissionOverwrite


def setting(name):
    v = jev_client._parse_dotenv(ENV).get(name) if ENV.exists() else None
    v = os.environ.get(name) or v
    return v.strip() if v and v.strip() and "PASTE" not in v else None


def write_env(values):
    """Set KEY=value lines in .env, keeping every other line (and its comments) as it is."""
    text = ENV.read_text() if ENV.exists() else ""
    for k, v in values.items():
        line = f"{k}={v}"
        text, n = re.subn(rf"^{k}=.*$", line, text, flags=re.M)
        if not n:
            text += ("" if text.endswith("\n") or not text else "\n") + line + "\n"
    ENV.write_text(text)


async def category(guild, name, wanted_id=None, overwrites=None):
    cat = guild.get_channel(wanted_id) if wanted_id else None
    cat = cat or discord.utils.get(guild.categories, name=name)
    if cat is None:
        print(f"  making category {name}")
        cat = await guild.create_category(name, overwrites=overwrites or {})
    elif overwrites:
        for who, ow in overwrites.items():
            await cat.set_permissions(who, overwrite=ow)
    return cat


async def text_channel(guild, cat, name, topic, overwrites, wanted_id=None):
    ch = guild.get_channel(wanted_id) if wanted_id else None
    ch = ch or discord.utils.get(guild.text_channels, name=name)
    if ch is None:
        print(f"  making #{name}")
        ch = await guild.create_text_channel(name, category=cat, topic=topic, overwrites=overwrites)
    else:
        await ch.edit(topic=topic, overwrites=overwrites)
    return ch


async def pin_guide(ch, me, errors_id):
    """Post the guide, or update the one already there (pinned or among the last 50 messages), and pin it.
    Pinning needs Discord's separate Pin Messages permission; without it the guide is still posted."""
    post = look.kwargs(look.guide(errors_id))
    mine = lambda m: m.author.id == me.id and m.embeds and m.embeds[0].title == GUIDE_TITLE
    found = None
    try:
        found = next(iter([m async for m in ch.pins() if mine(m)]), None)
    except discord.DiscordException:
        pass
    if found is None:
        found = next(iter([m async for m in ch.history(limit=50) if mine(m)]), None)
    if found is not None:
        await found.edit(**post)
        print(f"  guide in #{ch.name} updated")
    else:
        found = await ch.send(**post)
        print(f"  guide posted in #{ch.name}")
    if not found.pinned:
        try:
            await found.pin()
            print("  guide pinned")
        except discord.Forbidden:
            print(f"  couldn't pin the guide (the bot needs Pin Messages): pin it by hand in #{ch.name}")


async def lay_out(client, guild_id, write):
    guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
    me, everyone = guild.me, guild.default_role
    perms = me.guild_permissions
    missing = [n for n in ("manage_channels", "manage_roles", "manage_messages", "embed_links") if not getattr(perms, n)]
    if missing:
        sys.exit(f"The bot is missing {', '.join(missing)} in {guild.name}. Invite it again with the setup "
                 "link in discordbot/SETUP.md, then run this again.")
    print(f"Laying out {guild.name} ...")
    bot_can = O(view_channel=True, send_messages=True, embed_links=True, attach_files=True, add_reactions=True,
                read_message_history=True, manage_messages=True)
    read_only = O(send_messages=False, add_reactions=False, create_public_threads=False,
                  create_private_threads=False, use_application_commands=False)

    bear = await category(guild, BEAR_CAT)
    errors = await text_channel(guild, bear, ERRORS_CH, "Problems with BEAR runs, with a code and a fix. Only the bot posts here.",
                                {everyone: read_only, me: bot_can}, int(setting("ERROR_CHANNEL_ID") or 0) or None)
    guide = await text_channel(guild, bear, GUIDE_CH, "How to use BEAR. Read the pinned message.",
                               {everyone: read_only, me: bot_can})
    updates = await text_channel(guild, bear, UPDATES_CH, "What changed each time BEAR is updated. Only the bot posts here.",
                                 {everyone: read_only, me: bot_can}, int(setting("UPDATE_CHANNEL_ID") or 0) or None)
    part_id = await text_channel(guild, bear, PART_ID_CH, "Post a part-number photo: pick 1, 2 or 3, or type your own "
                                 "(nothing picked = 1). For testing.", {me: bot_can},
                                 int(setting("PART_ID_CHANNEL_ID") or 0) or None)
    cars = await category(guild, CARS_CAT, int(setting("CARS_CATEGORY_ID") or 0) or None, {me: bot_can})
    await category(guild, DONE_CAT, None, {everyone: read_only, me: O(view_channel=True, read_message_history=True)})
    await pin_guide(guide, me, errors.id)

    ids = {"DISCORD_GUILD_ID": guild.id, "ERROR_CHANNEL_ID": errors.id, "CARS_CATEGORY_ID": cars.id,
           "UPDATE_CHANNEL_ID": updates.id, "PART_ID_CHANNEL_ID": part_id.id}
    print("\nThe bot's settings:")
    for k, v in ids.items():
        print(f"  {k}={v}")
    if write:
        write_env(ids)
        print(f"Written to {ENV}. Restart the bot: systemctl restart bear-bot")
    else:
        print("Put these in .env (or run again with --write-env), then: systemctl restart bear-bot")
    print("\nNext: make a channel in Cars for each car, with the car in its topic, make first.")


def main():
    token, guild_id = setting("DISCORD_TOKEN"), setting("DISCORD_GUILD_ID")
    if not token or not guild_id or not guild_id.isdigit():
        sys.exit("DISCORD_TOKEN and DISCORD_GUILD_ID must be in .env first (discordbot/SETUP.md)")
    client = discord.Client(intents=discord.Intents.default())
    result = {}

    @client.event
    async def on_ready():
        try:
            await lay_out(client, int(guild_id), "--write-env" in sys.argv)
        except SystemExit as e:
            result["exit"] = e.code
        except discord.Forbidden as e:
            import traceback
            traceback.print_exc()
            result["exit"] = f"Discord said no ({e.text}). Check the bot's role is above @everyone and it has the setup permissions."
        except Exception as e:
            import traceback
            traceback.print_exc()
            result["exit"] = f"Setup stopped: {type(e).__name__}: {e}"
        finally:
            await client.close()

    asyncio.run(client.start(token))
    if result.get("exit"):
        sys.exit(result["exit"])


if __name__ == "__main__":
    main()

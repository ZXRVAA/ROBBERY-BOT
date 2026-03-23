import asyncio
import json
import os
import traceback
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "data.json"

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
data_lock = asyncio.Lock()


# ------------------------
# LOCATIONS
# ------------------------

locations = {
    1: "West Elizabeth | General Store",
    2: "West Elizabeth | Bank",
    3: "West Elizabeth | Flatneck Station",
    4: "New Austin | Thieves Landing",
    5: "New Austin | Fort Mercer",
    6: "New Austin | Bank",
    7: "New Austin | Fort Don Julio",
    8: "New Austin | Vultures Crossing Station",
    9: "New Hanover | Fort Wallace",
    10: "New Hanover | Oil Fields",
    11: "New Hanover | Mount Hagen Mine",
    12: "New Hanover | Army Wagon",
    13: "Lemoyne | Bank",
    14: "Lemoyne | Boat",
    15: "Lemoyne | General Store",
    16: "Lemoyne | Vanhorn Camp",
    17: "Lemoyne | Fort Lemoyne",
}


# ------------------------
# TIME HELPERS
# ------------------------

def now() -> datetime:
    return datetime.now(timezone.utc)


def parse_time(iso_string: str) -> datetime:
    dt = datetime.fromisoformat(iso_string)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_remaining(end_time: str) -> str:
    try:
        remaining = parse_time(end_time) - now()
        total_seconds = int(remaining.total_seconds())

        if total_seconds <= 0:
            return "0h 0m 0s"

        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"
    except Exception:
        return "0h 0m 0s"


# ------------------------
# DATA
# ------------------------

def default_data() -> dict:
    return {
        "locations": {},
        "user_cooldowns": {},
        "panels": []
    }


def normalize_data(data: dict) -> dict:
    if not isinstance(data, dict):
        return default_data()

    data.setdefault("locations", {})
    data.setdefault("user_cooldowns", {})
    data.setdefault("panels", [])

    if not isinstance(data["locations"], dict):
        data["locations"] = {}

    if not isinstance(data["user_cooldowns"], dict):
        data["user_cooldowns"] = {}

    if not isinstance(data["panels"], list):
        data["panels"] = []

    return data


def load_data() -> dict:
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return normalize_data(data)
    except Exception as e:
        print(f"Failed to load {DATA_FILE}: {e}")
        return default_data()


def save_data(data: dict) -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(normalize_data(data), f, indent=4)
    except Exception as e:
        print(f"Failed to save {DATA_FILE}: {e}")


# ------------------------
# CLEANUP
# ------------------------

def clean_expired_in_memory(data: dict) -> bool:
    current = now()
    changed = False

    for loc_id, users in list(data["locations"].items()):
        if not isinstance(users, dict):
            data["locations"].pop(loc_id, None)
            changed = True
            continue

        for uid, info in list(users.items()):
            try:
                end_time = info["end_time"]
                if current >= parse_time(end_time):
                    users.pop(uid, None)
                    changed = True
            except Exception as e:
                print(f"Bad robbery timer for user {uid} at location {loc_id}: {e}")
                users.pop(uid, None)
                changed = True

        if not users:
            data["locations"].pop(loc_id, None)
            changed = True

    for uid, end_time in list(data["user_cooldowns"].items()):
        try:
            if current >= parse_time(end_time):
                data["user_cooldowns"].pop(uid, None)
                changed = True
        except Exception as e:
            print(f"Bad cooldown for user {uid}: {e}")
            data["user_cooldowns"].pop(uid, None)
            changed = True

    return changed


# ------------------------
# EMBED
# ------------------------

def build_embed_from_data(data: dict) -> discord.Embed:
    embed = discord.Embed(
        title="Robbery Locations (Global Sync)",
        description="Timers synced across all servers",
        color=0xFF0000
    )

    for num, name in locations.items():
        loc_id = str(num)

        if loc_id in data["locations"] and data["locations"][loc_id]:
            lines = []

            for uid, info in data["locations"][loc_id].items():
                try:
                    robbery_time = format_remaining(info["end_time"])

                    cooldown_time = "Ready"
                    if uid in data["user_cooldowns"]:
                        cooldown_time = format_remaining(data["user_cooldowns"][uid])

                    if cooldown_time == "0h 0m 0s":
                        cooldown_time = "Ready"

                    display_name = info.get("name", "Unknown")
                    lines.append(f"👤 {display_name} — {robbery_time} | CD: {cooldown_time}")
                except Exception as e:
                    print(f"Bad embed data for user {uid} at location {loc_id}: {e}")

            value = "\n".join(lines) if lines else "🟢 Nobody active"
        else:
            value = "🟢 Nobody active"

        embed.add_field(name=f"{num} | {name}", value=value, inline=False)

    embed.set_footer(text="Refreshes automatically every minute")
    return embed


# ------------------------
# PANELS
# ------------------------

async def add_panel(guild_id: int, channel_id: int, message_id: int) -> None:
    async with data_lock:
        data = load_data()

        exists = any(
            p.get("message_id") == message_id
            for p in data["panels"]
            if isinstance(p, dict)
        )

        if not exists:
            data["panels"].append({
                "guild_id": guild_id,
                "channel_id": channel_id,
                "message_id": message_id
            })
            save_data(data)


async def update_all_panels() -> None:
    try:
        async with data_lock:
            data = load_data()
            changed = clean_expired_in_memory(data)
            if changed:
                save_data(data)

            embed = build_embed_from_data(data)
            panels = list(data["panels"])

        valid_panels = []

        for panel in panels:
            try:
                channel_id = panel["channel_id"]
                message_id = panel["message_id"]

                channel = bot.get_channel(channel_id)
                if channel is None:
                    channel = await bot.fetch_channel(channel_id)

                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=RobberyView())
                valid_panels.append(panel)

            except discord.NotFound:
                print(f"Panel message/channel not found, removing: {panel}")
            except discord.Forbidden:
                print(f"No permission to edit panel, removing: {panel}")
            except Exception as e:
                print(f"Failed to update panel {panel.get('message_id', 'unknown')}: {e}")

        async with data_lock:
            fresh_data = load_data()
            if len(valid_panels) != len(fresh_data["panels"]):
                fresh_data["panels"] = valid_panels
                save_data(fresh_data)

    except Exception:
        print("update_all_panels crashed:")
        traceback.print_exc()


# ------------------------
# BUTTONS
# ------------------------

class RobberyButton(discord.ui.Button):
    def __init__(self, num: int):
        super().__init__(
            label=str(num),
            style=discord.ButtonStyle.secondary,
            custom_id=f"rob_{num}"
        )
        self.num = num

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        uid = str(user.id)
        loc_id = str(self.num)

        message_text = None

        async with data_lock:
            data = load_data()
            clean_expired_in_memory(data)

            if loc_id not in data["locations"]:
                data["locations"][loc_id] = {}

            if uid in data["locations"][loc_id]:
                data["locations"][loc_id].pop(uid, None)
                data["user_cooldowns"].pop(uid, None)

                if not data["locations"][loc_id]:
                    data["locations"].pop(loc_id, None)

                save_data(data)
                message_text = "Removed your timer."
            else:
                active_elsewhere = any(
                    uid in users
                    for users in data["locations"].values()
                    if isinstance(users, dict)
                )

                if active_elsewhere:
                    await interaction.followup.send(
                        "You already have an active robbery timer.",
                        ephemeral=True
                    )
                    return

                if uid in data["user_cooldowns"]:
                    cooldown_end = data["user_cooldowns"][uid]

                    if now() < parse_time(cooldown_end):
                        await interaction.followup.send(
                            f"You're on cooldown. Time left: {format_remaining(cooldown_end)}",
                            ephemeral=True
                        )
                        return
                    else:
                        data["user_cooldowns"].pop(uid, None)

                robbery_end = now() + timedelta(hours=24)
                cooldown_end = now() + timedelta(hours=1)

                data["locations"][loc_id][uid] = {
                    "name": user.display_name,
                    "end_time": robbery_end.isoformat()
                }

                data["user_cooldowns"][uid] = cooldown_end.isoformat()

                save_data(data)
                message_text = "Started robbery."

        await interaction.followup.send(message_text, ephemeral=True)
        await update_all_panels()


class RobberyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for num in locations:
            self.add_item(RobberyButton(num))


# ------------------------
# LOOP
# ------------------------

@tasks.loop(minutes=1)
async def updater():
    try:
        await update_all_panels()
    except Exception:
        print("Updater iteration failed:")
        traceback.print_exc()


@updater.before_loop
async def updater_before_loop():
    await bot.wait_until_ready()


@updater.error
async def updater_error(error):
    print("Updater loop error:")
    traceback.print_exception(type(error), error, error.__traceback__)


# ------------------------
# COMMANDS
# ------------------------

@bot.command()
async def robberies(ctx: commands.Context):
    async with data_lock:
        data = load_data()
        clean_expired_in_memory(data)
        save_data(data)
        embed = build_embed_from_data(data)

    message = await ctx.send(embed=embed, view=RobberyView())

    await add_panel(
        guild_id=ctx.guild.id if ctx.guild else 0,
        channel_id=ctx.channel.id,
        message_id=message.id
    )


# ------------------------
# EVENTS
# ------------------------

@bot.event
async def on_ready():
    try:
        bot.add_view(RobberyView())
    except Exception as e:
        print(f"Failed to add persistent view: {e}")

    if not updater.is_running():
        updater.start()

    print(f"Logged in as {bot.user} ({bot.user.id})")


# ------------------------
# START
# ------------------------

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set.")

bot.run(TOKEN)
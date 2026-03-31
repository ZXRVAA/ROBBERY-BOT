import asyncio
import json
import os
import traceback
from datetime import datetime, timedelta, timezone
from typing import Any

import discord
from discord.ext import commands, tasks

TOKEN = os.getenv("DISCORD_TOKEN")
DATA_FILE = "data.json"
ROBBERY_DURATION_HOURS = 24
COOLDOWN_HOURS = 1
UPDATE_INTERVAL_SECONDS = 10
DISCORD_REQUEST_TIMEOUT = 10

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
        total_seconds = max(0, int(remaining.total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}h {minutes}m {seconds}s"
    except Exception:
        return "0h 0m 0s"


# ------------------------
# DATA HELPERS
# ------------------------

def default_data() -> dict[str, Any]:
    return {
        "locations": {},
        "user_cooldowns": {},
        "panels": [],
    }


def normalize_data(data: Any) -> dict[str, Any]:
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


def load_data() -> dict[str, Any]:
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            return normalize_data(json.load(file))
    except Exception as exc:
        print(f"Failed to load {DATA_FILE}: {exc}")
        return default_data()


def save_data(data: dict[str, Any]) -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as file:
            json.dump(normalize_data(data), file, indent=4)
    except Exception as exc:
        print(f"Failed to save {DATA_FILE}: {exc}")


def clean_expired_in_memory(data: dict[str, Any]) -> bool:
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
            except Exception as exc:
                print(f"Bad robbery timer for user {uid} at location {loc_id}: {exc}")
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
        except Exception as exc:
            print(f"Bad cooldown for user {uid}: {exc}")
            data["user_cooldowns"].pop(uid, None)
            changed = True

    return changed


def user_has_active_timer(data: dict[str, Any], uid: str, loc_id: str | None = None) -> bool:
    if loc_id is not None:
        return uid in data["locations"].get(loc_id, {})

    return any(
        isinstance(users, dict) and uid in users
        for users in data["locations"].values()
    )


def get_user_active_locations(data: dict[str, Any], uid: str) -> list[str]:
    active_locations: list[str] = []

    for loc_id, users in data["locations"].items():
        if isinstance(users, dict) and uid in users:
            active_locations.append(loc_id)

    return active_locations


def start_user_timer(
    data: dict[str, Any],
    uid: str,
    display_name: str,
    loc_id: str,
) -> tuple[bool, str]:
    if loc_id not in data["locations"]:
        data["locations"][loc_id] = {}

    if user_has_active_timer(data, uid, loc_id):
        return False, "You already have an active timer at this location."

    cooldown_end = data["user_cooldowns"].get(uid)
    if cooldown_end and now() < parse_time(cooldown_end):
        return False, f"You're on cooldown. Time left: {format_remaining(cooldown_end)}"

    if cooldown_end:
        data["user_cooldowns"].pop(uid, None)

    robbery_end = now() + timedelta(hours=ROBBERY_DURATION_HOURS)
    next_cooldown_end = now() + timedelta(hours=COOLDOWN_HOURS)

    data["locations"][loc_id][uid] = {
        "name": display_name,
        "end_time": robbery_end.isoformat(),
    }
    data["user_cooldowns"][uid] = next_cooldown_end.isoformat()

    return True, f"Started robbery at location {loc_id}."


def remove_user_timer(data: dict[str, Any], uid: str, loc_id: str) -> tuple[bool, str]:
    users = data["locations"].get(loc_id)
    if not isinstance(users, dict) or uid not in users:
        return False, "You do not have an active timer at this location."

    users.pop(uid, None)

    if not users:
        data["locations"].pop(loc_id, None)

    # Removing a timer also clears the user's cooldown
    data["user_cooldowns"].pop(uid, None)

    return True, f"Removed your timer from location {loc_id}. Your cooldown was also cleared."


# ------------------------
# EMBED
# ------------------------

def build_embed_from_data(data: dict[str, Any]) -> discord.Embed:
    embed = discord.Embed(
        title="Robbery Locations (Global Sync)",
        description="Timers synced across all servers",
        color=0xFF0000,
    )

    for num, name in locations.items():
        loc_id = str(num)
        users = data["locations"].get(loc_id, {})

        if isinstance(users, dict) and users:
            lines: list[str] = []

            for uid, info in users.items():
                try:
                    robbery_time = format_remaining(info["end_time"])

                    cooldown_time = "Ready"
                    cooldown_end = data["user_cooldowns"].get(uid)
                    if cooldown_end:
                        cooldown_time = format_remaining(cooldown_end)
                        if cooldown_time == "0h 0m 0s":
                            cooldown_time = "Ready"

                    display_name = info.get("name", "Unknown")
                    lines.append(f"👤 {display_name} — {robbery_time} | CD: {cooldown_time}")
                except Exception as exc:
                    print(f"Bad embed data for user {uid} at location {loc_id}: {exc}")

            value = "\n".join(lines) if lines else "🟢 Nobody active"
        else:
            value = "🟢 Nobody active"

        embed.add_field(name=f"{num} | {name}", value=value, inline=False)

    embed.set_footer(text=f"Refreshes automatically every {UPDATE_INTERVAL_SECONDS} seconds")
    return embed


# ------------------------
# PANELS
# ------------------------

async def add_panel(guild_id: int, channel_id: int, message_id: int) -> None:
    async with data_lock:
        data = load_data()

        exists = any(
            isinstance(panel, dict) and panel.get("message_id") == message_id
            for panel in data["panels"]
        )

        if not exists:
            data["panels"].append(
                {
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "message_id": message_id,
                }
            )
            save_data(data)


async def update_single_panel(panel: dict[str, Any], embed: discord.Embed) -> dict[str, Any] | None:
    try:
        channel_id = panel["channel_id"]
        message_id = panel["message_id"]

        channel = bot.get_channel(channel_id)
        if channel is None:
            channel = await asyncio.wait_for(
                bot.fetch_channel(channel_id),
                timeout=DISCORD_REQUEST_TIMEOUT,
            )

        message = await asyncio.wait_for(
            channel.fetch_message(message_id),
            timeout=DISCORD_REQUEST_TIMEOUT,
        )

        await asyncio.wait_for(
            message.edit(embed=embed),
            timeout=DISCORD_REQUEST_TIMEOUT,
        )

        return panel

    except discord.NotFound:
        print(f"Panel message/channel not found, removing: {panel}")
        return None
    except discord.Forbidden:
        print(f"No permission to edit panel, removing: {panel}")
        return None
    except asyncio.TimeoutError:
        print(f"Timed out updating panel, keeping for retry: {panel}")
        return panel
    except Exception as exc:
        print(f"Failed to update panel {panel.get('message_id', 'unknown')}: {exc}")
        return panel


async def update_all_panels() -> None:
    try:
        async with data_lock:
            data = load_data()
            changed = clean_expired_in_memory(data)
            if changed:
                save_data(data)

            embed = build_embed_from_data(data)
            panels = list(data["panels"])

        if not panels:
            return

        results = await asyncio.gather(
            *(update_single_panel(panel, embed) for panel in panels),
            return_exceptions=False,
        )

        valid_panels = [panel for panel in results if panel is not None]

        async with data_lock:
            fresh_data = load_data()
            if fresh_data["panels"] != valid_panels:
                fresh_data["panels"] = valid_panels
                save_data(fresh_data)

    except Exception:
        print("update_all_panels crashed:")
        traceback.print_exc()


# ------------------------
# UI
# ------------------------

class RobberyButton(discord.ui.Button):
    def __init__(self, num: int):
        super().__init__(
            label=str(num),
            style=discord.ButtonStyle.secondary,
            custom_id=f"rob_{num}",
        )
        self.num = num

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        uid = str(user.id)
        loc_id = str(self.num)

        async with data_lock:
            data = load_data()
            changed = clean_expired_in_memory(data)
            if changed:
                save_data(data)

            if user_has_active_timer(data, uid, loc_id):
                _, message_text = remove_user_timer(data, uid, loc_id)
                save_data(data)
            else:
                started, message_text = start_user_timer(
                    data=data,
                    uid=uid,
                    display_name=user.display_name,
                    loc_id=loc_id,
                )

                if started:
                    active_count = len(get_user_active_locations(data, uid))
                    save_data(data)
                    message_text = f"{message_text} You now have {active_count} active timer(s)."

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

@tasks.loop(seconds=UPDATE_INTERVAL_SECONDS)
async def updater():
    started = now()
    try:
        await update_all_panels()
    except Exception:
        print("Updater iteration failed:")
        traceback.print_exc()
    finally:
        duration = (now() - started).total_seconds()
        print(f"Updater ran in {duration:.2f}s")


@updater.before_loop
async def updater_before_loop():
    await bot.wait_until_ready()


@updater.error
async def updater_error(error: Exception):
    print("Updater loop error:")
    traceback.print_exception(type(error), error, error.__traceback__)


# ------------------------
# COMMANDS
# ------------------------

@bot.command()
async def robberies(ctx: commands.Context):
    async with data_lock:
        data = load_data()
        changed = clean_expired_in_memory(data)
        if changed:
            save_data(data)
        embed = build_embed_from_data(data)

    message = await ctx.send(embed=embed, view=RobberyView())

    await add_panel(
        guild_id=ctx.guild.id if ctx.guild else 0,
        channel_id=ctx.channel.id,
        message_id=message.id,
    )


# ------------------------
# EVENTS
# ------------------------

@bot.event
async def on_ready():
    try:
        bot.add_view(RobberyView())
    except Exception as exc:
        print(f"Failed to add persistent view: {exc}")

    if not updater.is_running():
        updater.start()

    print(f"Logged in as {bot.user} ({bot.user.id})")


# ------------------------
# START
# ------------------------

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is not set.")

bot.run(TOKEN)
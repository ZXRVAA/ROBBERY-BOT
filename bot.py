import discord
from discord.ext import commands, tasks
import os
import json
import traceback
from datetime import datetime, timedelta, timezone

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"


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
    17: "Lemoyne | Fort Lemoyne"
}


# ------------------------
# TIME HELPERS
# ------------------------

def now():
    return datetime.now(timezone.utc)


def parse_time(iso_string: str) -> datetime:
    dt = datetime.fromisoformat(iso_string)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_remaining(end_time: str) -> str:
    remaining = parse_time(end_time) - now()
    total_seconds = int(remaining.total_seconds())

    if total_seconds <= 0:
        return "0h 0m 0s"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}h {minutes}m {seconds}s"


# ------------------------
# DATA
# ------------------------

def default_data():
    return {
        "locations": {},
        "user_cooldowns": {},
        "panels": []
    }


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # make sure keys exist even if file is older/broken
        data.setdefault("locations", {})
        data.setdefault("user_cooldowns", {})
        data.setdefault("panels", [])
        return data

    except Exception as e:
        print(f"Failed to load {DATA_FILE}: {e}")
        return default_data()


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"Failed to save {DATA_FILE}: {e}")


# ------------------------
# CLEANUP
# ------------------------

def clean_expired():
    data = load_data()
    current = now()
    changed = False

    # Remove expired robbery timers
    for loc_id, users in list(data["locations"].items()):
        for uid, info in list(users.items()):
            try:
                if current >= parse_time(info["end_time"]):
                    users.pop(uid, None)
                    changed = True
            except Exception as e:
                print(f"Bad robbery timer for user {uid} at location {loc_id}: {e}")
                users.pop(uid, None)
                changed = True

        if not users:
            data["locations"].pop(loc_id, None)
            changed = True

    # Remove expired user cooldowns
    for uid, end_time in list(data["user_cooldowns"].items()):
        try:
            if current >= parse_time(end_time):
                data["user_cooldowns"].pop(uid, None)
                changed = True
        except Exception as e:
            print(f"Bad cooldown for user {uid}: {e}")
            data["user_cooldowns"].pop(uid, None)
            changed = True

    if changed:
        save_data(data)


# ------------------------
# EMBED
# ------------------------

def build_embed():
    data = load_data()

    embed = discord.Embed(
        title="Robbery Locations (Global Sync)",
        description="Timers synced across all servers",
        color=0xff0000
    )

    for num, name in locations.items():
        loc_id = str(num)

        if loc_id in data["locations"] and data["locations"][loc_id]:
            lines = []

            for uid, info in data["locations"][loc_id].items():
                robbery_time = format_remaining(info["end_time"])

                cooldown_time = "Ready"
                if uid in data["user_cooldowns"]:
                    cooldown_time = format_remaining(data["user_cooldowns"][uid])

                if cooldown_time == "0h 0m 0s":
                    cooldown_time = "Ready"

                lines.append(
                    f"👤 {info['name']} — {robbery_time} | CD: {cooldown_time}"
                )

            value = "\n".join(lines)
        else:
            value = "🟢 Nobody active"

        embed.add_field(name=f"{num} | {name}", value=value, inline=False)

    embed.set_footer(text="Refreshes automatically")
    return embed


# ------------------------
# PANELS
# ------------------------

def add_panel(guild_id: int, channel_id: int, message_id: int):
    data = load_data()

    exists = any(p["message_id"] == message_id for p in data["panels"])
    if not exists:
        data["panels"].append({
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id
        })
        save_data(data)


async def update_all_panels():
    data = load_data()
    embed = build_embed()
    valid_panels = []

    for panel in data["panels"]:
        try:
            channel = bot.get_channel(panel["channel_id"])
            if channel is None:
                channel = await bot.fetch_channel(panel["channel_id"])

            message = await channel.fetch_message(panel["message_id"])
            await message.edit(embed=embed)
            valid_panels.append(panel)

        except discord.NotFound:
            print(f"Panel message not found, removing: {panel}")
        except discord.Forbidden:
            print(f"No permission to edit panel, removing: {panel}")
        except Exception as e:
            print(f"Failed to update panel {panel['message_id']}: {e}")

    if len(valid_panels) != len(data["panels"]):
        data["panels"] = valid_panels
        save_data(data)


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

        data = load_data()

        if loc_id not in data["locations"]:
            data["locations"][loc_id] = {}

        # If user already has this location active, remove it
        if uid in data["locations"][loc_id]:
            data["locations"][loc_id].pop(uid, None)
            data["user_cooldowns"].pop(uid, None)

            if not data["locations"][loc_id]:
                data["locations"].pop(loc_id, None)

            save_data(data)
            await interaction.followup.send("Removed your timer.", ephemeral=True)
            await update_all_panels()
            return

        # Block starting another robbery if user already has one active somewhere else
        for other_loc_id, users in data["locations"].items():
            if uid in users:
                await interaction.followup.send(
                    "You already have an active robbery timer.",
                    ephemeral=True
                )
                return

        # Cooldown check
        if uid in data["user_cooldowns"]:
            if now() < parse_time(data["user_cooldowns"][uid]):
                await interaction.followup.send(
                    f"You're on cooldown. Time left: {format_remaining(data['user_cooldowns'][uid])}",
                    ephemeral=True
                )
                return
            else:
                data["user_cooldowns"].pop(uid, None)

        # Start robbery
        robbery_end = now() + timedelta(hours=24)
        cooldown_end = now() + timedelta(hours=1)

        data["locations"][loc_id][uid] = {
            "name": user.display_name,
            "end_time": robbery_end.isoformat()
        }

        data["user_cooldowns"][uid] = cooldown_end.isoformat()

        save_data(data)

        await interaction.followup.send("Started robbery.", ephemeral=True)
        await update_all_panels()


class RobberyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for num in locations:
            self.add_item(RobberyButton(num))


# ------------------------
# LOOP
# ------------------------

@tasks.loop(seconds=5)
async def updater():
    clean_expired()
    await update_all_panels()


@updater.before_loop
async def updater_before_loop():
    await bot.wait_until_ready()


@updater.error
async def updater_error(error):
    print("Updater crashed:")
    traceback.print_exception(type(error), error, error.__traceback__)


# ------------------------
# COMMANDS
# ------------------------

@bot.command()
async def robberies(ctx):
    message = await ctx.send(embed=build_embed(), view=RobberyView())
    add_panel(
        guild_id=ctx.guild.id if ctx.guild else 0,
        channel_id=ctx.channel.id,
        message_id=message.id
    )


# ------------------------
# EVENTS
# ------------------------

@bot.event
async def on_ready():
    bot.add_view(RobberyView())

    if not updater.is_running():
        updater.start()

    print(f"Logged in as {bot.user} ({bot.user.id})")


# ------------------------
# START
# ------------------------

bot.run(TOKEN)
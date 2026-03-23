import discord
from discord.ext import commands, tasks
import os
import json
from datetime import datetime, timedelta

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "data.json"


# ------------------------
# ROBBERY LOCATIONS
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
# DATA FUNCTIONS
# ------------------------

def default_data():
    return {"guilds": {}}


def load_data():
    if not os.path.exists(DATA_FILE):
        return default_data()

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return default_data()

    if "guilds" not in data or not isinstance(data["guilds"], dict):
        data["guilds"] = {}

    return data


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)


def get_guild_data(data, guild_id: int):
    guild_id = str(guild_id)

    if guild_id not in data["guilds"]:
        data["guilds"][guild_id] = {
            "locations": {},
            "user_cooldowns": {},
            "panel": None
        }

    guild_data = data["guilds"][guild_id]

    if "locations" not in guild_data or not isinstance(guild_data["locations"], dict):
        guild_data["locations"] = {}

    if "user_cooldowns" not in guild_data or not isinstance(guild_data["user_cooldowns"], dict):
        guild_data["user_cooldowns"] = {}

    if "panel" not in guild_data:
        guild_data["panel"] = None

    return guild_data


# ------------------------
# TIME FORMATTER
# ------------------------

def utcnow():
    return datetime.utcnow()


def format_remaining(end_time):
    end = datetime.fromisoformat(end_time)
    now = utcnow()
    remaining = end - now

    if remaining.total_seconds() <= 0:
        return "0h 0m"

    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


# ------------------------
# CLEAN EXPIRED COOLDOWNS
# ------------------------

def clean_expired():
    data = load_data()
    now = utcnow()
    changed = False

    for guild_id, guild_data in list(data["guilds"].items()):
        locations_map = guild_data.get("locations", {})
        cooldowns = guild_data.get("user_cooldowns", {})

        # Remove expired robbery timers
        for loc_id, user_map in list(locations_map.items()):
            for user_id, timer_data in list(user_map.items()):
                end_time = timer_data.get("end_time")
                if not end_time:
                    locations_map[loc_id].pop(user_id, None)
                    changed = True
                    continue

                if now >= datetime.fromisoformat(end_time):
                    locations_map[loc_id].pop(user_id, None)
                    changed = True

            if not locations_map.get(loc_id):
                locations_map.pop(loc_id, None)
                changed = True

        # Remove expired personal cooldowns
        for user_id, end_time in list(cooldowns.items()):
            if now >= datetime.fromisoformat(end_time):
                cooldowns.pop(user_id, None)
                changed = True

    if changed:
        save_data(data)


# ------------------------
# EMBED
# ------------------------

def build_embed(guild_id: int):
    data = load_data()
    guild_data = get_guild_data(data, guild_id)

    embed = discord.Embed(
        title="Robbery Locations",
        description=(
            "Click a button to start or remove **your** timer for that location.\n"
            "Each player has their own 24-hour robbery timer and personal 1-hour cooldown.\n"
            "Removing your robbery timer also clears your personal 1-hour cooldown."
        ),
        color=0xff0000
    )

    active_users = len(guild_data["user_cooldowns"])
    embed.set_footer(text=f"Players currently on personal cooldown: {active_users}")

    for num, name in locations.items():
        loc_id = str(num)

        if loc_id in guild_data["locations"] and guild_data["locations"][loc_id]:
            entries = []

            for user_id, timer_data in guild_data["locations"][loc_id].items():
                username = timer_data.get("name", "Unknown")
                robbery_remaining = format_remaining(timer_data["end_time"])

                cooldown_text = "Ready"
                if user_id in guild_data["user_cooldowns"]:
                    cooldown_text = format_remaining(guild_data["user_cooldowns"][user_id])

                entries.append(
                    f"👤 {username} — Robbery: {robbery_remaining} | Cooldown: {cooldown_text}"
                )

            value = "\n".join(entries[:10])
            if len(entries) > 10:
                value += f"\n...and {len(entries) - 10} more"
        else:
            value = "🟢 Nobody active"

        embed.add_field(
            name=f"{num} | {name}",
            value=value,
            inline=False
        )

    return embed


# ------------------------
# VIEW / BUTTONS
# ------------------------

class RobberyButton(discord.ui.Button):
    def __init__(self, number: int):
        super().__init__(
            label=str(number),
            style=discord.ButtonStyle.secondary,
            custom_id=f"robbery_button_{number}"
        )
        self.number = number

    async def callback(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message(
                "This can only be used inside a server.",
                ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        user_id = str(user.id)
        guild_id = interaction.guild.id
        now = utcnow()

        data = load_data()
        guild_data = get_guild_data(data, guild_id)

        loc_id = str(self.number)

        if loc_id not in guild_data["locations"]:
            guild_data["locations"][loc_id] = {}

        # Remove this user's timer for this location and clear their personal cooldown
        if user_id in guild_data["locations"][loc_id]:
            guild_data["locations"][loc_id].pop(user_id, None)

            if not guild_data["locations"][loc_id]:
                guild_data["locations"].pop(loc_id, None)

            guild_data["user_cooldowns"].pop(user_id, None)

            save_data(data)

            await interaction.followup.send(
                f"Removed **your** timer for **{locations[self.number]}**.\n"
                f"Your personal 1-hour cooldown has been cleared.",
                ephemeral=True
            )

            await update_guild_panel(guild_id)
            return

        # Check user's personal cooldown for this guild
        if user_id in guild_data["user_cooldowns"]:
            end = datetime.fromisoformat(guild_data["user_cooldowns"][user_id])

            if now < end:
                remaining = format_remaining(guild_data["user_cooldowns"][user_id])

                await interaction.followup.send(
                    f"⏳ You are on cooldown.\nWait **{remaining}** before starting another robbery.",
                    ephemeral=True
                )
                return

        # Start robbery timer for this user in this guild
        guild_data["locations"][loc_id][user_id] = {
            "name": user.display_name,
            "end_time": (now + timedelta(hours=24)).isoformat()
        }

        guild_data["user_cooldowns"][user_id] = (now + timedelta(hours=1)).isoformat()

        save_data(data)

        await interaction.followup.send(
            f"💰 You started **{locations[self.number]}**.",
            ephemeral=True
        )

        await update_guild_panel(guild_id)


class RobberyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for num in locations:
            self.add_item(RobberyButton(num))


# ------------------------
# PANEL HELPERS
# ------------------------

async def fetch_panel_message(guild_id: int):
    data = load_data()
    guild_data = get_guild_data(data, guild_id)
    panel = guild_data.get("panel")

    if not panel:
        return None

    channel_id = panel.get("channel_id")
    message_id = panel.get("message_id")

    if not channel_id or not message_id:
        return None

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return None

    try:
        message = await channel.fetch_message(message_id)
        return message
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None


async def update_guild_panel(guild_id: int):
    message = await fetch_panel_message(guild_id)
    if message is None:
        return

    try:
        await message.edit(
            embed=build_embed(guild_id),
            view=RobberyView()
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


async def update_all_panels():
    data = load_data()

    for guild_id_str in list(data["guilds"].keys()):
        try:
            await update_guild_panel(int(guild_id_str))
        except Exception:
            pass


# ------------------------
# AUTO CLEAN LOOP
# ------------------------

@tasks.loop(seconds=30)
async def cooldown_watcher():
    clean_expired()
    await update_all_panels()


@cooldown_watcher.before_loop
async def before_cooldown_watcher():
    await bot.wait_until_ready()


# ------------------------
# COMMANDS
# ------------------------

@bot.command()
@commands.guild_only()
async def robberies(ctx):
    data = load_data()
    guild_data = get_guild_data(data, ctx.guild.id)

    embed = build_embed(ctx.guild.id)
    view = RobberyView()

    message = await ctx.send(embed=embed, view=view)

    guild_data["panel"] = {
        "channel_id": ctx.channel.id,
        "message_id": message.id
    }
    save_data(data)


# ------------------------
# STARTUP
# ------------------------

@bot.event
async def on_ready():
    bot.add_view(RobberyView())

    if not cooldown_watcher.is_running():
        cooldown_watcher.start()

    print(f"Logged in as {bot.user} ({bot.user.id})")
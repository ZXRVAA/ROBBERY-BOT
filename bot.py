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
panel_message = None


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

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "locations": {},
            "user_cooldowns": {}
        }

    with open(DATA_FILE, "r") as f:
        data = json.load(f)

    if "locations" not in data:
        data["locations"] = {}
    if "user_cooldowns" not in data:
        data["user_cooldowns"] = {}

    return data


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ------------------------
# TIME FORMATTER
# ------------------------

def format_remaining(end_time):
    end = datetime.fromisoformat(end_time)
    now = datetime.utcnow()
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
    now = datetime.utcnow()
    changed = False

    # Remove expired robbery timers
    for loc_id, user_map in list(data["locations"].items()):
        for user_id, timer_data in list(user_map.items()):
            if now >= datetime.fromisoformat(timer_data["end_time"]):
                data["locations"][loc_id].pop(user_id, None)
                changed = True

        if not data["locations"][loc_id]:
            data["locations"].pop(loc_id, None)
            changed = True

    # Remove expired personal cooldowns
    for user_id, end_time in list(data["user_cooldowns"].items()):
        if now >= datetime.fromisoformat(end_time):
            data["user_cooldowns"].pop(user_id, None)
            changed = True

    if changed:
        save_data(data)


# ------------------------
# BUTTON
# ------------------------

class RobberyButton(discord.ui.Button):
    def __init__(self, number):
        super().__init__(label=str(number), style=discord.ButtonStyle.secondary)
        self.number = number

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        user = interaction.user
        user_id = str(user.id)
        now = datetime.utcnow()

        data = load_data()
        loc_id = str(self.number)

        if loc_id not in data["locations"]:
            data["locations"][loc_id] = {}

        # REMOVE ONLY THIS USER'S TIMER FOR THIS LOCATION
        # Keep their personal cooldown untouched
        if user_id in data["locations"][loc_id]:
            data["locations"][loc_id].pop(user_id, None)

            if not data["locations"][loc_id]:
                data["locations"].pop(loc_id, None)

            save_data(data)

            await interaction.followup.send(
                f"Removed **your** timer for **{locations[self.number]}**.\n"
                f"Your personal 1-hour cooldown is unchanged.",
                ephemeral=True
            )

            await update_panel()
            return

        # CHECK THIS USER'S PERSONAL COOLDOWN
        if user_id in data["user_cooldowns"]:
            end = datetime.fromisoformat(data["user_cooldowns"][user_id])

            if now < end:
                remaining = format_remaining(data["user_cooldowns"][user_id])

                await interaction.followup.send(
                    f"⏳ You are on cooldown.\nWait **{remaining}** before starting another robbery.",
                    ephemeral=True
                )
                return

        # START TIMER FOR THIS USER ONLY
        data["locations"][loc_id][user_id] = {
            "name": user.display_name,
            "end_time": (now + timedelta(hours=24)).isoformat()
        }

        data["user_cooldowns"][user_id] = (now + timedelta(hours=1)).isoformat()

        save_data(data)

        await interaction.followup.send(
            f"💰 You started **{locations[self.number]}**.",
            ephemeral=True
        )

        await update_panel()


# ------------------------
# VIEW
# ------------------------

class RobberyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for num in locations:
            self.add_item(RobberyButton(num))


# ------------------------
# EMBED
# ------------------------

def build_embed():
    data = load_data()

    embed = discord.Embed(
        title="Robbery Locations",
        description=(
            "Click a button to start or remove **your** timer for that location.\n"
            "Each player has their own 24-hour robbery timers and personal 1-hour cooldown.\n"
            "Removing a robbery timer does **not** remove your 1-hour cooldown."
        ),
        color=0xff0000
    )

    active_users = len(data["user_cooldowns"])
    embed.set_footer(text=f"Players currently on personal cooldown: {active_users}")

    for num, name in locations.items():
        loc_id = str(num)

        if loc_id in data["locations"] and data["locations"][loc_id]:
            entries = []

            for user_id, timer_data in data["locations"][loc_id].items():
                username = timer_data.get("name", "Unknown")
                robbery_remaining = format_remaining(timer_data["end_time"])

                cooldown_text = "Ready"
                if user_id in data["user_cooldowns"]:
                    cooldown_text = format_remaining(data["user_cooldowns"][user_id])

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
# PANEL UPDATE
# ------------------------

async def update_panel():
    global panel_message

    if panel_message is None:
        return

    embed = build_embed()
    view = RobberyView()

    await panel_message.edit(embed=embed, view=view)


# ------------------------
# AUTO CLEAN LOOP
# ------------------------

@tasks.loop(seconds=30)
async def cooldown_watcher():
    clean_expired()
    await update_panel()


@cooldown_watcher.before_loop
async def before_loop():
    await bot.wait_until_ready()


# ------------------------
# COMMAND
# ------------------------

@bot.command()
async def robberies(ctx):
    global panel_message

    embed = build_embed()
    view = RobberyView()

    panel_message = await ctx.send(embed=embed, view=view)


# ------------------------
# STARTUP
# ------------------------

@bot.event
async def on_ready():
    cooldown_watcher.start()
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
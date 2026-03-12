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
# DATA
# ------------------------

def load_data():

    if not os.path.exists(DATA_FILE):
        return {
            "locations": {},
            "robbers": {},
            "global_cooldown": None
        }

    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ------------------------
# CLEAN EXPIRED TIMERS
# ------------------------

def clean_expired():

    data = load_data()
    now = datetime.utcnow()

    changed = False

    # clean location timers
    expired = []
    for loc, end in data["locations"].items():
        if now >= datetime.fromisoformat(end):
            expired.append(loc)

    for loc in expired:
        data["locations"].pop(loc, None)
        data["robbers"].pop(loc, None)
        changed = True

    # clean global cooldown
    if data["global_cooldown"]:
        if now >= datetime.fromisoformat(data["global_cooldown"]):
            data["global_cooldown"] = None
            changed = True

    if changed:
        save_data(data)


# ------------------------
# TIME FORMAT
# ------------------------

def format_time(end):

    remaining = datetime.fromisoformat(end) - datetime.utcnow()
    seconds = int(remaining.total_seconds())

    if seconds <= 0:
        return "Available"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    return f"{hours}h {minutes}m"


# ------------------------
# GLOBAL COOLDOWN
# ------------------------

def get_global_cd():

    clean_expired()

    data = load_data()

    if not data["global_cooldown"]:
        return "Available"

    return format_time(data["global_cooldown"])


# ------------------------
# BUTTON
# ------------------------

class RobberyButton(discord.ui.Button):

    def __init__(self, number):

        super().__init__(label=str(number))
        self.number = number
        self.update_color()

    def update_color(self):

        data = load_data()

        if str(self.number) in data["locations"]:
            self.style = discord.ButtonStyle.danger
        else:
            self.style = discord.ButtonStyle.success

    async def callback(self, interaction: discord.Interaction):

        await interaction.response.defer(ephemeral=True)

        clean_expired()

        user = interaction.user
        now = datetime.utcnow()

        data = load_data()

        locs = data["locations"]
        robbers = data["robbers"]
        global_cd = data["global_cooldown"]

        num = str(self.number)

        # ------------------------
        # REMOVE TIMER + GLOBAL CD
        # ------------------------

        if num in locs:

            del locs[num]
            robbers.pop(num, None)

            data["global_cooldown"] = None

            save_data(data)

            await interaction.followup.send(
                f"Cooldown removed for **{locations[self.number]}**",
                ephemeral=True
            )

            await update_panel()
            return

        # ------------------------
        # CHECK GLOBAL COOLDOWN
        # ------------------------

        if global_cd:

            if now < datetime.fromisoformat(global_cd):

                remaining = format_time(global_cd)

                await interaction.followup.send(
                    f"⏳ Global cooldown active\nWait **{remaining}**",
                    ephemeral=True
                )
                return

        # ------------------------
        # START ROBBERY
        # ------------------------

        locs[num] = (now + timedelta(hours=24)).isoformat()
        robbers[num] = user.display_name
        data["global_cooldown"] = (now + timedelta(hours=1)).isoformat()

        save_data(data)

        await interaction.followup.send(
            f"💰 **{locations[self.number]} robbed by {user.display_name}!**"
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

    clean_expired()

    data = load_data()

    embed = discord.Embed(
        title="Robbery Locations",
        description=f"🟢 Available | 🔴 Robbed\n\n⏳ Global Cooldown: **{get_global_cd()}**",
        color=0xff0000
    )

    for num, name in locations.items():

        if str(num) in data["locations"]:

            remaining = format_time(data["locations"][str(num)])
            robber = data["robbers"].get(str(num), "Unknown")

            value = f"🔴 {remaining}\n👤 {robber}"

        else:

            value = "🟢 Available"

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

    if not panel_message:
        return

    embed = build_embed()
    view = RobberyView()

    await panel_message.edit(embed=embed, view=view)


# ------------------------
# AUTO REFRESH
# ------------------------

@tasks.loop(minutes=1)
async def refresh_panel():

    await update_panel()


# ------------------------
# EVENTS
# ------------------------

@bot.event
async def on_ready():

    refresh_panel.start()

    print(f"Logged in as {bot.user}")


# ------------------------
# COMMAND
# ------------------------

@bot.command()
async def robberies(ctx):

    global panel_message

    embed = build_embed()
    view = RobberyView()

    panel_message = await ctx.send(embed=embed, view=view)


bot.run(TOKEN)
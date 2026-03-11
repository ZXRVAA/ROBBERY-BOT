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


def load_data():
    if not os.path.exists(DATA_FILE):
        return {"cooldowns": {}, "locations": {}, "users": {}}

    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f)


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


def format_time(end_time):

    remaining = datetime.fromisoformat(end_time) - datetime.utcnow()
    seconds = int(remaining.total_seconds())

    if seconds <= 0:
        return "Available"

    hours = seconds // 3600
    minutes = (seconds % 3600) // 60

    return f"{hours}h {minutes}m"


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

        user = interaction.user
        now = datetime.utcnow()

        data = load_data()

        cooldowns = data["cooldowns"]
        locs = data["locations"]
        users = data["users"]

        num = str(self.number)
        uid = str(user.id)

        # REMOVE TIMER
        if num in locs:

            del locs[num]
            users.pop(num, None)

            save_data(data)

            await interaction.response.send_message(
                f"Timer removed for **{locations[self.number]}**",
                ephemeral=True
            )

            await update_panel()
            return

        # CHECK COOLDOWN
        if uid in cooldowns:

            end = datetime.fromisoformat(cooldowns[uid])

            if now < end:

                remaining = format_time(cooldowns[uid])

                await interaction.response.send_message(
                    f"Wait **{remaining}** before robbing again.",
                    ephemeral=True
                )
                return

        # START ROBBERY
        locs[num] = (now + timedelta(hours=24)).isoformat()
        users[num] = user.display_name

        cooldowns[uid] = (now + timedelta(hours=1)).isoformat()

        save_data(data)

        await interaction.response.send_message(
            f"💰 **{locations[self.number]} robbed by {user.display_name}!**"
        )

        await update_panel()


class RobberyView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=None)

        for num in locations:
            self.add_item(RobberyButton(num))


def build_embed():

    data = load_data()

    embed = discord.Embed(
        title="Robbery Locations",
        description="🟢 Available | 🔴 Robbed",
        color=0xff0000
    )

    for num, name in locations.items():

        if str(num) in data["locations"]:

            remaining = format_time(data["locations"][str(num)])
            robber = data["users"].get(str(num), "Unknown")

            value = f"🔴 {remaining}\n👤 {robber}"

        else:
            value = "🟢 Available"

        embed.add_field(name=f"{num} | {name}", value=value, inline=False)

    return embed


async def update_panel():

    global panel_message

    if panel_message is None:
        return

    embed = build_embed()
    view = RobberyView()

    await panel_message.edit(embed=embed, view=view)


@tasks.loop(minutes=1)
async def refresh_panel():

    await update_panel()


@bot.event
async def on_ready():

    refresh_panel.start()

    print(f"Logged in as {bot.user}")


@bot.command()
async def robberies(ctx):

    global panel_message

    embed = build_embed()
    view = RobberyView()

    panel_message = await ctx.send(embed=embed, view=view)


bot.run(TOKEN)
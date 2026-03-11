import discord
from discord.ext import commands
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

user_cooldowns = {}
location_timers = {}
location_users = {}

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


def format_time(end_time):
    remaining = end_time - datetime.utcnow()
    total_seconds = int(remaining.total_seconds())

    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60

    return f"{hours}h {minutes}m"


class RobberyButton(discord.ui.Button):
    def __init__(self, number):
        super().__init__(label=str(number), style=discord.ButtonStyle.primary)
        self.number = number

    async def callback(self, interaction: discord.Interaction):

        user = interaction.user
        now = datetime.utcnow()

        # Remove timer if location already robbed
        if self.number in location_timers:

            end_time = location_timers[self.number]
            remaining = format_time(end_time)

            del location_timers[self.number]
            location_users.pop(self.number, None)

            await interaction.response.send_message(
                f"⛔ Timer removed for **{locations[self.number]}**\n"
                f"Remaining time was **{remaining}**",
                ephemeral=True
            )
            return

        # Check user cooldown
        if user.id in user_cooldowns:

            if now < user_cooldowns[user.id]:

                remaining = format_time(user_cooldowns[user.id])

                await interaction.response.send_message(
                    f"⏳ You must wait **{remaining}** before another robbery.",
                    ephemeral=True
                )
                return

        # Start timers
        location_timers[self.number] = now + timedelta(hours=24)
        location_users[self.number] = user.display_name

        user_cooldowns[user.id] = now + timedelta(hours=1)

        await interaction.response.send_message(
            f"💰 **{locations[self.number]} robbed by {user.display_name}!**\n"
            f"Cooldown: **24h 0m**"
        )


class RobberyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for num in locations:
            self.add_item(RobberyButton(num))


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")


@bot.command()
async def robberies(ctx):

    embed = discord.Embed(
        title="Robbery Locations",
        description="Click a number to rob.\nClick again to remove timer.",
        color=0xff0000
    )

    for num, name in locations.items():

        if num in location_timers:

            remaining = format_time(location_timers[num])
            robber = location_users.get(num, "Unknown")

            value = f"⏳ {remaining}\n👤 {robber}"

        else:
            value = "✅ Available"

        embed.add_field(name=f"{num} | {name}", value=value, inline=False)

    await ctx.send(embed=embed, view=RobberyView())


bot.run(TOKEN)
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
# DATA
# ------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"locations": {}, "user_cooldowns": {}, "panels": []}

    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=4)


# ------------------------
# TIME (H:M:S)
# ------------------------

def now():
    return datetime.utcnow()


def format_time(end_time: str):
    end = datetime.fromisoformat(end_time)
    remaining = end - now()

    total_seconds = int(remaining.total_seconds())

    if total_seconds <= 0:
        return "0h 0m 0s"

    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    return f"{hours}h {minutes}m {seconds}s"


# ------------------------
# CLEANUP
# ------------------------

def clean_expired():
    data = load_data()
    current = now()
    changed = False

    for loc_id, users in list(data["locations"].items()):
        for uid, t in list(users.items()):
            if current >= datetime.fromisoformat(t["end_time"]):
                users.pop(uid)
                changed = True

        if not users:
            data["locations"].pop(loc_id)
            changed = True

    for uid, t in list(data["user_cooldowns"].items()):
        if current >= datetime.fromisoformat(t):
            data["user_cooldowns"].pop(uid)
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

        if loc_id in data["locations"]:
            lines = []

            for uid, t in data["locations"][loc_id].items():
                rob = format_time(t["end_time"])

                cd = "Ready"
                if uid in data["user_cooldowns"]:
                    cd = format_time(data["user_cooldowns"][uid])

                lines.append(f"👤 {t['name']} — {rob} | CD: {cd}")

            value = "\n".join(lines)
        else:
            value = "🟢 Nobody active"

        embed.add_field(name=f"{num} | {name}", value=value, inline=False)

    return embed


# ------------------------
# PANELS
# ------------------------

def add_panel(guild_id, channel_id, message_id):
    data = load_data()

    if not any(p["message_id"] == message_id for p in data["panels"]):
        data["panels"].append({
            "guild_id": guild_id,
            "channel_id": channel_id,
            "message_id": message_id
        })
        save_data(data)


async def update_all_panels():
    data = load_data()
    embed = build_embed()
    view = RobberyView()

    valid = []

    for p in data["panels"]:
        try:
            channel = bot.get_channel(p["channel_id"]) or await bot.fetch_channel(p["channel_id"])
            msg = await channel.fetch_message(p["message_id"])

            await msg.edit(embed=embed, view=view)
            valid.append(p)

        except:
            continue

    if len(valid) != len(data["panels"]):
        data["panels"] = valid
        save_data(data)


# ------------------------
# BUTTON
# ------------------------

class RobberyButton(discord.ui.Button):
    def __init__(self, num):
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
        data = load_data()
        loc = str(self.num)

        if loc not in data["locations"]:
            data["locations"][loc] = {}

        # REMOVE
        if uid in data["locations"][loc]:
            data["locations"][loc].pop(uid)
            data["user_cooldowns"].pop(uid, None)

            if not data["locations"][loc]:
                data["locations"].pop(loc)

            save_data(data)

            await interaction.followup.send("Removed your timer.", ephemeral=True)
            await update_all_panels()
            return

        # COOLDOWN CHECK
        if uid in data["user_cooldowns"]:
            if now() < datetime.fromisoformat(data["user_cooldowns"][uid]):
                await interaction.followup.send("You're on cooldown.", ephemeral=True)
                return

        # START
        data["locations"][loc][uid] = {
            "name": user.display_name,
            "end_time": (now() + timedelta(hours=24)).isoformat()
        }

        data["user_cooldowns"][uid] = (
            now() + timedelta(hours=1)
        ).isoformat()

        save_data(data)

        await interaction.followup.send("Started robbery.", ephemeral=True)
        await update_all_panels()


# ------------------------
# VIEW
# ------------------------

class RobberyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

        for i in locations:
            self.add_item(RobberyButton(i))


# ------------------------
# LOOP (FAST FOR SECONDS)
# ------------------------

@tasks.loop(seconds=1)
async def updater():
    clean_expired()
    await update_all_panels()


@updater.before_loop
async def before():
    await bot.wait_until_ready()


# ------------------------
# COMMAND
# ------------------------

@bot.command()
async def robberies(ctx):
    msg = await ctx.send(embed=build_embed(), view=RobberyView())
    add_panel(ctx.guild.id, ctx.channel.id, msg.id)


# ------------------------
# STARTUP
# ------------------------

@bot.event
async def on_ready():
    bot.add_view(RobberyView())
    updater.start()
    print(f"Logged in as {bot.user}")


bot.run(TOKEN)
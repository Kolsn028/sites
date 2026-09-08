import os
import discord
from dotenv import load_dotenv

from bot.core import ColomboBot
from bot.database import Database
from bot.commands import register_commands

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не задан. Создай .env по примеру .env.example")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = ColomboBot(command_prefix="!", intents=intents, db=Database("data/bot.db"))
register_commands(bot)
bot.run(TOKEN)

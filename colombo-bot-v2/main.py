import os
import discord
from dotenv import load_dotenv

load_dotenv()

from bot.core import ColomboBot
from bot.database import Database
from bot.commands import register_commands

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не задан. Создай .env по примеру .env.example")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = ColomboBot(command_prefix="!", intents=intents, db=Database(os.getenv("DATABASE_PATH", "data/bot.db")), allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True))
register_commands(bot)
bot.run(TOKEN)

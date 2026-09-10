import os
import discord
from dotenv import load_dotenv

load_dotenv()

from bot.core import ColomboBot
from bot.database import Database
from bot.commands import register_commands

from pathlib import Path
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/bot.db")
# This upgrade must never replace the user's existing history with an empty database.
if os.getenv("RAILWAY_ENVIRONMENT_ID") and not Path(DATABASE_PATH).is_file():
    raise RuntimeError("Existing database required. Restore the verified SQLite backup on the persistent volume before deployment.")

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не задан. Создай .env по примеру .env.example")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = ColomboBot(command_prefix="!", intents=intents, db=Database(DATABASE_PATH), allowed_mentions=discord.AllowedMentions.none())
register_commands(bot)
bot.run(TOKEN)

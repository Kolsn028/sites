import os
import discord
from dotenv import load_dotenv

load_dotenv()

from bot.core import ColomboBot
from bot.database import Database
from bot.commands import register_commands

# User-approved fresh v9 database. Existing v9 data is reopened, never deleted on restart.
DATABASE_PATH = os.getenv("DATABASE_PATH", "data/colombo-v9.db")
print(f"Database storage: path={DATABASE_PATH} data_mount={os.path.ismount(os.path.abspath('data'))}", flush=True)

TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN не задан. Создай .env по примеру .env.example")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = ColomboBot(command_prefix="!", intents=intents, db=Database(DATABASE_PATH), allowed_mentions=discord.AllowedMentions.none())
register_commands(bot)
bot.run(TOKEN)

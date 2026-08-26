import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from club_management import OfferView, setup as setup_club_management
from database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO)


class ProClubsBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.database = Database(os.getenv("DATABASE_PATH", "pro_clubs.db"))

    async def setup_hook(self) -> None:
        self.database.setup()
        await setup_club_management(self, self.database)

        for offer in self.database.pending_offers():
            self.add_view(OfferView(self, self.database, offer["id"]), message_id=offer["message_id"])

        test_guild_id = os.getenv("TEST_GUILD_ID", "").strip()
        if test_guild_id:
            guild = discord.Object(id=int(test_guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Synced commands to test guild %s", test_guild_id)
        else:
            await self.tree.sync()
            logging.info("Synced global commands")

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add your token.")

ProClubsBot().run(token)


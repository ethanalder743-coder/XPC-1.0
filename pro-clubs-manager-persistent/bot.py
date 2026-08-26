import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from club_management import OfferView, setup as setup_club_management
from dashboard import Dashboard
from database import Database

load_dotenv()
logging.basicConfig(level=logging.INFO)


class ProClubsBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        database_path = os.getenv("DATABASE_PATH", "").strip()
        on_railway = bool(
            os.getenv("RAILWAY_PROJECT_ID")
            or os.getenv("RAILWAY_ENVIRONMENT_ID")
            or os.getenv("RAILWAY_ENVIRONMENT")
        )
        if on_railway and not database_path.startswith("/data/"):
            logging.warning(
                "Railway database path %r is not persistent; forcing /data/pro_clubs.db",
                database_path or "(unset)",
            )
            database_path = "/data/pro_clubs.db"
        elif not database_path:
            database_path = "pro_clubs.db"
        self.database = Database(database_path)
        logging.info("Using database at %s", database_path)
        self.sync_task: asyncio.Task | None = None
        self.dashboard = Dashboard(self, self.database)

    async def setup_hook(self) -> None:
        self.database.setup()
        await setup_club_management(self, self.database)
        await self.dashboard.start()

        for offer in self.database.pending_offers():
            self.add_view(OfferView(self, self.database, offer["id"]), message_id=offer["message_id"])

    async def on_ready(self) -> None:
        logging.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")
        if self.sync_task is None:
            self.sync_task = asyncio.create_task(self.sync_commands())

    async def on_interaction(self, interaction: discord.Interaction) -> None:
        if interaction.type in (discord.InteractionType.component, discord.InteractionType.modal_submit):
            custom_id = str(interaction.data.get("custom_id", "component")) if interaction.data else "component"
            self.database.add_audit(
                interaction.guild_id,
                interaction.user.id,
                "Component used",
                custom_id,
            )

    async def sync_commands(self) -> None:
        """Sync without delaying the bot's connection to Discord."""
        try:
            test_guild_id = os.getenv("TEST_GUILD_ID", "").strip()
            if test_guild_id:
                guild = discord.Object(id=int(test_guild_id))
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logging.info("Synced commands to test guild %s", test_guild_id)
            else:
                await self.tree.sync()
                logging.info("Synced global commands")
        except discord.HTTPException:
            logging.exception("Command sync failed; the bot will remain online using existing commands")


token = os.getenv("DISCORD_TOKEN")
if not token:
    raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add your token.")

ProClubsBot().run(token)


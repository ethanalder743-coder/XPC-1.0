import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import Database


def manager_only():
    return app_commands.checks.has_permissions(manage_roles=True)


class OfferView(discord.ui.View):
    def __init__(self, bot: commands.Bot, database: Database, offer_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.db = database
        self.offer_id = offer_id

        accept = discord.ui.Button(
            label="Accept",
            style=discord.ButtonStyle.success,
            custom_id=f"club_offer:accept:{offer_id}",
        )
        deny = discord.ui.Button(
            label="Deny",
            style=discord.ButtonStyle.danger,
            custom_id=f"club_offer:deny:{offer_id}",
        )
        accept.callback = self.accept
        deny.callback = self.deny
        self.add_item(accept)
        self.add_item(deny)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        offer = self.db.offer(self.offer_id)
        if offer is None or offer["status"] != "pending":
            await interaction.response.send_message("This offer is no longer pending.", ephemeral=True)
            return False
        if interaction.user.id != offer["player_id"]:
            await interaction.response.send_message("Only the offered player can use these buttons.", ephemeral=True)
            return False
        return True

    async def accept(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        offer = self.db.offer(self.offer_id)
        if offer is None or interaction.guild is None:
            await interaction.followup.send("This offer could not be found.", ephemeral=True)
            return

        role = interaction.guild.get_role(offer["role_id"])
        member = interaction.guild.get_member(offer["player_id"])
        if role is None or member is None:
            await interaction.followup.send("The player or team role no longer exists.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason=f"Accepted club offer #{self.offer_id}")
        except discord.Forbidden:
            await interaction.followup.send(
                "I cannot assign that role. Put my bot role above the team role.", ephemeral=True
            )
            return

        if not self.db.decide_offer(self.offer_id, "accepted"):
            await interaction.followup.send("This offer was already handled.", ephemeral=True)
            return
        await self.finish(interaction, "Accepted", discord.Color.green())
        await interaction.followup.send("Offer accepted — welcome to the club!", ephemeral=True)
        await self.log_signing(interaction, member, role, offer)

    async def deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.db.decide_offer(self.offer_id, "denied"):
            await interaction.followup.send("This offer was already handled.", ephemeral=True)
            return
        await self.finish(interaction, "Denied", discord.Color.red())
        await interaction.followup.send("Offer denied.", ephemeral=True)

    async def finish(self, interaction: discord.Interaction, result: str, color: discord.Color) -> None:
        for child in self.children:
            child.disabled = True
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else discord.Embed()
        embed.color = color
        embed.add_field(name="Status", value=result, inline=False)
        if interaction.message:
            await interaction.message.edit(embed=embed, view=self)

    async def log_signing(self, interaction, member, role, offer) -> None:
        config = self.db.config(offer["guild_id"])
        if not config:
            return
        channel = interaction.guild.get_channel(config["signing_channel_id"])
        if isinstance(channel, discord.TextChannel):
            await channel.send(
                embed=discord.Embed(
                    title="Player Signed",
                    description=f"{member.mention} has signed for {role.mention}.",
                    color=discord.Color.green(),
                )
            )


class ClubManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, database: Database) -> None:
        self.bot = bot
        self.db = database

    async def team_autocomplete(self, interaction: discord.Interaction, current: str):
        if interaction.guild_id is None:
            return []
        current = current.casefold()
        return [
            app_commands.Choice(name=row["name"], value=row["name"])
            for row in self.db.teams(interaction.guild_id)
            if current in row["name"].casefold()
        ][:25]

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You do not have permission to use this command."
        elif isinstance(error, app_commands.BotMissingPermissions):
            message = "I am missing a Discord permission needed for this command."
        else:
            message = "Something went wrong while running that command. Check the bot console for details."
            raise error
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="offer", description="Send a player an offer from a configured team")
    @app_commands.guild_only()
    @manager_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def offer(self, interaction: discord.Interaction, player: discord.Member, team: str):
        assert interaction.guild and interaction.channel
        record = self.db.team(interaction.guild.id, team)
        if not record:
            await interaction.response.send_message("That team is not configured.", ephemeral=True)
            return
        role = interaction.guild.get_role(record["role_id"])
        if role is None:
            await interaction.response.send_message("That team's role was deleted. Ask an admin to fix it.", ephemeral=True)
            return
        if player.bot:
            await interaction.response.send_message("You cannot offer a bot.", ephemeral=True)
            return

        offer_id = self.db.create_offer(
            interaction.guild.id, player.id, record["name"], role.id,
            interaction.user.id, interaction.channel.id,
        )
        view = OfferView(self.bot, self.db, offer_id)
        embed = discord.Embed(
            title="Club Offer",
            description=f"{player.mention}, you have received an offer from {role.mention}.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Offered by", value=interaction.user.mention)
        embed.set_footer(text=f"Offer #{offer_id}")
        await interaction.response.send_message(content=player.mention, embed=embed, view=view)
        message = await interaction.original_response()
        self.db.set_offer_message(offer_id, message.id)

    @app_commands.command(name="release", description="Remove a configured team role from a player")
    @app_commands.guild_only()
    @manager_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def release(self, interaction: discord.Interaction, player: discord.Member, team: str, reason: str = "No reason provided"):
        assert interaction.guild
        record = self.db.team(interaction.guild.id, team)
        role = interaction.guild.get_role(record["role_id"]) if record else None
        if record is None or role is None:
            await interaction.response.send_message("That team is not configured correctly.", ephemeral=True)
            return
        if role not in player.roles:
            await interaction.response.send_message(f"{player.mention} does not have that team role.", ephemeral=True)
            return
        try:
            await player.remove_roles(role, reason=f"Released by {interaction.user}: {reason}")
        except discord.Forbidden:
            await interaction.response.send_message("I cannot remove that role. Check my role position.", ephemeral=True)
            return
        await interaction.response.send_message(f"Released {player.mention} from {role.mention}.", ephemeral=True)
        config = self.db.config(interaction.guild.id)
        channel = interaction.guild.get_channel(config["release_channel_id"]) if config else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=discord.Embed(
                title="Player Released",
                description=f"{player.mention} has been released from {role.mention}.\n**Reason:** {reason}",
                color=discord.Color.orange(),
            ))

    team_group = app_commands.Group(name="team", description="Configure club teams", guild_only=True)

    @team_group.command(name="add", description="Connect a team name to a Discord role")
    @app_commands.checks.has_permissions(administrator=True)
    async def team_add(self, interaction: discord.Interaction, name: str, role: discord.Role):
        if role.is_default() or role.managed:
            await interaction.response.send_message("Choose a normal assignable role.", ephemeral=True)
            return
        try:
            self.db.add_team(interaction.guild_id, name, role.id)
        except sqlite3.IntegrityError:
            await interaction.response.send_message("That team name or role is already configured.", ephemeral=True)
            return
        await interaction.response.send_message(f"Added **{name.strip()}** using {role.mention}.", ephemeral=True)

    @team_group.command(name="remove", description="Remove a configured team")
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(name=team_autocomplete)
    async def team_remove(self, interaction: discord.Interaction, name: str):
        removed = self.db.remove_team(interaction.guild_id, name)
        text = f"Removed **{name}**." if removed else "That team was not found."
        await interaction.response.send_message(text, ephemeral=True)

    @team_group.command(name="list", description="List configured teams")
    async def team_list(self, interaction: discord.Interaction):
        teams = self.db.teams(interaction.guild_id)
        text = "\n".join(f"• **{row['name']}** — <@&{row['role_id']}>" for row in teams)
        await interaction.response.send_message(text or "No teams are configured yet.", ephemeral=True)

    @app_commands.command(name="config_logs", description="Set signing and release log channels")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def config_logs(self, interaction: discord.Interaction, signing_channel: discord.TextChannel, release_channel: discord.TextChannel):
        self.db.configure_logs(interaction.guild_id, signing_channel.id, release_channel.id)
        await interaction.response.send_message(
            f"Signing logs: {signing_channel.mention}\nRelease logs: {release_channel.mention}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot, database: Database) -> None:
    await bot.add_cog(ClubManagement(bot, database))

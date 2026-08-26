import re
import sqlite3

import discord
from discord import app_commands
from discord.ext import commands

from database import Database


def get_player_roster(database: Database, guild: discord.Guild, role: discord.Role, team_name: str):
    """Return only players recorded after accepting an offer."""
    members = []
    for player_id in database.team_member_ids(guild.id, team_name):
        member = guild.get_member(player_id)
        if member and not member.bot and role in member.roles:
            members.append(member)
    return members


def roster_text(roster: list[discord.Member]) -> str:
    text = ", ".join(member.mention for member in roster[:20]) or "No signed players yet"
    if len(roster) > 20:
        text += f" and {len(roster) - 20} more"
    return text


def inline_team_logo(team) -> str:
    return f"<:clublogo:{team['emoji_id']}> " if team and team["emoji_id"] else ""


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
        if offer is None:
            await interaction.followup.send("This offer could not be found.", ephemeral=True)
            return

        guild = self.bot.get_guild(offer["guild_id"])
        if guild is None:
            await interaction.followup.send("I can no longer find the Discord server.", ephemeral=True)
            return
        role = guild.get_role(offer["role_id"])
        member = guild.get_member(offer["player_id"])
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
        self.db.add_team_member(guild.id, offer["team_name"], member.id)
        await self.finish(interaction, "accepted")
        await interaction.followup.send("Offer accepted — welcome to the club!", ephemeral=True)
        await self.log_signing(guild, member, role, offer)

    async def deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        if not self.db.decide_offer(self.offer_id, "denied"):
            await interaction.followup.send("This offer was already handled.", ephemeral=True)
            return
        await self.finish(interaction, "denied")
        await interaction.followup.send("Offer denied.", ephemeral=True)

    async def finish(self, interaction: discord.Interaction, result: str) -> None:
        for child in self.children:
            child.disabled = True
        offer = self.db.offer(self.offer_id)
        guild = self.bot.get_guild(offer["guild_id"]) if offer else None
        role = guild.get_role(offer["role_id"]) if guild and offer else None
        team = self.db.team(offer["guild_id"], offer["team_name"]) if offer else None
        accepted = result == "accepted"
        embed = discord.Embed(
            title="OFFER ACCEPTED" if accepted else "OFFER DECLINED",
            description=(
                f"Welcome to **{offer['team_name']}**! Your team role has been added successfully."
                if accepted else f"You declined the offer from **{offer['team_name']}**."
            ),
            color=(role.color if role and role.color.value else
                   (discord.Color.green() if accepted else discord.Color.red())),
        )
        embed.add_field(name="Player", value=f"<@{offer['player_id']}>", inline=True)
        embed.add_field(name="Team", value=role.mention if role else offer["team_name"], inline=True)
        embed.add_field(name="Offered by", value=f"<@{offer['offered_by']}>", inline=True)
        if team and team["owner_id"]:
            embed.add_field(name="Club owner", value=f"<@{team['owner_id']}>", inline=True)
        if accepted and guild and role:
            roster = get_player_roster(self.db, guild, role, offer["team_name"])
            embed.add_field(
                name=f"Player roster ({len(roster)})",
                value=roster_text(roster),
                inline=False,
            )
        if team and team["logo_url"]:
            embed.set_thumbnail(url=team["logo_url"])
        embed.set_footer(text=f"Offer #{self.offer_id} - Decision confirmed")
        if interaction.message:
            await interaction.message.edit(embed=embed, view=self)

    async def log_signing(self, guild, member, role, offer) -> None:
        config = self.db.config(offer["guild_id"])
        if not config:
            return
        channel = guild.get_channel(config["signing_channel_id"])
        if isinstance(channel, discord.TextChannel):
            roster = get_player_roster(self.db, guild, role, offer["team_name"])
            team = self.db.team(offer["guild_id"], offer["team_name"])
            roster_cap = team["roster_cap"] if team else 22
            owner_text = f"<@{team['owner_id']}>" if team and team["owner_id"] else "Not configured"
            embed = discord.Embed(
                description=(
                    "## PLAYER SIGNED\n"
                    f"### {member.mention} / {member.name}\n"
                    f"has signed with {inline_team_logo(team)}{role.mention}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"- **TEAM** — {inline_team_logo(team)}{role.mention}\n"
                    f"- **TEAM OWNER** — {owner_text}\n"
                    f"- **SIGNED BY** — <@{offer['offered_by']}>\n"
                    f"- **ROSTER** — `{len(roster):02d} / {roster_cap:02d}`"
                ),
                color=role.color if role.color.value else discord.Color.blurple(),
                timestamp=discord.utils.utcnow(),
            )
            if team and team["logo_url"]:
                embed.set_thumbnail(url=team["logo_url"])
                embed.set_author(
                    name=guild.name,
                    icon_url=guild.icon.url if guild.icon else team["logo_url"],
                )
            else:
                if guild.icon:
                    embed.set_author(name=guild.name, icon_url=guild.icon.url)
                else:
                    embed.set_author(name=guild.name)
            embed.set_footer(text="Made By EthanCoys")
            await channel.send(embed=embed)


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

    async def require_manager(self, interaction: discord.Interaction) -> bool:
        """Allow administrators or members with either configured manager role."""
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        config = self.db.config(interaction.guild_id)
        allowed = {
            config["manager_role_1_id"],
            config["manager_role_2_id"],
        } if config else set()
        if any(role.id in allowed for role in interaction.user.roles):
            return True
        await interaction.response.send_message(
            "Only an administrator or one of the two configured management roles can use this command.",
            ephemeral=True,
        )
        return False

    async def manager_team(self, interaction: discord.Interaction):
        """Find the team owned by the manager or represented by their team role."""
        if not isinstance(interaction.user, discord.Member):
            return None
        member_role_ids = {role.id for role in interaction.user.roles}
        matches = [
            team for team in self.db.teams(interaction.guild_id)
            if team["owner_id"] == interaction.user.id or team["role_id"] in member_role_ids
        ]
        if len(matches) == 1:
            return matches[0]
        if not matches:
            message = "You are not set as a team owner and do not have a configured team role. Ask an administrator to run /addteam with you as the owner."
        else:
            message = "You have more than one configured team role, so I cannot tell which team is making the offer."
        await interaction.response.send_message(message, ephemeral=True)
        return None

    async def create_logo_emoji(
        self, guild: discord.Guild, team_name: str, logo: discord.Attachment
    ) -> discord.Emoji | None:
        try:
            image = await logo.read()
            safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", team_name)[:24].strip("_")
            return await guild.create_custom_emoji(
                name=f"{safe_name or 'club'}_logo",
                image=image,
                reason=f"Inline club logo for {team_name}",
            )
        except (discord.Forbidden, discord.HTTPException):
            return None

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

    @app_commands.command(name="offer", description="Offer a player a place on your team")
    @app_commands.guild_only()
    async def offer(self, interaction: discord.Interaction, player: discord.Member):
        if not await self.require_manager(interaction):
            return
        assert interaction.guild and interaction.channel
        record = await self.manager_team(interaction)
        if not record:
            return
        role = interaction.guild.get_role(record["role_id"])
        if role is None:
            await interaction.response.send_message("That team's role was deleted. Ask an admin to fix it.", ephemeral=True)
            return
        if player.bot:
            await interaction.response.send_message("You cannot offer a bot.", ephemeral=True)
            return

        try:
            dm = await player.create_dm()
        except discord.HTTPException:
            await interaction.response.send_message("I could not open a DM with that player.", ephemeral=True)
            return

        offer_id = self.db.create_offer(
            interaction.guild.id, player.id, record["name"], role.id,
            interaction.user.id, dm.id,
        )
        view = OfferView(self.bot, self.db, offer_id)
        roster = get_player_roster(self.db, interaction.guild, role, record["name"])
        embed = discord.Embed(
            title=f"Club Offer — {record['name']}",
            description=f"You have received an offer to join **{record['name']}**.",
            color=role.color if role.color.value else discord.Color.blurple(),
        )
        embed.add_field(name="Team", value=role.mention, inline=True)
        embed.add_field(name="Offered by", value=interaction.user.mention, inline=True)
        if record["owner_id"]:
            embed.add_field(name="Team owner", value=f"<@{record['owner_id']}>", inline=True)
        embed.add_field(name=f"Player roster ({len(roster)})", value=roster_text(roster), inline=False)
        embed.add_field(name="Your decision", value="Use the buttons below to accept or deny this offer.", inline=False)
        if record["logo_url"]:
            embed.set_thumbnail(url=record["logo_url"])
        elif interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text=f"Offer #{offer_id}")
        try:
            message = await dm.send(embed=embed, view=view)
        except discord.Forbidden:
            self.db.decide_offer(offer_id, "delivery_failed")
            await interaction.response.send_message(
                "I could not DM that player. They need to allow direct messages from server members.",
                ephemeral=True,
            )
            return
        self.db.set_offer_message(offer_id, message.id)
        await interaction.response.send_message(
            f"Offer sent privately to {player.mention} for {role.mention}.", ephemeral=True
        )

    @app_commands.command(name="release", description="Release a player from your team")
    @app_commands.guild_only()
    async def release(
        self,
        interaction: discord.Interaction,
        player: discord.Member,
        reason: str = "No reason provided",
    ):
        if not await self.require_manager(interaction):
            return
        assert interaction.guild
        record = await self.manager_team(interaction)
        if not record:
            return
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
        self.db.remove_team_member(interaction.guild.id, record["name"], player.id)
        await interaction.response.send_message(f"Released {player.mention} from {role.mention}.", ephemeral=True)
        config = self.db.config(interaction.guild.id)
        channel = interaction.guild.get_channel(config["release_channel_id"]) if config else None
        if isinstance(channel, discord.TextChannel):
            roster = get_player_roster(self.db, interaction.guild, role, record["name"])
            roster_cap = record["roster_cap"] if record else 22
            owner_text = f"<@{record['owner_id']}>" if record["owner_id"] else "Not configured"
            reason_text = (
                f"\n\n**RELEASE NOTE**\n> {reason}"
                if reason != "No reason provided" else ""
            )
            embed = discord.Embed(
                description=(
                    "## PLAYER RELEASED\n"
                    f"### {player.mention} / {player.name}\n"
                    f"was released by {inline_team_logo(record)}{role.mention}\n\n"
                    "━━━━━━━━━━━━━━━━━━━━\n"
                    f"- **TEAM** — {inline_team_logo(record)}{role.mention}\n"
                    f"- **TEAM OWNER** — {owner_text}\n"
                    f"- **ROSTER** — `{len(roster):02d} / {roster_cap:02d}`"
                    f"{reason_text}"
                ),
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            if record["logo_url"]:
                embed.set_thumbnail(url=record["logo_url"])
                embed.set_author(
                    name=interaction.guild.name,
                    icon_url=interaction.guild.icon.url if interaction.guild.icon else record["logo_url"],
                )
            else:
                if interaction.guild.icon:
                    embed.set_author(
                        name=interaction.guild.name,
                        icon_url=interaction.guild.icon.url,
                    )
                else:
                    embed.set_author(name=interaction.guild.name)
            embed.set_footer(text="Made By EthanCoys")
            await channel.send(embed=embed)

    @app_commands.command(name="roster", description="View your team's signed roster")
    @app_commands.guild_only()
    async def roster(self, interaction: discord.Interaction):
        if not await self.require_manager(interaction):
            return
        assert interaction.guild
        record = await self.manager_team(interaction)
        if not record:
            return
        role = interaction.guild.get_role(record["role_id"])
        if role is None:
            await interaction.response.send_message(
                "Your configured team role no longer exists.", ephemeral=True
            )
            return
        players = get_player_roster(self.db, interaction.guild, role, record["name"])
        player_lines = "\n".join(
            f"`{number:02d}`  {player.mention}  —  **{player.name}**"
            for number, player in enumerate(players, start=1)
        ) or "*No players are currently signed.*"
        embed = discord.Embed(
            description=(
                f"## {record['name']} Roster\n"
                f"**{len(players):02d} / {record['roster_cap']:02d}**\n\n"
                f"{player_lines}"
            ),
            color=role.color if role.color.value else discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if record["logo_url"]:
            embed.set_thumbnail(url=record["logo_url"])
        if interaction.guild.icon:
            embed.set_author(name=interaction.guild.name, icon_url=interaction.guild.icon.url)
        else:
            embed.set_author(name=interaction.guild.name)
        embed.set_footer(text="Made By EthanCoys")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    team_group = app_commands.Group(name="team", description="Configure club teams", guild_only=True)

    @app_commands.command(name="addteam", description="Create a new team (Administrator only)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def addteam(
        self,
        interaction: discord.Interaction,
        name: str,
        role: discord.Role,
        owner: discord.Member,
        logo: discord.Attachment | None = None,
        roster_cap: app_commands.Range[int, 1, 99] = 22,
    ):
        if role.is_default() or role.managed:
            await interaction.response.send_message("Choose a normal assignable team role.", ephemeral=True)
            return
        if logo and logo.content_type and not logo.content_type.startswith("image/"):
            await interaction.response.send_message("The logo must be an image file.", ephemeral=True)
            return
        try:
            self.db.add_team(
                interaction.guild_id,
                name,
                role.id,
                owner.id,
                logo.url if logo else None,
                roster_cap,
            )
        except sqlite3.IntegrityError:
            await interaction.response.send_message("That team name or role is already configured.", ephemeral=True)
            return
        emoji = await self.create_logo_emoji(interaction.guild, name, logo) if logo else None
        if logo:
            self.db.update_team_logo(
                interaction.guild_id, name, logo.url, emoji.id if emoji else None
            )
        role_note = ""
        if role not in owner.roles:
            try:
                await owner.add_roles(role, reason=f"Made owner of {name.strip()}")
                role_note = "\nThe team role was also given to the owner."
            except discord.Forbidden:
                role_note = "\nI could not give the owner the team role; move my bot role above it. Owner-based offers will still work."
        embed = discord.Embed(
            title=f"Team created — {name.strip()}",
            color=role.color if role.color.value else discord.Color.blurple(),
        )
        embed.add_field(name="Role", value=role.mention)
        embed.add_field(name="Owner", value=owner.mention)
        embed.add_field(name="Roster cap", value=str(roster_cap))
        if logo:
            embed.set_thumbnail(url=logo.url)
        if role_note:
            embed.description = role_note
        if logo and emoji is None:
            embed.add_field(
                name="Inline logo",
                value="Logo saved, but the inline logo needs the bot's Manage Expressions permission.",
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="setteamlogo", description="Update a team's corner and inline logo")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(team=team_autocomplete)
    async def setteamlogo(
        self,
        interaction: discord.Interaction,
        team: str,
        logo: discord.Attachment,
    ):
        assert interaction.guild
        record = self.db.team(interaction.guild_id, team)
        if not record:
            await interaction.response.send_message("That team is not configured.", ephemeral=True)
            return
        if logo.content_type and not logo.content_type.startswith("image/"):
            await interaction.response.send_message("The logo must be an image file.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        emoji = await self.create_logo_emoji(interaction.guild, record["name"], logo)
        self.db.update_team_logo(
            interaction.guild_id, record["name"], logo.url, emoji.id if emoji else None
        )
        if emoji:
            message = f"Logo updated. It will appear inline as {emoji} and in the corner."
        else:
            message = "The corner logo was updated, but the inline logo needs the bot's Manage Expressions permission."
        await interaction.followup.send(message, ephemeral=True)

    @app_commands.command(name="removeteam", description="Remove a configured team (Administrator only)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(name=team_autocomplete)
    async def removeteam(self, interaction: discord.Interaction, name: str):
        removed = self.db.remove_team(interaction.guild_id, name)
        text = f"Removed **{name}**." if removed else "That team was not found."
        await interaction.response.send_message(text, ephemeral=True)

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
        text = "\n".join(f"- **{row['name']}** — <@&{row['role_id']}>" for row in teams)
        await interaction.response.send_message(text or "No teams are configured yet.", ephemeral=True)

    @app_commands.command(name="config_setup", description="Set log channels and the two management roles")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def config_setup(
        self,
        interaction: discord.Interaction,
        signing_channel: discord.TextChannel,
        release_channel: discord.TextChannel,
        manager_role_1: discord.Role,
        manager_role_2: discord.Role,
    ):
        if manager_role_1 == manager_role_2:
            await interaction.response.send_message("Please choose two different management roles.", ephemeral=True)
            return
        self.db.configure_guild(
            interaction.guild_id,
            signing_channel.id,
            release_channel.id,
            manager_role_1.id,
            manager_role_2.id,
        )
        await interaction.response.send_message(
            f"Signing logs: {signing_channel.mention}\n"
            f"Release logs: {release_channel.mention}\n"
            f"Management roles: {manager_role_1.mention} and {manager_role_2.mention}",
            ephemeral=True,
        )


async def setup(bot: commands.Bot, database: Database) -> None:
    await bot.add_cog(ClubManagement(bot, database))

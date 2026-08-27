import asyncio
import io
import json
import os
import re
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Literal

import discord
from discord import app_commands
from discord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageOps

from database import Database
from stats_ocr import extract_rating


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


def _font(size: int, bold: bool = False):
    names = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def render_welcome_card(banner_path: str, avatar_bytes: bytes, headline: str) -> io.BytesIO:
    width, height = 1100, 500
    with Image.open(banner_path) as source:
        background = ImageOps.fit(source.convert("RGB"), (width, height), Image.Resampling.LANCZOS)
    card = background.convert("RGBA")
    card.alpha_composite(Image.new("RGBA", card.size, (8, 10, 18, 25)))
    panel = Image.new("RGBA", card.size, (0, 0, 0, 0))
    ImageDraw.Draw(panel).rounded_rectangle(
        (90, 20, 1010, 480), radius=34, fill=(4, 6, 12, 135)
    )
    card.alpha_composite(panel)

    with Image.open(io.BytesIO(avatar_bytes)) as avatar_source:
        avatar = ImageOps.fit(
            avatar_source.convert("RGBA"), (210, 210), Image.Resampling.LANCZOS
        )
    mask = Image.new("L", avatar.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, 209, 209), fill=255)
    avatar.putalpha(mask)
    border = Image.new("RGBA", (228, 228), (0, 0, 0, 0))
    ImageDraw.Draw(border).ellipse((0, 0, 227, 227), fill=(255, 255, 255, 245))
    border.alpha_composite(avatar, (9, 9))
    card.alpha_composite(border, ((width - 228) // 2, 42))

    draw = ImageDraw.Draw(card)
    headline_font = _font(52, bold=False)
    while draw.textbbox((0, 0), headline, font=headline_font)[2] > width - 130 and headline_font.size > 32:
        headline_font = _font(headline_font.size - 2, bold=False)
    headline_box = draw.textbbox((0, 0), headline, font=headline_font, stroke_width=2)
    headline_x = (width - (headline_box[2] - headline_box[0])) // 2
    draw.text(
        (headline_x, 325), headline, font=headline_font, fill="white",
        stroke_width=2, stroke_fill=(0, 0, 0, 190),
    )
    output = io.BytesIO()
    card.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


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
        if self.db.blacklist_entry(guild.id, member.id):
            await interaction.followup.send("You are currently blacklisted and cannot accept offers.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason=f"Accepted club offer #{self.offer_id}")
        except discord.Forbidden:
            await interaction.followup.send(
                "I cannot assign that role. Put my bot role above the team role.", ephemeral=True
            )
            return

        config = self.db.config(guild.id)
        remove_role = guild.get_role(config["signing_remove_role_id"]) if config and config["signing_remove_role_id"] else None
        remove_warning = None
        if remove_role and remove_role in member.roles:
            try:
                await member.remove_roles(remove_role, reason=f"Signed for {offer['team_name']}")
            except discord.Forbidden:
                remove_warning = f" I could not remove {remove_role.mention}; put the bot role above it."

        if not self.db.decide_offer(self.offer_id, "accepted"):
            await interaction.followup.send("This offer was already handled.", ephemeral=True)
            return
        self.db.add_team_member(guild.id, offer["team_name"], member.id)
        await self.finish(interaction, "accepted")
        await interaction.followup.send("Offer accepted." + (remove_warning or ""), ephemeral=True)
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
                f"Your offer from **{offer['team_name']}** was accepted. Your team role has been added."
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
            league = self.db.league_config(guild.id)
            compact = bool(league and league["log_style"] == "compact")
            description = (
                f"**PLAYER SIGNED**\n{member.mention} signed with {role.mention} — "
                f"Roster `{len(roster):02d}/{roster_cap:02d}`"
                if compact else
                "## PLAYER SIGNED\n"
                f"### {member.mention} / {member.name}\n"
                f"has signed with {inline_team_logo(team)}{role.mention}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"- **TEAM** — {inline_team_logo(team)}{role.mention}\n"
                f"- **TEAM OWNER** — {owner_text}\n"
                f"- **SIGNED BY** — <@{offer['offered_by']}>\n"
                f"- **ROSTER** — `{len(roster):02d} / {roster_cap:02d}`"
            )
            embed = discord.Embed(
                description=description,
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


class TicketCloseView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.db = database

    @discord.ui.button(
        label="Close Ticket",
        style=discord.ButtonStyle.danger,
        custom_id="xpc_tickets:close",
    )
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        ticket = self.db.ticket(interaction.channel.id)
        config = self.db.ticket_config(interaction.guild.id)
        if not ticket or ticket["status"] != "open":
            await interaction.response.send_message("This ticket is already closed.", ephemeral=True)
            return
        member = interaction.user
        allowed = member.id == ticket["user_id"] or member.guild_permissions.administrator
        if config and isinstance(member, discord.Member):
            allowed = allowed or any(role.id == config["support_role_id"] for role in member.roles)
        if not allowed:
            await interaction.response.send_message(
                "Only the ticket owner or support team can close this ticket.", ephemeral=True
            )
            return
        button.disabled = True
        await interaction.response.edit_message(view=self)
        if not self.db.close_ticket(interaction.channel.id):
            await interaction.channel.send("This ticket is already closed.")
            return
        opener = interaction.guild.get_member(ticket["user_id"])
        if opener:
            await interaction.channel.set_permissions(
                opener, view_channel=True, send_messages=False, read_message_history=True
            )
        new_name = interaction.channel.name
        if not new_name.startswith("closed-"):
            new_name = f"closed-{new_name}"[:100]
        await interaction.channel.edit(name=new_name, reason=f"Ticket closed by {member}")
        await interaction.channel.send(
            embed=discord.Embed(
                title="Ticket Closed",
                description=f"Closed by {member.mention}. This channel will be deleted in 10 seconds.",
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
        )
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Closed ticket deleted after 10 seconds by {member}")
        except discord.NotFound:
            pass


class TicketProblemSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, database: Database, problems: list[str]) -> None:
        self.bot = bot
        self.db = database
        options = [
            discord.SelectOption(
                label=problem[:100],
                value=problem[:100],
                description=f"Open a {problem[:70]} ticket",
            )
            for problem in problems[:25]
        ] or [discord.SelectOption(label="General Support", value="General Support")]
        super().__init__(
            placeholder="Choose what you need help with",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="xpc_tickets:problem",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        await interaction.response.defer(ephemeral=True)
        config = self.db.ticket_config(interaction.guild.id)
        if not config:
            await interaction.followup.send("The ticket system is not configured.", ephemeral=True)
            return
        existing = self.db.open_ticket_for_user(interaction.guild.id, interaction.user.id)
        if existing:
            channel = interaction.guild.get_channel(existing["channel_id"])
            if channel:
                await interaction.followup.send(
                    f"You already have an open ticket: {channel.mention}", ephemeral=True
                )
                return
            self.db.close_ticket(existing["channel_id"])
        category = interaction.guild.get_channel(config["category_id"])
        support_role = interaction.guild.get_role(config["support_role_id"])
        if not isinstance(category, discord.CategoryChannel) or support_role is None:
            await interaction.followup.send(
                "The ticket category or support role was deleted. Ask an administrator to run /ticketsetup again.",
                ephemeral=True,
            )
            return
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True, attach_files=True
            ),
            support_role: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, read_message_history=True
            ),
            interaction.guild.me: discord.PermissionOverwrite(
                view_channel=True, send_messages=True, manage_channels=True
            ),
        }
        safe_user = re.sub(r"[^a-z0-9-]", "-", interaction.user.name.lower()).strip("-")
        safe_problem = re.sub(r"[^a-z0-9-]", "-", self.values[0].lower()).strip("-")
        channel = await interaction.guild.create_text_channel(
            name=f"{safe_problem or 'ticket'}-{safe_user or interaction.user.id}"[:100],
            category=category,
            overwrites=overwrites,
            reason=f"Ticket opened by {interaction.user}",
        )
        problem = self.values[0]
        self.db.create_ticket(channel.id, interaction.guild.id, interaction.user.id, problem)
        embed = discord.Embed(
            title=problem,
            description=(
                f"{interaction.user.mention}, describe the problem and include any useful screenshots.\n\n"
                "A member of the support team will respond here."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Made By EthanCoys")
        await channel.send(
            content=f"{interaction.user.mention} {support_role.mention}",
            embed=embed,
            view=TicketCloseView(self.db),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        await interaction.followup.send(f"Your ticket is ready: {channel.mention}", ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot, database: Database, problems: list[str]) -> None:
        super().__init__(timeout=None)
        self.add_item(TicketProblemSelect(bot, database, problems))


class StaffApplicationCloseView(discord.ui.View):
    def __init__(self, database: Database) -> None:
        super().__init__(timeout=None)
        self.db = database

    @discord.ui.button(label="Close Application", style=discord.ButtonStyle.danger, custom_id="xpc_staff:close")
    async def close_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild is None or not isinstance(interaction.channel, discord.TextChannel):
            return
        application = self.db.staff_application(interaction.channel.id)
        config = self.db.staff_application_config(interaction.guild.id)
        allowed = isinstance(interaction.user, discord.Member) and (
            interaction.user.guild_permissions.administrator
            or (config and any(role.id == config["reviewer_role_id"] for role in interaction.user.roles))
        )
        if not allowed:
            await interaction.response.send_message("Only the application review team can close this.", ephemeral=True)
            return
        if not application or not self.db.close_staff_application(interaction.channel.id):
            await interaction.response.send_message("This application is already closed.", ephemeral=True)
            return
        button.disabled = True
        await interaction.response.edit_message(view=self)
        await interaction.channel.send("Application closed. This channel will be deleted in 10 seconds.")
        await asyncio.sleep(10)
        try:
            await interaction.channel.delete(reason=f"Staff application closed by {interaction.user}")
        except discord.NotFound:
            pass


class StaffPositionSelect(discord.ui.Select):
    def __init__(self, database: Database, positions: list[str]) -> None:
        self.db = database
        super().__init__(
            placeholder="Choose the staff position",
            min_values=1,
            max_values=1,
            options=[discord.SelectOption(label=item[:100], value=item[:100]) for item in positions[:25]]
            or [discord.SelectOption(label="Staff", value="Staff")],
            custom_id="xpc_staff:position",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        await interaction.response.defer(ephemeral=True)
        config = self.db.staff_application_config(interaction.guild.id)
        if not config:
            await interaction.followup.send("Staff applications are not configured.", ephemeral=True)
            return
        existing = self.db.open_staff_application(interaction.guild.id, interaction.user.id)
        if existing:
            existing_channel = interaction.guild.get_channel(existing["channel_id"])
            if existing_channel:
                await interaction.followup.send(f"You already have an application: {existing_channel.mention}", ephemeral=True)
                return
            self.db.close_staff_application(existing["channel_id"])
        category = interaction.guild.get_channel(config["category_id"])
        reviewer_role = interaction.guild.get_role(config["reviewer_role_id"])
        if not isinstance(category, discord.CategoryChannel) or reviewer_role is None:
            await interaction.followup.send("The application category or reviewer role no longer exists.", ephemeral=True)
            return
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True),
            reviewer_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
        }
        safe_user = re.sub(r"[^a-z0-9-]", "-", interaction.user.name.lower()).strip("-")
        channel = await interaction.guild.create_text_channel(
            name=f"application-{safe_user or interaction.user.id}"[:100],
            category=category,
            overwrites=overwrites,
            reason=f"Staff application opened by {interaction.user}",
        )
        position = self.values[0]
        self.db.create_staff_application(channel.id, interaction.guild.id, interaction.user.id, position)
        embed = discord.Embed(
            title=f"{position} Application",
            description=(
                f"{interaction.user.mention}, please answer these questions clearly:\n\n"
                "1. What is your age?\n"
                "2. What timezone are you in?\n"
                "3. Why do you want this staff position?\n"
                "4. What experience do you have?\n"
                "5. How active can you be?\n"
                "6. What would make you a good member of staff?"
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Made By EthanCoys")
        await channel.send(
            content=f"{interaction.user.mention} {reviewer_role.mention}",
            embed=embed,
            view=StaffApplicationCloseView(self.db),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        await interaction.followup.send(f"Your application is ready: {channel.mention}", ephemeral=True)


class StaffApplicationPanelView(discord.ui.View):
    def __init__(self, database: Database, positions: list[str]) -> None:
        super().__init__(timeout=None)
        self.add_item(StaffPositionSelect(database, positions))


class ApplicationTypeSelect(discord.ui.Select):
    def __init__(self, bot: commands.Bot, database: Database) -> None:
        self.bot = bot
        self.db = database
        super().__init__(
            placeholder="Choose an application type",
            min_values=1,
            max_values=1,
            options=[
                discord.SelectOption(label="Staff Application", value="Staff", description="Apply to join the server staff team"),
                discord.SelectOption(label="Manager Application", value="Manager", description="Apply to manage a Pro Clubs team"),
            ],
            custom_id="xpc_applications:type",
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            return
        cog = self.bot.get_cog("ClubManagement")
        if cog is None:
            await interaction.response.send_message("Applications are temporarily unavailable.", ephemeral=True)
            return
        await cog.start_dm_application(interaction, self.values[0])


class ApplicationPanelView(discord.ui.View):
    def __init__(self, bot: commands.Bot, database: Database) -> None:
        super().__init__(timeout=None)
        self.add_item(ApplicationTypeSelect(bot, database))


class QuickSetupView(discord.ui.View):
    def __init__(self, wizard) -> None:
        super().__init__(timeout=600)
        self.wizard = wizard

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.wizard.owner_id:
            await interaction.response.send_message("Only the administrator who started Quick Setup can use this panel.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Yes", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.wizard.start_feature(interaction)

    @discord.ui.button(label="No", style=discord.ButtonStyle.secondary)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.wizard.skip_feature(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(embed=discord.Embed(title="Quick Setup Cancelled", color=discord.Color.red()), view=None)


class QuickSetupRolePicker(discord.ui.RoleSelect):
    def __init__(self, wizard, key: str, prompt: str, multiple: bool = False) -> None:
        self.wizard, self.key = wizard, key
        super().__init__(placeholder=prompt[:150], min_values=1, max_values=5 if multiple else 1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.wizard.owner_id:
            await interaction.response.send_message("Only the setup administrator can use this.", ephemeral=True)
            return
        await self.wizard.selected(interaction, self.key, list(self.values) if self.max_values > 1 else self.values[0])


class QuickSetupChannelPicker(discord.ui.ChannelSelect):
    def __init__(self, wizard, key: str, prompt: str, category: bool = False) -> None:
        self.wizard, self.key = wizard, key
        super().__init__(placeholder=prompt[:150], min_values=1, max_values=1, channel_types=[discord.ChannelType.category] if category else [discord.ChannelType.text])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.wizard.owner_id:
            await interaction.response.send_message("Only the setup administrator can use this.", ephemeral=True)
            return
        value = self.values[0]
        if hasattr(value, "resolve"):
            value = value.resolve() or value
        await self.wizard.selected(interaction, self.key, value)


class QuickSetupPickerView(discord.ui.View):
    def __init__(self, item: discord.ui.Item) -> None:
        super().__init__(timeout=600)
        self.add_item(item)


class QuickSetupWizard:
    FEATURES = [
        ("core", "Set signing/release log channels and the two manager roles?"),
        ("remove_role", "Remove a chosen role automatically whenever somebody signs?"),
        ("tickets", "Create a ticket panel with selectable problem types?"),
        ("applications", "Create the Staff and Manager Applications panel?"),
        ("moderation", "Set a moderation log channel and enable scam protection?"),
        ("role_saver", "Save chosen roles when members leave and restore them when they return?"),
    ]
    PICKS = {
        "core": [("signing", "channel", "Choose the signing log channel"), ("release", "channel", "Choose the release log channel"), ("manager_1", "role", "Choose the Manager role"), ("manager_2", "role", "Choose the Co-Manager role")],
        "remove_role": [("remove_role", "role", "Choose the role removed when somebody signs")],
        "tickets": [("ticket_panel", "channel", "Choose where the ticket panel is posted"), ("ticket_category", "category", "Choose the private ticket category"), ("support_role", "role", "Choose the ticket support role")],
        "applications": [("app_panel", "channel", "Choose where the Applications panel is posted"), ("app_category", "category", "Choose the private application category"), ("reviewer_role", "role", "Choose the application reviewer role")],
        "moderation": [("mod_log", "channel", "Choose the moderation log channel")],
        "role_saver": [("role_log", "channel", "Choose the Role Saver log channel"), ("saved_roles", "roles", "Choose up to five roles to save")],
    }

    def __init__(self, cog, owner_id: int, guild: discord.Guild) -> None:
        self.cog, self.db, self.owner_id, self.guild = cog, cog.db, owner_id, guild
        self.index, self.data, self.pending, self.completed = 0, {}, [], []

    def question_embed(self) -> discord.Embed:
        _, question = self.FEATURES[self.index]
        return discord.Embed(title=f"QUICK SETUP — {self.index + 1}/{len(self.FEATURES)}", description=question, color=discord.Color.blurple()).set_footer(text="Choose Yes or No")

    async def ask(self, interaction: discord.Interaction):
        if self.index >= len(self.FEATURES):
            description = "\n".join(f"- {item}" for item in self.completed) or "No systems were changed."
            await interaction.response.edit_message(embed=discord.Embed(title="QUICK SETUP COMPLETE", description=description, color=discord.Color.green()), view=None)
            return
        await interaction.response.edit_message(embed=self.question_embed(), view=QuickSetupView(self))

    async def skip_feature(self, interaction: discord.Interaction):
        self.index += 1
        await self.ask(interaction)

    async def start_feature(self, interaction: discord.Interaction):
        feature = self.FEATURES[self.index][0]
        self.pending = list(self.PICKS[feature])
        await self.show_next_picker(interaction)

    async def show_next_picker(self, interaction: discord.Interaction):
        key, kind, prompt = self.pending[0]
        item = QuickSetupChannelPicker(self, key, prompt, kind == "category") if kind in ("channel", "category") else QuickSetupRolePicker(self, key, prompt, kind == "roles")
        await interaction.response.edit_message(embed=discord.Embed(title="QUICK SETUP", description=prompt, color=discord.Color.blurple()), view=QuickSetupPickerView(item))

    async def selected(self, interaction: discord.Interaction, key: str, value):
        self.data[key] = value
        self.pending.pop(0)
        if self.pending:
            await self.show_next_picker(interaction)
            return
        await self.apply_feature()
        self.index += 1
        await self.ask(interaction)

    async def apply_feature(self):
        feature = self.FEATURES[self.index][0]
        if feature == "core":
            self.db.configure_guild(self.guild.id, self.data["signing"].id, self.data["release"].id, self.data["manager_1"].id, self.data["manager_2"].id)
            self.completed.append("Core club configuration enabled")
        elif feature == "remove_role":
            if self.db.config(self.guild.id):
                self.db.set_signing_remove_role(self.guild.id, self.data["remove_role"].id)
                self.completed.append("Automatic signing-role removal enabled")
            else:
                self.completed.append("Signing-role removal skipped — core configuration is required")
        elif feature == "tickets":
            problems = ["General Support", "Report a Player", "Team Issue", "Transfer Issue", "Other"]
            self.db.configure_tickets(self.guild.id, self.data["ticket_panel"].id, self.data["ticket_category"].id, self.data["support_role"].id, "\n".join(problems))
            embed = discord.Embed(title="CHOOSE A TICKET TYPE", description="Select the tab that best matches what you need help with.\n\nA private channel will be created for you and the support team.", color=discord.Color.blurple())
            await self.data["ticket_panel"].send(embed=embed, view=TicketPanelView(self.cog.bot, self.db, problems))
            self.completed.append("Ticket panel created")
        elif feature == "applications":
            staff = ["Which staff position are you applying for?", "What experience do you have?", "Why should you be accepted?"]
            manager = ["Which team would you like to manage?", "What management experience do you have?", "How would you build your roster?"]
            self.db.configure_staff_applications(self.guild.id, self.data["app_panel"].id, self.data["app_category"].id, self.data["reviewer_role"].id, "Staff", "\n".join(staff), "\n".join(manager))
            embed = discord.Embed(title="APPLICATIONS", description="Choose **Staff Application** or **Manager Application** below.\n\nThe bot will ask one question at a time in DMs.", color=discord.Color.blurple())
            await self.data["app_panel"].send(embed=embed, view=ApplicationPanelView(self.cog.bot, self.db))
            self.completed.append("Applications panel created")
        elif feature == "moderation":
            self.db.configure_moderation(self.guild.id, self.data["mod_log"].id, True)
            self.completed.append("Moderation logs and scam protection enabled")
        elif feature == "role_saver":
            roles = [role for role in self.data["saved_roles"] if not role.is_default() and not role.managed]
            self.db.configure_role_saver(self.guild.id, self.data["role_log"].id, [role.id for role in roles])
            self.completed.append(f"Role Saver enabled for {len(roles)} roles")


class ClubManagement(commands.Cog):
    def __init__(self, bot: commands.Bot, database: Database) -> None:
        self.bot = bot
        self.db = database
        self.active_applicants: set[tuple[int, int]] = set()
        self.invite_cache: dict[int, dict[str, tuple[int, int | None]]] = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        command_name = interaction.command.qualified_name if interaction.command else "unknown"
        self.db.add_audit(
            interaction.guild_id,
            interaction.user.id,
            f"/{command_name}",
            f"Channel {interaction.channel_id or 'DM'}",
        )
        if interaction.guild_id and not self.db.command_enabled(interaction.guild_id, command_name):
            await interaction.response.send_message(
                "That command is currently disabled by the bot dashboard.", ephemeral=True
            )
            return False
        return True

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await self.track_invite_join(member)
        saver = self.db.role_saver_config(member.guild.id)
        if saver:
            restored = []
            for role_id in self.db.saved_member_roles(member.guild.id, member.id):
                role = member.guild.get_role(role_id)
                if role and not role.managed and role < member.guild.me.top_role:
                    restored.append(role)
            if restored:
                try:
                    await member.add_roles(*restored, reason="XPC role saver restore")
                except discord.Forbidden:
                    restored = []
            log_channel = member.guild.get_channel(saver["log_channel_id"])
            if isinstance(log_channel, discord.TextChannel):
                text = ", ".join(role.mention for role in restored) if restored else "No saved roles"
                await log_channel.send(embed=discord.Embed(title="Member Rejoined", description=f"{member.mention}\nRestored: {text}", color=discord.Color.green(), timestamp=discord.utils.utcnow()))
        config = self.db.welcome_config(member.guild.id)
        if not config:
            return
        channel = member.guild.get_channel(config["channel_id"])
        if not isinstance(channel, discord.TextChannel) or not Path(config["banner_path"]).exists():
            return
        await self.send_welcome_card(member, channel, config)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        for guild in self.bot.guilds:
            await self.refresh_invite_cache(guild)

    async def refresh_invite_cache(self, guild: discord.Guild) -> None:
        try:
            invites = await guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            return
        self.invite_cache[guild.id] = {invite.code: (invite.uses or 0, invite.inviter.id if invite.inviter else None) for invite in invites}

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        if invite.guild: await self.refresh_invite_cache(invite.guild)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite) -> None:
        if invite.guild: await self.refresh_invite_cache(invite.guild)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, discord.TextChannel):
            return
        overwrites = []
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            overwrites.append({"id": target.id, "kind": "role" if isinstance(target, discord.Role) else "member", "allow": allow.value, "deny": deny.value})
        backup_id = self.db.save_channel_backup(channel.guild.id, channel.id, channel.name, "text", channel.category_id, channel.position, channel.topic, channel.nsfw, channel.slowmode_delay, json.dumps(overwrites))
        await self.send_mod_log(channel.guild, "Deleted Channel Captured", f"**#{channel.name}** was deleted.\nIts name, category, topic and permissions were saved automatically.\nRestore with `/restorechannel backup_id:{backup_id}`.", discord.Color.red())

    async def track_invite_join(self, member: discord.Member) -> None:
        previous = self.invite_cache.get(member.guild.id, {})
        try:
            invites = await member.guild.invites()
        except (discord.Forbidden, discord.HTTPException):
            self.db.record_invite_join(member.guild.id, member.id, None, None)
            return
        used = next((invite for invite in invites if (invite.uses or 0) > previous.get(invite.code, (0, None))[0]), None)
        self.db.record_invite_join(member.guild.id, member.id, used.inviter.id if used and used.inviter else None, used.code if used else None)
        self.invite_cache[member.guild.id] = {invite.code: (invite.uses or 0, invite.inviter.id if invite.inviter else None) for invite in invites}

    async def send_mod_log(self, guild: discord.Guild, title: str, description: str, color: discord.Color = discord.Color.orange()) -> None:
        config = self.db.moderation_config(guild.id)
        channel = guild.get_channel(config["log_channel_id"]) if config else None
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow()).set_footer(text="Made By EthanCoys"))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return
        config = self.db.moderation_config(message.guild.id)
        if not config or not config["scam_protection"] or message.author.guild_permissions.administrator:
            return
        images = [item for item in message.attachments if (item.content_type or "").startswith("image/") or item.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))]
        content = message.content.casefold()
        scam_phrases = ("free money", "guaranteed profit", "double your money", "crypto investment", "bitcoin investment", "cashapp flip", "money flip", "dm me to earn", "instant payout", "claim your airdrop", "investment opportunity")
        if not images or not any(phrase in content for phrase in scam_phrases):
            return
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        try:
            await message.author.ban(reason="Automatic protection: image-based money scam", delete_message_seconds=86400)
            action = "Message deleted and member banned"
        except discord.Forbidden:
            action = "Message deleted; bot could not ban the member"
        await self.send_mod_log(message.guild, "Automatic Scam Protection", f"{message.author} (`{message.author.id}`)\nChannel: {message.channel.mention}\nAction: **{action}**\nMatched an image-based money scam phrase.", discord.Color.red())

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        saver = self.db.role_saver_config(member.guild.id)
        if not saver:
            return
        allowed = {int(value) for value in saver["role_ids"].split(",") if value}
        saved = [role.id for role in member.roles if role.id in allowed]
        self.db.save_member_roles(member.guild.id, member.id, saved)
        log_channel = member.guild.get_channel(saver["log_channel_id"])
        if isinstance(log_channel, discord.TextChannel):
            roles = [member.guild.get_role(role_id) for role_id in saved]
            text = ", ".join(role.mention for role in roles if role) or "No configured roles"
            await log_channel.send(embed=discord.Embed(title="Member Left - Roles Saved", description=f"**{member}** (`{member.id}`)\nSaved: {text}", color=discord.Color.orange(), timestamp=discord.utils.utcnow()))

    async def start_dm_application(self, interaction: discord.Interaction, application_type: str) -> None:
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        config = self.db.staff_application_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message("Applications are not configured yet.", ephemeral=True)
            return
        key = (interaction.guild.id, interaction.user.id)
        if key in self.active_applicants:
            await interaction.response.send_message("You already have an application in progress in your DMs.", ephemeral=True)
            return
        existing = self.db.open_staff_application(interaction.guild.id, interaction.user.id)
        if existing:
            await interaction.response.send_message("You already have an application awaiting review.", ephemeral=True)
            return
        try:
            dm = await interaction.user.create_dm()
            await dm.send(embed=discord.Embed(title=f"{application_type} Application", description=f"Your application for **{interaction.guild.name}** will be completed here. I will send one question at a time. You have 10 minutes to answer each question.", color=discord.Color.blurple()))
        except discord.Forbidden:
            await interaction.response.send_message("I cannot DM you. Enable direct messages from server members and try again.", ephemeral=True)
            return
        self.active_applicants.add(key)
        await interaction.response.send_message("Your application has started. Check your DMs for the first question.", ephemeral=True)
        self.bot.loop.create_task(self.run_dm_application(interaction.guild, interaction.user, dm, application_type, config, key))

    async def run_dm_application(self, guild: discord.Guild, member: discord.Member, dm: discord.DMChannel, application_type: str, config, key) -> None:
        question_column = "staff_questions" if application_type == "Staff" else "manager_questions"
        questions = [value.strip() for value in (config[question_column] or "").split("\n") if value.strip()]
        if not questions:
            questions = ["Why are you applying?", "What relevant experience do you have?", "How active can you be each week?"]
        answers = []
        try:
            for number, question in enumerate(questions, 1):
                await dm.send(embed=discord.Embed(title=f"Question {number} of {len(questions)}", description=question, color=discord.Color.blurple()).set_footer(text="Reply to this DM with your answer"))
                try:
                    message = await self.bot.wait_for("message", timeout=600, check=lambda m: m.author.id == member.id and m.channel.id == dm.id and not m.author.bot)
                except asyncio.TimeoutError:
                    await dm.send("Your application expired because no answer was received for 10 minutes. You can start again from the Applications panel.")
                    return
                answers.append(message.content.strip()[:1500] or "No written answer")
            category = guild.get_channel(config["category_id"]); reviewer_role = guild.get_role(config["reviewer_role_id"])
            if not isinstance(category, discord.CategoryChannel) or reviewer_role is None:
                await dm.send("Your answers were received, but the review area is not configured correctly. Please contact an administrator.")
                return
            overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), reviewer_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True)}
            safe_user = re.sub(r"[^a-z0-9-]", "-", member.name.lower()).strip("-")
            channel = await guild.create_text_channel(name=f"{application_type.lower()}-{safe_user or member.id}"[:100], category=category, overwrites=overwrites, reason=f"{application_type} application submitted by {member}")
            position = application_type
            answer_text = json.dumps({"questions": questions, "answers": answers})
            self.db.create_staff_application(channel.id, guild.id, member.id, position, application_type, answer_text)
            embed = discord.Embed(title=f"{application_type} Application", description=f"Applicant: {member.mention}\nUsername: **{member}**\nUser ID: `{member.id}`", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
            if member.display_avatar: embed.set_thumbnail(url=member.display_avatar.url)
            for number, (question, answer) in enumerate(zip(questions, answers), 1): embed.add_field(name=f"{number}. {question[:240]}", value=answer[:1000], inline=False)
            embed.set_footer(text="Made By EthanCoys")
            await channel.send(content=reviewer_role.mention, embed=embed, view=StaffApplicationCloseView(self.db), allowed_mentions=discord.AllowedMentions(roles=True))
            await dm.send(embed=discord.Embed(title="Application Submitted", description=f"Your **{application_type} Application** has been sent to the review team. They will contact you when a decision is made.", color=discord.Color.green()))
        finally:
            self.active_applicants.discard(key)

    async def send_welcome_card(
        self, member: discord.Member, channel: discord.TextChannel, config
    ) -> bool:
        replacements = {
            "{user}": member.mention,
            "{display}": member.display_name,
            "{server}": member.guild.name,
            "{count}": str(member.guild.member_count or 0),
        }
        message_headline = config["headline"] or "Welcome {user} to {server}!"
        for placeholder, value in replacements.items():
            message_headline = message_headline.replace(placeholder, value)
        image_headline = f"{member.display_name} has landed."
        try:
            avatar_bytes = await member.display_avatar.with_size(256).read()
            card = await asyncio.to_thread(
                render_welcome_card,
                config["banner_path"],
                avatar_bytes,
                image_headline,
            )
            await channel.send(
                content=message_headline,
                file=discord.File(card, filename="welcome.png"),
            )
            return True
        except (discord.HTTPException, OSError):
            return False

    async def team_autocomplete(self, interaction: discord.Interaction, current: str):
        if interaction.guild_id is None:
            return []
        current = current.casefold()
        return [
            app_commands.Choice(name=row["name"], value=row["name"])
            for row in self.db.teams(interaction.guild_id)
            if current in row["name"].casefold()
        ][:25]

    async def refresh_budget_message(self, guild: discord.Guild) -> discord.Message | None:
        config = self.db.budget_config(guild.id)
        if not config:
            return None
        channel = guild.get_channel(config["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            return None
        entries = []
        for team in self.db.teams(guild.id):
            role = guild.get_role(team["role_id"])
            if role:
                entries.append(f"{role.mention}\n\n💰 - {self.db.team_budget(guild.id, team['name'])}M")
        content = "\n\n".join(entries) or "No teams have been configured yet."
        message = None
        if config["message_id"]:
            try:
                message = await channel.fetch_message(config["message_id"])
                await message.edit(
                    content=content,
                    allowed_mentions=discord.AllowedMentions(roles=False),
                )
            except (discord.NotFound, discord.Forbidden):
                message = None
        if message is None:
            message = await channel.send(
                content,
                allowed_mentions=discord.AllowedMentions(roles=False),
            )
            self.db.set_budget_message(guild.id, message.id)
        return message

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

    async def require_force_access(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        allowed = self.db.force_role_ids(interaction.guild_id)
        if any(role.id in allowed for role in interaction.user.roles):
            return True
        await interaction.response.send_message(
            "Only administrators and configured force-access roles can use this command.",
            ephemeral=True,
        )
        return False

    async def require_franchise_owner(self, interaction: discord.Interaction) -> bool:
        if not isinstance(interaction.user, discord.Member):
            return False
        if interaction.user.guild_permissions.administrator:
            return True
        config = self.db.league_config(interaction.guild_id)
        if config and config["franchise_role_id"] and any(
            role.id == config["franchise_role_id"] for role in interaction.user.roles
        ):
            return True
        await interaction.response.send_message(
            "Only the configured franchise owner role can use this command.", ephemeral=True
        )
        return False

    async def require_all_rosters_access(self, interaction: discord.Interaction) -> bool:
        """Allow only the server owner and the configured franchise-owner role."""
        if not isinstance(interaction.user, discord.Member) or interaction.guild is None:
            return False
        if interaction.user.id == interaction.guild.owner_id:
            return True
        config = self.db.league_config(interaction.guild_id)
        if config and config["franchise_role_id"] and any(
            role.id == config["franchise_role_id"] for role in interaction.user.roles
        ):
            return True
        await interaction.response.send_message(
            "Only the server owner and the configured Franchise Owner role can view every team's roster.",
            ephemeral=True,
        )
        return False

    def managed_team_for(self, member: discord.Member):
        role_ids = {role.id for role in member.roles}
        matches = [
            team for team in self.db.teams(member.guild.id)
            if team["owner_id"] == member.id or team["role_id"] in role_ids
        ]
        return matches[0] if len(matches) == 1 else None

    def totw_team_for_member(self, member: discord.Member):
        signed_team = self.db.signed_team_for_user(member.guild.id, member.id)
        if signed_team:
            return signed_team
        role_ids = {role.id for role in member.roles}
        matches = [
            team for team in self.db.teams(member.guild.id)
            if team["owner_id"] == member.id or team["role_id"] in role_ids
        ]
        return matches[0] if len(matches) == 1 else None

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
        if isinstance(error, app_commands.CheckFailure) and interaction.response.is_done():
            return
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
        if not self.db.transfer_window_open(interaction.guild_id):
            await interaction.response.send_message("The transfer window is currently closed.", ephemeral=True)
            return
        blacklist = self.db.blacklist_entry(interaction.guild_id, player.id)
        if blacklist:
            await interaction.response.send_message(
                f"That player is blacklisted: {blacklist['reason']}", ephemeral=True
            )
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
            await player.remove_roles(role, reason=f"Released by {interaction.user}")
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
            league = self.db.league_config(interaction.guild.id)
            compact = bool(league and league["log_style"] == "compact")
            description = (
                f"**PLAYER RELEASED**\n{player.mention} was released by {role.mention} — "
                f"Roster `{len(roster):02d}/{roster_cap:02d}`"
                if compact else
                "## PLAYER RELEASED\n"
                f"### {player.mention} / {player.name}\n"
                f"was released by {inline_team_logo(record)}{role.mention}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"- **TEAM** — {inline_team_logo(record)}{role.mention}\n"
                f"- **TEAM OWNER** — {owner_text}\n"
                f"- **ROSTER** — `{len(roster):02d} / {roster_cap:02d}`"
            )
            embed = discord.Embed(
                description=description,
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

    @app_commands.command(name="forceconfig", description="Set roles allowed to force sign and release")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def forceconfig(
        self,
        interaction: discord.Interaction,
        role_1: discord.Role,
        role_2: discord.Role | None = None,
        role_3: discord.Role | None = None,
        role_4: discord.Role | None = None,
        role_5: discord.Role | None = None,
    ):
        roles = list(dict.fromkeys(role for role in (role_1, role_2, role_3, role_4, role_5) if role))
        self.db.configure_force_roles(interaction.guild_id, [role.id for role in roles])
        await interaction.response.send_message(
            "Force-access roles set to: " + ", ".join(role.mention for role in roles),
            ephemeral=True,
        )

    @app_commands.command(name="forcesign", description="Force sign a player to any configured team")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def forcesign(
        self, interaction: discord.Interaction, player: discord.Member, team: str
    ):
        if not await self.require_force_access(interaction):
            return
        assert interaction.guild
        record = self.db.team(interaction.guild.id, team)
        role = interaction.guild.get_role(record["role_id"]) if record else None
        if not record or not role:
            await interaction.response.send_message("That team is not configured correctly.", ephemeral=True)
            return
        if player.bot:
            await interaction.response.send_message("You cannot sign a bot.", ephemeral=True)
            return
        if role in player.roles:
            await interaction.response.send_message("That player already has the team role.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await player.add_roles(role, reason=f"Force signed by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("I cannot assign that role. Check my role position.", ephemeral=True)
            return
        config = self.db.config(interaction.guild.id)
        remove_role = interaction.guild.get_role(config["signing_remove_role_id"]) if config and config["signing_remove_role_id"] else None
        remove_warning = ""
        if remove_role and remove_role in player.roles:
            try:
                await player.remove_roles(remove_role, reason=f"Force signed to {record['name']} by {interaction.user}")
            except discord.Forbidden:
                remove_warning = f" I could not remove {remove_role.mention}; put the bot role above it."
        offer_id = self.db.create_offer(
            interaction.guild.id,
            player.id,
            record["name"],
            role.id,
            interaction.user.id,
            interaction.channel_id,
        )
        self.db.decide_offer(offer_id, "accepted")
        self.db.add_team_member(interaction.guild.id, record["name"], player.id)
        offer = self.db.offer(offer_id)
        await OfferView(self.bot, self.db, offer_id).log_signing(
            interaction.guild, player, role, offer
        )
        await interaction.followup.send(
            f"Force signed {player.mention} to {role.mention}.{remove_warning}", ephemeral=True
        )

    @app_commands.command(name="forcerelease", description="Force release a player from any configured team")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def forcerelease(
        self, interaction: discord.Interaction, player: discord.Member, team: str
    ):
        if not await self.require_force_access(interaction):
            return
        assert interaction.guild
        record = self.db.team(interaction.guild.id, team)
        role = interaction.guild.get_role(record["role_id"]) if record else None
        if not record or not role:
            await interaction.response.send_message("That team is not configured correctly.", ephemeral=True)
            return
        if role not in player.roles:
            await interaction.response.send_message("That player does not have the team role.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await player.remove_roles(role, reason=f"Force released by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("I cannot remove that role. Check my role position.", ephemeral=True)
            return
        self.db.remove_team_member(interaction.guild.id, record["name"], player.id)
        config = self.db.config(interaction.guild.id)
        channel = interaction.guild.get_channel(config["release_channel_id"]) if config else None
        if isinstance(channel, discord.TextChannel):
            roster = get_player_roster(self.db, interaction.guild, role, record["name"])
            league = self.db.league_config(interaction.guild.id)
            compact = bool(league and league["log_style"] == "compact")
            description = (
                f"**PLAYER RELEASED**\n{player.mention} was released by {role.mention} — "
                f"Roster `{len(roster):02d}/{record['roster_cap']:02d}`"
                if compact else
                "## PLAYER RELEASED\n"
                f"### {player.mention} / {player.name}\n"
                f"was released by {inline_team_logo(record)}{role.mention}\n\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                f"- **TEAM** — {inline_team_logo(record)}{role.mention}\n"
                f"- **ACTIONED BY** — {interaction.user.mention}\n"
                f"- **ROSTER** — `{len(roster):02d} / {record['roster_cap']:02d}`"
            )
            embed = discord.Embed(
                description=description,
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow(),
            )
            if record["logo_url"]:
                embed.set_thumbnail(url=record["logo_url"])
            embed.set_author(name=interaction.guild.name)
            embed.set_footer(text="Made By EthanCoys")
            await channel.send(embed=embed)
        await interaction.followup.send(
            f"Force released {player.mention} from {role.mention}.", ephemeral=True
        )

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
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="allrosters", description="View every configured team's signed roster")
    @app_commands.guild_only()
    async def allrosters(self, interaction: discord.Interaction):
        if not await self.require_all_rosters_access(interaction):
            return
        assert interaction.guild
        teams = self.db.teams(interaction.guild.id)
        if not teams:
            await interaction.response.send_message(
                "No teams have been configured yet."
            )
            return

        embeds: list[discord.Embed] = []
        for record in teams:
            role = interaction.guild.get_role(record["role_id"])
            players = (
                get_player_roster(self.db, interaction.guild, role, record["name"])
                if role else []
            )
            player_lines = "\n".join(
                f"`{number:02d}` {player.mention} / **{player.name}**"
                for number, player in enumerate(players, start=1)
            ) or "*No players are currently signed.*"
            embed = discord.Embed(
                title=f"{record['name']} Roster",
                description=(
                    f"**{len(players):02d} / {record['roster_cap']:02d}**\n\n{player_lines}"
                ),
                color=(
                    role.color if role and role.color.value else discord.Color.blurple()
                ),
            )
            if record["logo_url"]:
                embed.set_thumbnail(url=record["logo_url"])
            embed.set_footer(text="Made By EthanCoys")
            embeds.append(embed)

        await interaction.response.send_message(embeds=embeds[:10])
        for index in range(10, len(embeds), 10):
            await interaction.followup.send(embeds=embeds[index:index + 10])

    @app_commands.command(name="totwsetweek", description="Set the active Team of the Week number")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def totwsetweek(
        self, interaction: discord.Interaction, week: app_commands.Range[int, 1, 999]
    ):
        self.db.set_totw_week(interaction.guild_id, week)
        await interaction.response.send_message(
            f"TOTW submissions are now open for week **{week}**.", ephemeral=True
        )

    @app_commands.command(name="uploadstats", description="Upload your FC performance screenshots for TOTW")
    @app_commands.guild_only()
    @app_commands.describe(
        position="Your 3-5-2 position group",
        summary="Screenshot with the Summary tab selected",
        stats="Shooting, Passing, Defending, or Goalkeeping screenshot for your position",
        defending="CDM only: screenshot with the Defending tab selected",
    )
    async def uploadstats(
        self,
        interaction: discord.Interaction,
        position: Literal["ST", "WM", "CAM", "CDM", "CB/FB", "GK"],
        summary: discord.Attachment,
        stats: discord.Attachment,
        defending: discord.Attachment | None = None,
    ):
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        team = self.totw_team_for_member(interaction.user)
        if not team:
            await interaction.response.send_message(
                "Only signed players, team owners, managers, and co-managers can submit TOTW stats.",
                ephemeral=True,
            )
            return
        uploads = [summary, stats] + ([defending] if defending else [])
        if any(item.content_type and not item.content_type.startswith("image/") for item in uploads):
            await interaction.response.send_message("All stat uploads must be images.", ephemeral=True)
            return
        if position == "CDM" and defending is None:
            await interaction.response.send_message(
                "CDMs must upload Summary, Passing, and Defending screenshots.", ephemeral=True
            )
            return
        label_by_position = {
            "ST": "Shooting",
            "WM": "Passing",
            "CAM": "Passing",
            "CDM": "Passing",
            "CB/FB": "Defending",
            "GK": "Goalkeeper",
        }
        await interaction.response.defer(ephemeral=True)
        try:
            summary_bytes, stats_bytes = await asyncio.gather(summary.read(), stats.read())
            summary_rating = await asyncio.to_thread(
                extract_rating, summary_bytes, "Total"
            )
            primary_rating = await asyncio.to_thread(
                extract_rating, stats_bytes, label_by_position[position]
            )
            defending_rating = None
            if position == "CDM" and defending:
                defending_rating = await asyncio.to_thread(
                    extract_rating, await defending.read(), "Defending"
                )
        except ValueError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return

        if position == "CDM":
            score = summary_rating * 0.50 + primary_rating * 0.25 + defending_rating * 0.25
        else:
            score = summary_rating * 0.60 + primary_rating * 0.40
        week = self.db.totw_week(interaction.guild.id)
        self.db.save_totw_submission(
            interaction.guild.id,
            week,
            interaction.user.id,
            team["name"],
            position,
            summary_rating,
            primary_rating,
            defending_rating,
            round(score, 3),
            summary.url,
            stats.url,
            defending.url if defending else None,
        )
        extra = f" | Defending {defending_rating:.1f}" if defending_rating is not None else ""
        await interaction.followup.send(
            f"Week {week} stats saved for **{team['name']}** at **{position}**.\n"
            f"Summary {summary_rating:.1f} | {label_by_position[position]} {primary_rating:.1f}{extra} | TOTW score **{score:.2f}**",
            ephemeral=True,
        )

    @app_commands.command(name="statsuploads", description="Show the screenshots submitted for the active TOTW week")
    @app_commands.guild_only()
    async def statsuploads(self, interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return
        config = self.db.league_config(interaction.guild_id)
        franchise_role_id = config["franchise_role_id"] if config else None
        if not franchise_role_id or not any(
            role.id == franchise_role_id for role in interaction.user.roles
        ):
            await interaction.response.send_message(
                "Only members with the configured Franchise Owner role can view stat uploads.",
                ephemeral=True,
            )
            return

        week = self.db.totw_week(interaction.guild_id)
        submissions = self.db.totw_submissions(interaction.guild_id, week)
        if not submissions:
            await interaction.response.send_message(
                f"No stats have been uploaded for Week **{week}** yet."
            )
            return

        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"TOTW STAT UPLOADS — WEEK {week}",
                description=f"**{len(submissions)}** player(s) have submitted their screenshots.",
                color=discord.Color.blurple(),
            )
        )
        for row in submissions:
            details = discord.Embed(
                title=f"{row['position_group']} — {row['team_name']}",
                description=(
                    f"Player: <@{row['user_id']}>\n"
                    f"Summary: **{row['summary_rating']:.1f}**\n"
                    f"Main stat: **{row['primary_rating']:.1f}**\n"
                    + (f"Defending: **{row['defending_rating']:.1f}**\n" if row["defending_rating"] is not None else "")
                    + f"TOTW score: **{row['score']:.2f}**"
                ),
                color=discord.Color.blurple(),
            )
            details.set_footer(text=f"Submitted by @{interaction.guild.get_member(row['user_id']).name}" if interaction.guild.get_member(row["user_id"]) else f"User ID {row['user_id']}")
            await interaction.followup.send(embed=details)
            image_rows = (
                ("Summary screenshot", row["summary_url"]),
                ("Main stats screenshot", row["stats_url"]),
                ("Defending screenshot", row["defending_url"]),
            )
            image_embeds = []
            for title, url in image_rows:
                if url:
                    image_embed = discord.Embed(title=title, color=discord.Color.dark_grey())
                    image_embed.set_image(url=url)
                    image_embeds.append(image_embed)
            if image_embeds:
                await interaction.followup.send(embeds=image_embeds)
            else:
                await interaction.followup.send(
                    f"No saved screenshots are available for <@{row['user_id']}> because this submission was made before image saving was added."
                )

    @app_commands.command(name="totwlist", description="Show the current 3-5-2 Team of the Week")
    @app_commands.guild_only()
    async def totwlist(self, interaction: discord.Interaction):
        week = self.db.totw_week(interaction.guild_id)
        submissions = self.db.totw_submissions(interaction.guild_id, week)
        slot_plan = [
            ("GK", "GK", 1),
            ("CB/FB", "DEF", 3),
            ("CDM", "CDM", 2),
            ("CAM", "CAM", 1),
            ("WM", "WM", 2),
            ("ST", "ST", 2),
        ]
        lines = []
        selected_count = 0
        for position_group, label, count in slot_plan:
            candidates = [row for row in submissions if row["position_group"] == position_group]
            for index in range(count):
                if index < len(candidates):
                    row = candidates[index]
                    player_name = f"<@{row['user_id']}>"
                    lines.append(
                        f"**{label}**  {player_name}  -  {row['team_name']}  -  `{row['score']:.2f}`"
                    )
                    selected_count += 1
                else:
                    lines.append(f"**{label}**  *Vacant*")
        embed = discord.Embed(
            title=f"TEAM OF THE WEEK - WEEK {week}",
            description=(
                "**Formation: 3-5-2**\n\n" + "\n".join(lines)
            ),
            color=discord.Color.gold(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(
            text=f"{selected_count}/11 positions filled - Made By EthanCoys"
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="budgetsetup", description="Set the channel for the live team budget list")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def budgetsetup(
        self, interaction: discord.Interaction, channel: discord.TextChannel,
        starting_budget: app_commands.Range[int, 0, 1000000],
    ):
        assert interaction.guild
        await interaction.response.defer(ephemeral=True)
        self.db.configure_budget_channel(interaction.guild.id, channel.id, starting_budget)
        await self.refresh_budget_message(interaction.guild)
        await interaction.followup.send(
            f"The live budget list is now in {channel.mention}. Every configured team starts with **{starting_budget}M**.",
            ephemeral=True,
        )

    @app_commands.command(name="setbudget", description="Set a configured team's budget in millions")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.autocomplete(team=team_autocomplete)
    async def setbudget(
        self, interaction: discord.Interaction, team: str,
        amount: app_commands.Range[int, 0, 1000000],
    ):
        assert interaction.guild
        record = self.db.team(interaction.guild.id, team)
        if not record:
            await interaction.response.send_message("That team is not configured.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        self.db.set_team_budget(interaction.guild.id, record["name"], amount)
        await self.refresh_budget_message(interaction.guild)
        await interaction.followup.send(
            f"{interaction.guild.get_role(record['role_id']).mention} now has **{amount}M**.",
            ephemeral=True,
        )

    @app_commands.command(name="budgets", description="Refresh the live team budget message")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def budgets(self, interaction: discord.Interaction):
        assert interaction.guild
        await interaction.response.defer(ephemeral=True)
        message = await self.refresh_budget_message(interaction.guild)
        await interaction.followup.send(
            "Budget message refreshed." if message else "Run /budgetsetup first.",
            ephemeral=True,
        )

    @app_commands.command(name="transfer", description="Transfer a signed player between teams for a fee")
    @app_commands.guild_only()
    @app_commands.autocomplete(selling_team=team_autocomplete, buying_team=team_autocomplete)
    async def transfer(
        self, interaction: discord.Interaction, player: discord.Member,
        selling_team: str, buying_team: str,
        fee: app_commands.Range[int, 0, 1000000],
    ):
        if not await self.require_force_access(interaction):
            return
        if not self.db.transfer_window_open(interaction.guild_id):
            await interaction.response.send_message("The transfer window is currently closed.", ephemeral=True)
            return
        assert interaction.guild
        seller = self.db.team(interaction.guild.id, selling_team)
        buyer = self.db.team(interaction.guild.id, buying_team)
        if not seller or not buyer or seller["name"].casefold() == buyer["name"].casefold():
            await interaction.response.send_message("Choose two different configured teams.", ephemeral=True)
            return
        seller_role = interaction.guild.get_role(seller["role_id"])
        buyer_role = interaction.guild.get_role(buyer["role_id"])
        if not seller_role or not buyer_role or seller_role not in player.roles:
            await interaction.response.send_message("The player is not signed to the selling team.", ephemeral=True)
            return
        if self.db.active_loan(interaction.guild.id, player.id):
            await interaction.response.send_message("End the player's active loan before transferring them.", ephemeral=True)
            return
        if self.db.team_budget(interaction.guild.id, buyer["name"]) < fee:
            await interaction.response.send_message("The buying team does not have enough budget.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await player.remove_roles(seller_role, reason=f"Transfer actioned by {interaction.user}")
            await player.add_roles(buyer_role, reason=f"Transfer actioned by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("I cannot move those roles. Put my bot role above both team roles.", ephemeral=True)
            return
        self.db.complete_transfer(
            interaction.guild.id, player.id, seller["name"], buyer["name"], fee, interaction.user.id
        )
        await self.refresh_budget_message(interaction.guild)
        await interaction.followup.send(
            f"Transferred {player.mention} from {seller_role.mention} to {buyer_role.mention} for **{fee}M**.",
            ephemeral=True,
        )

    @app_commands.command(name="loan", description="Loan a signed player to another configured team")
    @app_commands.guild_only()
    @app_commands.autocomplete(parent_team=team_autocomplete, loan_team=team_autocomplete)
    async def loan(
        self, interaction: discord.Interaction, player: discord.Member,
        parent_team: str, loan_team: str,
    ):
        if not await self.require_force_access(interaction):
            return
        if not self.db.transfer_window_open(interaction.guild_id):
            await interaction.response.send_message("The transfer window is currently closed.", ephemeral=True)
            return
        assert interaction.guild
        parent = self.db.team(interaction.guild.id, parent_team)
        destination = self.db.team(interaction.guild.id, loan_team)
        if not parent or not destination or parent["name"].casefold() == destination["name"].casefold():
            await interaction.response.send_message("Choose two different configured teams.", ephemeral=True)
            return
        parent_role = interaction.guild.get_role(parent["role_id"])
        loan_role = interaction.guild.get_role(destination["role_id"])
        if not parent_role or not loan_role or parent_role not in player.roles:
            await interaction.response.send_message("The player is not signed to the parent team.", ephemeral=True)
            return
        if self.db.active_loan(interaction.guild.id, player.id):
            await interaction.response.send_message("That player already has an active loan.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await player.remove_roles(parent_role, reason=f"Loan actioned by {interaction.user}")
            await player.add_roles(loan_role, reason=f"Loan actioned by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("I cannot move those roles. Put my bot role above both team roles.", ephemeral=True)
            return
        self.db.start_loan(
            interaction.guild.id, player.id, parent["name"], destination["name"], interaction.user.id
        )
        await interaction.followup.send(
            f"Loaned {player.mention} from {parent_role.mention} to {loan_role.mention}.", ephemeral=True
        )

    @app_commands.command(name="endloan", description="End a player's active loan and return them")
    @app_commands.guild_only()
    async def endloan(self, interaction: discord.Interaction, player: discord.Member):
        if not await self.require_force_access(interaction):
            return
        assert interaction.guild
        loan = self.db.active_loan(interaction.guild.id, player.id)
        if not loan:
            await interaction.response.send_message("That player does not have an active loan.", ephemeral=True)
            return
        parent = self.db.team(interaction.guild.id, loan["parent_team"])
        destination = self.db.team(interaction.guild.id, loan["loan_team"])
        parent_role = interaction.guild.get_role(parent["role_id"]) if parent else None
        loan_role = interaction.guild.get_role(destination["role_id"]) if destination else None
        if not parent_role or not loan_role:
            await interaction.response.send_message("One of the loan team roles no longer exists.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await player.remove_roles(loan_role, reason=f"Loan ended by {interaction.user}")
            await player.add_roles(parent_role, reason=f"Loan ended by {interaction.user}")
        except discord.Forbidden:
            await interaction.followup.send("I cannot move those roles. Put my bot role above both team roles.", ephemeral=True)
            return
        self.db.finish_loan(interaction.guild.id, player.id)
        await interaction.followup.send(
            f"Loan ended. {player.mention} returned to {parent_role.mention}.", ephemeral=True
        )

    @app_commands.command(name="loans", description="Show every active player loan")
    @app_commands.guild_only()
    async def loans(self, interaction: discord.Interaction):
        rows = self.db.active_loans(interaction.guild_id)
        if not rows:
            await interaction.response.send_message("There are no active loans.")
            return
        lines = []
        for loan in rows:
            parent = self.db.team(interaction.guild_id, loan["parent_team"])
            destination = self.db.team(interaction.guild_id, loan["loan_team"])
            parent_text = f"<@&{parent['role_id']}>" if parent else loan["parent_team"]
            destination_text = f"<@&{destination['role_id']}>" if destination else loan["loan_team"]
            lines.append(f"<@{loan['player_id']}> — {parent_text} → {destination_text}")
        embed = discord.Embed(
            title="ACTIVE LOANS",
            description="\n".join(lines),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_footer(text="Made By EthanCoys")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="pollconfig", description="Set the role pinged for custom polls")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def pollconfig(self, interaction: discord.Interaction, ping_role: discord.Role):
        self.db.configure_poll_role(interaction.guild_id, ping_role.id)
        await interaction.response.send_message(
            f"Custom polls will ping {ping_role.mention}.", ephemeral=True
        )

    @app_commands.command(name="poll", description="Create a custom poll and ping the configured role")
    @app_commands.guild_only()
    async def poll(
        self, interaction: discord.Interaction, question: str,
        option_1: str, option_2: str,
        option_3: str | None = None, option_4: str | None = None,
        duration: str = "24h",
        allow_multiple: bool = False,
    ):
        if not await self.require_force_access(interaction):
            return
        config = self.db.poll_config(interaction.guild_id)
        if not config:
            await interaction.response.send_message("Run /pollconfig first.", ephemeral=True)
            return
        role = interaction.guild.get_role(config["ping_role_id"])
        if role is None:
            await interaction.response.send_message("The configured poll role no longer exists.", ephemeral=True)
            return
        match = re.fullmatch(r"\s*(\d+)\s*([hdw])\s*", duration.lower())
        if not match:
            await interaction.response.send_message(
                "Use a duration like `1h`, `12h`, `3d`, or `1w`.", ephemeral=True
            )
            return
        amount = int(match.group(1))
        unit = match.group(2)
        hours = amount * {"h": 1, "d": 24, "w": 168}[unit]
        if hours < 1 or hours > 768:
            await interaction.response.send_message(
                "Discord polls can run from 1 hour up to 32 days.", ephemeral=True
            )
            return
        poll = discord.Poll(
            question=question[:300],
            duration=timedelta(hours=hours),
            multiple=allow_multiple,
        )
        for answer in (option_1, option_2, option_3, option_4):
            if answer:
                poll.add_answer(text=answer[:55])
        await interaction.response.send_message(
            content=role.mention,
            poll=poll,
            allowed_mentions=discord.AllowedMentions(roles=True),
        )

    @app_commands.command(name="franchiseconfig", description="Set the Discord role used for franchise owners")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def franchiseconfig(self, interaction: discord.Interaction, role: discord.Role):
        self.db.configure_franchise_role(interaction.guild_id, role.id)
        await interaction.response.send_message(f"Franchise owner role set to {role.mention}.", ephemeral=True)

    @app_commands.command(name="appointfranchiseowner", description="Give a member the franchise owner role")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def appointfranchiseowner(self, interaction: discord.Interaction, member: discord.Member):
        config = self.db.league_config(interaction.guild_id)
        role = interaction.guild.get_role(config["franchise_role_id"]) if config and config["franchise_role_id"] else None
        if role is None:
            await interaction.response.send_message("Run /franchiseconfig first.", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason=f"Appointed by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("I cannot assign that role. Put my bot role above it.", ephemeral=True)
            return
        await interaction.response.send_message(f"Appointed {member.mention} as a franchise owner.", ephemeral=True)

    @app_commands.command(name="blacklist", description="Blacklist a player from club offers")
    @app_commands.guild_only()
    async def blacklist(self, interaction: discord.Interaction, player: discord.Member, reason: str):
        if not await self.require_franchise_owner(interaction):
            return
        self.db.blacklist_user(interaction.guild_id, player.id, reason[:250], interaction.user.id)
        await interaction.response.send_message(f"Blacklisted {player.mention}: {reason}", ephemeral=True)

    @app_commands.command(name="removeblacklist", description="Remove a player from the blacklist")
    @app_commands.guild_only()
    async def removeblacklist(self, interaction: discord.Interaction, player: discord.Member):
        if not await self.require_franchise_owner(interaction):
            return
        removed = self.db.remove_blacklist(interaction.guild_id, player.id)
        await interaction.response.send_message(
            f"Removed {player.mention} from the blacklist." if removed else "That player is not blacklisted.",
            ephemeral=True,
        )

    @app_commands.command(name="blacklistlist", description="View every blacklisted player")
    @app_commands.guild_only()
    async def blacklistlist(self, interaction: discord.Interaction):
        if not await self.require_franchise_owner(interaction):
            return
        rows = self.db.blacklist_entries(interaction.guild_id)
        text = "\n".join(f"<@{row['user_id']}> — {row['reason']}" for row in rows) or "No blacklisted players."
        await interaction.response.send_message(embed=discord.Embed(title="BLACKLIST", description=text, color=discord.Color.red()), ephemeral=True)

    @app_commands.command(name="openwindow", description="Open the transfer window")
    @app_commands.guild_only()
    async def openwindow(self, interaction: discord.Interaction):
        if not await self.require_franchise_owner(interaction):
            return
        self.db.set_transfer_window(interaction.guild_id, True)
        await interaction.response.send_message("The transfer window is now **OPEN**.")

    @app_commands.command(name="closewindow", description="Close the transfer window")
    @app_commands.guild_only()
    async def closewindow(self, interaction: discord.Interaction):
        if not await self.require_franchise_owner(interaction):
            return
        self.db.set_transfer_window(interaction.guild_id, False)
        await interaction.response.send_message("The transfer window is now **CLOSED**.")

    @app_commands.command(name="canceloffer", description="Cancel one of your pending offers")
    @app_commands.guild_only()
    async def canceloffer(self, interaction: discord.Interaction, offer_id: int):
        offer = self.db.offer(offer_id)
        if not offer or offer["guild_id"] != interaction.guild_id or offer["status"] != "pending":
            await interaction.response.send_message("That pending offer was not found.", ephemeral=True)
            return
        config = self.db.league_config(interaction.guild_id)
        is_franchise = isinstance(interaction.user, discord.Member) and config and config["franchise_role_id"] and any(
            role.id == config["franchise_role_id"] for role in interaction.user.roles
        )
        if offer["offered_by"] != interaction.user.id and not interaction.user.guild_permissions.administrator and not is_franchise:
            await interaction.response.send_message("You cannot cancel that offer.", ephemeral=True)
            return
        self.db.cancel_offer(offer_id, interaction.guild_id)
        await interaction.response.send_message(f"Offer #{offer_id} cancelled.", ephemeral=True)

    @app_commands.command(name="myoffers", description="View your pending player offers")
    @app_commands.guild_only()
    async def myoffers(self, interaction: discord.Interaction):
        rows = self.db.pending_offers_for_player(interaction.guild_id, interaction.user.id)
        text = "\n".join(f"**#{row['id']}** — {row['team_name']} — <@{row['offered_by']}>" for row in rows) or "You have no pending offers."
        await interaction.response.send_message(embed=discord.Embed(title="MY OFFERS", description=text, color=discord.Color.blurple()), ephemeral=True)

    @app_commands.command(name="teamoffers", description="View pending offers sent by a team")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def teamoffers(self, interaction: discord.Interaction, team: str):
        if not await self.require_franchise_owner(interaction):
            return
        record = self.db.team(interaction.guild_id, team)
        if not record:
            await interaction.response.send_message("That team is not configured.", ephemeral=True)
            return
        rows = self.db.pending_offers_for_team(interaction.guild_id, record["name"])
        text = "\n".join(f"**#{row['id']}** — <@{row['player_id']}> — sent by <@{row['offered_by']}>" for row in rows) or "No pending offers."
        await interaction.response.send_message(embed=discord.Embed(title=f"{record['name']} OFFERS", description=text, color=discord.Color.blurple()), ephemeral=True)

    @app_commands.command(name="editteam", description="Edit a configured team's details")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def editteam(
        self, interaction: discord.Interaction, team: str, new_name: str,
        role: discord.Role, owner: discord.Member,
        roster_cap: app_commands.Range[int, 1, 99] = 22,
    ):
        if not await self.require_franchise_owner(interaction):
            return
        record = self.db.team(interaction.guild_id, team)
        if not record:
            await interaction.response.send_message("That team is not configured.", ephemeral=True)
            return
        self.db.update_team(interaction.guild_id, record["name"], new_name.strip(), role.id, owner.id, roster_cap)
        await interaction.response.send_message(f"Updated **{record['name']}** to {role.mention} / **{new_name.strip()}**.", ephemeral=True)

    @app_commands.command(name="transferownership", description="Transfer ownership of a configured team")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def transferownership(self, interaction: discord.Interaction, team: str, new_owner: discord.Member):
        if not await self.require_franchise_owner(interaction):
            return
        record = self.db.team(interaction.guild_id, team)
        if not record:
            await interaction.response.send_message("That team is not configured.", ephemeral=True)
            return
        self.db.set_team_owner(interaction.guild_id, record["name"], new_owner.id)
        await interaction.response.send_message(f"{new_owner.mention} now owns **{record['name']}**.", ephemeral=True)

    async def change_management_roles(
        self, interaction: discord.Interaction, player: discord.Member,
        team: str, level: Literal["Manager", "Co-Manager"], remove: bool = False,
    ):
        record = self.db.team(interaction.guild_id, team)
        config = self.db.config(interaction.guild_id)
        if not record or not config:
            await interaction.response.send_message("The team or management roles are not configured.", ephemeral=True)
            return
        role_id = config["manager_role_1_id"] if level == "Manager" else config["manager_role_2_id"]
        management_role = interaction.guild.get_role(role_id)
        team_role = interaction.guild.get_role(record["role_id"])
        if not management_role or not team_role:
            await interaction.response.send_message("A required Discord role no longer exists.", ephemeral=True)
            return
        try:
            if remove:
                await player.remove_roles(management_role, reason=f"Demoted by {interaction.user}")
            else:
                await player.add_roles(team_role, management_role, reason=f"Promoted by {interaction.user}")
                self.db.add_team_member(interaction.guild_id, record["name"], player.id)
        except discord.Forbidden:
            await interaction.response.send_message("I cannot manage those roles. Move my bot role higher.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"{'Demoted' if remove else 'Promoted'} {player.mention} {'from' if remove else 'to'} {management_role.mention}.", ephemeral=True
        )

    @app_commands.command(name="promote", description="Promote a player to manager or co-manager")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def promote(self, interaction: discord.Interaction, player: discord.Member, team: str, level: Literal["Manager", "Co-Manager"]):
        if not await self.require_franchise_owner(interaction):
            return
        await self.change_management_roles(interaction, player, team, level)

    @app_commands.command(name="demoteco", description="Demote a co-manager back to player")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def demoteco(self, interaction: discord.Interaction, player: discord.Member, team: str):
        if not await self.require_franchise_owner(interaction):
            return
        await self.change_management_roles(interaction, player, team, "Co-Manager", remove=True)

    @app_commands.command(name="forcepromote", description="Force promote a player to management")
    @app_commands.guild_only()
    @app_commands.autocomplete(team=team_autocomplete)
    async def forcepromote(self, interaction: discord.Interaction, player: discord.Member, team: str, level: Literal["Manager", "Co-Manager"]):
        if not await self.require_force_access(interaction):
            return
        await self.change_management_roles(interaction, player, team, level)

    @app_commands.command(name="forcedemote", description="Remove both management roles from a member")
    @app_commands.guild_only()
    async def forcedemote(self, interaction: discord.Interaction, player: discord.Member):
        if not await self.require_force_access(interaction):
            return
        config = self.db.config(interaction.guild_id)
        roles = [interaction.guild.get_role(config[key]) for key in ("manager_role_1_id", "manager_role_2_id")] if config else []
        roles = [role for role in roles if role]
        try:
            await player.remove_roles(*roles, reason=f"Force demoted by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("I cannot remove those roles.", ephemeral=True)
            return
        await interaction.response.send_message(f"Force demoted {player.mention} to player.", ephemeral=True)

    @app_commands.command(name="recallloan", description="Recall a player from their active loan")
    @app_commands.guild_only()
    async def recallloan(self, interaction: discord.Interaction, player: discord.Member):
        if not await self.require_franchise_owner(interaction):
            return
        loan = self.db.active_loan(interaction.guild_id, player.id)
        if not loan:
            await interaction.response.send_message("That player does not have an active loan.", ephemeral=True)
            return
        parent = self.db.team(interaction.guild_id, loan["parent_team"])
        destination = self.db.team(interaction.guild_id, loan["loan_team"])
        parent_role = interaction.guild.get_role(parent["role_id"]) if parent else None
        loan_role = interaction.guild.get_role(destination["role_id"]) if destination else None
        if not parent_role or not loan_role:
            await interaction.response.send_message("One of the loan team roles no longer exists.", ephemeral=True)
            return
        try:
            await player.remove_roles(loan_role, reason=f"Loan recalled by {interaction.user}")
            await player.add_roles(parent_role, reason=f"Loan recalled by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("I cannot move those roles. Move my bot role higher.", ephemeral=True)
            return
        self.db.finish_loan(interaction.guild_id, player.id)
        await interaction.response.send_message(f"Recalled {player.mention} to {parent_role.mention}.", ephemeral=True)

    @app_commands.command(name="result", description="Submit a league match result")
    @app_commands.guild_only()
    @app_commands.autocomplete(home_team=team_autocomplete, away_team=team_autocomplete)
    async def result(
        self, interaction: discord.Interaction, home_team: str, away_team: str,
        home_score: app_commands.Range[int, 0, 99], away_score: app_commands.Range[int, 0, 99],
    ):
        if not await self.require_manager(interaction):
            return
        home = self.db.team(interaction.guild_id, home_team)
        away = self.db.team(interaction.guild_id, away_team)
        managed = self.managed_team_for(interaction.user)
        if not home or not away or home["name"].casefold() == away["name"].casefold():
            await interaction.response.send_message("Choose two different configured teams.", ephemeral=True)
            return
        if not managed or managed["name"].casefold() not in {home["name"].casefold(), away["name"].casefold()}:
            await interaction.response.send_message("You can only submit a result involving your team.", ephemeral=True)
            return
        self.db.add_result(interaction.guild_id, home["name"], away["name"], home_score, away_score, interaction.user.id)
        await interaction.response.send_message(f"**{home['name']} {home_score}–{away_score} {away['name']}**")

    @app_commands.command(name="standings", description="Show the current league standings")
    @app_commands.guild_only()
    async def standings(self, interaction: discord.Interaction):
        if not await self.require_franchise_owner(interaction):
            return
        table = {team["name"]: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0} for team in self.db.teams(interaction.guild_id)}
        for row in self.db.results(interaction.guild_id):
            if row["home_team"] not in table or row["away_team"] not in table:
                continue
            home, away = table[row["home_team"]], table[row["away_team"]]
            home["p"] += 1; away["p"] += 1
            home["gf"] += row["home_score"]; home["ga"] += row["away_score"]
            away["gf"] += row["away_score"]; away["ga"] += row["home_score"]
            if row["home_score"] > row["away_score"]:
                home["w"] += 1; home["pts"] += 3; away["l"] += 1
            elif row["home_score"] < row["away_score"]:
                away["w"] += 1; away["pts"] += 3; home["l"] += 1
            else:
                home["d"] += 1; away["d"] += 1; home["pts"] += 1; away["pts"] += 1
        ordered = sorted(table.items(), key=lambda item: (item[1]["pts"], item[1]["gf"] - item[1]["ga"], item[1]["gf"]), reverse=True)
        lines = ["`#  TEAM                 P  W  D  L  GD PTS`"]
        for index, (name, stats) in enumerate(ordered, 1):
            gd = stats["gf"] - stats["ga"]
            lines.append(f"`{index:>2} {name[:18]:<18} {stats['p']:>2} {stats['w']:>2} {stats['d']:>2} {stats['l']:>2} {gd:>3} {stats['pts']:>3}`")
        await interaction.response.send_message(embed=discord.Embed(title="LEAGUE STANDINGS", description="\n".join(lines), color=discord.Color.gold()))

    @app_commands.command(name="logstyle", description="Choose compact or detailed bot logs")
    @app_commands.guild_only()
    async def logstyle(self, interaction: discord.Interaction, style: Literal["Compact", "Detailed"]):
        if not await self.require_franchise_owner(interaction):
            return
        self.db.set_log_style(interaction.guild_id, style.lower())
        await interaction.response.send_message(f"Log style changed to **{style}**.", ephemeral=True)

    @app_commands.command(name="debug", description="Check the bot configuration and permissions")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def debug(self, interaction: discord.Interaction):
        config = self.db.config(interaction.guild_id)
        league = self.db.league_config(interaction.guild_id)
        description = (
            f"Database: **Connected**\nTeams: **{len(self.db.teams(interaction.guild_id))}**\n"
            f"Club setup: **{'Ready' if config else 'Missing'}**\n"
            f"Franchise role: **{'Ready' if league and league['franchise_role_id'] else 'Missing'}**\n"
            f"Transfer window: **{'Open' if self.db.transfer_window_open(interaction.guild_id) else 'Closed'}**\n"
            f"Budget setup: **{'Ready' if self.db.budget_config(interaction.guild_id) else 'Missing'}**"
        )
        await interaction.response.send_message(embed=discord.Embed(title="BOT DEBUG", description=description, color=discord.Color.green()), ephemeral=True)

    @app_commands.command(name="endseason", description="Reset all season activity while keeping configured teams")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def endseason(self, interaction: discord.Interaction, confirm: bool):
        if not confirm:
            await interaction.response.send_message("Nothing was reset. Set confirm to True to end the season.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        self.db.end_season(interaction.guild_id)
        await self.refresh_budget_message(interaction.guild)
        await interaction.followup.send("Season ended. Results, offers, loans, rosters and season data were reset.", ephemeral=True)

    @app_commands.command(name="help", description="Show all XPC management commands")
    @app_commands.guild_only()
    async def help_command(self, interaction: discord.Interaction):
        text = (
            "**Clubs:** `/offer` `/release` `/roster` `/allrosters` `/myoffers` `/canceloffer` `/signingremoverole`\n"
            "**Transfers:** `/transfer` `/loan` `/endloan` `/recallloan` `/loans` `/openwindow` `/closewindow`\n"
            "**Budgets:** `/budgetsetup` `/setbudget` `/budgets`\n"
            "**League:** `/result` `/standings` `/endseason`\n"
            "**Teams:** `/addteam` `/editteam` `/removeteam` `/transferownership` `/teamoffers`\n"
            "**Staff:** `/promote` `/demoteco` `/forcepromote` `/forcedemote` `/forcesign` `/forcerelease`\n"
            "**Safety:** `/blacklist` `/removeblacklist` `/blacklistlist` `/debug`\n"
            "**Community:** `/quicksetup` `/poll` `/pollconfig` `/ticketsetup` `/applicationsetup` `/rolesaversetup` `/welcomesetup` `/rulesembed`\n"
            "**Moderation:** `/moderationsetup` `/warn` `/warnings` `/kick` `/ban` `/timeout` `/purge`\n"
            "**Safety & recovery:** `/channelbackup` `/channelbackups` `/restorechannel` `/invites`\n"
            "**TOTW:** `/uploadstats` `/statsuploads` `/totwlist` `/totwsetweek`"
        )
        embed = discord.Embed(title="XPC COMMAND HELP", description=text, color=discord.Color.blurple())
        embed.set_footer(text="Made By EthanCoys")
        await interaction.response.send_message(embed=embed)

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
        await interaction.response.send_message(embed=embed)

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
        await interaction.response.send_message(f"Added **{name.strip()}** using {role.mention}.")

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
        await interaction.response.send_message(text or "No teams are configured yet.")

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
        )

    @app_commands.command(name="quicksetup", description="Guided Yes/No setup using channel and role selectors")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def quicksetup(self, interaction: discord.Interaction):
        wizard = QuickSetupWizard(self, interaction.user.id, interaction.guild)
        await interaction.response.send_message(
            embed=wizard.question_embed(),
            view=QuickSetupView(wizard),
        )

    @app_commands.command(name="signingremoverole", description="Choose the role removed automatically when a player signs")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def signingremoverole(self, interaction: discord.Interaction, role: discord.Role):
        if role.is_default() or role.managed:
            await interaction.response.send_message("Choose a normal server role.", ephemeral=True)
            return
        if not self.db.config(interaction.guild_id):
            await interaction.response.send_message("Run `/config_setup` first.", ephemeral=True)
            return
        self.db.set_signing_remove_role(interaction.guild_id, role.id)
        await interaction.response.send_message(
            f"{role.mention} will now be removed automatically whenever a player accepts an offer or is force-signed. Put the bot role above this role.",
            ephemeral=True,
        )

    @app_commands.command(name="rulesembed", description="Post rules cards in a selected channel")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel where the rules should be posted",
        rules_banner="Wide image displayed with the server rules",
        rules_text="Rules and welcome text",
        contact_banner="Optional wide image for the moderator section",
        contact_text="Optional instructions for contacting moderators",
    )
    async def rulesembed(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        rules_banner: discord.Attachment,
        rules_text: app_commands.Range[str, 1, 4000],
        contact_banner: discord.Attachment | None = None,
        contact_text: app_commands.Range[str, 1, 4000] | None = None,
    ):
        attachments = [rules_banner] + ([contact_banner] if contact_banner else [])
        if any(item.content_type and not item.content_type.startswith("image/") for item in attachments):
            await interaction.response.send_message("Banner files must be images.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        rules_file = discord.File(
            io.BytesIO(await rules_banner.read()), filename="server-rules-banner.png"
        )
        rules_embed = discord.Embed(
            description=rules_text,
            color=discord.Color.blurple(),
        )
        rules_embed.set_author(name=interaction.guild.name)
        rules_embed.set_image(url="attachment://server-rules-banner.png")
        rules_embed.set_footer(text="Made By EthanCoys")
        await channel.send(embed=rules_embed, file=rules_file)

        if contact_banner or contact_text:
            contact_embed = discord.Embed(
                description=contact_text or "Contact the moderation team if you need help.",
                color=discord.Color.magenta(),
            )
            contact_embed.set_author(name="CONTACTING MODERATORS")
            contact_embed.set_footer(text="Made By EthanCoys")
            if contact_banner:
                contact_file = discord.File(
                    io.BytesIO(await contact_banner.read()), filename="contact-moderators-banner.png"
                )
                contact_embed.set_image(url="attachment://contact-moderators-banner.png")
                await channel.send(embed=contact_embed, file=contact_file)
            else:
                await channel.send(embed=contact_embed)

        await interaction.followup.send(
            f"Rules cards posted in {channel.mention}.", ephemeral=True
        )

    @app_commands.command(name="welcomesetup", description="Configure a custom welcome image")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        channel="Channel where welcome cards are posted",
        banner="Your wide welcome background image",
        headline="Message shown above the image; supports {user}, {display}, {server}, and {count}",
    )
    async def welcomesetup(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        banner: discord.Attachment,
        headline: str = "Welcome {user} to {server}!",
    ):
        if banner.content_type and not banner.content_type.startswith("image/"):
            await interaction.response.send_message("The banner must be an image file.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        suffix = Path(banner.filename).suffix.lower() or ".png"
        banner_path = self.db.path.parent / f"welcome_banner_{interaction.guild_id}{suffix}"
        banner_bytes = await banner.read()
        try:
            await asyncio.to_thread(banner_path.write_bytes, banner_bytes)
            await asyncio.to_thread(lambda: Image.open(banner_path).verify())
        except (OSError, ValueError):
            await interaction.followup.send("Discord could not process that banner image.", ephemeral=True)
            return
        self.db.configure_welcome(
            interaction.guild_id,
            channel.id,
            str(banner_path),
            headline[:100],
            "",
        )
        await interaction.followup.send(
            f"Welcome system configured for {channel.mention}.\n"
            "Message headline placeholders: `{user}`, `{display}`, `{server}`, `{count}`.",
            ephemeral=True,
        )

    @app_commands.command(name="welcometest", description="Test the configured welcome card")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def welcometest(self, interaction: discord.Interaction):
        assert interaction.guild and isinstance(interaction.user, discord.Member)
        config = self.db.welcome_config(interaction.guild.id)
        if not config:
            await interaction.response.send_message(
                "Run /welcomesetup first.", ephemeral=True
            )
            return
        channel = interaction.guild.get_channel(config["channel_id"])
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "The configured welcome channel no longer exists.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        sent = await self.send_welcome_card(interaction.user, channel, config)
        await interaction.followup.send(
            f"Welcome test posted in {channel.mention}." if sent else "The welcome card could not be generated.",
            ephemeral=True,
        )

    @app_commands.command(name="moderationsetup", description="Set moderation logs and automatic scam protection")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def moderationsetup(self, interaction: discord.Interaction, log_channel: discord.TextChannel, scam_protection: bool = True):
        self.db.configure_moderation(interaction.guild_id, log_channel.id, scam_protection)
        await interaction.response.send_message(f"Moderation logs set to {log_channel.mention}. Image-money scam protection is **{'ON' if scam_protection else 'OFF'}**.", ephemeral=True)

    @app_commands.command(name="warn", description="Warn a server member")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warn(self, interaction: discord.Interaction, member: discord.Member, reason: str):
        warning_id = self.db.add_warning(interaction.guild_id, member.id, interaction.user.id, reason)
        try: await member.send(f"You were warned in **{interaction.guild.name}**.\nReason: {reason}")
        except discord.Forbidden: pass
        await interaction.response.send_message(f"Warned {member.mention}. Warning `#{warning_id}`.", ephemeral=True)
        await self.send_mod_log(interaction.guild, "Member Warned", f"Member: {member.mention}\nModerator: {interaction.user.mention}\nReason: {reason}")

    @app_commands.command(name="warnings", description="View a member's warnings")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def warnings(self, interaction: discord.Interaction, member: discord.Member):
        rows = self.db.warnings_for(interaction.guild_id, member.id)
        lines = [f"`#{row['id']}` {row['reason']} — <@{row['moderator_id']}>" for row in rows[:20]] or ["No warnings."]
        await interaction.response.send_message(embed=discord.Embed(title=f"Warnings — {member}", description="\n".join(lines), color=discord.Color.orange()), ephemeral=True)

    @app_commands.command(name="kick", description="Kick a member from the server")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    async def kick_member(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message("You cannot kick someone with an equal or higher role.", ephemeral=True); return
        await member.kick(reason=f"{reason} — {interaction.user}")
        await interaction.response.send_message(f"Kicked **{member}**.", ephemeral=True)
        await self.send_mod_log(interaction.guild, "Member Kicked", f"Member: **{member}** (`{member.id}`)\nModerator: {interaction.user.mention}\nReason: {reason}", discord.Color.red())

    @app_commands.command(name="ban", description="Ban a member from the server")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    async def ban_member(self, interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
        if member.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id:
            await interaction.response.send_message("You cannot ban someone with an equal or higher role.", ephemeral=True); return
        await member.ban(reason=f"{reason} — {interaction.user}", delete_message_seconds=86400)
        await interaction.response.send_message(f"Banned **{member}**.", ephemeral=True)
        await self.send_mod_log(interaction.guild, "Member Banned", f"Member: **{member}** (`{member.id}`)\nModerator: {interaction.user.mention}\nReason: {reason}", discord.Color.red())

    @app_commands.command(name="timeout", description="Temporarily timeout a member")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    async def timeout_member(self, interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 40320], reason: str = "No reason provided"):
        await member.timeout(timedelta(minutes=minutes), reason=f"{reason} — {interaction.user}")
        await interaction.response.send_message(f"Timed out {member.mention} for **{minutes} minutes**.", ephemeral=True)
        await self.send_mod_log(interaction.guild, "Member Timed Out", f"Member: {member.mention}\nModerator: {interaction.user.mention}\nLength: {minutes} minutes\nReason: {reason}")

    @app_commands.command(name="purge", description="Delete multiple messages from the current channel")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        if not isinstance(interaction.channel, discord.TextChannel): return
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"Deleted **{len(deleted)}** messages.", ephemeral=True)
        await self.send_mod_log(interaction.guild, "Messages Purged", f"Moderator: {interaction.user.mention}\nChannel: {interaction.channel.mention}\nDeleted: {len(deleted)}")

    @app_commands.command(name="channelbackup", description="Save a text channel and all of its permissions")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def channelbackup(self, interaction: discord.Interaction, channel: discord.TextChannel):
        overwrites = []
        for target, overwrite in channel.overwrites.items():
            allow, deny = overwrite.pair()
            overwrites.append({"id": target.id, "kind": "role" if isinstance(target, discord.Role) else "member", "allow": allow.value, "deny": deny.value})
        backup_id = self.db.save_channel_backup(interaction.guild_id, channel.id, channel.name, "text", channel.category_id, channel.position, channel.topic, channel.nsfw, channel.slowmode_delay, json.dumps(overwrites))
        await interaction.response.send_message(f"Backed up {channel.mention} with all permissions. Backup ID: `{backup_id}`", ephemeral=True)

    @app_commands.command(name="channelbackups", description="List restorable channel backups")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def channelbackups(self, interaction: discord.Interaction):
        rows = self.db.channel_backups(interaction.guild_id)
        lines = [f"`{row['id']}` — **#{row['name']}** — {row['backed_up_at']}" for row in rows[:25]] or ["No channel backups saved."]
        await interaction.response.send_message(embed=discord.Embed(title="Channel Backups", description="\n".join(lines), color=discord.Color.blurple()), ephemeral=True)

    @app_commands.command(name="restorechannel", description="Recreate a deleted channel from a backup ID")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def restorechannel(self, interaction: discord.Interaction, backup_id: int):
        backup = self.db.channel_backup(interaction.guild_id, backup_id)
        if not backup:
            await interaction.response.send_message("That backup ID does not exist.", ephemeral=True); return
        overwrites = {}
        for saved in json.loads(backup["overwrites"]):
            target = interaction.guild.get_role(saved["id"]) if saved["kind"] == "role" else interaction.guild.get_member(saved["id"])
            if target:
                overwrites[target] = discord.PermissionOverwrite.from_pair(discord.Permissions(saved["allow"]), discord.Permissions(saved["deny"]))
        category = interaction.guild.get_channel(backup["category_id"]) if backup["category_id"] else None
        channel = await interaction.guild.create_text_channel(name=backup["name"], category=category if isinstance(category, discord.CategoryChannel) else None, overwrites=overwrites, topic=backup["topic"], nsfw=bool(backup["nsfw"]), slowmode_delay=backup["slowmode"], position=backup["position"], reason=f"Restored by {interaction.user}")
        await interaction.response.send_message(f"Restored {channel.mention} with its saved permissions.", ephemeral=True)
        await self.send_mod_log(interaction.guild, "Channel Restored", f"Channel: {channel.mention}\nBackup ID: `{backup_id}`\nRestored by: {interaction.user.mention}", discord.Color.green())

    @app_commands.command(name="invites", description="View how many tracked members someone invited")
    @app_commands.guild_only()
    async def invites(self, interaction: discord.Interaction, member: discord.Member | None = None):
        target = member or interaction.user
        count = self.db.invite_count(interaction.guild_id, target.id)
        join = self.db.invite_join(interaction.guild_id, target.id)
        invited_by = f"<@{join['inviter_id']}> using `{join['invite_code']}`" if join and join["inviter_id"] else "Unknown or vanity invite"
        await interaction.response.send_message(embed=discord.Embed(title=f"Invite Tracker — {target}", description=f"Tracked successful invites: **{count}**\nJoined through: {invited_by}", color=discord.Color.blurple()))

    @app_commands.command(name="applicationsetup", description="Create the Staff and Manager Applications panel")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        panel_channel="Channel where members open applications",
        application_category="Category where private applications are created",
        reviewer_role="Staff role that reviews applications and gets pinged",
        staff_questions="Staff questions separated with |",
        manager_questions="Manager questions separated with |",
    )
    async def applicationsetup(
        self, interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        application_category: discord.CategoryChannel,
        reviewer_role: discord.Role,
        staff_questions: str,
        manager_questions: str,
    ):
        def parse_questions(value: str) -> list[str]:
            return [item.strip() for item in value.replace("\r", "").split("|") if item.strip()]

        staff_question_list = parse_questions(staff_questions)
        manager_question_list = parse_questions(manager_questions)
        if not 1 <= len(staff_question_list) <= 15 or not 1 <= len(manager_question_list) <= 15:
            await interaction.response.send_message("Add between 1 and 15 questions for each application. Separate questions with the | symbol.", ephemeral=True)
            return
        if any(len(question) > 300 for question in staff_question_list + manager_question_list):
            await interaction.response.send_message("Each application question must be 300 characters or fewer.", ephemeral=True)
            return
        self.db.configure_staff_applications(
            interaction.guild_id, panel_channel.id, application_category.id,
            reviewer_role.id, "Staff", "\n".join(staff_question_list),
            "\n".join(manager_question_list),
        )
        embed = discord.Embed(
            title="APPLICATIONS",
            description=(
                "Choose **Staff Application** or **Manager Application** below.\n\n"
                "The bot will DM you one question at a time. Your completed answers are then sent privately to the application review team."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_footer(text="Made By EthanCoys")
        await panel_channel.send(
            embed=embed,
            view=ApplicationPanelView(self.bot, self.db),
        )
        await interaction.response.send_message(
            f"Applications panel posted in {panel_channel.mention}. {reviewer_role.mention} will review Staff and Manager applications.",
            ephemeral=True,
        )

    @app_commands.command(name="rolesaversetup", description="Choose roles saved when members leave and set the log channel")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def rolesaversetup(
        self, interaction: discord.Interaction, log_channel: discord.TextChannel,
        role_1: discord.Role, role_2: discord.Role | None = None,
        role_3: discord.Role | None = None, role_4: discord.Role | None = None,
        role_5: discord.Role | None = None,
    ):
        roles = list(dict.fromkeys(role for role in (role_1, role_2, role_3, role_4, role_5) if role and not role.is_default() and not role.managed))
        if not roles:
            await interaction.response.send_message("Choose at least one normal Discord role.", ephemeral=True)
            return
        self.db.configure_role_saver(interaction.guild_id, log_channel.id, [role.id for role in roles])
        await interaction.response.send_message(f"Role Saver enabled. Members will only have these configured roles restored when they return: {', '.join(role.mention for role in roles)}\nLogs: {log_channel.mention}", ephemeral=True)

    @app_commands.command(name="ticketsetup", description="Create and configure the support ticket panel")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        panel_channel="Channel where users open tickets",
        ticket_category="Category where private ticket channels are created",
        support_role="Role that can view tickets and gets pinged",
        problems="Ticket choices separated with |, for example Support | Report | Partnership",
    )
    async def ticketsetup(
        self,
        interaction: discord.Interaction,
        panel_channel: discord.TextChannel,
        ticket_category: discord.CategoryChannel,
        support_role: discord.Role,
        problems: str,
    ):
        problem_list = [item.strip() for item in problems.replace(",", "|").split("|") if item.strip()]
        if not problem_list:
            await interaction.response.send_message("Add at least one problem type.", ephemeral=True)
            return
        if len(problem_list) > 25:
            await interaction.response.send_message("You can configure up to 25 problem types.", ephemeral=True)
            return
        if any(len(problem) > 100 for problem in problem_list):
            await interaction.response.send_message("Each ticket type must be 100 characters or fewer.", ephemeral=True)
            return
        self.db.configure_tickets(
            interaction.guild_id,
            panel_channel.id,
            ticket_category.id,
            support_role.id,
            "\n".join(problem_list),
        )
        embed = discord.Embed(
            title="CHOOSE A TICKET TYPE",
            description=(
                "Select the tab that best matches what you need help with.\n\n"
                "A private channel will be created for you and the support team."
            ),
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        embed.set_author(name=interaction.guild.name)
        embed.set_footer(text="Made By EthanCoys")
        await panel_channel.send(
            embed=embed,
            view=TicketPanelView(self.bot, self.db, problem_list),
        )
        await interaction.response.send_message(
            f"Ticket panel posted in {panel_channel.mention}. {support_role.mention} will be pinged for new tickets.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot, database: Database) -> None:
    await bot.add_cog(ClubManagement(bot, database))
    bot.add_view(TicketPanelView(bot, database, ["General Support"]))
    bot.add_view(TicketCloseView(database))
    bot.add_view(ApplicationPanelView(bot, database))
    bot.add_view(StaffApplicationCloseView(database))


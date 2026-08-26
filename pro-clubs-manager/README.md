# Pro Clubs Manager Discord Bot

A small, independent Discord.py bot for managing Pro Clubs teams. It supports team offers with Accept/Deny buttons, role assignment, player releases, log channels, and SQLite storage.

This project is inspired only by common club-management workflows. It does not contain Byronic code, assets, or branding.

## Features

- `/offer player team` sends a team offer with Accept and Deny buttons.
- Only the offered player can respond.
- Accepting assigns the configured team role and writes a signing log.
- `/release player team reason` removes the team role and writes a release log.
- `/team add`, `/team remove`, and `/team list` manage selectable teams.
- `/config_logs` configures signing and release channels.
- Team names autocomplete from the server's saved configuration.
- SQLite stores teams, configuration, and offers.
- Pending offer buttons are restored after bot restarts.
- Admin/Manage Roles permission checks protect management commands.

## Requirements

- Python 3.11 or newer
- A Discord bot application
- Permission to manage roles, send messages, embed links, and use application commands

## Setup

1. Download and unzip this project.
2. Open a terminal inside the project folder.
3. Create a virtual environment:

   **Windows**

   ```powershell
   py -m venv .venv
   .venv\Scripts\activate
   ```

   **macOS/Linux**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

4. Install the packages:

   ```bash
   pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env` and put your bot token in it.
6. In the [Discord Developer Portal](https://discord.com/developers/applications), enable **Server Members Intent** on the Bot page.
7. Invite the bot with the `bot` and `applications.commands` scopes. Give it Manage Roles, Send Messages, Embed Links, and View Channels permissions.
8. In Discord's role settings, move the bot's role **above every team role** it needs to assign.
9. Start the bot:

   ```bash
   python bot.py
   ```

For quick testing, put your server ID in `TEST_GUILD_ID`. Commands in that server should update quickly. If it is blank, global command updates can take up to about an hour.

## First-time configuration

Run these commands in your Discord server:

```text
/team add name:Manchester City role:@Manchester City
/team add name:Arsenal role:@Arsenal
/config_logs signing_channel:#signings release_channel:#releases
```

Managers with **Manage Roles** can then use `/offer` and `/release`. Server administrators can change teams and log channels.

## GitHub and deployment

Upload the unzipped folder to a new GitHub repository. Do not upload your `.env` file; it is already ignored by `.gitignore`.

For a basic VPS or hosting service, install Python, install `requirements.txt`, add the same environment variables from `.env.example`, and run `python bot.py`. The SQLite database is a local file, so use persistent storage on your host.

## Notes

- One Discord role represents one team.
- Deleting a team configuration does not delete its Discord role.
- The bot intentionally keeps permissions simple: administrators configure it, and members with Manage Roles make offers/releases.
- Back up `pro_clubs.db` if you want to preserve data when moving hosts.


# Pro Clubs Manager Discord Bot

A small, independent Discord.py bot for managing Pro Clubs teams. It supports team offers with Accept/Deny buttons, role assignment, player releases, log channels, and SQLite storage.

This project is inspired only by common club-management workflows. It does not contain Byronic code, assets, or branding.

## Features

- `/offer player` privately DMs the player an offer with Accept and Deny buttons. The manager's team is detected from their configured team role.
- Only the offered player can respond.
- Accepting assigns the configured team role and writes a detailed signing log.
- Offer and signing embeds show the team role colour, roster, and manager who sent the offer.
- Rosters include only players who accepted an offer through the bot. Manually assigned team roles, owners, managers, and bots are not counted. `/release` removes the player from the saved roster.
- `/release player` removes the manager's automatically detected team role and writes a release log.
- `/team add`, `/team remove`, and `/team list` manage selectable teams.
- `/addteam` creates a team with a name, tagged role, tagged owner, optional uploaded logo, and roster cap (default 22).
- `/removeteam` removes a configured team without deleting its Discord role.
- `/roster` lets configured managers and co-managers privately view their automatically detected team's signed roster.
- `/setteamlogo` updates an existing team's logo and creates a custom server emoji for an inline logo. The bot needs Manage Expressions permission.
- `/rulesembed` lets an administrator post server rules and an optional contacting-moderators card with uploaded banner images in a selected channel.
- `/ticketsetup` lets an administrator choose the panel channel, private ticket category, support role to ping, and comma-separated problem types. Users choose a problem from the persistent dropdown, receive a private channel, and can close it with a button. Closed ticket channels are deleted after 10 seconds.
- `/forceconfig` sets up to five staff roles allowed to use `/forcesign` and `/forcerelease`. Administrators always have access. Force actions update Discord roles, saved rosters, and log channels.
- `/welcomesetup` lets an administrator choose a welcome channel, upload a custom banner, and set the smaller subtext. New members receive a generated card with their avatar and a dark translucent centre panel. The headline automatically uses the joined member's real server display name followed by “has landed.” Subtext supports `{user}`, `{display}`, `{server}`, and `{count}`.
- `/welcometest` posts a test welcome card for the administrator in the configured welcome channel.
- `/totwsetweek` opens a numbered TOTW week. Signed players and team staff use `/uploadstats` with Summary plus their position-specific tab; CDMs also upload Defending. OCR reads the visible ratings and `/totwlist` selects a 3-5-2: GK, three CB/FB, two CDMs, CAM, two WMs, and two STs.
- `/config_setup` configures signing/release channels and exactly two management roles.
- Team names autocomplete from the server's saved configuration.
- SQLite stores teams, configuration, and offers.
- Pending offer buttons are restored after bot restarts.
- Only administrators and the two configured management roles can make offers/releases.

## Requirements

### Transfers, loans, and budgets

- `/budgetsetup` sets the channel containing the live plain-text budget list.
- `/budgetsetup` also sets the starting budget for every configured team.
- `/setbudget` sets a configured team's budget in millions.
- `/budgets` manually refreshes the budget message.
- `/transfer` moves a player between teams, moves the fee between budgets, and refreshes the list.
- `/loan` temporarily moves a player to another team.
- `/endloan` returns a loaned player to their parent team.
- `/loans` lists every active loan.

### Polls and staff applications

- `/pollconfig` sets the role pinged whenever staff creates a poll.
- `/poll` creates a native Discord poll with custom choices.
- `/staffapplicationsetup` posts a position selector that opens private application channels.

### League administration

- `/franchiseconfig` sets the franchise-owner Discord role and `/appointfranchiseowner` assigns it.
- `/blacklist`, `/removeblacklist`, and `/blacklistlist` manage blocked players.
- `/openwindow` and `/closewindow` control ordinary offers, transfers, and loans.
- `/myoffers`, `/teamoffers`, and `/canceloffer` manage pending offers.
- `/promote`, `/demoteco`, `/forcepromote`, and `/forcedemote` manage staff roles.
- `/result` records scores and `/standings` calculates the 3/1/0 league table.
- `/editteam` and `/transferownership` update persistent team details.
- `/debug`, `/logstyle`, `/help`, and `/endseason` provide league administration tools.

Transfer and loan commands are restricted to administrators and the roles configured with `/forceconfig`.

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
/config_setup signing_channel:#signings release_channel:#releases manager_role_1:@Owner manager_role_2:@Manager
```

Members with either configured management role can then use `/offer` and `/release`. Server administrators can change teams, channels, and management roles.

To send an offer, a manager needs an allowed management role and must either be the owner selected in `/addteam` or hold exactly one configured team role. `/addteam` attempts to give the owner the team role automatically. They then run `/offer player` without selecting or mentioning a team.

Players must allow direct messages from server members to receive offers. Discord embed sidebars support a static colour only; this bot uses the configured team role colour. Discord does not support animated embed borders. An animated GIF uploaded as the team logo can animate in clients that allow animated media.

## GitHub and deployment

Upload the unzipped folder to a new GitHub repository. Do not upload your `.env` file; it is already ignored by `.gitignore`.

For a basic VPS or hosting service, install Python, install `requirements.txt`, add the same environment variables from `.env.example`, and run `python bot.py`.

### Keeping teams after Railway updates

The teams are saved in SQLite and survive normal bot restarts. On Railway, attach a persistent volume to the bot service, mount it at `/data`, and set:

```env
DATABASE_PATH=/data/pro_clubs.db
```

Without a persistent volume, Railway may remove the database during a redeploy. Updating/syncing slash commands does not itself remove teams, and `/team remove` is the only bot command that deletes a configured team.

On Railway, the bot forces `/data/pro_clubs.db` if `DATABASE_PATH` is missing or points outside `/data`. A volume must still be mounted at `/data`; code cannot preserve files that Railway deletes from an unmounted container.

## Notes

- One Discord role represents one team.
- Deleting a team configuration does not delete its Discord role.
- The bot intentionally keeps permissions simple: administrators configure it, and members with Manage Roles make offers/releases.
- Back up `pro_clubs.db` if you want to preserve data when moving hosts.


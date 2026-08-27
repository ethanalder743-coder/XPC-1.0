import sqlite3
from pathlib import Path


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def setup(self) -> None:
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id INTEGER PRIMARY KEY,
                    signing_channel_id INTEGER,
                    release_channel_id INTEGER,
                    manager_role_1_id INTEGER,
                    manager_role_2_id INTEGER,
                    signing_remove_role_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS teams (
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    role_id INTEGER NOT NULL,
                    owner_id INTEGER,
                    logo_url TEXT,
                    emoji_id INTEGER,
                    roster_cap INTEGER NOT NULL DEFAULT 22,
                    PRIMARY KEY (guild_id, name),
                    UNIQUE (guild_id, role_id)
                );

                CREATE TABLE IF NOT EXISTS offers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    team_name TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    offered_by INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT
                );

                CREATE TABLE IF NOT EXISTS team_members (
                    guild_id INTEGER NOT NULL,
                    team_name TEXT NOT NULL COLLATE NOCASE,
                    player_id INTEGER NOT NULL,
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, team_name, player_id)
                );

                CREATE TABLE IF NOT EXISTS ticket_config (
                    guild_id INTEGER PRIMARY KEY,
                    panel_channel_id INTEGER NOT NULL,
                    category_id INTEGER NOT NULL,
                    support_role_id INTEGER NOT NULL,
                    problems TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tickets (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    problem TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS force_config (
                    guild_id INTEGER PRIMARY KEY,
                    role_ids TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS welcome_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    banner_path TEXT NOT NULL,
                    headline TEXT NOT NULL,
                    subtext TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS totw_config (
                    guild_id INTEGER PRIMARY KEY,
                    active_week INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS totw_submissions (
                    guild_id INTEGER NOT NULL,
                    week INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    team_name TEXT NOT NULL,
                    position_group TEXT NOT NULL,
                    summary_rating REAL NOT NULL,
                    primary_rating REAL NOT NULL,
                    defending_rating REAL,
                    score REAL NOT NULL,
                    summary_url TEXT,
                    stats_url TEXT,
                    defending_url TEXT,
                    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, week, user_id)
                );

                CREATE TABLE IF NOT EXISTS budget_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER,
                    starting_budget INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS team_budgets (
                    guild_id INTEGER NOT NULL,
                    team_name TEXT NOT NULL COLLATE NOCASE,
                    amount INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, team_name)
                );

                CREATE TABLE IF NOT EXISTS transfers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    selling_team TEXT NOT NULL,
                    buying_team TEXT NOT NULL,
                    fee INTEGER NOT NULL,
                    actioned_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS loans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    parent_team TEXT NOT NULL,
                    loan_team TEXT NOT NULL,
                    actioned_by INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    ended_at TEXT
                );

                CREATE TABLE IF NOT EXISTS poll_config (
                    guild_id INTEGER PRIMARY KEY,
                    ping_role_id INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS staff_application_config (
                    guild_id INTEGER PRIMARY KEY,
                    panel_channel_id INTEGER NOT NULL,
                    category_id INTEGER NOT NULL,
                    reviewer_role_id INTEGER NOT NULL,
                    positions TEXT NOT NULL,
                    staff_questions TEXT,
                    manager_questions TEXT
                );

                CREATE TABLE IF NOT EXISTS staff_applications (
                    channel_id INTEGER PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    position TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    closed_at TEXT
                );

                CREATE TABLE IF NOT EXISTS role_saver_config (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER NOT NULL,
                    role_ids TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS saved_member_roles (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role_ids TEXT NOT NULL,
                    saved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS moderation_config (
                    guild_id INTEGER PRIMARY KEY,
                    log_channel_id INTEGER NOT NULL,
                    scam_protection INTEGER NOT NULL DEFAULT 1
                );

                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS channel_backups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    channel_type TEXT NOT NULL,
                    category_id INTEGER,
                    position INTEGER NOT NULL,
                    topic TEXT,
                    nsfw INTEGER NOT NULL DEFAULT 0,
                    slowmode INTEGER NOT NULL DEFAULT 0,
                    overwrites TEXT NOT NULL,
                    backed_up_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS invite_joins (
                    guild_id INTEGER NOT NULL,
                    joined_user_id INTEGER NOT NULL,
                    inviter_id INTEGER,
                    invite_code TEXT,
                    joined_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, joined_user_id)
                );

                CREATE TABLE IF NOT EXISTS premium_guilds (
                    guild_id INTEGER PRIMARY KEY,
                    expires_at TEXT,
                    granted_by INTEGER,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS premium_bypass (
                    user_id INTEGER PRIMARY KEY,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS premium_codes (
                    code_hash TEXT PRIMARY KEY,
                    days INTEGER NOT NULL,
                    created_by INTEGER NOT NULL,
                    redeemed_by INTEGER,
                    redeemed_guild_id INTEGER,
                    redeemed_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS premium_branding (
                    guild_id INTEGER PRIMARY KEY,
                    display_name TEXT,
                    accent_color INTEGER NOT NULL DEFAULT 5793266,
                    logo_url TEXT,
                    banner_url TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS league_config (
                    guild_id INTEGER PRIMARY KEY,
                    franchise_role_id INTEGER,
                    transfer_window_open INTEGER NOT NULL DEFAULT 1,
                    log_style TEXT NOT NULL DEFAULT 'detailed'
                );

                CREATE TABLE IF NOT EXISTS blacklist (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    added_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS match_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    home_score INTEGER NOT NULL,
                    away_score INTEGER NOT NULL,
                    submitted_by INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS command_status (
                    guild_id INTEGER NOT NULL,
                    command_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, command_name)
                );

                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    user_id INTEGER,
                    action TEXT NOT NULL,
                    details TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS fixtures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    home_team TEXT NOT NULL,
                    away_team TEXT NOT NULL,
                    kickoff TEXT NOT NULL,
                    competition TEXT NOT NULL DEFAULT 'League',
                    status TEXT NOT NULL DEFAULT 'scheduled'
                );

                CREATE TABLE IF NOT EXISTS trophies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    logo_url TEXT,
                    UNIQUE (guild_id, name)
                );

                CREATE TABLE IF NOT EXISTS trophy_winners (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    trophy_id INTEGER NOT NULL,
                    team_name TEXT NOT NULL,
                    season TEXT NOT NULL,
                    awarded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )

            # Upgrade databases created by older versions without losing teams.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(guild_config)")}
            for column in ("manager_role_1_id", "manager_role_2_id", "signing_remove_role_id"):
                if column not in columns:
                    db.execute(f"ALTER TABLE guild_config ADD COLUMN {column} INTEGER")

            team_columns = {row["name"] for row in db.execute("PRAGMA table_info(teams)")}
            for column, kind in (
                ("owner_id", "INTEGER"),
                ("logo_url", "TEXT"),
                ("emoji_id", "INTEGER"),
                ("roster_cap", "INTEGER NOT NULL DEFAULT 22"),
            ):
                if column not in team_columns:
                    db.execute(f"ALTER TABLE teams ADD COLUMN {column} {kind}")

            application_columns = {row["name"] for row in db.execute("PRAGMA table_info(staff_applications)")}
            for column, kind in (("application_type", "TEXT NOT NULL DEFAULT 'Staff'"), ("answers", "TEXT")):
                if column not in application_columns:
                    db.execute(f"ALTER TABLE staff_applications ADD COLUMN {column} {kind}")

            application_config_columns = {row["name"] for row in db.execute("PRAGMA table_info(staff_application_config)")}
            for column in ("staff_questions", "manager_questions"):
                if column not in application_config_columns:
                    db.execute(f"ALTER TABLE staff_application_config ADD COLUMN {column} TEXT")

            budget_columns = {row["name"] for row in db.execute("PRAGMA table_info(budget_config)")}
            if "starting_budget" not in budget_columns:
                db.execute("ALTER TABLE budget_config ADD COLUMN starting_budget INTEGER NOT NULL DEFAULT 0")

            totw_columns = {row["name"] for row in db.execute("PRAGMA table_info(totw_submissions)")}
            for column in ("summary_url", "stats_url", "defending_url"):
                if column not in totw_columns:
                    db.execute(f"ALTER TABLE totw_submissions ADD COLUMN {column} TEXT")
            db.execute("DELETE FROM totw_submissions WHERE user_id < 0")

            db.execute(
                """
                UPDATE welcome_config SET headline = '{display} has landed.'
                WHERE headline = '{user} just joined {server}!'
                """
            )

    def add_team(
        self,
        guild_id: int,
        name: str,
        role_id: int,
        owner_id: int | None = None,
        logo_url: str | None = None,
        roster_cap: int = 22,
        emoji_id: int | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO teams (guild_id, name, role_id, owner_id, logo_url, roster_cap, emoji_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (guild_id, name.strip(), role_id, owner_id, logo_url, roster_cap, emoji_id),
            )

    def remove_team(self, guild_id: int, name: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM teams WHERE guild_id = ? AND name = ?",
                (guild_id, name.strip()),
            )
            return cursor.rowcount > 0

    def teams(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(
                db.execute(
                    "SELECT name, role_id, owner_id, logo_url, roster_cap, emoji_id FROM teams WHERE guild_id = ? ORDER BY name",
                    (guild_id,),
                )
            )

    def team(self, guild_id: int, name: str) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT name, role_id, owner_id, logo_url, roster_cap, emoji_id FROM teams WHERE guild_id = ? AND name = ?",
                (guild_id, name.strip()),
            ).fetchone()

    def update_team_logo(
        self, guild_id: int, name: str, logo_url: str, emoji_id: int | None
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE teams SET logo_url = ?, emoji_id = ? WHERE guild_id = ? AND name = ?",
                (logo_url, emoji_id, guild_id, name.strip()),
            )

    def configure_guild(
        self,
        guild_id: int,
        signing_id: int,
        release_id: int,
        manager_role_1_id: int,
        manager_role_2_id: int,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO guild_config
                    (guild_id, signing_channel_id, release_channel_id,
                     manager_role_1_id, manager_role_2_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    signing_channel_id = excluded.signing_channel_id,
                    release_channel_id = excluded.release_channel_id,
                    manager_role_1_id = excluded.manager_role_1_id,
                    manager_role_2_id = excluded.manager_role_2_id
                """,
                (guild_id, signing_id, release_id, manager_role_1_id, manager_role_2_id),
            )

    def config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()

    def set_signing_remove_role(self, guild_id: int, role_id: int | None) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE guild_config SET signing_remove_role_id = ? WHERE guild_id = ?",
                (role_id, guild_id),
            )

    def create_offer(
        self,
        guild_id: int,
        player_id: int,
        team_name: str,
        role_id: int,
        offered_by: int,
        channel_id: int,
    ) -> int:
        with self.connect() as db:
            cursor = db.execute(
                """
                INSERT INTO offers
                    (guild_id, player_id, team_name, role_id, offered_by, channel_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (guild_id, player_id, team_name, role_id, offered_by, channel_id),
            )
            return int(cursor.lastrowid)

    def set_offer_message(self, offer_id: int, message_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE offers SET message_id = ? WHERE id = ?", (message_id, offer_id))

    def offer(self, offer_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM offers WHERE id = ?", (offer_id,)).fetchone()

    def pending_offers(self) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM offers WHERE status = 'pending'"))

    def decide_offer(self, offer_id: int, status: str) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE offers SET status = ?, decided_at = CURRENT_TIMESTAMP
                WHERE id = ? AND status = 'pending'
                """,
                (status, offer_id),
            )
            return cursor.rowcount > 0

    def add_team_member(self, guild_id: int, team_name: str, player_id: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT OR REPLACE INTO team_members (guild_id, team_name, player_id)
                VALUES (?, ?, ?)
                """,
                (guild_id, team_name, player_id),
            )

    def remove_team_member(self, guild_id: int, team_name: str, player_id: int) -> None:
        with self.connect() as db:
            db.execute(
                "DELETE FROM team_members WHERE guild_id = ? AND team_name = ? AND player_id = ?",
                (guild_id, team_name, player_id),
            )

    def team_member_ids(self, guild_id: int, team_name: str) -> list[int]:
        with self.connect() as db:
            return [
                row["player_id"]
                for row in db.execute(
                    "SELECT player_id FROM team_members WHERE guild_id = ? AND team_name = ? ORDER BY joined_at",
                    (guild_id, team_name),
                )
            ]

    def configure_tickets(
        self,
        guild_id: int,
        panel_channel_id: int,
        category_id: int,
        support_role_id: int,
        problems: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO ticket_config
                    (guild_id, panel_channel_id, category_id, support_role_id, problems)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    panel_channel_id = excluded.panel_channel_id,
                    category_id = excluded.category_id,
                    support_role_id = excluded.support_role_id,
                    problems = excluded.problems
                """,
                (guild_id, panel_channel_id, category_id, support_role_id, problems),
            )

    def ticket_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM ticket_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()

    def open_ticket_for_user(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM tickets WHERE guild_id = ? AND user_id = ? AND status = 'open'",
                (guild_id, user_id),
            ).fetchone()

    def create_ticket(
        self, channel_id: int, guild_id: int, user_id: int, problem: str
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO tickets (channel_id, guild_id, user_id, problem) VALUES (?, ?, ?, ?)",
                (channel_id, guild_id, user_id, problem),
            )

    def ticket(self, channel_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM tickets WHERE channel_id = ?", (channel_id,)
            ).fetchone()

    def close_ticket(self, channel_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE tickets SET status = 'closed', closed_at = CURRENT_TIMESTAMP
                WHERE channel_id = ? AND status = 'open'
                """,
                (channel_id,),
            )
            return cursor.rowcount > 0

    def configure_force_roles(self, guild_id: int, role_ids: list[int]) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO force_config (guild_id, role_ids) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET role_ids = excluded.role_ids
                """,
                (guild_id, ",".join(str(role_id) for role_id in role_ids)),
            )

    def force_role_ids(self, guild_id: int) -> set[int]:
        with self.connect() as db:
            row = db.execute(
                "SELECT role_ids FROM force_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()
        if not row or not row["role_ids"]:
            return set()
        return {int(value) for value in row["role_ids"].split(",") if value}

    def configure_welcome(
        self,
        guild_id: int,
        channel_id: int,
        banner_path: str,
        headline: str,
        subtext: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO welcome_config
                    (guild_id, channel_id, banner_path, headline, subtext)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    banner_path = excluded.banner_path,
                    headline = excluded.headline,
                    subtext = excluded.subtext
                """,
                (guild_id, channel_id, banner_path, headline, subtext),
            )

    def welcome_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM welcome_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()

    def signed_team_for_user(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                """
                SELECT t.name, t.role_id, t.owner_id, t.logo_url, t.roster_cap, t.emoji_id
                FROM team_members tm
                JOIN teams t ON t.guild_id = tm.guild_id AND t.name = tm.team_name
                WHERE tm.guild_id = ? AND tm.player_id = ?
                ORDER BY tm.joined_at DESC LIMIT 1
                """,
                (guild_id, user_id),
            ).fetchone()

    def set_totw_week(self, guild_id: int, week: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO totw_config (guild_id, active_week) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET active_week = excluded.active_week
                """,
                (guild_id, week),
            )

    def totw_week(self, guild_id: int) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT active_week FROM totw_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()
        return int(row["active_week"]) if row else 1

    def save_totw_submission(
        self,
        guild_id: int,
        week: int,
        user_id: int,
        team_name: str,
        position_group: str,
        summary_rating: float,
        primary_rating: float,
        defending_rating: float | None,
        score: float,
        summary_url: str | None = None,
        stats_url: str | None = None,
        defending_url: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO totw_submissions
                    (guild_id, week, user_id, team_name, position_group,
                    summary_rating, primary_rating, defending_rating, score,
                    summary_url, stats_url, defending_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, week, user_id) DO UPDATE SET
                    team_name = excluded.team_name,
                    position_group = excluded.position_group,
                    summary_rating = excluded.summary_rating,
                    primary_rating = excluded.primary_rating,
                    defending_rating = excluded.defending_rating,
                    score = excluded.score,
                    summary_url = excluded.summary_url,
                    stats_url = excluded.stats_url,
                    defending_url = excluded.defending_url,
                    submitted_at = CURRENT_TIMESTAMP
                """,
                (
                    guild_id, week, user_id, team_name, position_group,
                    summary_rating, primary_rating, defending_rating, score,
                    summary_url, stats_url, defending_url,
                ),
            )

    def totw_submissions(self, guild_id: int, week: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(
                db.execute(
                    """
                    SELECT * FROM totw_submissions
                    WHERE guild_id = ? AND week = ? AND user_id > 0
                    ORDER BY score DESC, summary_rating DESC, submitted_at ASC
                    """,
                    (guild_id, week),
                )
            )

    def configure_budget_channel(self, guild_id: int, channel_id: int, starting_budget: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO budget_config (guild_id, channel_id, starting_budget) VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id = excluded.channel_id,
                    starting_budget = excluded.starting_budget
                """,
                (guild_id, channel_id, starting_budget),
            )
            for team in db.execute("SELECT name FROM teams WHERE guild_id = ?", (guild_id,)):
                self._upsert_budget(db, guild_id, team["name"], starting_budget)

    def budget_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM budget_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()

    def set_budget_message(self, guild_id: int, message_id: int) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE budget_config SET message_id = ? WHERE guild_id = ?",
                (message_id, guild_id),
            )

    def set_team_budget(self, guild_id: int, team_name: str, amount: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO team_budgets (guild_id, team_name, amount) VALUES (?, ?, ?)
                ON CONFLICT(guild_id, team_name) DO UPDATE SET amount = excluded.amount
                """,
                (guild_id, team_name, amount),
            )

    def team_budget(self, guild_id: int, team_name: str) -> int:
        with self.connect() as db:
            row = db.execute(
                "SELECT amount FROM team_budgets WHERE guild_id = ? AND team_name = ?",
                (guild_id, team_name),
            ).fetchone()
        return int(row["amount"]) if row else 0

    def complete_transfer(
        self, guild_id: int, player_id: int, selling_team: str,
        buying_team: str, fee: int, actioned_by: int,
    ) -> None:
        with self.connect() as db:
            buyer = db.execute(
                "SELECT amount FROM team_budgets WHERE guild_id = ? AND team_name = ?",
                (guild_id, buying_team),
            ).fetchone()
            buyer_amount = int(buyer["amount"]) if buyer else 0
            if buyer_amount < fee:
                raise ValueError("The buying team does not have enough budget.")
            seller = db.execute(
                "SELECT amount FROM team_budgets WHERE guild_id = ? AND team_name = ?",
                (guild_id, selling_team),
            ).fetchone()
            seller_amount = int(seller["amount"]) if seller else 0
            self._upsert_budget(db, guild_id, buying_team, buyer_amount - fee)
            self._upsert_budget(db, guild_id, selling_team, seller_amount + fee)
            db.execute(
                "DELETE FROM team_members WHERE guild_id = ? AND team_name = ? AND player_id = ?",
                (guild_id, selling_team, player_id),
            )
            db.execute(
                "INSERT OR REPLACE INTO team_members (guild_id, team_name, player_id) VALUES (?, ?, ?)",
                (guild_id, buying_team, player_id),
            )
            db.execute(
                "INSERT INTO transfers (guild_id, player_id, selling_team, buying_team, fee, actioned_by) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, player_id, selling_team, buying_team, fee, actioned_by),
            )

    @staticmethod
    def _upsert_budget(db, guild_id: int, team_name: str, amount: int) -> None:
        db.execute(
            """
            INSERT INTO team_budgets (guild_id, team_name, amount) VALUES (?, ?, ?)
            ON CONFLICT(guild_id, team_name) DO UPDATE SET amount = excluded.amount
            """,
            (guild_id, team_name, amount),
        )

    def start_loan(
        self, guild_id: int, player_id: int, parent_team: str,
        loan_team: str, actioned_by: int,
    ) -> None:
        with self.connect() as db:
            active = db.execute(
                "SELECT id FROM loans WHERE guild_id = ? AND player_id = ? AND status = 'active'",
                (guild_id, player_id),
            ).fetchone()
            if active:
                raise ValueError("That player already has an active loan.")
            db.execute(
                "DELETE FROM team_members WHERE guild_id = ? AND team_name = ? AND player_id = ?",
                (guild_id, parent_team, player_id),
            )
            db.execute(
                "INSERT OR REPLACE INTO team_members (guild_id, team_name, player_id) VALUES (?, ?, ?)",
                (guild_id, loan_team, player_id),
            )
            db.execute(
                "INSERT INTO loans (guild_id, player_id, parent_team, loan_team, actioned_by) VALUES (?, ?, ?, ?, ?)",
                (guild_id, player_id, parent_team, loan_team, actioned_by),
            )

    def active_loan(self, guild_id: int, player_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM loans WHERE guild_id = ? AND player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (guild_id, player_id),
            ).fetchone()

    def active_loans(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute(
                "SELECT * FROM loans WHERE guild_id = ? AND status = 'active' ORDER BY started_at",
                (guild_id,),
            ))

    def configure_poll_role(self, guild_id: int, role_id: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO poll_config (guild_id, ping_role_id) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET ping_role_id = excluded.ping_role_id
                """,
                (guild_id, role_id),
            )

    def poll_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM poll_config WHERE guild_id = ?", (guild_id,)).fetchone()

    def configure_staff_applications(
        self, guild_id: int, panel_channel_id: int, category_id: int,
        reviewer_role_id: int, positions: str, staff_questions: str,
        manager_questions: str,
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO staff_application_config
                    (guild_id, panel_channel_id, category_id, reviewer_role_id, positions, staff_questions, manager_questions)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    panel_channel_id = excluded.panel_channel_id,
                    category_id = excluded.category_id,
                    reviewer_role_id = excluded.reviewer_role_id,
                    positions = excluded.positions,
                    staff_questions = excluded.staff_questions,
                    manager_questions = excluded.manager_questions
                """,
                (guild_id, panel_channel_id, category_id, reviewer_role_id, positions, staff_questions, manager_questions),
            )

    def staff_application_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM staff_application_config WHERE guild_id = ?", (guild_id,)
            ).fetchone()

    def open_staff_application(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM staff_applications WHERE guild_id = ? AND user_id = ? AND status = 'open'",
                (guild_id, user_id),
            ).fetchone()

    def create_staff_application(
        self, channel_id: int, guild_id: int, user_id: int, position: str,
        application_type: str = "Staff", answers: str | None = None,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO staff_applications (channel_id, guild_id, user_id, position, application_type, answers) VALUES (?, ?, ?, ?, ?, ?)",
                (channel_id, guild_id, user_id, position, application_type, answers),
            )

    def configure_role_saver(self, guild_id: int, log_channel_id: int, role_ids: list[int]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO role_saver_config (guild_id, log_channel_id, role_ids) VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET log_channel_id=excluded.log_channel_id, role_ids=excluded.role_ids""",
                (guild_id, log_channel_id, ",".join(str(role_id) for role_id in role_ids)),
            )

    def role_saver_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM role_saver_config WHERE guild_id = ?", (guild_id,)).fetchone()

    def save_member_roles(self, guild_id: int, user_id: int, role_ids: list[int]) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO saved_member_roles (guild_id, user_id, role_ids) VALUES (?, ?, ?)
                ON CONFLICT(guild_id, user_id) DO UPDATE SET role_ids=excluded.role_ids, saved_at=CURRENT_TIMESTAMP""",
                (guild_id, user_id, ",".join(str(role_id) for role_id in role_ids)),
            )

    def saved_member_roles(self, guild_id: int, user_id: int) -> list[int]:
        with self.connect() as db:
            row = db.execute("SELECT role_ids FROM saved_member_roles WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)).fetchone()
        return [int(value) for value in row["role_ids"].split(",") if value] if row and row["role_ids"] else []

    def configure_moderation(self, guild_id: int, log_channel_id: int, scam_protection: bool = True) -> None:
        with self.connect() as db:
            db.execute(
                """INSERT INTO moderation_config (guild_id, log_channel_id, scam_protection) VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET log_channel_id=excluded.log_channel_id, scam_protection=excluded.scam_protection""",
                (guild_id, log_channel_id, int(scam_protection)),
            )

    def moderation_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM moderation_config WHERE guild_id = ?", (guild_id,)).fetchone()

    def add_warning(self, guild_id: int, user_id: int, moderator_id: int, reason: str) -> int:
        with self.connect() as db:
            cursor = db.execute("INSERT INTO warnings (guild_id, user_id, moderator_id, reason) VALUES (?, ?, ?, ?)", (guild_id, user_id, moderator_id, reason[:1000]))
            return int(cursor.lastrowid)

    def warnings_for(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM warnings WHERE guild_id = ? AND user_id = ? ORDER BY id DESC", (guild_id, user_id)))

    def save_channel_backup(self, guild_id: int, channel_id: int, name: str, channel_type: str, category_id: int | None, position: int, topic: str | None, nsfw: bool, slowmode: int, overwrites: str) -> int:
        with self.connect() as db:
            db.execute(
                """INSERT INTO channel_backups (guild_id, channel_id, name, channel_type, category_id, position, topic, nsfw, slowmode, overwrites)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, channel_id) DO UPDATE SET name=excluded.name, channel_type=excluded.channel_type, category_id=excluded.category_id, position=excluded.position, topic=excluded.topic, nsfw=excluded.nsfw, slowmode=excluded.slowmode, overwrites=excluded.overwrites, backed_up_at=CURRENT_TIMESTAMP""",
                (guild_id, channel_id, name, channel_type, category_id, position, topic, int(nsfw), slowmode, overwrites),
            )
            row = db.execute("SELECT id FROM channel_backups WHERE guild_id = ? AND channel_id = ?", (guild_id, channel_id)).fetchone()
            return int(row["id"])

    def channel_backups(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM channel_backups WHERE guild_id = ? ORDER BY id DESC", (guild_id,)))

    def channel_backup(self, guild_id: int, backup_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM channel_backups WHERE guild_id = ? AND id = ?", (guild_id, backup_id)).fetchone()

    def record_invite_join(self, guild_id: int, joined_user_id: int, inviter_id: int | None, invite_code: str | None) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO invite_joins (guild_id, joined_user_id, inviter_id, invite_code) VALUES (?, ?, ?, ?)", (guild_id, joined_user_id, inviter_id, invite_code))

    def invite_count(self, guild_id: int, inviter_id: int) -> int:
        with self.connect() as db:
            row = db.execute("SELECT COUNT(*) amount FROM invite_joins WHERE guild_id = ? AND inviter_id = ?", (guild_id, inviter_id)).fetchone()
        return int(row["amount"])

    def invite_join(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM invite_joins WHERE guild_id = ? AND joined_user_id = ?", (guild_id, user_id)).fetchone()

    def grant_premium(self, guild_id: int, days: int | None, granted_by: int) -> None:
        with self.connect() as db:
            expires = None if days is None else db.execute("SELECT datetime('now', ?)", (f"+{days} days",)).fetchone()[0]
            db.execute(
                """INSERT INTO premium_guilds (guild_id, expires_at, granted_by) VALUES (?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET expires_at=excluded.expires_at, granted_by=excluded.granted_by, updated_at=CURRENT_TIMESTAMP""",
                (guild_id, expires, granted_by),
            )

    def revoke_premium(self, guild_id: int) -> None:
        with self.connect() as db: db.execute("DELETE FROM premium_guilds WHERE guild_id = ?", (guild_id,))

    def premium_status(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db: return db.execute("SELECT *, (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP) active FROM premium_guilds WHERE guild_id = ?", (guild_id,)).fetchone()

    def add_premium_bypass(self, user_id: int, added_by: int) -> None:
        with self.connect() as db: db.execute("INSERT OR REPLACE INTO premium_bypass (user_id, added_by) VALUES (?, ?)", (user_id, added_by))

    def remove_premium_bypass(self, user_id: int) -> None:
        with self.connect() as db: db.execute("DELETE FROM premium_bypass WHERE user_id = ?", (user_id,))

    def premium_bypass(self, user_id: int) -> bool:
        with self.connect() as db: return db.execute("SELECT 1 FROM premium_bypass WHERE user_id = ?", (user_id,)).fetchone() is not None

    def premium_bypasses(self) -> list[sqlite3.Row]:
        with self.connect() as db: return list(db.execute("SELECT * FROM premium_bypass ORDER BY created_at"))

    def create_premium_code(self, code_hash: str, days: int, created_by: int) -> None:
        with self.connect() as db: db.execute("INSERT INTO premium_codes (code_hash, days, created_by) VALUES (?, ?, ?)", (code_hash, days, created_by))

    def redeem_premium_code(self, code_hash: str, guild_id: int, user_id: int) -> int | None:
        with self.connect() as db:
            row = db.execute("SELECT days FROM premium_codes WHERE code_hash = ? AND redeemed_at IS NULL", (code_hash,)).fetchone()
            if not row: return None
            db.execute("UPDATE premium_codes SET redeemed_by=?, redeemed_guild_id=?, redeemed_at=CURRENT_TIMESTAMP WHERE code_hash=? AND redeemed_at IS NULL", (user_id, guild_id, code_hash))
            days = int(row["days"])
            current = db.execute("SELECT expires_at FROM premium_guilds WHERE guild_id = ? AND (expires_at IS NULL OR expires_at > CURRENT_TIMESTAMP)", (guild_id,)).fetchone()
            base = current["expires_at"] if current and current["expires_at"] else None
            expires = db.execute("SELECT datetime(COALESCE(?, CURRENT_TIMESTAMP), ?)", (base, f"+{days} days")).fetchone()[0]
            db.execute("INSERT INTO premium_guilds (guild_id, expires_at, granted_by) VALUES (?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET expires_at=excluded.expires_at, granted_by=excluded.granted_by, updated_at=CURRENT_TIMESTAMP", (guild_id, expires, user_id))
            return days

    def set_premium_branding(self, guild_id: int, display_name: str | None, accent_color: int, logo_url: str | None, banner_url: str | None) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO premium_branding (guild_id, display_name, accent_color, logo_url, banner_url) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET display_name=excluded.display_name, accent_color=excluded.accent_color, logo_url=excluded.logo_url, banner_url=excluded.banner_url, updated_at=CURRENT_TIMESTAMP""", (guild_id, display_name, accent_color, logo_url, banner_url))

    def premium_branding(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db: return db.execute("SELECT * FROM premium_branding WHERE guild_id = ?", (guild_id,)).fetchone()

    def staff_application(self, channel_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM staff_applications WHERE channel_id = ?", (channel_id,)
            ).fetchone()

    def close_staff_application(self, channel_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE staff_applications SET status = 'closed', closed_at = CURRENT_TIMESTAMP WHERE channel_id = ? AND status = 'open'",
                (channel_id,),
            )
            return cursor.rowcount > 0

    def configure_franchise_role(self, guild_id: int, role_id: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO league_config (guild_id, franchise_role_id) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET franchise_role_id = excluded.franchise_role_id
                """,
                (guild_id, role_id),
            )

    def league_config(self, guild_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute("SELECT * FROM league_config WHERE guild_id = ?", (guild_id,)).fetchone()

    def set_transfer_window(self, guild_id: int, is_open: bool) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO league_config (guild_id, transfer_window_open) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET transfer_window_open = excluded.transfer_window_open
                """,
                (guild_id, int(is_open)),
            )

    def transfer_window_open(self, guild_id: int) -> bool:
        row = self.league_config(guild_id)
        return bool(row["transfer_window_open"]) if row else True

    def set_log_style(self, guild_id: int, style: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO league_config (guild_id, log_style) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET log_style = excluded.log_style
                """,
                (guild_id, style),
            )

    def blacklist_user(self, guild_id: int, user_id: int, reason: str, added_by: int) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO blacklist (guild_id, user_id, reason, added_by) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, reason, added_by),
            )

    def remove_blacklist(self, guild_id: int, user_id: int) -> bool:
        with self.connect() as db:
            return db.execute(
                "DELETE FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            ).rowcount > 0

    def blacklist_entry(self, guild_id: int, user_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            return db.execute(
                "SELECT * FROM blacklist WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
            ).fetchone()

    def blacklist_entries(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM blacklist WHERE guild_id = ? ORDER BY created_at", (guild_id,)))

    def cancel_offer(self, offer_id: int, guild_id: int) -> bool:
        with self.connect() as db:
            return db.execute(
                "UPDATE offers SET status = 'cancelled', decided_at = CURRENT_TIMESTAMP WHERE id = ? AND guild_id = ? AND status = 'pending'",
                (offer_id, guild_id),
            ).rowcount > 0

    def pending_offers_for_player(self, guild_id: int, player_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute(
                "SELECT * FROM offers WHERE guild_id = ? AND player_id = ? AND status = 'pending' ORDER BY created_at DESC",
                (guild_id, player_id),
            ))

    def pending_offers_for_team(self, guild_id: int, team_name: str) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute(
                "SELECT * FROM offers WHERE guild_id = ? AND team_name = ? AND status = 'pending' ORDER BY created_at DESC",
                (guild_id, team_name),
            ))

    def update_team(
        self, guild_id: int, old_name: str, new_name: str,
        role_id: int, owner_id: int, roster_cap: int,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE teams SET name = ?, role_id = ?, owner_id = ?, roster_cap = ? WHERE guild_id = ? AND name = ?",
                (new_name, role_id, owner_id, roster_cap, guild_id, old_name),
            )
            for table, column in (("team_members", "team_name"), ("team_budgets", "team_name")):
                db.execute(f"UPDATE {table} SET {column} = ? WHERE guild_id = ? AND {column} = ?", (new_name, guild_id, old_name))
            for table, columns in (
                ("offers", ("team_name",)),
                ("transfers", ("selling_team", "buying_team")),
                ("loans", ("parent_team", "loan_team")),
                ("match_results", ("home_team", "away_team")),
                ("totw_submissions", ("team_name",)),
            ):
                for column in columns:
                    db.execute(
                        f"UPDATE {table} SET {column} = ? WHERE guild_id = ? AND {column} = ?",
                        (new_name, guild_id, old_name),
                    )

    def set_team_owner(self, guild_id: int, team_name: str, owner_id: int) -> None:
        with self.connect() as db:
            db.execute("UPDATE teams SET owner_id = ? WHERE guild_id = ? AND name = ?", (owner_id, guild_id, team_name))

    def add_result(
        self, guild_id: int, home_team: str, away_team: str,
        home_score: int, away_score: int, submitted_by: int,
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO match_results (guild_id, home_team, away_team, home_score, away_score, submitted_by) VALUES (?, ?, ?, ?, ?, ?)",
                (guild_id, home_team, away_team, home_score, away_score, submitted_by),
            )

    def results(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM match_results WHERE guild_id = ? ORDER BY created_at", (guild_id,)))

    def end_season(self, guild_id: int) -> None:
        with self.connect() as db:
            for table in ("match_results", "offers", "transfers", "loans", "team_members", "totw_submissions"):
                db.execute(f"DELETE FROM {table} WHERE guild_id = ?", (guild_id,))
            config = db.execute("SELECT starting_budget FROM budget_config WHERE guild_id = ?", (guild_id,)).fetchone()
            starting = int(config["starting_budget"]) if config else 0
            for team in db.execute("SELECT name FROM teams WHERE guild_id = ?", (guild_id,)):
                self._upsert_budget(db, guild_id, team["name"], starting)

    def command_enabled(self, guild_id: int, command_name: str) -> bool:
        with self.connect() as db:
            row = db.execute(
                "SELECT enabled FROM command_status WHERE guild_id = ? AND command_name = ?",
                (guild_id, command_name),
            ).fetchone()
        return bool(row["enabled"]) if row else True

    def set_command_enabled(self, guild_id: int, command_name: str, enabled: bool) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO command_status (guild_id, command_name, enabled) VALUES (?, ?, ?)
                ON CONFLICT(guild_id, command_name) DO UPDATE SET
                    enabled = excluded.enabled,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (guild_id, command_name, int(enabled)),
            )

    def command_statuses(self, guild_id: int) -> dict[str, bool]:
        with self.connect() as db:
            return {
                row["command_name"]: bool(row["enabled"])
                for row in db.execute(
                    "SELECT command_name, enabled FROM command_status WHERE guild_id = ?",
                    (guild_id,),
                )
            }

    def add_audit(
        self, guild_id: int | None, user_id: int | None,
        action: str, details: str = "",
    ) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit_log (guild_id, user_id, action, details) VALUES (?, ?, ?, ?)",
                (guild_id, user_id, action[:100], details[:1000]),
            )

    def audit_entries(self, guild_id: int, limit: int = 250) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute(
                "SELECT * FROM audit_log WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
                (guild_id, limit),
            ))

    def add_fixture(self, guild_id: int, home: str, away: str, kickoff: str, competition: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO fixtures (guild_id, home_team, away_team, kickoff, competition) VALUES (?, ?, ?, ?, ?)",
                (guild_id, home, away, kickoff, competition),
            )

    def fixtures(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM fixtures WHERE guild_id = ? ORDER BY kickoff", (guild_id,)))

    def add_trophy(self, guild_id: int, name: str, logo_url: str | None) -> int:
        with self.connect() as db:
            cursor = db.execute("INSERT INTO trophies (guild_id, name, logo_url) VALUES (?, ?, ?)", (guild_id, name, logo_url))
            return int(cursor.lastrowid)

    def trophies(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute("SELECT * FROM trophies WHERE guild_id = ? ORDER BY name", (guild_id,)))

    def award_trophy(self, guild_id: int, trophy_id: int, team_name: str, season: str) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO trophy_winners (guild_id, trophy_id, team_name, season) VALUES (?, ?, ?, ?)",
                (guild_id, trophy_id, team_name, season),
            )

    def trophy_winners(self, guild_id: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(db.execute(
                """SELECT w.*, t.name trophy_name, t.logo_url trophy_logo
                FROM trophy_winners w JOIN trophies t ON t.id = w.trophy_id
                WHERE w.guild_id = ? ORDER BY w.awarded_at DESC""",
                (guild_id,),
            ))

    def finish_loan(self, guild_id: int, player_id: int) -> sqlite3.Row | None:
        with self.connect() as db:
            loan = db.execute(
                "SELECT * FROM loans WHERE guild_id = ? AND player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (guild_id, player_id),
            ).fetchone()
            if not loan:
                return None
            db.execute(
                "UPDATE loans SET status = 'ended', ended_at = CURRENT_TIMESTAMP WHERE id = ?",
                (loan["id"],),
            )
            db.execute(
                "DELETE FROM team_members WHERE guild_id = ? AND team_name = ? AND player_id = ?",
                (guild_id, loan["loan_team"], player_id),
            )
            db.execute(
                "INSERT OR REPLACE INTO team_members (guild_id, team_name, player_id) VALUES (?, ?, ?)",
                (guild_id, loan["parent_team"], player_id),
            )
            return loan


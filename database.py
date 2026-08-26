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
                    manager_role_2_id INTEGER
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
                    submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, week, user_id)
                );

                CREATE TABLE IF NOT EXISTS budget_config (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER
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
                """
            )

            # Upgrade databases created by older versions without losing teams.
            columns = {row["name"] for row in db.execute("PRAGMA table_info(guild_config)")}
            for column in ("manager_role_1_id", "manager_role_2_id"):
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
    ) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO totw_submissions
                    (guild_id, week, user_id, team_name, position_group,
                     summary_rating, primary_rating, defending_rating, score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, week, user_id) DO UPDATE SET
                    team_name = excluded.team_name,
                    position_group = excluded.position_group,
                    summary_rating = excluded.summary_rating,
                    primary_rating = excluded.primary_rating,
                    defending_rating = excluded.defending_rating,
                    score = excluded.score,
                    submitted_at = CURRENT_TIMESTAMP
                """,
                (
                    guild_id, week, user_id, team_name, position_group,
                    summary_rating, primary_rating, defending_rating, score,
                ),
            )

    def totw_submissions(self, guild_id: int, week: int) -> list[sqlite3.Row]:
        with self.connect() as db:
            return list(
                db.execute(
                    """
                    SELECT * FROM totw_submissions
                    WHERE guild_id = ? AND week = ?
                    ORDER BY score DESC, summary_rating DESC, submitted_at ASC
                    """,
                    (guild_id, week),
                )
            )

    def configure_budget_channel(self, guild_id: int, channel_id: int) -> None:
        with self.connect() as db:
            db.execute(
                """
                INSERT INTO budget_config (guild_id, channel_id) VALUES (?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET channel_id = excluded.channel_id
                """,
                (guild_id, channel_id),
            )

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


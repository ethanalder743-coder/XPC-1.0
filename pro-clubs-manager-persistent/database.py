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

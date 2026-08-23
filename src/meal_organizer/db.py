import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import DB_PATH, ensure_app_dir


@dataclass(slots=True)
class InventoryItem:
    id: int
    name: str
    quantity: float
    unit: str
    location: str
    updated_at: str


class Database:
    def __init__(self, path=DB_PATH):
        ensure_app_dir()
        self.path = path
        self._initialize()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    quantity REAL NOT NULL CHECK(quantity >= 0),
                    unit TEXT NOT NULL,
                    location TEXT NOT NULL DEFAULT 'fridge',
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS price_cache (
                    product_key TEXT NOT NULL,
                    location TEXT NOT NULL,
                    price REAL NOT NULL CHECK(price >= 0),
                    currency TEXT NOT NULL DEFAULT 'EUR',
                    source TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    confidence TEXT NOT NULL,
                    PRIMARY KEY(product_key, location, source)
                );
                """
            )

    def list_inventory(self) -> list[InventoryItem]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM inventory ORDER BY location, name").fetchall()
        return [InventoryItem(**dict(row)) for row in rows]

    def upsert_inventory(self, name: str, quantity: float, unit: str, location: str) -> None:
        if quantity < 0:
            raise ValueError("quantity must be non-negative")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO inventory(name, quantity, unit, location, updated_at)
                   VALUES(?, ?, ?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET quantity=excluded.quantity,
                   unit=excluded.unit, location=excluded.location, updated_at=excluded.updated_at""",
                (name.strip(), quantity, unit.strip(), location.strip(), now),
            )

    def remove_inventory(self, name: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM inventory WHERE name = ?", (name.strip(),))
            return cur.rowcount > 0

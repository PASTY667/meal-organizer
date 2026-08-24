import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from .config import DB_PATH, ensure_app_dir
from .models import MealPlan, Recipe

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
        self.path = path
        ensure_app_dir()
        self._initialize()

    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self):
        with self.connect() as conn:
            conn.executescript("""
            CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL COLLATE NOCASE UNIQUE,quantity REAL NOT NULL CHECK(quantity>=0),unit TEXT NOT NULL,location TEXT NOT NULL DEFAULT 'fridge',updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS price_cache(product_key TEXT NOT NULL,location TEXT NOT NULL,price REAL NOT NULL CHECK(price>=0),currency TEXT NOT NULL DEFAULT 'EUR',source TEXT NOT NULL,observed_at TEXT NOT NULL,confidence TEXT NOT NULL,PRIMARY KEY(product_key,location,source));
            CREATE TABLE IF NOT EXISTS meal_plans(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT NOT NULL CHECK(status IN ('draft','accepted','paused','rejected')),data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recipes(id INTEGER PRIMARY KEY AUTOINCREMENT,plan_id INTEGER,meal_day TEXT NOT NULL,data TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(plan_id,meal_day));
            """)

    def list_inventory(self):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM inventory ORDER BY location,name").fetchall()
        return [InventoryItem(**dict(r)) for r in rows]

    def upsert_inventory(self,name,quantity,unit,location):
        if quantity < 0: raise ValueError("quantity must be non-negative")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute("""INSERT INTO inventory(name,quantity,unit,location,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET quantity=excluded.quantity,unit=excluded.unit,location=excluded.location,updated_at=excluded.updated_at""",(name.strip(),quantity,unit.strip(),location.strip(),now))

    def remove_inventory(self,name):
        with self.connect() as conn:
            return conn.execute("DELETE FROM inventory WHERE name=?",(name.strip(),)).rowcount>0

    def save_plan(self,plan,status="draft",plan_id=None):
        now = datetime.now(timezone.utc).isoformat()
        data = plan.model_dump_json()
        with self.connect() as conn:
            if plan_id is None:
                cur = conn.execute("INSERT INTO meal_plans(status,data,created_at,updated_at) VALUES(?,?,?,?)",(status,data,now,now))
                return int(cur.lastrowid)
            conn.execute("UPDATE meal_plans SET status=?,data=?,updated_at=? WHERE id=?",(status,data,now,plan_id))
            return plan_id

    def load_latest_plan(self,statuses=("draft","paused")):
        placeholders = ",".join("?" for _ in statuses)
        with self.connect() as conn:
            row = conn.execute(f"SELECT id,status,data,created_at,updated_at FROM meal_plans WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT 1",statuses).fetchone()
        return (int(row['id']),row['status'],MealPlan.model_validate_json(row['data']),row['created_at'],row['updated_at']) if row else None

    def load_latest_accepted_plan(self):
        with self.connect() as conn:
            row = conn.execute("SELECT id,status,data,created_at,updated_at FROM meal_plans WHERE status='accepted' ORDER BY id DESC LIMIT 1").fetchone()
        return (int(row['id']),row['status'],MealPlan.model_validate_json(row['data']),row['created_at'],row['updated_at']) if row else None

    def has_current_week_plan(self, now=None):
        latest = self.load_latest_accepted_plan()
        if not latest:
            return False, None
        now = now or datetime.now(timezone.utc)
        try:
            created = datetime.fromisoformat(latest[3].replace('Z','+00:00'))
        except ValueError:
            return False, latest
        return (now - created) < timedelta(days=7), latest

    def list_recent_meal_names(self,limit_plans=4):
        with self.connect() as conn:
            rows=conn.execute("SELECT data FROM meal_plans WHERE status='accepted' ORDER BY id DESC LIMIT ?",(limit_plans,)).fetchall()
        names=[]
        for row in rows:
            try: names.extend(m['name'] for m in MealPlan.model_validate_json(row['data']).model_dump()['meals'])
            except Exception: continue
        return names

    def save_recipe(self,plan_id,day,recipe):
        now=datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            existing=conn.execute("SELECT id FROM recipes WHERE plan_id IS ? AND meal_day=?",(plan_id,day)).fetchone()
            if existing:
                conn.execute("UPDATE recipes SET data=?,updated_at=? WHERE id=?",(recipe.model_dump_json(),now,existing['id'])); return int(existing['id'])
            cur=conn.execute("INSERT INTO recipes(plan_id,meal_day,data,created_at,updated_at) VALUES(?,?,?,?,?)",(plan_id,day,recipe.model_dump_json(),now,now)); return int(cur.lastrowid)

    def load_recipe(self,plan_id,day):
        with self.connect() as conn: row=conn.execute("SELECT data FROM recipes WHERE plan_id IS ? AND meal_day=? ORDER BY id DESC LIMIT 1",(plan_id,day)).fetchone()
        return Recipe.model_validate_json(row['data']) if row else None

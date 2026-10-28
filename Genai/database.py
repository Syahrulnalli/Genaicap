import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from flask import current_app, g

STATUSES = ("Pending", "In Progress", "Resolved", "Closed")
CATEGORIES = ("Delivery", "Refund", "Product", "Payment", "Account", "Other")
PRIORITIES = ("Low", "Medium", "High", "Critical")
SENTIMENTS = ("Positive", "Neutral", "Negative", "Very Negative")

def get_db():
    if "db" not in g:
        path = Path(current_app.config["DATABASE_PATH"])
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        g.db = connection
    return g.db

def close_db(_error=None):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()

def init_db():
    db = get_db()
    db.executescript((Path(current_app.root_path) / "schema.sql").read_text(encoding="utf-8"))
    columns = {row["name"] for row in db.execute("PRAGMA table_info(complaints)")}
    if "user_id" not in columns:
        db.execute("ALTER TABLE complaints ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE SET NULL")
    db.execute("CREATE INDEX IF NOT EXISTS idx_complaints_user_id ON complaints(user_id)")
    db.commit()

def normalize_email(email):
    return str(email or "").strip().lower()

def get_user(user_id):
    return get_db().execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

def get_user_by_email(email):
    return get_db().execute("SELECT * FROM users WHERE email=?", (normalize_email(email),)).fetchone()

def create_user(name, email, password_hash, role="customer"):
    if role not in ("customer", "admin"):
        raise ValueError("Invalid user role")
    db = get_db()
    cursor = db.execute("INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,?)",
                        (str(name).strip(), normalize_email(email), password_hash, role))
    db.commit()
    return get_user(cursor.lastrowid)

def create_complaint(data, user_id=None):
    db = get_db()
    cursor = db.execute("INSERT INTO complaints (customer_name,email,order_id,phone,complaint_text,ai_status,user_id) VALUES (?,?,?,?,?, 'Pending', ?)",
        (data["customer_name"], data["email"], data.get("order_id") or None, data.get("phone") or None, data["complaint_text"], user_id))
    db.commit()
    return get_complaint(cursor.lastrowid)

def get_complaint(complaint_id, user_id=None):
    if user_id is None:
        return get_db().execute("SELECT * FROM complaints WHERE id = ?", (complaint_id,)).fetchone()
    return get_db().execute("SELECT * FROM complaints WHERE id = ? AND user_id = ?", (complaint_id, user_id)).fetchone()

def get_complaints(search="", category="", priority="", status="", sentiment="", limit=None, offset=0, user_id=None):
    clauses, params = [], []
    if user_id is not None:
        clauses.append("user_id = ?")
        params.append(user_id)
    if search:
        pattern = f"%{search}%"
        clauses.append("(CAST(id AS TEXT) LIKE ? OR customer_name LIKE ? OR email LIKE ? OR COALESCE(order_id,'') LIKE ? OR complaint_text LIKE ?)")
        params.extend([pattern] * 5)
    for field, value, allowed in (("category", category, CATEGORIES), ("priority", priority, PRIORITIES), ("status", status, STATUSES), ("sentiment", sentiment, SENTIMENTS)):
        if value and value in allowed:
            clauses.append(f"{field} = ?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    sql = "SELECT * FROM complaints" + where + " ORDER BY created_at DESC, id DESC"
    if limit is not None:
        sql += " LIMIT ? OFFSET ?"
        params.extend([limit, offset])
    return get_db().execute(sql, params).fetchall()

def count_complaints(search="", category="", priority="", status="", sentiment="", user_id=None):
    return len(get_complaints(search, category, priority, status, sentiment, user_id=user_id))

def get_customer_stats(user_id):
    db = get_db()
    rows = db.execute("SELECT status, COUNT(*) AS total FROM complaints WHERE user_id=? GROUP BY status", (user_id,)).fetchall()
    counts = {row["status"]: row["total"] for row in rows}
    return {"total": sum(counts.values()), "pending": counts.get("Pending", 0),
            "in_progress": counts.get("In Progress", 0), "resolved": counts.get("Resolved", 0)}

def update_complaint_status(complaint_id, status):
    if status not in STATUSES:
        raise ValueError("Invalid complaint status")
    db = get_db()
    db.execute("UPDATE complaints SET status=?, updated_at=? WHERE id=?", (status, datetime.now(timezone.utc).isoformat(timespec="seconds"), complaint_id))
    db.commit()
    return get_complaint(complaint_id)

def update_complaint_priority(complaint_id, priority):
    if priority not in PRIORITIES:
        raise ValueError("Invalid complaint priority")
    db = get_db()
    db.execute("UPDATE complaints SET priority=?, updated_at=? WHERE id=?",
               (priority, datetime.now(timezone.utc).isoformat(timespec="seconds"), complaint_id))
    db.commit()
    return get_complaint(complaint_id)

def update_ai_analysis(complaint_id, analysis, model):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    db.execute("UPDATE complaints SET category=?,sentiment=?,priority=?,summary=?,recommended_action=?,generated_response=?,ai_status='Completed',ai_model=?,ai_analyzed_at=?,updated_at=? WHERE id=?",
        (analysis["category"], analysis["sentiment"], analysis["priority"], analysis["summary"], analysis["recommended_action"], analysis["response"], model, now, now, complaint_id))
    db.commit()
    return get_complaint(complaint_id)

def mark_ai_failed(complaint_id):
    db = get_db()
    db.execute("UPDATE complaints SET ai_status='Failed',updated_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(timespec="seconds"), complaint_id))
    db.commit()

def _group_stats(column, values):
    rows = get_db().execute(f"SELECT {column}, COUNT(*) AS total FROM complaints GROUP BY {column}").fetchall()
    counts = {row[column]: row["total"] for row in rows}
    return {value: counts.get(value, 0) for value in values}

def get_dashboard_stats():
    db = get_db()
    total = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    by_status, by_priority = _group_stats("status", STATUSES), _group_stats("priority", PRIORITIES)
    by_category, by_sentiment = _group_stats("category", CATEGORIES), _group_stats("sentiment", SENTIMENTS)
    return {"total": total, "pending": by_status["Pending"], "in_progress": by_status["In Progress"], "resolved": by_status["Resolved"],
        "high": by_priority["High"], "critical": by_priority["Critical"], "by_status": by_status,
        "by_priority": by_priority, "by_category": by_category, "by_sentiment": by_sentiment}

def get_category_stats(): return _group_stats("category", CATEGORIES)
def get_priority_stats(): return _group_stats("priority", PRIORITIES)
def get_sentiment_stats(): return _group_stats("sentiment", SENTIMENTS)

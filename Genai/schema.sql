CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL COLLATE NOCASE UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('customer','admin')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    email TEXT NOT NULL,
    order_id TEXT,
    phone TEXT,
    complaint_text TEXT NOT NULL,
    category TEXT CHECK (category IS NULL OR category IN ('Delivery','Refund','Product','Payment','Account','Other')),
    sentiment TEXT CHECK (sentiment IS NULL OR sentiment IN ('Positive','Neutral','Negative','Very Negative')),
    priority TEXT CHECK (priority IS NULL OR priority IN ('Low','Medium','High','Critical')),
    summary TEXT,
    recommended_action TEXT,
    generated_response TEXT,
    status TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','In Progress','Resolved','Closed')),
    ai_status TEXT NOT NULL DEFAULT 'Pending' CHECK (ai_status IN ('Pending','Completed','Failed')),
    ai_model TEXT,
    ai_analyzed_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_complaints_created_at ON complaints(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);

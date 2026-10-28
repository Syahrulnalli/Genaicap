import tempfile
import sqlite3
import unittest
from pathlib import Path
from app import create_app
import database

class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "DATABASE_PATH": str(Path(self.temp.name) / "test.db")})
        self.ctx = self.app.app_context(); self.ctx.push(); database.init_db()

    def tearDown(self): database.close_db(); self.ctx.pop(); self.temp.cleanup()

    def test_crud_status_and_stats(self):
        record = database.create_complaint({"customer_name":"A","email":"a@example.com","complaint_text":"A sufficiently detailed complaint."})
        self.assertEqual(record["status"], "Pending")
        updated = database.update_complaint_status(record["id"], "Resolved")
        self.assertEqual(updated["status"], "Resolved")
        self.assertEqual(database.get_dashboard_stats()["total"], 1)
        self.assertEqual(database.get_dashboard_stats()["resolved"], 1)

    def test_combined_filters_and_search(self):
        database.create_complaint({"customer_name":"Jordan","email":"j@example.com","order_id":"ORD-X","complaint_text":"Need help with a delivery."})
        self.assertEqual(len(database.get_complaints(search="ORD-X", status="Pending")), 1)
        self.assertEqual(len(database.get_complaints(category="Refund")), 0)

    def test_legacy_database_upgrade_preserves_rows_and_leaves_them_unowned(self):
        legacy_path = Path(self.temp.name) / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.execute("CREATE TABLE complaints (id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT NOT NULL, email TEXT NOT NULL, complaint_text TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'Pending', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        connection.execute("INSERT INTO complaints (id, customer_name, email, complaint_text, status) VALUES (41,'Legacy Customer','legacy@example.com','Older complaint row','Resolved')")
        connection.commit(); connection.close()
        legacy_app = create_app({"TESTING": True, "DATABASE_PATH": str(legacy_path)})
        with legacy_app.app_context():
            database.init_db()
            row = database.get_complaint(41)
            self.assertEqual(row["customer_name"], "Legacy Customer")
            self.assertEqual(row["status"], "Resolved")
            self.assertIsNone(row["user_id"])
            columns = {col["name"] for col in database.get_db().execute("PRAGMA table_info(complaints)")}
            self.assertIn("user_id", columns)

if __name__ == "__main__": unittest.main()

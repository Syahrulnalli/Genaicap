import sqlite3
import tempfile
import unittest
from pathlib import Path

from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
import database
from demo_data import DEMO_COMPLAINTS, DEMO_CUSTOMERS, DEMO_AI_MODEL


class DemoDataCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp.name) / "pccsms.db"
        self.app = create_app({
            "TESTING": True,
            "WTF_CSRF_ENABLED": False,
            "DATABASE_PATH": str(self.db_path),
            "SECRET_KEY": "demo-data-test-session-key",
        })
        self.runner = self.app.test_cli_runner()
        with self.app.app_context():
            database.init_db()
            self.admin = database.create_user(
                "Existing Admin", "owner@example.test",
                generate_password_hash("existing-admin-test-password"), role="admin",
            )
            self.original = database.get_db().execute(
                "INSERT INTO complaints (id,customer_name,email,complaint_text,status) "
                "VALUES (72,'Legacy Sample','legacy@example.com','Existing complaint to preserve in backup.','Resolved')"
            )
            database.get_db().commit()
            self.admin_before = dict(database.get_user(self.admin["id"]))

    def tearDown(self):
        self.temp.cleanup()

    def _complaint_count(self):
        connection = sqlite3.connect(self.db_path)
        try:
            return connection.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        finally:
            connection.close()

    def test_reset_requires_explicit_flag_and_leaves_db_and_backups_untouched(self):
        result = self.runner.invoke(args=["reset-demo-data"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--confirm-reset", result.output)
        self.assertEqual(self._complaint_count(), 1)
        self.assertFalse((self.db_path.parent / "backups").exists())

    def test_success_backups_resets_and_seeds_owned_synthetic_data_idempotently(self):
        demo_password = "demo-customer-test-password-2026"
        args = ["reset-demo-data", "--confirm-reset"]
        result = self.runner.invoke(args=args, input=f"{demo_password}\n{demo_password}\n")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn(demo_password, result.output)
        self.assertIn("Complaints deleted: 1", result.output)
        self.assertIn(f"Demo complaints inserted: {len(DEMO_COMPLAINTS)}", result.output)
        self.assertIn("Existing user accounts preserved: 1", result.output)
        self.assertIn("Complaint ID sequence was preserved", result.output)
        backup_line = next(line for line in result.output.splitlines() if line.startswith("Backup created: "))
        backup_path = Path(backup_line.removeprefix("Backup created: ").strip())
        self.assertTrue(backup_path.is_file())
        self.assertEqual(backup_path.parent, self.db_path.parent / "backups")

        backup = sqlite3.connect(backup_path)
        try:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT id FROM complaints").fetchone()[0], 72)
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
        finally:
            backup.close()

        with self.app.app_context():
            users = database.get_db().execute("SELECT * FROM users ORDER BY id").fetchall()
            counts = database.get_db().execute(
                "SELECT ai_status,COUNT(*) FROM complaints GROUP BY ai_status"
            ).fetchall()
            rows = database.get_db().execute("SELECT * FROM complaints ORDER BY id").fetchall()
            self.assertEqual(dict(database.get_user(self.admin["id"])), self.admin_before)
            self.assertEqual(len(users), 1 + len(DEMO_CUSTOMERS))
            self.assertEqual({row["role"] for row in users}, {"admin", "customer"})
            self.assertEqual({row["email"] for row in users if row["role"] == "customer"},
                             {customer.email for customer in DEMO_CUSTOMERS})
            self.assertEqual(len(rows), 18)
            self.assertTrue(all(row["user_id"] is not None for row in rows))
            self.assertTrue(all(row["id"] > 72 for row in rows))
            completed_rows = [row for row in rows if row["ai_status"] == "Completed"]
            self.assertEqual({row["category"] for row in completed_rows}, set(database.CATEGORIES))
            self.assertEqual({row["sentiment"] for row in completed_rows}, set(database.SENTIMENTS))
            self.assertEqual({row["priority"] for row in completed_rows}, set(database.PRIORITIES))
            self.assertEqual({row["status"] for row in rows}, set(database.STATUSES))
            self.assertEqual({row["ai_status"]: row["COUNT(*)"] for row in counts},
                             {"Completed": 13, "Failed": 2, "Pending": 3})
            completed_fields = ("category", "sentiment", "priority", "summary", "recommended_action", "generated_response")
            for row in rows:
                if row["ai_status"] == "Completed":
                    self.assertTrue(all(row[field] for field in completed_fields))
                    self.assertEqual(row["ai_model"], DEMO_AI_MODEL)
                    self.assertIsNotNone(row["ai_analyzed_at"])
                    self.assertIn(row["category"], database.CATEGORIES)
                    self.assertIn(row["sentiment"], database.SENTIMENTS)
                    self.assertIn(row["priority"], database.PRIORITIES)
                else:
                    self.assertTrue(all(row[field] is None for field in completed_fields))
                    self.assertIsNone(row["ai_model"])
                    self.assertIsNone(row["ai_analyzed_at"])
                self.assertIn(row["status"], database.STATUSES)
            customer_hashes = [row["password_hash"] for row in users if row["role"] == "customer"]
            self.assertEqual(len(set(customer_hashes)), len(DEMO_CUSTOMERS))
            self.assertTrue(all(check_password_hash(value, demo_password) for value in customer_hashes))

        # A customer can see the owned samples, including the synthetic-data label.
        client = self.app.test_client()
        customer_email = DEMO_CUSTOMERS[0].email
        login = client.post("/login", data={"email": customer_email, "password": demo_password})
        self.assertEqual(login.status_code, 302)
        history = client.get("/customer/complaints")
        self.assertEqual(history.status_code, 200)
        self.assertIn(b"3 of your records", history.data)
        with self.app.app_context():
            customer_record = database.get_db().execute(
                "SELECT id, generated_response FROM complaints WHERE user_id=(SELECT id FROM users WHERE email=?) "
                "AND ai_status='Completed' ORDER BY id LIMIT 1", (customer_email,),
            ).fetchone()
        detail = client.get(f"/customer/complaints/{customer_record['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(b"This is synthetic demonstration content", detail.data)
        self.assertIn(b"Response to your complaint", detail.data)
        self.assertIn(customer_record["generated_response"].encode(), detail.data)
        self.assertIn(b"This response is synthetic demonstration content", detail.data)
        self.assertNotIn(b"Groq", detail.data)
        self.assertNotIn(b"recommended_action", detail.data)
        client.post("/logout")
        client.post("/login", data={"email": "owner@example.test", "password": "existing-admin-test-password"})
        admin_dashboard = client.get("/")
        self.assertEqual(admin_dashboard.status_code, 200)
        dashboard_stats = client.get("/api/dashboard/stats")
        self.assertEqual(dashboard_stats.status_code, 200)
        self.assertEqual(dashboard_stats.json["data"]["total"], 18)
        self.assertEqual(dashboard_stats.json["data"]["by_status"], {
            "Pending": 7, "In Progress": 7, "Resolved": 2, "Closed": 2,
        })
        self.assertEqual(client.get("/complaints").status_code, 200)
        admin_page = client.get(f"/complaints/{rows[0]['id']}")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn(b"Synthetic demonstration data", admin_page.data)

        # Re-running replaces the 18 samples instead of appending duplicates and does not reset passwords.
        second = self.runner.invoke(args=args)
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertIn("Complaints deleted: 18", second.output)
        self.assertEqual(self._complaint_count(), 18)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 7)
            self.assertTrue(all(check_password_hash(value, demo_password) for value in customer_hashes))
        self.assertEqual(len(list((self.db_path.parent / "backups").glob("pccsms-before-demo-reset-*.db"))), 2)

    def test_demo_email_collision_with_admin_refuses_before_backup_or_delete(self):
        collision_app = create_app({
            "TESTING": True,
            "DATABASE_PATH": str(self.db_path),
            "ADMIN_EMAIL": DEMO_CUSTOMERS[0].email,
            "ADMIN_PASSWORD": "temporary-test-password-123",
        })
        with collision_app.app_context():
            database.create_user("Collision Admin", DEMO_CUSTOMERS[0].email,
                                 generate_password_hash("collision-admin-password"), role="admin")
        result = collision_app.test_cli_runner().invoke(args=["reset-demo-data", "--confirm-reset"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("non-customer account", result.output)
        self.assertEqual(self._complaint_count(), 1)
        self.assertFalse((self.db_path.parent / "backups").exists())

    def test_insert_failure_rolls_back_deletion_and_new_accounts_after_backup(self):
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "CREATE TRIGGER fail_demo_insert BEFORE INSERT ON complaints "
                "WHEN NEW.order_id='DEMO-4108' BEGIN SELECT RAISE(ABORT,'intentional test failure'); END"
            )
            connection.commit()
        finally:
            connection.close()
        password = "demo-customer-test-password-2026"
        result = self.runner.invoke(
            args=["reset-demo-data", "--confirm-reset"], input=f"{password}\n{password}\n"
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("intentional test failure", result.output)
        self.assertEqual(self._complaint_count(), 1)
        with self.app.app_context():
            self.assertEqual(database.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 1)
            self.assertEqual(database.get_complaint(72)["complaint_text"], "Existing complaint to preserve in backup.")
        backups = list((self.db_path.parent / "backups").glob("pccsms-before-demo-reset-*.db"))
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(backups[0])
        try:
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(backup.execute("SELECT COUNT(*) FROM complaints").fetchone()[0], 1)
        finally:
            backup.close()

    def test_demo_customer_password_reset_is_hidden_scoped_and_preserves_complaints(self):
        old_password = "demo-customer-old-password-2026"
        seed = self.runner.invoke(
            args=["reset-demo-data", "--confirm-reset"], input=f"{old_password}\n{old_password}\n"
        )
        self.assertEqual(seed.exit_code, 0, seed.output)
        with self.app.app_context():
            before = {
                row["email"]: dict(row)
                for row in database.get_db().execute("SELECT * FROM users")
            }
        old_password_hashes = [before[customer.email]["password_hash"] for customer in DEMO_CUSTOMERS]

        missing_confirmation = self.runner.invoke(args=["reset-demo-customer-password"])
        self.assertNotEqual(missing_confirmation.exit_code, 0)
        self.assertIn("--confirm", missing_confirmation.output)
        short_password = "short-demo"
        invalid = self.runner.invoke(
            args=["reset-demo-customer-password", "--confirm"],
            input=f"{short_password}\n{short_password}\n",
        )
        self.assertNotEqual(invalid.exit_code, 0)
        self.assertNotIn(short_password, invalid.output)

        new_password = "demo-customer-new-password-2026"
        reset = self.runner.invoke(
            args=["reset-demo-customer-password", "--confirm"],
            input=f"{new_password}\n{new_password}\n",
        )
        self.assertEqual(reset.exit_code, 0, reset.output)
        self.assertNotIn(new_password, reset.output)
        self.assertIn("Reset the password hashes for 6 demo customer accounts", reset.output)
        self.assertEqual(self._complaint_count(), 18)
        with self.app.app_context():
            after = {
                row["email"]: dict(row)
                for row in database.get_db().execute("SELECT * FROM users")
            }
            for customer, old_hash in zip(DEMO_CUSTOMERS, old_password_hashes):
                record = after[customer.email]
                self.assertEqual(record["role"], "customer")
                self.assertEqual(record["is_active"], 1)
                self.assertNotEqual(record["password_hash"], old_hash)
                self.assertTrue(check_password_hash(record["password_hash"], new_password))
            new_hashes = [after[customer.email]["password_hash"] for customer in DEMO_CUSTOMERS]
            self.assertEqual(len(set(new_hashes)), 6)
            self.assertEqual(after["owner@example.test"], before["owner@example.test"])

        client = self.app.test_client()
        login = client.post("/login", data={"email": DEMO_CUSTOMERS[0].email, "password": new_password})
        self.assertEqual(login.status_code, 302)
        self.assertEqual(client.get("/customer/complaints").status_code, 200)


if __name__ == "__main__":
    unittest.main()

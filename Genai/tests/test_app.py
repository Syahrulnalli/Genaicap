import sqlite3
import tempfile
import unittest
from pathlib import Path
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
import database


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False,
                               "DATABASE_PATH": str(Path(self.temp.name) / "test.db"), "AI_MOCK_MODE": True,
                               "SECRET_KEY": "test-session-key"})
        self.client = self.app.test_client()
        with self.app.app_context():
            database.init_db()
            self.customer = database.create_user("Taylor Customer", "taylor@example.com", generate_password_hash("customer-password"))
            self.other = database.create_user("Other Customer", "other@example.com", generate_password_hash("other-password"))
            self.admin = database.create_user("Admin", "admin@example.com", generate_password_hash("admin-password"), role="admin")

    def tearDown(self):
        self.temp.cleanup()

    def login(self, email="taylor@example.com", password="customer-password"):
        return self.client.post("/login", data={"email": email, "password": password}, follow_redirects=False)

    def payload(self):
        return {"customer_name": "Forged Name", "email": "forged@example.com", "phone": "555", "order_id": "A-42",
                "complaint_text": "My order delivery has not arrived and tracking is unchanged.",
                "role": "admin", "status": "Resolved", "priority": "Critical", "category": "Refund",
                "user_id": self.other["id"], "ai_status": "Completed",
                "recommended_action": "Forged internal action", "generated_response": "Forged draft"}

    def customer_complaint(self, email="taylor@example.com", password="customer-password"):
        self.client.post("/logout")
        self.login(email, password)
        return self.client.post("/api/complaints", json=self.payload()).json["data"]["id"]

    def test_public_auth_pages_and_protected_redirect(self):
        self.assertEqual(self.client.get("/login").status_code, 200)
        self.assertEqual(self.client.get("/register").status_code, 200)
        response = self.client.get("/complaints")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)
        self.assertEqual(self.client.get("/api/complaints/1").status_code, 401)

    def test_login_rejects_external_redirect_target(self):
        response = self.client.post("/login", data={"email": "taylor@example.com", "password": "customer-password", "next": "https://example.org/"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.location, "/customer")

    def test_registration_normalizes_email_hashes_password_and_forces_customer_role(self):
        response = self.client.post("/register", data={"name": "New Person", "email": " New@Example.com ",
            "password": "safe-password-123", "confirm_password": "safe-password-123", "role": "admin"})
        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            user = database.get_user_by_email("new@example.com")
            self.assertEqual(user["role"], "customer")
            self.assertTrue(check_password_hash(user["password_hash"], "safe-password-123"))
            self.assertNotEqual(user["password_hash"], "safe-password-123")

    def test_registration_rejects_duplicate_invalid_email_and_password_mismatch(self):
        duplicate = self.client.post("/register", data={"name": "Duplicate", "email": "TAYLOR@example.com",
            "password": "safe-password-123", "confirm_password": "safe-password-123"})
        invalid = self.client.post("/register", data={"name": "Bad", "email": "invalid", "password": "safe-password-123", "confirm_password": "safe-password-123"})
        mismatch = self.client.post("/register", data={"name": "Bad", "email": "new@example.com", "password": "safe-password-123", "confirm_password": "different-password"})
        self.assertEqual((duplicate.status_code, invalid.status_code, mismatch.status_code), (400, 400, 400))

    def test_login_routes_by_database_role_and_rejects_bad_or_inactive_account(self):
        bad = self.login(password="wrong-password")
        self.assertEqual(bad.status_code, 401)
        self.assertIn(b"Email or password is incorrect", bad.data)
        customer = self.login()
        self.assertEqual(customer.status_code, 302)
        self.assertTrue(customer.location.endswith("/customer"))
        self.client.post("/logout")
        admin = self.login("admin@example.com", "admin-password")
        self.assertTrue(admin.location.endswith("/"))
        self.client.post("/logout")
        with self.app.app_context():
            database.get_db().execute("UPDATE users SET is_active=0 WHERE id=?", (self.customer["id"],))
            database.get_db().commit()
        inactive = self.login()
        self.assertEqual(inactive.status_code, 403)

    def test_role_access_and_logout_session_clearing(self):
        self.login()
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/customer").status_code, 200)
        self.assertEqual(self.client.get("/customer/account").status_code, 200)
        self.assertEqual(self.client.get("/customer/complaints/new").status_code, 200)
        self.assertEqual(self.client.get("/complaints").status_code, 403)
        self.client.post("/logout")
        self.login("admin@example.com", "admin-password")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.client.post("/logout")
        self.login()
        self.assertEqual(self.client.get("/complaints").status_code, 403)

    def test_customer_submission_uses_session_identity_and_ignores_privileged_fields(self):
        self.login()
        response = self.client.post("/api/complaints", json=self.payload())
        self.assertEqual(response.status_code, 201)
        complaint_id = response.json["data"]["id"]
        record = self.client.get(f"/customer/complaints/{complaint_id}")
        self.assertEqual(record.status_code, 200)
        with self.app.app_context():
            saved = database.get_complaint(complaint_id)
            self.assertEqual(saved["user_id"], self.customer["id"])
            self.assertEqual(saved["customer_name"], "Taylor Customer")
            self.assertEqual(saved["email"], "taylor@example.com")
            self.assertEqual(saved["status"], "Pending")
            self.assertNotEqual(saved["priority"], "Critical")
            self.assertEqual(saved["user_id"], self.customer["id"])
            self.assertNotEqual(saved["recommended_action"], "Forged internal action")
            self.assertNotEqual(saved["generated_response"], "Forged draft")
            generated_response = saved["generated_response"]
        self.assertIn(b"Response to your complaint", record.data)
        self.assertIn(b"Review complete", record.data)
        self.assertIn(generated_response.encode(), record.data)
        self.assertIn(b"Customer Support", record.data)
        self.assertNotIn(b"AI Support", record.data)
        self.assertNotIn(b"AI-assisted", record.data)
        self.assertNotIn(b"AI-generated", record.data)
        self.assertNotIn(b"draft", record.data.lower())
        self.assertNotIn(b"Any AI-generated reply is a draft", record.data)

    def test_customer_detail_escapes_stored_ai_response(self):
        complaint_id = self.customer_complaint()
        with self.app.app_context():
            database.update_ai_analysis(complaint_id, {
                "category": "Product", "sentiment": "Negative", "priority": "Medium",
                "summary": "Products arrived damaged.", "recommended_action": "Review the case.",
                "response": "Hello Taylor, <script>alert('x')</script> We will review your case.",
            }, "Groq test model")
        self.login()
        page = self.client.get(f"/customer/complaints/{complaint_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Hello Taylor, &lt;script&gt;alert(&#39;x&#39;)&lt;/script&gt;", page.data)
        self.assertNotIn(b"<script>alert('x')</script>", page.data)

    def test_admin_and_customer_views_show_the_same_response_for_each_complaint(self):
        first_id = self.customer_complaint()
        second_id = self.customer_complaint()
        first_response = "We are sorry your parcel arrived damaged. Please share photos so support can investigate."
        second_response = "We are sorry your payment was charged twice. Support will review the transaction details."
        with self.app.app_context():
            for complaint_id, response in ((first_id, first_response), (second_id, second_response)):
                database.update_ai_analysis(complaint_id, {
                    "category": "Product", "sentiment": "Negative", "priority": "Medium",
                    "summary": "The customer reported an issue.", "recommended_action": "Review the case.",
                    "response": response,
                }, "Groq test model")

        self.client.post("/logout")
        self.login("admin@example.com", "admin-password")
        admin_first = self.client.get(f"/complaints/{first_id}")
        admin_second = self.client.get(f"/complaints/{second_id}")
        self.assertEqual((admin_first.status_code, admin_second.status_code), (200, 200))
        self.assertIn(b"Generated response", admin_first.data)
        self.assertIn(first_response.encode(), admin_first.data)
        self.assertIn(second_response.encode(), admin_second.data)
        self.assertNotIn(first_response.encode(), admin_second.data)

        self.client.post("/logout")
        self.login()
        customer_first = self.client.get(f"/customer/complaints/{first_id}")
        customer_second = self.client.get(f"/customer/complaints/{second_id}")
        self.assertEqual((customer_first.status_code, customer_second.status_code), (200, 200))
        self.assertIn(first_response.encode(), customer_first.data)
        self.assertIn(second_response.encode(), customer_second.data)
        self.assertNotIn(first_response.encode(), customer_second.data)
        self.assertNotIn(second_response.encode(), customer_first.data)

    def test_customer_detail_shows_pending_response_message_without_running_analysis(self):
        with self.app.app_context():
            pending = database.create_complaint({"customer_name": "Taylor Customer", "email": "taylor@example.com",
                "complaint_text": "My package is delayed."}, user_id=self.customer["id"])
        self.login()
        page = self.client.get(f"/customer/complaints/{pending['id']}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"A response will appear after its review is complete", page.data)
        self.assertNotIn(b"Groq", page.data)
        with self.app.app_context():
            self.assertEqual(database.get_complaint(pending["id"])["ai_status"], "Pending")
            self.assertIsNone(database.get_complaint(pending["id"])["generated_response"])

    def test_customer_detail_handles_completed_analysis_without_stored_response(self):
        complaint_id = self.customer_complaint()
        with self.app.app_context():
            database.get_db().execute("UPDATE complaints SET generated_response=NULL WHERE id=?", (complaint_id,))
            database.get_db().commit()
        self.login()
        page = self.client.get(f"/customer/complaints/{complaint_id}")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"The review is complete, but a response is not available", page.data)
        self.assertNotIn(b"Our support team will review your complaint. Any AI-generated reply", page.data)
        with self.app.app_context():
            complaint = database.get_complaint(complaint_id)
            self.assertEqual(complaint["ai_status"], "Completed")
            self.assertIsNone(complaint["generated_response"])

    def test_customer_idor_and_history_and_stats_are_scoped(self):
        own_id = self.customer_complaint()
        other_id = self.customer_complaint("other@example.com", "other-password")
        self.client.post("/logout")
        self.login()
        self.assertEqual(self.client.get(f"/customer/complaints/{own_id}").status_code, 200)
        with self.app.app_context():
            database.update_ai_analysis(other_id, {
                "category": "Other", "sentiment": "Neutral", "priority": "Low",
                "summary": "Private summary.", "recommended_action": "Internal note.",
                "response": "PRIVATE OTHER CUSTOMER RESPONSE",
            }, "Groq test model")
        other_page = self.client.get(f"/customer/complaints/{other_id}")
        self.assertEqual(other_page.status_code, 404)
        self.assertNotIn(b"PRIVATE OTHER CUSTOMER RESPONSE", other_page.data)
        history = self.client.get("/customer/complaints")
        self.assertIn(f"#{own_id}".encode(), history.data)
        self.assertNotIn(f"#{other_id}".encode(), history.data)
        response = self.client.get("/customer")
        self.assertIn(b">1<", response.data)
        self.assertNotIn(f"#{other_id}".encode(), response.data)

    def test_customer_cannot_use_admin_mutation_or_data_endpoints(self):
        complaint_id = self.customer_complaint()
        self.login()
        for path, data in ((f"/api/complaints/{complaint_id}/status", {"status": "Resolved"}),
                           (f"/api/complaints/{complaint_id}/priority", {"priority": "Critical"}),
                           (f"/api/complaints/{complaint_id}/analyze", {}),
                           (f"/api/complaints/{complaint_id}", {}), ("/api/dashboard/stats", {})):
            response = self.client.post(path, json=data) if path.endswith(("status", "priority", "analyze")) else self.client.get(path)
            self.assertEqual(response.status_code, 403, path)

    def test_admin_can_view_and_manage_owned_legacy_and_other_customer_records(self):
        customer_id = self.customer_complaint()
        with self.app.app_context():
            legacy = database.create_complaint({"customer_name": "Legacy", "email": "legacy@example.com",
                "complaint_text": "An existing complaint preserved without a registered account."})
            legacy_id = legacy["id"]
        self.client.post("/logout")
        self.login("admin@example.com", "admin-password")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/complaints").status_code, 200)
        self.assertEqual(self.client.get(f"/complaints/{customer_id}").status_code, 200)
        self.assertEqual(self.client.get(f"/complaints/{legacy_id}").status_code, 200)
        api_record = self.client.get(f"/api/complaints/{customer_id}")
        self.assertEqual(api_record.status_code, 200)
        self.assertNotIn(b"password_hash", api_record.data)
        self.assertEqual(self.client.post(f"/api/complaints/{customer_id}/status", json={"status": "Resolved"}).status_code, 200)
        self.assertEqual(self.client.post(f"/api/complaints/{customer_id}/priority", json={"priority": "High"}).status_code, 200)
        stats = self.client.get("/api/dashboard/stats")
        self.assertEqual(stats.status_code, 200)
        self.assertEqual(stats.json["data"]["total"], 2)
        self.assertEqual(stats.json["data"]["resolved"], 1)
        self.assertEqual(stats.json["data"]["pending"], 1)
        self.assertEqual(stats.json["data"]["high"], 1)
        self.assertEqual(self.client.post(f"/api/complaints/{customer_id}/analyze").status_code, 200)

    def test_admin_provision_command_is_safe_and_idempotent(self):
        app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE_PATH": str(Path(self.temp.name) / "provision.db"),
            "ADMIN_EMAIL": " First.Admin@Example.com ", "ADMIN_PASSWORD": "a-strong-password-123"})
        runner = app.test_cli_runner()
        first = runner.invoke(args=["provision-admin"])
        self.assertEqual(first.exit_code, 0, first.output)
        second = runner.invoke(args=["provision-admin"])
        self.assertEqual(second.exit_code, 0, second.output)
        with app.app_context():
            admin = database.get_user_by_email("first.admin@example.com")
            self.assertEqual(admin["role"], "admin")
            self.assertTrue(check_password_hash(admin["password_hash"], "a-strong-password-123"))

    def test_admin_provision_fails_without_configuration_and_creates_no_default(self):
        app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "DATABASE_PATH": str(Path(self.temp.name) / "unconfigured.db"),
                          "ADMIN_EMAIL": "", "ADMIN_PASSWORD": ""})
        with app.app_context():
            database.init_db()
        result = app.test_cli_runner().invoke(args=["provision-admin"])
        self.assertNotEqual(result.exit_code, 0)
        with app.app_context():
            self.assertEqual(database.get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)

    def test_protected_post_requires_csrf_token(self):
        app = create_app({"TESTING": True, "DATABASE_PATH": str(Path(self.temp.name) / "csrf.db"), "SECRET_KEY": "csrf-test-key"})
        response = app.test_client().post("/register", data={"name": "A", "email": "a@example.com", "password": "password123", "confirm_password": "password123"})
        self.assertEqual(response.status_code, 400)

    def test_api_failure_keeps_complaint_owner_and_retryable(self):
        self.login()
        self.app.config["AI_MOCK_MODE"] = False
        self.app.config["GROQ_API_KEY"] = ""
        response = self.client.post("/api/complaints", json=self.payload())
        self.assertEqual(response.status_code, 201)
        record = self.client.get(f"/customer/complaints/{response.json['data']['id']}")
        self.assertEqual(record.status_code, 200)
        self.assertIn(b"A response is not available right now", record.data)
        self.assertNotIn(b"API key", record.data)
        with self.app.app_context():
            saved = database.get_complaint(response.json["data"]["id"])
            self.assertEqual(saved["ai_status"], "Failed")
            self.assertEqual(saved["user_id"], self.customer["id"])
            original_text = saved["complaint_text"]
        self.client.post("/logout")
        self.app.config["AI_MOCK_MODE"] = True
        self.login("admin@example.com", "admin-password")
        retry = self.client.post(f"/api/complaints/{response.json['data']['id']}/analyze")
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json["data"]["ai_status"], "Completed")
        with self.app.app_context():
            recovered = database.get_complaint(response.json["data"]["id"])
            self.assertEqual(recovered["complaint_text"], original_text)
            self.assertEqual(recovered["user_id"], self.customer["id"])
            self.assertEqual(recovered["ai_status"], "Completed")
            self.assertTrue(recovered["generated_response"])

    def test_public_registration_never_creates_admin_even_with_role_field(self):
        self.client.post("/register", data={"name": "Role Tamper", "email": "tamper@example.com", "password": "password123", "confirm_password": "password123", "role": "admin"})
        with self.app.app_context():
            self.assertEqual(database.get_user_by_email("tamper@example.com")["role"], "customer")

if __name__ == "__main__":
    unittest.main()

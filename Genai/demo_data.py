"""Safe, repeatable reset-and-seed support for PCCSMS demonstrations."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from werkzeug.security import generate_password_hash

from database import CATEGORIES, PRIORITIES, SENTIMENTS, STATUSES, normalize_email
from services.ai_service import validate_analysis


DEMO_AI_MODEL = "Synthetic demo"


@dataclass(frozen=True)
class DemoCustomer:
    name: str
    email: str


@dataclass(frozen=True)
class DemoComplaint:
    customer_email: str
    order_id: str | None
    complaint_text: str
    category: str | None
    sentiment: str | None
    priority: str | None
    status: str
    ai_status: str
    summary: str | None
    recommended_action: str | None
    response: str | None
    days_ago: int


DEMO_CUSTOMERS = (
    DemoCustomer("Maya Patel", "maya.patel@example.com"),
    DemoCustomer("Daniel Kim", "daniel.kim@example.com"),
    DemoCustomer("Aisha Rahman", "aisha.rahman@example.com"),
    DemoCustomer("Oliver Chen", "oliver.chen@example.com"),
    DemoCustomer("Sara Johnson", "sara.johnson@example.com"),
    DemoCustomer("Noah Williams", "noah.williams@example.com"),
)


def _completed(
    email: str,
    order_id: str | None,
    complaint: str,
    category: str,
    sentiment: str,
    priority: str,
    status: str,
    summary: str,
    action: str,
    response: str,
    days_ago: int,
) -> DemoComplaint:
    return DemoComplaint(email, order_id, complaint, category, sentiment, priority,
                         status, "Completed", summary, action, response, days_ago)


def _not_analyzed(
    email: str,
    order_id: str | None,
    complaint: str,
    status: str,
    ai_status: str,
    days_ago: int,
) -> DemoComplaint:
    return DemoComplaint(email, order_id, complaint, None, None, None, status,
                         ai_status, None, None, None, days_ago)


DEMO_COMPLAINTS = (
    _completed("maya.patel@example.com", "DEMO-4102",
        "The parcel was marked delivered yesterday, but nothing was left at my door or with the building desk. Could someone check the delivery details?",
        "Delivery", "Negative", "High", "Pending", "Customer cannot locate an order marked as delivered.",
        "Review the delivery confirmation and investigate where the parcel was left.",
        "We’re sorry you have not been able to find your parcel. Our support team will review the delivery details and follow up with you.", 1),
    _completed("daniel.kim@example.com", "DEMO-4108",
        "I returned my headphones about two weeks ago, and I still cannot see the refund in my account. Please let me know what information you need to check it.",
        "Refund", "Very Negative", "Critical", "In Progress", "Customer reports a refund delay following a returned headphone order.",
        "Verify the return receipt and payment status, then provide a clear update.",
        "We’re sorry this refund is taking longer than expected. Our team will check the return and payment records and update you.", 2),
    _completed("aisha.rahman@example.com", "DEMO-4111",
        "The blender jar arrived with a crack near the handle. I have not used it because I am concerned it could break while blending.",
        "Product", "Very Negative", "Critical", "Pending", "Customer received a cracked blender jar and has not used it due to a safety concern.",
        "Review the product damage promptly and confirm the available support options.",
        "We’re sorry the blender arrived damaged. Please continue not using it while our team reviews the details and next steps.", 3),
    _completed("oliver.chen@example.com", "DEMO-4114",
        "My bank app showed two entries for the same order. One was still pending this morning, so I am not sure whether I have been charged twice.",
        "Payment", "Negative", "High", "In Progress", "Customer is concerned about two payment entries for one order, including a pending entry.",
        "Compare the order payment record with the bank transaction states before advising the customer.",
        "We understand why two payment entries would be concerning. Our team will review the transaction details and explain what we find.", 4),
    _completed("sara.johnson@example.com", None,
        "I cannot sign in even after using the password reset link. The link says it has expired when I open it from the email.",
        "Account", "Negative", "Medium", "In Progress", "Customer cannot access the account because the password reset link appears expired.",
        "Check the account recovery flow and guide the customer through a fresh secure reset.",
        "We’re sorry you are having trouble signing in. Our team will review the reset issue and help you regain access securely.", 5),
    _completed("noah.williams@example.com", "DEMO-4119",
        "The blue phone case I ordered arrived in black. The case itself looks fine, but it is not the colour shown on my order.",
        "Product", "Neutral", "Medium", "Pending", "Customer received a black phone case instead of the blue colour ordered.",
        "Confirm the ordered variant and review the appropriate exchange or return options.",
        "Thanks for letting us know. We’re sorry the colour does not match your order; our team will check the order details and follow up.", 6),
    _completed("maya.patel@example.com", "DEMO-4120",
        "Tracking has shown ‘label created’ for four days. I am leaving town soon and would appreciate an update on whether the parcel has been collected.",
        "Delivery", "Negative", "High", "In Progress", "Shipment tracking has remained at label created for four days.",
        "Check the carrier handoff and provide the most recent shipment information.",
        "We’re sorry the tracking has not moved. Our team will check the carrier handoff and share an update as soon as we can.", 7),
    _completed("daniel.kim@example.com", "DEMO-4125",
        "The backpack stitching came loose after a short time. Support reviewed my photos and explained the return options, and I have no further questions now.",
        "Product", "Neutral", "Medium", "Closed", "Customer reports stitching damage and says the support explanation answered their questions.",
        "Keep the case notes available in case the customer contacts support again.",
        "Thank you for sharing the details and photos. We’re glad the available options were explained; please contact us if you need anything else.", 9),
    _completed("aisha.rahman@example.com", "DEMO-4127",
        "The order page says cancelled, but I can still see a charge listed by my bank. Could you check whether it is a completed charge or a temporary authorization?",
        "Refund", "Neutral", "High", "Pending", "Customer asks about a bank charge for an order marked cancelled.",
        "Check the cancellation and payment state before explaining the transaction to the customer.",
        "We understand your concern about the charge. Our team will verify the order and payment status before providing an update.", 10),
    _completed("oliver.chen@example.com", "DEMO-4130",
        "My payment initially showed as pending, but my bank now shows one completed transaction for the order. I wanted to confirm that the order is moving forward.",
        "Payment", "Neutral", "Low", "Resolved", "Customer requested clarification after a pending payment became one completed transaction.",
        "Confirm the payment and order state in the account record and document the support update.",
        "Thanks for checking with us. Our team will confirm the order status in your account and make sure the information is up to date.", 12),
    _completed("sara.johnson@example.com", "DEMO-4132",
        "The replacement charger arrived on the revised delivery date and works as expected. Thank you for keeping me updated along the way.",
        "Delivery", "Positive", "Low", "Closed", "Customer reports that the replacement charger arrived and expresses satisfaction with the updates.",
        "Record the positive feedback and keep the case closed unless the customer needs more help.",
        "Thank you for the update. We’re glad the charger arrived and that the communication was helpful.", 14),
    _completed("noah.williams@example.com", "DEMO-4138",
        "I have contacted support twice about the same missing accessory, and each time I had to explain the order again. Can the case history be reviewed?",
        "Other", "Very Negative", "High", "In Progress", "Customer reports repeated contact about a missing accessory and wants the case history reviewed.",
        "Review prior case notes and coordinate a single clear follow-up with the customer.",
        "We’re sorry you have had to repeat the details. Our team will review the case history and coordinate the next update.", 16),
    _completed("maya.patel@example.com", "DEMO-4140",
        "The parcel arrived within the estimated window and was packed carefully. I wanted to share that the delivery went smoothly.",
        "Delivery", "Positive", "Low", "Resolved", "Customer shared positive feedback about an on-time delivery and careful packaging.",
        "Record the customer’s feedback for the delivery team.",
        "Thank you for taking the time to share this. We’re glad your delivery went smoothly.", 18),
    _not_analyzed("daniel.kim@example.com", "DEMO-4144",
        "I may have been charged twice for my subscription renewal. The statement has two similar entries, and I need help understanding them.",
        "Pending", "Failed", 20),
    _not_analyzed("aisha.rahman@example.com", "DEMO-4148",
        "The tracking page has not changed since Monday, and the estimated delivery date has passed. Could someone check the shipment?",
        "In Progress", "Failed", 22),
    _not_analyzed("oliver.chen@example.com", None,
        "The help page sent me to an account recovery form that would not submit. I am sending this report so the issue can be reviewed.",
        "Pending", "Pending", 24),
    _not_analyzed("sara.johnson@example.com", "DEMO-4155",
        "I received the wrong size of the item. I have not opened the sealed packaging and would like to know the next steps.",
        "Pending", "Pending", 26),
    _not_analyzed("noah.williams@example.com", "DEMO-4158",
        "The refund page says submitted, but I cannot tell when it was last updated. Could support check the current status?",
        "In Progress", "Pending", 28),
)


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _schema_check(connection: sqlite3.Connection) -> None:
    tables = {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    if not {"users", "complaints"}.issubset(tables):
        raise ValueError("The configured database is not initialized as a PCCSMS database. Run init-db first.")
    required_users = {"id", "name", "email", "password_hash", "role", "is_active"}
    required_complaints = {
        "id", "customer_name", "email", "order_id", "complaint_text", "category", "sentiment",
        "priority", "summary", "recommended_action", "generated_response", "status", "ai_status",
        "ai_model", "ai_analyzed_at", "created_at", "updated_at", "user_id",
    }
    for table, required in (("users", required_users), ("complaints", required_complaints)):
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({_quote_identifier(table)})")}
        if not required.issubset(columns):
            raise ValueError(f"The configured {table} table does not match the PCCSMS schema. No data was changed.")
    dependents = []
    for table in sorted(tables - {"complaints"}):
        references = connection.execute(f"PRAGMA foreign_key_list({_quote_identifier(table)})").fetchall()
        if any(str(row[2]).lower() == "complaints" for row in references):
            dependent_count = connection.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}").fetchone()[0]
            if dependent_count:
                dependents.append(table)
    if dependents:
        raise ValueError("The database has tables with records depending on complaints; refusing to reset those related records: "
                         + ", ".join(dependents))
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise ValueError("The database already has foreign-key violations. No data was changed.")


def _read_demo_accounts(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows: dict[str, sqlite3.Row] = {}
    for customer in DEMO_CUSTOMERS:
        row = connection.execute("SELECT * FROM users WHERE email=?", (normalize_email(customer.email),)).fetchone()
        if row:
            if row["role"] != "customer":
                raise ValueError("A reserved demo email already belongs to a non-customer account. No accounts or complaints were changed.")
            if not row["is_active"]:
                raise ValueError("A reserved demo customer account is inactive. No accounts or complaints were changed.")
            rows[normalize_email(customer.email)] = row
    return rows


def _make_analysis(complaint: DemoComplaint) -> dict[str, str]:
    return validate_analysis({
        "category": complaint.category,
        "sentiment": complaint.sentiment,
        "priority": complaint.priority,
        "summary": complaint.summary,
        "recommended_action": complaint.recommended_action,
        "response": complaint.response,
    })


def _validate_demo_catalog() -> None:
    allowed_statuses = set(STATUSES)
    allowed_ai_statuses = {"Completed", "Pending", "Failed"}
    for item in DEMO_COMPLAINTS:
        if item.customer_email not in {c.email for c in DEMO_CUSTOMERS}:
            raise ValueError("A demo complaint refers to an unknown synthetic customer.")
        if item.status not in allowed_statuses or item.ai_status not in allowed_ai_statuses:
            raise ValueError("A demo record contains an unsupported status.")
        if item.ai_status == "Completed":
            _make_analysis(item)
        elif any(value is not None for value in (
            item.category, item.sentiment, item.priority, item.summary,
            item.recommended_action, item.response,
        )):
            raise ValueError("Pending or failed demo analysis must not include AI result fields.")
        if item.category is not None and item.category not in CATEGORIES:
            raise ValueError("A demo record contains an unsupported category.")
        if item.sentiment is not None and item.sentiment not in SENTIMENTS:
            raise ValueError("A demo record contains an unsupported sentiment.")
        if item.priority is not None and item.priority not in PRIORITIES:
            raise ValueError("A demo record contains an unsupported priority.")


def reset_demo_database(
    database_path: str | Path,
    password_prompt: Callable[[], str],
) -> dict[str, object]:
    """Back up, then atomically replace complaints with owned synthetic records.

    The caller must first require an explicit confirmation flag. If new demo
    customer accounts are needed, ``password_prompt`` must collect a hidden
    password; only Werkzeug hashes are written to SQLite.
    """
    _validate_demo_catalog()
    path = Path(database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError("The configured PCCSMS database file does not exist. No database was created or changed.")

    inspect = sqlite3.connect(path, timeout=10)
    inspect.row_factory = sqlite3.Row
    try:
        _schema_check(inspect)
        existing_accounts = _read_demo_accounts(inspect)
        users_before = {
            int(row["id"]): tuple(row[key] for key in ("name", "email", "password_hash", "role", "is_active", "created_at", "updated_at"))
            for row in inspect.execute("SELECT * FROM users")
        }
        complaints_before = inspect.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        missing_emails = {normalize_email(c.email) for c in DEMO_CUSTOMERS} - set(existing_accounts)
    finally:
        inspect.close()

    password_hashes: dict[str, str] = {}
    if missing_emails:
        demo_password = password_prompt()
        if not isinstance(demo_password, str) or len(demo_password) < 12 or len(demo_password) > 256:
            raise ValueError("Use a demo customer password between 12 and 256 characters. No database data was changed.")
        password_hashes = {email: generate_password_hash(demo_password) for email in missing_emails}
        del demo_password

    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = backup_dir / f"pccsms-before-demo-reset-{stamp}.db"

    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    created_users = 0
    deleted_count = 0
    try:
        connection.execute("BEGIN IMMEDIATE")
        _schema_check(connection)
        accounts_now = _read_demo_accounts(connection)

        # Lock writers first, then take a read-only snapshot for an exact
        # backup of the rows that this transaction is about to replace.
        source = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=10)
        destination = sqlite3.connect(backup_path, timeout=10)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        backup_check = sqlite3.connect(backup_path, timeout=10)
        try:
            if backup_check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("The database backup failed its integrity check. No complaints were deleted.")
            backup_rows = backup_check.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
            if backup_rows != complaints_before:
                raise ValueError("The backup does not contain the expected complaint count. No complaints were deleted.")
        finally:
            backup_check.close()

        # Keep every existing user row and credential unchanged.
        for customer in DEMO_CUSTOMERS:
            email = normalize_email(customer.email)
            if email not in accounts_now:
                if email not in password_hashes:
                    raise ValueError("A demo account changed during setup. Retry the command; no complaint was deleted.")
                connection.execute(
                    "INSERT INTO users (name,email,password_hash,role) VALUES (?,?,?,'customer')",
                    (customer.name, email, password_hashes[email]),
                )
                created_users += 1

        deleted_count = connection.execute("DELETE FROM complaints").rowcount
        if connection.execute("SELECT COUNT(*) FROM complaints").fetchone()[0] != 0:
            raise ValueError("Complaint rows remain after deletion; the transaction will be rolled back.")

        user_ids = {
            normalize_email(row["email"]): row["id"]
            for row in connection.execute("SELECT id,email FROM users")
        }
        now = datetime.now(timezone.utc)
        for index, item in enumerate(DEMO_COMPLAINTS):
            created_at = now - timedelta(days=item.days_ago, hours=(index * 3) % 18)
            updated_at = min(created_at + timedelta(hours=(index % 4) * 2), now)
            values = {
                "customer_name": next(c.name for c in DEMO_CUSTOMERS if c.email == item.customer_email),
                "email": item.customer_email,
                "order_id": item.order_id,
                "complaint_text": item.complaint_text,
                "category": None,
                "sentiment": None,
                "priority": None,
                "summary": None,
                "recommended_action": None,
                "generated_response": None,
                "status": item.status,
                "ai_status": item.ai_status,
                "ai_model": None,
                "ai_analyzed_at": None,
                "created_at": created_at.isoformat(timespec="seconds"),
                "updated_at": updated_at.isoformat(timespec="seconds"),
                "user_id": user_ids[normalize_email(item.customer_email)],
            }
            if item.ai_status == "Completed":
                analysis = _make_analysis(item)
                values.update({
                    "category": analysis["category"],
                    "sentiment": analysis["sentiment"],
                    "priority": analysis["priority"],
                    "summary": analysis["summary"],
                    "recommended_action": analysis["recommended_action"],
                    "generated_response": analysis["response"],
                    "ai_model": DEMO_AI_MODEL,
                    "ai_analyzed_at": values["updated_at"],
                })
            columns = tuple(values)
            connection.execute(
                f"INSERT INTO complaints ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(values[column] for column in columns),
            )

        inserted = connection.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
        if inserted != len(DEMO_COMPLAINTS):
            raise ValueError("The number of inserted demo complaints was unexpected; the transaction will be rolled back.")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError("The new demo records violate a foreign key; the transaction will be rolled back.")

        users_after = {
            int(row["id"]): tuple(row[key] for key in ("name", "email", "password_hash", "role", "is_active", "created_at", "updated_at"))
            for row in connection.execute("SELECT * FROM users")
        }
        if any(users_after.get(user_id) != user_record for user_id, user_record in users_before.items()):
            raise ValueError("An existing user account changed; the transaction will be rolled back.")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

    return {
        "database_path": path,
        "backup_path": backup_path,
        "complaints_deleted": deleted_count,
        "complaints_inserted": len(DEMO_COMPLAINTS),
        "users_preserved": len(users_before),
        "demo_users_created": created_users,
        "demo_users_reused": len(DEMO_CUSTOMERS) - created_users,
        "ai_status_counts": {
            state: sum(1 for item in DEMO_COMPLAINTS if item.ai_status == state)
            for state in ("Completed", "Pending", "Failed")
        },
        "ids_reset": False,
    }


def reset_demo_customer_passwords(database_path: str | Path, new_password: str) -> int:
    """Change only the six reserved demo-customer passwords, storing hashes only."""
    if not isinstance(new_password, str) or len(new_password) < 12 or len(new_password) > 256:
        raise ValueError("Use a demo customer password between 12 and 256 characters. No account was changed.")
    path = Path(database_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    path = path.resolve()
    if not path.is_file():
        raise ValueError("The configured PCCSMS database file does not exist. No account was changed.")

    hashes = {normalize_email(customer.email): generate_password_hash(new_password)
              for customer in DEMO_CUSTOMERS}
    del new_password
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        account_rows = connection.execute(
            "SELECT * FROM users WHERE email IN (" + ",".join("?" for _ in DEMO_CUSTOMERS) + ")",
            tuple(customer.email for customer in DEMO_CUSTOMERS),
        ).fetchall()
        accounts = {normalize_email(row["email"]): row for row in account_rows}
        if len(accounts) != len(DEMO_CUSTOMERS):
            raise ValueError("All six demo customer accounts must exist before resetting their passwords. No account was changed.")
        for row in accounts.values():
            if row["role"] != "customer" or not row["is_active"]:
                raise ValueError("A reserved demo account is not an active customer. No account was changed.")

        before_other_users = {
            int(row["id"]): tuple(row[key] for key in ("name", "email", "password_hash", "role", "is_active", "created_at", "updated_at"))
            for row in connection.execute("SELECT * FROM users")
            if normalize_email(row["email"]) not in hashes
        }
        updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        updated = 0
        for email, password_hash in hashes.items():
            cursor = connection.execute(
                "UPDATE users SET password_hash=?,updated_at=? WHERE email=? AND role='customer' AND is_active=1",
                (password_hash, updated_at, email),
            )
            updated += cursor.rowcount
        if updated != len(DEMO_CUSTOMERS):
            raise ValueError("Not all demo customer passwords were updated. The transaction was rolled back.")

        after_other_users = {
            int(row["id"]): tuple(row[key] for key in ("name", "email", "password_hash", "role", "is_active", "created_at", "updated_at"))
            for row in connection.execute("SELECT * FROM users")
            if normalize_email(row["email"]) not in hashes
        }
        if before_other_users != after_other_users:
            raise ValueError("An unrelated user account changed. The transaction was rolled back.")
        connection.commit()
        return updated
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()

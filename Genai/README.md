# PCCSMS — AI-Powered Customer Complaint & Support Management System

PCCSMS is a Flask and SQLite capstone application for customer complaint intake, Groq-based AI triage, and human support review. It provides a customer portal and a separate administrator/support portal. AI analysis and generated replies are decision-support drafts; support staff retain the final decision and nothing is sent automatically.

## Technology and features

- Python, Flask, Jinja, HTML/CSS, and vanilla JavaScript.
- SQLite with an additive schema upgrade that preserves existing complaints.
- Groq Python SDK for structured category, sentiment, priority, summary, recommended-action, and response analysis.
- Flask-Login sessions and Werkzeug password hashing.
- Flask-WTF CSRF protection for form and AJAX state changes.
- Customers can register, submit complaints, and see only their own complaints and status.
- Administrators can review all new and legacy complaints, update status/priority, retry failed AI analysis, and copy draft responses.
- Complaints are committed before the Groq request; AI failures do not remove them.

## Project map

Use this short map to find the main parts of the project:

```text
Genai/
|-- app.py                 Flask pages, API routes, and command-line tasks
|-- auth.py                Login users and role checks
|-- config.py              App settings loaded from .env
|-- database.py            SQLite reads, writes, and schema setup
|-- schema.sql             Database tables
|-- demo_data.py           Safe demo-data reset helpers
|-- services/
|   `-- ai_service.py      Complaint analysis and response generation
|-- templates/
|   |-- auth/              Sign-in and registration pages
|   |-- admin/             Staff dashboard, queue, and case detail
|   |-- customer/          Customer dashboard, history, account, and detail
|   `-- shared/            Shared layout, complaint form, and error pages
|-- static/
|   |-- css/style.css      Site colors, layout, and responsive design
|   `-- js/                Browser interactions for forms and staff controls
|-- tests/                 Automated checks using temporary databases
`-- instance/              Local SQLite database and its backups
```

### How a complaint moves through the app

1. A Flask route in `app.py` receives the browser request.
2. `database.py` saves or retrieves the complaint.
3. When analysis is needed, `services/ai_service.py` returns the analysis fields.
4. The matching template in `templates/admin/` or `templates/customer/` displays the saved data.

The page folders only organize templates. The URL routes, database format, and complaint workflow stay the same.

## Roles and legacy records

Public registration always creates a `customer`. The role comes from the SQLite user record; submitted form fields and email addresses cannot grant administrator access. The first administrator is created through the `provision-admin` CLI command using `ADMIN_EMAIL` and `ADMIN_PASSWORD` from `.env`. The command is repeatable and never resets an existing admin password.

Existing complaints are migrated with a nullable `user_id`. Old records remain unowned and are visible to administrators; they are never assigned to a customer automatically. Customer queries always filter by the authenticated user ID. Customer detail pages show a limited, clearly labeled AI overview and do not expose the admin-only recommended action or generated-response draft.

## Setup (Windows PowerShell)

Prerequisites: Python 3.10+ and a Groq API key for live analysis. From the project folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally:

```dotenv
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=qwen/qwen3.8-27b
AI_MOCK_MODE=false
FLASK_SECRET_KEY=replace-with-a-long-random-secret
DATABASE_PATH=instance/pccsms.db
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD=use-a-unique-password-at-least-12-characters
SESSION_COOKIE_SECURE=false
```

Use a long random `FLASK_SECRET_KEY` and a unique administrator password. Keep `.env` private; `.gitignore` excludes it. The API key is only loaded by the Flask backend. `SESSION_COOKIE_SECURE=false` is for local HTTP development; enable it behind HTTPS in deployment. `GROQ_MODEL` is configurable and defaults to the value shown above.

## Initialize and provision the first administrator

Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in `.env` first. The provisioning command hashes the password, creates an `admin` role in SQLite, and leaves an existing admin unchanged on repeated runs.

```powershell
.\.venv\Scripts\python.exe -m flask --app app init-db
.\.venv\Scripts\python.exe -m flask --app app provision-admin
```

If the same email already belongs to a customer account, provisioning stops without promoting or changing it; choose a different admin email. The application does not create a default administrator. Customer registration is public and always creates a customer role.

The `init-db` command is safe to run against an existing database. It creates the users table, adds a nullable complaint ownership column when needed, and creates an index. It does not drop/recreate tables, alter existing complaint IDs, or delete complaint data.

## Reset complaints for a capstone demo

The explicit reset command replaces every complaint in the database selected by `DATABASE_PATH` with 18 clearly synthetic, customer-owned demo records. It does not run when Flask starts. Before deleting, it creates and verifies a timestamped SQLite backup in a `backups` folder next to the configured database file. With the current project setting, that folder is `instance/backups/`. It then replaces the complaints in one transaction. It leaves all existing accounts and credentials unchanged and does not reset SQLite's complaint ID sequence. If a table contains rows that depend on complaints, the command refuses to continue rather than deleting related data unexpectedly.

From the project folder, review the displayed target database and run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app reset-demo-data --confirm-reset
```

The flag is required; without it the command refuses to delete anything. If one or more demo customer accounts need to be created, the command asks twice for a shared demo-only password using hidden terminal input. It stores only password hashes. Newly created demo accounts use `example.com` addresses and receive owned complaints; accounts that already exist are reused without changing their roles, active state, password, or other fields. If a reserved demo email belongs to an administrator or an inactive account, the reset is refused before the backup or deletion.

The 18 seeded records include completed, pending, and failed analysis states. Completed records use locally authored synthetic values, marked `Synthetic demo` in the database and labeled on both customer and administrator complaint-detail pages; no Groq call is made. Pending and failed records have no AI result fields. The example customers are Maya Patel, Daniel Kim, Aisha Rahman, Oliver Chen, Sara Johnson, and Noah Williams, with `@example.com` addresses. Any generated response remains a draft for human review.

The older `seed.py` entry point now delegates to this same protected command and also requires `--confirm-reset`:

```powershell
.\.venv\Scripts\python.exe seed.py --confirm-reset
```

Backups are ignored by Git. Keep or copy a backup before a later reset if you need to retain that recovery point.

To change the shared password for the six demo customer accounts without changing the administrator or complaint records, run:

```powershell
.\.venv\Scripts\python.exe -m flask --app app reset-demo-customer-password --confirm
```

The command verifies all six reserved accounts are active customers, then asks twice for the new password using hidden terminal input. It requires at least 12 characters, updates only those six salted password hashes in one transaction, and never displays or stores the plaintext password. No complaint data or administrator credentials are changed.

## Run PCCSMS

```powershell
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:5000`. Customers use **Create a customer account** on the login page. Admins sign in with the provisioned account. The root route sends admins to the global dashboard and customers to their own dashboard. Stop the local server with Ctrl+C.

To use the local deterministic analyzer without Groq, set `AI_MOCK_MODE=true`. Keep it `false` to use the configured Groq model. Missing credentials or API errors leave complaints saved with failed AI status so an administrator can retry.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

Tests use temporary SQLite databases and mocked/deterministic AI. They cover registration and password hashing, role-based redirects, inactive accounts, CSRF, session logout, admin provisioning, customer ownership/IDOR protections, legacy migration, complaint persistence on AI failure, admin status/priority/retry, and existing AI validation.

## Main routes

- `/login`, `/register`, `/logout`
- `/customer`, `/customer/complaints`, `/customer/complaints/new`, `/customer/complaints/<id>`, `/customer/account`
- `/` (administrator dashboard), `/complaints`, `/complaints/new`, `/complaints/<id>` (administrator/support only)
- `/api/complaints` (authenticated; customer ownership is derived from the session)
- `/api/complaints/<id>/status`, `/priority`, and `/analyze` (administrator only)

The database remains the source of truth for account role, complaint ownership, status, and AI analysis. CSRF tokens are required for mutating browser actions. Session cookies are HTTP-only and SameSite=Lax; pages use no-store caching headers.

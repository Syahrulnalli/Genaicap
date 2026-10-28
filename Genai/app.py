import logging
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import click
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_user, logout_user, login_required
from flask_wtf.csrf import CSRFError, CSRFProtect
from werkzeug.security import check_password_hash, generate_password_hash

import database
from auth import User, admin_required, customer_required, login_manager
from config import Config
from demo_data import reset_demo_customer_passwords, reset_demo_database
from services.ai_service import AIAnalysisError, analyze_complaint

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
csrf = CSRFProtect()


def _safe_next(value):
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not value.startswith("/") or value.startswith("//"):
        return None
    return value


def _portal_url(user):
    return url_for("dashboard") if user.role == "admin" else url_for("customer_dashboard")


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    app.teardown_appcontext(database.close_db)
    login_manager.init_app(app)
    login_manager.login_view = "login"
    login_manager.login_message = "Please sign in to continue."
    csrf.init_app(app)
    logger.info("PCCSMS application initialized")

    @app.after_request
    def prevent_private_page_caching(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.template_filter("datetime")
    def format_datetime(value):
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed.strftime("%d %b %Y, %I:%M %p")
        except (TypeError, ValueError):
            return value or "—"

    @app.cli.command("init-db")
    def init_db_command():
        database.init_db()
        click.echo("Initialized or upgraded PCCSMS database. Existing complaint rows were preserved.")

    @app.cli.command("reset-demo-data")
    @click.option("--confirm-reset", is_flag=True, help="Confirm replacement of all complaint records in the configured PCCSMS database.")
    def reset_demo_data_command(confirm_reset):
        if not confirm_reset:
            raise click.ClickException("Refusing to delete complaints without --confirm-reset.")
        configured_path = Path(app.config["DATABASE_PATH"])
        target_path = (configured_path if configured_path.is_absolute() else Path.cwd() / configured_path).resolve()
        click.echo(f"Target database: {target_path}")

        def prompt_demo_password():
            return click.prompt(
                "Set a shared password for newly created demo customer accounts (12+ characters)",
                hide_input=True,
                confirmation_prompt=True,
            )

        try:
            result = reset_demo_database(target_path, prompt_demo_password)
        except (ValueError, sqlite3.Error, OSError) as exc:
            raise click.ClickException(str(exc)) from None
        click.echo(f"Backup created: {result['backup_path']}")
        click.echo(f"Complaints deleted: {result['complaints_deleted']}")
        click.echo(f"Demo complaints inserted: {result['complaints_inserted']}")
        click.echo(f"Existing user accounts preserved: {result['users_preserved']}")
        click.echo(f"Demo customer accounts created: {result['demo_users_created']}; reused: {result['demo_users_reused']}")
        counts = result["ai_status_counts"]
        click.echo(f"Synthetic demo analysis states: Completed={counts['Completed']}, Pending={counts['Pending']}, Failed={counts['Failed']}")
        click.echo("Complaint ID sequence was preserved; it was not reset.")

    @app.cli.command("reset-demo-customer-password")
    @click.option("--confirm", is_flag=True, help="Confirm updating passwords for the six reserved demo customer accounts.")
    def reset_demo_customer_password_command(confirm):
        if not confirm:
            raise click.ClickException("Refusing to change demo customer passwords without --confirm.")
        configured_path = Path(app.config["DATABASE_PATH"])
        target_path = (configured_path if configured_path.is_absolute() else Path.cwd() / configured_path).resolve()
        click.echo(f"Target database: {target_path}")
        new_password = click.prompt(
            "Set a new shared password for the six demo customer accounts (12+ characters)",
            hide_input=True,
            confirmation_prompt=True,
        )
        try:
            updated = reset_demo_customer_passwords(target_path, new_password)
        except (ValueError, sqlite3.Error, OSError) as exc:
            raise click.ClickException(str(exc)) from None
        finally:
            new_password = ""
        click.echo(f"Reset the password hashes for {updated} demo customer accounts. No plaintext password was stored or displayed.")

    @app.cli.command("provision-admin")
    def provision_admin_command():
        email = database.normalize_email(app.config.get("ADMIN_EMAIL"))
        password = app.config.get("ADMIN_PASSWORD") or ""
        if not email or not EMAIL_RE.fullmatch(email) or len(password) < 12:
            raise click.ClickException("Set a valid ADMIN_EMAIL and an ADMIN_PASSWORD of at least 12 characters in .env, then run this command again.")
        database.init_db()
        existing = database.get_user_by_email(email)
        if existing:
            if existing["role"] != "admin":
                raise click.ClickException("That email already belongs to a customer account. Choose a different ADMIN_EMAIL; no account was changed.")
            click.echo("Administrator already exists; its password and account were left unchanged.")
            return
        database.create_user("Administrator", email, generate_password_hash(password), role="admin")
        click.echo(f"Administrator account provisioned for {email}.")

    @app.get("/login")
    @app.post("/login")
    def login():
        if current_user.is_authenticated:
            return redirect(_portal_url(current_user))
        if request.method == "GET":
            return render_template("auth/login.html", next_url=_safe_next(request.args.get("next")))
        email = database.normalize_email(request.form.get("email"))
        password = request.form.get("password", "")
        user_record = database.get_user_by_email(email)
        try:
            valid_password = bool(user_record and check_password_hash(user_record["password_hash"], password))
        except (ValueError, TypeError):
            valid_password = False
        if not valid_password:
            flash("Email or password is incorrect.", "error")
            return render_template("auth/login.html", next_url=_safe_next(request.form.get("next"))), 401
        if not user_record["is_active"]:
            flash("This account is inactive. Contact support for help.", "error")
            return render_template("auth/login.html"), 403
        user = User.from_record(user_record)
        session.clear()
        login_user(user, remember=False, fresh=True)
        return redirect(_safe_next(request.form.get("next")) or _portal_url(user))

    @app.get("/register")
    @app.post("/register")
    def register():
        if current_user.is_authenticated:
            return redirect(_portal_url(current_user))
        if request.method == "GET":
            return render_template("auth/register.html")
        name = request.form.get("name", "").strip()
        email = database.normalize_email(request.form.get("email"))
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")
        errors = {}
        if not name or len(name) > 100:
            errors["name"] = "Enter your name (up to 100 characters)."
        if not EMAIL_RE.fullmatch(email) or len(email) > 254:
            errors["email"] = "Enter a valid email address."
        if len(password) < 8 or len(password) > 256:
            errors["password"] = "Use a password between 8 and 256 characters."
        if password != confirm:
            errors["confirm_password"] = "Passwords do not match."
        if email and database.get_user_by_email(email):
            errors["email"] = "An account with this email already exists. Sign in instead."
        if errors:
            return render_template("auth/register.html", errors=errors, name=name, email=email), 400
        try:
            database.create_user(name, email, generate_password_hash(password), role="customer")
        except sqlite3.IntegrityError:
            return render_template("auth/register.html", errors={"email": "An account with this email already exists. Sign in instead."}, name=name, email=email), 400
        except Exception:
            logger.exception("Unable to create customer account")
            flash("We could not create your account. Please try again.", "error")
            return render_template("auth/register.html", name=name, email=email), 500
        flash("Your account is ready. Sign in to continue.", "success")
        return redirect(url_for("login"))

    @app.post("/logout")
    @login_required
    def logout():
        logout_user()
        session.clear()
        flash("You have been signed out.", "success")
        return redirect(url_for("login"))

    @login_manager.unauthorized_handler
    def unauthorized():
        if request.path.startswith("/api/"):
            return jsonify(success=False, error="Please sign in to continue."), 401
        return redirect(url_for("login", next=request.full_path if request.query_string else request.path))

    @app.get("/")
    @login_required
    def dashboard():
        if current_user.role != "admin":
            return redirect(url_for("customer_dashboard"))
        return render_template("admin/dashboard.html", stats=database.get_dashboard_stats(), recent=database.get_complaints(limit=8))

    @app.get("/customer")
    @customer_required
    def customer_dashboard():
        stats = database.get_customer_stats(current_user.id)
        recent = database.get_complaints(user_id=current_user.id, limit=8)
        return render_template("customer/dashboard.html", stats=stats, recent=recent)

    @app.get("/customer/account")
    @customer_required
    def customer_account():
        return render_template("customer/account.html")

    @app.get("/customer/complaints")
    @customer_required
    def customer_complaints():
        filters = {key: request.args.get(key, "").strip() for key in ("q", "category", "status")}
        page, per_page = max(1, request.args.get("page", 1, type=int)), 10
        args = {"search": filters["q"], "category": filters["category"], "status": filters["status"], "user_id": current_user.id}
        total = database.count_complaints(**args)
        rows = database.get_complaints(**args, limit=per_page, offset=(page - 1) * per_page)
        return render_template("customer/complaints.html", complaints=rows, filters=filters, page=page,
                               pages=max(1, math.ceil(total / per_page)), total=total)

    @app.get("/customer/complaints/<int:complaint_id>")
    @customer_required
    def customer_complaint_detail(complaint_id):
        record = database.get_complaint(complaint_id, user_id=current_user.id)
        if record is None:
            abort(404)
        return render_template("customer/complaint_detail.html", complaint=record)

    @app.get("/customer/complaints/new")
    @customer_required
    def customer_submit_page():
        return render_template("shared/submit.html", customer_mode=True)

    @app.get("/complaints/new")
    @admin_required
    def submit_page():
        return render_template("shared/submit.html", customer_mode=False)

    @app.get("/complaints")
    @admin_required
    def complaints():
        filters = {key: request.args.get(key, "").strip() for key in ("q", "category", "priority", "status", "sentiment")}
        page, per_page = max(1, request.args.get("page", 1, type=int)), 10
        args = {"search": filters["q"], **{key: filters[key] for key in ("category", "priority", "status", "sentiment")}}
        total = database.count_complaints(**args)
        rows = database.get_complaints(**args, limit=per_page, offset=(page - 1) * per_page)
        return render_template("admin/complaints.html", complaints=rows, filters=filters, page=page,
                               pages=max(1, math.ceil(total / per_page)), total=total)

    @app.get("/complaints/<int:complaint_id>")
    @admin_required
    def complaint_detail(complaint_id):
        record = database.get_complaint(complaint_id)
        if record is None:
            return render_template("shared/404.html"), 404
        return render_template("admin/complaint_detail.html", complaint=record)

    @app.post("/api/complaints")
    @login_required
    def create_complaint():
        data = request.get_json(silent=True) if request.is_json else request.form
        data = data or {}
        if current_user.role == "customer":
            cleaned = {"customer_name": current_user.name, "email": current_user.email,
                       "order_id": str(data.get("order_id", "")).strip(), "phone": "",
                       "complaint_text": str(data.get("complaint_text", "")).strip()}
            owner_id = current_user.id
        elif current_user.role == "admin":
            cleaned = {key: str(data.get(key, "")).strip() for key in ("customer_name", "email", "order_id", "phone", "complaint_text")}
            owner_id = None
        else:
            abort(403)
        errors = {}
        if not cleaned["customer_name"] or len(cleaned["customer_name"]) > 100:
            errors["customer_name"] = "Enter a name (up to 100 characters)."
        if not EMAIL_RE.fullmatch(cleaned["email"]) or len(cleaned["email"]) > 254:
            errors["email"] = "Enter a valid email address."
        if len(cleaned["order_id"]) > 80 or len(cleaned["phone"]) > 40:
            errors["contact"] = "Order ID or phone number is too long."
        if len(cleaned["complaint_text"]) < 15 or len(cleaned["complaint_text"]) > 5000:
            errors["complaint_text"] = "Describe the issue in 15 to 5,000 characters."
        if errors:
            return jsonify(success=False, error="Please correct the highlighted fields.", errors=errors), 400
        try:
            record = database.create_complaint(cleaned, user_id=owner_id)
        except Exception:
            logger.exception("Unable to save complaint")
            return jsonify(success=False, error="We could not save your complaint. Please try again."), 500
        try:
            analysis = analyze_complaint(cleaned["complaint_text"])
            model = "mock" if app.config.get("AI_MOCK_MODE") else app.config.get("GROQ_MODEL")
            record = database.update_ai_analysis(record["id"], analysis, model)
            ai_message = None
        except AIAnalysisError as exc:
            database.mark_ai_failed(record["id"])
            logger.info("AI analysis unavailable for complaint %s", record["id"])
            record, ai_message = database.get_complaint(record["id"]), str(exc)
        destination = url_for("customer_complaint_detail", complaint_id=record["id"]) if current_user.role == "customer" else url_for("complaint_detail", complaint_id=record["id"])
        return jsonify(success=True, data={"id": record["id"], "url": destination,
                                          "ai_status": record["ai_status"], "ai_message": ai_message}), 201

    @app.get("/api/complaints/<int:complaint_id>")
    @admin_required
    def complaint_json(complaint_id):
        record = database.get_complaint(complaint_id)
        if record is None:
            return jsonify(success=False, error="Complaint not found."), 404
        return jsonify(success=True, data=dict(record))

    @app.post("/api/complaints/<int:complaint_id>/status")
    @admin_required
    def update_status(complaint_id):
        if database.get_complaint(complaint_id) is None:
            return jsonify(success=False, error="Complaint not found."), 404
        data = request.get_json(silent=True) or request.form
        status = str(data.get("status", "")).strip()
        if status not in database.STATUSES:
            return jsonify(success=False, error="Choose a valid complaint status."), 400
        record = database.update_complaint_status(complaint_id, status)
        return jsonify(success=True, data={"status": record["status"]})

    @app.post("/api/complaints/<int:complaint_id>/priority")
    @admin_required
    def update_priority(complaint_id):
        if database.get_complaint(complaint_id) is None:
            return jsonify(success=False, error="Complaint not found."), 404
        data = request.get_json(silent=True) or request.form
        priority = str(data.get("priority", "")).strip()
        if priority not in database.PRIORITIES:
            return jsonify(success=False, error="Choose a valid priority."), 400
        record = database.update_complaint_priority(complaint_id, priority)
        return jsonify(success=True, data={"priority": record["priority"]})

    @app.post("/api/complaints/<int:complaint_id>/analyze")
    @admin_required
    def retry_analysis(complaint_id):
        record = database.get_complaint(complaint_id)
        if record is None:
            return jsonify(success=False, error="Complaint not found."), 404
        try:
            analysis = analyze_complaint(record["complaint_text"])
            model = "mock" if app.config.get("AI_MOCK_MODE") else app.config.get("GROQ_MODEL")
            updated = database.update_ai_analysis(complaint_id, analysis, model)
        except AIAnalysisError as exc:
            database.mark_ai_failed(complaint_id)
            return jsonify(success=False, error=str(exc)), 503
        return jsonify(success=True, data={"ai_status": updated["ai_status"], "url": url_for("complaint_detail", complaint_id=complaint_id)})

    @app.get("/api/dashboard/stats")
    @admin_required
    def dashboard_stats():
        return jsonify(success=True, data=database.get_dashboard_stats())

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        if request.path.startswith("/api/"):
            return jsonify(success=False, error="Your session expired. Refresh the page and try again."), 400
        return render_template("shared/error.html", message="Your session expired. Refresh the page and try again."), 400

    @app.errorhandler(403)
    def forbidden(_error):
        if request.path.startswith("/api/"):
            return jsonify(success=False, error="You do not have permission to do that."), 403
        return render_template("shared/error.html", message="You do not have permission to view this page."), 403

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify(success=False, error="The requested resource was not found."), 404
        return render_template("shared/404.html"), 404

    @app.errorhandler(413)
    def too_large(_error):
        if request.path.startswith("/api/"):
            return jsonify(success=False, error="Request is too large. Please shorten the complaint."), 413
        return render_template("shared/error.html", message="Request is too large. Please shorten the complaint."), 413

    @app.errorhandler(500)
    def server_error(_error):
        logger.exception("Unhandled server error")
        if request.path.startswith("/api/"):
            return jsonify(success=False, error="An unexpected error occurred. Please try again."), 500
        return render_template("shared/error.html", message="An unexpected error occurred. Please try again."), 500

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", False))

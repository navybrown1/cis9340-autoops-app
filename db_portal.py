import math
import os
import time
from decimal import Decimal, InvalidOperation
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse

import pymysql
from flask import Flask, abort, current_app, flash, g, redirect, render_template, request, session, url_for
from pymysql.cursors import DictCursor
from werkzeug.security import check_password_hash

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional local convenience only
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent
if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env", override=False)

DEFAULT_DATABASE = os.getenv("MYSQL_DATABASE", "cis9340_physical_database")
DEFAULT_USER = os.getenv("MYSQL_USER", "root")
DEFAULT_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
DEFAULT_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
DEFAULT_PORT = int(os.getenv("MYSQL_PORT", "3306"))
DEFAULT_SOCKET = os.getenv("MYSQL_SOCKET", "/tmp/mysql.sock")
DEFAULT_SSL_MODE = os.getenv("MYSQL_SSL_MODE", "DISABLED").upper()
DEFAULT_SSL_CA = os.getenv("MYSQL_SSL_CA", "")
DEFAULT_CONNECT_TIMEOUT = int(os.getenv("MYSQL_CONNECT_TIMEOUT", "10"))
DEFAULT_SERVER_LABEL = os.getenv(
    "MYSQL_SERVER_LABEL",
    "Local MySQL 8.0" if DEFAULT_HOST in {"127.0.0.1", "localhost"} else "Azure MySQL Flexible Server",
)

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_FRONTDESK = "frontdesk"
ROLE_MECHANIC = "mechanic"
ROLE_ANALYST = "analyst"
ROLE_CHOICES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_FRONTDESK, ROLE_MECHANIC, ROLE_ANALYST}


def create_app():
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or "dev-secret-key-change-me"
    app.config["AUTH_ENABLED"] = env_flag("AUTH_ENABLED", default=False)
    app.config["OPS_WRITE_ENABLED"] = env_flag("OPS_WRITE_ENABLED", default=False)

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("mysql_db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def inject_globals():
        auth_on = current_app.config.get("AUTH_ENABLED", False)
        current_user = get_current_session_user()
        current_role = current_user["role"] if current_user else None
        nav_items = build_nav_items(auth_on, current_role)
        sidebar_cta = build_sidebar_cta(auth_on, current_role)
        return {
            "database_name": DEFAULT_DATABASE,
            "server_label": DEFAULT_SERVER_LABEL,
            "connection_target": get_connection_target(),
            "search_action": url_for("catalog") if is_studio_request() else url_for("ops_dashboard"),
            "search_placeholder": "Search tables, views, or saved queries"
            if is_studio_request()
            else "Search workflows and operational pages",
            "auth_enabled": auth_on,
            "is_authenticated": bool(current_user),
            "current_user": current_user,
            "current_user_name": (current_user["display_name"] if current_user else "Studio User"),
            "current_user_initials": initials_for_name(current_user["display_name"] if current_user else "Studio User"),
            "current_user_role": current_role,
            "nav_items": nav_items,
            "sidebar_cta": sidebar_cta,
            "show_sidebar": request.endpoint != "login",
        }

    @app.route("/")
    def root():
        if current_app.config.get("AUTH_ENABLED", False):
            if not get_current_session_user():
                return redirect(url_for("login", next=request.path))
            return redirect(url_for("app_home"))
        return render_studio_dashboard()

    @app.route("/app")
    @login_required
    def app_home():
        role = current_user_role()
        if role == ROLE_ADMIN:
            return redirect(url_for("dashboard"))
        if role in {ROLE_MANAGER, ROLE_FRONTDESK, ROLE_MECHANIC, ROLE_ANALYST}:
            return redirect(url_for("ops_dashboard"))
        return redirect(url_for("unauthorized"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not current_app.config.get("AUTH_ENABLED", False):
            flash("Authentication is disabled for this deployment.", "info")
            return redirect(url_for("root"))

        next_target = safe_next_url(request.values.get("next")) or url_for("app_home")
        if request.method == "POST":
            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""
            user, error_message = authenticate_user(get_db(), username, password)
            if user:
                set_current_session_user(user)
                flash("Signed in successfully.", "success")
                return redirect(next_target)
            flash(error_message or "Invalid username or password.", "danger")

        return render_template(
            "login.html",
            active_page="login",
            page_title="Sign in",
            next_target=next_target,
            hide_topbar=True,
            show_sidebar=False,
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        if current_app.config.get("AUTH_ENABLED", False):
            flash("Signed out.", "success")
            return redirect(url_for("login"))
        return redirect(url_for("root"))

    @app.route("/unauthorized")
    @login_required
    def unauthorized():
        return render_template("unauthorized.html", active_page="", page_title="Unauthorized")

    @app.route("/dashboard")
    @app.route("/studio")
    @app.route("/studio/dashboard")
    @roles_required(ROLE_ADMIN)
    def dashboard():
        return render_studio_dashboard()

    @app.route("/ops/dashboard")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_FRONTDESK, ROLE_MECHANIC, ROLE_ANALYST)
    def ops_dashboard():
        db = get_db()
        payload = build_ops_dashboard_data(db)
        return render_template(
            "ops_dashboard.html",
            active_page="ops_dashboard",
            page_title="Operations Dashboard",
            metrics=payload["metrics"],
            backlog=payload["backlog"],
            sales=payload["sales"],
            alerts=payload["alerts"],
            reports=payload["reports"],
        )

    @app.route("/ops/customers", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_FRONTDESK)
    def ops_customers():
        db = get_db()
        writes_enabled = current_app.config.get("OPS_WRITE_ENABLED", False)
        search_query = (request.values.get("q") or "").strip()
        if request.method == "POST":
            if not writes_enabled:
                flash("Customer creation is disabled. Set OPS_WRITE_ENABLED=true to allow writes.", "danger")
                return redirect(url_for("ops_customers", q=search_query))
            payload = {
                "first_name": (request.form.get("first_name") or "").strip(),
                "last_name": (request.form.get("last_name") or "").strip(),
                "dob": (request.form.get("dob") or "").strip() or None,
                "address": (request.form.get("address") or "").strip() or None,
                "phone": (request.form.get("phone") or "").strip() or None,
                "email": (request.form.get("email") or "").strip() or None,
            }
            created_id, error = create_customer_record(db, payload)
            if error:
                flash(error, "danger")
            else:
                flash(f"Customer {created_id} created successfully.", "success")
                return redirect(url_for("ops_customers"))

        customers = search_customers(db, search_query)
        return render_template(
            "ops_customers.html",
            active_page="ops_customers",
            page_title="Customers",
            customers=customers,
            search_query=search_query,
            writes_enabled=writes_enabled,
        )

    @app.route("/ops/appointments", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_FRONTDESK, ROLE_MECHANIC)
    def ops_appointments():
        db = get_db()
        writes_enabled = current_app.config.get("OPS_WRITE_ENABLED", False)
        if request.method == "POST":
            if not writes_enabled:
                flash("Appointment scheduling is disabled. Set OPS_WRITE_ENABLED=true to allow writes.", "danger")
                return redirect(url_for("ops_appointments"))
            payload = {
                "customer_id": request.form.get("customer_id"),
                "car_id": request.form.get("car_id"),
                "branch_id": request.form.get("branch_id"),
                "date": (request.form.get("date") or "").strip(),
                "time": (request.form.get("time") or "").strip(),
                "appointment_type": (request.form.get("appointment_type") or "").strip(),
                "status": (request.form.get("status") or "Scheduled").strip(),
                "employee_id": request.form.get("employee_id"),
            }
            appointment_id, error = create_appointment_record(db, payload)
            if error:
                flash(error, "danger")
            else:
                flash(f"Appointment {appointment_id} scheduled.", "success")
                return redirect(url_for("ops_appointments"))

        appointments = safe_rows_query(
            db,
            """
            SELECT
                a.appointment_ID,
                a.date,
                a.time,
                a.appointment_type,
                a.status,
                a.branch_ID,
                a.customer_ID,
                CONCAT(cp.first_name, ' ', cp.last_name) AS customer_name,
                a.employee_ID
            FROM APPOINTMENT a
            LEFT JOIN vw_customer_profile cp ON a.customer_ID = cp.customer_ID
            ORDER BY a.date DESC, a.time DESC
            LIMIT 30
            """,
        )
        customers = safe_rows_query(
            db,
            """
            SELECT customer_ID, CONCAT(first_name, ' ', last_name) AS customer_name
            FROM vw_customer_profile
            ORDER BY first_name, last_name
            LIMIT 200
            """,
        )
        cars = safe_rows_query(
            db,
            """
            SELECT product_ID, CONCAT(make, ' ', model, ' (', year, ')') AS car_label
            FROM CAR
            ORDER BY make, model, year
            LIMIT 200
            """,
        )
        branches = safe_rows_query(
            db,
            """
            SELECT branch_ID, address
            FROM BRANCH
            ORDER BY branch_ID
            """,
        )
        employees = safe_rows_query(
            db,
            """
            SELECT employee_ID, CONCAT(first_name, ' ', last_name, ' - ', role) AS employee_label
            FROM vw_employee_profile
            ORDER BY first_name, last_name
            LIMIT 200
            """,
        )
        return render_template(
            "ops_appointments.html",
            active_page="ops_appointments",
            page_title="Appointments",
            appointments=appointments,
            customers=customers,
            cars=cars,
            branches=branches,
            employees=employees,
            writes_enabled=writes_enabled,
        )

    @app.route("/ops/repairs", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_MECHANIC)
    def ops_repairs():
        db = get_db()
        writes_enabled = current_app.config.get("OPS_WRITE_ENABLED", False)
        action = (request.form.get("action") or "").strip()
        if request.method == "POST":
            if not writes_enabled:
                flash("Repair updates are disabled. Set OPS_WRITE_ENABLED=true to allow writes.", "danger")
                return redirect(url_for("ops_repairs"))
            if action == "create_repair":
                payload = {
                    "appointment_id": request.form.get("appointment_id"),
                    "employee_id": request.form.get("employee_id"),
                    "status": (request.form.get("status") or "In Progress").strip(),
                    "cost": request.form.get("cost"),
                }
                repair_id, error = create_repair_record(db, payload)
                if error:
                    flash(error, "danger")
                else:
                    flash(f"Repair {repair_id} created successfully.", "success")
                    return redirect(url_for("ops_repairs"))
            elif action == "update_repair":
                payload = {
                    "repair_id": request.form.get("repair_id"),
                    "status": (request.form.get("status") or "").strip(),
                    "cost": request.form.get("cost"),
                    "employee_id": request.form.get("employee_id"),
                }
                error = update_repair_record(db, payload)
                if error:
                    flash(error, "danger")
                else:
                    flash(f"Repair {payload.get('repair_id')} updated.", "success")
                    return redirect(url_for("ops_repairs"))

        queue_rows = safe_rows_query(
            db,
            """
            SELECT
                r.repair_ID,
                r.status,
                r.cost,
                a.appointment_ID,
                a.date AS appointment_date,
                a.time AS appointment_time,
                a.appointment_type,
                a.branch_ID,
                a.customer_ID,
                CONCAT(cp.first_name, ' ', cp.last_name) AS customer_name,
                r.employee_ID,
                CONCAT(ep.first_name, ' ', ep.last_name) AS mechanic_name
            FROM REPAIR r
            JOIN APPOINTMENT a ON r.appointment_ID = a.appointment_ID
            LEFT JOIN vw_customer_profile cp ON a.customer_ID = cp.customer_ID
            LEFT JOIN vw_employee_profile ep ON r.employee_ID = ep.employee_ID
            ORDER BY
                CASE r.status WHEN 'In Progress' THEN 0 WHEN 'On Hold' THEN 1 ELSE 2 END,
                a.date DESC,
                a.time DESC
            LIMIT 40
            """,
        )
        unassigned_appointments = safe_rows_query(
            db,
            """
            SELECT
                a.appointment_ID,
                a.date,
                a.time,
                a.appointment_type,
                a.branch_ID,
                CONCAT(cp.first_name, ' ', cp.last_name) AS customer_name
            FROM APPOINTMENT a
            LEFT JOIN REPAIR r ON a.appointment_ID = r.appointment_ID
            LEFT JOIN vw_customer_profile cp ON a.customer_ID = cp.customer_ID
            WHERE r.repair_ID IS NULL
              AND a.status IN ('Scheduled', 'Confirmed', 'In Progress', 'Completed')
            ORDER BY a.date DESC, a.time DESC
            LIMIT 40
            """,
        )
        mechanics = safe_rows_query(
            db,
            """
            SELECT employee_ID, CONCAT(first_name, ' ', last_name, ' - ', role) AS employee_label
            FROM vw_employee_profile
            WHERE role LIKE '%Mechanic%'
               OR role LIKE '%Manager%'
            ORDER BY first_name, last_name
            LIMIT 200
            """,
        )
        return render_template(
            "ops_repairs.html",
            active_page="ops_repairs",
            page_title="Repairs",
            queue_rows=queue_rows,
            unassigned_appointments=unassigned_appointments,
            mechanics=mechanics,
            writes_enabled=writes_enabled,
        )

    @app.route("/ops/sales", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_FRONTDESK)
    def ops_sales():
        db = get_db()
        writes_enabled = current_app.config.get("OPS_WRITE_ENABLED", False)
        if request.method == "POST":
            if not writes_enabled:
                flash("Sales recording is disabled. Set OPS_WRITE_ENABLED=true to allow writes.", "danger")
                return redirect(url_for("ops_sales"))
            payload = {
                "branch_id": request.form.get("branch_id"),
                "customer_id": request.form.get("customer_id"),
                "date": (request.form.get("date") or "").strip(),
                "time": (request.form.get("time") or "").strip(),
                "delivery_method": (request.form.get("delivery_method") or "").strip() or None,
                "product_id": request.form.get("product_id"),
                "quantity": request.form.get("quantity"),
                "unit_price": request.form.get("unit_price"),
            }
            sale_id, error = create_sale_record(db, payload)
            if error:
                flash(error, "danger")
            else:
                flash(f"Sale {sale_id} recorded successfully.", "success")
                return redirect(url_for("ops_sales"))

        branch_options = safe_rows_query(
            db,
            """
            SELECT branch_ID, address
            FROM BRANCH
            ORDER BY branch_ID
            """,
        )
        customer_options = safe_rows_query(
            db,
            """
            SELECT customer_ID, CONCAT(first_name, ' ', last_name) AS customer_name
            FROM vw_customer_profile
            ORDER BY first_name, last_name
            LIMIT 200
            """,
        )
        product_options = load_product_options(db)
        sales_rows = safe_rows_query(
            db,
            """
            SELECT sale_ID, sale_date, customer_name, product_description, quantity, unit_price, line_total
            FROM vw_sale_detail
            ORDER BY sale_date DESC, sale_ID DESC
            LIMIT 40
            """,
        )
        return render_template(
            "ops_sales.html",
            active_page="ops_sales",
            page_title="Sales",
            branch_options=branch_options,
            customer_options=customer_options,
            product_options=product_options,
            sales_rows=sales_rows,
            writes_enabled=writes_enabled,
        )

    @app.route("/ops/inventory")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_MECHANIC)
    def ops_inventory():
        db = get_db()
        branch_filter = (request.args.get("branch_id") or "").strip()
        if branch_filter:
            rows = safe_rows_query(
                db,
                """
                SELECT branch_ID, branch_address, product_ID, product_type, description, quantity_in_inventory, reorder_level, stock_status
                FROM vw_branch_inventory
                WHERE branch_ID = %s
                ORDER BY stock_status DESC, quantity_in_inventory ASC, product_ID ASC
                LIMIT 200
                """,
                (branch_filter,),
            )
        else:
            rows = safe_rows_query(
                db,
                """
                SELECT branch_ID, branch_address, product_ID, product_type, description, quantity_in_inventory, reorder_level, stock_status
                FROM vw_branch_inventory
                ORDER BY stock_status DESC, quantity_in_inventory ASC, branch_ID ASC
                LIMIT 300
                """,
            )
        branches = safe_rows_query(
            db,
            """
            SELECT branch_ID, address
            FROM BRANCH
            ORDER BY branch_ID
            """,
        )
        return render_template(
            "ops_inventory.html",
            active_page="ops_inventory",
            page_title="Inventory",
            rows=rows,
            branches=branches,
            branch_filter=branch_filter,
        )

    @app.route("/reports/overview")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_ANALYST)
    def reports_overview():
        db = get_db()
        data = build_reports_overview_data(db)
        return render_template(
            "reports_overview.html",
            active_page="reports_overview",
            page_title="Reports Overview",
            kpis=data["kpis"],
            top_branches=data["top_branches"],
            repair_status=data["repair_status"],
            inventory_alerts=data["inventory_alerts"],
        )

    @app.route("/reports/branches")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_ANALYST)
    def reports_branches():
        db = get_db()
        rows = safe_rows_query(
            db,
            """
            SELECT
                b.branch_ID,
                b.address AS branch_address,
                COUNT(DISTINCT s.sale_ID) AS sale_count,
                COALESCE(SUM(s.total_amount), 0) AS gross_sales,
                COUNT(DISTINCT CASE WHEN r.status <> 'Completed' THEN r.repair_ID END) AS open_repairs,
                COUNT(DISTINCT CASE WHEN vbi.stock_status = 'REORDER' THEN CONCAT(vbi.branch_ID, ':', vbi.product_ID) END) AS reorder_alerts
            FROM BRANCH b
            LEFT JOIN SALE s ON b.branch_ID = s.branch_ID
            LEFT JOIN APPOINTMENT a ON b.branch_ID = a.branch_ID
            LEFT JOIN REPAIR r ON a.appointment_ID = r.appointment_ID
            LEFT JOIN vw_branch_inventory vbi ON b.branch_ID = vbi.branch_ID
            GROUP BY b.branch_ID, b.address
            ORDER BY gross_sales DESC, sale_count DESC
            """,
        )
        return render_template(
            "reports_branches.html",
            active_page="reports_branches",
            page_title="Branch Comparisons",
            rows=rows,
        )

    @app.route("/reports/repairs")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_ANALYST)
    def reports_repairs():
        db = get_db()
        status_rows = safe_rows_query(
            db,
            """
            SELECT status, COUNT(*) AS repair_count, COALESCE(SUM(cost), 0) AS total_cost
            FROM REPAIR
            GROUP BY status
            ORDER BY repair_count DESC
            """,
        )
        history_rows = safe_rows_query(
            db,
            """
            SELECT repair_ID, appointment_ID, appointment_date, customer_name, vehicle, mechanic, repair_status, labor_cost
            FROM vw_repair_history
            ORDER BY appointment_date DESC, repair_ID DESC
            LIMIT 25
            """,
        )
        return render_template(
            "reports_repairs.html",
            active_page="reports_repairs",
            page_title="Repair Reporting",
            status_rows=status_rows,
            history_rows=history_rows,
        )

    @app.route("/reports/sales")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_ANALYST)
    def reports_sales():
        db = get_db()
        branch_rows = safe_rows_query(
            db,
            """
            SELECT b.branch_ID, b.address AS branch_address, COUNT(*) AS sale_count, COALESCE(SUM(s.total_amount), 0) AS gross_sales
            FROM SALE s
            JOIN BRANCH b ON s.branch_ID = b.branch_ID
            GROUP BY b.branch_ID, b.address
            ORDER BY gross_sales DESC, sale_count DESC
            """,
        )
        detail_rows = safe_rows_query(
            db,
            """
            SELECT sale_ID, sale_date, customer_name, product_description, quantity, unit_price, line_total
            FROM vw_sale_detail
            ORDER BY sale_date DESC, sale_ID DESC
            LIMIT 30
            """,
        )
        return render_template(
            "reports_sales.html",
            active_page="reports_sales",
            page_title="Sales Reporting",
            branch_rows=branch_rows,
            detail_rows=detail_rows,
        )

    @app.route("/reports/inventory-alerts")
    @roles_required(ROLE_ADMIN, ROLE_MANAGER, ROLE_ANALYST)
    def reports_inventory_alerts():
        db = get_db()
        alert_rows = safe_rows_query(
            db,
            """
            SELECT branch_ID, branch_address, product_ID, product_type, description, quantity_in_inventory, reorder_level, stock_status
            FROM vw_branch_inventory
            WHERE stock_status = 'REORDER'
            ORDER BY branch_ID ASC, quantity_in_inventory ASC, product_ID ASC
            """,
        )
        return render_template(
            "reports_inventory_alerts.html",
            active_page="reports_inventory_alerts",
            page_title="Inventory Alerts",
            alert_rows=alert_rows,
        )

    def render_studio_dashboard():
        db = get_db()
        catalog = load_catalog(db)
        search_query = request.args.get("q", "").strip()
        if search_query:
            lowered = search_query.lower()
            catalog = [
                item
                for item in catalog
                if lowered in item["table_name"].lower()
                or lowered in item["display_name"].lower()
                or lowered in item["table_type"].lower()
                or any(lowered in column["column_name"].lower() for column in item["columns"])
            ]

        stats = build_stats(catalog)
        spotlight = build_spotlight(catalog)
        samples = build_samples(db)
        dashboard_actions = [
            {
                "label": "Open Query Lab",
                "description": "Run read-only SQL against the live database",
                "href": url_for("query_lab"),
                "icon": "play_arrow",
            },
            {
                "label": "Browse Catalog",
                "description": "Inspect tables, views, and schema metadata",
                "href": url_for("catalog"),
                "icon": "table_view",
            },
            {
                "label": "Connection Settings",
                "description": "Review Azure MySQL access and security",
                "href": url_for("settings"),
                "icon": "settings",
            },
        ]
        recent_tables = spotlight["top_tables"][:3]
        activity = build_activity_feed(recent_tables)
        return render_template(
            "dashboard.html",
            active_page="dashboard",
            page_title="Overview",
            search_query=search_query,
            catalog=catalog,
            stats=stats,
            spotlight=spotlight,
            samples=samples,
            dashboard_actions=dashboard_actions,
            recent_tables=recent_tables,
            activity=activity,
        )

    @app.route("/catalog")
    @app.route("/studio/catalog")
    @roles_required(ROLE_ADMIN)
    def catalog():
        db = get_db()
        catalog = load_catalog(db)
        search_query = request.args.get("q", "").strip()
        if search_query:
            lowered = search_query.lower()
            catalog = [
                item
                for item in catalog
                if lowered in item["table_name"].lower()
                or lowered in item["display_name"].lower()
                or lowered in item["table_type"].lower()
                or any(lowered in column["column_name"].lower() for column in item["columns"])
            ]

        stats = build_stats(catalog)
        spotlight = build_spotlight(catalog)
        return render_template(
            "catalog.html",
            active_page="catalog",
            page_title="Catalog",
            search_query=search_query,
            catalog=catalog,
            stats=stats,
            spotlight=spotlight,
        )

    @app.route("/favicon.ico")
    def favicon():
        return "", 204

    @app.route("/objects/<path:object_name>")
    @app.route("/studio/objects/<path:object_name>")
    @roles_required(ROLE_ADMIN)
    def object_view(object_name):
        db = get_db()
        catalog = load_catalog(db)
        lookup = {item["table_name"].lower(): item for item in catalog}
        key = object_name.lower()
        if key not in lookup:
            abort(404)

        obj = lookup[key]
        page_size = clamp_int(request.args.get("page_size", 10), minimum=1, maximum=100)
        page = clamp_int(request.args.get("page", 1), minimum=1)
        total_rows = obj["row_count"]
        total_pages = max(1, math.ceil(total_rows / page_size))
        if page > total_pages:
            page = total_pages
        offset = (page - 1) * page_size
        rows = fetch_rows(db, obj["table_name"], page_size, offset)
        columns = obj["columns"]

        return render_template(
            "object.html",
            active_page="catalog",
            page_title=obj["display_name"],
            object=obj,
            rows=rows,
            columns=columns,
            page=page,
            page_size=page_size,
            total_rows=total_rows,
            total_pages=total_pages,
            has_prev=page > 1,
            has_next=page < total_pages,
        )

    @app.route("/query", methods=["GET", "POST"])
    @app.route("/studio/query", methods=["GET", "POST"])
    @roles_required(ROLE_ADMIN)
    def query_lab():
        db = get_db()
        catalog = load_catalog(db)
        samples = [
            {
                "label": "Sale detail preview",
                "sql": "SELECT * FROM vw_sale_detail LIMIT 5;",
            },
            {
                "label": "Branch inventory",
                "sql": "SELECT * FROM vw_branch_inventory LIMIT 5;",
            },
            {
                "label": "Customer directory",
                "sql": "SELECT * FROM vw_customer_profile LIMIT 5;",
            },
            {
                "label": "Row count check",
                "sql": "SELECT COUNT(*) AS row_count FROM PERSON;",
            },
        ]

        default_sql = request.values.get("sql", "SELECT * FROM vw_sale_detail LIMIT 5;").strip()
        executed_sql = None
        result = None
        elapsed_ms = None
        error = None

        if request.method == "POST":
            executed_sql = default_sql
            if not is_read_only_sql(executed_sql):
                error = "Only read-only SQL is allowed here. Use SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN."
                flash(error, "danger")
            else:
                start = time.perf_counter()
                try:
                    result = run_read_only_query(db, executed_sql)
                    elapsed_ms = round((time.perf_counter() - start) * 1000, 1)
                    flash("Query executed successfully.", "success")
                except pymysql.MySQLError as exc:
                    error = f"MySQL rejected the query: {exc}"
                    flash(error, "danger")

        query_tip = build_query_tip(default_sql)
        query_metrics = build_query_metrics(result, elapsed_ms)
        active_connections = build_active_connections()

        return render_template(
            "query.html",
            active_page="query",
            page_title="Query Lab",
            catalog=catalog,
            sql_text=default_sql,
            executed_sql=executed_sql,
            result=result,
            elapsed_ms=elapsed_ms,
            error=error,
            samples=samples,
            query_tip=query_tip,
            query_metrics=query_metrics,
            active_connections=active_connections,
        )

    @app.route("/settings")
    @app.route("/studio/settings")
    @roles_required(ROLE_ADMIN)
    def settings():
        db = get_db()
        catalog = load_catalog(db)
        stats = build_stats(catalog)
        spotlight = build_spotlight(catalog)
        connection = build_connection_snapshot()
        active_connections = build_active_connections()
        return render_template(
            "settings.html",
            active_page="settings",
            page_title="Connection Settings",
            connection=connection,
            active_connections=active_connections,
            stats=stats,
            spotlight=spotlight,
        )

    @app.route("/api/connection-check")
    @roles_required(ROLE_ADMIN)
    def connection_check():
        db = get_db()
        db.ping(reconnect=True)
        with db.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS row_count FROM PERSON")
            person_row = cursor.fetchone() or {"row_count": 0}
        connection = build_connection_snapshot()
        return {
            "ok": True,
            "message": f"{connection['name']} is live. PERSON has {person_row['row_count']} rows.",
            "target": connection["target"],
            "database": connection["database"],
            "user": connection["user"],
            "row_count": person_row["row_count"],
        }

    def render_ops_placeholder(active_page, title, description):
        return render_template(
            "ops_placeholder.html",
            active_page=active_page,
            page_title=title,
            title=title,
            description=description,
        )

    return app


def env_flag(name, default=False):
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_studio_request():
    endpoint = request.endpoint or ""
    studio_prefixes = {"dashboard", "catalog", "object_view", "query_lab", "settings"}
    return endpoint in studio_prefixes or request.path.startswith("/studio")


def safe_next_url(next_url):
    if not next_url:
        return None
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return None
    if not next_url.startswith("/"):
        return None
    return next_url


def get_current_session_user():
    user_id = session.get("user_id")
    username = session.get("username")
    display_name = session.get("display_name")
    role = session.get("role")
    if not user_id or not username or not role:
        return None
    return {
        "user_id": user_id,
        "username": username,
        "display_name": display_name or username,
        "role": role,
    }


def set_current_session_user(user):
    session.clear()
    session["user_id"] = user["user_id"]
    session["username"] = user["username"]
    session["display_name"] = user["display_name"]
    session["role"] = user["role"]


def current_user_role():
    user = get_current_session_user()
    return user["role"] if user else None


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("AUTH_ENABLED", False):
            return view_func(*args, **kwargs)
        if not get_current_session_user():
            next_target = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=next_target))
        return view_func(*args, **kwargs)

    return wrapped


def roles_required(*allowed_roles):
    allowed = set(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapped(*args, **kwargs):
            if not current_app.config.get("AUTH_ENABLED", False):
                return view_func(*args, **kwargs)
            user = get_current_session_user()
            if not user:
                next_target = request.full_path if request.query_string else request.path
                return redirect(url_for("login", next=next_target))
            if user["role"] not in allowed:
                flash("You do not have access to that page.", "danger")
                return redirect(url_for("unauthorized"))
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def authenticate_user(db, username, password):
    if not username or not password:
        return None, "Enter both username and password."

    try:
        user_row = load_user_by_username(db, username)
    except pymysql.MySQLError:
        return None, "Authentication is not ready. Ensure the users table exists and is readable."

    if not user_row or not user_row.get("is_active"):
        return None, "Invalid username or password."
    if user_row.get("role") not in ROLE_CHOICES:
        return None, "User role is not configured correctly."
    if not check_password_hash(user_row["password_hash"], password):
        return None, "Invalid username or password."

    return (
        {
            "user_id": user_row["user_id"],
            "username": user_row["username"],
            "display_name": user_row["display_name"],
            "role": user_row["role"],
        },
        None,
    )


def load_user_by_username(db, username):
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT user_id, username, display_name, role, password_hash, is_active
            FROM users
            WHERE username = %s
            LIMIT 1
            """,
            (username,),
        )
        row = cursor.fetchone()
    if not row:
        return None
    user = normalize_row(row)
    user["is_active"] = bool(user.get("is_active"))
    return user


def build_nav_items(auth_enabled, role):
    if not auth_enabled:
        return [
            {"label": "Dashboard", "icon": "dashboard", "endpoint": "dashboard", "key": "dashboard"},
            {"label": "Catalog", "icon": "table_view", "endpoint": "catalog", "key": "catalog"},
            {"label": "Query Lab", "icon": "terminal", "endpoint": "query_lab", "key": "query"},
            {"label": "Settings", "icon": "settings", "endpoint": "settings", "key": "settings"},
        ]

    if role == ROLE_ADMIN:
        return [
            {"label": "Studio Dashboard", "icon": "dashboard", "endpoint": "dashboard", "key": "dashboard"},
            {"label": "Catalog", "icon": "table_view", "endpoint": "catalog", "key": "catalog"},
            {"label": "Query Lab", "icon": "terminal", "endpoint": "query_lab", "key": "query"},
            {"label": "Settings", "icon": "settings", "endpoint": "settings", "key": "settings"},
            {"label": "Ops Dashboard", "icon": "monitoring", "endpoint": "ops_dashboard", "key": "ops_dashboard"},
            {"label": "Reports", "icon": "bar_chart", "endpoint": "reports_overview", "key": "reports_overview"},
        ]

    if role == ROLE_MANAGER:
        return [
            {"label": "Ops Dashboard", "icon": "monitoring", "endpoint": "ops_dashboard", "key": "ops_dashboard"},
            {"label": "Customers", "icon": "groups", "endpoint": "ops_customers", "key": "ops_customers"},
            {"label": "Appointments", "icon": "event", "endpoint": "ops_appointments", "key": "ops_appointments"},
            {"label": "Repairs", "icon": "build", "endpoint": "ops_repairs", "key": "ops_repairs"},
            {"label": "Sales", "icon": "point_of_sale", "endpoint": "ops_sales", "key": "ops_sales"},
            {"label": "Inventory", "icon": "inventory_2", "endpoint": "ops_inventory", "key": "ops_inventory"},
            {"label": "Reports", "icon": "bar_chart", "endpoint": "reports_overview", "key": "reports_overview"},
        ]

    if role == ROLE_FRONTDESK:
        return [
            {"label": "Ops Dashboard", "icon": "monitoring", "endpoint": "ops_dashboard", "key": "ops_dashboard"},
            {"label": "Customers", "icon": "groups", "endpoint": "ops_customers", "key": "ops_customers"},
            {"label": "Appointments", "icon": "event", "endpoint": "ops_appointments", "key": "ops_appointments"},
            {"label": "Sales", "icon": "point_of_sale", "endpoint": "ops_sales", "key": "ops_sales"},
        ]

    if role == ROLE_MECHANIC:
        return [
            {"label": "Ops Dashboard", "icon": "monitoring", "endpoint": "ops_dashboard", "key": "ops_dashboard"},
            {"label": "Repairs", "icon": "build", "endpoint": "ops_repairs", "key": "ops_repairs"},
            {"label": "Appointments", "icon": "event", "endpoint": "ops_appointments", "key": "ops_appointments"},
            {"label": "Inventory", "icon": "inventory_2", "endpoint": "ops_inventory", "key": "ops_inventory"},
        ]

    if role == ROLE_ANALYST:
        return [
            {"label": "Ops Dashboard", "icon": "monitoring", "endpoint": "ops_dashboard", "key": "ops_dashboard"},
            {"label": "Reports", "icon": "bar_chart", "endpoint": "reports_overview", "key": "reports_overview"},
            {"label": "Branch Reports", "icon": "storefront", "endpoint": "reports_branches", "key": "reports_branches"},
            {"label": "Sales Reports", "icon": "query_stats", "endpoint": "reports_sales", "key": "reports_sales"},
        ]

    return []


def build_sidebar_cta(auth_enabled, role):
    if not auth_enabled:
        return {"label": "New Query", "icon": "add", "endpoint": "query_lab"}
    if role == ROLE_ADMIN:
        return {"label": "New Query", "icon": "add", "endpoint": "query_lab"}
    if role in {ROLE_FRONTDESK, ROLE_MANAGER}:
        return {"label": "Open Appointments", "icon": "event", "endpoint": "ops_appointments"}
    if role == ROLE_MECHANIC:
        return {"label": "Open Repair Queue", "icon": "build", "endpoint": "ops_repairs"}
    return {"label": "Open Reports", "icon": "bar_chart", "endpoint": "reports_overview"}


def initials_for_name(display_name):
    parts = [part for part in (display_name or "").split() if part]
    if not parts:
        return "U"
    if len(parts) == 1:
        return parts[0][0].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def get_db():
    if "mysql_db" not in g:
        kwargs = build_connection_kwargs()
        g.mysql_db = pymysql.connect(**kwargs)
    return g.mysql_db


def build_connection_kwargs():
    kwargs = {
        "user": DEFAULT_USER,
        "password": DEFAULT_PASSWORD,
        "database": DEFAULT_DATABASE,
        "autocommit": True,
        "charset": "utf8mb4",
        "cursorclass": DictCursor,
        "connect_timeout": DEFAULT_CONNECT_TIMEOUT,
    }

    socket_path = Path(DEFAULT_SOCKET).expanduser()
    if socket_path.exists() and DEFAULT_HOST in {"127.0.0.1", "localhost"}:
        kwargs["unix_socket"] = str(socket_path)
    else:
        kwargs["host"] = DEFAULT_HOST
        kwargs["port"] = DEFAULT_PORT

    ssl_kwargs = build_ssl_kwargs()
    if ssl_kwargs is not None:
        kwargs["ssl"] = ssl_kwargs

    return kwargs


def get_connection_target():
    socket_path = Path(DEFAULT_SOCKET).expanduser()
    if socket_path.exists() and DEFAULT_HOST in {"127.0.0.1", "localhost"}:
        return f"{DEFAULT_HOST}:{DEFAULT_PORT} via socket"
    return f"{DEFAULT_HOST}:{DEFAULT_PORT}"


def build_ssl_kwargs():
    if DEFAULT_SSL_MODE == "DISABLED":
        return None

    ssl_kwargs = {"verify_mode": "none"}
    if DEFAULT_SSL_CA:
        ca_path = Path(DEFAULT_SSL_CA).expanduser()
        if ca_path.exists():
            ssl_kwargs["ca"] = str(ca_path)

    if DEFAULT_SSL_MODE in {"VERIFY_CA", "VERIFY_IDENTITY"} and "ca" not in ssl_kwargs:
        raise RuntimeError(
            "MYSQL_SSL_CA must point to a readable Azure MySQL CA bundle when MYSQL_SSL_MODE is VERIFY_CA or VERIFY_IDENTITY."
        )

    if DEFAULT_SSL_MODE == "VERIFY_CA":
        ssl_kwargs["verify_mode"] = "required"
        ssl_kwargs["check_hostname"] = False
    elif DEFAULT_SSL_MODE == "VERIFY_IDENTITY":
        ssl_kwargs["verify_mode"] = "required"
        ssl_kwargs["check_hostname"] = True

    return ssl_kwargs


def load_catalog(db):
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, table_type
            FROM information_schema.tables
            WHERE table_schema = %s
            ORDER BY CASE table_type WHEN 'BASE TABLE' THEN 0 ELSE 1 END, table_name
            """,
            (DEFAULT_DATABASE,),
        )
        objects = [normalize_row(row) for row in cursor.fetchall()]

    for item in objects:
        item["display_name"] = pretty_name(item["table_name"])
        item["kind_label"] = "View" if item["table_type"] == "VIEW" else "Table"
        item["columns"] = load_columns(db, item["table_name"])
        item["column_count"] = len(item["columns"])
        item["row_count"] = count_rows(db, item["table_name"])
    return objects


def load_columns(db, table_name):
    with db.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable, column_key, column_type, extra
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s
            ORDER BY ordinal_position
            """,
            (DEFAULT_DATABASE, table_name),
        )
        return [normalize_row(row) for row in cursor.fetchall()]


def count_rows(db, object_name):
    with db.cursor() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS row_count FROM {quote_identifier(object_name)}")
        row = normalize_row(cursor.fetchone())
    return int(row["row_count"])


def fetch_rows(db, object_name, limit, offset):
    with db.cursor() as cursor:
        cursor.execute(
            f"SELECT * FROM {quote_identifier(object_name)} LIMIT %s OFFSET %s",
            (limit, offset),
        )
        return cursor.fetchall()


def build_stats(catalog):
    tables = [item for item in catalog if item["table_type"] == "BASE TABLE"]
    views = [item for item in catalog if item["table_type"] == "VIEW"]
    return {
        "objects": len(catalog),
        "tables": len(tables),
        "views": len(views),
        "rows": sum(item["row_count"] for item in tables),
    }


def build_spotlight(catalog):
    tables = sorted(
        (item for item in catalog if item["table_type"] == "BASE TABLE"),
        key=lambda item: item["row_count"],
        reverse=True,
    )
    views = sorted(
        (item for item in catalog if item["table_type"] == "VIEW"),
        key=lambda item: item["row_count"],
        reverse=True,
    )
    widest = max(catalog, key=lambda item: item["column_count"], default=None)
    smallest = min(catalog, key=lambda item: item["column_count"], default=None)

    return {
        "top_tables": tables[:5],
        "top_views": views[:5],
        "largest_table": tables[0] if tables else None,
        "largest_view": views[0] if views else None,
        "widest_object": widest,
        "smallest_object": smallest,
        "table_row_max": tables[0]["row_count"] if tables else 1,
        "view_row_max": views[0]["row_count"] if views else 1,
    }


def build_samples(db):
    sample_targets = [
        ("vw_sale_detail", "Latest sales"),
        ("vw_branch_inventory", "Branch inventory"),
        ("vw_customer_profile", "Customer directory"),
    ]
    samples = []
    for object_name, title in sample_targets:
        try:
            columns = load_columns(db, object_name)
            rows = fetch_rows(db, object_name, limit=5, offset=0)
        except pymysql.MySQLError:
            continue

        samples.append(
            {
                "object_name": object_name,
                "title": title,
                "kind_label": "View",
                "columns": columns[:5],
                "rows": rows,
            }
        )
    return samples


def build_activity_feed(recent_tables):
    feed = []
    for index, item in enumerate(recent_tables[:3], start=1):
        feed.append(
            {
                "title": f"SELECT * FROM {item['table_name']} LIMIT 5;",
                "meta": f"{index * 5} mins ago · Success",
                "tone": "primary" if index == 1 else "muted",
                "detail": f"{item['display_name']} · {item['row_count']} rows",
            }
        )

    if not feed:
        feed = [
            {
                "title": "SELECT COUNT(*) AS row_count FROM PERSON;",
                "meta": "Now · Success",
                "tone": "primary",
                "detail": "No catalog data loaded",
            }
        ]
    return feed


def build_connection_snapshot():
    local_socket = Path(DEFAULT_SOCKET).expanduser()
    using_socket = local_socket.exists() and DEFAULT_HOST in {"127.0.0.1", "localhost"}
    return {
        "name": DEFAULT_SERVER_LABEL,
        "host": DEFAULT_HOST,
        "port": DEFAULT_PORT,
        "database": DEFAULT_DATABASE,
        "user": DEFAULT_USER,
        "ssl_mode": DEFAULT_SSL_MODE,
        "transport": "Unix socket" if using_socket else "TCP / TLS",
        "target": get_connection_target(),
        "mode": "local" if DEFAULT_HOST in {"127.0.0.1", "localhost"} else "azure",
        "socket": str(local_socket) if using_socket else None,
    }


def build_active_connections():
    connection = build_connection_snapshot()
    return [
        {
            "name": "Database endpoint",
            "endpoint": connection["target"],
            "status": "Live",
            "tone": "primary",
            "meta": f"{connection['database']} over {connection['transport']}",
            "icon": "storage",
        },
        {
            "name": "Application role",
            "endpoint": connection["user"],
            "status": "Read only",
            "tone": "tertiary",
            "meta": "SELECT and SHOW VIEW only",
            "icon": "verified_user",
        },
    ]


def build_query_tip(sql_text):
    cleaned = sql_text.strip().lower()
    if not cleaned:
        return "Start with SELECT, SHOW, DESCRIBE, or EXPLAIN to inspect the database safely."
    if "*" in cleaned and cleaned.startswith(("select", "with")):
        return "Narrow the projection when possible. `SELECT *` is fine for spot checks, not for broad analysis."
    if "limit" not in cleaned and cleaned.startswith(("select", "with")):
        return "Add LIMIT when exploring large tables so the first render stays fast."
    return "The query is scoped well for read-only inspection."


def build_query_metrics(result, elapsed_ms):
    return {
        "rows": result["row_count"] if result else 0,
        "columns": len(result["columns"]) if result else 0,
        "elapsed_ms": elapsed_ms,
        "engine": DEFAULT_SERVER_LABEL,
    }


def build_ops_dashboard_data(db):
    metrics = [
        {"label": "Customers", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM CUSTOMER"), "tone": "primary"},
        {"label": "Appointments Today", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM APPOINTMENT WHERE `date` = CURDATE()"), "tone": "secondary"},
        {"label": "Open Repairs", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM REPAIR WHERE status <> 'Completed'"), "tone": "secondary"},
        {"label": "Sales Records", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM SALE"), "tone": "secondary"},
    ]
    backlog = safe_rows_query(
        db,
        """
        SELECT appointment_ID, `date`, `time`, status, appointment_type
        FROM APPOINTMENT
        WHERE status IN ('Scheduled', 'Confirmed', 'In Progress')
        ORDER BY `date`, `time`
        LIMIT 8
        """,
    )
    sales = safe_rows_query(
        db,
        """
        SELECT b.branch_ID, b.address AS branch_address, COUNT(*) AS sale_count, SUM(s.total_amount) AS gross_amount
        FROM SALE s
        JOIN BRANCH b ON s.branch_ID = b.branch_ID
        GROUP BY b.branch_ID, b.address
        ORDER BY gross_amount DESC
        LIMIT 8
        """,
    )
    alerts = safe_rows_query(
        db,
        """
        SELECT branch_ID, product_ID, description, quantity_in_inventory, reorder_level, stock_status
        FROM vw_branch_inventory
        WHERE stock_status = 'REORDER'
        ORDER BY branch_ID, quantity_in_inventory
        LIMIT 8
        """,
    )
    reports = {
        "repairs": safe_scalar_query(db, "SELECT COUNT(*) FROM vw_repair_history"),
        "inventory": safe_scalar_query(db, "SELECT COUNT(*) FROM vw_branch_inventory WHERE stock_status = 'REORDER'"),
        "sales": safe_scalar_query(db, "SELECT COUNT(*) FROM vw_sale_detail"),
    }
    return {
        "metrics": metrics,
        "backlog": backlog,
        "sales": sales,
        "alerts": alerts,
        "reports": reports,
    }


def build_reports_overview_data(db):
    kpis = [
        {"label": "Total sales amount", "value": safe_scalar_query(db, "SELECT COALESCE(SUM(total_amount), 0) FROM SALE")},
        {"label": "Repair backlog", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM REPAIR WHERE status <> 'Completed'")},
        {"label": "Open appointments", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM APPOINTMENT WHERE status IN ('Scheduled', 'Confirmed', 'In Progress')")},
        {"label": "Inventory reorder alerts", "value": safe_scalar_query(db, "SELECT COUNT(*) FROM vw_branch_inventory WHERE stock_status = 'REORDER'")},
    ]
    top_branches = safe_rows_query(
        db,
        """
        SELECT b.branch_ID, b.address AS branch_address, COUNT(*) AS sale_count, COALESCE(SUM(s.total_amount), 0) AS gross_sales
        FROM SALE s
        JOIN BRANCH b ON s.branch_ID = b.branch_ID
        GROUP BY b.branch_ID, b.address
        ORDER BY gross_sales DESC, sale_count DESC
        LIMIT 5
        """,
    )
    repair_status = safe_rows_query(
        db,
        """
        SELECT status, COUNT(*) AS repair_count
        FROM REPAIR
        GROUP BY status
        ORDER BY repair_count DESC
        """,
    )
    inventory_alerts = safe_rows_query(
        db,
        """
        SELECT branch_ID, product_ID, description, quantity_in_inventory, reorder_level
        FROM vw_branch_inventory
        WHERE stock_status = 'REORDER'
        ORDER BY branch_ID, quantity_in_inventory
        LIMIT 10
        """,
    )
    return {
        "kpis": kpis,
        "top_branches": top_branches,
        "repair_status": repair_status,
        "inventory_alerts": inventory_alerts,
    }


def search_customers(db, search_query):
    cleaned = (search_query or "").strip()
    if not cleaned:
        return safe_rows_query(
            db,
            """
            SELECT customer_ID, person_ID, first_name, last_name, DOB, address, phone, email
            FROM vw_customer_profile
            ORDER BY customer_ID DESC
            LIMIT 50
            """,
        )

    like = f"%{cleaned}%"
    try:
        with db.cursor() as cursor:
            cursor.execute(
                """
                SELECT customer_ID, person_ID, first_name, last_name, DOB, address, phone, email
                FROM vw_customer_profile
                WHERE CAST(customer_ID AS CHAR) LIKE %s
                   OR first_name LIKE %s
                   OR last_name LIKE %s
                   OR COALESCE(phone, '') LIKE %s
                   OR COALESCE(email, '') LIKE %s
                ORDER BY customer_ID DESC
                LIMIT 100
                """,
                (like, like, like, like, like),
            )
            return cursor.fetchall()
    except pymysql.MySQLError:
        return []


def create_customer_record(db, payload):
    first_name = (payload.get("first_name") or "").strip()
    last_name = (payload.get("last_name") or "").strip()
    if not first_name or not last_name:
        return None, "First name and last name are required."

    try:
        person_id = next_numeric_id(db, "PERSON", "person_ID")
        customer_id = next_numeric_id(db, "CUSTOMER", "customer_ID")
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO PERSON (person_ID, first_name, last_name, DOB, address, phone, email)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    person_id,
                    first_name,
                    last_name,
                    payload.get("dob"),
                    payload.get("address"),
                    payload.get("phone"),
                    payload.get("email"),
                ),
            )
            cursor.execute(
                """
                INSERT INTO CUSTOMER (customer_ID, person_ID)
                VALUES (%s, %s)
                """,
                (customer_id, person_id),
            )
        return customer_id, None
    except pymysql.MySQLError as exc:
        return None, write_error_message("customer", exc)


def create_appointment_record(db, payload):
    try:
        customer_id = int(payload.get("customer_id"))
        car_id = int(payload.get("car_id"))
        branch_id = int(payload.get("branch_id"))
        employee_id = int(payload.get("employee_id"))
    except (TypeError, ValueError):
        return None, "Customer, car, branch, and employee are required."

    date_value = (payload.get("date") or "").strip()
    time_value = (payload.get("time") or "").strip()
    appointment_type = (payload.get("appointment_type") or "").strip()
    status = (payload.get("status") or "Scheduled").strip()
    if not date_value or not time_value or not appointment_type:
        return None, "Date, time, and appointment type are required."

    try:
        appointment_id = next_numeric_id(db, "APPOINTMENT", "appointment_ID")
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO APPOINTMENT (
                    appointment_ID, customer_ID, car_id, branch_ID, date, time, appointment_type, status, employee_ID
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    appointment_id,
                    customer_id,
                    car_id,
                    branch_id,
                    date_value,
                    time_value,
                    appointment_type,
                    status,
                    employee_id,
                ),
            )
        return appointment_id, None
    except pymysql.MySQLError as exc:
        return None, write_error_message("appointment", exc)


def create_sale_record(db, payload):
    try:
        branch_id = int(payload.get("branch_id"))
        customer_id = int(payload.get("customer_id"))
        product_id = int(payload.get("product_id"))
        quantity = int(payload.get("quantity"))
    except (TypeError, ValueError):
        return None, "Branch, customer, product, and quantity are required."
    if quantity <= 0:
        return None, "Quantity must be greater than zero."

    date_value = (payload.get("date") or "").strip()
    time_value = (payload.get("time") or "").strip()
    delivery_method = payload.get("delivery_method")
    if not date_value or not time_value:
        return None, "Date and time are required."

    unit_price = parse_decimal(payload.get("unit_price"))
    if unit_price is None:
        return None, "Unit price must be a valid number."
    if unit_price < 0:
        return None, "Unit price cannot be negative."
    total_amount = unit_price * Decimal(quantity)

    try:
        sale_id = next_numeric_id(db, "SALE", "sale_ID")
        sale_item_id = next_numeric_id(db, "SALE_ITEM", "sale_item_ID")
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO SALE (sale_ID, branch_ID, customer_ID, date, time, total_amount, delivery_method)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    sale_id,
                    branch_id,
                    customer_id,
                    date_value,
                    time_value,
                    total_amount,
                    delivery_method,
                ),
            )
            cursor.execute(
                """
                INSERT INTO SALE_ITEM (sale_item_ID, sale_ID, product_ID, quantity, unit_price)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    sale_item_id,
                    sale_id,
                    product_id,
                    quantity,
                    unit_price,
                ),
            )
        return sale_id, None
    except pymysql.MySQLError as exc:
        return None, write_error_message("sale", exc)


def create_repair_record(db, payload):
    try:
        appointment_id = int(payload.get("appointment_id"))
        employee_id = int(payload.get("employee_id"))
    except (TypeError, ValueError):
        return None, "Appointment and assigned employee are required."

    status = (payload.get("status") or "In Progress").strip()
    if status not in {"In Progress", "Completed", "On Hold"}:
        return None, "Repair status must be In Progress, Completed, or On Hold."
    cost = parse_decimal(payload.get("cost"))
    if cost is None:
        return None, "Repair cost must be a valid number."
    if cost < 0:
        return None, "Repair cost cannot be negative."

    existing = safe_rows_query(
        db,
        "SELECT repair_ID FROM REPAIR WHERE appointment_ID = %s LIMIT 1",
        (appointment_id,),
    )
    if existing:
        return None, f"Appointment {appointment_id} already has repair {existing[0]['repair_ID']}."

    try:
        repair_id = next_numeric_id(db, "REPAIR", "repair_ID")
        with db.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO REPAIR (repair_ID, appointment_ID, employee_ID, status, cost)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (repair_id, appointment_id, employee_id, status, cost),
            )
        return repair_id, None
    except pymysql.MySQLError as exc:
        return None, write_error_message("repair", exc)


def update_repair_record(db, payload):
    try:
        repair_id = int(payload.get("repair_id"))
    except (TypeError, ValueError):
        return "Repair ID is required."

    status = (payload.get("status") or "").strip()
    if status and status not in {"In Progress", "Completed", "On Hold"}:
        return "Repair status must be In Progress, Completed, or On Hold."
    cost_value = payload.get("cost")
    cost = parse_decimal(cost_value) if (cost_value or "").strip() else None
    if cost is not None and cost < 0:
        return "Repair cost cannot be negative."
    employee_raw = (payload.get("employee_id") or "").strip()
    try:
        employee_id = int(employee_raw) if employee_raw else None
    except ValueError:
        return "Assigned employee must be numeric."

    fields = []
    values = []
    if status:
        fields.append("status = %s")
        values.append(status)
    if cost is not None:
        fields.append("cost = %s")
        values.append(cost)
    if employee_id is not None:
        fields.append("employee_ID = %s")
        values.append(employee_id)
    if not fields:
        return "No changes were submitted."

    values.append(repair_id)
    try:
        with db.cursor() as cursor:
            cursor.execute(
                f"UPDATE REPAIR SET {', '.join(fields)} WHERE repair_ID = %s",
                tuple(values),
            )
            if cursor.rowcount == 0:
                return f"Repair {repair_id} was not found."
        return None
    except pymysql.MySQLError as exc:
        return write_error_message("repair", exc)


def parse_decimal(raw_value):
    text = (raw_value or "").strip()
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def next_numeric_id(db, table_name, column_name):
    with db.cursor() as cursor:
        cursor.execute(f"SELECT COALESCE(MAX({quote_identifier(column_name)}), 0) + 1 AS next_id FROM {quote_identifier(table_name)}")
        row = cursor.fetchone() or {"next_id": 1}
    return int(row["next_id"])


def write_error_message(entity_label, exc):
    # Keep production-safe messaging while surfacing permission constraints clearly.
    lowered = str(exc).lower()
    if "denied" in lowered or "read only" in lowered or "readonly" in lowered:
        return f"Unable to create {entity_label}: database user does not have write permission."
    return f"Unable to create {entity_label}: {exc}"


def safe_scalar_query(db, sql):
    try:
        with db.cursor() as cursor:
            cursor.execute(sql)
            row = cursor.fetchone()
            if not row:
                return 0
            first_value = list(row.values())[0]
            return int(first_value) if first_value is not None else 0
    except (ValueError, TypeError, pymysql.MySQLError):
        return 0


def safe_rows_query(db, sql, params=None):
    try:
        with db.cursor() as cursor:
            cursor.execute(sql, params or ())
            return cursor.fetchall()
    except pymysql.MySQLError:
        return []


def load_product_options(db):
    product_columns = {
        row["column_name"].lower()
        for row in safe_rows_query(
            db,
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = %s
              AND table_name = 'PRODUCT'
            """,
            (DEFAULT_DATABASE,),
        )
    }

    if {"description", "value"}.issubset(product_columns):
        return safe_rows_query(
            db,
            """
            SELECT product_ID, description, value
            FROM PRODUCT
            ORDER BY product_ID
            LIMIT 200
            """,
        )

    return safe_rows_query(
        db,
        """
        SELECT
            pr.product_ID,
            COALESCE(CONCAT(c.make, ' ', c.model), pt.part_name, CONCAT('Product ', pr.product_ID)) AS description,
            pr.price AS value
        FROM PRODUCT pr
        LEFT JOIN CAR c ON pr.product_ID = c.product_ID
        LEFT JOIN PART pt ON pr.product_ID = pt.product_ID
        ORDER BY pr.product_ID
        LIMIT 200
        """,
    )


def run_read_only_query(db, sql_text):
    query = sql_text.strip()
    if query.endswith(";"):
        query = query[:-1].strip()

    with db.cursor() as cursor:
        cursor.execute(query)
        columns = [column[0] for column in cursor.description] if cursor.description else []
        rows = cursor.fetchall() if cursor.description else []

    return {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


def is_read_only_sql(sql_text):
    cleaned = sql_text.strip().lower()
    if not cleaned:
        return False
    body = cleaned[:-1] if cleaned.endswith(";") else cleaned
    if ";" in body:
        return False
    return cleaned.startswith(("select", "with", "show", "describe", "desc", "explain"))


def clamp_int(value, minimum=1, maximum=None):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = minimum
    number = max(minimum, number)
    if maximum is not None:
        number = min(maximum, number)
    return number


def pretty_name(name):
    if name.lower().startswith("vw_"):
        name = name[3:]
    return name.replace("_", " ").title()


def quote_identifier(name):
    return "`" + name.replace("`", "``") + "`"


def normalize_row(row):
    return {key.lower(): value for key, value in row.items()}


app = create_app()

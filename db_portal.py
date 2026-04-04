import math
import os
import time
from pathlib import Path

import pymysql
from flask import Flask, abort, flash, g, render_template, request, url_for
from pymysql.cursors import DictCursor

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


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or "dev-secret-key-change-me"

    @app.teardown_appcontext
    def close_db(_exc):
        db = g.pop("mysql_db", None)
        if db is not None:
            db.close()

    @app.context_processor
    def inject_globals():
        return {
            "database_name": DEFAULT_DATABASE,
            "server_label": DEFAULT_SERVER_LABEL,
            "connection_target": get_connection_target(),
            "search_action": url_for("catalog"),
            "search_placeholder": "Search tables, views, or saved queries",
        }

    @app.route("/")
    def dashboard():
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
    def settings():
        db = get_db()
        catalog = load_catalog(db)
        stats = build_stats(catalog)
        spotlight = build_spotlight(catalog)
        connection = build_connection_snapshot()
        active_connections = build_active_connections()
        best_practices = [
            "Use the read-only app user for class sharing.",
            "Keep TLS enabled against Azure MySQL.",
            "Remove temporary firewall rules when direct admin access is no longer needed.",
        ]
        return render_template(
            "settings.html",
            active_page="settings",
            page_title="Connection Settings",
            connection=connection,
            active_connections=active_connections,
            stats=stats,
            spotlight=spotlight,
            best_practices=best_practices,
        )

    return app


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
    local_socket = connection["socket"] or "/tmp/mysql.sock"
    return [
        {
            "name": connection["name"],
            "endpoint": connection["target"],
            "status": "CONNECTED",
            "tone": "primary",
            "meta": f"{connection['database']} · {connection['transport']}",
            "icon": "storage",
        },
        {
            "name": "Read-only app user",
            "endpoint": connection["user"],
            "status": "ACTIVE",
            "tone": "tertiary",
            "meta": "SELECT and SHOW VIEW only",
            "icon": "verified_user",
        },
        {
            "name": "Local dev socket",
            "endpoint": local_socket,
            "status": "IDLE",
            "tone": "muted",
            "meta": "Temporary admin access removed",
            "icon": "dns",
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

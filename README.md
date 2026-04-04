# CIS 9340 Data Studio

MySQL-based Flask data studio for the `cis9340_physical_database` project.

## What it does

- Shows a live dashboard for the database catalog.
- Browses tables and views with pagination.
- Runs read-only SQL for safe inspection.
- Includes a connection settings view for Azure MySQL and local development.
- Supports local MySQL and Azure Database for MySQL Flexible Server.
- Supports optional session-based authentication with role-aware navigation.

## Stack

- Python 3.11+
- Flask
- PyMySQL
- Gunicorn for production hosting
- Jinja templates + custom CSS

## Repo layout

- `run.py` - local development entrypoint
- `application.py` - Azure App Service entrypoint
- `db_portal.py` - Flask + MySQL portal logic
- `templates/` - dashboard, catalog, query lab, table detail, and settings templates
- `static/styles.css` - app styling
- `database/mysql/bootstrap_cis9340_physical_database.sql` - clean MySQL bootstrap script
- `database/mysql/add_users_auth.sql` - additive users table + role seed data
- `database/mysql/add_business_views.sql` - additive role-oriented business reporting views
- `docs/baseline-freeze-2026-04-04.md` - frozen baseline inventory before RBAC evolution
- `.env.example` - environment template

## Local setup

```bash
cd path/to/cis9340-autoops-app
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
python3 run.py
```

Open the URL printed in Terminal.

## Local MySQL defaults

- host: `127.0.0.1`
- port: `3306`
- socket: `/tmp/mysql.sock`
- user: `root`
- database: `cis9340_physical_database`

## Azure deployment model

- Database: Azure Database for MySQL Flexible Server
- App hosting: Azure App Service for Linux
- App entrypoint: `application:app`

## Azure environment variables

Set these in Azure App Service configuration:

- `FLASK_SECRET_KEY`
- `AUTH_ENABLED`
- `OPS_WRITE_ENABLED`
- `MYSQL_HOST`
- `MYSQL_PORT`
- `MYSQL_DATABASE`
- `MYSQL_USER`
- `MYSQL_PASSWORD`
- `MYSQL_SSL_MODE`
- `MYSQL_SSL_CA`
- `MYSQL_CONNECT_TIMEOUT`
- `MYSQL_SERVER_LABEL`

Recommended Azure values:

- `AUTH_ENABLED=true` for role-based application mode
- `OPS_WRITE_ENABLED=false` unless your DB user has controlled write grants
- `MYSQL_SSL_MODE=REQUIRED`
- `MYSQL_SSL_CA=`
- `MYSQL_SERVER_LABEL=Azure MySQL Flexible Server`

If you want certificate verification instead of required-encryption only, switch to `MYSQL_SSL_MODE=VERIFY_CA` and point `MYSQL_SSL_CA` at your Azure MySQL CA bundle.

## Importing the schema into Azure MySQL

1. Create the Azure MySQL server and database.
2. Run the cleaned bootstrap SQL script:
   `database/mysql/bootstrap_cis9340_physical_database.sql`
3. Run the auth bootstrap script for role-based sign-in:
   `database/mysql/add_users_auth.sql`
4. (Optional but recommended) run role-oriented business views pack:
   `database/mysql/add_business_views.sql`
5. Verify tables, views, indexes, and seed data.

## Role-based authentication model

- Default auth architecture:
  - local `users` table in the same MySQL database
  - hashed passwords
  - role column (`admin`, `manager`, `frontdesk`, `mechanic`, `analyst`)
  - session login/logout and route guards in Flask
- Feature flag:
  - `AUTH_ENABLED=false` keeps legacy studio behavior (no login required)
  - `AUTH_ENABLED=true` enables login and role enforcement
- Operational write flag:
  - `OPS_WRITE_ENABLED=false` keeps front-desk create/schedule/record forms read-only
  - `OPS_WRITE_ENABLED=true` enables customer/appointment/sale writes for authorized roles
- Seed credentials from `add_users_auth.sql` are bootstrap-only and should be rotated.

## Role-based workflow surfaces (current)

- Admin studio:
  - `/studio/dashboard`, `/studio/catalog`, `/studio/query`, `/studio/settings`
- Operational:
  - `/ops/dashboard`
  - `/ops/customers` (search + optional create)
  - `/ops/appointments` (review + optional scheduling)
  - `/ops/repairs` (queue + optional create/update)
  - `/ops/sales` (review + optional record)
  - `/ops/inventory` (branch/filter view)
- Executive/reporting:
  - `/reports/overview`, `/reports/branches`, `/reports/repairs`, `/reports/sales`, `/reports/inventory-alerts`

## GitHub deployment

The repository is ready for GitHub-based source control and Azure deployment.

If you use GitHub Actions, create these secrets:

- `AZURE_WEBAPP_NAME`
- `AZURE_CREDENTIALS`

The workflow should deploy the repo root to Azure App Service.
The active workflow in this repo uses `azure/login@v2` with `AZURE_CREDENTIALS`, then `azure/webapps-deploy@v3` with `AZURE_WEBAPP_NAME`.

## Baseline freeze documentation

- Current frozen baseline inventory: `docs/baseline-freeze-2026-04-04.md`
- Use this document to separate stable baseline behavior from phased role-based changes.

## Read-only policy

The query lab only allows read-only statements:

- `SELECT`
- `WITH`
- `SHOW`
- `DESCRIBE` / `DESC`
- `EXPLAIN`

That keeps the shared class deployment safe.

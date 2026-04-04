# CIS 9340 Data Studio

MySQL-based Flask data studio for the `cis9340_physical_database` project.

## What it does

- Shows a live dashboard for the database catalog.
- Browses tables and views with pagination.
- Runs read-only SQL for safe inspection.
- Supports local MySQL and Azure Database for MySQL Flexible Server.

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
- `templates/` - UI templates
- `static/styles.css` - app styling
- `database/mysql/bootstrap_cis9340_physical_database.sql` - clean MySQL bootstrap script
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

- `MYSQL_SSL_MODE=REQUIRED`
- `MYSQL_SSL_CA=`
- `MYSQL_SERVER_LABEL=Azure MySQL Flexible Server`

If you want certificate verification instead of required-encryption only, switch to `MYSQL_SSL_MODE=VERIFY_CA` and point `MYSQL_SSL_CA` at your Azure MySQL CA bundle.

## Importing the schema into Azure MySQL

1. Create the Azure MySQL server and database.
2. Run the cleaned bootstrap SQL script:
   `database/mysql/bootstrap_cis9340_physical_database.sql`
3. Verify tables, views, indexes, and seed data.

## GitHub deployment

The repository is ready for GitHub-based source control and Azure deployment.

If you use GitHub Actions, create these secrets:

- `AZURE_WEBAPP_NAME`
- `AZURE_WEBAPP_PUBLISH_PROFILE`

The workflow should deploy the repo root to Azure App Service.

## Read-only policy

The query lab only allows read-only statements:

- `SELECT`
- `WITH`
- `SHOW`
- `DESCRIBE` / `DESC`
- `EXPLAIN`

That keeps the shared class deployment safe.

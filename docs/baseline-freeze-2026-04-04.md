# CIS9340 Baseline Freeze (2026-04-04)

This document freezes the known application baseline before role-based evolution.

## Purpose

- Preserve a concrete snapshot of what is currently working.
- Distinguish stable surfaces from future changes.
- Protect production behavior while introducing auth and role-specific UX.

## Runtime and Deployment Baseline

- Runtime: Flask app on Azure App Service for Linux.
- Entry point: `application:app` via `application.py`.
- Main app module: `db_portal.py`.
- Working deployment workflow: `.github/workflows/azure-app-service.yml`.
- GitHub Actions deploy path:
  - Python 3.11 setup
  - `pip install -r requirements.txt`
  - `azure/login@v2` using `AZURE_CREDENTIALS`
  - `azure/webapps-deploy@v3` using `AZURE_WEBAPP_NAME`
- Important: startup command is configured in App Service (not in repo scripts).

## Route Inventory (Current)

All current routes are defined in `db_portal.py`.

- `/` -> technical dashboard (studio overview)
- `/catalog` -> schema/catalog browser
- `/objects/<path:object_name>` -> object detail with schema + data
- `/query` -> query lab (read-only SQL execution)
- `/settings` -> connection and environment view
- `/api/connection-check` -> JSON health-style DB check
- `/favicon.ico` -> no-content response

## Page Inventory (Current Templates)

- `templates/base.html` -> shared shell layout + global nav
- `templates/dashboard.html` -> dashboard
- `templates/catalog.html` -> catalog and spotlight
- `templates/object.html` -> object details + paginated rows
- `templates/query.html` -> query lab
- `templates/settings.html` -> connection/settings page

## Static Asset Inventory

- `static/styles.css` -> all UI styling
- `static/app.js` -> query history/drafts and UI actions

## Database/Schema/View Baseline

Primary schema bootstrap:

- `database/mysql/bootstrap_cis9340_physical_database.sql`

Confirmed core entities include:

- `PERSON`, `BRANCH`, `EMPLOYEE`, `CUSTOMER`
- `PRODUCT`, `CAR`, `PART`
- `SALE`, `SALE_ITEM`, `PAYMENT`, `LOAN`
- `APPOINTMENT`, `REPAIR`, `REPAIR_PRODUCT`, `INVENTORY`

Known view layer:

- `vw_branch_inventory`
- `vw_customer_profile`
- `vw_employee_profile`
- `vw_repair_history`
- `vw_sale_detail`

Join truth constraint carried forward:

- `REPAIR` does not contain `customer_ID`.
- Customer-to-repair path is `CUSTOMER -> APPOINTMENT -> REPAIR`.

## Working Behavior Baseline

- Technical dashboard is operational.
- Catalog/object browsing is operational.
- Query Lab single-statement read-only queries are operational.
- Settings and connection check are operational.
- Existing query policy is allowlist-based (`SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `DESC`, `EXPLAIN`).

## Baseline Classification

- Working and stable:
  - Azure MySQL connectivity contract
  - Flask app runtime/deployment model
  - Technical studio surfaces
- Technical debt:
  - No app-level authentication or role-based authorization
  - Single technical nav exposed to every user
  - Technical endpoints not isolated by role
- Future features (not baseline regressions):
  - Operational role-specific workflows
  - Executive/reporting views
  - Curated business UX and role navigation


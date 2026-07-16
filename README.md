# PostgreSQL Export Tool

PostgreSQL Export Tool is a Windows GUI app that exports every table in a PostgreSQL database to CSV files (bundled into a ZIP), along with a SQL script that recreates the full schema — tables, primary keys, foreign keys, unique/check constraints, and indexes, with auto-increment columns correctly re-emitted as `GENERATED ... AS IDENTITY`.

## Usage

**Via context menu (recommended):**
1. Right-click any folder, or right-click inside a folder's empty space.
2. Select **"Export PostgreSQL Database Here"**.
3. The app opens with that folder pre-filled as the output location.
4. Enter your connection details (host, port, database, username, password), click **Test Connection** to verify, then **Start Export**.

**Standalone:**
Launch the app directly from the Start Menu or desktop shortcut. It opens using the current working directory as the output folder, which you can change via **Browse...**.

## Export modes

- **Full export** — CSV files for every table plus the SQL schema script, all zipped together.
- **SQL schema only** — just the `CREATE TABLE` script, no data.

Output files are timestamped, e.g. `mydb_export_20260716_143000.zip` or `mydb_schema_20260716_143000.sql`.

## Installation

Installed via the provided Inno Setup installer. During setup, make sure the **"Add 'SmartPgExport' to folder right-click menu"** task is checked — this is what registers the context menu entries (for both a folder itself and the empty space inside a folder).

Requires administrator rights during install, since the context menu is registered system-wide (`HKEY_LOCAL_MACHINE`).

## Uninstalling

Uninstall from **Settings → Apps → Installed apps**, or run the uninstaller in the install folder. This removes both the program files and the context menu entries.

# PostgreSQL Database Export Script

This script exports all tables from a PostgreSQL database to CSV files and packages them in a ZIP archive.

## Features

- Exports all tables from all schemas (excluding system schemas)
- CSV files are named as `schemaName_tableName.csv`
- Password input is hidden for security
- Creates a timestamped ZIP archive
- Handles large tables efficiently with batch processing
- Provides detailed progress feedback and summary

## Requirements

- Python 3.6 or higher
- PostgreSQL database access

## Installation

1. Install the required Python package:
```bash
pip install -r requirements.txt
```

Or install directly:
```bash
pip install psycopg2-binary
```

## Usage

Run the script:
```bash
python postgres_export.py
```

The script will prompt you for:
- **Host**: Database server address (default: localhost)
- **Port**: Database port (default: 5432)
- **Database name**: Name of the database to export
- **Username**: Database username
- **Password**: Database password (hidden input)

## Output

The script creates a ZIP file named:
```
databaseName_export_YYYYMMDD_HHMMSS.zip
```

This ZIP file contains CSV files for each table, named:
```
schemaName_tableName.csv
```

## Example

```
PostgreSQL Database Export Tool
==================================================

Please enter the database connection details:

Host (default: localhost): localhost
Port (default: 5432): 5432
Database name: mydb
Username: postgres
Password: ********

✓ Database connection successful!

Connected to database: mydb

Found 15 table(s) to export.

Exporting tables:
--------------------------------------------------
Exporting public.users... ✓
Exporting public.orders... ✓
Exporting public.products... ✓
...

--------------------------------------------------
Creating ZIP archive: mydb_export_20250520_143022.zip...

==================================================
Export Summary:
  Successful: 15 table(s)
  Failed: 0 table(s)
  Output file: mydb_export_20250520_143022.zip
  Location: /path/to/mydb_export_20250520_143022.zip
==================================================
```

## Notes

- The script excludes system schemas (`pg_catalog`, `information_schema`)
- Large tables are processed in batches of 1000 rows
- CSV files use UTF-8 encoding
- Temporary CSV files are automatically cleaned up after ZIP creation

## Troubleshooting

**Connection Failed**: Verify your connection details and ensure the PostgreSQL server is accessible.

**Permission Denied**: Ensure your database user has SELECT permissions on all tables you want to export.

**Module Not Found**: Install psycopg2-binary using pip as shown in the Installation section.

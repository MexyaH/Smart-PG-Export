#!/usr/bin/env python3
"""
PostgreSQL Database Table Export Script
Exports all tables from a PostgreSQL database to CSV files in a ZIP archive.
Also generates a SQL script to recreate all schemas and tables.
Can be called from Windows context menu to save export in the selected folder.
"""

import psycopg2
import csv
import zipfile
import os
import sys
from getpass import getpass
from datetime import datetime
import io


def get_connection_info():
    """Prompt user for database connection information."""
    print("PostgreSQL Database Export Tool")
    print("=" * 50)
    print("\nPlease enter the database connection details:\n")

    host = input("Host (default: localhost): ").strip() or "localhost"
    port = input("Port (default: 5432): ").strip() or "5432"
    database = input("Database name: ").strip()
    user = input("Username: ").strip()
    password = getpass("Password: ")  # Hidden input

    if not database or not user:
        print("\nError: Database name and username are required.")
        input("\nPress Enter to exit...")
        sys.exit(1)

    return {
        'host': host,
        'port': port,
        'database': database,
        'user': user,
        'password': password
    }


def get_export_mode():
    """Prompt user to choose export mode."""
    print("\n" + "=" * 50)
    print("Export Mode Selection")
    print("=" * 50)
    print("\n1. Export SQL script only (schema creation)")
    print("2. Export all tables to CSV + SQL script (full export)")
    print()

    while True:
        choice = input("Select mode (1 or 2): ").strip()
        if choice == "1":
            return "sql_only"
        elif choice == "2":
            return "full"
        else:
            print("Invalid choice. Please enter 1 or 2.")


def test_connection(conn_params):
    """Test database connection."""
    try:
        conn = psycopg2.connect(**conn_params)
        conn.close()
        print("\n✓ Database connection successful!")
        return True
    except psycopg2.Error as e:
        print(f"\n✗ Connection failed: {e}")
        return False


def get_all_schemas(conn):
    """Retrieve all non-system schemas."""
    cursor = conn.cursor()
    query = """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        AND schema_name NOT LIKE 'pg_temp_%'
        AND schema_name NOT LIKE 'pg_toast_temp_%'
        ORDER BY schema_name;
    """
    cursor.execute(query)
    schemas = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return schemas


def get_all_tables(conn):
    """Retrieve all tables from all schemas (excluding system schemas)."""
    cursor = conn.cursor()
    query = """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
        AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name;
    """
    cursor.execute(query)
    tables = cursor.fetchall()
    cursor.close()
    return tables


def get_table_ddl(conn, schema, table):
    """Generate CREATE TABLE statement for a given table in PostgreSQL format."""
    cursor = conn.cursor()

    # Get table owner
    owner_query = """
        SELECT tableowner
        FROM pg_tables
        WHERE schemaname = %s AND tablename = %s;
    """
    cursor.execute(owner_query, (schema, table))
    owner_result = cursor.fetchone()
    owner = owner_result[0] if owner_result else None

    # Get tablespace
    tablespace_query = """
        SELECT t.spcname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_tablespace t ON t.oid = c.reltablespace
        WHERE n.nspname = %s AND c.relname = %s;
    """
    cursor.execute(tablespace_query, (schema, table))
    tablespace_result = cursor.fetchone()
    tablespace = tablespace_result[0] if tablespace_result and tablespace_result[0] else 'pg_default'

    # Get column definitions with collation
    column_query = """
        SELECT 
            c.column_name,
            c.data_type,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            c.is_nullable,
            c.column_default,
            c.collation_name
        FROM information_schema.columns c
        WHERE c.table_schema = %s AND c.table_name = %s
        ORDER BY c.ordinal_position;
    """
    cursor.execute(column_query, (schema, table))
    columns = cursor.fetchall()

    # Get primary key
    pk_query = """
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
        AND tc.table_schema = %s
        AND tc.table_name = %s
        ORDER BY kcu.ordinal_position;
    """
    cursor.execute(pk_query, (schema, table))
    pk_columns = [row[0] for row in cursor.fetchall()]

    # Get foreign keys
    fk_query = """
        SELECT
            kcu.column_name,
            ccu.table_schema AS foreign_table_schema,
            ccu.table_name AS foreign_table_name,
            ccu.column_name AS foreign_column_name,
            rc.update_rule,
            rc.delete_rule,
            tc.constraint_name
        FROM information_schema.table_constraints AS tc
        JOIN information_schema.key_column_usage AS kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage AS ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        JOIN information_schema.referential_constraints AS rc
            ON rc.constraint_name = tc.constraint_name
            AND rc.constraint_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s
        AND tc.table_name = %s;
    """
    cursor.execute(fk_query, (schema, table))
    foreign_keys = cursor.fetchall()

    # Get unique constraints
    unique_query = """
        SELECT 
            tc.constraint_name,
            string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) as columns
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = %s
        AND tc.table_name = %s
        GROUP BY tc.constraint_name;
    """
    cursor.execute(unique_query, (schema, table))
    unique_constraints = cursor.fetchall()

    # Get check constraints with proper quoting using pg_get_constraintdef
    check_query = """
        SELECT 
            con.conname as constraint_name,
            pg_get_constraintdef(con.oid) as check_clause
        FROM pg_constraint con
        JOIN pg_namespace nsp ON nsp.oid = con.connamespace
        JOIN pg_class cls ON cls.oid = con.conrelid
        WHERE con.contype = 'c'
        AND nsp.nspname = %s
        AND cls.relname = %s;
    """
    cursor.execute(check_query, (schema, table))
    check_constraints = cursor.fetchall()

    # Get indexes
    index_query = """
        SELECT
            i.relname as index_name,
            a.attname as column_name,
            am.amname as index_type,
            ix.indisunique as is_unique,
            pg_get_indexdef(i.oid) as index_definition
        FROM pg_class t
        JOIN pg_index ix ON t.oid = ix.indrelid
        JOIN pg_class i ON i.oid = ix.indexrelid
        JOIN pg_am am ON i.relam = am.oid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE t.relkind = 'r'
        AND n.nspname = %s
        AND t.relname = %s
        AND NOT ix.indisprimary
        ORDER BY i.relname;
    """
    cursor.execute(index_query, (schema, table))
    indexes = cursor.fetchall()

    cursor.close()

    # Build CREATE TABLE statement matching the example format
    ddl = f'-- Table: {schema}.{table}\n'
    ddl += f'-- DROP TABLE IF EXISTS {schema}.{table};\n\n'
    ddl += f'CREATE TABLE IF NOT EXISTS {schema}.{table}\n(\n'

    # Add columns
    column_defs = []
    for col in columns:
        col_name, data_type, char_len, num_prec, num_scale, is_nullable, col_default, collation = col

        # Build data type
        if data_type == 'character varying':
            type_def = 'character varying' + (f'({char_len})' if char_len else '')
        elif data_type == 'character':
            type_def = 'character' + (f'({char_len})' if char_len else '')
        elif data_type == 'numeric' and num_prec:
            if num_scale:
                type_def = f'numeric({num_prec},{num_scale})'
            else:
                type_def = f'numeric({num_prec})'
        elif data_type == 'timestamp without time zone':
            type_def = 'timestamp without time zone'
        elif data_type == 'timestamp with time zone':
            type_def = 'timestamp with time zone'
        elif data_type == 'time without time zone':
            type_def = 'time without time zone'
        elif data_type == 'time with time zone':
            type_def = 'time with time zone'
        elif data_type == 'double precision':
            type_def = 'double precision'
        else:
            type_def = data_type

        # Quote column name to handle reserved keywords
        col_def = f'    "{col_name}" {type_def}'

        # Add COLLATE if present
        if collation and collation != 'default':
            col_def += f' COLLATE pg_catalog."{collation}"'

        # Add DEFAULT
        if col_default:
            col_def += f' DEFAULT {col_default}'

        # Add NOT NULL
        if is_nullable == 'NO':
            col_def += ' NOT NULL'

        column_defs.append(col_def)

    # Add primary key inline if present
    if pk_columns:
        pk_cols = ', '.join([f'"{col}"' for col in pk_columns])
        column_defs.append(f'    PRIMARY KEY ({pk_cols})')

    # Add unique constraints inline
    for constraint_name, columns_str in unique_constraints:
        # Quote each column name in the constraint
        quoted_cols = ', '.join([f'"{col.strip()}"' for col in columns_str.split(',')])
        column_defs.append(f'    CONSTRAINT "{constraint_name}" UNIQUE ({quoted_cols})')

    # Add check constraints inline
    for constraint_name, check_clause in check_constraints:
        # pg_get_constraintdef returns "CHECK (condition)" so we use it as-is
        column_defs.append(f'    CONSTRAINT "{constraint_name}" {check_clause}')

    ddl += ',\n'.join(column_defs)
    ddl += f'\n)\n\nTABLESPACE {tablespace};\n\n'

    # Add ALTER TABLE OWNER
    if owner:
        ddl += f'ALTER TABLE IF EXISTS {schema}.{table}\n'
        ddl += f'    OWNER to {owner};\n'

    # Add foreign keys as separate ALTER TABLE statements
    if foreign_keys:
        ddl += '\n'
        fk_dict = {}
        for fk in foreign_keys:
            col_name, fk_schema, fk_table, fk_col, update_rule, delete_rule, constraint_name = fk
            if constraint_name not in fk_dict:
                fk_dict[constraint_name] = {
                    'columns': [],
                    'fk_schema': fk_schema,
                    'fk_table': fk_table,
                    'fk_columns': [],
                    'update_rule': update_rule,
                    'delete_rule': delete_rule
                }
            fk_dict[constraint_name]['columns'].append(col_name)
            fk_dict[constraint_name]['fk_columns'].append(fk_col)

        for constraint_name, fk_info in fk_dict.items():
            cols = ', '.join([f'"{c}"' for c in fk_info['columns']])
            fk_cols = ', '.join([f'"{c}"' for c in fk_info['fk_columns']])
            ddl += f'ALTER TABLE IF EXISTS {schema}.{table}\n'
            ddl += f'    ADD CONSTRAINT "{constraint_name}" FOREIGN KEY ({cols})\n'
            ddl += f'    REFERENCES {fk_info["fk_schema"]}.{fk_info["fk_table"]} ({fk_cols}) MATCH SIMPLE'
            if fk_info['update_rule'] != 'NO ACTION':
                ddl += f'\n    ON UPDATE {fk_info["update_rule"]}'
            if fk_info['delete_rule'] != 'NO ACTION':
                ddl += f'\n    ON DELETE {fk_info["delete_rule"]}'
            ddl += ';\n\n'

    # Add indexes
    if indexes:
        ddl += '\n'
        seen_indexes = set()
        for index_name, col_name, index_type, is_unique, index_def in indexes:
            if index_name not in seen_indexes and not is_unique:
                ddl += f'{index_def};\n'
                seen_indexes.add(index_name)

    return ddl


def generate_create_script(conn, schemas, tables):
    """Generate complete SQL script to create all schemas and tables."""
    script = f"""-- PostgreSQL Database Schema Export
-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Database: {conn.get_dsn_parameters()['dbname']}

"""

    # Add schemas
    script += "-- ============================================\n"
    script += "-- SCHEMAS\n"
    script += "-- ============================================\n\n"

    for schema in schemas:
        if schema != 'public':  # public schema already exists
            script += f'CREATE SCHEMA IF NOT EXISTS "{schema}";\n'

    script += "\n"

    # Add tables
    script += "-- ============================================\n"
    script += "-- TABLES\n"
    script += "-- ============================================\n\n"

    for schema, table in tables:
        print(f"Generating DDL for {schema}.{table}...")
        try:
            table_ddl = get_table_ddl(conn, schema, table)
            script += f"-- Table: {schema}.{table}\n"
            script += table_ddl
            script += "\n"
        except Exception as e:
            script += f"-- ERROR generating DDL for {schema}.{table}: {str(e)}\n\n"

    return script


def export_table_to_csv(conn, schema, table, output_dir):
    """Export a single table to CSV file."""
    cursor = conn.cursor()
    filename = f"{schema}_{table}.csv"
    filepath = os.path.join(output_dir, filename)

    try:
        # Get all data from table
        query = f'SELECT * FROM "{schema}"."{table}"'
        cursor.execute(query)

        # Get column names
        column_names = [desc[0] for desc in cursor.description]

        # Write to CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(column_names)  # Write header

            # Write data in batches to handle large tables
            while True:
                rows = cursor.fetchmany(1000)
                if not rows:
                    break
                writer.writerows(rows)

        cursor.close()
        return filename, True, None

    except Exception as e:
        cursor.close()
        return filename, False, str(e)


def create_zip_archive(source_dir, output_filename, sql_script=None):
    """Create a ZIP archive from all CSV files in the directory and the SQL script."""
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add CSV files
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.endswith('.csv'):
                    filepath = os.path.join(root, file)
                    zipf.write(filepath, file)

        # Add SQL script if provided
        if sql_script:
            zipf.writestr('schema_create.sql', sql_script)

    return output_filename


def cleanup_temp_files(temp_dir):
    """Remove temporary CSV files."""
    try:
        for file in os.listdir(temp_dir):
            if file.endswith('.csv'):
                os.remove(os.path.join(temp_dir, file))
        os.rmdir(temp_dir)
    except:
        pass


def main():
    # Get output directory from command line argument or use current directory
    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
        # If it's a file path, get the directory
        if os.path.isfile(output_dir):
            output_dir = os.path.dirname(output_dir)
    else:
        output_dir = os.getcwd()

    # Ensure output directory exists
    if not os.path.exists(output_dir):
        output_dir = os.getcwd()

    print(f"\nOutput directory: {output_dir}\n")

    # Get connection information
    conn_params = get_connection_info()

    # Test connection
    if not test_connection(conn_params):
        input("\nPress Enter to exit...")
        sys.exit(1)

    # Get export mode
    export_mode = get_export_mode()

    # Connect to database
    try:
        conn = psycopg2.connect(**conn_params)
        print(f"\nConnected to database: {conn_params['database']}")

        # Get all schemas
        schemas = get_all_schemas(conn)
        print(f"\nFound {len(schemas)} schema(s): {', '.join(schemas)}")

        # Get all tables
        tables = get_all_tables(conn)

        if not tables:
            print("\n✗ No tables found in the database.")
            conn.close()
            input("\nPress Enter to exit...")
            sys.exit(1)

        print(f"Found {len(tables)} table(s).\n")

        # Generate SQL script
        print("=" * 50)
        print("Generating SQL schema creation script...")
        print("-" * 50)
        sql_script = generate_create_script(conn, schemas, tables)
        print("✓ SQL script generated successfully!\n")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        if export_mode == "sql_only":
            # Only export SQL script
            sql_filename = f"{conn_params['database']}_schema_{timestamp}.sql"
            sql_filepath = os.path.join(output_dir, sql_filename)

            with open(sql_filepath, 'w', encoding='utf-8') as f:
                f.write(sql_script)

            conn.close()

            # Summary
            print("=" * 50)
            print("Export Summary:")
            print(f"  Mode: SQL Schema Only")
            print(f"  Output file: {sql_filename}")
            print(f"  Location: {os.path.abspath(sql_filepath)}")
            print("=" * 50)

        else:  # full export
            # Create temporary directory for CSV files
            temp_dir = os.path.join(output_dir, f"temp_export_{timestamp}")
            os.makedirs(temp_dir, exist_ok=True)

            # Export each table
            successful = 0
            failed = 0

            print("=" * 50)
            print("Exporting tables:")
            print("-" * 50)

            for schema, table in tables:
                print(f"Exporting {schema}.{table}...", end=" ")
                filename, success, error = export_table_to_csv(conn, schema, table, temp_dir)

                if success:
                    print("✓")
                    successful += 1
                else:
                    print(f"✗ ({error})")
                    failed += 1

            conn.close()

            # Create ZIP archive in the output directory
            zip_filename = f"{conn_params['database']}_export_{timestamp}.zip"
            zip_filepath = os.path.join(output_dir, zip_filename)

            print("\n" + "-" * 50)
            print(f"Creating ZIP archive: {zip_filename}...")
            create_zip_archive(temp_dir, zip_filepath, sql_script)

            # Cleanup temporary files
            cleanup_temp_files(temp_dir)

            # Summary
            print("\n" + "=" * 50)
            print("Export Summary:")
            print(f"  Mode: Full Export (CSV + SQL)")
            print(f"  Successful: {successful} table(s)")
            print(f"  Failed: {failed} table(s)")
            print(f"  SQL Script: schema_create.sql (included in ZIP)")
            print(f"  Output file: {zip_filename}")
            print(f"  Location: {os.path.abspath(zip_filepath)}")
            print("=" * 50)

        input("\nExport completed! Press Enter to exit...")

    except psycopg2.Error as e:
        print(f"\nDatabase error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        input("\nPress Enter to exit...")
        sys.exit(1)


if __name__ == "__main__":
    main()
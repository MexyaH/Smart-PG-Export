#!/usr/bin/env python3
"""
PostgreSQL Database Table Export Tool - GUI Edition
Exports all tables from a PostgreSQL database to CSV files in a ZIP archive.
Also generates a SQL script to recreate all schemas and tables.
Auto-increment columns (SERIAL / IDENTITY) are correctly detected and
re-emitted using GENERATED ... AS IDENTITY syntax.

Can be called from a Windows context menu passing a target folder as argv[1];
that folder is pre-filled as the output directory.
"""

import utils.session
import os
import sys
import csv
import queue
import zipfile
import threading
import traceback
from datetime import datetime

import psycopg2

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext


# ----------------------------------------------------------------------
# Database / DDL logic (unchanged in spirit from the CLI version, with
# identity-column detection added)
# ----------------------------------------------------------------------

def get_all_schemas(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        AND schema_name NOT LIKE 'pg_temp_%'
        AND schema_name NOT LIKE 'pg_toast_temp_%'
        ORDER BY schema_name;
    """)
    schemas = [row[0] for row in cursor.fetchall()]
    cursor.close()
    return schemas


def get_all_tables(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_type = 'BASE TABLE'
        AND table_schema NOT IN ('pg_catalog', 'information_schema')
        ORDER BY table_schema, table_name;
    """)
    tables = cursor.fetchall()
    cursor.close()
    return tables


def get_table_ddl(conn, schema, table):
    """Generate a CREATE TABLE statement for a given table, correctly
    marking auto-increment columns (SERIAL and GENERATED ... AS IDENTITY)."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT tableowner FROM pg_tables
        WHERE schemaname = %s AND tablename = %s;
    """, (schema, table))
    owner_result = cursor.fetchone()
    owner = owner_result[0] if owner_result else None

    cursor.execute("""
        SELECT t.spcname
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_tablespace t ON t.oid = c.reltablespace
        WHERE n.nspname = %s AND c.relname = %s;
    """, (schema, table))
    tablespace_result = cursor.fetchone()
    tablespace = tablespace_result[0] if tablespace_result and tablespace_result[0] else 'pg_default'

    # is_identity / identity_generation tell us if a column is a real
    # PostgreSQL IDENTITY column (GENERATED ALWAYS/BY DEFAULT AS IDENTITY).
    # column_default catching 'nextval(...)' tells us if it's an
    # old-style SERIAL column tied to a sequence.
    cursor.execute("""
        SELECT
            c.column_name,
            c.data_type,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            c.is_nullable,
            c.column_default,
            c.collation_name,
            c.is_identity,
            c.identity_generation
        FROM information_schema.columns c
        WHERE c.table_schema = %s AND c.table_name = %s
        ORDER BY c.ordinal_position;
    """, (schema, table))
    columns = cursor.fetchall()

    cursor.execute("""
        SELECT kcu.column_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'PRIMARY KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
        ORDER BY kcu.ordinal_position;
    """, (schema, table))
    pk_columns = [row[0] for row in cursor.fetchall()]

    cursor.execute("""
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
        AND tc.table_schema = %s AND tc.table_name = %s;
    """, (schema, table))
    foreign_keys = cursor.fetchall()

    cursor.execute("""
        SELECT
            tc.constraint_name,
            string_agg(kcu.column_name, ', ' ORDER BY kcu.ordinal_position) as columns
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        WHERE tc.constraint_type = 'UNIQUE'
        AND tc.table_schema = %s AND tc.table_name = %s
        GROUP BY tc.constraint_name;
    """, (schema, table))
    unique_constraints = cursor.fetchall()

    cursor.execute("""
        SELECT
            con.conname as constraint_name,
            pg_get_constraintdef(con.oid) as check_clause
        FROM pg_constraint con
        JOIN pg_namespace nsp ON nsp.oid = con.connamespace
        JOIN pg_class cls ON cls.oid = con.conrelid
        WHERE con.contype = 'c'
        AND nsp.nspname = %s AND cls.relname = %s;
    """, (schema, table))
    check_constraints = cursor.fetchall()

    cursor.execute("""
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
        AND n.nspname = %s AND t.relname = %s
        AND NOT ix.indisprimary
        ORDER BY i.relname;
    """, (schema, table))
    indexes = cursor.fetchall()

    cursor.close()

    ddl = f'-- Table: {schema}.{table}\n'
    ddl += f'-- DROP TABLE IF EXISTS {schema}.{table};\n\n'
    ddl += f'CREATE TABLE IF NOT EXISTS {schema}.{table}\n(\n'

    column_defs = []
    for col in columns:
        (col_name, data_type, char_len, num_prec, num_scale, is_nullable,
         col_default, collation, is_identity, identity_generation) = col

        if data_type == 'character varying':
            type_def = 'character varying' + (f'({char_len})' if char_len else '')
        elif data_type == 'character':
            type_def = 'character' + (f'({char_len})' if char_len else '')
        elif data_type == 'numeric' and num_prec:
            type_def = f'numeric({num_prec},{num_scale})' if num_scale else f'numeric({num_prec})'
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

        col_def = f'    "{col_name}" {type_def}'

        if collation and collation != 'default':
            col_def += f' COLLATE pg_catalog."{collation}"'

        # --- Auto-increment handling ---------------------------------
        is_serial_sequence = bool(col_default) and 'nextval(' in col_default

        if is_identity == 'YES':
            # True IDENTITY column (Postgres 10+ style).
            gen_mode = 'ALWAYS' if identity_generation == 'ALWAYS' else 'BY DEFAULT'
            col_def += f' GENERATED {gen_mode} AS IDENTITY'
        elif is_serial_sequence:
            # Old-style SERIAL/BIGSERIAL backed by an owned sequence.
            # Keep the DEFAULT nextval(...) so the sequence link is
            # preserved, and flag it clearly with a trailing comment.
            col_def += f' DEFAULT {col_default}  -- auto-increment (SERIAL)'
        elif col_default:
            col_def += f' DEFAULT {col_default}'

        if is_nullable == 'NO':
            col_def += ' NOT NULL'

        column_defs.append(col_def)

    if pk_columns:
        pk_cols = ', '.join(f'"{c}"' for c in pk_columns)
        column_defs.append(f'    PRIMARY KEY ({pk_cols})')

    for constraint_name, columns_str in unique_constraints:
        quoted_cols = ', '.join(f'"{c.strip()}"' for c in columns_str.split(','))
        column_defs.append(f'    CONSTRAINT "{constraint_name}" UNIQUE ({quoted_cols})')

    for constraint_name, check_clause in check_constraints:
        column_defs.append(f'    CONSTRAINT "{constraint_name}" {check_clause}')

    ddl += ',\n'.join(column_defs)
    ddl += f'\n)\n\nTABLESPACE {tablespace};\n\n'

    if owner:
        ddl += f'ALTER TABLE IF EXISTS {schema}.{table}\n'
        ddl += f'    OWNER to {owner};\n'

    if foreign_keys:
        ddl += '\n'
        fk_dict = {}
        for col_name, fk_schema, fk_table, fk_col, update_rule, delete_rule, constraint_name in foreign_keys:
            entry = fk_dict.setdefault(constraint_name, {
                'columns': [], 'fk_schema': fk_schema, 'fk_table': fk_table,
                'fk_columns': [], 'update_rule': update_rule, 'delete_rule': delete_rule
            })
            entry['columns'].append(col_name)
            entry['fk_columns'].append(fk_col)

        for constraint_name, info in fk_dict.items():
            cols = ', '.join(f'"{c}"' for c in info['columns'])
            fk_cols = ', '.join(f'"{c}"' for c in info['fk_columns'])
            ddl += f'ALTER TABLE IF EXISTS {schema}.{table}\n'
            ddl += f'    ADD CONSTRAINT "{constraint_name}" FOREIGN KEY ({cols})\n'
            ddl += f'    REFERENCES {info["fk_schema"]}.{info["fk_table"]} ({fk_cols}) MATCH SIMPLE'
            if info['update_rule'] != 'NO ACTION':
                ddl += f'\n    ON UPDATE {info["update_rule"]}'
            if info['delete_rule'] != 'NO ACTION':
                ddl += f'\n    ON DELETE {info["delete_rule"]}'
            ddl += ';\n\n'

    if indexes:
        ddl += '\n'
        seen = set()
        for index_name, col_name, index_type, is_unique, index_def in indexes:
            if index_name not in seen and not is_unique:
                ddl += f'{index_def};\n'
                seen.add(index_name)

    return ddl


def generate_create_script(conn, schemas, tables, log):
    script = f"""-- PostgreSQL Database Schema Export
-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
-- Database: {conn.get_dsn_parameters()['dbname']}

"""
    script += "-- ============================================\n"
    script += "-- SCHEMAS\n"
    script += "-- ============================================\n\n"
    for schema in schemas:
        if schema != 'public':
            script += f'CREATE SCHEMA IF NOT EXISTS "{schema}";\n'
    script += "\n"

    script += "-- ============================================\n"
    script += "-- TABLES\n"
    script += "-- ============================================\n\n"

    for schema, table in tables:
        log(f"Generating DDL for {schema}.{table} ...")
        try:
            table_ddl = get_table_ddl(conn, schema, table)
            script += f"-- Table: {schema}.{table}\n"
            script += table_ddl
            script += "\n"
        except Exception as e:
            script += f"-- ERROR generating DDL for {schema}.{table}: {e}\n\n"

    return script


def export_table_to_csv(conn, schema, table, output_dir):
    cursor = conn.cursor()
    filename = f"{schema}_{table}.csv"
    filepath = os.path.join(output_dir, filename)
    try:
        cursor.execute(f'SELECT * FROM "{schema}"."{table}"')
        column_names = [desc[0] for desc in cursor.description]
        with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(column_names)
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
    with zipfile.ZipFile(output_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source_dir):
            for file in files:
                if file.endswith('.csv'):
                    zipf.write(os.path.join(root, file), file)
        if sql_script:
            zipf.writestr('schema_create.sql', sql_script)
    return output_filename


def cleanup_temp_files(temp_dir):
    try:
        for file in os.listdir(temp_dir):
            if file.endswith('.csv'):
                os.remove(os.path.join(temp_dir, file))
        os.rmdir(temp_dir)
    except Exception:
        pass


# ----------------------------------------------------------------------
# GUI
# ----------------------------------------------------------------------

BG = "#1e1e2e"
PANEL = "#2a2a3d"
ACCENT = "#7c9cff"
ACCENT_DARK = "#5b7ce0"
TEXT = "#e8e8f0"
SUBTEXT = "#9a9ab0"
GREEN = "#7ed6a5"
RED = "#ff7676"

FONT = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_TITLE = ("Segoe UI", 15, "bold")


class ExportApp(tk.Tk):
    def __init__(self, initial_output_dir):
        super().__init__()
        self.title("PostgreSQL Export Tool")
        self.geometry("640x680")
        self.minsize(600, 640)
        self.configure(bg=BG)

        self.log_queue = queue.Queue()
        self.worker_thread = None

        self._build_style()
        self._build_layout(initial_output_dir)
        self.after(100, self._poll_log_queue)

    # -- styling ---------------------------------------------------
    def _build_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT, font=FONT)
        style.configure("Sub.TLabel", background=PANEL, foreground=SUBTEXT, font=FONT)
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=FONT_TITLE)
        style.configure("TEntry", fieldbackground="#3a3a52", foreground=TEXT, insertcolor=TEXT)
        style.configure("TRadiobutton", background=PANEL, foreground=TEXT, font=FONT)
        style.map("TRadiobutton", background=[("active", PANEL)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#101018",
                        font=FONT_BOLD, padding=8, borderwidth=0)
        style.map("Accent.TButton", background=[("active", ACCENT_DARK)])
        style.configure("Ghost.TButton", background=PANEL, foreground=TEXT,
                        font=FONT, padding=6, borderwidth=1)
        style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL)

    # -- layout ------------------------------------------------------
    def _build_layout(self, initial_output_dir):
        outer = ttk.Frame(self, style="TFrame", padding=18)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="PostgreSQL Export Tool", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Export tables to CSV/ZIP and generate a full schema SQL script",
                  style="TLabel", foreground=SUBTEXT).pack(anchor="w", pady=(0, 14))

        # --- Connection panel ---
        conn_panel = tk.Frame(outer, bg=PANEL, padx=16, pady=14)
        conn_panel.pack(fill="x", pady=(0, 12))
        ttk.Label(conn_panel, text="Connection", style="Panel.TLabel", font=FONT_BOLD).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self.host_var = tk.StringVar(value="localhost")
        self.port_var = tk.StringVar(value="5432")
        self.db_var = tk.StringVar()
        self.user_var = tk.StringVar()
        self.pass_var = tk.StringVar()

        self._grid_field(conn_panel, "Host", self.host_var, 1, 0)
        self._grid_field(conn_panel, "Port", self.port_var, 1, 2)
        self._grid_field(conn_panel, "Database", self.db_var, 3, 0, columnspan=3)
        self._grid_field(conn_panel, "Username", self.user_var, 5, 0)
        self._grid_field(conn_panel, "Password", self.pass_var, 5, 2, show="*")

        for c in range(4):
            conn_panel.grid_columnconfigure(c, weight=1)

        btn_row = tk.Frame(conn_panel, bg=PANEL)
        btn_row.grid(row=7, column=0, columnspan=4, sticky="w", pady=(12, 0))
        ttk.Button(btn_row, text="Test Connection", style="Ghost.TButton",
                   command=self.test_connection).pack(side="left")
        self.conn_status = ttk.Label(btn_row, text="", style="Panel.TLabel")
        self.conn_status.pack(side="left", padx=10)

        # --- Export options panel ---
        opt_panel = tk.Frame(outer, bg=PANEL, padx=16, pady=14)
        opt_panel.pack(fill="x", pady=(0, 12))
        ttk.Label(opt_panel, text="Export Options", style="Panel.TLabel", font=FONT_BOLD).pack(anchor="w", pady=(0, 8))

        self.mode_var = tk.StringVar(value="full")
        ttk.Radiobutton(opt_panel, text="SQL schema script only", variable=self.mode_var,
                        value="sql_only", style="TRadiobutton").pack(anchor="w")
        ttk.Radiobutton(opt_panel, text="Full export (CSV data + SQL schema, zipped)",
                        variable=self.mode_var, value="full", style="TRadiobutton").pack(anchor="w", pady=(4, 10))

        dir_row = tk.Frame(opt_panel, bg=PANEL)
        dir_row.pack(fill="x")
        ttk.Label(dir_row, text="Output folder:", style="Panel.TLabel").pack(side="left")
        self.output_dir_var = tk.StringVar(value=initial_output_dir)
        entry = tk.Entry(dir_row, textvariable=self.output_dir_var, bg="#3a3a52", fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=FONT)
        entry.pack(side="left", fill="x", expand=True, padx=8, ipady=3)
        ttk.Button(dir_row, text="Browse...", style="Ghost.TButton",
                   command=self.browse_output_dir).pack(side="left")

        # --- Action button + progress ---
        action_row = tk.Frame(outer, bg=BG)
        action_row.pack(fill="x", pady=(4, 10))
        self.start_btn = ttk.Button(action_row, text="Start Export", style="Accent.TButton",
                                     command=self.start_export)
        self.start_btn.pack(side="left")
        self.status_label = ttk.Label(action_row, text="Ready", style="TLabel", foreground=SUBTEXT)
        self.status_label.pack(side="left", padx=12)

        self.progress = ttk.Progressbar(outer, mode="determinate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(0, 10))

        # --- Log panel ---
        ttk.Label(outer, text="Log", style="TLabel", font=FONT_BOLD).pack(anchor="w")
        self.log_box = scrolledtext.ScrolledText(
            outer, height=14, bg="#14141f", fg=TEXT, insertbackground=TEXT,
            font=("Consolas", 9), relief="flat", wrap="word")
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))
        self.log_box.configure(state="disabled")

    def _grid_field(self, parent, label, var, row, col, columnspan=1, show=None):
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(
            row=row, column=col, columnspan=columnspan, sticky="w", pady=(8, 2))
        entry = tk.Entry(parent, textvariable=var, bg="#3a3a52", fg=TEXT,
                         insertbackground=TEXT, relief="flat", font=FONT, show=show)
        entry.grid(row=row + 1, column=col, columnspan=columnspan, sticky="ew",
                   padx=(0, 10), pady=(0, 8), ipady=4)

    # -- helpers ------------------------------------------------------
    def browse_output_dir(self):
        chosen = filedialog.askdirectory(initialdir=self.output_dir_var.get() or os.getcwd())
        if chosen:
            self.output_dir_var.set(chosen)

    def _conn_params(self):
        return {
            'host': self.host_var.get().strip() or "localhost",
            'port': self.port_var.get().strip() or "5432",
            'database': self.db_var.get().strip(),
            'user': self.user_var.get().strip(),
            'password': self.pass_var.get(),
        }

    def log(self, message):
        self.log_queue.put(message)

    def _poll_log_queue(self):
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", message + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def set_status(self, text, color=SUBTEXT):
        self.status_label.configure(text=text, foreground=color)

    # -- actions ------------------------------------------------------
    def test_connection(self):
        params = self._conn_params()
        if not params['database'] or not params['user']:
            messagebox.showwarning("Missing info", "Database name and username are required.")
            return
        self.conn_status.configure(text="Testing...", foreground=SUBTEXT)
        self.update_idletasks()
        try:
            conn = psycopg2.connect(**params)
            conn.close()
            self.conn_status.configure(text="✓ Connected", foreground=GREEN)
        except psycopg2.Error as e:
            self.conn_status.configure(text="✗ Failed", foreground=RED)
            messagebox.showerror("Connection failed", str(e))

    def start_export(self):
        if self.worker_thread and self.worker_thread.is_alive():
            return

        params = self._conn_params()
        if not params['database'] or not params['user']:
            messagebox.showwarning("Missing info", "Database name and username are required.")
            return

        output_dir = self.output_dir_var.get().strip() or os.getcwd()
        if not os.path.isdir(output_dir):
            messagebox.showwarning("Invalid folder", "Please choose a valid output folder.")
            return

        mode = self.mode_var.get()
        self.start_btn.configure(state="disabled")
        self.progress.configure(value=0, mode="indeterminate")
        self.progress.start(12)
        self.set_status("Working...", ACCENT)

        self.worker_thread = threading.Thread(
            target=self._run_export, args=(params, mode, output_dir), daemon=True)
        self.worker_thread.start()

    def _run_export(self, params, mode, output_dir):
        try:
            conn = psycopg2.connect(**params)
            self.log(f"Connected to database: {params['database']}")

            schemas = get_all_schemas(conn)
            self.log(f"Found {len(schemas)} schema(s): {', '.join(schemas)}")

            tables = get_all_tables(conn)
            if not tables:
                self.log("No tables found in the database.")
                conn.close()
                self._finish(False, "No tables found.")
                return
            self.log(f"Found {len(tables)} table(s).")

            self.log("Generating SQL schema creation script...")
            sql_script = generate_create_script(conn, schemas, tables, self.log)
            self.log("SQL script generated successfully.")

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

            if mode == "sql_only":
                sql_filename = f"{params['database']}_schema_{timestamp}.sql"
                sql_filepath = os.path.join(output_dir, sql_filename)
                with open(sql_filepath, 'w', encoding='utf-8') as f:
                    f.write(sql_script)
                conn.close()
                self.log(f"Saved: {sql_filepath}")
                self._finish(True, f"Done — {sql_filename}")
            else:
                temp_dir = os.path.join(output_dir, f"temp_export_{timestamp}")
                os.makedirs(temp_dir, exist_ok=True)

                successful, failed = 0, 0
                for schema, table in tables:
                    filename, ok, error = export_table_to_csv(conn, schema, table, temp_dir)
                    if ok:
                        self.log(f"Exported {schema}.{table} -> {filename}")
                        successful += 1
                    else:
                        self.log(f"FAILED {schema}.{table}: {error}")
                        failed += 1

                conn.close()

                zip_filename = f"{params['database']}_export_{timestamp}.zip"
                zip_filepath = os.path.join(output_dir, zip_filename)
                self.log(f"Creating ZIP archive: {zip_filename} ...")
                create_zip_archive(temp_dir, zip_filepath, sql_script)
                cleanup_temp_files(temp_dir)

                self.log(f"Saved: {zip_filepath}")
                self.log(f"Tables exported: {successful} ok, {failed} failed")
                self._finish(True, f"Done — {zip_filename}")

        except psycopg2.Error as e:
            self.log(f"Database error: {e}")
            self._finish(False, "Database error")
        except Exception as e:
            self.log(f"Unexpected error: {e}")
            self.log(traceback.format_exc())
            self._finish(False, "Unexpected error")

    def _finish(self, success, message):
        def update():
            self.progress.stop()
            self.progress.configure(mode="determinate", value=100 if success else 0)
            self.start_btn.configure(state="normal")
            self.set_status(message, GREEN if success else RED)
            if success:
                messagebox.showinfo("Export complete", message)
        self.after(0, update)


def main():
    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
        if os.path.isfile(output_dir):
            output_dir = os.path.dirname(output_dir)
    else:
        output_dir = os.getcwd()

    if not os.path.isdir(output_dir):
        output_dir = os.getcwd()

    app = ExportApp(output_dir)
    app.mainloop()


if __name__ == "__main__":
    main()
import sqlite3
import os
import sys
from flask import g

DB_PATH = None
_db_initialized = False


def _resolve_db_path():
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, "library.db")


def get_db():
    """Return thread-local DB connection."""
    global DB_PATH, _db_initialized

    if "db" not in g:
        if DB_PATH is None:
            DB_PATH = _resolve_db_path()

        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row

        # run migrations only once
        if not _db_initialized:
            _initialize_tables(g.db)
            _db_initialized = True

    return g.db


def get_cursor():
    return get_db().cursor()


def close_db(e=None):
    """Close DB connection at request end."""
    db = g.pop("db", None)
    if db:
        db.close()


def init_db():
    """
    This function is called on app startup to create tables OR ensure that
    the first database connection initializes the schema.
    """
    global DB_PATH, _db_initialized

    DB_PATH = _resolve_db_path()

    # Manually create a connection to run initialization immediately
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    _initialize_tables(conn)

    conn.close()

    _db_initialized = True


def _initialize_tables(conn):
    """
    All CREATE TABLE and ALTER TABLE logic goes here.
    Keeps blueprint files clean.
    """
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Login(
            name TEXT,
            userid TEXT,
            password INTEGER,
            branch TEXT,
            mobile INTEGER,
            email TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Book(
            subject TEXT,
            title TEXT,
            author TEXT,
            serial INTEGER PRIMARY KEY,
            book_id TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS BookIssue(
            stdid TEXT,
            serial TEXT,
            issue DATE,
            exp DATE,
            book_id TEXT,
            assigned_by TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS BookReturn(
            stdid TEXT,
            title TEXT,
            copies INTEGER,
            issue DATE,
            returned DATE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS BookReturnDetail(
            stdid TEXT,
            title TEXT,
            book_id TEXT,
            issue DATE,
            returned DATE,
            returned_by TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DeletedLogin(
            name TEXT,
            userid TEXT,
            deleted DATE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS DeletedBook(
            subject TEXT,
            title TEXT,
            author TEXT,
            book_id TEXT,
            deleted DATE
        )
    """)

    conn.commit()
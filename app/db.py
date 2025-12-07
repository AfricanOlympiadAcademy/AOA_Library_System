# app/db.py
import os
import sys
import sqlite3 as sqlite
from flask import g
from datetime import datetime

DB_PATH = None
_db_initialized = False


def _resolve_db_path():
    """
    Decide where library.db lives.
    NOTE: Now it will live next to this file (app/library.db).
    Move your existing library.db there or adjust this path if needed.
    """
    global DB_PATH
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, 'library.db')


def get_db():
    """Get database connection (per-request)"""
    global DB_PATH, _db_initialized

    if 'db' not in g:
        if DB_PATH is None:
            DB_PATH = _resolve_db_path()

        g.db = sqlite.connect(DB_PATH)
        g.db.row_factory = sqlite.Row

        # Initialize db schema once
        if not _db_initialized:
            cur = g.db.cursor()

            # Create tables if they don't exist
            cur.execute('CREATE TABLE IF NOT EXISTS Login(name TEXT, userid TEXT, password INTEGER, branch TEXT, mobile INTEGER)')
            cur.execute('CREATE TABLE IF NOT EXISTS Book(subject TEXT, title TEXT, author TEXT, serial INTEGER PRIMARY KEY)')
            cur.execute('CREATE TABLE IF NOT EXISTS BookIssue(stdid TEXT, serial TEXT, issue DATE, exp DATE)')
            cur.execute('CREATE TABLE IF NOT EXISTS BookReturn(stdid TEXT, title TEXT, copies INTEGER, issue DATE, returned DATE)')
            cur.execute('CREATE TABLE IF NOT EXISTS BookReturnDetail(stdid TEXT, title TEXT, book_id TEXT, issue DATE, returned DATE)')
            cur.execute('CREATE TABLE IF NOT EXISTS DeletedLogin(name TEXT, userid TEXT, deleted DATE)')
            cur.execute('CREATE TABLE IF NOT EXISTS DeletedBook(subject TEXT, title TEXT, author TEXT, book_id TEXT, deleted DATE)')
            g.db.commit()

            # Helper to check columns
            def _table_columns(name: str):
                cur.execute("PRAGMA table_info('%s')" % (name,))
                return [r[1] for r in cur.fetchall()]

            # Book table extra columns
            book_cols = _table_columns('Book')
            if 'book_id' not in book_cols:
                cur.execute("ALTER TABLE Book ADD COLUMN book_id TEXT")
                g.db.commit()
                cur.execute("UPDATE Book SET book_id = CAST(serial AS TEXT) WHERE book_id IS NULL OR book_id = ''")
                g.db.commit()
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_book_book_id ON Book(book_id)")
                g.db.commit()

            # BookIssue table extra columns
            issue_cols = _table_columns('BookIssue')
            if 'book_id' not in issue_cols:
                cur.execute("ALTER TABLE BookIssue ADD COLUMN book_id TEXT")
                g.db.commit()
                cur.execute(
                    "UPDATE BookIssue SET book_id = (SELECT b.book_id FROM Book b WHERE b.serial = BookIssue.serial) "
                    "WHERE book_id IS NULL"
                )
                g.db.commit()
            if 'assigned_by' not in _table_columns('BookIssue'):
                cur.execute("ALTER TABLE BookIssue ADD COLUMN assigned_by TEXT")
                g.db.commit()

            # Login extra email column
            login_cols = _table_columns('Login')
            if 'email' not in login_cols:
                cur.execute("ALTER TABLE Login ADD COLUMN email TEXT")
                g.db.commit()

            # BookReturnDetail extra returned_by
            return_detail_cols = _table_columns('BookReturnDetail')
            if 'returned_by' not in return_detail_cols:
                cur.execute("ALTER TABLE BookReturnDetail ADD COLUMN returned_by TEXT")
                g.db.commit()

            g.db.commit()
            _db_initialized = True

    return g.db


def get_cursor():
    """Shortcut to get a cursor"""
    return get_db().cursor()


def close_db(error=None):
    """Close db at end of request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def populate_initial_students():
    """Populate initial student data if not already present"""
    db = get_db()
    cur = get_cursor()
    initial_students = [
        ('Kesha', 'Wanjare', 'wanjare.k@aoa.school'),
        ('Esther', 'Apendi', 'apendi.e@aoa.school'),
        ('Ethan', 'Mutyaba', 'mutyaba.e@aoa.school'),
        ('Baruch', 'Rugero', 'rugero.b@aoa.school'),
        ('Tokollo', 'Shaku', 'shaku.t@aoa.school'),
        ('Tumi', 'Nyagiro', 'nyagiro.t@aoa.school'),
        ('Imelda', 'Ikuzwe', 'ikuzwe.i@aoa.school'),
        ('Baraka', 'Mulwa', 'mulwa.b@aoa.school'),
        ('Sweetbert', 'Nene', 'nene.s@aoa.school'),
        ('Flora', 'Ineza', 'ineza.f@aoa.school'),
        ('Sonia', 'Keza', 'keza.s@aoa.school'),
        ('Lightness', 'Ngilule', 'ngilule.l@aoa.school'),
        ('Margaret', 'Angel', 'angel.m@aoa.school'),
        ('Herve', 'Uwayezu', 'uwayezu.h@aoa.school'),
        ('Elizabeth', 'Musiimenta', 'musiimenta.e@aoa.school'),
        ('Nathan', 'Khiisa', 'khiisa.n@aoa.school'),
        ('Joyce', 'Sulumo', 'sulumo.j@aoa.school'),
        ('Denys', 'Tuyisenge', 'tuyisenge.d@aoa.school'),
        ('Jayden', 'Osago', 'osago.j@aoa.school'),
        ('Roland', 'Ndjamba', 'ndjamba.r@aoa.school'),
        ('Andile', 'Kebopetswe', 'kebopetswe.a@aoa.school'),
        ('Stephanie', 'Kwenantsi', 'kwenantsi.s@aoa.school'),
        ('Helena', 'Haikali', 'haikali.h@aoa.school'),
        ('Anton', 'Wakele', 'wakele.a@aoa.school'),
        ('Lebone', 'Tau', 'tau.l@aoa.school'),
        ('Prince', 'Sokwe', 'sokwe.p@aoa.school'),
        ('Abasiofon', 'Sampson', 'sampson.a@aoa.school'),
        ('Chimfumnanya', 'Aghaduno', 'aghaduno.c@aoa.school'),
        ('Ndungu', 'Kibe', 'kibe.n@aoa.school'),
    ]

    cur.execute("SELECT COUNT(*) FROM Login")
    count = cur.fetchone()[0]

    if count == 0:
        for first, last, email in initial_students:
            full_name = f"{first} {last}"
            cur.execute("SELECT COALESCE(MAX(CAST(userid AS INTEGER)),0) FROM Login")
            row = cur.fetchone()
            next_id = (row[0] or 0) + 1
            cur.execute("INSERT INTO Login(name, userid, email) VALUES(?, ?, ?)", (full_name, str(next_id), email))
        db.commit()


def init_app(app):
    """Register db teardown with the app"""
    app.teardown_appcontext(close_db)

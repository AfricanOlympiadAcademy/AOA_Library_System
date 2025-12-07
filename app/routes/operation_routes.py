from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from datetime import datetime
import json

from ..db import get_db, get_cursor
from ..utils.decorators import login_required

# Staff shared list (you can also import from constants)
STAFF_MEMBERS = [
    'Afsa', 'Alex', 'Angella', 'Arun', 'Claudine', 'Emmy',
    'Gaidi', 'George', 'Guylain', 'Innocent I', 'Innocent M',
    'Jeanette', 'Josue', 'Kelly', 'Linda',
    'Marie Josee', 'Nepo', 'Obed', 'Sindi', 'Wendy'
]

operation_bp = Blueprint("operation_bp", __name__, url_prefix="/operations")

#
# ASSIGN BOOK
#
@operation_bp.route('/assign', methods=['GET', 'POST'])
@login_required
def assign_book():
    db = get_db()
    cur = get_cursor()

    if request.method == 'POST':
        student_id = request.form.get('student_id')
        title = request.form.get('title')
        assigned_by = request.form.get('assigned_by')
        return_date = request.form.get('return_date')
        book_ids_str = request.form.get('book_ids', '[]')

        try:
            book_ids = json.loads(book_ids_str)
        except:
            flash("Invalid book IDs", "error")
            return redirect(url_for("operation_bp.assign_book"))

        if not (student_id and title and assigned_by and book_ids):
            flash("Missing required fields", "error")
            return redirect(url_for("operation_bp.assign_book"))

        # Check student email
        cur.execute("SELECT email, name FROM Login WHERE userid=?", (student_id,))
        row = cur.fetchone()
        if not row:
            flash("Student not found", "error")
            return redirect(url_for("operation_bp.assign_book"))

        student_email = row["email"]
        student_name = row["name"]

        # Assign books
        for bid in book_ids:
            cur.execute("SELECT serial FROM Book WHERE book_id=?", (bid,))
            srow = cur.fetchone()
            serial = srow["serial"]

            cur.execute(
                """INSERT INTO BookIssue(stdid, serial, issue, exp, book_id, assigned_by)
                   VALUES(?, ?, DATE('now'), ?, ?, ?)""",
                (student_id, serial, return_date, bid, assigned_by)
            )

        db.commit()
        flash(f"Assigned {len(book_ids)} copy(ies)", "success")

        # Send email in background?
        # You can import send_email here if needed.

        return redirect(url_for("operation_bp.assign_book"))

    # GET request
    cur.execute("SELECT name, userid FROM Login ORDER BY name")
    students = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT DISTINCT title FROM Book ORDER BY title")
    titles = [r["title"] for r in cur.fetchall()]

    # Default available books
    available_books = []
    if titles:
        cur.execute("""
            SELECT book_id FROM Book 
            WHERE title=? AND NOT EXISTS(
                SELECT 1 FROM BookIssue WHERE BookIssue.book_id = Book.book_id
            )
            ORDER BY book_id
        """, (titles[0],))
        available_books = [r["book_id"] for r in cur.fetchall()]

    return render_template(
        "assign_book.html",
        students=students,
        books=titles,
        available_books=available_books,
        staff_members=STAFF_MEMBERS,
        current_date=datetime.now().strftime("%Y-%m-%d")
    )


#
# GET AVAILABLE BOOKS (AJAX)
#
@operation_bp.route('/api/get_available_books')
@login_required
def get_available_books():
    title = request.args.get("title", "").strip()
    if not title:
        return jsonify([])

    cur = get_cursor()
    cur.execute("""
        SELECT book_id FROM Book 
        WHERE title=? AND NOT EXISTS(
            SELECT 1 FROM BookIssue WHERE BookIssue.book_id = Book.book_id
        )
        ORDER BY book_id
    """, (title,))
    books = [r["book_id"] for r in cur.fetchall()]

    return jsonify(books)


#
# VIEW ALL ASSIGNMENTS
#
@operation_bp.route('/assignments')
@login_required
def view_assignments():
    cur = get_cursor()
    cur.execute("""
        SELECT l.name AS student,
               b.title,
               i.book_id,
               i.issue AS date_assigned,
               i.exp AS return_date,
               i.assigned_by
        FROM BookIssue i
        JOIN Login l ON l.userid=i.stdid
        JOIN Book b ON b.serial=i.serial
        ORDER BY i.issue DESC
    """)
    rows = [dict(r) for r in cur.fetchall()]
    return render_template("view_assignments.html", assignments=rows)


#
# RETURN BOOK
#
@operation_bp.route('/return', methods=['GET','POST'])
@login_required
def return_book():
    db = get_db()
    cur = get_cursor()

    if request.method == 'POST':
        student_id = request.form.get('student_id')
        title = request.form.get('title')
        returned_by = request.form.get('returned_by')
        return_date = request.form.get('return_date')
        book_ids = json.loads(request.form.get("book_ids", "[]"))

        # Insert return record
        cur.execute("""
            SELECT issue FROM BookIssue 
            WHERE stdid=? AND book_id=? LIMIT 1
        """, (student_id, book_ids[0]))
        row = cur.fetchone()
        issue_date = row["issue"]

        cur.execute("""
            INSERT INTO BookReturn(stdid, title, copies, issue, returned)
            VALUES (?, ?, ?, ?, ?)
        """, (student_id, title, len(book_ids), issue_date, return_date))

        for bid in book_ids:
            cur.execute("""
                INSERT INTO BookReturnDetail(stdid, title, book_id, issue, returned, returned_by)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (student_id, title, bid, issue_date, return_date, returned_by))

            cur.execute("DELETE FROM BookIssue WHERE stdid=? AND book_id=?", (student_id, bid))

        db.commit()
        flash("Book(s) returned", "success")
        return redirect(url_for("operation_bp.return_book"))

    # GET request — preload data
    cur.execute("""
        SELECT DISTINCT l.name, l.userid 
        FROM BookIssue i 
        JOIN Login l ON l.userid=i.stdid 
        ORDER BY l.name
    """)
    students = [dict(r) for r in cur.fetchall()]

    # Titles for first student
    titles = []
    if students:
        cur.execute("""
            SELECT DISTINCT b.title
            FROM BookIssue i 
            JOIN Book b ON b.serial=i.serial
            WHERE i.stdid=? 
            ORDER BY b.title
        """, (students[0]["userid"],))
        titles = [r["title"] for r in cur.fetchall()]

    # Books for first student's first title
    available_books = []
    if titles:
        cur.execute("""
            SELECT b.book_id
            FROM BookIssue i 
            JOIN Book b ON b.serial=i.serial
            WHERE i.stdid=? AND b.title=?
            ORDER BY b.book_id
        """, (students[0]["userid"], titles[0]))
        available_books = [r["book_id"] for r in cur.fetchall()]

    return render_template(
        "return_book.html",
        students=students,
        books=titles,
        available_books=available_books,
        staff_members=STAFF_MEMBERS
    )


#
# API: Get books for student+title
#
@operation_bp.route('/api/get_student_books')
@login_required
def get_student_books():
    student_id = request.args.get("student_id")
    title = request.args.get("title")

    if not(student_id and title):
        return jsonify([])

    cur = get_cursor()
    cur.execute("""
        SELECT b.book_id
        FROM BookIssue i
        JOIN Book b ON b.serial=i.serial
        WHERE i.stdid=? AND b.title=?
        ORDER BY b.book_id
    """, (student_id, title))

    rows = [r["book_id"] for r in cur.fetchall()]
    return jsonify(rows)


#
# VIEW RETURNS
#
@operation_bp.route('/returns')
@login_required
def view_returns():
    cur = get_cursor()

    cur.execute("""
        SELECT l.name AS student,
               d.title,
               GROUP_CONCAT(d.book_id, ', ') AS ids,
               MIN(d.issue) AS issue,
               MAX(d.returned) AS returned,
               MAX(d.returned_by) AS returned_by
        FROM BookReturnDetail d
        JOIN Login l ON l.userid=d.stdid
        GROUP BY l.name, d.title, DATE(d.returned)
        ORDER BY d.returned DESC
    """)
    detailed = [dict(r) for r in cur.fetchall()]

    return render_template("view_returns.html", returns=detailed)
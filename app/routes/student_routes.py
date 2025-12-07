from flask import Blueprint, render_template, request, redirect, url_for, flash
from ..db import get_db, get_cursor
from ..utils.decorators import login_required

student_bp = Blueprint("student_bp", __name__, url_prefix="/students")


@student_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_student():
    db = get_db()
    cur = get_cursor()

    if request.method == 'POST':
        first = request.form.get('first_name', '').strip()
        last = request.form.get('second_name', '').strip()
        email = request.form.get('email', '').strip()

        if not first:
            flash("Enter first name", "error")
            return redirect(url_for("student_bp.add_student"))

        if '@' not in email:
            flash("Invalid email", "error")
            return redirect(url_for("student_bp.add_student"))

        full_name = f"{first} {last}".strip()
        cur.execute("SELECT COALESCE(MAX(CAST(userid AS INTEGER)), 0) FROM Login")
        next_id = (cur.fetchone()[0] or 0) + 1

        cur.execute(
            "INSERT INTO Login(name, userid, email) VALUES (?, ?, ?)",
            (full_name, next_id, email)
        )
        db.commit()

        flash(f"Student {full_name} added", "success")
        return redirect(url_for("student_bp.view_students"))

    return render_template("add_student.html")


@student_bp.route('/view')
@login_required
def view_students():
    cur = get_cursor()
    cur.execute("SELECT name, userid, email FROM Login")
    students = [dict(row) for row in cur.fetchall()]
    return render_template("view_students.html", students=students)


@student_bp.route('/delete/<userid>', methods=['POST'])
@login_required
def delete_student(userid):
    db = get_db()
    cur = get_cursor()
    password = request.form.get("password")

    if password != "AOA@2027":
        flash("Wrong password", "error")
        return redirect(url_for("student_bp.view_students"))

    cur.execute("SELECT 1 FROM BookIssue WHERE stdid=? LIMIT 1", (userid,))
    if cur.fetchone():
        flash("Cannot delete: student has active assignments", "error")
        return redirect(url_for("student_bp.view_students"))

    cur.execute("""
        INSERT INTO DeletedLogin(name, userid, deleted)
        SELECT name, userid, DATE('now') FROM Login WHERE userid=?
    """, (userid,))

    cur.execute("DELETE FROM Login WHERE userid=?", (userid,))
    db.commit()

    flash("Student deleted", "success")
    return redirect(url_for("student_bp.view_students"))
# app/routes/book_routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from ..utils.decorators import login_required
from ..db import get_db, get_cursor

book_bp = Blueprint('books', __name__)


@book_bp.route('/books/add', methods=['GET', 'POST'])
@login_required
def add_book():
    # body identical to your original add_book
    get_db()
    cur = get_cursor()
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        book_id = request.form.get('book_id', '').strip()
        copies = request.form.get('copies', '1').strip()

        if not (subject and title and author):
            flash('Fill subject, title and author', 'error')
            return redirect(url_for('books.add_book'))

        try:
            copies_int = int(copies) if copies else 1
            if copies_int < 1:
                raise ValueError()
        except ValueError:
            flash('Copies must be a positive integer', 'error')
            return redirect(url_for('books.add_book'))

        custom_id = book_id
        if custom_id:
            if copies_int != 1:
                flash('Provide BOOK ID only when copies = 1', 'error')
                return redirect(url_for('books.add_book'))
            cur.execute("SELECT 1 FROM Book WHERE book_id=?", (custom_id,))
            if cur.fetchone():
                flash('Book ID already exists', 'error')
                return redirect(url_for('books.add_book'))
            cur.execute(
                "INSERT INTO Book(subject,title,author,book_id) VALUES(?,?,?,?)",
                (subject, title, author, custom_id)
            )
            get_db().commit()
            flash(f"Book {title} added", 'success')
            return redirect(url_for('auth.dashboard'))

        for _ in range(copies_int):
            cur.execute("INSERT INTO Book(subject,title,author) VALUES(?,?,?)", (subject, title, author))
            new_serial = cur.lastrowid
            cur.execute("UPDATE Book SET book_id = CAST(serial AS TEXT) WHERE serial = ?", (new_serial,))
        get_db().commit()
        flash(f"Book {title} added", 'success')
        return redirect(url_for('auth.dashboard'))

    return render_template('add_book.html')


@book_bp.route('/books/view')
@login_required
def view_books():
    get_db()
    cur = get_cursor()
    cur.execute('SELECT subject,title,author,book_id FROM Book')
    books = []
    for row in cur.fetchall():
        bid = row['book_id']
        cur.execute("SELECT 1 FROM BookIssue WHERE book_id=?", (bid,))
        is_issued = cur.fetchone() is not None
        books.append({
            'subject': row['subject'],
            'title': row['title'],
            'author': row['author'],
            'book_id': bid,
            'available': 'No' if is_issued else 'Yes'
        })
    return render_template('view_books.html', books=books)


@book_bp.route('/books/edit/<book_id>', methods=['POST'])
@login_required
def edit_book_id(book_id):
    get_db()
    cur = get_cursor()
    password = request.form.get('password', '').strip()
    new_id = request.form.get('new_id', '').strip()
    new_subject = request.form.get('new_subject', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('books.view_books'))
    
    # Check if book is available
    cur.execute("SELECT 1 FROM BookIssue WHERE book_id=?", (book_id,))
    if cur.fetchone():
        flash('Cannot edit: book is currently assigned to a student', 'error')
        return redirect(url_for('books.view_books'))
    
    # Get current book data
    cur.execute("SELECT subject, book_id FROM Book WHERE book_id=?", (book_id,))
    current_book = cur.fetchone()
    if not current_book:
        flash('Book not found', 'error')
        return redirect(url_for('books.view_books'))
    
    current_subject = current_book['subject']
    current_book_id = current_book['book_id']
    
    updates = []
    params = []
    
    # Update Book ID if provided and different
    if new_id and new_id != current_book_id:
        # Check if new ID exists
        cur.execute("SELECT 1 FROM Book WHERE book_id=?", (new_id,))
        if cur.fetchone():
            flash(f'Book ID "{new_id}" already exists', 'error')
            return redirect(url_for('books.view_books'))
        updates.append("book_id=?")
        params.append(new_id)
    
    # Update Subject (Category) if provided and different
    if new_subject and new_subject != current_subject:
        updates.append("subject=?")
        params.append(new_subject)
    
    if not updates:
        flash('No changes detected', 'error')
        return redirect(url_for('books.view_books'))
    
    params.append(book_id)
    
    try:
        update_query = f"UPDATE Book SET {', '.join(updates)} WHERE book_id=?"
        cur.execute(update_query, tuple(params))
        get_db().commit()
        
        changes = []
        if new_id and new_id != current_book_id:
            changes.append(f"Book ID: {current_book_id} → {new_id}")
        if new_subject and new_subject != current_subject:
            changes.append(f"Category: {current_subject} → {new_subject}")
        
        flash(f"Book updated: {', '.join(changes)}", 'success')
    except Exception as e:
        flash(f'Error updating book: {str(e)}', 'error')
        get_db().rollback()
    
    return redirect(url_for('books.view_books'))


@book_bp.route('/books/delete/<book_id>', methods=['POST'])
@login_required
def delete_book(book_id):
    get_db()
    cur = get_cursor()
    password = request.form.get('password', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('books.view_books'))
    
    cur.execute("SELECT 1 FROM BookIssue WHERE book_id=?", (book_id,))
    if cur.fetchone():
        flash('Cannot delete: book is currently assigned', 'error')
        return redirect(url_for('books.view_books'))
    
    cur.execute("INSERT INTO DeletedBook(subject, title, author, book_id, deleted) "
               "SELECT subject, title, author, book_id, DATE('now') FROM Book WHERE book_id=?", (book_id,))
    cur.execute("DELETE FROM Book WHERE book_id=?", (book_id,))
    get_db().commit()
    flash(f"Deleted Book ID {book_id}", 'success')
    return redirect(url_for('books.view_books'))


@book_bp.route('/books/titles')
@login_required
def view_titles():
    get_db()
    cur = get_cursor()
    cur.execute("""
        SELECT b.subject, b.title, b.author,
               COUNT(*) AS total,
               SUM(CASE WHEN NOT EXISTS (
                   SELECT 1 FROM BookIssue i WHERE i.book_id = b.book_id
               ) THEN 1 ELSE 0 END) AS available
        FROM Book b
        GROUP BY b.subject, b.title, b.author
        ORDER BY b.title
    """)
    titles = [dict(row) for row in cur.fetchall()]
    return render_template('view_titles.html', titles=titles)


@book_bp.route('/books/titles/delete', methods=['POST'])
@login_required
def delete_title():
    get_db()
    cur = get_cursor()
    title = request.form.get('title', '').strip()
    password = request.form.get('password', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('books.view_titles'))
    
    cur.execute("SELECT 1 FROM BookIssue i JOIN Book b ON b.book_id=i.book_id WHERE b.title=? LIMIT 1", (title,))
    if cur.fetchone():
        flash('Cannot delete: at least one copy is currently assigned', 'error')
        return redirect(url_for('books.view_titles'))
    
    cur.execute("DELETE FROM Book WHERE title=?", (title,))
    get_db().commit()
    flash(f"Deleted all copies of '{title}'", 'success')
    return redirect(url_for('books.view_titles'))


@book_bp.route('/books/deleted')
@login_required
def view_deleted_books():
    get_db()
    cur = get_cursor()
    cur.execute("SELECT subject, title, author, book_id, deleted FROM DeletedBook ORDER BY deleted DESC")
    books = [dict(row) for row in cur.fetchall()]
    return render_template('view_deleted_books.html', books=books)


@book_bp.route('/api/get_available_books')
@login_required
def get_available_books():
    get_db()
    cur = get_cursor()
    title = request.args.get('title', '').strip()
    if not title:
        return jsonify([])
    
    cur.execute("SELECT b.book_id FROM Book b WHERE b.title=? AND NOT EXISTS "
               "(SELECT 1 FROM BookIssue i WHERE i.book_id=b.book_id) ORDER BY b.book_id", (title,))
    books = [row['book_id'] for row in cur.fetchall()]
    return jsonify(books)
# routes_login.py
from flask import Blueprint, session, flash, request, redirect, render_template, url_for

login_bp = Blueprint('login_bp', __name__)

@login_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        admin_id = request.form.get('admin_id', '').trim()
        password = request.form.get('password', '').trim()

        if admin_id == 'AOA_Admin' and password == 'AOA@2027':
            session['admin_logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Wrong ID or Password', 'error')

    return render_template('login.html')

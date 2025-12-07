# app/routes/auth_routes.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from ..utils.decorators import login_required

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        admin_id = request.form.get('admin_id', '').strip()
        password = request.form.get('password', '').strip()

        if admin_id == 'AOA_Admin' and password == 'AOA@2027':
            session['admin_logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('auth.dashboard'))
        else:
            flash('Wrong ID or Password', 'error')

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')
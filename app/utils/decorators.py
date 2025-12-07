from functools import wraps
from flask import session, redirect, url_for, flash

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "admin_logged_in" not in session:
            flash("Please login to access this page", "error")
            return redirect(url_for("auth_bp.login"))
        return f(*args, **kwargs)
    return wrapper
from flask import Flask
from .db import init_db, close_db

# Blueprints
from .routes.auth_routes import auth_bp
from .routes.book_routes import book_bp
from .routes.student_routes import student_bp
from .routes.operation_routes import operation_bp
from .routes.admin_routes import admin_bp

# Background services
from .services.email_service import start_email_worker
from .services.reminder_service import start_reminder_system


def create_app():
    # REMEMBER TO USE THE SECRET KEY FOR THE MAILING SERVICES, EDDY
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )

    app.secret_key='CHANGE_ME'

    # Database teardown
    app.teardown_appcontext(close_db)

    # Initialize DB + background workers
    with app.app_context():
        init_db()
        start_email_worker()
        start_reminder_system()

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(book_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(operation_bp)
    app.register_blueprint(admin_bp)

    return app
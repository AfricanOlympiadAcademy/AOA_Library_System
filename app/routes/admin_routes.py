# app/routes/admin_routes.py
from flask import Blueprint, render_template, request, redirect, url_for, flash
from datetime import datetime
import os

from ..services.email_service import load_email_config, send_email_direct
from ..utils.decorators import login_required

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/admin/test-email', methods=['GET', 'POST'])
@login_required
def test_email():
    if request.method == 'POST':
        test_email_address = request.form.get('test_email', '').strip()
        if not test_email_address:
            flash('Please provide a test email address', 'error')
            return redirect(url_for('admin.test_email'))

        config = load_email_config()
        if not config:
            flash('Email configuration not found. Check environment variables.', 'error')
            return redirect(url_for('admin.test_email'))

        subject = 'AOA Library - Test Email'
        body = f'''
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Test Email from AOA Library System</h2>
            <p>If you received this email, your email configuration is working correctly!</p>
            <p>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        </body>
        </html>
        '''

        result = send_email_direct(test_email_address, subject, body)
        if result:
            flash(f'Test email sent successfully to {test_email_address}!', 'success')
        else:
            flash('Failed to send test email. Check logs for details.', 'error')

        return redirect(url_for('admin.test_email'))

    config = load_email_config()
    config_status = {}
    env_check = {
        'SMTP_SERVER': os.getenv('SMTP_SERVER', 'Not set'),
        'SMTP_PORT': os.getenv('SMTP_PORT', 'Not set'),
        'EMAIL_ADDRESS': os.getenv('EMAIL_ADDRESS', 'Not set'),
        'EMAIL_PASSWORD': 'Set' if os.getenv('EMAIL_PASSWORD') else 'Not set',
        'EMAIL_ENABLED': os.getenv('EMAIL_ENABLED', 'Not set'),
    }

    if config:
        config_status = {
            'enabled': config.get('enabled', False),
            'has_email': bool(config.get('email_address')),
            'has_password': bool(config.get('email_password')),
            'smtp_server': config.get('smtp_server', 'Not set'),
            'smtp_port': config.get('smtp_port', 'Not set'),
            'email_address': config.get('email_address', 'Not set'),
        }

    return render_template('test_email.html', config=config_status, env_check=env_check)

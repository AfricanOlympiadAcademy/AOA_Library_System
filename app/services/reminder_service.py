# app/services/reminder_service.py
from datetime import datetime, timedelta
import threading
import time
import schedule
import pytz
import sqlite3 as sqlite

from ..db import _resolve_db_path
from .email_service import load_email_config, send_email


def check_and_send_due_tomorrow_reminders():
    try:
        db = sqlite.connect(_resolve_db_path())
        db.row_factory = sqlite.Row
        cur = db.cursor()
        config = load_email_config()
        library_name = config.get('library_name', 'AOA Library') if config else 'AOA Library'

        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        cur.execute("""
            SELECT l.name, l.email, b.title, i.book_id, i.exp, i.issue
            FROM BookIssue i
            JOIN Login l ON l.userid = i.stdid
            JOIN Book b ON b.serial = i.serial
            WHERE i.exp = ?
        """, (tomorrow,))

        results = cur.fetchall()

        for row in results:
            student_name = row['name']
            student_email = row['email']
            book_title = row['title']
            book_id = row['book_id']
            return_date = row['exp']
            issue_date = row['issue']

            if not student_email:
                continue

            email_subject = f'{library_name} - Book Due Tomorrow Reminder'
            email_body = f'''
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
                    <h2 style="color: #E8A71D; border-bottom: 3px solid #E8A71D; padding-bottom: 10px;">Book Due Tomorrow Reminder</h2>

                    <p>Dear <strong>{student_name}</strong>,</p>

                    <p>This is a friendly reminder that the following book is <strong style="color: #E8A71D;">due tomorrow</strong>:</p>

                    <div style="background-color: #fff; padding: 15px; border-left: 4px solid #E8A71D; margin: 20px 0;">
                        <p><strong>Book Title:</strong> {book_title}</p>
                        <p><strong>Book ID:</strong> {book_id}</p>
                        <p><strong>Date Borrowed:</strong> {datetime.strptime(issue_date, '%Y-%m-%d').strftime('%B %d, %Y')}</p>
                        <p><strong>Due Date:</strong> <span style="color: #E8A71D; font-weight: bold;">{datetime.strptime(return_date, '%Y-%m-%d').strftime('%B %d, %Y')}</span></p>
                    </div>

                    <p style="background-color: #FFF3CD; padding: 12px; border-radius: 5px; border-left: 4px solid #E8A71D;">
                         <strong>Please return this book tomorrow</strong> to avoid any late penalties.
                    </p>

                    <p>Thank you for your attention to this matter.</p>
                </div>
            </body>
            </html>
            '''

            send_email(student_email, email_subject, email_body, background=False)
            print(f"Sent due tomorrow reminder to {student_name} ({student_email})")

        if results:
            print(f"Sent {len(results)} due tomorrow reminder(s)")
    except Exception as e:
        print(f"Error checking due tomorrow reminders: {e}")
    finally:
        if 'db' in locals():
            db.close()


def check_and_send_overdue_reminders():
    try:
        db = sqlite.connect(_resolve_db_path())
        db.row_factory = sqlite.Row
        cur = db.cursor()
        config = load_email_config()
        library_name = config.get('library_name', 'AOA Library') if config else 'AOA Library'

        today = datetime.now().strftime('%Y-%m-%d')

        cur.execute("""
            SELECT l.name, l.email, b.title, i.book_id, i.exp, i.issue
            FROM BookIssue i
            JOIN Login l ON l.userid = i.stdid
            JOIN Book b ON b.serial = i.serial
            WHERE i.exp < ?
        """, (today,))

        results = cur.fetchall()

        for row in results:
            student_name = row['name']
            student_email = row['email']
            book_title = row['title']
            book_id = row['book_id']
            return_date = row['exp']
            issue_date = row['issue']

            if not student_email:
                continue

            due_date = datetime.strptime(return_date, '%Y-%m-%d')
            today_date = datetime.strptime(today, '%Y-%m-%d')
            days_overdue = (today_date - due_date).days

            email_subject = f'{library_name} - OVERDUE Book Reminder'
            email_body = f'''
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
                    <h2 style="color: #C0392B; border-bottom: 3px solid #C0392B; padding-bottom: 10px;">OVERDUE Book Notice</h2>

                    <p>Dear <strong>{student_name}</strong>,</p>

                    <p style="color: #C0392B; font-weight: bold;">This is an important notice that the following book is now OVERDUE:</p>

                    <div style="background-color: #fff; padding: 15px; border-left: 4px solid #C0392B; margin: 20px 0;">
                        <p><strong>Book Title:</strong> {book_title}</p>
                        <p><strong>Book ID:</strong> {book_id}</p>
                        <p><strong>Date Borrowed:</strong> {datetime.strptime(issue_date, '%Y-%m-%d').strftime('%B %d, %Y')}</p>
                        <p><strong>Was Due:</strong> <span style="color: #C0392B; font-weight: bold;">{datetime.strptime(return_date, '%Y-%m-%d').strftime('%B %d, %Y')}</span></p>
                        <p><strong>Days Overdue:</strong> <span style="color: #C0392B; font-weight: bold; font-size: 18px;">{days_overdue} day(s)</span></p>
                    </div>
                </div>
            </body>
            </html>
            '''

            send_email(student_email, email_subject, email_body, background=False)
            print(f"Sent overdue reminder to {student_name} ({student_email}) - {days_overdue} day(s) overdue")

        if results:
            print(f"Sent {len(results)} overdue reminder(s)")
    except Exception as e:
        print(f"Error checking overdue reminders: {e}")
    finally:
        if 'db' in locals():
            db.close()


def run_daily_reminder_checks():
    print(f"\n{'='*60}")
    print(f"Running daily reminder checks at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    check_and_send_due_tomorrow_reminders()
    check_and_send_overdue_reminders()

    print(f"{'='*60}")
    print("Reminder checks completed")
    print(f"{'='*60}\n")


def setup_reminder_scheduler():
    eat_tz = pytz.timezone('Africa/Nairobi')
    schedule.every().day.at("18:00").do(run_daily_reminder_checks)
    print("Reminder scheduler initialized - checks will run daily at 6:00 PM EAT")


def run_scheduler_in_background():
    while True:
        schedule.run_pending()
        time.sleep(60)


def start_reminder_system():
    setup_reminder_scheduler()
    scheduler_thread = threading.Thread(target=run_scheduler_in_background, daemon=True)
    scheduler_thread.start()
    print("Reminder system started in background thread")
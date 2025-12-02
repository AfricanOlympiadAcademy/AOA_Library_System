from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g, send_file, Response
import os
import json
try:
    import resend
    RESEND_AVAILABLE = True
except ImportError:
    RESEND_AVAILABLE = False
    print("WARNING: resend package not installed. Install with: pip install resend")
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import urllib.parse as urlparse
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("ERROR: psycopg2 not installed. PostgreSQL is required. Install with: pip install psycopg2-binary")
    raise ImportError("psycopg2-binary is required. Install with: pip install psycopg2-binary")
from datetime import datetime, timedelta, date
import schedule
import threading
import time
import pytz
import queue
from functools import wraps

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'your-secret-key-change-this-in-production')  # Use SECRET_KEY env var in production

_db_initialized = False
DATABASE_URL = os.getenv('DATABASE_URL')

# PostgreSQL is required - no SQLite fallback
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required. Please set it in Render Dashboard.")
if not POSTGRES_AVAILABLE:
    raise ImportError("PostgreSQL support is required. Install psycopg2-binary.")

# Email queue for background sending
email_queue = queue.Queue()
email_worker_thread = None

def _get_postgres_connection():
    """Get PostgreSQL connection from DATABASE_URL"""
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")
    if not POSTGRES_AVAILABLE:
        raise ImportError("PostgreSQL support is required. Install psycopg2-binary")
    
    try:
        # Parse DATABASE_URL (format: postgresql://user:password@host:port/dbname)
        parsed = urlparse.urlparse(DATABASE_URL)
        conn = psycopg2.connect(
            database=parsed.path[1:],  # Remove leading '/'
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port
        )
        return conn
    except Exception as e:
        print(f"Error connecting to PostgreSQL: {e}")
        raise

def _get_db_connection():
    """Get a database connection (for background threads)"""
    return _get_postgres_connection(), 'postgres'

def get_db():
    """Get PostgreSQL database connection (thread-local)"""
    global _db_initialized
    
    if 'db' not in g:
        # PostgreSQL is required - no fallback
        g.db = _get_postgres_connection()
        g.db_type = 'postgres'
        
        # Initialize tables only once per application startup
        if not _db_initialized:
            cur = g.db.cursor()
            
            # PostgreSQL table creation
            cur.execute('''
                CREATE TABLE IF NOT EXISTS Login(
                    name TEXT, userid TEXT, password INTEGER, 
                    branch TEXT, mobile INTEGER, email TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS Book(
                    subject TEXT, title TEXT, author TEXT, 
                    serial SERIAL PRIMARY KEY, book_id TEXT UNIQUE
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS BookIssue(
                    stdid TEXT, serial TEXT, issue DATE, exp DATE, 
                    book_id TEXT, assigned_by TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS BookReturn(
                    stdid TEXT, title TEXT, copies INTEGER, 
                    issue DATE, returned DATE
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS BookReturnDetail(
                    stdid TEXT, title TEXT, book_id TEXT, 
                    issue DATE, returned DATE, returned_by TEXT
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS DeletedLogin(
                    name TEXT, userid TEXT, deleted DATE
                )
            ''')
            cur.execute('''
                CREATE TABLE IF NOT EXISTS DeletedBook(
                    subject TEXT, title TEXT, author TEXT, 
                    book_id TEXT, deleted DATE
                )
            ''')
            g.db.commit()
            
            # Fix SERIAL sequence if needed (after migration, sequences can be out of sync)
            # PostgreSQL creates sequences automatically for SERIAL columns
            # Format: tablename_columnname_seq
            try:
                cur.execute("SELECT setval('book_serial_seq', COALESCE((SELECT MAX(serial) FROM Book), 1), true)")
                g.db.commit()
            except Exception as e:
                # Sequence might not exist or already correct, ignore
                g.db.rollback()
            
            # Add missing columns if needed
            def _table_columns(name: str):
                # PostgreSQL stores table names in lowercase unless quoted
                cur.execute("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE LOWER(table_name) = LOWER(%s)
                """, (name,))
                return [r[0].lower() for r in cur.fetchall()]  # Normalize to lowercase for comparison
            
            def _has_column(table_name: str, column_name: str) -> bool:
                """Check if a column exists in a table (case-insensitive)"""
                cols = _table_columns(table_name)
                return column_name.lower() in cols
            
            # Check and add book_id to Book table
            if not _has_column('Book', 'book_id'):
                try:
                    cur.execute("ALTER TABLE Book ADD COLUMN book_id TEXT")
                    g.db.commit()
                    cur.execute("UPDATE Book SET book_id = CAST(serial AS TEXT) WHERE book_id IS NULL OR book_id = ''")
                    g.db.commit()
                    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_book_book_id ON Book(book_id)")
                    g.db.commit()
                except Exception as e:
                    # Column might already exist, ignore
                    g.db.rollback()
            
            # Check and add book_id to BookIssue table
            if not _has_column('BookIssue', 'book_id'):
                try:
                    cur.execute("ALTER TABLE BookIssue ADD COLUMN book_id TEXT")
                    g.db.commit()
                    cur.execute("UPDATE BookIssue SET book_id = (SELECT b.book_id FROM Book b WHERE CAST(b.serial AS TEXT) = BookIssue.serial) WHERE book_id IS NULL")
                    g.db.commit()
                except Exception as e:
                    g.db.rollback()
            
            # Check and add assigned_by to BookIssue table
            if not _has_column('BookIssue', 'assigned_by'):
                try:
                    cur.execute("ALTER TABLE BookIssue ADD COLUMN assigned_by TEXT")
                    g.db.commit()
                except Exception as e:
                    g.db.rollback()
            
            # Check and add email to Login table
            if not _has_column('Login', 'email'):
                try:
                    cur.execute("ALTER TABLE Login ADD COLUMN email TEXT")
                    g.db.commit()
                except Exception as e:
                    g.db.rollback()
            
            # Check and add returned_by to BookReturnDetail table
            if not _has_column('BookReturnDetail', 'returned_by'):
                try:
                    cur.execute("ALTER TABLE BookReturnDetail ADD COLUMN returned_by TEXT")
                    g.db.commit()
                except Exception as e:
                    g.db.rollback()
            
            g.db.commit()
            _db_initialized = True
    
    return g.db

class CursorWrapper:
    """Wrapper to convert SQLite-style ? parameters to PostgreSQL %s"""
    def __init__(self, cursor):
        self.cursor = cursor
    
    def execute(self, query, params=None):
        if params is not None:
            # Convert ? to %s for PostgreSQL
            query = query.replace('?', '%s')
            return self.cursor.execute(query, params)
        else:
            return self.cursor.execute(query)
    
    def __getattr__(self, name):
        return getattr(self.cursor, name)

def get_cursor():
    """Get PostgreSQL database cursor (thread-local)"""
    db = get_db()
    cur = db.cursor(cursor_factory=RealDictCursor)
    return CursorWrapper(cur)

@app.teardown_appcontext
def close_db(error):
    """Close PostgreSQL database connection at the end of request"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def populate_initial_students():
    """Populate initial student data if not already present"""
    db = get_db()
    cur = get_cursor()
    initial_students = [
    ('Kesha', 'Wanjare', 'kesha.w@aoa.school'),
    ('Esther', 'Apendi', 'esther.a@aoa.school'),
    ('Ethan', 'Mutyaba', 'ethan.m@aoa.school'),
    ('Baruch', 'Rugero', 'baruch.r@aoa.school'),
    ('Tokollo', 'Shaku', 'tokollo.s@aoa.school'),
    ('Tumi', 'Nyagiro', 'tumi.n@aoa.school'),
    ('Imelda', 'Ikuzwe', 'imelda.i@aoa.school'),
    ('Baraka', 'Mulwa', 'baraka.m@aoa.school'),
    ('Sweetbert', 'Nene', 'sweetbert.n@aoa.school'),
    ('Flora', 'Ineza', 'flora.i@aoa.school'),
    ('Sonia', 'Keza', 'sonia.k@aoa.school'),
    ('Lightness', 'Ngilule', 'lightness.n@aoa.school'),
    ('Margaret', 'Angel', 'margaret.a@aoa.school'),
    ('Herve', 'Uwayezu', 'herve.u@aoa.school'),
    ('Elizabeth', 'Musiimenta', 'elizabeth.m@aoa.school'),
    ('Nathan', 'Khiisa', 'nathan.k@aoa.school'),
    ('Joyce', 'Sulumo', 'joyce.s@aoa.school'),
    ('Denys', 'Tuyisenge', 'denys.t@aoa.school'),
    ('Jayden', 'Osago', 'jayden.o@aoa.school'),
    ('Roland', 'Ndjamba', 'roland.n@aoa.school'),
    ('Andile', 'Kebopetswe', 'andile.k@aoa.school'),
    ('Stephanie', 'Kwenantsi', 'stephanie.k@aoa.school'),
    ('Helena', 'Haikali', 'helena.h@aoa.school'),
    ('Anton', 'Wakele', 'anton.w@aoa.school'),
    ('Lebone', 'Tau', 'lebone.t@aoa.school'),
    ('Prince', 'Sokwe', 'prince.s@aoa.school'),
    ('Abasiofon', 'Sampson', 'abasiofon.s@aoa.school'),
    ('Chimfumnanya', 'Aghaduno', 'chimfumnanya.a@aoa.school'),
    ('Happy', 'David', 'happy.d@aoa.school'),
    ('Ndungu', 'Kibe', 'ndungu.k@aoa.school'),
    ('Jed', 'Oloo Odundo', 'jed.o@aoa.school'),
    ]
    
    cur.execute("SELECT COUNT(*) FROM Login")
    row = cur.fetchone()
    count = list(row.values())[0] if row else 0
    
    if count == 0:
        for first, last, email in initial_students:
            full_name = f"{first} {last}"
            cur.execute("SELECT COALESCE(MAX(CAST(userid AS INTEGER)),0) FROM Login")
            row = cur.fetchone()
            # RealDictCursor returns dict, get first value
            max_id = list(row.values())[0] if row else 0
            next_id = (max_id or 0) + 1
            cur.execute("INSERT INTO Login(name, userid, email) VALUES(?, ?, ?)", (full_name, str(next_id), email))
        db.commit()

def load_email_config():
    """Load email configuration from environment variables (production) or email_config.json (development)"""
    # Try environment variables first (more secure for production)
    # Check for Resend API key first (preferred method)
    if os.getenv('RESEND_API_KEY'):
        return {
            'enabled': os.getenv('EMAIL_ENABLED', 'true').lower() == 'true',
            'provider': 'resend',
            'resend_api_key': os.getenv('RESEND_API_KEY'),
            'email_address': os.getenv('EMAIL_ADDRESS', 'tech@africanolympiadfoundation.org'),
            'library_name': os.getenv('LIBRARY_NAME', 'AOA Library')
        }
    
    # Fallback to config file (for local development)
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'email_config.json')
        with open(config_path, 'r') as f:
            config = json.load(f)
            # Always use Resend
            config['provider'] = 'resend'
            return config
    except Exception as e:
        print(f"Error loading email config: {e}")
        return None

def sanitize_email(email):
    """Sanitize email address to prevent injection attacks"""
    if not email:
        return ""
    email = email.strip()
    if '@' not in email or '.' not in email:
        return ""
    email = ''.join(char for char in email if char.isprintable())
    dangerous_chars = ['\n', '\r', '\\', ';', ',', '<', '>']
    for char in dangerous_chars:
        if char in email:
            return ""
    if len(email) > 254:
        return ""
    return email

def send_email_direct(to_email, subject, body):
    """Send an email directly (blocking) - used internally by worker"""
    config = load_email_config()
    
    if not config:
        print("ERROR: Email config not found - check environment variables or email_config.json")
        print("  Make sure RESEND_API_KEY is set in Render Dashboard Environment variables")
        return False
    
    if not config.get('enabled', False):
        print("Email sending is disabled in config")
        return False
    
    # Check required fields
    if not config.get('email_address'):
        print("ERROR: email_address not set in config")
        return False
    
    to_email = sanitize_email(to_email)
    if not to_email:
        print("Invalid or dangerous email address provided")
        return False
    
    # Use Resend API for all email sending
    if not RESEND_AVAILABLE:
        print("ERROR: resend package not installed. Install with: pip install resend")
        return False
    
    if not config.get('resend_api_key'):
        print("ERROR: resend_api_key not set in config")
        print("  ACTION REQUIRED: Set RESEND_API_KEY environment variable in Render Dashboard")
        return False
    
    try:
        resend.api_key = config['resend_api_key']
        
        print(f"Attempting to send email to {to_email} via Resend API")
        params = {
            "from": config['email_address'],
            "to": [to_email],
            "subject": subject,
            "html": body
        }
        
        email = resend.Emails.send(params)
        print(f"✓ Email sent successfully to {to_email} via Resend (ID: {email.get('id', 'N/A')})")
        return True
    except Exception as e:
        print(f"ERROR sending email via Resend: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def send_email(to_email, subject, body, background=True):
    """Send an email - can be queued for background sending or sent immediately"""
    if background:
        # Check if worker is running
        global email_worker_thread
        if email_worker_thread is None or not email_worker_thread.is_alive():
            print("WARNING: Email worker thread not running! Starting it now...")
            start_email_worker()
        
        email_queue.put({
            'to': to_email,
            'subject': subject,
            'body': body
        })
        print(f"Email queued for background sending to {to_email} (queue size now: {email_queue.qsize()})")
        return True
    else:
        return send_email_direct(to_email, subject, body)

def email_worker():
    """Background worker that processes the email queue"""
    print("Email worker thread started")
    import time
    last_heartbeat = time.time()
    heartbeat_interval = 30  # Log heartbeat every 30 seconds
    
    while True:
        try:
            email_data = email_queue.get(timeout=1)
            print(f"Email worker: Processing email to {email_data['to']}")
            result = send_email_direct(
                email_data['to'],
                email_data['subject'],
                email_data['body']
            )
            if result:
                print(f"Email worker: Successfully sent email to {email_data['to']}")
            else:
                print(f"Email worker: Failed to send email to {email_data['to']} - check logs above for details")
            email_queue.task_done()
        except queue.Empty:
            # Log heartbeat periodically to confirm worker is alive
            current_time = time.time()
            if current_time - last_heartbeat >= heartbeat_interval:
                print(f"Email worker: Alive and waiting for emails (queue size: {email_queue.qsize()})")
                last_heartbeat = current_time
            continue
        except Exception as e:
            print(f"ERROR in email worker: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            try:
                email_queue.task_done()
            except:
                pass

def start_email_worker():
    """Start the background email worker thread"""
    global email_worker_thread
    
    if email_worker_thread is None or not email_worker_thread.is_alive():
        email_worker_thread = threading.Thread(target=email_worker, daemon=True)
        email_worker_thread.start()
        print("Email worker thread initialized")
        # Verify it's actually running
        import time
        time.sleep(0.1)  # Brief pause to let thread start
        if email_worker_thread.is_alive():
            print("Email worker thread confirmed running")
        else:
            print("WARNING: Email worker thread started but is not alive!")

def check_and_send_due_tomorrow_reminders():
    """Check for books due tomorrow and send reminder emails"""
    try:
        # Background thread - create own PostgreSQL connection
        db = _get_postgres_connection()
        cur = db.cursor(cursor_factory=RealDictCursor)
        config = load_email_config()
        library_name = config.get('library_name', 'AOA Library') if config else 'AOA Library'
        
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        cur.execute("""
            SELECT l.name, l.email, b.title, i.book_id, i.exp, i.issue
            FROM BookIssue i
            JOIN Login l ON l.userid = i.stdid
            JOIN Book b ON b.serial = CAST(i.serial AS INTEGER)
            WHERE i.exp = %s
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
                        <p style="margin: 5px 0;"><strong>Book Title:</strong> {book_title}</p>
                        <p style="margin: 5px 0;"><strong>Book ID:</strong> {book_id}</p>
                        <p style="margin: 5px 0;"><strong>Date Borrowed:</strong> {format_date_for_display(issue_date)}</p>
                        <p style="margin: 5px 0;"><strong>Due Date:</strong> <span style="color: #E8A71D; font-weight: bold;">{format_date_for_display(return_date)}</span></p>
                    </div>
                    
                    <p style="background-color: #FFF3CD; padding: 12px; border-radius: 5px; border-left: 4px solid #E8A71D;">
                         <strong>Please return this book tomorrow</strong> to avoid any late penalties.
                    </p>
                    
                    <p>If you need to extend your borrowing period, please consult the library staff as soon as possible.</p>
                    
                    <p>Thank you for your attention to this matter.</p>
                    
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    
                    <p style="font-size: 12px; color: #666;">
                        This is an automated reminder from {library_name}. Please do not reply to this email.
                    </p>
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
    """Check for overdue books and send reminder emails"""
    try:
        # Background thread - create own PostgreSQL connection
        db = _get_postgres_connection()
        cur = db.cursor(cursor_factory=RealDictCursor)
        config = load_email_config()
        library_name = config.get('library_name', 'AOA Library') if config else 'AOA Library'
        
        today = datetime.now().strftime('%Y-%m-%d')
        
        cur.execute("""
            SELECT l.name, l.email, b.title, i.book_id, i.exp, i.issue
            FROM BookIssue i
            JOIN Login l ON l.userid = i.stdid
            JOIN Book b ON b.serial = CAST(i.serial AS INTEGER)
            WHERE i.exp < %s
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
                        <p style="margin: 5px 0;"><strong>Book Title:</strong> {book_title}</p>
                        <p style="margin: 5px 0;"><strong>Book ID:</strong> {book_id}</p>
                        <p style="margin: 5px 0;"><strong>Date Borrowed:</strong> {format_date_for_display(issue_date)}</p>
                        <p style="margin: 5px 0;"><strong>Was Due:</strong> <span style="color: #C0392B; font-weight: bold;">{format_date_for_display(return_date)}</span></p>
                        <p style="margin: 5px 0;"><strong>Days Overdue:</strong> <span style="color: #C0392B; font-weight: bold; font-size: 18px;">{days_overdue} day(s)</span></p>
                    </div>
                    
                    <div style="background-color: #F8D7DA; padding: 15px; border-radius: 5px; border-left: 4px solid #C0392B; margin: 20px 0;">
                        <p style="margin: 5px 0; color: #721C24; font-weight: bold;">
                             IMMEDIATE ACTION REQUIRED
                        </p>
                        <p style="margin: 5px 0; color: #721C24;">
                            Please return this book to the library as soon as possible. Late returns may result in penalties or restrictions on future borrowing privileges.
                        </p>
                    </div>
                    
                    <p>If you have already returned this book, please disregard this message. Otherwise, please return it immediately or contact the library staff.</p>
                    
                    <p>Thank you for your prompt attention to this matter.</p>
                    
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    
                    <p style="font-size: 12px; color: #666;">
                        This is an automated reminder from {library_name}. Please do not reply to this email.
                    </p>
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
    """Run both due tomorrow and overdue checks"""
    print(f"\n{'='*60}")
    print(f"Running daily reminder checks at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    check_and_send_due_tomorrow_reminders()
    check_and_send_overdue_reminders()
    
    print(f"{'='*60}")
    print(f"Reminder checks completed")
    print(f"{'='*60}\n")

def setup_reminder_scheduler():
    """Setup scheduler to run checks at 6pm East African Time"""
    eat_tz = pytz.timezone('Africa/Nairobi')
    schedule.every().day.at("18:00").do(run_daily_reminder_checks)
    print(f"Reminder scheduler initialized - checks will run daily at 6:00 PM EAT")

def run_scheduler_in_background():
    """Run the scheduler in a background thread"""
    while True:
        schedule.run_pending()
        time.sleep(60)

def start_reminder_system():
    """Start the reminder system in a background thread"""
    setup_reminder_scheduler()
    scheduler_thread = threading.Thread(target=run_scheduler_in_background, daemon=True)
    scheduler_thread.start()
    print("Reminder system started in background thread")

# Authentication decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_logged_in' not in session:
            flash('Please login to access this page', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Helper function to format dates for display (handles both strings and date objects)
def format_date_for_display(date_value):
    """Format a date value (string or date object) for display"""
    if date_value is None:
        return ''
    
    # If it's already a datetime or date object, format it directly
    if isinstance(date_value, datetime):
        return date_value.strftime('%B %d, %Y')
    if isinstance(date_value, date):
        return date_value.strftime('%B %d, %Y')
    
    # If it's a string, parse it first
    if isinstance(date_value, str):
        try:
            dt = datetime.strptime(date_value, '%Y-%m-%d')
            return dt.strftime('%B %d, %Y')
        except:
            return date_value
    
    return str(date_value)

# Custom Jinja2 filters
@app.template_filter('date')
def date_filter(value, format='%Y-%m-%d'):
    """Format a date value"""
    if value is None:
        return ''
    if isinstance(value, datetime):
        return value.strftime(format)
    if isinstance(value, date):
        return value.strftime(format)
    if isinstance(value, str):
        if value == 'now':
            return datetime.now().strftime(format)
        try:
            dt = datetime.strptime(value, '%Y-%m-%d')
            return dt.strftime(format)
        except:
            return value
    return str(value)

# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        admin_id = request.form.get('admin_id', '').strip()
        password = request.form.get('password', '').strip()
        
        if admin_id == 'AOA_Admin' and password == 'AOA@2027':
            session['admin_logged_in'] = True
            flash('Login successful!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Wrong ID or Password', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    flash('Logged out successfully', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/admin/download-database')
@login_required
def download_database():
    """Download PostgreSQL database as SQL dump"""
    try:
        get_db()
        cur = get_cursor()
        
        # Get all tables
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """)
        tables = [row['table_name'] for row in cur.fetchall()]
        
        # Generate SQL dump
        sql_dump = []
        sql_dump.append("-- AOA Library System Database Dump")
        sql_dump.append(f"-- Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        sql_dump.append("-- PostgreSQL Database Export")
        sql_dump.append("")
        
        # Export each table
        for table in tables:
            sql_dump.append(f"-- Table: {table}")
            sql_dump.append(f"DROP TABLE IF EXISTS {table} CASCADE;")
            sql_dump.append("")
            
            # Get table structure
            cur.execute(f"""
                SELECT column_name, data_type, character_maximum_length, 
                       is_nullable, column_default
                FROM information_schema.columns
                WHERE table_name = %s
                ORDER BY ordinal_position
            """, (table,))
            columns = cur.fetchall()
            
            # Build CREATE TABLE statement
            create_parts = []
            primary_keys = []
            
            # Get primary keys
            cur.execute(f"""
                SELECT column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = %s AND tc.constraint_type = 'PRIMARY KEY'
            """, (table,))
            pk_cols = [row['column_name'] for row in cur.fetchall()]
            
            for col in columns:
                col_name = col['column_name']
                data_type = col['data_type']
                max_length = col['character_maximum_length']
                is_nullable = col['is_nullable'] == 'YES'
                default = col['column_default']
                
                # Map PostgreSQL types to SQL
                if data_type == 'character varying':
                    type_str = f"VARCHAR({max_length})" if max_length else "TEXT"
                elif data_type == 'integer':
                    type_str = "INTEGER"
                elif data_type == 'date':
                    type_str = "DATE"
                elif data_type == 'serial':
                    type_str = "SERIAL"
                else:
                    type_str = data_type.upper()
                
                col_def = f"{col_name} {type_str}"
                
                if not is_nullable:
                    col_def += " NOT NULL"
                
                if default:
                    # Clean up default value
                    if 'nextval' in str(default):
                        col_def += " DEFAULT " + str(default)
                    else:
                        col_def += f" DEFAULT {default}"
                
                create_parts.append(col_def)
            
            # Add PRIMARY KEY if exists
            if pk_cols:
                create_parts.append(f"PRIMARY KEY ({', '.join(pk_cols)})")
            
            # Add UNIQUE constraints
            cur.execute(f"""
                SELECT column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                WHERE tc.table_name = %s AND tc.constraint_type = 'UNIQUE'
            """, (table,))
            unique_cols = [row['column_name'] for row in cur.fetchall()]
            if unique_cols:
                create_parts.append(f"UNIQUE ({', '.join(unique_cols)})")
            
            sql_dump.append(f"CREATE TABLE {table} (")
            sql_dump.append("    " + ",\n    ".join(create_parts))
            sql_dump.append(");")
            sql_dump.append("")
            
            # Get table data
            cur.execute(f"SELECT * FROM {table} ORDER BY 1")
            rows = cur.fetchall()
            
            if rows:
                # Get column names from the first row (RealDictCursor returns dicts)
                if rows:
                    col_names = list(rows[0].keys())
                    sql_dump.append(f"-- Data for table: {table}")
                    
                    for row in rows:
                        values = []
                        for col_name in col_names:
                            val = row[col_name]
                            if val is None:
                                values.append("NULL")
                            elif isinstance(val, str):
                                # Escape single quotes
                                escaped = val.replace("'", "''")
                                values.append(f"'{escaped}'")
                            elif isinstance(val, (datetime,)):
                                values.append(f"'{val.strftime('%Y-%m-%d')}'")
                            else:
                                values.append(str(val))
                        
                        sql_dump.append(f"INSERT INTO {table} ({', '.join(col_names)}) VALUES ({', '.join(values)});")
                    
                    sql_dump.append("")
        
        sql_content = "\n".join(sql_dump)
        
        # Create response with SQL file
        filename = f"aoa_library_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        
        return Response(
            sql_content,
            mimetype='application/sql',
            headers={
                'Content-Disposition': f'attachment; filename={filename}',
                'Content-Type': 'text/plain; charset=utf-8'
            }
        )
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Error in download_database: {str(e)}")
        print(error_details)
        flash(f'Error generating database backup: {str(e)}', 'error')
        return redirect(url_for('dashboard'))

# Books routes
@app.route('/books/add', methods=['GET', 'POST'])
@login_required
def add_book():
    if request.method == 'POST':
        get_db()
        cur = get_cursor()
        subject = request.form.get('subject', '').strip()
        title = request.form.get('title', '').strip()
        author = request.form.get('author', '').strip()
        book_id = request.form.get('book_id', '').strip()
        copies = request.form.get('copies', '1').strip()
        
        if not (subject and title and author):
            flash('Fill subject, title and author', 'error')
            return redirect(url_for('add_book'))
        
        try:
            copies_int = int(copies) if copies else 1
            if copies_int < 1:
                raise ValueError()
        except ValueError:
            flash('Copies must be a positive integer', 'error')
            return redirect(url_for('add_book'))
        
        custom_id = book_id
        if custom_id:
            if copies_int != 1:
                flash('Provide BOOK ID only when copies = 1', 'error')
                return redirect(url_for('add_book'))
            cur.execute("SELECT 1 FROM Book WHERE book_id=?", (custom_id,))
            if cur.fetchone():
                flash('Book ID already exists', 'error')
                return redirect(url_for('add_book'))
            cur.execute("INSERT INTO Book(subject,title,author,book_id) VALUES(?,?,?,?)", 
                       (subject, title, author, custom_id))
            get_db().commit()
            flash(f"Book {title} added", 'success')
            return redirect(url_for('dashboard'))
        
        for _ in range(copies_int):
            cur.execute("INSERT INTO Book(subject,title,author) VALUES(?,?,?) RETURNING serial", 
                       (subject, title, author))
            new_serial = cur.fetchone()['serial']
            cur.execute("UPDATE Book SET book_id = CAST(serial AS TEXT) WHERE serial = ?", 
                       (new_serial,))
        get_db().commit()
        flash(f"Book {title} added", 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('add_book.html')

@app.route('/books/view')
@login_required
def view_books():
    get_db()
    cur = get_cursor()
    # Use EXISTS subquery to check availability in one efficient query
    cur.execute("""
        SELECT b.subject, b.title, b.author, b.book_id,
               CASE WHEN EXISTS (
                   SELECT 1 FROM BookIssue i WHERE i.book_id = b.book_id
               ) THEN 'No' ELSE 'Yes' END AS available
        FROM Book b
        ORDER BY b.title, b.book_id
    """)
    books = [dict(row) for row in cur.fetchall()]
    return render_template('view_books.html', books=books)

@app.route('/books/edit/<book_id>', methods=['POST'])
@login_required
def edit_book_id(book_id):
    get_db()
    cur = get_cursor()
    password = request.form.get('password', '').strip()
    new_id = request.form.get('new_id', '').strip()
    new_subject = request.form.get('new_subject', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('view_books'))
    
    # Check if book is available
    cur.execute("SELECT 1 FROM BookIssue WHERE book_id=?", (book_id,))
    if cur.fetchone():
        flash('Cannot edit: book is currently assigned to a student', 'error')
        return redirect(url_for('view_books'))
    
    # Get current book data
    cur.execute("SELECT subject, book_id FROM Book WHERE book_id=?", (book_id,))
    current_book = cur.fetchone()
    if not current_book:
        flash('Book not found', 'error')
        return redirect(url_for('view_books'))
    
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
            return redirect(url_for('view_books'))
        updates.append("book_id=?")
        params.append(new_id)
    
    # Update Subject (Category) if provided and different
    if new_subject and new_subject != current_subject:
        updates.append("subject=?")
        params.append(new_subject)
    
    if not updates:
        flash('No changes detected', 'error')
        return redirect(url_for('view_books'))
    
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
    
    return redirect(url_for('view_books'))

@app.route('/books/delete/<book_id>', methods=['POST'])
@login_required
def delete_book(book_id):
    get_db()
    cur = get_cursor()
    password = request.form.get('password', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('view_books'))
    
    cur.execute("SELECT 1 FROM BookIssue WHERE book_id=?", (book_id,))
    if cur.fetchone():
        flash('Cannot delete: book is currently assigned', 'error')
        return redirect(url_for('view_books'))
    
    cur.execute("INSERT INTO DeletedBook(subject, title, author, book_id, deleted) "
               "SELECT subject, title, author, book_id, CURRENT_DATE FROM Book WHERE book_id=?", (book_id,))
    cur.execute("DELETE FROM Book WHERE book_id=?", (book_id,))
    get_db().commit()
    flash(f"Deleted Book ID {book_id}", 'success')
    return redirect(url_for('view_books'))

@app.route('/books/titles')
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

@app.route('/books/titles/delete', methods=['POST'])
@login_required
def delete_title():
    get_db()
    cur = get_cursor()
    title = request.form.get('title', '').strip()
    password = request.form.get('password', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('view_titles'))
    
    cur.execute("SELECT 1 FROM BookIssue i JOIN Book b ON b.book_id=i.book_id WHERE b.title=? LIMIT 1", (title,))
    if cur.fetchone():
        flash('Cannot delete: at least one copy is currently assigned', 'error')
        return redirect(url_for('view_titles'))
    
    cur.execute("DELETE FROM Book WHERE title=?", (title,))
    get_db().commit()
    flash(f"Deleted all copies of '{title}'", 'success')
    return redirect(url_for('view_titles'))

@app.route('/books/deleted')
@login_required
def view_deleted_books():
    get_db()
    cur = get_cursor()
    cur.execute("SELECT subject, title, author, book_id, deleted FROM DeletedBook ORDER BY deleted DESC")
    books = [dict(row) for row in cur.fetchall()]
    return render_template('view_deleted_books.html', books=books)

# Students routes
@app.route('/students/add', methods=['GET', 'POST'])
@login_required
def add_student():
    if request.method == 'POST':
        get_db()
        cur = get_cursor()
        first_name = request.form.get('first_name', '').strip()
        second_name = request.form.get('second_name', '').strip()
        email = request.form.get('email', '').strip()
        
        if not first_name:
            flash('Enter first name', 'error')
            return redirect(url_for('add_student'))
        
        if not email:
            flash('Email is required', 'error')
            return redirect(url_for('add_student'))
        
        if '@' not in email or '.' not in email:
            flash('Please enter a valid email address', 'error')
            return redirect(url_for('add_student'))
        
        full_name = (first_name + (' ' + second_name if second_name else '')).strip()
        cur.execute("SELECT COALESCE(MAX(CAST(userid AS INTEGER)),0) FROM Login")
        row = cur.fetchone()
        # RealDictCursor returns dict, get first value
        max_id = list(row.values())[0] if row else 0
        new_id = (max_id or 0) + 1
        cur.execute("INSERT INTO Login(name, userid, email) VALUES(?, ?, ?)", (full_name, str(new_id), email))
        get_db().commit()
        flash(f"Student {full_name} added", 'success')
        return redirect(url_for('dashboard'))
    
    return render_template('add_student.html')

@app.route('/students/view')
@login_required
def view_students():
    get_db()
    cur = get_cursor()
    cur.execute('SELECT name, userid, email FROM Login')
    students = [dict(row) for row in cur.fetchall()]
    return render_template('view_students.html', students=students)

@app.route('/students/delete/<userid>', methods=['POST'])
@login_required
def delete_student(userid):
    get_db()
    cur = get_cursor()
    password = request.form.get('password', '').strip()
    
    if password != 'AOA@2027':
        flash('Wrong password', 'error')
        return redirect(url_for('view_students'))
    
    cur.execute("SELECT 1 FROM BookIssue WHERE stdid=? LIMIT 1", (userid,))
    if cur.fetchone():
        flash('Cannot delete: student has active assignments', 'error')
        return redirect(url_for('view_students'))
    
    cur.execute("INSERT INTO DeletedLogin(name, userid, deleted) "
               "SELECT name, userid, CURRENT_DATE FROM Login WHERE userid=?", (userid,))
    cur.execute("DELETE FROM Login WHERE userid=?", (userid,))
    get_db().commit()
    flash('Student deleted', 'success')
    return redirect(url_for('view_students'))

@app.route('/students/deleted')
@login_required
def view_deleted_students():
    get_db()
    cur = get_cursor()
    cur.execute("SELECT name, userid, deleted FROM DeletedLogin ORDER BY deleted DESC")
    students = [dict(row) for row in cur.fetchall()]
    return render_template('view_deleted_students.html', students=students)

# Operations routes
@app.route('/operations/assign', methods=['GET', 'POST'])
@login_required
def assign_book():
    if request.method == 'POST':
        get_db()
        cur = get_cursor()
        student_id = request.form.get('student_id', '').strip()
        title = request.form.get('title', '').strip()
        book_ids_str = request.form.get('book_ids', '[]')
        try:
            book_ids = json.loads(book_ids_str)
        except:
            flash('Invalid book IDs format', 'error')
            return redirect(url_for('assign_book'))
        return_date = request.form.get('return_date', '').strip()
        assigned_by = request.form.get('assigned_by', '').strip()
        
        if not (student_id and title and book_ids and assigned_by):
            flash('Fill all required fields', 'error')
            return redirect(url_for('assign_book'))
        
        if len(return_date) != 10 or return_date[4] != '-' or return_date[7] != '-':
            flash('Return date must be YYYY-MM-DD', 'error')
            return redirect(url_for('assign_book'))
        
        # Check availability
        for bid in book_ids:
            cur.execute("SELECT 1 FROM BookIssue WHERE book_id=?", (bid,))
            if cur.fetchone():
                flash(f"Book ID {bid} is no longer available", 'error')
                return redirect(url_for('assign_book'))
        
        # Get student email
        cur.execute("SELECT email FROM Login WHERE userid=?", (student_id,))
        email_row = cur.fetchone()
        student_email = email_row['email'] if email_row else None
        
        if not student_email:
            flash('No email found for student. Please update student email first.', 'error')
            return redirect(url_for('assign_book'))
        
        # Get student name
        cur.execute("SELECT name FROM Login WHERE userid=?", (student_id,))
        student_name = cur.fetchone()['name']
        
        # Insert assignments
        for bid in book_ids:
            cur.execute("SELECT serial FROM Book WHERE book_id=?", (bid,))
            serial = cur.fetchone()['serial']
            cur.execute("INSERT INTO BookIssue(stdid, serial, issue, exp, book_id, assigned_by) "
                       "VALUES(?, ?, CURRENT_DATE, ?, ?, ?)", (student_id, serial, return_date, bid, assigned_by))
        get_db().commit()
        
        # Send email
        config = load_email_config()
        library_name = config.get('library_name', 'AOA Library') if config else 'AOA Library'
        
        book_list_html = '<ul>' + ''.join([f'<li><strong>{title}</strong> (Book ID: {bid})</li>' for bid in book_ids]) + '</ul>'
        
        email_subject = f'{library_name} - Book Assignment Confirmation'
        email_body = f'''
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
            <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
                <h2 style="color: #265530; border-bottom: 3px solid #64A772; padding-bottom: 10px;">Book Assignment Confirmation</h2>
                
                <p>Dear <strong>{student_name}</strong>,</p>
                
                <p>This is to confirm that the following book(s) have been assigned to you from the {library_name}:</p>
                
                {book_list_html}
                
                <div style="background-color: #fff; padding: 15px; border-left: 4px solid #E8A71D; margin: 20px 0;">
                    <p style="margin: 5px 0;"><strong>Date Borrowed:</strong> {datetime.now().strftime('%B %d, %Y')}</p>
                    <p style="margin: 5px 0;"><strong>Return Date:</strong> <span style="color: #C87140; font-weight: bold;">{datetime.strptime(return_date, '%Y-%m-%d').strftime('%B %d, %Y')}</span></p>
                    <p style="margin: 5px 0;"><strong>Assigned By:</strong> {assigned_by}</p>
                </div>
                
                <p style="color: #C0392B; font-weight: bold;">Please return the book(s) by the date mentioned above to avoid any penalties.</p>
                
                <p>If you have any questions, please contact the library staff.</p>
                
                <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                
                <p style="font-size: 12px; color: #666;">
                    This is an automated message from {library_name}. Please do not reply to this email.
                </p>
            </div>
        </body>
        </html>
        '''
        
        send_email(student_email, email_subject, email_body, background=True)
        flash(f"Assigned {len(book_ids)} copy(ies) - Email queued", 'success')
        return redirect(url_for('dashboard'))
    
    # GET request - display form
    get_db()
    cur = get_cursor()
    cur.execute("SELECT name, userid FROM Login ORDER BY name")
    students = [dict(row) for row in cur.fetchall()]
    
    cur.execute("SELECT DISTINCT title FROM Book ORDER BY title")
    books = [row['title'] for row in cur.fetchall()]
    
    # Get available books for initial load
    available_books = []
    if books:
        cur.execute("SELECT b.book_id FROM Book b WHERE b.title=? AND NOT EXISTS "
                   "(SELECT 1 FROM BookIssue i WHERE i.book_id=b.book_id) ORDER BY b.book_id", (books[0],))
        available_books = [row['book_id'] for row in cur.fetchall()]
    
    return render_template('assign_book.html', students=students, books=books, 
                         available_books=available_books, staff_members=STAFF_MEMBERS,
                         current_date=datetime.now().strftime('%Y-%m-%d'))

@app.route('/api/get_available_books')
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

@app.route('/operations/assignments')
@login_required
def view_assignments():
    get_db()
    cur = get_cursor()
    cur.execute("""
        SELECT l.name AS student,
               b.title AS title,
               i.book_id AS book_id,
               i.issue AS date_assigned,
               i.exp AS return_date,
               i.assigned_by AS assigned_by
        FROM BookIssue i
        JOIN Login l ON l.userid = i.stdid
        JOIN Book b ON b.serial = CAST(i.serial AS INTEGER)
        ORDER BY i.issue DESC, l.name, b.title, i.book_id
    """)
    assignments = [dict(row) for row in cur.fetchall()]
    return render_template('view_assignments.html', assignments=assignments)

@app.route('/operations/return', methods=['GET', 'POST'])
@login_required
def return_book():
    if request.method == 'POST':
        get_db()
        cur = get_cursor()
        student_id = request.form.get('student_id', '').strip()
        title = request.form.get('title', '').strip()
        book_ids_str = request.form.get('book_ids', '[]')
        try:
            book_ids = json.loads(book_ids_str)
        except:
            flash('Invalid book IDs format', 'error')
            return redirect(url_for('return_book'))
        return_date = request.form.get('return_date', '').strip()
        returned_by = request.form.get('returned_by', '').strip()
        
        if not (student_id and title and book_ids and returned_by):
            flash('Fill all required fields', 'error')
            return redirect(url_for('return_book'))
        
        # Get student info
        cur.execute("SELECT name, email FROM Login WHERE userid=?", (student_id,))
        student_row = cur.fetchone()
        student_name = student_row['name']
        student_email = student_row['email'] if student_row else None
        
        # Get issue date
        cur.execute("SELECT i.issue FROM BookIssue i WHERE i.stdid=? AND i.book_id=?", 
                   (student_id, book_ids[0]))
        row_issue = cur.fetchone()
        if row_issue:
            issue_date_obj = row_issue['issue']
            # Convert date object to string if needed
            if isinstance(issue_date_obj, date):
                issue_date = issue_date_obj.strftime('%Y-%m-%d')
            else:
                issue_date = str(issue_date_obj)
        else:
            issue_date = return_date
        
        # Insert return records
        cur.execute("INSERT INTO BookReturn(stdid, title, copies, issue, returned) "
                   "VALUES(?, ?, ?, ?, ?)", (student_id, title, len(book_ids), issue_date, return_date))
        
        for bid in book_ids:
            cur.execute("INSERT INTO BookReturnDetail(stdid, title, book_id, issue, returned, returned_by) "
                       "VALUES(?, ?, ?, ?, ?, ?)", 
                       (student_id, title, bid, issue_date, return_date, returned_by))
            cur.execute("DELETE FROM BookIssue WHERE stdid=? AND book_id=?", (student_id, bid))
        get_db().commit()
        
        # Send email
        if student_email:
            config = load_email_config()
            library_name = config.get('library_name', 'AOA Library') if config else 'AOA Library'
            
            book_list_html = '<ul>' + ''.join([f'<li><strong>{title}</strong> (Book ID: {bid})</li>' for bid in book_ids]) + '</ul>'
            
            email_subject = f'{library_name} - Book Return Confirmation'
            email_body = f'''
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; background-color: #f9f9f9; border-radius: 10px;">
                    <h2 style="color: #265530; border-bottom: 3px solid #64A772; padding-bottom: 10px;">Book Return Confirmation</h2>
                    
                    <p>Dear <strong>{student_name}</strong>,</p>
                    
                    <p style="color: #27ae60; font-weight: bold;">Thank you! You have successfully returned the following book(s) to the {library_name}:</p>
                    
                    {book_list_html}
                    
                    <div style="background-color: #fff; padding: 15px; border-left: 4px solid #64A772; margin: 20px 0;">
                        <p style="margin: 5px 0;"><strong>Date Borrowed:</strong> {format_date_for_display(issue_date)}</p>
                        <p style="margin: 5px 0;"><strong>Date Returned:</strong> {format_date_for_display(return_date)}</p>
                        <p style="margin: 5px 0;"><strong>Processed By:</strong> {returned_by}</p>
                    </div>
                    
                    <p>Your return has been recorded in our system. You are welcome to borrow more books anytime!</p>
                    
                    <p>Thank you for using the {library_name}.</p>
                    
                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    
                    <p style="font-size: 12px; color: #666;">
                        This is an automated message from {library_name}. Please do not reply to this email.
                    </p>
                </div>
            </body>
            </html>
            '''
            
            send_email(student_email, email_subject, email_body, background=True)
            flash(f"Returned {len(book_ids)} ID(s) - Email queued", 'success')
        else:
            flash(f"Returned {len(book_ids)} ID(s)", 'success')
        
        return redirect(url_for('dashboard'))
    
    # GET request - display form
    get_db()
    cur = get_cursor()
    cur.execute("SELECT DISTINCT l.name, l.userid FROM BookIssue i JOIN Login l ON l.userid=i.stdid ORDER BY l.name")
    students = [dict(row) for row in cur.fetchall()]
    
    # Get titles for first student if any
    books = []
    if students:
        cur.execute("SELECT DISTINCT b.title FROM BookIssue i JOIN Book b ON b.serial=CAST(i.serial AS INTEGER) "
                   "WHERE i.stdid=? ORDER BY b.title", (students[0]['userid'],))
        books = [row['title'] for row in cur.fetchall()]
    
    # Get available books for initial load
    available_books = []
    if books:
        cur.execute("SELECT b.book_id FROM BookIssue i JOIN Book b ON b.serial=CAST(i.serial AS INTEGER) "
                   "WHERE i.stdid=? AND b.title=? ORDER BY b.book_id", 
                   (students[0]['userid'], books[0]))
        available_books = [row['book_id'] for row in cur.fetchall()]
    
    return render_template('return_book.html', students=students, books=books, 
                         available_books=available_books, staff_members=STAFF_MEMBERS)

@app.route('/api/get_student_books')
@login_required
def get_student_books():
    get_db()
    cur = get_cursor()
    student_id = request.args.get('student_id', '').strip()
    title = request.args.get('title', '').strip()
    
    if not (student_id and title):
        return jsonify([])
    
    cur.execute("SELECT b.book_id FROM BookIssue i JOIN Book b ON b.serial=CAST(i.serial AS INTEGER) "
               "WHERE i.stdid=? AND b.title=? ORDER BY b.book_id", (student_id, title))
    books = [row['book_id'] for row in cur.fetchall()]
    return jsonify(books)

@app.route('/operations/returns')
@login_required
def view_returns():
    get_db()
    cur = get_cursor()
    cur.execute("""
        SELECT l.name AS student,
               d.title,
               STRING_AGG(d.book_id, ', ') AS ids,
               MIN(d.issue) AS issue,
               MAX(d.returned) AS returned,
               MAX(d.returned_by) AS returned_by
        FROM BookReturnDetail d
        JOIN Login l ON l.userid = d.stdid
        GROUP BY l.name, d.title, DATE(d.returned)
        ORDER BY d.returned DESC
    """)
    returns_detail = [dict(row) for row in cur.fetchall()]
    
    cur.execute("""
        SELECT l.name AS student,
               r.title,
               '(' || CAST(r.copies AS TEXT) || ' copies)' AS ids,
               r.issue,
               r.returned
        FROM BookReturn r
        LEFT JOIN (
          SELECT DISTINCT stdid, title, DATE(returned) AS d
          FROM BookReturnDetail
        ) d ON d.stdid = r.stdid AND d.title = r.title AND d.d = DATE(r.returned)
        JOIN Login l ON l.userid = r.stdid
        WHERE d.stdid IS NULL
        ORDER BY r.returned DESC
    """)
    returns_old = [dict(row) for row in cur.fetchall()]
    
    return render_template('view_returns.html', returns=returns_detail + returns_old)

# Staff members list
STAFF_MEMBERS = ['Afsa', 'Alex', 'Angella', 'Arun', 'Claudine', 'Emmy', 'Gaidi', 'George', 
                 'Guylain', 'Innocent I', 'Innocent M', 'Jeanette', 'Josue', 'Kelly', 'Linda', 
                 'Marie Josee', 'Nepo', 'Obed', 'Sindi', 'Wendy', 'Jacky']

@app.route('/api/get_titles')
@login_required
def get_titles():
    get_db()
    cur = get_cursor()
    student_id = request.args.get('student_id', '').strip()
    if not student_id:
        return jsonify([])
    
    cur.execute("SELECT DISTINCT b.title FROM BookIssue i JOIN Book b ON b.serial=CAST(i.serial AS INTEGER) "
               "WHERE i.stdid=? ORDER BY b.title", (student_id,))
    titles = [row['title'] for row in cur.fetchall()]
    return jsonify(titles)

@app.route('/admin/test-email', methods=['GET', 'POST'])
@login_required
def test_email():
    """Test email configuration"""
    if request.method == 'POST':
        test_email_address = request.form.get('test_email', '').strip()
        if not test_email_address:
            flash('Please provide a test email address', 'error')
            return redirect(url_for('test_email'))
        
        config = load_email_config()
        if not config:
            flash('Email configuration not found. Check environment variables.', 'error')
            return redirect(url_for('test_email'))
        
        # Test email - send synchronously (not queued) for immediate feedback
        subject = 'AOA Library - Test Email'
        body = '''
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2>Test Email from AOA Library System</h2>
            <p>If you received this email, your email configuration is working correctly!</p>
            <p>Time: ''' + datetime.now().strftime('%Y-%m-%d %H:%M:%S') + '''</p>
        </body>
        </html>
        '''
        
        # Send directly (not queued) so we get immediate feedback
        result = send_email_direct(test_email_address, subject, body)
        if result:
            flash(f'Test email sent successfully to {test_email_address}!', 'success')
        else:
            flash('Failed to send test email. Check Render logs for details.', 'error')
        
        return redirect(url_for('test_email'))
    
    # GET request - show test form
    config = load_email_config()
    config_status = {}
    env_check = {}
    
    # Check environment variables directly
    import os
    env_check = {
        'RESEND_API_KEY': 'Set' if os.getenv('RESEND_API_KEY') else 'Not set',
        'EMAIL_ADDRESS': os.getenv('EMAIL_ADDRESS', 'Not set'),
        'EMAIL_ENABLED': os.getenv('EMAIL_ENABLED', 'Not set'),
    }
    
    if config:
        config_status = {
            'enabled': config.get('enabled', False),
            'provider': 'resend',
            'has_email': bool(config.get('email_address')),
            'email_address': config.get('email_address', 'Not set'),
            'has_resend_key': bool(config.get('resend_api_key')),
            'resend_api_key': 'Set' if config.get('resend_api_key') else 'Not set'
        }
    
    return render_template('test_email.html', config=config_status, env_check=env_check)

try:
    with app.app_context():
        get_db()
        # Populate initial students if database is empty
        populate_initial_students()
        start_email_worker()
        start_reminder_system()
        print("App initialized: Email worker and reminder system started")
except Exception as e:
    print(f"Warning: Could not initialize app components: {e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)


# app/services/email_service.py
import os
import json
import smtplib
import threading
import queue
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

email_queue = queue.Queue()
email_worker_thread = None


def load_email_config():
    if os.getenv('SMTP_SERVER'):
        return {
            'enabled': os.getenv('EMAIL_ENABLED', 'true').lower() == 'true',
            'smtp_server': os.getenv('SMTP_SERVER'),
            'smtp_port': int(os.getenv('SMTP_PORT', '587')),
            'email_address': os.getenv('EMAIL_ADDRESS'),
            'email_password': os.getenv('EMAIL_PASSWORD'),
            'library_name': os.getenv('LIBRARY_NAME', 'AOA Library')
        }

    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'email_config.json')
        config_path = os.path.abspath(config_path)
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading email config: {e}")
        return None


def sanitize_email(email):
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
    config = load_email_config()

    if not config:
        print("ERROR: Email config not found - check env or email_config.json")
        return False

    if not config.get('enabled', False):
        print("Email sending is disabled in config")
        return False

    if not config.get('email_address'):
        print("ERROR: email_address not set in config")
        return False

    if not config.get('email_password'):
        print("ERROR: email_password not set in config")
        return False

    if not config.get('smtp_server'):
        print("ERROR: smtp_server not set in config")
        return False

    print(
        f"Email config loaded: server={config.get('smtp_server')}, "
        f"port={config.get('smtp_port')}, from={config.get('email_address')}, "
        f"password_set={'Yes' if config.get('email_password') else 'No'}"
    )

    to_email = sanitize_email(to_email)
    if not to_email:
        print("Invalid or dangerous email address provided")
        return False

    try:
        msg = MIMEMultipart()
        msg['From'] = config['email_address']
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        email_password = config['email_password'].replace(' ', '')

        print(f"Attempting to send email to {to_email} via {config['smtp_server']}:{config['smtp_port']}")
        server = smtplib.SMTP(config['smtp_server'], config['smtp_port'])
        server.starttls()
        server.login(config['email_address'], email_password)
        server.send_message(msg)
        server.quit()

        print(f"✓ Email sent successfully to {to_email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        print(f"ERROR: SMTP Authentication failed - {e}")
        return False
    except smtplib.SMTPException as e:
        print(f"ERROR: SMTP error - {e}")
        return False
    except Exception as e:
        print(f"ERROR sending email: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False


def send_email(to_email, subject, body, background=True):
    if background:
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
    print("Email worker thread started")
    import time
    last_heartbeat = time.time()
    heartbeat_interval = 30

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
                print(f"Email worker: Failed to send email to {email_data['to']}")
            email_queue.task_done()
        except queue.Empty:
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
            except Exception:
                pass


def start_email_worker():
    global email_worker_thread

    if email_worker_thread is None or not email_worker_thread.is_alive():
        email_worker_thread = threading.Thread(target=email_worker, daemon=True)
        email_worker_thread.start()
        print("Email worker thread initialized")
        import time
        time.sleep(0.1)
        if email_worker_thread.is_alive():
            print("Email worker thread confirmed running")
        else:
            print("WARNING: Email worker thread started but is not alive!")

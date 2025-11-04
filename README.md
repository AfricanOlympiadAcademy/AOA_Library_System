# AOA Library Management System - Web Version

A fully web-based library management system with all the features of the desktop version. Built with Flask and modern web technologies for easy access from any device.

## Features

All desktop features have been preserved in the web version:
- Complete book management with categories
- Student registration and management
- Book assignment and return operations
- Email notifications (assignment, return, overdue reminders)
- Staff tracking for all operations
- Deleted items history
- Modern, responsive web interface

## Installation & Setup

### Requirements
- Python 3.x
- Web browser (Chrome, Firefox, Safari, Edge)
- Internet connection (for email features)

### Quick Start

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Configure email (optional):**
```bash
cp email_config.json.example email_config.json
# Edit email_config.json with your email credentials
```

3. **Run the web server:**
```bash
python web_app.py
```

4. **Access the system:**
   - Open your browser
   - Navigate to `http://localhost:5000`
   - Login with:
     - **Admin ID:** `AOA_Admin`
     - **Password:** `AOA@2027`

## Web-Specific Features

### Responsive Design
- Works on desktop, tablet, and mobile devices
- Touch-friendly interface
- Optimized for various screen sizes

### Real-time Updates
- Instant feedback on all operations
- Flash messages for user notifications
- No page refreshes needed for many operations

### Modern UI
- Clean, professional design
- AOA Library branding
- Intuitive navigation
- Accessible controls

## Deployment

### Local Network Access

To access from other devices on your local network:

1. Find your computer's IP address:
   - Windows: `ipconfig` in command prompt
   - Mac/Linux: `ifconfig` in terminal

2. Update the Flask app to bind to all interfaces:
   - Already configured: `app.run(host='0.0.0.0', port=5000)`

3. Access from other devices:
   - Use `http://YOUR_IP_ADDRESS:5000`

### Production Deployment

For production deployment, consider:

**Option 1: Gunicorn (Recommended)**
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 web_app:app
```

**Option 2: Docker**
Create a `Dockerfile`:
```dockerfile
FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "web_app:app"]
```

**Option 3: Cloud Platforms**
- Heroku
- AWS Elastic Beanstalk
- Google Cloud App Engine
- DigitalOcean App Platform

## Database

The web version uses the same SQLite database as the desktop version (`library.db`). Both versions can share the same database file, allowing for seamless migration or dual usage.

## Differences from Desktop Version

| Feature | Desktop | Web |
|---------|---------|-----|
| Installation | Executable | Web browser only |
| Access | Single machine | Any device with network access |
| Updates | Manual | Instant on server |
| Backup | Manual DB copy | Same database file |
| Email | Same | Same |
| Features | All | All |

## File Structure

```
Library-Management/
├── web_app.py              # Flask web application
├── app.py                  # Original desktop app (still works)
├── requirements.txt        # Python dependencies
├── email_config.json       # Email settings
├── library.db              # Shared database
├── templates/              # HTML templates
│   ├── login.html
│   ├── dashboard.html
│   ├── add_book.html
│   ├── view_books.html
│   └── ... (all pages)
├── static/
│   ├── css/
│   │   └── style.css      # Modern styling
│   └── js/
│       └── main.js        # JavaScript
└── README_WEB.md          # This file
```

## Security Notes

**For Production Deployment:**

1. **Change the secret key** in `web_app.py`:
```python
app.secret_key = 'your-unique-secret-key-here'
```

2. **Enable HTTPS** using SSL certificates

3. **Use a proper WSGI server** (Gunicorn, uWSGI) instead of Flask's development server

4. **Implement firewall rules** to restrict access if needed

5. **Regular database backups**

6. **Keep email configuration secure**

## Troubleshooting

### Port Already in Use
If port 5000 is busy:
```python
# Edit web_app.py, change last line:
app.run(debug=True, host='0.0.0.0', port=5001)
```

### Database Locked
- Close the desktop app if running
- Ensure only one instance accessing the database

### Email Not Working
- Check `email_config.json` exists
- Verify email settings are correct
- Test with a simple SMTP connection

### Styling Issues
- Clear browser cache (Ctrl+F5)
- Check static files are loading
- Verify `static/css/style.css` exists

## Migration from Desktop

To migrate from desktop to web:

1. Your existing `library.db` works as-is
2. Run web version alongside desktop (not at same time due to DB locking)
3. Copy `email_config.json` to new location if needed
4. All data is immediately available in web version

## Support

For issues specific to the web version:
- Check browser console for errors
- Review Flask server logs
- Verify all static files are present
- Test with different browsers

## License

Same as desktop version - for AOA Library use.


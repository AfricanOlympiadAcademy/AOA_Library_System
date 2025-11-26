# AOA Library Management System

A web-based library management system built with Flask. Manage books, students, assignments, and returns with automated email notifications.

## Features

- Book management with categories and tracking
- Student registration and management
- Book assignment and return operations
- Automated email notifications via Resend API
- Staff tracking for all operations
- History of deleted items
- Responsive web interface

## Quick Start

1. **Install dependencies:**
```bash
pip install -r requirements.txt
```

2. **Configure email:**
```bash
cp email_config.json.example email_config.json
# Edit email_config.json with your Resend API key
```

3. **Run the application:**
```bash
python app.py
```

4. **Access the system:**
   - Open browser to `http://localhost:5000`

## Project Structure

```
AOA_Library_System/
├── app.py                      # Main Flask application
├── requirements.txt            # Python dependencies
├── render.yaml                 # Render deployment config
├── email_config.json.example   # Email config template
├── library.db                  # SQLite database
├── templates/                  # HTML templates
│   ├── login.html
│   ├── dashboard.html
│   ├── add_book.html
│   └── ...
└── static/
    ├── css/style.css
    └── js/
        ├── main.js
        └── alerts.js
```

## Email Configuration

### Local Development
1. Copy `email_config.json.example` to `email_config.json`
2. Add your Resend API key
3. File is gitignored for security

### Production (Render)
Set environment variables in Render Dashboard:
- `RESEND_API_KEY` - Your Resend API key
- `EMAIL_ADDRESS` - From email address
- `EMAIL_ENABLED` - Set to `true`

Get your API key at [resend.com](https://resend.com)

## Deployment to Render

1. Push code to GitHub
2. Connect repository in Render Dashboard
3. Set environment variables (see above)
4. Deploy automatically via `render.yaml`

## Security

- Never commit `email_config.json` (already in `.gitignore`)
- Use environment variables for production
- Change `app.secret_key` in production
- If API key is exposed: revoke immediately and generate new one

## Troubleshooting

**Email not working:**
- Verify `RESEND_API_KEY` is set
- Check domain is verified in Resend
- Review app logs for errors

**Port already in use:**
Change port in `app.py`: `app.run(port=5001)`

**Database locked:**
Close any other instances accessing `library.db`

## License

For AOA Library use.


# Free Hosting Guide for AOA Library System

## Best Free Options with Persistent Database Storage

### Option 1: Render (Recommended - Easiest)

**Why Render?**
- ✅ Free tier with 750 hours/month
- ✅ Persistent disk storage (database won't be lost)
- ✅ Easy deployment from GitHub
- ✅ Automatic SSL certificates
- ✅ Free PostgreSQL option (if you want to upgrade later)

**Steps to Deploy on Render:**

1. **Prepare your repository:**
   ```bash
   # Make sure your code is on GitHub
   git add .
   git commit -m "Ready for deployment"
   git push origin main
   ```

2. **Create a `render.yaml` file** (optional, for easier setup):
   ```yaml
   services:
     - type: web
       name: aoa-library-system
       env: python
       buildCommand: pip install -r requirements.txt
       startCommand: gunicorn app:app
       envVars:
         - key: PYTHON_VERSION
           value: 3.11.0
   ```

3. **Deploy on Render:**
   - Go to https://render.com
   - Sign up with GitHub
   - Click "New +" → "Web Service"
   - Connect your GitHub repository
   - Settings:
     - **Name**: aoa-library-system
     - **Environment**: Python 3
     - **Build Command**: `pip install -r requirements.txt`
     - **Start Command**: `gunicorn app:app --bind 0.0.0.0:$PORT`
     - **Plan**: Free
   - Click "Create Web Service"

4. **Important for Database Persistence:**
   - Render's free tier uses persistent disk storage
   - Your `library.db` file will persist across deployments
   - The database is stored in the same directory as your app

**Note:** Add `gunicorn` to your `requirements.txt`:
```
gunicorn
```

---

### Option 2: Railway

**Why Railway?**
- ✅ $5 free credit per month
- ✅ Persistent storage
- ✅ Simple deployment

**Steps:**

1. Go to https://railway.app
2. Sign up with GitHub
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repository
5. Railway auto-detects Python and deploys
6. Add environment variable if needed: `PORT=5000`

---

### Option 3: PythonAnywhere

**Why PythonAnywhere?**
- ✅ Designed for Python apps
- ✅ Persistent storage
- ✅ Free tier available

**Steps:**

1. Go to https://www.pythonanywhere.com
2. Sign up for free account
3. Upload your files via Files tab
4. Create a new Web App
5. Point it to your `app.py`
6. Database file persists in your home directory

---

### Option 4: Fly.io (Advanced)

**Why Fly.io?**
- ✅ 3 free VMs
- ✅ Persistent volumes for database
- ✅ Good for production

**Steps:**

1. Install Fly CLI: `curl -L https://fly.io/install.sh | sh`
2. Create `fly.toml`:
   ```toml
   app = "aoa-library"
   primary_region = "iad"

   [build]

   [http_service]
     internal_port = 5000
     force_https = true
     auto_stop_machines = true
     auto_start_machines = true
     min_machines_running = 0

   [[vm]]
     memory_mb = 256
   ```

3. Create volume: `fly volumes create data --size 1`
4. Deploy: `fly deploy`

---

## Important: Update Your App for Production

Before deploying, make sure to:

1. **Update `requirements.txt`** to include:
   ```
   gunicorn
   ```

2. **Update `app.py`** for production:
   ```python
   if __name__ == '__main__':
       # Development
       app.run(debug=True, host='0.0.0.0', port=5000)
   ```

   For production, use Gunicorn:
   ```bash
   gunicorn app:app --bind 0.0.0.0:$PORT
   ```

3. **Set environment variables** (if needed):
   - `PORT`: Usually set automatically by hosting platform
   - `FLASK_ENV`: Set to `production`

4. **Backup your database** before first deployment:
   ```bash
   cp library.db library.db.backup
   ```

---

## Database Backup Strategy

Even with persistent storage, always backup:

1. **Manual backup script** (run periodically):
   ```python
   # backup_db.py
   import shutil
   from datetime import datetime
   
   timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
   shutil.copy('library.db', f'backups/library_{timestamp}.db')
   ```

2. **Automated backups** (if hosting platform supports cron jobs)

---

## Recommended: Render (Easiest Setup)

**Render is recommended because:**
- ✅ Easiest to set up
- ✅ Persistent storage on free tier
- ✅ Automatic deployments from GitHub
- ✅ Free SSL certificates
- ✅ Good documentation

**Limitation:**
- Free tier spins down after 15 min inactivity (but wakes up automatically on next request)

---

## Quick Start with Render

1. Push code to GitHub
2. Sign up at render.com with GitHub
3. Create new Web Service
4. Connect repository
5. Use these settings:
   - Build: `pip install -r requirements.txt`
   - Start: `gunicorn app:app --bind 0.0.0.0:$PORT`
6. Deploy!

Your database will persist! 🎉


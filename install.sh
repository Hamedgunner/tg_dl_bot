#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Define installation directory (short, lowercase name)
INSTALL_DIR="/opt/tg_dl_bot"

echo "██████████████████████████████████████████████████████████"
echo "█             ربات دانلودر شبکه‌های اجتماعی              █"
echo "█                     راه انداز خودکار                     █"
echo "██████████████████████████████████████████████████████████"
echo ""
echo "این اسکریپت ربات دانلودر تلگرام را روی سیستم عامل Ubuntu 22.04 LTS شما نصب و پیکربندی می‌کند."
echo "شامل نصب پیش نیازها، راه‌اندازی پایگاه داده، Nginx و Supervisor."
echo "قبل از ادامه اطمینان حاصل کنید که یک نام دامنه به آدرس IP این سرور متصل شده است."
echo "برای شروع، این اسکریپت نیاز به دسترسی sudo دارد."
echo ""
read -p "برای ادامه دکمه Enter را فشار دهید یا Ctrl+C را برای خروج بزنید..."

# Ensure running as root or with sudo
if [ "$EUID" -ne 0 ]; then
  echo "لطفاً این اسکریپت را با sudo اجرا کنید: sudo ./install.sh"
  exit 1
fi

echo "[۱/۷] به‌روزرسانی سیستم و نصب پیش‌نیازها..."
apt update -y
apt upgrade -y
apt install -y git python3 python3-pip python3-venv ffmpeg mariadb-server libmariadb-dev nginx supervisor certbot python3-certbot-nginx rsync curl

# Clone the repo if it's not already there. Assumes this script is either run from a temp clone or downloaded directly.
GIT_REPO_URL="https://github.com/Hamedgunner/tg_dl_bot.git" # <--- Updated with your GitHub repo URL

if [ ! -d "$INSTALL_DIR" ]; then
    echo "در حال کلون کردن مخزن گیت‌هاب از $GIT_REPO_URL به $INSTALL_DIR ..."
    git clone $GIT_REPO_URL $INSTALL_DIR
else
    echo "دایرکتوری نصب ($INSTALL_DIR) از قبل وجود دارد. به روزرسانی مخزن..."
    git -C "$INSTALL_DIR" pull
fi

cd "$INSTALL_DIR" || { echo "خطا: نتوانستم به دایرکتوری نصب بروم. اسکریپت متوقف شد."; exit 1; }

echo "[۲/۷] ایجاد محیط مجازی پایتون و نصب وابستگی‌ها..."
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -U yt-dlp # Ensure yt-dlp is latest version

# Create downloads directory if it doesn't exist (ignored by Git)
mkdir -p "$INSTALL_DIR/downloads"

echo "[۳/۷] تنظیمات پایگاه داده (MariaDB/MySQL)..."

read -s -p "رمز عبور کاربری که میخواهید ربات برای دیتابیس خود استفاده کند را وارد کنید (این رمز برای 'bot_user' استفاده خواهد شد): " DB_PASSWORD_PROMPT
echo ""
# Run MariaDB/MySQL commands
mysql -u root -p <<EOF
CREATE DATABASE IF NOT EXISTS telegram_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'bot_user'@'localhost' IDENTIFIED BY '${DB_PASSWORD_PROMPT}';
GRANT ALL PRIVILEGES ON telegram_bot.* TO 'bot_user'@'localhost';
FLUSH PRIVILEGES;
EOF

echo "اجرای اسکریپت شمای پایگاه داده..."
mysql -u bot_user -p"$DB_PASSWORD_PROMPT" telegram_bot < schemas.sql

echo "تنظیم پایگاه داده به پایان رسید."

echo "[۴/۷] پیکربندی متغیرهای محیطی (.env) و جزئیات ربات."
read -p "توکن ربات تلگرام خود را وارد کنید (از @BotFather دریافت کنید): " BOT_TOKEN_PROMPT
read -p "آیدی عددی تلگرام ادمین(ها) را وارد کنید (می‌توانید چندین آیدی را با کاما جدا کنید): " ADMIN_TELEGRAM_IDS_PROMPT
read -p "نام کاربری برای اولین ادمین پنل وب (مثلاً admin): " ADMIN_USERNAME_PROMPT
read -s -p "رمز عبور برای اولین ادمین پنل وب: " ADMIN_PASSWORD_PROMPT
echo ""
read -p "آیدی عددی تلگرام خود برای دریافت اعلان‌های ادمین از پنل وب (اختیاری): " ADMIN_TELEGRAM_ID_FOR_NOTIF_PROMPT
read -p "نام دامین که به آدرس IP این سرور اشاره می‌کند (مثلاً yourbot.com): " DOMAIN_NAME_PROMPT

# Generate a random Flask secret key
FLASK_SECRET_KEY=$(openssl rand -base64 32)

cat > "$INSTALL_DIR/.env" <<EOL
BOT_TOKEN=${BOT_TOKEN_PROMPT}
DB_HOST=localhost
DB_USER=bot_user
DB_PASSWORD=${DB_PASSWORD_PROMPT}
DB_NAME=telegram_bot
ADMIN_TELEGRAM_IDS=${ADMIN_TELEGRAM_IDS_PROMPT}
FLASK_SECRET_KEY=${FLASK_SECRET_KEY}
UPLOAD_FOLDER=${INSTALL_DIR}/downloads
WEBHOOK_PORT=8443
WEBHOOK_LISTEN_ADDRESS=0.0.0.0
DOMAIN_NAME=${DOMAIN_NAME_PROMPT}
EOL
echo ".env file created."

echo "ایجاد کاربر اولیه ادمین برای پنل وب..."
# Run a Python script to create the initial admin user using the database.py logic
# This handles password hashing correctly.
python3 -c "
import os
from dotenv import load_dotenv
from database import Database
from werkzeug.security import generate_password_hash

load_dotenv(os.path.join(os.getenv('INSTALL_DIR'), '.env')) # Load .env file using env var from shell
db = Database()
# Check if an admin user already exists to prevent re-creating the first one
if not db.execute_query('SELECT * FROM admin_users', fetch=True):
    password_hash = generate_password_hash('$ADMIN_PASSWORD_PROMPT')
    tele_id = int('$ADMIN_TELEGRAM_ID_FOR_NOTIF_PROMPT') if '$ADMIN_TELEGRAM_ID_FOR_NOTIF_PROMPT' and '$ADMIN_TELEGRAM_ID_FOR_NOTIF_PROMPT' != 'None' else None
    db.add_admin_user('$ADMIN_USERNAME_PROMPT', password_hash, True, tele_id)
    print('Initial admin user created.')
else:
    print('Admin user(s) already exist. Skipping initial admin creation.')
" INSTALL_DIR="$INSTALL_DIR" # Pass INSTALL_DIR as env variable to python script

echo "کاربر ادمین اولیه ایجاد شد."

echo "[۵/۷] پیکربندی Nginx..."
# Webhook path is the bot token itself for simplicity
WEBHOOK_PATH="${BOT_TOKEN_PROMPT}" 

# Remove default nginx config to avoid conflicts
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/sites-available/default

cat > "/etc/nginx/sites-available/$DOMAIN_NAME_PROMPT" <<EOF
server {
    listen 80;
    server_name ${DOMAIN_NAME_PROMPT} www.${DOMAIN_NAME_PROMPT};
    return 301 https://\$host\$request_uri; # Redirect HTTP to HTTPS
}

server {
    listen 443 ssl http2;
    server_name ${DOMAIN_NAME_PROMPT} www.${DOMAIN_NAME_PROMPT};

    # SSL Configuration (Certbot will manage these)
    ssl_certificate /etc/letsencrypt/live/${DOMAIN_NAME_PROMPT}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN_NAME_PROMPT}/privkey.pem;
    ssl_trusted_certificate /etc/letsencrypt/live/${DOMAIN_NAME_PROMPT}/chain.pem;
    ssl_dhparam /etc/nginx/ssl-dhparams.pem; # Generated by certbot, if not, add it for better security.

    # Webhook for Telegram Bot
    location /${WEBHOOK_PATH} {
        proxy_pass http://127.0.0.1:8443; # Bot webhook port
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header Host \$host;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_pass_request_headers on;
        proxy_read_timeout 600s; # Long timeout for potential long processing
        proxy_send_timeout 600s;
        send_timeout 600s;
    }

    # Admin Panel (served by Gunicorn via Flask, Flask handles static files within its /admin path)
    location /admin/ {
        proxy_pass http://127.0.0.1:5000/admin/; # Flask admin panel port, includes the /admin/ path
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_connect_timeout 75s;
        proxy_read_timeout 75s;
        proxy_send_timeout 75s;
    }

    error_page 404 /404.html;
    location = /404.html {
        root /usr/share/nginx/html;
        internal;
    }

    error_page 500 502 503 504 /50x.html;
    location = /50x.html {
        root /usr/share/nginx/html;
        internal;
    }
}
EOF

ln -s "/etc/nginx/sites-available/$DOMAIN_NAME_PROMPT" "/etc/nginx/sites-enabled/$DOMAIN_NAME_PROMPT"
echo "در حال نصب گواهی SSL با Let's Encrypt... این مرحله ممکن است سوالاتی از شما بپرسد (اگه از شما ایمیل نپرسید چون قبلاً تنظیم کرده‌اید اوکیه)."
# It's generally better to provide an email for Certbot:
certbot --nginx -d ${DOMAIN_NAME_PROMPT} -d www.${DOMAIN_NAME_PROMPT} --non-interactive --agree-tos --email noreply@${DOMAIN_NAME_PROMPT}

# Certbot will reload Nginx automatically.
# If for any reason certbot fails or if you previously installed Nginx directly:
# sudo nginx -t && sudo systemctl reload nginx

echo "[۶/۷] پیکربندی Supervisor برای اجرای ربات و پنل..."

cat > "/etc/supervisor/conf.d/telegram_bot.conf" <<EOF
[program:telegram_bot]
directory=${INSTALL_DIR}
command=${INSTALL_DIR}/venv/bin/python3 bot.py
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/telegram_bot_err.log
stdout_logfile=/var/log/supervisor/telegram_bot_out.log
user=www-data
environment=PATH="/usr/local/bin:/usr/bin:/bin"
stopsignal=KILL
killasgroup=true
EOF

cat > "/etc/supervisor/conf.d/admin_panel.conf" <<EOF
[program:admin_panel]
directory=${INSTALL_DIR}
command=${INSTALL_DIR}/venv/bin/gunicorn --workers 3 --bind 0.0.0.0:5000 admin_app:app
autostart=true
autorestart=true
stderr_logfile=/var/log/supervisor/admin_panel_err.log
stdout_logfile=/var/log/supervisor/admin_panel_out.log
user=www-data
stopsignal=KILL
killasgroup=true
EOF

supervisorctl reread
supervisorctl update
supervisorctl status

echo "[۷/۷] تنظیم Webhook تلگرام (پس از چند ثانیه تا ربات کاملاً آماده شود)..."
sleep 5 # Give the bot some time to start and bind to port

# Configure Telegram Webhook using curl
WEBHOOK_URL="https://${DOMAIN_NAME_PROMPT}/${BOT_TOKEN_PROMPT}"
echo "تنظیم Webhook تلگرام به آدرس: ${WEBHOOK_URL}"
curl -s -F "url=${WEBHOOK_URL}" \
    https://api.telegram.org/bot${BOT_TOKEN_PROMPT}/setWebhook

echo ""
echo "██████████████████████████████████████████████████████████"
echo "█                 نصب با موفقیت به پایان رسید!             █"
echo "██████████████████████████████████████████████████████████"
echo ""
echo "مراحل بعدی:"
echo "۱. به ربات تلگرام خود در آدرس t.me/<نام‌کاربری‌ربات‌شما> بروید و /start را ارسال کنید."
echo "۲. به پنل مدیریت خود در مرورگر در آدرس https://${DOMAIN_NAME_PROMPT}/admin/ دسترسی پیدا کنید."
echo "   نام کاربری: ${ADMIN_USERNAME_PROMPT}"
echo "   رمز عبور: ${ADMIN_PASSWORD_PROMPT}"
echo "   حتماً بعداً در اولین فرصت از طریق پنل مدیریت رمز عبور را تغییر دهید!"
echo "۳. می‌توانید لاگ‌های ربات و پنل را با دستورات زیر مشاهده کنید:"
echo "   sudo tail -f /var/log/supervisor/telegram_bot_out.log"
echo "   sudo tail -f /var/log/supervisor/admin_panel_out.log"
echo "۴. برای مشاهده وضعیت سرویس‌ها:"
echo "   sudo supervisorctl status"
echo "۵. به صورت منظم yt-dlp را به‌روز نگه دارید:"
echo "   cd ${INSTALL_DIR} && source venv/bin/activate && pip install -U yt-dlp"
echo ""
echo "موفق باشید!"

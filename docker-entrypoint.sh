#!/usr/bin/env bash
set -e

if [ ! -d "$PLAYWRIGHT_BROWSERS_PATH" ] || [ -z "$(ls -A "$PLAYWRIGHT_BROWSERS_PATH" 2>/dev/null)" ]; then
  python -m playwright install chromium || true
fi

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Project module is "whatsapp_webapp"
exec gunicorn invoicegen.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers 3 \
  --timeout 90

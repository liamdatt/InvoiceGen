# syntax=docker/dockerfile:1.7-labs
FROM python:3.12-slim

# If you don't compile native deps, you can skip apt completely
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Install Chromium and required system deps for Playwright PDF rendering
RUN python -m playwright install --with-deps chromium

COPY . .

COPY docker-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
CMD ["/entrypoint.sh"]

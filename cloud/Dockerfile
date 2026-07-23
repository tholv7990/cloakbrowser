# Plasma cloud control plane — build context is the repo root:
#   docker build -f cloud/Dockerfile -t plasma-cloud .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY cloud/requirements.txt /app/cloud/requirements.txt
RUN pip install --no-cache-dir -r /app/cloud/requirements.txt

COPY cloud /app/cloud

EXPOSE 8000
# Migrate to head, then serve. Secrets + DATABASE_URL come from the environment.
CMD ["sh", "-c", "python -m alembic -c cloud/alembic.ini upgrade head && python -m uvicorn --factory cloud.app:create_app --host 0.0.0.0 --port 8000"]

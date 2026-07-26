# Plasma cloud control plane — build context is the repo root:
#   docker build -f cloud/Dockerfile -t plasma-cloud .
FROM node:20-alpine AS admin-ui
WORKDIR /build
COPY cloud/admin-ui/package*.json ./
RUN npm install
COPY cloud/admin-ui .
COPY manager/frontend/src ../manager/frontend/src
COPY manager/frontend/tsconfig.json ../manager/frontend/
RUN npm run build

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY cloud/requirements.txt /app/cloud/requirements.txt
RUN pip install --no-cache-dir -r /app/cloud/requirements.txt

COPY cloud /app/cloud
COPY --from=admin-ui /build/dist /app/cloud/features/admin/static/dist

EXPOSE 8000
# Migrate to head, then serve. Secrets + DATABASE_URL come from the environment.
CMD ["sh", "-c", "python -m alembic -c cloud/alembic.ini upgrade head && python -m uvicorn --factory cloud.app:create_app --host 0.0.0.0 --port 8000"]

# Avante — Backend API

[![Google Play](https://img.shields.io/badge/Google_Play-Published-green?logo=google-play)](https://play.google.com/store/apps/details?id=com.jazbedoya.avante)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.12-blue?logo=python)](https://python.org)
[![Railway](https://img.shields.io/badge/Railway-deployed-purple?logo=railway)](https://railway.app)

REST API for [Avante](https://play.google.com/store/apps/details?id=com.jazbedoya.avante), a mobile app **published on Google Play** that helps people balance family, work, and personal time with emotional context awareness.

> See the mobile app with screenshots: [calendario_front](https://github.com/jazbedoya/calendario_front)

## Tech Stack

| Layer | Technology |
|---|---|
| **Language** | Python 3.12 |
| **Framework** | FastAPI (async) |
| **ORM** | SQLAlchemy 2 (async) + Alembic migrations |
| **Database** | PostgreSQL 16 |
| **Auth** | JWT (access + refresh tokens) · Google OAuth 2.0 |
| **Validation** | Pydantic v2 |
| **Logging** | structlog |
| **Infra** | Docker · Railway (production) |
| **CI** | GitHub Actions |

## Architecture

```
app/
├── core/           # Config, DB engine, security, middleware
├── modules/
│   ├── auth/       # JWT auth + Google OAuth (login + calendar connect)
│   ├── events/     # CRUD + soft-delete + recurrence (daily/weekly/monthly)
│   ├── tasks/      # Daily tasks with ordering
│   ├── calendar/   # Google Calendar sync (OAuth + batch upsert)
│   ├── context/    # Energy & mood tracking per day
│   ├── stats/      # Monthly aggregations by life area
│   ├── home/       # Dashboard summary (upcoming events, task progress)
│   └── notifications/ # Push notification tokens
└── alembic/        # 13 migrations (UUID PKs, composite indexes)
```

## Key Features

- **Async everywhere** — async endpoints, async SQLAlchemy, asyncpg driver
- **Google Calendar integration** — OAuth 2.0 flow with batch upsert (single INSERT...ON CONFLICT)
- **Recurring events** — generates occurrences (daily×90, weekly×52, monthly×12) with batch insert
- **Soft-delete** — events use `deleted_at` for safe deletion + restore
- **Performance** — UPDATE...RETURNING (no extra SELECT), composite indexes, batch operations
- **Weekly intentions** — JSON field for flexible goal tracking per area

## Running locally

```bash
# 1. PostgreSQL on port 5436
# 2. Create .env with DATABASE_URL, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET

# Install dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start server
uvicorn app.main:app --host 0.0.0.0 --port 9001 --reload
```

API docs at `http://localhost:9001/docs`

## Tests

```bash
python -m pytest tests/ -v
# 81 unit tests covering auth, events, tasks, and calendar sync
```

## Production

Deployed on **Railway** with automatic migrations on deploy.
Health check: `/health`

## Frontend

The mobile app is in a separate repo: [calendario_front](https://github.com/jazbedoya/calendario_front)

---

Built by **Jazmín Bedoya** — [GitHub](https://github.com/jazbedoya)

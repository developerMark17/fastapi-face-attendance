# Backend (FastAPI)

## Features

- Face registration using `face_recognition`
- Face recognition with configurable tolerance
- Liveness challenge (`blink` or `smile`) using facial landmarks
- Attendance logging with timestamp
- Duplicate attendance prevention (cooldown window)
- Optional geofence validation (latitude/longitude)
- Admin JWT login/logout and protected admin APIs
- Student management, reports, and payment records
- Admin web panel at `/admin-panel/`
- Demo payment provider with Stripe Checkout readiness

## Setup

1. Create Python virtual environment and install dependencies:

```bash
cd backend
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
```

2. Configure environment:

```bash
copy .env.example .env
```

3. Start PostgreSQL from project root:

```bash
cd ..
docker compose up -d postgres
```

4. Run API:

```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

5. API docs:

- http://localhost:8000/docs

## Endpoints

- `POST /register-face` (multipart: `name`, `image`)
- `POST /recognize-face` (multipart: `image`, `challenge`, optional `latitude`, `longitude`)
- `GET /attendance`
- `POST /auth/token` (JSON body for admin JWT)
- `POST /auth/logout` (Bearer token)
- `GET /admin/dashboard` (Bearer token)
- `GET /admin/students` (Bearer token)
- `POST /admin/students` (Bearer token)
- `GET /admin/reports/attendance` (Bearer token)
- `GET /billing/plans`
- `POST /payments/checkout-session` (Bearer token)
- `POST /payments/stripe/webhook`

## Production notes

- Replace `SECRET_KEY`, `ADMIN_PASSWORD`, and DB credentials.
- Restrict CORS origins in `app/main.py`.
- Put FastAPI behind reverse proxy (Nginx/Traefik).
- Serve over HTTPS only.
- Use PostgreSQL, a vector index, background jobs, and object storage for 1M-user production scale.

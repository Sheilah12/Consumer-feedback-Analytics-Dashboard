# Power Monitor — Vercel + Neon

Lightweight power theft detection and energy monitoring dashboard. FastAPI on Vercel serverless, Neon Postgres, push-based device ingestion, client polling for live updates.

## Architecture

```
ESP8266 ──HTTPS POST──▶ /api/blynk/webhook ──▶ Neon Postgres
                                                    ▲
Browser ──polls /api/latest (5s, pauses when hidden)─┘

Vercel Cron (daily) ──GET /api/cron/prune──▶ retention cleanup
```

Static HTML/CSS/JS is served from `public/` via the Vercel CDN. API routes are handled by `api/index.py` (FastAPI).

## Invocation budget (read this)

**Vercel Hobby allows ~100,000 serverless function invocations per month** and is non-commercial only.

| Cadence | Ingestion invocations/month |
|---------|----------------------------|
| Every 2 s | ~1.3 million (will exhaust Hobby) |
| Every 30 s | ~86,400 |
| Every 60 s | ~43,200 |

**Recommendations:**

- Device normal cadence: **30–60 seconds** (configurable in firmware).
- **Immediate POST** when differential exceeds threshold (theft alert).
- Browser polls `/api/latest` every **5 s**, but **pauses when the tab is hidden** (`poll.js`).
- For true 2 s telemetry, use **Vercel Pro**, a small always-on VPS for ingestion, or optional Ably/Upstash realtime (publish from webhook, subscribe in browser — bypasses Vercel for live updates).

## Quick start (local)

```bash
cd power-monitor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt

cp .env.example .env
# Set DATABASE_URL to Neon pooled string

python scripts/migrate.py
python scripts/demo_seed.py   # optional historical data

export DATABASE_URL=... INGEST_SECRET=dev-secret
pytest
```

Demo UI without a database: open `/?demo=1` — `poll.js` generates synthetic readings in the browser.

## Deploy to Vercel

1. Push this repo to GitHub and import into [Vercel](https://vercel.com).
2. **Storage → Neon** integration → injects `DATABASE_URL`. Use the **pooled** host (`-pooler` in the hostname).
3. Run schema once:
   ```bash
   DATABASE_URL=... python scripts/migrate.py
   ```
4. Set environment variables in Vercel project settings:

   | Variable | Purpose |
   |----------|---------|
   | `DATABASE_URL` | Neon **pooled** connection string |
   | `INGEST_SECRET` | Shared secret for device webhook |
   | `ADMIN_TOKEN` | Protects config writes, alert ack, delete |
   | `BLYNK_TOKEN` | Optional, for `/api/blynk/test` only |
   | `BLYNK_SERVER` | Default `https://blynk.cloud` |
   | `ALERT_THRESHOLD_MA` | Default 150 |
   | `CONSECUTIVE_SAMPLES` | Noise-suppressed alert window (default 2) |
   | `TARIFF_KWH_COST` | KES per kWh |
   | `RETENTION_DAYS` | Daily cron pruning (default 30) |
   | `CRON_SECRET` | Auto-provisioned by Vercel |

5. Configure the ESP8266 to POST complete snapshots:

   ```
   POST https://<project>.vercel.app/api/blynk/webhook?secret=<INGEST_SECRET>
   Content-Type: application/json

   {
     "live_current": 4.123,
     "neutral_current": 4.118,
     "differential": 0.005,
     "voltage": 229.4,
     "real_power": 945.2,
     "energy_kwh_cumulative": 1234.5,
     "system_status": "normal",
     "ts": "2026-05-30T12:00:00.000Z"
   }
   ```

   Map Blynk data streams 1–7 to these keys (`app/stream_fields.py`). Legacy `V0`–`V5` / `current_in` / `current_out` JSON is still accepted.

   Send **all fields in one request** — never one webhook per pin. Normal cadence 30–60 s; immediate POST on alert.

6. Deploy. Daily prune cron (`0 3 * * *`) registers from `vercel.json`.

## Device webhook contract

| Blynk stream | JSON field | Notes |
|--------------|------------|--------|
| 1 | `live_current` | Live leg current (A) |
| 2 | `neutral_current` | Neutral leg current (A) |
| 3 | `differential` | Optional; amperes (server can derive \|live − neutral\|) |
| 4 | `voltage` | Volts |
| 5 | `real_power` | Watts |
| 6 | `energy_kwh_cumulative` | Meter cumulative kWh |
| 7 | `system_status` | `normal` / `alert` (or legacy `V5`) |
| — | `ts` | Optional ISO-8601 device timestamp |

Interval energy and sustained alerts are computed server-side from history.

- Interval energy: `max(0, current_cumulative - previous_cumulative)`; if counter resets (reboot), interval = 0.
- Alert: current differential and the previous `CONSECUTIVE_SAMPLES - 1` readings must all exceed `ALERT_THRESHOLD_MA`.

## API overview

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/health` | DB size, last ingest timestamp |
| GET | `/api/latest` | Latest reading (polled by dashboard) |
| POST | `/api/blynk/webhook?secret=` | Device ingestion |
| GET | `/api/blynk/test` | One-shot Blynk REST probe |
| GET | `/api/cron/prune` | Daily retention (Bearer `CRON_SECRET`) |
| GET | `/api/readings`, `/hourly`, `/daily` | History & aggregates |
| GET/POST | `/api/config` | POST requires `ADMIN_TOKEN` |
| GET | `/api/alerts` | Paginated alerts |
| POST | `/api/alerts/{id}/ack` | Requires admin token |
| DELETE | `/api/alerts` | Requires admin token |

Live updates use client polling via `public/js/poll.js` (pauses when the tab is hidden).

## Project layout

```
power-monitor/
├── api/index.py          # Vercel entrypoint
├── app/
│   ├── routes.py         # FastAPI routes
│   ├── ingest.py         # Webhook + alert logic
│   ├── db.py             # Neon/asyncpg
│   ├── models.py
│   └── config.py
├── public/               # Static frontend (Vercel CDN)
├── scripts/migrate.py
├── scripts/demo_seed.py
├── tests/
├── vercel.json
└── requirements.txt
```

## Optional realtime upgrade

Publish each ingested reading to **Ably** or **Upstash Redis** from the webhook handler so browsers subscribe directly — live updates without polling Vercel functions. Not included by default to stay within Hobby invocation limits.

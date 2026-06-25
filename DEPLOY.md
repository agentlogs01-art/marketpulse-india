# Deploying MarketPulse India to Railway

This file exists specifically to prevent the most common setup mistake
with this repo: **the GitHub repo root must contain the `marketpulse/`
folder itself**, not the *contents* of that folder spilled loose into
the repo root. Every file in this codebase imports using the full
package path (`from marketpulse.models.schemas import ...`,
`from marketpulse.persistence.subscriber_repo import ...`, etc.) — if
`marketpulse/` isn't visible as a subfolder from wherever Railway runs
the start command, every one of those imports fails immediately and the
app won't boot, which is the failure this guide exists to head off.

## Correct repo layout

```
your-repo/                  <- GitHub repo root
├── Procfile                <- tells Railway how to start the app
├── railway.json            <- Railway-native config (belt-and-suspenders with Procfile)
├── requirements.txt        <- top-level copy, so Nixpacks' Python auto-detect finds it
├── runtime.txt              <- pins Python 3.11
├── .gitignore
├── DEPLOY.md                <- this file
└── marketpulse/             <- the actual Python package; DO NOT flatten this
    ├── api/
    ├── models/
    ├── persistence/
    ├── webapp/
    ├── ... (every other module)
    └── requirements.txt     <- kept here too, for local `cd marketpulse && pip install -r requirements.txt`
```

If you previously pushed the *contents* of `marketpulse/` directly to
your repo root (so you'd see `api/`, `models/`, etc. sitting next to
`README.md` with no `marketpulse/` folder wrapping them), that's almost
certainly why Railway "couldn't find" the app — fix it by moving
everything under a `marketpulse/` subfolder, or re-push using the
project zip exactly as structured.

## Railway setup steps

1. **Push this exact structure to a GitHub repo** (see layout above).
2. In Railway: **New Project → Deploy from GitHub repo** → select the repo.
3. Railway should auto-detect Python via `requirements.txt` at the repo
   root and use Nixpacks. If it instead asks you to pick a builder or
   shows no detected language, double-check `requirements.txt` is
   actually at the repo root (not only inside `marketpulse/`).
4. **Start command**: Railway should pick up `railway.json`'s
   `startCommand` automatically. If it doesn't (e.g., you're on an older
   Railway project that predates `railway.json` support), manually set
   the start command in the service's Settings → Deploy tab to:
   ```
   gunicorn marketpulse.api.app:app --bind 0.0.0.0:$PORT
   ```
5. **Environment variables**: open the service's Variables tab and add
   everything listed in `marketpulse/.env.example` — at minimum
   `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` for the app to boot
   without errors when it touches the database, plus `SMTP_*` and
   `WEBAPP_BASE_URL` for signup emails to work. The app will still start
   without these, but `/api/signup`, `/api/login`, etc. will fail at
   request time without a working Supabase connection.
6. **Generate a public domain**: Settings → Networking → Generate
   Domain. Confirm `GET /` returns the sign-up/sign-in page and
   `GET /api/me` returns a 401 (expected — you're not signed in yet).
   That 401, not a 404 or 502, is the sign the app deployed correctly.

## Verifying it worked

```bash
curl -I https://<your-railway-domain>/          # expect 200
curl -I https://<your-railway-domain>/api/me    # expect 401, not 404/502
```

A 404 on `/api/me` means the Flask app isn't running at all (wrong start
command or import failure — check Railway's deploy logs for a traceback,
which will almost always be a `ModuleNotFoundError: No module named
'marketpulse'` if the folder-structure issue above is the cause). A 502
usually means the app crashed on boot — check logs for a missing
environment variable or a Python exception during import.

## The daily pipeline and EOD job are separate from the web service

The Railway web service above only serves the website/API
(`marketpulse.api.app`). The actual daily briefing pipeline
(`scheduler/run_daily_briefing.py`) and the end-of-day close-recording
job (`scheduler/record_daily_close.py`) run on their own schedule via
**GitHub Actions**, not Railway — see
`marketpulse/.github/workflows/daily_briefing.yml`. That workflow needs
its own set of repo secrets configured in GitHub (Settings → Secrets and
variables → Actions), independent of Railway's environment variables.
Railway hosts the website; GitHub Actions runs the pipeline. Both need
the same Supabase credentials, configured separately in each platform.

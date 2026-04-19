# NI AI Review Generator

Vercel + Supabase deployment for Nilkanth Infotech review generation.

## Architecture

- `app.html` is the Vercel-hosted frontend.
- `api/index.py` is the Vercel Python API endpoint.
- Supabase stores service rotation state and only the latest 10 generated reviews per service.
- OpenAI generates the review text.

## Required Vercel Environment Variables

Add these in Vercel Project Settings -> Environment Variables:

```text
OPENAI_API_KEY=your_openai_key
SUPABASE_URL=https://ivqwbremiipcunnvlmfp.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your_supabase_secret_key
```

If Supabase labels your server-side key as a "secret key", paste that value into
`SUPABASE_SERVICE_ROLE_KEY`. The frontend never needs the publishable key.

Optional after you know your production domain:

```text
ALLOWED_ORIGIN=https://your-project.vercel.app
```

## Supabase Setup

1. Open Supabase SQL Editor.
2. Paste the contents of `supabase.sql`.
3. Click Run.
4. Confirm these objects exist:
   - `service_state`
   - `review_history`
   - `reserve_review_state`
   - `trim_review_history_to_latest_10`

`review_history` is intentionally kept small. After every generated review,
Supabase automatically deletes older rows so only the latest 10 reviews per
service remain, matching the old local JSON cache behavior.

## Local Validation

Run before pushing:

```bash
python3 validate.py
```

This checks JSON parsing, Python syntax, frontend dropdown sync, and prompt rendering.

## Deploy

Push this repo to GitHub, then import it in Vercel.

Vercel should detect the Python API from `api/index.py` and install
dependencies from `requirements.txt`.

## Important Security Notes

- Do not commit `.env` or real API keys.
- Do not put OpenAI or Supabase secret keys inside `app.html`.
- `SUPABASE_SERVICE_ROLE_KEY` is server-only and must stay in Vercel env vars.

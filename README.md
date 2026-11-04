# MultiModal GameArchitect — GDD Builder

> Built for the Meta AI Developer Hackathon (2026).
> From a one-line idea to a complete game package — design doc, engine code, concept art, and music — in minutes.

**GDD Builder** is an agentic pipeline that turns a game idea into a production-ready starter package: a structured Game Design Document, engine-targeted code, visual assets, and a concept music loop. Everything is generated live, downloadable, and auditable — no mocks on the demo path.

## Why it stands out

- **End-to-end, not a chatbot.** One prompt flows through specialized agents: GDD, code, art, review, music.
- **Self-correcting.** A dedicated review agent audits every GDD against a checklist and fixes gaps only after your confirmation.
- **Grounded in real game data.** RAWG, IGDB, and Steam signals feed the generation so references and comparisons are real.
- **Demo-proof.** Badged fallbacks, explicit JSON errors (never a 500), rate limiting, and a test suite that is green: 58/58 backend tests, clean `tsc` + `eslint`.

## Features

**Design documents**
- One-Sheet, Ten-Pager, and Full GDD, powered by Meta `muse-wonder-1.0`.
- Dynamic Rogers-style form: fields adapt to the document type (3C rule, core loop, lore, level design, AI/physics options).
- GDD audit page (`/gdd-review`): checklist review, confirm-to-fix completion, and upload of your own `.md` / `.txt` / `.json` drafts.

**Code generation**
- Engine-targeted starter code for Godot 4, Unity, and Unreal (GDScript, C#, C++).
- Every form field (genre, mechanics, features, engine, visual style) flows into the prompts — nothing is decorative.

**Visual assets**
- Concept art, UI concepts, and sprites via Meta Muse image generation.
- 1–5 images per type, style dropdown, parallel prompt variance (no two images share a prompt).
- SAM sprite cutout (sprites only) for ready-to-use transparent PNGs.

**Music**
- Concept music loops via a MusicGen agent (Replicate), downloadable as WAV or MP3.
- Loop-aware prompting + equal-power crossfade DSP so excerpts actually loop.

**Exports & product polish**
- Downloads in Markdown, JSON, TXT, and styled PDF (Pro or Gamebook layout, rendered locally with fpdf2 — no paid API).
- Grounded references from RAWG / IGDB / Steam, cost estimates (~, never billed silently), local history, demo examples.
- Bring Your Own Key (optional, per user, `localStorage` + `Authorization: Bearer`), voice dictation + TTS in the browser, EN/FR/ES/DE/IT UI.

## Architecture

```
Next.js 16 (localhost:3000)  ──fetch──▶  FastAPI (127.0.0.1:8000)
  /             pipeline home                 │  agents: gdd · code · asset · review
  /gdd-form     Rogers-style form             │          music · sam · voice
  /gdd-review   audit + confirm-to-fix        │  tools: RAWG · IGDB · Steam
                                              ▼
                                    Meta Llama · Meta Muse Image
                                    Replicate (MusicGen) · fpdf2 (local PDFs)
```

## Quickstart

Prerequisites: Python 3.10+ with the project `.venv` (or conda), Node 20+.

```bash
# Terminal 1 — backend (http://127.0.0.1:8000, docs at /docs)
cd backend
../.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — frontend (http://localhost:3000)
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`, optionally set your Meta key (navbar → API key), and hit **Launch the AI pipeline**.

## Configuration

All secrets live in `backend/.env` (git-ignored). Without keys, the app serves badged mock/fallback output so the UI is always explorable.

| Variable | Purpose | Required for |
|---|---|---|
| `META_LLAMA_API_KEY` | GDD text generation (`muse-wonder-1.0`) | Live GDD / review |
| `MUSE_IMAGE_API_KEY` | Visual asset generation | Live art |
| `REPLICATE_API_TOKEN` | MusicGen excerpts (~$0.03/excerpt) | Live music (or per-user BYOK) |
| `RAWG_API_KEY` | Similar-game metadata | Grounded references |
| `TWITCH_CLIENT_ID` / `TWITCH_CLIENT_SECRET` | IGDB gameplay references | Grounded references |
| `HUGGINGFACE_API_KEY` | Reserved | — |
| `ALLOW_ORIGINS` | Extra CORS origins, comma-separated (localhost always allowed) | Production frontend URL |

Users can also bring their own Meta key in the browser (BYOK); the server key is the fallback.

## Deploy (jury link)

Backend on Render, frontend on Vercel. Order matters:

1. **Backend**: Render dashboard → New → Blueprint → select this repo (`render.yaml` provisions the API). Set the secret env vars in the dashboard, deploy, and note the API URL (`https://gdd-builder-api.onrender.com`).
2. **Frontend**: Vercel → import repo, root directory `frontend/`, env var `NEXT_PUBLIC_API_URL=<step-1 URL>` (baked in at build time), deploy, and note the site URL.
3. **CORS**: back on Render, set `ALLOW_ORIGINS=<step-2 URL>` and redeploy the API.

Notes: Render's free tier cold-starts (~1–2 min) after idle — warn evaluators. Railway/Fly.io alternative: build `backend/Dockerfile` instead. Never commit `.env` files; see `backend/.env.example` and `frontend/.env.example`.

## API

Interactive docs at `http://127.0.0.1:8000/docs`. All endpoints return explicit JSON errors — no 500s on tool failures.

| Method & path | Purpose |
|---|---|
| `POST /api/v1/generate-gdd` | Full pipeline: GDD + code + art prompts |
| `POST /api/v1/generate-code` | Engine-targeted code only |
| `POST /api/v1/generate-asset` | Visual assets (concept / UI / sprite) |
| `POST /api/v1/review-gdd` | Checklist audit of a GDD |
| `POST /api/v1/fix-gdd` | Apply confirmed fixes to a GDD |
| `POST /api/v1/gdd-pdf` | Styled PDF export (pro / gamebook) |
| `POST /api/v1/cutout` | SAM sprite cutout (sprites only) |
| `POST /api/v1/generate-music` | MusicGen excerpt (WAV) |
| `POST /api/v1/music-to-mp3` | WAV → MP3 conversion |
| `POST /api/v1/transcribe` | Voice agent transcription |

## Testing & quality gates

```bash
cd backend && ../.venv/Scripts/python -m unittest discover -s tests -t .  # 58/58 green
cd frontend && ./node_modules/.bin/tsc --noEmit && npm run lint -- --quiet  # clean
```

Security pass done before release: CORS locked to the dashboard origins, in-memory rate limiting on POST routes (per-minute + per-day caps, `BILLING_PAUSED` kill-switch), SSRF guards on fetched URLs, input size caps (prompt 4k, review/fix 100 KB, PDF 200 KB), CPU-bound PDF/MP3 work off the event loop.

## Project structure

```
backend/   FastAPI app (app/main.py, routers/, agents/, services/) + unittest suite
frontend/  Next.js app (app/, components/, lib/) — EN default, FR/ES/DE/IT
exports/   Sample local outputs
VIDEO_SCRIPT.md  2–3 min demo video script
```

## License

MIT — built during the Meta AI Developer Hackathon.

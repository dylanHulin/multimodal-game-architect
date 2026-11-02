# Demo Video Script — GDD Builder (2–3 min)

Target: **~2 min 30 s** (≈ 350 words voiceover). Record at 1080p, capture
`http://localhost:3000` full-window, live-generate everything (no slides of
mockups). Speak the **bold** lines; the rest is stage direction.

## 0:00–0:20 — Hook (home page)

> **"Every game starts as a sentence. GDD Builder turns that sentence into a
> design document, engine code, concept art, and music — in one pipeline."**

- Show the home page, type the idea live:
  *"A cozy co-op farming sim on a haunted island, Godot 4, pastel pixel art."*
- Point at the pipeline steps; hit **Launch the AI pipeline**.

## 0:20–0:55 — GDD + grounded references

> **"The GDD agent drafts the document — pillars, mechanics, 3C, core loop —
> grounded in real games pulled from RAWG, IGDB, and Steam, not hallucinated
> references."**

- Scroll the generated One-Sheet; linger 2 s on the references row.
- Switch doc type to **Full GDD**, show lore + feature checkboxes.

## 0:55–1:20 — Self-correction (the wow moment)

> **"Then the review agent audits the GDD — and only fixes what I approve."**

- Open `/gdd-review`, run the audit, show the checklist (ok / weak / missing).
- Tick one suggestion, confirm, show the before/after diff.

## 1:20–1:50 — Art + sprite cutout

> **"Art ships in parallel: concept art, UI, and sprites — each with its own
> prompt, so nothing looks copy-pasted. Sprites get SAM cutout for
> ready-to-use PNGs."**

- Generate 3 concept arts; show they differ. Cut out one sprite, show the
  transparency checkerboard.

## 1:50–2:15 — Music + export

> **"A MusicGen agent composes a real loop — hear the seamless repeat — and
> everything exports: Markdown, JSON, and a styled Gamebook PDF."**

- Play the loop twice (volume up). Download WAV + the Gamebook PDF; flip
  through 3 pages.

## 2:15–2:30 — Close

> **"GDD Builder: from sentence to playable starter package. Built on Meta
> Llama and Muse, tested end to end — repo and docs in the description."**

- Freeze on the PDF cover + the three page tabs. End card: repo URL.

## Recording checklist

- Fresh `npm run dev` + backend reload before recording; close notif popups.
- Pre-generate NOTHING except the demo-example idea text; jury wants live calls.
- Backup: if a live call is slow, cut to the already-loaded result — never fake it.
- Captions on (auto-English), 1080p60, mic check: music segment must be audible.

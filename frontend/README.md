# FantasyEdge web

Vite + React + TypeScript + Tailwind v4 + shadcn/ui. Dark mode by default.

```bash
pnpm install
pnpm dev          # http://localhost:5173 (expects the API on :8000; override with VITE_API_BASE)
pnpm test         # vitest
pnpm run gen-api  # regenerate src/api from ./openapi.json (run `python tasks.py gen-api` from the repo root to export it first)
```

`src/api/` and `src/components/ui/` are generated (hey-api / shadcn CLI) — edit the generators, not the files.

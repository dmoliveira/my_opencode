# News Search Demo (Worktree + Parallel Tracks)

This demo is a small full-stack app with fake news docs:

- backend API: `demo/news_search/backend/server.py`
- ingestor: `demo/news_search/ingestor/ingest.py`
- frontend search UI: `demo/news_search/frontend/*`

## Quick start

1) Ingest fake docs into SQLite:

```bash
python3 demo/news_search/ingestor/ingest.py --output demo/news_search/runtime/news.db
```

2) Start backend (terminal A):

```bash
python3 demo/news_search/backend/server.py --db-path demo/news_search/runtime/news.db --port 8000
```

3) Start frontend static host (terminal B):

```bash
python3 -m http.server 5173 --directory demo/news_search/frontend
```

4) Open:

- `http://127.0.0.1:5173`

## Endpoints

- `GET /health`
- `GET /api/topics`
- `GET /api/search?q=<query>&topic=<topic>&limit=<n>`

## Parallel execution strategy used

We modeled work as 5 tracks with path reservations to allow parallelism safely:

1. backend/API (`backend/**`)
2. ingestor/data (`ingestor/**`, `data/**`)
3. search component (`backend/search_service.py`)
4. frontend UI (`frontend/**`)
5. UX review + polish (`frontend/**`, docs)

This follows single-writer safety per path while still allowing two active parallel tracks at a time.

## Subagent trigger guidance in OpenCode

- use `explore` for repo pattern discovery and file reservations before implementation
- use `strategic-planner` to split milestones and parallel tracks
- use `verifier` after each wave (backend/ingestor wave, frontend/ux wave)
- use `reviewer` for final safety/maintainability pass before PR

## Notes

- Data is intentionally fake and local-only.
- The backend uses SQLite FTS5 for simple ranked text search.

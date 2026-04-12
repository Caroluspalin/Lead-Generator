# Agency Hunter

Lead generation tool for finding local businesses that need web development services. Search any industry + city combination, automatically analyze their web presence, and manage prospects through a sales pipeline.

## How It Works

1. **Search** — Enter an industry and city. The app queries Google Places API using a 3x3 grid search to cover the entire city area, not just top results.
2. **Analyze** — Each business's website is automatically checked: does it exist, does it respond, is it mobile-friendly (viewport meta tag)?
3. **Save** — Bookmark interesting leads to your local database with one click.
4. **Manage** — Track leads through pipeline stages: Shortlisted → Contacted → Proposal Received → Hired / Rejected.

### Website Status Scoring

| Status | Meaning |
|---|---|
| `NO WEBSITE` | Business has no website at all |
| `BROKEN WEBSITE` | Site returns HTTP errors or doesn't respond |
| `NOT MOBILE` | Site works but missing viewport meta tag |
| `WEBSITE OK` | Site works and is mobile-friendly |

The "Opportunities Only" filter hides `WEBSITE OK` results — those aren't potential clients.

## Tech Stack

**Frontend:** React 19 + TypeScript, Vite 7, Tailwind CSS 3, Framer Motion, Lucide icons, Sonner toasts

**Backend:** FastAPI, SQLModel (SQLAlchemy + Pydantic), SQLite (swappable to PostgreSQL), Google Places API, BeautifulSoup4

## Getting Started

### Prerequisites

- Node.js 18+
- Python 3.10+
- Google Places API key ([get one here](https://console.cloud.google.com/google/maps-apis))

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Then edit .env with your API key
uvicorn app.main:app --reload
```

Backend runs at `http://127.0.0.1:8000`. API docs at `/docs`.

### Frontend

```bash
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

### Environment Variables

Create `backend/.env`:

```
DATABASE_URL=sqlite:///agency_hunter.db
GOOGLE_API_KEY=your_key_here
USE_LIVE_GOOGLE=false
```

Set `USE_LIVE_GOOGLE=true` when you're ready to make real API calls. With `false`, the app returns mock data for development.

### PostgreSQL (Optional)

```bash
docker compose up -d
```

Then update `DATABASE_URL` in `.env` to `postgresql://postgres:password@localhost:5432/agency_hunter`.

## Project Structure

```
agency-hunter/
├── src/                    # React frontend
│   ├── components/         # UI components
│   ├── context/            # PipelineContext (global state + API calls)
│   └── types/              # TypeScript interfaces
├── backend/
│   └── app/
│       ├── main.py         # FastAPI routes + Google Places service
│       ├── models.py       # SQLModel database models
│       └── database.py     # DB connection setup
├── docker-compose.yml      # PostgreSQL + pgAdmin (optional)
└── package.json
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/search?business_type=X&city=Y` | Search businesses via Google Places (stateless) |
| `POST` | `/leads` | Save a lead to the database |
| `GET` | `/leads` | Get all saved leads |
| `PATCH` | `/leads/{id}` | Update lead status, notes, phone, or website |
| `DELETE` | `/leads/{id}` | Delete a lead |

## Grid Search Algorithm

Instead of a single Google search (which returns ~20 results), Agency Hunter divides the city into a **3x3 grid** and searches each cell independently. The search radius is calculated dynamically from the city's viewport size with 20% overlap between cells. Results are deduplicated by `place_id`.

Safety limits prevent runaway API costs:
- **15** max search API calls (geocode + nearby search + pagination)
- **40** max detail API calls (one per unique business)

## License

MIT

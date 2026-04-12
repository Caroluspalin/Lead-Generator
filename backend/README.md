# Agency Hunter Backend

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the `backend/` directory:
```bash
cp .env.example .env
```

3. Add your Google Maps API key to `.env`:
```
GOOGLE_API_KEY=your_actual_api_key_here
USE_LIVE_GOOGLE=False
```

4. Run the server:
```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Environment Variables

- `GOOGLE_API_KEY`: Your Google Maps API key (get it from [Google Cloud Console](https://console.cloud.google.com/google/maps-apis))
- `USE_LIVE_GOOGLE`: Set to `True` to enable live Google API calls (default: `False` for dev mode with mock data)

## Security

- **Never commit `.env` to git** - it's already in `.gitignore`
- Use `.env.example` as a template for other developers
- Keep your API keys secure and rotate them if exposed

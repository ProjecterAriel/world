# Terra AI

A cross-platform Earth exploration and AI platform.

## Current foundation
- FastAPI backend with MongoDB-backed accounts and preferences
- Responsive web client served by the API
- JWT authentication
- Health endpoint for Render

## Local development
1. Create a virtual environment and install `backend/requirements.txt`.
2. Copy `.env.example` to `.env` and configure MongoDB and a JWT secret.
3. Run `uvicorn backend.main:app --reload`.
4. Open http://localhost:8000.

The Cesium, OpenWeather, Groq and Cloudflare integrations will be added in subsequent implementation stages. Keep provider credentials on the server; never commit real API keys.

# Saki - Active Learning Framework

## Project Structure

- `saki-web/`: Frontend (React + TypeScript + Vite)
- `saki-api/`: Backend (FastAPI + Python)
- `data/`: Data storage

## Getting Started

### Prerequisites

- Node.js (v16+)
- Python (v3.9+)

### Backend Setup (using uv)

1. Navigate to `saki-api`:
   ```bash
   cd saki-api
   ```
2. Install dependencies and create virtual environment with uv:
   ```bash
   # Install uv if you haven't already: pip install uv
   uv sync
   ```
3. Run the server:
   ```bash
   uv run uvicorn main:app --reload
   ```

### Frontend Setup

1. Navigate to `saki-web`:
   ```bash
   cd saki-web
   ```
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev
   ```

## Documentation

See `DESIGN.md` for architecture details.

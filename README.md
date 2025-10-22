# Pickleball Open Play (Streamlit)

This Streamlit app runs a Pickleball open-play queue and court manager:
- doubles with winners staying and splitting into opposing teams
- winners can stay for up to N consecutive games (configurable)
- losers go to back of queue
- avoids repeat teammates when filling spots (best-effort)
- autosaves state to `pickleball_data.json`
- exports history + state to Excel

## Files
- `app.py` — main Streamlit app
- `requirements.txt` — required Python packages
- `pickleball_data.json` — created automatically when the app is used

## Run locally
1. Install Python 3.8+.
2. Create and activate a virtual environment (optional but recommended).
3. Install dependencies:

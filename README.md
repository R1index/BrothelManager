# Discord Gacha Girls Bot

Features:
- Girl collection
- Leveling: girls, skills, sub-skills
- Gacha
- Currency
- Service market (demand/supply; 100% failure if requirements mismatch)
- Stamina (regenerates every 10 minutes)
- JSON storage (`data/`)

## Run

1. Установите зависимости (Python 3.10+):
```bash
python -m venv .venv
. .venv/Scripts/activate  # Windows
pip install -r requirements.txt
```

2. Put your token into `config.json`:
```json
{ "token": "PASTE_YOUR_BOT_TOKEN_HERE" }
```

3. Run:
```bash
python -m src.bot
```

## Main Slash Commands
- `/start` — create profile, get starter coins and your first girl
- `/profile` — show coins and stamina
- `/gacha [times]` — gacha rolls
- `/girls` — list your girls + images
- `/market` — generate/show service market
- `/work job_id girl_id` — do a job with chosen girl
- `/upgrade girl_id [level|skill|sub] ...` — контекстные апгрейды при наличии валюты

Все данные сохраняются в `data/users/<user_id>.json` и `data/market/<user_id>.json`.

- `/dismantle` — dismantle a girl for coins


## Local Image Assets
Put character images under `assets/girls/<girl_slug>/`:
```
assets/girls/lyra/
  lyra_profile.png
  monster/
    anal.png
    vaginal.png
    oral.png
    nipple.png
  beast/
    anal.png
    vaginal.png
    oral.png
    nipple.png
  insect/
    anal.png
    vaginal.png
    oral.png
    nipple.png
  human/
    anal.png
    vaginal.png
    oral.png
    nipple.png
```
- Profile: `<slug>_profile.(png|jpg)` or `profile.(png|jpg)`
- Action images are picked by main & sub skill used in `/work`.
- If a local image is missing, the bot falls back to the girl's `image_url`.

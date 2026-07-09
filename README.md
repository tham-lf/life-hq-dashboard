# Life HQ — Gym & Sleep dashboard

A Streamlit app that sits **on top of your existing Notion gym data**. Log sets
and sleep, see progression and sleep trends — without clicking through Notion.
Your `gym-session-prep` routine keeps generating the sessions + targets; this is
just a faster way to record and review.

## What it does

| Tab | What |
|---|---|
| 🏋️ Log | Pick a date → today's session as an editable table. Type weight/reps/RPE, tick Done, hit **Save** → writes back to the Notion Set Log. Shows the muscles + recovery + cue up top. |
| 📈 Progress | Pick an exercise → top-set weight over time + best/latest/session-count stats. |
| 🗓️ Upcoming | Next planned sessions with muscles worked + the ~48h recovery note. |
| 😴 Sleep | Log hours + quality (creates a **Sleep Log** DB in Notion on first use), trend chart vs your 7h target, 7-night average. |

## Setup (one time)

```powershell
cd C:\Users\thaml.DESKTOP-K200JBN\projects\life-hq\gym_dashboard
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# open .env and paste your Notion integration token (the gym one)
```

## Run

```powershell
streamlit run app.py
```

Opens at http://localhost:8501.

## Notes

- **Data source of truth is Notion.** Reads/writes Sessions, Set Log, Exercises
  via the raw 2025-09-03 data-source REST API (ids hardcoded in `app.py`).
- **Sleep** lives in its own `😴 Sleep Log` Notion database, created under the Gym
  hub the first time you use the Sleep tab; its id is cached in `sleep_ds.txt`.
- `.env` and `sleep_ds.txt` are local only — do not commit them.
- If the sidebar says "Notion not connected", the token in `.env` is missing or
  lacks access to the gym databases.

## Deploy (Streamlit Community Cloud)

Lets you log from your phone at the gym. Free.

1. **Push this folder to a private GitHub repo.** `.env` and `sleep_ds.txt` are
   git-ignored, so no secrets get committed.
2. **Create the Sleep Log first, locally** (run the app, open the Sleep tab,
   click "Create Sleep Log"). Copy the id from `sleep_ds.txt` — you'll paste it
   into cloud secrets so the deploy reuses it instead of recreating it each reboot
   (the cloud filesystem is ephemeral).
3. On https://share.streamlit.io → **New app** → pick the repo, `app.py`.
4. **App settings → Secrets**, paste:
   ```toml
   NOTION_TOKEN = "ntn_your_token"
   SLEEP_DS = "your_sleep_data_source_id"
   ```
5. **App settings → Sharing → make it private**, and add your own Google email as
   the only viewer. ⚠️ Do this — a public app would expose your gym/sleep data and,
   because the app writes to Notion, let anyone with the URL poke your data.


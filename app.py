"""Life HQ — Gym & Sleep dashboard.

A fast face over the existing Notion gym databases (Sessions, Set Log,
Exercises) plus a self-created Sleep Log. Log sets and sleep, see
progression and sleep trends. Run: streamlit run app.py
"""
import datetime as dt
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import notion_api as nx

load_dotenv(Path(__file__).with_name(".env"))

# --- Notion data-source ids (non-secret; from gym-session-prep SKILL.md) ---
EXERCISES_DS = "aceaf93b-f1fb-491d-9660-fa261b972e3d"
SESSIONS_DS = "5b4eb401-0dbd-4a41-a5b1-b8f46b046596"
SETLOG_DS = "74a380f4-1512-4095-9965-82f79f69ac0f"
GYM_HUB_PAGE = "37e924cf-541c-817e-8a77-dfb889ee63cb"

SLEEP_TARGET = 7.0
SLEEP_DS_FILE = Path(__file__).with_name("sleep_ds.txt")

MUSCLES = {
    "Push": "Chest · Shoulders · Triceps",
    "Pull": "Back · Biceps · Rear delts",
    "Legs": "Quads · Hamstrings · Glutes · Calves",
}

st.set_page_config(page_title="Life HQ — Gym & Sleep", page_icon="💪", layout="wide")

# On Streamlit Cloud there is no .env — fall back to st.secrets for the token
# (and an optional pre-created Sleep Log id, so ephemeral deploys don't recreate it).
try:
    for _k in ("NOTION_TOKEN", "SLEEP_DS"):
        if not os.environ.get(_k) and _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001  (no secrets file locally is fine)
    pass


def muscles_for(day):
    for prefix, mus in MUSCLES.items():
        if day and day.startswith(prefix):
            return mus
    return "—"


def _num(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return float(v)


def _changed(a, b):
    return _num(a) != _num(b)


@st.cache_data(ttl=600, show_spinner=False)
def load_exercises():
    out = {}
    for r in nx.query(EXERCISES_DS, page_size=100):
        p = r["properties"]
        out[r["id"]] = {
            "name": nx.title_text(p, "Name"),
            "increment": nx.number(p, "Increment kg"),
            "start": nx.number(p, "Start weight kg"),
            "muscle": nx.select_name(p, "Muscle Group"),
            "rep_range": nx.rich_text(p, "Rep range"),
        }
    return out


def session_for_date(day_iso):
    rows = nx.query(SESSIONS_DS, filter={"property": "Date", "date": {"equals": day_iso}}, page_size=5)
    return rows[0] if rows else None


def sets_for_session(session_id):
    return nx.query(
        SETLOG_DS,
        filter={"property": "Session", "relation": {"contains": session_id}},
        sorts=[{"property": "Order", "direction": "ascending"}],
        page_size=100,
    )


def sleep_ds_id():
    # Prefer an explicit id (env/secret) so cloud deploys don't recreate the DB
    # on every reboot; else the locally-cached id from first creation.
    if os.environ.get("SLEEP_DS"):
        return os.environ["SLEEP_DS"].strip()
    return SLEEP_DS_FILE.read_text().strip() if SLEEP_DS_FILE.exists() else None


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Life HQ")
st.sidebar.caption("Gym & sleep · on top of Notion")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

try:
    nx.query(SESSIONS_DS, page_size=1)
    st.sidebar.success("Notion connected")
except Exception as exc:  # noqa: BLE001
    st.sidebar.error("Notion not connected")
    st.sidebar.caption(str(exc)[:300])
    st.title("💪 Life HQ — Gym & Sleep")
    st.warning("Set NOTION_TOKEN in .env (copy from .env.example), then Refresh.")
    st.stop()

exercises = load_exercises()

tab_log, tab_prog, tab_up, tab_sleep = st.tabs(
    ["🏋️ Log", "📈 Progress", "🗓️ Upcoming", "😴 Sleep"]
)

# ---------------------------------------------------------------- Log tab
with tab_log:
    top = st.columns([1, 2])
    day = top[0].date_input("Session date", dt.date.today())
    day_iso = day.isoformat()
    sess = session_for_date(day_iso)

    if not sess:
        st.info(f"No workout session on {day_iso} — rest day, or the morning routine hasn't generated it yet.")
    else:
        sp = sess["properties"]
        day_name = nx.select_name(sp, "Day") or "—"
        status = nx.select_name(sp, "Status") or "—"
        top[1].markdown(f"### {day_name} · _{status}_")
        top[1].caption(
            f"💪 {muscles_for(day_name)}  ·  🔧 grows ~48h — leave ~2 days before the next hard "
            f"session for these  ·  🏋️ 3-sec lowering · rest 1–3 min · phone away"
        )

        rows = sets_for_session(sess["id"])
        recs, page_ids = [], []
        for r in rows:
            p = r["properties"]
            ex_ids = nx.relation_ids(p, "Exercise")
            ex_name = exercises.get(ex_ids[0], {}).get("name") if ex_ids else None
            recs.append({
                "Exercise": ex_name or nx.title_text(p, "Entry"),
                "Set": nx.number(p, "Set #"),
                "Target": nx.number(p, "Target kg"),
                "Weight": nx.number(p, "Weight kg"),
                "Reps": nx.number(p, "Reps"),
                "RPE": nx.number(p, "RPE"),
                "Done": nx.checkbox(p, "Done"),
            })
            page_ids.append(r["id"])

        if not recs:
            st.warning("This session has no Set Log rows yet (skeleton not populated).")
        else:
            original = pd.DataFrame(recs)
            edited = st.data_editor(
                original,
                key=f"editor_{sess['id']}",
                use_container_width=True,
                hide_index=True,
                disabled=["Exercise", "Set", "Target"],
                column_config={
                    "Target": st.column_config.NumberColumn("Target kg", format="%.1f"),
                    "Weight": st.column_config.NumberColumn("Weight kg", format="%.1f", min_value=0.0, step=0.5),
                    "Reps": st.column_config.NumberColumn("Reps", min_value=0, step=1),
                    "RPE": st.column_config.NumberColumn("RPE", min_value=1.0, max_value=10.0, step=0.5),
                    "Done": st.column_config.CheckboxColumn("Done"),
                },
            )

            if st.button("💾 Save sets", type="primary"):
                saved, errors = 0, []
                for i, pid in enumerate(page_ids):
                    props = {}
                    for col, field in (("Weight", "Weight kg"), ("Reps", "Reps"), ("RPE", "RPE")):
                        if _changed(original.at[i, col], edited.at[i, col]):
                            props[field] = {"number": _num(edited.at[i, col])}
                    if bool(original.at[i, "Done"]) != bool(edited.at[i, "Done"]):
                        props["Done"] = {"checkbox": bool(edited.at[i, "Done"])}
                    if props:
                        try:
                            nx.update_page(pid, props)
                            saved += 1
                        except Exception as exc:  # noqa: BLE001
                            errors.append(str(exc)[:200])
                if errors:
                    st.error(f"Saved {saved}, {len(errors)} failed — {errors[0]}")
                elif saved:
                    st.success(f"Saved {saved} row(s) to Notion.")
                else:
                    st.info("No changes to save.")

# ------------------------------------------------------------ Progress tab
with tab_prog:
    names = sorted({v["name"] for v in exercises.values() if v["name"]})
    if not names:
        st.info("No exercises found.")
    else:
        default = names.index("Barbell Back Squat") if "Barbell Back Squat" in names else 0
        name = st.selectbox("Exercise", names, index=default)
        ex_id = next((eid for eid, v in exercises.items() if v["name"] == name), None)
        logs = nx.query(
            SETLOG_DS,
            filter={"property": "Exercise", "relation": {"contains": ex_id}},
            sorts=[{"property": "Date", "direction": "ascending"}],
            page_size=100,
        ) if ex_id else []
        recs = []
        for r in logs:
            p = r["properties"]
            d, w = nx.date_start(p, "Date"), nx.number(p, "Weight kg")
            if d and w:
                recs.append({"Date": d, "Weight": w, "Reps": nx.number(p, "Reps") or 0})
        if not recs:
            st.info("No logged sets yet for this exercise — log some on the Log tab.")
        else:
            df = pd.DataFrame(recs)
            df["Date"] = pd.to_datetime(df["Date"])
            top_sets = df.groupby("Date", as_index=False)["Weight"].max()
            chart = (
                alt.Chart(top_sets)
                .mark_line(point=True)
                .encode(x=alt.X("Date:T", title=""), y=alt.Y("Weight:Q", title="Top-set weight (kg)"))
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
            c = st.columns(3)
            c[0].metric("Best ever", f"{df['Weight'].max():.1f} kg")
            c[1].metric("Latest top set", f"{top_sets.iloc[-1]['Weight']:.1f} kg")
            c[2].metric("Sessions logged", f"{top_sets.shape[0]}")
            st.dataframe(
                df.sort_values("Date", ascending=False).head(20),
                hide_index=True, use_container_width=True,
            )

# ------------------------------------------------------------ Upcoming tab
with tab_up:
    today_iso = dt.date.today().isoformat()
    rows = nx.query(
        SESSIONS_DS,
        filter={"and": [
            {"property": "Status", "select": {"equals": "Planned"}},
            {"property": "Date", "date": {"on_or_after": today_iso}},
        ]},
        sorts=[{"property": "Date", "direction": "ascending"}],
        page_size=30,
    )
    if not rows:
        st.info("No upcoming planned sessions.")
    for r in rows:
        p = r["properties"]
        d = nx.date_start(p, "Date")
        day_name = nx.select_name(p, "Day") or "—"
        when = pd.to_datetime(d).strftime("%a %d %b") if d else "—"
        with st.container(border=True):
            st.markdown(f"**{when} · {day_name}**")
            st.caption(f"💪 {muscles_for(day_name)}  ·  🔧 grows ~48h → leave ~2 days before hitting these again")

# ------------------------------------------------------------ Sleep tab
with tab_sleep:
    ds = sleep_ds_id()
    if not ds:
        st.info("No Sleep Log table yet. Create one in Notion (under your Gym hub) in one click:")
        if st.button("➕ Create Sleep Log in Notion"):
            try:
                db = nx.create_database(GYM_HUB_PAGE, "😴 Sleep Log", {
                    "Night": {"title": {}},
                    "Date": {"date": {}},
                    "Hours": {"number": {"format": "number"}},
                    "Quality": {"select": {"options": [
                        {"name": "Great", "color": "green"},
                        {"name": "OK", "color": "yellow"},
                        {"name": "Poor", "color": "red"},
                    ]}},
                    "Notes": {"rich_text": {}},
                })
                SLEEP_DS_FILE.write_text(db["data_sources"][0]["id"])
                st.success("Created. Reloading…")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc)[:400])
    else:
        with st.form("sleep_form"):
            cols = st.columns(3)
            night = cols[0].date_input("Night of", dt.date.today())
            hours = cols[1].number_input("Hours slept", 0.0, 14.0, 7.0, 0.25)
            quality = cols[2].selectbox("Quality", ["Great", "OK", "Poor"], index=1)
            note = st.text_input("Notes", "")
            if st.form_submit_button("💾 Log sleep", type="primary"):
                props = {
                    "Night": {"title": [{"text": {"content": night.isoformat()}}]},
                    "Date": {"date": {"start": night.isoformat()}},
                    "Hours": {"number": float(hours)},
                    "Quality": {"select": {"name": quality}},
                }
                if note:
                    props["Notes"] = {"rich_text": [{"text": {"content": note}}]}
                try:
                    nx.create_page(ds, props)
                    st.success(f"Logged {hours:g}h for {night.isoformat()}.")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc)[:400])

        logs = nx.query(ds, sorts=[{"property": "Date", "direction": "ascending"}], page_size=100)
        recs = []
        for r in logs:
            p = r["properties"]
            d, h = nx.date_start(p, "Date"), nx.number(p, "Hours")
            if d and h is not None:
                recs.append({"Date": d, "Hours": h})
        if recs:
            df = pd.DataFrame(recs)
            df["Date"] = pd.to_datetime(df["Date"])
            bars = alt.Chart(df).mark_bar().encode(
                x=alt.X("Date:T", title=""), y=alt.Y("Hours:Q", title="Hours slept")
            ).properties(height=300)
            target = alt.Chart(pd.DataFrame({"y": [SLEEP_TARGET]})).mark_rule(
                color="#E24B4A", strokeDash=[4, 4]
            ).encode(y="y:Q")
            st.altair_chart(bars + target, use_container_width=True)
            last7 = df.sort_values("Date").tail(7)["Hours"].mean()
            st.metric("Avg last 7 nights", f"{last7:.1f} h", delta=f"{last7 - SLEEP_TARGET:+.1f} vs 7h target")
        else:
            st.caption("No sleep logged yet — add your first night above.")

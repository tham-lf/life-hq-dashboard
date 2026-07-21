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
import plan

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

RPE_LABELS = {6: "6 · easy", 7: "7 · 3 left", 8: "8 · 2 left", 9: "9 · 1 left", 10: "10 · max"}
RPE_OPTIONS = ["", "6 · easy", "7 · 3 left", "8 · 2 left", "9 · 1 left", "10 · max"]
RPE_HELP = "How hard it felt — 10 = all-out, 9 = ~1 rep left, 8 = ~2 left, 7 = ~3 left. Aim 8–9 on working sets."


def rpe_to_label(n):
    return RPE_LABELS.get(int(round(n)), "") if n is not None else ""


def label_to_rpe(label):
    return int(label.split()[0]) if label else None

st.set_page_config(page_title="Life HQ — Gym & Sleep", page_icon="💪", layout="wide")

# On Streamlit Cloud there is no .env — fall back to st.secrets for the token
# (and an optional pre-created Sleep Log id, so ephemeral deploys don't recreate it).
try:
    for _k in ("NOTION_TOKEN", "SLEEP_DS"):
        if not os.environ.get(_k) and _k in st.secrets:
            os.environ[_k] = str(st.secrets[_k])
except Exception:  # noqa: BLE001  (no secrets file locally is fine)
    pass

st.markdown(
    """<style>
    div[data-testid="stNumberInput"] input { font-size: 1.15rem; padding: 0.45rem 0.5rem; }
    div[data-testid="stNumberInput"] button { min-height: 2.6rem; }
    div.stButton > button { min-height: 2.9rem; font-size: 1.05rem; }
    </style>""",
    unsafe_allow_html=True,
)


def muscles_for(day):
    for prefix, mus in MUSCLES.items():
        if day and day.startswith(prefix):
            return mus
    return "—"


def save_set(pid):
    """Write one set to Notion immediately (per-set autosave — survives a
    mid-workout disconnect; only the current set can be lost, never the session)."""
    ss = st.session_state
    props = {"Done": {"checkbox": bool(ss.get(f"done_{pid}", False))}}
    if ss.get(f"w_{pid}") is not None:
        props["Weight kg"] = {"number": float(ss[f"w_{pid}"])}
    if ss.get(f"r_{pid}") is not None:
        props["Reps"] = {"number": int(ss[f"r_{pid}"])}
    if f"rpe_{pid}" in ss:
        props["RPE"] = {"number": label_to_rpe(ss[f"rpe_{pid}"])}
    try:
        nx.update_page(pid, props)
        ss[f"err_{pid}"] = ""
    except Exception as exc:  # noqa: BLE001
        ss[f"err_{pid}"] = str(exc)[:150]


def toggle_done(pid):
    st.session_state[f"done_{pid}"] = not st.session_state.get(f"done_{pid}", False)
    save_set(pid)


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


@st.cache_data(ttl=60, show_spinner=False)
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


@st.cache_data(ttl=300, show_spinner=False)
def training_days():
    """{iso_date: sets_logged} for each day that has >=1 logged Weight."""
    out = {}
    for r in nx.query(SETLOG_DS, page_size=100):
        p = r["properties"]
        d, w = nx.date_start(p, "Date"), nx.number(p, "Weight kg")
        if d and w is not None:
            key = d[:10]
            out[key] = out.get(key, 0) + 1
    return out


@st.cache_data(ttl=120, show_spinner=False)
def last_perf(before_iso):
    """{exercise_id: (weight, reps, date)} — heaviest set of the most recent
    session BEFORE before_iso, for the 'last time' progress hint while logging."""
    by_ex = {}
    for r in nx.query(SETLOG_DS, sorts=[{"property": "Date", "direction": "descending"}], page_size=100):
        p = r["properties"]
        ex = nx.relation_ids(p, "Exercise")
        d, w, rp = nx.date_start(p, "Date"), nx.number(p, "Weight kg"), nx.number(p, "Reps")
        if not ex or w is None or not d or d[:10] >= before_iso:
            continue
        by_ex.setdefault(ex[0], []).append((d[:10], w, rp))
    out = {}
    for eid, lst in by_ex.items():
        last_date = max(x[0] for x in lst)
        w_best, rp_best = max(((w, rp) for (d, w, rp) in lst if d == last_date), key=lambda x: x[0])
        out[eid] = (w_best, rp_best, last_date)
    return out


def sleep_ds_id():
    # Prefer an explicit id (env/secret) so cloud deploys don't recreate the DB
    # on every reboot; else the locally-cached id from first creation.
    if os.environ.get("SLEEP_DS"):
        return os.environ["SLEEP_DS"].strip()
    return SLEEP_DS_FILE.read_text().strip() if SLEEP_DS_FILE.exists() else None


# Cached reads — these fire on every rerun (all tabs execute); caching keeps a
# per-set Done tap to ~1 write + 1 fresh sets query instead of ~6 round-trips.
@st.cache_data(ttl=300, show_spinner=False)
def notion_ok():
    nx.query(SESSIONS_DS, page_size=1)
    return True


@st.cache_data(ttl=120, show_spinner=False)
def exercise_history(ex_id):
    if not ex_id:
        return []
    return nx.query(
        SETLOG_DS,
        filter={"property": "Exercise", "relation": {"contains": ex_id}},
        sorts=[{"property": "Date", "direction": "ascending"}],
        page_size=100,
    )


@st.cache_data(ttl=120, show_spinner=False)
def upcoming_sessions(today_iso):
    return nx.query(
        SESSIONS_DS,
        filter={"and": [
            {"property": "Status", "select": {"equals": "Planned"}},
            {"property": "Date", "date": {"on_or_after": today_iso}},
        ]},
        sorts=[{"property": "Date", "direction": "ascending"}],
        page_size=30,
    )


@st.cache_data(ttl=120, show_spinner=False)
def sleep_logs(ds):
    return nx.query(ds, sorts=[{"property": "Date", "direction": "ascending"}], page_size=100)


# ---------------------------------------------------------------- sidebar
st.sidebar.title("Life HQ")
st.sidebar.caption("Gym & sleep · on top of Notion")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()

try:
    notion_ok()
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
        sets_data = []
        for r in rows:
            p = r["properties"]
            ex_ids = nx.relation_ids(p, "Exercise")
            name = (exercises.get(ex_ids[0], {}).get("name") if ex_ids else None) or nx.title_text(p, "Entry")
            tgt = nx.number(p, "Target kg")
            sets_data.append({
                "pid": r["id"], "ex_id": ex_ids[0] if ex_ids else None, "name": name, "set": nx.number(p, "Set #"),
                "target": tgt, "weight": nx.number(p, "Weight kg"), "reps": nx.number(p, "Reps"),
                "rpe": rpe_to_label(nx.number(p, "RPE")), "done": nx.checkbox(p, "Done"),
                "note": nx.rich_text(p, "Notes"), "weighted": tgt is not None,
            })

        if not sets_data:
            gen_key = f"gen_{sess['id']}"
            ex_by_name = {
                v["name"]: {"id": eid, "increment": v["increment"], "start": v["start"]}
                for eid, v in exercises.items()
            }
            # Auto-build today's sets on open — no dependency on the 6:30 laptop task.
            # "done"/"failed" latch so a lagging re-read can't double-generate or loop.
            if st.session_state.get(gen_key) not in ("failed", "done") and day_name in plan.PLANS:
                try:
                    with st.spinner(f"Setting up today's {day_name} — one moment…"):
                        made, _missing = plan.generate_sets(
                            nx, SETLOG_DS, sess["id"], day_name, day_iso, ex_by_name
                        )
                    st.session_state[gen_key] = "done" if made > 0 else "failed"
                    if made > 0:
                        st.cache_data.clear()
                        st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.session_state[gen_key] = "failed"
                    st.error(f"Auto-setup hit an error: {str(exc)[:200]}")
            st.warning(f"Tap to build today's {day_name} lineup:")
            if st.button("⚡ Generate today's sets", type="primary", width="stretch"):
                st.session_state[gen_key] = None
                st.rerun()
        else:
            perf = last_perf(day_iso)
            plan_reps = {e[0]: e[3] for e in plan.PLANS.get(day_name, {}).get("ex", [])}
            done_n = sum(1 for s in sets_data if st.session_state.get(f"done_{s['pid']}", s["done"]))
            st.progress(done_n / len(sets_data), text=f"{done_n} / {len(sets_data)} sets done")
            show_rpe = st.checkbox("Log RPE", value=False, help=RPE_HELP)
            st.caption("Boxes pre-fill to your target — hit it? just tap **Done**. Different? change the box first. Every **Done** saves to Notion instantly (no session to lose).")

            last_name = None
            for s in sets_data:
                pid = s["pid"]
                if f"done_{pid}" not in st.session_state:
                    st.session_state[f"done_{pid}"] = s["done"]
                treps = plan_reps.get(s["name"]) if s["weighted"] else None
                if s["name"] != last_name:
                    last_name = s["name"]
                    hdr = f"**{s['name']}**"
                    if s["weighted"]:
                        hdr += f"  ·  🎯 {s['target']:g} kg" + (f" × {treps}" if treps else "")
                    st.markdown(hdr)
                    lp = perf.get(s["ex_id"])
                    if lp:
                        st.caption(f"↩️ last time: {lp[0]:g} kg × {lp[1] if lp[1] is not None else '—'}  ·  {lp[2]}")
                    elif s["note"] and not s["weighted"]:
                        st.caption(s["note"])

                wants_reps = s["weighted"] or "rep" in s["note"].lower() or "amrap" in s["note"].lower()
                dflt_w = s["weight"] if s["weight"] is not None else s["target"]
                dflt_r = s["reps"] if s["reps"] is not None else (treps if s["weighted"] else None)
                fields = []
                if s["weighted"]:
                    fields.append("w")
                if wants_reps:
                    fields.append("r")
                if s["weighted"] and show_rpe:
                    fields.append("rpe")
                fields.append("done")
                span = {"w": 1.1, "r": 1.0, "rpe": 1.2, "done": 1.6}
                cols = st.columns([0.4] + [span[f] for f in fields])
                cols[0].markdown(f"<div style='padding-top:1.9rem;color:#888'>S{int(s['set']) if s['set'] else '·'}</div>", unsafe_allow_html=True)
                ci = 1
                for f in fields:
                    c = cols[ci]
                    ci += 1
                    if f == "w":
                        c.number_input("weight (kg)", value=float(dflt_w) if dflt_w is not None else None, min_value=0.0, step=0.5, format="%.1f", key=f"w_{pid}", on_change=save_set, args=(pid,))
                    elif f == "r":
                        c.number_input("reps", value=int(dflt_r) if dflt_r is not None else None, min_value=0, step=1, key=f"r_{pid}", on_change=save_set, args=(pid,))
                    elif f == "rpe":
                        sel = RPE_OPTIONS.index(s["rpe"]) if s["rpe"] in RPE_OPTIONS else 0
                        c.selectbox("RPE", RPE_OPTIONS, index=sel, key=f"rpe_{pid}", on_change=save_set, args=(pid,))
                    elif f == "done":
                        dn = st.session_state.get(f"done_{pid}", False)
                        c.markdown("<div style='height:1.55rem'></div>", unsafe_allow_html=True)
                        c.button("✓ Done" if dn else "Done", key=f"btn_{pid}", type="primary" if dn else "secondary", on_click=toggle_done, args=(pid,), width="stretch")
                if st.session_state.get(f"err_{pid}"):
                    st.caption(f"⚠️ didn't save — {st.session_state[f'err_{pid}']} · tap Done again")

# ------------------------------------------------------------ Progress tab
with tab_prog:
    st.markdown("#### How consistent you've been")
    _days = training_days()
    if not _days:
        st.info("No workouts logged yet — log sets on the Log tab and your consistency shows up here.")
    else:
        _dts = sorted(dt.date.fromisoformat(k) for k in _days)
        _today = dt.date.today()
        _wk = _today - dt.timedelta(days=_today.weekday())
        _mo = _today.replace(day=1)
        _c = st.columns(4)
        _c[0].metric("This week", sum(1 for d in _dts if d >= _wk))
        _c[1].metric("This month", sum(1 for d in _dts if d >= _mo))
        _c[2].metric("Last 30 days", sum(1 for d in _dts if d >= _today - dt.timedelta(days=30)))
        _c[3].metric("Days since last", (_today - _dts[-1]).days)
        st.caption("Counts days you logged a workout in this app.")

        _weeks = []
        for _i in range(11, -1, -1):
            _ws = _wk - dt.timedelta(weeks=_i)
            _weeks.append({
                "Week of": _ws,
                "Workouts": sum(1 for d in _dts if _ws <= d < _ws + dt.timedelta(days=7)),
            })
        _wdf = pd.DataFrame(_weeks)
        _wdf["Week of"] = pd.to_datetime(_wdf["Week of"])
        st.altair_chart(
            alt.Chart(_wdf).mark_bar(size=18).encode(
                x=alt.X("Week of:T", title=""),
                y=alt.Y("Workouts:Q", title="Workouts / week", axis=alt.Axis(tickMinStep=1)),
                tooltip=["Week of:T", "Workouts:Q"],
            ).properties(height=200),
            width="stretch",
        )

        _grid, _gs, _cur = [], _wk - dt.timedelta(weeks=11), _wk - dt.timedelta(weeks=11)
        while _cur <= _today:
            _grid.append({
                "week": (_cur - _gs).days // 7,
                "dow": _cur.strftime("%a"),
                "date": _cur.isoformat(),
                "sets": _days.get(_cur.isoformat(), 0),
            })
            _cur += dt.timedelta(days=1)
        _gdf = pd.DataFrame(_grid)
        st.altair_chart(
            alt.Chart(_gdf).mark_rect(stroke="white", strokeWidth=2).encode(
                x=alt.X("week:O", title="last 12 weeks", axis=alt.Axis(labels=False, ticks=False)),
                y=alt.Y("dow:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=""),
                color=alt.Color("sets:Q", title="sets", scale=alt.Scale(scheme="greens")),
                tooltip=["date", "sets"],
            ).properties(height=170),
            width="stretch",
        )

    st.divider()
    st.markdown("#### Strength by exercise")
    names = sorted({v["name"] for v in exercises.values() if v["name"]})
    if not names:
        st.info("No exercises found.")
    else:
        default = names.index("Barbell Back Squat") if "Barbell Back Squat" in names else 0
        name = st.selectbox("Exercise", names, index=default)
        ex_id = next((eid for eid, v in exercises.items() if v["name"] == name), None)
        logs = exercise_history(ex_id)
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
            st.altair_chart(chart, width="stretch")
            c = st.columns(3)
            c[0].metric("Best ever", f"{df['Weight'].max():.1f} kg")
            c[1].metric("Latest top set", f"{top_sets.iloc[-1]['Weight']:.1f} kg")
            c[2].metric("Sessions logged", f"{top_sets.shape[0]}")
            st.dataframe(
                df.sort_values("Date", ascending=False).head(20),
                hide_index=True, width="stretch",
            )

# ------------------------------------------------------------ Upcoming tab
with tab_up:
    today_iso = dt.date.today().isoformat()
    rows = upcoming_sessions(today_iso)
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
                    st.cache_data.clear()
                    st.success(f"Logged {hours:g}h for {night.isoformat()}.")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc)[:400])

        logs = sleep_logs(ds)
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
            st.altair_chart(bars + target, width="stretch")
            last7 = df.sort_values("Date").tail(7)["Hours"].mean()
            st.metric("Avg last 7 nights", f"{last7:.1f} h", delta=f"{last7 - SLEEP_TARGET:+.1f} vs 7h target")
        else:
            st.caption("No sleep logged yet — add your first night above.")

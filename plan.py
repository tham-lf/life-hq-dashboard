"""Session generation ported from the gym-session-prep routine.

Builds Set Log rows for a given Day with double-progression targets, so the app
can populate a session even when the morning routine didn't run. Increments and
start weights come from the Exercises DB (passed in); the templates below only
fix which exercises, how many sets, the rep-range top, and non-weighted notes.
"""

WALL_SIT = "Hold 45 s · ~15 s rest · knees ~60°, pain ≤3/10"

# (name, sets, kind, rep_high, note)
#   kind: "w" weighted (double progression on rep_high), "t" timed hold,
#         "bw" bodyweight reps, "ball", "amrap", "cardio"
PLANS = {
    "Push A": {"incline": "10–12", "ex": [
        ("Wall Sit", 3, "t", None, WALL_SIT),
        ("Incline Chest Press", 4, "w", 10, None),
        ("Chest Press (pin-loaded)", 3, "w", 12, None),
        ("Pec Fly", 3, "w", 15, None),
        ("Shoulder Press (machine)", 3, "w", 12, None),
        ("Cable Tricep Pushdown", 3, "w", 15, None),
        ("Plank", 3, "t", None, "Hold 45 s"),
        ("Incline Walk", 1, "cardio", None, None),
    ]},
    "Pull A": {"incline": "10–12", "ex": [
        ("Wall Sit", 3, "t", None, WALL_SIT),
        ("Lat Pulldown", 4, "w", 10, None),
        ("Seated Row", 3, "w", 12, None),
        ("Rear Delt Fly", 3, "w", 15, None),
        ("Cable Bicep Curl", 3, "w", 12, None),
        ("Back Extension", 3, "bw", None, "12–15 reps"),
        ("Hanging Knee Raise", 3, "bw", None, "12–15 reps"),
        ("Incline Walk", 1, "cardio", None, None),
    ]},
    "Legs A": {"incline": "8–10", "ex": [
        ("Wall Sit", 5, "t", None, WALL_SIT),
        ("Leg Press", 4, "w", 12, None),
        ("Glute Drive", 3, "w", 12, None),
        ("Leg Curl", 3, "w", 15, None),
        ("Hip Adductor / Abductor", 3, "w", 15, None),
        ("Cable Crunch", 3, "w", 20, None),
        ("Russian Twist (Wall Ball)", 3, "ball", None, "20 reps · 4–6 kg ball"),
        ("Incline Walk", 1, "cardio", None, None),
    ]},
    "Push B": {"incline": "10–12", "ex": [
        ("Wall Sit", 3, "t", None, WALL_SIT),
        ("Barbell Bench Press (Flat)", 4, "w", 8, None),
        ("Decline Bench Press", 3, "w", 10, None),
        ("Dumbbell Incline Fly", 3, "w", 12, None),
        ("Smith Machine Shoulder Press", 3, "w", 10, None),
        ("Overhead Tricep Extension", 3, "w", 15, None),
        ("Ab Wheel", 3, "bw", None, "12 reps"),
        ("Incline Walk", 1, "cardio", None, None),
    ]},
    "Pull B": {"incline": "10–12", "ex": [
        ("Wall Sit", 3, "t", None, WALL_SIT),
        ("Deadlift", 4, "w", 6, None),
        ("Pull-up (or Assisted)", 3, "amrap", None, "AMRAP · BW or −20/−30 kg assist"),
        ("Dumbbell Row (single arm)", 3, "w", 12, None),
        ("Face Pull (cable)", 3, "w", 20, None),
        ("Hammer Curl (dumbbell)", 3, "w", 12, None),
        ("Side Plank", 2, "t", None, "Hold 30 s each side"),
        ("Incline Walk", 1, "cardio", None, None),
    ]},
    "Legs B": {"incline": "6–8", "ex": [
        ("Wall Sit", 5, "t", None, WALL_SIT),
        ("Barbell Back Squat", 4, "w", 10, None),
        ("Romanian Deadlift", 3, "w", 12, None),
        ("Bulgarian Split Squat", 3, "w", 12, None),
        ("Standing Calf Raise", 4, "w", 20, None),
        ("Wall Ball Shots", 3, "ball", None, "20 reps · 6–9 kg ball · skip if catch hurts knee"),
        ("Incline Walk", 1, "cardio", None, None),
    ]},
}


def _round_half(x):
    return round(x * 2) / 2


def compute_target(nx, setlog_ds, ex, rep_high, today_iso):
    """Double progression: from the most recent PRIOR date that has logged
    weights for this exercise, take the heaviest set. Cleared the top of the
    rep range -> add the increment; else repeat; no history -> start weight."""
    logs = nx.query(
        setlog_ds,
        filter={"and": [
            {"property": "Exercise", "relation": {"contains": ex["id"]}},
            {"property": "Date", "date": {"before": today_iso}},
        ]},
        sorts=[{"property": "Date", "direction": "descending"}],
        page_size=25,
    )
    target_date, maxw, reps_at_max = None, None, 0
    for r in logs:
        p = r["properties"]
        d, w, reps = nx.date_start(p, "Date"), nx.number(p, "Weight kg"), nx.number(p, "Reps")
        if w is None:
            continue
        if target_date is None:
            target_date = d
        if d != target_date:
            break
        if maxw is None or w > maxw:
            maxw, reps_at_max = w, reps or 0
    if maxw is None:
        return ex.get("start")
    inc = ex.get("increment") or 0
    if rep_high is not None and reps_at_max >= rep_high:
        return _round_half(maxw + inc)
    return maxw


def generate_sets(nx, setlog_ds, session_id, day, today_iso, exercises_by_name):
    """Create Set Log rows for the session's Day. Returns (created, missing_names)."""
    plan = PLANS.get(day)
    if not plan:
        raise ValueError(f"No plan template for day '{day}'.")
    order, created, missing = 0, 0, []
    for name, sets, kind, rep_high, note in plan["ex"]:
        ex = exercises_by_name.get(name)
        if not ex:
            missing.append(name)
            continue
        target = compute_target(nx, setlog_ds, ex, rep_high, today_iso) if kind == "w" else None
        row_note = f"30 min · incline {plan['incline']}, 5.0–5.5 km/h" if kind == "cardio" else note
        for s in range(1, sets + 1):
            order += 1
            props = {
                "Entry": {"title": [{"text": {"content": f"{name} · S{s}"}}]},
                "Order": {"number": order},
                "Set #": {"number": s},
                "Date": {"date": {"start": today_iso}},
                "Session": {"relation": [{"id": session_id}]},
                "Exercise": {"relation": [{"id": ex["id"]}]},
            }
            if target is not None:
                props["Target kg"] = {"number": target}
            if row_note:
                props["Notes"] = {"rich_text": [{"text": {"content": row_note}}]}
            nx.create_page(setlog_ds, props)
            created += 1
    return created, missing

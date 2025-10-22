# app.py
import streamlit as st
import pandas as pd
import json
from collections import deque
from datetime import datetime
from itertools import combinations
from pathlib import Path
from io import BytesIO

# ---------- constants / paths ----------
DATA_FILE = Path("pickleball_data.json")

# ---------- persistence ----------
def load_state():
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            state = {}
            state["config"] = raw.get("config", {})
            state["players"] = raw.get("players", [])
            state["active"] = raw.get("active", {})
            state["queue"] = deque(raw.get("queue", []))
            state["courts"] = {int(k):v for k,v in raw.get("courts", {}).items()}
            state["streaks"] = raw.get("streaks", {})
            state["history"] = raw.get("history", [])
            # past_teams stored as lists -> convert to sets
            state["past_teams"] = {k:set(v) for k,v in raw.get("past_teams", {}).items()}
            return state
        except Exception as e:
            st.warning(f"Could not load saved state: {e}")
    return None

def save_state():
    raw = {
        "config": st.session_state.config,
        "players": st.session_state.players,
        "active": st.session_state.active,
        "queue": list(st.session_state.queue),
        "courts": {str(k):v for k,v in st.session_state.courts.items()},
        "streaks": st.session_state.streaks,
        "history": st.session_state.history,
        "past_teams": {k:list(v) for k,v in st.session_state.past_teams.items()}
    }
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(raw, f, indent=2, default=str)

# ---------- initialization ----------
def init():
    loaded = load_state()
    if loaded:
        # initialize session_state from file
        for k,v in loaded.items():
            st.session_state[k] = v
        # ensure types are correct
        if not isinstance(st.session_state.queue, deque):
            st.session_state.queue = deque(st.session_state.queue)
        return

    # defaults
    if "config" not in st.session_state:
        st.session_state.config = {
            "max_consec_games": 2,
            "num_courts": 3,
            "num_players": 20,
            "score_to_win": 11
        }
    if "players" not in st.session_state:
        st.session_state.players = [f"Player {i}" for i in range(1, st.session_state.config["num_players"]+1)]
    if "active" not in st.session_state:
        st.session_state.active = {p: True for p in st.session_state.players}
    if "queue" not in st.session_state:
        st.session_state.queue = deque([p for p in st.session_state.players if st.session_state.active.get(p, True)])
    if "courts" not in st.session_state:
        st.session_state.courts = {i:[None,None,None,None] for i in range(1, st.session_state.config["num_courts"]+1)}
    if "streaks" not in st.session_state:
        st.session_state.streaks = {p:{"on_court":0,"overall":0} for p in st.session_state.players}
    if "history" not in st.session_state:
        st.session_state.history = []
    if "past_teams" not in st.session_state:
        st.session_state.past_teams = {p:set() for p in st.session_state.players}

# ---------- helpers ----------
def initialize_queue_from_players():
    st.session_state.queue = deque([p for p in st.session_state.players if st.session_state.active.get(p, True)])
    save_state()

def push_to_queue_back(player):
    st.session_state.queue.append(player)

def pop_queue_top():
    if st.session_state.queue:
        return st.session_state.queue.popleft()
    return None

def mark_pairing(a,b):
    st.session_state.past_teams.setdefault(a,set()).add(b)
    st.session_state.past_teams.setdefault(b,set()).add(a)

def assign_players_to_court(court_id):
    for i in range(4):
        if st.session_state.courts[court_id][i] is None:
            if st.session_state.queue:
                p = st.session_state.queue.popleft()
                st.session_state.courts[court_id][i] = p
                st.session_state.streaks.setdefault(p, {"on_court":0,"overall":0})
                st.session_state.streaks[p]["on_court"] = 1
    save_state()

def assign_all_courts():
    for cid in st.session_state.courts:
        assign_players_to_court(cid)

# ---------- game processing ----------
def process_winner(court_id, winners):
    court_players = st.session_state.courts[court_id].copy()
    if not all(w in court_players for w in winners):
        st.error("Winners must be on that court.")
        return
    if len(set(winners)) != 2:
        st.error("Enter exactly two distinct winners.")
        return

    team1 = court_players[:2]
    team2 = court_players[2:]

    if set(winners) == set(team1):
        winning_team, losing_team = team1, team2
    else:
        winning_team, losing_team = team2, team1

    # log history
    st.session_state.history.append({
        "timestamp": datetime.now().isoformat(),
        "court": court_id,
        "team1": team1,
        "team2": team2,
        "winning_team": winning_team.copy()
    })

    # record pairings
    for p1,p2 in combinations(team1,2):
        if p1 and p2: mark_pairing(p1,p2)
    for p1,p2 in combinations(team2,2):
        if p1 and p2: mark_pairing(p1,p2)

    # rotate losers
    for loser in losing_team:
        if loser:
            push_to_queue_back(loser)
            st.session_state.streaks[loser]["on_court"] = 0

    # winners may stay if under limit
    max_streak = int(st.session_state.config["max_consec_games"])
    keep = []
    for w in winning_team:
        if st.session_state.streaks.get(w, {"on_court":0})["on_court"] < max_streak:
            keep.append(w)
        else:
            push_to_queue_back(w)
            st.session_state.streaks[w]["on_court"] = 0

    # new court; try to keep winners in opposing slots
    new = [None,None,None,None]
    if len(keep) == 2:
        new[0] = keep[0]
        new[2] = keep[1]
    elif len(keep) == 1:
        new[0] = keep[0]

    # fill remaining slots avoiding repeat teammates if possible
    for idx in range(4):
        if new[idx] is None:
            candidate = None
            qlen = len(st.session_state.queue)
            for _ in range(qlen):
                p = st.session_state.queue.popleft()
                # teammates to check (other members of the team slots)
                if idx in (0,1):
                    teammates = [x for x in new[0:2] if x is not None]
                else:
                    teammates = [x for x in new[2:4] if x is not None]
                conflict = False
                for tm in teammates:
                    if tm and p in st.session_state.past_teams.get(tm,set()):
                        conflict = True
                        break
                if not conflict:
                    candidate = p
                    break
                else:
                    st.session_state.queue.append(p)
            if candidate is None:
                if st.session_state.queue:
                    candidate = st.session_state.queue.popleft()
            if candidate:
                new[idx] = candidate
                st.session_state.streaks.setdefault(candidate, {"on_court":0,"overall":0})
                st.session_state.streaks[candidate]["on_court"] = 1

    st.session_state.courts[court_id] = new
    # persist
    save_state()

# ---------- export ----------
def history_to_excel_bytes():
    if not st.session_state.history:
        return None
    df = pd.DataFrame(st.session_state.history)
    df["timestamp"] = df["timestamp"].astype(str)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="History")
        # also export current courts and queue
        pd.DataFrame.from_dict(st.session_state.courts, orient="index", columns=["P1","P2","P3","P4"]).to_excel(writer, sheet_name="Courts")
        pd.DataFrame(list(st.session_state.queue), columns=["Queue"]).to_excel(writer, sheet_name="Queue")
    output.seek(0)
    return output.read()

# ---------- UI ----------
st.set_page_config(layout="wide", page_title="Pickleball Open Play")

init()
st.title("Pickleball Open Play (Streamlit)")

# Sidebar config
with st.sidebar:
    st.header("Configuration")
    num_players = st.number_input("Number of players", value=len(st.session_state.players), min_value=4, max_value=200, step=1)
    num_courts = st.number_input("Number of courts", value=len(st.session_state.courts), min_value=1, max_value=10, step=1)
    max_consec = st.number_input("Max consecutive games (winners stay until this)", value=int(st.session_state.config["max_consec_games"]), min_value=1, max_value=10, step=1)
    score_to_win = st.number_input("Score to win", value=int(st.session_state.config["score_to_win"]), min_value=1, step=1)

    if st.button("Apply config"):
        st.session_state.config["num_players"] = int(num_players)
        st.session_state.config["num_courts"] = int(num_courts)
        st.session_state.config["max_consec_games"] = int(max_consec)
        st.session_state.config["score_to_win"] = int(score_to_win)
        # rebuild players if player count changed
        if len(st.session_state.players) != st.session_state.config["num_players"]:
            st.session_state.players = [f"Player {i}" for i in range(1, st.session_state.config["num_players"]+1)]
            st.session_state.active = {p: True for p in st.session_state.players}
        # reinitialize courts and streaks
        st.session_state.courts = {i:[None,None,None,None] for i in range(1, st.session_state.config["num_courts"]+1)}
        st.session_state.streaks = {p:{"on_court":0,"overall":0} for p in st.session_state.players}
        st.session_state.past_teams = {p:set() for p in st.session_state.players}
        initialize_queue_from_players()
        save_state()
        st.success("Configuration applied and state reset/adjusted.")

# Players editor
st.subheader("Players (edit names, toggle Active)")
col1, col2 = st.columns([3,1])
with col1:
    players_text = "\n".join(st.session_state.players)
    new_text = st.text_area("Player names (one per line)", value=players_text, height=200)
with col2:
    st.write("Active toggles")
    new_list = [line.strip() for line in new_text.splitlines() if line.strip()]
    if new_list != st.session_state.players:
        st.session_state.players = new_list
        st.session_state.active = {p: st.session_state.active.get(p, True) for p in st.session_state.players}
    for p in st.session_state.players:
        val = st.selectbox(f"{p} active?", options=["Yes","No"], index=0 if st.session_state.active.get(p,True) else 1, key=f"act_{p}")
        st.session_state.active[p] = (val=="Yes")
    if st.button("Rebuild queue from active players"):
        initialize_queue_from_players()
        save_state()
        st.success("Queue rebuilt from active players.")

# Controls and Queue
left, right = st.columns([2,3])
with left:
    st.subheader("Queue")
    st.write(list(st.session_state.queue))
    if st.button("Initialize queue (active players)"):
        initialize_queue_from_players()
        save_state()
        st.success("Queue initialized from players.")
    if st.button("Assign all courts"):
        assign_all_courts()
        st.experimental_rerun()
    if st.button("Reset everything (queue, courts, history)"):
        # reset state file and session state
        if DATA_FILE.exists():
            DATA_FILE.unlink()
        st.experimental_rerun()
    excel_bytes = history_to_excel_bytes()
    if excel_bytes:
        st.download_button("Download history + state as Excel", data=excel_bytes, file_name=f"pickleball_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")

with right:
    st.subheader("Courts")
    # ensure courts count matches config
    desired = st.session_state.config["num_courts"]
    if desired != len(st.session_state.courts):
        new = {i: st.session_state.courts.get(i, [None,None,None,None]) for i in range(1, desired+1)}
        st.session_state.courts = new
    for cid in sorted(st.session_state.courts.keys()):
        st.markdown(f"### Court {cid}")
        cp = st.session_state.courts[cid]
        st.write("Team 1:", f"{cp[0] or ''}  /  {cp[1] or ''}")
        st.write("Team 2:", f"{cp[2] or ''}  /  {cp[3] or ''}")
        winners_input = st.text_input(f"Winners (comma separated) - court {cid}", key=f"w_input_{cid}")
        colA, colB = st.columns(2)
        with colA:
            if st.button(f"Submit Winner (Court {cid})", key=f"submit_{cid}"):
                winners = [w.strip() for w in winners_input.split(",") if w.strip()]
                if len(winners) != 2:
                    st.error("Enter exactly 2 winners")
                else:
                    process_winner(cid, winners)
                    st.experimental_rerun()
        with colB:
            if st.button(f"Assign Players (Court {cid})", key=f"assign_{cid}"):
                assign_players_to_court(cid)
                st.experimental_rerun()

st.subheader("Recent History")
hist = st.session_state.history[-20:]
if hist:
    df = pd.DataFrame(hist)
    st.dataframe(df)
else:
    st.write("No games yet.")

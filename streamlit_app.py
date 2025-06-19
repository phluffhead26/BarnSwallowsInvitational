import streamlit as st
import requests
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import math
import datetime

# ── Must be first ──
st.set_page_config(page_title="Barnswallow Invitational", layout="wide")

# ── Background & overlay ──
bg_url = "https://i.imgur.com/eBrepb7.png"
st.markdown(f"""
<style>
.stApp {{
  background-image: url('{bg_url}');
  background-size: cover;
  background-repeat: no-repeat;
  background-position: center center;
  background-attachment: fixed;
}}
.stApp::before {{
  content: "";
  background: rgba(255,255,255,0.85);
  position: absolute; top:0; left:0;
  width:100%; height:100%; z-index:0;
}}
main > div {{ position: relative; z-index:1; }}
[data-testid="stDataFrameContainer"], [data-testid="stTable"] {{
  background-color: rgba(255,255,255,0.95) !important;
  border-radius: 8px;
  padding: 8px;
}}
</style>
""", unsafe_allow_html=True)

# ── Alias map (lowercase keys) ──
ALIAS_MAP = {
    # ... your full alias map ...
    "2001": "also sprach zarathustra",
    # etc.
    "yem": "you enjoy myself",
}

# ── API & Google Sheets setup ──
PHISH_NET_BASE = "https://api.phish.net/v5"
PHISH_IN_BASE  = "https://phish.in/api/v2"
PHISH_API_KEY  = st.secrets["PHISHNET_API_KEY"]

creds_info     = st.secrets["GSPREAD_SERVICE_ACCOUNT"]
scope          = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds          = ServiceAccountCredentials.from_json_keyfile_dict(creds_info, scope)
gc             = gspread.authorize(creds)
SPREADSHEET_ID = "13sQpCnwwxJ9KzD2ONtPS4Y2xKPLBVrxwF8E3yxnI0l8"
spreadsheet    = gc.open_by_key(SPREADSHEET_ID)

# ── Ensure Draft worksheet & header ──
HEADER_ROW = ["Player"] + [f"Pick {i}" for i in range(1,13)]
try:
    draft_ws = spreadsheet.worksheet("Draft")
    if draft_ws.row_values(1) != HEADER_ROW:
        draft_ws.clear()
        draft_ws.append_row(HEADER_ROW)
except gspread.exceptions.WorksheetNotFound:
    draft_ws = spreadsheet.add_worksheet("Draft", rows=100, cols=len(HEADER_ROW))
    draft_ws.append_row(HEADER_ROW)

# ── Core helpers ──
@st.cache_data(ttl=3600)
def fetch_catalog():
    resp = requests.get(f"{PHISH_NET_BASE}/songs.json", params={"apikey":PHISH_API_KEY})
    data = resp.json().get("data", [])
    rows = []
    for s in data:
        song = s["song"]
        if song.strip().lower() in ALIAS_MAP:
            continue
        rows.append({
            "Song": song,
            "Times Played": s.get("times_played", s.get("plays",0)),
            "Debut Date": s.get("debut",""),
            "Shows Since Last Played": s.get("gap",""),
            "Last Played": s.get("last_played","")
        })
    return pd.DataFrame(rows).sort_values("Song")

def get_draft_df():
    vals = draft_ws.get_all_values()
    if len(vals) <= 1:
        return pd.DataFrame([], columns=HEADER_ROW)
    return pd.DataFrame(vals[1:], columns=vals[0])

def write_pick(player, song):
    norm = ALIAS_MAP.get(song.strip().lower(), song)
    df = get_draft_df()
    for i, rec in enumerate(df.itertuples(), start=2):
        if rec.Player == player:
            for c in range(2, len(HEADER_ROW)+1):
                if not draft_ws.cell(i, c).value:
                    draft_ws.update_cell(i, c, norm)
                    return True
    return False

# ── Draft order helpers ──
def count_picks():
    arr = get_draft_df().iloc[:,1:].values
    return sum(1 for row in arr for cell in row if isinstance(cell, str) and cell.strip())

def next_pick_player(order, total):
    n   = len(order)
    up  = total + 1
    rnd = math.ceil(up / n)
    pos = (up - 1) % n
    idx = (n - 1 - pos) if rnd % 2 == 0 else pos
    return order[idx], up

order_ws      = spreadsheet.worksheet("Draft Order")
initial_order = pd.DataFrame(order_ws.get_all_records())["Player"].tolist()
if not initial_order:
    st.error("❌ Please populate the Draft Order sheet first.")
    st.stop()

total_picks       = count_picks()
pick_on, pick_num = next_pick_player(initial_order, total_picks)

# ── Scoring via Phish.in v2 ──
def score_show(show_date, return_breakdown=False):
    r = requests.get(f"{PHISH_IN_BASE}/shows/{show_date}")
    if r.status_code != 200:
        st.error(f"No Phish.in data for {show_date}")
        return ({}, {}) if return_breakdown else {}
    payload = r.json()
    tracks  = payload.get("tracks", [])

    seen, info = set(), []
    for t in tracks:
        title = t["title"].strip()
        key   = ALIAS_MAP.get(title.lower(), title).lower()
        if key in seen: 
            continue
        seen.add(key)
        dur_min = t.get("duration", 0) / 1000.0 / 60.0
        is_bust = any(tag.get("name","").lower()=="bustout" for tag in t.get("tags", []))
        info.append((key, dur_min, is_bust))

    pts_map = {}
    for key, dmin, bust in info:
        pts = 4
        if 20 <= dmin < 30:
            pts += 2
        elif 30 <= dmin < 40:
            pts += 3
        if bust:
            pts += 10
        pts_map[key] = pts

    board     = get_draft_df()
    totals    = {p:0 for p in initial_order}
    breakdown = {}
    for _, row in board.iterrows():
        p = row["Player"]
        breakdown[p] = {}
        for pick in row[1:]:
            if isinstance(pick, str) and pick.strip():
                kk  = ALIAS_MAP.get(pick.lower(), pick.lower())
                val = pts_map.get(kk, 0)
                totals[p] += val
                breakdown[p][pick] = val

    return (breakdown, totals) if return_breakdown else totals

def append_scores(date, scores):
    try:
        ws = spreadsheet.worksheet("Scores")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet("Scores", rows=len(initial_order)+10, cols=4)
        ws.append_row(["Show Date","Player","Points","Cumulative"])

    # read existing & build seen set
    rows = ws.get_all_values()[1:]
    seen = set((r[0], r[1]) for r in rows)
    cum  = {r[1]: int(r[3]) for r in rows if len(r)>=4}

    for p in initial_order:
        if (date, p) in seen:
            continue
        pts  = scores.get(p, 0)
        prev = cum.get(p, 0)
        ws.append_row([date, p, pts, prev+pts])

# ── UI Tabs ──
tab1, tab2, tab3 = st.tabs(["🏟️ Draft","🎯 Score a Show","🏆 Standings"])

with tab1:
    st.header("Draft & Catalog")
    st.info(f"⏰ Pick {pick_num} on the clock: **{pick_on}**")
    players = get_draft_df()["Player"].tolist() or initial_order
    player  = st.selectbox("Who are you?", players)
    choice  = st.selectbox("Pick a song:", fetch_catalog()["Song"])
    if st.button("🏷️ Draft this song"):
        ok = write_pick(player, choice)
        st.success("✅ Drafted!") if ok else st.error("❌ No slots left.")
    st.subheader("Current Draft Board")
    st.dataframe(get_draft_df(), use_container_width=True)
    st.subheader("Phish Catalog")
    st.dataframe(fetch_catalog(), use_container_width=True)

with tab2:
    st.header("Score a Show")
    today     = datetime.date.today().isoformat()
    show_date = st.text_input("Show date (YYYY-MM-DD):", today)
    if st.button("🏆 Compute Scores"):
        bd, tot = score_show(show_date, True)
        append_scores(show_date, tot)
        st.subheader("Totals")
        st.table(pd.DataFrame.from_dict(tot, orient="index", columns=["Points"]))
        st.subheader("Pick-by-Pick Breakdown")
        st.dataframe(pd.DataFrame.from_dict(bd, orient="index").fillna(0).astype(int))

with tab3:
    st.header("League Standings")
    try:
        ws_vals = spreadsheet.worksheet("Scores").get_all_values()
        if len(ws_vals) <= 1:
            st.info("No scores recorded yet.")
        else:
            header = ws_vals[0]
            data   = ws_vals[1:]
            df     = pd.DataFrame(data, columns=header)
            df["Points"] = df["Points"].astype(int)

            # remove duplicate (Show Date,Player), keep last entry
            df = df.drop_duplicates(subset=["Show Date","Player"], keep="last")

            pivot = (
                df
                .pivot(index="Player", columns="Show Date", values="Points")
                .fillna(0)
                .astype(int)
            )
            totals = (
                pivot
                .sum(axis=1)
                .sort_values(ascending=False)
                .reset_index()
                .rename(columns={0: "Total Points"})
            )

            st.subheader("Current Standings")
            st.table(totals)
            st.subheader("Show-by-Show Breakdown")
            st.table(pivot)
    except gspread.exceptions.WorksheetNotFound:
        st.info("Score a show to create the sheet.")

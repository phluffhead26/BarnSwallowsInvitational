import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import math
import datetime
import re

# -----------------------------------------------------------------------------
# PAGE CONFIGURATION (must be the first Streamlit command)
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Barnswallow Invitational", layout="wide")

# -----------------------------------------------------------------------------
# STYLING
# -----------------------------------------------------------------------------
# Define different background images for desktop and mobile
desktop_bg_url = "https://i.imgur.com/eBrepb7.png"
mobile_bg_url = "https://i.imgur.com/ZobK8r1.png" # A more vertically-friendly image

# Background image and overlay to improve readability
st.markdown(f"""
<style>
/* Default (Desktop) Background */
.stApp {{
  background-image: url('{desktop_bg_url}');
  background-size: cover;
  background-repeat: no-repeat;
  background-position: center center;
  background-attachment: fixed;
}}

/* Mobile Background - applied only for screens 768px or less */
@media (max-width: 768px) {{
  .stApp {{
    background-image: url('{mobile_bg_url}');
  }}
}}

/* Overlay to make text more readable on the background image */
.stApp::before {{
  content: "";
  background: rgba(255, 255, 255, 0.85);
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
}}
/* Ensure content is layered on top of the overlay */
main > div {{
  position: relative;
  z-index: 1;
}}
/* Style for dataframes to give them a slight background */
[data-testid="stDataFrameContainer"], [data-testid="stTable"] {{
  background-color: rgba(255, 255, 255, 0.95) !important;
  border-radius: 8px;
  padding: 8px;
}}

/* --- STYLES FOR TEXT COLOR --- */

/* Target all headers (h1, h2, h3) */
h1, h2, h3 {{
    color: black !important;
}}

/* Target all regular text and labels */
p, label, .st-emotion-cache-16txtl3, .st-emotion-cache-1jicfl2 {{
    color: black !important;
}}

/* Target the tab labels */
.st-emotion-cache-13qjbs3, .st-emotion-cache-ltfnpr {{
    color: black !important;
}}

/* Target the info box text for 'On the Clock' */
.stAlert p {{
    color: black !important;
}}

</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# CONSTANTS & CONFIGURATION
# -----------------------------------------------------------------------------
PHISH_NET_BASE = "https://api.phish.net/v5"
PHISH_IN_BASE = "https://phish.in/api/v2"
PHISH_API_KEY = st.secrets["PHISHNET_API_KEY"]
SPREADSHEET_ID = "13sQpCnwwxJ9KzD2ONtPS4Y2xKPLBVrxwF8E3yxnI0l8"
TOUR_START_DATE = datetime.date(2025, 6, 19) # Official start date of the tour

# Alias map to normalize song titles (keys should be lowercase)
ALIAS_MAP = {
    "2001": "also sprach zarathustra",
    "yem": "you enjoy myself",
    # Add other aliases here
}

# -----------------------------------------------------------------------------
# GOOGLE SHEETS AUTHENTICATION & SETUP
# -----------------------------------------------------------------------------
@st.cache_resource
def authorize_gspread():
    """Authorizes gspread using Streamlit's secrets."""
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_info = st.secrets["GSPREAD_SERVICE_ACCOUNT"]
    creds = Credentials.from_service_account_info(creds_info, scopes=scope)
    return gspread.authorize(creds)

try:
    gc = authorize_gspread()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
except Exception as e:
    st.error(f"Error connecting to Google Sheets. Please ensure your GSPREAD_SERVICE_ACCOUNT secrets are configured correctly. Details: {e}")
    st.stop()

# -----------------------------------------------------------------------------
# WORKSHEET INITIALIZATION
# -----------------------------------------------------------------------------
HEADER_ROW = ["Player"] + [f"Pick {i}" for i in range(1, 13)]

def get_or_create_worksheet(name, header):
    """Gets a worksheet by name, creating it with a header if it doesn't exist."""
    try:
        ws = spreadsheet.worksheet(name)
        if ws.row_values(1) != header:
             ws.clear()
             ws.append_row(header)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(name, rows=100, cols=len(header))
        ws.append_row(header)
        return ws

draft_ws = get_or_create_worksheet("Draft", HEADER_ROW)

# -----------------------------------------------------------------------------
# CORE HELPER FUNCTIONS
# -----------------------------------------------------------------------------
@st.cache_data(ttl=3600)
def fetch_catalog():
    """Fetches the full song catalog from Phish.net."""
    params = {"apikey": PHISH_API_KEY}
    response = requests.get(f"{PHISH_NET_BASE}/songs.json", params=params)
    response.raise_for_status()
    data = response.json().get("data", [])
    rows = []
    for s in data:
        song = s["song"]
        if song.strip().lower() in ALIAS_MAP:
            continue
        rows.append({
            "Song": song,
            "Times Played": s.get("times_played", s.get("plays", 0)),
            "Debut Date": s.get("debut", ""),
            "Shows Since Last Played": s.get("gap", ""),
            "Last Played": s.get("last_played", "")
        })
    return pd.DataFrame(rows).sort_values("Song")

@st.cache_data(ttl=60) # Cache the draft board for 60 seconds to reduce API calls
def get_draft_df():
    """Fetches the current draft board from the 'Draft' worksheet."""
    vals = draft_ws.get_all_values()
    if len(vals) <= 1:
        return pd.DataFrame([], columns=HEADER_ROW)
    return pd.DataFrame(vals[1:], columns=vals[0])

def write_pick(player, song):
    """Writes a new pick to the draft board for the specified player."""
    normalized_song = ALIAS_MAP.get(song.strip().lower(), song.strip().lower())
    try:
        cell = draft_ws.find(player)
        row_num = cell.row
        row_values = draft_ws.row_values(row_num)
        col_num = len(row_values) + 1
        
        if col_num > len(HEADER_ROW):
             return False # No slots left

        draft_ws.update_cell(row_num, col_num, normalized_song)
        # Clear the cache so the new pick shows up immediately for all users
        get_draft_df.clear()
        return True
    except gspread.exceptions.CellNotFound:
        st.error(f"Player '{player}' not found on the draft board.")
        return False

def append_scores(date, scores):
    """Appends scores for a given date to the 'Scores' worksheet."""
    try:
        ws = spreadsheet.worksheet("Scores")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet("Scores", rows=100, cols=3)
        ws.append_row(["Show Date", "Player", "Points"])

    rows_to_add = []
    for player, points in scores.items():
        rows_to_add.append([date, player, points])
    
    if rows_to_add:
        ws.append_rows(rows_to_add)


# -----------------------------------------------------------------------------
# DRAFT ORDER & SCORING LOGIC
# -----------------------------------------------------------------------------
@st.cache_data(ttl=600) # Cache draft order for 10 minutes
def get_draft_order():
    """Retrieves the official draft order from the 'Draft Order' worksheet."""
    try:
        order_ws = spreadsheet.worksheet("Draft Order")
        records = order_ws.get_all_records()
        if not records or 'Player' not in records[0]:
            st.error("The 'Draft Order' worksheet must have a column with the header 'Player'. Please fix the sheet.")
            st.stop()
        return [row['Player'] for row in records if row.get('Player')]
    except gspread.exceptions.WorksheetNotFound:
        st.error("A 'Draft Order' worksheet is required. Please create one with a 'Player' column in the header.")
        st.stop()
    except KeyError:
        st.error("The 'Draft Order' worksheet must have a column with the header 'Player'.")
        st.stop()


def next_pick_player(order, total_picks):
    """Determines whose turn it is in a snake draft."""
    n = len(order)
    if n == 0: return "N/A", 0
    
    pick_number = total_picks + 1
    round_number = math.ceil(pick_number / n)
    position_in_round = (pick_number - 1) % n
    
    if round_number % 2 == 0: # Even rounds are reversed
        player_index = n - 1 - position_in_round
    else: # Odd rounds are normal order
        player_index = position_in_round
        
    return order[player_index], pick_number

def score_show(show_date, draft_board, return_breakdown=False):
    """Scores a show based on Phish.in data and the current draft board."""
    try:
        r = requests.get(f"{PHISH_IN_BASE}/shows/{show_date}")
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        st.error(f"Could not retrieve data from Phish.in for {show_date}. Error: {e}")
        return ({}, {}) if return_breakdown else {}

    payload = r.json() 

    if not isinstance(payload, dict) or not payload.get("tracks"):
        st.warning(f"No setlist data found on Phish.in for {show_date}. The API data is empty for this date.")
        return ({}, {}) if return_breakdown else {}

    tracks = payload.get("tracks", [])
    
    # --- SCORING LOGIC REBUILT FOR ACCURACY AND DETAIL ---

    # Step 1: Create a list of all possible scoring events from the show's data.
    point_events = []
    songs_played_this_show = set() 
    reprise_counters = {} # To create unique labels for multiple reprises
    for track in tracks:
        # --- Event: Song Play / Reprise ---
        played_title = track["title"].strip()
        played_key = ALIAS_MAP.get(played_title.lower(), played_title.lower())
        
        duration_ms = track.get("duration", 0)
        duration_min = round(duration_ms / 60000)

        if played_key not in songs_played_this_show:
            pts = 4
            if 20 <= duration_min < 30: pts += 2
            elif duration_min >= 30: pts += 3
            label = f"{played_title} ({duration_min} min)"
            point_events.append({'key': played_key, 'points': pts, 'label': label})
            songs_played_this_show.add(played_key)
        else:
            # Subsequent play is a reprise
            reprise_count = reprise_counters.get(played_key, 0) + 1
            reprise_counters[played_key] = reprise_count
            label = f"{played_title} (Reprise #{reprise_count})"
            point_events.append({'key': played_key, 'points': 2, 'label': label})
        
        # --- Event: Tease ---
        for tag in track.get("tags", []):
            if tag.get("name", "").lower() == "tease" and tag.get("notes"):
                tease_note = tag["notes"].strip()
                teased_title = tease_note.split(" by ")[0].strip()
                teased_key = ALIAS_MAP.get(teased_title.lower(), teased_title.lower())
                tease_label = f"{teased_title} (Tease in {played_title})"
                point_events.append({'key': teased_key, 'points': 1, 'label': tease_label})

    # Step 2: Tally points for each player by checking their picks against the events.
    player_totals = {p: 0 for p in draft_board["Player"]}
    player_breakdown = {p: {} for p in draft_board["Player"]}

    for _, row in draft_board.iterrows():
        player_name = row["Player"]
        for pick in row[1:]:
            if isinstance(pick, str) and pick.strip():
                pick_key = ALIAS_MAP.get(pick.lower(), pick.lower())
                
                for event in point_events:
                    if event['key'] == pick_key:
                        player_totals[player_name] += event['points']
                        player_breakdown[player_name][event['label']] = player_breakdown[player_name].get(event['label'], 0) + event['points']

    return (player_breakdown, player_totals) if return_breakdown else player_totals


# --- Initial Data Load ---
initial_order = get_draft_order()
draft_df = get_draft_df()
total_picks = sum(draft_df.iloc[:, 1:].ne("").sum())
pick_on, pick_num = next_pick_player(initial_order, total_picks)

# -----------------------------------------------------------------------------
# STREAMLIT UI
# -----------------------------------------------------------------------------
st.title("Barnswallow Invitational")

tab1, tab2, tab3 = st.tabs(["🏟️ Draft", "🎯 Score a Show", "🏆 Standings"])

with tab1:
    st.header("Draft & Catalog")
    st.info(f"⏰ Pick #{pick_num}: **{pick_on}** is on the clock!")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Make Your Pick")
        players = initial_order
        player = st.selectbox("Who are you?", players, key="draft_player")

        full_catalog_df = fetch_catalog()
        drafted_songs_series = draft_df.iloc[:, 1:].values.flatten()
        drafted_songs_set = {str(song).strip().lower() for song in drafted_songs_series if pd.notna(song) and str(song).strip()}
        
        full_catalog_df['normalized'] = full_catalog_df['Song'].apply(
            lambda s: ALIAS_MAP.get(s.strip().lower(), s.strip().lower())
        )
        available_songs_df = full_catalog_df[~full_catalog_df['normalized'].isin(drafted_songs_set)]
        
        choice = st.selectbox("Pick a song:", available_songs_df["Song"], key="draft_song")

        if st.button("🏷️ Draft This Song"):
            if player == pick_on:
                if write_pick(player, choice):
                    st.success(f"✅ {player} drafted {choice}!")
                    st.rerun()
                else:
                    st.error("❌ You have no open draft slots left.")
            else:
                st.warning(f"It's not your turn! Waiting for {pick_on}.")
    
    st.subheader("Current Draft Board")
    st.dataframe(draft_df, use_container_width=True)
    
    with st.expander("Full Song Catalog"):
        st.dataframe(fetch_catalog(), use_container_width=True)

with tab2:
    st.header("Score a Show")
    today = datetime.date.today()
    first_phish_show = datetime.date(1983, 12, 2)
    
    st.date_input(
        "Select a show date to score",
        value=today,
        min_value=first_phish_show,
        max_value=today,
        key="score_date"
    )

    if st.button("Calculate Scores"):
        show_date = st.session_state.score_date
        date_str = show_date.strftime("%Y-%m-%d")
        
        breakdown, totals = score_show(date_str, draft_df, return_breakdown=True)
        
        # Only append scores if the scoring function returned data
        if totals:
            append_scores(date_str, totals)
            st.subheader(f"Scores for {date_str}")
            scores_df = pd.DataFrame.from_dict(totals, orient='index', columns=['Points'])
            scores_df = scores_df.sort_values('Points', ascending=False)
            st.dataframe(scores_df)

            st.subheader("Scoring Breakdown")
            if not any(v for v in breakdown.values() if v):
                st.write("No drafted songs were played or teased in this show.")
            else:
                for player, songs in breakdown.items():
                    if songs:
                        st.write(f"**{player}**")
                        for song_label, points in songs.items():
                            st.write(f"- {song_label}: {points} pts")


with tab3:
    st.header("🏆 Overall Standings")
    
    try:
        scores_ws = spreadsheet.worksheet("Scores")
        records = scores_ws.get_all_records()
        
        if not records or len(records) <= 1:
            st.info("No shows have been scored yet.")
        else:
            scores_df = pd.DataFrame(records[1:], columns=records[0])
            scores_df['Points'] = pd.to_numeric(scores_df['Points'])
            scores_df['Show Date'] = pd.to_datetime(scores_df['Show Date']).dt.date
            
            tour_scores_df = scores_df[scores_df['Show Date'] >= TOUR_START_DATE].copy()

            if tour_scores_df.empty:
                st.info(f"No official tour shows have been scored yet (since {TOUR_START_DATE.strftime('%Y-%m-%d')}).")
            else:
                standings = tour_scores_df.groupby('Player')['Points'].sum().sort_values(ascending=False).reset_index()
                standings.index = standings.index + 1
                
                st.write(f"Standings for all shows since {TOUR_START_DATE.strftime('%Y-%m-%d')}")
                st.dataframe(standings, use_container_width=True)

    except gspread.exceptions.WorksheetNotFound:
        st.info("The 'Scores' worksheet has not been created yet. Score a show to begin.")
    except Exception as e:
        st.error(f"An error occurred while calculating standings: {e}")

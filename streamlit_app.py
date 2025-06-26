import streamlit as st
import requests
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import math
import datetime
import re
import random

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
@media only screen and (max-width: 768px) {{
  .stApp {{
    background-image: url('{mobile_bg_url}') !important;
    /* 'fixed' attachment can be buggy on mobile, so we override it */
    background-attachment: scroll !important; 
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
            "Last Played": s.get("last_played", ""),
            "Artist": s.get("artist") # Fetch artist to identify originals
        })
    # Ensure 'Shows Since Last Played' is numeric for calculations
    df = pd.DataFrame(rows)
    df['Shows Since Last Played'] = pd.to_numeric(df['Shows Since Last Played'], errors='coerce').fillna(0)
    return df.sort_values("Song")

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

def append_scores(date_str, scores, status_placeholder):
    """Appends scores for a given date, replacing old scores if they exist."""
    try:
        ws = spreadsheet.worksheet("Scores")
    except gspread.exceptions.WorksheetNotFound:
        ws = spreadsheet.add_worksheet("Scores", rows=100, cols=3)
        ws.append_row(["Show Date", "Player", "Points"])

    # Check if scores for this date already exist
    existing_cells = ws.findall(date_str, in_column=1)
    if existing_cells:
        status_placeholder.info(f"Updating existing scores for {date_str}...")
        # Get row numbers to delete
        rows_to_delete = [cell.row for cell in existing_cells]
        # Delete rows in reverse order to avoid shifting indices
        for row_num in sorted(rows_to_delete, reverse=True):
            ws.delete_rows(row_num)

    # Append the new scores
    rows_to_add = []
    for player, points in scores.items():
        rows_to_add.append([date_str, player, points])
    
    if rows_to_add:
        ws.append_rows(rows_to_add, value_input_option='USER_ENTERED')
        status_placeholder.success(f"Scores for {date_str} have been successfully recorded!")


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
        return ({}, {}, {}) if return_breakdown else {}

    payload = r.json() 

    if not isinstance(payload, dict) or not payload.get("tracks"):
        return ({}, {}, {}) if return_breakdown else {}

    tracks = payload.get("tracks", [])
    
    draft_map = {}
    for _, row in draft_board.iterrows():
        player_name = row["Player"]
        for pick in row[1:]:
            if isinstance(pick, str) and pick.strip():
                pick_key = ALIAS_MAP.get(pick.lower(), pick.lower())
                if pick_key not in draft_map:
                    draft_map[pick_key] = []
                draft_map[pick_key].append(player_name)

    player_totals = {p: 0 for p in draft_board["Player"]}
    setlist_breakdown = {}
    songs_played_this_show = set()
    reprise_counters = {}

    for track in tracks:
        set_name = track.get("set_name", "Unknown Set")
        if set_name not in setlist_breakdown:
            setlist_breakdown[set_name] = []
        
        played_title = track["title"].strip()
        played_key = ALIAS_MAP.get(played_title.lower(), played_title.lower())
        duration_min = round(track.get("duration", 0) / 60000)
        
        track_info = {'title': played_title, 'duration_min': duration_min, 'events': []}

        if played_key not in songs_played_this_show:
            pts = 4
            if played_key in draft_map:
                for player in draft_map[played_key]:
                    player_totals[player] += pts
                    track_info['events'].append({'player': player, 'reason': 'Song Played', 'points': pts})
            songs_played_this_show.add(played_key)
            if 20 <= duration_min < 30:
                pts_bonus = 2
                if played_key in draft_map:
                    for player in draft_map[played_key]:
                        player_totals[player] += pts_bonus
                        track_info['events'].append({'player': player, 'reason': f'Duration Bonus ({duration_min} min)', 'points': pts_bonus})
            elif duration_min >= 30:
                pts_bonus = 3
                if played_key in draft_map:
                    for player in draft_map[played_key]:
                        player_totals[player] += pts_bonus
                        track_info['events'].append({'player': player, 'reason': f'Duration Bonus ({duration_min} min)', 'points': pts_bonus})
        else:
            reprise_count = reprise_counters.get(played_key, 0) + 1
            reprise_counters[played_key] = reprise_count
            pts_reprise = 2
            if played_key in draft_map:
                 for player in draft_map[played_key]:
                    player_totals[player] += pts_reprise
                    track_info['events'].append({'player': player, 'reason': f'Reprise #{reprise_count}', 'points': pts_reprise})

        for tag in track.get("tags", []):
            tag_name = tag.get("name", "").lower()
            if tag_name == "tease" and tag.get("notes"):
                tease_note = tag["notes"].strip()
                teased_title = tease_note.split(" by ")[0].strip()
                teased_key = ALIAS_MAP.get(teased_title.lower(), teased_title.lower())
                if teased_key in draft_map:
                    for player in draft_map[teased_key]:
                        player_totals[player] += 1
                        track_info['events'].append({'player': player, 'reason': f'Tease of {teased_title}', 'points': 1})
            if tag_name == "bustout":
                pts_bustout = 10
                if played_key in draft_map:
                    for player in draft_map[played_key]:
                        player_totals[player] += pts_bustout
                        track_info['events'].append({'player': player, 'reason': 'Bust Out!', 'points': 10})
        
        setlist_breakdown[set_name].append(track_info)
        
    player_breakdown = {player: {'Total Points': total} for player, total in player_totals.items() if total > 0}
        
    return (player_breakdown, player_totals, setlist_breakdown) if return_breakdown else ({}, {}, {})


# --- POWER RANKINGS & PREDICTION FUNCTIONS (REVISED) ---

def generate_narrative(rank, player, data):
    """Generates a dynamic narrative for a player's power ranking."""
    
    openers = [
        f"Sitting at #{rank}, **{player}** is looking like a strong contender.",
        f"Coming in at number {rank}, **{player}** has built a solid foundation.",
        f"At rank #{rank}, **{player}** is a team to watch closely.",
    ]
    
    middles = {
        "high_score": f"Their current score of {data['Current Score']} is impressive, showing their picks have paid off early.",
        "low_score": f"While their current score of {data['Current Score']} is modest, their true strength lies in what's to come.",
        "balanced": f"With a healthy score of {data['Current Score']} and significant potential, they are well-balanced for the long haul."
    }
    
    closers = {
        "has_bustouts": "The real excitement comes from their high-risk, high-reward picks like **{bustout_song}**, making them a threat for massive point swings.",
        "no_bustouts": "Their strategy of picking reliable, frequently played songs could provide a steady stream of points throughout the tour.",
    }

    narrative = random.choice(openers) + " "

    if data['Current Score'] > 50:
        narrative += middles['high_score']
    elif data['Current Score'] < 20:
        narrative += middles['low_score']
    else:
        narrative += middles['balanced']
        
    narrative += " "

    if data["Bustout Candidates"]:
        bustout_song = random.choice(data['Bustout Candidates'])
        narrative += closers['has_bustouts'].format(bustout_song=bustout_song)
    else:
        narrative += closers['no_bustouts']
        
    return narrative

def calculate_power_rankings(draft_df, catalog_df, standings_df):
    """Calculates power rankings and generates a narrative explanation."""
    
    player_data = {}

    for _, row in draft_df.iterrows():
        player = row["Player"]
        total_gap = 0
        unplayed_count = 0
        bustout_picks = []
        
        for pick in row[1:]:
            if isinstance(pick, str) and pick.strip():
                song_info = catalog_df[catalog_df["Song"] == pick]
                if not song_info.empty:
                    gap = song_info.iloc[0]["Shows Since Last Played"]
                    total_gap += gap
                    unplayed_count += 1
                    if gap > 100:
                        bustout_picks.append(f"{pick}")
        
        avg_gap = total_gap / unplayed_count if unplayed_count > 0 else 0
        current_score = standings_df[standings_df["Player"] == player]["Points"].sum()
        power_score = current_score + (avg_gap * 0.1) 
        
        player_data[player] = {
            "Power Score": round(power_score, 2),
            "Bustout Candidates": bustout_picks,
            "Current Score": current_score,
            "Average Gap": avg_gap
        }

    ranked_players = sorted(player_data.items(), key=lambda item: item[1]["Power Score"], reverse=True)
    
    for i, (player, data) in enumerate(ranked_players):
        rank = i + 1
        data['Narrative'] = generate_narrative(rank, player, data)

    return pd.DataFrame([data for _, data in player_data.items()], index=player_data.keys()).sort_values("Power Score", ascending=False)


def predict_setlist(catalog_df):
    """Generates a speculative setlist prediction for the next show."""
    # CORRECTED: Filter for Phish originals only
    phish_originals = catalog_df[catalog_df['Artist'].isnull() | (catalog_df['Artist'] == 'Phish')].copy()
    
    if phish_originals.empty:
        return {"Error": ["Could not fetch Phish original songs for prediction."]}

    likely_candidates = phish_originals[phish_originals["Shows Since Last Played"] > 10].copy()
    
    # Get common jam vehicles and openers
    jam_vehicles = ["Tweezer", "Carini", "Chalk Dust Torture", "Simple", "Down with Disease"]
    openers = ["AC/DC Bag", "Buried Alive", "The Moma Dance", "Free", "First Tube"]

    # Build the prediction
    set1 = []
    set2 = []
    encore = []

    # Pick a random opener
    set1.append(random.choice(openers))

    # Fill Set 1
    if not likely_candidates.empty:
        set1.extend(likely_candidates.nlargest(6, "Shows Since Last Played")["Song"].tolist())
    
    # Fill Set 2 with a jam vehicle
    set2.append(random.choice(jam_vehicles))
    if not likely_candidates.empty:
        set2.extend(likely_candidates.nlargest(10, "Shows Since Last Played").tail(4)["Song"].tolist())
    
    # Pick an encore
    if not likely_candidates.empty:
        encore.extend(likely_candidates.nlargest(15, "Shows Since Last Played").tail(2)["Song"].tolist())
    
    prediction = {"Set 1": set1, "Set 2": set2, "Encore": encore}
    return prediction


# --- Initial Data Load ---
initial_order = get_draft_order()
draft_df = get_draft_df()
full_catalog = fetch_catalog()
total_picks = sum(draft_df.iloc[:, 1:].ne("").sum())
pick_on, pick_num = next_pick_player(initial_order, total_picks)

# -----------------------------------------------------------------------------
# STREAMLIT UI
# -----------------------------------------------------------------------------
st.title("Barnswallow Invitational")

# NEW TAB ORDER
tab1, tab2, tab3, tab4 = st.tabs(["🏆 Standings", "⚡️ Power Rankings", "🏟️ Draft", "🎯 Score a Show"])

with tab1: # STANDINGS TAB
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
                
                st.dataframe(standings, use_container_width=True)

                st.divider()
                st.header("Most Recent Show Breakdown")
                
                latest_date = tour_scores_df['Show Date'].max()
                latest_date_str = latest_date.strftime('%Y-%m-%d')
                st.subheader(f"Show Date: {latest_date_str}")
                
                _, _, setlist_data = score_show(latest_date_str, draft_df, return_breakdown=True)

                for set_name, tracks_in_set in setlist_data.items():
                    with st.expander(f"**{set_name}**"):
                        for track in tracks_in_set:
                            st.markdown(f"**{track['title']} ({track['duration_min']} min)**")
                            if track['events']:
                                for event in track['events']:
                                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ **{event['player']}**: {event['reason']} **(+{event['points']})**")
                            else:
                                st.markdown("&nbsp;&nbsp;&nbsp;&nbsp;↳ _No points scored_")

    except gspread.exceptions.WorksheetNotFound:
        st.info("The 'Scores' worksheet has not been created yet. Score a show to begin.")
    except Exception as e:
        st.error(f"An error occurred while calculating standings: {e}")

with tab2: # POWER RANKINGS TAB
    st.header("⚡️ Power Rankings")
    with st.expander("How are Power Rankings Calculated?"):
        st.markdown("""
        The Power Score is a blend of past performance and future potential. It's calculated using the following formula:
        
        `Power Score = (Current Total Points) + (Average Song Gap * 0.1)`
        
        A higher "Average Song Gap" means a player has drafted more songs that haven't been played in a long time, giving them greater "bust-out potential" for future shows.
        """)

    try:
        scores_ws = spreadsheet.worksheet("Scores")
        records = scores_ws.get_all_records()
        if not records or len(records) <= 1:
            st.info("Score at least one show to generate Power Rankings.")
        else:
            scores_df = pd.DataFrame(records[1:], columns=records[0])
            scores_df['Points'] = pd.to_numeric(scores_df['Points'])
            standings_for_power = scores_df.groupby('Player')['Points'].sum().reset_index()
            
            power_rankings_df = calculate_power_rankings(draft_df, full_catalog, standings_for_power)
            
            st.subheader("Top 5 Power Rankings")
            st.dataframe(power_rankings_df[['Power Score']].head(5)) # Display the table
            st.divider()

            for index, row in power_rankings_df.head(5).iterrows():
                st.markdown(row["Narrative"])
                st.caption(f"Power Score: {row['Power Score']}")
                st.write("---")
            
            st.divider()
            with st.expander("🔮 Next Show Prediction (For Fun!)"):
                prediction = predict_setlist(full_catalog)
                for set_name, songs in prediction.items():
                    st.subheader(set_name)
                    for song in songs:
                        st.markdown(f"- {song} (~{random.randint(5,15)} min)")
    except gspread.exceptions.WorksheetNotFound:
        st.info("Score at least one show to generate Power Rankings.")
    except Exception as e:
        st.error(f"An error occurred while generating power rankings: {e}")

with tab3: # DRAFT TAB
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

with tab4: # SCORE A SHOW TAB
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
    
    status_placeholder = st.empty()

    if st.button("Calculate Scores"):
        show_date = st.session_state.score_date
        date_str = show_date.strftime("%Y-%m-%d")
        
        breakdown, totals, _ = score_show(date_str, draft_df, return_breakdown=True)
        
        if totals:
            append_scores(date_str, totals, status_placeholder)
            
            st.subheader(f"Scores for {date_str}")
            scores_df = pd.DataFrame.from_dict(totals, orient='index', columns=['Points'])
            scores_df = scores_df.sort_values('Points', ascending=False)
            st.dataframe(scores_df)

            st.subheader("Player Scoring Breakdown")
            if not any(v for v in breakdown.values() if v):
                st.write("No drafted songs were played or teased in this show.")
            else:
                for player, songs in breakdown.items():
                    if songs:
                        st.write(f"**{player}**")
                        for song_label, points in songs.items():
                            st.write(f"- {song_label}: {points} pts")

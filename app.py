import datetime
import json
import os
import uuid
import requests
import pandas as pd
import streamlit as st

# ==================== CONFIGURATION & USERS ====================
# NOTE: Set your JSONBin credentials in environment variables or Streamlit secrets!
BIN_ID = os.getenv("JSONBIN_ID", "6a70bea2da38895dfeb46969")
API_KEY = os.getenv("JSONBIN_API_KEY", "")  # Put your API key here if not using env vars
BASE_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
CACHE_FILE = os.path.expanduser("~/.paas_joint_cache.json")

USERS = {
    "Taki Yasir": {"pin": "0782", "role": "Primary Member", "avatar": "👑"},
    "Mahir Mannan": {"pin": "9031", "role": "Partner Member", "avatar": "⚡"}
}

CATEGORIES = ["Food", "Bills & Utilities", "Entertainment", "Shopping", "Transport", "Investments", "Other"]

st.set_page_config(
    page_title="PAAS — Joint Accounting System",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ==================== CUSTOM UI STYLING ====================
st.markdown("""
<style>
    div[data-testid="stMetric"] {
        background: rgba(255, 255, 255, 0.05);
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 15px 20px;
        border-radius: 12px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
    }
    button[data-baseweb="tab"] {
        font-weight: 600;
        font-size: 1rem;
    }
    hr {
        margin: 1.5em 0;
        opacity: 0.2;
    }
</style>
""", unsafe_allow_html=True)

# ==================== DATA SYNCHRONIZATION ====================

def get_default_structure():
    return {
        "expenses": [],
        "wishlist": [
            {"id": "init-1", "item": "Camping Tent", "price": 120.0, "added_by": "Taki Yasir", "date": str(datetime.date.today())},
            {"id": "init-2", "item": "Portable Charger", "price": 45.0, "added_by": "Mahir Mannan", "date": str(datetime.date.today())}
        ],
        "extra_income": [],
        "activity_log": [],
        "savings_goal": {"name": "Emergency Fund", "target": 50000.0}
    }

def read_local_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return get_default_structure()
    return get_default_structure()

def write_local_cache(data):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        st.sidebar.warning(f"Local save warning: {e}")

def deduplicate_list(items):
    seen = set()
    unique_items = []
    for item in items:
        sig = item.get("id") or tuple(sorted((k, str(v)) for k, v in item.items()))
        if sig not in seen:
            seen.add(sig)
            unique_items.append(item)
    return unique_items

def sync_data():
    """Fetches authoritative cloud data without resurrecting deleted items."""
    local_data = read_local_cache()
    if not API_KEY:
        return local_data

    headers = {
        "Content-Type": "application/json",
        "X-Master-Key": API_KEY
    }
    
    try:
        response = requests.get(f"{BASE_URL}/latest", headers=headers, timeout=4)
        if response.status_code == 200:
            cloud_data = response.json().get("record", get_default_structure())
            for key in ["expenses", "wishlist", "extra_income", "activity_log"]:
                cloud_data.setdefault(key, [])
            cloud_data.setdefault("savings_goal", {"name": "Emergency Fund", "target": 50000.0})
            
            # Use cloud_data as the authoritative source of truth
            write_local_cache(cloud_data)
            return cloud_data
        return local_data
    except Exception:
        return local_data

def save_and_sync(data):
    """Saves locally, updates Streamlit session state, and pushes to Cloud immediately."""
    st.session_state.paas_data = data
    write_local_cache(data)
    if API_KEY:
        try:
            headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}
            response = requests.put(BASE_URL, json=data, headers=headers, timeout=5)
            if response.status_code not in (200, 201):
                st.sidebar.error(f"Cloud sync failed (Status {response.status_code}).")
        except Exception as e:
            st.sidebar.error(f"Cloud network warning: {e}")

def log_activity(data, action_text, user):
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "user": user,
        "action": action_text
    }
    data.setdefault("activity_log", []).insert(0, entry)

# ==================== FINANCIAL CALCULATIONS ====================

def calculate_earnings_until(target_date, start_day=6):
    today = datetime.date.today()
    start_date = datetime.date(today.year, today.month, start_day)
    if target_date < start_date:
        return 0

    total_earned = 0
    current = start_date
    while current <= target_date:
        weekday = current.weekday()
        if weekday == 5:      # Saturday
            daily = 0
        elif weekday == 4:    # Friday
            daily = 1500
        else:                 # Sunday - Thursday
            daily = 500
        total_earned += daily
        current += datetime.timedelta(days=1)
    return total_earned

def get_current_balance(data):
    today = datetime.date.today()
    scheduled_earned = calculate_earnings_until(today)
    extra_earned = sum(item.get("amount", 0) for item in data.get("extra_income", []))
    spent_total = sum(item.get("amount", 0) for item in data.get("expenses", []))
    available = (scheduled_earned + extra_earned) - spent_total

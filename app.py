import datetime
import json
import os
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import streamlit as st

# ==================== STREAMLIT INITIALIZATION ====================
# Must be called before any other Streamlit UI commands
st.set_page_config(
    page_title="PAAS — Joint Accounting System",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==================== CONFIGURATION & CONSTANTS ====================
def _get_secret(key: str, default: str = "") -> str:
    """Safely fetch secrets from environment variables or Streamlit secrets."""
    value = os.getenv(key)
    if value:
        return value
    try:
        return str(st.secrets.get(key, default))
    except Exception:
        return default


BIN_ID: str = _get_secret("JSONBIN_ID", "6a70bea2da38895dfeb46969")
API_KEY: str = _get_secret("JSONBIN_API_KEY", "")
BASE_URL: str = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
CACHE_FILE: Path = Path.home() / ".paas_joint_cache.json"

USERS: dict[str, dict[str, str]] = {
    "Taki Yasir": {"pin": "0782", "role": "Primary Member", "avatar": "👑"},
    "Mahir Mannan": {"pin": "9031", "role": "Partner Member", "avatar": "⚡"},
}

CATEGORIES: list[str] = [
    "Food",
    "Bills & Utilities",
    "Entertainment",
    "Shopping",
    "Transport",
    "Investments",
    "Other",
]

# ==================== CUSTOM UI STYLING ====================
st.markdown(
    """
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
    """,
    unsafe_allow_html=True,
)


# ==================== DATA SYNCHRONIZATION ====================
def get_default_structure() -> dict[str, Any]:
    """Returns the default data schema for the application."""
    today_str = str(datetime.date.today())
    return {
        "expenses": [],
        "wishlist": [
            {
                "id": "init-1",
                "item": "Camping Tent",
                "price": 120.0,
                "added_by": "Taki Yasir",
                "date": today_str,
            },
            {
                "id": "init-2",
                "item": "Portable Charger",
                "price": 45.0,
                "added_by": "Mahir Mannan",
                "date": today_str,
            },
        ],
        "extra_income": [],
        "activity_log": [],
        "savings_goal": {"name": "Emergency Fund", "target": 50000.0},
    }


def read_local_cache() -> dict[str, Any]:
    """Reads the local JSON cache file, falling back to default structure on failure."""
    if not CACHE_FILE.exists():
        return get_default_structure()

    try:
        with CACHE_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
            return isinstance(data, dict) and data or get_default_structure()
    except (json.JSONDecodeError, OSError):
        return get_default_structure()


def write_local_cache(data: dict[str, Any]) -> None:
    """Safely writes the data dictionary to the local JSON cache."""
    try:
        with CACHE_FILE.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except OSError as e:
        st.sidebar.warning(f"Local cache write warning: {e}")


def deduplicate_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Removes duplicate dictionaries based on their 'id' or full value signature."""
    seen = set()
    unique_items = []
    for item in items:
        # Use ID if available, otherwise hash sorted key-value pairs
        sig = item.get("id") or tuple(sorted((k, str(v)) for k, v in item.items()))
        if sig not in seen:
            seen.add(sig)
            unique_items.append(item)
    return unique_items


def sync_data() -> dict[str, Any]:
    """
    Fetches authoritative cloud data from JSONBin without resurrecting deleted items.
    Falls back to local cache if network errors occur or API key is missing.
    """
    local_data = read_local_cache()
    if not API_KEY:
        return local_data

    headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}

    try:
        response = requests.get(
            f"{BASE_URL}/latest", headers=headers, timeout=4.0
        )
        if response.status_code == 200:
            cloud_data = response.json().get("record", {})
            if not isinstance(cloud_data, dict):
                return local_data

            # Guarantee required schema keys exist
            for key in ["expenses", "wishlist", "extra_income", "activity_log"]:
                cloud_data.setdefault(key, [])
            cloud_data.setdefault(
                "savings_goal", {"name": "Emergency Fund", "target": 50000.0}
            )

            write_local_cache(cloud_data)
            return cloud_data

        st.sidebar.warning(f"Cloud sync returned status {response.status_code}. Using local cache.")
        return local_data
    except requests.RequestException:
        return local_data


def save_and_sync(data: dict[str, Any]) -> None:
    """Saves data locally, updates session state, and pushes to cloud immediately."""
    st.session_state.paas_data = data
    write_local_cache(data)

    if not API_KEY:
        return

    headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}
    try:
        response = requests.put(BASE_URL, json=data, headers=headers, timeout=5.0)
        if response.status_code not in (200, 201):
            st.sidebar.error(f"Cloud sync failed (Status {response.status_code}).")
    except requests.RequestException as e:
        st.sidebar.error(f"Cloud network warning: {e}")


def log_activity(data: dict[str, Any], action_text: str, user: str) -> None:
    """Prepends a new activity log entry to the dataset."""
    entry = {
        "id": uuid.uuid4().hex[:8],
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "user": user,
        "action": action_text,
    }
    data.setdefault("activity_log", []).insert(0, entry)


# ==================== FINANCIAL CALCULATIONS ====================
def calculate_earnings_until(
    target_date: datetime.date, start_day: int = 6
) -> int:
    """
    Calculates scheduled daily earnings from the 'start_day' of the current month
    up to the target_date.
    
    Earnings Schedule:
    - Friday (Weekday 4): 1500
    - Saturday (Weekday 5): 0
    - Sun-Thu (Weekdays 0,1,2,3,6): 500
    """
    today = datetime.date.today()
    try:
        start_date = datetime.date(today.year, today.month, start_day)
    except ValueError:
        # Handles invalid day numbers gracefully by capping to month end
        start_date = datetime.date(today.year, today.month, 1)

    if target_date < start_date:
        return 0

    daily_rates = {
        4: 1500,  # Friday
        5: 0,     # Saturday
    }
    default_rate = 500  # Sunday through Thursday

    total_earned = 0
    current = start_date
    while current <= target_date:
        total_earned += daily_rates.get(current.weekday(), default_rate)
        current += datetime.timedelta(days=1)

    return total_earned


def get_current_balance(data: dict[str, Any]) -> float:
    """Computes the net available balance from scheduled earnings, extra income, and expenses."""
    today = datetime.date.today()
    scheduled_earned = float(calculate_earnings_until(today))
    
    extra_earned = sum(
        float(item.get("amount") or 0.0)
        for item in data.get("extra_income", [])
    )
    spent_total = sum(
        float(item.get("amount") or 0.0)
        for item in data.get("expenses", [])
    )
    
    return (scheduled_earned + extra_earned) - spent_total

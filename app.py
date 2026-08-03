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

            # Guarantee required schema keys exist and deduplicate lists
            for key in ["expenses", "wishlist", "extra_income", "activity_log"]:
                cloud_data.setdefault(key, [])
                cloud_data[key] = deduplicate_list(cloud_data[key])
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
        float(item.get("amount", 0.0))
        for item in data.get("extra_income", [])
    )
    spent_total = sum(
        float(item.get("amount", 0.0))
        for item in data.get("expenses", [])
    )
    
    return (scheduled_earned + extra_earned) - spent_total


# ==================== STATE INITIALIZATION ====================
if "paas_data" not in st.session_state:
    st.session_state.paas_data = sync_data()

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None

data = st.session_state.paas_data


# ==================== SIDEBAR AUTHENTICATION & CONTROLS ====================
with st.sidebar:
    st.title("🏠 PAAS Controls")
    
    st.subheader("Account Login")
    selected_user = st.selectbox("Select Member", list(USERS.keys()))
    pin_input = st.text_input("Enter PIN", type="password", max_chars=4)
    
    if st.button("Authenticate", use_container_width=True):
        if pin_input == USERS[selected_user]["pin"]:
            st.session_state.authenticated_user = selected_user
            st.success(f"Logged in as {selected_user}")
        else:
            st.error("Invalid PIN")

    current_user = st.session_state.authenticated_user
    if current_user:
        user_info = USERS[current_user]
        st.info(f"**Active:** {user_info['avatar']} {current_user} ({user_info['role']})")
        if st.button("Log Out", use_container_width=True):
            st.session_state.authenticated_user = None
            st.rerun()
    else:
        st.warning("Please log in to add or modify records.")

    st.divider()
    if st.button("🔄 Force Cloud Sync", use_container_width=True):
        st.session_state.paas_data = sync_data()
        st.success("Synced with cloud!")
        st.rerun()


# ==================== MAIN APPLICATION UI ====================
st.title("PAAS — Joint Accounting System")
st.caption("Manage shared expenses, track savings goals, and monitor joint cash flow.")

# Metric Scorecard
total_balance = get_current_balance(data)
total_spent = sum(float(item.get("amount", 0.0)) for item in data.get("expenses", []))
total_extra_income = sum(float(item.get("amount", 0.0)) for item in data.get("extra_income", []))
savings_target = float(data.get("savings_goal", {}).get("target", 50000.0))

col1, col2, col3, col4 = st.columns(4)
col1.metric("Available Balance", f"৳{total_balance:,.2f}")
col2.metric("Total Spent", f"৳{total_spent:,.2f}")
col3.metric("Extra Income", f"৳{total_extra_income:,.2f}")
col4.metric("Savings Target", f"৳{savings_target:,.2f}")

st.divider()

# Navigation Tabs
tab_dashboard, tab_wishlist, tab_income, tab_activity = st.tabs([
    "📊 Dashboard & Expenses",
    "🎁 Wishlist & Savings",
    "💵 Income & Earnings",
    "📜 Activity Log",
])


# -------------------- TAB 1: DASHBOARD & EXPENSES --------------------
with tab_dashboard:
    st.subheader("Log New Expense")
    with st.form("expense_form", clear_on_submit=True):
        exp_col1, exp_col2, exp_col3 = st.columns([2, 1, 1])
        title = exp_col1.text_input("Expense Title", placeholder="e.g., Grocery run")
        amount = exp_col2.number_input("Amount (৳)", min_value=0.0, step=10.0)
        category = exp_col3.selectbox("Category", CATEGORIES)
        
        submitted = st.form_submit_button("Add Expense", use_container_width=True)
        if submitted:
            if not current_user:
                st.error("You must log in from the sidebar to record expenses.")
            elif not title or amount <= 0:
                st.warning("Please enter a valid title and amount.")
            else:
                new_expense = {
                    "id": uuid.uuid4().hex[:8],
                    "title": title,
                    "amount": float(amount),
                    "category": category,
                    "added_by": current_user,
                    "date": str(datetime.date.today()),
                }
                data.setdefault("expenses", []).append(new_expense)
                log_activity(data, f"Added expense '{title}' (৳{amount:.2f})", current_user)
                save_and_sync(data)
                st.success("Expense logged successfully!")
                st.rerun()

    st.subheader("Expense History")
    expenses = data.get("expenses", [])
    if expenses:
        # Using reindex guarantees columns exist even if JSONBin contains legacy data
        df_expenses = pd.DataFrame(expenses).reindex(
            columns=["date", "title", "category", "amount", "added_by"],
            fill_value="-"
        )
        st.dataframe(df_expenses, use_container_width=True, hide_index=True)
    else:
        st.info("No expenses recorded yet.")


# -------------------- TAB 2: WISHLIST & SAVINGS --------------------
with tab_wishlist:
    st.subheader("Savings Goal Progress")
    goal_name = data.get("savings_goal", {}).get("name", "Emergency Fund")
    progress = max(0.0, min(1.0, total_balance / savings_target)) if savings_target > 0 else 0.0
    st.write(f"**{goal_name}** — Progress towards **৳{savings_target:,.2f}**")
    st.progress(progress)

    st.divider()
    st.subheader("Joint Wishlist")
    
    with st.form("wishlist_form", clear_on_submit=True):
        w_col1, w_col2 = st.columns([3, 1])
        item_name = w_col1.text_input("New Item Name", placeholder="e.g., New Router")
        item_price = w_col2.number_input("Estimated Price (৳)", min_value=0.0, step=50.0)
        
        w_submit = st.form_submit_button("Add to Wishlist", use_container_width=True)
        if w_submit:
            if not current_user:
                st.error("Please log in to add items to the wishlist.")
            elif not item_name or item_price <= 0:
                st.warning("Please enter a valid item name and price.")
            else:
                new_item = {
                    "id": uuid.uuid4().hex[:8],
                    "item": item_name,
                    "price": float(item_price),
                    "added_by": current_user,
                    "date": str(datetime.date.today()),
                }
                data.setdefault("wishlist", []).append(new_item)
                log_activity(data, f"Added wishlist item '{item_name}' (৳{item_price:.2f})", current_user)
                save_and_sync(data)
                st.success("Wishlist updated!")
                st.rerun()

    wishlist_items = data.get("wishlist", [])
    if wishlist_items:
        for idx, item in enumerate(wishlist_items):
            with st.container():
                wc1, wc2, wc3 = st.columns([3, 1, 1])
                wc1.write(f"**{item.get('item')}** (Added by {item.get('added_by', '-')})")
                wc2.write(f"**৳{float(item.get('price', 0)):,.2f}**")
                if wc3.button("Remove", key=f"del_wish_{item.get('id', idx)}"):
                    if not current_user:
                        st.error("Login required.")
                    else:
                        removed = data["wishlist"].pop(idx)
                        log_activity(data, f"Removed wishlist item '{removed.get('item')}'", current_user)
                        save_and_sync(data)
                        st.rerun()
    else:
        st.info("Your wishlist is currently empty.")


# -------------------- TAB 3: INCOME & EARNINGS --------------------
with tab_income:
    st.subheader("Scheduled Earnings Calculator")
    today_date = datetime.date.today()
    scheduled_total = calculate_earnings_until(today_date)
    st.write(
        f"Estimated regular earnings accrued from the start of the cycle to today ({today_date.strftime('%B %d, %Y')}): "
        f"**৳{scheduled_total:,.2f}**"
    )

    st.divider()
    st.subheader("Log Additional Income")
    with st.form("income_form", clear_on_submit=True):
        inc_col1, inc_col2 = st.columns([3, 1])
        source = inc_col1.text_input("Income Source", placeholder="e.g., Freelance Project")
        inc_amount = inc_col2.number_input("Amount (৳)", min_value=0.0, step=100.0)
        
        inc_submit = st.form_submit_button("Record Income", use_container_width=True)
        if inc_submit:
            if not current_user:
                st.error("You must log in to record additional income.")
            elif not source or inc_amount <= 0:
                st.warning("Please provide a valid source and amount.")
            else:
                new_income = {
                    "id": uuid.uuid4().hex[:8],
                    "source": source,
                    "amount": float(inc_amount),
                    "added_by": current_user,
                    "date": str(datetime.date.today()),
                }
                data.setdefault("extra_income", []).append(new_income)
                log_activity(data, f"Recorded income from '{source}' (৳{inc_amount:.2f})", current_user)
                save_and_sync(data)
                st.success("Income recorded!")
                st.rerun()

    extra_income_list = data.get("extra_income", [])
    if extra_income_list:
        df_income = pd.DataFrame(extra_income_list).reindex(
            columns=["date", "source", "amount", "added_by"],
            fill_value="-"
        )
        st.dataframe(df_income, use_container_width=True, hide_index=True)
    else:
        st.info("No extra income records found.")


# -------------------- TAB 4: ACTIVITY LOG --------------------
with tab_activity:
    st.subheader("Recent Activity & Audit Trail")
    logs = data.get("activity_log", [])
    if logs:
        df_logs = pd.DataFrame(logs).reindex(
            columns=["timestamp", "user", "action"],
            fill_value="-"
        )
        st.dataframe(df_logs, use_container_width=True, hide_index=True)
    else:
        st.info("No activity recorded yet.")

import datetime
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, Tuple

import pandas as pd
import requests
import streamlit as st

# Optional: Using cryptography for local cache encryption at rest
try:
    from cryptography.fernet import Fernet
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False

# ==================== STREAMLIT INITIALIZATION ====================
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
API_KEY: str = _get_secret("JSONBIN_API_KEY", "$2a$10$fJV5FBu.w7Frp.1rcAwPOOo77Na3X0uoRiHihmwMJEUU866aB6KSm")
BASE_URL: str = f"https://api.jsonbin.io/v3/b/6a70bea2da38895dfeb46969"
CACHE_FILE: Path = Path.home() / ".paas_joint_cache.json"
BACKUP_FILE: Path = Path.home() / ".paas_joint_cache.json.bak"
ENCRYPTION_KEY: str = _get_secret("LOCAL_CACHE_KEY", "")

USERS: dict[str, dict[str, Any]] = {
    "Taki Yasir": {
        "salt": b"salt_taki_2026",
        "pin_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b85",
        "test_pin": "0782",
        "role": "Primary Member",
        "avatar": "👑",
    },
    "Mahir Mannan": {
        "salt": b"salt_mahir_2026",
        "pin_hash": "a4ay8384298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b85",
        "test_pin": "9031",
        "role": "Partner Member",
        "avatar": "⚡",
    },
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


# ==================== SECURITY & ENCRYPTION HELPERS ====================
def get_fernet_cipher() -> Any:
    if HAS_CRYPTO and ENCRYPTION_KEY:
        try:
            return Fernet(ENCRYPTION_KEY.encode())
        except Exception:
            return None
    return None


def hash_pin(pin: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode("utf-8"), salt, 100_000).hex()


def verify_user_pin(username: str, pin_input: str) -> bool:
    user_info = USERS.get(username)
    if not user_info:
        return False
    hashed_attempt = hash_pin(pin_input, user_info["salt"])
    return pin_input == user_info["test_pin"] or hashed_attempt == user_info["pin_hash"]


# ==================== DEDUPLICATION & CLEANUP ENGINE ====================
def get_item_signature(item: dict[str, Any], category_type: str = "wishlist") -> str:
    name = str(item.get("item" if category_type == "wishlist" else "title", "")).strip().lower()
    price_or_amt = str(item.get("price" if category_type == "wishlist" else "amount", "")).strip()
    added_by = str(item.get("added_by", "Joint")).strip().lower()
    if category_type == "expenses":
        date_str = str(item.get("date", "")).strip()
        return f"{name}|{price_or_amt}|{added_by}|{date_str}"
    return f"{name}|{price_or_amt}|{added_by}"


def deduplicate_list(items: list[dict[str, Any]], category_type: str = "wishlist") -> list[dict[str, Any]]:
    seen_signatures = set()
    seen_ids = set()
    cleaned = []
    for entry in items:
        if not entry.get("id"):
            sig_hash = hashlib.md5(get_item_signature(entry, category_type).encode()).hexdigest()[:8]
            entry["id"] = f"id_{sig_hash}"

        if category_type == "expenses":
            entry.setdefault("category", "Other")
            entry.setdefault("title", entry.get("item", "Untitled"))
            entry.setdefault("amount", 0.0)
            entry.setdefault("date", str(datetime.date.today()))
            entry.setdefault("added_by", "Joint")

        item_id = entry["id"]
        sig = get_item_signature(entry, category_type)
        if sig in seen_signatures or item_id in seen_ids:
            continue
        seen_signatures.add(sig)
        seen_ids.add(item_id)
        cleaned.append(entry)
    return cleaned


def clean_and_deduplicate_data(data: dict[str, Any]) -> dict[str, Any]:
    for key in ["expenses", "wishlist", "extra_income", "activity_log"]:
        data.setdefault(key, [])
    data["expenses"] = deduplicate_list(data["expenses"], "expenses")
    data["wishlist"] = deduplicate_list(data["wishlist"], "wishlist")
    data["extra_income"] = deduplicate_list(data["extra_income"], "wishlist")
    return data


# ==================== DATA SYNCHRONIZATION ====================
def get_default_structure() -> dict[str, Any]:
    today_str = str(datetime.date.today())
    return {
        "expenses": [],
        "wishlist": [
            {
                "id": "init-1",
                "item": "Camping Tent",
                "price": 3200.0,
                "added_by": "Taki Yasir",
                "date": today_str,
            },
            {
                "id": "init-2",
                "item": "Portable Charger",
                "price": 1800.0,
                "added_by": "Mahir Mannan",
                "date": today_str,
            },
        ],
        "extra_income": [],
        "activity_log": [],
        "savings_goal": {"name": "Emergency Fund", "target": 50000.0},
        "updated_at": 0.0,
    }


def read_local_cache() -> dict[str, Any]:
    if not CACHE_FILE.exists():
        return get_default_structure()
    try:
        with CACHE_FILE.open("rb") as f:
            raw_data = f.read()
        cipher = get_fernet_cipher()
        if cipher:
            raw_data = cipher.decrypt(raw_data)
        data = json.loads(raw_data.decode("utf-8"))
        return clean_and_deduplicate_data(data)
    except Exception:
        return get_default_structure()


def write_local_cache(data: dict[str, Any]) -> None:
    try:
        data = clean_and_deduplicate_data(data)
        if CACHE_FILE.exists():
            shutil.copyfile(CACHE_FILE, BACKUP_FILE)
        data["updated_at"] = datetime.datetime.now().timestamp()
        serialized = json.dumps(data, indent=4, ensure_ascii=False).encode("utf-8")
        cipher = get_fernet_cipher()
        if cipher:
            serialized = cipher.encrypt(serialized)
        with CACHE_FILE.open("wb") as f:
            f.write(serialized)
    except Exception as e:
        st.sidebar.warning(f"Local cache save warning: {e}")


def sync_data() -> dict[str, Any]:
    local_data = read_local_cache()
    if not API_KEY:
        return local_data
    headers = {"Content-Type": "application/json", "X-Master-Key": API_KEY}
    try:
        response = requests.get(f"{BASE_URL}/latest", headers=headers, timeout=4.0)
        if response.status_code == 200:
            cloud_data = response.json().get("record", {})
            if isinstance(cloud_data, dict):
                cloud_data = clean_and_deduplicate_data(cloud_data)
                cloud_data.setdefault("savings_goal", {"name": "Emergency Fund", "target": 50000.0})
                write_local_cache(cloud_data)
                return cloud_data
        return local_data
    except requests.RequestException:
        return local_data


def save_and_sync(data: dict[str, Any]) -> None:
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
    entry = {
        "id": uuid.uuid4().hex[:8],
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %I:%M %p"),
        "user": user,
        "action": action_text,
    }
    data.setdefault("activity_log", []).insert(0, entry)


# ==================== FINANCIAL CALCULATIONS & EARNING RULES ====================
def calculate_individual_earnings_until(target_date: datetime.date, start_day: int = 6) -> Tuple[float, float]:
    """
    Calculates scheduled daily earnings from the 6th of the current month:
    - Taki Yasir: Fri = 1500, Sat = 0, Sun-Thu = 500
    - Mahir Mannan: 100 every single day
    """
    today = datetime.date.today()
    try:
        start_date = datetime.date(today.year, today.month, start_day)
    except ValueError:
        start_date = datetime.date(today.year, today.month, 1)

    if target_date < start_date:
        return 0.0, 0.0

    taki_earned = 0.0
    mahir_earned = 0.0
    current = start_date

    while current <= target_date:
        mahir_earned += 100.0
        weekday = current.weekday()
        if weekday == 5:    # Saturday
            taki_daily = 0.0
        elif weekday == 4:  # Friday
            taki_daily = 1500.0
        else:               # Sunday through Thursday
            taki_daily = 500.0
        taki_earned += taki_daily
        current += datetime.timedelta(days=1)

    return taki_earned, mahir_earned


def get_all_balances(data: dict[str, Any], target_date: datetime.date = None) -> dict[str, float]:
    """Computes separate individual balances and the joint pool balance."""
    target = target_date or datetime.date.today()
    taki_earned, mahir_earned = calculate_individual_earnings_until(target)

    taki_extra = 0.0
    mahir_extra = 0.0
    for inc in data.get("extra_income", []):
        amt = float(inc.get("amount", 0.0))
        user = inc.get("added_by", "Joint")
        if "Taki" in user:
            taki_extra += amt
        elif "Mahir" in user:
            mahir_extra += amt
        else:
            taki_extra += amt / 2.0
            mahir_extra += amt / 2.0

    taki_spent = 0.0
    mahir_spent = 0.0
    for exp in data.get("expenses", []):
        amt = float(exp.get("amount", 0.0))
        user = exp.get("added_by", "Joint")
        if "Taki" in user:
            taki_spent += amt
        elif "Mahir" in user:
            mahir_spent += amt
        else:
            taki_spent += amt / 2.0
            mahir_spent += amt / 2.0

    taki_balance = (taki_earned + taki_extra) - taki_spent
    mahir_balance = (mahir_earned + mahir_extra) - mahir_spent
    joint_balance = taki_balance + mahir_balance

    return {
        "Taki": taki_balance,
        "Mahir": mahir_balance,
        "Joint": joint_balance,
        "Taki_Spent": taki_spent,
        "Mahir_Spent": mahir_spent,
        "Total_Spent": taki_spent + mahir_spent,
    }


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
    pin_input = st.text_input("Enter PIN", type="password", max_chars=10)

    if st.button("Authenticate", use_container_width=True):
        if verify_user_pin(selected_user, pin_input):
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
        st.warning("Please log in to add, edit, or remove records.")

    st.divider()
    if st.button("🔄 Force Cloud Sync", use_container_width=True):
        st.session_state.paas_data = sync_data()
        st.success("Synced with cloud!")
        st.rerun()

# ==================== MAIN APPLICATION UI ====================
st.title("PAAS — Joint Accounting System")
st.caption("Manage shared expenses, track savings goals, and monitor joint cash flow.")

# Metric Scorecard with Individual Balances
balances = get_all_balances(data)
savings_target = float(data.get("savings_goal", {}).get("target", 50000.0))

col1, col2, col3, col4 = st.columns(4)
col1.metric("Joint Available Balance", f"৳{balances['Joint']:,.2f}")
col2.metric("Taki's Balance", f"৳{balances['Taki']:,.2f}")
col3.metric("Mahir's Balance", f"৳{balances['Mahir']:,.2f}")
col4.metric("Total Spent", f"৳{balances['Total_Spent']:,.2f}")

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

    # Visual Spending Chart (Guarded against missing columns)
    expenses = data.get("expenses", [])
    if expenses:
        st.divider()
        st.subheader("Spending by Category")

        df_exp = pd.DataFrame(expenses)
        for col, def_val in [
            ("category", "Other"),
            ("amount", 0.0),
            ("title", "Untitled"),
            ("date", str(datetime.date.today())),
            ("added_by", "Joint"),
        ]:
            if col not in df_exp.columns:
                df_exp[col] = def_val
            else:
                df_exp[col] = df_exp[col].fillna(def_val)

        df_exp["amount"] = pd.to_numeric(df_exp["amount"], errors="coerce").fillna(0.0)
        cat_spending = df_exp.groupby("category")["amount"].sum()
        st.bar_chart(cat_spending)

        st.subheader("Expense History & Management")
        for idx, entry in enumerate(expenses):
            with st.expander(
                f"[{entry.get('date', '-')}] {entry.get('title', 'Expense')} — ৳{float(entry.get('amount', 0)):,.2f} ({entry.get('category', 'Other')})"
            ):
                ec1, ec2, ec3 = st.columns([2, 1, 1])
                new_title = ec1.text_input("Edit Title", value=entry.get("title", ""), key=f"title_{idx}")
                new_amt = ec2.number_input("Edit Amount (৳)", value=float(entry.get("amount", 0)), step=10.0, key=f"amt_{idx}")
                new_cat = ec3.selectbox(
                    "Category",
                    CATEGORIES,
                    index=CATEGORIES.index(entry["category"]) if entry.get("category") in CATEGORIES else len(CATEGORIES) - 1,
                    key=f"cat_{idx}",
                )

                bc1, bc2 = st.columns(2)
                if bc1.button("Save Changes", key=f"save_{idx}", use_container_width=True):
                    if not current_user:
                        st.error("Login required.")
                    else:
                        entry["title"] = new_title
                        entry["amount"] = float(new_amt)
                        entry["category"] = new_cat
                        log_activity(data, f"Edited expense '{new_title}' (৳{new_amt:.2f})", current_user)
                        save_and_sync(data)
                        st.success("Expense updated!")
                        st.rerun()
                if bc2.button("🗑️ Delete Expense", key=f"del_{idx}", use_container_width=True):
                    if not current_user:
                        st.error("Login required.")
                    else:
                        removed = data["expenses"].pop(idx)
                        log_activity(data, f"Deleted expense '{removed.get('title')}'", current_user)
                        save_and_sync(data)
                        st.success("Expense deleted!")
                        st.rerun()
    else:
        st.info("No expenses recorded yet.")

# -------------------- TAB 2: WISHLIST & SAVINGS --------------------
with tab_wishlist:
    st.subheader("Savings Goal Progress")
    goal_name = data.get("savings_goal", {}).get("name", "Emergency Fund")
    progress = max(0.0, min(1.0, balances["Joint"] / savings_target)) if savings_target > 0 else 0.0
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
                existing_names = [w.get("item", "").strip().lower() for w in data.get("wishlist", [])]
                if item_name.strip().lower() in existing_names:
                    st.warning("⚠️ This item is already in your wishlist!")
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
                wc1, wc2, wc3, wc4 = st.columns([3, 1, 1, 1])
                wc1.write(f"**{item.get('item')}** (Added by {item.get('added_by', '-')})")
                wc2.write(f"**৳{float(item.get('price', 0)):,.2f}**")

                if wc3.button("🛍️ Buy Now", key=f"buy_wish_{item.get('id', idx)}", use_container_width=True):
                    if not current_user:
                        st.error("Login required.")
                    else:
                        bought = data["wishlist"].pop(idx)
                        new_exp = {
                            "id": uuid.uuid4().hex[:8],
                            "title": bought["item"],
                            "amount": float(bought["price"]),
                            "category": "Shopping",
                            "added_by": current_user,
                            "date": str(datetime.date.today()),
                        }
                        data.setdefault("expenses", []).append(new_exp)
                        log_activity(
                            data,
                            f"Purchased wishlist item '{bought['item']}' (৳{bought['price']:.2f})",
                            current_user,
                        )
                        save_and_sync(data)
                        st.success(f"Purchased '{bought['item']}'! Logged under Shopping expenses.")
                        st.rerun()

                if wc4.button("Remove", key=f"del_wish_{item.get('id', idx)}", use_container_width=True):
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
    st.subheader("Scheduled Earnings & Daily Rules")
    today_date = datetime.date.today()
    earned_taki, earned_mahir = calculate_individual_earnings_until(today_date)
    st.write(
        f"**Taki Yasir** (Fri: 1,500 | Sat: 0 | Sun–Thu: 500): **৳{earned_taki:,.2f}** accrued this cycle."
    )
    st.write(
        f"**Mahir Mannan** (100 every single day): **৳{earned_mahir:,.2f}** accrued this cycle."
    )

    st.divider()
    st.subheader("🔮 Future Balance Projection")
    days_to_project = st.slider("Project balance days into the future:", min_value=1, max_value=90, value=15)
    future_date = today_date + datetime.timedelta(days=days_to_project)
    future_balances = get_all_balances(data, target_date=future_date)

    fc1, fc2, fc3 = st.columns(3)
    fc1.metric(f"Projected Joint ({future_date})", f"৳{future_balances['Joint']:,.2f}")
    fc2.metric(f"Projected Taki ({future_date})", f"৳{future_balances['Taki']:,.2f}")
    fc3.metric(f"Projected Mahir ({future_date})", f"৳{future_balances['Mahir']:,.2f}")

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
            columns=["date", "source", "amount", "added_by"], fill_value="-"
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
            columns=["timestamp", "user", "action"], fill_value="-"
        )
        st.dataframe(df_logs, use_container_width=True, hide_index=True)
    else:
        st.info("No activity recorded yet.")

import datetime
import json
import os
import uuid
import requests
import streamlit as st

# ==================== CONFIGURATION & USERS ====================
BIN_ID = os.getenv("JSONBIN_ID", "6a70bea2da38895dfeb46969")
API_KEY = os.getenv("JSONBIN_API_KEY", "$2a$10$fJV5FBu.w7Frp.1rcAwPOOo77Na3X0uoRiHihmwMJEUU866aB6KSm")
BASE_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
CACHE_FILE = os.path.expanduser("~/.paas_joint_cache.json")

# Define authorized joint members and their individual PINs
USERS = {
    "Alex": {"pin": "0782", "role": "Primary Member"},
    "Jordan": {"pin": "0782", "role": "Partner Member"}
}

CATEGORIES = ["Food", "Bills & Utilities", "Entertainment", "Shopping", "Transport", "Other"]

st.set_page_config(
    page_title="PAAS — Joint Accounting System",
    page_icon="🏠",
    layout="wide"
)

# ==================== DATA SYNCHRONIZATION ====================

def get_default_structure():
    return {
        "expenses": [],
        "wishlist": [
            {"id": "init-1", "item": "Camping Tent", "price": 120.0, "added_by": "Alex", "date": str(datetime.date.today())},
            {"id": "init-2", "item": "Portable Charger", "price": 45.0, "added_by": "Jordan", "date": str(datetime.date.today())}
        ],
        "extra_income": [],
        "activity_log": []
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
        # Use item ID or sorted tuple as signature
        sig = item.get("id") or tuple(sorted((k, str(v)) for k, v in item.items()))
        if sig not in seen:
            seen.add(sig)
            unique_items.append(item)
    return unique_items

def sync_data():
    headers = {
        "Content-Type": "application/json",
        "X-Master-Key": API_KEY
    }
    local_data = read_local_cache()
    
    try:
        response = requests.get(f"{BASE_URL}/latest", headers=headers, timeout=4)
        if response.status_code == 200:
            cloud_data = response.json().get("record", get_default_structure())
            for key in ["expenses", "wishlist", "extra_income", "activity_log"]:
                cloud_data.setdefault(key, [])
            
            merged = {
                "expenses": deduplicate_list(cloud_data["expenses"] + local_data.get("expenses", [])),
                "wishlist": deduplicate_list(cloud_data["wishlist"] + local_data.get("wishlist", [])),
                "extra_income": deduplicate_list(cloud_data["extra_income"] + local_data.get("extra_income", [])),
                "activity_log": deduplicate_list(cloud_data["activity_log"] + local_data.get("activity_log", []))
            }
            
            if merged != cloud_data:
                requests.put(BASE_URL, json=merged, headers=headers, timeout=4)
                
            write_local_cache(merged)
            return merged
        return local_data
    except Exception:
        return local_data

def log_activity(data, action_text, user):
    """Records an action in the shared chronological feed."""
    entry = {
        "id": str(uuid.uuid4())[:8],
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
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
    return available, scheduled_earned, extra_earned, spent_total

def find_afford_date(data, price):
    today = datetime.date.today()
    extra_earned = sum(item.get("amount", 0) for item in data.get("extra_income", []))
    spent_total = sum(item.get("amount", 0) for item in data.get("expenses", []))
    
    current_check = today
    max_days = 365 * 5 
    for days_counter in range(max_days + 1):
        scheduled = calculate_earnings_until(current_check)
        if (scheduled + extra_earned) - spent_total >= price:
            return current_check, days_counter
        current_check += datetime.timedelta(days=1)
    return None, None

# ==================== AUTHENTICATION SIDEBAR ====================

if "current_user" not in st.session_state:
    st.session_state.current_user = None

st.sidebar.title("🔐 Joint Account Login")

if st.session_state.current_user is None:
    selected_user = st.sidebar.selectbox("Select Member Profile", list(USERS.keys()))
    pin_input = st.sidebar.text_input("Enter Member PIN", type="password", max_chars=4)
    
    if st.sidebar.button("Sign In"):
        if pin_input == USERS[selected_user]["pin"]:
            st.session_state.current_user = selected_user
            st.sidebar.success(f"Welcome, {selected_user}!")
            st.rerun()
        else:
            st.sidebar.error("Incorrect PIN for selected member.")
else:
    active_user = st.session_state.current_user
    st.sidebar.success(f"Logged in as: **{active_user}**")
    st.sidebar.caption(f"Role: {USERS[active_user]['role']}")
    
    if st.sidebar.button("Sign Out"):
        st.session_state.current_user = None
        st.rerun()

# ==================== MAIN DASHBOARD ====================

st.title("🏠 Personal Automated Accounting System (PAAS)")
st.caption("Joint Member Financial Dashboard & Collaborative Tracker")
st.divider()

data = sync_data()
current_balance, sched_earn, extra_earn, total_spent = get_current_balance(data)

# Summary Cards
c1, c2, c3, c4 = st.columns(4)
c1.metric("Shared Available Balance", f"৳{current_balance:,.2f}")
c2.metric("Scheduled Earnings", f"৳{sched_earn:,.2f}")
c3.metric("Joint Extra Income", f"৳{extra_earn:,.2f}")
c4.metric("Total Shared Expenses", f"৳{total_spent:,.2f}")

st.divider()

if st.session_state.current_user is None:
    st.info("👋 Please select your member profile and enter your **PIN** in the sidebar to add transactions, update the shared wishlist, or view the activity log.")
    st.stop()

active_user = st.session_state.current_user

# Navigation Tabs
tab_expense, tab_income, tab_wishlist, tab_activity, tab_reports = st.tabs([
    "💸 Log Expense",
    "💵 Add Shared Income",
    "🎁 Joint Wishlist",
    "📜 Activity Feed",
    "📊 Member Contributions"
])

# --- TAB 1: LOG EXPENSE ---
with tab_expense:
    st.subheader("Record an Expense Receipt")
    with st.form("expense_form", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            exp_item = st.text_input("What was purchased?")
            exp_amount = st.number_input("Amount Spent (৳)", min_value=0.0, step=10.0)
        with col_b:
            exp_cat = st.selectbox("Category", CATEGORIES, index=5)
            exp_date = st.date_input("Date of Purchase", value=datetime.date.today())
        
        if st.form_submit_button("✅ Save Expense"):
            if exp_item and exp_amount > 0:
                data["expenses"].append({
                    "id": str(uuid.uuid4())[:8],
                    "date": str(exp_date),
                    "item": exp_item,
                    "amount": float(exp_amount),
                    "category": exp_cat,
                    "added_by": active_user
                })
                log_activity(data, f"Logged expense '{exp_item}' (৳{exp_amount:,.2f}) under {exp_cat}", active_user)
                write_local_cache(data)
                sync_data()
                st.success(f"Expense recorded by {active_user}!")
                st.rerun()
            else:
                st.error("Please provide a valid item name and amount.")

# --- TAB 2: ADD SHARED INCOME ---
with tab_income:
    st.subheader("Contribute Extra Money to Shared Balance")
    with st.form("income_form", clear_on_submit=True):
        col_x, col_y = st.columns(2)
        with col_x:
            inc_source = st.text_input("Source (e.g., Bonus, Freelance, Cash Gift)")
        with col_y:
            inc_amount = st.number_input("Amount Received (৳)", min_value=0.0, step=100.0)
            
        if st.form_submit_button("✅ Add to Joint Balance"):
            if inc_source and inc_amount > 0:
                data["extra_income"].append({
                    "id": str(uuid.uuid4())[:8],
                    "date": str(datetime.date.today()),
                    "source": inc_source,
                    "amount": float(inc_amount),
                    "added_by": active_user
                })
                log_activity(data, f"Added ৳{inc_amount:,.2f} extra income from '{inc_source}'", active_user)
                write_local_cache(data)
                sync_data()
                st.success(f"Extra balance added by {active_user}!")
                st.rerun()
            else:
                st.error("Please enter a valid source and amount.")

# --- TAB 3: JOINT WISHLIST ---
with tab_wishlist:
    st.subheader("Shared Wishlist & Affordability Status")
    
    with st.expander("➕ Add New Item to Shared Wishlist"):
        with st.form("wish_form", clear_on_submit=True):
            w_item = st.text_input("Item Name")
            w_price = st.number_input("Estimated Cost (৳)", min_value=0.0, step=100.0)
            if st.form_submit_button("Add to Wishlist"):
                if w_item and w_price > 0:
                    data["wishlist"].append({
                        "id": str(uuid.uuid4())[:8],
                        "item": w_item,
                        "price": float(w_price),
                        "added_by": active_user,
                        "date": str(datetime.date.today())
                    })
                    log_activity(data, f"Added '{w_item}' (৳{w_price:,.2f}) to joint wishlist", active_user)
                    write_local_cache(data)
                    sync_data()
                    st.success(f"'{w_item}' added by {active_user}!")
                    st.rerun()
                else:
                    st.error("Enter a valid item name and cost.")

    if not data["wishlist"]:
        st.info("The shared wishlist is currently empty.")
    else:
        for idx, entry in enumerate(data["wishlist"]):
            price = entry["price"]
            afford_date, days_needed = find_afford_date(data, price)
            author = entry.get("added_by", "Joint")
            
            if days_needed is None:
                status, color = "❌ Cannot afford within 5 years", "red"
            elif days_needed == 0:
                status, color = "✅ CAN BUY TODAY!", "green"
            else:
                status, color = f"📅 Affordable on {afford_date} (in {days_needed} days)", "blue"
                
            with st.container():
                c_item, c_author, c_price, c_status, c_btn = st.columns([3, 2, 2, 3, 2])
                c_item.write(f"**{idx+1}. {entry['item']}**")
                c_author.write(f"👤 Added by: **{author}**")
                c_price.write(f"৳{price:,.2f}")
                c_status.markdown(f":{color}[{status}]")
                
                if c_btn.button("🛍️ Buy Now", key=f"buy_{entry['id']}"):
                    selected = data["wishlist"].pop(idx)
                    data["expenses"].append({
                        "id": str(uuid.uuid4())[:8],
                        "date": str(datetime.date.today()),
                        "item": selected["item"],
                        "amount": selected["price"],
                        "category": "Shopping",
                        "added_by": active_user
                    })
                    log_activity(data, f"Purchased wishlist item '{selected['item']}' for ৳{selected['price']:,.2f}", active_user)
                    write_local_cache(data)
                    sync_data()
                    st.success(f"Purchased '{selected['item']}'! Moved to shared expenses.")
                    st.rerun()
                st.divider()

# --- TAB 4: ACTIVITY FEED ---
with tab_activity:
    st.subheader("Recent Joint Activity Log")
    if not data.get("activity_log"):
        st.info("No activity recorded yet.")
    else:
        for act in data["activity_log"][:20]:  # Display last 20 actions
            c_time, c_user, c_action = st.columns([2, 2, 6])
            c_time.caption(act.get("timestamp", ""))
            c_user.write(f"**{act.get('user', 'Unknown')}**")
            c_action.write(act.get("action", ""))
            st.divider()

# --- TAB 5: MEMBER CONTRIBUTIONS ---
with tab_reports:
    st.subheader("Member Contribution Breakdown")
    col_r1, col_r2 = st.columns(2)
    
    with col_r1:
        st.markdown("#### Extra Income by Member")
        inc_by_user = {}
        for entry in data.get("extra_income", []):
            u = entry.get("added_by", "Joint")
            inc_by_user[u] = inc_by_user.get(u, 0.0) + entry.get("amount", 0.0)
        
        if not inc_by_user:
            st.caption("No extra income contributions yet.")
        else:
            for u, amt in inc_by_user.items():
                st.write(f"**{u}:** ৳{amt:,.2f}")
                st.progress(min(int((amt / max(extra_earn, 1)) * 100), 100))
                
    with col_r2:
        st.markdown("#### Expenses Logged by Member")
        exp_by_user = {}
        for entry in data.get("expenses", []):
            u = entry.get("added_by", "Joint")
            exp_by_user[u] = exp_by_user.get(u, 0.0) + entry.get("amount", 0.0)
            
        if not exp_by_user:
            st.caption("No expenses recorded yet.")
        else:
            for u, amt in exp_by_user.items():
                st.write(f"**{u}:** ৳{amt:,.2f}")
                st.progress(min(int((amt / max(total_spent, 1)) * 100), 100))

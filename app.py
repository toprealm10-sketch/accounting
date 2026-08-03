import datetime
import json
import os
import uuid
import requests
import pandas as pd
import streamlit as st

# ==================== CONFIGURATION & USERS ====================
BIN_ID = os.getenv("JSONBIN_ID", "6a70bea2da38895dfeb46969")
API_KEY = os.getenv("JSONBIN_API_KEY", "$2a$10$fJV5FBu.w7Frp.1rcAwPOOo77Na3X0uoRiHihmwMJEUU866aB6KSm")
BASE_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"
CACHE_FILE = os.path.expanduser("~/.paas_joint_cache.json")

# Authorized joint members and their PINs
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
            cloud_data.setdefault("savings_goal", {"name": "Emergency Fund", "target": 50000.0})
            
            merged = {
                "expenses": deduplicate_list(cloud_data["expenses"] + local_data.get("expenses", [])),
                "wishlist": deduplicate_list(cloud_data["wishlist"] + local_data.get("wishlist", [])),
                "extra_income": deduplicate_list(cloud_data["extra_income"] + local_data.get("extra_income", [])),
                "activity_log": deduplicate_list(cloud_data["activity_log"] + local_data.get("activity_log", [])),
                "savings_goal": cloud_data.get("savings_goal", local_data.get("savings_goal"))
            }
            
            if merged != cloud_data:
                requests.put(BASE_URL, json=merged, headers=headers, timeout=4)
                
            write_local_cache(merged)
            return merged
        return local_data
    except Exception:
        return local_data

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
    
    if st.sidebar.button("🚀 Sign In", use_container_width=True):
        if pin_input == USERS[selected_user]["pin"]:
            st.session_state.current_user = selected_user
            st.sidebar.success(f"Welcome back, {selected_user}!")
            st.rerun()
        else:
            st.sidebar.error("Incorrect PIN.")
else:
    active_user = st.session_state.current_user
    avatar = USERS[active_user]["avatar"]
    role = USERS[active_user]["role"]
    
    st.sidebar.success(f"{avatar} **{active_user}**\n\n`{role}`")
    if st.sidebar.button("🚪 Sign Out", use_container_width=True):
        st.session_state.current_user = None
        st.rerun()

# ==================== MAIN DASHBOARD ====================

st.title("🏠 PAAS — Personal Automated Accounting System")
st.caption("Collaborative Joint Ledger • Smart Projections • Expense Attribution")
st.divider()

data = sync_data()
current_balance, sched_earn, extra_earn, total_spent = get_current_balance(data)

# --- TOP KPI METRIC CARDS ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Available Balance", f"৳{current_balance:,.2f}", delta="Net Pool")
c2.metric("Scheduled Earnings", f"৳{sched_earn:,.2f}", delta="6th to Today")
c3.metric("Shared Extra Income", f"৳{extra_earn:,.2f}", delta="Contributions")
c4.metric("Total Expenses", f"৳{total_spent:,.2f}", delta="- Outflow", delta_color="inverse")

st.divider()

if st.session_state.current_user is None:
    st.info("👋 Select your profile and enter your **4-digit PIN** in the sidebar to log transactions, manage the shared wishlist, or inspect reports.")
    st.stop()

active_user = st.session_state.current_user

# --- NAVIGATION TABS ---
tab_dash, tab_add, tab_wishlist, tab_history, tab_activity = st.tabs([
    "📊 Analytics & Goals",
    "💸 Log Transactions",
    "🎁 Wishlist & Targets",
    "🧾 Receipt History",
    "📜 Activity Feed"
])

# ==================== TAB 1: ANALYTICS & GOALS ====================
with tab_dash:
    st.subheader("Financial Breakdown")
    col_left, col_right = st.columns(2)
    
    with col_left:
        st.markdown("#### Spending by Category")
        if not data["expenses"]:
            st.info("No expense data available to chart.")
        else:
            cat_totals = {cat: 0.0 for cat in CATEGORIES}
            for entry in data["expenses"]:
                cat = entry.get("category", "Other")
                cat_totals[cat] = cat_totals.get(cat, 0.0) + entry.get("amount", 0.0)
            
            chart_data = {k: v for k, v in cat_totals.items() if v > 0}
            if chart_data:
                st.bar_chart(chart_data)
            else:
                st.info("No spending recorded yet.")
                
    with col_right:
        st.markdown("#### Member Contributions (Extra Income)")
        inc_by_user = {}
        for entry in data.get("extra_income", []):
            u = entry.get("added_by", "Joint")
            inc_by_user[u] = inc_by_user.get(u, 0.0) + entry.get("amount", 0.0)
            
        if inc_by_user:
            st.bar_chart(inc_by_user)
        else:
            st.info("No extra income contributions logged yet.")
            
    st.divider()
    
    st.markdown("#### 🎯 Shared Savings Goal Tracker")
    goal = data.get("savings_goal", {"name": "Emergency Fund", "target": 50000.0})
    target_amt = goal["target"]
    progress_pct = min(max((current_balance / target_amt), 0.0), 1.0) if target_amt > 0 else 0
    
    g_col1, g_col2 = st.columns([3, 1])
    with g_col1:
        st.write(f"**Current Goal:** {goal['name']} — Target: **৳{target_amt:,.2f}**")
        st.progress(progress_pct)
        st.caption(f"Progress: {(progress_pct * 100):.1f}% of target goal reached using current available balance.")
    with g_col2:
        with st.popover("⚙️ Edit Goal"):
            new_goal_name = st.text_input("Goal Name", value=goal["name"])
            new_goal_target = st.number_input("Target Amount (৳)", min_value=100.0, value=float(target_amt), step=1000.0)
            if st.button("Update Goal"):
                data["savings_goal"] = {"name": new_goal_name, "target": float(new_goal_target)}
                log_activity(data, f"Updated savings goal to '{new_goal_name}' (৳{new_goal_target:,.2f})", active_user)
                write_local_cache(data)
                sync_data()
                st.rerun()

# ==================== TAB 2: LOG TRANSACTIONS ====================
with tab_add:
    col_exp, col_inc = st.columns(2)
    
    with col_exp:
        st.subheader("💸 Log an Expense")
        with st.form("expense_form", clear_on_submit=True):
            exp_item = st.text_input("What was purchased?", placeholder="e.g., Grocery shopping")
            exp_amount = st.number_input("Amount Spent (৳)", min_value=0.0, step=10.0)
            exp_cat = st.selectbox("Category", CATEGORIES, index=0)
            exp_date = st.date_input("Date of Purchase", value=datetime.date.today())
            
            if st.form_submit_button("✅ Save Expense", use_container_width=True):
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
                    st.error("Please enter a valid item and amount.")

    with col_inc:
        st.subheader("💵 Contribute Extra Income")
        with st.form("income_form", clear_on_submit=True):
            inc_source = st.text_input("Income Source", placeholder="e.g., Freelance project, Bonus")
            inc_amount = st.number_input("Amount Received (৳)", min_value=0.0, step=100.0)
            inc_date = st.date_input("Date Received", value=datetime.date.today())
            
            if st.form_submit_button("✅ Add to Joint Balance", use_container_width=True):
                if inc_source and inc_amount > 0:
                    data["extra_income"].append({
                        "id": str(uuid.uuid4())[:8],
                        "date": str(inc_date),
                        "source": inc_source,
                        "amount": float(inc_amount),
                        "added_by": active_user
                    })
                    log_activity(data, f"Added ৳{inc_amount:,.2f} extra income from '{inc_source}'", active_user)
                    write_local_cache(data)
                    sync_data()
                    st.success(f"Income recorded by {active_user}!")
                    st.rerun()
                else:
                    st.error("Please enter a valid source and amount.")

# ==================== TAB 3: WISHLIST & TARGETS ====================
with tab_wishlist:
    st.subheader("Shared Wishlist & Affordability Forecast")
    
    with st.expander("➕ Add New Item to Wishlist", expanded=False):
        with st.form("wish_form", clear_on_submit=True):
            w_item = st.text_input("Item Name")
            w_price = st.number_input("Estimated Cost (৳)", min_value=0.0, step=100.0)
            if st.form_submit_button("Add Item"):
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
                    st.success(f"'{w_item}' added!")
                    st.rerun()
                else:
                    st.error("Enter a valid item name and price.")

    if not data["wishlist"]:
        st.info("The shared wishlist is currently empty.")
    else:
        for idx, entry in enumerate(data["wishlist"]):
            price = entry["price"]
            afford_date, days_needed = find_afford_date(data, price)
            author = entry.get("added_by", "Joint")
            item_id = entry.get("id", f"item_{idx}")
            
            if days_needed is None:
                status, color = "❌ Cannot afford within 5 years", "red"
            elif days_needed == 0:
                status, color = "✅ CAN BUY TODAY!", "green"
            else:
                status, color = f"📅 Affordable on {afford_date} (in {days_needed} days)", "blue"
                
            with st.container():
                c_item, c_author, c_price, c_status, c_buy, c_remove = st.columns([3, 2, 2, 3, 1.5, 1])
                c_item.write(f"**{idx+1}. {entry['item']}**")
                c_author.write(f"👤 **{author}**")
                c_price.write(f"৳{price:,.2f}")
                c_status.markdown(f":{color}[{status}]")
                
                # Buy Button
                if c_buy.button("🛍️ Buy Now", key=f"buy_{item_id}"):
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
                
                # Remove Item Button
                if c_remove.button("🗑️", key=f"remove_{item_id}", help="Remove from Wishlist"):
                    removed = data["wishlist"].pop(idx)
                    log_activity(data, f"Removed '{removed['item']}' from joint wishlist", active_user)
                    write_local_cache(data)
                    sync_data()
                    st.success(f"Removed '{removed['item']}' from Wishlist.")
                    st.rerun()
                    
                st.divider()

# ==================== TAB 4: RECEIPT HISTORY ====================
with tab_history:
    st.subheader("Joint Receipt & Transaction Log")
    
    if not data["expenses"]:
        st.info("No expenses recorded yet.")
    else:
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            selected_cat = st.multiselect("Filter by Category", CATEGORIES, default=CATEGORIES)
        with f_col2:
            members = list(USERS.keys()) + ["Joint"]
            selected_user_filter = st.multiselect("Filter by Member", members, default=members)
            
        filtered_expenses = [
            e for e in data["expenses"]
            if e.get("category", "Other") in selected_cat and e.get("added_by", "Joint") in selected_user_filter
        ]
        
        if not filtered_expenses:
            st.warning("No expenses match your selected filters.")
        else:
            df = pd.DataFrame(filtered_expenses)
            cols_order = [col for col in ["date", "item", "amount", "category", "added_by"] if col in df.columns]
            df_display = df[cols_order].sort_values(by="date", ascending=False)
            
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            
            csv = df_display.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="📥 Download Log as CSV",
                data=csv,
                file_name="paas_joint_expenses.csv",
                mime="text/csv",
                use_container_width=True
            )

# ==================== TAB 5: ACTIVITY FEED ====================
with tab_activity:
    st.subheader("Chronological Activity Feed")
    if not data.get("activity_log"):
        st.info("No activity logged yet.")
    else:
        for act in data["activity_log"][:25]:
            c_time, c_user, c_action = st.columns([2, 2, 6])
            c_time.caption(act.get("timestamp", ""))
            c_user.write(f"**{act.get('user', 'System')}**")
            c_action.write(act.get("action", ""))
            st.divider()

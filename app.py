import datetime
import json
import os
import requests
import uuid
import streamlit as st

# -------------------- CONFIGURATION --------------------
# Uses environment variables if set; otherwise defaults to configured JSONBin credentials
BIN_ID = os.getenv("JSONBIN_ID", "6a70bea2da38895dfeb46969")
API_KEY = os.getenv("JSONBIN_API_KEY", "$2a$10$fJV5FBu.w7Frp.1rcAwPOOo77Na3X0uoRiHihmwMJEUU866aB6KSm")
BASE_URL = f"https://api.jsonbin.io/v3/b/{BIN_ID}"

SECURITY_PIN = "0782"
CACHE_FILE = os.path.expanduser("~/.paas_cache.json")
CATEGORIES = ["Food", "Bills & Utilities", "Entertainment", "Shopping", "Transport", "Other"]
# --------------------------------------------------------

# Page Config
st.set_page_config(
    page_title="PAAS — Accounting System",
    page_icon="🏠",
    layout="wide"
)

# -------------------- DATA & CLOUD FUNCTIONS --------------------

def get_default_structure():
    return {"expenses": [], "wishlist": [], "extra_income": []}


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
        sig = tuple(sorted(item.items()))
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
            cloud_data.setdefault("expenses", [])
            cloud_data.setdefault("wishlist", [])
            cloud_data.setdefault("extra_income", [])
            
            merged_expenses = deduplicate_list(cloud_data["expenses"] + local_data.get("expenses", []))
            merged_wishlist = deduplicate_list(cloud_data["wishlist"] + local_data.get("wishlist", []))
            merged_income = deduplicate_list(cloud_data["extra_income"] + local_data.get("extra_income", []))
            
            final_data = {
                "expenses": merged_expenses,
                "wishlist": merged_wishlist,
                "extra_income": merged_income
            }
            
            if final_data != cloud_data:
                requests.put(BASE_URL, json=final_data, headers=headers, timeout=4)
                
            write_local_cache(final_data)
            return final_data
        else:
            return local_data
    except (requests.ConnectionError, requests.Timeout):
        return local_data
    except Exception:
        return local_data


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
    return (scheduled_earned + extra_earned) - spent_total, scheduled_earned, extra_earned, spent_total


def find_afford_date(data, price):
    today = datetime.date.today()
    extra_earned = sum(item.get("amount", 0) for item in data.get("extra_income", []))
    spent_total = sum(item.get("amount", 0) for item in data.get("expenses", []))
    
    current_check = today
    max_days = 365 * 5 
    days_counter = 0

    while days_counter <= max_days:
        scheduled = calculate_earnings_until(current_check)
        balance = (scheduled + extra_earned) - spent_total
        if balance >= price:
            return current_check, days_counter
        current_check += datetime.timedelta(days=1)
        days_counter += 1

    return None, None

# -------------------- SESSION STATE (PIN AUTH) --------------------

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

st.sidebar.title("🔒 Security Access")
if not st.session_state.authenticated:
    pin_input = st.sidebar.text_input("Enter Security PIN", type="password", max_chars=4)
    if st.sidebar.button("Unlock PAAS"):
        if pin_input == SECURITY_PIN:
            st.session_state.authenticated = True
            st.sidebar.success("Access Granted!")
            st.rerun()
        else:
            st.sidebar.error("Incorrect PIN.")
else:
    st.sidebar.success("✅ Logged in securely")
    if st.sidebar.button("Lock / Log Out"):
        st.session_state.authenticated = False
        st.rerun()

# -------------------- MAIN STREAMLIT UI --------------------

st.title("🏠 Personal Automated Accounting System (PAAS)")
st.caption("Synchronized Joint Tracker & Financial Forecast Dashboard")
st.divider()

# Fetch latest synced data
data = sync_data()
current_balance, sched_earn, extra_earn, total_spent = get_current_balance(data)

# Always show top-level balance overview
col1, col2, col3, col4 = st.columns(4)
col1.metric("Available Balance", f"৳{current_balance:,.2f}")
col2.metric("Scheduled Earnings", f"৳{sched_earn:,.2f}")
col3.metric("Extra Income", f"৳{extra_earn:,.2f}")
col4.metric("Total Expenses", f"৳{total_spent:,.2f}")

st.divider()

# Require PIN for detailed features
if not st.session_state.authenticated:
    st.info("👋 Welcome! Please enter your **Security PIN** in the sidebar on the left to access logs, add expenses, view wishlist timelines, or check spending reports.")
    st.stop()

# Navigation Tabs for authorized users
tab_expense, tab_income, tab_receipts, tab_reports, tab_forecast, tab_wishlist = st.tabs([
    "💸 Log Expense", 
    "💵 Extra Income", 
    "🧾 Receipt Log", 
    "📊 Reports", 
    "🔮 Forecast", 
    "🎁 Wish List"
])

# --- TAB 1: LOG EXPENSE ---
with tab_expense:
    st.subheader("Add New Expense Receipt")
    with st.form("expense_form", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            exp_item = st.text_input("What did you spend on?")
            exp_amount = st.number_input("Amount Spent (৳)", min_value=0.0, step=10.0)
            exp_date = st.date_input("Date", value=datetime.date.today())
        with col_b:
            exp_cat = st.selectbox("Category", CATEGORIES, index=5)
            exp_payer = st.text_input("Who Paid?", value="Joint")
        
        submit_exp = st.form_submit_button("✅ Save Expense")
        if submit_exp:
            if exp_item and exp_amount > 0:
                data["expenses"].append({
                    "id": str(uuid.uuid4())[:8],
                    "date": str(exp_date),
                    "item": exp_item,
                    "amount": float(exp_amount),
                    "category": exp_cat,
                    "payer": exp_payer or "Joint"
                })
                write_local_cache(data)
                sync_data()
                st.success(f"Logged ৳{exp_amount:.2f} for '{exp_item}'!")
                st.rerun()
            else:
                st.error("Please enter a valid item name and amount.")

# --- TAB 2: EXTRA INCOME ---
with tab_income:
    st.subheader("Add Extra Balance / Income")
    with st.form("income_form", clear_on_submit=True):
        col_x, col_y = st.columns(2)
        with col_x:
            inc_source = st.text_input("Source (Gift, Bonus, Freelance, etc.)")
        with col_y:
            inc_amount = st.number_input("Amount Received (৳)", min_value=0.0, step=100.0)
            
        submit_inc = st.form_submit_button("✅ Add to Balance")
        if submit_inc:
            if inc_source and inc_amount > 0:
                data["extra_income"].append({
                    "id": str(uuid.uuid4())[:8],
                    "date": str(datetime.date.today()),
                    "source": inc_source,
                    "amount": float(inc_amount)
                })
                write_local_cache(data)
                sync_data()
                st.success(f"Added ৳{inc_amount:.2f} extra balance from '{inc_source}'!")
                st.rerun()
            else:
                st.error("Please enter a valid source and amount.")

# --- TAB 3: RECEIPT LOG ---
with tab_receipts:
    st.subheader("Joint Receipt History")
    if not data["expenses"]:
        st.info("No expenses recorded yet.")
    else:
        sorted_expenses = sorted(data["expenses"], key=lambda x: x.get("date", ""), reverse=True)
        st.dataframe(sorted_expenses, use_container_width=True, hide_index=True)

# --- TAB 4: REPORTS ---
with tab_reports:
    st.subheader("Spending Breakdown")
    if not data["expenses"]:
        st.info("No spending data available.")
    else:
        col_r1, col_r2 = st.columns(2)
        
        cat_totals = {cat: 0.0 for cat in CATEGORIES}
        payer_totals = {}
        for entry in data["expenses"]:
            cat = entry.get("category", "Other")
            payer = entry.get("payer", "Joint")
            amt = entry.get("amount", 0.0)
            cat_totals[cat] = cat_totals.get(cat, 0.0) + amt
            payer_totals[payer] = payer_totals.get(payer, 0.0) + amt
            
        with col_r1:
            st.markdown("#### By Category")
            for cat, amt in cat_totals.items():
                if amt > 0:
                    pct = (amt / total_spent) * 100 if total_spent > 0 else 0
                    st.write(f"**{cat}:** ৳{amt:,.2f} ({pct:.1f}%)")
                    st.progress(min(int(pct), 100))
                    
        with col_r2:
            st.markdown("#### By Payer")
            for payer, amt in payer_totals.items():
                pct = (amt / total_spent) * 100 if total_spent > 0 else 0
                st.write(f"**{payer}:** ৳{amt:,.2f} ({pct:.1f}%)")
                st.progress(min(int(pct), 100))

# --- TAB 5: FORECAST ---
with tab_forecast:
    st.subheader("Project Future Available Balance")
    target_date = st.date_input("Select Future Date to Forecast:", value=datetime.date.today() + datetime.timedelta(days=7))
    
    if target_date >= datetime.date.today():
        sched_fut = calculate_earnings_until(target_date)
        proj_bal = (sched_fut + extra_earn) - total_spent
        days_diff = (target_date - datetime.date.today()).days
        
        col_f1, col_f2 = st.columns(2)
        col_f1.metric(f"Projected Balance in {days_diff} days", f"৳{proj_bal:,.2f}")
        col_f2.metric("Projected Scheduled Earnings", f"৳{sched_fut:,.2f}")
    else:
        st.warning("Please select today or a future date.")

# --- TAB 6: WISH LIST ---
with tab_wishlist:
    st.subheader("Joint Wish List & Affordability Timelines")
    
    # Add Item Section
    with st.expander("➕ Add New Item to Wish List"):
        with st.form("wish_form", clear_on_submit=True):
            w_item = st.text_input("Item Name")
            w_price = st.number_input("Cost (৳)", min_value=0.0, step=500.0)
            if st.form_submit_button("Add Item"):
                if w_item and w_price > 0:
                    data["wishlist"].append({"item": w_item, "price": float(w_price)})
                    write_local_cache(data)
                    sync_data()
                    st.success(f"Added '{w_item}' to Wish List!")
                    st.rerun()
                else:
                    st.error("Enter a valid item name and cost.")

    # Show Wishlist Items
    if not data["wishlist"]:
        st.info("Wish list is empty.")
    else:
        for idx, entry in enumerate(data["wishlist"]):
            price = entry["price"]
            afford_date, days_needed = find_afford_date(data, price)
            
            if days_needed is None:
                status = "❌ Cannot afford within 5 years"
                color = "red"
            elif days_needed == 0:
                status = "✅ CAN BUY TODAY!"
                color = "green"
            else:
                status = f"📅 Affordable on {afford_date} (in {days_needed} days)"
                color = "blue"
                
            with st.container():
                c1, c2, c3, c4 = st.columns([3, 2, 3, 2])
                c1.write(f"**{idx+1}. {entry['item']}**")
                c2.write(f"৳{price:,.2f}")
                c3.markdown(f":{color}[{status}]")
                
                # Direct Buy Button
                if c4.button("🛍️ Buy Now", key=f"buy_{idx}"):
                    selected = data["wishlist"].pop(idx)
                    data["expenses"].append({
                        "id": str(uuid.uuid4())[:8],
                        "date": str(datetime.date.today()),
                        "item": selected["item"],
                        "amount": selected["price"],
                        "category": "Shopping",
                        "payer": "Joint"
                    })
                    write_local_cache(data)
                    sync_data()
                    st.success(f"Purchased '{selected['item']}'! Moved to Receipt Log.")
                    st.rerun()
                st.divider()
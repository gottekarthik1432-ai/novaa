import os
import sqlite3
import hashlib
import requests
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, timedelta
import json
from typing import Dict, List, Optional, Tuple
import re

# ---------------------- Config ----------------------
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")  # FastAPI default
DB_FILE = "users.db"

st.set_page_config(
    page_title="Personal Finance Chatbot", 
    page_icon="💰", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------------- Custom CSS ----------------------
st.markdown("""
<style>
    .stButton > button {
        width: 100%;
        background-color: #4CAF50;
        color: white;
        border-radius: 5px;
    }
    .stButton > button:hover {
        background-color: #45a049;
    }
    .finance-card {
        padding: 1rem;
        border-radius: 0.5rem;
        background-color: #f0f2f6;
        margin-bottom: 1rem;
    }
    .metric-card {
        text-align: center;
        padding: 1rem;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------- Enhanced Database Setup ----------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            user_type TEXT DEFAULT 'Student',
            monthly_income REAL DEFAULT 0,
            savings_goal REAL DEFAULT 0
        )
    """)
    
    # Chat history table
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            user_message TEXT,
            bot_response TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    """)
    
    # Expenses tracking table
    c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            category TEXT,
            amount REAL,
            description TEXT,
            date DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    """)
    
    # Investment portfolio table
    c.execute("""
        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            investment_type TEXT,
            amount REAL,
            returns REAL DEFAULT 0,
            date_invested DATE DEFAULT CURRENT_DATE,
            FOREIGN KEY (username) REFERENCES users(username)
        )
    """)
    
    conn.commit()
    conn.close()

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username: str, password: str, user_type: str = "Student") -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (username, password_hash, user_type) VALUES (?, ?, ?)", 
            (username, hash_password(password), user_type)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def validate_user(username: str, password: str) -> bool:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT password_hash FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    return row and row[0] == hash_password(password)

def get_user_profile(username: str) -> Dict:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT user_type, monthly_income, savings_goal FROM users WHERE username=?", 
        (username,)
    )
    row = c.fetchone()
    conn.close()
    if row:
        return {
            "user_type": row[0],
            "monthly_income": row[1] or 0,
            "savings_goal": row[2] or 0
        }
    return {"user_type": "Student", "monthly_income": 0, "savings_goal": 0}

def update_user_profile(username: str, user_type: str, income: float, savings_goal: float):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET user_type=?, monthly_income=?, savings_goal=? WHERE username=?",
        (user_type, income, savings_goal, username)
    )
    conn.commit()
    conn.close()

def save_chat_history(username: str, user_msg: str, bot_response: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO chat_history (username, user_message, bot_response) VALUES (?, ?, ?)",
        (username, user_msg, bot_response)
    )
    conn.commit()
    conn.close()

def get_chat_history(username: str, limit: int = 10) -> List[Tuple]:
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "SELECT user_message, bot_response, timestamp FROM chat_history WHERE username=? ORDER BY timestamp DESC LIMIT ?",
        (username, limit)
    )
    history = c.fetchall()
    conn.close()
    return history

def add_expense(username: str, category: str, amount: float, description: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO expenses (username, category, amount, description) VALUES (?, ?, ?, ?)",
        (username, category, amount, description)
    )
    conn.commit()
    conn.close()

def get_expenses(username: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT category, amount, description, date FROM expenses WHERE username=?"
    df = pd.read_sql_query(query, conn, params=(username,))
    conn.close()
    return df

def add_investment(username: str, inv_type: str, amount: float, returns: float = 0):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        "INSERT INTO investments (username, investment_type, amount, returns) VALUES (?, ?, ?, ?)",
        (username, inv_type, amount, returns)
    )
    conn.commit()
    conn.close()

def get_investments(username: str) -> pd.DataFrame:
    conn = sqlite3.connect(DB_FILE)
    query = "SELECT investment_type, amount, returns, date_invested FROM investments WHERE username=?"
    df = pd.read_sql_query(query, conn, params=(username,))
    conn.close()
    return df

# ---------------------- Session State ----------------------
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False
if "username" not in st.session_state:
    st.session_state.username = ""
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "current_page" not in st.session_state:
    st.session_state.current_page = "chatbot"

# ---------------------- Helpers ----------------------
def get_budget_summary(user_type: str, income: float = 0) -> Dict:
    if user_type == "Student":
        budget = {
            "Essentials": 0.50,
            "Education": 0.30,
            "Savings": 0.20
        }
    else:
        budget = {
            "Essentials": 0.40,
            "Savings": 0.20,
            "Investments": 0.20,
            "Discretionary": 0.20
        }
    
    if income > 0:
        return {k: v * income for k, v in budget.items()}
    return budget

def call_backend(prompt: str, user_type: str) -> str:
    system = (
        f"You are a helpful financial assistant specializing in Indian personal finance. "
        f"Give concise, practical guidance with India-specific examples. "
        f"User type: {user_type}. Include relevant tax laws, investment options like PPF, NPS, ELSS, "
        f"and Indian banking practices where applicable."
    )
    payload = {
        "prompt": prompt,
        "system": system,
        "max_new_tokens": 256,
        "temperature": 0.2,
        "top_p": 0.95
    }
    url = f"{BACKEND_URL}/v1/generate"
    resp = requests.post(url, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    return data["generated_text"]

def calculate_tax(income: float, user_type: str) -> Dict:
    """Simple Indian tax calculator"""
    annual_income = income * 12
    
    # New tax regime (simplified)
    if annual_income <= 300000:
        tax = 0
    elif annual_income <= 600000:
        tax = (annual_income - 300000) * 0.05
    elif annual_income <= 900000:
        tax = 15000 + (annual_income - 600000) * 0.10
    elif annual_income <= 1200000:
        tax = 45000 + (annual_income - 900000) * 0.15
    elif annual_income <= 1500000:
        tax = 90000 + (annual_income - 1200000) * 0.20
    else:
        tax = 150000 + (annual_income - 1500000) * 0.30
    
    # Add cess
    cess = tax * 0.04
    total_tax = tax + cess
    
    return {
        "annual_income": annual_income,
        "tax": tax,
        "cess": cess,
        "total_tax": total_tax,
        "monthly_tax": total_tax / 12,
        "effective_rate": (total_tax / annual_income * 100) if annual_income > 0 else 0
    }

def create_expense_chart(df: pd.DataFrame):
    if df.empty:
        return None
    
    # Group by category
    category_totals = df.groupby('category')['amount'].sum().reset_index()
    
    fig = px.pie(
        category_totals, 
        values='amount', 
        names='category',
        title='Expense Distribution',
        color_discrete_sequence=px.colors.qualitative.Set3
    )
    return fig

def create_investment_chart(df: pd.DataFrame):
    if df.empty:
        return None
    
    fig = go.Figure()
    
    # Add bars for investment amounts
    fig.add_trace(go.Bar(
        name='Amount Invested',
        x=df['investment_type'],
        y=df['amount'],
        marker_color='lightblue'
    ))
    
    # Add bars for returns
    fig.add_trace(go.Bar(
        name='Returns',
        x=df['investment_type'],
        y=df['returns'],
        marker_color='lightgreen'
    ))
    
    fig.update_layout(
        title='Investment Portfolio',
        barmode='group',
        xaxis_title='Investment Type',
        yaxis_title='Amount (₹)'
    )
    
    return fig

# ---------------------- Pages ----------------------
def login_page():
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.title("🔐 Login to Finance Chatbot")
        st.markdown("---")
        
        tab1, tab2 = st.tabs(["Login", "Register"])
        
        with tab1:
            username = st.text_input("Username", key="login_username")
            password = st.text_input("Password", type="password", key="login_password")
            
            if st.button("Login", type="primary"):
                if validate_user(username, password):
                    st.session_state.logged_in = True
                    st.session_state.username = username
                    st.success(f"✅ Welcome back, {username}!")
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password")
        
        with tab2:
            new_username = st.text_input("New Username", key="reg_username")
            new_password = st.text_input("New Password", type="password", key="reg_password")
            user_type = st.selectbox("User Type", ["Student", "Professional"], key="reg_type")
            
            if st.button("Register", type="primary"):
                if new_username.strip() == "" or new_password.strip() == "":
                    st.error("⚠️ Username and password cannot be empty")
                elif len(new_password) < 6:
                    st.error("⚠️ Password must be at least 6 characters")
                elif register_user(new_username, new_password, user_type):
                    st.success("✅ Registration successful! You can now log in.")
                else:
                    st.error("⚠️ Username already exists. Try another.")

def sidebar_menu():
    with st.sidebar:
        st.title("📊 Navigation")
        st.markdown(f"**User:** {st.session_state.username}")
        st.markdown("---")
        
        if st.button("💬 Chatbot", use_container_width=True):
            st.session_state.current_page = "chatbot"
            st.rerun()
        
        if st.button("👤 Profile", use_container_width=True):
            st.session_state.current_page = "profile"
            st.rerun()
        
        if st.button("💵 Expense Tracker", use_container_width=True):
            st.session_state.current_page = "expenses"
            st.rerun()
        
        if st.button("📈 Investments", use_container_width=True):
            st.session_state.current_page = "investments"
            st.rerun()
        
        if st.button("🧮 Tax Calculator", use_container_width=True):
            st.session_state.current_page = "tax"
            st.rerun()
        
        if st.button("📜 History", use_container_width=True):
            st.session_state.current_page = "history"
            st.rerun()
        
        st.markdown("---")
        
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.logged_in = False
            st.session_state.username = ""
            st.session_state.chat_messages = []
            st.rerun()

def chatbot_page():
    st.title("💰 Personal Finance Chatbot")
    
    # Display metrics
    profile = get_user_profile(st.session_state.username)
    
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("User Type", profile["user_type"])
    with col2:
        st.metric("Monthly Income", f"₹{profile['monthly_income']:,.0f}")
    with col3:
        st.metric("Savings Goal", f"₹{profile['savings_goal']:,.0f}")
    with col4:
        if st.button("🔄 Check Backend"):
            try:
                h = requests.get(f"{BACKEND_URL}/health", timeout=10).json()
                st.success(f"Backend OK: {h['status']}")
            except Exception as e:
                st.error(f"Backend not reachable: {e}")
    
    st.markdown("---")
    
    # Chat interface
    st.markdown("### 💬 Ask your finance questions")
    
    # Display chat messages
    for message in st.session_state.chat_messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
    
    # Input
    user_input = st.chat_input("Ask about savings, taxes, investments...")
    
    if user_input:
        # Add user message
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        
        with st.chat_message("user"):
            st.write(user_input)
        
        # Get bot response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    response = call_backend(user_input, profile["user_type"])
                    st.write(response)
                    
                    # Save to history
                    save_chat_history(st.session_state.username, user_input, response)
                    
                    # Add bot message
                    st.session_state.chat_messages.append({"role": "assistant", "content": response})
                    
                except Exception as e:
                    st.error(f"Error: {e}")

def profile_page():
    st.title("👤 User Profile")
    
    profile = get_user_profile(st.session_state.username)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Update Profile")
        user_type = st.selectbox("User Type", ["Student", "Professional", "Retired"], 
                                 index=["Student", "Professional", "Retired"].index(profile["user_type"]))
        income = st.number_input("Monthly Income (₹)", min_value=0.0, value=profile["monthly_income"], step=1000.0)
        savings_goal = st.number_input("Monthly Savings Goal (₹)", min_value=0.0, value=profile["savings_goal"], step=500.0)
        
        if st.button("Update Profile", type="primary"):
            update_user_profile(st.session_state.username, user_type, income, savings_goal)
            st.success("✅ Profile updated successfully!")
            st.rerun()
    
    with col2:
        st.subheader("Budget Recommendation")
        if income > 0:
            budget = get_budget_summary(user_type, income)
            
            for category, amount in budget.items():
                st.metric(category, f"₹{amount:,.0f}")
            
            # Create pie chart
            fig = px.pie(
                values=list(budget.values()),
                names=list(budget.keys()),
                title="Recommended Budget Distribution",
                color_discrete_sequence=px.colors.qualitative.Set2
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Set your monthly income to see budget recommendations")

def expense_tracker_page():
    st.title("💵 Expense Tracker")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Add Expense")
        category = st.selectbox("Category", ["Food", "Transport", "Entertainment", "Utilities", 
                                            "Healthcare", "Education", "Shopping", "Other"])
        amount = st.number_input("Amount (₹)", min_value=0.0, step=100.0)
        description = st.text_input("Description")
        
        if st.button("Add Expense", type="primary"):
            if amount > 0:
                add_expense(st.session_state.username, category, amount, description)
                st.success("✅ Expense added!")
                st.rerun()
            else:
                st.error("Amount must be greater than 0")
    
    with col2:
        st.subheader("Expense Summary")
        expenses_df = get_expenses(st.session_state.username)
        
        if not expenses_df.empty:
            # Show total
            total_expenses = expenses_df['amount'].sum()
            st.metric("Total Expenses", f"₹{total_expenses:,.0f}")
            
            # Show chart
            fig = create_expense_chart(expenses_df)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            
            # Show recent expenses
            st.subheader("Recent Expenses")
            st.dataframe(expenses_df.tail(10), use_container_width=True)
        else:
            st.info("No expenses recorded yet")

def investment_page():
    st.title("📈 Investment Portfolio")
    
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("Add Investment")
        inv_type = st.selectbox("Investment Type", ["Stocks", "Mutual Funds", "FD", "PPF", 
                                                   "NPS", "Gold", "Real Estate", "Crypto", "Other"])
        amount = st.number_input("Amount Invested (₹)", min_value=0.0, step=1000.0)
        returns = st.number_input("Current Returns (₹)", min_value=-999999.0, step=100.0)
        
        if st.button("Add Investment", type="primary"):
            if amount > 0:
                add_investment(st.session_state.username, inv_type, amount, returns)
                st.success("✅ Investment added!")
                st.rerun()
            else:
                st.error("Amount must be greater than 0")
    
    with col2:
        st.subheader("Portfolio Summary")
        investments_df = get_investments(st.session_state.username)
        
        if not investments_df.empty:
            # Calculate totals
            total_invested = investments_df['amount'].sum()
            total_returns = investments_df['returns'].sum()
            roi = (total_returns / total_invested * 100) if total_invested > 0 else 0
            
            col_a, col_b, col_c = st.columns(3)
            with col_a:
                st.metric("Total Invested", f"₹{total_invested:,.0f}")
            with col_b:
                st.metric("Total Returns", f"₹{total_returns:,.0f}", 
                         delta=f"{roi:.1f}%")
            with col_c:
                st.metric("Portfolio Value", f"₹{total_invested + total_returns:,.0f}")
            
            # Show chart
            fig = create_investment_chart(investments_df)
            if fig:
                st.plotly_chart(fig, use_container_width=True)
            
            # Show investments table
            st.subheader("Investment Details")
            st.dataframe(investments_df, use_container_width=True)
        else:
            st.info("No investments recorded yet")

def tax_calculator_page():
    st.title("🧮 Tax Calculator (India)")
    
    profile = get_user_profile(st.session_state.username)
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Income Details")
        monthly_income = st.number_input("Monthly Income (₹)", 
                                        min_value=0.0, 
                                        value=profile["monthly_income"], 
                                        step=1000.0)
        
        st.subheader("Deductions (Section 80C)")
        pf = st.number_input("EPF/PPF (₹)", min_value=0.0, max_value=150000.0, step=1000.0)
        elss = st.number_input("ELSS (₹)", min_value=0.0, max_value=150000.0, step=1000.0)
        lic = st.number_input("LIC Premium (₹)", min_value=0.0, max_value=150000.0, step=1000.0)
        
        total_80c = min(pf + elss + lic, 150000)
        st.info(f"Total 80C Deductions: ₹{total_80c:,.0f} (Max: ₹1,50,000)")
        
        if st.button("Calculate Tax", type="primary"):
            if monthly_income > 0:
                tax_info = calculate_tax(monthly_income, profile["user_type"])
                
                # Ask backend for tax saving tips
                prompt = f"Give me top 3 tax saving tips for someone earning ₹{monthly_income} per month in India"
                try:
                    tips = call_backend(prompt, profile["user_type"])
                    st.session_state.tax_tips = tips
                except:
                    st.session_state.tax_tips = "Unable to fetch tax saving tips"
                
                st.session_state.tax_calculation = tax_info
                st.rerun()
    
    with col2:
        if "tax_calculation" in st.session_state:
            st.subheader("Tax Calculation Results")
            tax_info = st.session_state.tax_calculation
            
            st.metric("Annual Income", f"₹{tax_info['annual_income']:,.0f}")
            st.metric("Income Tax", f"₹{tax_info['tax']:,.0f}")
            st.metric("Health & Education Cess", f"₹{tax_info['cess']:,.0f}")
            st.metric("Total Tax", f"₹{tax_info['total_tax']:,.0f}")
            st.metric("Monthly Tax", f"₹{tax_info['monthly_tax']:,.0f}")
            st.metric("Effective Tax Rate", f"{tax_info['effective_rate']:.2f}%")
            
            if "tax_tips" in st.session_state:
                st.subheader("💡 Tax Saving Tips")
                st.info(st.session_state.tax_tips)

def history_page():
    st.title("📜 Chat History")
    
    history = get_chat_history(st.session_state.username, limit=20)
    
    if history:
        for user_msg, bot_response, timestamp in reversed(history):
            st.markdown(f"**🕐 {timestamp}**")
            
            with st.chat_message("user"):
                st.write(user_msg)
            
            with st.chat_message("assistant"):
                st.write(bot_response)
            
            st.markdown("---")
    else:
        st.info("No chat history available")

# ---------------------- Main App ----------------------
def main_app():
    sidebar_menu()
    
    # Route to appropriate page
    if st.session_state.current_page == "chatbot":
        chatbot_page()
    elif st.session_state.current_page == "profile":
        profile_page()
    elif st.session_state.current_page == "expenses":
        expense_tracker_page()
    elif st.session_state.current_page == "investments":
        investment_page()
    elif st.session_state.current_page == "tax":
        tax_calculator_page()
    elif st.session_state.current_page == "history":
        history_page()
    else:
        chatbot_page()

# ---------------------- Main ----------------------
init_db()

if st.session_state.logged_in:
    main_app()
else:
    login_page()
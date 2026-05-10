import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from scipy import stats
import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

# ---------------------------------------------------------
# SETUP & CUSTOM STYLING (Professional Light Mode)
# ---------------------------------------------------------
st.set_page_config(page_title="Factory Intelligence Dashboard", layout="wide")

# Custom CSS for a unique look without hiding core Streamlit features
st.markdown("""
    <style>
    /* Professional Slate-themed Manager Guide (Not Blue) */
    .manager-box {
        background-color: #f8f9fa;
        border-left: 5px solid #d4af37; /* Gold accent */
        padding: 20px;
        border-radius: 5px;
        margin-bottom: 25px;
        color: #333;
        font-size: 0.95rem;
    }
    .manager-title {
        font-weight: bold;
        color: #d4af37;
        text-transform: uppercase;
        margin-bottom: 10px;
        display: block;
    }

    /* Self-Test Card Styling */
    .test-card {
        background-color: white;
        border: 1px solid #e0e0e0;
        padding: 15px;
        border-radius: 8px;
        margin-bottom: 10px;
        box-shadow: 2px 2px 5px rgba(0,0,0,0.02);
    }
    
    /* Clean Metrics */
    [data-testid="stMetricValue"] {
        color: #2c3e50 !important;
    }
    </style>
""", unsafe_allow_html=True)

# Database Connection Logic
load_dotenv(override=True)
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

if not NEO4J_URI:
    try:
        NEO4J_URI = st.secrets["NEO4J_URI"]
        NEO4J_USER = st.secrets["NEO4J_USER"]
        NEO4J_PASSWORD = st.secrets["NEO4J_PASSWORD"]
    except:
        pass

if not NEO4J_PASSWORD or not NEO4J_URI:
    st.error("CRITICAL ERROR: Credentials missing. Check .env or Secrets.")
    st.stop()

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

driver = get_driver()

def run_query(query, parameters=None):
    with driver.session() as session:
        result = session.run(query, parameters)
        return pd.DataFrame([r.data() for r in result])

# ---------------------------------------------------------
# NAVIGATION
# ---------------------------------------------------------
st.sidebar.title("Level 6 Aditi Mehta")
page = st.sidebar.radio("Go to", [
    "Self-Test", 
    "1. Project Overview", 
    "2. Station Load", 
    "3. Capacity Tracker", 
    "4. Worker Coverage",
    "5. Predictive Forecast"
])

# Professional Light Theme for Charts
def apply_chart_theme(fig):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        colorway=["#2c3e50", "#27ae60", "#f39c12", "#e74c3c", "#8e44ad"],
        font=dict(family="Arial, sans-serif", size=12, color="#333"),
        margin=dict(l=10, r=10, t=50, b=10)
    )
    return fig

# ---------------------------------------------------------
# PAGE LOGIC
# ---------------------------------------------------------

if page == "Self-Test":
    st.title("System Diagnostic Report")
    st.write("Validation of Neo4j Graph Architecture and Data Integrity.")
    
    def run_self_test_internal(driver):
        checks = []
        try:
            with driver.session() as s:
                s.run("RETURN 1")
            checks.append(("Database Connection", "Alive", True, 3))
        except:
            checks.append(("Database Connection", "Offline", False, 3))
            return checks
        with driver.session() as s:
            res = s.run("MATCH (n) RETURN count(n) AS c").single()
            checks.append(("Node Population", f"{res['c']} (Min 50)", res['c'] >= 50, 3))
            res = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
            checks.append(("Relationship Density", f"{res['c']} (Min 100)", res['c'] >= 100, 3))
            res = s.run("CALL db.labels() YIELD label RETURN count(label) AS c").single()
            checks.append(("Schema Complexity (Labels)", f"{res['c']} (Min 6)", res['c'] >= 6, 3))
            res = s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN count(relationshipType) AS c").single()
            checks.append(("Schema Complexity (Types)", f"{res['c']} (Min 8)", res['c'] >= 8, 3))
            res = s.run("""
                MATCH (p:Project)-[r:SCHEDULED_AT]->(s:Station)
                WHERE r.actual_hours > r.planned_hours * 1.1
                RETURN count(*) AS c
            """).single()
            checks.append(("Variance Calculation", f"{res['c']} Records found", res['c'] > 0, 5))
        return checks

    with st.spinner("Analyzing graph..."):
        results = run_self_test_internal(driver)
    
    total_score = sum([score for _, _, passed, score in results if passed])
    max_score = sum([score for _, _, _, score in results])

    col_score, col_status = st.columns([1, 2])
    col_score.metric("Final Audit Score", f"{total_score}/{max_score}")
    
    st.write("Detailed Check Results:")
    for label, status, passed, score in results:
        color = "#27ae60" if passed else "#e74c3c"
        st.markdown(f"""
            <div class="test-card">
                <span style="color: {color}; font-weight: bold;">[{'PASS' if passed else 'FAIL'}]</span> 
                <b>{label}</b>: {status} <span style="float: right;">{score if passed else 0}/{score} pts</span>
            </div>
        """, unsafe_allow_html=True)

elif page == "1. Project Overview":
    st.title("Project Overview")
    st.markdown("""<div class="manager-box">
        <span class="manager-title">Manager Guide</span>
        This dashboard monitors the fiscal and temporal health of active fabrication projects. 
        Focus on Variance Percent: Values above 0% indicate projects exceeding budget/schedule. 
        Negative values represent early completion.
    </div>""", unsafe_allow_html=True)
    
    query = """
    MATCH (p:Project)
    OPTIONAL MATCH (p)-[r:SCHEDULED_AT]->(:Station)
    OPTIONAL MATCH (p)-[:PRODUCES]->(pr:Product)
    RETURN p.name AS Project, sum(r.planned_hours) AS Planned_Hours, 
           sum(r.actual_hours) AS Actual_Hours, collect(DISTINCT pr.type) AS Products
    """
    df = run_query(query)
    if not df.empty:
        df['Variance %'] = ((df['Actual_Hours'] - df['Planned_Hours']) / df['Planned_Hours'] * 100).round(2)
        df['Products'] = df['Products'].apply(lambda x: ", ".join(x))
        c1, c2, c3 = st.columns(3)
        c1.metric("Active Projects", len(df))
        c2.metric("Total Labor Budget", f"{df['Planned_Hours'].sum():,.0f}h")
        c3.metric("System-wide Variance", f"{df['Variance %'].mean():.1f}%")
        st.dataframe(df, use_container_width=True)

elif page == "2. Station Load":
    st.title("Station Load (Weekly Timeline)")
    st.markdown("""<div class="manager-box">
        <span class="manager-title">Manager Guide</span>
        Historical workload tracking by station. Significant gaps between Planned and Actual 
        hours often suggest technical friction or operational inefficiencies at that specific node.
    </div>""", unsafe_allow_html=True)
    
    query = """
    MATCH (p:Project)-[r:SCHEDULED_AT]->(s:Station)
    RETURN s.name AS Station, r.week AS Week, sum(r.planned_hours) AS Planned, sum(r.actual_hours) AS Actual
    ORDER BY Week
    """
    df = run_query(query)
    if not df.empty:
        stations = sorted(df['Station'].unique().tolist())
        sel = st.selectbox("Select Station for Focus:", ["All Stations"] + stations)
        plot_df = df if sel == "All Stations" else df[df['Station'] == sel]
        df_melt = plot_df.melt(id_vars=["Station", "Week"], value_vars=["Planned", "Actual"], var_name="Metric", value_name="Hours")
        fig = px.bar(df_melt, x="Week", y="Hours", color="Metric", barmode="group", title=f"Operational Load: {sel}")
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)

elif page == "3. Capacity Tracker":
    st.title("Factory Capacity vs Demand")
    st.markdown("""<div class="manager-box">
        <span class="manager-title">Manager Guide</span>
        Workforce optimization data. The Deficit column is critical: positive numbers show 
        available slack, while negative (red) numbers indicate labor shortfalls requiring 
        intervention (overtime or temporary hiring).
    </div>""", unsafe_allow_html=True)
    
    query = """
    MATCH (wk:Week)-[c:HAS_CAPACITY]->()
    RETURN wk.name AS Week, c.own AS Own_Hours, c.hired AS Hired, c.overtime AS Overtime, c.deficit AS Deficit
    ORDER BY Week
    """
    df = run_query(query)
    if not df.empty:
        df['Capacity'] = df['Own_Hours'] + df['Hired'] + df['Overtime']
        df['Demand'] = df['Capacity'] - df['Deficit']
        def highlight(val): return 'color: #e74c3c; font-weight: bold;' if val < 0 else ''
        st.dataframe(df.style.map(highlight, subset=['Deficit']), use_container_width=True)

elif page == "4. Worker Coverage":
    st.title("Worker Coverage Matrix")
    query = """
    MATCH (w:Worker), (s:Station)
    WHERE s.name IS NOT NULL
    OPTIONAL MATCH (w)-[r:CAN_COVER|WORKS_AT]->(s)
    RETURN w.name AS Worker, s.name AS Station, count(r) > 0 AS Status
    """
    df = run_query(query)
    if not df.empty:
        covered = df[df['Status'] == True]
        counts = covered['Station'].value_counts()
        spofs = counts[counts == 1].index.tolist()
        if spofs:
            st.error(f"Alert: Single Point of Failure detected for stations: {', '.join(spofs)}")
        matrix = pd.crosstab(index=df['Worker'], columns=df['Station'], values=df['Status'], aggfunc='max').fillna(False)
        st.dataframe(matrix.replace({True: "Qualified", False: "-"}), use_container_width=True)

elif page == "5. Predictive Forecast":
    st.title("Week 9 Manufacturing Risk Forecast")
    st.write("Linear regression modeling applied to historical station performance to predict upcoming bottlenecks.")
    
    query = """
    MATCH (p:Project)-[r:SCHEDULED_AT]->(s:Station)
    RETURN s.name AS Station, r.week AS Week, r.actual_hours AS Actual
    """
    df = run_query(query)
    if not df.empty:
        df['W_Num'] = df['Week'].str.extract('(\d+)').astype(int)
        stations = sorted(df['Station'].unique())
        sel = st.selectbox("Station Selection:", stations)
        s_df = df[df['Station'] == sel].groupby('W_Num')['Actual'].sum().reset_index()
        x, y = s_df['W_Num'].values, s_df['Actual'].values
        m, b, r, p, err = stats.linregress(x, y)
        w9 = m * 9 + b
        
        # Plot
        weeks = np.array(range(1, 10))
        preds = m * weeks + b
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=weeks, y=preds, mode='lines', name='Trajectory', line=dict(dash='dash', color='#2c3e50')))
        fig.add_trace(go.Scatter(x=x, y=y, mode='markers+lines', name='History', marker=dict(color='#27ae60')))
        st.plotly_chart(apply_chart_theme(fig), use_container_width=True)
        st.info(f"Forecast for Week 9 ({sel}): {w9:.1f} hours.")
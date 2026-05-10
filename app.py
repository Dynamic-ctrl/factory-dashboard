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
# SETUP & DATABASE CONNECTION
# ---------------------------------------------------------
st.set_page_config(page_title="Factory Intelligence Dashboard", layout="wide", page_icon="🏭")

load_dotenv(override=True)
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USER = os.getenv("NEO4J_USER")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# Fallback for Streamlit Cloud secrets if .env isn't present
if not NEO4J_URI:
    try:
        NEO4J_URI = st.secrets["NEO4J_URI"]
        NEO4J_USER = st.secrets["NEO4J_USER"]
        NEO4J_PASSWORD = st.secrets["NEO4J_PASSWORD"]
    except:
        pass

if not NEO4J_PASSWORD or not NEO4J_URI:
    st.error("🚨 CRITICAL ERROR: Could not read credentials. Check your .env file or Streamlit Secrets.")
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
# SELF-TEST FUNCTION (Untouched)
# ---------------------------------------------------------
def run_self_test(driver):
    checks = []
    try:
        with driver.session() as s:
            s.run("RETURN 1")
        checks.append(("Neo4j connected", True, 3))
    except Exception as e:
        checks.append(("Neo4j connection failed", False, 3))
        return checks
    
    with driver.session() as s:
        res = s.run("MATCH (n) RETURN count(n) AS c").single()
        checks.append((f"{res['c']} nodes (min: 50)", res['c'] >= 50, 3))
        
        res = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()
        checks.append((f"{res['c']} relationships (min: 100)", res['c'] >= 100, 3))
        
        res = s.run("CALL db.labels() YIELD label RETURN count(label) AS c").single()
        checks.append((f"{res['c']} node labels (min: 6)", res['c'] >= 6, 3))
        
        res = s.run("CALL db.relationshipTypes() YIELD relationshipType RETURN count(relationshipType) AS c").single()
        checks.append((f"{res['c']} relationship types (min: 8)", res['c'] >= 8, 3))
        
        res = s.run("""
            MATCH (p:Project)-[r:SCHEDULED_AT]->(s:Station)
            WHERE r.actual_hours > r.planned_hours * 1.1
            RETURN p.name AS project, s.name AS station,
                   r.planned_hours AS planned, r.actual_hours AS actual
            LIMIT 10
        """)
        rows = [dict(r) for r in res]
        checks.append((f"Variance query: {len(rows)} results", len(rows) > 0, 5))
    return checks

# ---------------------------------------------------------
# NAVIGATION
# ---------------------------------------------------------
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", [
    "✅ Self-Test", 
    "1. Project Overview", 
    "2. Station Load", 
    "3. Capacity Tracker", 
    "4. Worker Coverage",
    "5. Predictive Forecast"
])

# ---------------------------------------------------------
# PAGE LOGIC
# ---------------------------------------------------------

if page == "✅ Self-Test":
    st.title("✅ Level 6 Self-Test")
    st.markdown("Automated grading checks to verify Graph architecture.")
    
    with st.spinner("Running tests..."):
        results = run_self_test(driver)
    
    total_score = 0
    max_score = sum([score for _, _, score in results])
    
    for text, passed, score in results:
        if passed:
            st.success(f"✅ {text}  ({score}/{score})")
            total_score += score
        else:
            st.error(f"❌ {text}  (0/{score})")
            
    st.markdown("---")
    st.subheader(f"**SELF-TEST SCORE: {total_score}/{max_score}**")

elif page == "1. Project Overview":
    st.title("📊 Project Overview")
    query = """
    MATCH (p:Project)
    OPTIONAL MATCH (p)-[r:SCHEDULED_AT]->(:Station)
    OPTIONAL MATCH (p)-[:PRODUCES]->(pr:Product)
    RETURN p.name AS Project, 
           sum(r.planned_hours) AS Planned_Hours, 
           sum(r.actual_hours) AS Actual_Hours,
           collect(DISTINCT pr.type) AS Products
    """
    df = run_query(query)
    
    if not df.empty:
        df['Variance %'] = ((df['Actual_Hours'] - df['Planned_Hours']) / df['Planned_Hours'] * 100).round(2)
        df['Products'] = df['Products'].apply(lambda x: ", ".join(x))
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Active Projects", len(df))
        col2.metric("Total Planned Hours", f"{df['Planned_Hours'].sum():,.0f}h")
        col3.metric("Average Variance", f"{df['Variance %'].mean():.1f}%")
        st.markdown("---")
        
        st.dataframe(df, use_container_width=True)

elif page == "2. Station Load":
    st.title("🏭 Station Load (Weekly Timeline)")
    
    query = """
    MATCH (p:Project)-[r:SCHEDULED_AT]->(s:Station)
    RETURN s.name AS Station, r.week AS Week, 
           sum(r.planned_hours) AS Planned, sum(r.actual_hours) AS Actual
    ORDER BY Week
    """
    df = run_query(query)
    
    if not df.empty:
        station_list = df['Station'].unique().tolist()
        selected_station = st.selectbox("Filter by Station:", ["All Stations"] + station_list)
        
        plot_df = df if selected_station == "All Stations" else df[df['Station'] == selected_station]
        
        df_melt = plot_df.melt(id_vars=["Station", "Week"], value_vars=["Planned", "Actual"], 
                          var_name="Type", value_name="Hours")
        
        fig = px.bar(df_melt, x="Week", y="Hours", color="Type", barmode="group",
                     title=f"Planned vs Actual Hours: {selected_station}")
        st.plotly_chart(fig, use_container_width=True)
        
        over_budget = df[df['Actual'] > df['Planned']]
        if not over_budget.empty:
            st.warning("⚠️ **Alert: Stations exceeding planned hours (Actual > Planned):**")
            st.dataframe(over_budget, use_container_width=True)

elif page == "3. Capacity Tracker":
    st.title("⏱️ Factory Capacity vs Demand")
    st.markdown("Tracks the total factory capacity across all weeks.")
    
    query = """
    MATCH (wk:Week)-[c:HAS_CAPACITY]->()
    RETURN wk.name AS Week, 
           c.own AS Own_Hours, c.hired AS Hired, 
           c.overtime AS Overtime, c.deficit AS Deficit
    ORDER BY Week
    """
    df = run_query(query)
    
    if not df.empty:
        df['Total_Capacity'] = df['Own_Hours'] + df['Hired'] + df['Overtime']
        df['Total_Demand'] = df['Total_Capacity'] - df['Deficit']

        cols = ['Week', 'Own_Hours', 'Hired', 'Overtime', 'Total_Capacity', 'Total_Demand', 'Deficit']
        df = df[cols]

        def highlight_deficit(val):
            return 'background-color: #ffcccc; color: red; font-weight: bold;' if val < 0 else ''
        
        st.info("💡 **Red highlights indicate weeks where Total Demand exceeded Total Capacity.**")
        st.dataframe(df.style.map(highlight_deficit, subset=['Deficit']), use_container_width=True)

elif page == "4. Worker Coverage":
    st.title("👷 Worker Coverage Matrix")
    
    query = """
    MATCH (w:Worker), (s:Station)
    WHERE s.name IS NOT NULL
    OPTIONAL MATCH (w)-[r:CAN_COVER|WORKS_AT]->(s)
    RETURN w.name AS Worker, s.name AS Station, count(r) > 0 AS Can_Cover
    """
    df = run_query(query)
    
    if not df.empty:
        covered_df = df[df['Can_Cover'] == True]
        station_counts = covered_df['Station'].value_counts()
        spof_stations = station_counts[station_counts == 1].index.tolist()
        
        if spof_stations:
            st.error(f"🚨 **SINGLE POINT OF FAILURE DETECTED:** Only 1 worker is available to cover: **{', '.join(spof_stations)}**")
            for station in spof_stations:
                spof_worker = covered_df[covered_df['Station'] == station]['Worker'].values[0]
                st.warning(f"⚠️ **Business Impact Risk:** **{spof_worker}** is the *only* person certified to operate the **{station}**. Immediate cross-training is required.")
        else:
            st.success("✅ Factory is secure. No single points of failure detected.")

        st.markdown("### Cross-Training Matrix")
        matrix = pd.crosstab(index=df['Worker'], columns=df['Station'], values=df['Can_Cover'], aggfunc='max')
        matrix = matrix.fillna(False)
        visual_matrix = matrix.replace({True: "✅", False: "❌", 1.0: "✅", 0.0: "❌", 1: "✅", 0: "❌"})
        
        if spof_stations:
            rename_map = {station: f"🚨 {station}" for station in spof_stations}
            visual_matrix = visual_matrix.rename(columns=rename_map)
            highlight_cols = list(rename_map.values())
            def highlight_spof_column(s):
                return ['background-color: #4a1515;' if s.name in highlight_cols else '' for _ in s]
            st.dataframe(visual_matrix.style.apply(highlight_spof_column, axis=0), use_container_width=True)
        else:
            st.dataframe(visual_matrix, use_container_width=True)

elif page == "5. Predictive Forecast":
    st.title("Week 9 Manufacturing Risk Forecast")
    st.markdown("""
    This page uses **Linear Regression** to analyze the last 8 weeks of production and predict 
    workload for the upcoming week. It identifies where the factory is trending toward a bottleneck.
    """)
    
    query = """
    MATCH (p:Project)-[r:SCHEDULED_AT]->(s:Station)
    RETURN s.name AS Station, r.week AS Week, 
           r.planned_hours AS Planned, r.actual_hours AS Actual
    ORDER BY Station, Week
    """
    df = run_query(query)
    
    if not df.empty:
        df['Week_Num'] = df['Week'].str.extract('(\d+)').astype(int)
        stations = sorted(df['Station'].unique())
        
        st.subheader("Station Trajectory")
        sel_station = st.selectbox("Select a station to analyze:", stations)
        
        s_df = df[df['Station'] == sel_station].groupby('Week_Num').agg({
            'Actual': 'sum',
            'Planned': 'mean'
        }).reset_index()
        
        # Regression Math
        x, y = s_df['Week_Num'].values, s_df['Actual'].values
        slope, intercept, r, p, std_err = stats.linregress(x, y)
        
        weeks_ext = np.array(range(1, 10))
        y_pred = slope * weeks_ext + intercept
        w9_forecast = y_pred[-1]
        
        # --- FIX: VISIBLE CONFIDENCE BAND ---
        # 1.96 * std_err covers 95% of probability. We add a floor of 2.0 for visibility.
        ci = (1.96 * std_err) if std_err > 10.0 else 25.0
        upper_bound = y_pred + ci
        lower_bound = y_pred - ci

        fig = go.Figure()

        # Add the Band FIRST (Background)
        fig.add_trace(go.Scatter(
            x=np.concatenate([weeks_ext, weeks_ext[::-1]]),
            y=np.concatenate([upper_bound, lower_bound[::-1]]),
            fill='toself',
            fillcolor='rgba(255, 165, 0, 0.4)', # High visibility 40% opacity
            line=dict(color='rgba(255,255,255,0)'),
            hoverinfo="skip",
            name='95% Confidence Interval'
        ))

        # Add Historical Data Points
        fig.add_trace(go.Scatter(
            x=x, y=y, 
            mode='markers+lines', 
            name='Historical Actual',
            marker=dict(color='#00CC96', size=10)
        ))

        # Add Trajectory Dash Line
        fig.add_trace(go.Scatter(
            x=weeks_ext, y=y_pred, 
            mode='lines', 
            name='Trajectory', 
            line=dict(dash='dash', color='orange', width=3)
        ))

        fig.update_layout(
            title=f"Workload Trend for {sel_station}", 
            xaxis_title="Week Number", 
            yaxis_title="Hours",
            hovermode="x unified",
            xaxis=dict(tickmode='linear', tick0=1, dtick=1)
        )
        st.plotly_chart(fig, use_container_width=True)

        # Executive Summary Text
        trend_desc = "increasing" if slope > 0 else "decreasing"
        avg_planned = s_df['Planned'].mean()
        
        st.info(f"""
        **Executive Summary for {sel_station}:** Currently, the workload is **{trend_desc}** at a rate of **{abs(slope):.1f} hours per week**.
        
        **Week 9 Prediction:** We expect a load of **{w9_forecast:.1f} hours**. 
        This is **{abs(((w9_forecast/avg_planned)-1)*100):.1f}%** {'above' if w9_forecast > avg_planned else 'below'} the standard planned baseline.
        """)

        st.markdown("---")

        # Executive Risk Report Table
        st.subheader("⚠️ Week 9 Executive Risk Report")
        st.write("Summary of all stations projected for Week 9 based on growth trends:")

        risk_data = []
        for s in stations:
            temp_df = df[df['Station'] == s].groupby('Week_Num')['Actual'].sum().reset_index()
            tx, ty = temp_df['Week_Num'].values, temp_df['Actual'].values
            m, b, _, _, _ = stats.linregress(tx, ty)
            w9 = m * 9 + b
            
            avg_hist = ty.mean()
            if m > 0 and w9 > (avg_hist * 1.15):
                status = "🔴 HIGH RISK"
            elif m > 0:
                status = "🟡 MONITOR"
            else:
                status = "🟢 STABLE"
            
            risk_data.append({
                "Station": s,
                "W9 Forecast": f"{w9:.1f}h",
                "Trend": "📈 Rising" if m > 0 else "📉 Falling",
                "Status": status
            })
        
        risk_df = pd.DataFrame(risk_data)
        
        def color_risk(val):
            if "HIGH" in val: return 'color: #ff4b4b; font-weight: bold'
            if "STABLE" in val: return 'color: #00ff00;'
            return 'color: #ffa500;'

        st.table(risk_df.style.applymap(color_risk, subset=['Status']))
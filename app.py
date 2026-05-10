import streamlit as st
import pandas as pd
import plotly.express as px
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

if not NEO4J_PASSWORD or not NEO4J_URI:
    st.error("🚨 CRITICAL ERROR: Could not read credentials from the .env file. Please check your formatting.")
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
# SELF-TEST FUNCTION (Untouched - Keeps your 20/20)
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
    "4. Worker Coverage"
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
        
        # Deficit is negative in CSV if there is a shortfall. 
        # So Capacity - Deficit = Total Demand (e.g., 480 - (-132) = 612)
        df['Total_Demand'] = df['Total_Capacity'] - df['Deficit']

       
        cols = ['Week', 'Own_Hours', 'Hired', 'Overtime', 'Total_Capacity', 'Total_Demand', 'Deficit']
        df = df[cols]

        def highlight_deficit(val):
            # Highlight red if the factory was short on hours (negative deficit)
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
        # 1. SPOF Logic (Filter to True coverage, then count)
        covered_df = df[df['Can_Cover'] == True]
        station_counts = covered_df['Station'].value_counts()
        spof_stations = station_counts[station_counts == 1].index.tolist()
        
        if spof_stations:
            st.error(f"🚨 **SINGLE POINT OF FAILURE DETECTED:** Only 1 worker is available to cover: **{', '.join(spof_stations)}**")
            
            
            for station in spof_stations:
                # Find exactly WHO the single worker is for this station
                spof_worker = covered_df[covered_df['Station'] == station]['Worker'].values[0]
                
                st.warning(f"⚠️ **Business Impact Risk:** **{spof_worker}** is the *only* person certified to operate the **{station}**. If {spof_worker} calls in sick, takes vacation, or leaves the company, this machine completely shuts down and halts production. Immediate cross-training is required.")
        else:
            st.success("✅ Factory is secure. No single points of failure detected.")

        st.markdown("### Cross-Training Matrix")
        
        # 2. Build the visual Matrix using Pandas crosstab
        matrix = pd.crosstab(index=df['Worker'], columns=df['Station'], values=df['Can_Cover'], aggfunc='max')
        
        # 3. Convert True/False into visual icons
        matrix = matrix.fillna(False)
        visual_matrix = matrix.replace({True: "✅", False: "❌", 1.0: "✅", 0.0: "❌", 1: "✅", 0: "❌"})
        
        # 4. Highlight the SPOF column directly in the matrix
        if spof_stations:
            rename_map = {station: f"🚨 {station}" for station in spof_stations}
            visual_matrix = visual_matrix.rename(columns=rename_map)
            
            highlight_cols = list(rename_map.values())
            def highlight_spof_column(s):
                return ['background-color: #4a1515;' if s.name in highlight_cols else '' for _ in s]
            
            st.dataframe(visual_matrix.style.apply(highlight_spof_column, axis=0), use_container_width=True)
        else:
            st.dataframe(visual_matrix, use_container_width=True)
import streamlit as st

st.set_page_config(page_title="Housing Price Tracker", page_icon="🏢", layout="wide")

home_page = st.Page("home.py", title="Home", icon="🏠", default=True)
config_batch = st.Page("config/config_batch.py", title="Batch Criteria", icon="🎯")
config_notif = st.Page("config/config_notif.py", title="Global Notifications", icon="🌍")
res_batch = st.Page("reports/results_batch.py", title="Market Dynamics", icon="📈")
res_notif = st.Page("reports/results_notif.py", title="Opportunity Alerts", icon="🔔")
sys_settings = st.Page("monitoring/monitoring_sys_settings.py", title="Settings", icon="🔧")
sys_logs = st.Page("monitoring/monitoring_logs.py", title="Logs", icon="📋")
sys_errors = st.Page("monitoring/monitoring_errors.py", title="System Errors", icon="⚠️")

pg = st.navigation(
    {
        "Overview": [home_page],
        "Analysis": [res_batch, res_notif],
        "Configuration": [config_batch, config_notif],
        "Maintenance": [sys_settings, sys_logs, sys_errors],
    }, 
)
pg.run()
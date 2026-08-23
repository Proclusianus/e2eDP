from datetime import datetime


from zoneinfo import ZoneInfo
import streamlit as st
from streamlit_javascript import st_javascript


def get_browser_timezone() -> str:
    tz_name = st_javascript("""Intl.DateTimeFormat().resolvedOptions().timeZone""", key="browser_timezone_detector")
    if tz_name:
        st.session_state.user_tz = tz_name

def format_dt_to_local(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    if not dt:
        return "N/A"
    
    tz_name = st.session_state.get("user_tz", "UTC")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        
    try:
        local_dt = dt.astimezone(ZoneInfo(tz_name))
        return local_dt.strftime(format_str)
    except Exception:
        return dt.strftime(format_str)
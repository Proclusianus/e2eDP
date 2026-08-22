from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import math


import streamlit as st


from database.db_manager import DBManager
from database.models import LogStatus, TimeUnit, SearchTargetType, SearchTarget, RawExecLog, CleanExecLog, AnalyticsExecLog, AnomalyAnalysis, BatchAnalysis
from database.exceptions import DatabaseError


### A small trick to persist widget values between page switching - when widgets are hidden they remove their session_state data
widget_names = {'logs_sc_gnr_search_all', 'logs_showing_soft_deleted', 'logs_sc_gnr_select', 'logs_types_select', 
                'logs_completion_status', 'logs_time_amount', 'logs_time_unit', 'logs_sortby', 'logs_page_limit_amount'}
if "logs_first_page_open_in_session" in st.session_state: # Page must've been loaded before...
    if 'logs_page_change_checker' not in st.session_state: # Page is being opened again...
        for n in widget_names:
            st.session_state[f"{n}"] = st.session_state[f"{n}_store"]
    else: # User is on-page...
        for k, v in st.session_state.items():
            if k in widget_names:
                st.session_state[f"{k}_store"] = v
# Invisible element - used to check if user enters this page from another
with st.container():
    st.markdown(
        f"""<style>div[data-testid="stVerticalBlock"] > div:has(input[aria-label="logs_page_change_checker"]) {{display: none;}}</style>""",
        unsafe_allow_html=True,
    )
    st.checkbox('logs_page_change_checker', key='logs_page_change_checker', label_visibility="collapsed")

#############
# FUNCTIONS #
#############
def get_search_targets_names(db, select_inactive: bool=False) -> list[SearchTarget]:
    try:
        gnr_list = [SearchTarget(name, SearchTargetType.GNR) for name in get_cached_gnr_names(db, select_inactive)]
        sc_list = [SearchTarget(name, SearchTargetType.SC) for name in get_cached_sc_names(db, select_inactive)] 
    except DatabaseError as e:
        st.toast("Obtaining Search Target Names Failed!", icon="❌", duration=8)
        return []
    all_st = gnr_list + sc_list
    all_st.sort(key=lambda x: x.search_target_name.casefold())

    return all_st

def get_pages_number_list() -> list[int]:
    pg_amount = math.ceil(st.session_state.logs_data_count / st.session_state.logs_page_limit_amount)
    return range(1, max(1, pg_amount)+1)

def are_there_any_search_targets(db) -> bool:
    sc = db.get_search_criteria_count()
    gnr = db.get_global_notification_rules_count()
    if sc == 0 and gnr == 0:
        return False 
    else:
        return True # Failed reading DB, let the code continue to draw the UI
                    # Or there are STs and the code should continue

def validate_inputs() -> list[str]:
    error_msgs = []
    s = st.session_state
    if not s.logs_sc_gnr_search_all:
        if len(s.logs_sc_gnr_select) == 0:
            error_msgs.append("You must select at least one search target!  ")
    if len(s.logs_types_select) == 0:
        error_msgs.append("You must select at least one log type!")

    return error_msgs

def draw_execlog_card(log: RawExecLog | CleanExecLog | AnalyticsExecLog):
    if isinstance(log, AnalyticsExecLog):
        analysis_name = "Unknown!"
        if log.batch_analysis_id:
            batch_analyses: list[BatchAnalysis] = get_batch_analysis_definitions(db)
            if not batch_analyses:
                st.toast("Obtaining Analysis Data Failed!", icon="❌", duration=8)
            else:
                for ba in batch_analyses:
                    if ba.id == log.batch_analysis_id:
                        analysis_name = ba.name_en
                        break;
        elif log.anomaly_analysis_id:
            anomaly_analyses: list[AnomalyAnalysis] = get_anomaly_analysis_definitions(db)
            if not anomaly_analyses:
                st.toast("Obtaining Analysis Data Failed!", icon="❌", duration=8)
            else:
                for aa in anomaly_analyses:
                    if aa.id == log.anomaly_analysis_id:
                        analysis_name = aa.name_en
                        break;

    status_style = {
        "SUCCESS": {"color": "green", "icon": "✅"},
        "FAILED": {"color": "red", "icon": "🔴"},
        "RUNNING": {"color": "blue", "icon": "🔄"},
        "WARNING": {"color": "orange", "icon": "⚠️"}
    }.get(log.status, {"color": "gray", "icon": "⚪"})

    duration = "N/A"
    if log.finished_at and log.started_at:
        diff = log.finished_at - log.started_at
        duration = f"{diff.total_seconds():.1f}s"
    elif log.status == "RUNNING":
        duration = "In progress..."

    if isinstance(log, RawExecLog):
        layer_name, layer_color = "RAW", "#cd7f32"
    elif isinstance(log, CleanExecLog):
        layer_name, layer_color = "CLEAN", "#c0c0c0"
    else:
        layer_name, layer_color = "ANALYTICS", "#ffd700"

    with st.container(border=True):
        c1, c2 = st.columns([1, 4])
        with c1:
            st.markdown(f"### {status_style['icon']}")
            st.caption(f":{status_style['color']}[{log.status}]")
        with c2:
            st.markdown(f"**{log.job_name.upper()}**")
            st.write(f"Search Target: `{log.target_display_name}`")

        col_time, col_duration, col_info = st.columns(3)
        with col_time:
            st.caption(f"📅 **Started:** {log.started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        with col_duration:
            st.caption(f"⏱️ **Duration:** {duration}")
        with col_info:
            st.markdown(f"🏷️ **Layer:** <span style='color:{layer_color}; font-weight:bold;'>{layer_name}</span>", unsafe_allow_html=True)

        if isinstance(log, AnalyticsExecLog):
            if log.batch_analysis_id:
                st.caption(f"📈 **Batch Analysis Method:** {analysis_name}")
            elif log.anomaly_analysis_id:
                st.caption(f"🔔 **Anomaly Analysis Method:** {analysis_name}")

        with st.expander("🛠️ Technical Details & Trace"):
            tech_c1, tech_c2 = st.columns(2)
            with tech_c1:
                st.write(f"**Log ID:** `{log.id}`")
                if hasattr(log, 'batch_id'): st.write(f"**Batch ID:** `{log.batch_id}`")
            with tech_c2:
                if isinstance(log, CleanExecLog):
                    st.write(f"**Raw Listing ID:** `{log.raw_listing_id}`")
                if isinstance(log, AnalyticsExecLog):
                    if log.clean_listing_id: st.write(f"**Clean Listing ID:** `{log.clean_listing_id}`")
                    if log.global_rule_id: st.write(f"**Global Rule ID:** `{log.global_rule_id}`")

            if log.error_message:
                st.error(f"**Error Message:**\n{log.error_message}")

#############
# CALLBACKS #
#############
def get_data_callback(update_pg_number: bool = True):
    error_msgs = validate_inputs()
    if len(error_msgs) == 1:
        st.toast(error_msgs[0], icon="❌", duration=8)
    elif len(error_msgs) > 1:
        st.toast("\n".join([e for e in error_msgs]), icon="❌", duration=8)
    else:
        old_val = st.session_state.logs_page_number
        if update_pg_number: st.session_state.logs_page_number = 1
        if update_session_data():
            #st.toast("Obtaining Log Data Successful!", icon="✅", duration=8)
            pass
        else:
            st.toast("Obtaining Log Data Failed!", icon="❌", duration=8)
            st.session_state.logs_page_number = old_val

def change_page_callback():
    get_data_callback(False)

def per_page_callback():
    if st.session_state.logs_page_limit_amount > 200:
        st.toast("You can only select a maximum of 200 results per page!", icon="❌", duration=8)
        st.session_state.logs_page_limit_amount = 200
    elif st.session_state.logs_page_limit_amount < 1:
        st.toast("You must select at least 1 result per page!", icon="❌", duration=8)
        st.session_state.logs_page_limit_amount = 1
    else:
        get_data_callback()

def time_since_callback():
    if st.session_state.logs_time_amount < 1:
        st.toast("Time amount must be > 0!", icon="❌", duration=8)
        st.session_state.logs_time_amount = 1

###########################
# Cached Data & Fragments #
###########################
@st.cache_resource
def get_db():
    return DBManager()
db = get_db()

@st.cache_resource
def get_batch_analysis_definitions(_db):
    return _db.get_batch_analysis_definitions()
@st.cache_resource
def get_anomaly_analysis_definitions(_db):
    return _db.get_anomaly_analysis_definitions()

@st.cache_resource(ttl=60)
def get_cached_gnr_names(_db, select_inactive: bool) -> list[str]:
    return _db.get_all_gnr_names(select_inactive)
@st.cache_resource(ttl=60)
def get_cached_sc_names(_db, select_inactive: bool) -> list[str]:
    return _db.get_all_sc_names(select_inactive)

def update_session_data() -> bool:
    """Updates session data (logs and log count). On success returns True, on failure False"""
    count, data = get_logs_and_log_count()
    st.session_state.logs_data = data
    if count == -1 and data == []:
        st.session_state.logs_data_count = 0
        return False
    else:
        st.session_state.logs_data_count = count
        return True

def get_logs_and_log_count() -> tuple[int, list[RawExecLog | CleanExecLog | AnalyticsExecLog]]:
    ss = st.session_state
    
    # Clean names
    selected_targets_objects = ss.get("logs_sc_gnr_select", [])
    cleaned_names = [
        t.search_target_name.replace(' [ARCHIVED]', '').replace(' [PAUSED]', '').strip()
        for t in selected_targets_objects
    ]
    # Status
    raw_status = ss.get("logs_completion_status", "Any")
    if raw_status == "Any":
        final_status = LogStatus.ANY
    else:
        final_status = LogStatus(raw_status.upper())
    # Time
    raw_unit = ss.get("logs_time_unit", "Hour(s)")
    if raw_unit == "All Time":
        unit_enum = TimeUnit.ALL_TIME
    else:
        unit_key = raw_unit.replace("(s)", "").upper()
        unit_enum = TimeUnit[unit_key]
    # Types (on first loading, all types are selected)
    selected_types = ss.get("logs_types_select", ["Raw", "Clean", "Analytics"])

    return db.get_all_execution_logs(
        log_status=final_status,
        target_names=cleaned_names,
        limit_records=ss.get("logs_page_limit_amount", 50),
        pg_number=ss.get("logs_page_number", 1),
        unit_of_time=unit_enum,
        time_amount=ss.get("logs_time_amount", 1),
        sort_by=ss.get("logs_sortby", "Newest"),
        select_inactive=ss.get("logs_showing_soft_deleted", False),
        get_raw="Raw" in selected_types,
        get_clean="Clean" in selected_types,
        get_analytics="Analytics" in selected_types
    )

if "logs_data_count" not in st.session_state:
    st.session_state.logs_data_count = 0
if "logs_data" not in st.session_state:
    st.session_state.logs_data = []
if are_there_any_search_targets(db):
    if "logs_first_page_open_in_session" not in st.session_state:
        st.session_state.logs_first_page_open_in_session = True
        if update_session_data():
            pass
        else:
            st.toast("Obtaining Log Data Failed!", icon="❌", duration=8)
else:
    st.info("👋 Welcome! It looks like you haven't defined any Search Targets yet.")
    st.warning("Monitoring logs is only possible when there is something to monitor.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("🎯 Add Batch Criteria", use_container_width=True):
            st.switch_page("config/config_batch.py")
    with c2:
        if st.button("🌍 Add Global Rule", use_container_width=True):
            st.switch_page("config/config_notif.py")
    st.stop() 

################
# WEBPAGE CODE #
################
st.header("📋 Execution Logs")
st.markdown("This menu allows you to view and filter system execution logs. Listed below are all the logs generated by this application while running its processes.")
st.subheader("Filters:")
with st.container(key="logs_filter_container", border=True, width='content'):
    col_all_st, col0_space, col_sd_st = st.columns([1.0, 0.2, 1.0])
    with col_all_st:
        is_logs_sc_gnr_all = st.checkbox(
            "Search in all search targets?", key="logs_sc_gnr_search_all", value=True, 
            help="If checked, every execution log will be included regardless of which search target it belongs to."
        )
    with col_sd_st:
        is_showing_soft_deleted = st.checkbox(
            "Include inactive search targets' logs?", key="logs_showing_soft_deleted", value=False,
            help="If checked, inactive (disabled or soft-deleted) search targets' logs will be included in the search target name multiselect widget. If searching in all search targets, these targets will also be included in the search."
        )
    col_sc_gnr, col1_space, col_log_type = st.columns([1.0, 0.2, 1.0])
    with col_sc_gnr:
        st.multiselect(
            "Select search criteria/global notification rule:", key="logs_sc_gnr_select",
            options=get_search_targets_names(db, is_showing_soft_deleted), disabled=is_logs_sc_gnr_all, 
            format_func=lambda x: f"{'SC' if x.search_target_type == SearchTargetType.SC else 'GNR'}: {x.search_target_name}"  
        )
    with col_log_type:
        st.multiselect(
            "Select log type(s):", key="logs_types_select",
            options=["Raw", "Clean", "Analytics"], default=["Raw", "Clean", "Analytics"]
        )
    col_lc, col_2, col2_space, col_3, col_4 = st.columns([1.0, 1.0, 0.4, 1.0, 1.0])
    with col_lc:
        select_log_completion = st.selectbox("Log completion status:", key="logs_completion_status", options=["Any"] + [s.value.capitalize() for s in LogStatus], index=0)
    with col_3:
        st.number_input(
            "Time since log recorded:", key="logs_time_amount", value=int(1), step=1, on_change=time_since_callback,
            disabled=(st.session_state.get("logs_time_unit", None) == "All Time")
        )
    with col_4:
        select_log_tu = st.selectbox("Unit of time:", key="logs_time_unit", options=["Minute(s)", "Hour(s)", "Day(s)", "All Time"], index=1)

col_filter, col_refresh, col4_empty = st.columns([1.5, 1.5, 4.0])
with col_filter:
    st.button("🔍 Apply Filters", key="logs_apply_filters", on_click=get_data_callback, width="stretch")
with col_refresh:
    st.button("🔄 Refresh Results", key="logs_refresh", on_click=get_data_callback, width="stretch")
col5_sort, col5_limit, col5_empty = st.columns([1.5, 1.5, 4.0])
with col5_sort:
    st.selectbox("Sort by:", key="logs_sortby", on_change=get_data_callback, options=["Newest", "Oldest", "Execution Time"])
with col5_limit:
    st.number_input("Results per page: (200 max.)", key="logs_page_limit_amount", on_change=per_page_callback, value=int(50), step=1)

st.subheader("Execution Logs List:")
pg_number = st.selectbox("Page:", key="logs_page_number", on_change=change_page_callback, options=get_pages_number_list(), width=80, disabled=st.session_state.get('logs_data', []) == [])
with st.container(border=True):
    if not st.session_state.logs_data:
        st.info("📂 No execution logs found for the selected filters.")
        st.caption("Try adjusting the time range or status filters to see more results.")
    else:
        for row in st.session_state.logs_data:
            draw_execlog_card(row)
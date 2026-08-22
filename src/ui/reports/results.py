from datetime import datetime, timedelta
import math
import traceback


import streamlit as st


from database.db_manager import DBManager
import database.models as dbmodels
from database.exceptions import DatabaseError
from processing.pdf_reporter import PDFReporter

### A small trick to persist widget values between page switching - when widgets are hidden they remove their session_state data
widget_names = {'results_sc_search_all', 'results_showing_soft_deleted', 'results_sc_select', 'results_time_amount', 
                'results_time_unit', 'results_sortby', 'results_page_limit_amount'}
if "results_first_page_open_in_session" in st.session_state: # Page must've been loaded before...
    if 'results_page_change_checker' not in st.session_state: # Page is being opened again...
        for n in widget_names:
            st.session_state[f"{n}"] = st.session_state[f"{n}_store"]
    else: # User is on-page...
        for k, v in st.session_state.items():
            if k in widget_names:
                st.session_state[f"{k}_store"] = v
# Invisible element - used to check if user enters this page from another
with st.container():
    st.markdown(
        f"""<style>div[data-testid="stVerticalBlock"] > div:has(input[aria-label="results_page_change_checker"]) {{display: none;}}</style>""",
        unsafe_allow_html=True,
    )
    st.checkbox('results_page_change_checker', key='results_page_change_checker', label_visibility="collapsed")

#############
# FUNCTIONS #
#############
def get_search_criteria_names(db, select_inactive: bool=False) -> list[dbmodels.SearchTarget]:
    try:
        sc_list = [dbmodels.SearchTarget(name, dbmodels.SearchTargetType.SC) for name in get_cached_sc_names(db, select_inactive)] 
    except DatabaseError as e:
        st.toast("Obtaining Search Criteria Names Failed!", icon="❌", duration=8)
        return []
    sc_list.sort(key=lambda x: x.search_target_name.casefold())

    return sc_list

def get_pages_number_list() -> list[int]:
    pg_amount = math.ceil(st.session_state.results_data_count / st.session_state.results_page_limit_amount)
    return range(1, max(1, pg_amount)+1)

def are_there_any_batches(db) -> bool:
    return (db.get_batches_count() != 0)

def validate_inputs() -> list[str]:
    error_msgs = []
    s = st.session_state
    if not s.results_sc_search_all:
        if len(s.results_sc_select) == 0:
            error_msgs.append("You must select at least one search criteria!")
    return error_msgs

@st.fragment
def draw_batch_card(batch: dbmodels.BatchData, target_map: dict[int, str]):
    target_name = target_map.get(batch.criteria_id, "Unknown Target")
    
    status_colors = {
        "SUCCESS": "🟢",
        "PARTIAL": "🟡",
    }
    status_icon = status_colors.get(batch.status.value, "❓")
    with st.container(border=True):
        col_info, col_time, col_action = st.columns([4, 4, 1.5])
        with col_info:
            st.markdown(f"#### {status_icon} Batch #{batch.id}")
            st.markdown(f"**Target:** {target_name}")
            st.caption(f"Status: {batch.status.value}")
        with col_time:
            start_str = batch.started_at.strftime("%Y-%m-%d %H:%M:%S")
            end_str = batch.finished_at.strftime("%Y-%m-%d %H:%M:%S") if batch.finished_at else "In progress..."
            st.write("**Duration Information:**")
            st.caption(f"📅 Start: {start_str}")
            st.caption(f"🏁 End: {end_str}")
        with col_action:
            st.write("")
            pdf_key = f"pdf_bytes_{batch.id}"
            if st.button("📄 Prepare Report", key=f"btn_prep_{batch.id}", use_container_width=True):
                with st.spinner("🛠️ Crunching data..."):
                    try:
                        reporter = PDFReporter()
                        st.session_state[pdf_key] = reporter.generate_report(batch.id)
                        st.toast("Report is ready for download!", icon="✅")
                    except Exception as e:
                        st.error("Report failed.")
                        db.log_system_error(
                            error_source=dbmodels.ErrorSources.DASHBOARD,
                            module_name='prepare_report',
                            error_message=str(e),
                            stack_trace=traceback.format_exc(),
                            context_data={"pdf_key": pdf_key}
                        )
            if pdf_key in st.session_state:
                st.download_button(
                    label="📥 Download PDF",
                    data=st.session_state[pdf_key],
                    file_name=f"Report_Batch_{batch.id}.pdf",
                    mime="application/pdf",
                    key=f"btn_dl_{batch.id}",
                    use_container_width=True,
                    type="primary"
                )

#############
# CALLBACKS #
#############
def get_data_callback(update_pg_number: bool = True):
    error_msgs = validate_inputs()
    if len(error_msgs) == 1:
        st.toast(error_msgs[0], icon="❌", duration=8)
    else:
        old_val = st.session_state.results_page_number
        if update_pg_number: st.session_state.results_page_number = 1
        if update_session_data():
            #st.toast("Obtaining Results Data Successful!", icon="✅", duration=8)
            pass
        else:
            st.toast("Obtaining Results Data Failed!", icon="❌", duration=8)
            st.session_state.results_page_number = old_val

def change_page_callback():
    get_data_callback(False)

def per_page_callback():
    if st.session_state.results_page_limit_amount > 200:
        st.toast("You can only select a maximum of 200 results per page!", icon="❌", duration=8)
        st.session_state.results_page_limit_amount = 200
    elif st.session_state.results_page_limit_amount < 1:
        st.toast("You must select at least 1 result per page!", icon="❌", duration=8)
        st.session_state.results_page_limit_amount = 1
    else:
        get_data_callback()

def time_since_callback():
    if st.session_state.results_time_amount < 1:
        st.toast("Time amount must be > 0!", icon="❌", duration=8)
        st.session_state.results_time_amount = 1

###########################
# Cached Data & Fragments #
###########################
@st.cache_resource
def get_db():
    return DBManager()
db = get_db()
@st.cache_resource
def get_pdf_reporter():
    return PDFReporter()
reporter = get_pdf_reporter()

@st.cache_resource
def get_batch_analysis_definitions(_db):
    return _db.get_batch_analysis_definitions()
@st.cache_resource
def get_anomaly_analysis_definitions(_db):
    return _db.get_anomaly_analysis_definitions()
@st.cache_resource(ttl=60)
def get_cached_sc_names(_db, select_inactive: bool) -> list[str]:
    return _db.get_all_sc_names(select_inactive)
@st.cache_resource(ttl=60)
def get_cached_criteria_id_name_mapping(_db) -> dict[int, str]:
    return _db.get_criteria_id_name_mapping()

def update_session_data() -> bool:
    """Updates session data (batches and batch count). On success returns True, on failure False"""
    count, data = get_batches_and_batch_count()
    st.session_state.results_data = data
    if count == -1 and data == []:
        st.session_state.results_data_count = 0
        return False
    else:
        st.session_state.results_data_count = count
        return True

def get_batches_and_batch_count() -> tuple[int, list[dbmodels.BatchData]]:
    ss = st.session_state
    
    # Clean names
    selected_criteria_objects = ss.get("results_sc_select", [])
    cleaned_names = [
        t.search_target_name.replace(' [ARCHIVED]', '').replace(' [PAUSED]', '').strip()
        for t in selected_criteria_objects
    ]
    # Time
    raw_unit = ss.get("results_time_unit", "Day(s)")
    if raw_unit == "All Time":
        unit_enum = dbmodels.TimeUnit.ALL_TIME
    else:
        unit_key = raw_unit.replace("(s)", "").upper()
        unit_enum = dbmodels.TimeUnit[unit_key]

    return db.get_all_batches_paged(
        search_criteria_names=cleaned_names,
        limit_records=ss.get("results_page_limit_amount", 50),
        pg_number=ss.get("results_page_number", 1),
        unit_of_time=unit_enum,
        time_amount=ss.get("results_time_amount", 1),
        sort_by=ss.get("results_sortby", "Newest"),
        select_inactive=ss.get("results_showing_soft_deleted", False),
    )

if "results_data_count" not in st.session_state:
    st.session_state.results_data_count = 0
if "results_data" not in st.session_state:
    st.session_state.results_data = []
if are_there_any_batches(db):
    if "results_first_page_open_in_session" not in st.session_state:
        st.session_state.results_first_page_open_in_session = True
        if update_session_data():
            pass
        else:
            st.toast("Obtaining Results Data Failed!", icon="❌", duration=8)
else:
    st.info("👋 Welcome! It looks like you haven't started gathering any data yet.")
    st.warning("Monitoring results is only possible when there is something to monitor.")
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
st.header("📈 Results Panel")
st.markdown("This menu allows you to view, filter and download the results of your search targets. Listed below are all the reports generated by this application while running its search targets.")
st.subheader("Filters:")
with st.container(key="results_filter_container", border=True, width='content'):
    col_all_st, col0_space, col_sd_st = st.columns([1.0, 0.0975, 1.0])
    with col_all_st:
        is_results_sc_all = st.checkbox(
            "Search all batches?", key="results_sc_search_all", value=True, 
            help="If checked, every batch report will be included regardless of which search criteria it belongs to."
        )
    with col_sd_st:
        is_showing_soft_deleted = st.checkbox(
            "Include inactive search criteria's results?", key="results_showing_soft_deleted", value=False,
            help="If checked, inactive (disabled or soft-deleted) search criteria's logs will be included in the search criteria name multiselect widget. If searching for all search criteria, these criteria will also be included in the search."
        )
    col_sc, col1_space, col_3, col_4, col1_space2 = st.columns([2.0, 0.2, 1.2, 0.75, 0.05])
    with col_sc:
        st.multiselect(
            "Select search criteria:", key="results_sc_select",
            options=get_search_criteria_names(db, is_showing_soft_deleted), disabled=is_results_sc_all, 
            format_func=lambda x: f"SC: {x.search_target_name}"  
        )
    with col_3:
        st.number_input(
            "Time since batch recorded:", key="results_time_amount", value=int(1), step=1, on_change=time_since_callback,
            disabled=(st.session_state.get("results_time_unit", None) == "All Time")
        )
    with col_4:
        select_log_tu = st.selectbox("Unit of time:", key="results_time_unit", options=["Minute(s)", "Hour(s)", "Day(s)", "All Time"], index=2)

col_filter, col_refresh, col4_empty = st.columns([1.5, 1.5, 4.0])
with col_filter:
    st.button("🔍 Apply Filters", key="results_apply_filters", on_click=get_data_callback, width="stretch")
with col_refresh:
    st.button("🔄 Refresh Results", key="results_refresh", on_click=get_data_callback, width="stretch")
col5_sort, col5_limit, col5_empty = st.columns([1.5, 1.5, 4.0])
with col5_sort:
    st.selectbox("Sort by:", key="results_sortby", on_change=get_data_callback, options=["Newest", "Oldest"])
with col5_limit:
    st.number_input("Results per page: (200 max.)", key="results_page_limit_amount", on_change=per_page_callback, value=int(50), step=1)

st.subheader("Batch Results List:")
pg_number = st.selectbox("Page:", key="results_page_number", on_change=change_page_callback, options=get_pages_number_list(), width=80, disabled=st.session_state.get('results_data', []) == [])
with st.container(border=True):
    if not st.session_state.results_data:
        st.info("📂 No results found for the selected filters.")
        st.caption("Try adjusting the time range or status filters to see more results.")
    else:
        target_map = get_cached_criteria_id_name_mapping(db)
        for row in st.session_state.results_data:
            draw_batch_card(row, target_map)
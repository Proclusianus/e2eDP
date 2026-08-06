from math import ceil
import json


import streamlit as st


from database.models import AppSystemError, ErrorSources
from database.db_manager import DBManager

#############
# FUNCTIONS #
#############
def get_pages_number_list() -> list[int]:
    ss = st.session_state
    pg_amount = ceil(ss.syserr_data_count / ss.sys_errors_page_limit_amount)
    return range(1, max(1, pg_amount)+1)

def convert_solve_status_str2bool() -> bool:
    string = st.session_state.get('sys_errors_solve_status', "Unsolved")
    return string == "Solved"

def draw_syserr_card(err: AppSystemError):
    source_icons = {
        ErrorSources.SCRAPER.value: "🕸️",
        ErrorSources.CLEANER.value: "🧹",
        ErrorSources.ANALYZER.value: "🧠",
        ErrorSources.DASHBOARD.value: "🖥️",
        ErrorSources.MAINTENANCE.value: "♻️",
        ErrorSources.DATABASE.value: "🗄️",
    }
    icon = source_icons.get(err.error_source, "⚠️")
    with st.container(border=True):
        col_header, col_err_id, col_status = st.columns([3, 1, 1])
        with col_header:
            st.markdown(f"### Error Source: {icon} {err.error_source}")
            st.caption(f"📍 Module: `{err.module_name or 'N/A'}`")
        with col_err_id:
            st.markdown(f"🔑 Error ID: {err.id}")
        with col_status:
            st.write(f"🕒 {err.occurred_at.strftime('%H:%M:%S')}")
            st.caption(err.occurred_at.strftime('%Y-%m-%d'))

        st.error(f"**Error:** {err.error_message}")
        if err.stack_trace or err.context_data:
            with st.expander("🔍 View Stack Trace & Context"):
                if err.context_data:
                    st.write("**Context Data (JSONB):**")
                    st.json(err.context_data)
                if err.stack_trace:
                    st.write("**Python Stack Trace:**")
                    st.code(err.stack_trace, language="python")

        if not err.is_resolved:
            st.button(
                "✅ Mark as Resolved", key=f"sys_errors_resolve_{err.id}", use_container_width=True,
                on_click=mark_resolved_callback, args=(err.id, True)
            )
        else:
            st.button(
                "↩️ Reopen Error", key=f"sys_errors_unresolve_{err.id}", use_container_width=True,
                on_click=mark_unresolved_callback, args=(err.id, False)
            )

#############
# CALLBACKS #
#############
def get_data_callback(update_pg_number: bool = True):
    old_val = st.session_state.sys_errors_page_number
    if update_pg_number: st.session_state.sys_errors_page_number = 1
    if update_session_data():
        #st.toast("Obtaining Log Data Successful!", icon="✅", duration=8)
        pass
    else:
        st.toast("Obtaining Log Data Failed!", icon="❌", duration=8)
        st.session_state.sys_errors_page_number = old_val

def change_page_callback():
    get_data_callback(False)

def per_page_callback():
    ss=st.session_state
    if ss.sys_errors_page_limit_amount > 200:
        st.toast("You can only select a maximum of 200 results per page!", icon="❌", duration=8)
        ss.sys_errors_page_limit_amount = 200
    elif ss.sys_errors_page_limit_amount < 1:
        st.toast("You must select at least 1 result per page!", icon="❌", duration=8)
        ss.sys_errors_page_limit_amount = 1
    else:
        get_data_callback()

def mark_resolved_callback(syserr_id: int, syserr_new_status: bool):
    if db.set_system_error_resolution_status(syserr_id, syserr_new_status):
        remove_err_from_session_data(syserr_id)
        st.toast(f"Error {syserr_id} marked as resolved!", icon="✅", duration=8)
    else:
        st.toast(f"Failed to set error {syserr_id}'s status!", icon="❌", duration=8)

def mark_unresolved_callback(syserr_id: int, syserr_new_status: bool):
    if db.set_system_error_resolution_status(syserr_id, syserr_new_status):
        remove_err_from_session_data(syserr_id)
        st.toast(f"Error {syserr_id} reopened!", icon="✅", duration=8)
    else:
        st.toast(f"Failed to reopen error {syserr_id}!", icon="❌", duration=8)

###########################
# Cached Data & Fragments #
###########################
@st.cache_resource
def get_db():
    return DBManager()
db = get_db()

def update_session_data() -> bool:
    """Updates session data (syserrors and syserror count). On success returns True, on failure False"""
    ss = st.session_state
    count, data = db.get_system_errors(
        is_solved=convert_solve_status_str2bool(),
        limit_records=ss.get("sys_errors_page_limit_amount", 50),
        pg_number=ss.get("sys_errors_page_number", 1)
    )
    ss.syserr_data = data
    if count == -1 and data == []:
        ss.syserr_data_count = 0
        return False
    else:
        ss.syserr_data_count = count
        return True

def remove_err_from_session_data(syserr_id: int):
    ss = st.session_state
    ss.syserr_data = [
        err for err in ss.syserr_data 
        if err.id != syserr_id
    ]
    ss.syserr_data_count = ss.syserr_data_count - 1
    if ss.syserr_data_count % ss.sys_errors_page_limit_amount == 0 and ss.syserr_data_count != 0:
        get_data_callback() # In case somebody removes the last element off a page

if "syserr_data_count" not in st.session_state:
    st.session_state.syserr_data_count = 0
if "syserr_data" not in st.session_state:
    st.session_state.syserr_data = []
if "syserr_first_page_open_in_session" not in st.session_state:
    st.session_state.syserr_first_page_open_in_session = True
    if update_session_data():
        pass
    else:
        st.toast("Obtaining Error Data Failed!", icon="❌", duration=8)

################
# WEBPAGE CODE #
################
st.header("⚠️ System Errors")
st.markdown("This menu allows you to view and mark system errors as solved/unsolved. Listed below are all the errors generated by this application while running its processes.")

c1e1, c1e2, c1e3, c1e4 = st.columns([2.0, 1.0, 1.5, 3.0])
with c1e1:
    st.number_input("Results per page: (200 max.)", key="sys_errors_page_limit_amount", on_change=per_page_callback, value=int(50), step=1)
with c1e2:
    st.selectbox("Page:", key="sys_errors_page_number", on_change=change_page_callback, options=get_pages_number_list())
with c1e3:
    st.selectbox("⚠️ Error status:", key="sys_errors_solve_status", on_change=get_data_callback, options=["Unsolved", "Solved"], 
                 format_func=lambda x: ('🔴 ' + x) if x[0]=='U' else ('🟢 ' + x))
st.button("🔄 Refresh Results", key="sys_errors_refresh", on_click=get_data_callback, use_container_width=True)

st.subheader("System Errors List:")
with st.container(border=True):
    if not st.session_state.syserr_data:
        st.info("📂 No errors found!")
        if st.session_state.sys_errors_solve_status == "Unsolved":
            st.caption("Nice!")
    else:
        for row in st.session_state.syserr_data:
            draw_syserr_card(row)
import datetime
from dataclasses import dataclass, field
import re


import streamlit as st


from database.db_manager import DBManager
from database.models import AnomalyAnalysis, Location, ActivatedAnalysis, GlobalNotificationRule

###########
# STRINGS #
###########
GNR_HELP_MARKDOWN="""
    <u>Target Name</u> - Give your search a simple name so you can find it later (e.g., "My Dream Home").
    <br>
    <u>Description</u> - Add some notes for yourself about why you created this search.
    <br>
    <u>Sale or Rent</u> - Choose if you want to see prices for buying a property or monthly rent costs.
    <br><br>
    <u>Cities</u> - Pick the cities where you want the app to look for offers.
    <br>
    <u>Or... search in all cities</u> - Checks every offer, no matter what city it's in.
    <br><br>
    <u>Schedule</u> - Pick the hours during the day when the app should automatically go and check for new offers.
    <br>
    <u>Deal Detection (Anomaly Analysis)</u> - Allows you to select which per-offer analyses should be ran.
"""

GNR_DELETE_INFO_TEXT="""
    A note on deleting global rule notifications - of which there are two ways:
    *   **Soft Delete:** When you delete a target here, the record is flagged as `is_soft_deleted`. It becomes invisible in this menu, but all historical data, price trends, and logs remain in the database for **Data Lineage** and audit purposes.
    *   **Hard Delete:** Physical removal of data is restricted to the Database Administrator level to prevent accidental loss of historical market insights.
"""

##############
# DATA TYPES #
##############
@dataclass
class ValidationResult:
    error_msgs: str
    parsed_hours: list[datetime.time]

@dataclass
class ValidationData:
    current_name: str
    initial_name: str | None
    clean_desc: str | None
    all_cities: list[str]
    selected_anomaly_analyses: list[ActivatedAnalysis]

#############
# FUNCTIONS #
#############
def has_essential_changes(edited: GlobalNotificationRule, initial: GlobalNotificationRule) -> bool:
    if edited.transaction_type != initial.transaction_type:
        return True
    if edited.is_searching_all_cities != initial.is_searching_all_cities:
        return True
    if not edited.is_searching_all_cities and not initial.is_searching_all_cities:
        if set(c.upper() for c in edited.cities) != set(c.upper() for c in initial.cities):
            return True

    return False

def has_non_essential_changes(edited: GlobalNotificationRule, initial: GlobalNotificationRule) -> bool:
    def to_analysis_set(analyses):
        return {
            (a.analysis_id, a.param_value if a.param_value is not None else None) 
            for a in analyses
        }
    return (
        edited.rule_name != initial.rule_name or
        edited.description != initial.description or
        to_analysis_set(edited.analyses) != to_analysis_set(initial.analyses) or
        set(edited.execution_hours) != set(initial.execution_hours)
    )

def prepare_gnr_data_for_validation(target_name: str, initial_values: GlobalNotificationRule, desc: str, 
                                    selected_existing_cities: list[Location], new_cities_input: str,
                                    search_all: bool, all_anomaly_analyses: list[AnomalyAnalysis]) -> ValidationData:
    """Cleans up and prepares input data for validation & saving"""
    current_name = target_name.strip()
    initial_name = initial_values.rule_name if initial_values is not None else ''
    clean_description = (desc or "").strip() or None
    all_cities = list(set([c.city_name.upper() for c in selected_existing_cities] + 
                            [c.strip().upper() for c in new_cities_input.split(',') if c.strip()])) if not search_all else []
    anomaly_inputs = []
    for an in all_anomaly_analyses:
        is_checked = st.session_state.get(f"gnr_edit_an_{an.id}", False)
        if is_checked:
            val = st.session_state.get(f"gnr_edit_an_val_{an.id}")
            anomaly_inputs.append(ActivatedAnalysis(
                analysis_id=an.id, 
                param_value=val
            ))
    return ValidationData(
        current_name=current_name,
        initial_name=initial_name,
        clean_desc=clean_description,
        all_cities=all_cities,
        selected_anomaly_analyses=anomaly_inputs
    )

def validate_gnr_form(db: DBManager, val_data: ValidationData, search_all: bool, schedule_input: str,
                        anomaly_analyses: list[AnomalyAnalysis]) -> ValidationResult:
    """Validates data (returns string of validation errors) and prepares execution hours for saving"""
    error_msgs = []
    # GNR Name
    current_name = val_data.current_name
    if not current_name:
        error_msgs.append("Global Notification Rule name cannot be empty.")
    if len(current_name) > 255:
        error_msgs.append("Global Notification Rule name cannot be longer than 255 characters.")
    if current_name.lower() != val_data.initial_name.lower():
        if db.does_global_notification_rule_name_exist(current_name):
            error_msgs.append(f"A global notification rule with the name '{current_name}' already exists. Please choose a unique name.")

    # Cities
    if not val_data.all_cities and not search_all:
        error_msgs.append("At least one location (city) is required.")
    for city in val_data.all_cities:
        if len(city) > 100:
            error_msgs.append(f"City name '{city}' cannot be longer than 100 characters.")

    # Scheduled hours
    time_pattern = re.compile(r"^\d{1,2}:\d{2}$")
    parsed_hours = []
    if schedule_input.strip():
        raw_times = [t.strip() for t in schedule_input.split(',') if t.strip()]
        for t in raw_times:
            if not time_pattern.match(t):
                error_msgs.append(f"Invalid format: '{t}'. Minutes must have two digits (e.g., 8:09 instead of 8:9).")
                continue
            try:
                valid_time = datetime.datetime.strptime(t, "%H:%M").time()
                parsed_hours.append(valid_time)
            except Exception as e:
                error_msgs.append(f"Invalid time format: '{t}'. Use HH:MM (24h).")
    else:
        error_msgs.append("Execution schedule cannot be empty.")
    parsed_hours = list(set(parsed_hours)) # Deduplicate...

    # Analytics
    analysis_defs = {an.id: an for an in anomaly_analyses}
    for selected in val_data.selected_anomaly_analyses:
        rule_def = analysis_defs.get(selected.analysis_id)
        if rule_def:
            if rule_def.takes_parameter and selected.param_value is None:
                error_msgs.append(f"Anomaly detection '{rule_def.name_en}' requires a threshold value.")
    if not val_data.selected_anomaly_analyses:
        error_msgs.append("Select at least one analysis method.")

    return ValidationResult(
        error_msgs=error_msgs,
        parsed_hours=parsed_hours
    )

def find_transaction_type_idx(tt_list: list[str], tt_str: str) -> int:
    """Returns the given's transaction_type's index in transaction_type list; If no such tt exists, returns 0"""
    try:
        t_index = tt_list.index(tt_str)
    except (ValueError, AttributeError):
        t_index = 0
    return t_index

# Switching views
# 1st view shows the list of grn
# 2nd view allows you to edit and add new grn
if 'gnr_view_mode' not in st.session_state:
    st.session_state.gnr_view_mode = 'list'
if 'gnr_edit_id' not in st.session_state:
    st.session_state.gnr_edit_id = None
def go_to_form(grn_id=None):
    st.session_state.gnr_view_mode = 'form'
    st.session_state.gnr_edit_id = grn_id
    if grn_id:
        st.session_state.notif_initial_values = db.get_global_notification_rule(grn_id)
def go_to_list():
    st.session_state.gnr_view_mode = 'list'
    st.session_state.gnr_edit_id = None
    st.session_state.pop("notif_initial_values", None)

#############
# CALLBACKS #
#############
def soft_delete_gnr_callback(gnr_id, rule_name):
    if db.soft_delete_global_notification_rule(gnr_id):
        remove_gnr_from_state(gnr_id)
        st.session_state.gnr_toast_msg = f"Rule '{rule_name}' disabled and archived."
    else:
        st.session_state.gnr_toast_error = "Error during deletion."

def toggle_active_callback(gnr_id):
    """Activates/Deactivates a gnr"""
    new_status = st.session_state[f"gnr_active_{gnr_id}"]
    if db.set_global_notification_activation_status(gnr_id, new_status):
        update_single_row_in_state(gnr_id)
    else:
        st.session_state[f"gnr_active_{gnr_id}"] = not new_status
        st.toast("Failed to update status.", icon="❌", duration=8)

def manual_refresh_callback():
    """Gets current DB gnr data into st.session_state.gnr_data"""
    refresh_all_data()
    st.session_state.gnr_toast_msg = "Data refreshed from database! 🔄"

###########################
# Cached Data & Fragments #
###########################
@st.cache_resource
def get_db():
    return DBManager()
db = get_db()

# Must be cached as resource; db_manager.py stores the class definition at one place in RAM.
# This page, even if it were to directly import it from db_manager, on reload, the class definition
# might change its place in memory, resulting in pickle seeing it as two different classes
# and being unable to serialize it.
#
# Since these three caches are only used as selectable options (aren't modified), 
# cache_resource's mutability is not a reason not to use it here.
@st.cache_resource(ttl=600) 
def get_cached_locations(_db):
    return _db.get_all_locations()

@st.cache_resource
def get_cached_transaction_types(_db):
    return _db.get_all_transaction_types()

@st.cache_resource
def get_cached_analyses(_db):
    return _db.get_anomaly_analysis_definitions()

if "gnr_data" not in st.session_state:
    st.session_state.gnr_data = db.get_current_global_notifs()
def refresh_all_data():
    st.session_state.gnr_data = db.get_current_global_notifs()
def remove_gnr_from_state(gnr_id):
    """Removes a single gnr record from st.session_state.gnr_data"""
    st.session_state.gnr_data = [
        rule for rule in st.session_state.gnr_data 
        if rule.id != gnr_id
    ]
def update_single_row_in_state(gnr_id):
    """
        Updates a single gnr record in st.session_state.gnr_data,  
        If it isn't found in gnr_data, it's added to it.
    """
    new_rule_obj = db.get_global_notification_rule(gnr_id)
    if new_rule_obj:
        current_list = st.session_state.gnr_data
        found = False
        for i, rule in enumerate(current_list):
            if rule.id == gnr_id:
                current_list[i] = new_rule_obj
                found = True
                break
        if not found:
            current_list.insert(0, new_rule_obj)
        st.session_state.gnr_data = current_list

@st.fragment
def render_gnr_card(gnr: GlobalNotificationRule):
    with st.container(border=True):
        c1, c2, spacer, c3 = st.columns([5, 2.5, 0.5, 2.5])
        
        with c1:
            st.subheader(gnr.rule_name)
            desc = gnr.description
            if not desc or desc.strip() == "":
                desc = f"🔍 {gnr.transaction_type.upper()} in {', '.join(gnr.cities) if gnr.cities else 'All locations'}"
            st.write(desc)
        
        with c2:
            st.write("**⏰ Schedule:**")
            st.caption(", ".join([h.strftime("%H:%M") for h in gnr.execution_hours]))
            
        with c3:
            btn_col1, btn_col2 = st.columns([1.2, 1])
            with btn_col1:
                is_active = st.toggle(
                    "🟢 Active" if st.session_state.get(f"gnr_active_{gnr.id}", gnr.is_active) else "⚪ Paused", 
                    value=gnr.is_active, key=f"gnr_active_{gnr.id}",
                    on_change=toggle_active_callback, args=(gnr.id,)
                )
                
            with btn_col2:
                if st.button("📝 Edit", key=f"gnr_edit_{gnr.id}", on_click=go_to_form, args=(gnr.id,), use_container_width=True):
                    st.rerun()
            
            del_spacer, del_col = st.columns([1.2, 1])
            with del_col:
                with st.popover("🗑️ Delete", use_container_width=True):
                    st.warning(f"Delete {gnr.rule_name}?")
                    if st.button("🗑️ Delete", key=f"gnr_del_{gnr.id}", type="secondary", use_container_width=True, 
                            on_click=soft_delete_gnr_callback, args=(gnr.id, gnr.rule_name)):
                        st.rerun()

################
# WEBPAGE CODE #
################
#####################
# GNR LIST - VIEW 1 #
#####################
if st.session_state.gnr_view_mode == 'list':
    toast_msg = st.session_state.pop("gnr_toast_msg", None)
    if toast_msg:
        st.toast(toast_msg, icon="✅", duration=8)
    err = st.session_state.pop("gnr_toast_error", None)
    if err:
        st.toast(err, icon="❌", duration=8)

    st.header("🌍 Current Global Notification Rules")
    st.divider()
    st.markdown("This menu allows you to view, edit and create your global notification rules.")
    st.markdown("Global notification rules are configuration objects that allow you to monitor all gathered data and find anomalies which fulfill selected conditions")
    with st.expander("See Global Notification Rules Parameters..."):
        st.markdown(GNR_HELP_MARKDOWN, unsafe_allow_html=True)
    st.info(GNR_DELETE_INFO_TEXT)
    st.divider()
    st.subheader("Global Notification Rules List:")
    with st.container(border=True):
        col_add, col_refresh, col_empty = st.columns([1.3, 0.7, 4])
        with col_add:
            st.button("➕ Add New Global Notification Rules", on_click=go_to_form, use_container_width=True)
        with col_refresh:
            st.button("🔄 Refresh Data", on_click=manual_refresh_callback, use_container_width=True)

        gnr_data = st.session_state.gnr_data
        if not gnr_data:
            st.info("No global notification rules found. Click 'Add New Global Notification Rules' to start.")
        else:
            with st.container(height=900):
                for rule in gnr_data:
                    render_gnr_card(rule)
    st.divider()

#########################
# GNR EDIT/ADD - VIEW 2 #
#########################
elif st.session_state.gnr_view_mode == 'form':
    st.divider()
    mode_label = "Edit Target" if st.session_state.gnr_edit_id else "Create New Rule Object"
    st.header(mode_label)
    if st.button("⬅️ Back to List"):
        go_to_list()
        st.rerun()

    # Get dictionary data from DB
    transaction_types: list[str] = get_cached_transaction_types(db)
    existing_locations: list[Location] = get_cached_locations(db)
    anomaly_analyses: list[AnomalyAnalysis] = get_cached_analyses(db)

    # Prepare default values (is_active doesn't matter here)
    form_defaults = GlobalNotificationRule(id=0, rule_name='', description='', transaction_type=transaction_types[0], is_searching_all_cities=False, is_active=False)
    initial_values = None
    edit_id = st.session_state.gnr_edit_id
    if edit_id:
        initial_values = st.session_state.get("notif_initial_values")
        if initial_values:
            if initial_values.id != edit_id:
                st.session_state.pop("notif_initial_values", None)
                st.session_state.notif_initial_values = db.get_global_notification_rule(edit_id)
            form_defaults = initial_values
    else:
        st.session_state.pop("notif_initial_values", None)

    with st.container(border=True):
        st.subheader("1. General Information")
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            target_name = st.text_input("Rule Object Name", key="gnr_edit_rule_name", placeholder="e.g. Dobre Oferty Kraków", value=form_defaults.rule_name)
        with col2:
            transaction_type = st.selectbox("Transaction", key="gnr_edit_tt", options=transaction_types, format_func=lambda x: x.capitalize(), 
                                            index=find_transaction_type_idx(transaction_types, form_defaults.transaction_type))
        
        description = st.text_area("Description (Optional)", key="gnr_edit_desc", value=form_defaults.description)

        st.subheader("2. Locations")
        search_all = st.checkbox(
            "Search in all cities", key="gnr_edit_search_all",
            value=form_defaults.is_searching_all_cities,
            help="If checked, the system will monitor all gathered data regardless of location."
        )
        saved_cities_set = set(form_defaults.cities or [])
        selected_existing_cities = st.multiselect(
            "Select from existing cities:", key="gnr_edit_cities_select",
            options=existing_locations, format_func=lambda x: x.city_name,
            default=[l for l in existing_locations if l.city_name in saved_cities_set] if not search_all else [],
            disabled=search_all
        )
        new_cities_input = st.text_input("Or add new cities (comma separated):", key="gnr_edit_new_cities_input", 
                                         placeholder="Gdańsk, Sopot, Gdynia", disabled=search_all)

        st.subheader("3. Automated Schedule")
        schedule_input = st.text_input(
            "Execution Hours (hh:mm, comma separated)", key="gnr_edit_schedule",
            placeholder="08:00, 12:30, 22:00", help="Enter hours in 24h format, e.g., 8:00, 15:45",
            value=", ".join(h.strftime("%H:%M") for h in sorted(form_defaults.execution_hours))
        )

        st.subheader("5. Analytics Activation")
        st.markdown("Please select at least one of the following:")
        activated_map = {a.analysis_id: a.param_value for a in form_defaults.analyses}
        for an in anomaly_analyses:
            is_active = an.id in activated_map
            saved_val = activated_map.get(an.id)
            c1, c2 = st.columns([3, 2])
            with c1:
                st.checkbox(an.name_en, value=is_active, key=f"gnr_edit_an_{an.id}", help=an.description_en)
            with c2:
                if an.takes_parameter:
                    st.number_input(
                        "Threshold", key=f"gnr_edit_an_val_{an.id}", label_visibility="collapsed",
                        value=float(saved_val) if saved_val is not None else 5.0
                    )

        # Saving
        st.divider()
        save = st.button("Save and Activate Configuration", use_container_width=True, type="primary")
        if save:
            prepared_data = prepare_gnr_data_for_validation(target_name, initial_values, description,
                               selected_existing_cities, new_cities_input, search_all, anomaly_analyses)
            val = validate_gnr_form(db, prepared_data, search_all, schedule_input, anomaly_analyses)
            if len(val.error_msgs) == 1:
                st.error(val.error_msgs[0])
            elif len(val.error_msgs) > 1:
                st.error("**Please correct the following:**\n" + "\n".join(['- ' + e.strip() for e in val.error_msgs]))
            else: ### Saving begin
                data_to_save = GlobalNotificationRule(
                    id=0, rule_name=prepared_data.current_name, description=prepared_data.clean_desc,
                    transaction_type=transaction_type, is_searching_all_cities=search_all, is_active=True,
                    cities=prepared_data.all_cities, analyses=prepared_data.selected_anomaly_analyses, 
                    execution_hours=val.parsed_hours
                ) #id,is_active don't matter here
                if edit_id: # EDITING
                    if has_essential_changes(data_to_save, initial_values):
                        n_id = db.replace_global_rule(edit_id, data_to_save)
                        if n_id:
                            st.session_state.gnr_toast_msg = f"Parameters changed successfully"
                            remove_gnr_from_state(edit_id)
                            update_single_row_in_state(n_id)
                            get_cached_locations.clear()
                            go_to_list()
                            st.rerun()
                        else:
                            st.error(f"Cannot modify the global notification rule due to a database error.")
                    elif has_non_essential_changes(data_to_save, initial_values):
                        if db.update_global_notification_nonessential_data(
                                gnr_id = edit_id, name=data_to_save.rule_name,
                                desc=data_to_save.description, hours=data_to_save.execution_hours,
                                analyses=data_to_save.analyses
                            ):
                            st.session_state.gnr_toast_msg = f"Parameters changed successfully"
                            update_single_row_in_state(edit_id)
                            go_to_list()
                            st.rerun()
                        else:
                            st.error(f"Cannot modify the global notification rule due to a database error.")
                    else:# Nothing changed but user clicked save either way
                        st.info("No changes detected. Change something to save.")
                else:       # ADDING
                    n_id = db.save_new_global_notification_rule(data_to_save)
                    if n_id:
                        st.session_state.gnr_toast_msg = f"Configuration '{target_name}' has been successfully activated!"
                        update_single_row_in_state(n_id)
                        get_cached_locations.clear()
                        go_to_list()
                        st.rerun()
                    else:
                        st.error(f"Cannot add the global notification rule due to a database error.")
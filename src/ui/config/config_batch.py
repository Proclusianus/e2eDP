import datetime
from typing import NamedTuple
import re


import streamlit as st


from database.db_manager import DBManager
from database.models import SearchCriteria, SearchCriteriaNonEssentialData, PropertyType, RoomCount, BatchAnalysis, AnomalyAnalysis, Location, ActivatedAnalysis

###########
# STRINGS #
###########
CRITERIA_HELP_MARKDOWN = """
    <u>Target Name</u> - Give your search a simple name so you can find it later (e.g., "My Dream Home").
    <br>
    <u>Description</u> - Add some notes for yourself about why you created this search.
    <br><br>
    <u>Sale or Rent</u> - Choose if you want to see prices for buying a property or monthly rent costs.
    <br>
    <u>Market Type</u> - Select "Primary" for brand-new developer homes, "Secondary" for used ones, or "Both".
    <br>
    <u>Min & Max Price</u> - Set your budget limits so you don't see results that are too expensive or irrelevant.
    <br>
    <u>Min & Max Area</u> - Set the size range (in square meters) you are looking for.
    <br><br>
    <u>Cities</u> - Pick the cities where you want the app to look for offers.
    <br>
    <u>Property Type</u> - Choose if you are interested in apartments, houses, or both.
    <br>
    <u>Room Count</u> - Select exactly how many rooms the property should have (e.g., only 2 and 3-room flats).
    <br><br>
    <u>Schedule</u> - Pick the hours during the day when the app should automatically go and check for new offers.
    <br>
    <u>General Trends (Batch Analysis)</u> - Allows you to select which data group analyses should be ran.
    <br>
    <u>Deal Detection (Anomaly Analysis)</u> - Allows you to select which per-offer analyses should be ran.
"""
CRITERIA_DELETE_INFO_TEXT = """
    A note on deleting search criteria - of which there are two ways:
    *   **Soft Delete:** When you delete a target here, the record is flagged as `is_soft_deleted`. It becomes invisible in this menu, but all historical data, price trends, and logs remain in the database for **Data Lineage** and audit purposes.
    *   **Hard Delete:** Physical removal of data is restricted to the Database Administrator level to prevent accidental loss of historical market insights.
"""

##############
# DATA TYPES #
##############
class ValidationResult(NamedTuple):
    error_msgs: list[str]
    hours: list[datetime.time]
    batch_an: list[ActivatedAnalysis]
    anomaly_an: list[ActivatedAnalysis]

#############
# FUNCTIONS #
#############
def validate_criteria_form(db: DBManager, initial_name: str, target_name: str, cities: list[str], price_min: float, 
                           price_max: float, area_min: float, area_max: float, schedule_input: str, 
                           batch_analyses: list[BatchAnalysis], anomaly_analyses: list[AnomalyAnalysis]) -> ValidationResult:
    error_msgs = []
    # Search Criteria Name
    current_name = target_name.strip()
    if not current_name:
        error_msgs.append("Search Criteria name cannot be empty.")
    if len(current_name) > 255:
        error_msgs.append("Search Criteria name cannot be longer than 255 characters.")
    if current_name.lower() != initial_name.lower():
        if db.does_this_search_criteria_name_exist(target_name):
            error_msgs.append(f"A search criteria with the name '{target_name}' already exists. Please choose a unique name.")

    # Cities
    location_pattern = re.compile(r"^[A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ-]+(?: [A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ-]+)*(?:\/[A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ-]+(?: [A-Za-ząćęłńóśźżĄĆĘŁŃÓŚŹŻ-]+)*)*$")
    if not cities:
        error_msgs.append("At least one location (city) is required.")
    for city in cities:
        if len(city) > 100:
            error_msgs.append(f"City name '{city}' cannot be longer than 100 characters.")
        if not re.match(location_pattern, city):
            error_msgs.append(f"Invalid format for location: '{city}'. Use: Unit1/Unit2/Town")

    # Price
    if price_min > price_max:
        error_msgs.append(f"Minimum price {price_min} must be lesser than maximum price {price_max}")
    # Area
    if area_min > area_max:
        error_msgs.append(f"Minimum area {area_min} must be lesser than maximum area {area_max}")

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
    selected_batch_an: list[ActivatedAnalysis] = []
    selected_anomaly_an: list[ActivatedAnalysis] = []
    for an in batch_analyses:
        if st.session_state.get(f"cb_batch_{an.id}"): # Whether this analysis has been selected
            val = st.session_state.get(f"val_batch_{an.id}")
            if an.takes_parameter and (val is None):
                error_msgs.append(f"Batch trends analysis '{an.name_en}' requires a parameter value.")
            selected_batch_an.append(ActivatedAnalysis(analysis_id=an.id, param_value=val)) # Doesn't matter if an incorrect value is added, everything will be rejected if there are any error_msgs
    for an in anomaly_analyses:
        if st.session_state.get(f"cb_ano_{an.id}"):
            val = st.session_state.get(f"val_ano_{an.id}")
            if an.takes_parameter and (val is None):
                error_msgs.append(f"Anomaly detection '{an.name_en}' requires a parameter value.")
            selected_anomaly_an.append(ActivatedAnalysis(analysis_id=an.id, param_value=val))
    if not selected_batch_an and not selected_anomaly_an:
        error_msgs.append("Select at least one analysis method.")

    return ValidationResult(
        error_msgs=error_msgs,
        hours=parsed_hours,
        batch_an=selected_batch_an,
        anomaly_an=selected_anomaly_an,
    )

def has_essential_changes(current: SearchCriteria, initial: SearchCriteria) -> bool:
    current_pt_ids = {pt.pt_id for pt in current.property_types}
    initial_pt_ids = {pt.pt_id for pt in initial.property_types}
    current_room_ids = {r.room_id for r in current.rooms}
    initial_room_ids = {r.room_id for r in initial.rooms}
    return (
        current.transaction_type != initial.transaction_type or
        current.market_type != initial.market_type or
        current.min_price != initial.min_price or
        current.max_price != initial.max_price or
        current.min_area != initial.min_area or
        current.max_area != initial.max_area or
        set([c.strip().upper() for c in current.cities]) != set([c.strip().upper() for c in initial.cities]) or
        current_pt_ids != initial_pt_ids or
        current_room_ids != initial_room_ids
    )

def has_non_essential_changes(current: SearchCriteria, initial: SearchCriteria) -> bool:
    def to_analysis_set(analyses):
        return {
            (a.analysis_id, a.param_value if a.param_value is not None else None) 
            for a in analyses
        }
    return (
        current.target_name != initial.target_name or
        current.description != initial.description or
        to_analysis_set(current.batch_analyses) != to_analysis_set(initial.batch_analyses) or
        to_analysis_set(current.anomaly_analyses) != to_analysis_set(initial.anomaly_analyses) or
        set(current.execution_hours) != set(initial.execution_hours)
    )

# Switching views
# 1st view shows the list of search criteria
# 2nd view allows you to edit and add new search criteria
if 'view_mode' not in st.session_state:
    st.session_state.view_mode = 'list'
if 'edit_criteria_id' not in st.session_state:
    st.session_state.edit_criteria_id = None
def go_to_form(criteria_id=None):
    st.session_state.view_mode = 'form'
    st.session_state.edit_criteria_id = criteria_id
def go_to_list():
    st.session_state.view_mode = 'list'
    st.session_state.edit_criteria_id = None

#############
# CALLBACKS #
#############
def soft_delete_criteria_callback(criteria_id, target_name):
    if db.soft_delete_criteria(criteria_id):
        remove_criteria_from_state(criteria_id)
        st.session_state.toast_msg = f"Target '{target_name}' disabled and archived."
    else:
        st.session_state.toast_error = "Error during deletion."

def toggle_active_callback(criteria_id):
    """Activates/Deactivates a search criteria"""
    new_status = st.session_state[f"active_{criteria_id}"]
    if db.set_criteria_activation_status(criteria_id, new_status):
        update_single_row_in_state(criteria_id)
    else:
        st.session_state[f"active_{criteria_id}"] = not new_status
        st.toast("Failed to update status.", icon="❌", duration=8)

def manual_refresh_callback():
    """Gets current DB search_criteria data into st.session_state.sc_data"""
    refresh_all_data()
    st.session_state.toast_msg = "Data refreshed from database! 🔄"

############################
# Cached Data &  Fragments #
############################
@st.cache_resource
def get_db():
    return DBManager()
db = get_db()

@st.cache_resource
def sc_get_cached_transaction_types(_db) -> list[str]:
    return _db.get_all_transaction_types()
@st.cache_resource
def sc_get_cached_market_types(_db) -> list[str]:
    return _db.get_all_market_types()
@st.cache_resource
def sc_get_cached_property_types(_db) -> list[PropertyType]:
    return _db.get_all_property_types()
@st.cache_resource
def sc_get_cached_room_counts(_db) -> list[RoomCount]:
    return _db.get_all_room_counts()
@st.cache_resource
def sc_get_cached_batch_analyses(_db) -> list[BatchAnalysis]:
    return _db.get_batch_analysis_definitions()
@st.cache_resource
def sc_get_cached_anomaly_analyses(_db) -> list[AnomalyAnalysis]:
    return _db.get_anomaly_analysis_definitions()

if "sc_data" not in st.session_state:
    st.session_state.sc_data = db.get_all_search_criteria()
def refresh_all_data():
    st.session_state.sc_data = db.get_all_search_criteria()
def remove_criteria_from_state(criteria_id):
    """Removes a single criteria record from st.session_state.sc_data"""
    st.session_state.sc_data = [
        sc for sc in st.session_state.sc_data 
        if sc.id != criteria_id
    ]
def update_single_row_in_state(criteria_id):
    """
        Updates a single criteria record in st.session_state.sc_data,  
        If it isn't found in sc_data, it's added to it.
    """
    new_sc_obj = db.get_search_criteria(criteria_id)
    if new_sc_obj:
        current_list = st.session_state.get("sc_data", [])
        found = False
        for i, sc in enumerate(current_list):
            if sc.id == criteria_id:
                current_list[i] = new_sc_obj
                found = True
                break
        if not found:
            current_list.insert(0, new_sc_obj)
        
        st.session_state.sc_data = list(current_list)

@st.fragment
def render_criteria_card(sc: SearchCriteria):
    with st.container(border=True):
        c1, c2, spacer, c3 = st.columns([5, 2.5, 0.5, 2.5])
        
        with c1:
            st.subheader(sc.target_name)
            desc = sc.description
            if not desc or desc.strip() == "":
                desc = f"🔍 {sc.transaction_type.upper()} in {', '.join(sc.cities)} | {sc.min_price or 0.0} - {sc.max_price or 'No ceiling'} PLN"
            st.write(desc)
        
        with c2:
            st.write("**⏰ Schedule:**")
            st.caption(", ".join([h.strftime('%H:%M') for h in sorted(sc.execution_hours)]))
            
        with c3:
            btn_col1, btn_col2 = st.columns([1.2, 1])
            with btn_col1:
                is_active = st.toggle(
                    "🟢 Active" if st.session_state.get(f"active_{sc.id}", sc.is_active) else "⚪ Paused", 
                    value=sc.is_active, key=f"active_{sc.id}",
                    on_change=toggle_active_callback, args=(sc.id,)
                )
                
            with btn_col2:
                if st.button("📝 Edit", key=f"edit_{sc.id}", on_click=go_to_form, args=(sc.id,), use_container_width=True):
                    st.rerun()
            
            del_spacer, del_col = st.columns([1.2, 1])
            with del_col:
                with st.popover("🗑️ Delete", use_container_width=True):
                    st.warning(f"Delete {sc.target_name}?")
                    if st.button("🗑️ Delete", key=f"del_{sc.id}", type="secondary", use_container_width=True, 
                            on_click=soft_delete_criteria_callback, args=(sc.id, sc.target_name)):
                        st.rerun()

################
# WEBPAGE CODE #
################
#################################
# SEARCH CRITERIA LIST - VIEW 1 #
#################################
if st.session_state.view_mode == 'list':
    toast_msg = st.session_state.pop("toast_msg", None)
    if toast_msg:
        st.toast(toast_msg, icon="✅", duration=8)

    err = st.session_state.pop("toast_error", None)
    if err:
        st.toast(err, icon="❌", duration=8)

    st.header("🎯 Current Search Criteria")
    st.divider()
    st.markdown("This menu allows you to view, edit and create your search criteria.")
    st.markdown("Search criteria are configuration objects that dictate exactly what data is harvested from real estate portals and how it should be processed.")
    with st.expander("See Search Criteria Parameters..."):
        st.markdown(CRITERIA_HELP_MARKDOWN, unsafe_allow_html=True)
    st.info(CRITERIA_DELETE_INFO_TEXT)
    st.divider()
    st.subheader("Search Criteria List:")
    with st.container(border=True):
        col_add, col_refresh, col_empty = st.columns([1, 0.7, 4])
        with col_add:
            st.button("➕ Add New Search Criteria", on_click=go_to_form, use_container_width=True)
        with col_refresh:
            st.button("🔄 Refresh Data", on_click=manual_refresh_callback, use_container_width=True)

        if not st.session_state.sc_data:
            st.info("No search targets found. Click 'Add New Search Criteria' to start.")
        else:
            with st.container(height=900):
                for sc in st.session_state.sc_data:
                    render_criteria_card(sc)
    st.divider()

#####################################
# SEARCH CRITERIA EDIT/ADD - VIEW 2 #
#####################################
elif st.session_state.view_mode == 'form':
    st.divider()
    mode_label = "Edit Target" if st.session_state.edit_criteria_id else "Create New Target"
    st.header(mode_label)
    if st.button("⬅️ Back to List"):
        go_to_list()
        st.rerun()

    # Get dictionary data from DB
    # These can't be modified by the user so it's safe to cache them without a ttl
    transaction_types: list[str] = sc_get_cached_transaction_types(db)
    market_types: list[str] = sc_get_cached_market_types(db)
    available_property_types: list[PropertyType] = sc_get_cached_property_types(db)
    available_rooms: list[RoomCount] = sc_get_cached_room_counts(db)
    batch_analyses: list[BatchAnalysis] = sc_get_cached_batch_analyses(db)
    anomaly_analyses: list[AnomalyAnalysis] = sc_get_cached_anomaly_analyses(db)

    # This one should be presumed to update on submitting the form/entering view 2, so no caching
    existing_locations: list[Location] = db.get_all_locations()

    # If in edit mode - SELECT currently edited data
    # Default values for adding a new sc. id, is_active, is_soft_deleted, created_at are unused
    form_defaults = SearchCriteria(
        id=0, target_name="", description="", transaction_type=transaction_types[0], market_type=market_types[0], min_price=0.0, 
        max_price=1000000.0, min_area=30.0, max_area=100.0, is_active=True, is_soft_deleted=False, created_at=datetime.datetime.now()
    )
    initial_values: SearchCriteria | None = None
    edit_id = st.session_state.edit_criteria_id
    if edit_id:
        initial_values = db.get_search_criteria(edit_id)
        if initial_values:
            form_defaults = initial_values

    with st.form("criteria_form", clear_on_submit=False):
        st.subheader("1. General Information")
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            target_name = st.text_input("Search Criteria Name", placeholder="e.g. Mieszkania Kraków", value=form_defaults.target_name)
        with col2:
            transaction_type = st.selectbox("Transaction", options=transaction_types, format_func=lambda x: x.capitalize(), index=transaction_types.index(form_defaults.transaction_type))
        with col3:
            market_type = st.selectbox("Market", options=market_types, format_func=lambda x: x.replace('_', ' ').capitalize(), index=market_types.index(form_defaults.market_type))
        description = st.text_area("Description (Optional)", value=form_defaults.description)

        st.subheader("2. Locations")
        initial_city_names = set(initial_values.cities) if initial_values else set()
        selected_existing_cities = st.multiselect(
            "Select from existing locations:", 
            options=existing_locations,
            format_func=lambda x: x.city_name,
            default=[l for l in existing_locations if l.city_name in initial_city_names]
        )
        new_cities_input = st.text_input("Or add new locations (separate each location with a comma; for best accuracy type Admin Unit1/Admin Unit2/Town; just Cityname works too but might result in a mismatch):", 
                                         placeholder="Wielkopolskie/Gnieźnieński/Gniezno, Mazowieckie/Warszawa, Gdańsk")

        st.subheader("3. Property Filters")
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            price_min = st.number_input("Min Price/Rent (PLN)", min_value=0.0, value=form_defaults.min_price)
            price_max = st.number_input("Max Price/Rent (PLN)", min_value=0.0, value=form_defaults.max_price)
        with f_col2:
            area_min = st.number_input("Min Area (m²)", min_value=0.0, value=form_defaults.min_area)
            area_max = st.number_input("Max Area (m²)", min_value=0.0, value=form_defaults.max_area)

        st.write("**Specific Requirements:**")
        initial_property_types = {pt.pt_id for pt in form_defaults.property_types}
        initial_room_count = {rc.room_id for rc in form_defaults.rooms}
        sel_prop_types = st.multiselect("Property Types (Optional - if not selected, checks all)", options=available_property_types, 
                                        format_func=lambda x: x.type_name.capitalize(), default=[pt for pt in available_property_types if pt.pt_id in initial_property_types])
        sel_rooms = st.multiselect("Room Counts (Optional - if not selected, checks every)", options=available_rooms, 
                                   format_func=lambda x: x.room_label, default=[rc for rc in available_rooms if rc.room_id in initial_room_count])

        st.subheader("4. Automated Schedule")
        schedule_input = st.text_input(
            "Execution Hours (hh:mm, comma separated)", 
            placeholder="08:00, 12:30, 22:00",
            help="Enter hours in 24h format, e.g., 8:00, 15:45",
            value=", ".join(h.strftime("%H:%M") for h in sorted(form_defaults.execution_hours))
        )

        st.subheader("5. Analytics Activation")
        st.markdown("Please select at least one of the following:")
        batch_an_map = {a.analysis_id: a.param_value for a in form_defaults.batch_analyses}
        anomaly_an_map = {a.analysis_id: a.param_value for a in form_defaults.anomaly_analyses}
        an_col1, an_col2 = st.columns(2)
        with an_col1:
            st.caption("Batch Trends (Macro)")
            for an in batch_analyses:
                is_active = an.id in batch_an_map
                saved_val = batch_an_map.get(an.id)
                c1, c2 = st.columns([3, 2])
                with c1:
                    checked = st.checkbox(an.name_en, value=is_active, key=f"cb_batch_{an.id}", help=an.description_en)
                with c2:
                    if an.takes_parameter:
                        st.number_input(
                            "Value", key=f"val_batch_{an.id}", 
                            value=float(saved_val) if saved_val is not None else 0.0, 
                            placeholder="5.0", label_visibility="collapsed"
                        )
        with an_col2:
            st.caption("Anomaly Detection (Micro)")
            for an in anomaly_analyses:
                is_active = an.id in anomaly_an_map
                saved_val = anomaly_an_map.get(an.id)
                c1, c2 = st.columns([3, 2])
                with c1:
                    st.checkbox(an.name_en, value=is_active, key=f"cb_ano_{an.id}", help=an.description_en)
                with c2:
                    if an.takes_parameter:
                        st.number_input(
                            "Threshold", key=f"val_ano_{an.id}", 
                            value=float(saved_val) if saved_val is not None else 0.0, 
                            placeholder="5.0", label_visibility="collapsed"
                        )

        # Saving
        st.divider()
        save = st.form_submit_button("Save and Activate Configuration", use_container_width=True, type="primary")
        if save:
            # If user selected nothing, fill with all available
            final_property_types = [pt for pt in (sel_prop_types or available_property_types)]
            final_rooms = [r for r in (sel_rooms or available_rooms)]
            # Prepare the rest of the data
            old_name = initial_values.target_name if initial_values else ''
            clean_description = (description or "").strip() or None
            all_cities = list(set([c.city_name for c in selected_existing_cities] + 
                                  [c.strip() for c in new_cities_input.split(',') if c.strip()]))
            val = validate_criteria_form(db, old_name, target_name, all_cities, price_min, price_max, 
                                         area_min, area_max, schedule_input, batch_analyses, anomaly_analyses)
            error_msgs: list[str] = val.error_msgs
            parsed_hours: list[datetime.time] = val.hours
            selected_batch_an: list[ActivatedAnalysis] = val.batch_an
            selected_anomaly_an: list[ActivatedAnalysis] = val.anomaly_an
            if len(error_msgs) == 1:
                st.error(error_msgs[0])
            elif len(error_msgs) > 1:
                st.error("**Please correct the following:**\n" + "\n".join(['- ' + e.strip() for e in error_msgs]))
            else: ### Saving begin
                final_data = SearchCriteria(
                    id=edit_id if edit_id else 0, # unnecessary for adding a new one
                    target_name=target_name.strip(), description=clean_description, transaction_type=transaction_type,
                    market_type=market_type, min_price=float(price_min), max_price=float(price_max),
                    min_area=float(area_min), max_area=float(area_max), cities=all_cities,
                    property_types=final_property_types, rooms=final_rooms, execution_hours=parsed_hours,
                    batch_analyses=selected_batch_an, anomaly_analyses=selected_anomaly_an,
                    is_active=True, is_soft_deleted=False, created_at=datetime.datetime.now() # <- unused
                )
                if edit_id: # EDITING AN EXISTING ONE
                    if has_essential_changes(final_data, initial_values):
                        n_id = db.replace_search_criteria(old_id=edit_id, new_sc=final_data)
                        if n_id:
                            st.session_state.toast_msg = f"Parameters changed successfully"
                            remove_criteria_from_state(edit_id)
                            update_single_row_in_state(n_id)
                            go_to_list()
                            st.rerun()
                        else:
                            st.error(f"Cannot modify the search criteria due to a database error.")
                    elif has_non_essential_changes(final_data, initial_values):
                        if db.update_search_criteria_nonessential_data(
                                criteria_id=edit_id, data=SearchCriteriaNonEssentialData(
                                    name=final_data.target_name,
                                    description=final_data.description,
                                    execution_hours=final_data.execution_hours,
                                    batch_analyses=final_data.batch_analyses,
                                    anomaly_analyses=final_data.anomaly_analyses
                            )):
                            st.session_state.toast_msg = f"Parameters changed successfully"
                            update_single_row_in_state(edit_id)
                            go_to_list()
                            st.rerun()
                        else:
                            st.error(f"Cannot modify the search criteria due to a database error.")
                    else: # Nothing changed but user clicked save either way
                        st.info("No changes detected. Change something to save.")
                else: # ADDING A NEW ONE
                    n_id = db.save_new_search_criteria(final_data)
                    if n_id:
                        st.session_state.toast_msg = f"Configuration '{target_name}' has been successfully activated!"
                        update_single_row_in_state(n_id)
                        go_to_list()
                        st.rerun()
                    else:
                        st.error(f"Cannot add the search criteria due to a database error.")
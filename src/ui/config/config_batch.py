import datetime
import traceback
from typing import NamedTuple
from typing import Optional, TypedDict


import streamlit as st
import pandas as pd


from database.db_manager import DBManager

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
    batch_an: list[dict]
    anomaly_an: list[dict]

class AnalysisInput(TypedDict):
    id: int
    code: str
    name_en: str
    takes_parameter: bool
    is_checked: bool
    input_value: Optional[float]

#############
# FUNCTIONS #
#############
def validate_criteria_form(db: DBManager, initial_name: str, target_name: str, cities: list, price_min: float, 
                           price_max: float, area_min: float, area_max: float, schedule_input: str, 
                           batch_analyses: list[AnalysisInput], anomaly_analyses: list[AnalysisInput]) -> ValidationResult:
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
    if not cities:
        error_msgs.append("At least one location (city) is required.")
    for city in cities:
        if len(city) > 100:
            error_msgs.append(f"City name '{city}' cannot be longer than 100 characters.")

    # Price
    if price_min > price_max:
        error_msgs.append(f"Minimum price {price_min} must be lesser than maximum price {price_max}")
    # Area
    if area_min > area_max:
        error_msgs.append(f"Minimum area {area_min} must be lesser than maximum area {area_max}")

    # Scheduled hours
    parsed_hours = []
    if schedule_input.strip():
        raw_times = [t.strip() for t in schedule_input.split(',') if t.strip()]
        for t in raw_times:
            try:
                valid_time = datetime.datetime.strptime(t, "%H:%M").time()
                parsed_hours.append(valid_time)
            except Exception as e:
                error_msgs.append(f"Invalid time format: '{t}'. Use HH:MM (24h).")
    else:
        error_msgs.append("Execution schedule cannot be empty.")
    parsed_hours = list(set(parsed_hours)) # Deduplicate...

    # Analytics
    selected_batch_an = [] # <v lists of {'id': id, 'value': val}
    selected_anomaly_an = []
    for an in batch_analyses:
        if an['is_checked']:
            val = an['input_value']
            if an['takes_parameter'] and (val is None):
                error_msgs.append(f"Batch trends analysis '{an['name_en']}' requires a parameter value.")
            selected_batch_an.append({'id': an['id'], 'value': val})
    for an in anomaly_analyses:
        if an['is_checked']:
            val = an['input_value']
            if an['takes_parameter'] and (val is None):
                error_msgs.append(f"Anomaly detection '{an['name_en']}' requires a parameter value.")
            selected_anomaly_an.append({'id': an['id'], 'value': val})
    if not selected_batch_an and not selected_anomaly_an:
        error_msgs.append("Select at least one analysis method.")

    return ValidationResult(
        error_msgs=error_msgs,
        hours=parsed_hours,
        batch_an=selected_batch_an,
        anomaly_an=selected_anomaly_an,
    )

def has_essential_changes(current: dict, initial: dict) -> bool:
    return (
        current["tt"] != initial['transaction_type'] or
        current["mt"] != initial['market_type'] or
        current["p_min"] != float(initial['min_price']) or
        current["p_max"] != float(initial['max_price']) or
        current["a_min"] != float(initial['min_area']) or
        current["a_max"] != float(initial['max_area']) or
        set([c.strip().upper() for c in current["cities"]]) != set([c['city_name'].upper() for c in initial['cities']]) or
        current["props"] != set([p['id'] for p in initial['property_types']]) or
        current["rooms"] != set([r['id'] for r in initial['rooms']])
    )

def has_non_essential_changes(current: dict, initial: dict) -> bool:
    return (
        current["name"] != initial['target_name'] or
        current["desc"] != initial['description'] or
        current["hours"] != set([datetime.datetime.strptime(h['execution_time'], "%H:%M").time() for h in initial['schedule']]) or
        current["batch_an"] != {a['id']: a['param_value'] for a in initial['batch_analyses']} or
        current["anomaly_an"] != {a['id']: a['param_value'] for a in initial['anomaly_analyses']}
    )

def update_form_defaults(transaction_types: list, market_types: list, available_property_types: list[dict], available_rooms: list[dict],
                         form_defaults: dict, initial_values: dict):
    v = initial_values
    form_defaults.update({
        "name": v['target_name'],
        "desc": v['description'],
        "tt_idx": transaction_types.index(v['transaction_type']),
        "mt_index": market_types.index(v['market_type']),
        "p_min": float(v['min_price']), "p_max": float(v['max_price']),
        "a_min": float(v['min_area']), "a_max": float(v['max_area']),
        "hours": ", ".join([h['execution_time'] for h in v['schedule']]),
    })
    saved_prop_ids = [pt['id'] for pt in v.get('property_types', [])]
    form_defaults["sel_props"] = [pt for pt in available_property_types if pt['id'] in saved_prop_ids]
    saved_room_ids = [r['id'] for r in v.get('rooms', [])]
    form_defaults["sel_rooms"] = [r for r in available_rooms if r['id'] in saved_room_ids]
    form_defaults["batch_an_settings"] = {a['id']: a['param_value'] for a in v.get('batch_analyses', [])}
    form_defaults["anomaly_an_settings"] = {a['id']: a['param_value'] for a in v.get('anomaly_analyses', [])}

def save_search_criteria(db: DBManager, target_name: str, desc: str, transaction_type: str, market_type: str, price_min: float, 
                         price_max: float, area_min: float, area_max: float, cities: list, property_type_ids: list, 
                         room_ids: list, hours: list, batch_analyses: list, anomaly_analyses: list, is_new: bool) -> int:
    """
        Saves a new search criteria or an edit of essential values in a search criteria.  
        Returns the id of saved criteria. (If saving failed, returns None)  
        is_new == True - uses localization for adding a new s_c,  
        is_new == False - uses loc for modifying the current s_c.
    """
    if is_new:
        err_module_name = 'config_batch_save'
    else:
        err_module_name = 'config_batch_edit_essential'

    try:
        n_id = db.save_new_search_criteria(
            target_name=target_name.strip(), desc=desc,
            transaction_type=transaction_type, market_type=market_type,
            price_max=float(price_max), price_min=float(price_min), 
            area_max=float(area_max), area_min=float(area_min),
            cities=cities, property_type_ids=property_type_ids,
            room_ids=room_ids, hours=hours,
            batch_analyses=batch_analyses, anomaly_analyses=anomaly_analyses
        )
        return n_id
    except Exception as e:
        db.log_system_error(
            error_source='DASHBOARD',
            module_name=err_module_name,
            error_message=str(e),
            stack_trace=traceback.format_exc(),
            context_data={"target_name": target_name}
        )
        return None

def flatten_criteria_dict_to_row(v: dict):
    """Converts a dictionary given by get_search_criteria() to the format used by st.session_state.main_df."""
    cities_str = ", ".join([c['city_name'] for c in v.get('cities', [])])
    prop_types_str = ", ".join([p['type_name'] for p in v.get('property_types', [])])
    hours_str = ", ".join([h['execution_time'] for h in v.get('schedule', [])])

    return {
        "criteria_id": v['id'],
        "target_name": v['target_name'],
        "description": v['description'] or "",
        "transaction_type": v['transaction_type'],
        "market_type": v['market_type'],
        "min_price": float(v['min_price']),
        "max_price": float(v['max_price']),
        "min_area": float(v['min_area']),
        "max_area": float(v['max_area']),
        "is_active": v['is_active'],
        "cities": cities_str,
        "property_types": prop_types_str,
        "schedule_hours": hours_str
    }

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
    """Gets current DB search_criteria data into st.session_state.main_df"""
    refresh_all_data()
    st.session_state.toast_msg = "Data refreshed from database! 🔄"

############################
# Cached Data &  Fragments #
############################
@st.cache_resource
def get_db():
    return DBManager()
db = get_db()

if "main_df" not in st.session_state:
    st.session_state.main_df = db.get_current_search_criteria()
def refresh_all_data():
    st.session_state.main_df = db.get_current_search_criteria()
def remove_criteria_from_state(criteria_id):
    """Removes a single criteria record from st.session_state.main_df"""
    st.session_state.main_df = st.session_state.main_df[st.session_state.main_df['criteria_id'] != criteria_id]
def update_single_row_in_state(criteria_id):
    """
        Updates a single criteria record in st.session_state.main_df,  
        If it isn't found in main_df, it's added to it.
    """
    new_data_dict = db.get_search_criteria(criteria_id)
    if new_data_dict:
        flat_row = flatten_criteria_dict_to_row(new_data_dict)
        df = st.session_state.main_df
        idx_list = df.index[df['criteria_id'] == criteria_id].tolist()
        if idx_list:
            for key, value in flat_row.items():
                df.at[idx_list[0], key] = value
        else:
            new_row_df = pd.DataFrame([flat_row])
            st.session_state.main_df = pd.concat([new_row_df, df], ignore_index=True)

@st.fragment
def render_criteria_card(row):
    with st.container(border=True):
        c1, c2, spacer, c3 = st.columns([5, 2.5, 0.5, 2.5])
        
        with c1:
            st.subheader(row['target_name'])
            desc = row['description']
            if not desc or desc.strip() == "":
                desc = f"🔍 {row['transaction_type'].upper()} in {row['cities']} | {int(row['min_price'])} - {int(row['max_price'])} PLN"
            st.write(desc)
        
        with c2:
            st.write("**⏰ Schedule:**")
            st.caption(row['schedule_hours'] or "No hours scheduled")
            
        with c3:
            btn_col1, btn_col2 = st.columns([1.2, 1])
            with btn_col1:
                is_active = st.toggle(
                    "🟢 Active" if st.session_state.get(f"active_{row['criteria_id']}", row['is_active']) else "⚪ Paused", 
                    value=row['is_active'], key=f"active_{row['criteria_id']}",
                    on_change=toggle_active_callback, args=(row['criteria_id'],)
                )
                
            with btn_col2:
                if st.button("📝 Edit", key=f"edit_{row['criteria_id']}", on_click=go_to_form, args=(row['criteria_id'],), use_container_width=True):
                    st.rerun()
            
            del_spacer, del_col = st.columns([1.2, 1])
            with del_col:
                with st.popover("🗑️ Delete", use_container_width=True):
                    st.warning(f"Delete {row['target_name']}?")
                    if st.button("🗑️ Delete", key=f"del_{row['criteria_id']}", type="secondary", use_container_width=True, 
                            on_click=soft_delete_criteria_callback, args=(row['criteria_id'], row['target_name'])):
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

    st.divider()
    st.header("🎯 Current Search Criteria")
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

        df = st.session_state.main_df
        if df.empty:
            st.info("No search targets found. Click 'Add New Search Criteria' to start.")
        else:
            with st.container(height=900):
                for _, row in df.iterrows():
                    render_criteria_card(row)
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
    transaction_types = db.get_all_transaction_types()
    market_types = db.get_all_market_types()
    existing_locations = db.get_all_locations()
    available_property_types = db.get_all_property_types()
    available_rooms = db.get_all_room_counts()
    batch_analyses = db.get_batch_analysis_definitions()
    anomaly_analyses = db.get_anomaly_analysis_definitions()

    # If in edit mode - SELECT currently edited data
    form_defaults = {
        "name": "", "desc": "", "tt_idx": 0, "mt_index": 0,
        "p_min": 0.0, "p_max": 1000000.0, "a_min": 30.0, "a_max": 100.0,
        "cities": [], "sel_props": [], "sel_rooms": [], "hours": "",
        "batch_an_settings": {}, "anomaly_an_settings": {}
    }
    initial_values = None
    edit_id = st.session_state.edit_criteria_id
    if edit_id:
        initial_values = db.get_search_criteria(edit_id)
        if initial_values:
            update_form_defaults(transaction_types, market_types, available_property_types, available_rooms, form_defaults, initial_values)

    with st.form("criteria_form", clear_on_submit=False):
        st.subheader("1. General Information")
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            target_name = st.text_input("Search Criteria Name", placeholder="e.g. Mieszkania Kraków", value=form_defaults['name'])
        with col2:
            transaction_type = st.selectbox("Transaction", options=transaction_types, format_func=lambda x: x.capitalize(), index=form_defaults["tt_idx"])
        with col3:
            market_type = st.selectbox("Market", options=market_types, format_func=lambda x: x.replace('_', ' ').capitalize(), index=form_defaults["mt_index"])
        
        description = st.text_area("Description (Optional)", value=form_defaults["desc"])

        st.subheader("2. Locations")
        default_cities = [l for l in existing_locations if l['id'] in [c['id'] for c in (initial_values or {}).get('cities', [])]] if initial_values else []
        selected_existing_cities = st.multiselect(
            "Select from existing cities:", 
            options=existing_locations,
            format_func=lambda x: x['city_name'],
            default=default_cities
        )
        new_cities_input = st.text_input("Or add new cities (comma separated):", placeholder="Gdańsk, Sopot, Gdynia")

        st.subheader("3. Property Filters")
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            price_min = st.number_input("Min Price/Rent (PLN)", min_value=0.0, value=form_defaults["p_min"])
            price_max = st.number_input("Max Price/Rent (PLN)", min_value=0.0, value=form_defaults["p_max"])
        with f_col2:
            area_min = st.number_input("Min Area (m²)", min_value=0.0, value=form_defaults["a_min"])
            area_max = st.number_input("Max Area (m²)", min_value=0.0, value=form_defaults["a_max"])

        st.write("**Specific Requirements:**")
        sel_prop_types = st.multiselect("Property Types (Optional - if not selected, checks all)", options=available_property_types, 
                                        format_func=lambda x: x['type_name'].capitalize(), default=form_defaults["sel_props"])
        sel_rooms = st.multiselect("Room Counts (Optional - if not selected, checks every)", options=available_rooms, 
                                   format_func=lambda x: x['room_label'], default=form_defaults["sel_rooms"])

        st.subheader("4. Automated Schedule")
        schedule_input = st.text_input(
            "Execution Hours (hh:mm, comma separated)", 
            placeholder="08:00, 12:30, 22:00",
            help="Enter hours in 24h format, e.g., 8:00, 15:45",
            value=form_defaults["hours"]
        )

        st.subheader("5. Analytics Activation")
        st.markdown("Please select at least one of the following:")
        an_col1, an_col2 = st.columns(2)
        with an_col1:
            st.caption("Batch Trends (Macro)")
            for an in batch_analyses:
                is_active = an['id'] in form_defaults["batch_an_settings"]
                saved_val = form_defaults["batch_an_settings"].get(an['id'], None)
                c1, c2 = st.columns([3, 2])
                with c1:
                    checked = st.checkbox(an['name_en'], value=is_active, key=f"cb_batch_{an['id']}", help=an['description_en'])
                with c2:
                    if an['takes_parameter']:
                        st.number_input(
                            "Value", 
                            key=f"val_batch_{an['id']}", 
                            value=saved_val, 
                            placeholder="5.0",
                            label_visibility="collapsed"
                        )
        with an_col2:
            st.caption("Anomaly Detection (Micro)")
            for an in anomaly_analyses:
                is_active = an['id'] in form_defaults["anomaly_an_settings"]
                saved_val = form_defaults["anomaly_an_settings"].get(an['id'], None)
                c1, c2 = st.columns([3, 2])
                with c1:
                    st.checkbox(an['name_en'], value=is_active, key=f"cb_ano_{an['id']}", help=an['description_en'])
                with c2:
                    if an.get('takes_parameter'):
                        st.number_input(
                            "Threshold", 
                            key=f"val_ano_{an['id']}", 
                            value=saved_val, 
                            placeholder="5.0",
                            label_visibility="collapsed"
                        )

        # Saving
        st.divider()
        save = st.form_submit_button("Save and Activate Configuration", use_container_width=True, type="primary")
        if save:
            # If user selected nothing, fill with all available
            prop_type_ids = [pt['id'] for pt in (sel_prop_types or available_property_types)]
            room_ids = [r['id'] for r in (sel_rooms or available_rooms)]
            # Prepare the rest of the data
            clean_description = (description or "").strip() or None
            all_cities = list(set([c['city_name'] for c in selected_existing_cities] + 
                                  [c.strip() for c in new_cities_input.split(',') if c.strip()]))
            raw_batch_inputs = [
                {
                    'id': an['id'], 'code': an['code'], 'name_en': an['name_en'], 'takes_parameter': an['takes_parameter'],
                    'is_checked': st.session_state.get(f"cb_batch_{an['id']}"), 
                    'input_value': st.session_state.get(f"val_batch_{an['id']}")
                } for an in batch_analyses
            ]
            raw_anomaly_inputs = [
                {
                    'id': an['id'], 'code': an['code'], 'name_en': an['name_en'], 'takes_parameter': an['takes_parameter'],
                    'is_checked': st.session_state.get(f"cb_ano_{an['id']}"),
                    'input_value': st.session_state.get(f"val_ano_{an['id']}")
                } for an in anomaly_analyses
            ]
            old_name = (initial_values or {}).get('target_name', '')
            val = validate_criteria_form(db, old_name, target_name, all_cities, price_min, price_max, 
                                         area_min, area_max, schedule_input, raw_batch_inputs, raw_anomaly_inputs)
            error_msgs = val.error_msgs
            parsed_hours = val.hours
            selected_batch_an = val.batch_an # <v lists of {'id': id, 'value': val}
            selected_anomaly_an = val.anomaly_an
            if len(error_msgs) == 1:
                st.error(error_msgs[0])
            elif len(error_msgs) > 1:
                st.error("**Please correct the following:**\n" + "\n".join(['- ' + e.strip() for e in error_msgs]))
            else: ### Saving begin
                final_data = {
                    "db": db, "target_name": target_name.strip(), "desc": clean_description,
                    "transaction_type": transaction_type, "market_type": market_type, "price_max": float(price_max),
                    "price_min": float(price_min), "area_max": float(area_max), "area_min": float(area_min),
                    "cities": all_cities, "property_type_ids": prop_type_ids, "room_ids": room_ids,
                    "hours": parsed_hours, "batch_analyses": selected_batch_an, "anomaly_analyses": selected_anomaly_an
                }
                if edit_id: # EDITING AN EXISTING ONE
                    current_essential = { 
                        "tt": transaction_type, "mt": market_type, "p_min": float(price_min), 
                        "p_max": float(price_max), "a_min": float(area_min), "a_max": float(area_max), 
                        "cities": set(all_cities), "props": set(prop_type_ids), "rooms": set(room_ids)
                    }
                    current_non_essential = {
                        "name": target_name.strip(), "desc": clean_description, "hours": set(parsed_hours),
                        "batch_an": {a['id']: a['value'] for a in selected_batch_an},
                        "anomaly_an": {a['id']: a['value'] for a in selected_anomaly_an}
                    }
                    if has_essential_changes(current_essential, initial_values):
                        # soft_delete the old one and make a new one out of changed parameters
                        db.soft_delete_criteria(edit_id)
                        n_id = save_search_criteria(**final_data, is_new=False)
                        if n_id:
                            st.session_state.toast_msg = f"Parameters changed successfuly"
                            remove_criteria_from_state(edit_id)
                            update_single_row_in_state(n_id)
                            go_to_list()
                            st.rerun()
                        else:
                            st.error(f"Cannot modify the search criteria due to a database error.")
                    elif has_non_essential_changes(current_non_essential, initial_values):
                        try:
                            db.update_search_criteria_nonessential_data(
                                criteria_id=edit_id,
                                name=current_non_essential["name"],
                                desc=current_non_essential["desc"],
                                hours=list(current_non_essential["hours"]),
                                batch_an=selected_batch_an,
                                anomaly_an=selected_anomaly_an
                            )
                            st.session_state.toast_msg = f"Parameters changed successfuly"
                            update_single_row_in_state(edit_id)
                            
                            go_to_list()
                            st.rerun()
                        except Exception as e:
                            db.log_system_error(
                                error_source='DASHBOARD',
                                module_name='config_batch_edit_non_essential',
                                error_message=str(e),
                                stack_trace=traceback.format_exc(),
                                context_data={"target_name": target_name}
                            )
                            st.error(f"Cannot modify the search criteria due to a database error.")
                    else: # Nothing changed but user clicked save either way
                        st.info("No changes detected. Change something to save.")
                else: # ADDING A NEW ONE
                    n_id = save_search_criteria(**final_data, is_new=True)
                    if n_id:
                        st.session_state.toast_msg = f"Configuration '{target_name}' has been successfully activated!"
                        update_single_row_in_state(n_id)
                        go_to_list()
                        st.rerun()
                    else:
                        st.error(f"Cannot add the search criteria due to a database error.")
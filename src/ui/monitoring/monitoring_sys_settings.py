from dataclasses import dataclass, field


import streamlit as st
import pandas as pd


from database.db_manager import DBManager
from database.models import SystemSetting, SystemSettingChange

#############
# FUNCTIONS #
#############
def update_edit_fields_values():
    for s in st.session_state.system_settings:
        st.session_state[f"sys_setting_active_{s.setting_key}"] = s.is_enabled
        st.session_state[f"sys_setting_val_{s.setting_key}"] = s.setting_value

def reset_page_with_last_saved_settings() -> bool:
    """Returns True on success, False if failed"""
    if refresh_sys_settings():
        update_edit_fields_values()
        reset_noted_changes()
        return True
    else:
        return False

#############
# CALLBACKS #
#############
def save_callback():
    """UPDATES current DB sys_setting data with st.session_state.system_settings"""
    changed_settings: list[SystemSettingChange] = []
    for s in st.session_state.system_settings:
        if st.session_state.system_settings_changed[s.setting_key]:
            changed_settings.append(SystemSettingChange(
                setting_key=s.setting_key,
                setting_value=int(st.session_state.get(f"sys_setting_val_{s.setting_key}", s.setting_value)),
                is_enabled=bool(st.session_state.get(f"sys_setting_active_{s.setting_key}", s.is_enabled))
            ))
    if db.modify_system_settings(changed_settings):
        refresh_sys_settings()
        reset_noted_changes()
        st.toast("Current changes saved!", icon="✅", duration=8)
    else:
        st.toast("Saving changes failed!", icon="❌", duration=8)

def revert_callback():
    """Gets current DB sys_setting data into st.session_state.system_settings"""
    if reset_page_with_last_saved_settings():
        st.toast("Current changes reverted!", icon="✅", duration=8)
    else:
        st.toast("Reverting changes failed!", icon="❌", duration=8)

def restore_defaults_callback():
    if db.restore_default_system_settings():
        if reset_page_with_last_saved_settings():
            st.toast("Default settings restored!", icon="✅", duration=8)
        else:
            st.toast("Reverting changes failed!", icon="❌", duration=8)
    else:
        st.toast("Reverting changes failed!", icon="❌", duration=8)

def note_change_callback(setting_key: str):
    st.session_state.system_settings_changed[setting_key] = True

###########################
# Cached Data & Fragments #
###########################
def refresh_sys_settings() -> bool:
    """Returns True on success, False on failure"""
    sys_setts = db.get_all_system_settings()
    if sys_setts:
        st.session_state.system_settings = sys_setts
        return True
    else:
        return False
def reset_noted_changes():
    st.session_state.system_settings_changed = dict.fromkeys(st.session_state.system_settings_changed, False)

@st.cache_resource
def get_db():
    return DBManager()
db = get_db()

# On returning to this page, reset widgets and session data
# When switching to another page app.py pops() this session state variable
if "sys_settings_initialized" not in st.session_state:
    st.session_state['sys_settings_initialized'] = True
    if "system_settings" in st.session_state:
        reset_page_with_last_saved_settings()

if "system_settings" not in st.session_state:
    st.session_state.system_settings = db.get_all_system_settings()
if "system_settings_changed" not in st.session_state:
    st.session_state.system_settings_changed = { s.setting_key: False for s in st.session_state.system_settings }

################
# WEBPAGE CODE #
################
st.header("🔧 System Settings")
st.markdown("This menu allows you to view and edit system settings. Listed below are all the settings used by this application alongside brief descriptions explaining the purpose of the given setting.")
st.divider()
col_save, col_revert, col_restore_def, col_empty = st.columns([0.7, 0.7, 0.7, 3.3])
with col_save:
    with st.popover("💾 Save Changes", use_container_width=True):
        st.warning(f"Are you sure?")
        st.button("Yes", key="sys_settings_save_changes_btn", on_click=save_callback, use_container_width=True)
with col_revert:
    st.button("🔄 Revert Changes", on_click=revert_callback, use_container_width=True)
with col_restore_def:
    with st.popover("📋 Restore Defaults", use_container_width=True):
        st.warning(f"Are you sure?")
        st.button("Yes", key="sys_settings_restore_defaults_btn", on_click=restore_defaults_callback, use_container_width=True)
st.subheader("System Settings List:")

with st.container(border=True):
    for s in st.session_state.system_settings:
        st.markdown(f"**{s.name_en}** :gray[- {s.description_en}]")
        # "config"."system_setting_type_enum" AS ENUM('numeric', 'boolean', 'both')
        if s.value_type == "boolean" or s.value_type == "both":
            st.toggle(
                "✅ Enabled" if st.session_state.get(f"sys_setting_active_{s.setting_key}", s.is_enabled) else "❌ Disabled", 
                value=s.is_enabled, key=f"sys_setting_active_{s.setting_key}",
                on_change=note_change_callback, args=(s.setting_key,)
            )
        if s.value_type == "numeric" or s.value_type == "both":
            st.number_input("Value:", key=f"sys_setting_val_{s.setting_key}", value=int(s.setting_value), step=1,
                            on_change=note_change_callback, args=(s.setting_key,))
        st.divider()
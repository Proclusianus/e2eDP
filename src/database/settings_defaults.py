from database.models import SystemSettingChange

DEFAULT_SYSTEM_SETTINGS = [
    SystemSettingChange(
        setting_key='raw_retention_days', 
        setting_value=30, 
        is_enabled=True
    ),
    SystemSettingChange(
        setting_key='clean_inactivity_days', 
        setting_value=5, 
        is_enabled=True
    ),
    SystemSettingChange(
        setting_key='execution_logs_retention_days', 
        setting_value=14, 
        is_enabled=True
    ),
]
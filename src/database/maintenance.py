import datetime
import logging


from sqlalchemy import text


from database.db_manager import DBManager


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("Maintenance")
DB = DBManager()

def should_run(cfg, task_name: str) -> bool:
    if not cfg or not cfg.is_enabled:
        return False
    if cfg.last_run_at is None:
        logger.info(f"Task {task_name}: never run before. Running...")
        return True

    now = datetime.datetime.now(datetime.timezone.utc)
    last_run = cfg.last_run_at
    if last_run.tzinfo is None:
        last_run = last_run.replace(tzinfo=datetime.timezone.utc)
    diff = now - last_run
    
    if diff.days >= cfg.setting_value:
        return True
    
    logger.info(f"Task {task_name}: skipped. Last run was {diff.total_seconds() // 3600:.1f}h ago.")
    return False

def run_maintenance():
    logger.info("Starting system maintenance...")

    settings_list = DB.get_all_system_settings()
    if not settings_list:
        logger.warning("No system settings found or error occurred. Skipping.")
        return
    settings = {s.setting_key: s for s in settings_list}

    cfg = settings.get('raw_retention_days')
    if should_run(cfg, "Raw Retention"):
        logger.info(f"Task: Raw Data Retention ({cfg.setting_value} days)")
        count = DB.maintenance_delete_old_raw_listings(cfg.setting_value)
        if count >= 0:
            logger.info(f"Successfully removed {count} old raw records.")
        else:
            logger.error("Failed to clean raw listings.")

    cfg = settings.get('clean_inactivity_days')
    if should_run(cfg, "Clean Inactivity Check"):
        logger.info(f"Task: Inactivity Check ({cfg.setting_value} days)")
        count = DB.maintenance_deactivate_old_clean_listings(cfg.setting_value)
        if count >= 0:
            logger.info(f"Successfully deactivated {count} listings.")
        else:
            logger.error("Failed to deactivate listings.")

    cfg = settings.get('execution_logs_retention_days')
    if should_run(cfg, "Exec Logs Retention"):
        logger.info(f"Task: Execution Logs Retention ({cfg.setting_value} days)")
        count = DB.maintenance_delete_old_exec_logs(cfg.setting_value)
        if count >= 0:
            logger.info(f"Successfully removed {count} old exec logs.")
        else:
            logger.error("Failed to clean exec logs.")

    cfg = settings.get('system_errors_retention_days')
    if should_run(cfg, "System Errors Retention"):
        logger.info(f"Task: System Errors Retention ({cfg.setting_value} days)")
        count = DB.maintenance_delete_old_system_errors(cfg.setting_value)
        if count >= 0:
            logger.info(f"Successfully removed {count} old system error logs.")
        else:
            logger.error("Failed to clean system errors.")

    logger.info("Maintenance finished.")

if __name__ == "__main__":
    run_maintenance()
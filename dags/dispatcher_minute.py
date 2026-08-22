from datetime import datetime, timezone
import logging


from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.api.common.trigger_dag import trigger_dag


from database.db_manager import DBManager


def check_schedule_and_trigger(**context):
    db = DBManager()
    now = datetime.now().time().replace(second=0, microsecond=0)
    current_time = now.strftime("%H:%M:00")

    criteria_ids = db.get_scheduled_criteria_ids(current_time)
    if not criteria_ids:
        logging.info(f"No tasks scheduled for {current_time}\n")
        return

    for cid in criteria_ids:
        logging.info(f"Triggering pipeline for criteria_id: {cid}")
        trigger_dag(
            dag_id="main_property_pipeline",
            run_id=f"triggered_id_{cid}{datetime.now().timestamp()}",
            conf={"criteria_id": cid},
            replace_microseconds=False
        )

with DAG(
    dag_id="dispatcher_per_minute_check",
    start_date=datetime(2024, 1, 1),
    schedule_interval="* * * * *",
    catchup=False,
    tags=['orchestration']
) as dag:  
    check_task = PythonOperator(
        task_id="check_schedule",
        python_callable=check_schedule_and_trigger
    )
from datetime import datetime


from airflow import DAG
from airflow.operators.bash import BashOperator
from datetime import datetime


with DAG(
    dag_id="daily_system_maintenance",
    start_date=datetime(2024, 1, 1),
    schedule_interval="0 18 * * *",
    catchup=False,
    tags=['system', 'maintenance']
) as dag:
    run_maintenance = BashOperator(
        task_id="run_maintenance_script",
        bash_command="python3 /opt/airflow/src/database/maintenance.py",
    )
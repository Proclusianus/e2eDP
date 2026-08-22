from datetime import datetime


from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id="main_property_pipeline",
    start_date=datetime(2024, 1, 1),
    schedule_interval=None,
    catchup=False,
    tags=['main pipeline']
) as dag:
    scrape_task = BashOperator(
        task_id="scrape_task",
        bash_command="python3 /opt/airflow/src/scraper/scraper.py {{ dag_run.conf['criteria_id'] }}",
        do_xcom_push=True
    )
    clean_task = BashOperator(
        task_id="clean_task",
        bash_command="python3 /opt/airflow/src/processing/cleaner.py {{ ti.xcom_pull(task_ids='scrape_task') }}",
        do_xcom_push=True
    )
    analyze_task = BashOperator(
        task_id="analyze_task",
        bash_command="python3 /opt/airflow/src/processing/analyzer.py {{ ti.xcom_pull(task_ids='clean_task') }}",
        do_xcom_push=False
    )
    scrape_task >> clean_task >> analyze_task
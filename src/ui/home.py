import streamlit as st

st.title("🏙️ Real Estate Pricing Analytics Platform")
st.markdown("""
### Project Overview
This is an **End-to-End Data Engineering platform** designed to track, analyze, and alert on real estate market trends in Poland. 
The system automates the entire data lifecycle—from raw web scraping to statistical analysis and professional reporting.
""")

st.header("🌟 Key Features")
col1, col2, col3 = st.columns(3)
with col1:
    st.subheader("🤖 Automation")
    st.write("""
    - **Distributed Scraping**: Powered by Playwright & Stealth.
    - **Orchestration**: Managed by Apache Airflow.
    - **Tor/VPN Integration**: Automated IP rotation to bypass anti-bot systems.
    """)
with col2:
    st.subheader("📊 Analytics")
    st.write("""
    - **Anomaly Detection**: Price drops and market outliers detection.
    - **Market Dynamics**: Macro-scale trend analysis (Median, Avg, Supply).
    - **Statistical Binning**: Price distribution histograms using NumPy.
    """)
with col3:
    st.subheader("🛡️ Engineering")
    st.write("""
    - **Medallion Architecture**: Bronze (Raw), Silver (Clean), Gold (Analytics).
    - **Data Integrity**: SCD Type 2 logic for tracking history.
    - **Idempotency**: "Nuke & Boot" ready SQL infrastructure.
    """)
st.divider()

st.header("🛠️ Tech Stack")
st.markdown("""
| Layer | Technologies |
| :--- | :--- |
| **Languages** | ![Python](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python) ![SQL](https://img.shields.io/badge/SQL-PostgreSQL-lightgrey?style=flat-square&logo=postgresql) |
| **Database** | ![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791?style=flat-square&logo=postgresql) ![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-Toolkit-red?style=flat-square&logo=sqlalchemy) |
| **Orchestration** | ![Airflow](https://img.shields.io/badge/Apache_Airflow-2.9-red?style=flat-square&logo=apache-airflow) |
| **Data Processing** | ![Pandas](https://img.shields.io/badge/Pandas-Cleaning-150458?style=flat-square&logo=pandas) ![NumPy](https://img.shields.io/badge/NumPy-Math-013243?style=flat-square&logo=numpy) |
| **Scraping & Stealth** | ![Playwright](https://img.shields.io/badge/Playwright-Automation-2EAD33?style=flat-square&logo=playwright) ![Stealth](https://img.shields.io/badge/Playwright--Stealth-Privacy-blueviolet?style=flat-square) |
| **Infrastructure** | ![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker) ![Gluetun](https://img.shields.io/badge/Gluetun-VPN_Gateway-555555?style=flat-square&logo=docker) |
| **Quality & Testing** | ![Pytest](https://img.shields.io/badge/Pytest-Testing-0A9EDC?style=flat-square&logo=pytest) |
| **Reporting** | ![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-FF4B4B?style=flat-square&logo=streamlit) ![FPDF2](https://img.shields.io/badge/FPDF2-PDF_Generation-yellow?style=flat-square) |
""")
st.divider()

st.header("🏗️ System Architecture & Design")
tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(["Infrastructure (SAD)", "Data Flow (SD)", "Database (ERD)", "Results Reporting (SD)", "Use Cases (UCD)", "Other Actions (SD)"])
with tab1:
    st.markdown("#### Containerized Infrastructure")
    st.info("The system is fully containerized using Docker Compose, isolating the Database, Orchestrator, and Dashboard.")
    st.image("./src/assets/doc/SAD.png", caption="System Architecture Diagram")
    st.code("""
    Services:
    - PostgreSQL 15 (Data Warehouse)
    - Apache Airflow (Orchestrator)
    - Streamlit (Business UI)
    - Gluetun (VPN Gateway)
    - Tor Proxy (Unused)
    """, language="text")
with tab2:
    st.markdown("#### End-to-End Data Pipeline")
    st.write("Visual representation of how raw JSON data from portals transforms into actionable insights.")
    st.image("./src/assets/doc/SD_Data_Pipeline.png", caption="Sequence Diagram")
with tab3:
    st.markdown("#### Relational Data Model")
    st.write("Highly normalized schema with support for multi-language dictionaries and snapshotting.")
    st.image("./src/assets/doc/ERD.png", caption="Entity Relationship Diagram")
with tab4:
    st.markdown("#### Export Analytics Results To PDF")
    st.write("Visual and easy-to-understand representation in the form of a PDF document.")
    st.image("./src/assets/doc/SD_pdf.png", caption="Sequence Diagram")
with tab5:
    st.markdown("#### Application's Use Cases")
    st.write("Initial project goals defined by what service it ought to provide to the end user.")
    st.image("./src/assets/doc/UCD.png", caption="Use Case Diagram")
with tab6:
    st.markdown("#### Other Actions")
    st.write("Here are some other sequence diagrams, showing how the application performs maintenance operations on its data, or how a user may interact with it.")
    st.image("./src/assets/doc/SD_Database_Maintenance.png", caption="Database Maintenance Sequence Diagram")
    st.image("./src/assets/doc/SD_Application_Action_Management.png", caption="Application Action Management Sequence Diagram")
    st.image("./src/assets/doc/SD_Monitor_Operations_Status.png", caption="Operations Status Monitoring Sequence Diagram")
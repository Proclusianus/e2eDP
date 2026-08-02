from dataclasses import dataclass, field
import datetime
import os
import traceback
import json

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv


from database.models import Location, GlobalNotificationRule, AnomalyAnalysis, ActivatedAnalysis, SystemSetting, SystemSettingChange
from database.settings_defaults import DEFAULT_SYSTEM_SETTINGS

# Load credentials from env
load_dotenv()

class DBManager:
    def __init__(self):
        user = os.getenv("POSTGRES_USER")
        password = os.getenv("POSTGRES_PASSWORD")
        db = os.getenv("POSTGRES_DB")
        if os.getenv("RUNNING_IN_DOCKER") == "true":
            host = "pricing_postgres"
            port = "5432"
        else:
            host = "localhost"
            port = "54321"

        self.conn_url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
        self.engine = create_engine(self.conn_url)

    ################
    # DICTIONARIES #
    ################
    def _get_or_create_location_id(self, conn, city_name: str) -> int:
        """
        Private method which handles adding and standardizing locations.  
        (Pass a new location name to INSERT it and SELECT its ID)  
        (Pass an existing location's name to SELECT its ID)
        """
        clean_city = city_name.strip().upper()
        conn.execute(
            text("INSERT INTO config.locations (city_name) VALUES (:c) ON CONFLICT (city_name) DO NOTHING"),
            {"c": clean_city}
        )
        res = conn.execute(
            text("SELECT id FROM config.locations WHERE city_name = :c"),
            {"c": clean_city}
        )
        return res.fetchone()[0]

    def get_all_locations(self) -> list[Location]:
        """Returns a list of Locations. Returns an empty list if none exist or on error."""
        query_str = "SELECT id, INITCAP(city_name) as city_name FROM config.locations ORDER BY city_name"
        try:
            locations = []
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str))
                for row in result:
                    r = row._mapping
                    locations.append(Location(
                        location_id=r['id'],
                        city_name=r['city_name']
                    ))
                return locations
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='get_all_locations',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def _get_enum_labels(self, enum_name: str) -> list[str]:
        """Private method for getting enum labels. Returns empty list if no labels were found or on error."""
        query = text("""
            SELECT enumlabel FROM pg_enum
            JOIN pg_type ON pg_enum.enumtypid = pg_type.oid
            WHERE pg_type.typname = :enum_name
            ORDER BY enumsortorder;
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"enum_name": enum_name})
                return [row[0] for row in result]
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name=f'get_enum_{enum_name}',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_all_transaction_types(self) -> list[str]:
        """Returns a list of enum values labels (strings). Returns empty list if no labels were found or on error."""
        return self._get_enum_labels('transaction_type_enum')
            
    def get_all_market_types(self) -> list[str]:
        """Returns a list of enum values labels (strings). Returns empty list if no labels were found or on error."""
        return self._get_enum_labels('market_type_enum')

    def get_anomaly_analysis_definitions(self) -> list[AnomalyAnalysis]:
        """Returns a list of AnomalyAnalysis. Returns an empty list if none exist or on error."""
        query_str = "SELECT id, code, name_en, description_en, name_pl, description_pl, takes_parameter FROM config.anomaly_analysis_dictionary"
        try:
            anomaly_analyses = []
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str))
                for row in result:
                    r = row._mapping
                    anomaly_analyses.append(AnomalyAnalysis(
                        id=r['id'],
                        code=r['code'],
                        name_pl=r['name_pl'],
                        name_en=r['name_en'],
                        description_pl=r['description_pl'],
                        description_en=r['description_en'],
                        takes_parameter=r['takes_parameter']
                    ))
                return anomaly_analyses
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='get_anomaly_analysis_definitions',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    ### vvv REFACTOR
    def get_all_locations_old(self):
        """Returns a list of record dictionaries (id, city_name)"""
        query = "SELECT id, INITCAP(city_name) as city_name FROM config.locations ORDER BY city_name"
        return pd.read_sql(query, self.engine).to_dict('records')

    def get_anomaly_analysis_definitions_old(self):
        """Returns a list of record dictionaries (entire record)"""
        query = "SELECT id, code, name_en, description_en, name_pl, description_pl, takes_parameter FROM config.anomaly_analysis_dictionary"
        return pd.read_sql(query, self.engine).to_dict('records')

    def get_all_property_types(self):
        """Returns a list of record dictionaries (id, type_name)"""
        query = "SELECT id, type_name FROM config.property_types ORDER BY type_name"
        return pd.read_sql(query, self.engine).to_dict('records')

    def get_all_room_counts(self):
        """Returns a list of record dictionaries (id, room_label)"""
        query = "SELECT id, room_label FROM config.room_counts ORDER BY id"
        return pd.read_sql(query, self.engine).to_dict('records')

    def get_batch_analysis_definitions(self):
        """Returns a list of record dictionaries (entire record)"""
        query = "SELECT id, code, name_en, description_en, name_pl, description_pl, takes_parameter FROM config.batch_analysis_dictionary"
        return pd.read_sql(query, self.engine).to_dict('records')

    ###########################
    # SEARCH CRITERIA METHODS #
    ###########################
    def get_current_search_criteria(self):
        """Returns all non-soft_deleted search criteria"""
        query = """
            SELECT 
                sc.id as criteria_id,
                sc.target_name,
                COALESCE(sc.description, '') as description,
                sc.transaction_type,
                sc.market_type,
                sc.min_price,
                sc.max_price,
                sc.min_area,
                sc.max_area,
                sc.is_active,
                string_agg(DISTINCT INITCAP(l.city_name), ', ') as cities,
                string_agg(DISTINCT pt.type_name, ', ') as property_types,
                string_agg(DISTINCT to_char(sch.execution_time, 'HH24:MI'), ', ') as schedule_hours
            FROM config.search_criteria sc
            LEFT JOIN config.criteria_locations cl ON sc.id = cl.criteria_id
            LEFT JOIN config.locations l ON cl.location_id = l.id
            LEFT JOIN config.criteria_property_types cpt ON sc.id = cpt.criteria_id
            LEFT JOIN config.property_types pt ON cpt.property_type_id = pt.id
            LEFT JOIN config.search_criteria_schedule sch ON sc.id = sch.criteria_id
            WHERE sc.is_soft_deleted = false
            GROUP BY 
                sc.id, sc.target_name, sc.description, sc.transaction_type, 
                sc.market_type, sc.min_price, sc.max_price, sc.min_area, 
                sc.max_area, sc.is_active
            ORDER BY sc.created_at DESC;
        """
        return pd.read_sql(query, self.engine)

    def get_search_criteria(self, criteria_id: int) -> dict:
        """
            Retrieves the complete configuration for a specific search criteria, 
            including all nested relational data.  
            If no such search criteria exists, returns None   

            Returns a dictionary with the following keys:
            - id (int): The unique database identifier for the criteria.
            - target_name (str): User-defined name of the search target.
            - description (str): Optional notes or metadata.
            - transaction_type (enum): Either 'sale' or 'rent'.
            - market_type (enum): 'primary', 'secondary', or 'both'.
            - min_price (Decimal): Minimum price threshold.
            - max_price (Decimal): Maximum price threshold.
            - min_area (Decimal): Minimum surface area in m2.
            - max_area (Decimal): Maximum surface area in m2.
            - is_active (bool): Current operational status.
            - is_soft_deleted (bool): Logical deletion flag.
            - created_at (datetime): Timestamp of creation.
            - cities (list[dict]): List of objects with {'id', 'city_name'}.
            - property_types (list[dict]): List of objects with {'id', 'type_name'}.
            - rooms (list[dict]): List of objects with {'id', 'room_label'}.
            - schedule (list[dict]): List of objects with {'id', 'execution_time' (str HH:MM)}.
            - batch_analyses (list[dict]): List of {'id', 'param_value'} for macro trends.
            - anomaly_analyses (list[dict]): List of {'id', 'param_value'} for micro alerts.
        """
        with self.engine.connect() as conn:
            main_row = conn.execute(text("SELECT * FROM config.search_criteria WHERE id = :id"), {"id": criteria_id}).fetchone()
            if not main_row: return None

            data = dict(main_row._mapping)
            data['cities'] = [
                {"id": r._mapping['id'], "city_name": r._mapping['city_name']}
                for r in conn.execute(text("""
                    SELECT l.id, INITCAP(l.city_name) as city_name FROM config.locations l
                    JOIN config.criteria_locations cl ON l.id = cl.location_id
                    WHERE cl.criteria_id = :id
                """), {"id": criteria_id})
            ]
            data['property_types'] = [
                {"id": r._mapping['id'], "type_name": r._mapping['type_name']}
                for r in conn.execute(text("""
                    SELECT pt.id, pt.type_name FROM config.property_types pt
                    JOIN config.criteria_property_types cpt ON pt.id = cpt.property_type_id
                    WHERE cpt.criteria_id = :id
                """), {"id": criteria_id})
            ]
            data['rooms'] = [
                {"id": r._mapping['id'], "room_label": r._mapping['room_label']}
                for r in conn.execute(text("""
                    SELECT r.id, r.room_label FROM config.room_counts r
                    JOIN config.criteria_rooms cr ON r.id = cr.room_id
                    WHERE cr.criteria_id = :id 
                """), {"id": criteria_id})
            ]
            data['schedule'] = [
                {"id": r._mapping['id'], "execution_time": r._mapping['execution_time'].strftime("%H:%M")}
                for r in conn.execute(text("""
                    SELECT id, execution_time FROM config.search_criteria_schedule
                    WHERE criteria_id = :id
                """), {"id": criteria_id})
            ]
            data['batch_analyses'] = [
                {"id": r._mapping['analysis_id'], "param_value": float(r._mapping['param_value']) if r._mapping['param_value'] else None}
                for r in conn.execute(text("""
                    SELECT analysis_id, param_value FROM config.activated_batch_analyses
                    WHERE criteria_id = :id
                """), {"id": criteria_id})
            ]
            data['anomaly_analyses'] = [
                {"id": r._mapping['analysis_id'], "param_value": float(r._mapping['param_value']) if r._mapping['param_value'] else None}
                for r in conn.execute(text("""
                    SELECT analysis_id, param_value FROM config.activated_anomaly_analyses
                    WHERE criteria_id = :id
                """), {"id": criteria_id})
            ]

            return data

    def save_new_search_criteria(self, target_name: str, desc: str, transaction_type: str, market_type: str, price_min: float, 
                                 price_max: float, area_min: float, area_max: float, cities: list, property_type_ids: list, 
                                 room_ids: list, hours: list, batch_analyses: list, anomaly_analyses: list) -> int:
        """
            Returns the the ID (int) of the created search criteria  
              
            cities: list[str], property_type_ids: list[int],  
            room_ids: list[int], hours: list[datetime.time],  
            batch_analyses: list[dict] {'id': int, 'value': float/None},  
            anomaly_analyses: list[dict] {'id': int, 'value': float/None}
        """
        with self.engine.begin() as conn:
            # First create a record in the table itself...
            res = conn.execute(text("""
                    INSERT INTO config.search_criteria
                    (target_name, description, transaction_type, market_type, min_price, max_price, min_area, max_area)
                    VALUES
                    (:name, :desc, :tt, :mt, :pmin, :pmax, :amin, :amax)
                    RETURNING id
                """),{
                    "name": target_name, "desc": desc, "tt": transaction_type, "mt": market_type,
                    "pmin": price_min, "pmax": price_max, "amin": area_min, "amax": area_max 
            })
            new_id = res.fetchone()[0]

            # Now take care of the FKs...
            for city in cities:
                loc_id = self._get_or_create_location_id(conn, city)
                conn.execute(text("INSERT INTO config.criteria_locations (criteria_id, location_id) VALUES (:cid, :lid)"), 
                            {"cid": new_id, "lid": loc_id})

            for pt in property_type_ids:
                conn.execute(text("INSERT INTO config.criteria_property_types (criteria_id, property_type_id) VALUES (:cid, :ptid)"), 
                            {"cid": new_id, "ptid": pt})

            for rid in room_ids:
                conn.execute(text("INSERT INTO config.criteria_rooms (criteria_id, room_id) VALUES (:cid, :rid)"), 
                            {"cid": new_id, "rid": rid})

            for hour in hours:
                conn.execute(text("INSERT INTO config.search_criteria_schedule (criteria_id, execution_time) VALUES (:cid, :t)"), 
                            {"cid": new_id, "t": hour})

            for ba in batch_analyses:
                conn.execute(text("INSERT INTO config.activated_batch_analyses (criteria_id, analysis_id, param_value) VALUES (:cid, :aid, :pv)"), 
                            {"cid": new_id, "aid": ba['id'], "pv": ba['value']})
            
            for aa in anomaly_analyses:
                conn.execute(text("INSERT INTO config.activated_anomaly_analyses (criteria_id, analysis_id, param_value) VALUES (:cid, :aid, :pv)"), 
                            {"cid": new_id, "aid": aa['id'], "pv": aa['value']})

            return new_id

    def does_this_search_criteria_name_exist(self, name: str, ignore_soft_deleted: bool = True) -> bool:
        """
            Checks if the given search_criteria name already exists (not case sensitive).  
            ignore_soft_deleted:  
            True (default) -> checks only active/paused items (user can re-use names of deleted items).  
            False -> checks all items (strict uniqueness).
        """
        query_str = "SELECT 1 FROM config.search_criteria WHERE LOWER(target_name) = LOWER(:name)"
        if ignore_soft_deleted:
            query_str += " AND is_soft_deleted = false"

        with self.engine.connect() as conn:
            result = conn.execute(text(query_str), {"name": name.strip()})
            return result.fetchone() is not None

    def soft_delete_criteria(self, criteria_id: int) -> bool:
        """
        Marks search criteria as soft_deleted and deletes its schedule records (config.search_criteria_schedule)  
        Returns True if successfuly soft deleted the criterion.
        """
        query_update = text("""
            UPDATE config.search_criteria 
            SET is_active = false, is_soft_deleted = true 
            WHERE id = :id
        """)
        query_del_schedule = text("""
            DELETE FROM config.search_criteria_schedule 
            WHERE criteria_id = :id
        """)
        # The rest should be kept to retain important information
        try:
            with self.engine.begin() as conn:
                conn.execute(query_update, {"id": criteria_id})
                conn.execute(query_del_schedule, {"id": criteria_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='soft_delete_criteria',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"criteria_id": criteria_id}
            )
            return False

    def set_criteria_activation_status(self, criteria_id: int, is_active: bool) -> bool:
        """Returns True if status changed successfuly"""
        query = text("UPDATE config.search_criteria SET is_active = :status WHERE id = :id")
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"status": is_active, "id": criteria_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='update_criteria_status',
                error_message=str(e)
            )
            return False

    def update_search_criteria_nonessential_data(self, criteria_id, name, desc, hours, batch_an, anomaly_an):
        """Deletes & Re-inserts non essential data for a search criteria"""
        with self.engine.begin() as conn:
            # Update name & desc in search_criteria
            conn.execute(text("""
                UPDATE config.search_criteria 
                SET target_name = :name, description = :desc 
                WHERE id = :id
            """), {"name": name, "desc": desc, "id": criteria_id})

            # Delete & Re-insert the schedule
            conn.execute(text("DELETE FROM config.search_criteria_schedule WHERE criteria_id = :id"), {"id": criteria_id})
            for hour in hours:
                conn.execute(text("INSERT INTO config.search_criteria_schedule (criteria_id, execution_time) VALUES (:id, :t)"), 
                            {"id": criteria_id, "t": hour})

            # Delete & Re-insert batch analyses
            conn.execute(text("DELETE FROM config.activated_batch_analyses WHERE criteria_id = :id"), {"id": criteria_id})
            for ba in batch_an:
                conn.execute(text("""
                    INSERT INTO config.activated_batch_analyses (criteria_id, analysis_id, param_value) 
                    VALUES (:id, :aid, :pv)
                """), {"id": criteria_id, "aid": ba['id'], "pv": ba['value']})

            # Delete & Re-insert anomaly analyses
            conn.execute(text("DELETE FROM config.activated_anomaly_analyses WHERE criteria_id = :id"), {"id": criteria_id})
            for aa in anomaly_an:
                conn.execute(text("""
                    INSERT INTO config.activated_anomaly_analyses (criteria_id, analysis_id, param_value) 
                    VALUES (:id, :aid, :pv)
                """), {"id": criteria_id, "aid": aa['id'], "pv": aa['value']})

    ########################
    # GLOBAL NOTIFICATIONS #
    ########################
    def get_current_global_notifs(self) -> list[GlobalNotificationRule]:
        """
            Returns all non-soft_deleted global notification rules mapped to GlobalNotificationRule dataclass.  
            If there aren't any or an error occurs returns an empty list.
        """
        query = text("""
            SELECT
                gnr.id,
                gnr.rule_name,
                COALESCE(gnr.description, '') as description,
                gnr.transaction_type,
                gnr.is_searching_all_cities,
                gnr.is_active,
                COALESCE(json_agg(DISTINCT INITCAP(l.city_name)) FILTER (WHERE l.city_name IS NOT NULL), '[]'::json) as cities_json,
                json_agg(DISTINCT to_char(gs.execution_time, 'HH24:MI')) as hours_json,
                json_agg(DISTINCT jsonb_build_object('id', an.analysis_id, 'val', an.param_value)) as analyses_json
            FROM config.global_notification_rules gnr
            LEFT JOIN config.global_rule_locations grl ON gnr.id = grl.global_rule_id
            LEFT JOIN config.locations l ON l.id = grl.location_id
            LEFT JOIN config.global_rules_schedule gs ON gs.global_rule_id = gnr.id
            LEFT JOIN config.activated_notifications an ON an.global_rule_id = gnr.id
            WHERE gnr.is_soft_deleted = false
            GROUP BY gnr.id
            ORDER BY gnr.created_at DESC;
        """)
        try:
            rules = []
            with self.engine.begin() as conn:
                result = conn.execute(query)
                for row in result:
                    r = row._mapping
                    # Map data to ActivatedAnalysis
                    analyses_objs = [
                        ActivatedAnalysis(analysis_id=a['id'], param_value=float(a['val']) if a['val'] is not None else None)
                        for a in r['analyses_json']
                    ]
                    # Map execution_hours to datetime.time
                    hours_objs = [
                        datetime.datetime.strptime(h, "%H:%M").time()
                        for h in r['hours_json']
                    ]
                    # Create data struct
                    rules.append(GlobalNotificationRule(
                        id=r['id'],
                        rule_name=r['rule_name'],
                        description=r['description'],
                        transaction_type=r['transaction_type'],
                        is_searching_all_cities=r['is_searching_all_cities'],
                        is_active=r['is_active'],
                        cities=r['cities_json'],
                        analyses=analyses_objs,
                        execution_hours=hours_objs
                    ))
            return rules
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='get_current_global_notifs',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_global_notification_rule(self, gnr_id: int) -> GlobalNotificationRule | None:
        """
            Retrieves the complete configuration for a specific global notification rule, 
            including all nested relational data.  
            If no such gnr exists, returns None.
        """
        query = text("""
            SELECT
                gnr.id,
                gnr.rule_name,
                COALESCE(gnr.description, '') as description,
                gnr.transaction_type,
                gnr.is_searching_all_cities,
                gnr.is_active,
                COALESCE(json_agg(DISTINCT INITCAP(l.city_name)) FILTER (WHERE l.city_name IS NOT NULL), '[]') as cities_json,
                COALESCE(json_agg(DISTINCT to_char(gs.execution_time, 'HH24:MI')) FILTER (WHERE gs.execution_time IS NOT NULL), '[]') as hours_json,
                COALESCE(json_agg(DISTINCT jsonb_build_object('id', an.analysis_id, 'val', an.param_value)) FILTER (WHERE an.analysis_id IS NOT NULL), '[]') as analyses_json
            FROM config.global_notification_rules gnr
            LEFT JOIN config.global_rule_locations grl ON gnr.id = grl.global_rule_id
            LEFT JOIN config.locations l ON l.id = grl.location_id
            LEFT JOIN config.global_rules_schedule gs ON gs.global_rule_id = gnr.id
            LEFT JOIN config.activated_notifications an ON an.global_rule_id = gnr.id
            WHERE gnr.id = :id
            GROUP BY gnr.id;
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"id": gnr_id}).fetchone()
                if result is None:
                    return None
                r = result._mapping
                analyses_objs = [
                    ActivatedAnalysis(analysis_id=a['id'], param_value=float(a['val']) if a['val'] is not None else None)
                    for a in r['analyses_json']
                ]
                hours_objs = [
                    datetime.datetime.strptime(h, "%H:%M").time()
                    for h in r['hours_json']
                ]
                return GlobalNotificationRule(
                    id=r['id'],
                    rule_name=r['rule_name'],
                    description=r['description'],
                    transaction_type=r['transaction_type'],
                    is_searching_all_cities=r['is_searching_all_cities'],
                    is_active=r['is_active'],
                    cities=r['cities_json'],
                    analyses=analyses_objs,
                    execution_hours=hours_objs
                )
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='get_global_notification_rule',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"gnr_id": gnr_id}
            )
            return None

    def save_new_global_notification_rule(self, gnr: GlobalNotificationRule, conn=None) -> int | None:
        """
            Saves a new global_notification_rule.  
            Returns id of created gnr, or None if the creation failed.
        """
        def _execute_save_logic(c):
            res = c.execute(text("""
                INSERT INTO config.global_notification_rules 
                (rule_name, description, transaction_type, is_searching_all_cities)
                VALUES (:name, :desc, :tt, :all_cities)
                RETURNING id
            """), {"name": gnr.rule_name, "desc": gnr.description, "tt": gnr.transaction_type, "all_cities": gnr.is_searching_all_cities})
            new_id = res.fetchone()[0]
            if not gnr.is_searching_all_cities and gnr.cities:
                for city_name in gnr.cities:
                    loc_id = self._get_or_create_location_id(c, city_name)
                    c.execute(text("INSERT INTO config.global_rule_locations (global_rule_id, location_id) VALUES (:grid, :lid)"), 
                            {"grid": new_id, "lid": loc_id})
            for hour in gnr.execution_hours:
                c.execute(text("INSERT INTO config.global_rules_schedule (global_rule_id, execution_time) VALUES (:grid, :t)"), 
                        {"grid": new_id, "t": hour})
            for an in gnr.analyses:
                c.execute(text("INSERT INTO config.activated_notifications (global_rule_id, analysis_id, param_value) VALUES (:grid, :aid, :pv)"), 
                        {"grid": new_id, "aid": an.analysis_id, "pv": an.param_value})
            return new_id

        if conn is None:
            try:
                with self.engine.begin() as new_conn:
                    return _execute_save_logic(new_conn)
            except Exception as e:
                self.log_system_error(
                    error_source='DATABASE',
                    module_name='save_new_global_notification_rule',
                    error_message=str(e),
                    stack_trace=traceback.format_exc(),
                    context_data={"rule_name": gnr.rule_name}
                )
                return None
        else:
            return _execute_save_logic(conn)

    def soft_delete_global_notification_rule(self, gnr_id: int, conn=None) -> bool:
        """
            Marks GNR as soft_deleted and deletes its schedule records (config.global_rules_schedule)  
            Returns True if successfuly soft deleted the GNR.
        """
        query_update = text("""
            UPDATE config.global_notification_rules 
            SET is_active = false, is_soft_deleted = true 
            WHERE id = :id
        """)
        query_del_schedule = text("""
            DELETE FROM config.global_rules_schedule 
            WHERE global_rule_id = :id
        """)
        if conn is None:
            try:
                with self.engine.begin() as new_conn:
                    new_conn.execute(query_update, {"id": gnr_id})
                    new_conn.execute(query_del_schedule, {"id": gnr_id})
                return True
            except Exception as e:
                self.log_system_error(
                    error_source='DATABASE',
                    module_name='soft_delete_global_notification_rule',
                    error_message=str(e),
                    stack_trace=traceback.format_exc(),
                    context_data={"gnr_id": gnr_id}
                )
                return False
        else: # Calling function should handle the fail case
            conn.execute(query_update, {"id": gnr_id})
            conn.execute(query_del_schedule, {"id": gnr_id})
            return True

    def replace_global_rule(self, old_id: int, new_gnr: GlobalNotificationRule) -> int | None:
        """
            Soft deletes the old version of the rule, and adds the new one.  
            Returns id of created gnr, or None if the operation failed.
        """
        try:
            with self.engine.begin() as conn:
                self.soft_delete_global_notification_rule(old_id, conn=conn)
                new_id = self.save_new_global_notification_rule(new_gnr, conn=conn)
                return new_id
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='replace_global_rule',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"old_id": old_id, "new_name": new_gnr.rule_name}
            )
            return None

    def set_global_notification_activation_status(self, gnr_id: int, status: bool) -> bool:
        """Returns True if status changed successfuly"""
        query = text("""
            UPDATE config.global_notification_rules 
            SET is_active = :status 
            WHERE id = :id
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"status": status, "id": gnr_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='set_global_notification_activation_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"gnr_id": gnr_id}
            )
            return False

    def update_global_notification_nonessential_data(self, gnr_id: int, name: str, desc: str | None, hours: list[datetime.time], 
                                                     analyses: list[ActivatedAnalysis]) -> bool:
        """
            Deletes & Re-inserts non essential data for a GNR.  
            Returns True if operation succeeded or False if failed.
        """
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    UPDATE config.global_notification_rules 
                    SET rule_name = :name, description = :desc 
                    WHERE id = :id
                """), {"name": name, "desc": desc, "id": gnr_id})
                conn.execute(text("DELETE FROM config.global_rules_schedule WHERE global_rule_id = :id"), {"id": gnr_id})
                for hour in hours:
                    conn.execute(text("""
                        INSERT INTO config.global_rules_schedule (global_rule_id, execution_time) 
                        VALUES (:id, :t)
                    """), {"id": gnr_id, "t": hour})
                conn.execute(text("DELETE FROM config.activated_notifications WHERE global_rule_id = :id"), {"id": gnr_id})
                for an in analyses:
                    conn.execute(text("""
                        INSERT INTO config.activated_notifications (global_rule_id, analysis_id, param_value) 
                        VALUES (:id, :aid, :pv)
                    """), {"id": gnr_id, "aid": an.analysis_id, "pv": an.param_value})
                return True
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='update_global_notification_nonessential_data',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return False

    def does_global_notification_rule_name_exist(self, name: str, ignore_soft_deleted: bool = True) -> bool | None:
        """
            Checks if the given GNR name already exists (not case sensitive).  
            ignore_soft_deleted:  
            True (default) -> checks only active/paused items (user can re-use names of deleted items).  
            False -> checks all items (strict uniqueness).  
            Returns None if failed to check name existence.
        """
        query_str = "SELECT 1 FROM config.global_notification_rules WHERE LOWER(rule_name) = LOWER(:name)"
        if ignore_soft_deleted:
            query_str += " AND is_soft_deleted = false"
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str), {"name": name.strip()})
                return result.fetchone() is not None
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='does_global_notification_rule_name_exist',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"gnr_name": name, "ignore_sd": ignore_soft_deleted}
            )
            return None

    ###########################
    # SYSTEM SETTINGS METHODS #
    ###########################
    def get_all_system_settings(self) -> list[SystemSetting]:
        """
            Returns all system settings. If none are in the DB, or on error, returns an empty list.  
            Note that there should ALWAYS be >=1 setting in the DB.
        """
        query = text("""SELECT setting_key, setting_value, is_enabled, value_type, name_pl, name_en, description_pl, description_en FROM config.system_settings ORDER BY name_en""")
        try:
            sys_settings = []
            with self.engine.connect() as conn:
                result = conn.execute(query)
                for row in result:
                    r = row._mapping
                    sys_settings.append(SystemSetting(
                        setting_key=r['setting_key'],
                        setting_value=r['setting_value'],
                        is_enabled=r['is_enabled'],
                        value_type=r['value_type'],
                        name_pl=r['name_pl'],
                        name_en=r['name_en'],
                        description_pl=r['description_pl'],
                        description_en=r['description_en']
                    ))
                return sys_settings
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE', 
                module_name='get_all_system_settings', 
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def modify_system_setting(self, setting_key: str, setting_value: int | None = None, is_enabled: bool | None = None, conn = None) -> bool:
        """ 
            Modifies a system setting given by setting_key.  
            If modification successful returns True, if not False.  
            If wrong setting parameters are passed, throws a ValueError Exception.
        """
        def _execute_modify_logic(c):
            meta_res = c.execute(text("""SELECT value_type FROM config.system_settings WHERE setting_key = :sk"""), {"sk": setting_key}).fetchone()
            if not meta_res:
                raise ValueError(f"Setting key '{setting_key}' not found.")

            v_type = meta_res[0].upper() # NUMERIC, BOOLEAN, BOTH
            if v_type == 'NUMERIC' and setting_value is None:
                raise ValueError(f"Setting '{setting_key}' is numeric and requires a value.")
            if v_type == 'BOOLEAN' and is_enabled is None:
                raise ValueError(f"Setting '{setting_key}' is boolean and requires enabled/disabled status.")
            if v_type == 'BOTH' and (setting_value is None or is_enabled is None):
                raise ValueError(f"Setting '{setting_key}' requires both a value and a status.")

            c.execute(text("""
                UPDATE config.system_settings 
                SET setting_value = COALESCE(:sv, setting_value), 
                    is_enabled = COALESCE(:en, is_enabled) 
                WHERE setting_key = :sk
            """), {"sv": setting_value, "en": is_enabled, "sk": setting_key})

        if conn is None:
            try:
                with self.engine.begin() as new_conn:
                    _execute_modify_logic(new_conn)
                return True
            except Exception as e:
                self.log_system_error(
                    error_source='DATABASE', 
                    module_name='modify_system_setting', 
                    error_message=str(e),
                    stack_trace=traceback.format_exc(),
                    context_data={"setting_key": setting_key, "setting_value": setting_value, "is_enabled": is_enabled}
                )
                return False
        else:
            _execute_modify_logic(conn)
            return True

    def modify_system_settings(self, changed_settings: list[SystemSettingChange]) -> bool:
        """
            Modifies system settings given by changed_settings
            Returns True on success, or False if the operation failed.
        """
        try:
            with self.engine.begin() as conn:
                for s in changed_settings:
                    self.modify_system_setting(setting_key=s.setting_key, setting_value=s.setting_value, is_enabled=s.is_enabled, conn=conn)
                return True
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='modify_system_settings',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"changed_settings": [vars(s) for s in changed_settings]}
            )
            return False

    def restore_default_system_settings(self) -> bool:
        """
            Restores default settings values defined in settings_defaults.py.  
            Returns True on success, or False if the operation failed.
        """
        return self.modify_system_settings(DEFAULT_SYSTEM_SETTINGS)

    ##################################
    # EXECUTION & ERROR LOGS METHODS #
    ##################################
    def log_system_error(self, error_source: str, module_name: str, error_message: str, 
                        stack_trace: str = None, context_data: dict = None):
        """Saves an error log to orchestration.system_errors"""
        query = text("""
            INSERT INTO orchestration.system_errors 
            (error_source, module_name, error_message, stack_trace, context_data)
            VALUES (:source, :mod, :msg, :trace, :ctx)
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(text("""
                    INSERT INTO orchestration.system_errors 
                    (error_source, module_name, error_message, stack_trace, context_data)
                    VALUES (:source, :mod, :msg, :trace, :ctx)
                """),{
                    "source": error_source, "mod": module_name,
                    "msg": error_message, "trace": stack_trace,
                    "ctx": json.dumps(context_data) if context_data else None
                })
        except Exception as e:
            print(f"CRITICAL ERROR: Could not log to DB: {e}")


# Test if a connection may be established
if __name__ == "__main__":
    try:
        manager = DBManager()
        df = manager.get_active_search_criteria()
        print("Connected with DB.")
        print(f"There are {len(df)} active search criteria:")
        print(df)
    except Exception as e:
        print(f"Connection Error: {e}")
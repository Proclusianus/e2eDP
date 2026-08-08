from dataclasses import dataclass, field
import datetime
import os
import traceback
import json


import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv


import database.models as dbmodels
import database.exceptions as dbexcepts
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

    ##########
    # COMMON #
    ##########
    def _get_active_count(self, table_name: str, only_active: bool) -> int:
        """
            Counts records in a sc/gnr tables.  
            Returns -1 if failed.
        """
        query = text(f"""
            SELECT COUNT(*) 
            FROM config.{table_name} 
            WHERE (is_active = true OR :oa = false)
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"oa": only_active})
                return result.scalar()
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name=f'get_count_{table_name}',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return -1

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

    def get_all_locations(self) -> list[dbmodels.Location]:
        """Returns a list of Locations. Returns an empty list if none exist or on error."""
        query_str = "SELECT id, INITCAP(city_name) as city_name FROM config.locations ORDER BY city_name"
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str))
                if not result:
                    return []
                return [dbmodels.Location(
                    location_id=r._mapping['id'],
                    city_name=r._mapping['city_name']
                ) for r in result]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
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
                error_source=dbmodels.ErrorSources.DATABASE,
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

    def get_anomaly_analysis_definitions(self) -> list[dbmodels.AnomalyAnalysis]:
        """Returns a list of AnomalyAnalysis. Returns an empty list if none exist (There should always be >0) or on error."""
        query_str = "SELECT id, code, name_en, description_en, name_pl, description_pl, takes_parameter FROM config.anomaly_analysis_dictionary"
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str))
                if not result:
                    return []
                return [dbmodels.AnomalyAnalysis(
                        id=r._mapping['id'],
                        code=r._mapping['code'],
                        name_pl=r._mapping['name_pl'],
                        name_en=r._mapping['name_en'],
                        description_pl=r._mapping['description_pl'],
                        description_en=r._mapping['description_en'],
                        takes_parameter=r._mapping['takes_parameter']
                    ) for r in result
                ]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_anomaly_analysis_definitions',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_batch_analysis_definitions(self) -> list[dbmodels.BatchAnalysis]:
        """Returns a list of BatchAnalysis. Returns an empty list if none exist (There should always be >0) or on error."""
        query_str = "SELECT id, code, name_en, description_en, name_pl, description_pl, takes_parameter FROM config.batch_analysis_dictionary"
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str))
                if not result:
                    return []
                return [
                    dbmodels.BatchAnalysis(
                        id=r._mapping['id'],
                        code=r._mapping['code'],
                        name_pl=r._mapping['name_pl'],
                        name_en=r._mapping['name_en'],
                        description_pl=r._mapping['description_pl'],
                        description_en=r._mapping['description_en'],
                        takes_parameter=r._mapping['takes_parameter']
                    ) for r in result
                ]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_batch_analysis_definitions',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_all_property_types(self) -> list[dbmodels.PropertyType]:
        """Returns a list of PropertyType. Returns an empty list if none exist (There should always be >0) or on error."""
        query = text("""SELECT id, type_name FROM config.property_types ORDER BY type_name""")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query)
                if not result:
                    return []
                return [
                    dbmodels.PropertyType(
                        pt_id=r._mapping['id'],
                        type_name=r._mapping['type_name']
                    ) for r in result
                ]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_all_property_types',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_all_room_counts(self) -> list[dbmodels.RoomCount]:
        """Returns a list of RoomCount. Returns an empty list if none exist (There should always be >0) or on error."""
        query = text("""SELECT id, room_label FROM config.room_counts ORDER BY id""")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query)
                if not result:
                    return []
                return [
                    dbmodels.RoomCount(
                        room_id=r._mapping['id'],
                        room_label=r._mapping['room_label']
                    ) for r in result
                ]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_all_room_counts',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    ###########################
    # SEARCH CRITERIA METHODS #
    ###########################
    def get_all_search_criteria(self, get_soft_deleted: bool = False) -> list[dbmodels.SearchCriteria]:
        """
            Returns all search criteria. Will include soft-deleted search criteria if get_soft_deleted == True.
        """
        query = text("""
            SELECT 
                sc.id,
                sc.target_name,
                COALESCE(sc.description, '') as description,
                sc.transaction_type,
                sc.market_type,
                sc.min_price,
                sc.max_price,
                sc.min_area,
                sc.max_area,
                sc.is_active,
                sc.is_soft_deleted,
                sc.created_at,
                COALESCE(jsonb_agg(DISTINCT INITCAP(l.city_name)), '[]'::jsonb) as cities_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', pt.id, 'type_name', pt.type_name)), '[]'::jsonb) as property_types_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', rc.id, 'room_label', rc.room_label)), '[]'::jsonb) as rooms_jsonb,
                COALESCE(jsonb_agg(DISTINCT to_char(sch.execution_time, 'HH24:MI')), '[]'::jsonb) as execution_hours_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', aba.analysis_id, 'param_value', aba.param_value)), '[]'::jsonb) as batch_analyses_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', aaa.analysis_id, 'param_value', aaa.param_value)), '[]'::jsonb) as anomaly_analyses_jsonb
            FROM config.search_criteria sc
            LEFT JOIN config.criteria_locations cl ON sc.id = cl.criteria_id
            LEFT JOIN config.locations l ON cl.location_id = l.id
            LEFT JOIN config.criteria_property_types cpt ON sc.id = cpt.criteria_id
            LEFT JOIN config.property_types pt ON cpt.property_type_id = pt.id
            LEFT JOIN config.criteria_rooms cr ON sc.id = cr.criteria_id
            LEFT JOIN config.room_counts rc ON cr.room_id = rc.id
            LEFT JOIN config.search_criteria_schedule sch ON sc.id = sch.criteria_id
            LEFT JOIN config.activated_batch_analyses aba ON sc.id = aba.criteria_id
            LEFT JOIN config.activated_anomaly_analyses aaa ON sc.id = aaa.criteria_id
            WHERE sc.is_soft_deleted = :get_sd
            GROUP BY sc.id
            ORDER BY sc.created_at DESC;
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"get_sd": get_soft_deleted})
                if not result:
                    return []
                return [dbmodels.SearchCriteria(
                    id=r._mapping['id'],
                    target_name=r._mapping['target_name'],
                    description=r._mapping['description'],
                    transaction_type=r._mapping['transaction_type'],
                    market_type=r._mapping['market_type'],
                    min_price=float(r._mapping['min_price']) if r._mapping['min_price'] else None,
                    max_price=float(r._mapping['max_price']) if r._mapping['max_price'] else None,
                    min_area=float(r._mapping['min_area']) if r._mapping['min_area'] else None,
                    max_area=float(r._mapping['max_area']) if r._mapping['max_area'] else None,
                    is_active=r._mapping['is_active'],
                    is_soft_deleted=r._mapping['is_soft_deleted'],
                    created_at=r._mapping['created_at'],
                    cities=r._mapping['cities_jsonb'],
                    property_types=[dbmodels.PropertyType(pt_id=p['id'], type_name=p['type_name']) for p in r._mapping['property_types_jsonb']],
                    rooms=[dbmodels.RoomCount(room_id=rm['id'], room_label=rm['room_label']) for rm in r._mapping['rooms_jsonb']],
                    execution_hours=[datetime.datetime.strptime(h, "%H:%M").time() for h in r._mapping['execution_hours_jsonb']],
                    batch_analyses=[dbmodels.ActivatedAnalysis(analysis_id=ba['id'], param_value=float(ba['param_value']) if ba['param_value'] else None) for ba in r._mapping['batch_analyses_jsonb']],
                    anomaly_analyses=[dbmodels.ActivatedAnalysis(analysis_id=aa['id'], param_value=float(aa['param_value']) if aa['param_value'] else None) for aa in r._mapping['anomaly_analyses_jsonb']]
                ) for r in result]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_all_search_criteria',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_search_criteria(self, criteria_id: int) -> dbmodels.SearchCriteria | None:
        """
            Retrieves the complete configuration for a specific search criteria, 
            including all nested relational data.  
            If no such search criteria exists, returns None   
        """
        query = text("""
            SELECT 
                sc.id,
                sc.target_name,
                COALESCE(sc.description, '') as description,
                sc.transaction_type,
                sc.market_type,
                sc.min_price,
                sc.max_price,
                sc.min_area,
                sc.max_area,
                sc.is_active,
                sc.is_soft_deleted,
                sc.created_at,
                COALESCE(jsonb_agg(DISTINCT INITCAP(l.city_name)), '[]'::jsonb) as cities_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', pt.id, 'type_name', pt.type_name)), '[]'::jsonb) as property_types_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', rc.id, 'room_label', rc.room_label)), '[]'::jsonb) as rooms_jsonb,
                COALESCE(jsonb_agg(DISTINCT to_char(sch.execution_time, 'HH24:MI')), '[]'::jsonb) as execution_hours_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', aba.analysis_id, 'param_value', aba.param_value)), '[]'::jsonb) as batch_analyses_jsonb,
                COALESCE(jsonb_agg(DISTINCT jsonb_build_object('id', aaa.analysis_id, 'param_value', aaa.param_value)), '[]'::jsonb) as anomaly_analyses_jsonb
            FROM config.search_criteria sc
            LEFT JOIN config.criteria_locations cl ON sc.id = cl.criteria_id
            LEFT JOIN config.locations l ON cl.location_id = l.id
            LEFT JOIN config.criteria_property_types cpt ON sc.id = cpt.criteria_id
            LEFT JOIN config.property_types pt ON cpt.property_type_id = pt.id
            LEFT JOIN config.criteria_rooms cr ON sc.id = cr.criteria_id
            LEFT JOIN config.room_counts rc ON cr.room_id = rc.id
            LEFT JOIN config.search_criteria_schedule sch ON sc.id = sch.criteria_id
            LEFT JOIN config.activated_batch_analyses aba ON sc.id = aba.criteria_id
            LEFT JOIN config.activated_anomaly_analyses aaa ON sc.id = aaa.criteria_id
            WHERE sc.id = :id
            GROUP BY sc.id;
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"id": criteria_id}).fetchone()
                if not result:
                    return None
                r = result._mapping
                return dbmodels.SearchCriteria(
                    id=r['id'],
                    target_name=r['target_name'],
                    description=r['description'],
                    transaction_type=r['transaction_type'],
                    market_type=r['market_type'],
                    min_price=float(r['min_price']) if r['min_price'] else None,
                    max_price=float(r['max_price']) if r['max_price'] else None,
                    min_area=float(r['min_area']) if r['min_area'] else None,
                    max_area=float(r['max_area']) if r['max_area'] else None,
                    is_active=r['is_active'],
                    is_soft_deleted=r['is_soft_deleted'],
                    created_at=r['created_at'],
                    cities=r['cities_jsonb'],
                    property_types=[dbmodels.PropertyType(pt_id=p['id'], type_name=p['type_name']) for p in r['property_types_jsonb']],
                    rooms=[dbmodels.RoomCount(room_id=rm['id'], room_label=rm['room_label']) for rm in r['rooms_jsonb']],
                    execution_hours=[datetime.datetime.strptime(h, "%H:%M").time() for h in r['execution_hours_jsonb']],
                    batch_analyses=[dbmodels.ActivatedAnalysis(analysis_id=ba['id'], param_value=float(ba['param_value']) if ba['param_value'] else None) for ba in r['batch_analyses_jsonb']],
                    anomaly_analyses=[dbmodels.ActivatedAnalysis(analysis_id=aa['id'], param_value=float(aa['param_value']) if aa['param_value'] else None) for aa in r['anomaly_analyses_jsonb']]
                )
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_search_criteria',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return None

    def save_new_search_criteria(self, sc: dbmodels.SearchCriteria, conn=None) -> int | None:
        """
            Returns the the ID (int) of the created search criteria. If failed to save returns None.    
        """
        def _execute_save_logic(c):
            res = c.execute(text("""
                INSERT INTO config.search_criteria
                (target_name, description, transaction_type, market_type, min_price, max_price, min_area, max_area)
                VALUES
                (:name, :desc, :tt, :mt, :pmin, :pmax, :amin, :amax)
                RETURNING id
            """), {
                "name": sc.target_name, "desc": sc.description, 
                "tt": sc.transaction_type, "mt": sc.market_type,
                "pmin": sc.min_price, "pmax": sc.max_price, 
                "amin": sc.min_area, "amax": sc.max_area 
            })
            new_id = res.fetchone()[0]
            for city in sc.cities:
                loc_id = self._get_or_create_location_id(c, city)
                c.execute(text("INSERT INTO config.criteria_locations (criteria_id, location_id) VALUES (:cid, :lid)"), 
                            {"cid": new_id, "lid": loc_id})
            for pt in sc.property_types:
                c.execute(text("INSERT INTO config.criteria_property_types (criteria_id, property_type_id) VALUES (:cid, :ptid)"), 
                            {"cid": new_id, "ptid": pt.pt_id})
            for rc in sc.rooms:
                c.execute(text("INSERT INTO config.criteria_rooms (criteria_id, room_id) VALUES (:cid, :rid)"), 
                            {"cid": new_id, "rid": rc.room_id})
            for hour in sc.execution_hours:
                c.execute(text("INSERT INTO config.search_criteria_schedule (criteria_id, execution_time) VALUES (:cid, :t)"), 
                            {"cid": new_id, "t": hour})
            for an in sc.batch_analyses:
                c.execute(text("INSERT INTO config.activated_batch_analyses (criteria_id, analysis_id, param_value) VALUES (:cid, :aid, :pv)"), 
                            {"cid": new_id, "aid": an.analysis_id, "pv": an.param_value})
            for an in sc.anomaly_analyses:
                c.execute(text("INSERT INTO config.activated_anomaly_analyses (criteria_id, analysis_id, param_value) VALUES (:cid, :aid, :pv)"), 
                            {"cid": new_id, "aid": an.analysis_id, "pv": an.param_value})
            return new_id

        if conn is None:
            try:
                with self.engine.begin() as new_conn:
                    return _execute_save_logic(new_conn)
            except Exception as e:
                self.log_system_error(
                    error_source=dbmodels.ErrorSources.DATABASE,
                    module_name='save_new_search_criteria',
                    error_message=str(e),
                    stack_trace=traceback.format_exc()
                )
                return None
        else:
            return _execute_save_logic(conn)

    def soft_delete_criteria(self, criteria_id: int, conn=None) -> bool:
        """
            Marks search criteria as soft_deleted and deletes its schedule records (config.search_criteria_schedule)  
            Returns True if successfuly soft deleted the criterion.
        """
        query_update = text("""UPDATE config.search_criteria SET is_active = false, is_soft_deleted = true WHERE id = :id""")
        query_del_schedule = text("""DELETE FROM config.search_criteria_schedule WHERE criteria_id = :id""")
        def _execute_delete_logic(c):
            c.execute(query_update, {"id": criteria_id})
            c.execute(query_del_schedule, {"id": criteria_id})
            return True

        if conn is None:
            try:
                with self.engine.begin() as new_conn:
                    return _execute_delete_logic(new_conn)
            except Exception as e:
                self.log_system_error(
                    error_source=dbmodels.ErrorSources.DATABASE,
                    module_name='soft_delete_criteria',
                    error_message=str(e),
                    stack_trace=traceback.format_exc()
                )
                return False
        else:
            return _execute_delete_logic(conn)

    def replace_search_criteria(self, old_id: int, new_sc: dbmodels.SearchCriteria) -> int | None:
        """
            Archives old criteria and creates a new one in one transaction.  
            Returns the created criteria's id on success or None on failure.
        """
        try:
            with self.engine.begin() as conn:
                self.soft_delete_criteria(old_id, conn=conn)
                return self.save_new_search_criteria(new_sc, conn=conn)
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='replace_search_criteria',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"old_id": old_id}
            )
            return None

    def set_criteria_activation_status(self, criteria_id: int, is_active: bool) -> bool:
        """Returns True if status changed successfuly"""
        query = text("UPDATE config.search_criteria SET is_active = :status WHERE id = :id")
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"status": is_active, "id": criteria_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_criteria_activation_status',
                stack_trace=traceback.format_exc(),
                error_message=str(e)
            )
            return False

    def update_search_criteria_nonessential_data(self, criteria_id, data: dbmodels.SearchCriteriaNonEssentialData) -> bool:
        """
            Deletes & Re-inserts non-essential data for a search criteria (If a parameter is supposed to stay the same, its old value must be passed to 'data').  
            Returns True if succeeded, False if failed.
        """
        try:
            with self.engine.begin() as conn:
                # Update name & desc in search_criteria
                conn.execute(text("""
                    UPDATE config.search_criteria 
                    SET target_name = :name, description = :desc 
                    WHERE id = :id
                """), {"name": data.name, "desc": data.description, "id": criteria_id})

                # Delete & Re-insert the schedule
                conn.execute(text("DELETE FROM config.search_criteria_schedule WHERE criteria_id = :id"), {"id": criteria_id})
                for hour in data.execution_hours:
                    conn.execute(text("INSERT INTO config.search_criteria_schedule (criteria_id, execution_time) VALUES (:id, :t)"), 
                                {"id": criteria_id, "t": hour})

                # Delete & Re-insert batch analyses
                conn.execute(text("DELETE FROM config.activated_batch_analyses WHERE criteria_id = :id"), {"id": criteria_id})
                for ba in data.batch_analyses:
                    conn.execute(text("""
                        INSERT INTO config.activated_batch_analyses (criteria_id, analysis_id, param_value) 
                        VALUES (:id, :aid, :pv)
                    """), {"id": criteria_id, "aid": ba.analysis_id, "pv": ba.param_value})

                # Delete & Re-insert anomaly analyses
                conn.execute(text("DELETE FROM config.activated_anomaly_analyses WHERE criteria_id = :id"), {"id": criteria_id})
                for aa in data.anomaly_analyses:
                    conn.execute(text("""
                        INSERT INTO config.activated_anomaly_analyses (criteria_id, analysis_id, param_value) 
                        VALUES (:id, :aid, :pv)
                    """), {"id": criteria_id, "aid": aa.analysis_id, "pv": aa.param_value})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='update_search_criteria_nonessential_data',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"criteria_id": criteria_id}
            )
            return False

    def get_all_sc_names(self, select_inactive: bool) -> list[str]:
        """
            select_inactive - if true include inactive search targets in the resulting list.  
            Raises a exceptions.DatabaseError exception when the operation fails.  
            Returns an empty list if no names have been obtained.
        """
        query = text("""
            SELECT DISTINCT
                target_name || CASE 
                    WHEN is_soft_deleted THEN ' [ARCHIVED]' 
                    WHEN NOT is_active THEN ' [PAUSED]' 
                    ELSE '' 
                END as display_name
            FROM config.search_criteria 
            WHERE (is_active = true OR :inc_inact = true)
            ORDER BY display_name ASC
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"inc_inact": select_inactive})
                return [row[0] for row in result]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_all_sc_names',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            raise dbexcepts.DatabaseError(f"Failed to fetch SC names from database: {str(e)}") from e

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

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query_str), {"name": name.strip()})
                return result.fetchone() is not None
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='does_this_search_criteria_name_exist',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return False

    def get_search_criteria_count(self, only_active: bool = True) -> int:
        """
            Counts records in the SC table.  
            Returns -1 if failed.
        """
        return self._get_active_count("search_criteria", only_active)

    ########################
    # GLOBAL NOTIFICATIONS #
    ########################
    def get_current_global_notifs(self) -> list[dbmodels.GlobalNotificationRule]:
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
                        dbmodels.ActivatedAnalysis(analysis_id=a['id'], param_value=float(a['val']) if a['val'] is not None else None)
                        for a in r['analyses_json']
                    ]
                    # Map execution_hours to datetime.time
                    hours_objs = [
                        datetime.datetime.strptime(h, "%H:%M").time()
                        for h in r['hours_json']
                    ]
                    # Create data struct
                    rules.append(dbmodels.GlobalNotificationRule(
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
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_current_global_notifs',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def get_global_notification_rule(self, gnr_id: int) -> dbmodels.GlobalNotificationRule | None:
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
                    dbmodels.ActivatedAnalysis(analysis_id=a['id'], param_value=float(a['val']) if a['val'] is not None else None)
                    for a in r['analyses_json']
                ]
                hours_objs = [
                    datetime.datetime.strptime(h, "%H:%M").time()
                    for h in r['hours_json']
                ]
                return dbmodels.GlobalNotificationRule(
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
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_global_notification_rule',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"gnr_id": gnr_id}
            )
            return None

    def save_new_global_notification_rule(self, gnr: dbmodels.GlobalNotificationRule, conn=None) -> int | None:
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
                    error_source=dbmodels.ErrorSources.DATABASE,
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
                    error_source=dbmodels.ErrorSources.DATABASE,
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

    def replace_global_rule(self, old_id: int, new_gnr: dbmodels.GlobalNotificationRule) -> int | None:
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
                error_source=dbmodels.ErrorSources.DATABASE,
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
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_global_notification_activation_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"gnr_id": gnr_id}
            )
            return False

    def update_global_notification_nonessential_data(self, gnr_id: int, name: str, desc: str | None, hours: list[datetime.time], 
                                                     analyses: list[dbmodels.ActivatedAnalysis]) -> bool:
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
                error_source=dbmodels.ErrorSources.DATABASE,
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
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='does_global_notification_rule_name_exist',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"gnr_name": name, "ignore_sd": ignore_soft_deleted}
            )
            return None

    def get_all_gnr_names(self, select_inactive: bool) -> list[str]:
        """
            select_inactive - if true include inactive search targets in the resulting list.  
            Returns an empty list if failed or if there are no such names.
        """
        query = text("""
            SELECT DISTINCT
                rule_name || CASE 
                    WHEN is_soft_deleted THEN ' [ARCHIVED]' 
                    WHEN NOT is_active THEN ' [PAUSED]' 
                    ELSE '' 
                END as display_name
            FROM config.global_notification_rules 
            WHERE (is_active = true OR :inc_inact = true)
            ORDER BY display_name ASC
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"inc_inact": select_inactive})
                return [row[0] for row in result]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_all_gnr_names',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            raise dbexcepts.DatabaseError(f"Failed to fetch GNR names from database: {str(e)}") from e

    def get_global_notification_rules_count(self, only_active: bool = True) -> int:
        """
            Counts records in the GNR table.  
            Returns -1 if failed.
        """
        return self._get_active_count("global_notification_rules", only_active)

    ###########################
    # SYSTEM SETTINGS METHODS #
    ###########################
    def get_all_system_settings(self) -> list[dbmodels.SystemSetting]:
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
                    sys_settings.append(dbmodels.SystemSetting(
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
                error_source=dbmodels.ErrorSources.DATABASE, 
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
                    error_source=dbmodels.ErrorSources.DATABASE, 
                    module_name='modify_system_setting', 
                    error_message=str(e),
                    stack_trace=traceback.format_exc(),
                    context_data={"setting_key": setting_key, "setting_value": setting_value, "is_enabled": is_enabled}
                )
                return False
        else:
            _execute_modify_logic(conn)
            return True

    def modify_system_settings(self, changed_settings: list[dbmodels.SystemSettingChange]) -> bool:
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
                error_source=dbmodels.ErrorSources.DATABASE,
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
    def log_system_error(self, error_source: dbmodels.ErrorSources, module_name: str, error_message: str, 
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
                    "source": error_source.value, "mod": module_name,
                    "msg": error_message, "trace": stack_trace,
                    "ctx": json.dumps(context_data) if context_data else None
                })
        except Exception as e:
            print(f"CRITICAL ERROR: Could not log to DB: {e}")

    def get_system_errors(self, is_solved: bool, limit_records: int, pg_number: int) -> tuple[int, list[dbmodels.AppSystemError]]:
        """
            Returns a tuple of matching record count and a list of system errors (models.SystemError).  
            If operation fails returns (-1, []).
        """
        query = text("""
            SELECT 
                id, 
                error_source, 
                COALESCE(module_name, '') as module_name, 
                error_message, 
                COALESCE(stack_trace, '') as stack_trace, 
                context_data as context_data, 
                occurred_at, 
                is_resolved,
                COUNT(*) OVER() as total_records_count
            FROM orchestration.system_errors
            WHERE is_resolved = :is
            ORDER BY occurred_at DESC
            LIMIT :limit_n OFFSET :offset_n
        """)
        offset_n = (pg_number - 1) * limit_records
        try:
            with self.engine.begin() as conn:
                result = conn.execute(query, {"is": is_solved, "limit_n": limit_records, "offset_n": offset_n}).all()
                if not result:
                    return (0, [])
                total_count = result[0]._mapping["total_records_count"]
                sys_errors: list[dbmodels.AppSystemError] = [
                    dbmodels.AppSystemError(
                        id=r._mapping["id"],
                        error_source=r._mapping["error_source"],
                        module_name=r._mapping["module_name"],
                        error_message=r._mapping["error_message"],
                        stack_trace=r._mapping["stack_trace"],
                        context_data=r._mapping["context_data"],
                        occurred_at=r._mapping["occurred_at"],
                        is_resolved=r._mapping["is_resolved"]
                    ) for r in result
                ]
                return (total_count, sys_errors)
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_system_errors',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return (-1, [])

    def set_system_error_resolution_status(self, syserr_id: int, syserr_new_status: bool) -> bool:
        """
            Sets is_resolved to syserr_new_status for system error given by syserr_id.  
            Returns True on success, False on failure.
        """
        query = text("""
            UPDATE orchestration.system_errors 
            SET is_resolved = :ns 
            WHERE id = :seid
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"ns": syserr_new_status, "seid": syserr_id})
                return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_system_error_resolution_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"syserr_id": syserr_id, "syserr_new_status": syserr_new_status}
            )
            return False

    def _build_log_query(self, schema: str, log_status: dbmodels.LogStatus, 
                         target_names: list[str], unit: dbmodels.TimeUnit, 
                         amount: int, select_inactive: bool) -> str:
        ### GETTING ALL TABLE DATA ###
        # Common columns in all execution log tables
        base_cols = "l.id, '{layer}', l.job_name, l.status, l.error_message, l.started_at, l.finished_at"
        sc_display_name = """
            sc.target_name || CASE 
                WHEN sc.is_soft_deleted THEN ' [ARCHIVED]' 
                WHEN NOT sc.is_active THEN ' [PAUSED]' 
                ELSE '' 
            END
        """
        gnr_display_name = """
            gnr.rule_name || CASE 
                WHEN gnr.is_soft_deleted THEN ' [ARCHIVED]' 
                WHEN NOT gnr.is_active THEN ' [PAUSED]' 
                ELSE '' 
            END
        """
        
        if schema == 'raw':
            cols = f"{base_cols.format(layer='RAW')}, l.batch_id, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, {sc_display_name}"
            joins = """
                JOIN orchestration.batches b ON l.batch_id = b.id
                JOIN config.search_criteria sc ON b.criteria_id = sc.id
            """
        elif schema == 'clean':
            # SC NAME PATH: Clean Log -> Raw Listing -> Batch -> Criteria
            cols = f"{base_cols.format(layer='CLEAN')}, rl.batch_id, l.raw_listing_id, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, NULL::INTEGER, {sc_display_name}"
            joins = """
                JOIN raw.listings rl ON l.raw_listing_id = rl.id
                JOIN orchestration.batches b ON rl.batch_id = b.id
                JOIN config.search_criteria sc ON b.criteria_id = sc.id
            """
        elif schema == 'analytics':
            # SC NAME PATH: Analytics Log -> Batch -> Criteria
            # GNR NAME PATH: Analytics Log -> GNR
            cols = f"""{base_cols.format(layer='ANALYTICS')}, l.batch_id, NULL::INTEGER, l.clean_listing_id, 
                    l.batch_analysis_id, l.anomaly_analysis_id, l.global_rule_id,
                    COALESCE({sc_display_name}, {gnr_display_name})"""
            joins = """
                LEFT JOIN orchestration.batches b ON l.batch_id = b.id
                LEFT JOIN config.search_criteria sc ON b.criteria_id = sc.id
                LEFT JOIN config.global_notification_rules gnr ON l.global_rule_id = gnr.id
            """

        query = f"SELECT {cols} FROM {schema}.execution_logs l {joins} WHERE 1=1"

        ### FILTERS ###
        if log_status != dbmodels.LogStatus.ANY:
            query += f" AND l.status = '{log_status.value}'"
        if not select_inactive:
            if schema == 'analytics':
                query += " AND (sc.is_active = true OR gnr.is_active = true)"
            else:
                query += " AND sc.is_active = true"
        if target_names:
            names = [f"'{t}'" for t in target_names]
            target_col = "sc.target_name" if schema != 'analytics' else "COALESCE(sc.target_name, gnr.rule_name)"
            query += f" AND {target_col} IN ({', '.join(names)})"
        if unit != dbmodels.TimeUnit.ALL_TIME:
            pg_unit = unit.value.lower() # 'minute', 'hour', 'day'
            query += f" AND l.started_at >= NOW() - INTERVAL '{amount} {pg_unit}'"

        return query

    def _map_row_to_exec_log(self, row) -> dbmodels.RawExecLog | dbmodels.CleanExecLog | dbmodels.AnalyticsExecLog:
        """Builds DTO objects out of raw DB data."""
        r = row._mapping
        layer = r['layer']
        common = {
            "id": r['id'],
            "target_display_name": r['target_display_name'],
            "job_name": r['job_name'],
            "status": r['status'],
            "error_message": r['error_message'],
            "started_at": r['started_at'],
            "finished_at": r['finished_at']
        }
        if layer == 'RAW':
            return dbmodels.RawExecLog(**common, batch_id=r['batch_id'])
        elif layer == 'CLEAN':
            return dbmodels.CleanExecLog(**common, raw_listing_id=r['raw_listing_id'])
        elif layer == 'ANALYTICS':
            return dbmodels.AnalyticsExecLog(
                **common,
                batch_id=r['batch_id'],
                clean_listing_id=r['clean_listing_id'],
                batch_analysis_id=r['batch_analysis_id'],
                anomaly_analysis_id=r['anomaly_analysis_id'],
                global_rule_id=r['global_rule_id']
            )

    def get_all_execution_logs(self, log_status: dbmodels.LogStatus, target_names: list[str], limit_records: int, pg_number: int,
                               unit_of_time: dbmodels.TimeUnit, time_amount: int, sort_by: str, select_inactive: bool, 
                               get_raw: bool = True, get_clean: bool = True, get_analytics: bool = True
                               ) -> tuple[int, list[dbmodels.RawExecLog | dbmodels.CleanExecLog | dbmodels.AnalyticsExecLog]]:
        """
            Parameters  
            ----------
            **log_status** models.LogStatus  
            Which status should be searched for. Statuses are defined in models.LogStatus, however if given 'Any', all statuses will be accepted.  
            **target_names** list[str]  
            List of search target (search criteria & global notification rules) names which will be searched for. If [], all names will be accpeted.  
            **limit_records** int  
            Amount records to select.  
            **pg_number**  
            Which page should be selected.  
            **units_of_time** models.TimeUnit  
            Selected unit of time defined in models.TimeUnit; If set to ALL_TIME, all created_at will be accepted and time_amount is ignored.  
            **time_amount** int  
            Amount of time units.  
            **sort_by** str  
            How to sort the resulting list - available options "newest", "oldest", "execution_time".    
            **select_inactive** bool  
            If true include inactive search targets in the resulting list.  
            **get_raw, get_clean, get_analytics**  
            If set to True (default value), the returned list will contain results of raw/clean/analytics type

            Returns
            -------
            A list of analyses (models.RawExecLog | models.CleanExecLog | models.AnalyticsExecLog), with a number of total records found on success,  
            (-1, []) on failure.
        """
        parts = []
        if get_raw:
            parts.append(self._build_log_query('raw', log_status, target_names, unit_of_time, time_amount, select_inactive))
        if get_clean:
            parts.append(self._build_log_query('clean', log_status, target_names, unit_of_time, time_amount, select_inactive))
        if get_analytics:
            parts.append(self._build_log_query('analytics', log_status, target_names, unit_of_time, time_amount, select_inactive))
        if not parts:
            return (0, [])
        union_query = " UNION ALL ".join(parts)
        sort_logic = {
            "newest": "started_at DESC",
            "oldest": "started_at ASC",
            "execution_time": "(finished_at - started_at) DESC"
        }.get(sort_by, "started_at DESC")
        offset_n = (pg_number - 1) * limit_records
        final_query = text(f"""
            SELECT *, COUNT(*) OVER() as total_records_count
            FROM ({union_query}) as combined_logs
            ORDER BY {sort_logic}
            LIMIT :limit_n OFFSET :offset_n
        """)

        try:
            with self.engine.connect() as conn:
                result = conn.execute(final_query, {'limit_n': limit_records, "offset_n": offset_n}).all()
                if not result:
                    return (0, [])

                total_count = result[0]._mapping['total_records_count']
                logs = [self._map_row_to_exec_log(row) for row in result]
                return (total_count, logs)
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_all_execution_logs',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return (-1, [])


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
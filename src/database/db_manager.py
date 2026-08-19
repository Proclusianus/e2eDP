from dataclasses import dataclass, field
import datetime
import os
import traceback
import json
from collections import defaultdict


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

    def get_location_by_name(self, location_name: str) -> dbmodels.Location | None:
        """Returns a Location for the given location_name. If none found or error returns None."""
        query = text("SELECT id, INITCAP(city_name) as city_name FROM config.locations WHERE city_name = :c")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"c": location_name.strip().upper()}).fetchone()
                if not result:
                    return None
                r = result._mapping
                return dbmodels.Location(
                    location_id=r['id'],
                    city_name=r['city_name']
                )
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_location_by_name',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"location_name": location_name}
            )
            return None

    def get_location_lookup(self) -> dict[int, str] | None:
        """Returns (location_id: location name) mapping, or None if failed."""
        query = text("SELECT id, INITCAP(city_name) as city_name FROM config.locations")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query)
                return {row.id: row.city_name for row in result}
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_location_lookup',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return None

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

    def get_property_type_id_by_name(self, type_name: str) -> int | None:
        """Returns the property type id for the given name"""
        query = text("""SELECT id FROM config.property_types WHERE type_name = :tn""")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"tn": type_name}).fetchone()
                return result._mapping['id'] if result else None 
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_property_type_id_by_name',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"type_name": type_name}
            )
            return None

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

    def create_location_mapping(self, location_id: int, portal_name: str, external_name: str) -> bool:
        """Creates a location mapping. Returns True on success, False on fail."""
        query = text("""
            INSERT INTO config.location_mappings (location_id, portal_name, external_name)
            VALUES (:lid, :pname, :ename)
            ON CONFLICT (external_name, portal_name) DO NOTHING
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"lid": location_id, "pname": portal_name, "ename": external_name})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE, 
                module_name="create_location_mapping", 
                error_message=str(e), 
                stack_trace=traceback.format_exc(),
                context_data={"location_id": location_id, "portal_name": portal_name, "external_name": external_name}
            )
            return False

    def get_location_mapping_location(self, portal_name: str, external_name: str) -> dbmodels.Location | None:
        """Returns a Location object for the given portal and external name. Returns None if failed to obtain."""
        query = text("""
            SELECT l.id, l.city_name 
            FROM config.locations l
            JOIN config.location_mappings lm ON l.id = lm.location_id
            WHERE lm.portal_name = :pname AND lm.external_name = :ename
        """)
        try:
            with self.engine.connect() as conn:
                res = conn.execute(query, {"pname": portal_name, "ename": external_name}).fetchone()
                if res:
                    return dbmodels.Location(location_id=res._mapping['id'], city_name=res._mapping['city_name'])
                return None
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE, 
                module_name="get_location_mapping_location", 
                error_message=str(e), 
                stack_trace=traceback.format_exc(),
                context_data={"portal_name": portal_name, "external_name": external_name}
            )
            return None

    def get_location_mapping_external_name(self, portal_name: str, location_id: int) -> str | None:
        """Returns an external name for the given location id and portal name. Returns None if failed to obtain."""
        query = text("""
            SELECT external_name FROM config.location_mappings 
            WHERE portal_name = :pname AND location_id = :lid
        """)
        try:
            with self.engine.connect() as conn:
                res = conn.execute(query, {"pname": portal_name, "lid": location_id}).fetchone()
                return res[0] if res else None
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE, 
                module_name="get_location_mapping_external_name", 
                error_message=str(e), 
                stack_trace=traceback.format_exc(),
                context_data={"portal_name": portal_name, "location_id": location_id}
            )
            return None

    def remove_location_mapping(self, location_id: int, portal_name: str, external_name: str) -> bool:
        """Removes a location mapping. Returns True on success, False on fail."""
        query = text("""
            DELETE FROM config.location_mappings 
            WHERE location_id = :lid AND portal_name = :pname AND external_name = :ename
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"lid": location_id, "pname": portal_name, "ename": external_name})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE, 
                module_name="remove_location_mapping", 
                error_message=str(e), 
                stack_trace=traceback.format_exc(),
                context_data={"location_id": location_id, "portal_name": portal_name, "external_name": external_name}
            )
            return False

    def is_location_mapped(self, location_id: int, portal_name: str, external_name: str) -> bool:
        """Returns True if location is mapped, False if not (or if can't connect to DB)."""
        query = text("""
            SELECT EXISTS(
                SELECT 1 FROM config.location_mappings 
                WHERE location_id = :lid AND portal_name = :pname AND external_name = :ename
            )
        """)
        try:
            with self.engine.connect() as conn:
                return conn.execute(query, {"lid": location_id, "pname": portal_name, "ename": external_name}).scalar()
        except Exception:
            return False

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
                    min_price=float(r._mapping['min_price']) if r._mapping['min_price'] is not None else None,
                    max_price=float(r._mapping['max_price']) if r._mapping['max_price'] is not None else None,
                    min_area=float(r._mapping['min_area']) if r._mapping['min_area'] is not None else None,
                    max_area=float(r._mapping['max_area']) if r._mapping['max_area'] is not None else None,
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
                    min_price=float(r['min_price']) if r['min_price'] is not None else None,
                    max_price=float(r['max_price']) if r['max_price'] is not None else None,
                    min_area=float(r['min_area']) if r['min_area'] is not None else None,
                    max_area=float(r['max_area']) if r['max_area'] is not None else None,
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

    def get_system_setting_values(self, sys_setting_key: str) -> dbmodels.SystemSettingValues | None:
        """
            Returns the values for a given system setting.  
            Returns None if failed to obtain these values.
        """
        query = text("""SELECT setting_value, is_enabled FROM config.system_settings WHERE setting_key = :sk""")
        try:
            with self.engine.connect() as conn:
                row = conn.execute(query, {"sk": sys_setting_key}).fetchone()
                if row:
                    return dbmodels.SystemSettingValues(
                        setting_value=row._mapping['setting_value'],
                        is_enabled=row._mapping['is_enabled']
                    )
                return None
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE, 
                module_name='get_system_setting_values', 
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"sys_setting_key": sys_setting_key}
            )
            return None

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

    def begin_raw_execution_log(self, job_name: str, batch_id: int, started_at: datetime.datetime) -> int | None:
        """
            Creates a new raw execution log.  
            Returns id of the created raw exec log, None if failed to do so
        """
        query = text("""
            INSERT INTO raw.execution_logs (job_name, batch_id, status, started_at)
            VALUES (:jn, :bid, :s, :sa)
            RETURNING id
        """)
        try:
            with self.engine.begin() as conn:
                return conn.execute(query, {"jn": job_name, "bid": batch_id, "s": dbmodels.LogStatus.RUNNING, "sa": started_at}).fetchone()[0]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='begin_raw_execution_log',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"batch_id": batch_id, "started_at": started_at}
            )
            return None

    def set_raw_execution_log_status(self, raw_exec_log_id: int, status: dbmodels.LogStatus, 
                                     finished_at: datetime.datetime, err_msg: str = None) -> bool:
        """
            Sets the status for the raw execlog given by raw_exec_log_id.  
            Returns True on success, False on failure.
        """
        query = text("""
            UPDATE raw.execution_logs
            SET status = :st, finished_at = :n, error_message = :err
            WHERE id = :lid
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"st": status, "n": finished_at, "err": err_msg, "lid": raw_exec_log_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_raw_execution_log_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"raw_exec_log_id": raw_exec_log_id, "finished_at": finished_at}
            )
            return False

    def insert_raw_execution_logs_bulk(self, logs: list[dbmodels.RawExecLog]) -> bool:
        """
            Used to insert raw execlogs coming from each listing in bulk to save DB resources.  
            Returns True on success, False on failure.
        """
        if not logs: return True

        query = text("""
            INSERT INTO raw.execution_logs 
            (job_name, batch_id, status, error_message, started_at, finished_at)
            VALUES 
            (:job_name, :batch_id, :status, :error_message, :started_at, :finished_at)
        """)
        data = [{
            "job_name": log.job_name,
            "batch_id": log.batch_id,
            "status": log.status,
            "error_message": log.error_message,
            "started_at": log.started_at,
            "finished_at": log.finished_at,
        } for log in logs]

        try:
            with self.engine.begin() as conn:
                conn.execute(query, data)
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='insert_raw_execution_logs_bulk',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"log_count": len(logs)}
            )
            return False

    def begin_clean_execution_log(self, job_name: str, raw_listing_id: int, started_at: datetime.datetime) -> int | None:
        """
            Creates a new clean execution log.  
            Returns id of the created clean exec log, None if failed to do so
        """
        query = text("""
            INSERT INTO clean.execution_logs (job_name, raw_listing_id, status, started_at)
            VALUES (:jn, :rlid, :s, :sa)
            RETURNING id
        """)
        try:
            with self.engine.begin() as conn:
                return conn.execute(query, {"jn": job_name, "rlid": raw_listing_id, "s": dbmodels.LogStatus.RUNNING, "sa": started_at}).fetchone()[0]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='begin_clean_execution_log',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"raw_listing_id": raw_listing_id, "started_at": started_at}
            )
            return None
    
    def set_clean_execution_log_status(self, clean_exec_log_id: int, status: dbmodels.LogStatus, 
                                        finished_at: datetime.datetime, err_msg: str = None) -> bool:
        """
            Sets the status for the clean execlog given by clean_exec_log_id.  
            Returns True on success, False on failure.
        """
        query = text("""
            UPDATE clean.execution_logs
            SET status = :st, finished_at = :n, error_message = :err
            WHERE id = :lid
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"st": status, "n": finished_at, "err": err_msg, "lid": clean_exec_log_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_clean_execution_log_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"clean_exec_log_id": clean_exec_log_id, "finished_at": finished_at}
            )
            return False

    def insert_clean_execution_logs_bulk(self, logs: list[dbmodels.CleanExecLog]) -> bool:
        """
            Used to insert clean execlogs coming from each listing in bulk to save DB resources.  
            Returns True on success, False on failure.
        """
        if not logs: return True

        query = text("""
            INSERT INTO clean.execution_logs 
            (job_name, raw_listing_id, status, error_message, started_at, finished_at)
            VALUES 
            (:job_name, :raw_listing_id, :status, :error_message, :started_at, :finished_at)
        """)
        data = [{
            "job_name": log.job_name,
            "raw_listing_id": log.raw_listing_id,
            "status": log.status,
            "error_message": log.error_message,
            "started_at": log.started_at,
            "finished_at": log.finished_at,
        } for log in logs]

        try:
            with self.engine.begin() as conn:
                conn.execute(query, data)
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='insert_clean_execution_logs_bulk',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"log_count": len(logs)}
            )
            return False

    def insert_analytics_execution_logs_bulk(self, logs: list[dbmodels.AnalyticsExecLog]) -> bool:
        """
            Used to insert analytics execlogs coming from each listing in bulk to save DB resources.  
            Returns True on success, False on failure.
        """
        if not logs: return True
        query = text("""
            INSERT INTO analytics.execution_logs 
            (job_name, batch_id, clean_listing_id, batch_analysis_id, anomaly_analysis_id, 
             global_rule_id, status, error_message, started_at, finished_at)
            VALUES 
            (:jn, :bid, :clid, :baid, :aaid, :grid, :st, :err, :sa, :fa)
        """)
        data = [{
            "jn": log.job_name,
            "bid": log.batch_id,
            "clid": log.clean_listing_id,
            "baid": log.batch_analysis_id,
            "aaid": log.anomaly_analysis_id,
            "grid": log.global_rule_id,
            "st": log.status,
            "err": log.error_message,
            "sa": log.started_at,
            "fa": log.finished_at
        } for log in logs]
        
        try:
            with self.engine.begin() as conn:
                conn.execute(query, data)
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='insert_analytics_execution_logs_bulk',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"log_count": len(logs)}
            )
            return False

    #################################
    # ORCHESTRATION.BATCHES METHODS #
    #################################
    def start_batch(self, criteria_id: int) -> int:
        """
            Creates a new batch record with 'RUNNING' status.  
            Returns the id of the created record on success, -1 on failure.
        """
        query = text("""
            INSERT INTO orchestration.batches (criteria_id, status, started_at)
            VALUES (:cid, :st, :n)
            RETURNING id
        """)
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            with self.engine.begin() as conn:
                res = conn.execute(query, {"cid": criteria_id, "st": dbmodels.BatchStatus.RUNNING, "n": now})
                return res.fetchone()[0]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='start_batch',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"criteria_id": criteria_id, "datetime": now.isoformat()}
            )
            return -1

    def get_batch(self, batch_id: int) -> dbmodels.BatchData | None:
        """Returns a batch with the given id. Returns None if not found or on failure."""
        query = text("""
            SELECT id, criteria_id, status, started_at, finished_at
            FROM orchestration.batches
            WHERE id = :bid
        """)
        try:
            with self.engine.begin() as conn:
                res = conn.execute(query, {"bid": batch_id}).fetchone()
                if not res:
                    return None
                r = res._mapping
                return dbmodels.BatchData(
                    id=r['id'],
                    criteria_id=r['criteria_id'],
                    status=dbmodels.BatchStatus(r['status']),
                    started_at=r['started_at'],
                    finished_at=r['finished_at']
                )
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_batch',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"batch_id": batch_id}
            )
            return None

    def set_batch_status(self, batch_id: int, status: dbmodels.BatchStatus) -> bool:
        """
            Finishes a batch with the given status.  
            Returns True on success, False on failure.
        """
        query = text("""
            UPDATE orchestration.batches 
            SET status = :st, finished_at = :n 
            WHERE id = :bid
        """)
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"st": status, "bid": batch_id, "n": now})
                return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_batch_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"batch_id": batch_id, "datetime": now.isoformat()}
            )
            return False

    ############
    # LISTINGS #
    ############
    ### RAW ###
    def insert_raw_listing(self, raw_listing: dbmodels.RawListing) -> int:
        """
            Inserts a RawListing into the DB.  
            Returns the id of the inserted raw listing on success and -1 on failure.
        """
        query = text("""
            INSERT INTO raw.listings
            (criteria_id, batch_id, portal_name, external_id, scraping_url, location_url, raw_content, http_status)
            VALUES (:cid, :bid, :portal, :eid, :url, :lurl, :content, :status)
            RETURNING id
        """)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(query, {
                    "cid": raw_listing.criteria_id,
                    "bid": raw_listing.batch_id,
                    "portal": raw_listing.portal_name,
                    "eid": raw_listing.external_id,
                    "url": raw_listing.scraping_url,
                    "lurl": raw_listing.location_url,
                    "content": json.dumps(raw_listing.raw_content),
                    "status": raw_listing.http_status
                })
            return result.fetchone()[0]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='insert_raw_listing',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
            )
            return -1

    def get_raw_listing(self, raw_listing_id: int) -> dbmodels.RawListing | None:
        """
            Returns a RawListing dataclass for a raw.listing with an id of raw_listing_id.  
            If operation fails or no such listing exists, None is returned.
        """
        query = text("""
            SELECT 
                id, criteria_id, batch_id, portal_name, 
                external_id, scraping_url, location_url, raw_content, http_status, scraped_at
            FROM raw.listings
            WHERE id = :id;
        """)
        try:
            with self.engine.begin() as conn:
                result = conn.execute(query, {"id": raw_listing_id}).fetchone()
                if not result:
                    return None
                r = result._mapping
                return dbmodels.RawListing(
                    id=r['id'],
                    criteria_id=r['criteria_id'],
                    batch_id=r['batch_id'],
                    portal_name=r['portal_name'],
                    external_id=r['external_id'],
                    scraping_url=r['scraping_url'],
                    location_url=r['location_url'],
                    raw_content=r['raw_content'],
                    http_status=r['http_status'],
                    scraped_at=r['scraped_at']
                )
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_raw_listing',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"raw_listing_id": raw_listing_id}
            )
            return None

    def get_raw_listings_by_batch(self, batch_id: int) -> list[dbmodels.RawListing]:
        """
            Returns a list of RawListings by their batch_id.  
            Returns an empty list if no elements found or on failure.
        """
        query = text("""
            SELECT 
                id, criteria_id, batch_id, portal_name, 
                external_id, scraping_url, location_url, raw_content, http_status, scraped_at
            FROM raw.listings
            WHERE batch_id = :bid
        """)
        try:  
            with self.engine.begin() as conn:
                results = conn.execute(query, {"bid": batch_id}).fetchall()
                if not results:
                    return []
                return [dbmodels.RawListing(
                    id=r._mapping['id'],
                    criteria_id=r._mapping['criteria_id'],
                    batch_id=r._mapping['batch_id'],
                    portal_name=r._mapping['portal_name'],
                    external_id=r._mapping['external_id'],
                    scraping_url=r._mapping['scraping_url'],
                    location_url=r._mapping['location_url'],
                    raw_content=r._mapping['raw_content'],
                    http_status=r._mapping['http_status'],
                    scraped_at=r._mapping['scraped_at']
                ) for r in results]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE, 
                module_name='get_raw_listings_by_batch', 
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return []

    def does_this_raw_listing_exist(self, external_id: str, portal_name: str) -> bool:
        """
            Checks if the listing given by external_id and scraped from portal_name already exists.  
            Returns True if it does, False if not. Raises a DatabaseError exception on failure.
        """
        query = text("""SELECT EXISTS(SELECT 1 FROM raw.listings WHERE external_id = :eid AND portal_name = :pname)""")
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"eid": external_id, "pname": portal_name}).fetchone()[0]
                return result
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='does_this_raw_listing_exist',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"external_id": external_id, "portal_name": portal_name}
            )
            raise dbexcepts.DatabaseError

    ### CLEAN ###
    def insert_new_clean_listing(self, listing: dbmodels.CleanListing, price_history: dbmodels.PriceHistory) -> int | None:
        """
            Inserts a new clean listing.  
            Returns the id of the created listing, or None on failure.
        """
        query_listing = text("""
            INSERT INTO clean.listings 
            (criteria_id, raw_listing_id, location_id, external_id, portal_name, listing_url, title, 
            area_m2, rooms, property_type_id, market, transaction_type, first_seen_at, last_seen_at)
            VALUES 
            (:cid, :rlid, :lid, :eid, :pname, :url, :title, :area, :rooms, :ptid, :mkt, :tt, :fsa, :lsa)
            RETURNING id
        """)
        query_price = text("""
            INSERT INTO clean.price_history 
            (listing_id, batch_id, price_sale_total, price_sale_per_m2, price_rent_monthly, seen_at)
            VALUES 
            (:lid, :bid, :pst, :psm, :prm, :seen)
        """)
        try:
            with self.engine.begin() as conn:
                res = conn.execute(query_listing, {
                    "cid": listing.criteria_id, "rlid": listing.raw_listing_id,
                    "lid": listing.location_id, "eid": listing.external_id, 
                    "pname": listing.portal_name, "url": listing.listing_url, 
                    "title": listing.title, "area": listing.area_m2, 
                    "rooms": listing.rooms, "ptid": listing.property_type_id, 
                    "mkt": listing.market, "tt": listing.transaction_type, 
                    "fsa": listing.first_seen_at, "lsa": listing.last_seen_at
                })
                new_listing_id = res.fetchone()[0]
                conn.execute(query_price, {
                    "lid": new_listing_id,
                    "bid": price_history.batch_id,
                    "pst": price_history.price_sale_total,
                    "psm": price_history.price_sale_per_m2,
                    "prm": price_history.price_rent_monthly,
                    "seen": price_history.seen_at
                })
                return new_listing_id
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='insert_new_clean_listing',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"external_id": listing.external_id}
            )
            return None

    def update_clean_listing(self, clean_listing_id: int, raw_listing_id: int, last_seen_at: datetime.datetime, price_history: dbmodels.PriceHistory) -> bool:
        """
            INSERTS a new price history record for an aleardy existing listing.  
            Updates last_seen_at, raw_listing_id attributes. Also sets is_active to TRUE.  
            Returns True on success, False on failure.
        """
        query_listing = text("""
            UPDATE clean.listings 
            SET last_seen_at = :seen, 
                raw_listing_id = :rid,
                is_active = TRUE 
            WHERE id = :lid
        """)
        query_price = text("""
            INSERT INTO clean.price_history 
            (listing_id, batch_id, price_sale_total, price_sale_per_m2, price_rent_monthly, seen_at)
            VALUES 
            (:lid, :bid, :pst, :psm, :prm, :seen)
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query_price, {
                    "lid": clean_listing_id,
                    "bid": price_history.batch_id,
                    "pst": price_history.price_sale_total,
                    "psm": price_history.price_sale_per_m2,
                    "prm": price_history.price_rent_monthly,
                    "seen": last_seen_at
                })
                conn.execute(query_listing, {"seen": last_seen_at, "rid": raw_listing_id, "lid": clean_listing_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='update_clean_listing',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"clean_listing_id": clean_listing_id}
            )
            return False

    def get_clean_listing_id(self, external_id: str, portal_name: str) -> int | None:
        """
            Checks if the clean listing already exists and returns its ID, or None if not found.  
            Raises a DatabaseError exception on failure.
        """
        query = text("""
            SELECT id 
            FROM clean.listings 
            WHERE external_id = :eid AND portal_name = :pname
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"eid": external_id, "pname": portal_name}).fetchone()
                return result[0] if result else None
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_clean_listing_id',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"external_id": external_id, "portal_name": portal_name}
            )
            raise dbexcepts.DatabaseError from e

    def get_clean_listings_by_batch(self, batch_id: int) -> list[dbmodels.CleanListing]:
        """
            Returns a list of CleanListings by their batch_id.  
            Returns an empty list if no elements found or on failure.
        """
        query = text("""
            SELECT 
                cl.id, cl.raw_listing_id, cl.criteria_id, cl.location_id, cl.external_id,
                cl.portal_name, cl.listing_url, cl.title, cl.area_m2, cl.rooms,
                cl.property_type_id, cl.market, cl.transaction_type,
                cl.first_seen_at, cl.last_seen_at, cl.is_active
            FROM clean.listings cl
            JOIN clean.price_history ph ON cl.id = ph.listing_id
            WHERE ph.batch_id = :bid
        """)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"bid": batch_id})
                return [dbmodels.CleanListing(
                    id=r._mapping['id'], 
                    raw_listing_id=r._mapping['raw_listing_id'],
                    criteria_id=r._mapping['criteria_id'],
                    location_id=r._mapping['location_id'],
                    external_id=r._mapping['external_id'],
                    portal_name=r._mapping['portal_name'],
                    listing_url=r._mapping['listing_url'],
                    title=r._mapping['title'],
                    area_m2=r._mapping['area_m2'],
                    rooms=r._mapping['rooms'],
                    property_type_id=r._mapping['property_type_id'],
                    market=r._mapping['market'],
                    transaction_type=r._mapping['transaction_type'],
                    first_seen_at=r._mapping['first_seen_at'],
                    last_seen_at=r._mapping['last_seen_at'],
                    is_active=r._mapping['is_active'],
                ) for r in result]
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_clean_listings_by_batch',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"batch_id": batch_id}
            )
            return []

    def set_clean_listing_active_status(self, clean_listing_id: int, status: bool) -> bool:
        """
            Sets the is_active attribute for clean_listing_id.  
            Returns True on success, False on failure.
        """
        query = text("""
            UPDATE clean.listings
            SET is_active = :s
            WHERE id = :lid
        """)
        try:
            with self.engine.begin() as conn:
                conn.execute(query, {"s": status, "lid": clean_listing_id})
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='set_clean_listing_active_status',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"clean_listing_id": clean_listing_id, "new_status": status}
            )
            return False

    def get_price_histories_for_batch(self, batch_id: int) -> dict[int, list[dbmodels.PriceHistory]]:
        """Returns the price histories of clean listings in a given batch. Returns a dictionary {listing_id: list[PriceHistory]}"""
        query = text("""
            SELECT id, listing_id, batch_id, price_sale_total, price_sale_per_m2, price_rent_monthly, seen_at
            FROM clean.price_history
            WHERE listing_id IN (SELECT listing_id FROM clean.price_history WHERE batch_id = :bid)
            ORDER BY listing_id, seen_at DESC;
        """)
        histories_map = defaultdict(list)
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"bid": batch_id})
                for row in result:
                    r = row._mapping
                    obj = dbmodels.PriceHistory(
                        id=r['id'],
                        listing_id=r['listing_id'],
                        batch_id=r['batch_id'],
                        price_sale_total=float(r['price_sale_total']) if r['price_sale_total'] is not None else None,
                        price_sale_per_m2=float(r['price_sale_per_m2']) if r['price_sale_per_m2'] is not None else None,
                        price_rent_monthly=float(r['price_rent_monthly']) if r['price_rent_monthly'] is not None else None,
                        seen_at=r['seen_at']
                    )
                    histories_map[r['listing_id']].append(obj)
            return dict(histories_map)
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_price_histories_for_batch',
                error_message=str(e),
                context_data={"batch_id": batch_id}
            )
            return {}

    ### ANALYTICS ###
    def save_anomalies_bulk(self, anomalies: list[dbmodels.DetectedAnomaly]) -> bool:
        """Saves detected anomalies in bulk. Returns True on success, False on failure."""
        if not anomalies: return True
        try:
            with self.engine.begin() as conn:
                # Deduplicate snapshots
                unique_snapshots = {}
                for a in anomalies:
                    # (url, date) <- key to identify the listing and it's version
                    snap_key = (a.listing_snapshot.listing_url, a.listing_snapshot.captured_at)
                    if snap_key not in unique_snapshots:
                        unique_snapshots[snap_key] = a.listing_snapshot

                # Insert snapshots
                snap_id_map = {} # (url, time) -> id, used when inserting detected anomalies
                for key, snap in unique_snapshots.items():
                    res = conn.execute(text("""
                        INSERT INTO analytics.listing_snapshots 
                        (listing_url, title, location_id, area_m2, price_type, price_total, price_per_m2, price_rent, captured_at)
                        VALUES (:url, :title, :loc, :area, :ptype, :ptot, :pm2, :prent, :cap)
                        RETURNING id
                    """), {
                        "url": snap.listing_url, "title": snap.title, "loc": snap.location_id,
                        "area": snap.area_m2, "ptype": snap.price_type, "ptot": snap.price_total,
                        "pm2": snap.price_per_m2, "prent": snap.price_rent, "cap": snap.captured_at
                    })
                    snap_id_map[key] = res.fetchone()[0]

                # Prepare & insert anomalies
                anomalies_data = []
                for a in anomalies:
                    snap_key = (a.listing_snapshot.listing_url, a.listing_snapshot.captured_at)
                    snapshot_id = snap_id_map[snap_key]
                    
                    anomalies_data.append({
                        "lid": a.listing_id,
                        "sid": snapshot_id,
                        "scope": a.scope,
                        "cid": a.criteria_id,
                        "grid": a.global_rule_id,
                        "bid": a.batch_id,
                        "aid": a.analysis_id,
                        "det": json.dumps(a.trigger_details),
                        "read": a.is_read,
                        "dat": a.detected_at
                    })
                conn.execute(text("""
                    INSERT INTO analytics.detected_anomalies 
                    (listing_id, listing_snapshot_id, scope, criteria_id, global_rule_id, batch_id, analysis_id, trigger_details, is_read, detected_at)
                    VALUES (:lid, :sid, :scope, :cid, :grid, :bid, :aid, :det, :read, :dat)
                """), anomalies_data)
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='save_anomalies_bulk',
                error_message=str(e),
                stack_trace=traceback.format_exc()
            )
            return False

    def insert_batch_metrics_bulk(self, metrics_list: list[dbmodels.BatchMetrics]) -> bool:
        """Saves batch_metrics for the given batch. Returns True on success, False on failure."""
        if not metrics_list: return True
        query = text("""
            INSERT INTO analytics.batch_metrics 
            (criteria_id, batch_id, analysis_id, metrics, calculated_at)
            VALUES 
            (:criteria_id, :batch_id, :analysis_id, :metrics, :calculated_at)
        """)
        data = []
        for m in metrics_list:
            data.append({
                "criteria_id": m.criteria_id,
                "batch_id": m.batch_id,
                "analysis_id": m.analysis_id,
                "metrics": json.dumps(m.metrics), 
                "calculated_at": m.calculated_at
            })
        try:
            with self.engine.begin() as conn:
                conn.execute(query, data)
            return True
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='insert_batch_metrics_bulk',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"metrics_count": len(metrics_list)}
            )
            return False

    def get_supply_volume_history(self, criteria_id: int) -> pd.DataFrame | None:
        """Selects the data required to show supply volume as a function of time. Returns a dataframes object, or None if failed."""
        query = text("""
            SELECT 
                calculated_at,
                metrics
            FROM analytics.batch_metrics
            WHERE criteria_id = :cid 
            AND analysis_id = (SELECT id FROM config.batch_analysis_dictionary WHERE code = 'SUPPLY_VOLUME')
            ORDER BY calculated_at ASC
        """)

        loc_lookup: dict[int, str] = self.get_location_lookup()
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"cid": criteria_id})
                flat_data = []
                for row in result:
                    calc_at = row.calculated_at
                    location_data = row.metrics.get('by_location', {})
                    for loc_id_str, details in location_data.items():
                        loc_id = int(loc_id_str)
                        city_name = loc_lookup.get(loc_id, f"Loc: {loc_id}")
                        
                        flat_data.append({
                            "time": calc_at,
                            "location_name": int(loc_id),
                            "type": "Sale",
                            "volume": details['sale_count']
                        })
                        flat_data.append({
                            "time": calc_at,
                            "location_name": int(loc_id),
                            "type": "Rent",
                            "volume": details['rent_count']
                        })
                return pd.DataFrame(flat_data)
        except Exception as e:
            self.log_system_error(
                error_source=dbmodels.ErrorSources.DATABASE,
                module_name='get_supply_volume_history',
                error_message=str(e),
                stack_trace=traceback.format_exc(),
                context_data={"criteria_id": criteria_id}
            )
            return None

    def get_price_dynamics_history(self, criteria_id: int) -> pd.DataFrame | None:
        """Selects the data required to show price dynamics as a function of time. Returns a dataframes object, or None if failed. """
        loc_lookup = self.get_location_lookup()
        query = text("""
            SELECT 
                bm.calculated_at,
                bm.metrics
            FROM analytics.batch_metrics bm
            JOIN config.batch_analysis_dictionary bad ON bm.analysis_id = bad.id
            WHERE bm.criteria_id = :cid 
            AND bad.code = 'PRICE_DYNAMICS'
            ORDER BY bm.calculated_at ASC;
        """)
        
        flat_data = []
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"cid": criteria_id})
                for row in result:
                    calc_at = row.calculated_at
                    location_data = row.metrics.get('by_location', {})
                    for loc_id_str, types in location_data.items():
                        loc_id = int(loc_id_str)
                        city_name = loc_lookup.get(loc_id, f"Loc: {loc_id}")
                        for trans_type, stats in types.items():
                            if stats.get('avg') is None:
                                continue
                            flat_data.append({
                                "timestamp": calc_at,
                                "city": city_name,
                                "transaction_type": trans_type.capitalize(), # 'Sale' / 'Rent'
                                "average": float(stats['avg']),
                                "median": float(stats['median']),
                                "stddev": float(stats['std_dev']) if stats.get('std_dev') else 0.0
                            })
            return pd.DataFrame(flat_data)
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='get_price_dynamics_history',
                error_message=str(e),
                context_data={"criteria_id": criteria_id}
            )
            return None

    def get_price_distribution_latest(self, criteria_id: int) -> pd.DataFrame | None:
        """Gets the lastest price distribution data. Returns a DataFrame object or None if failed."""
        loc_lookup = self.get_location_lookup()
        query = text("""
            SELECT 
                bm.metrics,
                bm.calculated_at
            FROM analytics.batch_metrics bm
            JOIN config.batch_analysis_dictionary bad ON bm.analysis_id = bad.id
            WHERE bm.criteria_id = :cid 
            AND bad.code = 'DISTRIBUTION_CALC'
            ORDER BY bm.calculated_at DESC 
            LIMIT 1;
        """)

        flat_data = []
        try:
            with self.engine.connect() as conn:
                result = conn.execute(query, {"cid": criteria_id}).fetchone()
                if not result: return None
                metrics = result.metrics
                location_data = metrics.get('by_location', {})
                for loc_id_str, types in location_data.items():
                    loc_id = int(loc_id_str)
                    city_name = loc_lookup.get(loc_id, f"Loc {loc_id}")
                    for trans_type, dist_details in types.items():
                        bins = dist_details.get('bins', {})
                        for price_range, count in bins.items():
                            flat_data.append({
                                "city": city_name,
                                "transaction_type": trans_type.capitalize(),
                                "price_range": price_range,
                                "offer_count": int(count),
                                "calculation_date": result.calculated_at
                            })
            return pd.DataFrame(flat_data)
        except Exception as e:
            self.log_system_error(
                error_source='DATABASE',
                module_name='get_price_distribution_latest',
                error_message=str(e),
                context_data={"criteria_id": criteria_id}
            )
            return None

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
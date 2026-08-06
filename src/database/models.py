from dataclasses import dataclass, field
from datetime import datetime, time
from enum import Enum

################
# DICTIONARIES #
################
@dataclass(frozen=True)
class Location:
    location_id: int
    city_name: str

@dataclass(frozen=True)
class SystemSetting:
    setting_key: str
    setting_value: int
    is_enabled: bool
    value_type: str
    name_pl: str
    name_en: str
    description_pl: str | None
    description_en: str | None

@dataclass(frozen=True)
class SystemSettingChange:
    setting_key: str
    setting_value: int
    is_enabled: bool

class LogStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    WARNING = "WARNING"
    ANY = "ANY"

# For several queries
class TimeUnit(str, Enum):
    MINUTE = "MINUTE"
    HOUR = "HOUR"
    DAY = "DAY"
    ALL_TIME = "ALL TIME"

class ErrorSources(str, Enum):
    SCRAPER = "SCRAPER"
    CLEANER = "CLEANER"
    ANALYZER = "ANALYZER"
    DASHBOARD = "DASHBOARD"
    MAINTENANCE = "MAINTENANCE"
    DATABASE = "DATABASE"

##################
# SEARCH TARGETS #
##################
@dataclass(frozen=True)
class AnomalyAnalysis:
    id: int
    code: str
    name_pl: str
    name_en: str
    description_pl: str | None
    description_en: str | None
    takes_parameter: bool

@dataclass(frozen=True)
class BatchAnalysis:
    id: int
    code: str
    name_pl: str
    name_en: str
    description_pl: str | None
    description_en: str | None
    takes_parameter: bool

@dataclass(frozen=True)
class ActivatedAnalysis:
    analysis_id: int
    param_value: float | None

@dataclass(frozen=True)
class GlobalNotificationRule:
    id: int
    rule_name: str
    description: str | None
    transaction_type: str
    is_searching_all_cities: bool
    is_active: bool
    cities: list[str] = field(default_factory=list)
    analyses: list[ActivatedAnalysis] = field(default_factory=list)
    execution_hours: list[datetime.time] = field(default_factory=list)


###########################
# EXECUTION LOGS & ERRORS #
###########################
class SearchTargetType(Enum):
    SC = 1
    GNR = 2

@dataclass(frozen=True)
class SearchTarget:
    search_target_name: str
    search_target_type: SearchTargetType

@dataclass(frozen=True)
class RawExecLog:
    id: int
    target_display_name: str
    job_name: str
    batch_id: str
    status: str
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None

@dataclass(frozen=True)
class CleanExecLog:
    id: int
    target_display_name: str
    job_name: str
    raw_listing_id: int
    status: str
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None

@dataclass(frozen=True)
class AnalyticsExecLog:
    id: int
    target_display_name: str
    job_name: str
    batch_id: int
    clean_listing_id: int | None
    batch_analysis_id: int | None
    anomaly_analysis_id: int | None
    global_rule_id: int | None
    status: str
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None

@dataclass(frozen=True)
class AppSystemError:
    id: int
    error_source: str
    module_name: str | None
    error_message: str
    stack_trace: str | None
    context_data: dict | None
    occurred_at: datetime
    is_resolved: bool
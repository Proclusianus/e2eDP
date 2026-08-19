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
class PropertyType:
    pt_id: int
    type_name: str

@dataclass(frozen=True)
class RoomCount:
    room_id: int
    room_label: str

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

@dataclass(frozen=True)
class SystemSettingValues:
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
    UNKNOWN = "UNKNOWN"

class BatchStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY" # No data found
    PARTIAL = "PARTIAL" # Part of the pages/records error'd
    PARTIAL_RUNNING = "PARTIAL_RUNNING" #if some fail during raw/clean stages
    FAILED = "FAILED"

class ListingPriceType(str, Enum):
    RENT = "RENT"
    SALE = "SALE"

class DetectedAnomaliesScope(str, Enum):
    BATCH = "BATCH"
    GLOBAL = "GLOBAL"

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
    execution_hours: list[time] = field(default_factory=list)

@dataclass(frozen=True)
class SearchCriteria:
    id: int
    target_name: str
    description: str | None
    transaction_type: str
    market_type: str
    min_price: float | None
    max_price: float | None
    min_area: float | None
    max_area: float | None
    is_active: bool
    is_soft_deleted: bool
    created_at: datetime
    cities: list[str] = field(default_factory=list)
    property_types: list[PropertyType] = field(default_factory=list)
    rooms: list[RoomCount] = field(default_factory=list)
    execution_hours: list[time] = field(default_factory=list)
    batch_analyses: list[ActivatedAnalysis] = field(default_factory=list)
    anomaly_analyses: list[ActivatedAnalysis] = field(default_factory=list)

@dataclass(frozen=True)
class SearchCriteriaNonEssentialData:
    name: str | None
    description: str | None
    execution_hours: list[time]
    batch_analyses: list[ActivatedAnalysis]
    anomaly_analyses: list[ActivatedAnalysis]

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

########################
# LISTINGS & ANALYTICS #
########################
@dataclass(frozen=True)
class BatchData:
    id: int
    criteria_id: int | None
    status: BatchStatus
    started_at: datetime
    finished_at: datetime | None

@dataclass(frozen=True)
class RawListing:
    id: int
    criteria_id: int | None
    batch_id: int | None
    portal_name: str
    external_id: str
    scraping_url: str
    location_url: str
    raw_content: dict
    http_status: int
    scraped_at: datetime

@dataclass(frozen=True)
class PriceHistory:
    id: int
    listing_id: int
    batch_id: int | None
    price_sale_total: float | None
    price_sale_per_m2: float | None
    price_rent_monthly: float | None
    seen_at: datetime

@dataclass(frozen=True)
class CleanListing:
    id: int
    criteria_id: int | None
    raw_listing_id: int | None
    location_id: int
    external_id: str
    portal_name: str
    listing_url: str
    title: str
    area_m2: float
    rooms: int | None
    property_type_id: int
    market: str
    transaction_type: str
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool

@dataclass(frozen=True)
class ListingSnapshot:
    id: int
    listing_url: str
    title: str | None
    location_id: int
    area_m2: float | None
    price_type: ListingPriceType
    price_total: float | None
    price_per_m2: float | None
    price_rent: float | None
    captured_at: datetime

@dataclass(frozen=True)
class DetectedAnomaly:
    id: int
    listing_id: int | None
    listing_snapshot: ListingSnapshot
    scope: DetectedAnomaliesScope
    criteria_id: int | None
    global_rule_id: int | None
    batch_id: int | None
    analysis_id: int
    trigger_details: dict
    is_read: bool
    detected_at: datetime

@dataclass(frozen=True)
class BatchMetrics:
    id: int
    criteria_id: int | None
    batch_id: int | None
    analysis_id: int
    metrics: dict
    calculated_at: datetime
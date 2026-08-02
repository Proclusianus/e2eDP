from dataclasses import dataclass, field
from datetime import datetime, time

@dataclass(frozen=True)
class Location:
    location_id: int
    city_name: str

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
from typing import TypedDict, Dict

#############
# ANOMALIES #
#############
class PriceDropResult(TypedDict):
    old_price: float
    new_price: float
    drop_abs: float
    drop_rel_percent: float

class BelowThresholdResult(TypedDict):
    current_price: float
    threshold_value: float
    difference_abs: float

class BelowAvgPercentResult(TypedDict):
    current_price: float
    location_avg_price: float
    diff_percent: float

#########
# BATCH #
#########
# Supply Volume
class LocationSupplyDetails(TypedDict):
    sale_count: int
    rent_count: int
    total_count: int

class SupplyVolumeResult(TypedDict):
    total_listings: int
    by_location: Dict[str, LocationSupplyDetails] # str - location_id cast to string

# Price dynamics
class LocationPriceDetails(TypedDict):
    avg: float | None
    median: float | None
    std_dev: float | None

class PriceDynamicsResult(TypedDict):
    # str(location_id): dict["sale"/"rent": LocationPriceDetails]
    by_location: Dict[str, Dict[str, LocationPriceDetails]]

# Distribution
class DistributionDetails(TypedDict):
    # Represents one bin in a histogram
    bins: Dict[str, int] # {"10000-12000": 15, "12000-14000": 42}
    min_val: float
    max_val: float

class PriceDistributionResult(TypedDict):
    # str(location_id): dict["sale"/"rent": DistributionDetails]
    by_location: Dict[str, Dict[str, DistributionDetails]]

import argparse
import sys
import os
import datetime
import traceback
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Dict


import numpy as np


import database.models as dbmodels
import analysis_results as armodels
from database.db_manager import DBManager

##############
# DATA TYPES #
##############
@dataclass()
class ShouldDoAnalysis:
    an_PRICE_DROP: bool
    an_BELOW_THRESHOLD: bool
    an_BELOW_AVG_PERCENT: bool
    ba_DISTRIBUTION_CALC: bool
    ba_PRICE_DYNAMICS: bool
    ba_SUPPLY_VOLUME: bool

@dataclass(frozen=True)
class LocationMetrics:
    location_id: int

    avg_sale_pm2: float | None = None
    median_sale_pm2: float | None = None
    std_dev_sale_pm2: float | None = None
    count_sale: int = 0
    
    avg_rent_total: float | None = None
    median_rent_total: float | None = None
    std_dev_rent_total: float | None = None
    count_rent: int = 0

####################
# GLOBAL VARIABLES #
####################
DB = DBManager()
BID = 0
DEBUG = False

BATCH_DEFINITIONS = DB.get_batch_analysis_definitions()
ANOMALY_DEFINITIONS = DB.get_anomaly_analysis_definitions()
ANALYSIS_KEY2ID_MAPPING = {}

#############
# FUNCTIONS #
#############
def get_analysis_key2id_mapping() -> dict:
    mapping = {}
    for definition in ANOMALY_DEFINITIONS:
        mapping[f"{definition.code}"] = definition.id
    for definition in BATCH_DEFINITIONS:
        mapping[f"{definition.code}"] = definition.id
    return mapping

def get_matching_global_rules(criteria: dbmodels.SearchCriteria) -> list[dbmodels.GlobalNotificationRule]:
    all_gnr: list[dbmodels.GlobalNotificationRule] = DB.get_current_global_notifs()
    if not all_gnr:
        if DEBUG: print("No global rules found in database.")
        return []

    matching_rules: list[dbmodels.GlobalNotificationRule] = []
    criteria_cities: set[str] = {c for c in criteria.cities}
    for rule in all_gnr:
        if not rule.is_active:
            continue
        if rule.transaction_type != criteria.transaction_type:
            continue
        if rule.is_searching_all_cities:
            matching_rules.append(rule)

        rule_cities = {c for c in rule.cities}
        if criteria_cities.intersection(rule_cities):
            matching_rules.append(rule)
            if DEBUG: print(f"Global rule '{rule.rule_name}' matches current batch.")

    return matching_rules

def get_gnr_anomaly_ids(global_rules: list[dbmodels.GlobalNotificationRule]) -> dict[int, list[int]]:
    return {rule.id: {an.analysis_id for an in rule.analyses} for rule in global_rules}

def get_active_analyses_for_this_run(criteria: dbmodels.SearchCriteria, rules: list[dbmodels.GlobalNotificationRule]) -> ShouldDoAnalysis:
    active_ids = set()
    for an in criteria.batch_analyses:
        active_ids.add(an.analysis_id)
    for an in criteria.anomaly_analyses:
        active_ids.add(an.analysis_id)
    for rule in rules:
        for an in rule.analyses:
            active_ids.add(an.analysis_id)

    flags = {
        "an_PRICE_DROP": False,
        "an_BELOW_THRESHOLD": False,
        "an_BELOW_AVG_PERCENT": False,
        "ba_DISTRIBUTION_CALC": False,
        "ba_PRICE_DYNAMICS": False,
        "ba_SUPPLY_VOLUME": False
    }
    for d in BATCH_DEFINITIONS:
        if d.id in active_ids:
            key = f"ba_{d.code}"
            if key in flags:
                flags[key] = True
    for d in ANOMALY_DEFINITIONS:
        if d.id in active_ids:
            key = f"an_{d.code}"
            if key in flags:
                flags[key] = True

    return ShouldDoAnalysis(**flags)

def calculate_stats_per_location(clean_data: list[dbmodels.CleanListing],
                                 prices_map: dict[int, list[dbmodels.PriceHistory]]) -> dict[int, LocationMetrics]:
    grouped_prices = defaultdict(lambda: {'sale': [], 'rent': []})
    for cd in clean_data:
        ph = prices_map.get(cd.id)
        if not ph: continue
        if cd.transaction_type == 'sale' and ph[0].price_sale_per_m2:
            grouped_prices[cd.location_id]['sale'].append(float(ph[0].price_sale_per_m2))
        elif cd.transaction_type == 'rent' and ph[0].price_rent_monthly:
            grouped_prices[cd.location_id]['rent'].append(float(ph[0].price_rent_monthly))

    final_stats = {}
    for loc_id, types in grouped_prices.items():
        s_prices = np.array(types['sale'])
        r_prices = np.array(types['rent'])
        s_metrics = {}
        if len(s_prices) > 0:
            s_metrics = {
                "avg": float(np.mean(s_prices)),
                "med": float(np.median(s_prices)),
                "std": float(np.std(s_prices)),
                "count": len(s_prices)
            }
        r_metrics = {}
        if len(r_prices) > 0:
            r_metrics = {
                "avg": float(np.mean(r_prices)),
                "med": float(np.median(r_prices)),
                "std": float(np.std(r_prices)),
                "count": len(r_prices)
            }
        final_stats[loc_id] = LocationMetrics(
            location_id=loc_id,
            avg_sale_pm2=s_metrics.get("avg"),
            median_sale_pm2=s_metrics.get("med"),
            std_dev_sale_pm2=s_metrics.get("std"),
            count_sale=s_metrics.get("count", 0),
            avg_rent_total=r_metrics.get("avg"),
            median_rent_total=r_metrics.get("med"),
            std_dev_rent_total=r_metrics.get("std"),
            count_rent=r_metrics.get("count", 0)
        )
    return final_stats

def create_detected_anomaly(listing_snapshot: dbmodels.ListingSnapshot, details: dict, analysis_id: int, listing_id: int, 
                            global_rule_id: int | None, criteria_id: int | None) -> dbmodels.DetectedAnomaly | None:
    if global_rule_id is not None:
        scope = dbmodels.DetectedAnomaliesScope.GLOBAL
    elif criteria_id is not None:
        scope = dbmodels.DetectedAnomaliesScope.BATCH
    else:
        if DEBUG: print("Warning: Attempted to create anomaly without criteria_id or global_rule_id")
        return None

    return dbmodels.DetectedAnomaly(
        id=0, #unused
        listing_id=listing_id,
        listing_snapshot=listing_snapshot,
        scope=scope,
        criteria_id=criteria_id,
        global_rule_id=global_rule_id,
        batch_id=BID,
        analysis_id=analysis_id,
        trigger_details=details,
        is_read=False,
        detected_at=datetime.datetime.now(datetime.timezone.utc)
    )

def create_listing_snapshot(clean_listing: dbmodels.CleanListing, price_history: list[dbmodels.PriceHistory]) -> dbmodels.ListingSnapshot | None:
    if clean_listing is None: 
        if DEBUG: print("Failed to create a listing snapshot for clean listing; clean_listing is None")
        return None
    if not price_history:
        if DEBUG: print(f"Failed to create a listing snapshot for clean listing {clean_listing.id}; price_history is None")
        return None
    cl = clean_listing
    ph = price_history[0]

    if cl.transaction_type == 'sale':
        price_type = dbmodels.ListingPriceType.SALE
    else:
        price_type = dbmodels.ListingPriceType.RENT

    return dbmodels.ListingSnapshot(
        id=0, #unused
        listing_url=cl.listing_url,
        title=cl.title,
        location_id=cl.location_id,
        area_m2=cl.area_m2,
        price_type=price_type,
        price_total=ph.price_sale_total,
        price_per_m2=ph.price_sale_per_m2,
        price_rent=ph.price_rent_monthly,
        captured_at=cl.last_seen_at
    )

def get_search_target_param_value(search_target_anomaly_analyses: list[dbmodels.ActivatedAnalysis], analysis_id) -> float | None:
    match = next((an for an in search_target_anomaly_analyses if an.analysis_id == analysis_id), None)
    if match:
        return float(match.param_value) if match.param_value is not None else None
    return None

def do_SUPPLY_VOLUME(location_stats: dict[int, LocationMetrics]) -> armodels.SupplyVolumeResult:
    if location_stats is None: 
        if DEBUG: print(f"Failed to obtain function parameter/parameters for do_SUPPLY_VOLUME")
        return None
    if DEBUG: print(f"Starting do_SUPPLY_VOLUME")
    total = 0
    by_loc: Dict[str, armodels.LocationSupplyDetails] = {}

    for loc_id, stats in location_stats.items():
        count_sale = stats.count_sale
        count_rent = stats.count_rent
        
        total += (count_sale + count_rent)
        by_loc[str(loc_id)] = armodels.LocationSupplyDetails(
            sale_count=count_sale,
            rent_count=count_rent,
            total_count=count_sale + count_rent
        )

    return armodels.SupplyVolumeResult(
        total_listings=total,
        by_location=by_loc
    )

def do_PRICE_DYNAMICS(location_stats: dict[int, LocationMetrics]) -> armodels.PriceDynamicsResult:
    location_breakdown: Dict[str, Dict[str, armodels.LocationPriceDetails]] = {}
    for loc_id, stats in location_stats.items():
        location_breakdown[str(loc_id)] = {
            "sale": armodels.LocationPriceDetails(
                avg=stats.avg_sale_pm2,
                median=stats.median_sale_pm2,
                std_dev=stats.std_dev_sale_pm2
            ),
            "rent": armodels.LocationPriceDetails(
                avg=stats.avg_rent_total,
                median=stats.median_rent_total,
                std_dev=stats.std_dev_rent_total
            )
        }

    return armodels.PriceDynamicsResult(by_location=location_breakdown)

def do_DISTRIBUTION_CALC(clean_data: list[dbmodels.CleanListing], prices_map: dict[int, list[dbmodels.PriceHistory]], 
                         bin_count: int = 10) -> armodels.PriceDistributionResult:
    # Cpllect raw prices
    raw_data_map = defaultdict(lambda: {'sale': [], 'rent': []})
    for cd in clean_data:
        ph_list = prices_map.get(cd.id)
        if not ph_list: continue
        curr = ph_list[0]
        
        if cd.transaction_type == 'sale' and curr.price_sale_per_m2:
            raw_data_map[cd.location_id]['sale'].append(float(curr.price_sale_per_m2))
        elif cd.transaction_type == 'rent' and curr.price_rent_monthly:
            raw_data_map[cd.location_id]['rent'].append(float(curr.price_rent_monthly))

    # Sort the data into bins
    final_result: Dict[str, Dict[str, armodels.DistributionDetails]] = {}
    for loc_id, types in raw_data_map.items():
        loc_res = {}
        for t_type, prices in types.items():
            if len(prices) < 2: continue # Needs at least two data points
            
            np_prices = np.array(prices)
            counts, edges = np.histogram(np_prices, bins=bin_count)
            bin_dict = {}
            for i in range(len(counts)):
                label = f"{int(edges[i])}-{int(edges[i+1])}"
                bin_dict[label] = int(counts[i])

            loc_res[t_type] = armodels.DistributionDetails(
                bins=bin_dict,
                min_val=float(np.min(np_prices)),
                max_val=float(np.max(np_prices))
            )
        if loc_res:
            final_result[str(loc_id)] = loc_res
    return armodels.PriceDistributionResult(by_location=final_result)

def do_PRICE_DROP(clean_listing: dbmodels.CleanListing, 
                  price_histories: dict[int, list[dbmodels.PriceHistory]]) -> armodels.PriceDropResult | None:
    """Returns True if price has dropped, False if not"""
    if clean_listing is None or price_histories is None: 
        if DEBUG: print(f"Failed to obtain function parameter/parameters for do_PRICE_DROP")
        return None
    cid = clean_listing.id
    history = price_histories.get(cid)
    if not history: 
        if DEBUG: print(f"Failed to obtain history for do_PRICE_DROP")
        return None
    if len(history) < 2:
        if DEBUG: print(f"Failed to obtain len(history)<2 for do_PRICE_DROP")
        return None
    if DEBUG: print(f"Starting do_PRICE_DROP(clean_listing_id={cid})")

    new_price = None
    if clean_listing.transaction_type == 'sale': new_price = history[0].price_sale_total
    else: new_price = history[0].price_rent_monthly
    old_price = None
    if clean_listing.transaction_type == 'sale': old_price = history[1].price_sale_total
    else: old_price = history[1].price_rent_monthly

    if new_price is None: 
        if DEBUG: print(f"Failed to obtain new_price for do_PRICE_DROP(clean_listing_id={cid})")
        return None
    if old_price is None:
        if DEBUG: print(f"Failed to obtain old_price for do_PRICE_DROP(clean_listing_id={cid})")
        return None

    if new_price < old_price:
        drop_abs = float(old_price - new_price)
        if DEBUG: print(f"FOUND ANOMALY: clean listing (id={cid}) price dropped by {drop_abs}")
        return armodels.PriceDropResult(
            old_price=float(old_price),
            new_price=float(new_price),
            drop_abs=drop_abs,
            drop_rel_percent=round((drop_abs / float(old_price)) * 100, 2)
        )
    return None

def do_BELOW_THRESHOLD(clean_listing: dbmodels.CleanListing, price_histories: dict[int, list[dbmodels.PriceHistory]], 
                       threshold_value: float) -> armodels.BelowThresholdResult | None:
    if clean_listing is None or price_histories is None or threshold_value is None: 
        if DEBUG: print(f"Failed to obtain function parameter/parameters for do_BELOW_THRESHOLD")
        return None
    cl=clean_listing
    if DEBUG: print(f"Starting do_BELOW_THRESHOLD(clean_listing_id={cl.id})")
    latest_history = price_histories.get(cl.id)

    if not latest_history: 
        if DEBUG: print(f"Failed to obtain latest_history for do_BELOW_THRESHOLD(clean_listing_id={cl.id})")
        return None
    current_price = latest_history[0]
    if cl.transaction_type == 'sale':
        current_val = current_price.price_sale_total
    else:
        current_val = current_price.price_rent_monthly
    if current_val is None:
        if DEBUG: print(f"Failed to obtain current_val for do_BELOW_THRESHOLD(clean_listing_id={cl.id})")
        return None

    current_val_f = float(current_val)
    if current_val_f < threshold_value:
        diff = round(threshold_value - current_val_f, 2)
        if DEBUG: print(f"FOUND ANOMALY: clean listing (id={cl.id}) is {diff} below the threshold value")
        return armodels.BelowThresholdResult(
            current_price=current_val_f,
            threshold_value=threshold_value,
            difference_abs=diff
        )
    return None

def do_BELOW_AVG_PERCENT(clean_listing: dbmodels.CleanListing, price_histories: dict[int, list[dbmodels.PriceHistory]],
                         location_stats: dict[int, LocationMetrics], threshold_percent: float) -> armodels.BelowAvgPercentResult | None:
    if clean_listing is None or price_histories is None or location_stats is None or threshold_percent is None: 
        if DEBUG: print(f"Failed to obtain function parameter/parameters for do_BELOW_AVG_PERCENT")
        return None
    cl = clean_listing
    if DEBUG: print(f"Starting do_BELOW_AVG_PERCENT(clean_listing_id={cl.id})")

    stats = location_stats.get(cl.location_id)
    if not stats: 
        if DEBUG: print(f"Failed to obtain stats for do_BELOW_AVG_PERCENT(clean_listing_id={cl.id})")
        return None
    history = price_histories.get(clean_listing.id)
    if not history:
        if DEBUG: print(f"Failed to obtain history for do_BELOW_AVG_PERCENT(clean_listing_id={cl.id})")
        return None
    current_rec = history[0]

    market_avg = None
    current_val = None
    if cl.transaction_type == 'sale':
        market_avg = stats.avg_sale_pm2
        current_val = current_rec.price_sale_per_m2
    elif cl.transaction_type == 'rent':
        market_avg = stats.avg_rent_total
        current_val = current_rec.price_rent_monthly
    if market_avg is None or current_val is None or market_avg <= 0:
        if DEBUG: print(f"Failed to obtain price data for do_BELOW_AVG_PERCENT: market_avg={market_avg}, current_val={current_val}")
        return None
    current_val_f = float(current_val)
    market_avg_f = float(market_avg)

    diff_abs = market_avg_f - current_val_f
    if diff_abs <= 0:
        return None
    diff_percent = (diff_abs / market_avg_f) * 100
    if diff_percent >= threshold_percent:
        if DEBUG: print(f"FOUND ANOMALY: clean listing (id={cl.id}) is {round(diff_percent, 2)}% below avg")
        return armodels.BelowAvgPercentResult(
            current_price=current_val_f,
            location_avg_price=market_avg_f,
            diff_percent=round(diff_percent, 2)
        )
    return None

def analyze_batch() -> bool:
    """
        Analyzes the collected batch records.  
        Returns int of the processed batch, or -1 on failure
    """
    batch: dbmodels.BatchData = DB.get_batch(BID)
    if batch is None:
        if DEBUG: print(f"Failed to SELECT the batch with an id: {BID}")
        return False

    criteria: dbmodels.SearchCriteria = DB.get_search_criteria(batch.criteria_id)
    if criteria is None:
        if DEBUG: print(f"Failed to SELECT the criteria with an id: {batch.criteria_id}")
        return False
    criteria_anomaly_analysis_ids = {an.analysis_id for an in criteria.anomaly_analyses}

    clean_data: list[dbmodels.CleanListing] = DB.get_clean_listings_by_batch(BID)
    if not clean_data:
        if DEBUG: print(f"Failed to SELECT the clean listings for batch with an id: {BID}")
        return False

    global_rules: list[dbmodels.GlobalNotificationRule] = get_matching_global_rules(criteria)
    gnr_anomaly_analysis_ids: dict[int, list[int]] = get_gnr_anomaly_ids(global_rules)
    should_do_analysis: ShouldDoAnalysis = get_active_analyses_for_this_run(criteria, global_rules)
    does_any_anomaly_analysis: bool = (should_do_analysis.an_BELOW_AVG_PERCENT or should_do_analysis.an_BELOW_THRESHOLD or should_do_analysis.an_PRICE_DROP)
    does_any_batch_analysis: bool = (should_do_analysis.ba_DISTRIBUTION_CALC or should_do_analysis.ba_PRICE_DYNAMICS or should_do_analysis.ba_SUPPLY_VOLUME)

    price_histories: dict[int, list[dbmodels.PriceHistory]] = DB.get_price_histories_for_batch(BID) 
    stats_map: dict[int, LocationMetrics] = calculate_stats_per_location(clean_data, price_histories)

    detected_anomalies: list[dbmodels.DetectedAnomaly] = []
    batch_metrics: list[dbmodels.BatchMetrics] = []
    execution_logs: list[dbmodels.AnalyticsExecLog] = []
    if does_any_anomaly_analysis:
        for cd in clean_data:
            if DEBUG: print(f"Starting analysis loop for (clean_listing_id={cd.id})")
            analyzing_started_at = datetime.datetime.now(datetime.timezone.utc)
            current_status = dbmodels.LogStatus.SUCCESS
            error_msg = None
            listing_snapshot = create_listing_snapshot(cd, price_histories.get(cd.id))

            if should_do_analysis.an_PRICE_DROP:
                try:
                    result = do_PRICE_DROP(cd, price_histories)
                    if result is not None:
                        pd_an_id = ANALYSIS_KEY2ID_MAPPING['PRICE_DROP']
                        if pd_an_id in criteria_anomaly_analysis_ids:
                            detected_anomalies.append(create_detected_anomaly(listing_snapshot, result, pd_an_id, cd.id, None, criteria.id))
                        for rule in global_rules:
                            if pd_an_id in gnr_anomaly_analysis_ids.get(rule.id):
                                detected_anomalies.append(create_detected_anomaly(listing_snapshot, result, pd_an_id, cd.id, rule.id, None))
                except Exception as e:
                    current_status = dbmodels.LogStatus.FAILED
                    error_msg = str(e)
                    if DEBUG: print(f"Error processing clean_listing {cd.id} for analysis PRICE_DROP: {e}")
                execution_logs.append(dbmodels.AnalyticsExecLog(
                    id=0, target_display_name = "", # unused
                    job_name="analyzer.py",
                    batch_id=BID,
                    clean_listing_id=cd.id,
                    batch_analysis_id=None,
                    anomaly_analysis_id=ANALYSIS_KEY2ID_MAPPING['PRICE_DROP'],
                    global_rule_id=None, # is ignored here, but it doesn't matter much
                    status=current_status,
                    error_message=error_msg,
                    started_at=analyzing_started_at,
                    finished_at=datetime.datetime.now(datetime.timezone.utc)
                ))
                current_status = dbmodels.LogStatus.SUCCESS
                error_msg = None

            if should_do_analysis.an_BELOW_THRESHOLD:
                try:
                    bt_an_id = ANALYSIS_KEY2ID_MAPPING['BELOW_THRESHOLD']
                    if bt_an_id in criteria_anomaly_analysis_ids:
                        crit_result = do_BELOW_THRESHOLD(cd, price_histories, get_search_target_param_value(criteria.anomaly_analyses, bt_an_id))
                        if crit_result:
                            detected_anomalies.append(create_detected_anomaly(listing_snapshot, crit_result, bt_an_id, cd.id, None, criteria.id))
                    for rule in global_rules:
                        if bt_an_id in gnr_anomaly_analysis_ids.get(rule.id):
                            rule_result = do_BELOW_THRESHOLD(cd, price_histories, get_search_target_param_value(rule.analyses, bt_an_id))
                            if rule_result:
                                detected_anomalies.append(create_detected_anomaly(listing_snapshot, rule_result, bt_an_id, cd.id, rule.id, None))
                except Exception as e:
                    current_status = dbmodels.LogStatus.FAILED
                    error_msg = str(e)
                    if DEBUG: print(f"Error processing clean_listing {cd.id} for analysis BELOW_THRESHOLD: {e}")
                execution_logs.append(dbmodels.AnalyticsExecLog(
                    id=0, target_display_name = "", # unused
                    job_name="analyzer.py",
                    batch_id=BID,
                    clean_listing_id=cd.id,
                    batch_analysis_id=None,
                    anomaly_analysis_id=bt_an_id,
                    global_rule_id=None,
                    status=current_status,
                    error_message=error_msg,
                    started_at=analyzing_started_at,
                    finished_at=datetime.datetime.now(datetime.timezone.utc)
                ))
                current_status = dbmodels.LogStatus.SUCCESS
                error_msg = None

            if should_do_analysis.an_BELOW_AVG_PERCENT:
                try:
                    bap_an_id = ANALYSIS_KEY2ID_MAPPING['BELOW_AVG_PERCENT']
                    if bap_an_id in criteria_anomaly_analysis_ids:
                        crit_result = do_BELOW_AVG_PERCENT(cd, price_histories, stats_map, get_search_target_param_value(criteria.anomaly_analyses, bap_an_id))
                        if crit_result:
                            detected_anomalies.append(create_detected_anomaly(listing_snapshot, crit_result, bap_an_id, cd.id, None, criteria.id))
                    for rule in global_rules:
                        if bap_an_id in gnr_anomaly_analysis_ids.get(rule.id):
                            rule_result = do_BELOW_AVG_PERCENT(cd, price_histories, stats_map, get_search_target_param_value(rule.analyses, bap_an_id))
                            if rule_result:
                                detected_anomalies.append(create_detected_anomaly(listing_snapshot, rule_result, bap_an_id, cd.id, rule.id, None))
                except Exception as e:
                    current_status = dbmodels.LogStatus.FAILED
                    error_msg = str(e)
                    if DEBUG: print(f"Error processing clean_listing {cd.id} for analysis BELOW_AVG_PERCENT: {e}")
                execution_logs.append(dbmodels.AnalyticsExecLog(
                    id=0, target_display_name = "", # unused
                    job_name="analyzer.py",
                    batch_id=BID,
                    clean_listing_id=cd.id,
                    batch_analysis_id=None,
                    anomaly_analysis_id=bap_an_id,
                    global_rule_id=None,
                    status=current_status,
                    error_message=error_msg,
                    started_at=analyzing_started_at,
                    finished_at=datetime.datetime.now(datetime.timezone.utc)
                ))

        if DEBUG: print(f"Anomaly analysis loop for batch={BID} Finished. Starting Batch metrics")
    else:
        if DEBUG: print(f"No anomaly analyses for batch={BID} requested. Starting Batch metrics")

    if should_do_analysis.ba_SUPPLY_VOLUME:
        analyzing_started_at = datetime.datetime.now(datetime.timezone.utc)
        current_status = dbmodels.LogStatus.SUCCESS
        error_msg = None
        sv_an_id = ANALYSIS_KEY2ID_MAPPING['SUPPLY_VOLUME']
        try:
            if DEBUG: print(f"Beginning SUPPLY_VOLUME analysis for batch={BID}")
            batch_metrics.append(dbmodels.BatchMetrics(
                id=0, # unused
                criteria_id=criteria.id,
                batch_id=BID,
                analysis_id=sv_an_id,
                metrics=do_SUPPLY_VOLUME(stats_map),
                calculated_at=datetime.datetime.now(datetime.timezone.utc)
            ))
        except Exception as e:
            current_status = dbmodels.LogStatus.FAILED
            error_msg = str(e)
            if DEBUG: print(f"Error processing batch analysis SUPPLY_VOLUME: {e}")
        execution_logs.append(dbmodels.AnalyticsExecLog(
            id=0, target_display_name = "", # unused
            job_name="analyzer.py",
            batch_id=BID,
            clean_listing_id=None,
            batch_analysis_id=sv_an_id,
            anomaly_analysis_id=None,
            global_rule_id=None,
            status=current_status,
            error_message=error_msg,
            started_at=analyzing_started_at,
            finished_at=datetime.datetime.now(datetime.timezone.utc)
        ))

    if should_do_analysis.ba_PRICE_DYNAMICS:
        analyzing_started_at = datetime.datetime.now(datetime.timezone.utc)
        current_status = dbmodels.LogStatus.SUCCESS
        error_msg = None
        pdyn_an_id = ANALYSIS_KEY2ID_MAPPING['PRICE_DYNAMICS']
        try:
            if DEBUG: print(f"Beginning PRICE_DYNAMICS analysis for batch={BID}")
            batch_metrics.append(dbmodels.BatchMetrics(
                id=0, # unused
                criteria_id=criteria.id,
                batch_id=BID,
                analysis_id=pdyn_an_id,
                metrics=do_PRICE_DYNAMICS(stats_map),
                calculated_at=datetime.datetime.now(datetime.timezone.utc)
            ))
        except Exception as e:
            current_status = dbmodels.LogStatus.FAILED
            error_msg = str(e)
            if DEBUG: print(f"Error processing batch analysis PRICE_DYNAMICS: {e}")
        execution_logs.append(dbmodels.AnalyticsExecLog(
            id=0, target_display_name = "", # unused
            job_name="analyzer.py",
            batch_id=BID,
            clean_listing_id=None,
            batch_analysis_id=pdyn_an_id,
            anomaly_analysis_id=None,
            global_rule_id=None,
            status=current_status,
            error_message=error_msg,
            started_at=analyzing_started_at,
            finished_at=datetime.datetime.now(datetime.timezone.utc)
        ))

    if should_do_analysis.ba_DISTRIBUTION_CALC:
        analyzing_started_at = datetime.datetime.now(datetime.timezone.utc)
        current_status = dbmodels.LogStatus.SUCCESS
        error_msg = None
        dc_an_id = ANALYSIS_KEY2ID_MAPPING['DISTRIBUTION_CALC']
        try:
            if DEBUG: print(f"Beginning DISTRIBUTION_CALC analysis for batch={BID}")
            batch_metrics.append(dbmodels.BatchMetrics(
                id=0, # unused
                criteria_id=criteria.id,
                batch_id=BID,
                analysis_id=dc_an_id,
                metrics=do_DISTRIBUTION_CALC(clean_data, price_histories),
                calculated_at=datetime.datetime.now(datetime.timezone.utc)
            ))
        except Exception as e:
            current_status = dbmodels.LogStatus.FAILED
            error_msg = str(e)
            if DEBUG: print(f"Error processing batch analysis DISTRIBUTION_CALC: {e}")
        execution_logs.append(dbmodels.AnalyticsExecLog(
            id=0, target_display_name = "", # unused
            job_name="analyzer.py",
            batch_id=BID,
            clean_listing_id=None,
            batch_analysis_id=dc_an_id,
            anomaly_analysis_id=None,
            global_rule_id=None,
            status=current_status,
            error_message=error_msg,
            started_at=analyzing_started_at,
            finished_at=datetime.datetime.now(datetime.timezone.utc)
        ))

    flag_inserted_ba_an = False
    flag_inserted_an_an = False
    if does_any_batch_analysis and DB.insert_batch_metrics_bulk(batch_metrics):
        if DEBUG: print("Inserting batch metrics successful.")
        flag_inserted_ba_an = True
    else:
        if DEBUG: print("ERROR: Inserting batch metrics failed!")
    if does_any_anomaly_analysis and DB.save_anomalies_bulk(detected_anomalies):
        if DEBUG: print("Inserting detected anomalies successful.")
        flag_inserted_an_an = True
    else:
        if DEBUG: print("ERROR: Inserting detected anomalies failed!")
    if DB.insert_analytics_execution_logs_bulk(execution_logs):
        if DEBUG: print("Inserting execution logs successful.")
    else:
        if DEBUG: print("ERROR: Inserting execution logs failed!")

    if (flag_inserted_ba_an and does_any_batch_analysis) or (flag_inserted_an_an and does_any_anomaly_analysis):
        DB.set_batch_status(BID, dbmodels.BatchStatus.SUCCESS)
        return True
    elif ((not flag_inserted_ba_an) and does_any_batch_analysis) or ((not flag_inserted_an_an) and does_any_anomaly_analysis):
        DB.set_batch_status(BID, dbmodels.BatchStatus.PARTIAL)
        return True
    else:
        DB.set_batch_status(BID, dbmodels.BatchStatus.FAILED)
        return False

def main():
    """
        Starts the analyzer for the given batch id.  
        Exits with code 0 on success, code 1 on failure
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "batch_id", 
        type=int, 
        help="ID of the batch to process from orchestration.batches"
    )
    parser.add_argument(
        "-d", "--debug", 
        action='store_true', 
        help="Prints debug statements"
    )
    args = parser.parse_args()
    global BID, DEBUG, ANALYSIS_KEY2ID_MAPPING
    BID = args.batch_id
    DEBUG = args.debug
    ANALYSIS_KEY2ID_MAPPING = get_analysis_key2id_mapping()

    if DEBUG: print(f"Analysis begins for batch_id: {BID}")
    try:
        success = analyze_batch()
    except Exception as e:
        if DEBUG: print(f"Analysis for batch_id: {BID} failed: {str(e)}")
        DB.set_batch_status(BID, dbmodels.BatchStatus.FAILED)
        DB.log_system_error(
            error_source=dbmodels.ErrorSources.ANALYZER,
            module_name="analyzer.analyze_batch",
            error_message=str(e),
            stack_trace=traceback.format_exc(),
            context_data={"batch_id": BID}
        )
        sys.exit(2)
        
    if success:
        if DEBUG: print(f"Analysis for batch_id: {BID} successful")
        #print(BID)
        sys.exit(0)
    else:
        if DEBUG: print(f"Analysis for batch_id: {BID} failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
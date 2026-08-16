import argparse
import sys
import os
import datetime
from dataclasses import dataclass, field
from typing import Literal

import database.models as dbmodels
from database.db_manager import DBManager

##############
# DATA TYPES #
##############
@dataclass()
class MetaData:
    """Obtained from previously collected data - from search criteria/raw listing etc"""
    location_id: int
    portal_name: str
    property_type_id: int
    transaction_type: Literal['sale', 'rent']

@dataclass()
class ExtractedData:
    """Obtained from cleaning a raw listing"""
    external_id: str
    listing_url: str
    title: str
    area_m2: float
    rooms: int | None
    price_sale_total: float | None
    price_sale_per_m2: float | None
    price_rent_monthly: float | None
    seen_at: datetime

####################
# GLOBAL VARIABLES #
####################
DB = DBManager()
BID = 0
DEBUG = False
PORTAL = 'otodom'

ROOM_MAP = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
    "SIX": 6, "SEVEN": 7, "EIGHT": 8, "NINE": 9, "TEN": 10
}
PROPERTY_TYPES: list[dbmodels.PropertyType] = DB.get_all_property_types()
PROPERTY_TYPE_MAP = {pt.type_name: pt.pt_id for pt in PROPERTY_TYPES}

#############
# FUNCTIONS #
#############
def is_regular_ad(data: dict) -> bool:
    return data.get("estate") != "INVESTMENT"

def get_property_type_id_from_scraping_url(scraping_url: str) -> int | None:
    clean_url = scraping_url.split('?')[0]
    property_map = {"Apartment": "mieszkanie", "House": "dom"}
    
    found_internal_name = None
    for internal_name, url_fragment in property_map.items():
        if f"/{url_fragment}" in clean_url:
            found_internal_name = internal_name
            break
            
    if found_internal_name:
        return PROPERTY_TYPE_MAP.get(found_internal_name)
        
    return None

def get_market_type(ad: dict, scraping_url: str) -> str:
    clean_url = scraping_url.split('?')[0]
    market_map = {'primary': ",rynek-pierwotny", 'secondary': ",rynek-wtorny"}
    for market_key, url_fragment in market_map.items():
        if url_fragment in clean_url:
            return market_key

    # If it's unspecified in the scraping url, check the json
    # To be precise this would also require scraping the offer url specified in ad,
    # because there is no information about it in the ad itself.
    # Since this project is just an exercise and this one piece of data is insignificant, 
    # I will use this simpler version here.
    if ad.get("estate") == "INVESTMENT":
        return "primary"
    agency_type = ad.get("agency", {}).get("type") if ad.get("agency") else None
    if agency_type == "DEVELOPER":
        return "primary"
    if ad.get("isPrivateOwner") is True:
        return "secondary"
    return "secondary"

def get_listing_metadata(raw_listing: dbmodels.RawListing, criteria: dbmodels.SearchCriteria) -> MetaData:
    if DEBUG: print(f"{raw_listing.location_url}")
    return MetaData(
        location_id=DB.get_location_mapping_location(PORTAL, raw_listing.location_url).location_id,
        portal_name=raw_listing.portal_name,
        property_type_id=get_property_type_id_from_scraping_url(raw_listing.scraping_url),
        transaction_type=criteria.transaction_type
    )

def parse_rooms(rooms_str: str | None) -> int | None:
    if not rooms_str: return None
    return ROOM_MAP.get(rooms_str.upper())

def extract_regular_ad(ad: dict, transaction_type: Literal['sale', 'rent'], scraped_at: datetime.datetime) -> ExtractedData:
    offer_url = ad.get("slug", "")
    full_url = f"https://www.otodom.pl/pl/oferta/{offer_url}"

    extracted: ExtractedData = ExtractedData(
        external_id = str(ad.get("id")),
        listing_url=full_url,
        title=ad.get("title", "No Title"),
        area_m2=float(ad.get("areaInSquareMeters") or 0),
        rooms=parse_rooms(ad.get("roomsNumber")),
        price_sale_total=None,
        price_sale_per_m2=None,
        price_rent_monthly=None,
        seen_at=scraped_at
    )

    total_price = ad.get("totalPrice") # If sale then that's the price for sale, if rent, then that's the monthly rent
    price_val = float(total_price["value"]) if total_price and total_price.get("value") is not None else None
    m2_price = ad.get("pricePerSquareMeter")
    price_m2_val = float(m2_price["value"]) if m2_price and m2_price.get("value") is not None else None
    if transaction_type == "rent":
        rent_price = ad.get("rentPrice") # some additional monthly payments
        price_val += float(rent_price["value"]) if rent_price and rent_price.get("value") is not None else None

    if transaction_type == "sale":
        extracted.price_sale_total = price_val
    else:
        extracted.price_rent_monthly = price_val
    extracted.price_sale_per_m2 = price_m2_val
    if DEBUG: print(f"Extracting data for: {extracted.external_id} complete")

    return extracted

def extract_investment(ad: dict, transaction_type: Literal['sale', 'rent'], scraped_at: datetime.datetime) -> list[ExtractedData]:
    results = []
    sub_ads = ad.get("relatedAds", [])
    for sub_ad in sub_ads:
        extracted = extract_regular_ad(sub_ad, transaction_type, scraped_at)
        if extracted:
            results.append(extracted)
    return results

def create_clean_listing(extracted: ExtractedData, meta: MetaData, criteria: dbmodels.SearchCriteria, market_string: str, raw_listing_id: int) -> dbmodels.CleanListing:
    return dbmodels.CleanListing(
        id=0, is_active=True, # <-- unused
        criteria_id=criteria.id,
        raw_listing_id=raw_listing_id,
        location_id=meta.location_id,
        external_id=extracted.external_id,
        portal_name=meta.portal_name,
        listing_url=extracted.listing_url,
        title=extracted.title,
        area_m2=extracted.area_m2,
        rooms=extracted.rooms,
        property_type_id=meta.property_type_id,
        market=market_string,
        transaction_type=meta.transaction_type,
        first_seen_at=extracted.seen_at, # <-- used only when adding a new one
        last_seen_at=extracted.seen_at
    )

def create_price_history(extracted: ExtractedData) -> dbmodels.PriceHistory:
    return dbmodels.PriceHistory(
        id=0, listing_id=0, # unused
        batch_id=BID,
        price_sale_total=extracted.price_sale_total,
        price_sale_per_m2=extracted.price_sale_per_m2,
        price_rent_monthly=extracted.price_rent_monthly,
        seen_at=extracted.seen_at
    )

def clean_batch() -> bool:
    """
        Cleans the collected batch records.  
        Returns int of the processed batch, or -1 on failure?
    """
    batch: dbmodels.BatchData = DB.get_batch(BID)
    if batch is None:
        if DEBUG: print(f"Failed to SELECT the batch with an id: {BID}")
        return False

    criteria: dbmodels.SearchCriteria = DB.get_search_criteria(batch.criteria_id)
    if criteria is None:
        if DEBUG: print(f"Failed to SELECT the criteria with an id: {batch.criteria_id}")
        return False

    raw_data: list[dbmodels.RawListing] = DB.get_raw_listings_by_batch(BID)
    if not raw_data:
        if DEBUG: print(f"Failed to SELECT the raw listings for batch with an id: {BID}")
        return False

    processed_count = 0
    execution_logs: list[dbmodels.CleanExecLog] = []
    for rl in raw_data:
        cleaning_started_at = datetime.datetime.now(datetime.timezone.utc)
        current_status = dbmodels.LogStatus.SUCCESS
        error_msg = None

        try:
            metadata: MetaData = get_listing_metadata(rl, criteria)
            market = get_market_type(rl.raw_content, rl.scraping_url)
            extracted_data: list[ExtractedData] = []
            if DEBUG: print(f"Extracting data from raw listing: {rl.id}")
            if is_regular_ad(rl.raw_content):
                extracted_data.append(extract_regular_ad(rl.raw_content, metadata.transaction_type, rl.scraped_at)) # Single element
            else:
                extracted_data = extract_investment(rl.raw_content, metadata.transaction_type, rl.scraped_at) # Many

            for ed in extracted_data:
                clean_listing: dbmodels.CleanListing = create_clean_listing(ed, metadata, criteria, market, rl.id)
                price_history: dbmodels.PriceHistory = create_price_history(ed)
                new_listing = DB.get_clean_listing_id(ed.external_id, metadata.portal_name)
                if new_listing is not None:
                    DB.update_clean_listing(new_listing, rl.id, rl.scraped_at, price_history)
                else:
                    new_listing = DB.insert_new_clean_listing(clean_listing, price_history)

                if new_listing:
                    if DEBUG: print(f"Listing processsed: {ed.external_id}")
                    processed_count += 1
        except Exception as e:
            current_status = dbmodels.LogStatus.FAILED
            error_msg = str(e)
            if DEBUG: print(f"Error processing raw_id {rl.id}: {e}")

        execution_logs.append(dbmodels.CleanExecLog(
            id=0, target_display_name = "", # unused
            job_name="cleaner.py",
            raw_listing_id=rl.id,
            status=current_status,
            error_message=error_msg,
            started_at=cleaning_started_at,
            finished_at=datetime.datetime.now(datetime.timezone.utc)
        ))
    DB.insert_clean_execution_logs_bulk(execution_logs)
    return processed_count > 0

def main():
    """
        Starts the cleaner for the given batch id.  
        Returns int of the processed batch, or -1 if (when)?
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
    global BID, DEBUG
    BID = args.batch_id
    DEBUG = args.debug

    if DEBUG: print(f"Cleaning begins for batch_id: {BID}")
    success = clean_batch()
    if success:
        if DEBUG: print(f"Cleaning for batch_id: {BID} successful")
        print(BID) # Input for analyzer.py
        sys.exit(0)
    else:
        if DEBUG: print(f"Cleaning for batch_id: {BID} failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
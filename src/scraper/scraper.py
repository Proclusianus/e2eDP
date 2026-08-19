import argparse
import sys
import os
import time
import json
import socket
import random
import traceback
import datetime
from dataclasses import dataclass, field


from playwright.sync_api import sync_playwright, Page
from playwright_stealth import Stealth


import database.models as dbmodels
from database.db_manager import DBManager

##############
# DATA TYPES #
##############
@dataclass(frozen=True)
class UrlData:
    target_url_base: str
    pages_amount: int

@dataclass(frozen=True)
class ScrapedResultData:
    to_scrap_amount: int
    scrapped_successfuly: int

####################
# GLOBAL VARIABLES #
####################
DB = DBManager()
CID = 0
DEBUG = False
PORTAL = 'otodom'

#############
# FUNCTIONS #
#############
def get_proxy_url() -> str:
    if os.getenv("RUNNING_IN_DOCKER"):
        hostname = "vpn-gateway"
        port = "8888"
        try:
            container_ip = socket.gethostbyname(hostname)
            return f"http://{container_ip}:{port}"
        except socket.gaierror:
            return "vpn-gateway:8888"
    else:
        return"http://127.0.0.1:55502"

def get_website_location_string(location: str, take_fallback: bool, page: Page) -> str | None:
    """Returns the location string used by the website's urls"""
    try:
        if DEBUG: print(f"Obtaining url location string for: {location}")

        # COOKIES
        cookie_selector = "#onetrust-accept-btn-handler"
        try:
            page.wait_for_selector(cookie_selector, timeout=7000)
            page.click(cookie_selector)
            if DEBUG: print(f"Cookies accepted for: {location}")
            time.sleep(1)
        except:
            pass

        # Input location
        input_selector = 'input[data-cy="search.form.location.button"]'
        page.wait_for_selector(input_selector, timeout=10000)
        loc_input = page.locator(input_selector)
        loc_input.click(force=True)
        loc_input.fill("")
        time.sleep(1.0) # To make sure none of the first written letters are lost
        loc_input.type(location.replace('/', ' '), delay=100) # 100ms, pretend to be a human
        if DEBUG: print(f"Typed into location input for: {location}")
        
        # Get location url string from suggestion list
        item_selector = 'div[role="treeitem"]'
        suggestions_list = page.locator('#location-search-controls')
        suggestions_list.wait_for(state="visible", timeout=10000)
        page.wait_for_function(
            f"""() => {{
                const items = document.querySelectorAll('{item_selector}');
                return items.length > 0 && items[0].innerText.length > 0;
            }}""",
            timeout=10000
        )
        
        # Select the one equal to the lowest location string (rightmost word)
        # If not found select the first
        suggestions = page.locator(item_selector).all()
        if DEBUG: print(f"Locations list obtained for: {location}")
        target_loc_url = None
        city_name_target = location.split('/')[-1].strip().lower()
        for suggestion in suggestions:
            label = suggestion.get_attribute("aria-label")
            location_url = suggestion.get_attribute("id")
            if label and city_name_target == label.lower():
                target_loc_url = location_url.split(',')[0] if location_url else None
                break

        if DEBUG: page.screenshot(path="debug_view2.png")
        if target_loc_url:
            if DEBUG: print(f"Location found for: {location} - {target_loc_url}; Added to location mappings")
            DB.create_location_mapping(DB.get_location_by_name(location).location_id, PORTAL, target_loc_url)
            return target_loc_url
        if len(suggestions) > 0 and take_fallback:
            fallback_id = suggestions[0].get_attribute("id").split(',')[0]
            if fallback_id:
                if DEBUG: print(f"No fitting location found for: {location} - using fallback: {fallback_id}")
                DB.create_location_mapping(DB.get_location_by_name(location).location_id, PORTAL, fallback_id)
                return fallback_id
        if DEBUG: print(f"No locations found at all for: {location}")
        return None
    except Exception as e:
        if DEBUG: 
            print(f"Failure while getting url location string for: '{location}': {e}")
            page.screenshot(path="debug_view3.png")
        return None

def test_obtained_string(loc_string: str, page: Page) -> bool:
    test_url = f"https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/{loc_string}"
    if DEBUG: print(f"testurl is {test_url}")
    try:
        response = page.goto(test_url, wait_until="domcontentloaded", timeout=20000)
        if response.status == 404:
            raise Exception("Status 404")

        # Check for redirects
        if "cala-polska" in page.url and "cala-polska" not in loc_string:
            page.screenshot(path="redirect1.png")
            raise Exception("Redirected 1")
        if page.url.endswith(".pl/"):
            page.screenshot(path="redirect2.png")
            raise Exception("Redirected 2")
        
        if DEBUG: print("The DB location string works; skipping scraping location string")
        return True
    except Exception as e:
        if DEBUG: print(f"The DB location string failed; removing location mapping & scraping location string : {e}")
        return False

def attempt_to_get_website_location_string(location: str, max_retries: int, page: Page) -> str | None:
    # Check if we don't already have the locating string
    location_id = DB.get_location_by_name(location).location_id
    mapped_loc_string = DB.get_location_mapping_external_name(PORTAL, location_id)
    if mapped_loc_string:
        if DEBUG: print(f"Found location string in DB: {mapped_loc_string}")
        if test_obtained_string(mapped_loc_string, page):
            return mapped_loc_string
        else:
            DB.remove_location_mapping(location_id, PORTAL, mapped_loc_string)

    # First attempt to connect to the website...
    for attempt in range(1, max_retries + 1):  
        try:
            page.goto("https://www.otodom.pl/pl/wyniki/sprzedaz/mieszkanie/cala-polska", wait_until="domcontentloaded", timeout=60000)
            break
        except Exception as e:
            if attempt != max_retries:
                wait_time = min(attempt * 2, 10)
                if DEBUG: print(f"Failed to connect to the website: {e}\nRetrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                return None

    # Then attempt to obtain the location string...
    location_string = None
    for attempt in range(1, max_retries + 1):
        if DEBUG: print(f"Attempt {attempt}/{max_retries} to resolve location: {location}")

        # During the final and n-1 attempt reload the page and accept fallback if no target found
        if attempt == max_retries or attempt == max_retries - 1:
            page.reload(wait_until="domcontentloaded")
            location_string = get_website_location_string(location, True, page)
        else:
            location_string = get_website_location_string(location, False, page)
        if location_string:
            break

        wait_time = min(attempt * 2, 10)
        if DEBUG: print(f"Failed to get location string. Retrying in {wait_time}s...")
        time.sleep(wait_time)

    if location_string is not None:
        return location_string
    else:
        DB.log_system_error(
            error_source=dbmodels.ErrorSources.SCRAPER,
            module_name="attempt_to_get_website_location_string",
            error_message=f"Persistent failure to resolve location: {location}",
            context_data={"criteria_id": CID, "location": location}
        )
        return None

def get_target_url(url_location_string: str, criteria: dbmodels.SearchCriteria) -> list[str]:
    """Returns a list of URL(s) to be scraped for a given location"""
    result: list[str] = []
    c = criteria
    transaction_map = {"sale": "sprzedaz", "rent": "wynajem"}
    property_map = {"Apartment": "mieszkanie", "House": "dom"}
    market_map = {'primary': ",rynek-pierwotny", 'secondary': ",rynek-wtorny"} # 'both' doesn't modify the url
    room_count_map = {'1': 'ONE', '2': 'TWO', '3': 'THREE', '4': 'FOUR', '5': 'FIVE', '6+': 'SIX_OR_MORE'}
    room_count_joiner = '%2C'

    url_array = ["https://www.otodom.pl/pl/wyniki/"]
    url_array.append(f"{transaction_map[c.transaction_type]}/")
    url_array.append("") # Added later in the loop... (property_type,market_type/)
    url_array.append(f"{url_location_string}?limit=72&ownerTypeSingleSelect=ALL&")
    if c.min_price != 0.0: url_array.append(f"priceMin={int(c.min_price)}&")
    if c.max_price is not None: url_array.append(f"priceMax={int(c.max_price)}&")
    if c.min_area != 0.0: url_array.append(f"areaMin={int(c.min_area)}&")
    if c.max_area is not None: url_array.append(f"areaMax={int(c.max_area)}&")
    if c.rooms:
        url_array.append("roomsNumber=[")
        is_first = True
        for room in c.rooms:
            if is_first:
                is_first = False
            else:
                url_array.append(room_count_joiner)
            url_array.append(room_count_map[room.room_label])
        url_array.append("]&")
    url_array.append("by=DEFAULT&direction=DESC&")

    for prop_type in c.property_types:
        if c.market_type != 'both':
            url_array[2] = f"{property_map[prop_type.type_name]}{market_map[c.market_type]}/"
        else:
            url_array[2] = f"{property_map[prop_type.type_name]}/"
        result.append(''.join(url_array))

    if DEBUG: print(f"URL(s) constructed for: {url_location_string} - criteria_id: {c.id} - property_types: {c.property_types}: {result}")
    return result

def get_pages_amount(page_data: dict) -> int:
    """Returns the amount of pages for the current url query"""
    try:
        pagination = page_data.get('props', {}) \
                             .get('pageProps', {}) \
                             .get('data', {}) \
                             .get('searchAds', {}) \
                             .get('pagination', {})
        total_pages = pagination.get('totalPages', 1)
        return max(int(total_pages), 1)
    except (ValueError, TypeError, AttributeError):
        if DEBUG: print("Error during finding pages amount!")
        return 1

def is_real_listing(item: dict) -> bool:
    """
        Returns True if the listing is an actual unique offer.  
        False if a technical duplicate.
    """
    href = item.get('href', '')
    ext_id = str(item.get('id', ''))
    created_at = item.get('createdAtFirst', '')
    #images = item.get('images', [])
    if len(ext_id) > 10:
        return False
    if 'hpr/' in href:
        return False
    if "1999" in created_at:
        return False
    #if not images or len(images) == 0:
    #    return False

    return True

def create_raw_listings_from_page(page_data: dict, batch_id: int, criteria_id: int, url: str, loc_url: str) -> ScrapedResultData:
    """Returns the amount of successfuly saved listings"""
    try:
        search_data = page_data.get('props', {}).get('pageProps', {}).get('data', {}).get('searchAds', {})
        items = search_data.get('items', [])
    except Exception as e:
        if DEBUG: print(f"Failed to find: props.pageProps.data.searchAds.items in JSON content: {e}")
        return ScrapedResultData(0, 0)
    if not items:
        return ScrapedResultData(0, 0)

    total_count = 0
    success_count = 0
    for item in items:
        if not is_real_listing(item):
            if DEBUG: print(f"Skipped technical duplicate: {item.get('id')}")
            continue
        total_count += 1
        try:
            ext_id = str(item.get('id', 'unknown'))
            raw_listing = dbmodels.RawListing(
                id=0, scraped_at=None, # unused now
                criteria_id=criteria_id, batch_id=batch_id,
                portal_name=PORTAL,
                external_id=ext_id,
                scraping_url=url,
                location_url=loc_url,
                raw_content=item,
                http_status=200
            )
            if DB.insert_raw_listing(raw_listing) != -1:
                success_count += 1
        except Exception as e:
            DB.log_system_error(
                error_source=dbmodels.ErrorSources.SCRAPER,
                module_name='create_raw_listings_from_page_loop',
                error_message=f"Error processing item (external_id={item.get('id')}): {e}",
                stack_trace=traceback.format_exc(),
                context_data={"batch_id": batch_id, "criteria_id": criteria_id, "url": url}
            )
            continue
    return ScrapedResultData(to_scrap_amount=total_count, scrapped_successfuly=success_count)

def scrape_for_id() -> int:
    """
        Main scrapping process.  
        Returns int of the created batch, or -1 if the batch failed (FAILED) or collected no data (EMPTY).
    """
    criteria: dbmodels.SearchCriteria = DB.get_search_criteria(CID)
    if not criteria:
        if DEBUG: print(f"Failed to obtain the SC for id: {CID}")
        return -1

    batch_id: int = DB.start_batch(CID)
    if batch_id == -1:
        if DEBUG: print(f"Failed to create a batch for id: {CID}")
        return -1

    scraping_success_data: list[ScrapedResultData] = []
    execution_logs: list[dbmodels.RawExecLog] = []

    max_pages_per_url: dbmodels.SystemSettingValues = DB.get_system_setting_values('max_pages_per_url')
    if DEBUG: print(f"max_pages_per_url setting_value={max_pages_per_url.setting_value}, is_enabled {max_pages_per_url.is_enabled}")

    proxy_url: str = get_proxy_url()
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True, proxy={"server": proxy_url})
        context = browser.new_context(viewport={'width': 1920, 'height': 1080}, locale='pl-PL', timezone_id='Europe/Warsaw',
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        for loc in criteria.cities:
            location_string = attempt_to_get_website_location_string(loc, 5, page)
            if location_string is None:
                if DEBUG: print(f"Skipping location {loc} due to resolution failure.")
                continue
            target_url = get_target_url(location_string, criteria)
            for t_url in target_url: # might be 1 or 2 due to the website's handling of property type
                page_number = 1
                pages_amount = 1
                while page_number <= pages_amount:
                    final_url = f"{t_url}page={page_number}"
                    scraping_started_at = datetime.datetime.now(datetime.timezone.utc)
                    current_status = dbmodels.LogStatus.SUCCESS
                    error_msg = None
                    try:
                        page.goto(final_url, wait_until="domcontentloaded", timeout=15000)
                        time.sleep(random.uniform(1, 4))
                        page.mouse.wheel(0, 500)
                        time.sleep(random.uniform(1, 2))
                    except Exception as e:
                        if DEBUG: print(f"Entering page number {page_number} failed: {e}")
                        current_status = dbmodels.LogStatus.FAILED
                        error_msg = str(e)
                        DB.log_system_error(
                            error_source=dbmodels.ErrorSources.SCRAPER,
                            module_name='scrape_for_id;page.goto',
                            error_message=f"Failed to load page {page_number}: {str(e)}",
                            stack_trace=traceback.format_exc(),
                            context_data={"url": final_url}
                        )
                        time.sleep(random.uniform(2, 4))
                        continue

                    raw_json = page.locator("script#__NEXT_DATA__").inner_text()
                    page_data = json.loads(raw_json)
                    if page_number == 1:
                        pages_amount = get_pages_amount(page_data)
                        if DEBUG: print(f"Counted {pages_amount} pages for {final_url}")
                        if max_pages_per_url is not None and max_pages_per_url.is_enabled:
                            pages_amount = min(pages_amount, max_pages_per_url.setting_value)
                            if DEBUG: print(f"Limited amount of pages to {max_pages_per_url.setting_value}")

                    scraping_result = create_raw_listings_from_page(page_data, batch_id, CID, final_url, location_string)
                    if scraping_result.scrapped_successfuly != scraping_result.to_scrap_amount:
                        current_status = dbmodels.LogStatus.WARNING
                        error_msg = f"Scraped only {scraping_result.scrapped_successfuly} offers out of {scraping_result.to_scrap_amount}"
                    scraping_success_data.append(scraping_result)

                    page_number += 1
                    execution_logs.append(dbmodels.RawExecLog(
                        id=0, target_display_name = "", # unused
                        job_name="scraper.py",
                        batch_id=batch_id,
                        status=current_status,
                        error_message=error_msg,
                        started_at=scraping_started_at,
                        finished_at=datetime.datetime.now(datetime.timezone.utc)
                    ))

    successful = 0
    count = 0
    for e in scraping_success_data:
        successful += e.scrapped_successfuly
        count += e.to_scrap_amount
    if successful == 0:
        DB.set_batch_status(batch_id, dbmodels.BatchStatus.EMPTY)
        return -1 # No data - no cleaning/analyzing
    elif successful < count:
        DB.set_batch_status(batch_id, dbmodels.BatchStatus.PARTIAL_RUNNING)
        return batch_id # Set to PARTIAL on success in clean/analysis
    else:
        return batch_id # All good, continue

def main() -> int:
    """
        Starts the main scrapping process.  
        Prints id of the created batch, or nothing if the batch failed (FAILED) or collected no data (EMPTY).
    """
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "criteria_id", 
        type=int, 
        help="ID of the search criteria to process from config.search_criteria"
    )
    parser.add_argument(
        "-d", "--debug", 
        action='store_true', 
        help="Prints debug statements"
    )
    args = parser.parse_args()
    global CID, DEBUG
    CID = args.criteria_id
    DEBUG = args.debug

    if DEBUG: print(f"Scraping begins for criteria_id: {CID}")
    new_batch_id = scrape_for_id()
    if new_batch_id != -1:
        if DEBUG: print(f"Scraping for criteria_id: {CID} successful")
        print(new_batch_id) # Input for cleaner.py
        sys.exit(0)
    else:
        if DEBUG: print(f"Scraping for criteria_id: {CID} failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
    # Gotta add execution_log support here
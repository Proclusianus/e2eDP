from datetime import datetime, timezone, time
from dataclasses import replace


import pytest
from unittest.mock import MagicMock
from unittest.mock import patch


from src.processing.analyzer import do_PRICE_DROP
from src.processing.analyzer import do_BELOW_THRESHOLD
from src.processing.analyzer import do_BELOW_AVG_PERCENT, LocationMetrics
from src.ui.config.config_batch import validate_criteria_form
from src.ui.config.config_notif import validate_gnr_form, ValidationData
import src.database.models as dbmodels

#############
# MOCK DATA #
#############
@pytest.fixture
def sample_clean_listing_sale():
    return dbmodels.CleanListing(
        id=1,
        criteria_id=10,
        raw_listing_id=100,
        location_id=1,
        external_id="OT123",
        portal_name="Otodom",
        listing_url="http://url.com",
        title="Test Sale",
        area_m2=50.0,
        rooms=2,
        property_type_id=1,
        market="secondary",
        transaction_type="sale",
        first_seen_at=datetime.now(timezone.utc),
        last_seen_at=datetime.now(timezone.utc),
        is_active=True
    )

@pytest.fixture
def sample_clean_listing_rent(sample_clean_listing_sale):
    return replace(sample_clean_listing_sale, transaction_type="rent")

@pytest.fixture
def sample_location_stats():
    return {
        1: LocationMetrics(
            location_id=1,
            avg_sale_pm2=20000.0,
            median_sale_pm2=19500.0,
            std_dev_sale_pm2=1000.0,
            count_sale=10,
            avg_rent_total=3000.0,
            median_rent_total=2900.0,
            std_dev_rent_total=200.0,
            count_rent=5
        )
    }

@pytest.fixture
def mock_db():
    db = MagicMock()
    db.does_this_search_criteria_name_exist.return_value = False
    db.does_global_notification_rule_name_exist.return_value = False
    return db

@pytest.fixture
def valid_analysis_input():
    return [
        dbmodels.AnomalyAnalysis(
            id=1, 
            code='PRICE_DROP', 
            name_pl='Wykrywanie obniżek', 
            name_en='Price Drop', 
            description_pl=None, 
            description_en='Detects price drops', 
            takes_parameter=False
        ),
        dbmodels.AnomalyAnalysis(
            id=2, 
            code='BELOW_THRESHOLD', 
            name_pl='Poniżej progu', 
            name_en='Below Threshold', 
            description_pl=None, 
            description_en='Price below X', 
            takes_parameter=True
        )
    ]

#########
# TESTS #
#########
### do_PRICE_DROP ###
def test_do_price_drop_sale_success(sample_clean_listing_sale):
    histories = {
        1: [
            dbmodels.PriceHistory(id=2, listing_id=1, batch_id=2, price_sale_total=80000.0, price_sale_per_m2=1600, price_rent_monthly=None, seen_at=datetime.now()),
            dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=100000.0, price_sale_per_m2=2000, price_rent_monthly=None, seen_at=datetime.now())
        ]
    }
    result = do_PRICE_DROP(sample_clean_listing_sale, histories)
    
    assert result is not None
    assert result['new_price'] == 80000.0
    assert result['drop_abs'] == 20000.0
    assert result['drop_rel_percent'] == 20.0

def test_do_price_drop_rent_success(sample_clean_listing_rent):
    histories = {
        1: [
            dbmodels.PriceHistory(id=2, listing_id=1, batch_id=2, price_sale_total=None, price_sale_per_m2=None, price_rent_monthly=2500.0, seen_at=datetime.now()),
            dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=None, price_sale_per_m2=None, price_rent_monthly=3000.0, seen_at=datetime.now())
        ]
    }
    result = do_PRICE_DROP(sample_clean_listing_rent, histories)
    
    assert result is not None
    assert result['drop_abs'] == 500.0

def test_do_price_drop_no_change_returns_none(sample_clean_listing_sale):
    histories = {
        1: [
            dbmodels.PriceHistory(id=2, listing_id=1, batch_id=2, price_sale_total=500000.0, price_sale_per_m2=10000, price_rent_monthly=None, seen_at=datetime.now()),
            dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=500000.0, price_sale_per_m2=10000, price_rent_monthly=None, seen_at=datetime.now())
        ]
    }
    result = do_PRICE_DROP(sample_clean_listing_sale, histories)
    assert result is None

def test_do_price_drop_increase_ignored(sample_clean_listing_sale):
    histories = {
        1: [
            dbmodels.PriceHistory(id=2, listing_id=1, batch_id=2, price_sale_total=120000.0, price_sale_per_m2=2400, price_rent_monthly=None, seen_at=datetime.now()),
            dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=100000.0, price_sale_per_m2=2000, price_rent_monthly=None, seen_at=datetime.now())
        ]
    }
    result = do_PRICE_DROP(sample_clean_listing_sale, histories)
    assert result is None

def test_do_price_drop_insufficient_history(sample_clean_listing_sale):
    histories = {
        1: [
            dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=100000.0, price_sale_per_m2=2000, price_rent_monthly=None, seen_at=datetime.now())
        ]
    }
    result = do_PRICE_DROP(sample_clean_listing_sale, histories)
    assert result is None

### do_BELOW_THRESHOLD ###
def test_do_below_threshold_sale_success(sample_clean_listing_sale):
    threshold = 500000.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=450000.0, price_sale_per_m2=9000, price_rent_monthly=None, seen_at=datetime.now())]
    }
    result = do_BELOW_THRESHOLD(sample_clean_listing_sale, histories, threshold)
    
    assert result is not None
    assert result['current_price'] == 450000.0
    assert result['difference_abs'] == 50000.0

def test_do_below_threshold_rent_success(sample_clean_listing_rent):
    threshold = 3000.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=None, price_sale_per_m2=None, price_rent_monthly=2800.0, seen_at=datetime.now())]
    }
    result = do_BELOW_THRESHOLD(sample_clean_listing_rent, histories, threshold)
    
    assert result is not None
    assert result['current_price'] == 2800.0
    assert result['difference_abs'] == 200.0

def test_do_below_threshold_fail_above(sample_clean_listing_sale):
    threshold = 500000.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=600000.0, price_sale_per_m2=12000, price_rent_monthly=None, seen_at=datetime.now())]
    }
    result = do_BELOW_THRESHOLD(sample_clean_listing_sale, histories, threshold)
    assert result is None

def test_do_below_threshold_exact_match(sample_clean_listing_sale):
    threshold = 500000.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=500000.0, price_sale_per_m2=10000, price_rent_monthly=None, seen_at=datetime.now())]
    }
    result = do_BELOW_THRESHOLD(sample_clean_listing_sale, histories, threshold)
    assert result is None

def test_do_below_threshold_missing_price(sample_clean_listing_sale):
    threshold = 500000.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=None, price_sale_per_m2=None, price_rent_monthly=None, seen_at=datetime.now())]
    }
    result = do_BELOW_THRESHOLD(sample_clean_listing_sale, histories, threshold)
    assert result is None

### do_BELOW_AVG_PERCENT ###
def test_do_below_avg_sale_success(sample_clean_listing_sale, sample_location_stats):
    threshold = 20.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=750000.0, price_sale_per_m2=15000.0, price_rent_monthly=None, seen_at=datetime.now())]
    }
    result = do_BELOW_AVG_PERCENT(sample_clean_listing_sale, histories, sample_location_stats, threshold)
    
    assert result is not None
    assert result['diff_percent'] == 25.0
    assert result['location_avg_price'] == 20000.0

def test_do_below_avg_rent_success(sample_clean_listing_rent, sample_location_stats):
    threshold = 10.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=None, price_sale_per_m2=None, price_rent_monthly=2400.0, seen_at=datetime.now())]
    }
    result = do_BELOW_AVG_PERCENT(sample_clean_listing_rent, histories, sample_location_stats, threshold)
    
    assert result is not None
    assert result['diff_percent'] == 20.0

def test_do_below_avg_fail_not_enough_discount(sample_clean_listing_sale, sample_location_stats):
    threshold = 10.0
    histories = {
        1: [dbmodels.PriceHistory(id=1, listing_id=1, batch_id=1, price_sale_total=950000.0, price_sale_per_m2=19000.0, price_rent_monthly=None, seen_at=datetime.now())]
    }
    result = do_BELOW_AVG_PERCENT(sample_clean_listing_sale, histories, sample_location_stats, threshold)
    assert result is None

### validate_criteria_form ###
def test_validate_criteria_form_success(mock_db, valid_analysis_input):
    mock_session = {
        f"cb_ano_1": True,
        f"cb_ano_2": True,
        f"val_ano_2": 500000.0
    }
    with patch('streamlit.session_state', mock_session):
        result = validate_criteria_form(
            db=mock_db,
            initial_name="",
            target_name="Okazje Kraków",
            cities=["Kraków"],
            price_min=1000.0,
            price_max=5000.0,
            area_min=30.0,
            area_max=50.0,
            schedule_input="08:00, 15:30",
            batch_analyses=[],
            anomaly_analyses=valid_analysis_input
        )
    
    assert len(result.error_msgs) == 0
    assert len(result.anomaly_an) == 2
    assert time(8, 0) in result.hours
    assert time(15, 30) in result.hours

def test_validate_criteria_form_invalid_price_range(mock_db):
    result = validate_criteria_form(
        db=mock_db, initial_name="", target_name="Test", cities=["X"],
        price_min=500.0, price_max=100.0,
        area_min=10.0, area_max=20.0, schedule_input="12:00",
        batch_analyses=[], anomaly_analyses=[]
    )
    
    assert any("price" in msg.lower() for msg in result.error_msgs)

def test_validate_criteria_form_duplicate_name(mock_db):
    mock_db.does_this_search_criteria_name_exist.return_value = True
    result = validate_criteria_form(
        db=mock_db, initial_name="Stara Nazwa", target_name="Nowa Nazwa", 
        cities=["X"], price_min=0, price_max=10, area_min=0, area_max=10,
        schedule_input="10:00", batch_analyses=[], anomaly_analyses=[]
    )
    
    assert any("already exists" in msg for msg in result.error_msgs)

def test_validate_criteria_form_bad_schedule_format(mock_db):
    result = validate_criteria_form(
        db=mock_db, initial_name="", target_name="Test", cities=["X"],
        price_min=0, price_max=10, area_min=0, area_max=10,
        schedule_input="25:00",
        batch_analyses=[], anomaly_analyses=[]
    )
    
    assert any("Invalid time format" in msg for msg in result.error_msgs)

def test_validate_criteria_form_missing_analysis_param(mock_db, valid_analysis_input):
    mock_session = {f"cb_ano_2": True}
    with patch('streamlit.session_state', mock_session):
        result = validate_criteria_form(
            db=mock_db, initial_name="", target_name="Test", cities=["X"],
            price_min=0, price_max=10, area_min=0, area_max=10,
            schedule_input="10:00", batch_analyses=[], anomaly_analyses=valid_analysis_input
        )
    
    assert any("requires a parameter value" in msg for msg in result.error_msgs)

### validate_gnr_form ###
def test_validate_gnr_form_all_cities_success(mock_db, valid_analysis_input):
    val_data = ValidationData(
        current_name="Global Radar",
        initial_name="",
        clean_desc=None,
        all_cities=[],
        selected_anomaly_analyses=[dbmodels.ActivatedAnalysis(1, 0.0)]
    )
    result = validate_gnr_form(
        db=mock_db,
        val_data=val_data,
        search_all=True,
        schedule_input="12:00",
        anomaly_analyses=valid_analysis_input
    )
    
    assert len(result.error_msgs) == 0

def test_validate_gnr_form_specific_cities_missing_error(mock_db):
    val_data = ValidationData(
        current_name="Specific Radar",
        initial_name="",
        clean_desc=None,
        all_cities=[],
        selected_anomaly_analyses=[]
    )
    result = validate_gnr_form(
        db=mock_db,
        val_data=val_data,
        search_all=False,
        schedule_input="12:00",
        anomaly_analyses=[]
    )
    
    assert any("At least one location" in msg for msg in result.error_msgs)

def test_validate_gnr_form_duplicate_name(mock_db):
    mock_db.does_global_notification_rule_name_exist.return_value = True
    val_data = ValidationData(
        current_name="Istniejąca Nazwa",
        initial_name="Stara",
        clean_desc=None,
        all_cities=[],
        selected_anomaly_analyses=[]
    )
    result = validate_gnr_form(
        db=mock_db,
        val_data=val_data,
        search_all=True,
        schedule_input="10:00",
        anomaly_analyses=[]
    )
    
    assert any("already exists" in msg for msg in result.error_msgs)
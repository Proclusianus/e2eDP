import io
import datetime
import pandas as pd
from dataclasses import dataclass
from pathlib import Path


from fpdf import FPDF
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import numpy as np
from PIL import Image


import database.models as dbmodels
from database.db_manager import DBManager

##############
# DATA TYPES #
##############
@dataclass(frozen=True)
class ReportData():
    batch: dbmodels.BatchData
    criteria: dbmodels.SearchCriteria
    loc_lookup: dict[int, str]
    clean_listings: list[dbmodels.CleanListing]
    clean_listings_prices: dict[int, list[dbmodels.PriceHistory]]
    metrics_SUPPLY_VOLUME: pd.DataFrame | None
    metrics_PRICE_DYNAMICS: pd.DataFrame | None
    metrics_DISTRIBUTION_CALC: pd.DataFrame | None
    anomalies_PRICE_DROP: list[dbmodels.DetectedAnomaly]
    anomalies_BELOW_THRESHOLD: list[dbmodels.DetectedAnomaly]
    anomalies_BELOW_AVG_PERCENT: list[dbmodels.DetectedAnomaly]

##############
# MAIN CLASS #
##############
class PDFReporter:
    def __init__(self):
        self.db = DBManager()
        self.pdf = FPDF()
        self.pdf.set_auto_page_break(auto=True, margin=15)
        self.HUMAN_LABELS = {
            "old_price": "Previous Price",
            "new_price": "New Price",
            "drop_abs": "Price Drop",
            "drop_rel_percent": "Drop (%)",

            "current_price": "Listing Price",
            "threshold_value": "Limit Set",
            "difference_abs": "Difference",
            
            "location_avg_price": "Market Avg.",
            "diff_percent": "Below Avg (%)"
        }
        self.batch_analyses_definitions: list[dbmodels.BatchAnalysis] = self.db.get_batch_analysis_definitions()
        self.anomaly_analyses_definitions: list[dbmodels.AnomalyAnalysis] = self.db.get_anomaly_analysis_definitions()

        # Load font
        BASE_DIR = Path(__file__).resolve().parent.parent # to src/
        FONT_DIR = BASE_DIR / "assets" / "fonts"
        self.pdf.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.pdf.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.pdf.add_font("DejaVu", "I", str(FONT_DIR / "DejaVuSans-Oblique.ttf"))
        self.pdf.set_font("DejaVu", size=12)

    def _get_report_data(self, batch_id: int) -> ReportData:
        batch = self.db.get_batch(batch_id)
        if not batch:
            raise ValueError(f"Batch {batch_id} not found in database")

        criteria = self.db.get_search_criteria(batch.criteria_id)
        if not criteria: # just in case - somebody might delete the criteria
            raise ValueError(f"Criteria {batch.criteria_id} not found in database")

        loc_lookup = self.db.get_location_lookup()
        if not loc_lookup:
            raise ValueError(f"Failed to obtain location lookup for batch_id={batch_id}")

        clean_listings = self.db.get_clean_listings_by_batch(batch_id)
        if not clean_listings:
            raise ValueError(f"Clean listings for batch_id={batch_id}: failed to obtain from DB")

        clean_listings_prices = self.db.get_price_histories_for_batch(batch_id)
        if not clean_listings_prices:
            raise ValueError(f"Price history for batch_id={batch_id}: failed to obtain from DB")

        metrics_SUPPLY_VOLUME = self.db.get_supply_volume_history(criteria.id)
        metrics_PRICE_DYNAMICS = self.db.get_price_dynamics_history(criteria.id)
        metrics_DISTRIBUTION_CALC = self.db.get_price_distribution_latest(criteria.id)

        anomalies_PRICE_DROP = self.db.get_anomalies_by_type(batch_id, 'PRICE_DROP')
        anomalies_BELOW_THRESHOLD = self.db.get_anomalies_by_type(batch_id, 'BELOW_THRESHOLD')
        anomalies_BELOW_AVG_PERCENT = self.db.get_anomalies_by_type(batch_id, 'BELOW_AVG_PERCENT')

        return ReportData(
            batch=batch, criteria=criteria, loc_lookup=loc_lookup,
            clean_listings=clean_listings, clean_listings_prices=clean_listings_prices,
            metrics_DISTRIBUTION_CALC=metrics_DISTRIBUTION_CALC,
            metrics_PRICE_DYNAMICS=metrics_PRICE_DYNAMICS,
            metrics_SUPPLY_VOLUME=metrics_SUPPLY_VOLUME,
            anomalies_PRICE_DROP=anomalies_PRICE_DROP,
            anomalies_BELOW_THRESHOLD=anomalies_BELOW_THRESHOLD,
            anomalies_BELOW_AVG_PERCENT=anomalies_BELOW_AVG_PERCENT
        )

    def _add_header(self, target_name: str, batch_id: int):
        self.pdf.set_font("DejaVu", 'B', 18)
        self.pdf.cell(0, 10, f"Real Estate Analysis Report", align='C', new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_font("DejaVu", '', 12)
        self.pdf.cell(0, 10, f"Target: {target_name} | Batch ID: {batch_id}", align='C', new_x="LMARGIN", new_y="NEXT")
        self.pdf.cell(0, 10, f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}", align='C', new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(10)

    def _add_criteria_info(self, criteria: dbmodels.SearchCriteria):
        self.pdf.set_font("DejaVu", 'B', 14)
        self.pdf.set_fill_color(240, 240, 240)
        self.pdf.cell(0, 10, f"Search Criteria: {criteria.target_name}", fill=True, new_x="LMARGIN", new_y="NEXT", border='B')
        
        self.pdf.ln(2)
        self.pdf.set_font("DejaVu", 'I', 10)
        desc = criteria.description if criteria.description else "No description provided."
        self.pdf.multi_cell(0, 7, f"Notes: {desc}", new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(2)

        self.pdf.set_font("DejaVu", 'B', 11)
        self.pdf.cell(0, 8, "Market Filters:", new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_font("DejaVu", '', 10)
    
        self.pdf.cell(0, 7, f"• Transaction: {criteria.transaction_type.upper()} | Market: {criteria.market_type.upper()}", new_x="LMARGIN", new_y="NEXT")
        price_text = f"• Price Range: {criteria.min_price:,.0f} - {criteria.max_price:,.0f} PLN"
        area_text = f"Area Range: {criteria.min_area} - {criteria.max_area} m²"
        self.pdf.cell(0, 7, f"{price_text} | {area_text}", new_x="LMARGIN", new_y="NEXT")

        self.pdf.ln(2)
        self.pdf.set_font("DejaVu", 'B', 11)
        self.pdf.cell(0, 8, "Scope & Requirements:", new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_font("DejaVu", '', 10)

        cities_str = ", ".join(criteria.cities) if criteria.cities else "All Cities"
        self.pdf.multi_cell(0, 7, f"• Target Cities: {cities_str}", new_x="LMARGIN", new_y="NEXT")

        prop_types = ", ".join([p.type_name for p in criteria.property_types])
        rooms = ", ".join([r.room_label for r in criteria.rooms])
        self.pdf.multi_cell(0, 7, f"• Property Types: {prop_types} | Room Counts: {rooms}", new_x="LMARGIN", new_y="NEXT")

        self.pdf.ln(2)
        self.pdf.set_font("DejaVu", 'B', 11)
        self.pdf.cell(0, 8, "Activated Analytics:", new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_font("DejaVu", '', 10)

        batch_an_names = {ba.id: ba.name_en for ba in self.batch_analyses_definitions}
        ba_collected_names = []
        for ba in criteria.batch_analyses:
            ba_collected_names.append(batch_an_names.get(ba.analysis_id, ""))
        self.pdf.cell(0, 7, f"• Batch Trends (Macro): {', '.join(ba_collected_names)}", new_x="LMARGIN", new_y="NEXT")

        anomaly_an_names = {an.id: an.name_en for an in self.anomaly_analyses_definitions}
        an_collected_names = []
        for an in criteria.anomaly_analyses:
            an_collected_names.append(anomaly_an_names.get(an.analysis_id, ""))
        self.pdf.cell(0, 7, f"• Anomaly Checks (Micro): {', '.join(an_collected_names)}", new_x="LMARGIN", new_y="NEXT")

        self.pdf.ln(10)

    def _save_plt_to_buf(self):
        buf = io.BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
        plt.close()
        buf.seek(0)
        return buf

    def _plot_supply_volume(self, df, transaction_type: str):
        plt.figure(figsize=(10, 5))
        allowed_types = []
        if transaction_type in ['sale', 'both']: allowed_types.append('Sale')
        if transaction_type in ['rent', 'both']: allowed_types.append('Rent')

        plot_df = df[df['type'].isin(allowed_types)]
        if plot_df.empty:
            plt.text(0.5, 0.5, "No data for selected transaction type", ha='center')
        else:
            plot_df['time'] = pd.to_datetime(plot_df['time'])
            for city in plot_df['location_name'].unique():
                city_subset = plot_df[plot_df['location_name'] == city]
                
                for t_type in city_subset['type'].unique():
                    final_subset = city_subset[city_subset['type'] == t_type].sort_values('time')
                    plt.plot(
                        final_subset['time'], 
                        final_subset['volume'], 
                        marker='o', 
                        linestyle='-', 
                        label=f"{city} - {t_type}"
                    )
        ax = plt.gca()
        date_fmt = mdates.DateFormatter('%d.%m.%y')
        ax.xaxis.set_major_formatter(date_fmt)
        plt.xticks(rotation=45, fontsize=8)

        max_volume = plot_df['volume'].max() if not plot_df.empty else 10
        plt.ylim(0, max_volume * 1.15)

        plt.title("Total Supply Volume Evolution")
        plt.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), fontsize=8, ncol=3, frameon=False)
        plt.grid(True, alpha=0.3, linestyle='--')
        plt.tight_layout()
        return self._save_plt_to_buf()

    def _plot_price_dynamics(self, df):
        plt.figure(figsize=(10, 6))
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.sort_values('timestamp')

        for city in df['city'].unique():
            subset = df[df['city'] == city]
            # Median
            line, = plt.plot(
                subset['timestamp'], 
                subset['median'], 
                marker='s', 
                linestyle='-', 
                label=f"{city} (Median)",
                linewidth=2
            )
            color = line.get_color()
            # Average
            plt.scatter(
                subset['timestamp'], 
                subset['average'], 
                marker='o', 
                color=color, 
                label=f"{city} (Avg)",
                s=30, # wielkość kropki
                zorder=3 # kropki nad wstęgą
            )
            # Std. dev.
            plt.fill_between(
                subset['timestamp'],
                subset['average'] - subset['stddev'],
                subset['average'] + subset['stddev'],
                color=color,
                alpha=0.15,
                label=f"{city} (1σ)"
            )
        ax = plt.gca()
        date_fmt = mdates.DateFormatter('%d.%m.%y')
        ax.xaxis.set_major_formatter(date_fmt)
        plt.xticks(rotation=45, fontsize=8)
        plt.title("Price Dynamics")
        plt.ylabel("Price (PLN)")
        
        plt.legend(loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=3, fontsize=8, frameon=False)
        plt.grid(True, alpha=0.2, linestyle='--')
        plt.tight_layout()
        
        return self._save_plt_to_buf()

    def _plot_single_city_distribution(self, city_df, city_name):
        plt.figure(figsize=(10, 5))
        
        # Sort the bins
        city_df = city_df.copy()
        city_df['lower_bound'] = city_df['price_range'].str.split('-').str[0].astype(int)
        city_df = city_df.sort_values('lower_bound')

        # Bars
        unique_types = city_df['transaction_type'].unique()
        x = np.arange(len(city_df['price_range'].unique()))
        width = 0.35
        for i, t_type in enumerate(unique_types):
            subset = city_df[city_df['transaction_type'] == t_type]
            offset = (i - len(unique_types)/2 + 0.5) * width
            plt.bar(x + offset, subset['offer_count'], width, label=t_type, alpha=0.8)

        plt.title(f"Market Price Structure: {city_name}")
        plt.xlabel("Price Range (PLN)")
        plt.ylabel("Number of Offers")
        plt.xticks(x, city_df['price_range'].unique(), rotation=45, fontsize=9)
        if len(unique_types) > 1:
            plt.legend()
            
        plt.grid(axis='y', linestyle='--', alpha=0.3)
        plt.tight_layout()
        return self._save_plt_to_buf()

    def _find_plot_height(self, img_buf) -> float:
        img = Image.open(img_buf)
        width, height = img.size
        aspect_ratio = height / width
        rendered_width = 180
        return rendered_width * aspect_ratio

    def _add_metrics_section(self, data: ReportData):
        self.pdf.set_font("DejaVu", 'B', 14)
        self.pdf.cell(0, 10, "Batch Analyses:", new_x="LMARGIN", new_y="NEXT")
        self.pdf.set_font("DejaVu", 'B', 12)

        if data.metrics_SUPPLY_VOLUME is None and data.metrics_PRICE_DYNAMICS is None and data.metrics_DISTRIBUTION_CALC is None:
            self.pdf.cell(0, 10, "None requested.")
            return
        
        if data.metrics_SUPPLY_VOLUME is not None and not data.metrics_SUPPLY_VOLUME.empty:
            img_buf = self._plot_supply_volume(data.metrics_SUPPLY_VOLUME, data.criteria.transaction_type)
            rendered_height = self._find_plot_height(img_buf)
            space_needed = 10 + 2 + rendered_height + 5
            if self.pdf.get_y() + space_needed > (self.pdf.h - 20):
                self.pdf.add_page()

            self.pdf.set_font("DejaVu", 'B', 12)
            self.pdf.cell(0, 10, "Supply Volume Trends", new_x="LMARGIN", new_y="NEXT")
            self.pdf.ln(2)
            img_buf.seek(0)
            self.pdf.image(img_buf, x=15, w=180)
            self.pdf.ln(5)
        if data.metrics_PRICE_DYNAMICS is not None and not data.metrics_PRICE_DYNAMICS.empty:
            img_buf = self._plot_price_dynamics(data.metrics_PRICE_DYNAMICS)
            rendered_height = self._find_plot_height(img_buf)
            space_needed = 10 + 2 + rendered_height + 5
            if self.pdf.get_y() + space_needed > (self.pdf.h - 20):
                self.pdf.add_page()
                
            self.pdf.set_font("DejaVu", 'B', 12)
            self.pdf.cell(0, 10, "Price Evolution Over Time", new_x="LMARGIN", new_y="NEXT")
            self.pdf.ln(2)
            img_buf.seek(0)
            self.pdf.image(img_buf, x=15, w=180)
            self.pdf.ln(5)
        if data.metrics_DISTRIBUTION_CALC is not None and not data.metrics_DISTRIBUTION_CALC.empty:
            self.pdf.set_font("DejaVu", 'B', 14)
            header_height = 10
            unique_cities = data.metrics_DISTRIBUTION_CALC['city'].unique()
            for i, city in enumerate(unique_cities):
                city_subset = data.metrics_DISTRIBUTION_CALC[data.metrics_DISTRIBUTION_CALC['city'] == city]
                img_buf = self._plot_single_city_distribution(city_subset, city)
                
                img = Image.open(img_buf)
                rendered_height = (180 * img.size[1]) / img.size[0]
                img_buf.seek(0)

                space_needed = rendered_height + 5
                if i == 0:
                    space_needed += header_height + 2
                if self.pdf.get_y() + space_needed > (self.pdf.h - 20):
                    self.pdf.add_page()
                if i == 0:
                    self.pdf.set_font("DejaVu", 'B', 12)
                    self.pdf.cell(0, header_height, "Current Price Distribution", new_x="LMARGIN", new_y="NEXT")
                    self.pdf.ln(2)
                self.pdf.image(img_buf, x=15, w=180)
                self.pdf.ln(5)

    def _get_matching_global_rules(self, criteria: dbmodels.SearchCriteria) -> list[dbmodels.GlobalNotificationRule]:
        all_gnr: list[dbmodels.GlobalNotificationRule] = self.db.get_current_global_notifs()
        if not all_gnr:
            raise ValueError(f"Failed to obtain GNR data from database")

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

        return matching_rules

    def _format_trigger_details(self, details: dict, anomaly) -> str:
        formatted_parts = []
        for key, value in details.items():
            label = self.HUMAN_LABELS.get(key, key.replace('_', ' ').title())
            if "percent" in key:
                value_str = f"{float(value):.2f}%"
            elif anomaly.analysis_id == 3: # BELOW_AVG_PERCENT
                value_str = f"{float(value):,.2f} (per m²) PLN"
            else:
                value_str = f"{float(value):,.2f} PLN"
            formatted_parts.append(f"{label}: {value_str}")
        return " | ".join(formatted_parts)

    def _draw_anomaly_table(self, anomalies, loc_lookup, criteria: dbmodels.SearchCriteria):
        global_rules: list[dbmodels.GlobalNotificationRule] = self._get_matching_global_rules(criteria)
        id2GNRname = {gnr.id: gnr.rule_name for gnr in global_rules}

        for an in anomalies:
            snap = an.listing_snapshot
            if self.pdf.get_y() > (self.pdf.h - 60):
                self.pdf.add_page()

            full_w = self.pdf.epw
            source_name = f"SC: {criteria.target_name}" if an.scope == "BATCH" else f"GNR: {id2GNRname.get(an.global_rule_id, 'Global Rule')}"
            disp_source = (source_name[:25] + '..') if len(source_name) > 25 else source_name
            disp_title = (snap.title[:70] + '..') if len(snap.title) > 70 else snap.title
            self.pdf.set_font("DejaVu", 'B', 8)
            self.pdf.set_fill_color(245, 245, 245)
            self.pdf.cell(50, 8, f" Source - {disp_source}", border='TL', fill=True)
            self.pdf.cell(0, 8, f" Title: {disp_title}", border='TR', fill=True, new_x="LMARGIN", new_y="NEXT")

            self.pdf.set_font("DejaVu", '', 8)
            allowed_w = (full_w * 0.65) - 5
            disp_loc = loc_lookup.get(snap.location_id, f"ID: {snap.location_id}")
            if self.pdf.get_string_width(disp_loc) > allowed_w:
                while self.pdf.get_string_width(disp_loc + "...") > allowed_w:
                    disp_loc = disp_loc[:-1]
                disp_loc = disp_loc.strip() + "..."
            price_display = f"{snap.price_total or snap.price_rent or 0.0:,.2f} PLN"
            self.pdf.cell(full_w*0.65, 8, f" Loc: {disp_loc}", border='L')
            self.pdf.cell(full_w*0.25, 8, f" Price: {price_display}", align='C')
            self.pdf.cell(full_w*0.10, 8, f" Type: {snap.price_type} ", border='R', align='R', new_x="LMARGIN", new_y="NEXT")

            self.pdf.set_fill_color(255, 250, 240)
            self.pdf.set_font("DejaVu", 'I', 7)
            details_str = " Details: " + self._format_trigger_details(an.trigger_details, an)
            disp_details = (details_str[:110] + '..') if len(details_str) > 110 else details_str
            self.pdf.cell(0, 6, disp_details, border='LR', fill=True, new_x="LMARGIN", new_y="NEXT")

            self.pdf.set_font("DejaVu", 'U', 7)
            self.pdf.set_text_color(0, 0, 255)
            display_url = (snap.listing_url[:100] + '...') if len(snap.listing_url) > 100 else snap.listing_url
            self.pdf.cell(0, 7, f" Link: {display_url}", border='LRB', link=snap.listing_url, new_x="LMARGIN", new_y="NEXT")
            
            self.pdf.set_text_color(0, 0, 0)
            self.pdf.ln(4)

    def _add_anomalies_section(self, data: ReportData):
        self.pdf.add_page()
        self.pdf.set_font("DejaVu", 'B', 14)
        self.pdf.cell(0, 10, "Detected Anomalies:", new_x="LMARGIN", new_y="NEXT")

        if data.anomalies_BELOW_AVG_PERCENT is None and data.anomalies_BELOW_THRESHOLD is None and data.anomalies_PRICE_DROP is None:
            self.pdf.cell(0, 10, "No anomaly detection requested.", new_x="LMARGIN", new_y="NEXT")
            return
        elif not data.anomalies_BELOW_AVG_PERCENT and not data.anomalies_BELOW_THRESHOLD and not data.anomalies_PRICE_DROP:
            self.pdf.cell(0, 10, "No anomalies detected.", new_x="LMARGIN", new_y="NEXT")
            return

        categories = [
            ("PRICE DROP DETECTION", data.anomalies_PRICE_DROP),
            ("BELOW THRESHOLD ALERTS", data.anomalies_BELOW_THRESHOLD),
            ("BELOW MARKET AVERAGE OUTLIERS", data.anomalies_BELOW_AVG_PERCENT)
        ]

        title_count = 0
        for title, anomaly_list in categories:
            if not anomaly_list:
                continue
            if title_count != 0:
                self.pdf.add_page()
            
            self.pdf.set_font("DejaVu", 'B', 12)
            self.pdf.set_text_color(0, 51, 102) # Dark blue
            self.pdf.cell(0, 10, title)
            self.pdf.ln(10)
            self.pdf.set_text_color(0, 0, 0)

            self._draw_anomaly_table(anomaly_list, data.loc_lookup, data.criteria)
            self.pdf.ln(10)
            title_count += 1

    def _add_clean_listings_section(self, data: ReportData):
        if not data.clean_listings:
            return

        self.pdf.add_page()
        self.pdf.set_font("DejaVu", 'B', 16)
        self.pdf.cell(self.pdf.epw, 10, "All Processed Listings", new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(5)
        self.pdf.set_font("DejaVu", 'I', 10)
        self.pdf.cell(self.pdf.epw, 8, "Complete list of properties identified and cleaned in this batch.", new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(5)

        sorted_listings = sorted(data.clean_listings, key=lambda x: x.title.lower() if x.title else "")
        for cl in sorted_listings:
            if self.pdf.get_y() > (self.pdf.h - 35):
                self.pdf.add_page()
            full_w = self.pdf.epw

            history = data.clean_listings_prices.get(cl.id, [])
            price_val = 0.0
            if history:
                curr = history[0]
                price_val = curr.price_sale_total or curr.price_rent_monthly or 0.0

            self.pdf.set_font("DejaVu", 'B', 9)
            self.pdf.set_fill_color(245, 245, 245)
            display_title = (cl.title[:90] + '..') if len(cl.title) > 90 else cl.title
            self.pdf.cell(full_w, 8, f" Title: {display_title}", border='TLR', fill=True, new_x="LMARGIN", new_y="NEXT")
            self.pdf.set_font("DejaVu", '', 8)

            allowed_w = (full_w * 0.65) - 5
            disp_loc = data.loc_lookup.get(cl.location_id, f"ID: {cl.location_id}")
            if self.pdf.get_string_width(disp_loc) > allowed_w:
                while self.pdf.get_string_width(disp_loc + "...") > allowed_w:
                    disp_loc = disp_loc[:-1]
                disp_loc = disp_loc.strip() + "..."
            self.pdf.cell(full_w*0.65, 8, f" Loc: {disp_loc}", border='L')
            self.pdf.cell(full_w*0.25, 8, f" Price: {price_val:,.2f} PLN", align='C')
            self.pdf.cell(full_w*0.10, 8, f" Type: {cl.transaction_type.upper()} ", border='R', align='R', new_x="LMARGIN", new_y="NEXT")

            self.pdf.set_font("DejaVu", 'U', 7)
            self.pdf.set_text_color(0, 102, 204)
            short_url = (cl.listing_url[:110] + '...') if len(cl.listing_url) > 110 else cl.listing_url
            self.pdf.cell(full_w, 7, f" View: {short_url}", border='LRB', link=cl.listing_url, new_x="LMARGIN", new_y="NEXT")
            
            self.pdf.set_text_color(0, 0, 0)
            self.pdf.ln(4)

    def generate_report(self, batch_id: int):
        data: ReportData = self._get_report_data(batch_id)
        self.pdf.add_page()

        self._add_header(data.criteria.target_name, batch_id)
        self._add_criteria_info(data.criteria)
        self._add_metrics_section(data)
        self._add_anomalies_section(data)
        self._add_clean_listings_section(data)
        return bytes(self.pdf.output())

#if __name__ == "__main__":
#    a = PDFReporter()
#    a.generate_report(26)
#    a.pdf.output("test_report.pdf")
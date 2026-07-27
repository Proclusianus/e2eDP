BEGIN; -- just to make sure the whole init.sql gets executed

CREATE SCHEMA IF NOT EXISTS "config";

CREATE TABLE IF NOT EXISTS "config"."system_settings" (
  "id" SERIAL PRIMARY KEY,
  "setting_key" varchar(50) UNIQUE NOT NULL,
  "setting_value" integer NOT NULL,
  "is_enabled" boolean DEFAULT true NOT NULL,
  "description_pl" text,
  "description_en" text
);

-- Enums
DO $$ BEGIN
  CREATE TYPE "config"."transaction_type_enum" AS ENUM ('sale', 'rent');
  CREATE TYPE "config"."market_type_enum" AS ENUM ('primary', 'secondary', 'both');
  EXCEPTION WHEN duplicate_object THEN null; 
END $$;

CREATE TABLE IF NOT EXISTS "config"."global_notification_rules" (
  "id" SERIAL PRIMARY KEY,
  "rule_name" varchar(255) NOT NULL,
  "description" text,
  "transaction_type" config.transaction_type_enum NOT NULL,
  "is_searching_all_cities" boolean DEFAULT false NOT NULL,
  "is_active" boolean DEFAULT true NOT NULL,
  "is_soft_deleted" boolean DEFAULT false NOT NULL,
  "created_at" timestamp DEFAULT (now()) NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_target_name 
ON "config"."global_notification_rules" ("rule_name") 
WHERE (is_soft_deleted = false);

CREATE TABLE IF NOT EXISTS "config"."search_criteria" (
  "id" SERIAL PRIMARY KEY,
  "target_name" varchar(255) NOT NULL,
  "description" text,
  "transaction_type" config.transaction_type_enum NOT NULL,
  "market_type" config.market_type_enum NOT NULL,
  "min_price" decimal(12,2),
  "max_price" decimal(12,2),
  "min_area" decimal(8,2),
  "max_area" decimal(8,2),
  "is_active" boolean DEFAULT true NOT NULL,
  "is_soft_deleted" boolean DEFAULT false NOT NULL,
  "created_at" timestamp DEFAULT (now()) NOT NULL,
  CONSTRAINT price_check CHECK (min_price >= 0 AND max_price >= min_price),
  CONSTRAINT area_check CHECK (min_area >= 0 AND max_area >= min_area)
);
CREATE INDEX IF NOT EXISTS idx_config_criteria_active ON "config"."search_criteria"("is_active", "is_soft_deleted");
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_target_name 
ON "config"."search_criteria" ("target_name") 
WHERE (is_soft_deleted = false);
-- ^^^ target_name must be unique (soft_deleted s_c names aren't taken into account)
-- so you can have s_c named the same as soft deleted previous s_c

-- N:M tables + join tables
CREATE TABLE IF NOT EXISTS "config"."locations" (
  "id" SERIAL PRIMARY KEY,
  "city_name" varchar(100) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS "config"."criteria_locations" (
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE, 
  "location_id" integer REFERENCES "config"."locations"("id") ON DELETE RESTRICT ON UPDATE CASCADE, 
  PRIMARY KEY ("criteria_id", "location_id")
);
CREATE TABLE IF NOT EXISTS "config"."global_rule_locations" (
  "global_rule_id" integer REFERENCES "config"."global_notification_rules"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "location_id" integer REFERENCES "config"."locations"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  PRIMARY KEY ("global_rule_id", "location_id")
);

CREATE TABLE IF NOT EXISTS "config"."property_types" (
  "id" SERIAL PRIMARY KEY,
  "type_name" varchar(50) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS "config"."criteria_property_types" (
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE, 
  "property_type_id" integer REFERENCES "config"."property_types"("id") ON DELETE RESTRICT ON UPDATE CASCADE, 
  PRIMARY KEY ("criteria_id", "property_type_id")
);

CREATE TABLE IF NOT EXISTS "config"."room_counts" (
  "id" SERIAL PRIMARY KEY,
  "room_label" varchar(10) UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS "config"."criteria_rooms" (
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE, 
  "room_id" integer REFERENCES "config"."room_counts"("id") ON DELETE RESTRICT ON UPDATE CASCADE, 
  PRIMARY KEY ("criteria_id", "room_id")
);

CREATE TABLE IF NOT EXISTS "config"."search_criteria_schedule" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer NOT NULL REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "execution_time" time NOT NULL,
  UNIQUE ("criteria_id", "execution_time")
);
CREATE INDEX IF NOT EXISTS idx_criteria_schedule_time ON "config"."search_criteria_schedule"("execution_time");

CREATE TABLE IF NOT EXISTS "config"."global_rules_schedule" (
  "id" SERIAL PRIMARY KEY,
  "global_rule_id" integer NOT NULL REFERENCES "config"."global_notification_rules"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "execution_time" time NOT NULL,
  UNIQUE ("global_rule_id", "execution_time")
);
CREATE INDEX IF NOT EXISTS idx_global_schedule_time ON "config"."global_rules_schedule"("execution_time");

-- data analysis
CREATE TABLE IF NOT EXISTS "config"."batch_analysis_dictionary" (
  "id" SERIAL PRIMARY KEY,
  "code" varchar(50) UNIQUE NOT NULL,
  "name_pl" varchar(100) NOT NULL,
  "name_en" varchar(100) NOT NULL,
  "description_pl" text,
  "description_en" text,
  "takes_parameter" BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS "config"."anomaly_analysis_dictionary" (
  "id" SERIAL PRIMARY KEY,
  "code" varchar(50) UNIQUE NOT NULL,
  "name_pl" varchar(100) NOT NULL,
  "name_en" varchar(100) NOT NULL,
  "description_pl" text,
  "description_en" text,
  "takes_parameter" BOOLEAN NOT NULL DEFAULT FALSE
);

-- data batch analysis (per data target config)
CREATE TABLE IF NOT EXISTS "config"."activated_batch_analyses" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer NOT NULL REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "analysis_id" integer NOT NULL REFERENCES "config"."batch_analysis_dictionary"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "param_value" decimal(12,2),
  UNIQUE ("criteria_id","analysis_id")
);

CREATE TABLE IF NOT EXISTS "config"."activated_anomaly_analyses" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer NOT NULL REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "analysis_id" integer NOT NULL REFERENCES "config"."anomaly_analysis_dictionary"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "param_value" decimal(12,2),
  UNIQUE ("criteria_id","analysis_id")
);

-- global data analysis (for all new coming data)
CREATE TABLE IF NOT EXISTS "config"."activated_notifications" (
  "id" SERIAL PRIMARY KEY,
  "global_rule_id" integer NOT NULL REFERENCES "config"."global_notification_rules"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "analysis_id" integer NOT NULL REFERENCES "config"."anomaly_analysis_dictionary"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "param_value" decimal(12,2),
  UNIQUE ("global_rule_id", "analysis_id")
);

-- Seeding data
INSERT INTO config.property_types (type_name) VALUES ('Apartment'), ('House') ON CONFLICT (type_name) DO NOTHING;
INSERT INTO config.room_counts (room_label) VALUES ('1'), ('2'), ('3'), ('4'), ('5'), ('6'), ('7'), ('8'), ('9'), ('+10') ON CONFLICT (room_label) DO NOTHING;
INSERT INTO "config"."batch_analysis_dictionary" 
("code", "name_en", "name_pl", "description_en", "description_pl") VALUES 
('DISTRIBUTION_CALC', 'Price Distribution', 'Rozkład cen w lokalizacji', 
 'Calculates price distribution (histogram) for current target.', 'Oblicza statystyki rozkładu cen (histogram).'),
('PRICE_DYNAMICS', 'Price Dynamics Analysis', 'Analiza dynamiki cen', 
 'Calculates average/median price changes over time.', 'Oblicza zmiany średniej i mediany w czasie.'),
('SUPPLY_VOLUME', 'Supply Volume Tracking', 'Monitorowanie wolumenu ofert', 
 'Tracks number of active listings over time.', 'Śledzi liczbę aktywnych ogłoszeń w czasie.')
ON CONFLICT (code) DO NOTHING;
INSERT INTO "config"."anomaly_analysis_dictionary" 
("code", "name_en", "name_pl", "description_en", "description_pl") VALUES 
('PRICE_DROP', 'Price Drop Detection', 'Wykrywanie obniżek cen', 
 'Detects when price decreases compared to previous snapshots.', 'Wykrywa spadki cen w stosunku do poprzednich zapisów.'),
('BELOW_THRESHOLD', 'Price Below Threshold', 'Cena poniżej progu X', 
 'Finds offers where total price/rent is lower than X.', 'Znajduje oferty z ceną całkowitą/wynajmu niższą niż X.'),
('BELOW_AVG_PERCENT', 'Price Below Average %', 'Cena X% poniżej średniej', 
 'Finds offers with price lower by X% than batch average.', 'Znajduje oferty z ceną niższą o X% od średniej.')
ON CONFLICT (code) DO NOTHING;
INSERT INTO "config"."system_settings" ("setting_key", "setting_value", "is_enabled", "description_pl", "description_en") VALUES 
('raw_retention_days', 30, true, 'Przez ile dni przechowywać surowe pobrane dane', 'How many days to keep raw JSON data'),
('clean_inactivity_days', 5, true, 'Ilość dni po której oferta jest uznawana za nieważną', 'Days after which listing is marked as inactive')
ON CONFLICT (setting_key) DO NOTHING;

-- End of config schema

-- Start of orchestration schema
CREATE SCHEMA IF NOT EXISTS "orchestration";

CREATE TABLE IF NOT EXISTS "orchestration"."batches" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "status" varchar(20) NOT NULL DEFAULT 'RUNNING',
  "started_at" timestamp NOT NULL DEFAULT now(),
  "finished_at" timestamp
);
CREATE INDEX IF NOT EXISTS idx_batch_data_criteria_id ON "orchestration"."batches"("criteria_id");

DO $$ BEGIN
  CREATE TYPE "orchestration"."error_source_enum" AS ENUM (
    'ANALYSIS', 'DASHBOARD', 'MAINTENANCE', 'DATABASE', 'UNKNOWN'
  );
  EXCEPTION WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS "orchestration"."system_errors" (
  "id" SERIAL PRIMARY KEY,
  "error_source" orchestration.error_source_enum NOT NULL,
  "module_name" varchar(100),
  "error_message" text NOT NULL,
  "stack_trace" text,
  "context_data" jsonb, 
  "occurred_at" timestamp DEFAULT now() NOT NULL,
  "is_resolved" boolean DEFAULT false NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_errors_unresolved ON "orchestration"."system_errors"("occurred_at" DESC) WHERE is_resolved = false;

-- End of orchestration schema

-- Start of raw data schema
CREATE SCHEMA IF NOT EXISTS "raw";

CREATE TABLE IF NOT EXISTS "raw"."execution_logs" (
  "id" SERIAL PRIMARY KEY,
  "job_name" varchar(50) NOT NULL,
  "batch_id" integer NOT NULL REFERENCES "orchestration"."batches"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "status" varchar(20) NOT NULL DEFAULT 'RUNNING',
  "error_message" text,
  "started_at" timestamp NOT NULL DEFAULT now(),
  "finished_at" timestamp
);
CREATE INDEX IF NOT EXISTS idx_scraping_logs_batch_id ON "raw"."execution_logs"("batch_id");

CREATE TABLE IF NOT EXISTS "raw"."listings" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "batch_id" integer REFERENCES "orchestration"."batches"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "clean_listing_id" integer, -- is a FK! added after creating/updating a clean listing out of this one
  "portal_name" varchar(50) NOT NULL,
  "external_id" varchar(100) NOT NULL,
  "listing_url" text NOT NULL,
  "raw_content" jsonb NOT NULL,
  "http_status" integer NOT NULL,
  "scraped_at" timestamp DEFAULT (now()) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_batch_id ON "raw"."listings"("batch_id");
CREATE INDEX IF NOT EXISTS idx_raw_scraped_at ON "raw"."listings"("scraped_at");

-- End of raw data schema

-- Start of clean data schema
CREATE SCHEMA IF NOT EXISTS "clean";

CREATE TABLE IF NOT EXISTS "clean"."execution_logs" (
  "id" SERIAL PRIMARY KEY,
  "job_name" varchar(50) NOT NULL,
  "raw_listing_id" integer NOT NULL REFERENCES "raw"."listings"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "status" varchar(20) NOT NULL DEFAULT 'RUNNING',
  "error_message" text,
  "started_at" timestamp NOT NULL DEFAULT now(),
  "finished_at" timestamp
);
CREATE INDEX IF NOT EXISTS idx_cleaning_logs_raw_id ON "clean"."execution_logs"("raw_listing_id");

CREATE TABLE IF NOT EXISTS "clean"."listings" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "location_id" integer NOT NULL REFERENCES "config"."locations"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "external_id" varchar(100) UNIQUE NOT NULL,
  "portal_name" varchar(50) NOT NULL,
  "listing_url" text NOT NULL,
  "title" varchar(255) NOT NULL,
  "area_m2" decimal(10,2) NOT NULL,
  "rooms" integer,
  "property_type_id" integer NOT NULL REFERENCES "config"."property_types"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "market" config.market_type_enum NOT NULL,
  "transaction_type" config.transaction_type_enum NOT NULL,
  "first_seen_at" timestamp DEFAULT (now()) NOT NULL,
  "last_seen_at" timestamp DEFAULT (now()) NOT NULL,
  "is_active" boolean DEFAULT true NOT NULL
);
DO $$ BEGIN
  --pg_constraint - internal system table which keeps records on PKs, FKs and other stuff
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_raw_listings_clean_id') THEN
    ALTER TABLE "raw"."listings" ADD CONSTRAINT fk_raw_listings_clean_id
    FOREIGN KEY ("clean_listing_id") REFERENCES "clean"."listings"("id") ON DELETE SET NULL ON UPDATE CASCADE;
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_clean_listings_criteria_id ON "clean"."listings"("criteria_id");
CREATE INDEX IF NOT EXISTS idx_clean_listings_external_id ON "clean"."listings"("external_id");

CREATE TABLE IF NOT EXISTS "clean"."price_history" (
  "id" SERIAL PRIMARY KEY,
  "listing_id" integer NOT NULL REFERENCES "clean"."listings"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "batch_id" integer REFERENCES "orchestration"."batches"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "price_sale_total" decimal(12,2),
  "price_sale_per_m2" decimal(12,2),
  "price_rent_monthly" decimal(12,2),
  "seen_at" timestamp DEFAULT (now()) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_price_history_batch_id ON "clean"."price_history"("batch_id");
CREATE INDEX IF NOT EXISTS idx_price_history_listing_id ON "clean"."price_history"("listing_id");

-- End of clean data schema

-- Start of analysis schema
CREATE SCHEMA IF NOT EXISTS "analytics";

CREATE TABLE IF NOT EXISTS "analytics"."execution_logs" (
  "id" SERIAL PRIMARY KEY,
  "job_name" varchar(50) NOT NULL,
  "batch_id" integer NOT NULL REFERENCES "orchestration"."batches"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "clean_listing_id" integer REFERENCES "clean"."listings"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "batch_analysis_id" integer REFERENCES "config"."batch_analysis_dictionary"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "anomaly_analysis_id" integer REFERENCES "config"."anomaly_analysis_dictionary"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "status" varchar(20) NOT NULL DEFAULT 'RUNNING',
  "error_message" text,
  "started_at" timestamp NOT NULL DEFAULT now(),
  "finished_at" timestamp,
  CONSTRAINT analysis_log_type_check CHECK (
    -- Case 1: Batch analysis
    (batch_analysis_id IS NOT NULL AND anomaly_analysis_id IS NULL AND clean_listing_id IS NULL)
    OR
    -- Case 2: Anomaly analysis
    (anomaly_analysis_id IS NOT NULL AND clean_listing_id IS NOT NULL AND batch_analysis_id IS NULL)
  )
);
CREATE INDEX IF NOT EXISTS idx_analytics_logs_batch ON "analytics"."execution_logs"("batch_id");
CREATE INDEX IF NOT EXISTS idx_analytics_logs_listing ON "analytics"."execution_logs"("clean_listing_id");

DO $$ BEGIN
  CREATE TYPE "analytics"."listing_price_type_enum" AS ENUM ('RENT', 'SALE');
  CREATE TYPE "analytics"."detected_anomalies_scope_enum" AS ENUM ('BATCH', 'GLOBAL');
  EXCEPTION WHEN duplicate_object THEN null;
END $$;

CREATE TABLE IF NOT EXISTS "analytics"."batch_metrics" (
  "id" SERIAL PRIMARY KEY,
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "batch_id" integer REFERENCES "orchestration"."batches"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "analysis_id" integer NOT NULL REFERENCES "config"."batch_analysis_dictionary"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "metrics" jsonb NOT NULL,
  "calculated_at" timestamp DEFAULT (now()) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_batch_metrics_batch ON "analytics"."batch_metrics"("batch_id");
CREATE INDEX IF NOT EXISTS idx_batch_metrics_criteria ON "analytics"."batch_metrics"("criteria_id");
CREATE INDEX IF NOT EXISTS idx_batch_metrics_analysis ON "analytics"."batch_metrics"("analysis_id");
CREATE INDEX IF NOT EXISTS idx_batch_metrics_date ON "analytics"."batch_metrics"("calculated_at");

CREATE TABLE IF NOT EXISTS "analytics"."listing_snapshots" (
  "id" SERIAL PRIMARY KEY,
  "listing_url" text NOT NULL,
  "title" varchar(255),
  "location_id" integer NOT NULL REFERENCES "config"."locations"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "area_m2" decimal(10,2),
  "price_type" analytics.listing_price_type_enum NOT NULL,
  "price_total" decimal(12,2),
  "price_per_m2" decimal(12,2),
  "price_rent" decimal(12,2),
  "captured_at" timestamp NOT NULL, -- Czas z listingu
  CONSTRAINT price_presence_check CHECK (
    (price_type = 'SALE' AND (price_total IS NOT NULL OR price_per_m2 IS NOT NULL)) OR
    (price_type = 'RENT' AND price_rent IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS "analytics"."detected_anomalies" (
  "id" SERIAL PRIMARY KEY,
  "listing_id" integer REFERENCES "clean"."listings"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "listing_snapshot_id" integer NOT NULL REFERENCES "analytics"."listing_snapshots"("id") ON DELETE CASCADE ON UPDATE CASCADE,
  "scope" analytics.detected_anomalies_scope_enum NOT NULL,
  "criteria_id" integer REFERENCES "config"."search_criteria"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "global_rule_id" integer REFERENCES "config"."global_notification_rules"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "batch_id" integer REFERENCES "orchestration"."batches"("id") ON DELETE SET NULL ON UPDATE CASCADE,
  "analysis_id" integer NOT NULL REFERENCES "config"."anomaly_analysis_dictionary"("id") ON DELETE RESTRICT ON UPDATE CASCADE,
  "trigger_details" jsonb NOT NULL,
  "is_read" boolean DEFAULT false NOT NULL,
  "detected_at" timestamp DEFAULT (now()) NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_listing ON "analytics"."detected_anomalies"("listing_id");
CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_criteria_id ON "analytics"."detected_anomalies"("criteria_id");
CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_global_rule_id ON "analytics"."detected_anomalies"("global_rule_id");
CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_batch_id ON "analytics"."detected_anomalies"("batch_id");
CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_analysis_id ON "analytics"."detected_anomalies"("analysis_id");
CREATE INDEX IF NOT EXISTS idx_analytics_anomalies_unread ON "analytics"."detected_anomalies"("is_read") WHERE is_read = false;

COMMIT;
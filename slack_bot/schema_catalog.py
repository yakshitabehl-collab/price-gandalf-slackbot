"""
Pricing Analytics table catalog.

Sourced from datahub-airflow YAML definitions (dh_squad: pricing-analytics).
All tables live in fulfillment-dwh-production.curated_data_shared unless noted.
Injected into the Gemini system prompt so the bot can answer data questions.
"""

SCHEMA_CATALOG = """
=== PRICING ANALYTICS — BIGQUERY TABLE CATALOG ===

Default project: fulfillment-dwh-production
Primary datasets: curated_data_shared, cl, rl
- curated_data_shared: shared curated tables (stable, analyst-facing)
- cl: core operational/curated layer (some tables are internal, prefixed with _)
- rl: reporting layer (aggregated, dashboard-facing)
Always filter on the partition field. Use clustering fields where possible.

---

TABLE: curated_data_shared.pricing_performance
Partition: partition_date_local | Cluster: global_entity_id
Description: Order-level pricing performance data for all entities. The primary table for pricing analysis.
Combines market metadata, customer scoring, vendor info, order details, logistics, DPS fee assignments, P&L metrics, and aggregated fee totals.
Key columns:
  - global_entity_id: Entity identifier (e.g. FP_MY, OP_SE)
  - country_code: ISO 3166-1 alpha-2 country code
  - partition_date_local: Local date order was placed (partition key)
  - order_id: Unique order identifier
  - is_successful: TRUE if order completed (status ACCEPTED/DELIVERED/PICKED_UP)
  - gmv_eur: Gross Merchandise Value in EUR
  - basket_value_nominal_eur: Subtotal of items in EUR (excludes fees/incentives)
  - delivery_fee_eur: Final delivery fee paid by customer in EUR
  - dps_travel_time_fee_eur: Travel Time Fee component in EUR
  - dps_surge_fee_eur: Surge (Fleet Delay) Fee in EUR
  - dps_saver_discount_eur: Saver discount suggested to customer in EUR
  - dps_priority_fee_eur: Priority Fee in EUR
  - dps_service_fee_eur: Service Fee in EUR
  - dps_bad_weather_fee_eur: Bad Weather Surcharge in EUR
  - dps_minimum_order_value_eur: Minimum Order Value in EUR
  - dps_small_basket_fee_eur: Small Basket Fee (Small Order Fee) in EUR
  - dps_payment_method_fee_eur: Payment Method Fee in EUR
  - analytical_profit: Gross profit (revenue_net minus cost_of_sales) in EUR
  - revenue_net: Total net revenues in EUR
  - delivery_costs: Rider cost per delivery in EUR
  - is_subscriber: TRUE if customer has active subscription
  - subscription_monthly_price_local: Monthly subscription price in local currency
  - is_dps: TRUE if DPS data was mapped to the order
  - is_customer_new: TRUE if this is the customer's first order
  - customer_value_segment: Customer lifetime value segment
  - customer_delivery_fee_score: WTP score for delivery fee [0-1]
  - travel_time_distance_km: Manhattan distance vendor to customer in km
  - occasion_time_of_day: dinner/breakfast/lunch/afternoon
  - occasion_day_of_week: weekday/weekend
  - vertical_type: restaurants/groceries/pharmacies
  - is_marketing: TRUE if order has a marketing incentive
  - has_dps_campaign_assignment: TRUE if any fee was driven by a Campaign

---

TABLE: curated_data_shared.dps_experiment_setups
Partition: test_start_date | Cluster: entity_id
Description: Setup of AB tests launched through DPS Service.
Granularity: entity_id + test_id + variation_group + vendor_group_id.
Key columns:
  - test_id: Unique experiment ID per entity
  - test_name: Experiment name in DPS
  - entity_id: Global entity identifier
  - country_code: ISO country code
  - test_start_date: When test started (UTC)
  - test_end_date: When test ended (UTC)
  - is_active: TRUE if experiment is currently running
  - experiment_type: AB / switchback / MAB
  - variation_group: Name of the variant (e.g. Control, Treatment)
  - variation_share: % of users in this variant
  - is_sustainable: TRUE if test started after 2022-03-24 (reliable data)
  - is_incentive_experiment: TRUE if at least one variant has an incentive
  - experiment_target_type: BASIC / INCENTIVE / SUBSCRIBER
  - randomization_unit: customer_id / vendor_id / order_id
  - zone_ids: Drop-off zones included in the experiment
  - price_scheme_id: Price scheme tested
  - hypothesis: Experiment hypothesis
  - objective: Primary success metric
  - is_already_executed: TRUE if experiment is running/ran (FALSE = planned)
  - misconfigured: TRUE if test name contains 'miscon' or duration < 2 days

---

TABLE: curated_data_shared.pricing_configuration_versions
Partition: scheme_active_from | Cluster: entity_id
Description: All historical DPS price scheme configurations at version level.
Key columns:
  - entity_id: Global entity identifier
  - country_code: ISO country code
  - scheme_id: Price scheme identifier
  - scheme_name: Price scheme name
  - scheme_active_from: When scheme became active in DPS
  - scheme_active_to: When scheme became inactive (NULL if current)
  - scheme_price_mechanisms: Record of booleans per component type
    (is_dbdf, is_dbmov, is_surge_mov, is_service_fee, is_priority_fee,
     is_saver_fee, is_small_order_fee, is_bad_weather_fee, is_payment_method_fee,
     is_logistics_fee, mov_type, travel_time_type, service_fee_type)
  - scheme_component_configs: Full nested config for each component

---

TABLE: curated_data_shared.pricing_component_configuration_versions_minimum_order_value
Cluster: entity_id
Description: Historical DPS Minimum Order Value (MOV) component configs.
Key columns:
  - entity_id, country_code, component_id
  - active_from, active_to
  - mov_type: Variable / Flat_non_zero / Flat_zero
  - is_surge_mov: Has Surge MOV component
  - is_small_order_fee: Has Small Order Fee inside MOV
  - is_dbmov: Has Distance Based MOV
  - config.minimum_order_value: MOV that applies at respective travel time
  - config.travel_time_threshold: Upper travel time limit for the MOV

---

TABLE: curated_data_shared.pricing_component_configuration_versions_travel_time_fee
Cluster: entity_id
Description: Historical DPS Travel Time Fee component configs.
Key columns:
  - entity_id, country_code, component_id
  - active_from, active_to
  - travel_time_fee_type: Variable / Flat_non_zero / Flat_zero
  - is_dbdf: TRUE for distance-based (Variable type)
  - config.travel_time_threshold: Upper travel time limit for the fee
  - config.travel_time_fee: Delivery fee at respective travel time

---

TABLE: curated_data_shared.pricing_component_configuration_versions_delay_fee
Cluster: entity_id
Description: Historical DPS Fleet Delay Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - type: ABSOLUTE or PERCENTAGE
  - min_fee, max_fee: Min/max configured delay fee
  - min_discount, max_discount: Min/max fleet saturation discount
  - config.delay_config.delay_threshold, config.delay_config.delay_fee

---

TABLE: curated_data_shared.pricing_component_configuration_versions_basket_value_fee
Cluster: entity_id
Description: Historical DPS Basket Value Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - config.basket_value_config.basket_value_fee
  - config.basket_value_config.basket_value_threshold

---

TABLE: curated_data_shared.pricing_component_configuration_versions_priority_fee
Cluster: entity_id
Description: Historical DPS Priority Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - config.percentage_fee: Priority fee in percentage
  - config.min_fee, config.max_fee: Min/max priority fee in local currency

---

TABLE: curated_data_shared.pricing_component_configuration_versions_saver_fee
Cluster: entity_id
Description: Historical DPS Saver Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - config.percentage_fee: Saver fee discount in percentage
  - config.min_fee, config.max_fee: Min/max saver fee in local currency

---

TABLE: curated_data_shared.pricing_component_configuration_versions_service_fee
Cluster: entity_id
Description: Historical DPS Service Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - service_fee_type: Absolute or Percentage
  - config.service_fee, config.min_service_fee, config.max_service_fee

---

TABLE: curated_data_shared.pricing_component_configuration_versions_logistics_fee
Cluster: entity_id
Description: Historical DPS Logistics Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - logistics_fee_type: Absolute or Percentage
  - config.logistics_fee, config.min_logistics_fee, config.max_logistics_fee

---

TABLE: curated_data_shared.pricing_component_configuration_versions_bad_weather_surcharge
Cluster: entity_id
Description: Historical DPS Bad Weather Surcharge component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - config.severity: 1-5 scale
  - config.surcharge: Surcharge value in local currency

---

TABLE: curated_data_shared.pricing_component_configuration_versions_payment_method_fee
Cluster: entity_id
Description: Historical DPS Cash on Delivery / Payment Method Fee component configs.
Key columns:
  - entity_id, country_code, component_id, active_from, active_to
  - config.payment_type: e.g. cash_on_delivery
  - config.payment_method_fee: Fee in local currency

---

TABLE: curated_data_shared.pricing_customer_conditions
Description: DPS customer condition configurations.
Key columns:
  - region, country_code
  - customer_condition_id
  - description
  - orders_number_less_than: Order count threshold for "new" customer definition
  - days_since_first_order_less_than: Days threshold
  - counting_method: VENDOR_VERTICAL or TOTAL
  - active_from, active_to

---

TABLE: curated_data_shared.pricing_customer_attribute_conditions
Cluster: country_code, condition_id
Description: DPS CDP-attribute customer conditions for campaign and incentive targeting.
One row per (country_code, condition_id). ALL rules must be met (AND logic).
Key columns:
  - country_code, condition_id, global_entity_id
  - active_from, active_to
  - num_rules: Number of active targeting rules
  - rules: ARRAY<STRUCT> with targeting rules
    (cdp_path, attribute_label, targeting_mode, value, include_null_values)
  - condition_text: Human-readable AND-joined summary of rules

---

TABLE: curated_data_shared.pricing_customer_area_versions
Cluster: country_code
Description: Historical DPS customer area polygon configurations.
Key columns:
  - region, country_code, city_id, area_id
  - customer_area_history.area_name
  - customer_area_history.polygon: Geography polygon
  - customer_area_history.active_from, customer_area_history.active_to

---

TABLE: curated_data_shared.compliance_score_tracking_aggregated
Description: Pricing Compliance Score per entity on a weekly basis.
Key columns:
  - entity_id, management_entity, init_week
  - n_in_use: Number of pricing mechanisms in use
  - n_mechanism: Number of pricing mechanisms to be used
  - entity_comp_score: Ratio of mechanisms in use / to be used
  - entity_orders: Weekly confirmed food orders (used as weight)

---

TABLE: curated_data_shared.coredata_incentives_reconciliation_dps_experiments
Cluster: entity_id (global_entity_id column)
Description: Reconciles DPS experiments with coredata incentives.
Key columns:
  - customer_incentive_uid, global_entity_id, customer_incentive_id
  - incentive_type, incentive_category, incentive_applied_to
  - purpose_type, sub_program, campaign_name
  - amount_lc, percentage
  - is_active, is_carc, is_targeted
  - start_timestamp_utc, expire_timestamp_utc

---

TABLE: curated_data_shared.coredata_incentives_reconciliation_dps_subscriptions
Cluster: entity_id (global_entity_id column)
Description: Reconciles DPS subscriptions with coredata incentives.
Same schema as coredata_incentives_reconciliation_dps_experiments.

---

TABLE: curated_data_shared.coredata_incentives_reconciliation_dps_campaigns
Cluster: entity_id (global_entity_id column)
Description: Reconciles DPS campaigns and campaign overrides with coredata incentives.
Same schema as coredata_incentives_reconciliation_dps_experiments.

---

TABLE: curated_data_shared.coredata_incentives_reconciliation_dps
Cluster: entity_id (global_entity_id column)
Description: Full reconciliation of all DPS incentive types with coredata (experiments + campaigns + subscriptions + new customer assignments).
Same schema as coredata_incentives_reconciliation_dps_experiments.

---

TABLE: curated_data_shared.dps_vendor_dynamic_cofunding
Description: Vendor cofunding configurations in DPS (campaigns, subscriptions, experiments).
Partition: created_date | Cluster: global_entity_id
Key columns:
  - region, country_code, global_entity_id
  - cofunding_id, vendor_id, chain_id
  - start_date, end_date, created_date
  - campaign_id, subscription_id, incentive_experiment_id
  - deleted, created_by, updated_by

---

TABLE: curated_data_shared.dps_vendor_dynamic_cofunding_threshold
Description: Basket value thresholds and funding amounts for each cofunding configuration.
Partition: created_date | Cluster: global_entity_id
Key columns:
  - region, country_code, global_entity_id
  - threshold_id, cofunding_id
  - basket_value_min_threshold, basket_value_max_threshold
  - funding_amount: Funding amount in local currency
  - funding_amount_subscribers: Funding amount for subscribers

---

TABLE: curated_data_shared.vendors_dynamic_pricing
Description: Vendor information from Dynamic Pricing Service (DPS). View.
Key columns: entity_id + standard vendor attributes from DPS.

---

TABLE: curated_data_shared.zone_overlap_shapes
Cluster: entity_id, city_id, zone_id_a
Description: Pairwise zone overlaps per city. One row per pair of overlapping zones.
Key columns:
  - entity_id, country_code, country_name
  - city_id, city_name
  - zone_id_a, zone_name_a, zone_id_b, zone_name_b
  - intersection_geometry: Geography polygon of the overlap
  - intersection_area: Area of overlap in KM²

---

TABLE: cl.dps_sessions_mapped_to_orders
Dataset: fulfillment-dwh-production.cl (shared view also in curated_data_shared)
Partition: created_date | Cluster: entity_id
WARNING: DO NOT USE FOR FINANCIAL DECISIONS. Use pricing_performance for financials.
Description: Orders enriched with the last DPS response before order placement. Includes DPS config, session, customer experiments, and fee breakdown. Covers both OD and VP orders. Backfill from 2022-04-01.
Key columns:
  - platform_order_code, order_id, delivery_id
  - created_date, created_date_local, order_placed_at, order_placed_at_local
  - region, country_code, city_id, zone_id
  - entity_id, vendor_id, chain_id, vendor_vertical_parent
  - customer_id, analytical_customer_id, account_id, dps_customer_id
  - is_customer_subscriber, is_customer_holdout
  - dps_session_id, dps_session_timestamp, dps_request_id, fe_session_id
  - customer_experiments: ARRAY of experiment assignments
  - dps_delivery_fee_local, dps_surge_fee_local, dps_travel_time_fee_local
  - dps_service_fee_local, dps_priority_fee_local, dps_bad_weather_fee_local
  - dps_cash_on_delivery_fee_local, dps_logistics_fee_local
  - dps_minimum_order_value_local, dps_basket_value_local
  - gmv_local, gfv_local, mov_customer_fee_local

---

TABLE: cl.dps_test_orders
Dataset: fulfillment-dwh-production.cl (shared view also in curated_data_shared)
Partition: created_date | Cluster: entity_id, test_id
Description: Orders associated with DPS experiments. Granularity: entity_id + test_id + platform_order_code (one order can appear multiple times if in multiple experiments). Backfill from 2022-04-01.
Key columns:
  - platform_order_code, order_id, delivery_id
  - region, entity_id, country_code, city_id, zone_id
  - vendor_id, vendor_vertical_parent, chain_id, vertical_type
  - customer_id, perseus_client_id, dps_customer_tag, is_customer_subscriber
  - test_id, test_name, test_type, test_variant, is_in_treatment
  - dps_basket_value_local, dps_delivery_fee_local, dps_surge_fee_local
  - dps_travel_time_fee_local, dps_minimum_order_value_local
  - dps_service_fee_local, dps_priority_fee_local, dps_bad_weather_fee_local
  - dps_cash_on_delivery_fee_local, dps_logistics_fee_local
  - mov_customer_fee_local, gmv_local, gfv_local, profit_local

---

TABLE: cl.dynamic_pricing_user_sessions
Dataset: fulfillment-dwh-production.cl (view)
Partition: created_date
Description: Raw DPS request/response logs for business analytics. Retention: 90 days. Endpoint can be multipleFee or singleFee.
Key columns:
  - region, country_code, entity_id
  - created_at, created_date
  - endpoint: multipleFee or singleFee
  - customer.id, customer.user_id (perseus_client_id)
  - customer.session.id: DPS session ID
  - customer.experiments: ARRAY of test assignments
  - customer.zones: ARRAY of zone info
  - vendors.id, vendors.delivery_fee, vendors.customer_tag
  - vendors.experiments, vendors.assignments
  - request_id, correlation_urns, version

---

TABLE: curated_data_shared.dps_perseus_sessions
Dataset: fulfillment-dwh-production.curated_data_shared
Partition: created_date | Cluster: entity_id
Description: Matches DPS sessions with Perseus frontend sessions using session_id. Only sessions present in both sources are included. Shows session-level CVRs, frontend events, and DPS pricing data. Granularity: entity_id + session_id. Backfill from 2024-12-01.
Key columns:
  - created_date, created_at, dh_platform
  - country_code, entity_id, operating_system
  - session_id, perseus_client_id, customer_id
  - cvr, cvr3, cvr_home_to_vendor
  - mcvr1, mcvr2, mcvr3, mcvr4, total_transactions
  - zones: STRUCT (zone_id, zone_name, city_id, city_name)
  - perseus_events: ARRAY of frontend events
  - perseus_transactions: STRUCT
  - dps: STRUCT (customer experiments, vendors, assignments)

---

TABLE: curated_data_shared.dps_test_cvrs
Dataset: fulfillment-dwh-production.curated_data_shared
Partition: created_date | Cluster: entity_id, test_id
Description: Session-level CVRs for DPS experiments. Granularity: session_id + entity_id + test_id + test_user_id + test_variant + treatment + is_target_group_level + target_group. Always filter on these columns to select the correct granularity. Backfill from 2023-08-01.
Key columns:
  - created_date, created_date_local, created_at
  - dh_platform, country_code, entity_id, operating_system
  - session_id, test_user_type, test_user_id, is_customer_subscriber
  - test_id, test_name, test_type, test_variant
  - is_test_switchback, is_test_partial, is_test_incentive, is_test_variant_incentive
  - treatment, is_in_treatment, is_target_group_level, target_group
  - cvr, cvr3, cvr_home_to_vendor
  - mcvr1, mcvr2, mcvr3, mcvr4
  - has_transaction, is_new_user, is_new_customer

---

TABLE: curated_data_shared.dps_test_users
Dataset: fulfillment-dwh-production.curated_data_shared
Partition: created_date
Description: Daily mapping of customer_id and perseus_client_id to DPS experiment and variant. Created from DPS business logs. May have duplicates on id columns due to table granularity.
Key columns:
  - created_date, country, country_code, entity_id
  - customer_id, perseus_client_id
  - test_id, test_variant, test_user_type, test_user_id
  - is_valid_test_user_id, is_valid_test_user

---

TABLE: curated_data_shared.dps_holdout_users
Dataset: fulfillment-dwh-production.curated_data_shared
Partition: created_date
Description: Daily mapping of customer_id to DPS holdout group, based on DPS business logs.
Key columns:
  - created_date, country, country_code, entity_id
  - customer_id, is_customer_holdout, is_valid_customer_id

---

TABLE: rl.dps_ab_test_significance_dataset
Dataset: fulfillment-dwh-production.rl
Description: Statistical significance results for DPS AB experiments. Updated daily at 11:30 UTC by the DPS Pricing significance DAG. Uses delta method and t-test.
Key columns:
  - country_code, test_name, test_id
  - metric columns with statistical results (profit_local, fully_loaded_gross_profit_local, gmv_local, dps_delivery_fee_local, etc.)
  - per-user metrics: orders_per_user, profit_local_per_user, gmv_local_per_user, dps_delivery_fee_local_per_user

---

TABLE: rl.dps_incentive_metrics
Dataset: fulfillment-dwh-production.rl
Partition: created_date_local | Cluster: entity_id
Description: Source table for the Pricing Domain Metrics dashboard. Contains platform-level aggregated metrics tracking High Value Actions (HVAs), Vendor Funding Incentives (VFIs), Overrides, and Revenue. Source: cl.dps_sessions_mapped_to_orders. Backfill from 2023-09-01.
Key columns:
  - region, country_name, platform, entity_id, vertical
  - created_date_local
  - total_spent_on_incentives, marketing_discount, hva_discount, fdnc_discount

---

TABLE: rl.dps_ab_test_dashboard_orders
Dataset: fulfillment-dwh-production.rl
Partition: created_date_local | Cluster: entity_id, test_id, dps_test_variant, treatment
Description: Order-level data powering the DPS AB Test Dashboard. Partition expiration: 12 months. Backfill from 2022-04-01.
Key columns:
  - created_date_local, entity_id
  - test_id, dps_test_variant, treatment

---

TABLE: rl.dps_ab_test_dashboard_cvr
Dataset: fulfillment-dwh-production.rl
Partition: created_date_local | Cluster: entity_id, test_id, variant, treatment
Description: CVR data powering the DPS AB Test Dashboard. Source: dps_test_cvrs + _dps_ab_test_user_cvrs + dps_experiment_setups. Partition expiration: 12 months. Backfill from 2024-08-01.
Key columns:
  - created_date_local, entity_id
  - test_id, variant, treatment

---

TABLE: rl.dps_holdouts_main_metrics
Dataset: fulfillment-dwh-production.rl
Partition: created_date | Cluster: entity_id, is_customer_holdout
Description: Main session-level metrics for holdout group analysis. Backfill from 2024-12-01. Source: dps_holdout_users + dps_perseus_sessions + dps_sessions_mapped_to_orders.
Key columns:
  - created_date, entity_id, is_customer_holdout

---

TABLE: rl.dps_holdouts_order_metrics
Dataset: fulfillment-dwh-production.rl
Partition: created_date | Cluster: entity_id, is_customer_holdout
Description: Order-level metrics for holdout group analysis. Backfill from 2024-12-01. Source: dps_holdout_users + dps_sessions_mapped_to_orders.
Key columns:
  - created_date, entity_id, is_customer_holdout

---

TABLE: rl.pricing_assignment_price_mechanism
Dataset: fulfillment-dwh-production.rl
Description: Report on pricing mechanism assignments per order. Source: cl._dps_orders_with_pricing_mechanism.

---

TABLE: rl.pricing_assignment_experiment_impact
Dataset: fulfillment-dwh-production.rl
Description: Report on pricing experiment impact via pricing mechanism assignments. Source: cl._dps_orders_with_pricing_mechanism.

---

TABLE: cl.pricing_campaign_configuration_versions
Dataset: fulfillment-dwh-production.cl
Description: Version history of pricing campaign configurations in DPS.

=== END OF TABLE CATALOG ===
"""


def get_schema_prompt() -> str:
    """Return the schema catalog formatted as a system prompt section."""
    return (
        "You have access to the following Pricing Analytics BigQuery tables. "
        "When answering data questions, reference these tables by their full name "
        "(fulfillment-dwh-production.curated_data_shared.table_name). "
        "Always filter on partition and cluster fields to keep queries efficient.\n\n"
        + SCHEMA_CATALOG
    )

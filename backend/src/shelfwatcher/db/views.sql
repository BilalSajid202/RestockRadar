-- PostgreSQL Read-Only Views for Chatbot (Section 9.8)

CREATE OR REPLACE VIEW v_shelf_status AS
SELECT 
    s.shelf_id,
    s.name AS shelf_name,
    s.aisle,
    s.level,
    s.total_facings,
    ss.item_count,
    ss.gap_count,
    ss.fill_pct,
    ss.status,
    ss.captured_at
FROM shelves s
LEFT JOIN (
    SELECT shelf_id, item_count, gap_count, fill_pct, status, captured_at
    FROM shelf_snapshots
    WHERE snapshot_id IN (
        SELECT MAX(snapshot_id) FROM shelf_snapshots GROUP BY shelf_id
    )
) ss ON s.shelf_id = ss.shelf_id;

CREATE OR REPLACE VIEW v_sku AS
SELECT 
    sku_id,
    name_en,
    name_ur,
    category,
    unit_price,
    pack_size,
    shelf_life_days
FROM skus;

CREATE OR REPLACE VIEW v_snapshots AS
SELECT 
    snapshot_id,
    shelf_id,
    sku_id,
    captured_at,
    item_count,
    gap_count,
    fill_pct,
    status
FROM shelf_snapshots;

CREATE OR REPLACE VIEW v_events AS
SELECT 
    event_id,
    shelf_id,
    sku_id,
    type,
    occurred_at
FROM events;

CREATE OR REPLACE VIEW v_forecasts AS
SELECT 
    forecast_id,
    sku_id,
    generated_at,
    horizon_days,
    predicted_stockout_at,
    model_version,
    used_fallback
FROM forecasts;

CREATE OR REPLACE VIEW v_tickets AS
SELECT 
    ticket_id,
    store_id,
    sku_id,
    shelf_id,
    supplier_id,
    qty,
    cost,
    status,
    approval_required,
    created_at,
    updated_at
FROM restock_tickets;

CREATE OR REPLACE VIEW v_orders AS
SELECT 
    ticket_id,
    store_id,
    sku_id,
    supplier_id,
    qty,
    cost,
    status,
    created_at,
    updated_at
FROM restock_tickets
WHERE status IN ('APPROVED', 'ORDERED', 'AWAITING_DELIVERY', 'DELIVERED', 'VERIFIED_FILLED');

CREATE OR REPLACE VIEW v_suppliers AS
SELECT 
    supplier_id,
    name,
    lead_time_days,
    moq
FROM suppliers;

CREATE OR REPLACE VIEW v_summaries AS
SELECT 
    summary_id,
    store_id,
    summary_date,
    language,
    text
FROM summaries;

-- ============================================================================
-- CIS9340 AutoOps Business Views Pack
-- Additive script for role-oriented operational/reporting surfaces.
-- ============================================================================

USE cis9340_physical_database_updated;

DROP VIEW IF EXISTS vw_sales_daily_rollup;
DROP VIEW IF EXISTS vw_inventory_low_stock;
DROP VIEW IF EXISTS vw_mechanic_repair_queue;
DROP VIEW IF EXISTS vw_manager_branch_summary;
DROP VIEW IF EXISTS vw_frontdesk_customer_search;

CREATE OR REPLACE VIEW vw_branch_inventory AS
SELECT
    b.branch_ID,
    b.address AS branch_address,
    pr.product_ID,
    pr.product_type,
    CASE pr.product_type
        WHEN 'CAR' THEN CONCAT(c.year, ' ', c.make, ' ', c.model)
        WHEN 'PART' THEN pt.part_name
        ELSE CONCAT('Product #', pr.product_ID)
    END AS product_description,
    pr.price,
    i.quantity_in_stock,
    i.reorder_level,
    CASE
        WHEN i.quantity_in_stock <= i.reorder_level THEN 'REORDER'
        ELSE 'OK'
    END AS stock_status
FROM INVENTORY i
JOIN BRANCH b ON i.branch_ID = b.branch_ID
JOIN PRODUCT pr ON i.product_ID = pr.product_ID
LEFT JOIN CAR c ON pr.product_ID = c.product_ID
LEFT JOIN PART pt ON pr.product_ID = pt.product_ID;

CREATE VIEW vw_frontdesk_customer_search AS
SELECT
    customer_ID,
    first_name,
    last_name,
    DOB,
    address,
    phone,
    email
FROM vw_customer_profile;

CREATE VIEW vw_manager_branch_summary AS
SELECT
    b.branch_ID,
    b.address AS branch_address,
    COUNT(DISTINCT s.sale_ID) AS sale_count,
    COALESCE(SUM(s.total_amount), 0) AS gross_sales,
    COUNT(DISTINCT CASE WHEN r.status <> 'Completed' THEN r.repair_ID END) AS open_repairs,
    COUNT(DISTINCT CASE WHEN vbi.stock_status = 'REORDER' THEN CONCAT(vbi.branch_ID, ':', vbi.product_ID) END) AS reorder_alerts
FROM BRANCH b
LEFT JOIN SALE s ON b.branch_ID = s.branch_ID
LEFT JOIN APPOINTMENT a ON b.branch_ID = a.branch_ID
LEFT JOIN REPAIR r ON a.appointment_ID = r.appointment_ID
LEFT JOIN vw_branch_inventory vbi ON b.branch_ID = vbi.branch_ID
GROUP BY b.branch_ID, b.address;

CREATE VIEW vw_mechanic_repair_queue AS
SELECT
    r.repair_ID,
    r.status AS repair_status,
    r.cost,
    a.appointment_ID,
    a.date AS appointment_date,
    a.time AS appointment_time,
    a.appointment_type,
    a.branch_ID,
    a.customer_ID,
    CONCAT(cp.first_name, ' ', cp.last_name) AS customer_name,
    r.employee_ID,
    CONCAT(ep.first_name, ' ', ep.last_name) AS mechanic_name
FROM REPAIR r
JOIN APPOINTMENT a ON r.appointment_ID = a.appointment_ID
LEFT JOIN vw_customer_profile cp ON a.customer_ID = cp.customer_ID
LEFT JOIN vw_employee_profile ep ON r.employee_ID = ep.employee_ID;

CREATE VIEW vw_inventory_low_stock AS
SELECT
    branch_ID,
    branch_address,
    product_ID,
    product_type,
    product_description,
    quantity_in_stock,
    reorder_level,
    stock_status
FROM vw_branch_inventory
WHERE stock_status = 'REORDER';

CREATE VIEW vw_sales_daily_rollup AS
SELECT
    s.date AS sale_date,
    s.branch_ID,
    COUNT(*) AS sale_count,
    COALESCE(SUM(s.total_amount), 0) AS gross_sales,
    COALESCE(AVG(s.total_amount), 0) AS avg_sale_value
FROM SALE s
GROUP BY s.date, s.branch_ID;

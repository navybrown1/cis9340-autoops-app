-- ============================================================================
-- CIS 9340: Principles of Database Management
-- Physical Database Implementation (MySQL 8)
--
-- Group 1: Nastassjia Durand (Captain), Akshan Rai (Vice Captain),
--          Jessica Ezem, Kimberly Jonas, Edwin Brown
--
-- Source: Logical Data Model Logic Document + Revised ERD v17
-- Converted from the uploaded PostgreSQL-flavored script to MySQL 8 syntax.
--
-- ============================================================================
CREATE DATABASE IF NOT EXISTS cis9340_physical_database;
USE cis9340_physical_database;

-- ============================================================================
-- CLEANUP
-- Drop views first, then tables. Disable FK checks during cleanup.
-- ============================================================================

DROP VIEW IF EXISTS vw_repair_history;
DROP VIEW IF EXISTS vw_sale_detail;
DROP VIEW IF EXISTS vw_branch_inventory;
DROP VIEW IF EXISTS vw_employee_profile;
DROP VIEW IF EXISTS vw_customer_profile;

SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS INVENTORY;
DROP TABLE IF EXISTS REPAIR_PRODUCT;
DROP TABLE IF EXISTS REPAIR;
DROP TABLE IF EXISTS APPOINTMENT;
DROP TABLE IF EXISTS LOAN;
DROP TABLE IF EXISTS PAYMENT;
DROP TABLE IF EXISTS SALE_ITEM;
DROP TABLE IF EXISTS SALE;
DROP TABLE IF EXISTS PART;
DROP TABLE IF EXISTS CAR;
DROP TABLE IF EXISTS PRODUCT;
DROP TABLE IF EXISTS CUSTOMER;
DROP TABLE IF EXISTS EMPLOYEE;
DROP TABLE IF EXISTS BRANCH;
DROP TABLE IF EXISTS PERSON;

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
-- 1. PERSON
-- ============================================================================

CREATE TABLE PERSON (
    person_ID    INT          PRIMARY KEY,
    first_name   VARCHAR(50)  NOT NULL,
    last_name    VARCHAR(50)  NOT NULL,
    DOB          DATE,
    address      VARCHAR(200),
    phone        VARCHAR(20),
    email        VARCHAR(100)
);

-- ============================================================================
-- 2. BRANCH
-- Created without manager FK to break circular dependency
-- ============================================================================

CREATE TABLE BRANCH (
    branch_ID          INT           PRIMARY KEY,
    address            VARCHAR(200)  NOT NULL,
    phone              VARCHAR(20),
    email              VARCHAR(100),
    branch_manager_ID  INT
);

-- ============================================================================
-- 3. EMPLOYEE
-- ============================================================================

CREATE TABLE EMPLOYEE (
    employee_ID  INT          PRIMARY KEY,
    person_ID    INT          NOT NULL UNIQUE,
    branch_ID    INT          NOT NULL,
    `role`       VARCHAR(50)  NOT NULL,

    CONSTRAINT fk_employee_person
        FOREIGN KEY (person_ID) REFERENCES PERSON (person_ID),
    CONSTRAINT fk_employee_branch
        FOREIGN KEY (branch_ID) REFERENCES BRANCH (branch_ID)
);

-- Add manager FK after EMPLOYEE exists
ALTER TABLE BRANCH
    ADD CONSTRAINT fk_branch_manager
        FOREIGN KEY (branch_manager_ID) REFERENCES EMPLOYEE (employee_ID);

-- ============================================================================
-- 4. CUSTOMER
-- ============================================================================

CREATE TABLE CUSTOMER (
    customer_ID  INT  PRIMARY KEY,
    person_ID    INT  NOT NULL UNIQUE,

    CONSTRAINT fk_customer_person
        FOREIGN KEY (person_ID) REFERENCES PERSON (person_ID)
);

-- ============================================================================
-- 5. PRODUCT
-- ============================================================================

CREATE TABLE PRODUCT (
    product_ID    INT            PRIMARY KEY,
    product_type  VARCHAR(10)    NOT NULL,
    description   VARCHAR(200),
    `value`       DECIMAL(10,2),

    CONSTRAINT chk_product_type
        CHECK (product_type IN ('CAR', 'PART'))
);

-- ============================================================================
-- 6. CAR
-- ============================================================================

CREATE TABLE CAR (
    product_ID  INT          PRIMARY KEY,
    make        VARCHAR(50)  NOT NULL,
    model       VARCHAR(50)  NOT NULL,
    `year`      INT          NOT NULL,
    VIN         CHAR(17)     NOT NULL UNIQUE,

    CONSTRAINT fk_car_product
        FOREIGN KEY (product_ID) REFERENCES PRODUCT (product_ID)
);

-- ============================================================================
-- 7. PART
-- ============================================================================

CREATE TABLE PART (
    product_ID     INT           PRIMARY KEY,
    serial_number  VARCHAR(50),
    part_name      VARCHAR(100)  NOT NULL,

    CONSTRAINT fk_part_product
        FOREIGN KEY (product_ID) REFERENCES PRODUCT (product_ID)
);

-- ============================================================================
-- 8. SALE
-- ============================================================================

CREATE TABLE SALE (
    sale_ID          INT            PRIMARY KEY,
    branch_ID        INT            NOT NULL,
    customer_ID      INT            NOT NULL,
    `date`           DATE           NOT NULL,
    `time`           TIME           NOT NULL,
    total_amount     DECIMAL(10,2)  NOT NULL,
    delivery_method  VARCHAR(50),

    CONSTRAINT fk_sale_branch
        FOREIGN KEY (branch_ID) REFERENCES BRANCH (branch_ID),
    CONSTRAINT fk_sale_customer
        FOREIGN KEY (customer_ID) REFERENCES CUSTOMER (customer_ID)
);

-- ============================================================================
-- 9. SALE_ITEM
-- ============================================================================

CREATE TABLE SALE_ITEM (
    sale_item_ID  INT            PRIMARY KEY,
    sale_ID       INT            NOT NULL,
    product_ID    INT            NOT NULL,
    quantity      INT            NOT NULL,
    unit_price    DECIMAL(10,2)  NOT NULL,

    CONSTRAINT fk_saleitem_sale
        FOREIGN KEY (sale_ID) REFERENCES SALE (sale_ID),
    CONSTRAINT fk_saleitem_product
        FOREIGN KEY (product_ID) REFERENCES PRODUCT (product_ID),

    CONSTRAINT chk_saleitem_quantity
        CHECK (quantity > 0),
    CONSTRAINT chk_saleitem_price
        CHECK (unit_price >= 0)
);

-- ============================================================================
-- 10. PAYMENT
-- ============================================================================

CREATE TABLE PAYMENT (
    payment_ID             INT            PRIMARY KEY,
    sale_ID                INT            NOT NULL,
    amount                 DECIMAL(10,2)  NOT NULL,
    `date`                 DATE           NOT NULL,
    `time`                 TIME           NOT NULL,
    payment_type           VARCHAR(30)    NOT NULL,
    transaction_reference  VARCHAR(50),

    CONSTRAINT fk_payment_sale
        FOREIGN KEY (sale_ID) REFERENCES SALE (sale_ID),

    CONSTRAINT chk_payment_amount
        CHECK (amount > 0)
);

-- ============================================================================
-- 11. LOAN
-- ============================================================================

CREATE TABLE LOAN (
    loan_ID              INT            PRIMARY KEY,
    sale_ID              INT            NOT NULL UNIQUE,
    amount               DECIMAL(10,2)  NOT NULL,
    financier_name       VARCHAR(100)   NOT NULL,
    loan_term_months     INT            NOT NULL,
    interest_rate        DECIMAL(5,4)   NOT NULL,
    credit_check_status  VARCHAR(20)    NOT NULL,
    monthly_payment      DECIMAL(10,2)  NOT NULL,

    CONSTRAINT fk_loan_sale
        FOREIGN KEY (sale_ID) REFERENCES SALE (sale_ID),

    CONSTRAINT chk_loan_amount
        CHECK (amount > 0),
    CONSTRAINT chk_loan_term
        CHECK (loan_term_months > 0),
    CONSTRAINT chk_loan_rate
        CHECK (interest_rate >= 0),
    CONSTRAINT chk_loan_monthly
        CHECK (monthly_payment > 0),
    CONSTRAINT chk_loan_credit_status
        CHECK (credit_check_status IN ('Approved', 'Denied', 'Pending'))
);

-- ============================================================================
-- 12. APPOINTMENT
-- ============================================================================

CREATE TABLE APPOINTMENT (
    appointment_ID    INT          PRIMARY KEY,
    customer_ID       INT          NOT NULL,
    car_id            INT          NOT NULL,
    branch_ID         INT          NOT NULL,
    `date`            DATE         NOT NULL,
    `time`            TIME         NOT NULL,
    appointment_type  VARCHAR(30)  NOT NULL,
    status            VARCHAR(20)  NOT NULL,
    employee_ID       INT          NOT NULL,

    CONSTRAINT fk_appointment_customer
        FOREIGN KEY (customer_ID) REFERENCES CUSTOMER (customer_ID),
    CONSTRAINT fk_appointment_car
        FOREIGN KEY (car_id) REFERENCES CAR (product_ID),
    CONSTRAINT fk_appointment_branch
        FOREIGN KEY (branch_ID) REFERENCES BRANCH (branch_ID),
    CONSTRAINT fk_appointment_employee
        FOREIGN KEY (employee_ID) REFERENCES EMPLOYEE (employee_ID),

    CONSTRAINT chk_appointment_status
        CHECK (status IN ('Scheduled', 'Confirmed', 'In Progress', 'Completed', 'Cancelled'))
);

-- ============================================================================
-- 13. REPAIR
-- ============================================================================

CREATE TABLE REPAIR (
    repair_ID       INT            PRIMARY KEY,
    appointment_ID  INT            NOT NULL,
    employee_ID     INT            NOT NULL,
    status          VARCHAR(20)    NOT NULL,
    cost            DECIMAL(10,2)  NOT NULL,

    CONSTRAINT fk_repair_appointment
        FOREIGN KEY (appointment_ID) REFERENCES APPOINTMENT (appointment_ID),
    CONSTRAINT fk_repair_employee
        FOREIGN KEY (employee_ID) REFERENCES EMPLOYEE (employee_ID),

    CONSTRAINT chk_repair_status
        CHECK (status IN ('In Progress', 'Completed', 'On Hold')),
    CONSTRAINT chk_repair_cost
        CHECK (cost >= 0)
);

-- ============================================================================
-- 14. REPAIR_PRODUCT
-- ============================================================================

CREATE TABLE REPAIR_PRODUCT (
    repair_ID      INT  NOT NULL,
    product_ID     INT  NOT NULL,
    quantity_used  INT  NOT NULL,

    CONSTRAINT pk_repair_product
        PRIMARY KEY (repair_ID, product_ID),
    CONSTRAINT fk_rp_repair
        FOREIGN KEY (repair_ID) REFERENCES REPAIR (repair_ID),
    CONSTRAINT fk_rp_product
        FOREIGN KEY (product_ID) REFERENCES PRODUCT (product_ID),

    CONSTRAINT chk_rp_quantity
        CHECK (quantity_used > 0)
);

-- ============================================================================
-- 15. INVENTORY
-- ============================================================================

CREATE TABLE INVENTORY (
    inventory_ID            INT  PRIMARY KEY,
    branch_ID               INT  NOT NULL,
    product_ID              INT  NOT NULL,
    quantity_in_inventory   INT  NOT NULL DEFAULT 0,
    reorder_level           INT  NOT NULL DEFAULT 0,

    CONSTRAINT fk_inventory_branch
        FOREIGN KEY (branch_ID) REFERENCES BRANCH (branch_ID),
    CONSTRAINT fk_inventory_product
        FOREIGN KEY (product_ID) REFERENCES PRODUCT (product_ID),

    CONSTRAINT uq_inventory_branch_product
        UNIQUE (branch_ID, product_ID),

    CONSTRAINT chk_inventory_qty
        CHECK (quantity_in_inventory >= 0),
    CONSTRAINT chk_inventory_reorder
        CHECK (reorder_level >= 0)
);

-- ============================================================================
-- INDEXES
-- ============================================================================

CREATE INDEX idx_customer_person   ON CUSTOMER (person_ID);
CREATE INDEX idx_employee_person   ON EMPLOYEE (person_ID);
CREATE INDEX idx_employee_branch   ON EMPLOYEE (branch_ID);

CREATE INDEX idx_sale_customer     ON SALE (customer_ID);
CREATE INDEX idx_sale_branch       ON SALE (branch_ID);
CREATE INDEX idx_sale_date         ON SALE (`date`);

CREATE INDEX idx_saleitem_sale     ON SALE_ITEM (sale_ID);
CREATE INDEX idx_saleitem_product  ON SALE_ITEM (product_ID);

CREATE INDEX idx_payment_sale      ON PAYMENT (sale_ID);
CREATE INDEX idx_loan_sale         ON LOAN (sale_ID);

CREATE INDEX idx_appt_customer     ON APPOINTMENT (customer_ID);
CREATE INDEX idx_appt_car          ON APPOINTMENT (car_id);
CREATE INDEX idx_appt_branch       ON APPOINTMENT (branch_ID);
CREATE INDEX idx_appt_employee     ON APPOINTMENT (employee_ID);
CREATE INDEX idx_appt_date         ON APPOINTMENT (`date`);

CREATE INDEX idx_repair_appt       ON REPAIR (appointment_ID);
CREATE INDEX idx_repair_employee   ON REPAIR (employee_ID);

CREATE INDEX idx_inventory_branch  ON INVENTORY (branch_ID);
CREATE INDEX idx_inventory_product ON INVENTORY (product_ID);

-- ============================================================================
-- VIEWS
-- Use DROP VIEW IF EXISTS above for maximum MySQL compatibility
-- ============================================================================

CREATE VIEW vw_customer_profile AS
SELECT
    c.customer_ID,
    p.person_ID,
    p.first_name,
    p.last_name,
    p.DOB,
    p.address,
    p.phone,
    p.email
FROM CUSTOMER c
JOIN PERSON p ON c.person_ID = p.person_ID;

CREATE VIEW vw_employee_profile AS
SELECT
    e.employee_ID,
    p.first_name,
    p.last_name,
    e.`role`,
    b.branch_ID,
    b.address AS branch_address
FROM EMPLOYEE e
JOIN PERSON p ON e.person_ID = p.person_ID
JOIN BRANCH b ON e.branch_ID = b.branch_ID;

CREATE VIEW vw_branch_inventory AS
SELECT
    b.branch_ID,
    b.address AS branch_address,
    pr.product_ID,
    pr.product_type,
    pr.description,
    i.quantity_in_inventory,
    i.reorder_level,
    CASE
        WHEN i.quantity_in_inventory <= i.reorder_level THEN 'REORDER'
        ELSE 'OK'
    END AS stock_status
FROM INVENTORY i
JOIN BRANCH b ON i.branch_ID = b.branch_ID
JOIN PRODUCT pr ON i.product_ID = pr.product_ID;

CREATE VIEW vw_sale_detail AS
SELECT
    s.sale_ID,
    s.`date` AS sale_date,
    s.total_amount,
    CONCAT(cp.first_name, ' ', cp.last_name) AS customer_name,
    si.sale_item_ID,
    pr.description AS product_description,
    si.quantity,
    si.unit_price,
    (si.quantity * si.unit_price) AS line_total
FROM SALE s
JOIN vw_customer_profile cp ON s.customer_ID = cp.customer_ID
JOIN SALE_ITEM si ON s.sale_ID = si.sale_ID
JOIN PRODUCT pr ON si.product_ID = pr.product_ID;

CREATE VIEW vw_repair_history AS
SELECT
    r.repair_ID,
    a.appointment_ID,
    a.`date` AS appointment_date,
    CONCAT(cp.first_name, ' ', cp.last_name) AS customer_name,
    CONCAT(c.make, ' ', c.model, ' (', c.`year`, ')') AS vehicle,
    CONCAT(ep.first_name, ' ', ep.last_name) AS mechanic,
    r.status AS repair_status,
    r.cost AS labor_cost,
    pr.description AS part_used,
    rp.quantity_used
FROM REPAIR r
JOIN APPOINTMENT a ON r.appointment_ID = a.appointment_ID
JOIN vw_customer_profile cp ON a.customer_ID = cp.customer_ID
JOIN CAR c ON a.car_id = c.product_ID
JOIN vw_employee_profile ep ON r.employee_ID = ep.employee_ID
LEFT JOIN REPAIR_PRODUCT rp ON r.repair_ID = rp.repair_ID
LEFT JOIN PRODUCT pr ON rp.product_ID = pr.product_ID;

-- ============================================================================
-- SEED DATA
-- ============================================================================

INSERT INTO PERSON VALUES
(1,  'Maria',   'Santos',     '1985-03-14', '123 Main St, Bronx, NY 10451',           '718-555-0101', 'maria.santos@email.com'),
(2,  'James',   'Washington', '1978-11-22', '456 Grand Ave, Brooklyn, NY 11238',      '718-555-0102', 'james.w@email.com'),
(3,  'Aisha',   'Patel',      '1990-07-08', '789 Broadway, Manhattan, NY 10003',      '212-555-0103', 'aisha.p@email.com'),
(4,  'Carlos',  'Rivera',     '1982-01-30', '321 Oak Blvd, Queens, NY 11375',         '347-555-0104', 'carlos.r@email.com'),
(5,  'Tamika',  'Johnson',    '1995-09-17', '654 Elm St, Staten Island, NY 10301',    '917-555-0105', 'tamika.j@email.com'),
(6,  'Robert',  'Kim',        '1980-05-25', '100 Service Rd, Bronx, NY 10452',        '718-555-0201', 'robert.k@email.com'),
(7,  'Diana',   'Okafor',     '1988-12-03', '200 Mechanic Ln, Brooklyn, NY 11201',    '718-555-0202', 'diana.o@email.com'),
(8,  'Miguel',  'Torres',     '1975-06-19', '300 Auto Plaza, Queens, NY 11101',       '347-555-0203', 'miguel.t@email.com'),
(9,  'Sarah',   'Chen',       '1992-04-11', '400 Parts Way, Manhattan, NY 10016',     '212-555-0204', 'sarah.c@email.com'),
(10, 'Anthony', 'Brown',      '1987-08-29', '500 Dealer Dr, Staten Island, NY 10314', '917-555-0205', 'anthony.b@email.com');

INSERT INTO BRANCH (branch_ID, address, phone, email) VALUES
    (1, '1000 Auto Mall Dr, Bronx, NY 10451',   '718-555-1000', 'bronx@autodealer.com'),
    (2, '2000 Motor Ave, Brooklyn, NY 11201',   '718-555-2000', 'brooklyn@autodealer.com'),
    (3, '3000 Car Plaza Blvd, Queens, NY 11101','347-555-3000', 'queens@autodealer.com');

INSERT INTO EMPLOYEE VALUES
(1, 6, 1, 'Branch Manager'),
(2, 7, 2, 'Branch Manager'),
(3, 8, 3, 'Branch Manager'),
(4, 9, 1, 'Mechanic'),
(5, 10, 2, 'Sales Associate');

UPDATE BRANCH SET branch_manager_ID = 1 WHERE branch_ID = 1;
UPDATE BRANCH SET branch_manager_ID = 2 WHERE branch_ID = 2;
UPDATE BRANCH SET branch_manager_ID = 3 WHERE branch_ID = 3;

INSERT INTO CUSTOMER VALUES
(1, 1),
(2, 2),
(3, 3),
(4, 4),
(5, 5);

INSERT INTO PRODUCT VALUES
(1,  'CAR',  '2024 Honda Civic Sedan',       28500.00),
(2,  'CAR',  '2023 Toyota Camry XSE',        35200.00),
(3,  'CAR',  '2024 Ford F-150 XLT',          45900.00),
(4,  'CAR',  '2023 Hyundai Tucson SEL',      32100.00),
(10, 'PART', 'Synthetic Motor Oil 5W-30 (5qt)', 42.99),
(11, 'PART', 'Premium Brake Pad Set (Front)',   129.50),
(12, 'PART', 'Cabin Air Filter',                 24.95),
(13, 'PART', 'Serpentine Belt',                  67.80),
(14, 'PART', 'Wiper Blade Set (Pair)',           34.50);

INSERT INTO CAR VALUES
(1, 'Honda',   'Civic',  2024, '1HGFE1F70RJ000001'),
(2, 'Toyota',  'Camry',  2023, '4T1K61AK9PU000002'),
(3, 'Ford',    'F-150',  2024, '1FTEW1EP5RFA00003'),
(4, 'Hyundai', 'Tucson', 2023, 'KM8JBCAL5PU000004');

INSERT INTO PART VALUES
(10, 'SYN-OIL-5W30-5Q',  'Synthetic Motor Oil 5W-30'),
(11, 'BRK-PAD-FRONT-PR', 'Premium Brake Pad Set'),
(12, 'FLT-CABIN-STD',    'Cabin Air Filter'),
(13, 'BLT-SERP-UNV',     'Serpentine Belt'),
(14, 'WPR-BLD-PAIR',     'Wiper Blade Set');

INSERT INTO SALE VALUES
(1, 1, 1, '2025-11-15', '10:30:00', 28500.00, 'Pickup'),
(2, 2, 2, '2025-11-18', '14:00:00', 35200.00, 'Delivery'),
(3, 1, 3, '2025-12-02', '11:15:00', 45900.00, 'Pickup'),
(4, 3, 4, '2025-12-10', '09:45:00', 32100.00, 'Pickup');

INSERT INTO SALE_ITEM VALUES
(1, 1, 1, 1, 28500.00),
(2, 2, 2, 1, 35200.00),
(3, 3, 3, 1, 45900.00),
(4, 4, 4, 1, 32100.00);

INSERT INTO PAYMENT VALUES
(1, 1, 28500.00, '2025-11-15', '10:45:00', 'Certified Check', 'CHK-2025-00441'),
(2, 2,  5200.00, '2025-11-18', '14:30:00', 'Debit Card',      'TXN-2025-08832'),
(3, 3, 10000.00, '2025-12-02', '11:30:00', 'Wire Transfer',   'WIR-2025-01193'),
(4, 4, 32100.00, '2025-12-10', '10:00:00', 'Cashier Check',   'CHK-2025-00587');

INSERT INTO LOAN VALUES
(1, 2, 30000.00, 'Chase Auto Finance', 60, 0.0549, 'Approved', 573.42),
(2, 3, 35900.00, 'Capital One Auto',   72, 0.0625, 'Approved', 598.33);

INSERT INTO APPOINTMENT VALUES
(1, 1, 1, 1, '2026-02-10', '09:00:00', 'Oil Change',         'Completed', 4),
(2, 2, 2, 2, '2026-02-15', '10:30:00', 'Brake Inspection',   'Completed', 2),
(3, 3, 3, 1, '2026-03-01', '08:00:00', 'General Inspection', 'Scheduled', 4),
(4, 1, 1, 1, '2026-03-20', '13:00:00', 'Wiper Replacement',  'Confirmed', 4);

INSERT INTO REPAIR VALUES
(1, 1, 4, 'Completed',   49.99),
(2, 2, 2, 'Completed',  189.00),
(3, 4, 4, 'In Progress', 35.00);

INSERT INTO REPAIR_PRODUCT VALUES
(1, 10, 1),
(1, 12, 1),
(2, 11, 1),
(3, 14, 1);

INSERT INTO INVENTORY VALUES
(1,  1, 10, 25, 10),
(2,  1, 11, 12,  5),
(3,  1, 12, 30,  8),
(4,  1, 13,  8,  4),
(5,  1, 14, 15,  6),
(6,  2, 10, 18, 10),
(7,  2, 11,  6,  5),
(8,  2, 12, 22,  8),
(9,  3, 10, 20, 10),
(10, 3, 13,  3,  4);

-- End of bootstrap file. Run your own verification queries separately.

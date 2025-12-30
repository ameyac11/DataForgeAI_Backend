-- Telecommunications Usage Database
-- Database for telecom usage data with call records, data usage, and customer billing information

-- Create database
CREATE DATABASE IF NOT EXISTS telecommunications_usage;
USE telecommunications_usage;

-- Create customers table
CREATE TABLE customers (
    customer_id VARCHAR(20) PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    phone_number VARCHAR(15) UNIQUE NOT NULL,
    email VARCHAR(100),
    address VARCHAR(200),
    city VARCHAR(50),
    state VARCHAR(20),
    zip_code VARCHAR(10),
    account_type ENUM('Prepaid', 'Postpaid') NOT NULL,
    plan_id VARCHAR(20),
    activation_date DATE,
    status ENUM('Active', 'Suspended', 'Terminated') DEFAULT 'Active'
);

-- Create service_plans table
CREATE TABLE service_plans (
    plan_id VARCHAR(20) PRIMARY KEY,
    plan_name VARCHAR(100) NOT NULL,
    monthly_fee DECIMAL(10,2),
    data_allowance_gb INT,
    voice_minutes INT,
    text_messages INT,
    international_included BOOLEAN DEFAULT FALSE
);

-- Create call_records table
CREATE TABLE call_records (
    call_id VARCHAR(30) PRIMARY KEY,
    customer_id VARCHAR(20),
    call_type ENUM('Voice', 'Video', 'Conference') NOT NULL,
    direction ENUM('Outbound', 'Inbound') NOT NULL,
    destination_number VARCHAR(15),
    call_date DATE,
    call_time TIME,
    duration_seconds INT,
    cost DECIMAL(8,4),
    tower_id VARCHAR(10),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

-- Create data_usage table
CREATE TABLE data_usage (
    usage_id VARCHAR(30) PRIMARY KEY,
    customer_id VARCHAR(20),
    usage_date DATE,
    data_used_mb DECIMAL(10,2),
    app_category VARCHAR(50),
    session_duration_minutes INT,
    tower_id VARCHAR(10),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

-- Create billing_records table
CREATE TABLE billing_records (
    bill_id VARCHAR(25) PRIMARY KEY,
    customer_id VARCHAR(20),
    billing_period_start DATE,
    billing_period_end DATE,
    base_charges DECIMAL(10,2),
    overage_charges DECIMAL(10,2),
    taxes DECIMAL(8,2),
    total_amount DECIMAL(10,2),
    due_date DATE,
    payment_status ENUM('Paid', 'Pending', 'Overdue') DEFAULT 'Pending',
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

-- Insert sample data

-- Sample service plans
INSERT INTO service_plans VALUES
('PLAN-001', 'Basic Mobile', 29.99, 2, 500, 1000, FALSE),
('PLAN-002', 'Standard Mobile', 49.99, 8, 1000, 2000, FALSE),
('PLAN-003', 'Premium Mobile', 79.99, 25, 2000, 5000, TRUE),
('PLAN-004', 'Unlimited Pro', 99.99, -1, -1, -1, TRUE),
('PLAN-005', 'Family Share', 159.99, 50, 3000, 10000, TRUE);

-- Sample customers
INSERT INTO customers VALUES
('CUST-001', 'John', 'Smith', '+1-555-0101', 'john.smith@email.com', '123 Main St', 'New York', 'NY', '10001', 'Postpaid', 'PLAN-002', '2023-06-15', 'Active'),
('CUST-002', 'Sarah', 'Johnson', '+1-555-0102', 'sarah.j@email.com', '456 Oak Ave', 'Los Angeles', 'CA', '90210', 'Postpaid', 'PLAN-003', '2023-08-22', 'Active'),
('CUST-003', 'Mike', 'Brown', '+1-555-0103', 'mike.brown@email.com', '789 Pine Rd', 'Chicago', 'IL', '60601', 'Prepaid', 'PLAN-001', '2023-09-10', 'Active'),
('CUST-004', 'Emily', 'Davis', '+1-555-0104', 'emily.davis@email.com', '321 Elm St', 'Houston', 'TX', '77001', 'Postpaid', 'PLAN-004', '2023-05-03', 'Active'),
('CUST-005', 'David', 'Wilson', '+1-555-0105', 'david.w@email.com', '654 Maple Dr', 'Phoenix', 'AZ', '85001', 'Postpaid', 'PLAN-002', '2023-07-18', 'Suspended');

-- Sample call records
INSERT INTO call_records VALUES
('CALL-001', 'CUST-001', 'Voice', 'Outbound', '+1-555-9876', '2024-02-01', '09:15:30', 180, 0.25, 'TOWER-101'),
('CALL-002', 'CUST-001', 'Voice', 'Inbound', '+1-555-5432', '2024-02-01', '14:22:15', 95, 0.00, 'TOWER-101'),
('CALL-003', 'CUST-002', 'Video', 'Outbound', '+1-555-1234', '2024-02-01', '19:45:00', 1200, 1.50, 'TOWER-205'),
('CALL-004', 'CUST-003', 'Voice', 'Outbound', '+1-555-7890', '2024-02-02', '08:30:45', 240, 0.35, 'TOWER-308'),
('CALL-005', 'CUST-004', 'Conference', 'Outbound', '+1-555-2468', '2024-02-02', '11:15:20', 2700, 3.25, 'TOWER-412');

-- Sample data usage
INSERT INTO data_usage VALUES
('DATA-001', 'CUST-001', '2024-02-01', 125.50, 'Social Media', 45, 'TOWER-101'),
('DATA-002', 'CUST-001', '2024-02-01', 89.25, 'Video Streaming', 120, 'TOWER-101'),
('DATA-003', 'CUST-002', '2024-02-01', 256.75, 'Gaming', 180, 'TOWER-205'),
('DATA-004', 'CUST-003', '2024-02-02', 45.80, 'Web Browsing', 30, 'TOWER-308'),
('DATA-005', 'CUST-004', '2024-02-02', 512.25, 'Video Streaming', 240, 'TOWER-412');

-- Sample billing records
INSERT INTO billing_records VALUES
('BILL-001', 'CUST-001', '2024-01-01', '2024-01-31', 49.99, 5.25, 4.89, 60.13, '2024-02-15', 'Paid'),
('BILL-002', 'CUST-002', '2024-01-01', '2024-01-31', 79.99, 0.00, 7.20, 87.19, '2024-02-15', 'Pending'),
('BILL-003', 'CUST-003', '2024-01-01', '2024-01-31', 29.99, 2.50, 2.92, 35.41, '2024-02-15', 'Paid'),
('BILL-004', 'CUST-004', '2024-01-01', '2024-01-31', 99.99, 0.00, 9.00, 108.99, '2024-02-15', 'Overdue'),
('BILL-005', 'CUST-005', '2024-01-01', '2024-01-31', 49.99, 15.75, 5.92, 71.66, '2024-02-15', 'Overdue');

-- Financial Records Dataset
-- Financial transaction data with accounts, budgets, expenses, and revenue tracking
-- Format: SQL
-- Rows: 3000
-- Category: Finance
-- Size: 4.2 MB
-- Last Updated: 2024-01-25
-- Version: 1.0

CREATE DATABASE IF NOT EXISTS finance_db;
USE finance_db;

-- Create tables
CREATE TABLE accounts (
    account_id INT PRIMARY KEY AUTO_INCREMENT,
    account_number VARCHAR(20) UNIQUE NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    account_type ENUM('Asset', 'Liability', 'Equity', 'Revenue', 'Expense'),
    parent_account_id INT,
    is_active BOOLEAN DEFAULT TRUE,
    created_date DATE,
    balance DECIMAL(15,2) DEFAULT 0.00
);

CREATE TABLE transactions (
    transaction_id INT PRIMARY KEY AUTO_INCREMENT,
    transaction_date DATE NOT NULL,
    reference_number VARCHAR(50),
    description TEXT,
    total_amount DECIMAL(15,2) NOT NULL,
    transaction_type ENUM('Income', 'Expense', 'Transfer'),
    category VARCHAR(50),
    subcategory VARCHAR(50),
    payment_method VARCHAR(30),
    vendor_id INT,
    project_id INT,
    department_id INT,
    created_by INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE transaction_entries (
    entry_id INT PRIMARY KEY AUTO_INCREMENT,
    transaction_id INT,
    account_id INT,
    debit_amount DECIMAL(15,2) DEFAULT 0.00,
    credit_amount DECIMAL(15,2) DEFAULT 0.00,
    description VARCHAR(255),
    FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id),
    FOREIGN KEY (account_id) REFERENCES accounts(account_id)
);

CREATE TABLE budgets (
    budget_id INT PRIMARY KEY AUTO_INCREMENT,
    budget_name VARCHAR(100) NOT NULL,
    fiscal_year YEAR,
    department_id INT,
    category VARCHAR(50),
    budgeted_amount DECIMAL(15,2),
    actual_amount DECIMAL(15,2) DEFAULT 0.00,
    variance DECIMAL(15,2) DEFAULT 0.00,
    status ENUM('Draft', 'Approved', 'Active', 'Closed'),
    created_date DATE
);

CREATE TABLE vendors (
    vendor_id INT PRIMARY KEY AUTO_INCREMENT,
    vendor_name VARCHAR(100) NOT NULL,
    vendor_code VARCHAR(20) UNIQUE,
    contact_person VARCHAR(100),
    email VARCHAR(100),
    phone VARCHAR(20),
    address TEXT,
    tax_id VARCHAR(50),
    payment_terms VARCHAR(50),
    is_active BOOLEAN DEFAULT TRUE
);

-- Insert sample data
INSERT INTO accounts (account_number, account_name, account_type, balance, created_date) VALUES
('1000', 'Cash', 'Asset', 125000.00, '2023-01-01'),
('1100', 'Accounts Receivable', 'Asset', 45000.00, '2023-01-01'),
('1200', 'Inventory', 'Asset', 75000.00, '2023-01-01'),
('2000', 'Accounts Payable', 'Liability', 32000.00, '2023-01-01'),
('2100', 'Short-term Debt', 'Liability', 50000.00, '2023-01-01'),
('3000', 'Owner\'s Equity', 'Equity', 163000.00, '2023-01-01'),
('4000', 'Sales Revenue', 'Revenue', 0.00, '2023-01-01'),
('5000', 'Cost of Goods Sold', 'Expense', 0.00, '2023-01-01'),
('6000', 'Operating Expenses', 'Expense', 0.00, '2023-01-01'),
('6100', 'Salaries and Wages', 'Expense', 0.00, '2023-01-01');

INSERT INTO vendors (vendor_name, vendor_code, contact_person, email, phone, payment_terms) VALUES
('TechSupply Corp', 'TECH001', 'John Smith', 'john@techsupply.com', '+1-555-1001', 'Net 30'),
('Office Solutions Ltd', 'OFF001', 'Sarah Johnson', 'sarah@officesol.com', '+1-555-1002', 'Net 15'),
('Marketing Partners', 'MKT001', 'Mike Davis', 'mike@mktpartners.com', '+1-555-1003', 'Net 30'),
('Utilities Company', 'UTIL001', 'Admin', 'billing@utilities.com', '+1-555-1004', 'Due on Receipt'),
('Legal Services Inc', 'LEG001', 'Jennifer Brown', 'jennifer@legalserv.com', '+1-555-1005', 'Net 15');

INSERT INTO transactions (transaction_date, reference_number, description, total_amount, transaction_type, category, payment_method, vendor_id) VALUES
('2024-01-15', 'TXN-001', 'Product Sales - January Week 2', 15000.00, 'Income', 'Sales', 'Bank Transfer', NULL),
('2024-01-16', 'TXN-002', 'Office Supplies Purchase', 850.00, 'Expense', 'Office Expenses', 'Credit Card', 2),
('2024-01-17', 'TXN-003', 'Monthly Salary Payment', 12000.00, 'Expense', 'Payroll', 'Bank Transfer', NULL),
('2024-01-18', 'TXN-004', 'Marketing Campaign Payment', 3500.00, 'Expense', 'Marketing', 'Check', 3),
('2024-01-19', 'TXN-005', 'Utility Bills - January', 1200.00, 'Expense', 'Utilities', 'Online Payment', 4),
('2024-01-20', 'TXN-006', 'Product Sales - Bulk Order', 25000.00, 'Income', 'Sales', 'Wire Transfer', NULL),
('2024-01-21', 'TXN-007', 'Legal Consultation Fees', 2800.00, 'Expense', 'Professional Services', 'Check', 5),
('2024-01-22', 'TXN-008', 'Equipment Purchase', 8500.00, 'Expense', 'Capital Expenditure', 'Bank Transfer', 1);

INSERT INTO transaction_entries (transaction_id, account_id, debit_amount, credit_amount, description) VALUES
-- Sales transaction
(1, 1, 15000.00, 0.00, 'Cash received from sales'),
(1, 7, 0.00, 15000.00, 'Sales revenue'),
-- Office supplies
(2, 9, 850.00, 0.00, 'Office supplies expense'),
(2, 1, 0.00, 850.00, 'Cash payment'),
-- Salary payment
(3, 10, 12000.00, 0.00, 'Salary expense'),
(3, 1, 0.00, 12000.00, 'Cash payment'),
-- Marketing payment
(4, 9, 3500.00, 0.00, 'Marketing expense'),
(4, 1, 0.00, 3500.00, 'Cash payment'),
-- Utility bills
(5, 9, 1200.00, 0.00, 'Utility expense'),
(5, 1, 0.00, 1200.00, 'Cash payment');

INSERT INTO budgets (budget_name, fiscal_year, category, budgeted_amount, actual_amount, status, created_date) VALUES
('Sales Revenue Budget 2024', 2024, 'Revenue', 500000.00, 40000.00, 'Active', '2024-01-01'),
('Marketing Budget 2024', 2024, 'Marketing', 45000.00, 3500.00, 'Active', '2024-01-01'),
('Payroll Budget 2024', 2024, 'Payroll', 180000.00, 12000.00, 'Active', '2024-01-01'),
('Office Expenses Budget 2024', 2024, 'Operations', 25000.00, 850.00, 'Active', '2024-01-01'),
('Capital Expenditure Budget 2024', 2024, 'CapEx', 75000.00, 8500.00, 'Active', '2024-01-01');

-- Sales Transactions Dataset
-- Complete e-commerce sales data including customer details, products, orders, and revenue analytics
-- Format: SQL
-- Rows: 2500
-- Category: Sales
-- Size: 5.1 MB
-- Last Updated: 2024-01-20
-- Version: 1.0

CREATE DATABASE IF NOT EXISTS sales_db;
USE sales_db;

-- Create tables
CREATE TABLE customers (
    customer_id INT PRIMARY KEY AUTO_INCREMENT,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    phone VARCHAR(20),
    address TEXT,
    city VARCHAR(50),
    state VARCHAR(50),
    zip_code VARCHAR(10),
    country VARCHAR(50) DEFAULT 'USA',
    registration_date DATE,
    customer_segment VARCHAR(20)
);

CREATE TABLE products (
    product_id INT PRIMARY KEY AUTO_INCREMENT,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    subcategory VARCHAR(50),
    brand VARCHAR(50),
    unit_price DECIMAL(10,2),
    cost DECIMAL(10,2),
    stock_quantity INT,
    supplier_id INT,
    created_date DATE
);

CREATE TABLE orders (
    order_id INT PRIMARY KEY AUTO_INCREMENT,
    customer_id INT,
    order_date DATE,
    ship_date DATE,
    ship_mode VARCHAR(20),
    order_priority VARCHAR(10),
    order_status VARCHAR(20),
    total_amount DECIMAL(10,2),
    discount_amount DECIMAL(10,2),
    profit DECIMAL(10,2),
    FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
    order_item_id INT PRIMARY KEY AUTO_INCREMENT,
    order_id INT,
    product_id INT,
    quantity INT,
    unit_price DECIMAL(10,2),
    discount DECIMAL(5,2),
    total_price DECIMAL(10,2),
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- Insert sample data
INSERT INTO customers (first_name, last_name, email, phone, address, city, state, zip_code, registration_date, customer_segment) VALUES
('Alice', 'Brown', 'alice.brown@email.com', '+1-555-1001', '123 Market St', 'New York', 'NY', '10001', '2023-01-15', 'Premium'),
('Bob', 'Taylor', 'bob.taylor@email.com', '+1-555-1002', '456 Broadway', 'Los Angeles', 'CA', '90001', '2023-02-20', 'Standard'),
('Carol', 'Anderson', 'carol.anderson@email.com', '+1-555-1003', '789 Fifth Ave', 'Chicago', 'IL', '60601', '2023-03-10', 'Premium'),
('Daniel', 'Martinez', 'daniel.martinez@email.com', '+1-555-1004', '321 Main St', 'Houston', 'TX', '77001', '2023-04-05', 'Standard'),
('Emma', 'Garcia', 'emma.garcia@email.com', '+1-555-1005', '654 Oak St', 'Phoenix', 'AZ', '85001', '2023-05-12', 'Gold');

INSERT INTO products (product_name, category, subcategory, brand, unit_price, cost, stock_quantity, supplier_id, created_date) VALUES
('Wireless Headphones', 'Electronics', 'Audio', 'TechBrand', 199.99, 120.00, 150, 1001, '2023-01-01'),
('Smartphone Case', 'Electronics', 'Accessories', 'ProtectPro', 29.99, 15.00, 500, 1002, '2023-01-01'),
('Laptop Stand', 'Office', 'Furniture', 'ErgoDesk', 89.99, 45.00, 75, 1003, '2023-01-01'),
('Coffee Mug', 'Home', 'Kitchen', 'BrewMaster', 19.99, 8.00, 200, 1004, '2023-01-01'),
('Running Shoes', 'Sports', 'Footwear', 'RunFast', 129.99, 70.00, 100, 1005, '2023-01-01');

INSERT INTO orders (customer_id, order_date, ship_date, ship_mode, order_priority, order_status, total_amount, discount_amount, profit) VALUES
(1, '2023-06-01', '2023-06-03', 'Express', 'High', 'Delivered', 229.98, 0.00, 89.98),
(2, '2023-06-02', '2023-06-05', 'Standard', 'Medium', 'Delivered', 89.99, 9.00, 35.99),
(3, '2023-06-03', '2023-06-06', 'Express', 'High', 'Delivered', 149.98, 15.00, 54.98),
(4, '2023-06-04', '2023-06-07', 'Standard', 'Low', 'Shipped', 19.99, 0.00, 11.99),
(5, '2023-06-05', '2023-06-08', 'Express', 'High', 'Processing', 159.98, 16.00, 73.98);

INSERT INTO order_items (order_id, product_id, quantity, unit_price, discount, total_price) VALUES
(1, 1, 1, 199.99, 0.00, 199.99),
(1, 2, 1, 29.99, 0.00, 29.99),
(2, 3, 1, 89.99, 10.00, 89.99),
(3, 1, 1, 199.99, 10.00, 199.99),
(3, 4, 1, 19.99, 0.00, 19.99),
(4, 4, 1, 19.99, 0.00, 19.99),
(5, 5, 1, 129.99, 10.00, 129.99),
(5, 2, 1, 29.99, 0.00, 29.99);

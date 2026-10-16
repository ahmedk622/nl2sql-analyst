DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
  customer_id INT PRIMARY KEY,
  name        VARCHAR(80)  NOT NULL,
  email       VARCHAR(120) NOT NULL,
  city        VARCHAR(40)  NOT NULL,
  country     VARCHAR(30)  NOT NULL,
  segment     VARCHAR(20)  NOT NULL COMMENT 'Consumer, SMB or Enterprise',
  signup_date DATE         NOT NULL
);

CREATE TABLE products (
  product_id INT PRIMARY KEY,
  name       VARCHAR(80)   NOT NULL,
  category   VARCHAR(40)   NOT NULL,
  price      DECIMAL(10,2) NOT NULL COMMENT 'list price',
  cost       DECIMAL(10,2) NOT NULL COMMENT 'unit cost to the company'
);

CREATE TABLE orders (
  order_id    INT PRIMARY KEY,
  customer_id INT         NOT NULL,
  order_date  DATE        NOT NULL,
  status      VARCHAR(20) NOT NULL COMMENT 'completed, cancelled, returned or pending',
  channel     VARCHAR(20) NOT NULL COMMENT 'sales channel',
  FOREIGN KEY (customer_id) REFERENCES customers(customer_id)
);

CREATE TABLE order_items (
  item_id      INT PRIMARY KEY,
  order_id     INT           NOT NULL,
  product_id   INT           NOT NULL,
  quantity     INT           NOT NULL,
  unit_price   DECIMAL(10,2) NOT NULL COMMENT 'price actually charged per unit',
  discount_pct INT           NOT NULL COMMENT 'discount percentage, 0-100',
  FOREIGN KEY (order_id)   REFERENCES orders(order_id),
  FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE INDEX idx_orders_date ON orders(order_date);
CREATE INDEX idx_orders_customer ON orders(customer_id);
CREATE INDEX idx_items_order ON order_items(order_id);

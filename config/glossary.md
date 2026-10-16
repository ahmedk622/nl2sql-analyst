# Business definitions (the model must follow these)

- **Net revenue** = SUM(order_items.quantity * order_items.unit_price * (1 - order_items.discount_pct / 100)), counting ONLY orders with orders.status = 'completed'.
- **Gross profit** = net revenue - SUM(order_items.quantity * products.cost), with the same completed-order filter.
- **Average order value (AOV)** = net revenue / COUNT(DISTINCT orders.order_id) over completed orders.
- **Cancellation rate** = cancelled orders / all orders (all statuses).
- **Active customer** = a customer with at least one completed order.
- Unless the question says otherwise, "revenue" means net revenue.
- Order data covers 2024-01-01 to 2025-12-31. "H1" = Jan-Jun, "H2" = Jul-Dec.
- Order statuses: completed, cancelled, returned, pending.

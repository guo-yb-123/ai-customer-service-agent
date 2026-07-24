-- 1. 建表
CREATE TABLE IF NOT EXISTS t_order (
    id INT PRIMARY KEY AUTO_INCREMENT,
    order_no VARCHAR(50) NOT NULL,
    user_id VARCHAR(20) NOT NULL,
    goods_name VARCHAR(100) NOT NULL,
    pay_amount DECIMAL(10, 2) NOT NULL,
    order_status VARCHAR(20) NOT NULL,
    create_time DATETIME NOT NULL
);

CREATE TABLE IF NOT EXISTS t_customer (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(50) NOT NULL,
    member_level VARCHAR(50) NOT NULL,
    total_order_count INT NOT NULL,
    has_unfinished_aftersale TINYINT(1) NOT NULL,
    points INT NOT NULL,
    register_time DATETIME NOT NULL,
    phone VARCHAR(20) NOT NULL
);

CREATE TABLE IF NOT EXISTS t_goods (
    goods_id VARCHAR(20) PRIMARY KEY,
    goods_name VARCHAR(100) NOT NULL,
    price DECIMAL(10, 2) NOT NULL,
    origin_price DECIMAL(10, 2) NOT NULL,
    spec TEXT NOT NULL,
    stock INT NOT NULL,
    `desc` TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS t_logistics (
    id INT PRIMARY KEY AUTO_INCREMENT,
    tracking_no VARCHAR(50) NOT NULL,
    track_list JSON NOT NULL
);

CREATE TABLE IF NOT EXISTS t_aftersale_ticket (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(20) NOT NULL,
    session_id VARCHAR(50) NOT NULL,
    order_no VARCHAR(50) NOT NULL,
    problem_desc TEXT NOT NULL,
    create_time DATETIME NOT NULL,
    update_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ticket_status VARCHAR(20) NOT NULL
);

-- 2. 插入数据（先只插订单，验证能跑通即可）
INSERT INTO t_order (order_no, user_id, goods_name, pay_amount, order_status, create_time) VALUES
('OD202606001', 'u001', '智能电饭煲', 299.00, '已签收', '2026-06-10 10:10:00'),
('OD202606002', 'u001', '无线吸尘器', 499.00, '已签收', '2026-06-11 11:20:00'),
('OD202606003', 'u001', '电动牙刷', 129.00, '配送中', '2026-06-12 09:15:00'),
('OD202606004', 'u001', '空气净化器', 899.00, '待发货', '2026-06-13 16:40:00'),
('OD202606005', 'u001', '智能门锁', 699.00, '已签收', '2026-06-14 14:30:00'),
('OD202606006', 'u001', '破壁机', 359.00, '已签收', '2026-06-15 08:20:00'),
('OD202606007', 'u001', '恒温热水壶', 169.00, '配送中', '2026-06-15 17:10:00'),
('OD202606008', 'u001', '厨房置物架', 129.00, '待发货', '2026-06-16 10:00:00'),
('OD202606009', 'u001', '洗菜机', 459.00, '已签收', '2026-06-16 15:20:00'),
('OD202606010', 'u001', '刀具套装', 229.00, '已退货', '2026-06-17 09:40:00');
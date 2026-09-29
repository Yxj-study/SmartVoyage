DROP DATABASE IF EXISTS travel_rag;
CREATE DATABASE travel_rag CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE travel_rag;

CREATE TABLE train_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增，唯一标识每条记录',
    departure_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '出发城市（如“北京”）',
    arrival_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '到达城市（如“上海”）',
    departure_time DATETIME NOT NULL COMMENT '出发时间（如“2025-08-12 07:00:00”）',
    arrival_time DATETIME NOT NULL COMMENT '到达时间（如“2025-08-12 11:30:00”）',
    train_number VARCHAR(20) NOT NULL COMMENT '火车车次（如“G1001”）',
    seat_type VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '座位类型（如“二等座”）',
    total_seats INT NOT NULL COMMENT '总座位数（如 1000）',
    remaining_seats INT NOT NULL COMMENT '剩余座位数（如 50）',
    price DECIMAL(10, 2) NOT NULL COMMENT '票价（如 553.50）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间，自动记录插入时间',
    UNIQUE KEY unique_train (departure_time, train_number) -- 唯一约束，确保同一时间和车次不重复
) COMMENT='火车票信息表';

CREATE TABLE flight_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY COMMENT '主键，自增，唯一标识每条记录',
    departure_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '出发城市（如“北京”）',
    arrival_city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '到达城市（如“上海”）',
    departure_time DATETIME NOT NULL COMMENT '出发时间（如“2025-08-12 08:00:00”）',
    arrival_time DATETIME NOT NULL COMMENT '到达时间（如“2025-08-12 10:30:00”）',
    flight_number VARCHAR(20) NOT NULL COMMENT '航班号（如“CA1234”）',
    cabin_type VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '舱位类型（如“经济舱”）',
    total_seats INT NOT NULL COMMENT '总座位数（如 200）',
    remaining_seats INT NOT NULL COMMENT '剩余座位数（如 10）',
    price DECIMAL(10, 2) NOT NULL COMMENT '票价（如 1200.00）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间，自动记录插入时间',
    UNIQUE KEY unique_flight (departure_time, flight_number) -- 唯一约束，确保同一时间和航班号不重复
) COMMENT='航班机票信息表';

CREATE TABLE concert_tickets (
    id INT AUTO_INCREMENT PRIMARY KEY, -- 主键，自增，唯一标识每条记录
    artist VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, -- 艺人名称（如“周杰伦”）
    city VARCHAR(50) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, -- 举办城市（如“上海”）
    venue VARCHAR(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, -- 场馆（如“上海体育场”）
    start_time DATETIME NOT NULL, -- 开始时间（如“2025-08-12 19:00:00”）
    end_time DATETIME NOT NULL, -- 结束时间（如“2025-08-12 22:00:00”）
    ticket_type VARCHAR(20) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL, -- 票类型（如“VIP”）
    total_seats INT NOT NULL, -- 总座位数（如 5000）
    remaining_seats INT NOT NULL, -- 剩余座位数（如 100）
    price DECIMAL(10, 2) NOT NULL, -- 票价（如 880.00）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, -- 创建时间，自动记录插入时间
    UNIQUE KEY unique_concert (start_time, artist, ticket_type) -- 唯一约束，确保同一时间、艺人和票类型不重复
);


DROP TABLE IF EXISTS weather_data;
CREATE TABLE IF NOT EXISTS weather_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    city VARCHAR(50) NOT NULL COMMENT '城市名称',
    fx_date DATE NOT NULL COMMENT '预报日期',
    sunrise TIME COMMENT '日出时间',
    sunset TIME COMMENT '日落时间',
    moonrise TIME COMMENT '月升时间',
    moonset TIME COMMENT '月落时间',
    moon_phase VARCHAR(20) COMMENT '月相名称',
    moon_phase_icon VARCHAR(10) COMMENT '月相图标代码',
    temp_max INT COMMENT '最高温度',
    temp_min INT COMMENT '最低温度',
    icon_day VARCHAR(10) COMMENT '白天天气图标代码',
    text_day VARCHAR(20) COMMENT '白天天气描述',
    icon_night VARCHAR(10) COMMENT '夜间天气图标代码',
    text_night VARCHAR(20) COMMENT '夜间天气描述',
    wind360_day INT COMMENT '白天风向360角度',
    wind_dir_day VARCHAR(20) COMMENT '白天风向',
    wind_scale_day VARCHAR(10) COMMENT '白天风力等级',
    wind_speed_day INT COMMENT '白天风速 (km/h)',
    wind360_night INT COMMENT '夜间风向360角度',
    wind_dir_night VARCHAR(20) COMMENT '夜间风向',
    wind_scale_night VARCHAR(10) COMMENT '夜间风力等级',
    wind_speed_night INT COMMENT '夜间风速 (km/h)',
    precip DECIMAL(5,1) COMMENT '降水量 (mm)',
    uv_index INT COMMENT '紫外线指数',
    humidity INT COMMENT '相对湿度 (%)',
    pressure INT COMMENT '大气压强 (hPa)',
    vis INT COMMENT '能见度 (km)',
    cloud INT COMMENT '云量 (%)',
    update_time DATETIME COMMENT '数据更新时间',
    UNIQUE KEY unique_city_date (city, fx_date)
) ENGINE=INNODB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='天气数据表';


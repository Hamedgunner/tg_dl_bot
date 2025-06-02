-- BEFORE running this, manually create the database and user with appropriate encoding.
-- For example in MariaDB/MySQL cli:
-- CREATE DATABASE telegram_bot CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- CREATE USER 'bot_user'@'localhost' IDENTIFIED BY 'YOUR_STRONG_PASSWORD';
-- GRANT ALL PRIVILEGES ON telegram_bot.* TO 'bot_user'@'localhost';
-- FLUSH PRIVILEGES;

USE telegram_bot;

-- جدول کاربران ربات
CREATE TABLE IF NOT EXISTS `users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `telegram_id` BIGINT UNIQUE NOT NULL,
    `first_name` VARCHAR(255) DEFAULT NULL,
    `last_name` VARCHAR(255) DEFAULT NULL,
    `username` VARCHAR(255) DEFAULT NULL,
    `language_code` VARCHAR(10) DEFAULT NULL,
    `is_bot` BOOLEAN DEFAULT FALSE,
    `is_blocked` BOOLEAN DEFAULT FALSE,
    `current_state` VARCHAR(255) DEFAULT 'idle', -- برای مدیریت مراحل گفتگو (مثلا 'waiting_for_link')
    `last_activity` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `joined_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- جدول لاگ دانلودها
CREATE TABLE IF NOT EXISTS `downloads` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT, -- ID از جدول users
    `telegram_user_id` BIGINT NOT NULL,
    `platform` VARCHAR(50) NOT NULL, -- 'tiktok', 'instagram', 'youtube', 'x', 'generic'
    `url` TEXT NOT NULL,
    `status` ENUM('pending', 'downloading', 'completed', 'failed', 'file_sent', 'too_large') DEFAULT 'pending',
    `file_path` TEXT DEFAULT NULL, -- مسیر فایل دانلود شده روی سرور (موقت)
    `file_size_bytes` BIGINT DEFAULT NULL,
    `error_message` TEXT DEFAULT NULL,
    `downloaded_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- جدول تنظیمات ربات
CREATE TABLE IF NOT EXISTS `bot_settings` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `setting_key` VARCHAR(255) UNIQUE NOT NULL,
    `setting_value` TEXT NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO `bot_settings` (`setting_key`, `setting_value`) VALUES
('button_tiktok_enabled', 'true'),
('button_instagram_enabled', 'true'),
('button_youtube_enabled', 'true'),
('button_x_enabled', 'true'),
('button_generic_enabled', 'true'),
('force_subscribe_enabled', 'false')
ON DUPLICATE KEY UPDATE `setting_value` = `setting_value`;


-- جدول کانال‌های قفل‌دار (برای اجبار به عضویت)
CREATE TABLE IF NOT EXISTS `locked_channels` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `channel_id` BIGINT UNIQUE NOT NULL, -- Changed to BIGINT to handle negative channel IDs
    `channel_name` VARCHAR(255) NOT NULL,
    `channel_link` VARCHAR(255) DEFAULT NULL,
    `is_active` BOOLEAN DEFAULT TRUE,
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- جدول ادمین‌های پنل مدیریت
CREATE TABLE IF NOT EXISTS `admin_users` (
    `id` INT AUTO_INCREMENT PRIMARY KEY,
    `username` VARCHAR(255) UNIQUE NOT NULL,
    `password_hash` VARCHAR(255) NOT NULL,
    `is_super_admin` BOOLEAN DEFAULT FALSE,
    `telegram_user_id` BIGINT UNIQUE DEFAULT NULL, -- Added Telegram User ID for notifications
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
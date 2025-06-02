import mysql.connector
from mysql.connector import Error
import os
from dotenv import load_dotenv

# Load environment variables (usually for local development or when called directly)
# In production via gunicorn/supervisor, they should already be loaded.
load_dotenv() 

class Database:
    def __init__(self):
        self.host = os.getenv('DB_HOST')
        self.user = os.getenv('DB_USER')
        self.password = os.getenv('DB_PASSWORD')
        self.database = os.getenv('DB_NAME')
        self.connection = None

    def connect(self):
        try:
            self.connection = mysql.connector.connect(
                host=self.host,
                user=self.user,
                password=self.password,
                database=self.database
            )
            if self.connection and self.connection.is_connected():
                # print("Connected to MySQL database") # Can be uncommented for debugging
                pass
        except Error as e:
            print(f"Error connecting to MySQL database: {e}")
            self.connection = None

    def close(self):
        if self.connection and self.connection.is_connected():
            self.connection.close()
            # print("MySQL connection closed") # Can be uncommented for debugging

    def execute_query(self, query, params=None, fetch=False, commit=False):
        try:
            self.connect()
            if not self.connection:
                print("Database connection not established. Cannot execute query.")
                return None

            cursor = self.connection.cursor(buffered=True, dictionary=True)
            cursor.execute(query, params)
            if commit:
                self.connection.commit()
            result = cursor.fetchall() if fetch else None
            cursor.close()
            return result
        except Error as e:
            print(f"Error executing query: {e}")
            if self.connection:
                self.connection.rollback()
            return None
        finally:
            self.close()

    # --- User Operations ---
    def get_user(self, telegram_id):
        query = "SELECT * FROM users WHERE telegram_id = %s"
        result = self.execute_query(query, (telegram_id,), fetch=True)
        return result[0] if result else None

    def add_or_update_user(self, user_data):
        telegram_id = user_data.id
        first_name = user_data.first_name
        last_name = user_data.last_name
        username = user_data.username
        language_code = user_data.language_code if hasattr(user_data, 'language_code') else None
        is_bot = user_data.is_bot

        existing_user = self.get_user(telegram_id)
        if existing_user:
            query = """
                UPDATE users SET first_name=%s, last_name=%s, username=%s,
                language_code=%s, is_bot=%s, last_activity=NOW() WHERE telegram_id=%s
            """
            params = (first_name, last_name, username, language_code, is_bot, telegram_id)
            self.execute_query(query, params, commit=True)
            return existing_user['id']
        else:
            query = """
                INSERT INTO users (telegram_id, first_name, last_name, username, language_code, is_bot)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            params = (telegram_id, first_name, last_name, username, language_code, is_bot)
            self.execute_query(query, params, commit=True)
            # Fetch the newly inserted user ID
            new_user = self.get_user(telegram_id)
            return new_user['id'] if new_user else None


    def update_user_state(self, telegram_id, state):
        query = "UPDATE users SET current_state = %s WHERE telegram_id = %s"
        self.execute_query(query, (state, telegram_id), commit=True)
    
    def set_user_blocked_status(self, telegram_id, is_blocked):
        query = "UPDATE users SET is_blocked = %s WHERE telegram_id = %s"
        self.execute_query(query, (is_blocked,), commit=True)

    # --- Download Log Operations ---
    def add_download_log(self, user_id, telegram_user_id, platform, url, status, file_path=None, file_size_bytes=None, error_message=None):
        query = """
            INSERT INTO downloads
            (user_id, telegram_user_id, platform, url, status, file_path, file_size_bytes, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (user_id, telegram_user_id, platform, url, status, file_path, file_size_bytes, error_message)
        self.execute_query(query, params, commit=True)

    # --- Settings Operations ---
    def get_setting(self, key):
        query = "SELECT setting_value FROM bot_settings WHERE setting_key = %s"
        result = self.execute_query(query, (key,), fetch=True)
        return result[0]['setting_value'] if result else None

    def update_setting(self, key, value):
        query = "UPDATE bot_settings SET setting_value = %s WHERE setting_key = %s"
        self.execute_query(query, (value,), commit=True)

    # --- Locked Channels Operations ---
    def get_locked_channels(self, active_only=True):
        query = "SELECT * FROM locked_channels"
        if active_only:
            query += " WHERE is_active = TRUE"
        return self.execute_query(query, fetch=True)

    def add_locked_channel(self, channel_id, channel_name, channel_link):
        query = "INSERT INTO locked_channels (channel_id, channel_name, channel_link) VALUES (%s, %s, %s)"
        params = (channel_id, channel_name, channel_link)
        self.execute_query(query, params, commit=True)

    def remove_locked_channel(self, channel_id):
        query = "DELETE FROM locked_channels WHERE channel_id = %s"
        self.execute_query(query, (channel_id,), commit=True)

    def is_force_subscribe_enabled(self):
        value = self.get_setting('force_subscribe_enabled')
        return value == 'true'
    
    # Admin User Operations
    def get_admin_user_by_username(self, username):
        query = "SELECT * FROM admin_users WHERE username = %s"
        result = self.execute_query(query, (username,), fetch=True)
        return result[0] if result else None
        
    def add_admin_user(self, username, password_hash, is_super_admin=False, telegram_user_id=None):
        query = """
            INSERT INTO admin_users (username, password_hash, is_super_admin, telegram_user_id)
            VALUES (%s, %s, %s, %s)
        """
        params = (username, password_hash, is_super_admin, telegram_user_id)
        self.execute_query(query, params, commit=True)

    def get_all_admin_users(self):
        query = "SELECT id, username, is_super_admin, telegram_user_id, created_at FROM admin_users"
        return self.execute_query(query, fetch=True)

    def delete_admin_user(self, admin_id):
        query = "DELETE FROM admin_users WHERE id = %s"
        self.execute_query(query, (admin_id,), commit=True)
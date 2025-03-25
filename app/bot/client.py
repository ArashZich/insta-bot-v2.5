import json
import os
import time
import random
from pathlib import Path
from sqlalchemy.orm import Session
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError, PleaseWaitFewMinutes, ClientError, ClientLoginRequired

from app.config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, SESSION_FILE
from app.models.database import BotSession
from app.logger import setup_logger

# Setup logger
logger = setup_logger("instagram_client")


class InstagramClient:
    def __init__(self, db: Session):
        # افزایش تایم‌اوت به 120 ثانیه
        self.client = Client(request_timeout=120)
        self.db = db
        self.logged_in = False
        self.last_login_attempt = None
        self.login_retry_count = 0

        # تنظیمات کاستوم برای بهبود استفاده از API
        self.client.delay_range = [10, 20]  # تاخیر بین درخواست‌ها
        self.client.request_timeout = 60

    def login(self, force=False):
        """Login to Instagram account using session or credentials"""
        logger.info(f"Attempting to login as {INSTAGRAM_USERNAME}")

        # بررسی وجود نام کاربری و رمز عبور
        if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
            logger.error(
                "Instagram username or password not set in environment variables")
            return False

        # همیشه تنظیمات قبلی رو پاک کنیم
        self.client.settings = {}
        self.client.cookie = {}
        logger.info("Cleared previous settings and cookies for fresh login")

        # افزودن تاخیر قبل از لاگین برای جلوگیری از محدودیت‌ها
        wait_time = random.randint(20, 40)
        logger.info(f"Waiting {wait_time} seconds before login attempt...")
        time.sleep(wait_time)

        try:
            # ورود با نام کاربری و رمز عبور
            if INSTAGRAM_PASSWORD.startswith('$enc'):
                # در حالتی که رمز به صورت رمزگذاری شده ذخیره شده باشد
                # حذف $enc از ابتدای رمز
                password = INSTAGRAM_PASSWORD[4:]
                logger.info("Using encrypted password format")
            else:
                password = INSTAGRAM_PASSWORD

            logger.info("Login with username and password")
            self.logged_in = self.client.login(INSTAGRAM_USERNAME, password)

            if self.logged_in:
                logger.info("Successfully logged in with credentials")
                # ذخیره جلسه
                self._save_session()
                return True
            else:
                logger.error("Failed to login with credentials")
                # تلاش مجدد بعد از یک تاخیر
                time.sleep(60)

                # تلاش مجدد با تنظیمات تازه
                self.client = Client(request_timeout=120)
                self.client.delay_range = [10, 20]
                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password)

                if self.logged_in:
                    logger.info("Successfully logged in on second attempt")
                    self._save_session()
                    return True

                return False

        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            time.sleep(60)  # یک دقیقه صبر کنیم و دوباره تلاش کنیم

            try:
                # ایجاد یک نمونه جدید از کلاینت
                self.client = Client(request_timeout=120)
                self.client.delay_range = [10, 20]

                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password)
                if self.logged_in:
                    logger.info("Successfully logged in after error retry")
                    self._save_session()
                    return True
                else:
                    return False
            except Exception as retry_error:
                logger.error(f"Error during retry login: {str(retry_error)}")
                return False

        except (ClientLoginRequired, LoginRequired) as e:
            logger.error(f"Login required error: {str(e)}")
            # صبر کنیم و دوباره با تنظیمات تازه تلاش کنیم
            time.sleep(random.randint(120, 240))

            try:
                # ایجاد یک نمونه جدید از کلاینت و تلاش دوباره
                self.client = Client(request_timeout=120)
                self.client.delay_range = [10, 20]

                logger.info(
                    "Retrying with fresh client after login required error")
                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password)
                if self.logged_in:
                    logger.info(
                        "Successfully logged in after login required error")
                    self.login_retry_count = 0
                    self._save_session()
                    return True
                else:
                    logger.error("Failed to login after login required error")
                    return False
            except Exception as retry_error:
                logger.error(f"Error during retry login: {str(retry_error)}")
                return False

        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            # تلاش دوباره بعد از یک تاخیر طولانی‌تر
            wait_time = random.randint(180, 300)
            logger.info(f"Trying again after {wait_time} seconds delay...")
            time.sleep(wait_time)
            try:
                # ایجاد یک نمونه جدید از کلاینت
                self.client = Client(request_timeout=120)
                self.client.delay_range = [10, 20]

                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password)
                if self.logged_in:
                    logger.info("Successfully logged in on second attempt")
                    self.login_retry_count = 0
                    self._save_session()
                    return True
                else:
                    logger.error("Failed to login on second attempt")
                    return False
            except Exception as retry_error:
                logger.error(f"Error during retry login: {str(retry_error)}")
                return False

    def _save_session(self):
        """Save session data to file and database"""
        try:
            # اطمینان از وجود پوشه sessions
            os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)

            # ذخیره در فایل
            self.client.dump_settings(SESSION_FILE)
            logger.info(f"Session saved to file: {SESSION_FILE}")

            # ذخیره در دیتابیس
            session_data = json.dumps(self.client.get_settings())

            # بررسی وجود جلسه قبلی در دیتابیس
            existing_session = self.db.query(BotSession).filter(
                BotSession.username == INSTAGRAM_USERNAME
            ).first()

            if existing_session:
                existing_session.session_data = session_data
                existing_session.is_active = True
            else:
                new_session = BotSession(
                    username=INSTAGRAM_USERNAME,
                    session_data=session_data,
                    is_active=True
                )
                self.db.add(new_session)

            self.db.commit()
            logger.info(f"Session saved to database for {INSTAGRAM_USERNAME}")
        except Exception as e:
            logger.error(f"Error saving session: {str(e)}")
            self.db.rollback()

    def load_session(self):
        """Try to load session from file or database"""
        try:
            # First try from database (preferred)
            session_record = self.db.query(BotSession).filter(
                BotSession.username == INSTAGRAM_USERNAME,
                BotSession.is_active == True
            ).first()

            if session_record:
                logger.info(
                    f"Loading session from database for {INSTAGRAM_USERNAME}")
                session_data = json.loads(session_record.session_data)
                self.client.set_settings(session_data)

                # Verify session with a simple request - تغییر متد برای سازگاری
                try:
                    # روش متفاوت برای بررسی اعتبار نشست
                    me = self.client.account_info()
                    if me:
                        self.logged_in = True
                        logger.info(
                            "Successfully loaded and verified session from database")
                        return True
                except Exception as verify_error:
                    logger.warning(
                        f"Database session verification failed: {str(verify_error)}")
                    # Continue to try file session
            else:
                logger.info("No active session found in database")

            # Then try from file
            if os.path.exists(SESSION_FILE):
                logger.info(f"Loading session from file: {SESSION_FILE}")
                self.client.load_settings(SESSION_FILE)

                # Verify session with a simple request - تغییر متد برای سازگاری
                try:
                    # روش متفاوت برای بررسی اعتبار نشست
                    me = self.client.account_info()
                    if me:
                        self.logged_in = True
                        logger.info(
                            "Successfully loaded and verified session from file")
                        return True
                except Exception as verify_error:
                    logger.warning(
                        f"File session verification failed: {str(verify_error)}")
            else:
                logger.info(f"Session file not found: {SESSION_FILE}")

            # If we get here, both methods failed or session is invalid
            logger.warning(
                "Could not load valid session from database or file")
            return False

        except Exception as e:
            logger.error(f"Error loading session: {str(e)}")
            return False

    def handle_request_error(self, error, operation_name):
        """Handle common API request errors with appropriate strategies"""
        if isinstance(error, (PleaseWaitFewMinutes, RateLimitError)):
            logger.warning(
                f"Rate limit hit during {operation_name}: {str(error)}")
            # Return False to indicate the operation should be retried later
            return False
        elif isinstance(error, (LoginRequired, ClientLoginRequired)):
            logger.warning(
                f"Login required during {operation_name}: {str(error)}")
            # Try to re-login
            return self.login(force=True)
        else:
            logger.error(
                f"Unexpected error during {operation_name}: {str(error)}")
            return False

    def get_client(self):
        """Get the Instagram client instance, ensuring login if needed"""
        if not self.logged_in:
            # Try to load session first
            if not self.load_session():
                # If session loading failed, try regular login
                if not self.login():
                    logger.error(
                        "Failed to get a valid client - both session loading and login failed")
                    # Even if login fails, return client so operations can at least try

        return self.client

    def logout(self):
        """Logout from Instagram"""
        if self.logged_in:
            try:
                self.client.logout()
                self.logged_in = False
                logger.info("Successfully logged out")
                return True
            except Exception as e:
                logger.error(f"Error during logout: {str(e)}")
                return False
        return False

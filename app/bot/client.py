import json
import os
import time
import random
import logging
from pathlib import Path
from sqlalchemy.orm import Session
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError, PleaseWaitFewMinutes, ClientError, ClientLoginRequired, ClientThrottledError

from app.config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, SESSION_FILE
from app.models.database import BotSession
from app.logger import setup_logger

# Setup logger
logger = setup_logger("instagram_client")


class InstagramClient:
    def __init__(self, db: Session):
        # افزایش تایم‌اوت به 180 ثانیه
        self.client = Client(request_timeout=180)
        self.db = db
        self.logged_in = False
        self.last_login_attempt = None
        self.login_retry_count = 0
        self.session_check_count = 0
        self.last_session_check = time.time()

        # تنظیمات کاستوم برای بهبود استفاده از API
        self.client.delay_range = [12, 30]  # تاخیر بیشتر بین درخواست‌ها
        self.client.request_timeout = 90

        # رفتار نزدیک به انسان
        self.client.handle_exception = self._custom_exception_handler  # هندلر اختصاصی خطا

        # تلاش برای بارگذاری نشست در همان ابتدا
        self.try_load_session()

    def _custom_exception_handler(self, client, exception):
        """مدیریت خطای سفارشی برای اینستاگرام کلاینت"""
        if isinstance(exception, (ClientThrottledError, RateLimitError, PleaseWaitFewMinutes)):
            logger.warning(f"Rate limit detected: {str(exception)}")
            # افزایش تاخیر تصادفی برای محدودیت نرخ
            delay = random.randint(300, 600)  # 5-10 دقیقه تاخیر
            logger.info(f"Sleeping for {delay} seconds due to rate limit")
            time.sleep(delay)
            return False

        if isinstance(exception, LoginRequired):
            logger.warning("Login session expired, attempting to login again")
            # تلاش برای ورود مجدد
            return self.login(force=True)

        if isinstance(exception, KeyError) and "'data'" in str(exception):
            logger.warning(
                "Instagram API returned unexpected response without 'data' field")
            # تأخیر قبل از تلاش مجدد
            time.sleep(random.randint(60, 180))
            return False

        # برگرداندن خطا به هندلر پیش‌فرض در موارد دیگر
        return False

    def try_load_session(self):
        """تلاش برای بارگذاری نشست بدون ارسال خطا"""
        try:
            loaded = self.load_session()
            if loaded:
                logger.info(
                    "Successfully loaded session during initialization")
        except Exception as e:
            logger.warning(
                f"Could not load session during initialization: {str(e)}")

    def login(self, force=False):
        """Login to Instagram account using session or credentials with improved error handling"""
        current_time = time.time()

        # محدودیت تلاش‌های مکرر برای لاگین
        # 5 دقیقه حداقل فاصله
        if not force and self.last_login_attempt and (current_time - self.last_login_attempt < 300):
            logger.warning(
                "Login attempted too frequently. Waiting before next attempt.")
            return self.logged_in

        self.last_login_attempt = current_time
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

        # افزودن تاخیر تصادفی قبل از لاگین برای جلوگیری از محدودیت‌ها
        wait_time = random.randint(30, 60)
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

            # تنظیم پارامترهای لاگین برای بهبود عملکرد
            self.logged_in = self.client.login(
                INSTAGRAM_USERNAME,
                password,
                relogin=True,  # تلاش مجدد برای لاگین در صورت نیاز
                verification_code=None  # در صورت فعال بودن احراز هویت دو مرحله‌ای، اینجا باید تغییر کند
            )

            if self.logged_in:
                logger.info("Successfully logged in with credentials")
                # ریست تعداد تلاش
                self.login_retry_count = 0
                # ذخیره جلسه
                self._save_session()
                return True
            else:
                logger.error("Failed to login with credentials")
                self.login_retry_count += 1
                # تلاش مجدد بعد از یک تاخیر
                time.sleep(90)  # افزایش تاخیر به 1.5 دقیقه

                # تلاش مجدد با تنظیمات تازه
                self.client = Client(request_timeout=180)
                self.client.delay_range = [12, 30]
                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password
                )

                if self.logged_in:
                    logger.info("Successfully logged in on second attempt")
                    self.login_retry_count = 0
                    self._save_session()
                    return True

                return False

        except (ClientLoginRequired, LoginRequired) as e:
            logger.error(f"Login required error: {str(e)}")
            self.login_retry_count += 1

            # صبر کنیم و دوباره با تنظیمات تازه تلاش کنیم
            # افزایش تاخیر بر اساس تعداد تلاش‌ها
            delay = random.randint(120, 240) * min(self.login_retry_count, 3)
            logger.info(f"Will retry login after {delay} seconds")
            time.sleep(delay)

            try:
                # ایجاد یک نمونه جدید از کلاینت و تلاش دوباره
                self.client = Client(request_timeout=180)
                self.client.delay_range = [12, 30]
                self.client.handle_exception = self._custom_exception_handler

                logger.info(
                    "Retrying with fresh client after login required error")
                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password
                )
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
            self.login_retry_count += 1

            # تلاش دوباره بعد از یک تاخیر طولانی‌تر
            wait_time = random.randint(180, 300) * \
                min(self.login_retry_count, 3)
            logger.info(f"Trying again after {wait_time} seconds delay...")
            time.sleep(wait_time)

            try:
                # ایجاد یک نمونه جدید از کلاینت
                self.client = Client(request_timeout=180)
                self.client.delay_range = [12, 30]
                self.client.handle_exception = self._custom_exception_handler

                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, password
                )
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
        """Save session data to file and database with improved error handling"""
        try:
            # اطمینان از وجود پوشه sessions
            os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)

            # ذخیره در فایل
            try:
                self.client.dump_settings(SESSION_FILE)
                logger.info(f"Session saved to file: {SESSION_FILE}")
            except Exception as file_error:
                logger.error(
                    f"Error saving session to file: {str(file_error)}")

            # ذخیره در دیتابیس
            try:
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
                logger.info(
                    f"Session saved to database for {INSTAGRAM_USERNAME}")
            except Exception as db_error:
                logger.error(
                    f"Error saving session to database: {str(db_error)}")
                try:
                    self.db.rollback()
                except:
                    pass
        except Exception as e:
            logger.error(f"Error in _save_session: {str(e)}")

    def load_session(self):
        """Try to load session from file or database with improved error handling"""
        try:
            # First try from database (preferred)
            try:
                session_record = self.db.query(BotSession).filter(
                    BotSession.username == INSTAGRAM_USERNAME,
                    BotSession.is_active == True
                ).first()

                if session_record:
                    logger.info(
                        f"Loading session from database for {INSTAGRAM_USERNAME}")
                    session_data = json.loads(session_record.session_data)
                    self.client.set_settings(session_data)

                    # Verify session with a simple request
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
                        # ادامه به تلاش برای بارگذاری از فایل
            except Exception as db_error:
                logger.warning(
                    f"Error loading session from database: {str(db_error)}")

            # Then try from file
            if os.path.exists(SESSION_FILE):
                logger.info(f"Loading session from file: {SESSION_FILE}")
                try:
                    self.client.load_settings(SESSION_FILE)

                    # Verify session with a simple request
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
                except Exception as load_error:
                    logger.warning(
                        f"Error loading settings from file: {str(load_error)}")
            else:
                logger.info(f"Session file not found: {SESSION_FILE}")

            # If we get here, both methods failed or session is invalid
            logger.warning(
                "Could not load valid session from database or file")
            return False

        except Exception as e:
            logger.error(f"Error loading session: {str(e)}")
            return False

    def verify_session(self, force=False):
        """بررسی اعتبار نشست و بازیابی در صورت نیاز"""
        current_time = time.time()

        # کاهش تعداد بررسی‌های مکرر
        # حداقل 30 دقیقه بین بررسی‌ها
        if not force and (current_time - self.last_session_check < 1800):
            return self.logged_in

        self.last_session_check = current_time
        self.session_check_count += 1

        logger.info("Verifying session validity...")

        try:
            # انجام یک عملیات ساده برای بررسی اعتبار نشست
            me = self.client.account_info()
            if me:
                logger.info("Session verified successfully")
                self.logged_in = True
                # ریست شمارنده بررسی
                self.session_check_count = 0
                return True
        except Exception as e:
            logger.warning(f"Session verification failed: {str(e)}")

            # تلاش برای ورود مجدد
            logger.info(
                "Attempting to relogin after session verification failure")
            return self.login(force=True)

    def handle_request_error(self, error, operation_name):
        """Handle common API request errors with appropriate strategies"""
        if isinstance(error, (PleaseWaitFewMinutes, RateLimitError, ClientThrottledError)):
            logger.warning(
                f"Rate limit hit during {operation_name}: {str(error)}")
            # محاسبه زمان انتظار بر اساس پیام خطا
            wait_seconds = 300  # پیش‌فرض 5 دقیقه

            # استخراج زمان از پیام خطا (اگر موجود باشد)
            error_msg = str(error).lower()
            if "wait" in error_msg and "minute" in error_msg:
                try:
                    # تلاش برای استخراج عدد از پیام خطا
                    import re
                    minutes = re.findall(r'(\d+)\s*minute', error_msg)
                    if minutes and minutes[0].isdigit():
                        # کمی زمان اضافه
                        wait_seconds = int(
                            minutes[0]) * 60 + random.randint(30, 120)
                except:
                    pass

            logger.info(f"Waiting {wait_seconds} seconds before retry...")
            time.sleep(wait_seconds)

            # وضعیت نشست را بررسی کنیم
            self.verify_session()

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
        else:
            # اگر لاگین هستیم، گهگاهی اعتبار نشست را بررسی کنیم
            if random.random() < 0.2:  # 20% احتمال بررسی در هر درخواست
                self.verify_session()

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

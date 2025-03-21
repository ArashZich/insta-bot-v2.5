import json
import os
import time
import random
from pathlib import Path
from sqlalchemy.orm import Session
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, RateLimitError, PleaseWaitFewMinutes

from app.config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, SESSION_FILE
from app.models.database import BotSession
from app.logger import setup_logger

# Setup logger
logger = setup_logger("instagram_client")


class InstagramClient:
    def __init__(self, db: Session):
        self.client = Client()
        self.db = db
        self.logged_in = False
        # اضافه کردن تایمر برای آخرین زمان لاگین
        self.last_login_attempt = None

    def login(self):
        """Login to Instagram account using session or credentials"""
        logger.info(f"Attempting to login as {INSTAGRAM_USERNAME}")

        # بررسی وجود نام کاربری و رمز عبور
        if not INSTAGRAM_USERNAME or not INSTAGRAM_PASSWORD:
            logger.error(
                "Instagram username or password not set in environment variables")
            return False

        # بررسی اینکه آیا به تازگی تلاش برای ورود داشته‌ایم
        current_time = time.time()
        # 5 دقیقه
        if self.last_login_attempt and (current_time - self.last_login_attempt) < 300:
            logger.warning(
                "Last login attempt was less than 5 minutes ago. Waiting to avoid rate limits...")
            remaining = 300 - (current_time - self.last_login_attempt)
            logger.info(
                f"Will wait {remaining:.0f} seconds before trying again")
            time.sleep(remaining)

        # ثبت زمان این تلاش
        self.last_login_attempt = time.time()

        # تلاش برای ورود ساده با نام کاربری و رمز عبور
        try:
            # اضافه کردن تاخیر قبل از لاگین
            wait_time = random.randint(30, 60)
            logger.info(f"Waiting {wait_time} seconds before login attempt...")
            time.sleep(wait_time)  # تاخیر قبل از ورود

            # خالی کردن کوکی‌ها و تنظیمات قبلی
            self.client.settings = {}
            self.client.cookie = {}

            # تنظیم پارامترهای بیشتر برای کلاینت
            self.client.delay_range = [10, 20]  # تاخیر بیشتر بین درخواست‌ها
            self.client.request_timeout = 30  # زمان انتظار بیشتر برای درخواست‌ها

            # ورود با نام کاربری و رمز عبور
            self.logged_in = self.client.login(
                INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)

            if self.logged_in:
                logger.info("Successfully logged in with credentials")
                # ذخیره جلسه
                self._save_session()
                return True
            else:
                logger.error("Failed to login with credentials")
                return False
        except PleaseWaitFewMinutes as e:
            # خطای محدودیت نرخ درخواست - نیاز به صبر کردن داریم
            logger.error(f"Rate limit error during login: {str(e)}")
            logger.info("Will retry after a longer delay (15 minutes)...")
            time.sleep(900)  # 15 دقیقه صبر می‌کنیم
            try:
                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                if self.logged_in:
                    logger.info(
                        "Successfully logged in on second attempt after rate limit")
                    self._save_session()
                    return True
                else:
                    logger.error(
                        "Failed to login on second attempt after rate limit")
                    return False
            except Exception as retry_error:
                logger.error(
                    f"Error during retry login after rate limit: {str(retry_error)}")
                return False
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            # تلاش دوباره بعد از یک تاخیر طولانی‌تر
            wait_time = random.randint(60, 120)
            logger.info(f"Trying again after {wait_time} seconds delay...")
            time.sleep(wait_time)
            try:
                self.logged_in = self.client.login(
                    INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
                if self.logged_in:
                    logger.info("Successfully logged in on second attempt")
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
        # First try from file
        if os.path.exists(SESSION_FILE):
            try:
                logger.info(f"Loading session from file: {SESSION_FILE}")
                self.client.load_settings(SESSION_FILE)
                # تنظیم پارامترهای بیشتر برای کلاینت
                # تاخیر بیشتر بین درخواست‌ها
                self.client.delay_range = [10, 20]
                self.client.request_timeout = 30  # زمان انتظار بیشتر برای درخواست‌ها

                # Test if session is valid
                try:
                    # اضافه کردن تاخیر قبل از تست
                    time.sleep(5)
                    self.client.get_timeline_feed()
                    self.logged_in = True
                    logger.info("Successfully loaded valid session from file")
                    return True
                except LoginRequired:
                    logger.warning("Session from file is expired")
                except Exception as e:
                    logger.warning(
                        f"Could not validate session from file: {str(e)}")
            except Exception as e:
                logger.warning(f"Could not load session from file: {str(e)}")

        # Then try from database
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
                # تنظیم پارامترهای بیشتر برای کلاینت
                # تاخیر بیشتر بین درخواست‌ها
                self.client.delay_range = [10, 20]
                self.client.request_timeout = 30  # زمان انتظار بیشتر برای درخواست‌ها

                # Test if session is valid
                try:
                    # اضافه کردن تاخیر قبل از تست
                    time.sleep(5)
                    self.client.get_timeline_feed()
                    self.logged_in = True
                    logger.info(
                        "Successfully loaded valid session from database")
                    return True
                except LoginRequired:
                    logger.warning("Session from database is expired")
                except Exception as e:
                    logger.warning(
                        f"Could not validate session from database: {str(e)}")
        except Exception as e:
            logger.warning(f"Could not load session from database: {str(e)}")

        return False

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

    def get_client(self):
        """Get the Instagram client instance"""
        if not self.logged_in:
            # Try to load session first
            if not self.load_session():
                # If session loading failed, try regular login
                self.login()
        return self.client

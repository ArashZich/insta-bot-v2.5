import json
import os
import time
from pathlib import Path
from sqlalchemy.orm import Session
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

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

    def login(self):
        """Login to Instagram account using session or credentials"""
        logger.info(f"Attempting to login as {INSTAGRAM_USERNAME}")

        # تلاش برای ورود ساده با نام کاربری و رمز عبور
        try:
            # اضافه کردن تاخیر قبل از لاگین
            logger.info("Waiting a few seconds before login attempt...")
            time.sleep(3)  # تاخیر 3 ثانیه قبل از ورود

            # خالی کردن کوکی‌ها و تنظیمات قبلی
            self.client.settings = {}
            self.client.cookie = {}

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
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            # تلاش دوباره بعد از 5 ثانیه
            logger.info("Trying again after a short delay...")
            time.sleep(5)
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
                # Test if session is valid
                try:
                    self.client.get_timeline_feed()
                    self.logged_in = True
                    logger.info("Successfully loaded valid session from file")
                    return True
                except LoginRequired:
                    logger.warning("Session from file is expired")
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

                # Test if session is valid
                try:
                    self.client.get_timeline_feed()
                    self.logged_in = True
                    logger.info(
                        "Successfully loaded valid session from database")
                    return True
                except LoginRequired:
                    logger.warning("Session from database is expired")
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

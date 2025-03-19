import json
import os
from pathlib import Path
from sqlalchemy.orm import Session
from instagrapi import Client
from instagrapi.exceptions import LoginRequired

from app.config import INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD, SESSION_FILE
from app.models.database import BotSession
from app.logger import setup_logger

# Configure logging
logger = setup_logger("instagram_client")


class InstagramClient:
    def __init__(self, db: Session):
        self.client = Client()
        self.db = db
        self.logged_in = False

    def login(self):
        """Login to Instagram account using session or credentials"""
        logger.info(f"Attempting to login as {INSTAGRAM_USERNAME}")

        # Try to use stored session
        if self._load_session_from_file() or self._load_session_from_db():
            try:
                # Test if session is valid
                self.client.get_timeline_feed()
                self.logged_in = True
                logger.info("Successfully logged in using saved session")
                return True
            except LoginRequired:
                logger.warning(
                    "Session is expired, trying to login with credentials")

        # Login with username and password
        try:
            self.logged_in = self.client.login(
                INSTAGRAM_USERNAME, INSTAGRAM_PASSWORD)
            if self.logged_in:
                logger.info("Successfully logged in with credentials")
                self._save_session()
                return True
            else:
                logger.error("Failed to login with credentials")
                return False
        except Exception as e:
            logger.error(f"Error during login: {str(e)}")
            return False

    def _load_session_from_file(self):
        """Load session data from file"""
        if os.path.exists(SESSION_FILE):
            try:
                logger.info(f"Loading session from file: {SESSION_FILE}")
                self.client.load_settings(SESSION_FILE)
                return True
            except Exception as e:
                logger.error(f"Error loading session from file: {str(e)}")
        return False

    def _load_session_from_db(self):
        """Load session data from database"""
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
                return True
        except Exception as e:
            logger.error(f"Error loading session from database: {str(e)}")
        return False

    def _save_session(self):
        """Save session data to file and database"""
        try:
            # Make sure the sessions directory exists
            os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)

            # Save to file
            self.client.dump_settings(SESSION_FILE)
            logger.info(f"Session saved to file: {SESSION_FILE}")

            # Save to database
            session_data = json.dumps(self.client.get_settings())

            # Check if session already exists in DB
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
            self.login()
        return self.client

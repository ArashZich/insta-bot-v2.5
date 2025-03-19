import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

# Instagram credentials
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Database settings
DATABASE_URL = f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"

# Bot settings
SESSION_PATH = os.getenv("SESSION_PATH", "/app/sessions")
SESSION_FILE = Path(SESSION_PATH) / f"{INSTAGRAM_USERNAME}.json"

# Action limits
MIN_DELAY_BETWEEN_ACTIONS = int(os.getenv("MIN_DELAY_BETWEEN_ACTIONS", 30))
MAX_DELAY_BETWEEN_ACTIONS = int(os.getenv("MAX_DELAY_BETWEEN_ACTIONS", 180))
DAILY_FOLLOW_LIMIT = int(os.getenv("DAILY_FOLLOW_LIMIT", 50))
DAILY_UNFOLLOW_LIMIT = int(os.getenv("DAILY_UNFOLLOW_LIMIT", 50))
DAILY_LIKE_LIMIT = int(os.getenv("DAILY_LIKE_LIMIT", 100))
DAILY_COMMENT_LIMIT = int(os.getenv("DAILY_COMMENT_LIMIT", 25))
DAILY_DIRECT_LIMIT = int(os.getenv("DAILY_DIRECT_LIMIT", 15))
DAILY_STORY_REACTION_LIMIT = int(os.getenv("DAILY_STORY_REACTION_LIMIT", 20))

# Bot behavior
RANDOM_ACTIVITY_MODE = os.getenv(
    "RANDOM_ACTIVITY_MODE", "True").lower() == "true"
REST_PERIOD_MIN = int(os.getenv("REST_PERIOD_MIN", 2))  # Hours
REST_PERIOD_MAX = int(os.getenv("REST_PERIOD_MAX", 6))  # Hours

# API settings
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = int(os.getenv("API_PORT", 8000))

# Define activities list
ACTIVITIES = [
    "follow",
    "unfollow",
    "like",
    "comment",
    "direct",
    "story_reaction"
]

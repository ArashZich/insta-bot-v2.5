import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

# Instagram credentials
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Database settings
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASSWORD = os.getenv('DB_PASSWORD', 'postgres')
DB_HOST = os.getenv('DB_HOST', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')
DB_NAME = os.getenv('DB_NAME', 'instagrambot')

DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Fall back to SQLite if needed
SQLITE_FALLBACK = os.getenv('SQLITE_FALLBACK', 'False').lower() == 'true'
if SQLITE_FALLBACK:
    DATABASE_URL = "sqlite:///instagram_bot.db"

# Bot settings
SESSION_PATH = os.getenv("SESSION_PATH", "/app/sessions")
SESSION_FILE = Path(SESSION_PATH) / f"{INSTAGRAM_USERNAME}.json"

# افزایش فاصله زمانی بین فعالیت‌ها
MIN_DELAY_BETWEEN_ACTIONS = int(
    os.getenv("MIN_DELAY_BETWEEN_ACTIONS", 120))  # حداقل 2 دقیقه
MAX_DELAY_BETWEEN_ACTIONS = int(
    os.getenv("MAX_DELAY_BETWEEN_ACTIONS", 300))  # حداکثر 5 دقیقه


DAILY_FOLLOW_LIMIT = int(os.getenv("DAILY_FOLLOW_LIMIT", 5))
DAILY_UNFOLLOW_LIMIT = int(os.getenv("DAILY_UNFOLLOW_LIMIT", 5))
DAILY_LIKE_LIMIT = int(os.getenv("DAILY_LIKE_LIMIT", 15))
DAILY_COMMENT_LIMIT = int(os.getenv("DAILY_COMMENT_LIMIT", 2))
DAILY_DIRECT_LIMIT = int(os.getenv("DAILY_DIRECT_LIMIT", 1))
DAILY_STORY_REACTION_LIMIT = int(os.getenv("DAILY_STORY_REACTION_LIMIT", 3))

# Bot behavior - تنظیم زمان استراحت
RANDOM_ACTIVITY_MODE = os.getenv(
    "RANDOM_ACTIVITY_MODE", "True").lower() == "true"

REST_PERIOD_MIN = float(os.getenv("REST_PERIOD_MIN", "0.25"))  # حداقل 15 دقیقه
REST_PERIOD_MAX = float(
    os.getenv("REST_PERIOD_MAX", "0.75"))  # حداکثر 45 دقیقه

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

# Database health check interval (seconds)
DB_HEALTH_CHECK_INTERVAL = int(
    os.getenv("DB_HEALTH_CHECK_INTERVAL", 300))  # 5 minutes by default

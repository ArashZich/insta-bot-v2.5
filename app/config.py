import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file
load_dotenv()

# Instagram credentials
INSTAGRAM_USERNAME = os.getenv("INSTAGRAM_USERNAME")
INSTAGRAM_PASSWORD = os.getenv("INSTAGRAM_PASSWORD")

# Database settings
DATABASE_URL = f"postgresql://{os.getenv('DB_USER', 'postgres')}:{os.getenv('DB_PASSWORD', 'postgres')}@{os.getenv('DB_HOST', 'postgres')}:{os.getenv('DB_PORT', '5432')}/{os.getenv('DB_NAME', 'postgres')}"

# Bot settings
SESSION_PATH = os.getenv("SESSION_PATH", "/app/sessions")
SESSION_FILE = Path(SESSION_PATH) / f"{INSTAGRAM_USERNAME}.json"

# Action limits - تنظیم مقادیر منطقی‌تر
MIN_DELAY_BETWEEN_ACTIONS = int(
    os.getenv("MIN_DELAY_BETWEEN_ACTIONS", 30))  # حداقل 30 ثانیه
MAX_DELAY_BETWEEN_ACTIONS = int(
    os.getenv("MAX_DELAY_BETWEEN_ACTIONS", 90))  # حداکثر 90 ثانیه
DAILY_FOLLOW_LIMIT = int(os.getenv("DAILY_FOLLOW_LIMIT", 20))  # کاهش به 20
DAILY_UNFOLLOW_LIMIT = int(os.getenv("DAILY_UNFOLLOW_LIMIT", 20))  # کاهش به 20
DAILY_LIKE_LIMIT = int(os.getenv("DAILY_LIKE_LIMIT", 50))  # کاهش به 50
DAILY_COMMENT_LIMIT = int(os.getenv("DAILY_COMMENT_LIMIT", 10))  # کاهش به 10
DAILY_DIRECT_LIMIT = int(os.getenv("DAILY_DIRECT_LIMIT", 5))  # کاهش به 5
DAILY_STORY_REACTION_LIMIT = int(
    os.getenv("DAILY_STORY_REACTION_LIMIT", 10))  # کاهش به 10

# Bot behavior - تنظیم زمان استراحت
RANDOM_ACTIVITY_MODE = os.getenv(
    "RANDOM_ACTIVITY_MODE", "True").lower() == "true"

# مقادیر به ساعت - می‌توانید برای تست کاهش دهید
# 0.5 ساعت = 30 دقیقه = 1800 ثانیه
# 2 ساعت = 120 دقیقه = 7200 ثانیه
# تغییر به حدود 5 دقیقه
REST_PERIOD_MIN = float(os.getenv("REST_PERIOD_MIN", "0.08"))
# تغییر به حدود 15 دقیقه
REST_PERIOD_MAX = float(os.getenv("REST_PERIOD_MAX", "0.25"))

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

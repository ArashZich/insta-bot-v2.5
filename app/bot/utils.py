import time
import random
from datetime import datetime, timedelta
from sqlalchemy.orm import Session

from app.models.database import DailyStats
from app.config import MIN_DELAY_BETWEEN_ACTIONS, MAX_DELAY_BETWEEN_ACTIONS
from app.config import REST_PERIOD_MIN, REST_PERIOD_MAX, ACTIVITIES
from app.logger import setup_logger

# Configure logging
logger = setup_logger("utils")


def random_delay():
    """Add a random delay between actions to make bot behavior more human-like"""
    delay = random.randint(MIN_DELAY_BETWEEN_ACTIONS,
                           MAX_DELAY_BETWEEN_ACTIONS)
    logger.info(f"Waiting for {delay} seconds before next action")
    time.sleep(delay)


def should_rest():
    """Decide if the bot should take a break based on time of day and randomness"""
    # Random chance of resting
    if random.random() < 0.1:  # 10% chance of random rest
        logger.info("Taking a random rest period based on chance")
        return True

    # Check time of day - avoid late night activity (more suspicious)
    current_hour = datetime.now().hour
    if 1 <= current_hour <= 6:  # Between 1 AM and 6 AM
        logger.info(f"Taking a rest because current hour is {current_hour}")
        return True

    return False


def take_rest():
    """Pause bot activity for a rest period"""
    rest_hours = random.uniform(REST_PERIOD_MIN, REST_PERIOD_MAX)
    rest_seconds = int(rest_hours * 3600)
    logger.info(
        f"Taking a rest for {rest_hours:.2f} hours ({rest_seconds} seconds)")
    time.sleep(rest_seconds)


def choose_random_activity():
    """Choose a random activity from available activities"""
    return random.choice(ACTIVITIES)


def get_daily_limits_status(db: Session):
    """Get the current status of daily limits"""
    today = datetime.utcnow().date()
    stats = db.query(DailyStats).filter(
        DailyStats.date >= today
    ).first()

    if not stats:
        # No stats for today yet
        return {
            "follows": 0,
            "unfollows": 0,
            "likes": 0,
            "comments": 0,
            "directs": 0,
            "story_reactions": 0
        }

    return {
        "follows": stats.follows_count,
        "unfollows": stats.unfollows_count,
        "likes": stats.likes_count,
        "comments": stats.comments_count,
        "directs": stats.directs_count,
        "story_reactions": stats.story_reactions_count
    }


def get_activity_stats(db: Session, period='daily'):
    """Get activity statistics for a given period"""
    today = datetime.utcnow().date()

    if period == 'daily':
        start_date = today
    elif period == 'weekly':
        start_date = today - timedelta(days=7)
    elif period == 'monthly':
        start_date = today - timedelta(days=30)
    elif period == 'six_months':
        start_date = today - timedelta(days=180)
    else:
        start_date = today

    stats = db.query(DailyStats).filter(
        DailyStats.date >= start_date
    ).all()

    # Initialize results
    results = {
        'follows': 0,
        'unfollows': 0,
        'likes': 0,
        'comments': 0,
        'directs': 0,
        'story_reactions': 0,
        'followers_gained': 0,
        'followers_lost': 0,
        'days': len(stats)
    }

    # Sum up all values
    for stat in stats:
        results['follows'] += stat.follows_count
        results['unfollows'] += stat.unfollows_count
        results['likes'] += stat.likes_count
        results['comments'] += stat.comments_count
        results['directs'] += stat.directs_count
        results['story_reactions'] += stat.story_reactions_count
        results['followers_gained'] += stat.followers_gained
        results['followers_lost'] += stat.followers_lost

    # Calculate averages
    if results['days'] > 0:
        results['avg_follows'] = results['follows'] / results['days']
        results['avg_unfollows'] = results['unfollows'] / results['days']
        results['avg_likes'] = results['likes'] / results['days']
        results['avg_comments'] = results['comments'] / results['days']
        results['avg_directs'] = results['directs'] / results['days']
        results['avg_story_reactions'] = results['story_reactions'] / \
            results['days']
        results['avg_followers_gained'] = results['followers_gained'] / \
            results['days']
        results['avg_followers_lost'] = results['followers_lost'] / \
            results['days']

    return results


def update_follower_counts(client, db: Session):
    """Update follower count changes in the database"""
    try:
        # Get my user ID
        user_id = client.user_id

        # Get my current follower count
        user_info = client.user_info(user_id)
        current_follower_count = user_info.follower_count

        # Get yesterday's stats to determine changes
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        yesterday_stats = db.query(DailyStats).filter(
            DailyStats.date >= yesterday,
            DailyStats.date < datetime.utcnow().date()
        ).first()

        # Get or create today's stats
        today = datetime.utcnow().date()
        today_stats = db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if not today_stats:
            today_stats = DailyStats(date=today)
            db.add(today_stats)

        # Calculate gains and losses if we have yesterday's data
        if yesterday_stats:
            previous_count = yesterday_stats.followers_gained - yesterday_stats.followers_lost

            # Calculate the difference
            difference = current_follower_count - previous_count

            if difference > 0:
                today_stats.followers_gained = difference
            elif difference < 0:
                today_stats.followers_lost = abs(difference)

        db.commit()
        logger.info(
            f"Updated follower counts in database. Current followers: {current_follower_count}")

    except Exception as e:
        logger.error(f"Error updating follower counts: {str(e)}")
        db.rollback()

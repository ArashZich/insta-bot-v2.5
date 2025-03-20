import random
import time
import logging
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.models.database import DailyStats, BotActivity
from app.config import (
    MIN_DELAY_BETWEEN_ACTIONS,
    MAX_DELAY_BETWEEN_ACTIONS,
    REST_PERIOD_MIN,
    REST_PERIOD_MAX,
    ACTIVITIES,
    DAILY_FOLLOW_LIMIT,
    DAILY_UNFOLLOW_LIMIT,
    DAILY_LIKE_LIMIT,
    DAILY_COMMENT_LIMIT,
    DAILY_DIRECT_LIMIT,
    DAILY_STORY_REACTION_LIMIT
)

logger = logging.getLogger("bot_utils")


def random_delay(min_delay=None, max_delay=None):
    """Add a random delay between actions to make behavior more human-like"""
    min_delay = min_delay or MIN_DELAY_BETWEEN_ACTIONS
    max_delay = max_delay or MAX_DELAY_BETWEEN_ACTIONS

    delay = random.uniform(min_delay, max_delay)
    logger.info(f"Taking a short break for {delay:.2f} seconds")
    time.sleep(delay)
    return delay


def should_rest():
    """Determine if the bot should take a longer rest based on probability"""
    # 10% chance of taking a rest
    return random.random() < 0.1


def take_rest():
    """Take a longer rest to simulate human breaks"""
    # Convert hours to seconds
    min_rest = REST_PERIOD_MIN * 60
    max_rest = REST_PERIOD_MAX * 60

    rest_time = random.uniform(min_rest, max_rest)
    logger.info(f"Taking a longer rest for {rest_time/60:.2f} minutes")

    # Just return the rest time without actually sleeping
    # The scheduler will handle the rest period using its own mechanism
    return rest_time


def choose_random_activity():
    """Choose a random activity from the available activities"""
    return random.choice(ACTIVITIES)


def get_daily_limits_status(db: Session):
    """Get current daily limits status"""
    today = datetime.utcnow().date()
    stats = db.query(DailyStats).filter(
        DailyStats.date >= today
    ).first()

    if not stats:
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


def get_activity_stats(db: Session, period):
    """Calculate activity statistics for a specified period"""
    now = datetime.utcnow()

    # Determine start date based on period
    if period == "daily":
        days = 1
        start_date = now - timedelta(days=1)
    elif period == "weekly":
        days = 7
        start_date = now - timedelta(days=7)
    elif period == "monthly":
        days = 30
        start_date = now - timedelta(days=30)
    elif period == "six_months":
        days = 180
        start_date = now - timedelta(days=180)
    else:
        days = 1
        start_date = now - timedelta(days=1)

    # Query activities
    activities = db.query(BotActivity).filter(
        BotActivity.created_at >= start_date,
        BotActivity.created_at <= now
    ).all()

    # Count by type
    follows = sum(1 for a in activities if a.activity_type ==
                  "follow" and a.status == "success")
    unfollows = sum(1 for a in activities if a.activity_type ==
                    "unfollow" and a.status == "success")
    likes = sum(1 for a in activities if a.activity_type ==
                "like" and a.status == "success")
    comments = sum(1 for a in activities if a.activity_type ==
                   "comment" and a.status == "success")
    directs = sum(1 for a in activities if a.activity_type ==
                  "direct" and a.status == "success")
    story_reactions = sum(1 for a in activities if a.activity_type ==
                          "story_reaction" and a.status == "success")

    # For followers gained/lost, we would need to query the stats table
    stats = db.query(DailyStats).filter(
        DailyStats.date >= start_date,
        DailyStats.date <= now
    ).all()

    followers_gained = sum(s.followers_gained for s in stats)
    followers_lost = sum(s.followers_lost for s in stats)

    # Calculate averages
    avg_follows = follows / days if days > 0 else 0
    avg_unfollows = unfollows / days if days > 0 else 0
    avg_likes = likes / days if days > 0 else 0
    avg_comments = comments / days if days > 0 else 0
    avg_directs = directs / days if days > 0 else 0
    avg_story_reactions = story_reactions / days if days > 0 else 0
    avg_followers_gained = followers_gained / days if days > 0 else 0
    avg_followers_lost = followers_lost / days if days > 0 else 0

    return {
        "follows": follows,
        "unfollows": unfollows,
        "likes": likes,
        "comments": comments,
        "directs": directs,
        "story_reactions": story_reactions,
        "followers_gained": followers_gained,
        "followers_lost": followers_lost,
        "days": days,
        "avg_follows": round(avg_follows, 2),
        "avg_unfollows": round(avg_unfollows, 2),
        "avg_likes": round(avg_likes, 2),
        "avg_comments": round(avg_comments, 2),
        "avg_directs": round(avg_directs, 2),
        "avg_story_reactions": round(avg_story_reactions, 2),
        "avg_followers_gained": round(avg_followers_gained, 2),
        "avg_followers_lost": round(avg_followers_lost, 2)
    }


def update_follower_counts(client, db: Session):
    """Update follower count statistics in the database"""
    try:
        # Get my user_id
        user_id = client.user_id

        # Get current follower count
        current_followers_count = len(client.user_followers(user_id))

        # Get yesterday's stats if available
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        yesterday_stats = db.query(DailyStats).filter(
            DailyStats.date == yesterday
        ).first()

        # Get or create today's stats
        today = datetime.utcnow().date()
        today_stats = db.query(DailyStats).filter(
            DailyStats.date == today
        ).first()

        if not today_stats:
            today_stats = DailyStats(date=today)
            db.add(today_stats)

        # Calculate followers gained/lost if we have yesterday's stats
        if yesterday_stats:
            yesterday_followers = yesterday_stats.followers_gained - \
                yesterday_stats.followers_lost
            if yesterday_followers > 0:  # prevent negative values
                # Calculate the difference
                if current_followers_count > yesterday_followers:
                    today_stats.followers_gained = current_followers_count - yesterday_followers
                elif current_followers_count < yesterday_followers:
                    today_stats.followers_lost = yesterday_followers - current_followers_count

        db.commit()
        logger.info(
            f"Updated follower counts. Current followers: {current_followers_count}")
        return True
    except Exception as e:
        logger.error(f"Error updating follower counts: {str(e)}")
        db.rollback()
        return False

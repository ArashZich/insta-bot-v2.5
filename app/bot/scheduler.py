import random
import threading
import time
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.bot.client import InstagramClient
from app.bot.actions import ActionManager
from app.bot.utils import (
    random_delay,
    should_rest,
    take_rest,
    choose_random_activity,
    update_follower_counts
)
from app.config import RANDOM_ACTIVITY_MODE
from app.logger import setup_logger

# Configure logging
logger = setup_logger("scheduler")


class BotScheduler:
    def __init__(self, db: Session):
        self.db = db
        self.client = InstagramClient(db)
        self.actions = None
        self.scheduler = BackgroundScheduler()
        self.running = False
        self.lock = threading.Lock()  # Lock to prevent concurrent actions

    def initialize(self):
        """Initialize the bot by logging in and setting up actions"""
        if self.client.login():
            self.actions = ActionManager(self.client.get_client(), self.db)
            logger.info("Bot initialized successfully")
            return True
        else:
            logger.error("Failed to initialize bot - login failed")
            return False

    def start(self):
        """Start the bot scheduler"""
        if not self.initialize():
            return False

        # Schedule the main activity task
        self.scheduler.add_job(
            self.perform_activity,
            # Check for activity every 10 minutes
            trigger=IntervalTrigger(minutes=10),
            id='activity_job',
            replace_existing=True
        )

        # Schedule daily follower count update
        self.scheduler.add_job(
            self.update_follower_stats,
            trigger=IntervalTrigger(hours=6),  # Update 4 times per day
            id='follower_stats_job',
            replace_existing=True
        )

        self.scheduler.start()
        self.running = True
        logger.info("Bot scheduler started")
        return True

    def stop(self):
        """Stop the bot scheduler"""
        if self.scheduler.running:
            self.scheduler.shutdown()
        self.running = False
        logger.info("Bot scheduler stopped")

    def perform_activity(self):
        """Perform a bot activity based on schedule and limits"""
        # Use lock to prevent concurrent actions
        if not self.lock.acquire(blocking=False):
            logger.info("Another activity is already in progress, skipping")
            return

        try:
            # Check if we should take a rest
            if should_rest():
                take_rest()
                return

            # Choose a random activity if in random mode, otherwise cycle through activities
            if RANDOM_ACTIVITY_MODE:
                activity = choose_random_activity()
            else:
                # In a real implementation, you might want a more sophisticated approach
                # For simplicity, we'll just use random here as well
                activity = choose_random_activity()

            logger.info(f"Performing activity: {activity}")

            # Perform the selected activity
            if activity == "follow":
                self.perform_follow_activity()
            elif activity == "unfollow":
                self.perform_unfollow_activity()
            elif activity == "like":
                self.perform_like_activity()
            elif activity == "comment":
                self.perform_comment_activity()
            elif activity == "direct":
                self.perform_direct_activity()
            elif activity == "story_reaction":
                self.perform_story_reaction_activity()

        except Exception as e:
            logger.error(f"Error performing activity: {str(e)}")
        finally:
            self.lock.release()

    def perform_follow_activity(self):
        """Perform follow-related activities"""
        try:
            # Choose a random follow action
            action = random.choice([
                "follow_hashtag_users",
                "follow_user_followers",
                "follow_my_followers"
            ])

            if action == "follow_hashtag_users":
                # Choose a random hashtag from our topics
                from app.data.topics import HASHTAGS
                if HASHTAGS:
                    hashtag = random.choice(HASHTAGS)
                    count = self.actions.follow.follow_hashtag_users(
                        hashtag, max_users=3)
                    logger.info(
                        f"Followed {count} users from hashtag #{hashtag}")

            elif action == "follow_user_followers":
                # Choose a user from our topics
                from app.data.topics import TARGET_USERS
                if TARGET_USERS:
                    username = random.choice(TARGET_USERS)
                    count = self.actions.follow.follow_user_followers(
                        username, max_users=3)
                    logger.info(
                        f"Followed {count} followers of user {username}")

            elif action == "follow_my_followers":
                count = self.actions.follow.follow_my_followers(max_users=3)
                logger.info(
                    f"Followed {count} of my followers that I wasn't following back")

            # Add a delay before the next action
            random_delay()

        except Exception as e:
            logger.error(f"Error in follow activity: {str(e)}")

    def perform_unfollow_activity(self):
        """Perform unfollow-related activities"""
        try:
            # Choose a random unfollow action
            action = random.choice([
                "unfollow_non_followers",
                "unfollow_old_followings",
                "unfollow_users_who_unfollowed_me"
            ])

            if action == "unfollow_non_followers":
                count = self.actions.unfollow.unfollow_non_followers(
                    max_users=3)
                logger.info(
                    f"Unfollowed {count} users who don't follow me back")

            elif action == "unfollow_old_followings":
                # Random days threshold between 7-14 days
                days = random.randint(7, 14)
                count = self.actions.unfollow.unfollow_old_followings(
                    days_threshold=days, max_users=3)
                logger.info(
                    f"Unfollowed {count} users who didn't follow back after {days} days")

            elif action == "unfollow_users_who_unfollowed_me":
                count = self.actions.unfollow.unfollow_users_who_unfollowed_me(
                    max_users=3)
                logger.info(f"Unfollowed {count} users who unfollowed me")

            # Add a delay before the next action
            random_delay()

        except Exception as e:
            logger.error(f"Error in unfollow activity: {str(e)}")

    def perform_like_activity(self):
        """Perform like-related activities"""
        try:
            # Choose a random like action
            action = random.choice([
                "like_hashtag_medias",
                "like_user_media",
                "like_followers_media",
                "like_feed_medias"
            ])

            if action == "like_hashtag_medias":
                # Choose a random hashtag from our topics
                from app.data.topics import HASHTAGS
                if HASHTAGS:
                    hashtag = random.choice(HASHTAGS)
                    count = self.actions.like.like_hashtag_medias(
                        hashtag, max_likes=5)
                    logger.info(f"Liked {count} posts from hashtag #{hashtag}")

            elif action == "like_user_media":
                # Choose a user from our topics
                from app.data.topics import TARGET_USERS
                if TARGET_USERS:
                    username = random.choice(TARGET_USERS)
                    user_id = self.client.get_client().user_id_from_username(username)
                    count = self.actions.like.like_user_media(
                        user_id, max_likes=3)
                    logger.info(f"Liked {count} posts from user {username}")

            elif action == "like_followers_media":
                count = self.actions.like.like_followers_media(
                    max_users=2, posts_per_user=2)
                logger.info(f"Liked {count} posts from my followers")

            elif action == "like_feed_medias":
                count = self.actions.like.like_feed_medias(max_likes=5)
                logger.info(f"Liked {count} posts from my feed")

            # Add a delay before the next action
            random_delay()

        except Exception as e:
            logger.error(f"Error in like activity: {str(e)}")

    def perform_comment_activity(self):
        """Perform comment-related activities"""
        try:
            # Choose a random comment action
            action = random.choice([
                "comment_on_hashtag_medias",
                "comment_on_followers_media",
                "comment_on_feed_medias"
            ])

            if action == "comment_on_hashtag_medias":
                # Choose a random hashtag from our topics
                from app.data.topics import HASHTAGS
                if HASHTAGS:
                    hashtag = random.choice(HASHTAGS)
                    count = self.actions.comment.comment_on_hashtag_medias(
                        hashtag, max_comments=2)
                    logger.info(
                        f"Commented on {count} posts from hashtag #{hashtag}")

            elif action == "comment_on_followers_media":
                count = self.actions.comment.comment_on_followers_media(
                    max_users=2)
                logger.info(f"Commented on {count} posts from my followers")

            elif action == "comment_on_feed_medias":
                count = self.actions.comment.comment_on_feed_medias(
                    max_comments=3)
                logger.info(f"Commented on {count} posts from my feed")

            # Add a delay before the next action
            random_delay()

        except Exception as e:
            logger.error(f"Error in comment activity: {str(e)}")

    def perform_direct_activity(self):
        """Perform direct message-related activities"""
        try:
            # Choose a random direct message action
            action = random.choice([
                "send_welcome_messages_to_new_followers",
                "send_engagement_messages",
                "send_inactive_follower_messages"
            ])

            if action == "send_welcome_messages_to_new_followers":
                count = self.actions.direct.send_welcome_messages_to_new_followers(
                    max_messages=2)
                logger.info(f"Sent welcome messages to {count} new followers")

            elif action == "send_engagement_messages":
                count = self.actions.direct.send_engagement_messages(
                    max_messages=1)
                logger.info(f"Sent engagement messages to {count} users")

            elif action == "send_inactive_follower_messages":
                count = self.actions.direct.send_inactive_follower_messages(
                    days_inactive=30, max_messages=1)
                logger.info(f"Sent messages to {count} inactive followers")

            # Add a delay before the next action
            random_delay()

        except Exception as e:
            logger.error(f"Error in direct message activity: {str(e)}")

    def perform_story_reaction_activity(self):
        """Perform story reaction-related activities"""
        try:
            # Choose a random story reaction action
            action = random.choice([
                "react_to_followers_stories",
                "react_to_following_stories"
            ])

            if action == "react_to_followers_stories":
                count = self.actions.story_reaction.react_to_followers_stories(
                    max_users=3, max_reactions_per_user=1)
                logger.info(f"Reacted to {count} stories from my followers")

            elif action == "react_to_following_stories":
                count = self.actions.story_reaction.react_to_following_stories(
                    max_users=3, max_reactions_per_user=1)
                logger.info(f"Reacted to {count} stories from users I follow")

            # Add a delay before the next action
            random_delay()

        except Exception as e:
            logger.error(f"Error in story reaction activity: {str(e)}")

    def update_follower_stats(self):
        """Update follower statistics in the database"""
        try:
            update_follower_counts(self.client.get_client(), self.db)
        except Exception as e:
            logger.error(f"Error updating follower stats: {str(e)}")

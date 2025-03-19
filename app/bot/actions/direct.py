import random
from datetime import datetime
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_DIRECT_LIMIT
from app.data.responses import DIRECT_MESSAGES
from app.logger import setup_logger

# Configure logging
logger = setup_logger("direct_action")


class DirectAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db

    def get_daily_direct_count(self):
        """Get the number of direct messages for today"""
        today = datetime.utcnow().date()
        stats = self.db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if stats:
            return stats.directs_count
        return 0

    def can_perform_action(self):
        """Check if we can perform a direct message action today"""
        directs_count = self.get_daily_direct_count()
        return directs_count < DAILY_DIRECT_LIMIT

    def get_appropriate_message(self, user_info=None, context=None):
        """Get a random appropriate direct message based on context"""
        if not DIRECT_MESSAGES:
            return "سلام 👋"

        # Get category based on context if available
        category = 'general'

        if context == 'new_follower':
            category = 'welcome'
        elif context == 'engagement':
            category = 'engagement'
        elif context == 'inactive':
            category = 'reconnect'

        # Select message from appropriate category if available, otherwise from general
        if category in DIRECT_MESSAGES and DIRECT_MESSAGES[category]:
            messages = DIRECT_MESSAGES[category]
        else:
            messages = DIRECT_MESSAGES.get('general', ["سلام 👋", "چطوری؟"])

        message = random.choice(messages)

        # Personalize message if user info is available
        if user_info and hasattr(user_info, 'username'):
            username = user_info.username
            message = message.replace("{username}", username)

        return message

    def send_direct_message(self, user_id, text=None, username=None):
        """Send a direct message to a specific user"""
        try:
            # Get user info if not provided
            if not username:
                user_info = self.client.user_info(user_id)
                username = user_info.username

                # Get message text if not provided
                if not text:
                    text = self.get_appropriate_message(user_info)
            elif not text:
                text = self.get_appropriate_message()

            # Send the direct message
            result = self.client.direct_send(text, [user_id])

            if result:
                # Record the activity
                activity = BotActivity(
                    activity_type="direct",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="success",
                    details=text
                )
                self.db.add(activity)

                # Update daily stats
                today = datetime.utcnow().date()
                stats = self.db.query(DailyStats).filter(
                    DailyStats.date >= today
                ).first()

                if stats:
                    stats.directs_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        directs_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully sent direct message to user {username}")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="direct",
                    target_user_id=user_id,
                    target_user_username=username,
                    status="failed",
                    details=f"Direct message failed: {text}"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(
                    f"Failed to send direct message to user {username}")
                return False

        except ClientError as e:
            # Record the error
            activity = BotActivity(
                activity_type="direct",
                target_user_id=user_id,
                target_user_username=username if username else "unknown",
                status="failed",
                details=f"Error: {str(e)}, Message: {text if text else 'None'}"
            )
            self.db.add(activity)
            self.db.commit()
            logger.error(
                f"Error sending direct message to user {user_id}: {str(e)}")
            return False

    def send_welcome_messages_to_new_followers(self, max_messages=3):
        """Send welcome messages to new followers"""
        if not self.can_perform_action():
            logger.info(
                f"Daily direct message limit reached: {DAILY_DIRECT_LIMIT}")
            return 0

        try:
            # Get my user ID
            user_id = self.client.user_id

            # Get my followers
            current_followers = self.client.user_followers(user_id)
            current_follower_ids = set(current_followers.keys())

            # Get followers we've already sent messages to from activity history
            one_day_ago = datetime.utcnow() - datetime.timedelta(days=1)
            recent_welcome_messages = self.db.query(BotActivity).filter(
                BotActivity.activity_type == "direct",
                BotActivity.created_at >= one_day_ago,
                # Simple way to identify welcome messages
                BotActivity.details.like("%welcome%")
            ).all()

            already_messaged_ids = {
                activity.target_user_id for activity in recent_welcome_messages}

            # Find new followers we haven't messaged yet
            new_followers = current_follower_ids - already_messaged_ids

            message_count = 0
            # Convert to list and shuffle
            new_follower_list = list(new_followers)
            random.shuffle(new_follower_list)

            for follower_id in new_follower_list[:max_messages]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                user_info = self.client.user_info(follower_id)

                # Get welcome message
                message = self.get_appropriate_message(
                    user_info, 'new_follower')

                # Send direct message
                if self.send_direct_message(follower_id, message, user_info.username):
                    message_count += 1

            return message_count

        except Exception as e:
            logger.error(
                f"Error sending welcome messages to new followers: {str(e)}")
            return 0

    def send_engagement_messages(self, max_messages=2):
        """Send engagement messages to users who have interacted with our content"""
        if not self.can_perform_action():
            logger.info(
                f"Daily direct message limit reached: {DAILY_DIRECT_LIMIT}")
            return 0

        try:
            # Find users who recently liked or commented on our content
            # We can use recent notifications or fetch recent activities on our media

            # For demonstration, let's focus on users who commented on our posts
            # Get my user ID
            user_id = self.client.user_id

            # Get my recent media
            my_medias = self.client.user_medias(user_id, 5)

            engaged_users = set()

            # Collect users who commented on our recent posts
            for media in my_medias:
                try:
                    comments = self.client.media_comments(media.id)
                    for comment in comments:
                        engaged_users.add(
                            (comment.user.pk, comment.user.username))
                except Exception as e:
                    logger.warning(
                        f"Could not get comments for media {media.id}: {str(e)}")
                    continue

            # Check if we've messaged these users recently (last 7 days)
            one_week_ago = datetime.utcnow() - datetime.timedelta(days=7)
            recent_messages = self.db.query(BotActivity).filter(
                BotActivity.activity_type == "direct",
                BotActivity.created_at >= one_week_ago
            ).all()

            already_messaged_ids = {
                activity.target_user_id for activity in recent_messages}

            # Filter out users we've messaged recently
            engaged_users = [(user_id, username) for user_id,
                             username in engaged_users if user_id not in already_messaged_ids]

            message_count = 0
            # Shuffle to make it more human-like
            random.shuffle(engaged_users)

            for user_id, username in engaged_users[:max_messages]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Get engagement message
                message = self.get_appropriate_message(None, 'engagement')
                message = message.replace("{username}", username)

                # Send direct message
                if self.send_direct_message(user_id, message, username):
                    message_count += 1

            return message_count

        except Exception as e:
            logger.error(f"Error sending engagement messages: {str(e)}")
            return 0

    def send_inactive_follower_messages(self, days_inactive=30, max_messages=2):
        """Send messages to followers who haven't interacted with us recently"""
        if not self.can_perform_action():
            logger.info(
                f"Daily direct message limit reached: {DAILY_DIRECT_LIMIT}")
            return 0

        try:
            # Get my user ID and followers
            user_id = self.client.user_id
            followers = self.client.user_followers(user_id)
            follower_ids = set(followers.keys())

            # Get users who have interacted with us recently
            threshold_date = datetime.utcnow() - datetime.timedelta(days=days_inactive)
            recent_interactions = self.db.query(BotActivity).filter(
                BotActivity.created_at >= threshold_date,
                BotActivity.target_user_id.in_(follower_ids)
            ).all()

            active_user_ids = {
                activity.target_user_id for activity in recent_interactions}

            # Find inactive followers
            inactive_followers = follower_ids - active_user_ids

            # Check if we've messaged these users recently (last 30 days)
            recent_messages = self.db.query(BotActivity).filter(
                BotActivity.activity_type == "direct",
                BotActivity.created_at >= threshold_date
            ).all()

            already_messaged_ids = {
                activity.target_user_id for activity in recent_messages}

            # Filter out users we've messaged recently
            inactive_followers = inactive_followers - already_messaged_ids

            message_count = 0
            # Convert to list and shuffle
            inactive_follower_list = list(inactive_followers)
            random.shuffle(inactive_follower_list)

            for follower_id in inactive_follower_list[:max_messages]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                user_info = self.client.user_info(follower_id)

                # Get reconnect message
                message = self.get_appropriate_message(user_info, 'inactive')

                # Send direct message
                if self.send_direct_message(follower_id, message, user_info.username):
                    message_count += 1

            return message_count

        except Exception as e:
            logger.error(f"Error sending inactive follower messages: {str(e)}")
            return 0

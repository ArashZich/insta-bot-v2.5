
import random
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from instagrapi.exceptions import ClientError

from app.models.database import BotActivity, DailyStats
from app.config import DAILY_STORY_REACTION_LIMIT
from app.data.responses import STORY_REACTIONS
from app.logger import setup_logger

# Configure logging
logger = setup_logger("story_reaction_action")


class StoryReactionAction:
    def __init__(self, client, db: Session):
        self.client = client
        self.db = db

    def get_daily_story_reaction_count(self):
        """Get the number of story reactions for today"""
        today = datetime.now(timezone.utc).date()
        stats = self.db.query(DailyStats).filter(
            DailyStats.date >= today
        ).first()

        if stats:
            return stats.story_reactions_count
        return 0

    def can_perform_action(self):
        """Check if we can perform a story reaction action today"""
        reactions_count = self.get_daily_story_reaction_count()
        return reactions_count < DAILY_STORY_REACTION_LIMIT

    def get_random_reaction(self, story_content=None):
        """Get a random reaction emoji or text"""
        if not STORY_REACTIONS:
            return "👍"

        # Default to emoji reactions
        reaction_type = 'emoji'

        # Randomly decide to use text reaction sometimes
        if random.random() < 0.3:  # 30% chance of using text
            reaction_type = 'text'

        # Choose reaction from the appropriate type
        if reaction_type in STORY_REACTIONS and STORY_REACTIONS[reaction_type]:
            reactions = STORY_REACTIONS[reaction_type]
            return random.choice(reactions)
        else:
            # Default fallback reactions
            emoji_defaults = ["❤️", "👍", "🔥", "👏", "😍"]
            text_defaults = ["عالی", "خیلی خوب", "جالبه", "قشنگه"]

            return random.choice(emoji_defaults if reaction_type == 'emoji' else text_defaults)

    def react_to_story(self, story_id, text=None, user_id=None, username=None):
        """React to a specific story by story_id"""
        try:
            # Get story info if user info not provided
            if not user_id or not username:
                # Note: instagrapi doesn't provide a direct method to get story info by ID
                # So we'll have to work with what we have
                # In a real scenario, we'd likely already have this info from fetching stories

                # For the sake of this example, we'll assume we don't have the info
                # and we'll use placeholder values if not provided
                user_id = user_id or "unknown"
                username = username or "unknown"

            # Get reaction text if not provided
            if not text:
                text = self.get_random_reaction()

            # React to the story
            result = self.client.story_send_reaction(story_id, [text])

            if result:
                # Record the activity
                activity = BotActivity(
                    activity_type="story_reaction",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=story_id,
                    status="success",
                    details=text
                )
                self.db.add(activity)

                # Update daily stats
                today = datetime.now(timezone.utc).date()
                stats = self.db.query(DailyStats).filter(
                    DailyStats.date >= today
                ).first()

                if stats:
                    stats.story_reactions_count += 1
                else:
                    stats = DailyStats(
                        date=today,
                        story_reactions_count=1
                    )
                    self.db.add(stats)

                self.db.commit()
                logger.info(
                    f"Successfully reacted to story {story_id} of user {username}")
                return True
            else:
                # Record failed activity
                activity = BotActivity(
                    activity_type="story_reaction",
                    target_user_id=user_id,
                    target_user_username=username,
                    target_media_id=story_id,
                    status="failed",
                    details=f"Story reaction failed: {text}"
                )
                self.db.add(activity)
                self.db.commit()
                logger.warning(f"Failed to react to story {story_id}")
                return False

        except ClientError as e:
            # Record the error
            activity = BotActivity(
                activity_type="story_reaction",
                target_user_id=user_id,
                target_user_username=username,
                target_media_id=story_id,
                status="failed",
                details=f"Error: {str(e)}, Reaction: {text if text else 'None'}"
            )
            self.db.add(activity)
            self.db.commit()
            logger.error(f"Error reacting to story {story_id}: {str(e)}")
            return False

    def react_to_user_stories(self, user_id, max_reactions=2):
        """React to stories from a specific user"""
        if not self.can_perform_action():
            logger.info(
                f"Daily story reaction limit reached: {DAILY_STORY_REACTION_LIMIT}")
            return 0

        try:
            # Get user info
            user_info = self.client.user_info(user_id)
            username = user_info.username

            # Get user stories
            stories = self.client.user_stories(user_id)

            reacted_count = 0
            # Shuffle to make it more human-like
            random.shuffle(stories)

            for story in stories[:max_reactions]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # Get random reaction
                reaction = self.get_random_reaction()

                # React to the story
                if self.react_to_story(story.id, reaction, user_id, username):
                    reacted_count += 1

            return reacted_count

        except Exception as e:
            logger.error(
                f"Error reacting to stories for user {user_id}: {str(e)}")
            return 0

    def react_to_followers_stories(self, max_users=3, max_reactions_per_user=1):
        """React to stories from users who follow us"""
        if not self.can_perform_action():
            logger.info(
                f"Daily story reaction limit reached: {DAILY_STORY_REACTION_LIMIT}")
            return 0

        try:
            # Get my user ID
            user_id = self.client.user_id

            # Get my followers
            my_followers = self.client.user_followers(user_id)

            reacted_count = 0
            # Convert to list and shuffle
            follower_ids = list(my_followers.keys())
            random.shuffle(follower_ids)

            for follower_id in follower_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # React to user's stories
                reacted_for_user = self.react_to_user_stories(
                    follower_id, max_reactions_per_user)
                reacted_count += reacted_for_user

            return reacted_count

        except Exception as e:
            logger.error(f"Error reacting to followers stories: {str(e)}")
            return 0

    def react_to_following_stories(self, max_users=5, max_reactions_per_user=1):
        """React to stories from users we follow"""
        if not self.can_perform_action():
            logger.info(
                f"Daily story reaction limit reached: {DAILY_STORY_REACTION_LIMIT}")
            return 0

        try:
            # Get my user ID
            user_id = self.client.user_id

            # Get users I'm following
            my_following = self.client.user_following(user_id)

            reacted_count = 0
            # Convert to list and shuffle
            following_ids = list(my_following.keys())
            random.shuffle(following_ids)

            for following_id in following_ids[:max_users]:
                # Skip if we've already reached the daily limit
                if not self.can_perform_action():
                    break

                # React to user's stories
                reacted_for_user = self.react_to_user_stories(
                    following_id, max_reactions_per_user)
                reacted_count += reacted_for_user

            return reacted_count

        except Exception as e:
            logger.error(f"Error reacting to following stories: {str(e)}")
            return 0

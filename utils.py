import os
from database import Database
import logging

logger = logging.getLogger(__name__)

# Re-initialize DB connection to be safe, especially in Flask threads or separate processes.
# For main bot logic, the global 'db' instance in bot.py should be fine.
db = Database()

async def check_user_force_subscription(user_id, bot_instance):
    """
    Checks if a user is subscribed to all required channels.
    Returns True if subscribed to all, False otherwise.
    If False, also returns a list of channels the user is NOT subscribed to.
    """
    if not db.is_force_subscribe_enabled():
        return True, [] # Feature is disabled, no channels required

    locked_channels = db.get_locked_channels(active_only=True)
    if not locked_channels:
        return True, [] # No channels configured for forced subscription

    not_subscribed_channels = []
    for channel in locked_channels:
        try:
            chat_member = await bot_instance.get_chat_member(chat_id=channel['channel_id'], user_id=user_id)
            if chat_member.status in ['member', 'administrator', 'creator']:
                continue # User is subscribed
            else:
                not_subscribed_channels.append(channel) # User is not subscribed
        except Exception as e:
            # This can happen if the bot is not an admin in the channel, or channel ID is incorrect.
            # Treat as "not subscribed" for safety or log it for admin investigation.
            logger.error(f"Error checking channel {channel['channel_name']} ({channel['channel_id']}) for user {user_id}: {e}")
            # If an error occurs (e.g., bot cannot get chat member info), it's safer to block.
            # You might want to consider adding a 'graceful degradation' for such channels
            # if they are optional or error often. For mandatory, they must pass.
            not_subscribed_channels.append(channel) 

    return True if not not_subscribed_channels else False, not_subscribed_channels
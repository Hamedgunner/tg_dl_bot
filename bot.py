import logging
import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
)
from telegram.constants import ParseMode # For HTML parsing in messages
from telegram.error import TelegramError
import asyncio # For running async operations (like network I/O with Telegram or to_thread)
import time # For delays if needed
from database import Database # Our custom database interaction module
from downloader import Downloader, DOWNLOADS_DIR # Our custom downloader module
from utils import check_user_force_subscription # Utility for force subscribe feature
from telegram.helpers import InputMediaPhoto, InputMediaVideo # For sending media groups (Instagram albums)

# Load environment variables from .env file at the project root
load_dotenv()

# --- Configuration Variables ---
BOT_TOKEN = os.getenv('BOT_TOKEN')
# Admin Telegram IDs for notifications. Expects a comma-separated string in .env
ADMIN_TELEGRAM_IDS = [int(aid.strip()) for aid in os.getenv('ADMIN_TELEGRAM_IDS', '').split(',') if aid.strip()]

# Telegram file size limits for direct media uploads (bytes)
# Videos/Audios as direct media (send_video, send_audio) often have practical limits
# Telegram's official document limit is 2 GB.
MAX_FILE_SIZE_FOR_DIRECT_PHOTO_MB = 20  # Roughly 20MB for photos
MAX_FILE_SIZE_FOR_DIRECT_VIDEO_AUDIO_MB = 50 # Roughly 50MB for video/audio (Telegram compresses it for playback)
TELEGRAM_DOCUMENT_MAX_SIZE_BYTES = 2 * 1024 * 1024 * 1024 # 2 GB for sending as document


# --- Webhook Specific Settings ---
WEBHOOK_PORT = int(os.getenv('WEBHOOK_PORT', 8443)) # Port for the bot's webhook to listen on
WEBHOOK_URL_PATH = BOT_TOKEN # The URL path for the webhook (using bot token for simplicity)
WEBHOOK_LISTEN_ADDRESS = os.getenv('WEBHOOK_LISTEN_ADDRESS', '0.0.0.0') # Listen on all network interfaces
DOMAIN_NAME = os.getenv('DOMAIN_NAME') # The domain name pointing to your server (must be provided in .env)
# The full URL that Telegram will call to send updates
WEBHOOK_URL = f"https://{DOMAIN_NAME}/{WEBHOOK_URL_PATH}" if DOMAIN_NAME else None

# --- Configure Logging ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Initialize Database and Downloader Classes ---
db = Database()
downloader = Downloader()

# --- Helper Functions for Bot Logic ---

async def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Constructs the inline keyboard for the main menu based on current settings."""
    keyboard_layout = []
    
    # Check button states from the database settings table
    tiktok_enabled = db.get_setting('button_tiktok_enabled') == 'true'
    instagram_enabled = db.get_setting('button_instagram_enabled') == 'true'
    youtube_enabled = db.get_setting('button_youtube_enabled') == 'true'
    x_enabled = db.get_setting('button_x_enabled') == 'true'
    generic_enabled = db.get_setting('button_generic_enabled') == 'true'

    if tiktok_enabled:
        keyboard_layout.append([InlineKeyboardButton("⬇️ دانلود از تیک تاک", callback_data="download_tiktok")])
    if instagram_enabled:
        keyboard_layout.append([InlineKeyboardButton("📸 دانلود از اینستاگرام", callback_data="download_instagram")])
    if youtube_enabled:
        keyboard_layout.append([InlineKeyboardButton("▶️ دانلود از یوتیوب", callback_data="download_youtube")])
    if x_enabled:
        keyboard_layout.append([InlineKeyboardButton("🐦 دانلود از ایکس", callback_data="download_x")])
    if generic_enabled:
        keyboard_layout.append([InlineKeyboardButton("🔗 دانلود از سایر لینک‌ها", callback_data="download_generic")])

    return InlineKeyboardMarkup(keyboard_layout)

async def check_subscription_and_notify(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """
    Checks if a user is subscribed to all required channels.
    If not, sends a message instructing them to subscribe and returns False.
    Returns True if subscribed or if force subscribe is disabled.
    """
    # User might initiate from a direct message or callback, effective_message handles both.
    message_destination = update.effective_message 

    # 'context.bot' is the Telegram Bot API client.
    is_subscribed, channels_to_join = await check_user_force_subscription(update.effective_user.id, context.bot)
    
    if not is_subscribed:
        message_text = "برای استفاده از ربات، لطفاً ابتدا در کانال‌های زیر عضو شوید:\n\n"
        for channel in channels_to_join:
            # Using HTML links for better user experience
            message_text += f"▪️ <a href=\"{channel['channel_link']}\">{channel['channel_name']}</a>\n"
        message_text += "\nپس از عضویت، روی دکمه '✅ بررسی عضویت' کلیک کنید."
        
        reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_subscription")]])
        
        # Use ParseMode.HTML to render the HTML links correctly
        await message_destination.reply_html(
            message_text,
            reply_markup=reply_markup,
            disable_web_page_preview=True # Prevent Telegram from showing large link previews
        )
        return False
    return True

# --- Command Handlers ---

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command. Welcomes new users and shows main menu."""
    user = update.effective_user # Get user details from the update

    # Add or update user in database and get their DB ID
    # add_or_update_user also logs last activity
    user_db_id = db.add_or_update_user(user)

    # Notify admins about a new user, but only if the user is not already an admin
    if user.id not in ADMIN_TELEGRAM_IDS:
        for admin_id in ADMIN_TELEGRAM_IDS:
            try:
                await context.bot.send_message(
                    chat_id=admin_id,
                    text=f"✨ کاربر جدید: {user.full_name} (@{user.username or 'N/A'}) (ID: {user.id}) ربات را استارت کرد.",
                    parse_mode=ParseMode.HTML # For formatting full_name or username if they include special chars
                )
            except TelegramError as e:
                logger.error(f"Failed to notify admin {admin_id} about new user: {e}")

    # Check for mandatory channel subscription before allowing use of bot features
    if not await check_subscription_and_notify(update, context):
        return # Stop processing if user is not subscribed

    # If subscribed, set user state to 'idle' and show main menu
    db.update_user_state(user.id, 'idle')
    keyboard = await build_main_menu_keyboard()
    await update.message.reply_html(
        f"سلام {user.mention_html()} 👋\n\nبه ربات دانلودر محتوای شبکه‌های اجتماعی خوش آمدید!\n"
        "لینک محتوای مورد نظر خود را ارسال کنید یا از دکمه‌های زیر استفاده کنید:",
        reply_markup=keyboard
    )

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /menu command. Shows the main menu to the user."""
    user = update.effective_user
    
    # Check for mandatory channel subscription
    if not await check_subscription_and_notify(update, context):
        return # Stop processing if user is not subscribed

    # If subscribed, set user state to 'idle' and show main menu
    db.update_user_state(user.id, 'idle')
    keyboard = await build_main_menu_keyboard()
    await update.message.reply_text(
        "از منوی زیر می‌توانید سرویس دانلود مورد نظر خود را انتخاب کنید:", 
        reply_markup=keyboard
    )

# --- Callback Query Handlers (Inline Buttons) ---

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles inline keyboard button presses."""
    query = update.callback_query # The callback query object
    user = query.from_user
    await query.answer() # Always answer callback queries, even if empty

    # Check for mandatory channel subscription before processing button click
    is_subscribed, channels = await check_subscription_and_notify(query, context) # Pass query for message
    if not is_subscribed:
        # Edit the original message to inform the user about subscription requirements
        # If it's a callback, we edit the message where the button was.
        await query.edit_message_text(
            f"لطفاً ابتدا در کانال‌های خواسته شده عضو شوید.",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_subscription")]])
        )
        return

    action = query.data # Get the callback data (e.g., "download_tiktok")

    if action == "check_subscription":
        # User clicked "Check subscription" button after joining channels
        is_subscribed_again, _ = await check_user_force_subscription(user.id, context.bot)
        if is_subscribed_again:
            await query.edit_message_text("عضویت شما با موفقیت تایید شد! حالا می‌توانید از ربات استفاده کنید.")
            db.update_user_state(user.id, 'idle')
            keyboard = await build_main_menu_keyboard()
            # Send main menu in a new message after confirmation
            await context.bot.send_message(chat_id=user.id, text="منوی اصلی:", reply_markup=keyboard)
        else:
            # Still not subscribed, inform them again with channels to join
            message_text = "هنوز عضو کانال‌های لازم نیستید. لطفا ابتدا عضو شده و دوباره تلاش کنید:\n\n"
            for channel in channels: # 'channels' list is from the initial check_subscription_and_notify
                 message_text += f"▪️ <a href=\"{channel['channel_link']}\">{channel['channel_name']}</a>\n"
            message_text += "\nپس از عضویت، روی دکمه '✅ بررسی عضویت' کلیک کنید."
            await query.edit_message_text(
                message_text, 
                parse_mode=ParseMode.HTML, 
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ بررسی عضویت", callback_data="check_subscription")]])
            )
        return

    # Handle various download type buttons
    platform_map = {
        "download_tiktok": "tiktok",
        "download_instagram": "instagram",
        "download_youtube": "youtube",
        "download_x": "x",
        "download_generic": "generic"
    }

    platform_key = platform_map.get(action)
    if platform_key:
        # Set the user's state to indicate which platform's link is expected next
        db.update_user_state(user.id, f'waiting_for_link_{platform_key}')
        await query.edit_message_text(f"لطفا لینک {platform_key.upper()} را برای دانلود ارسال کنید.")
    else:
        await query.edit_message_text("خطا: دکمه ناشناخته انتخاب شد.")

# --- Message Handler (for processing URLs and other text messages) ---

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Processes incoming text messages, mainly focusing on URLs for download."""
    user = update.effective_user
    message_text = update.message.text
    chat_id = update.effective_chat.id

    # Update user activity in DB or add new user if not exists
    user_db_id = db.add_or_update_user(user)

    # Check for mandatory channel subscription
    if not await check_subscription_and_notify(update, context):
        return # Stop processing if user is not subscribed

    # Retrieve user's current state from the database
    user_data = db.get_user(user.id)
    current_state = user_data['current_state'] if user_data else 'idle'
    
    # Determine which platform's link the user was supposed to send based on their state
    platform_from_state = None
    if current_state.startswith('waiting_for_link_'):
        platform_from_state = current_state.replace('waiting_for_link_', '')
        db.update_user_state(user.id, 'idle') # Reset state after receiving link

    # --- Initial URL Validation ---
    if not (message_text.startswith('http://') or message_text.startswith('https://')):
        await update.message.reply_text("لطفاً یک لینک معتبر (که با http:// یا https:// شروع شود) ارسال کنید.")
        return

    # --- Platform Determination ---
    # Try to deduce platform from URL if state is generic or idle (user pasted link directly)
    platform = platform_from_state # Default: use platform selected by button
    if platform == 'generic' or platform is None: # If not specified by button or general downloader button clicked
        if "tiktok.com" in message_text: platform = "tiktok"
        elif "instagram.com" in message_text: platform = "instagram"
        elif "youtube.com" in message_text or "youtu.be" in message_text: platform = "youtube"
        elif "x.com" in message_text or "twitter.com" in message_text: platform = "x"
        else: platform = "generic" # Keep as generic if URL doesn't match specific platforms

    # --- Check if the selected/detected platform's button is enabled in settings ---
    if platform_from_state and db.get_setting(f'button_{platform}_enabled') != 'true':
        await update.message.reply_text(f"متاسفانه، دانلود از {platform.upper()} در حال حاضر غیرفعال است.")
        return
    elif not platform_from_state and platform != 'generic' and db.get_setting(f'button_{platform}_enabled') != 'true':
         await update.message.reply_text(f"سرویس {platform.upper()} در حال حاضر غیرفعال است. لطفاً لینک یک سرویس فعال را ارسال کنید.")
         return
    elif platform == 'generic' and db.get_setting(f'button_generic_enabled') != 'true':
        await update.message.reply_text(f"سرویس دانلود از لینک‌های عمومی در حال حاضر غیرفعال است.")
        return
         
    # --- Start Download Process ---
    # Inform user that download is in progress
    processing_msg = await update.message.reply_text("در حال پردازش و دانلود... لطفاً منتظر بمانید. (این فرایند بسته به حجم فایل ممکن است کمی طول بکشد.)")

    # Log download attempt as pending in the database
    db.add_download_log(user_db_id, user.id, platform, message_text, 'pending')
    
    # Run the download operation in a separate thread to not block the event loop
    # 'best_overall' means yt-dlp decides the best quality for both video and audio.
    result = await downloader.download_content(message_text, 'best_overall')
    
    if result['status'] == 'completed':
        # Download successful, now send the file to the user
        file_path = result['path']
        file_size = result['file_size']
        file_type = result['file_type'] # 'video', 'audio', 'image'
        file_title = result['title']

        # Log completion
        db.add_download_log(user_db_id, user.id, platform, message_text, 'completed', file_path, file_size)

        try:
            # Check against Telegram's general document size limit (2GB)
            if file_size > TELEGRAM_DOCUMENT_MAX_SIZE_BYTES:
                await processing_msg.edit_text(
                    "متاسفانه حجم فایل خیلی زیاد است و امکان ارسال آن از طریق تلگرام وجود ندارد (حداکثر 2GB)."
                )
                db.add_download_log(user_db_id, user.id, platform, message_text, 'too_large', file_path, file_size, 'File too large for Telegram (over 2GB).')
                downloader.cleanup_file(file_path)
                return
                 
            # Open file in binary read mode to send via Telegram API
            with open(file_path, 'rb') as f:
                # Decide which Telegram send method to use based on file type and size
                # Note: For send_video/send_audio/send_photo, Telegram might re-compress
                # Sending as document is generally safest for larger files or to preserve original quality.
                if file_type == 'video' and file_size <= MAX_VIDEO_AUDIO_SIZE_MB * 1024 * 1024:
                    await context.bot.send_video(
                        chat_id=chat_id,
                        video=InputFile(f, filename=os.path.basename(file_path)),
                        caption=file_title,
                        # thumbnail=InputFile(open(result['thumbnail_path'], 'rb')) if 'thumbnail_path' in result else None # if you handle thumbnail downloads
                    )
                elif file_type == 'audio' and file_size <= MAX_VIDEO_AUDIO_SIZE_MB * 1024 * 1024:
                    await context.bot.send_audio(
                        chat_id=chat_id, 
                        audio=InputFile(f, filename=os.path.basename(file_path)), 
                        caption=file_title
                    )
                elif file_type == 'image' and file_size <= MAX_FILE_SIZE_FOR_DIRECT_PHOTO_MB * 1024 * 1024:
                    await context.bot.send_photo(
                        chat_id=chat_id, 
                        photo=InputFile(f, filename=os.path.basename(file_path)), 
                        caption=file_title
                    )
                else:
                    # For larger files or general file types, send as document
                    await context.bot.send_document(
                        chat_id=chat_id, 
                        document=InputFile(f, filename=os.path.basename(file_path)), 
                        caption=file_title
                    )

            await processing_msg.delete() # Delete the "processing..." message
            downloader.cleanup_file(file_path) # Delete the downloaded file from server to save space
            # Log that the file was successfully sent to the user
            db.add_download_log(user_db_id, user.id, platform, message_text, 'file_sent', file_path, file_size)

        except TelegramError as e:
            # Handle specific Telegram API errors
            error_message_to_user = f"خطا در ارسال فایل به تلگرام: {e}"
            if "file size is too big" in str(e):
                error_message_to_user = "خطا در ارسال فایل: حجم فایل بیش از حد مجاز تلگرام است."
                db.add_download_log(user_db_id, user.id, platform, message_text, 'too_large', file_path, file_size, f"Telegram send error: {e}")
            elif "Request entity too large" in str(e):
                error_message_to_user = "خطا در ارسال فایل: درخواست ارسال بیش از حد بزرگ است."
                db.add_download_log(user_db_id, user.id, platform, message_text, 'too_large', file_path, file_size, f"Telegram send error: {e}")
            elif "bot was blocked by the user" in str(e):
                error_message_to_user = "خطا در ارسال فایل: ربات توسط شما مسدود شده است."
                db.set_user_blocked_status(user.id, True) # Mark user as blocked in DB
            
            await processing_msg.edit_text(error_message_to_user)
            logger.error(f"Telegram API Error sending file {file_path} to user {user.id}: {e}")
            downloader.cleanup_file(file_path) # Still cleanup
            db.add_download_log(user_db_id, user.id, platform, message_text, 'failed', file_path, file_size, f"Telegram API error: {e}")

        except Exception as e:
            # Catch any other unexpected errors during file sending
            await processing_msg.edit_text(f"خطا در ارسال فایل: {e}. لطفاً دوباره امتحان کنید.")
            logger.error(f"Unknown error sending file {file_path} to Telegram for user {user.id}: {e}")
            downloader.cleanup_file(file_path) # Still cleanup
            db.add_download_log(user_db_id, user.id, platform, message_text, 'failed', file_path, file_size, f"Unexpected send error: {e}")

    elif result['status'] == 'album':
        # Handle media albums (e.g., Instagram carousel posts)
        try:
            media_group = []
            # sent_count_album_items = 0
            
            # Telegram Media Group limitations: Max 10 photos/videos. File size limits.
            # If an item is too large for a group, or too many items, they need to be sent individually as documents.

            for item in result['files']:
                path = item['path']
                title = item['title']
                file_type = item['type'] 
                
                if not os.path.exists(path):
                    logger.warning(f"File {path} from album not found, skipping for sending.")
                    continue

                item_size = os.path.getsize(path)

                # Prioritize adding to media_group if it meets typical media size limits
                # Otherwise, plan to send it as a separate document
                if file_type == 'video' and item_size <= MAX_VIDEO_AUDIO_SIZE_MB * 1024 * 1024:
                    media_group.append(InputMediaVideo(media=InputFile(open(path, 'rb')), caption=title))
                elif file_type == 'image' and item_size <= MAX_FILE_SIZE_FOR_DIRECT_PHOTO_MB * 1024 * 1024:
                    media_group.append(InputMediaPhoto(media=InputFile(open(path, 'rb')), caption=title))
                else:
                    # Item is too large for media group or other non-standard type, send as document
                    await context.bot.send_document(
                        chat_id=chat_id, 
                        document=InputFile(open(path, 'rb'), filename=os.path.basename(path)), 
                        caption=title
                    )
                    logger.info(f"Sent album item {os.path.basename(path)} as document for user {user.id} due to size/type limitations.")
                    downloader.cleanup_file(path) # Clean up individual items as they are sent
                    # sent_count_album_items += 1 # If tracking individually sent items


            # Send media group in chunks of 10
            # Ensure proper handling of file handles when sending media groups (InputFile from open() objects)
            # The files might be opened multiple times, and need proper closing.
            # Python-telegram-bot handles open file objects internally quite well,
            # but for robust code, you might explicitly manage file handles.
            
            total_media_items_sent_in_groups = 0
            for i in range(0, len(media_group), 10):
                try:
                    current_chunk = media_group[i:i+10]
                    # This makes actual file handles, which need to stay open until sent
                    media_for_send = [InputMediaPhoto(media.media) if isinstance(media, InputMediaPhoto) else InputMediaVideo(media.media) for media in current_chunk]
                    
                    # Ensure captions are handled. Captions only on first item.
                    if current_chunk:
                         media_for_send[0].caption = current_chunk[0].caption

                    await context.bot.send_media_group(chat_id=chat_id, media=media_for_send)
                    total_media_items_sent_in_groups += len(current_chunk)

                except TelegramError as e:
                    logger.error(f"Error sending media group chunk to user {user.id}: {e}")
                    # You might add logic here to retry sending remaining items as documents if media group fails
                    await context.bot.send_message(chat_id=chat_id, text=f"خطا در ارسال برخی آیتم‌های آلبوم به صورت گروهی. (Error: {e})")
                except Exception as e:
                     logger.error(f"Unexpected error sending media group: {e}")
                     await context.bot.send_message(chat_id=chat_id, text=f"خطا در ارسال آلبوم. (Error: {e})")

            await processing_msg.delete() # Delete "processing..." message

            # Clean up all files *after* all attempts to send the album
            for item in result['files']:
                downloader.cleanup_file(item['path'])
            
            # Log album sending status
            if total_media_items_sent_in_groups > 0:
                db.add_download_log(user_db_id, user.id, platform, message_text, 'file_sent', error_message=f'Album sent successfully with {total_media_items_sent_in_groups} media group items.')
            else:
                await update.message.reply_text("متاسفانه هیچ کدام از محتوای آلبوم قابل ارسال نبود.")
                db.add_download_log(user_db_id, user.id, platform, message_text, 'failed', error_message='No album items sent or all sent as documents.')


        except Exception as e:
            await processing_msg.edit_text(f"خطا در ارسال آلبوم: {e}")
            logger.error(f"Error handling album from {message_text} for user {user.id}: {e}")
            for item in result['files']: # Ensure cleanup even if album sending fails
                downloader.cleanup_file(item['path'])
            db.add_download_log(user_db_id, user.id, platform, message_text, 'failed', error_message=f"Album handling error: {e}")

    else:
        # Download failed or returned an unknown status
        await processing_msg.edit_text(
            result.get('message', "خطا در دانلود یا محتوا یافت نشد. لطفاً مطمئن شوید لینک معتبر و عمومی است.")
        )
        # Log the failure
        db.add_download_log(user_db_id, user.id, platform, message_text, 'failed', error_message=result.get('message', 'Unknown download error'))


# --- Main Function to Run the Bot ---

def main():
    """Sets up and runs the Telegram Bot."""
    if not BOT_TOKEN or not DOMAIN_NAME:
        logger.critical("BOT_TOKEN or DOMAIN_NAME environment variables are not set. Exiting.")
        exit(1)
        
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # --- Register Handlers ---
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    # MessageHandler to process text messages that are not commands
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # --- Run the bot with Webhook for Public Deployment ---
    # Telegram will send updates to the configured WEBHOOK_URL
    logger.info(f"Setting webhook for bot to URL: {WEBHOOK_URL} on port {WEBHOOK_PORT} (listening on {WEBHOOK_LISTEN_ADDRESS}).")
    application.run_webhook(
        listen=WEBHOOK_LISTEN_ADDRESS, # IP address for the server to listen on
        port=WEBHOOK_PORT,             # Port for the server to listen on
        url_path=WEBHOOK_URL_PATH,     # The path that Telegram sends updates to (part of WEBHOOK_URL)
        webhook_url=WEBHOOK_URL,       # The full URL that Telegram will call
        # cert="/path/to/fullchain.pem" # If you get your certificate in a way that certbot doesn't handle,
                                       # you might need to provide the cert path directly to run_webhook.
                                       # Certbot/Nginx handles this for us by forwarding to HTTP 8443 behind it.
    )

if __name__ == "__main__":
    # Ensure the 'downloads' directory exists at startup
    if not os.path.exists(DOWNLOADS_DIR):
        try:
            os.makedirs(DOWNLOADS_DIR)
            logger.info(f"Created downloads directory: {DOWNLOADS_DIR}")
        except OSError as e:
            logger.critical(f"Failed to create downloads directory {DOWNLOADS_DIR}: {e}. Exiting.")
            exit(1)
    
    # Basic check for database connection on startup
    db_test = Database()
    try:
        db_test.connect()
        if db_test.connection:
            logger.info("Database connection successful at startup.")
        else:
            logger.critical("Database connection failed at startup. Exiting.")
            exit(1)
    finally:
        db_test.close()

    main() # Call the main function to start the bot
import os
import logging
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Break management data
break_data = {
    "toilet": {"users": {}, "limit": 2, "daily_limit": 5},
    "drinking": {"users": {}, "limit": 2, "daily_limit": 5},
    "outside": {"users": {}, "limit": 4, "daily_limit": 5}
}

# Store late return reasons and fines
late_returns = {}
fines = {}

# Admin chat ID (replace with your Telegram chat ID)
ADMIN_CHAT_ID = 6495686029  # Change this to your admin chat ID

# Command: /start
async def start(update: Update, context: CallbackContext):
    keyboard = [["Toilet Break", "Drinking Break", "Outside Break", "Check Availability"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    await update.message.reply_text("Please choose a break type:", reply_markup=reply_markup)

# Handle break requests
async def handle_break(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    username = update.message.from_user.username
    break_type = update.message.text.lower().replace(" break", "")

    # Check if the user is already on a break
    for break_name, data in break_data.items():
        if user_id in data["users"]:
            await update.message.reply_text("You must return from your current break before starting a new one.")
            return

    if break_type not in break_data:
        await update.message.reply_text("Invalid break type. Please try again.")
        return

    data = break_data[break_type]

    # Check if user has exceeded daily limit
    if user_id in data["users"] and len(data["users"][user_id]) >= data["daily_limit"]:
        await update.message.reply_text(f"You’ve reached your daily {break_type} break limit ({data['daily_limit']}).")
        return

    # Check if break slot is available
    if len(data["users"]) >= data["limit"]:
        await update.message.reply_text(f"Sorry, only {data['limit']} people are allowed on a {break_type} break at a time.")
        return

    # Start break
    start_time = datetime.now()
    data["users"][user_id] = {"start_time": start_time, "username": username}
    await update.message.reply_text(f"Your {break_type} break has started. You have 15 minutes. Please return on time!")

    # Notify admin
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"@{username} has started a {break_type} break at {start_time.strftime('%H:%M:%S')}."
    )

    # Schedule break end
    async def end_break(context: CallbackContext):
        if user_id in data["users"]:
            end_time = datetime.now()
            duration = (end_time - start_time).seconds // 60  # Duration in minutes
            data["users"].pop(user_id)

            # Check if the user is late
            if duration > 15:
                late_returns[user_id] = {"username": username, "break_type": break_type, "duration": duration}
                await update.message.reply_text("You are late! Please provide a reason for your delay.")
            else:
                await update.message.reply_text(
                    f"@{username} took {duration} minutes for {break_type}.\n"
                    "You can go for another break after 15 minutes."
                )

            # Notify admin
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"@{username} has ended their {break_type} break after {duration} minutes."
            )

    context.job_queue.run_once(end_break, 15 * 60)  # 15 minutes

# Handle late return reason
async def handle_reason(update: Update, context: CallbackContext):
    user_id = update.message.from_user.id
    reason = update.message.text

    if user_id in late_returns:
        username = late_returns[user_id]["username"]
        break_type = late_returns[user_id]["break_type"]
        duration = late_returns[user_id]["duration"]

        # Notify admin for approval
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"@{username} was late for their {break_type} break by {duration - 15} minutes.\n"
                 f"Reason: {reason}\n"
                 "Approve fine of 100 PKR? (Yes/No)"
        )
        late_returns[user_id]["reason"] = reason
    else:
        await update.message.reply_text("You are not currently on a break.")

# Handle admin approval for fines
async def handle_admin_approval(update: Update, context: CallbackContext):
    if update.message.chat_id == ADMIN_CHAT_ID:
        text = update.message.text.lower()
        if text in ["yes", "no"]:
            for user_id, data in late_returns.items():
                username = data["username"]
                break_type = data["break_type"]
                duration = data["duration"]
                reason = data["reason"]

                if text == "yes":
                    fines[user_id] = 100
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"A fine of 100 PKR has been imposed for being late on your {break_type} break."
                    )
                    await update.message.reply_text(f"Fine of 100 PKR imposed on @{username}.")
                else:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text="Your reason for being late has been accepted. No fine imposed."
                    )
                    await update.message.reply_text(f"No fine imposed on @{username}.")

                # Clear late return data
                del late_returns[user_id]

# Command: /check
async def check_availability(update: Update, context: CallbackContext):
    message = "Break Availability:\n"
    for break_type, data in break_data.items():
        message += f"- {break_type.capitalize()}: {len(data['users'])}/{data['limit']} people\n"
    await update.message.reply_text(message)

# Reset data at midnight
async def reset_data(context: CallbackContext):
    global break_data, late_returns, fines
    break_data = {
        "toilet": {"users": {}, "limit": 2, "daily_limit": 5},
        "drinking": {"users": {}, "limit": 2, "daily_limit": 5},
        "outside": {"users": {}, "limit": 4, "daily_limit": 5}
    }
    late_returns = {}
    fines = {}
    logger.info("Data reset for the new day.")

# Main function
def main():
    # Use environment variable for the token
    application = ApplicationBuilder().token(os.getenv('TELEGRAM_BOT_TOKEN')).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.Text(["Toilet Break", "Drinking Break", "Outside Break"]), handle_break))
    application.add_handler(MessageHandler(filters.Text(["I'm back"]), handle_return))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_approval))
    application.add_handler(CommandHandler("check", check_availability))

    # Schedule data reset at midnight
    now = datetime.now()
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    application.job_queue.run_once(reset_data, (midnight - now).total_seconds())

    # Start the bot
    application.run_polling()

if __name__ == '__main__':
    main()

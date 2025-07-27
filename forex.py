import json
import random
import os
import re
import pytesseract
import string
from PIL import Image
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
    MessageHandler,
    filters
)

PENDING_APPROVALS = {}  # Stores pending approval requests: {message_id: (user_id, amount)}
BOT_TOKEN = '7207157292:AAH_AL1rnxPcEK4E23ZxQenf5OdatBhhV-k'
ADMIN_USER_ID = 7402408566
BALANCE_FILE = "user_balances.json"
TRANSACTION_LOG = "transactions.log"
REFERRALS_FILE = "referrals.json"
REFERRAL_BONUS = 15

if not os.path.exists(BALANCE_FILE):
    with open(BALANCE_FILE, 'w') as f:
        json.dump({}, f)

def load_referrals():
    if not os.path.exists(REFERRALS_FILE):
        return {
            "user_codes": {},
            "code_to_user": {},
            "referrals": {},
            "referred_by": {},
            "bonus_given": {}
        }
    try:
        with open(REFERRALS_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            "user_codes": {},
            "code_to_user": {},
            "referrals": {},
            "referred_by": {},
            "bonus_given": {}
        }

def save_referrals(data):
    with open(REFERRALS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def generate_referral_code(length=6):
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

async def award_referral_bonus(user_id, context: ContextTypes.DEFAULT_TYPE):
    referrals = load_referrals()
    user_id_str = str(user_id)
    referred_by = referrals.get('referred_by', {})
    bonus_given = referrals.get('bonus_given', {})
    
    if user_id_str in referred_by and user_id_str not in bonus_given:
        ref_code = referred_by[user_id_str]
        code_to_user = referrals.get('code_to_user', {})
        
        if ref_code in code_to_user:
            referrer_id = int(code_to_user[ref_code])
            # Give bonus to referrer
            update_balance(referrer_id, REFERRAL_BONUS)
            # Mark as given
            referrals['bonus_given'][user_id_str] = True
            save_referrals(referrals)
            
            # Notify referrer
            try:
                await context.bot.send_message(
                    chat_id=referrer_id,
                    text=f"🎉 You received a {REFERRAL_BONUS} birr referral bonus! User {user_id} made their first deposit."
                )
            except Exception as e:
                print(f"Failed to notify referrer: {e}")

class MiningGame:
    def __init__(self, user_id: int, base_amount: int):
        self.user_id = user_id
        self.grid_size = 16
        self.bomb_count = 3
        self.bomb_positions = random.sample(range(self.grid_size), self.bomb_count)
        self.revealed = [False] * self.grid_size
        self.score = 0
        self.game_over = False
        self.message_id = None
        self.base_amount = base_amount  # Store base amount per game

    def reveal_tile(self, index: int) -> str:
        if index in self.bomb_positions:
            self.game_over = True
            return "bomb"
        if not self.revealed[index]:
            self.revealed[index] = True
            self.score += 2
            return "safe"
        return "already_revealed"

    def all_safe_revealed(self) -> bool:
        safe_tiles = [i for i in range(self.grid_size) if i not in self.bomb_positions]
        return all(self.revealed[i] for i in safe_tiles)

def load_balances():
    try:
        with open(BALANCE_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

def save_balances(balances: dict):
    with open(BALANCE_FILE, 'w') as f:
        json.dump(balances, f, indent=2)

def update_balance(user_id: int, amount: int) -> int:
    user_str = str(user_id)
    balances = load_balances()
    if user_str not in balances:
        balances[user_str] = 0
    balances[user_str] += amount
    save_balances(balances)
    log_transaction(user_id, amount, balances[user_str])
    return balances[user_str]

def get_balance(user_id: int) -> int:
    balances = load_balances()
    return balances.get(str(user_id), 0)

def log_transaction(user_id: int, amount: int, new_balance: int):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(TRANSACTION_LOG, 'a') as f:
        f.write(f"{timestamp} | User {user_id} | Amount: {amount:+} | New Balance: {new_balance}\n")

async def send_game_board(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = context.user_data.get('game')
    if not game:
        return
    keyboard = []
    for i in range(16):
        emoji = "🟦"
        if game.game_over and i in game.bomb_positions:
            emoji = "💣"
        elif game.revealed[i]:
            emoji = "✅"
        keyboard.append(InlineKeyboardButton(emoji, callback_data=f"dig_{i}"))
    grid = [keyboard[i:i+4] for i in range(0, 16, 4)]
    if any(game.revealed):
        grid.append([InlineKeyboardButton("💸 Cash Out", callback_data="cashout")])
    tiles = game.score // 2
    multiplier = f"{tiles}x" if tiles > 0 else "—"
    msg = (
        f"💰 Balance: {get_balance(game.user_id)} birr | 🏆 Tiles: {tiles} | 🎯 Odd: {multiplier}\n"
        f"🔍 Tiles left: {16 - sum(game.revealed) - 3}\n\n"
        "Click a tile to dig:"
    )
    if game.message_id:
        await context.bot.edit_message_text(
            text=msg,
            chat_id=update.effective_chat.id,
            message_id=game.message_id,
            reply_markup=InlineKeyboardMarkup(grid)
        )
    else:
        sent = await update.effective_message.reply_text(msg, reply_markup=InlineKeyboardMarkup(grid))
        game.message_id = sent.message_id

async def handle_dig(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    game = context.user_data.get('game')
    if not game:
        await query.answer("No game in progress.")
        return
        
    index = int(query.data.split('_')[1])
    result = game.reveal_tile(index)
    await query.answer()
    await send_game_board(update, context)
    
    # Handle bomb hit
    if result == "bomb":
        safe_tiles = game.score // 2
        
        # Special case for 7 or 8 tiles
        if safe_tiles in (7, 8):
            multiplier = 1.6
            earnings = round(game.base_amount * multiplier)
            new_balance = update_balance(game.user_id, earnings)
            await query.message.reply_text(
                f"💥 BOOM! You hit a bomb!\n"
                f"✅ Safe tiles: {safe_tiles}\n"
                f"🏅 Multiplier: {multiplier}x\n"
                f"💰 Earned: {earnings} birr\n"
                f"💳 New balance: {new_balance} birr"
            )
        elif safe_tiles > 0:
            # 1-6 tiles: no payout
            await query.message.reply_text(
                "💥 BOOM! You hit a bomb!\n"
                "😢 You earned 0 birr this round\n"
                "❌ Try again!"
            )
        else:
            # 0 tiles: no payout
            await query.message.reply_text(
                "💥 BOOM! You hit a bomb!\n"
                "😢 You earned 0 birr this round\n"
                "❌ Try again!"
            )
        context.user_data.pop('game')
        return
    
    # Handle winning by clearing all safe tiles
    if result == "safe" and game.all_safe_revealed():
        safe_tiles = game.score // 2
        multiplier = round(1.6 if safe_tiles == 1 else safe_tiles, 2)
        earnings = round(game.base_amount * multiplier)
        new_balance = update_balance(game.user_id, earnings)
        await query.message.reply_text(
            f"🎉 You cleared the minefield!\n"
            f"✅ Safe tiles: {safe_tiles}\n"
            f"🏅 Multiplier: {multiplier}x\n"
            f"💰 Earned: {earnings} birr\n"
            f"💳 New balance: {new_balance} birr"
        )
        context.user_data.pop('game')

async def handle_cashout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = update.effective_user.id
    game = context.user_data.get('game')
    
    if not game:
        await query.answer("No active game to cash out")
        return
        
    # Calculate winnings based on revealed tiles
    safe_tiles = game.score // 2
    if safe_tiles == 0:
        await query.answer("❌ You haven't revealed any tiles yet", show_alert=True)
        return
        
    multiplier = 1.6 if safe_tiles == 1 else safe_tiles
    earnings = round(game.base_amount * multiplier)
    
    # Update balance with winnings
    new_balance = update_balance(game.user_id, earnings)
    
    # Show cashout message
    await query.answer()
    await query.message.reply_text(
        f"💸 You cashed out!\n"
        f"✅ Safe tiles: {safe_tiles}\n"
        f"🏅 Multiplier: {multiplier}x\n"
        f"💰 Earned: {earnings} birr\n"
        f"💳 New balance: {new_balance} birr"
    )
    
    # End game
    context.user_data.pop('game')
    
    # Update game board to show results
    try:
        await context.bot.edit_message_text(
            text=query.message.text + "\n\n💸 Cashed Out!",
            chat_id=update.effective_chat.id,
            message_id=query.message.message_id,
            reply_markup=None
        )
    except:
        pass

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = get_balance(user_id)
    IMAGE_PATH = r"C:\Users\Sami and Edd\Downloads\6099997903e5f63e87b6945d4a0bf591-modified.png"

    try:
        with open(IMAGE_PATH, "rb") as photo:
            await update.message.reply_photo(photo)
    except Exception as e:
        print(f"❌ Error sending welcome image: {e}")
    
    # Ensure user has referral code
    referrals = load_referrals()
    if str(user_id) not in referrals.get('user_codes', {}):
        code = generate_referral_code()
        while code in referrals.get('code_to_user', {}):
            code = generate_referral_code()
        referrals['user_codes'][str(user_id)] = code
        referrals['code_to_user'][code] = str(user_id)
        save_referrals(referrals)
    
    # Check for referral code in command
    if context.args and context.args[0].startswith('ref'):
        ref_code = context.args[0][3:]
        referrals = load_referrals()
        code_to_user = referrals.get('code_to_user', {})
        
        if ref_code in code_to_user:
            # Record the referral
            referred_by = referrals.get('referred_by', {})
            if str(user_id) not in referred_by:
                referrals['referred_by'][str(user_id)] = ref_code
                if ref_code not in referrals['referrals']:
                    referrals['referrals'][ref_code] = []
                if str(user_id) not in referrals['referrals'][ref_code]:
                    referrals['referrals'][ref_code].append(str(user_id))
                save_referrals(referrals)
    
    buttons = [
        [InlineKeyboardButton("💰 Deposit", callback_data="deposit")],
        [InlineKeyboardButton("🕹️ Start Mining", callback_data="start")],
        [InlineKeyboardButton("💳 Balance", callback_data="balance")],
        [InlineKeyboardButton("📤 Refer Friends", callback_data="referral")],
        [InlineKeyboardButton("🏆 Top Miners", callback_data="top_miners")]
    ]
    await update.message.reply_text(
        f"⛏️ Welcome {update.effective_user.first_name}!\n\n💰 Your Balance: {balance} birr\n\nChoose an option:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def top_miners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    # Format the leaderboard with monospace
    leaderboard = (
        "🏆 *TOP MINERS LEADERBOARD* 🏆\n\n"
        "```\n"
        "25191*59➡️➡️➡️5,000 br\n"
        "25194*94➡️➡️➡️5,000 br\n"
        "25191*00➡️➡️➡️2,500 br\n"
        "25192*11➡️➡️➡️2,500 br\n"
        "25192*65➡️➡️➡️2,500 br\n"
        "25191*42➡️➡️➡️2,500 br\n"
        "25194*21➡️➡️➡️2,500 br\n"
        "25191*75➡️➡️➡️2,500 br\n"
        "25191*62➡️➡️➡️2,500 br\n"
        "25191*97➡️➡️➡️2,500 br\n"
        "25195*46➡️➡️➡️2,500 br\n"
        "25194*19➡️➡️➡️2,500 br\n"
        "25191*50➡️➡️➡️1,000 br\n"
        "25194*80➡️➡️➡️1,000 br\n"
        "25195*05➡️➡️➡️1,000 br\n"
        "25196*94➡️➡️➡️1,000 br\n"
        "25195*14➡️➡️➡️1,000 br\n"
        "```"
    )
    
    keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
    await query.edit_message_text(
        leaderboard,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    user_id = update.effective_user.id

    if data == "start":
        balance = get_balance(user_id)
        if balance < 10:
            await query.answer("❌ You need at least 15 birr to start mining", show_alert=True)
            return
            
        # Ask for bet amount
        context.user_data['awaiting_bet'] = True
        await query.message.reply_text("💵 How much would you like to bet? (Minimum 15 birr)")
    elif data == "balance":
        balance = get_balance(user_id)
        keyboard = [[InlineKeyboardButton("💸 Withdraw Funds", callback_data="withdraw_start")]]
        await query.edit_message_text(
            text=f"💰 Your current balance is: {balance} birr",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    elif data == "cashout":
        await handle_cashout(update, context)
    elif data == "deposit":
        buttons = [
            [InlineKeyboardButton("📱 Pay with Telebirr", callback_data="pay_telebirr")],
            [InlineKeyboardButton("🏦 Pay with CBE", callback_data="pay_cbe")]
        ]
        await query.edit_message_text(
            "💵 Choose a payment method:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    elif data == "pay_telebirr":
        context.user_data['awaiting_screenshot'] = True  # Set flag to expect photo
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=(
                "📲 *Telebirr Wallet Info:*\n"
                "```\n"
                "Name: Minning Rush\n"
                "Number: *+251912345678*\n"
                "Minimum Deposit: 15 birr\n"
                "Note: Send screenshot of payment confirmation after payment\n"
                "```"
            ),
            parse_mode='Markdown'
        )
    elif data == "pay_cbe":
        context.user_data['awaiting_screenshot'] = True  # Set flag to expect photo
        await context.bot.send_message(
            chat_id=query.message.chat.id,
            text=(
                "🏦 *CBE Account Info:*\n"
                "```\n"
                "Bank: Commercial Bank of Ethiopia\n"
                "Account Name: Minning Rush\n"
                "Account Number: *1234567890*\n"
                "Minimum Deposit: 15 birr\n"
                "Note: Send screenshot of payment confirmation after payment\n"
                "```"
            ),
            parse_mode='Markdown'
        )
    elif data == "withdraw_start":
        balance = get_balance(user_id)
        if balance < 20:
            await query.answer("❌ Minimum withdrawal is 20 birr.", show_alert=True)
            return
        await query.message.reply_text("💸 Please enter the amount you want to withdraw:")
        context.user_data['awaiting_withdraw'] = True
    elif data == "referral":
        user_id = update.effective_user.id
        referrals = load_referrals()
        user_id_str = str(user_id)
        
        # Get user's referral code
        code = referrals['user_codes'].get(user_id_str)
        if not code:
            await query.answer("Error: No referral code found")
            return
            
        # Count successful referrals
        successful = 0
        if code in referrals['referrals']:
            for referred_id in referrals['referrals'][code]:
                if referred_id in referrals.get('bonus_given', {}):
                    successful += 1
                    
        total_referrals = len(referrals['referrals'].get(code, []))
        
        text = (
            f"📤 *Refer Friends & Earn!*\n\n"
            f"🔗 Your referral link:\n"
            f"`https://t.me/{(await context.bot.get_me()).username}?start=ref{code}`\n\n"
            f"👥 Total referrals: {total_referrals}\n"
            f"✅ Successful referrals: {successful}\n"
            f"💰 Total bonus earned: {successful * REFERRAL_BONUS} birr\n\n"
            f"*How it works:*\n"
            f"1. Share your link with friends\n"
            f"2. When they join and make their first deposit (min 15 birr), you get {REFERRAL_BONUS} birr bonus!\n"
        )
        
        keyboard = [[InlineKeyboardButton("⬅️ Back", callback_data="back_to_main")]]
        await query.edit_message_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))
    elif data == "top_miners":
        await top_miners(update, context)
    elif data == "back_to_main":
        user_id = update.effective_user.id
        balance = get_balance(user_id)
        buttons = [
            [InlineKeyboardButton("💰 Deposit", callback_data="deposit")],
            [InlineKeyboardButton("🕹️ Start Mining", callback_data="start")],
            [InlineKeyboardButton("💳 Balance", callback_data="balance")],
            [InlineKeyboardButton("📤 Refer Friends", callback_data="referral")],
            [InlineKeyboardButton("🏆 Top Miners", callback_data="top_miners")]
        ]
        await query.edit_message_text(
            f"⛏️ Welcome back!\n\n💰 Your Balance: {balance} birr\n\nChoose an option:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text

    # Check if we're expecting a bet amount
    if context.user_data.get('awaiting_bet'):
        context.user_data.pop('awaiting_bet', None)  # Reset state
        
        # Extract bet amount
        numbers = re.findall(r"\d+", text)
        if not numbers:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

        bet_amount = int(numbers[0])
        balance = get_balance(user_id)

        if bet_amount < 10:
            await update.message.reply_text("❌ Minimum bet is 10 birr.")
            return
            
        if bet_amount > balance:
            await update.message.reply_text(f"❌ You only have {balance} birr. You can't bet more than your balance.")
            return

        # Deduct the bet amount from balance
        update_balance(user_id, -bet_amount)
        
        # Start game with bet amount
        context.user_data['game'] = MiningGame(user_id, bet_amount)
        await update.message.reply_text(f"✅ Bet of {bet_amount} birr placed. Let's start mining!")
        await send_game_board(update, context)
        return

    # Check if we're expecting a withdrawal amount
    if context.user_data.get('awaiting_withdraw'):
        context.user_data['awaiting_withdraw'] = False  # Reset state
        
        # Extract withdrawal amount
        numbers = re.findall(r"\d+", text)
        if not numbers:
            await update.message.reply_text("❌ Please enter a valid number.")
            return

        amount = int(numbers[0])
        balance = get_balance(user_id)

        if amount > balance:
            await update.message.reply_text(f"❌ You only have {balance} birr. You can't withdraw more than your balance.")
            return

        if amount < 20:
            await update.message.reply_text("❌ Minimum withdrawal is 20 birr.")
            return

        update_balance(user_id, -amount)
        await update.message.reply_text(f"✅ Withdraw request of {amount} birr received. We'll process it soon.")

        # Notify admin
        await context.bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                f"📬 *New Withdraw Request*\n"
                f"👤 User: {update.effective_user.full_name} (ID: `{user_id}`)\n"
                f"💸 Amount: {amount} birr\n"
                f"📩 Username: @{update.effective_user.username or 'N/A'}"
            ),
            parse_mode='Markdown'
        )
        return

    # Otherwise handle as deposit confirmation
    numbers = re.findall(r"\d+", text)
    if not numbers:
        await update.message.reply_text("❌ Please mention how much you paid.")
        return
    amount = int(numbers[0])
    if amount < 15:
        await update.message.reply_text("❌ Minimum deposit is 15 birr.")
        return
    update_balance(user_id, amount)
    await award_referral_bonus(user_id, context)  # Award referral bonus if applicable
    await update.message.reply_text(f"✅ Payment of {amount} birr received. Your balance is now {get_balance(user_id)} birr.")

async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('awaiting_screenshot'):
        return

    context.user_data['awaiting_screenshot'] = False
    user_id = update.effective_user.id

    photo_file = update.message.photo[-1]
    amount = await extract_amount_from_photo(photo_file, context)

    context.user_data['deposit_amount'] = amount

    await update.message.reply_text("✅ Thank you! The admin will review your payment shortly.")

    photo_file_id = photo_file.file_id

    try:
        sent_message = await context.bot.send_photo(
            chat_id=ADMIN_USER_ID,
            photo=photo_file_id,
            caption=(
                f"🖼️ *New Payment Screenshot*\n"
                f"👤 User: {update.effective_user.full_name}\n"
                f"🆔 ID: `{user_id}`\n"
                f"📩 Username: @{update.effective_user.username or 'N/A'}\n"
                f"💰 Amount: {amount} birr\n\n"
                f"⚠️ Please verify payment:"
            ),
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Approve Payment", callback_data=f"approve_{user_id}_{amount}"),
                    InlineKeyboardButton("❌ Decline Payment", callback_data=f"decline_{user_id}")
                ]
            ])
        )
        PENDING_APPROVALS[sent_message.message_id] = (user_id, amount)

    except Exception as e:
        print(f"Error sending photo to admin: {e}")
        await update.message.reply_text("❌ Failed to send payment to admin. Please try again later.")

async def handle_admin_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    admin_id = update.effective_user.id
    
    # Only allow admin to handle approvals
    if admin_id != ADMIN_USER_ID:
        await query.answer("❌ Only admin can approve payments", show_alert=True)
        return
        
    if data.startswith("approve_"):
        # Extract user info from callback data
        _, user_id, amount = data.split('_')
        user_id = int(user_id)
        amount = int(amount)
        
        # Update user balance
        new_balance = update_balance(user_id, amount)
        await award_referral_bonus(user_id, context)  # Award referral bonus if applicable
        
        # Notify user
        await context.bot.send_message(
            chat_id=user_id,
            text=f"✅ Your payment of {amount} birr has been approved!\n"
                 f"💳 New balance: {new_balance} birr\n"
                 f"Press 'Start Mining' to play"
        )
        
        # Update admin message
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n✅ APPROVED",
            reply_markup=None
        )
        await query.answer(f"Approved {amount} birr for user {user_id}")
        
    elif data.startswith("decline_"):
        # Extract user info from callback data
        _, user_id = data.split('_')
        user_id = int(user_id)
        
        # Notify user
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Your payment was declined. Please contact admin if this is a mistake."
        )
        
        # Update admin message
        await query.edit_message_caption(
            caption=query.message.caption + "\n\n❌ DECLINED",
            reply_markup=None
        )
        await query.answer("Payment declined")

async def extract_amount_from_photo(photo_file, context):
    file = await photo_file.get_file()
    file_path = await file.download_to_drive()

    try:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img)
        print("OCR Text:", text)  # For debugging in terminal

        # Extract first large number (could improve this with better pattern)
        amounts = re.findall(r"[\d,]+\.\d{2}", text)
        if amounts:
            amount_text = amounts[0].replace(",", "")
            return int(float(amount_text))
    except Exception as e:
        print("OCR Error:", e)

    return 0  # default if nothing found

async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_USER_ID:
        await update.message.reply_text("❌ Only admin can deposit funds")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /deposit <amount> <user_id>")
        return
    try:
        amount = int(context.args[0])
        target_id = int(context.args[1])
        new_balance = update_balance(target_id, amount)
        await update.message.reply_text(f"✅ Deposited {amount} birr to {target_id}. New balance: {new_balance}")
    except:
        await update.message.reply_text("❌ Invalid input.")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("deposit", deposit))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo_message))
    app.add_handler(CallbackQueryHandler(handle_buttons, pattern="^(start|balance|deposit|pay_telebirr|pay_cbe|cashout|withdraw_start|referral|top_miners|back_to_main)$"))
    app.add_handler(CallbackQueryHandler(handle_admin_approval, pattern="^(approve|decline)_"))
    app.add_handler(CallbackQueryHandler(handle_dig, pattern="^dig_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    print("✅ Bot Running")
    app.run_polling()

if __name__ == '__main__':
    main()
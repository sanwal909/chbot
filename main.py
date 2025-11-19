import asyncio
import os
import re
import json
import sys
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import SessionPasswordNeeded

# Environment variables
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH'])
BOT_TOKEN = os.environ['BOT_TOKEN']
PHONE_NUMBER = os.environ['PHONE_NUMBER']
TARGET_GROUP = os.environ['TARGET_GROUP']
ADMIN_USER_ID = int(os.environ['ADMIN_USER_ID'])  # Your user ID

SOURCE_CHANNELS = [
    int(os.environ['CHANNEL_1']),
    int(os.environ['CHANNEL_2'])
]

WAIT_FOR_REPLY = int(os.environ.get('WAIT_FOR_REPLY', '15'))
NEXT_POST_DELAY = int(os.environ.get('NEXT_POST_DELAY', '10'))

PROCESSED_FILE = 'processed_messages.json'
posted_count = 0
pinned_count = 0

# Login state management
class LoginManager:
    def __init__(self):
        self.phone_code = None
        self.password = None
        self.phone_code_event = asyncio.Event()
        self.password_event = asyncio.Event()
        self.user_client = None
        
    async def wait_for_phone_code(self):
        """Wait for phone code from admin via bot"""
        print("⏳ Waiting for phone code from admin...")
        await self.phone_code_event.wait()
        return self.phone_code
    
    async def wait_for_password(self):
        """Wait for password from admin via bot"""
        print("⏳ Waiting for 2FA password from admin...")
        await self.password_event.wait()
        return self.password

login_manager = LoginManager()

# Bot client for receiving login codes - ONLY LISTENS TO ADMIN
bot = Client("login_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot.on_message(filters.user(ADMIN_USER_ID) & filters.private & filters.text)
async def handle_admin_login_codes(client, message):
    """Receive login codes and passwords ONLY from admin"""
    text = message.text.strip()
    
    print(f"📨 Received from ADMIN {ADMIN_USER_ID}: {text}")
    
    # Welcome message
    if text in ['/start', '/help', 'start', 'help']:
        await message.reply(
            "🤖 **Admin Login Assistant**\n\n"
            "I'll help you login to your Telegram account.\n\n"
            "🔢 **Please send:**\n"
            "• 5-digit confirmation code (from Telegram)\n"
            "• Or your 2FA password\n\n"
            "📱 You'll receive a code on Telegram app shortly."
        )
        return
    
    # Check if it's a phone code (5 digits)
    if text.isdigit() and len(text) == 5:
        login_manager.phone_code = text
        await message.reply("✅ **Code received!**\n\nLogging you in...")
        login_manager.phone_code_event.set()
    
    # Check if it's password
    elif len(text) >= 4 and not text.isdigit():
        login_manager.password = text
        await message.reply("✅ **Password received!**\n\nCompleting login...")
        login_manager.password_event.set()
    
    else:
        await message.reply(
            "❌ **Invalid input**\n\n"
            "Please send:\n"
            "• 5-digit confirmation code\n"
            "• Or your 2FA password\n\n"
            "You should receive the code on Telegram app."
        )

# Ignore messages from other users
@bot.on_message(filters.private & ~filters.user(ADMIN_USER_ID))
async def handle_other_users(client, message):
    await message.reply("❌ **Access Denied**\n\nThis bot is for admin use only.")

async def perform_user_login():
    """Perform user login with bot assistance"""
    print("🚀 Starting user login process...")
    
    # Start bot to receive codes
    await bot.start()
    bot_me = await bot.get_me()
    print(f"🤖 Bot started: @{bot_me.username}")
    
    # Send welcome message to admin
    try:
        await bot.send_message(
            chat_id=ADMIN_USER_ID,
            text=(
                f"🔐 **Telegram Login Started**\n\n"
                f"📱 Phone: `{PHONE_NUMBER}`\n"
                f"🤖 Assistant: @{bot_me.username}\n\n"
                f"Please wait for confirmation code..."
            )
        )
    except Exception as e:
        print(f"❌ Could not send message to admin: {e}")
    
    # Create user client
    user_client = Client("user_session", api_id=API_ID, api_hash=API_HASH)
    
    try:
        # Step 1: Connect and send code request
        await user_client.connect()
        print("📲 Requesting login code from Telegram...")
        sent_code = await user_client.send_code(PHONE_NUMBER)
        print("✅ Code request sent!")
        
        # Notify admin via bot
        try:
            await bot.send_message(
                chat_id=ADMIN_USER_ID,
                text="📱 **Check Telegram!**\n\nYou should receive a 5-digit code. Send it to me here."
            )
        except:
            pass
        
        # Step 2: Wait for phone code via bot (from admin only)
        phone_code = await login_manager.wait_for_phone_code()
        if not phone_code:
            print("❌ No phone code received")
            return None
        
        print(f"🔢 Code received from admin: {phone_code}")
        
        # Step 3: Sign in with code
        try:
            await user_client.sign_in(
                phone_number=PHONE_NUMBER,
                phone_code_hash=sent_code.phone_code_hash,
                phone_code=phone_code
            )
            print("✅ Login successful!")
            
            # Notify success to admin
            try:
                await bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text="🎉 **Login Successful!**\n\nStarting monitor..."
                )
            except:
                pass
            
        except SessionPasswordNeeded:
            print("🔐 2FA password required")
            
            # Request password from admin via bot
            try:
                await bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text="🔐 **2FA Password Required**\n\nPlease send your 2FA password:"
                )
            except:
                pass
            
            # Step 4: Wait for password via bot (from admin only)
            password = await login_manager.wait_for_password()
            if not password:
                print("❌ No password received")
                return None
            
            # Step 5: Sign in with password
            await user_client.check_password(password)
            print("✅ 2FA authentication successful!")
            
            # Notify success to admin
            try:
                await bot.send_message(
                    chat_id=ADMIN_USER_ID,
                    text="🎉 **2FA Verified!**\n\nStarting monitor..."
                )
            except:
                pass
        
        # Return the logged-in client
        login_manager.user_client = user_client
        return user_client
        
    except Exception as e:
        print(f"❌ Login failed: {e}")
        
        # Notify error to admin
        try:
            await bot.send_message(
                chat_id=ADMIN_USER_ID,
                text=f"❌ **Login Failed**\n\nError: `{str(e)}`"
            )
        except:
            pass
        
        await user_client.disconnect()
        return None

class FileStorage:
    @staticmethod
    def load_json(filename):
        try:
            if os.path.exists(filename):
                with open(filename, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return {}
        except:
            return {}
    
    @staticmethod
    def save_json(filename, data):
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            return True
        except:
            return False

def init_storage():
    if not os.path.exists(PROCESSED_FILE):
        FileStorage.save_json(PROCESSED_FILE, {})

def extract_cc_details(text):
    if not text:
        return None
    cc_pattern = r'\b(\d{16}\|\d{2}\|\d{2}\|\d{3})\b'
    match = re.search(cc_pattern, text)
    return match.group(1) if match else None

def is_message_processed(message_signature):
    processed = FileStorage.load_json(PROCESSED_FILE)
    return message_signature in processed

def mark_message_processed(message_signature, cc_details, status):
    processed = FileStorage.load_json(PROCESSED_FILE)
    processed[message_signature] = {
        'cc_details': cc_details,
        'status': status,
        'timestamp': datetime.now().isoformat(),
        'pinned': status == 'approved'
    }
    FileStorage.save_json(PROCESSED_FILE, processed)

def print_stats():
    print(f"📊 Posted: {posted_count} | Pinned: {pinned_count}")

async def pin_approved_message(client, message_id):
    global pinned_count
    try:
        await client.pin_chat_message(TARGET_GROUP, message_id)
        pinned_count += 1
        print("✅ Message pinned")
        print_stats()
        return True
    except Exception as e:
        print(f"❌ Pin error: {e}")
        return False

async def cleanup_group_messages(client):
    """Delete all messages except pinned ones"""
    try:
        deleted_count = 0
        print("🔄 Cleaning up group messages...")
        
        async for message in client.get_chat_history(TARGET_GROUP, limit=200):
            if not message.pinned:
                try:
                    await message.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.3)
                except Exception:
                    continue
        
        print(f"✅ Cleanup completed. Deleted {deleted_count} messages")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")

async def send_and_wait_for_reply(client, cc_details):
    global posted_count
    
    try:
        print(f"🔄 Sending CC: {cc_details}")
        
        # Send message to bot
        sent_message = await client.send_message(TARGET_GROUP, f".chk {cc_details}")
        posted_count += 1
        print_stats()
        
        # Wait for bot reply
        print(f"⏳ Waiting {WAIT_FOR_REPLY} seconds for reply...")
        await asyncio.sleep(WAIT_FOR_REPLY)
        
        # Check for replies
        async for message in client.get_chat_history(TARGET_GROUP, limit=50):
            if message.reply_to_message_id == sent_message.id:
                message_text = message.text or ""
                print(f"🤖 Bot reply: {message_text[:100]}...")
                
                # Check for APPROVED
                if any(approved in message_text for approved in ["Approved ✅", "Status: Approved", "APPROVED", "Approved", "Card added", "Response: Card added", "Status: Approved ✅", "✅ Approved", "APPROVED ✅"]):
                    print("🎯 APPROVED detected!")
                    await pin_approved_message(client, message.id)
                    return "approved"
                
                # Check for declined
                elif any(declined in message_text for declined in ["Declined", "DECLINED", "declined", "❌"]):
                    print("❌ DECLINED detected")
                    return "declined"
        
        print("⏰ No reply received")
        return "no_reply"
        
    except Exception as e:
        print(f"❌ Send error: {e}")
        return "error"

async def process_source_channel(client, channel_id):
    try:
        print(f"🔄 Processing channel: {channel_id}")
        message_count = 0
        
        async for message in client.get_chat_history(channel_id, limit=500):
            text = message.text or message.caption
            if not text:
                continue
            
            message_signature = f"{channel_id}_{message.id}"
            cc_details = extract_cc_details(text)
            
            if cc_details and not is_message_processed(message_signature):
                print(f"🎯 Found CC: {cc_details}")
                result = await send_and_wait_for_reply(client, cc_details)
                mark_message_processed(message_signature, cc_details, result)
                await asyncio.sleep(NEXT_POST_DELAY)
                message_count += 1
        
        print(f"✅ Channel {channel_id} processed. Found {message_count} messages")
        return True
        
    except Exception as e:
        print(f"❌ Channel error: {e}")
        return False

async def main():
    print("=" * 50)
    print("🚀 TELEGRAM MONITOR - ADMIN BOT LOGIN")
    print("=" * 50)
    print(f"📱 Phone: {PHONE_NUMBER}")
    print(f"🎯 Target: {TARGET_GROUP}")
    print(f"👤 Admin ID: {ADMIN_USER_ID}")
    print("=" * 50)
    
    init_storage()
    
    # Perform login with bot assistance (admin only)
    user_client = await perform_user_login()
    
    if not user_client:
        print("❌ Login failed. Exiting.")
        await bot.stop()
        return
    
    try:
        print("✅ Login successful! Starting monitor...")
        
        # Get user info
        me = await user_client.get_me()
        print(f"👤 User: {me.first_name} (@{me.username})")
        
        # Stop bot (no longer needed)
        await bot.stop()
        print("🤖 Bot stopped")
        
        print("📊 Posted: 0 | Pinned: 0")
        
        # Cleanup group
        await cleanup_group_messages(user_client)
        
        # Process existing messages
        for channel_id in SOURCE_CHANNELS:
            await process_source_channel(user_client, channel_id)
        
        print(f"\n✅ Ready | Posted: {posted_count} | Pinned: {pinned_count}")
        print("🔍 Monitoring for new messages...")
        
        # Message handler for new messages
        @user_client.on_message(filters.chat(SOURCE_CHANNELS))
        async def handle_new_message(client, message):
            text = message.text or message.caption
            if not text:
                return
            
            message_signature = f"{message.chat.id}_{message.id}"
            if is_message_processed(message_signature):
                return
            
            cc_details = extract_cc_details(text)
            if cc_details:
                print(f"🆕 New CC: {cc_details}")
                result = await send_and_wait_for_reply(client, cc_details)
                mark_message_processed(message_signature, cc_details, result)
                await asyncio.sleep(NEXT_POST_DELAY)
        
        # Keep running
        await user_client.run_until_disconnected()
        
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await user_client.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped | Posted: {posted_count} | Pinned: {pinned_count}")
    except Exception as e:
        print(f"💥 Fatal error: {e}")

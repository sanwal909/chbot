import asyncio
import os
import re
import json
import sys
import sqlite3
import logging
from datetime import datetime
from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, PhoneCodeExpired

# Environment variables
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
TARGET_GROUP = os.environ['TARGET_GROUP']

SOURCE_CHANNELS = [
    int(os.environ['CHANNEL_1']),
    int(os.environ['CHANNEL_2'])
]

WAIT_FOR_REPLY = int(os.environ.get('WAIT_FOR_REPLY', '15'))
NEXT_POST_DELAY = int(os.environ.get('NEXT_POST_DELAY', '10'))

PROCESSED_FILE = 'processed_messages.json'
posted_count = 0
pinned_count = 0

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SessionBot:
    def __init__(self):
        self.user_states = {}
        self.setup_database()
        
    def setup_database(self):
        """Setup SQLite database for storing user sessions"""
        self.conn = sqlite3.connect('user_sessions.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                phone TEXT,
                session_file TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self.conn.commit()
        logger.info("Database setup completed")
    
    async def start_bot(self):
        """Start the Telegram bot"""
        try:
            logger.info("Creating Telegram client...")
            
            # Bot client with bot_token in constructor
            self.client = Client(
                'session_bot', 
                api_id=API_ID, 
                api_hash=API_HASH,
                bot_token=BOT_TOKEN
            )
            
            # Event handlers
            @self.client.on_message(filters.command("start") & filters.private)
            async def start_handler(client, message):
                welcome_msg = """
🤖 **Welcome to Session Generator Bot!**

To create a Telegram session, send your details in this format:

`API_ID API_HASH PHONE_NUMBER`

**Example:**
`123456 abc123def456 +919876543210`

🔒 *Your data is safe and stored only locally*
                """
                await message.reply(welcome_msg)
                logger.info(f"Start command from user {message.from_user.id}")
            
            @self.client.on_message(filters.command("help") & filters.private)
            async def help_handler(client, message):
                help_msg = """
📖 **How to use this bot:**

1. Go to https://my.telegram.org
2. Create an app and get API_ID & API_HASH
3. Send in format: `API_ID API_HASH PHONE_NUMBER`
4. Follow the verification steps

⚠️ **Note:** Use this only for personal testing
                """
                await message.reply(help_msg)
            
            @self.client.on_message(filters.command("monitor") & filters.private)
            async def monitor_handler(client, message):
                """Start monitoring after session creation"""
                user_id = message.from_user.id
                session_file = f"user_{user_id}.session"
                
                if os.path.exists(session_file):
                    await message.reply("✅ **Starting Monitor...**")
                    await self.start_monitoring(user_id, session_file)
                else:
                    await message.reply("❌ **No session found!**\nCreate session first with: `API_ID API_HASH PHONE_NUMBER`")
            
            @self.client.on_message(filters.private & filters.text)
            async def message_handler(client, message):
                try:
                    user_id = message.from_user.id
                    message_text = message.text.strip()
                    
                    # Check if user is in verification process
                    if user_id in self.user_states:
                        await self.handle_verification(client, message, user_id, message_text)
                        return
                    
                    # Check if message contains credentials (ignore commands)
                    if not message_text.startswith('/'):
                        parts = message_text.split()
                        if len(parts) == 3:
                            await self.handle_credentials(client, message, parts, user_id)
                        else:
                            await message.reply("❌ **Invalid format!**\n\nUse: `API_ID API_HASH PHONE_NUMBER`")
                            
                except Exception as e:
                    logger.error(f"Message handler error: {e}")
                    await message.reply("❌ An error occurred. Please try again.")
            
            logger.info("Starting bot...")
            
            # Start the client
            await self.client.start()
            
            me = await self.client.get_me()
            logger.info(f"Bot started successfully: @{me.username}")
            logger.info(f"Bot @{me.username} is now running and ready to receive commands")
            
            # Keep bot running
            await idle()
            
        except Exception as e:
            logger.error(f"Failed to start bot: {e}")
        finally:
            # Cleanup
            if hasattr(self, 'client'):
                await self.client.stop()
    
    async def handle_credentials(self, client, message, parts, user_id):
        """Handle user credentials and start session creation"""
        try:
            api_id, api_hash, phone = parts
            
            # Validate API_ID
            if not api_id.isdigit():
                await message.reply("❌ API_ID must be a number!")
                return
            
            await message.reply("⏳ **Processing your request...**")
            logger.info(f"Creating session for user {user_id}")
            
            # Store user state for verification
            self.user_states[user_id] = {
                'api_id': int(api_id),
                'api_hash': api_hash,
                'phone': phone,
                'step': 'creating_client'
            }
            
            # Start session creation process
            await self.create_user_session(user_id)
                
        except Exception as e:
            logger.error(f"Credentials handling error: {e}")
            await message.reply("❌ An error occurred while processing your request.")
    
    async def handle_verification(self, client, message, user_id, message_text):
        """Handle verification code and password input"""
        try:
            user_state = self.user_states[user_id]
            
            if user_state['step'] == 'waiting_code':
                user_state['code'] = message_text
                user_state['step'] = 'processing_code'
                await self.process_verification(user_id)
                
            elif user_state['step'] == 'waiting_password':
                user_state['password'] = message_text
                user_state['step'] = 'processing_password'
                await self.process_password(user_id)
                
        except Exception as e:
            logger.error(f"Verification handling error: {e}")
            await message.reply("❌ Verification failed. Please start over with /start")
            if user_id in self.user_states:
                del self.user_states[user_id]
    
    async def create_user_session(self, user_id):
        """Create Telegram session for user"""
        try:
            user_state = self.user_states[user_id]
            api_id = user_state['api_id']
            api_hash = user_state['api_hash']
            phone = user_state['phone']
            
            session_name = f"user_{user_id}"
            
            # Create client for user session
            user_client = Client(session_name, api_id=api_id, api_hash=api_hash)
            await user_client.connect()
            
            # ✅ FIXED: Pyrogram v2.0 compatible - Directly try to get_me() se check karo
            try:
                # Try to get user info - agar authorized hai toh yeh kaam karega
                me = await user_client.get_me()
                # Agar yahan tak pahunche matlab authorized hai
                logger.info(f"User already authorized: {me.first_name}")
                await self.save_session(user_id, phone, session_name, user_client)
                return
                
            except Exception:
                # Agar get_me() fail hua matlab sign in karna hoga
                logger.info("User not authorized, sending verification code...")
            
            # Send verification code
            sent_code = await user_client.send_code(phone)
            user_state['phone_code_hash'] = sent_code.phone_code_hash
            user_state['client'] = user_client
            user_state['step'] = 'waiting_code'
            
            await self.client.send_message(
                user_id, 
                "📲 **Verification code sent!**\n\nPlease enter the code you received:"
            )
            logger.info(f"Waiting for code from user {user_id}")
            
        except Exception as e:
            logger.error(f"Session creation error: {e}")
            await self.client.send_message(user_id, f"❌ **Error:** `{str(e)}`")
            if user_id in self.user_states:
                del self.user_states[user_id]
    
    async def process_verification(self, user_id):
        """Process verification code"""
        try:
            user_state = self.user_states[user_id]
            user_client = user_state['client']
            phone = user_state['phone']
            code = user_state['code']
            phone_code_hash = user_state['phone_code_hash']
            
            try:
                # Sign in with code
                await user_client.sign_in(
                    phone_number=phone,
                    phone_code_hash=phone_code_hash,
                    phone_code=code
                )
                
                session_name = f"user_{user_id}"
                await self.save_session(user_id, phone, session_name, user_client)
                
            except SessionPasswordNeeded:
                # Ask for 2FA password
                await self.client.send_message(
                    user_id,
                    "🔐 **Two-Factor Authentication Enabled**\n\nPlease enter your 2FA password:"
                )
                user_state['step'] = 'waiting_password'
            except (PhoneCodeInvalid, PhoneCodeExpired):
                await self.client.send_message(
                    user_id,
                    "❌ **Invalid or expired code!**\nPlease start over with /start"
                )
                if user_id in self.user_states:
                    if 'client' in user_state:
                        await user_state['client'].disconnect()
                    del self.user_states[user_id]
                
        except Exception as e:
            logger.error(f"Verification processing error: {e}")
            await self.client.send_message(user_id, f"❌ **Verification failed:** `{str(e)}`")
            if user_id in self.user_states:
                if 'client' in user_state:
                    await user_state['client'].disconnect()
                del self.user_states[user_id]
    
    async def process_password(self, user_id):
        """Process 2FA password"""
        try:
            user_state = self.user_states[user_id]
            password = user_state['password']
            user_client = user_state['client']
            
            await user_client.check_password(password)
            
            session_name = f"user_{user_id}"
            phone = user_state['phone']
            await self.save_session(user_id, phone, session_name, user_client)
            
        except Exception as e:
            logger.error(f"Password processing error: {e}")
            await self.client.send_message(user_id, f"❌ **Login failed:** `{str(e)}`")
            if user_id in self.user_states:
                if 'client' in user_state:
                    await user_state['client'].disconnect()
                del self.user_states[user_id]
    
    async def save_session(self, user_id, phone, session_name, user_client):
        """Save session and notify user"""
        try:
            await user_client.disconnect()
            
            # Save to database
            self.cursor.execute(
                'INSERT OR REPLACE INTO users (user_id, phone, session_file) VALUES (?, ?, ?)',
                (user_id, phone, f"{session_name}.session")
            )
            self.conn.commit()
            
            # Send success message
            success_msg = f"""
✅ **Session Created Successfully!**

📱 Phone: `{phone}`
💾 Session File: `{session_name}.session`
🆔 Your ID: `{user_id}`

🔐 Session saved locally for future use.

📊 **Start monitoring with:** `/monitor`
            """
            await self.client.send_message(user_id, success_msg)
            logger.info(f"Session created for user {user_id}")
            
            # Cleanup user state
            if user_id in self.user_states:
                del self.user_states[user_id]
                
        except Exception as e:
            logger.error(f"Session save error: {e}")
            await self.client.send_message(user_id, f"❌ **Session save failed:** `{str(e)}`")
            try:
                await user_client.disconnect()
            except:
                pass

    # MONITORING FUNCTIONS
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

    def init_storage(self):
        if not os.path.exists(PROCESSED_FILE):
            self.FileStorage.save_json(PROCESSED_FILE, {})

    def extract_cc_details(self, text):
        if not text:
            return None
        cc_pattern = r'\b(\d{16}\|\d{2}\|\d{2}\|\d{3})\b'
        match = re.search(cc_pattern, text)
        return match.group(1) if match else None

    def is_message_processed(self, message_signature):
        processed = self.FileStorage.load_json(PROCESSED_FILE)
        return message_signature in processed

    def mark_message_processed(self, message_signature, cc_details, status):
        processed = self.FileStorage.load_json(PROCESSED_FILE)
        processed[message_signature] = {
            'cc_details': cc_details,
            'status': status,
            'timestamp': datetime.now().isoformat(),
            'pinned': status == 'approved'
        }
        self.FileStorage.save_json(PROCESSED_FILE, processed)

    def print_stats(self):
        print(f"📊 Posted: {posted_count} | Pinned: {pinned_count}")

    async def pin_approved_message(self, client, message_id):
        global pinned_count
        try:
            await client.pin_chat_message(TARGET_GROUP, message_id)
            pinned_count += 1
            print("✅ Message pinned")
            self.print_stats()
            return True
        except Exception as e:
            print(f"❌ Pin error: {e}")
            return False

    async def cleanup_group_messages(self, client):
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

    async def send_and_wait_for_reply(self, client, cc_details):
        global posted_count
        
        try:
            print(f"🔄 Sending CC: {cc_details}")
            
            sent_message = await client.send_message(TARGET_GROUP, f".chk {cc_details}")
            posted_count += 1
            self.print_stats()
            
            await asyncio.sleep(WAIT_FOR_REPLY)
            
            async for message in client.get_chat_history(TARGET_GROUP, limit=50):
                if message.reply_to_message_id == sent_message.id:
                    message_text = message.text or ""
                    print(f"🤖 Bot reply: {message_text[:100]}...")
                    
                    if any(approved in message_text for approved in ["Approved ✅", "Status: Approved", "APPROVED", "Approved", "Card added", "Response: Card added", "Status: Approved ✅", "✅ Approved", "APPROVED ✅"]):
                        print("🎯 APPROVED detected!")
                        await self.pin_approved_message(client, message.id)
                        return "approved"
                    
                    elif any(declined in message_text for declined in ["Declined", "DECLINED", "declined", "❌"]):
                        print("❌ DECLINED detected")
                        return "declined"
            
            return "no_reply"
            
        except Exception as e:
            print(f"❌ Send error: {e}")
            return "error"

    async def process_source_channel(self, client, channel_id):
        try:
            print(f"🔄 Processing channel: {channel_id}")
            message_count = 0
            
            async for message in client.get_chat_history(channel_id, limit=500):
                text = message.text or message.caption
                if not text:
                    continue
                
                message_signature = f"{channel_id}_{message.id}"
                cc_details = self.extract_cc_details(text)
                
                if cc_details and not self.is_message_processed(message_signature):
                    print(f"🎯 Found CC: {cc_details}")
                    result = await self.send_and_wait_for_reply(client, cc_details)
                    self.mark_message_processed(message_signature, cc_details, result)
                    await asyncio.sleep(NEXT_POST_DELAY)
                    message_count += 1
            
            print(f"✅ Channel {channel_id} processed. Found {message_count} messages")
            return True
            
        except Exception as e:
            print(f"❌ Channel error: {e}")
            return False

    async def start_monitoring(self, user_id, session_file):
        """Start monitoring channels after session creation"""
        try:
            logger.info(f"Starting monitoring for user {user_id}")
            
            # Create user client from session file
            user_client = Client(session_file, api_id=API_ID, api_hash=API_HASH)
            await user_client.start()
            
            me = await user_client.get_me()
            logger.info(f"Monitoring started for: {me.first_name}")
            
            self.init_storage()
            
            # Notify user
            await self.client.send_message(
                user_id,
                f"🔍 **Monitoring Started!**\n\n"
                f"👤 User: {me.first_name}\n"
                f"🎯 Target: {TARGET_GROUP}\n"
                f"📡 Channels: {len(SOURCE_CHANNELS)}\n\n"
                f"Monitoring channels for CC details..."
            )
            
            print("📊 Posted: 0 | Pinned: 0")
            
            # Cleanup
            await self.cleanup_group_messages(user_client)
            
            # Process channels
            for channel_id in SOURCE_CHANNELS:
                await self.process_source_channel(user_client, channel_id)
            
            print(f"\n✅ Ready | Posted: {posted_count} | Pinned: {pinned_count}")
            print("🔍 Monitoring for new messages...")
            
            # Message handler
            @user_client.on_message(filters.chat(SOURCE_CHANNELS))
            async def handle_message(client, message):
                text = message.text or message.caption
                if not text:
                    return
                
                signature = f"{message.chat.id}_{message.id}"
                if self.is_message_processed(signature):
                    return
                
                cc = self.extract_cc_details(text)
                if cc:
                    print(f"🆕 New CC: {cc}")
                    result = await self.send_and_wait_for_reply(client, cc)
                    self.mark_message_processed(signature, cc, result)
                    await asyncio.sleep(NEXT_POST_DELAY)
            
            # Keep monitoring running
            await idle()
            
        except Exception as e:
            logger.error(f"Monitoring error: {e}")
            await self.client.send_message(
                user_id, 
                f"❌ **Monitoring failed:** `{str(e)}`"
            )

async def main():
    try:
        bot = SessionBot()
        await bot.start_bot()
        
    except Exception as e:
        logger.error(f"Main function error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

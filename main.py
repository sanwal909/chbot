import asyncio
import os
import re
import json
import sys
import sqlite3
import logging
import time
from datetime import datetime
from typing import List, Union
from pyrogram.client import Client
from pyrogram import filters
from pyrogram.types import Message
from telethon import TelegramClient, events

# Environment variables for BOT ONLY
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']

# Default monitoring settings (can be customized per user later)
DEFAULT_WAIT_FOR_REPLY = int(os.environ.get('WAIT_FOR_REPLY', '5'))
DEFAULT_NEXT_POST_DELAY = int(os.environ.get('NEXT_POST_DELAY', '2'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class SessionBot:
    def __init__(self):
        self.user_states = {}
        self.monitoring_clients = {}
        self.setup_database()

    def setup_database(self):
        """Setup SQLite database for storing user sessions and processed messages"""
        self.conn = sqlite3.connect('bot_database.db', check_same_thread=False)
        self.cursor = self.conn.cursor()
        
        # Users table - stores user credentials and session info
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                api_id INTEGER,
                api_hash TEXT,
                phone TEXT,
                session_file TEXT,
                target_group TEXT,
                source_channels TEXT,
                checker_bot TEXT,
                wait_for_reply INTEGER DEFAULT 5,
                next_post_delay INTEGER DEFAULT 2,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Processed messages table - replaces JSON files
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                message_signature TEXT UNIQUE,
                cc_details TEXT,
                status TEXT,
                pinned INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        # Stats table
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id INTEGER PRIMARY KEY,
                posted_count INTEGER DEFAULT 0,
                pinned_count INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        ''')
        
        self.conn.commit()
        logger.info("Database setup completed")

    async def start_bot(self):
        """Start the Telegram bot"""
        try:
            logger.info("Creating Telegram bot client...")
            self.client = Client('session_bot', api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

            # Event handlers
            @self.client.on_message(filters.command("start") & filters.private)
            async def start_handler(client, message):
                welcome_msg = """
🤖 **Welcome to Multi-Account CC Monitor Bot!**

**Step 1: Create Session**
Send your details in this format:
`API_ID API_HASH PHONE_NUMBER`

**Example:**
`123456 abc123def456 +919876543210`

**Step 2: Configure Monitoring**
After session creation, use:
`/config TARGET_GROUP SOURCE_CHANNEL1 SOURCE_CHANNEL2 CHECKER_BOT`

**Example:**
`/config @mygroup -1001234567 -1009876543 @CheckerBot`

**Step 3: Start Monitoring**
`/monitor`

🔒 *All data is stored securely in database*
                """
                await message.reply(welcome_msg)
                logger.info(f"Start command from user {message.from_user.id}")

            @self.client.on_message(filters.command("help") & filters.private)
            async def help_handler(client, message):
                help_msg = """
📖 **How to use this bot:**

1. Go to https://my.telegram.org
2. Create an app and get API_ID & API_HASH
3. Send: `API_ID API_HASH PHONE_NUMBER`
4. Follow verification steps
5. Configure with `/config`
6. Start monitoring with `/monitor`

**Commands:**
/start - Start bot
/help - Show help
/config - Configure monitoring
/monitor - Start monitoring
/stop - Stop monitoring
/stats - View stats

⚠️ **Note:** Use this only for personal testing
                """
                await message.reply(help_msg)

            @self.client.on_message(filters.command("config") & filters.private)
            async def config_handler(client, message):
                """Configure monitoring settings"""
                try:
                    user_id = message.from_user.id
                    parts = message.text.split()[1:]  # Skip /config
                    
                    if len(parts) < 4:
                        await message.reply("❌ **Invalid format!**\n\nUse:\n`/config TARGET_GROUP SOURCE_CH1 SOURCE_CH2 CHECKER_BOT`\n\nExample:\n`/config @mygroup -1001234567 -1009876543 @CheckerBot`")
                        return
                    
                    target_group = parts[0]
                    source_ch1 = parts[1]
                    source_ch2 = parts[2]
                    checker_bot = parts[3]
                    
                    source_channels = f"{source_ch1},{source_ch2}"
                    
                    # Update or insert config
                    self.cursor.execute('''
                        UPDATE users 
                        SET target_group = ?, source_channels = ?, checker_bot = ?
                        WHERE user_id = ?
                    ''', (target_group, source_channels, checker_bot, user_id))
                    self.conn.commit()
                    
                    await message.reply(f"""
✅ **Configuration Saved!**

🎯 Target Group: `{target_group}`
📡 Source Channels: `{source_ch1}`, `{source_ch2}`
🤖 Checker Bot: `{checker_bot}`

Now use `/monitor` to start!
                    """)
                    
                except Exception as e:
                    logger.error(f"Config error: {e}")
                    await message.reply(f"❌ **Config error:** `{str(e)}`")

            @self.client.on_message(filters.command("monitor") & filters.private)
            async def monitor_handler(client, message):
                """Start monitoring after session creation"""
                user_id = message.from_user.id
                
                # Check if user exists and has config
                self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
                user_data = self.cursor.fetchone()
                
                if not user_data:
                    await message.reply("❌ **No session found!**\n\nCreate session first with:\n`API_ID API_HASH PHONE_NUMBER`")
                    return
                
                if not user_data[5] or not user_data[6]:  # target_group and source_channels
                    await message.reply("❌ **Configuration missing!**\n\nPlease configure with `/config` first")
                    return
                
                session_file = f"user_{user_id}"
                if not os.path.exists(session_file + '.session'):
                    await message.reply("❌ **Session file not found!**\n\nPlease recreate your session")
                    return
                
                await message.reply("✅ **Starting Monitor...**")
                await self.start_monitoring(user_id)

            @self.client.on_message(filters.command("stop") & filters.private)
            async def stop_handler(client, message):
                """Stop monitoring"""
                user_id = message.from_user.id
                if user_id in self.monitoring_clients:
                    await message.reply("🛑 **Stopping monitor...**")
                    # Stop will be handled by the monitoring loop
                else:
                    await message.reply("❌ **No active monitoring found**")

            @self.client.on_message(filters.command("stats") & filters.private)
            async def stats_handler(client, message):
                """Show user stats"""
                user_id = message.from_user.id
                self.cursor.execute('SELECT * FROM user_stats WHERE user_id = ?', (user_id,))
                stats = self.cursor.fetchone()
                
                if stats:
                    await message.reply(f"""
📊 **Your Stats:**

📤 Posted: {stats[1]}
📌 Pinned: {stats[2]}
                    """)
                else:
                    await message.reply("📊 **No stats yet!**\n\nStart monitoring to collect stats")

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
            await self.client.start()

            me = await self.client.get_me()
            logger.info(f"Bot started successfully: @{me.username}")
            logger.info("Bot is now running and ready to accept commands!")

            # Keep bot running
            await asyncio.Event().wait()

        except Exception as e:
            logger.error(f"Failed to start bot: {e}")

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
        """Create Telegram session for user using Telethon"""
        try:
            user_state = self.user_states[user_id]
            api_id = user_state['api_id']
            api_hash = user_state['api_hash']
            phone = user_state['phone']

            session_name = f"user_{user_id}"

            # Create Telethon client for user session
            user_client = TelegramClient(session_name, api_id, api_hash)
            await user_client.connect()

            # Send verification code
            await user_client.send_code_request(phone)
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

            try:
                # Sign in with code (Telethon)
                await user_client.sign_in(phone, code)

                session_name = f"user_{user_id}"
                await self.save_session(user_id, phone, session_name, user_client)

            except Exception as two_fa_error:
                # Check if it's 2FA error
                if "password" in str(two_fa_error).lower() or "2fa" in str(two_fa_error).lower():
                    # Ask for 2FA password
                    await self.client.send_message(
                        user_id,
                        "🔐 **Two-Factor Authentication Enabled**\n\nPlease enter your 2FA password:"
                    )
                    user_state['step'] = 'waiting_password'
                else:
                    raise two_fa_error

        except Exception as e:
            logger.error(f"Verification processing error: {e}")
            await self.client.send_message(user_id, f"❌ **Verification failed:** `{str(e)}`")
            if user_id in self.user_states:
                user_state = self.user_states[user_id]
                if 'client' in user_state:
                    await user_state['client'].disconnect()
                del self.user_states[user_id]

    async def process_password(self, user_id):
        """Process 2FA password"""
        try:
            user_state = self.user_states[user_id]
            password = user_state['password']
            user_client = user_state['client']
            phone = user_state['phone']

            # Sign in with password (Telethon)
            await user_client.sign_in(phone, password=password)

            session_name = f"user_{user_id}"
            await self.save_session(user_id, phone, session_name, user_client)

        except Exception as e:
            logger.error(f"Password processing error: {e}")
            await self.client.send_message(user_id, f"❌ **Login failed:** `{str(e)}`")
            if user_id in self.user_states:
                user_state = self.user_states[user_id]
                if 'client' in user_state:
                    await user_state['client'].disconnect()
                del self.user_states[user_id]

    async def save_session(self, user_id, phone, session_name, user_client):
        """Save session and notify user"""
        try:
            user_state = self.user_states[user_id]
            api_id = user_state['api_id']
            api_hash = user_state['api_hash']
            
            await user_client.disconnect()

            # Save to database
            self.cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, api_id, api_hash, phone, session_file, wait_for_reply, next_post_delay) 
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, api_id, api_hash, phone, f"{session_name}.session", DEFAULT_WAIT_FOR_REPLY, DEFAULT_NEXT_POST_DELAY))
            
            # Initialize stats
            self.cursor.execute('''
                INSERT OR IGNORE INTO user_stats (user_id, posted_count, pinned_count)
                VALUES (?, 0, 0)
            ''', (user_id,))
            
            self.conn.commit()

            # Send success message
            success_msg = f"""
✅ **Session Created Successfully!**

📱 Phone: `{phone}`
💾 Session File: `{session_name}.session`
🆔 Your ID: `{user_id}`

🔐 Session saved securely in database.

**Next Steps:**
1. Configure monitoring with `/config`
2. Start monitoring with `/monitor`
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

    # MONITORING FUNCTIONS (Using Telethon from main2.py)
    
    def extract_cc_details(self, text):
        """Extract credit card details from text"""
        if not text:
            return None
        cc_pattern = r'\b(\d{16}\|\d{2}\|\d{2}\|\d{3})\b'
        match = re.search(cc_pattern, text)
        return match.group(1) if match else None

    def is_message_processed(self, user_id, message_signature):
        """Check if message was already processed - uses database"""
        self.cursor.execute('''
            SELECT id FROM processed_messages 
            WHERE user_id = ? AND message_signature = ?
        ''', (user_id, message_signature))
        return self.cursor.fetchone() is not None

    def mark_message_processed(self, user_id, message_signature, cc_details, status):
        """Mark message as processed - uses database"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO processed_messages 
                (user_id, message_signature, cc_details, status, pinned, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (user_id, message_signature, cc_details, status, 1 if status == 'approved' else 0, datetime.now().isoformat()))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error marking message: {e}")

    def update_stats(self, user_id, posted=0, pinned=0):
        """Update user stats"""
        try:
            self.cursor.execute('''
                UPDATE user_stats 
                SET posted_count = posted_count + ?, pinned_count = pinned_count + ?
                WHERE user_id = ?
            ''', (posted, pinned, user_id))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error updating stats: {e}")

    async def pin_approved_message(self, telethon_client, target_group, message):
        """Pin approved message"""
        try:
            await telethon_client.pin_message(target_group, message)
            return True
        except Exception as e:
            logger.error(f"Pin failed: {e}")
            return False

    async def delete_declined_message(self, message):
        """Delete declined message"""
        try:
            await message.delete()
            return True
        except Exception:
            return False

    async def cleanup_group_messages(self, telethon_client, target_group):
        """Delete all unpinned messages from target group"""
        try:
            deleted_count = 0
            async for message in telethon_client.iter_messages(target_group, limit=100):
                if message.pinned or (message.text and message.text.startswith('/chk')):
                    continue
                try:
                    await message.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.5)
                except Exception:
                    continue
            logger.info(f"Cleaned {deleted_count} messages")
            return True
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            return False

    async def send_and_wait_for_reply(self, user_id, telethon_client, target_group, cc_details, wait_time):
        """Send CC to checker bot and wait for response"""
        try:
            # Send message to bot
            sent_message = await telethon_client.send_message(target_group, f"/chk {cc_details}")
            self.update_stats(user_id, posted=1, pinned=0)
            
            logger.info(f"[User {user_id}] Sent: {cc_details}")

            # Wait for bot reply
            await asyncio.sleep(wait_time)

            # Check for replies
            async for message in telethon_client.iter_messages(target_group, limit=50):
                if message.reply_to and message.reply_to.reply_to_msg_id == sent_message.id:
                    message_text = message.text or ""
                    logger.info(f"[User {user_id}] Bot replied: {message_text[:100]}")

                    # APPROVED PATTERNS
                    approved_patterns = [
                        "approved", "Approved", "APPROVED", "✅", "success", "Success",
                        "Card added", "Response: Card added", "Status:Approved✅", 
                        "✅ Approved", "APPROVED✅"
                    ]

                    # DECLINED PATTERNS  
                    declined_patterns = [
                        "declined", "Declined", "DECLINED", "❌", "failed", "Failed",
                        "dead", "Dead", "DEAD", "invalid", "Invalid", "error", "Error",
                        "Declined ❌"
                    ]

                    # Check for approved
                    if any(pattern.lower() in message_text.lower() for pattern in approved_patterns):
                        logger.info(f"[User {user_id}] APPROVED! Pinning...")
                        success = await self.pin_approved_message(telethon_client, target_group, message)
                        if success:
                            self.update_stats(user_id, posted=0, pinned=1)
                            return "approved"
                        return "approved_but_pin_failed"

                    # Check for declined
                    elif any(pattern.lower() in message_text.lower() for pattern in declined_patterns):
                        logger.info(f"[User {user_id}] DECLINED! Deleting...")
                        await self.delete_declined_message(message)
                        return "declined"

            logger.info(f"[User {user_id}] No valid reply")
            return "no_reply"

        except Exception as e:
            logger.error(f"[User {user_id}] Send error: {e}")
            return "error"

    async def process_source_channel(self, user_id, telethon_client, target_group, channel_id, wait_time, delay_time):
        """Process existing messages in source channel"""
        try:
            message_count = 0
            logger.info(f"[User {user_id}] Processing channel: {channel_id}")

            async for message in telethon_client.iter_messages(channel_id, limit=200):
                text = message.text
                if not text:
                    continue

                message_signature = f"{channel_id}_{message.id}"
                cc_details = self.extract_cc_details(text)

                if cc_details and not self.is_message_processed(user_id, message_signature):
                    logger.info(f"[User {user_id}] Found CC: {cc_details}")
                    result = await self.send_and_wait_for_reply(user_id, telethon_client, target_group, cc_details, wait_time)
                    self.mark_message_processed(user_id, message_signature, cc_details, result)
                    await asyncio.sleep(delay_time)
                    message_count += 1

            logger.info(f"[User {user_id}] Channel processed: {message_count} messages")
            return True

        except Exception as e:
            logger.error(f"[User {user_id}] Channel error: {e}")
            return False

    async def start_monitoring(self, user_id):
        """Start monitoring channels using Telethon after session creation"""
        try:
            logger.info(f"Starting monitoring for user {user_id}")
            
            # Get user data from database
            self.cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
            user_data = self.cursor.fetchone()
            
            if not user_data:
                await self.client.send_message(user_id, "❌ **User data not found!**")
                return
            
            api_id = user_data[1]
            api_hash = user_data[2]
            session_file = f"user_{user_id}"
            target_group = user_data[5]
            source_channels_str = user_data[6]
            checker_bot = user_data[7]
            wait_for_reply = user_data[8]
            next_post_delay = user_data[9]
            
            if not source_channels_str:
                await self.client.send_message(user_id, "❌ **Configure monitoring first with /config**")
                return
            
            source_channels = [int(ch.strip()) if ch.strip().lstrip('-').isdigit() else ch.strip() for ch in source_channels_str.split(',')]

            # Create Telethon client
            telethon_client = TelegramClient(session_file, api_id, api_hash)
            await telethon_client.start()

            me = await telethon_client.get_me()
            logger.info(f"Monitoring started for: {me.first_name}")

            # Store client
            self.monitoring_clients[user_id] = telethon_client

            # Notify user
            await self.client.send_message(
                user_id,
                f"🔍 **Monitoring Started!**\n\n"
                f"👤 User: {me.first_name}\n"
                f"🎯 Target: {target_group}\n"
                f"📡 Channels: {len(source_channels)}\n"
                f"🤖 Checker: {checker_bot}\n\n"
                f"Monitoring channels for CC details..."
            )

            # Initial cleanup
            logger.info(f"[User {user_id}] Initial cleanup...")
            await self.cleanup_group_messages(telethon_client, target_group)

            # Message handler for new messages
            @telethon_client.on(events.NewMessage)
            async def handler(event):
                try:
                    message = event.message
                    chat_id = message.chat.id if hasattr(message.chat, 'id') else message.chat_id

                    # Only process source channels
                    if chat_id not in source_channels:
                        return

                    text = message.text
                    if not text:
                        return

                    message_signature = f"{chat_id}_{message.id}"
                    if self.is_message_processed(user_id, message_signature):
                        return

                    cc_details = self.extract_cc_details(text)
                    if cc_details:
                        logger.info(f"[User {user_id}] New CC found: {cc_details}")
                        result = await self.send_and_wait_for_reply(user_id, telethon_client, target_group, cc_details, wait_for_reply)
                        self.mark_message_processed(user_id, message_signature, cc_details, result)
                        await asyncio.sleep(next_post_delay)

                except Exception as e:
                    logger.error(f"[User {user_id}] Handler error: {e}")

            # Process existing messages
            for channel_id in source_channels:
                await self.process_source_channel(user_id, telethon_client, target_group, channel_id, wait_for_reply, next_post_delay)

            logger.info(f"[User {user_id}] Monitoring active")
            
            # Get current stats
            self.cursor.execute('SELECT * FROM user_stats WHERE user_id = ?', (user_id,))
            stats = self.cursor.fetchone()
            if stats:
                await self.client.send_message(
                    user_id,
                    f"✅ **Monitoring Active!**\n\n📊 Posted: {stats[1]} | Pinned: {stats[2]}"
                )

            # Keep monitoring running
            await asyncio.Event().wait()

        except Exception as e:
            logger.error(f"Monitoring error for user {user_id}: {e}")
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

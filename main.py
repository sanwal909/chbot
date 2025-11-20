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

# Persistent data directory for Railway deployment
# Railway's filesystem is ephemeral, so we use /app/data with volume mount
# For local development, use current directory
DATA_DIR = os.environ.get('DATA_DIR', '/app/data')
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)
    
# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
logger.info(f"Using data directory: {DATA_DIR}")

class SessionBot:
    def __init__(self):
        self.user_states = {}
        self.monitoring_clients = {}
        self.setup_database()

    def setup_database(self):
        """Setup SQLite database for storing user sessions and processed messages"""
        db_path = os.path.join(DATA_DIR, 'bot_database.db')
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.cursor = self.conn.cursor()
        logger.info(f"Database connected at: {db_path}")
        
        # Sessions table - supports multiple accounts per user
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS sessions (
                session_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_name TEXT UNIQUE,
                api_id INTEGER,
                api_hash TEXT,
                phone TEXT,
                session_file TEXT,
                target_group TEXT,
                source_channels TEXT,
                checker_bot TEXT,
                wait_for_reply INTEGER DEFAULT 5,
                next_post_delay INTEGER DEFAULT 2,
                is_active INTEGER DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Processed messages table - replaces JSON files
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS processed_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER,
                message_signature TEXT UNIQUE,
                cc_details TEXT,
                status TEXT,
                pinned INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        ''')
        
        # Stats table - per session stats
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS session_stats (
                session_id INTEGER PRIMARY KEY,
                posted_count INTEGER DEFAULT 0,
                pinned_count INTEGER DEFAULT 0,
                FOREIGN KEY (session_id) REFERENCES sessions(session_id)
            )
        ''')
        
        self.conn.commit()
        logger.info("Database setup completed")

    def get_active_session(self, user_id):
        """Get active session for a user"""
        self.cursor.execute('''
            SELECT session_id, session_name, api_id, api_hash, phone, session_file, 
                   target_group, source_channels, checker_bot, wait_for_reply, next_post_delay
            FROM sessions 
            WHERE user_id = ? AND is_active = 1
        ''', (user_id,))
        return self.cursor.fetchone()

    def get_session_by_name(self, user_id, session_name):
        """Get session by name for a user"""
        self.cursor.execute('''
            SELECT session_id, session_name, api_id, api_hash, phone, session_file,
                   target_group, source_channels, checker_bot, wait_for_reply, next_post_delay
            FROM sessions 
            WHERE user_id = ? AND session_name = ?
        ''', (user_id, session_name))
        return self.cursor.fetchone()
    
    def get_session_path(self, session_file):
        """Get full session path for Telethon - Telethon adds .session automatically"""
        return os.path.join(DATA_DIR, session_file)

    async def start_bot(self):
        """Start the Telegram bot"""
        try:
            logger.info("Creating Telegram bot client...")
            bot_session_path = os.path.join(DATA_DIR, 'session_bot')
            self.client = Client(bot_session_path, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

            # Event handlers
            @self.client.on_message(filters.command("start") & filters.private)
            async def start_handler(client, message):
                welcome_msg = (
                    "🤖 Welcome to Multi-Account CC Monitor Bot!\n\n"
                    "✨ Now supports MULTIPLE ACCOUNTS! ✨\n\n"
                    "Step 1: Add Account (Session)\n"
                    "Send your details in this format:\n"
                    "SESSION_NAME API_ID API_HASH PHONE_NUMBER\n\n"
                    "Example:\n"
                    "account1 123456 abc123def456 +919876543210\n"
                    "account2 654321 xyz789abc123 +919999999999\n\n"
                    "Step 2: Manage Sessions\n"
                    "• /sessions - View all your accounts\n"
                    "• /switch SESSION_NAME - Switch active account\n"
                    "• /delete SESSION_NAME - Delete an account\n\n"
                    "Step 3: Configure Active Account\n"
                    "/config TARGET_GROUP SOURCE_CH1 SOURCE_CH2 CHECKER_BOT\n\n"
                    "Step 4: Start Monitoring\n"
                    "/monitor - Start monitoring with active account\n"
                    "/stop - Stop monitoring\n\n"
                    "🔒 All data is stored securely in database"
                )
                await message.reply(welcome_msg)
                logger.info(f"Start command from user {message.from_user.id}")

            @self.client.on_message(filters.command("help") & filters.private)
            async def help_handler(client, message):
                help_msg = (
                    "📖 How to use this bot:\n\n"
                    "1. Go to https://my.telegram.org\n"
                    "2. Create an app and get API_ID & API_HASH\n"
                    "3. Send: SESSION_NAME API_ID API_HASH PHONE_NUMBER\n"
                    "4. Follow verification steps\n"
                    "5. Use /sessions to view accounts\n"
                    "6. Use /switch SESSION_NAME to activate\n"
                    "7. Configure with /config\n"
                    "8. Start monitoring with /monitor\n\n"
                    "Commands:\n"
                    "/start - Start bot\n"
                    "/help - Show help\n"
                    "/sessions - View all accounts\n"
                    "/switch - Switch active account\n"
                    "/delete - Delete an account\n"
                    "/config - Configure active account\n"
                    "/monitor - Start monitoring\n"
                    "/stop - Stop monitoring\n"
                    "/stats - View stats\n\n"
                    "⚠️ Note: Use this only for personal testing"
                )
                await message.reply(help_msg)

            @self.client.on_message(filters.command("config") & filters.private)
            async def config_handler(client, message):
                """Configure monitoring settings for active session"""
                try:
                    user_id = message.from_user.id
                    parts = message.text.split()[1:]  # Skip /config
                    
                    if len(parts) < 4:
                        await message.reply("❌ Invalid format!\n\nUse:\n/config TARGET_GROUP SOURCE_CH1 SOURCE_CH2 CHECKER_BOT\n\nExample:\n/config @mygroup -1001234567 -1009876543 @CheckerBot")
                        return
                    
                    # Get active session
                    active_session = self.get_active_session(user_id)
                    if not active_session:
                        await message.reply("❌ No active session!\n\nUse /sessions to view accounts\nUse /switch SESSION_NAME to activate one")
                        return
                    
                    session_id = active_session[0]
                    session_name = active_session[1]
                    
                    target_group = parts[0]
                    source_ch1 = parts[1]
                    source_ch2 = parts[2]
                    checker_bot = parts[3]
                    
                    source_channels = f"{source_ch1},{source_ch2}"
                    
                    # Update config for active session
                    self.cursor.execute('''
                        UPDATE sessions 
                        SET target_group = ?, source_channels = ?, checker_bot = ?
                        WHERE session_id = ?
                    ''', (target_group, source_channels, checker_bot, session_id))
                    self.conn.commit()
                    
                    config_msg = (
                        f"✅ Configuration Saved for '{session_name}'!\n\n"
                        f"🎯 Target Group: {target_group}\n"
                        f"📡 Source Channels: {source_ch1}, {source_ch2}\n"
                        f"🤖 Checker Bot: {checker_bot}\n\n"
                        f"Now use /monitor to start!"
                    )
                    await message.reply(config_msg)
                    
                except Exception as e:
                    logger.error(f"Config error: {e}")
                    await message.reply(f"❌ Config error: {str(e)}")

            @self.client.on_message(filters.command("monitor") & filters.private)
            async def monitor_handler(client, message):
                """Start monitoring with active session"""
                user_id = message.from_user.id
                
                # Get active session
                active_session = self.get_active_session(user_id)
                if not active_session:
                    await message.reply("❌ No active session!\n\nUse /sessions to view accounts\nUse /switch SESSION_NAME to activate one")
                    return
                
                session_id, session_name, api_id, api_hash, phone, session_file, target_group, source_channels, checker_bot, wait_for_reply, next_post_delay = active_session
                
                if not target_group or not source_channels:
                    await message.reply("❌ Configuration missing!\n\nPlease configure with /config first")
                    return
                
                # Check if session file exists (Telethon adds .session extension automatically)
                session_path_with_ext = f"{self.get_session_path(session_file)}.session"
                if not os.path.exists(session_path_with_ext):
                    await message.reply("❌ Session file not found!\n\nPlease recreate your session")
                    return
                
                await message.reply(f"✅ Starting Monitor for '{session_name}'...")
                await self.start_monitoring(session_id)

            @self.client.on_message(filters.command("stop") & filters.private)
            async def stop_handler(client, message):
                """Stop monitoring for active session"""
                user_id = message.from_user.id
                
                # Get active session
                active_session = self.get_active_session(user_id)
                if not active_session:
                    await message.reply("❌ No active session!")
                    return
                
                session_id = active_session[0]
                session_name = active_session[1]
                
                if session_id in self.monitoring_clients:
                    client_to_stop = self.monitoring_clients[session_id]
                    try:
                        await client_to_stop.disconnect()
                        del self.monitoring_clients[session_id]
                        await message.reply(f"🛑 Monitoring stopped for '{session_name}'!")
                    except Exception as e:
                        await message.reply(f"❌ Error stopping monitor: {str(e)}")
                else:
                    await message.reply(f"❌ No active monitoring for '{session_name}'")

            @self.client.on_message(filters.command("stats") & filters.private)
            async def stats_handler(client, message):
                """Show stats for active session"""
                user_id = message.from_user.id
                
                # Get active session
                self.cursor.execute('SELECT session_id FROM sessions WHERE user_id = ? AND is_active = 1', (user_id,))
                active = self.cursor.fetchone()
                
                if not active:
                    await message.reply("❌ No active session!\n\nUse /sessions to view and /switch to activate")
                    return
                
                session_id = active[0]
                self.cursor.execute('SELECT * FROM session_stats WHERE session_id = ?', (session_id,))
                stats = self.cursor.fetchone()
                
                if stats:
                    stats_msg = (
                        f"📊 Your Stats:\n\n"
                        f"📤 Posted: {stats[1]}\n"
                        f"📌 Pinned: {stats[2]}"
                    )
                    await message.reply(stats_msg)
                else:
                    await message.reply("📊 No stats yet!\n\nStart monitoring to collect stats")

            @self.client.on_message(filters.command("sessions") & filters.private)
            async def sessions_handler(client, message):
                """List all sessions for user"""
                user_id = message.from_user.id
                
                self.cursor.execute('SELECT session_id, session_name, phone, is_active FROM sessions WHERE user_id = ?', (user_id,))
                sessions = self.cursor.fetchall()
                
                if not sessions:
                    await message.reply("❌ No sessions found!\n\nAdd a new account:\nSESSION_NAME API_ID API_HASH PHONE_NUMBER")
                    return
                
                msg = "📱 Your Accounts:\n\n"
                for session in sessions:
                    session_id, session_name, phone, is_active = session
                    status = "✅ Active" if is_active else "⚪ Inactive"
                    msg += f"{status} {session_name} - {phone}\n"
                
                msg += "\n💡 Use /switch SESSION_NAME to activate an account"
                await message.reply(msg)

            @self.client.on_message(filters.command("switch") & filters.private)
            async def switch_handler(client, message):
                """Switch active session"""
                user_id = message.from_user.id
                parts = message.text.split()
                
                if len(parts) < 2:
                    await message.reply("❌ Invalid format!\n\nUse: /switch SESSION_NAME")
                    return
                
                session_name = parts[1]
                
                # Check if session exists
                self.cursor.execute('SELECT session_id FROM sessions WHERE user_id = ? AND session_name = ?', (user_id, session_name))
                session = self.cursor.fetchone()
                
                if not session:
                    await message.reply(f"❌ Session '{session_name}' not found!\n\nUse /sessions to view all accounts")
                    return
                
                # Deactivate all sessions for this user
                self.cursor.execute('UPDATE sessions SET is_active = 0 WHERE user_id = ?', (user_id,))
                
                # Activate selected session
                self.cursor.execute('UPDATE sessions SET is_active = 1 WHERE user_id = ? AND session_name = ?', (user_id, session_name))
                self.conn.commit()
                
                await message.reply(f"✅ Active account switched to: {session_name}")

            @self.client.on_message(filters.command("delete") & filters.private)
            async def delete_handler(client, message):
                """Delete a session"""
                user_id = message.from_user.id
                parts = message.text.split()
                
                if len(parts) < 2:
                    await message.reply("❌ Invalid format!\n\nUse: /delete SESSION_NAME")
                    return
                
                session_name = parts[1]
                
                # Check if session exists
                self.cursor.execute('SELECT session_id, session_file FROM sessions WHERE user_id = ? AND session_name = ?', (user_id, session_name))
                session = self.cursor.fetchone()
                
                if not session:
                    await message.reply(f"❌ Session '{session_name}' not found!")
                    return
                
                session_id, session_file = session
                
                # Delete from database
                self.cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
                self.cursor.execute('DELETE FROM session_stats WHERE session_id = ?', (session_id,))
                self.cursor.execute('DELETE FROM processed_messages WHERE session_id = ?', (session_id,))
                self.conn.commit()
                
                # Delete session file (Telethon adds .session extension)
                try:
                    session_path_with_ext = f"{self.get_session_path(session_file)}.session"
                    if os.path.exists(session_path_with_ext):
                        os.remove(session_path_with_ext)
                except:
                    pass
                
                await message.reply(f"✅ Session '{session_name}' deleted successfully!")

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
                        if len(parts) == 4:
                            await self.handle_credentials(client, message, parts, user_id)
                        else:
                            await message.reply("❌ Invalid format!\n\nUse: SESSION_NAME API_ID API_HASH PHONE_NUMBER\n\nExample: account1 123456 abc123def456 +919876543210")

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
            session_name, api_id, api_hash, phone = parts

            # Validate session_name (alphanumeric only)
            if not session_name.replace('_', '').isalnum():
                await message.reply("❌ Session name must be alphanumeric (e.g., account1, my_session)")
                return

            # Check if session name already exists
            if self.get_session_by_name(user_id, session_name):
                await message.reply(f"❌ Session '{session_name}' already exists!\n\nUse a different name or delete the existing one with /delete {session_name}")
                return

            # Validate API_ID
            if not api_id.isdigit():
                await message.reply("❌ API_ID must be a number!")
                return

            await message.reply(f"⏳ Creating session '{session_name}'...")
            logger.info(f"Creating session '{session_name}' for user {user_id}")

            # Store user state for verification
            self.user_states[user_id] = {
                'session_name': session_name,
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
            session_name = user_state['session_name']
            api_id = user_state['api_id']
            api_hash = user_state['api_hash']
            phone = user_state['phone']

            # Create unique session file path: user_{user_id}_{session_name}
            # NOTE: Telethon automatically adds .session extension to the session file
            session_file_base = f"user_{user_id}_{session_name}"
            session_path = self.get_session_path(session_file_base)

            # Create Telethon client for user session
            user_client = TelegramClient(session_path, api_id, api_hash)
            await user_client.connect()

            # Send verification code
            await user_client.send_code_request(phone)
            user_state['client'] = user_client
            user_state['session_file_base'] = session_file_base
            user_state['step'] = 'waiting_code'

            await self.client.send_message(
                user_id, 
                "📲 Verification code sent to {}!\n\nPlease enter the code you received:".format(phone)
            )
            logger.info(f"Waiting for code from user {user_id} for session '{session_name}'")

        except Exception as e:
            logger.error(f"Session creation error: {e}")
            await self.client.send_message(user_id, f"❌ Error: {str(e)}")
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
                await self.save_session(user_id, user_client)

            except Exception as two_fa_error:
                # Check if it's 2FA error
                if "password" in str(two_fa_error).lower() or "2fa" in str(two_fa_error).lower():
                    # Ask for 2FA password
                    await self.client.send_message(
                        user_id,
                        "🔐 Two-Factor Authentication Enabled\n\nPlease enter your 2FA password:"
                    )
                    user_state['step'] = 'waiting_password'
                else:
                    raise two_fa_error

        except Exception as e:
            logger.error(f"Verification processing error: {e}")
            await self.client.send_message(user_id, f"❌ Verification failed: {str(e)}")
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
            await self.save_session(user_id, user_client)

        except Exception as e:
            logger.error(f"Password processing error: {e}")
            await self.client.send_message(user_id, f"❌ Login failed: {str(e)}")
            if user_id in self.user_states:
                user_state = self.user_states[user_id]
                if 'client' in user_state:
                    await user_state['client'].disconnect()
                del self.user_states[user_id]

    async def save_session(self, user_id, user_client):
        """Save session and notify user"""
        try:
            user_state = self.user_states[user_id]
            session_name = user_state['session_name']
            api_id = user_state['api_id']
            api_hash = user_state['api_hash']
            phone = user_state['phone']
            session_file_base = user_state['session_file_base']
            
            await user_client.disconnect()

            # Save to sessions table (store the base name without .session extension)
            self.cursor.execute('''
                INSERT INTO sessions 
                (user_id, session_name, api_id, api_hash, phone, session_file, wait_for_reply, next_post_delay, is_active) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (user_id, session_name, api_id, api_hash, phone, session_file_base, DEFAULT_WAIT_FOR_REPLY, DEFAULT_NEXT_POST_DELAY, 1))
            
            session_id = self.cursor.lastrowid
            
            # Initialize stats for this session
            self.cursor.execute('''
                INSERT INTO session_stats (session_id, posted_count, pinned_count)
                VALUES (?, 0, 0)
            ''', (session_id,))
            
            # Deactivate other sessions for this user (make this the active one)
            self.cursor.execute('''
                UPDATE sessions SET is_active = 0 
                WHERE user_id = ? AND session_id != ?
            ''', (user_id, session_id))
            
            self.conn.commit()

            # Send success message
            success_msg = (
                f"✅ Session '{session_name}' Created Successfully!\n\n"
                f"📱 Phone: {phone}\n"
                f"💾 Session ID: {session_id}\n"
                f"🆔 Your User ID: {user_id}\n\n"
                f"🔐 Session saved securely in database.\n"
                f"✅ This is now your active session.\n\n"
                f"Next Steps:\n"
                f"1. View all sessions: /sessions\n"
                f"2. Configure this account: /config TARGET_GROUP SOURCE_CH1 SOURCE_CH2 CHECKER_BOT\n"
                f"3. Start monitoring: /monitor\n\n"
                f"Add more accounts anytime:\n"
                f"SESSION_NAME2 API_ID API_HASH PHONE_NUMBER"
            )
            await self.client.send_message(user_id, success_msg)
            logger.info(f"Session '{session_name}' (ID: {session_id}) created for user {user_id}")

            # Cleanup user state
            if user_id in self.user_states:
                del self.user_states[user_id]

        except Exception as e:
            logger.error(f"Session save error: {e}")
            await self.client.send_message(user_id, f"❌ Session save failed: {str(e)}")
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

    def is_message_processed(self, session_id, message_signature):
        """Check if message was already processed - uses database"""
        self.cursor.execute('''
            SELECT id FROM processed_messages 
            WHERE session_id = ? AND message_signature = ?
        ''', (session_id, message_signature))
        return self.cursor.fetchone() is not None

    def mark_message_processed(self, session_id, message_signature, cc_details, status):
        """Mark message as processed - uses database"""
        try:
            self.cursor.execute('''
                INSERT OR REPLACE INTO processed_messages 
                (session_id, message_signature, cc_details, status, pinned, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (session_id, message_signature, cc_details, status, 1 if status == 'approved' else 0, datetime.now().isoformat()))
            self.conn.commit()
        except Exception as e:
            logger.error(f"Error marking message: {e}")

    def update_stats(self, session_id, posted=0, pinned=0):
        """Update session stats"""
        try:
            self.cursor.execute('''
                UPDATE session_stats 
                SET posted_count = posted_count + ?, pinned_count = pinned_count + ?
                WHERE session_id = ?
            ''', (posted, pinned, session_id))
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

    async def send_and_wait_for_reply(self, session_id, telethon_client, target_group, cc_details, wait_time):
        """Send CC to checker bot and wait for response"""
        try:
            # Send message to bot
            sent_message = await telethon_client.send_message(target_group, f"/chk {cc_details}")
            self.update_stats(session_id, posted=1, pinned=0)
            
            logger.info(f"[Session {session_id}] Sent: {cc_details}")

            # Wait for bot reply
            await asyncio.sleep(wait_time)

            # Check for replies
            async for message in telethon_client.iter_messages(target_group, limit=50):
                if message.reply_to and message.reply_to.reply_to_msg_id == sent_message.id:
                    message_text = message.text or ""
                    logger.info(f"[Session {session_id}] Bot replied: {message_text[:100]}")

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
                        logger.info(f"[Session {session_id}] APPROVED! Pinning...")
                        success = await self.pin_approved_message(telethon_client, target_group, message)
                        if success:
                            self.update_stats(session_id, posted=0, pinned=1)
                            return "approved"
                        return "approved_but_pin_failed"

                    # Check for declined
                    elif any(pattern.lower() in message_text.lower() for pattern in declined_patterns):
                        logger.info(f"[Session {session_id}] DECLINED! Deleting...")
                        await self.delete_declined_message(message)
                        return "declined"

            logger.info(f"[Session {session_id}] No valid reply")
            return "no_reply"

        except Exception as e:
            logger.error(f"[Session {session_id}] Send error: {e}")
            return "error"

    async def process_source_channel(self, session_id, telethon_client, target_group, channel_id, wait_time, delay_time):
        """Process existing messages in source channel"""
        try:
            message_count = 0
            logger.info(f"[Session {session_id}] Processing channel: {channel_id}")

            async for message in telethon_client.iter_messages(channel_id, limit=200):
                text = message.text
                if not text:
                    continue

                message_signature = f"{channel_id}_{message.id}"
                cc_details = self.extract_cc_details(text)

                if cc_details and not self.is_message_processed(session_id, message_signature):
                    logger.info(f"[Session {session_id}] Found CC: {cc_details}")
                    result = await self.send_and_wait_for_reply(session_id, telethon_client, target_group, cc_details, wait_time)
                    self.mark_message_processed(session_id, message_signature, cc_details, result)
                    await asyncio.sleep(delay_time)
                    message_count += 1

            logger.info(f"[Session {session_id}] Channel processed: {message_count} messages")
            return True

        except Exception as e:
            logger.error(f"[Session {session_id}] Channel error: {e}")
            return False

    async def start_monitoring(self, session_id):
        """Start monitoring channels using Telethon for a specific session"""
        try:
            logger.info(f"Starting monitoring for session {session_id}")
            
            # Get session data from database
            self.cursor.execute('''
                SELECT user_id, session_name, api_id, api_hash, phone, session_file, 
                       target_group, source_channels, checker_bot, wait_for_reply, next_post_delay
                FROM sessions WHERE session_id = ?
            ''', (session_id,))
            session_data = self.cursor.fetchone()
            
            if not session_data:
                logger.error(f"Session {session_id} not found!")
                return
            
            user_id, session_name, api_id, api_hash, phone, session_file, target_group, source_channels_str, checker_bot, wait_for_reply, next_post_delay = session_data
            
            if not source_channels_str:
                await self.client.send_message(user_id, f"❌ Configure '{session_name}' first with /config")
                return
            
            source_channels = [int(ch.strip()) if ch.strip().lstrip('-').isdigit() else ch.strip() for ch in source_channels_str.split(',')]

            # Get session file path (Telethon automatically adds .session extension)
            session_path = self.get_session_path(session_file)

            # Create Telethon client with persistent path
            telethon_client = TelegramClient(session_path, api_id, api_hash)
            await telethon_client.start()

            me = await telethon_client.get_me()
            logger.info(f"Monitoring started for session '{session_name}': {me.first_name}")

            # Store client with session_id as key
            self.monitoring_clients[session_id] = telethon_client

            # Notify user
            monitoring_msg = (
                f"🔍 Monitoring Started for '{session_name}'!\n\n"
                f"👤 User: {me.first_name}\n"
                f"📱 Phone: {phone}\n"
                f"🎯 Target: {target_group}\n"
                f"📡 Channels: {len(source_channels)}\n"
                f"🤖 Checker: {checker_bot}\n\n"
                f"Monitoring channels for CC details..."
            )
            await self.client.send_message(user_id, monitoring_msg)

            # Initial cleanup
            logger.info(f"[Session {session_id}] Initial cleanup...")
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
                    if self.is_message_processed(session_id, message_signature):
                        return

                    cc_details = self.extract_cc_details(text)
                    if cc_details:
                        logger.info(f"[Session {session_id}] New CC found: {cc_details}")
                        result = await self.send_and_wait_for_reply(session_id, telethon_client, target_group, cc_details, wait_for_reply)
                        self.mark_message_processed(session_id, message_signature, cc_details, result)
                        await asyncio.sleep(next_post_delay)

                except Exception as e:
                    logger.error(f"[Session {session_id}] Handler error: {e}")

            # Process existing messages
            for channel_id in source_channels:
                await self.process_source_channel(session_id, telethon_client, target_group, channel_id, wait_for_reply, next_post_delay)

            logger.info(f"[Session {session_id}] Monitoring active for '{session_name}'")
            
            # Get current stats
            self.cursor.execute('SELECT * FROM session_stats WHERE session_id = ?', (session_id,))
            stats = self.cursor.fetchone()
            if stats:
                await self.client.send_message(
                    user_id,
                    f"✅ Monitoring Active for '{session_name}'!\n\n📊 Posted: {stats[1]} | Pinned: {stats[2]}"
                )

            # Keep monitoring running
            await asyncio.Event().wait()

        except Exception as e:
            logger.error(f"Monitoring error for session {session_id}: {e}")
            if 'user_id' in locals():
                await self.client.send_message(
                    user_id, 
                    f"❌ Monitoring failed: {str(e)}"
                )

async def main():
    try:
        bot = SessionBot()
        await bot.start_bot()

    except Exception as e:
        logger.error(f"Main function error: {e}")

if __name__ == "__main__":
    asyncio.run(main())

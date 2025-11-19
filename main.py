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
API_HASH = os.environ['API_HASH']
BOT_TOKEN = os.environ['BOT_TOKEN']
PHONE_NUMBER = os.environ['PHONE_NUMBER']
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

# Login management
login_data = {
    'code': None,
    'password': None,
    'code_event': asyncio.Event(),
    'password_event': asyncio.Event()
}

# Bot for login assistance
bot_app = Client("login_helper_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

@bot_app.on_message(filters.private)
async def handle_login_input(client, message):
    """Bot ko code/password receive karega"""
    text = message.text.strip()
    user_id = message.from_user.id
    
    print(f"📨 Received from user {user_id}: {text}")
    
    # Check for confirmation code (5-6 digits)
    if text.isdigit() and 5 <= len(text) <= 6:
        login_data['code'] = text
        await message.reply("✅ Confirmation code received! Processing login...")
        login_data['code_event'].set()
    
    # Check for password
    elif len(text) >= 4:
        login_data['password'] = text
        await message.reply("✅ Password received! Completing login...")
        login_data['password_event'].set()
    
    else:
        await message.reply("❌ Please send:\n• 5-6 digit confirmation code\n• Or your 2FA password")

async def send_code_request():
    """Bot se code request bheje"""
    bot_me = await bot_app.get_me()
    print("=" * 60)
    print("🔐 LOGIN REQUIRED - BOT ASSISTANCE")
    print("=" * 60)
    print(f"🤖 Send confirmation code to: @{bot_me.username}")
    print("📱 You will receive code via Telegram app")
    print("💬 Forward that code to the bot")
    print("=" * 60)

async def login_with_bot_assistance():
    """Bot ki help se login kare"""
    
    # Start bot first
    await bot_app.start()
    print("✅ Bot started for login assistance")
    
    # Send code request message
    await send_code_request()
    
    # Create user client
    user_app = Client("user_session", api_id=API_ID, api_hash=API_HASH)
    
    try:
        # Step 1: Send code request
        await user_app.connect()
        sent_code = await user_app.send_code(PHONE_NUMBER)
        print("📲 Code request sent to Telegram")
        
        # Step 2: Wait for code via bot
        print("⏳ Waiting for confirmation code via bot...")
        login_data['code_event'].clear()
        await login_data['code_event'].wait()
        
        if not login_data['code']:
            print("❌ No code received")
            return None
        
        print(f"🔢 Code received: {login_data['code']}")
        
        # Step 3: Sign in with code
        try:
            await user_app.sign_in(
                phone_number=PHONE_NUMBER,
                phone_code_hash=sent_code.phone_code_hash,
                phone_code=login_data['code']
            )
            print("✅ Signed in successfully!")
            
        except SessionPasswordNeeded:
            print("🔐 2FA Password required")
            
            # Step 4: Wait for password via bot
            login_data['password_event'].clear()
            await login_data['password_event'].wait()
            
            if not login_data['password']:
                print("❌ No password received")
                return None
            
            # Step 5: Sign in with password
            await user_app.check_password(login_data['password'])
            print("✅ 2FA authentication successful!")
        
        # Return the authorized client
        return user_app
        
    except Exception as e:
        print(f"❌ Login failed: {e}")
        await user_app.disconnect()
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
    print("🚀 TELEGRAM MONITOR - BOT LOGIN SYSTEM")
    print("=" * 50)
    print(f"📱 Phone: {PHONE_NUMBER}")
    print(f"🎯 Target: {TARGET_GROUP}")
    print("=" * 50)
    
    init_storage()
    
    # Login with bot assistance
    user_app = await login_with_bot_assistance()
    
    if not user_app:
        print("❌ Login failed. Exiting.")
        await bot_app.stop()
        return
    
    try:
        print("✅ Login successful! Starting monitor...")
        
        me = await user_app.get_me()
        print(f"👤 User: {me.first_name} (@{me.username})")
        
        # Stop bot (no longer needed)
        await bot_app.stop()
        print("🤖 Bot stopped")
        
        print("📊 Posted: 0 | Pinned: 0")
        
        # Cleanup group
        await cleanup_group_messages(user_app)
        
        # Process existing messages
        for channel_id in SOURCE_CHANNELS:
            await process_source_channel(user_app, channel_id)
        
        print(f"\n✅ Ready | Posted: {posted_count} | Pinned: {pinned_count}")
        print("🔍 Monitoring for new messages...")
        
        # Keep running
        while True:
            await asyncio.sleep(3600)
            print("💚 Still monitoring...")
            
    except Exception as e:
        print(f"❌ Error: {e}")
    finally:
        await user_app.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped | Posted: {posted_count} | Pinned: {pinned_count}")
    except Exception as e:
        print(f"💥 Fatal error: {e}")

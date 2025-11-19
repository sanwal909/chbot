import asyncio
import os
import re
import json
import sys
from datetime import datetime
from pyrogram import Client, filters
from pyrogram.types import Message
import time

# Check environment variables first
def check_environment():
    required_vars = ['API_ID', 'API_HASH', 'PHONE_NUMBER', 'TARGET_GROUP', 'CHANNEL_1', 'CHANNEL_2']
    missing_vars = []
    
    for var in required_vars:
        if var not in os.environ:
            missing_vars.append(var)
    
    if missing_vars:
        print("❌ MISSING ENVIRONMENT VARIABLES:")
        for var in missing_vars:
            print(f"   - {var}")
        print("\n💡 Railway pe yeh variables set karo:")
        print("   API_ID, API_HASH, PHONE_NUMBER, TARGET_GROUP, CHANNEL_1, CHANNEL_2")
        sys.exit(1)

# Check environment before anything
check_environment()

# Now safely get environment variables
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH'] 
PHONE_NUMBER = os.environ['PHONE_NUMBER']
TARGET_GROUP = os.environ['TARGET_GROUP']

SOURCE_CHANNELS = [
    int(os.environ['CHANNEL_1']),
    int(os.environ['CHANNEL_2'])
]

# Settings with defaults
WAIT_FOR_REPLY = int(os.environ.get('WAIT_FOR_REPLY', '15'))
NEXT_POST_DELAY = int(os.environ.get('NEXT_POST_DELAY', '10'))

# File-based storage
PROCESSED_FILE = 'processed_messages.json'

# Counters
posted_count = 0
pinned_count = 0

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
    if match:
        return match.group(1)
    return None

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

# Pyrogram Client
app = Client(
    "telegram_session",
    api_id=API_ID,
    api_hash=API_HASH,
    phone_number=PHONE_NUMBER
)

@app.on_message(filters.chat(SOURCE_CHANNELS))
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

async def main():
    print("=" * 50)
    print("🚀 TELEGRAM MONITOR STARTING...")
    print("=" * 50)
    print(f"📱 Phone: {PHONE_NUMBER}")
    print(f"🎯 Target: {TARGET_GROUP}")
    print(f"📡 Channels: {len(SOURCE_CHANNELS)}")
    print("=" * 50)
    
    init_storage()
    
    async with app:
        print("✅ Logged in successfully!")
        me = await app.get_me()
        print(f"👤 User: {me.first_name}")
        
        print("📊 Posted: 0 | Pinned: 0")
        
        # Cleanup group
        await cleanup_group_messages(app)
        
        # Process existing messages
        for channel_id in SOURCE_CHANNELS:
            await process_source_channel(app, channel_id)
        
        print(f"\n✅ Ready | Posted: {posted_count} | Pinned: {pinned_count}")
        print("🔍 Monitoring for new messages...")
        print("💡 Press Ctrl+C to stop")
        
        # Keep running
        while True:
            await asyncio.sleep(3600)
            print("💚 Still monitoring...")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped | Posted: {posted_count} | Pinned: {pinned_count}")
    except Exception as e:
        print(f"💥 Error: {e}")

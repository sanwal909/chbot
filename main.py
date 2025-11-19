import sys
print(f"🐍 Python version: {sys.version}")
import asyncio
from telethon import TelegramClient, events
import json
import os
import re
from datetime import datetime
import time
import traceback

# REQUIRED Environment variables - no default values
API_ID = int(os.environ['API_ID'])
API_HASH = os.environ['API_HASH']
PHONE_NUMBER = os.environ['PHONE_NUMBER']
TARGET_GROUP = os.environ['TARGET_GROUP']

# Source channels from environment
SOURCE_CHANNELS = [
    int(os.environ['CHANNEL_1']),
    int(os.environ['CHANNEL_2'])
]

# Optional settings with defaults
WAIT_FOR_REPLY = int(os.environ.get('WAIT_FOR_REPLY', '15'))
NEXT_POST_DELAY = int(os.environ.get('NEXT_POST_DELAY', '10'))
SESSION_FILE = os.environ.get('SESSION_FILE', 'telegram_session')

# File-based storage
PROCESSED_FILE = 'processed_messages.json'

# Counters
posted_count = 0
pinned_count = 0

class FileStorage:
    @staticmethod
    def load_json(filename):
        for _ in range(3):
            try:
                if os.path.exists(filename):
                    with open(filename, 'r', encoding='utf-8') as f:
                        return json.load(f)
                return {}
            except:
                time.sleep(0.1)
        return {}
    
    @staticmethod
    def save_json(filename, data):
        for _ in range(3):
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                return True
            except:
                time.sleep(0.1)
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

async def pin_approved_message(client, message):
    global pinned_count
    try:
        await client.pin_message(TARGET_GROUP, message)
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
        
        async for message in client.iter_messages(TARGET_GROUP, limit=200):
            if not message.pinned:
                try:
                    await message.delete()
                    deleted_count += 1
                    await asyncio.sleep(0.3)
                except Exception as e:
                    continue
        
        print(f"✅ Cleanup completed. Deleted {deleted_count} messages")
    except Exception as e:
        print(f"❌ Cleanup error: {e}")

async def send_and_wait_for_reply(client, cc_details):
    global posted_count
    
    try:
        print(f"🔄 Sending CC: {cc_details}")
        
        # Send message to bot
        await client.send_message(TARGET_GROUP, f".chk {cc_details}")
        posted_count += 1
        print_stats()
        
        # Wait for bot reply
        print(f"⏳ Waiting {WAIT_FOR_REPLY} seconds for reply...")
        await asyncio.sleep(WAIT_FOR_REPLY)
        
        # Check for replies
        async for message in client.iter_messages(TARGET_GROUP, limit=200):
            if message.reply_to_msg_id:
                message_text = message.text or ""
                print(f"🤖 Bot reply: {message_text[:100]}...")
                
                # Check for APPROVED
                if any(approved in message_text for approved in ["Approved ✅", "Status: Approved", "APPROVED", "Approved", "Card added", "Response: Card added", "Status: Approved ✅", "✅ Approved", "APPROVED ✅"]):
                    print("🎯 APPROVED detected!")
                    await pin_approved_message(client, message)
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

async def setup_client():
    client = TelegramClient(SESSION_FILE, API_ID, API_HASH)
    return client

async def process_source_channel(client, channel_id):
    try:
        print(f"🔄 Processing channel: {channel_id}")
        message_count = 0
        
        async for message in client.iter_messages(channel_id, limit=500):
            text = message.text
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
    print("🚀 Starting Secure Telegram Monitor...")
    print("🔒 All credentials from environment variables")
    
    # Verify required environment variables
    required_vars = ['API_ID', 'API_HASH', 'PHONE_NUMBER', 'TARGET_GROUP', 'CHANNEL_1', 'CHANNEL_2']
    for var in required_vars:
        if var not in os.environ:
            print(f"❌ Missing required environment variable: {var}")
            return
    
    init_storage()
    
    client = await setup_client()
    
    # Cloud-friendly login
    try:
        print(f"📱 Logging in with phone: {PHONE_NUMBER}")
        await client.start(phone=PHONE_NUMBER)
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return
    
    me = await client.get_me()
    print(f"✅ Logged in as: {me.first_name}")
    
    print("📊 Posted: 0 | Pinned: 0")
    
    # Cleanup group
    await cleanup_group_messages(client)
    
    # Message handler for NEW messages
    @client.on(events.NewMessage)
    async def handler(event):
        message = event.message
        chat_id = message.chat.id
        
        if chat_id not in SOURCE_CHANNELS:
            return
        
        text = message.text
        if not text:
            return
        
        message_signature = f"{chat_id}_{message.id}"
        if is_message_processed(message_signature):
            return
        
        cc_details = extract_cc_details(text)
        if cc_details:
            print(f"🆕 New CC: {cc_details}")
            result = await send_and_wait_for_reply(client, cc_details)
            mark_message_processed(message_signature, cc_details, result)
            await asyncio.sleep(NEXT_POST_DELAY)
    
    # Process existing messages
    for channel_id in SOURCE_CHANNELS:
        await process_source_channel(client, channel_id)
    
    print(f"\n✅ Ready | Posted: {posted_count} | Pinned: {pinned_count}")
    print("🔍 Monitoring for new messages...")
    
    # Keep alive loop
    while True:
        try:
            await asyncio.sleep(3600)  # 1 hour
            print("💚 Still running...")
        except KeyboardInterrupt:
            break
    
    await client.disconnect()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n🛑 Stopped | Posted: {posted_count} | Pinned: {pinned_count}")
    except Exception as e:
        print(f"💥 Error: {e}")
        traceback.print_exc()

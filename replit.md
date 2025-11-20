# Telegram Session Bot Project

## Overview
A Telegram bot built with Pyrogram that creates user sessions and monitors channels for credit card details. The bot can automatically process messages, detect approved/declined status, and pin approved messages.

## Project Structure
```
.
├── main.py                       # Main bot application
├── requirements.txt              # Python dependencies
├── Procfile                      # Railway deployment config
├── .gitignore                    # Git ignore rules
├── RAILWAY_DEPLOYMENT.md         # Deployment guide
└── replit.md                     # This file
```

## Main Features
1. **Session Management**: Creates and manages Telegram user sessions
2. **Channel Monitoring**: Monitors source channels for specific patterns
3. **Auto Processing**: Automatically processes credit card details
4. **Message Pinning**: Pins approved messages in target group
5. **Database Storage**: SQLite for user session management
6. **2FA Support**: Handles two-factor authentication

## Dependencies
- `pyrogram==2.0.106` - Telegram client library
- `tgcrypto==1.2.5` - Encryption for faster performance

## Environment Variables Required
```
API_ID              # Telegram API ID from my.telegram.org
API_HASH            # Telegram API Hash
BOT_TOKEN           # Bot token from @BotFather
TARGET_GROUP        # Target group ID for posting
CHANNEL_1           # First source channel ID
CHANNEL_2           # Second source channel ID
WAIT_FOR_REPLY      # Seconds to wait for reply (default: 15)
NEXT_POST_DELAY     # Delay between posts (default: 10)
```

## Bot Commands
- `/start` - Start the bot and see welcome message
- `/help` - Get help on how to use the bot
- `/monitor` - Start monitoring channels (after session creation)

## Recent Changes
- **2025-11-20**: Fixed all Pyrogram 2.0 compatibility issues:
  - Fixed bot_token parameter issue
  - Removed is_user_authorized() method (deprecated in Pyrogram 2.0)
  - Fixed run_until_disconnected() method (changed to asyncio.Event)
  - Fixed syntax error (line 15 - removed extra parenthesis)
- **2025-11-20**: Added Railway deployment configuration (requirements.txt, Procfile)
- **2025-11-20**: Created .gitignore to protect sensitive files
- **2025-11-20**: Created deployment guide for Railway

## Deployment
This project is configured for Railway deployment. See `RAILWAY_DEPLOYMENT.md` for detailed deployment instructions.

## User Preferences
- User prefers Hindi/Hinglish communication
- Project is meant for Railway hosting

## Architecture Notes
- Uses Pyrogram for Telegram client functionality
- SQLite for session storage
- JSON file for tracking processed messages
- Asyncio-based event handling
- Separate user session management per user

## Important Files
- `*.session` files - Telegram session data (not committed to git)
- `user_sessions.db` - SQLite database for user management
- `processed_messages.json` - Tracks processed messages to avoid duplicates

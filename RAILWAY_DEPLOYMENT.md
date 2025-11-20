# Railway पर Deployment करने की Guide 🚀

## आपकी Bot की जानकारी
यह एक Telegram bot है जो:
- Users के लिए Telegram sessions बनाता है
- Channels को monitor करता है
- CC details को automatically process करता है

## Railway पर Deploy करने के Steps:

### 1️⃣ **GitHub पर Code Upload करें**

अपने computer पर:
```bash
git init
git add .
git commit -m "Initial commit"
```

फिर GitHub पर:
- एक नया repository बनाएं
- अपना code push करें:
```bash
git remote add origin https://github.com/your-username/your-repo-name.git
git push -u origin main
```

### 2️⃣ **Railway पर Sign Up करें**

1. Visit करें: https://railway.app
2. "Login with GitHub" button click करें
3. अपने GitHub account से login करें

### 3️⃣ **New Project बनाएं**

1. Railway dashboard में "New Project" click करें
2. "Deploy from GitHub repo" select करें
3. अपना repository choose करें

### 4️⃣ **Environment Variables Add करें** ⚠️ बहुत Important!

Railway में Settings → Variables में जाएं और ये सब add करें:

```
API_ID = 12345678
API_HASH = your_api_hash_here
BOT_TOKEN = 1234567890:ABCdefGHIjklMNOpqrsTUVwxyz
TARGET_GROUP = -1001234567890
CHANNEL_1 = -1001111111111
CHANNEL_2 = -1002222222222
WAIT_FOR_REPLY = 15
NEXT_POST_DELAY = 10
```

**ये कैसे पाएं:**
- **API_ID और API_HASH**: https://my.telegram.org पर जाएं
- **BOT_TOKEN**: @BotFather से bot बनाकर मिलेगा
- **TARGET_GROUP**: अपनी group की ID
- **CHANNEL_1, CHANNEL_2**: Source channels की IDs

### 5️⃣ **⚠️ IMPORTANT: Persistent Storage Setup करें**

**बहुत ज़रूरी:** Railway का filesystem ephemeral है, यानी हर redeploy पर सब files delete हो जाती हैं! 

आपकी bot को `.session` files और database को save रखना ज़रूरी है। दो options हैं:

**Option A: Railway Volume Add करें (Recommended)**

1. Railway dashboard में अपनी service select करें
2. "Settings" tab में जाएं
3. "Volumes" section में scroll करें
4. "New Volume" click करें
5. Mount Path डालें: `/app/data`
6. Volume create करें

फिर code में path change करें:
- Session files: `/app/data/user_{user_id}.session`
- Database: `/app/data/user_sessions.db`
- Processed file: `/app/data/processed_messages.json`

**Option B: External Database Use करें (Partial Solution)**

⚠️ **Note**: यह option सिर्फ database को persist करेगा, `.session` files के लिए Volume फिर भी चाहिए!

SQLite की जगह Railway का PostgreSQL database use करें:
1. Railway में "New" → "Database" → "PostgreSQL"
2. Connection URL automatically `DATABASE_URL` में मिलेगा
3. Code को update करके PostgreSQL use करें
4. **लेकिन** `.session` और `.json` files के लिए Volume (Option A) add करना ज़रूरी है!

**Best Practice**: दोनों combine करें:
- PostgreSQL database के लिए
- Volume `/app/data` session files के लिए

### 6️⃣ **Deploy करें!**

सब set करने के बाद:
- Railway automatically आपका bot deploy कर देगा
- Logs में देखें कि सब सही चल रहा है
- "Deployments" tab में देख सकते हैं status

## 🔍 Troubleshooting

### Bot शुरू नहीं हो रहा?
- Environment variables check करें
- Logs में errors देखें
- Railway dashboard में "View Logs" click करें

### Database/Session issues?
- ⚠️ **Railway का filesystem ephemeral है** - हर redeploy पर files delete होंगी
- Volume mount करना ज़रूरी है persistent storage के लिए
- Volume mount path: `/app/data`
- Volume setup के बिना sessions हर redeploy पर delete होंगे!

### Bot crash हो रहा है?
- Logs check करें
- API_ID, API_HASH, BOT_TOKEN सही हैं verify करें

## 📊 Important Notes

1. **Free Tier**: Railway का free tier limited है ($5 credit monthly)
2. **⚠️ Persistent Storage**: Railway का default filesystem ephemeral है! Volume mount करना **mandatory** है session files save करने के लिए
3. **Volume Cost**: Volumes paid plan पर available हैं (Free tier पर limited)
4. **Logs**: Railway dashboard से real-time logs देख सकते हैं
5. **Auto Deploy**: GitHub पर हर push के बाद automatically deploy होगा
6. **Filesystem**: बिना volume के, हर redeploy पर सब files (sessions, database) delete हो जाएंगे

## 🎯 Bot Commands

Users के लिए:
- `/start` - Bot शुरू करें
- `/help` - Help message
- `/monitor` - Monitoring शुरू करें

## ⚠️ Security

- **कभी भी** अपने environment variables को code में न डालें
- `.gitignore` file session files को protect करती है
- Railway पर ही variables set करें

## 📞 Support

अगर कोई problem आए तो:
1. Railway logs check करें
2. Environment variables verify करें
3. Bot token और API credentials check करें

**Happy Deploying! 🚀**

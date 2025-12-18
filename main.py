import requests
import time
import logging
import json
import re
import os
import threading
from datetime import datetime, timedelta
from typing import Optional
from flask import Flask, jsonify

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pella_bot_automation.log'),
        logging.StreamHandler()
    ]
)

# Flask app for Render health checks
app = Flask(__name__)

@app.route('/', methods=['GET'])
def health_check():
    return jsonify({"status": "Pella Bot is running"}), 200

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "ok"}), 200

class PellaAccount:
    def __init__(self, account_name, email, password, server_id, telegram_chat_id=None, 
                 custom_restart_time=45, auto_restart=True, is_active=True):
        self.account_name = account_name
        self.email = email
        self.password = password
        self.server_id = server_id
        self.telegram_chat_id = telegram_chat_id
        self.custom_restart_time = custom_restart_time
        self.auto_restart = auto_restart
        self.is_active = is_active
        self.current_token = None
        self.session = requests.Session()
        self.last_restart_time: Optional[datetime] = None
        self.restart_count = 0

    def __str__(self):
        return f"PellaAccount({self.account_name}, Server: {self.server_id}, RestartTime: {self.custom_restart_time}min)"

class PellaMultiAutomation:
    def __init__(self):
        self.config_file = "config.json"
        self.base_url = "https://api.pella.app/server"
        self.clerk_url = "https://clerk.pella.app/v1/client"
        
        self.last_request_time = 0
        self.request_delay = 3
        self.bot_running = True
        self.last_update_id = 0
        
        self.load_config()

    def load_config(self):
        """Load config from environment variables or config file"""
        # Try to load from config.json first
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                
                self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN") or config.get("telegram_bot_token", "")
                self.accounts = []
                
                for acc_data in config.get("accounts", []):
                    account = PellaAccount(
                        account_name=acc_data["account_name"],
                        email=acc_data["email"],
                        password=acc_data["password"],
                        server_id=acc_data["server_id"],
                        telegram_chat_id=acc_data.get("telegram_chat_id"),
                        custom_restart_time=acc_data.get("custom_restart_time", 45),
                        auto_restart=acc_data.get("auto_restart", True),
                        is_active=acc_data.get("is_active", True)
                    )
                    self.accounts.append(account)
                
                logging.info(f"✅ Loaded {len(self.accounts)} accounts from config file")
                return
            
            except Exception as e:
                logging.error(f"❌ Failed to load config file: {e}")
        
        # Fallback to environment variables
        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.accounts = []
        
        # Load accounts from environment variables (JSON format)
        accounts_json = os.getenv("PELLA_ACCOUNTS", "")
        if accounts_json:
            try:
                accounts_data = json.loads(accounts_json)
                for acc_data in accounts_data:
                    account = PellaAccount(
                        account_name=acc_data.get("account_name", "Default"),
                        email=acc_data.get("email", ""),
                        password=acc_data.get("password", ""),
                        server_id=acc_data.get("server_id", ""),
                        telegram_chat_id=acc_data.get("telegram_chat_id"),
                        custom_restart_time=acc_data.get("custom_restart_time", 45),
                        auto_restart=acc_data.get("auto_restart", True),
                        is_active=acc_data.get("is_active", True)
                    )
                    self.accounts.append(account)
                logging.info(f"✅ Loaded {len(self.accounts)} accounts from environment variables")
            except Exception as e:
                logging.error(f"❌ Failed to parse PELLA_ACCOUNTS: {e}")
        
        if not self.accounts:
            logging.warning(f"⚠️  No accounts configured. Please set PELLA_ACCOUNTS environment variable")
    
    def save_config(self):
        """Save config to file if it exists, otherwise only in memory"""
        try:
            config = {
                "accounts": []
            }
            
            for account in self.accounts:
                acc_data = {
                    "account_name": account.account_name,
                    "email": account.email,
                    "password": account.password,
                    "server_id": account.server_id,
                    "telegram_chat_id": account.telegram_chat_id,
                    "custom_restart_time": account.custom_restart_time,
                    "auto_restart": account.auto_restart,
                    "is_active": account.is_active
                }
                config["accounts"].append(acc_data)
            
            # Try to save to file if writable
            try:
                with open(self.config_file, 'w') as f:
                    json.dump(config, f, indent=2)
                logging.info("✅ Config saved to file successfully")
            except (IOError, OSError):
                logging.info("ℹ️  Running in read-only environment (expected on Render)")
            
            return True
        
        except Exception as e:
            logging.error(f"❌ Failed to save config: {e}")
            return False

    def rate_limit(self):
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time
        if time_since_last_request < self.request_delay:
            sleep_time = self.request_delay - time_since_last_request
            logging.info(f"⏳ Rate limiting: Waiting {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self.last_request_time = time.time()

    def send_telegram_message(self, message, chat_id=None):
        if not self.telegram_bot_token:
            logging.warning("⚠️  Telegram bot token not set")
            return False

        if not chat_id:
            logging.warning("⚠️  No chat ID specified")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }

        try:
            self.rate_limit()
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                logging.info("📱 Telegram message sent successfully")
                return True
            else:
                logging.error(f"❌ Failed to send Telegram message: {response.text}")
                return False
        except Exception as e:
            logging.error(f"❌ Telegram error: {e}")
            return False

    def send_broadcast_message(self, message):
        success_count = 0
        unique_chats = set()

        for account in self.accounts:
            if account.telegram_chat_id:
                unique_chats.add(account.telegram_chat_id)

        for chat_id in unique_chats:
            if self.send_telegram_message(message, chat_id):
                success_count += 1
            time.sleep(1)

        return success_count

    def extract_session_ids(self, response):
        sia_id = None
        sess_id = None

        try:
            data = response.json()

            if 'response' in data and 'id' in data['response']:
                sia_id = data['response']['id']
            elif 'client' in data and 'sign_in' in data['client'] and 'id' in data['client']['sign_in']:
                sia_id = data['client']['sign_in']['id']

            if 'response' in data and 'created_session_id' in data['response']:
                sess_id = data['response']['created_session_id']
            elif 'client' in data and 'last_active_session_id' in data['client']:
                sess_id = data['client']['last_active_session_id']

        except Exception as e:
            logging.warning(f"⚠️  Could not parse JSON: {e}")

        return sia_id, sess_id

    def extract_jwt_token(self, response):
        try:
            data = response.json()

            if 'token' in data:
                jwt_token = data['token']
                return f"Bearer {jwt_token}"

            if 'client' in data and 'sessions' in data['client'] and data['client']['sessions']:
                for session in data['client']['sessions']:
                    if 'last_active_token' in session and 'jwt' in session['last_active_token']:
                        jwt_token = session['last_active_token']['jwt']
                        return f"Bearer {jwt_token}"

            if 'response' in data and 'last_active_token' in data['response']:
                jwt_token = data['response']['last_active_token']['jwt']
                return f"Bearer {jwt_token}"

            response_text = json.dumps(data)
            jwt_pattern = r'eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+'
            matches = re.findall(jwt_pattern, response_text)
            if matches:
                return f"Bearer {matches[0]}"

        except Exception as e:
            logging.warning(f"⚠️  Could not extract JWT token: {e}")

        return None

    def perform_complete_login(self, account):
        logging.info(f"🔐 [{account.account_name}] Performing complete login...")

        try:
            account.session = requests.Session()

            # STEP 1: Initial sign in
            url1 = f"{self.clerk_url}/sign_ins?__clerk_api_version=2025-11-10&_clerk_js_version=5.109.2"
            payload1 = {
                'identifier': account.email,
                'locale': "en-IN"
            }

            headers1 = {
                'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                'Accept-Encoding': "identity",
                'Content-Type': 'application/x-www-form-urlencoded',
                'sec-ch-ua-platform': "\"Windows\"",
                'sec-ch-ua': "\"Chromium\";v=\"142\", \"Not_A Brand\";v=\"99\"",
                'sec-ch-ua-mobile': "?0",
                'origin': "https://www.pella.app",
                'x-requested-with': "mark.via.gp",
                'sec-fetch-site': "same-site",
                'sec-fetch-mode': "cors",
                'sec-fetch-dest': "empty",
                'referer': "https://www.pella.app/",
                'accept-language': "en-IN,en-US;q=0.9,en;q=0.8",
                'priority': "u=1, i"
            }

            self.rate_limit()
            response1 = account.session.post(url1, data=payload1, headers=headers1, timeout=15)
            logging.info(f"📧 [{account.account_name}] Step 1 - Sign in: {response1.status_code}")

            if response1.status_code != 200:
                logging.error(f"❌ [{account.account_name}] Sign in failed: {response1.text}")
                return False

            sia_id, sess_id = self.extract_session_ids(response1)
            logging.info(f"🔍 [{account.account_name}] Extracted - SIA: {sia_id}")

            if not sia_id:
                logging.error(f"❌ [{account.account_name}] Could not extract sign in attempt ID")
                return False

            time.sleep(3)

            # STEP 2: Password authentication
            url2 = f"{self.clerk_url}/sign_ins/{sia_id}/attempt_first_factor?__clerk_api_version=2025-11-10&_clerk_js_version=5.109.2"
            payload2 = {
                'strategy': "password",
                'password': account.password
            }

            self.rate_limit()
            response2 = account.session.post(url2, data=payload2, headers=headers1, timeout=15)
            logging.info(f"🔑 [{account.account_name}] Step 2 - Password: {response2.status_code}")

            if response2.status_code != 200:
                logging.error(f"❌ [{account.account_name}] Password authentication failed: {response2.text}")
                return False

            logging.info(f"✅ [{account.account_name}] Password authentication successful!")
            account.current_token = self.extract_jwt_token(response2)

            time.sleep(3)

            # STEP 3: Session touch
            if account.current_token:
                sia_id2, sess_id2 = self.extract_session_ids(response2)
                if sess_id2:
                    url3 = f"{self.clerk_url}/sessions/{sess_id2}/touch?__clerk_api_version=2025-11-10&_clerk_js_version=5.109.2"
                    payload3 = {'active_organization_id': ""}

                    self.rate_limit()
                    response3 = account.session.post(url3, data=payload3, headers=headers1, timeout=15)
                    logging.info(f"🔐 [{account.account_name}] Step 3 - Session Touch: {response3.status_code}")

                    if response3.status_code == 200:
                        logging.info(f"✅ [{account.account_name}] Session established successfully!")
                        new_token = self.extract_jwt_token(response3)
                        if new_token:
                            account.current_token = new_token

            if not account.current_token:
                logging.warning(f"⚠️  [{account.account_name}] No JWT token extracted, will use session cookies")

            return True

        except requests.exceptions.Timeout:
            logging.error(f"❌ [{account.account_name}] Login timeout - network issue")
            return False
        except Exception as e:
            logging.error(f"❌ [{account.account_name}] Login error: {e}")
            return False

    def get_fresh_token(self, account):
        logging.info(f"🔄 [{account.account_name}] Getting fresh authentication token...")

        if self.perform_complete_login(account):
            return True

        logging.info(f"🔄 [{account.account_name}] Complete login failed, trying fallback...")

        try:
            url1 = f"{self.clerk_url}/sign_ins?__clerk_api_version=2025-11-10&_clerk_js_version=5.109.2"
            payload1 = {
                'identifier': account.email,
                'locale': "en-IN"
            }

            headers1 = {
                'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                'Accept-Encoding': "identity",
                'Content-Type': 'application/x-www-form-urlencoded',
                'sec-ch-ua-platform': "\"Windows\"",
                'sec-ch-ua': "\"Chromium\";v=\"142\", \"Not_A Brand\";v=\"99\"",
                'sec-ch-ua-mobile': "?0",
                'origin': "https://www.pella.app",
                'x-requested-with': "mark.via.gp",
                'sec-fetch-site': "same-site",
                'sec-fetch-mode': "cors",
                'sec-fetch-dest': "empty",
                'referer': "https://www.pella.app/",
                'accept-language': "en-IN,en-US;q=0.9,en;q=0.8",
                'priority': "u=1, i"
            }

            self.rate_limit()
            response1 = account.session.post(url1, data=payload1, headers=headers1, timeout=15)
            logging.info(f"📧 [{account.account_name}] Fallback - Sign in: {response1.status_code}")

            if response1.status_code != 200:
                if response1.status_code == 400 and "already signed in" in response1.text:
                    logging.info(f"ℹ️  [{account.account_name}] Already signed in, proceeding...")
                    account.current_token = self.extract_jwt_token(response1)
                    return True
                else:
                    logging.error(f"❌ [{account.account_name}] Fallback sign in failed: {response1.text}")
                    return False

            return True

        except requests.exceptions.Timeout:
            logging.error(f"❌ [{account.account_name}] Fallback timeout")
            return False
        except Exception as e:
            logging.error(f"❌ [{account.account_name}] Fallback login error: {e}")
            return False

    def make_api_request(self, account, method, endpoint, payload=None, retry_count=0):
        if retry_count >= 2:
            logging.error(f"❌ [{account.account_name}] Max retries reached for API request")
            return None

        url = f"{self.base_url}/{endpoint}"

        headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
            'Accept-Encoding': "identity",
            'Content-Type': "application/json",
            'sec-ch-ua-platform': "\"Windows\"",
            'sec-ch-ua': "\"Chromium\";v=\"142\", \"Not_A Brand\";v=\"99\"",
            'sec-ch-ua-mobile': "?0",
            'origin': "https://www.pella.app",
            'x-requested-with': "mark.via.gp",
            'sec-fetch-site': "same-site",
            'sec-fetch-mode': "cors",
            'sec-fetch-dest': "empty",
            'referer': "https://www.pella.app/",
            'accept-language': "en-IN,en-US;q=0.9,en;q=0.8",
            'priority': "u=1, i"
        }

        if account.current_token:
            headers['authorization'] = account.current_token
            logging.info(f"🔑 [{account.account_name}] Using JWT token for authentication")
        else:
            logging.info(f"🍪 [{account.account_name}] Using session cookies for authentication")

        if payload is None:
            payload = {}

        if 'id' not in payload and endpoint in ['start', 'stop', 'info']:
            payload['id'] = account.server_id

        try:
            self.rate_limit()

            if method.upper() == 'GET':
                if 'id' in payload:
                    url = f"{url}?id={payload['id']}"
                response = account.session.get(url, headers=headers, timeout=15)
            else:
                response = account.session.post(url, data=json.dumps(payload), headers=headers, timeout=15)

            logging.info(f"🌐 [{account.account_name}] API {method} {endpoint}: {response.status_code}")

            if response.status_code == 200:
                logging.info(f"📄 [{account.account_name}] Response preview: {response.text[:200]}...")

            if response.status_code == 401:
                logging.warning(f"🔄 [{account.account_name}] Authentication failed, re-authenticating...")
                if self.get_fresh_token(account):
                    return self.make_api_request(account, method, endpoint, payload, retry_count + 1)
                else:
                    return None

            if response.status_code == 429:
                logging.warning(f"⏳ [{account.account_name}] Rate limited, waiting 60 seconds...")
                time.sleep(60)
                return self.make_api_request(account, method, endpoint, payload, retry_count + 1)

            return response

        except requests.exceptions.Timeout:
            logging.error(f"❌ [{account.account_name}] API request timeout")
            return None
        except requests.exceptions.ConnectionError:
            logging.error(f"❌ [{account.account_name}] Connection error - checking network")
            return None
        except Exception as e:
            logging.error(f"❌ [{account.account_name}] API request error: {e}")
            return None

    def safe_json_parse(self, response):
        try:
            return response.json()
        except json.JSONDecodeError as e:
            logging.error(f"❌ JSON parse error: {e}")
            return None
        except Exception as e:
            logging.error(f"❌ Unexpected parse error: {e}")
            return None

    def get_server_info(self, account):
        logging.info(f"📊 [{account.account_name}] Getting server info...")

        response = self.make_api_request(account, 'GET', 'info', {'id': account.server_id})

        if response and response.status_code == 200:
            data = self.safe_json_parse(response)
            if data:
                status = data.get('status', 'unknown')
                logging.info(f"🟢 [{account.account_name}] Server Status: {status}")
                return status
            else:
                logging.error(f"❌ [{account.account_name}] Could not parse server info response")
                return None
        else:
            if response:
                logging.error(f"❌ [{account.account_name}] Failed to get server info: {response.status_code}")
            else:
                logging.error(f"❌ [{account.account_name}] No response from server info request")
            return None

    def start_server(self, account):
        logging.info(f"▶️  [{account.account_name}] Starting server...")

        response = self.make_api_request(account, 'POST', 'start', {'id': account.server_id})

        if response:
            if response.status_code == 200:
                logging.info(f"✅ [{account.account_name}] Server start command sent successfully")

                if account.telegram_chat_id:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    message = f"🚀 <b>{account.account_name} - Service Started</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n📊 Status: Starting..."
                    self.send_telegram_message(message, account.telegram_chat_id)

                data = self.safe_json_parse(response)
                if data:
                    logging.info(f"📋 [{account.account_name}] Start response: {data}")

                logging.info(f"⏳ [{account.account_name}] Waiting 2 minutes for server to fully start...")
                time.sleep(120)

                return True
            else:
                error_msg = f"❌ [{account.account_name}] Failed to start server: {response.status_code}"
                logging.error(error_msg)
                
                if account.telegram_chat_id:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    telegram_msg = f"❌ <b>START FAILED - {account.account_name}</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n❌ Error: HTTP {response.status_code}\n📝 {response.text[:100]}"
                    self.send_telegram_message(telegram_msg, account.telegram_chat_id)
                
                return False
        else:
            error_msg = f"❌ [{account.account_name}] No response from start server request"
            logging.error(error_msg)
            
            if account.telegram_chat_id:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                telegram_msg = f"❌ <b>START FAILED - {account.account_name}</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n❌ Error: No response from server"
                self.send_telegram_message(telegram_msg, account.telegram_chat_id)
            
            return False

    def stop_server(self, account):
        logging.info(f"⏹️  [{account.account_name}] Stopping server...")

        response = self.make_api_request(account, 'POST', 'stop', {'id': account.server_id})

        if response:
            if response.status_code == 200:
                logging.info(f"🛑 [{account.account_name}] Server stop command sent successfully")

                if account.telegram_chat_id:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    message = f"🛑 <b>{account.account_name} - Service Stopped</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n📊 Status: Stopping..."
                    self.send_telegram_message(message, account.telegram_chat_id)

                data = self.safe_json_parse(response)
                if data:
                    logging.info(f"📋 [{account.account_name}] Stop response: {data}")

                logging.info(f"⏳ [{account.account_name}] Waiting 1 minute for server to fully stop...")
                time.sleep(60)

                return True
            else:
                error_msg = f"❌ [{account.account_name}] Failed to stop server: {response.status_code}"
                logging.error(error_msg)
                
                if account.telegram_chat_id:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    telegram_msg = f"❌ <b>STOP FAILED - {account.account_name}</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n❌ Error: HTTP {response.status_code}"
                    self.send_telegram_message(telegram_msg, account.telegram_chat_id)
                
                return False
        else:
            error_msg = f"❌ [{account.account_name}] No response from stop server request"
            logging.error(error_msg)
            
            if account.telegram_chat_id:
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                telegram_msg = f"❌ <b>STOP FAILED - {account.account_name}</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n❌ Error: No response from server"
                self.send_telegram_message(telegram_msg, account.telegram_chat_id)
            
            return False

    def restart_server(self, account):
        logging.info(f"🔄 [{account.account_name}] Restarting server...")
        
        if self.stop_server(account):
            logging.info(f"⏳ [{account.account_name}] Waiting 30 seconds before restart...")
            time.sleep(30)
            return self.start_server(account)
        
        return False

    def monitor_and_restart(self, account):
        logging.info(f"👁️  [{account.account_name}] Starting monitoring...")
        
        while self.bot_running and account.is_active:
            try:
                status = self.get_server_info(account)
                
                if status == "offline":
                    if account.auto_restart:
                        logging.info(f"⚠️  [{account.account_name}] Server is offline - initiating restart")
                        
                        if account.telegram_chat_id:
                            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            message = f"⚠️  <b>{account.account_name} - Server Down</b>\n\n⏰ Time: {current_time}\n🆔 Server: {account.server_id}\n📊 Status: Offline - Restarting..."
                            self.send_telegram_message(message, account.telegram_chat_id)
                        
                        if self.restart_server(account):
                            account.last_restart_time = datetime.now()
                            account.restart_count += 1
                            logging.info(f"✅ [{account.account_name}] Restart successful!")
                        else:
                            logging.error(f"❌ [{account.account_name}] Restart failed!")
                    else:
                        logging.info(f"⚠️  [{account.account_name}] Server is offline but auto-restart is disabled")
                
                elif status == "online":
                    logging.info(f"✅ [{account.account_name}] Server is running normally")
                
                # Custom restart time logic
                if account.last_restart_time:
                    elapsed = (datetime.now() - account.last_restart_time).total_seconds() / 60
                    if elapsed >= account.custom_restart_time:
                        logging.info(f"⏱️  [{account.account_name}] Custom restart time reached ({account.custom_restart_time}min)")
                        if self.restart_server(account):
                            account.last_restart_time = datetime.now()
                            account.restart_count += 1
                
                # Sleep for 5 minutes before next check
                logging.info(f"💤 [{account.account_name}] Sleeping for 5 minutes...")
                time.sleep(300)
            
            except Exception as e:
                logging.error(f"❌ [{account.account_name}] Error in monitoring loop: {e}")
                time.sleep(60)

    def run(self):
        if not self.accounts:
            logging.error("❌ No accounts configured!")
            logging.info("📋 Please configure accounts in PELLA_ACCOUNTS environment variable or config.json")
            logging.info("📋 Example: PELLA_ACCOUNTS='[{\"account_name\":\"Account1\",\"email\":\"user@example.com\",\"password\":\"pwd\",\"server_id\":\"12345\"}]'")
            return

        logging.info("🤖 STARTING BOT-CONTROLLED AUTOMATION!")
        logging.info(f"🤖 Loaded {len(self.accounts)} accounts for monitoring")
        
        if self.telegram_bot_token:
            logging.info("✅ Telegram bot token configured")
            message = f"🤖 Pella Bot Started\n⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📊 Accounts: {len(self.accounts)}"
            self.send_broadcast_message(message)
        else:
            logging.warning("⚠️  Telegram notifications disabled (no token)")
        
        try:
            while self.bot_running:
                for account in self.accounts:
                    if account.is_active:
                        self.monitor_and_restart(account)
        except KeyboardInterrupt:
            logging.info("\n🛑 Bot interrupted by user")
            self.bot_running = False
        except Exception as e:
            logging.error(f"❌ Fatal error: {e}")
            if self.telegram_bot_token:
                self.send_broadcast_message(f"❌ Bot Fatal Error: {str(e)[:100]}")
        finally:
            logging.info("🛑 Bot shutdown complete")

def run_bot_in_background():
    """Run the bot in a background thread"""
    bot = PellaMultiAutomation()
    bot.run()

if __name__ == "__main__":
    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot_in_background, daemon=True)
    bot_thread.start()
    
    # Start Flask web server on port 10000 for Render health checks
    port = int(os.getenv('PORT', '10000'))
    logging.info(f"🌐 Starting Flask health check server on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)

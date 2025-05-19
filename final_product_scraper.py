#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FINAL VERSION: 1688.com and Taobao.com Product Scraper for WooCommerce
Fully automated scraping with captcha bypass and translation support.
"""

import time
import os
import re
import json
import uuid
import random
import requests
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.chrome import ChromeDriverManager
from fake_useragent import UserAgent
from anticaptchaofficial.recaptchav2proxyless import *
from anticaptchaofficial.recaptchav3proxyless import *
from anticaptchaofficial.hcaptchaproxyless import *
import cloudscraper
from bs4 import BeautifulSoup
import translators as ts
from PIL import Image
import io
import hashlib
import pickle
import logging
from datetime import datetime
import concurrent.futures
import queue
import threading

# Create necessary directories
os.makedirs('product_images', exist_ok=True)
os.makedirs('cookies', exist_ok=True)
os.makedirs('logs', exist_ok=True)

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'logs/scraper_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def log(message):
    """Enhanced logging function"""
    logger.info(message)
    print(f"[LOG] {message}")

class FinalProductScraper:
    def __init__(self):
        # Set up Chrome options
        chrome_options = Options()
        
        # Essential options
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--start-maximized")
        
        # Anti-detection options
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        # Random user agent
        ua = UserAgent()
        chrome_options.add_argument(f"user-agent={ua.random}")
        
        # User data directory for session persistence
        user_data_dir = os.path.join(os.getcwd(), "chrome_user_data")
        os.makedirs(user_data_dir, exist_ok=True)
        chrome_options.add_argument(f"--user-data-dir={user_data_dir}")
        
        # Initialize WebDriver
        log("Starting Chrome WebDriver...")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        
        # Apply stealth JS
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """
        })
        
        # Initialize cloudscraper for bypassing cloudflare
        self.scraper = cloudscraper.create_scraper(
            browser={
                'browser': 'chrome',
                'platform': 'windows',
                'mobile': False
            }
        )
        
        # Product data storage
        self.products = []
        self.image_hashes = set()  # For duplicate image detection
        
        # Translation function - load lazily
        self.translator = None
        
        # Initialize captcha solver
        self.captcha_solver = None
        self.init_captcha_solver()
        
        # Load cookies if available
        self.load_cookies()
        
        # Initialize thread-safe queue for concurrent processing
        self.product_queue = queue.Queue()
        self.max_workers = 3  # Number of concurrent workers
    
    def init_captcha_solver(self):
        """Initialize captcha solver with API key"""
        try:
            # You can set your API key here or load from environment variable
            api_key = os.getenv('ANTICAPTCHA_KEY', '')
            if api_key:
                self.captcha_solver = {
                    'recaptcha_v2': recaptchaV2Proxyless(api_key),
                    'recaptcha_v3': recaptchaV3Proxyless(api_key),
                    'hcaptcha': hCaptchaProxyless(api_key)
                }
                log("Captcha solver initialized")
            else:
                log("No captcha solver API key found")
        except Exception as e:
            log(f"Error initializing captcha solver: {e}")
    
    def load_cookies(self):
        """Load cookies for both sites"""
        try:
            # Load 1688 cookies
            cookie_file = os.path.join('cookies', '1688_cookies.pkl')
            if os.path.exists(cookie_file):
                with open(cookie_file, 'rb') as f:
                    cookies = pickle.load(f)
                    for cookie in cookies:
                        self.driver.add_cookie(cookie)
                log("Loaded 1688 cookies")
            
            # Load Taobao cookies
            cookie_file = os.path.join('cookies', 'taobao_cookies.pkl')
            if os.path.exists(cookie_file):
                with open(cookie_file, 'rb') as f:
                    cookies = pickle.load(f)
                    for cookie in cookies:
                        self.driver.add_cookie(cookie)
                log("Loaded Taobao cookies")
        except Exception as e:
            log(f"Error loading cookies: {e}")
    
    def save_cookies(self, site):
        """Save cookies for the specified site"""
        try:
            cookies = self.driver.get_cookies()
            cookie_file = os.path.join('cookies', f'{site}_cookies.pkl')
            with open(cookie_file, 'wb') as f:
                pickle.dump(cookies, f)
            log(f"Saved {site} cookies")
        except Exception as e:
            log(f"Error saving cookies: {e}")
    
    def get_translator(self):
        """Initialize translator on first use"""
        if not self.translator:
            try:
                import translators as ts
                self.translator = ts
                log("Translator initialized")
            except Exception as e:
                log(f"Could not initialize translator: {e}")
                self.translator = None
        return self.translator
    
    def translate_text(self, text):
        """Translate Chinese text to English with fallbacks"""
        if not text or text == "N/A":
            return text
            
        ts = self.get_translator()
        if not ts:
            return text  # Return original if translator not available
            
        try:
            # Try multiple services in case one fails
            try:
                return ts.google(text, from_language='zh', to_language='en')
            except:
                try:
                    return ts.bing(text, from_language='zh', to_language='en')
                except:
                    try:
                        return ts.translate_text(text, from_language='zh', to_language='en')
                    except:
                        return text  # Return original text if all translation methods fail
        except Exception as e:
            log(f"Translation error: {e}")
            return text
    
    def download_image(self, image_url, product_name):
        """Download an image and return the local path"""
        try:
            if not image_url:
                return None
                
            # Clean the URL
            if not image_url.startswith(('http://', 'https://')):
                if image_url.startswith('//'):
                    image_url = 'https:' + image_url
                else:
                    image_url = 'https://' + image_url
            
            # Create a safe filename
            safe_name = re.sub(r'[^\w\s-]', '', product_name).strip().replace(' ', '_')
            if not safe_name:
                safe_name = 'product'
                
            unique_id = str(uuid.uuid4())[:8]
            
            # Get file extension (default to jpg)
            file_ext = '.jpg'
            if '.' in image_url.split('?')[0].split('/')[-1]:
                ext = image_url.split('?')[0].split('/')[-1].split('.')[-1].lower()
                if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                    file_ext = '.' + ext
            
            # Create local filename
            filename = f"{safe_name}_{unique_id}{file_ext}"
            local_path = os.path.join('product_images', filename)
            
            # Download with headers to avoid blocking
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                'Referer': 'https://www.1688.com/',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive'
            }
            
            response = requests.get(image_url, headers=headers, timeout=15, stream=True)
            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                        
                log(f"Downloaded image: {local_path}")
                return local_path
            else:
                log(f"Failed to download image. Status: {response.status_code}")
                return None
        except Exception as e:
            log(f"Error downloading image: {e}")
            return None
    
    def handle_login(self):
        """Enhanced login handling with automatic captcha solving"""
        try:
            # Check if we're on a login page
            if any(text in self.driver.page_source.lower() for text in 
                   ["login", "sign in", "登录", "登入", "验证", "verify"]):
                log("Login/verify screen detected")
                
                # Try to solve any captchas
                self.solve_captchas()
                
                # Try guest options first
                guest_selectors = [
                    'a[href*="guest"]', 'a[href*="visitor"]', 
                    'a:contains("guest")', 'a:contains("visitor")',
                    'a:contains("continue")', 'button:contains("continue")'
                ]
                
                for selector in guest_selectors:
                    try:
                        elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                        if elements:
                            elements[0].click()
                            log("Clicked guest/visitor link")
                            time.sleep(2)
                            return
                    except:
                        pass
                
                # If no guest option, try to use saved cookies
                if self.driver.get_cookies():
                    log("Using saved cookies for authentication")
                    return
                
                # If still on login page, try to solve any remaining captchas
                self.solve_captchas()
                
                # Wait for successful login
                time.sleep(5)
                
                # Save cookies after successful login
                if "1688.com" in self.driver.current_url:
                    self.save_cookies("1688")
                elif "taobao.com" in self.driver.current_url:
                    self.save_cookies("taobao")
                
        except Exception as e:
            log(f"Error in login handling: {e}")
    
    def solve_captchas(self):
        """Solve various types of captchas"""
        try:
            # Check for reCAPTCHA v2
            if self.driver.find_elements(By.CSS_SELECTOR, '.g-recaptcha'):
                if self.captcha_solver and 'recaptcha_v2' in self.captcha_solver:
                    site_key = self.driver.find_element(By.CSS_SELECTOR, '.g-recaptcha').get_attribute('data-sitekey')
                    response = self.captcha_solver['recaptcha_v2'].solve_and_return_solution(site_key)
                    if response:
                        self.driver.execute_script(
                            f'document.getElementById("g-recaptcha-response").innerHTML="{response}";'
                        )
                        log("Solved reCAPTCHA v2")
            
            # Check for reCAPTCHA v3
            if self.driver.find_elements(By.CSS_SELECTOR, '[data-sitekey]'):
                if self.captcha_solver and 'recaptcha_v3' in self.captcha_solver:
                    site_key = self.driver.find_element(By.CSS_SELECTOR, '[data-sitekey]').get_attribute('data-sitekey')
                    response = self.captcha_solver['recaptcha_v3'].solve_and_return_solution(site_key)
                    if response:
                        self.driver.execute_script(
                            f'document.getElementById("g-recaptcha-response").innerHTML="{response}";'
                        )
                        log("Solved reCAPTCHA v3")
            
            # Check for hCaptcha
            if self.driver.find_elements(By.CSS_SELECTOR, '.h-captcha'):
                if self.captcha_solver and 'hcaptcha' in self.captcha_solver:
                    site_key = self.driver.find_element(By.CSS_SELECTOR, '.h-captcha').get_attribute('data-sitekey')
                    response = self.captcha_solver['hcaptcha'].solve_and_return_solution(site_key)
                    if response:
                        self.driver.execute_script(
                            f'document.getElementById("h-captcha-response").innerHTML="{response}";'
                        )
                        log("Solved hCaptcha")
            
            # Check for slider captchas
            slider_selectors = [
                '.nc_iconfont.btn_slide',
                '.nc-lang-cnt',
                '.yidun_slider'
            ]
            
            for selector in slider_selectors:
                if self.driver.find_elements(By.CSS_SELECTOR, selector):
                    try:
                        slider = self.driver.find_element(By.CSS_SELECTOR, selector)
                        action = webdriver.ActionChains(self.driver)
                        action.click_and_hold(slider)
                        action.move_by_offset(300, 0)  # Move slider to the right
                        action.release()
                        action.perform()
                        log("Solved slider captcha")
                        time.sleep(2)
                    except:
                        pass
            
        except Exception as e:
            log(f"Error solving captchas: {e}")
    
    def handle_cloudflare(self):
        """Handle Cloudflare protection"""
        try:
            if "cloudflare" in self.driver.page_source.lower():
                log("Cloudflare detected, attempting to bypass...")
                
                # Use cloudscraper to get the page
                response = self.scraper.get(self.driver.current_url)
                
                # Update cookies
                for cookie in self.scraper.cookies:
                    self.driver.add_cookie(cookie)
                
                # Refresh the page
                self.driver.refresh()
                time.sleep(5)
                
                log("Cloudflare bypass attempted")
        except Exception as e:
            log(f"Error handling Cloudflare: {e}")
    
    def extract_json_data(self, page_source):
        """Try to extract structured product data from JSON in page source"""
        try:
            # Look for common JSON data patterns
            json_patterns = [
                r'window\.__INIT_DATA__\s*=\s*({.*?});',
                r'var offer\s*=\s*({.*?});',
                r'window\.__GLOBAL_DATA\s*=\s*({.*?});',
                r'"offerData"\s*:\s*({.*?}),'
            ]
            
            for pattern in json_patterns:
                matches = re.search(pattern, page_source, re.DOTALL)
                if matches:
                    try:
                        data = json.loads(matches.group(1))
                        log("Found JSON data in page source")
                        return data
                    except:
                        pass
            
            # Try to find any JSON object that contains product info
            json_obj_pattern = r'{[^{]*?"product(?:Name|Title|Info)"[^}]*?}'
            matches = re.search(json_obj_pattern, page_source, re.DOTALL)
            if matches:
                try:
                    data = json.loads(matches.group(0))
                    log("Found product JSON object")
                    return data
                except:
                    pass
                    
            return None
        except Exception as e:
            log(f"Error extracting JSON data: {e}")
            return None
    
    def extract_product_name(self):
        """Extract product name using multiple methods"""
        name = "N/A"
        
        try:
            # Method 1: Try direct selectors
            selectors = [
                'h1.d-title', '.title-text', 'h1.title', 
                '.offer-title', 'h1', '.product-title',
                '[class*="title"]'
            ]
            
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    if text and len(text) > 3:
                        name = text
                        log(f"Found product name via selector: {name}")
                        return name
            
            # Method 2: Page title
            title = self.driver.title
            if title and len(title) > 3:
                # Remove site name if present
                if "-" in title:
                    name = title.split("-")[0].strip()
                else:
                    name = title.strip()
                log(f"Found product name from page title: {name}")
                return name
            
            # Method 3: Meta tags
            meta_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                'meta[property="og:title"], meta[name="title"]')
            
            for element in meta_elements:
                content = element.get_attribute('content')
                if content and len(content) > 3:
                    name = content
                    log(f"Found product name from meta tag: {name}")
                    return name
            
            # Method 4: JSON data
            page_source = self.driver.page_source
            json_data = self.extract_json_data(page_source)
            
            if json_data:
                # Look for name in common JSON structures
                for key in ['subject', 'title', 'productName', 'name', 'offerTitle']:
                    if key in json_data and json_data[key]:
                        name = str(json_data[key])
                        log(f"Found product name from JSON data: {name}")
                        return name
            
            # Method 5: Direct regex on page source
            title_patterns = [
                r'<title>(.*?)[<\-]',
                r'"title"\s*:\s*"(.*?)"',
                r'"subject"\s*:\s*"(.*?)"',
                r'"productName"\s*:\s*"(.*?)"'
            ]
            
            for pattern in title_patterns:
                match = re.search(pattern, page_source)
                if match:
                    name = match.group(1).strip()
                    if name and len(name) > 3:
                        log(f"Found product name via regex: {name}")
                        return name
            
            return name
        except Exception as e:
            log(f"Error extracting product name: {e}")
            return name
    
    def extract_price(self):
        """Extract product price using multiple methods"""
        price = "N/A"
        
        try:
            # Method 1: Direct selectors
            selectors = [
                '.price', '.price-text', '.price-value', 
                '.price-now', '[class*="price"]', '[id*="price"]'
            ]
            
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    if text:
                        # Extract numbers from price text
                        price_match = re.search(r'[\d,.]+', text)
                        if price_match:
                            price = price_match.group(0)
                            log(f"Found price via selector: {price}")
                            return price
            
            # Method 2: JSON data
            page_source = self.driver.page_source
            json_data = self.extract_json_data(page_source)
            
            if json_data:
                # Look for price in common JSON structures
                for key in ['price', 'priceDisplay', 'offerPrice', 'retailPrice']:
                    if key in json_data:
                        try:
                            price = str(json_data[key])
                            log(f"Found price from JSON data: {price}")
                            return price
                        except:
                            pass
            
            # Method 3: Direct regex on page source
            price_patterns = [
                r'"price":\s*"?([\d.]+)"?',
                r'"priceText":\s*"?([\d.]+)"?',
                r'"current(?:Price|price)":\s*"?([\d.]+)"?',
                r'"retailPrice":\s*"?([\d.]+)"?'
            ]
            
            for pattern in price_patterns:
                match = re.search(pattern, page_source)
                if match:
                    price = match.group(1)
                    log(f"Found price via regex: {price}")
                    return price
            
            return price
        except Exception as e:
            log(f"Error extracting price: {e}")
            return price
    
    def extract_description(self):
        """Extract product description using multiple methods"""
        description = "N/A"
        
        try:
            # Method 1: Direct selectors
            selectors = [
                '.description', '.detail-content', '.product-description',
                '#description', '#detail', '#product-info',
                '[class*="description"]', '[class*="detail-content"]'
            ]
            
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    if text and len(text) > 15:  # Substantial content
                        description = text
                        log(f"Found description via selector (length: {len(description)})")
                        return description
            
            # Method 2: Description tab
            tab_selectors = [
                '.tab-trigger', '.tab-item', '[role="tab"]',
                '[class*="tab"]', '[data-tab]'
            ]
            
            for selector in tab_selectors:
                tabs = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for tab in tabs:
                    tab_text = tab.text.lower()
                    if any(word in tab_text for word in ['detail', 'description', '详情', '描述']):
                        try:
                            # Try to click the tab
                            tab.click()
                            time.sleep(2)
                            log("Clicked on description tab")
                            
                            # Look for content after clicking
                            for desc_selector in selectors:
                                elements = self.driver.find_elements(By.CSS_SELECTOR, desc_selector)
                                for element in elements:
                                    text = element.text.strip()
                                    if text and len(text) > 15:
                                        description = text
                                        log(f"Found description after clicking tab (length: {len(description)})")
                                        return description
                        except:
                            pass
            
            # Method 3: Meta description
            meta_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                'meta[name="description"], meta[property="og:description"]')
            
            for element in meta_elements:
                content = element.get_attribute('content')
                if content and len(content) > 15:
                    description = content
                    log(f"Found description from meta tag (length: {len(description)})")
                    return description
            
            # Method 4: JSON data
            page_source = self.driver.page_source
            json_data = self.extract_json_data(page_source)
            
            if json_data:
                # Look for description in common JSON structures
                for key in ['description', 'productDescription', 'detail', 'details']:
                    if key in json_data and json_data[key]:
                        try:
                            description = str(json_data[key])
                            log(f"Found description from JSON data (length: {len(description)})")
                            return description
                        except:
                            pass
            
            # Method 5: Looking for substantial paragraphs
            paragraphs = self.driver.find_elements(By.TAG_NAME, 'p')
            for p in paragraphs:
                text = p.text.strip()
                if text and len(text) > 30:  # Substantial paragraph
                    description = text
                    log(f"Found description from paragraph (length: {len(description)})")
                    return description
            
            # Method 6: Direct regex on page source
            desc_patterns = [
                r'"description"\s*:\s*"(.*?)"',
                r'"productDescription"\s*:\s*"(.*?)"',
                r'<meta\s+name="description"\s+content="([^"]+)"'
            ]
            
            for pattern in desc_patterns:
                match = re.search(pattern, page_source)
                if match:
                    description = match.group(1)
                    if description and len(description) > 15:
                        log(f"Found description via regex (length: {len(description)})")
                        return description
            
            return description
        except Exception as e:
            log(f"Error extracting description: {e}")
            return description
    
    def extract_images(self):
        """Extract product images using multiple methods"""
        images = []
        
        try:
            # Method 1: Direct image elements
            selectors = [
                '.detail-gallery img', '.tab-trigger img',
                '[class*="gallery"] img', '[class*="image"] img',
                'img[src*=".jpg"], img[src*=".png"]',
                'img:not([width="1"]):not([height="1"])'  # Larger images
            ]
            
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                
                for element in elements:
                    # Try multiple image attributes
                    for attr in ['src', 'data-src', 'data-lazy-src', 'data-original']:
                        src = element.get_attribute(attr)
                        
                        if src and (src.startswith('http') or src.startswith('//')):
                            # Check dimensions if available
                            try:
                                width = element.get_attribute('width')
                                height = element.get_attribute('height')
                                
                                if width and height:
                                    if int(width) < 50 or int(height) < 50:
                                        continue  # Skip tiny images
                            except:
                                pass
                            
                            # Fix protocol-relative URLs
                            if src.startswith('//'):
                                src = 'https:' + src
                            
                            # Add if not already in list
                            if src not in images:
                                images.append(src)
                                log(f"Found image: {src}")
                            
                            break  # Break after finding a valid attribute
                
                if len(images) >= 3:  # Stop after finding a few images
                    break
            
            # Method 2: JSON data extraction
            if not images:
                page_source = self.driver.page_source
                
                # Look for image URLs in JSON patterns
                image_patterns = [
                    r'"imageUrl":\s*"(https?:[^"]+)"',
                    r'"imageUrl":\s*"(/[^"]+)"',
                    r'"imageUrl":\s*"(//[^"]+)"',
                    r'"image":\s*"(https?:[^"]+)"',
                    r'"image":\s*"(/[^"]+)"',
                    r'"image":\s*"(//[^"]+)"'
                ]
                
                for pattern in image_patterns:
                    matches = re.findall(pattern, page_source)
                    for match in matches:
                        # Fix URLs
                        if match.startswith('//'):
                            url = 'https:' + match
                        elif match.startswith('/'):
                            url = 'https://www.1688.com' + match
                        else:
                            url = match
                        
                        if url not in images:
                            images.append(url)
                            log(f"Found image from JSON: {url}")
                
                if images:
                    log(f"Found {len(images)} images from JSON patterns")
            
            # Method 3: Attribute-based search using JavaScript
            if not images or len(images) < 2:
                # Use JS to find all elements with src or data-src attributes that look like images
                js_script = """
                    let images = [];
                    // Find all elements with image-like attributes
                    document.querySelectorAll('[src*=".jpg"],[src*=".png"],[src*=".jpeg"],[data-src*=".jpg"],[data-src*=".png"],[data-src*=".jpeg"]').forEach(el => {
                        let src = el.getAttribute('src') || el.getAttribute('data-src');
                        if (src && !images.includes(src)) {
                            images.push(src);
                        }
                    });
                    return images;
                """
                
                try:
                    js_images = self.driver.execute_script(js_script)
                    if js_images:
                        for img_src in js_images:
                            if img_src and (img_src.startswith('http') or img_src.startswith('//')):
                                # Fix protocol-relative URLs
                                if img_src.startswith('//'):
                                    img_src = 'https:' + img_src
                                
                                if img_src not in images:
                                    images.append(img_src)
                                    log(f"Found image via JavaScript: {img_src}")
                    
                    if images:
                        log(f"Found {len(images)} images via JavaScript")
                except Exception as js_err:
                    log(f"Error in JavaScript image extraction: {js_err}")
            
            return images
        except Exception as e:
            log(f"Error extracting images: {e}")
            return images
    
    def scrape_product(self, url):
        """Enhanced product scraping with support for both 1688 and Taobao"""
        try:
            log(f"Processing URL: {url}")
            
            # Load the page
            self.driver.get(url)
            time.sleep(5)  # Wait for initial load
            
            # Handle Cloudflare if present
            self.handle_cloudflare()
            
            # Handle login if needed
            self.handle_login()
            
            # Scroll to load all content
            self.driver.execute_script("window.scrollTo(0, 0);")  # Start at top
            time.sleep(1)
            
            # Scroll down gradually
            total_height = self.driver.execute_script("return document.body.scrollHeight")
            for i in range(0, total_height, 300):
                self.driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.2)
            
            # Go back to top
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            
            # Extract product data
            name = self.extract_product_name()
            price = self.extract_price()
            description = self.extract_description()
            image_urls = self.extract_images()
            variations = self.extract_variations()
            shipping_info = self.extract_shipping_info()
            seller_info = self.extract_seller_info()
            
            # Translate to English
            log("Translating product data...")
            
            name_en = name
            if name != "N/A":
                name_en = self.translate_text(name)
                log(f"Translated name: {name_en}")
            
            description_en = description
            if description != "N/A":
                description_en = self.translate_text(description)
                log(f"Translated description (length: {len(description_en)})")
            
            # Download images (skip duplicates)
            local_image_paths = []
            if image_urls:
                log(f"Downloading {len(image_urls)} images...")
                
                for img_url in image_urls:
                    if not self.is_duplicate_image(img_url):
                        local_path = self.download_image(img_url, name_en)
                        if local_path:
                            local_image_paths.append(local_path)
            
            # Create short description for WooCommerce
            short_description = description_en
            if len(short_description) > 150:
                short_description = short_description[:147] + "..."
            
            # Generate SKU
            sku = f"IMP-{str(uuid.uuid4())[:8]}"
            
            # Format variations for WooCommerce
            variation_data = []
            if variations:
                for var in variations:
                    variation_data.append(f"{var['name']}: {var['value']}")
            
            # Format shipping info
            shipping_text = []
            for key, value in shipping_info.items():
                shipping_text.append(f"{key}: {value}")
            
            # Format seller info
            seller_text = []
            for key, value in seller_info.items():
                seller_text.append(f"{key}: {value}")
            
            # Create WooCommerce product data
            product_data = {
                'SKU': sku,
                'Name': name_en,
                'Regular price': price,
                'Description': description_en,
                'Short description': short_description,
                'Images': ','.join(local_image_paths),
                'In stock?': 1,
                'Type': 'variable' if variations else 'simple',
                'Categories': 'Imported Products',
                'Original URL': url,
                'Variations': '|'.join(variation_data) if variation_data else '',
                'Shipping Info': '|'.join(shipping_text) if shipping_text else '',
                'Seller Info': '|'.join(seller_text) if seller_text else ''
            }
            
            self.products.append(product_data)
            
            log(f"Successfully processed product: {name_en}")
            return True
            
        except Exception as e:
            log(f"Error processing product: {e}")
            return False
    
    def scrape_all_products(self, urls_file='urls.txt'):
        """Process all products from URLs file with concurrent processing"""
        # Clear existing products
        self.products = []
        
        # Check if file exists
        if not os.path.exists(urls_file):
            log(f"URLs file not found: {urls_file}")
            
            # Create sample file
            with open(urls_file, 'w', encoding='utf-8') as f:
                f.write("https://detail.1688.com/offer/653499140995.html\n")
                f.write("https://detail.1688.com/offer/636312391325.html\n")
                f.write("https://item.taobao.com/item.htm?id=123456789\n")
            
            log(f"Created sample URLs file: {urls_file}")
        
        # Read URLs
        with open(urls_file, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]
        
        if not urls:
            log("No URLs found in file!")
            return False
        
        log(f"Found {len(urls)} URLs to process")
        
        # First visit homepage to handle login
        try:
            log("Visiting homepage first...")
            self.driver.get("https://www.1688.com/")
            time.sleep(5)
            self.handle_login()
            
            # Also visit Taobao
            self.driver.get("https://www.taobao.com/")
            time.sleep(5)
            self.handle_login()
        except Exception as e:
            log(f"Error visiting homepages: {e}")
        
        # Process URLs concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = []
            for url in urls:
                if not url.startswith('http'):
                    log(f"Skipping invalid URL: {url}")
                    continue
                
                # Add to queue
                self.product_queue.put(url)
                
                # Submit task
                future = executor.submit(self.scrape_product, url)
                futures.append(future)
            
            # Wait for all tasks to complete
            for future in concurrent.futures.as_completed(futures):
                try:
                    success = future.result()
                    if not success:
                        log("Failed to process a product")
                except Exception as e:
                    log(f"Error in concurrent processing: {e}")
        
        # Save results to CSV
        if self.products:
            df = pd.DataFrame(self.products)
            csv_file = 'woocommerce_products.csv'
            df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            log(f"Saved {len(self.products)} products to {csv_file}")
            return True
        else:
            log("No products were successfully scraped!")
            return False
    
    def close(self):
        """Close the WebDriver"""
        try:
            self.driver.quit()
            log("WebDriver closed")
        except:
            pass
    
    def extract_variations(self):
        """Extract product variations (size, color, etc.)"""
        variations = []
        try:
            # Common variation selectors
            selectors = [
                '.sku-property', '.sku-item', '.sku-select',
                '.product-sku', '.sku-list', '.sku-property-item'
            ]
            
            for selector in selectors:
                elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    for element in elements:
                        try:
                            # Get variation name
                            name = element.get_attribute('title') or element.text
                            if name:
                                # Get variation value
                                value = element.get_attribute('data-value') or element.get_attribute('value')
                                if value:
                                    variations.append({
                                        'name': self.translate_text(name),
                                        'value': self.translate_text(value)
                                    })
                        except:
                            continue
            
            # Try to find variations in JSON data
            if not variations:
                json_data = self.extract_json_data(self.driver.page_source)
                if json_data:
                    # Look for common variation patterns
                    for key in ['skuProps', 'skuList', 'variations', 'properties']:
                        if key in json_data:
                            try:
                                props = json_data[key]
                                if isinstance(props, list):
                                    for prop in props:
                                        if isinstance(prop, dict):
                                            name = prop.get('name', '')
                                            value = prop.get('value', '')
                                            if name and value:
                                                variations.append({
                                                    'name': self.translate_text(name),
                                                    'value': self.translate_text(value)
                                                })
                            except:
                                continue
            
            return variations
        except Exception as e:
            log(f"Error extracting variations: {e}")
            return variations
    
    def extract_shipping_info(self):
        """Extract shipping information"""
        shipping_info = {}
        try:
            # Common shipping selectors
            selectors = {
                'shipping_fee': ['.shipping-fee', '.logistics-fee', '.delivery-fee'],
                'shipping_time': ['.shipping-time', '.delivery-time', '.logistics-time'],
                'shipping_method': ['.shipping-method', '.delivery-method', '.logistics-method']
            }
            
            for key, selector_list in selectors.items():
                for selector in selector_list:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        text = elements[0].text.strip()
                        if text:
                            shipping_info[key] = self.translate_text(text)
                            break
            
            # Try to find shipping info in JSON data
            if not shipping_info:
                json_data = self.extract_json_data(self.driver.page_source)
                if json_data:
                    # Look for common shipping patterns
                    for key in ['shipping', 'logistics', 'delivery']:
                        if key in json_data:
                            try:
                                info = json_data[key]
                                if isinstance(info, dict):
                                    for k, v in info.items():
                                        if isinstance(v, (str, int, float)):
                                            shipping_info[k] = self.translate_text(str(v))
                            except:
                                continue
            
            return shipping_info
        except Exception as e:
            log(f"Error extracting shipping info: {e}")
            return shipping_info
    
    def extract_seller_info(self):
        """Extract seller information"""
        seller_info = {}
        try:
            # Common seller selectors
            selectors = {
                'name': ['.seller-name', '.shop-name', '.store-name'],
                'rating': ['.seller-rating', '.shop-rating', '.store-rating'],
                'location': ['.seller-location', '.shop-location', '.store-location'],
                'response_rate': ['.response-rate', '.reply-rate'],
                'response_time': ['.response-time', '.reply-time']
            }
            
            for key, selector_list in selectors.items():
                for selector in selector_list:
                    elements = self.driver.find_elements(By.CSS_SELECTOR, selector)
                    if elements:
                        text = elements[0].text.strip()
                        if text:
                            seller_info[key] = self.translate_text(text)
                            break
            
            # Try to find seller info in JSON data
            if not seller_info:
                json_data = self.extract_json_data(self.driver.page_source)
                if json_data:
                    # Look for common seller patterns
                    for key in ['seller', 'shop', 'store']:
                        if key in json_data:
                            try:
                                info = json_data[key]
                                if isinstance(info, dict):
                                    for k, v in info.items():
                                        if isinstance(v, (str, int, float)):
                                            seller_info[k] = self.translate_text(str(v))
                            except:
                                continue
            
            return seller_info
        except Exception as e:
            log(f"Error extracting seller info: {e}")
            return seller_info
    
    def is_duplicate_image(self, image_url):
        """Check if an image is a duplicate using content hash"""
        try:
            # Download image content
            response = requests.get(image_url, timeout=10)
            if response.status_code == 200:
                # Calculate image hash
                image_hash = hashlib.md5(response.content).hexdigest()
                
                # Check if hash exists
                if image_hash in self.image_hashes:
                    return True
                
                # Add hash to set
                self.image_hashes.add(image_hash)
                return False
        except:
            pass
        return False

# Main execution
if __name__ == "__main__":
    print("=" * 70)
    print("FINAL VERSION: 1688.com and Taobao.com Product Scraper for WooCommerce")
    print("=" * 70)
    print("\nThis script will automatically:")
    print("1. Handle login and captchas")
    print("2. Scrape product data from both 1688.com and Taobao.com")
    print("3. Translate Chinese text to English")
    print("4. Download and deduplicate images")
    print("5. Save results in WooCommerce-compatible format\n")
    
    scraper = FinalProductScraper()
    
    try:
        success = scraper.scrape_all_products()
        
        if success:
            print("\nScraping completed successfully!")
            print("Results saved to woocommerce_products.csv")
            print("Product images saved to product_images folder")
            print("Logs saved to logs folder")
        else:
            print("\nScraping completed with issues.")
            print("Check logs folder for details")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
    finally:
        scraper.close()
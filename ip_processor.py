
import re
import requests
import logging
from typing import Dict, List, Any

class IPProcessor:
    def __init__(self):
        self.logger = logging.getLogger('ip_processor')
        
        # تعریف پرچم کشورهای مختلف
        self.country_flags = {
            "Qatar": "🇶🇦",
            "UAE": "🇦🇪",
            "United Arab Emirates": "🇦🇪",
            "Saudi Arabia": "🇸🇦",
            "Iran": "🇮🇷",
            "Iraq": "🇮🇶",
            "Kuwait": "🇰🇼",
            "Bahrain": "🇧🇭",
            "Oman": "🇴🇲",
            "Egypt": "🇪🇬",
            "Turkey": "🇹🇷",
            "Russia": "🇷🇺",
            "United States": "🇺🇸",
            "USA": "🇺🇸",
            "Germany": "🇩🇪",
            "United Kingdom": "🇬🇧",
            "UK": "🇬🇧",
            "France": "🇫🇷",
            "China": "🇨🇳",
            "India": "🇮🇳",
            "Japan": "🇯🇵",
            "Canada": "🇨🇦",
            "Pakistan": "🇵🇰",
            "Afghanistan": "🇦🇫",
            "Armenia": "🇦🇲",
            "Azerbaijan": "🇦🇿",
            "Bangladesh": "🇧🇩",
            "Belarus": "🇧🇾",
            "Belgium": "🇧🇪",
            "Brazil": "🇧🇷",
            "Italy": "🇮🇹",
            "Spain": "🇪🇸",
            "Australia": "🇦🇺",
            "New Zealand": "🇳🇿",
            "South Korea": "🇰🇷",
            "North Korea": "🇰🇵",
            "Vietnam": "🇻🇳",
            "Thailand": "🇹🇭",
            "Indonesia": "🇮🇩",
            "Malaysia": "🇲🇾",
            "Singapore": "🇸🇬",
            "Philippines": "🇵🇭",
            "Israel": "🇮🇱",
            "Palestine": "🇵🇸",
            "Syria": "🇸🇾",
            "Lebanon": "🇱🇧",
            "Jordan": "🇯🇴",
            "Yemen": "🇾🇪",
            "Algeria": "🇩🇿",
            "Morocco": "🇲🇦",
            "Tunisia": "🇹🇳",
            "Libya": "🇱🇾",
            "Sudan": "🇸🇩",
            "South Sudan": "🇸🇸",
            "Ethiopia": "🇪🇹",
            "Kenya": "🇰🇪",
            "Nigeria": "🇳🇬",
            "South Africa": "🇿🇦",
            "Mexico": "🇲🇽",
            "Argentina": "🇦🇷",
            "Chile": "🇨🇱",
            "Colombia": "🇨🇴",
            "Peru": "🇵🇪",
            "Venezuela": "🇻🇪",
            "Netherlands": "🇳🇱",
            "Sweden": "🇸🇪",
            "Norway": "🇳🇴",
            "Finland": "🇫🇮",
            "Denmark": "🇩🇰",
            "Switzerland": "🇨🇭",
            "Austria": "🇦🇹",
            "Greece": "🇬🇷",
            "Poland": "🇵🇱",
            "Czech Republic": "🇨🇿",
            "Hungary": "🇭🇺",
            "Romania": "🇷🇴",
            "Bulgaria": "🇧🇬",
            "Ukraine": "🇺🇦",
            "Kazakhstan": "🇰🇿",
            "Uzbekistan": "🇺🇿",
            "Tajikistan": "🇹🇯",
            "Turkmenistan": "🇹🇲",
            "Kyrgyzstan": "🇰🇬",
            "Croatia": "🇭🇷",
            "Serbia": "🇷🇸",
            "Portugal": "🇵🇹",
            "Ireland": "🇮🇪",
            "New Zealand": "🇳🇿",
            "Costa Rica": "🇨🇷",
            "Panama": "🇵🇦",
            "Dominican Republic": "🇩🇴",
            "Jamaica": "🇯🇲",
            "Cuba": "🇨🇺",
            "Iceland": "🇮🇸",
            "Taiwan": "🇹🇼",
            "Hong Kong": "🇭🇰",
            "Macao": "🇲🇴",
            "Mongolia": "🇲🇳",
            "Myanmar": "🇲🇲",
            "Cambodia": "🇰🇭",
            "Laos": "🇱🇦",
            "Nepal": "🇳🇵",
            "Sri Lanka": "🇱🇰",
            "Maldives": "🇲🇻",
            "Luxembourg": "🇱🇺",
            "Slovenia": "🇸🇮",
            "Bosnia and Herzegovina": "🇧🇦",
            "Moldova": "🇲🇩",
            "Monaco": "🇲🇨",
            "Vatican City": "🇻🇦",
            "San Marino": "🇸🇲",
            "Albania": "🇦🇱"
        }
        
        # لیست کشورهایی که نیاز به اصلاح نام دارند
        self.country_name_fixes = {
            "UAE": "United Arab Emirates",
            "USA": "United States",
            "UK": "United Kingdom",
        }
    
    def get_flag_for_country(self, country_name: str) -> str:
        """دریافت پرچم برای کشور"""
        # ابتدا بررسی می‌کنیم که آیا پرچم در لیست آماده موجود است
        if country_name in self.country_flags:
            return self.country_flags[country_name]
            
        # اگر در لیست نبود، از کد کشور برای ساخت پرچم استفاده می‌کنیم
        # ابتدا سعی می‌کنیم با استفاده از API کد کشور را پیدا کنیم
        try:
            response = requests.get(f"https://restcountries.com/v3.1/name/{country_name}?fields=cca2")
            if response.status_code == 200:
                data = response.json()
                if data and len(data) > 0:
                    country_code = data[0].get('cca2')
                    if country_code and len(country_code) == 2:
                        # تبدیل کد کشور به ایموجی پرچم
                        flag = ''.join(chr(ord(c) + 127397) for c in country_code.upper())
                        return flag
        except Exception as e:
            self.logger.warning(f"خطا در دریافت کد کشور برای {country_name}: {e}")
        
        # اگر نتوانستیم پرچم را پیدا کنیم، پرچم خنثی برمی‌گردانیم
        return "🏳️"
    
    def get_country_name(self, ip_address: str) -> tuple:
        """دریافت اطلاعات کشور برای یک آدرس IP"""
        try:
            # استفاده از API برای دریافت اطلاعات کشور
            response = requests.get(f"https://api.iplocation.net/?ip={ip_address}")
            if response.status_code == 200:
                data = response.json()
                country_name = data.get('country_name')
                
                # اصلاح نام کشور در صورت نیاز
                if country_name in self.country_name_fixes:
                    country_name = self.country_name_fixes[country_name]
                
                # دریافت پرچم کشور
                flag = self.get_flag_for_country(country_name)
                
                return country_name, flag
            else:
                return "Unknown", "🏳️"
        except Exception as e:
            self.logger.error(f"خطا در دریافت اطلاعات کشور برای IP {ip_address}: {e}")
            return "Unknown", "🏳️"
    
    def process_ip(self, ip_text: str) -> dict:
        """پردازش یک متن حاوی آدرس IP و استخراج اطلاعات آن"""
        # الگوی استخراج آدرس IP از متن
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        
        # جستجوی IP در متن
        match = re.search(ip_pattern, ip_text)
        if not match:
            return None
            
        ip_address = match.group(0)
        
        # دریافت اطلاعات کشور
        country_name, flag = self.get_country_name(ip_address)
        
        return {
            "ip": ip_address,
            "country": country_name,
            "flag": flag
        }
    
    def process_bulk_ips(self, text: str) -> Dict[str, List[Dict[str, Any]]]:
        """پردازش گروهی آدرس‌های IP از یک متن"""
        # الگوی استخراج آدرس IP از متن
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        
        # پیدا کردن همه آدرس‌های IP در متن
        ip_matches = re.finditer(ip_pattern, text)
        
        # دسته‌بندی بر اساس کشور
        country_ips = {}
        
        for match in ip_matches:
            ip_address = match.group(0)
            
            # دریافت اطلاعات کشور
            country_name, flag = self.get_country_name(ip_address)
            country_key = f"{flag} {country_name}"
            
            if country_key not in country_ips:
                country_ips[country_key] = []
                
            country_ips[country_key].append({
                "ip": ip_address,
                "country": country_name,
                "flag": flag
            })
        
        return country_ips

import re
import requests
import logging
from collections import defaultdict
from collections import defaultdict

class IPProcessor:
    def __init__(self):
        self.ip_validation_api = "https://api.iplocation.net/?ip="
        self.logger = logging.getLogger(__name__)

        # نقشه پرچم‌های خاص برای کشورهای مشکل‌دار
        self.special_flags = {
            "QA": "🇶🇦", "AE": "🇦🇪", "SA": "🇸🇦", "IR": "🇮🇷",
            "IQ": "🇮🇶", "KW": "🇰🇼", "BH": "🇧🇭", "OM": "🇴🇲",
            "EG": "🇪🇬", "TR": "🇹🇷", "RU": "🇷🇺", "US": "🇺🇸",
            "DE": "🇩🇪", "GB": "🇬🇧", "FR": "🇫🇷", "CN": "🇨🇳",
            "IN": "🇮🇳", "JP": "🇯🇵", "CA": "🇨🇦", "PK": "🇵🇰",
            "GE": "🇬🇪", # افزودن پرچم گرجستان
            "KSA": "🇸🇦"  # کد جایگزین برای عربستان 
        }

        # نگاشت کشورهای خاص
        self.special_country_codes = {
            "Qatar": "QA", "UAE": "AE", "United Arab Emirates": "AE",
            "Saudi Arabia": "SA", "Saudi": "SA", "KSA": "SA",
            "Iran": "IR", "Iraq": "IQ", "Kuwait": "KW", 
            "Bahrain": "BH", "Oman": "OM", "Egypt": "EG", 
            "Turkey": "TR", "Russia": "RU", "United States": "US", 
            "USA": "US", "Germany": "DE", "United Kingdom": "GB", 
            "UK": "GB", "France": "FR", "China": "CN", 
            "India": "IN", "Japan": "JP", "Canada": "CA", 
            "Pakistan": "PK", "Georgia": "GE"
        }

    def extract_ips(self, text):
        """استخراج تمام آدرس‌های IP از متن ورودی"""
        ip_pattern = r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
        return re.findall(ip_pattern, text)

    def get_country_info(self, ip_address):
        """دریافت اطلاعات کشور برای یک آدرس IP"""
        try:
            response = requests.get(f"{self.ip_validation_api}{ip_address}")
            if response.status_code == 200:
                data = response.json()
                country_name = data.get('country_name', 'نامشخص')
                country_code = data.get('country_code', '').upper()

                # جایگزینی کد کشور برای کشورهای خاص
                if country_name in self.special_country_codes:
                    country_code = self.special_country_codes[country_name]

                # دریافت پرچم
                flag = "🏳️"  # پرچم پیش‌فرض

                if country_code in self.special_flags:
                    flag = self.special_flags[country_code]
                elif country_code and len(country_code) == 2:
                    try:
                        # تبدیل کد کشور به پرچم
                        flag_chars = []
                        for c in country_code.upper():
                            if 'A' <= c <= 'Z':
                                flag_chars.append(chr(ord(c) + 127397))
                        if len(flag_chars) == 2:
                            flag = "".join(flag_chars)
                    except Exception as e:
                        self.logger.error(f"خطا در تولید پرچم: {e}")

                return {
                    "country_name": country_name,
                    "country_code": country_code,
                    "flag": flag,
                    "ip": ip_address
                }
        except Exception as e:
            self.logger.error(f"خطا در دریافت اطلاعات کشور برای IP {ip_address}: {e}")

        # در صورت بروز خطا یا عدم یافتن اطلاعات
        return {
            "country_name": "نامشخص",
            "country_code": "XX",
            "flag": "🏳️",
            "ip": ip_address
        }

    def extract_country_from_text(self, text, ip):
        """استخراج نام کشور و پرچم از متن ورودی"""
        # الگوی 1: [PING OK] 39.62.163.207 -> 🇵🇰 Pakistan
        if '->' in text:
            try:
                country_part = text.split('->')[1].strip()
                flag, country_name = country_part.strip().split(maxsplit=1)
                return {"country_name": country_name, "flag": flag, "ip": ip}
            except:
                pass

        # الگوی 2: New IP Found! IP: 188.210.21.97 Country: Germany
        country_pattern = r'[Cc]ountry:?\s*([A-Za-z\s]+)'
        country_match = re.search(country_pattern, text)
        if country_match:
            country_name = country_match.group(1).strip()

            # یافتن کد کشور و پرچم
            country_code = None
            for name, code in self.special_country_codes.items():
                if name.lower() in country_name.lower():
                    country_code = code
                    break

            flag = "🏳️"
            if country_code and country_code in self.special_flags:
                flag = self.special_flags[country_code]

            return {"country_name": country_name, "flag": flag, "ip": ip}

        # اگر هیچ کشوری یافت نشد، از API استفاده کنیم
        return self.get_country_info(ip)

    def process_bulk_ips(self, text):
        """پردازش گروهی آدرس‌های IP و گروه‌بندی بر اساس کشور"""
        ips = self.extract_ips(text)
        if not ips:
            return {}

        # تبدیل متن به خطوط برای بررسی هر خط
        lines = text.strip().split('\n')
        ip_data = {}

        # پردازش هر خط برای یافتن اطلاعات کشور همراه با IP
        for line in lines:
            line_ips = self.extract_ips(line)
            if line_ips:
                for ip in line_ips:
                    # بررسی این IP قبلاً پردازش نشده باشد
                    if ip not in ip_data:
                        country_info = self.extract_country_from_text(line, ip)
                        ip_data[ip] = country_info

        # برای IPهایی که هنوز اطلاعات کشورشان استخراج نشده، از API استفاده می‌کنیم
        processed_count = 0
        total_count = len(ips)

        for ip in ips:
            if ip not in ip_data:
                ip_data[ip] = self.get_country_info(ip)
                processed_count += 1
                # لاگ کردن پیشرفت پردازش برای تعداد زیاد IP
                if processed_count % 10 == 0 or processed_count == total_count:
                    self.logger.info(f"پردازش IP ها: {processed_count}/{total_count}")

        # نرمال‌سازی و تصحیح نام‌های کشورها
        normalized_data = {}
        for ip, data in ip_data.items():
            # تصحیح نام و کد کشورهای خاص
            country_name = data['country_name']
            country_code = data.get('country_code', '')

            # تصحیح عربستان سعودی - گسترش موارد شناسایی
            if (country_name.lower() in ['saudi', 'saudi arabia', 'ksa', 'kingdom of saudi arabia', 'عربستان', 'عربستان سعودی', 'سعودی'] 
                or 'saudi' in country_name.lower() 
                or 'عربستان' in country_name
                or (country_code and country_code.upper() in ['KSA', 'SAUDI', 'SA'])):

                country_name = 'Saudi Arabia'
                country_code = 'SA'
                data['flag'] = self.special_flags.get('SA', data['flag'])
                # Log for debugging
                self.logger.info(f"Saudi Arabia identified and standardized: {country_name}, {country_code}")

            # تصحیح گرجستان
            elif country_name.lower() in ['georgia', 'گرجستان']:
                country_name = 'Georgia'
                country_code = 'GE'
                data['flag'] = self.special_flags.get('GE', data['flag'])

            # تصحیح سایر موارد با استفاده از مپ کشورها
            elif country_name in self.special_country_codes:
                country_code = self.special_country_codes[country_name]
                data['flag'] = self.special_flags.get(country_code, data['flag'])

            # به‌روزرسانی داده‌ها
            data['country_name'] = country_name
            data['country_code'] = country_code
            normalized_data[ip] = data

        # گروه‌بندی IPها بر اساس کشور
        country_groups = defaultdict(list)
        for ip, data in normalized_data.items():
            country_key = f"{data['flag']} {data['country_name']}"
            country_groups[country_key].append(data)

        return country_groups
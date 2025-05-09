import pickle
from typing import Dict, Set, List, Tuple, Optional
from collections import defaultdict, deque
import time


import pickle
from typing import Dict, List, Tuple, Set
from collections import deque

class DBManager:

    def __init__(self):
        self.active_codes: Dict[str, Dict[str, any]] = {
        }  # code -> {type: str, tokens: int, used_count: int, created_at: time, users: list}
        self.active_users: Dict[int, Dict[str, any]] = {
        }  # user_id -> {type: str, tokens: int, joined_date: str, activation_code: str}
        self.ipv4_data: Dict[str, Tuple[str, str, List[str]]] = {
        }  # country_code -> (name, flag, [ips])
        self.disabled_users: Set[int] = set()  # مجموعه کاربران غیرفعال
        self.disabled_locations: Dict[str, bool] = {}  # کشورهای غیرفعال شده
        self.wg_endpoints: list = []
        self.last_added_ips = deque(maxlen=20)  # آخرین IPهای اضافه شده
        self.load_database()

    def load_database(self):
        try:
            with open('bot_database.pkl', 'rb') as f:
                data = pickle.load(f)
                self.active_codes = data.get('active_codes', {})
                self.active_users = data.get('active_users', {})
                self.ipv4_data = data.get('ipv4_data', {})
                self.disabled_users = data.get('disabled_users', set())
                self.disabled_locations = data.get('disabled_locations', {})
                self.wg_endpoints = data.get('wg_endpoints', [])
                self.last_added_ips = data.get('last_added_ips', deque(maxlen=20))

                # اضافه کردن فیلدهای جدید به کدهای فعالسازی موجود
                for code in self.active_codes:
                    if 'used_count' not in self.active_codes[code]:
                        self.active_codes[code]['used_count'] = 0
                    if 'created_at' not in self.active_codes[code]:
                        self.active_codes[code]['created_at'] = time.time()
                    if 'users' not in self.active_codes[code]:
                        self.active_codes[code]['users'] = []

                # اضافه کردن فیلدهای جدید به کاربران فعال موجود
                for user_id in self.active_users:
                    if 'joined_date' not in self.active_users[user_id]:
                        self.active_users[user_id]['joined_date'] = "نامشخص"
                    if 'activation_code' not in self.active_users[user_id]:
                        self.active_users[user_id]['activation_code'] = "نامشخص"
        except Exception as e:
            print(f"خطا در بارگذاری پایگاه داده: {e}")

    def save_database(self):
        """ذخیره پایگاه داده"""
        try:
            with open('bot_database.pkl', 'wb') as f:
                pickle.dump({
                    'active_codes': self.active_codes,
                    'active_users': self.active_users,
                    'ipv4_data': self.ipv4_data,
                    'disabled_users': self.disabled_users,
                    'disabled_locations': self.disabled_locations,
                    'wg_endpoints': self.wg_endpoints,
                    'last_added_ips': self.last_added_ips
                }, f)
        except Exception as e:
            print(f"خطا در ذخیره پایگاه داده: {e}")

    def get_endpoints(self):
        """دریافت لیست endpoint های وایرگارد"""
        return self.wg_endpoints

    def add_endpoint(self, endpoint):
        """اضافه کردن endpoint جدید"""
        if endpoint not in self.wg_endpoints:
            self.wg_endpoints.append(endpoint)
            self.save_database()
            return True
        return False

    def remove_endpoint(self, endpoint):
        """حذف endpoint"""
        if endpoint in self.wg_endpoints:
            self.wg_endpoints.remove(endpoint)
            self.save_database()
            return True
        return False

    def is_location_disabled(self, country_code, ip_type="ipv4"):
        """بررسی وضعیت فعال/غیرفعال یک لوکیشن"""
        try:
            location_key = f"{country_code}_{ip_type}_disabled"
            if location_key not in self.disabled_locations:
                self.disabled_locations[location_key] = False
            return self.disabled_locations[location_key]
        except FileNotFoundError:
            self.save_database()
            return False

    def save_database(self):
        with open('bot_database.pkl', 'wb') as f:
            pickle.dump(
                {
                    'active_codes': self.active_codes,
                    'active_users': self.active_users,
                    'ipv4_data': self.ipv4_data,
                    'disabled_users': getattr(self, 'disabled_users', set()),
                    'disabled_locations': getattr(self, 'disabled_locations',
                                                  {}),
                    'wg_endpoints': getattr(self, 'wg_endpoints', []),
                    'last_added_ips': getattr(self, 'last_added_ips', deque(maxlen=20))
                }, f)

    def is_user_subscribed(self, user_id: int) -> bool:
        return user_id in self.active_users and user_id not in self.disabled_users

    def get_tokens(self, user_id: int) -> int:
        if not self.is_user_subscribed(user_id):
            return 0
        user_data = self.active_users.get(user_id, {})
        if user_data.get('type') == 'unlimited':
            return 999999
        return user_data.get('tokens', 0)

    def is_user_active(self, user_id: int) -> bool:
        return user_id in self.active_users and user_id not in self.disabled_users

    def check_activation_code(self, code: str) -> Tuple[bool, Optional[dict]]:
        if code in self.active_codes:
            code_data = self.active_codes[code].copy()
            # به جای حذف کد، آمار استفاده را افزایش می‌دهیم
            self.active_codes[
                code]['used_count'] = self.active_codes[code].get(
                    'used_count', 0) + 1
            self.save_database()
            return True, code_data
        return False, None

    def activate_user(self,
                      user_id: int,
                      code_data: dict,
                      code: str = "نامشخص") -> bool:
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())

        if code_data["type"] == "token":
            tokens = code_data.get("tokens", 0)
            if tokens > 0:
                self.active_users[user_id] = {
                    "type": code_data["type"],
                    "tokens": tokens,
                    "joined_date": current_time,
                    "activation_code": code
                }

                # اضافه کردن کاربر به لیست استفاده‌کنندگان از کد
                if code != "نامشخص" and code in self.active_codes:
                    if 'users' not in self.active_codes[code]:
                        self.active_codes[code]['users'] = []
                    self.active_codes[code]['users'].append(user_id)

                self.save_database()
                return True
            return False

        self.active_users[user_id] = {
            "type": code_data["type"],
            "tokens": 999999,
            "joined_date": current_time,
            "activation_code": code
        }

        # اضافه کردن کاربر به لیست استفاده‌کنندگان از کد
        if code != "نامشخص" and code in self.active_codes:
            if 'users' not in self.active_codes[code]:
                self.active_codes[code]['users'] = []
            self.active_codes[code]['users'].append(user_id)

        self.save_database()
        return True

    def grant_tokens(self, user_id: int, amount: int) -> bool:
        """افزودن توکن به کاربر."""
        if user_id in self.active_users:
            current_tokens = self.active_users[user_id].get("tokens", 0)
            self.active_users[user_id]["tokens"] = current_tokens + amount
            self.save_database()
            return True
        return False

    def use_tokens(self, user_id: int, amount: int = 1) -> bool:
        """استفاده از توکن توسط کاربر."""
        if not self.is_user_active(user_id):
            return False

        user_data = self.active_users.get(user_id, {})
        if user_data.get('type') == 'unlimited':
            return True

        current_tokens = user_data.get('tokens', 0)
        if current_tokens < amount:
            return False

        self.active_users[user_id]['tokens'] = current_tokens - amount
        self.save_database()
        return True

    def add_active_code(self,
                        code: str,
                        code_type: str,
                        tokens: int = 0) -> None:
        self.active_codes[code] = {
            "type": code_type,
            "tokens": tokens,
            "used_count": 0,
            "created_at": time.time(),
            "users": []
        }
        self.save_database()

    def remove_active_code(self, code: str) -> bool:
        """حذف یک کد فعال‌سازی"""
        if code in self.active_codes:
            del self.active_codes[code]
            self.save_database()
            return True
        return False

    def update_active_code(self,
                           code: str,
                           code_type: str,
                           tokens: int = 0) -> bool:
        """به‌روزرسانی یک کد فعال‌سازی"""
        if code in self.active_codes:
            self.active_codes[code].update({
                "type": code_type,
                "tokens": tokens
            })
            self.save_database()
            return True
        return False

    def get_code_stats(self, code: str) -> Dict:
        """دریافت آمار استفاده از یک کد فعال‌سازی"""
        if code in self.active_codes:
            return {
                "کد":
                code,
                "نوع":
                "دائمی"
                if self.active_codes[code]["type"] == "unlimited" else "توکنی",
                "توکن‌ها":
                self.active_codes[code].get("tokens", 0),
                "تعداد استفاده":
                self.active_codes[code].get("used_count", 0),
                "تاریخ ایجاد":
                time.strftime(
                    "%Y-%m-%d %H:%M:%S",
                    time.localtime(self.active_codes[code].get(
                        "created_at", time.time()))),
                "کاربران":
                len(self.active_codes[code].get("users", []))
            }
        return {}

    def get_all_codes(self) -> Dict[str, Dict]:
        """دریافت تمام کدهای فعال‌سازی"""
        return self.active_codes

    # Adding some initial activation codes
    def initialize_codes(self):
        # Unlimited codes (10 codes)
        self.add_active_code("UNLIMITED2024", "unlimited")
        self.add_active_code("VIP2024", "unlimited")
        self.add_active_code("PREMIUM2024", "unlimited")
        self.add_active_code("FOREVER2024", "unlimited")
        self.add_active_code("INFINITY2024", "unlimited")
        self.add_active_code("UNLIMIT1234", "unlimited")
        self.add_active_code("LIFETIME2024", "unlimited")
        self.add_active_code("PROACCESS2024", "unlimited")
        self.add_active_code("ELITEACCESS24", "unlimited")
        self.add_active_code("MAXUNLIMITED24", "unlimited")

        # Token-based subscription codes (10 codes)
        self.add_active_code("TOKEN500", "token", 500)
        self.add_active_code("TOKEN1000", "token", 1000)
        self.add_active_code("TOKEN250", "token", 250)
        self.add_active_code("TOKEN100", "token", 100)
        self.add_active_code("CREDIT750", "token", 750)
        self.add_active_code("STARTER50", "token", 50)
        self.add_active_code("BASIC200", "token", 200)
        self.add_active_code("TRIAL25", "token", 25)
        self.add_active_code("BONUS300", "token", 300)
        self.add_active_code("GIFT150", "token", 150)

    def get_ipv4_countries(self) -> Dict[str, Tuple[str, str, List[str]]]:
        return self.ipv4_data

    def get_ips_by_country(self, country_code: str) -> List[str]:
        if country_code in self.ipv4_data:
            return self.ipv4_data[country_code][2]
        return []

    def add_ipv4_address(self, country_name: str, flag: str, ipv4: str) -> None:
        # استاندارد‌سازی نام‌ها و کدها بر اساس قوانین خاص
        country_name_lower = country_name.lower()

        # تشخیص خاص عربستان
        if 'saudi' in country_name_lower or 'عربستان' in country_name_lower or 'سعودی' in country_name_lower:
            country_code = 'SA'
            standard_country_name = 'Saudi Arabia'

            # استاندارد کردن نام عربستان به زبان انگلیسی
            if 'عربستان' in country_name or 'سعودی' in country_name:
                country_name = 'Saudi Arabia'

        else:
            # در سایر موارد، کد کشور را از نام استخراج می‌کنیم
            country_code = country_name.lower().replace(' ', '_')
            standard_country_name = country_name

            # بررسی وجود کشور با نام مشابه
            existing_country = next((key for key in self.ipv4_data.keys() 
                                   if key.lower().replace(' ', '_') == country_code 
                                   or (len(key) <= 3 and key.lower() == country_code.lower())), None)
            if existing_country:
                country_code = existing_country
                standard_country_name = self.ipv4_data[existing_country][0]  # استفاده از نام موجود

        # Standardize Saudi Arabia country codes
        saudi_keys = ['sa', 'ksa', 'saudi', 'saudi_arabia', 'saudiarabia', 'kingdomofsaudiarabia', 'ksaudi', 'saudi arabia']
        for key in list(self.ipv4_data.keys()):
            if key.lower() in saudi_keys:
                # Merge all Saudi Arabia addresses with different keys
                if key.upper() != 'SA' and 'SA' in self.ipv4_data:
                    name, flag_emoji, ips = self.ipv4_data['SA']
                    _, _, saudi_ips = self.ipv4_data[key]
                    merged_ips = list(set(ips + saudi_ips))  # ادغام بدون تکرار
                    self.ipv4_data['SA'] = (name, flag_emoji, merged_ips)
                    del self.ipv4_data[key]
                elif key != 'SA':
                    self.ipv4_data['SA'] = self.ipv4_data[key]
                    del self.ipv4_data[key]
                country_code = 'SA'
                break

        if country_code not in self.ipv4_data:
            self.ipv4_data[country_code] = (standard_country_name, flag, [])

        name, flag_emoji, ips = self.ipv4_data[country_code]
        if ipv4 not in ips:
            ips.append(ipv4)
            self.ipv4_data[country_code] = (name, flag_emoji, ips)
            # اضافه کردن به لیست آخرین IPهای اضافه شده
            self.last_added_ips.appendleft(f"{flag} {standard_country_name}: {ipv4}")
            self.save_database()

    def remove_country(self, country_code: str) -> bool:
        """حذف کامل یک کشور و تمام آدرس‌های آن"""
        if country_code in self.ipv4_data:
            del self.ipv4_data[country_code]
            self.save_database()
            return True
        return False

    def remove_ipv4_address(self, country_code: str, ipv4: str) -> bool:
        """حذف یک آدرس IP از پایگاه داده."""
        if country_code in self.ipv4_data:
            name, flag, ips = self.ipv4_data[country_code]
            if ipv4 in ips:
                ips.remove(ipv4)
                self.ipv4_data[country_code] = (name, flag, ips)
                self.save_database()
                return True
        return False

    def disable_user(self, user_id: int) -> bool:
        """غیرفعال کردن یک کاربر."""
        if user_id in self.active_users and user_id not in self.disabled_users:
            self.disabled_users.add(user_id)
            self.save_database()
            return True
        return False

    def enable_user(self, user_id: int) -> bool:
        """فعال کردن یک کاربر."""
        if user_id in self.disabled_users:
            self.disabled_users.remove(user_id)
            self.save_database()
            return True
        return False

    def is_user_disabled(self, user_id: int) -> bool:
        """بررسی اینکه آیا کاربر غیرفعال شده است یا خیر."""
        return user_id in self.disabled_users

    def disable_location(self,
                         country_code: str,
                         ip_type: str = "ipv4") -> bool:
        """غیرفعال کردن یک لوکیشن"""
        if country_code in self.ipv4_data or ip_type == "ipv6":
            if country_code not in self.disabled_locations:
                self.disabled_locations[country_code] = {
                    "ipv4": False,
                    "ipv6": False
                }
            elif not isinstance(self.disabled_locations[country_code], dict):
                # تبدیل مقادیر قدیمی به فرمت جدید
                was_disabled = self.disabled_locations[country_code]
                self.disabled_locations[country_code] = {
                    "ipv4": was_disabled,
                    "ipv6": was_disabled
                }

            self.disabled_locations[country_code][ip_type] = True
            self.save_database()
            return True
        return False

    def enable_location(self,
                        country_code: str,
                        ip_type: str = "ipv4") -> bool:
        """فعال کردن یک لوکیشن"""
        if country_code in self.disabled_locations:
            if not isinstance(self.disabled_locations[country_code], dict):
                # تبدیل مقادیر قدیمی به فرمت جدید
                was_disabled = self.disabled_locations[country_code]
                self.disabled_locations[country_code] = {
                    "ipv4": was_disabled,
                    "ipv6": was_disabled
                }

            self.disabled_locations[country_code][ip_type] = False
            self.save_database()
            return True
        return False

    # متد جدید برای مدیریت IPv6
    def add_ipv6_address(self, country_name: str, flag: str,
                         ipv6: str) -> None:
        """اضافه کردن آدرس IPv6 به کشور"""
        # نرمال‌سازی نام کشور برای استفاده به عنوان کلید
        country_code = country_name.lower().replace(' ', '_')

        # بررسی وجود کشور با نام‌های مشابه
        existing_country = None
        for key in self.ipv4_data.keys():
            if key.lower().replace(' ', '_') == country_code:
                existing_country = key
                break

        if existing_country:
            country_code = existing_country

        # اگر کشور در پایگاه داده وجود ندارد، اضافه کن
        if country_code not in self.ipv4_data:
            self.ipv4_data[country_code] = (country_name, flag, [])

        # افزودن پشتیبانی IPv6 به ساختار داده
        # به‌زودی پیاده‌سازی خواهد شد

    def is_location_disabled(self,
                             country_code: str,
                             ip_type: str = "ipv4") -> bool:
        """بررسی اینکه آیا یک لوکیشن غیرفعال است"""
        if not isinstance(self.disabled_locations, dict):
            self.disabled_locations = {}

        if country_code not in self.disabled_locations:
            self.disabled_locations[country_code] = {
                "ipv4": False,
                "ipv6": False
            }
        elif not isinstance(self.disabled_locations[country_code], dict):
            # تبدیل مقادیر قدیمی به فرمت جدید
            was_disabled = self.disabled_locations[country_code]
            self.disabled_locations[country_code] = {
                "ipv4": was_disabled,
                "ipv6": was_disabled
            }

        return self.disabled_locations[country_code].get(ip_type, False)

    def get_all_locations(self) -> Dict[str, Dict]:
        """دریافت تمام لوکیشن‌ها با وضعیت فعال/غیرفعال"""
        result = {}

        # IPv4 locations
        for country_code, (name, flag, ips) in self.ipv4_data.items():
            if country_code not in result:
                result[country_code] = {
                    "name":
                    name,
                    "flag":
                    flag,
                    "ipv4_count":
                    len(ips),
                    "ipv6_count":
                    0,
                    "ipv4_disabled":
                    self.is_location_disabled(country_code, "ipv4"),
                    "ipv6_disabled":
                    self.is_location_disabled(country_code, "ipv6")
                }
            else:
                result[country_code]["ipv4_count"] = len(ips)

        # اضافه کردن آدرس‌های IPv6 به نتیجه (پیاده‌سازی در آینده)
        # این قسمت برای پشتیبانی از IPv6 در آینده است

        return result

    def get_stats(self) -> Dict[str, int]:
        return {
            "کاربران فعال": len(self.active_users) - len(self.disabled_users),
            "کاربران غیرفعال": len(self.disabled_users),
            "کدهای فعال‌سازی": len(self.active_codes),
            "تعداد کشورها": len(self.ipv4_data),
            "تعداد کل IPv4":
            sum(len(ips) for _, _, ips in self.ipv4_data.values())
        }

    def get_endpoints(self):
        return self.wg_endpoints

    def add_endpoint(self, endpoint: str):
        if endpoint not in self.wg_endpoints:
            self.wg_endpoints.append(endpoint)
            self.save_database()

    def remove_endpoint(self, endpoint: str):
        if endpoint in self.wg_endpoints:
            self.wg_endpoints.remove(endpoint)
            self.save_database()

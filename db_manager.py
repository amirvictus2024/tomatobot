import pickle
from typing import Dict, Set, List, Tuple
from collections import defaultdict

class DBManager:
    def __init__(self):
        self.active_codes: Dict[str, Dict[str, any]] = {}  # code -> {type: str, tokens: int}
        self.active_users: Dict[int, Dict[str, any]] = {}  # user_id -> {type: str, tokens: int}
        self.ipv4_data: Dict[str, Tuple[str, str, List[str]]] = {}  # country_code -> (name, flag, [ips])
        self.disabled_users: Set[int] = set()  # مجموعه کاربران غیرفعال
        self.load_database()

    def load_database(self):
        try:
            with open('bot_database.pkl', 'rb') as f:
                data = pickle.load(f)
                self.active_codes = data.get('active_codes', {})
                self.active_users = data.get('active_users', {})
                self.ipv4_data = data.get('ipv4_data', {})
                self.disabled_users = data.get('disabled_users', set())
        except FileNotFoundError:
            self.save_database()

    def save_database(self):
        with open('bot_database.pkl', 'wb') as f:
            pickle.dump({
                'active_codes': self.active_codes,
                'active_users': self.active_users,
                'ipv4_data': self.ipv4_data,
                'disabled_users': getattr(self, 'disabled_users', set())
            }, f)

    def is_user_subscribed(self, user_id: int) -> bool:
        return user_id in self.active_users

    def get_tokens(self, user_id: int) -> int:
        return 999999 if self.is_user_subscribed(user_id) else 0

    def is_user_active(self, user_id: int) -> bool:
        return user_id in self.active_users

    def check_activation_code(self, code: str) -> bool:
        if code in self.active_codes:
            code_data = self.active_codes[code]
            del self.active_codes[code]
            self.save_database()
            return True, code_data
        return False, None

    def activate_user(self, user_id: int, code_data: dict) -> bool:
        if code_data["type"] == "token":
            remaining_tokens = code_data.get("tokens", 0)
            if remaining_tokens > 0:
                code_data["tokens"] -= 1
                self.active_users[user_id] = {"type": code_data["type"], "tokens": self.get_tokens(user_id) + 1}
                self.save_database()
                return True
            return False
        self.active_users[user_id] = code_data
        self.save_database()
        return True

    def grant_tokens(self, user_id: int, amount: int) -> None:
        if user_id in self.active_users:
            self.active_users[user_id]["tokens"] = self.get_tokens(user_id) + amount
            self.save_database()
        self.save_database()

    def add_active_code(self, code: str, code_type: str, tokens: int = 0) -> None:
        self.active_codes[code] = {"type": code_type, "tokens": tokens}
        self.save_database()

    # Adding some initial activation codes
    def initialize_codes(self):
        # Unlimited codes
        self.add_active_code("UNLIMITED2024", "unlimited")
        self.add_active_code("VIP2024", "unlimited")
        self.add_active_code("PREMIUM2024", "unlimited")

        # Token-based subscription codes
        self.add_active_code("TOKEN500", "token", 500)
        self.add_active_code("TOKEN1000", "token", 1000)

    def get_ipv4_countries(self) -> Dict[str, Tuple[str, str, List[str]]]:
        return self.ipv4_data

    def get_ips_by_country(self, country_code: str) -> List[str]:
        if country_code in self.ipv4_data:
            return self.ipv4_data[country_code][2]
        return []

    def add_ipv4_address(self, country_name: str, flag: str, ipv4: str) -> None:
        # نرمال‌سازی نام کشور برای استفاده به عنوان کلید
        country_code = country_name.lower().replace(' ', '_')

        # بررسی وجود کشور با نام‌های مشابه
        # برای مثال "Saudi Arabia" و "saudi arabia" باید به یک کلید تبدیل شوند
        existing_country = None
        for key in self.ipv4_data.keys():
            if key.lower() == country_code.lower():
                existing_country = key
                break

        if existing_country:
            country_code = existing_country

        # اگر کشور در پایگاه داده وجود ندارد، اضافه کن
        if country_code not in self.ipv4_data:
            self.ipv4_data[country_code] = (country_name, flag, [])

        # آدرس IP را به لیست اضافه کن اگر تکراری نیست
        name, flag_emoji, ips = self.ipv4_data[country_code]
        if ipv4 not in ips:
            ips_new = ips.copy()
            ips_new.append(ipv4)
            self.ipv4_data[country_code] = (name, flag_emoji, ips_new)
            self.save_database()

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

    def get_stats(self) -> Dict[str, int]:
        return {
            "کاربران فعال": len(self.active_users),
            "کدهای فعال‌سازی": len(self.active_codes),
            "تعداد کشورها": len(self.ipv4_data),
            "تعداد کل IPv4": sum(len(ips) for _, _, ips in self.ipv4_data.values())
        }
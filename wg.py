
import random
import os
import ipaddress
import base64

class WireguardConfig:
    def __init__(self):
        self.endpoint_ports = [53, 80, 443, 8080, 51820, 1194]
        self.dns_servers = ["1.1.1.1", "8.8.8.8", "9.9.9.9", "149.112.112.112"]
        self.mtu_options = [1280, 1380, 1420, 1480]

    def generate_private_key(self):
        """تولید کلید خصوصی"""
        key_chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        return base64.b64encode(os.urandom(32)).decode('utf-8')
    
    def generate_public_key(self):
        """تولید کلید عمومی"""
        key_chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
        return base64.b64encode(os.urandom(32)).decode('utf-8')
    
    def generate_config(self, address=None, port=None, dns=None, mtu=None, endpoint=None, country=None, allowed_ips=None, keepalive=None, config_name=None):
        """تولید پیکربندی وایرگارد با پارامترهای دلخواه"""
        # تنظیم مقادیر پیش‌فرض اگر پارامتری تعیین نشده باشد
        if address is None:
            address = random.choice([
                "10.10.0.2/32", "10.66.66.2/32", "192.168.100.2/32", "172.16.0.2/32"
            ])
        
        if port is None:
            port = random.choice(self.endpoint_ports)
        
        if dns is None:
            dns_server1 = random.choice(self.dns_servers)
            # انتخاب DNS دوم متفاوت از اولی
            dns_server2 = random.choice([s for s in self.dns_servers if s != dns_server1])
            dns = f"{dns_server1}, {dns_server2}"
        
        if mtu is None:
            mtu = random.choice(self.mtu_options)
        
        if endpoint is None:
            if country and country.lower() == "italy":
                # استفاده از رنج آی‌پی مربوط به ایتالیا (فرضی)
                endpoint = f"93.184.{random.randint(1, 254)}.{random.randint(1, 254)}"
            else:
                endpoint = f"162.159.{random.randint(192, 200)}.{random.randint(1, 254)}"
        
        # تولید نام کانفیگ رندوم 6 کاراکتری اگر تعیین نشده باشد
        if config_name is None:
            import string
            chars = string.ascii_letters + string.digits
            config_name = ''.join(random.choice(chars) for _ in range(6))
        
        # تولید کلیدها
        private_key = self.generate_private_key()
        public_key = self.generate_public_key()
        
        # تنظیم AllowedIPs و PersistentKeepalive
        if allowed_ips is None:
            allowed_ips = "0.0.0.0/4, ::/4"
        
        if keepalive is None:
            keepalive = 15
        
        # ساخت پیکربندی
        config = f"""[Interface]
PrivateKey = {private_key}
Address = {address}
DNS = {dns}
MTU = {mtu}

[Peer]
PublicKey = {public_key}
AllowedIPs = {allowed_ips}
Endpoint = {endpoint}:{port}
PersistentKeepalive = {keepalive}
"""
        return config, config_name
    
    def get_server_info(self, endpoint):
        """دریافت اطلاعات سرور از آدرس Endpoint"""
        try:
            import requests
            response = requests.get(f"https://api.iplocation.net/?ip={endpoint}")
            if response.status_code == 200:
                data = response.json()
                return {
                    "country": data.get('country_name', 'نامشخص'),
                    "country_code": data.get('country_code', 'XX'),
                    "isp": data.get('isp', 'نامشخص')
                }
        except Exception:
            pass
        
        return {
            "country": "نامشخص",
            "country_code": "XX",
            "isp": "نامشخص"
        }

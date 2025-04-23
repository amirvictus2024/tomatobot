import random
import os
import ipaddress


class WireguardConfig:

    def __init__(self):
        # تنظیمات پیش‌فرض وایرگارد
        self.default_dns = ["10", "8.8.8.8"]
        self.default_allowed_ips = ["0.0.0.0/0", "::/0"]
        self.default_keepalive = 25
        self.default_port_range = (10000, 60000)

    def generate_private_key(self):
        """تولید کلید خصوصی تصادفی"""
        return ''.join(random.choices('abcdef0123456789', k=44))

    def generate_public_key(self):
        """تولید کلید عمومی تصادفی"""
        return ''.join(random.choices('abcdef0123456789', k=44))

    def generate_server_ip(self):
        """تولید آدرس IP سرور"""
        return f"162.159.{random.randint(1, 255)}.{random.randint(1, 255)}"

    def generate_client_ip(self):
        """تولید آدرس IP کلاینت"""
        return f"10.66.66.{random.randint(2, 254)}/32"

    def generate_port(self):
        """تولید پورت تصادفی"""
        return random.randint(self.default_port_range[0],
                              self.default_port_range[1])

    def generate_config(self,
                        custom_dns=None,
                        custom_server=None,
                        custom_port=None):
        """تولید پیکربندی کامل وایرگارد"""
        private_key = self.generate_private_key()
        public_key = self.generate_public_key()
        client_ip = self.generate_client_ip()
        server_ip = custom_server or self.generate_server_ip()
        port = custom_port or self.generate_port()
        dns = custom_dns or self.default_dns

        # تولید پیکربندی
        config = f"""[Interface]
PrivateKey = {private_key}
Address = {client_ip}
DNS = {', '.join(dns)}

[Peer]
PublicKey = {public_key}
AllowedIPs = {', '.join(self.default_allowed_ips)}
Endpoint = {server_ip}:{port}
PersistentKeepalive = {self.default_keepalive}
"""
        return config

    def generate_advanced_config(self, custom_options=None):
        """تولید پیکربندی پیشرفته با گزینه‌های سفارشی"""
        base_config = self.generate_config()

        if custom_options and isinstance(custom_options, dict):
            # افزودن گزینه‌های سفارشی به پیکربندی
            if 'pre_up' in custom_options:
                base_config = base_config.replace(
                    "[Interface]",
                    f"[Interface]\nPreUp = {custom_options['pre_up']}")

            if 'post_up' in custom_options:
                base_config = base_config.replace(
                    "[Interface]",
                    f"[Interface]\nPostUp = {custom_options['post_up']}")

            if 'pre_down' in custom_options:
                base_config = base_config.replace(
                    "[Interface]",
                    f"[Interface]\nPreDown = {custom_options['pre_down']}")

            if 'post_down' in custom_options:
                base_config = base_config.replace(
                    "[Interface]",
                    f"[Interface]\nPostDown = {custom_options['post_down']}")

        return base_config

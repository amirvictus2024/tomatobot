
import os
import time
import logging
import fcntl
import errno
import atexit

class LockManager:
    def __init__(self, lock_file="bot.lock"):
        """
        مدیریت قفل فایل برای جلوگیری از اجرای همزمان چندین نمونه
        
        Args:
            lock_file (str): مسیر فایل قفل
        """
        self.lock_file = lock_file
        self.lock_fd = None
        self.locked = False
        self.logger = logging.getLogger('lock_manager')
        
    def acquire_lock(self):
        """
        سعی در بدست آوردن قفل. اگر قفل قبلا گرفته شده باشد، False برمی‌گرداند.
        
        Returns:
            bool: True اگر قفل با موفقیت گرفته شود، در غیر این صورت False
        """
        try:
            # باز کردن یا ایجاد فایل قفل
            self.lock_fd = open(self.lock_file, 'w')
            
            # سعی در قفل کردن فایل به صورت غیرمسدودکننده
            fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            
            # نوشتن PID فرآیند فعلی در فایل قفل
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()
            
            # ثبت تابع پاکسازی قفل برای هنگام خروج از برنامه
            atexit.register(self.release_lock)
            
            self.locked = True
            self.logger.info("قفل ربات با موفقیت گرفته شد.")
            return True
            
        except IOError as e:
            # اگر فایل قفل قبلا گرفته شده باشد
            if e.errno == errno.EAGAIN:
                self.logger.warning("یک نمونه دیگر از ربات در حال اجراست. خروج...")
                if self.lock_fd:
                    self.lock_fd.close()
                return False
            # سایر خطاهای I/O
            self.logger.error(f"خطا در گرفتن قفل: {e}")
            if self.lock_fd:
                self.lock_fd.close()
            return False
            
    def release_lock(self):
        """آزاد کردن قفل فایل"""
        if self.locked and self.lock_fd:
            try:
                fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
                self.lock_fd.close()
                if os.path.exists(self.lock_file):
                    os.remove(self.lock_file)
                self.locked = False
                self.logger.info("قفل ربات آزاد شد.")
            except Exception as e:
                self.logger.error(f"خطا در آزاد کردن قفل: {e}")

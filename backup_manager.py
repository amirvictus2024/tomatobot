import os
import time
import shutil
import datetime
import logging
import threading

class BackupManager:
    def __init__(self, backup_interval=3600, max_backups=5):
        """
        Initialize the backup manager with the specified interval and max number of backups.
        
        Args:
            backup_interval (int): Time between backups in seconds (default: 1 hour)
            max_backups (int): Maximum number of backups to keep (default: 5)
        """
        self.backup_interval = backup_interval  # Default: backup every hour
        self.max_backups = max_backups
        self.backup_dir = "database_backups"
        self.running = False
        self.logger = logging.getLogger('backup_manager')
        
        # Create backup directory if it doesn't exist
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)

    def start_backup_thread(self):
        """Start the background thread for automatic backups."""
        if not self.running:
            self.running = True
            self.backup_thread = threading.Thread(target=self._backup_loop, daemon=True)
            self.backup_thread.start()
            self.logger.info("Automated database backup started.")

    def stop_backup_thread(self):
        """Stop the automated backup process."""
        self.running = False
        if hasattr(self, 'backup_thread') and self.backup_thread.is_alive():
            self.backup_thread.join(timeout=1.0)
        self.logger.info("Automated database backup stopped.")

    def _backup_loop(self):
        """Background process that performs periodic backups."""
        while self.running:
            try:
                self.create_backup()
                self.cleanup_old_backups()
            except Exception as e:
                self.logger.error(f"Error during automatic backup: {e}")
            
            # Sleep until next backup
            time.sleep(self.backup_interval)

    def create_backup(self):
        """
        Create a backup of the database file.
        
        Returns:
            str: Path to the created backup file
        """
        try:
            source_file = 'bot_database.pkl'
            if not os.path.exists(source_file):
                self.logger.warning(f"Database file {source_file} not found, skipping backup")
                return None
                
            # Create timestamp for the backup filename
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"bot_database_{timestamp}.pkl"
            backup_path = os.path.join(self.backup_dir, backup_filename)
            
            # Copy the database file
            shutil.copy2(source_file, backup_path)
            
            self.logger.info(f"Database backup created: {backup_path}")
            return backup_path
        except Exception as e:
            self.logger.error(f"Failed to create backup: {e}")
            raise

    def restore_backup(self, backup_file=None):
        """
        Restore database from backup.
        
        Args:
            backup_file (str, optional): Specific backup file to restore. 
                                         If None, restores the most recent backup.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if backup_file is None:
                # Find the most recent backup
                backups = self.list_backups()
                if not backups:
                    self.logger.warning("No backups found to restore")
                    return False
                backup_file = backups[0][1]  # Get the path from the most recent backup
            
            # بررسی اعتبار فایل بکاپ قبل از بازیابی
            import pickle
            try:
                with open(backup_file, 'rb') as test_file:
                    pickle.load(test_file)
            except Exception as pickle_error:
                self.logger.error(f"فایل بکاپ معتبر نیست: {pickle_error}")
                return False
                
            # Restore the database
            shutil.copy2(backup_file, 'bot_database.pkl')
            self.logger.info(f"Database restored from {backup_file}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to restore backup: {e}")
            return False

    def list_backups(self):
        """
        List all available backups, sorted by creation time (newest first).
        
        Returns:
            list: List of tuples (timestamp, file_path) of available backups
        """
        if not os.path.exists(self.backup_dir):
            return []
            
        backups = []
        for filename in os.listdir(self.backup_dir):
            if filename.startswith("bot_database_") and filename.endswith(".pkl"):
                file_path = os.path.join(self.backup_dir, filename)
                created_time = os.path.getctime(file_path)
                backups.append((created_time, file_path))
        
        # Sort by creation time (newest first)
        backups.sort(reverse=True)
        return backups

    def cleanup_old_backups(self):
        """Remove old backups to keep only the specified maximum number."""
        backups = self.list_backups()
        if len(backups) > self.max_backups:
            for _, file_path in backups[self.max_backups:]:
                try:
                    os.remove(file_path)
                    self.logger.info(f"Removed old backup: {file_path}")
                except Exception as e:
                    self.logger.error(f"Failed to remove old backup {file_path}: {e}")

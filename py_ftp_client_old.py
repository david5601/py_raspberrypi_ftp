import os
import ftplib
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from pynput import keyboard

class FTPMonitor:
    def __init__(self, ftp_server, ftp_username, ftp_password, local_path):
        self.ftp_server = ftp_server
        self.ftp_username = ftp_username
        self.ftp_password = ftp_password
        self.running = True
        self.ftp = None
        self.ctrl_pressed = False
        self.local_path = local_path
        self.observer = Observer()
        self.prev_items = set()

    def connect(self):
        while self.running:
            try:
                # Connect to the FTP server
                self.ftp = ftplib.FTP(self.ftp_server)
                self.ftp.login(user=self.ftp_username, passwd=self.ftp_password)
                print("Login successful")
                break
            except ftplib.all_errors as e:
                print(f"FTP error: {e}. Retrying in 5 seconds...")
                time.sleep(5)

    def list_directories(self):
        while self.running:
            try:
                if not self.ftp:
                    self.connect()

                current_items = set()
                # Get the list of directories
                items = self.ftp.nlst()
                for item in items:
                    try:
                        self.ftp.cwd(item)  # Try to change to directory
                        current_items.add(item)
                        self.ftp.cwd('..')  # Change back to parent directory
                    except ftplib.error_perm:
                        # Not a directory, skip it
                        continue

                # Compare current items with previous items
                if current_items != self.prev_items:
                    print("\nCurrent directories:")
                    for item in current_items:
                        print(item)
                    self.prev_items = current_items

                    # Upload new directories
                    self.upload_diffs(current_items)

                # Wait for a short time before listing again
                time.sleep(5)
            except (ftplib.all_errors, OSError) as e:
                print(f"Connection lost: {e}. Reconnecting...")
                self.ftp = None  # Reset the connection

    def start_monitoring(self):
        self.connect()
        # Start the directory listing in a separate thread
        threading.Thread(target=self.list_directories).start()
        # Start local file system monitoring with watchdog
        event_handler = LocalFileEventHandler(self)
        self.observer.schedule(event_handler, self.local_path, recursive=True)
        self.observer.start()
        # Start the keyboard listener in the main thread
        with keyboard.Listener(on_press=self.on_press, on_release=self.on_release) as listener:
            listener.join()

    def stop_monitoring(self):
        self.observer.stop()
        self.observer.join()

    def on_press(self, key):
        if key == keyboard.Key.cmd_l:
            self.ctrl_pressed = True
        elif key == keyboard.KeyCode.from_char('q') and self.ctrl_pressed:
            print("Win + Q pressed, disconnecting...")
            self.running = False
            self.stop_monitoring()
            if self.ftp:
                self.ftp.quit()
            return False  # Stop the listener

    def on_release(self, key):
        if key == keyboard.Key.cmd_l:
            self.ctrl_pressed = False


    def upload_diffs(self, current_items):
        local_directories = self.get_local_directories()
        server_directories = self.get_server_directories(self.prev_items)

        print(local_directories)
        print(server_directories)

        # Upload missing directories and their contents
        for directory in local_directories:
            if directory not in server_directories:
                self.upload_folder(directory)

        # Upload missing or modified files
        # for file in local_files:
        #     if file not in server_files:
        #         self.upload_file(file)

    def get_local_directories(self):
        local_items = set()
        for root, dirs, _ in os.walk(self.local_path):
            for dir in dirs:
                local_items.add(f"{os.path.relpath(os.path.join(root, dir), self.local_path)}")
        return local_items

    def get_server_directories(self, current_items):
        server_items = set()
        for item in current_items:
            server_items.add(item)
        return server_items

    def upload_folder(self, folder_path):
        try:

            remote_path = folder_path.replace('\\', '/')
            self.ftp.mkd(remote_path)
            print(f"Created directory on server: {remote_path}")
            for root, _, files in os.walk(os.path.join(self.local_path, folder_path)):
                for file in files:
                    local_file = os.path.join(root, file)
                    remote_file = os.path.relpath(local_file, self.local_path).replace('\\', '/')
                    self.upload_file(remote_file)
        except ftplib.all_errors as e:
            print(f"Failed to upload folder {folder_path}: {e}")

    def upload_file(self, file_path):
        try:
            local_file = os.path.join(self.local_path, file_path)
            remote_path = file_path.replace('\\', '/')
            
            # Check if the file exists locally
            if not os.path.exists(local_file):
                print(f"Local file {local_file} does not exist.")
                return

            with open(local_file, 'rb') as f:
                self.ftp.storbinary(f'STOR {remote_path}', f)
                print(f"Uploaded file: {remote_path}")
        except ftplib.all_errors as e:
            print(f"Failed to upload file {remote_path}: {e}")

    # def upload_folder(self, folder_path):
    #     try:
    #         remote_path = folder_path[len("Directory: "):]
    #         self.ftp.mkd(remote_path)
    #         print(f"Created directory on server: {remote_path}")
    #         for root, dirs, files in os.walk(os.path.join(self.local_path, remote_path)):
    #             for file in files:
    #                 local_file = os.path.join(root, file)
    #                 remote_file = os.path.relpath(local_file, self.local_path)
    #                 self.upload_file(f"File: {remote_file}")
    #             for dir in dirs:
    #                 local_dir = os.path.join(root, dir)
    #                 remote_dir = os.path.relpath(local_dir, self.local_path)
    #                 self.upload_folder(f"Directory: {remote_dir}")
    #     except ftplib.all_errors as e:
    #         print(f"Failed to upload folder {remote_path}: {e}")

class LocalFileEventHandler(FileSystemEventHandler):
    def __init__(self, ftp_monitor):
        self.ftp_monitor = ftp_monitor

    def on_created(self, event):
        if event.is_directory:
            time.sleep(5)
            self.ftp_monitor.upload_diffs(self.ftp_monitor.get_local_directories())

    def on_modified(self, event):
        time.sleep(5)
        if not event.is_directory:
            self.ftp_monitor.upload_diffs(self.ftp_monitor.get_local_directories())

    def on_moved(self, event):
        if not event.is_directory:
            time.sleep(5)
            self.ftp_monitor.upload_diffs(self.ftp_monitor.get_local_directories())

# FTP server details
ftp_server = '192.168.50.129'  # or use the IP address of the Raspberry Pi
ftp_username = 'mike'  # replace with your Raspberry Pi username
ftp_password = 'pi'  # replace with your Raspberry Pi password
local_path = 'C:/Users/mike/Downloads/upload'  # Replace with the local directory to monitor

# Create FTPMonitor instance and start monitoring
ftp_monitor = FTPMonitor(ftp_server, ftp_username, ftp_password, local_path)
ftp_monitor.start_monitoring()

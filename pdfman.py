import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
from tkinter import ttk
from gui import Tooltip, IconButtonManager     # sử dụng Tooltip và IconButtonManager cho các nút chức năng
from PIL import Image, ImageTk
import fitz  # PyMuPDF
from pypdf import PdfReader, PdfWriter
import os
import sys
import gc
import ctypes
import tkinterdnd2
from tkinterdnd2 import DND_FILES, DND_TEXT
import shutil
import webbrowser
import traceback
try:
    import winreg
except Exception:
    winreg = None


class PDFManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("PDF Manager - Copyright © 2026 by Hailúa")
        self.root.geometry("1080x800")

        # Bật chế độ low-memory cho MuPDF (nếu có) để hạn chế cache nội bộ
        try:
            if hasattr(fitz, "TOOLS") and hasattr(fitz.TOOLS, "set_low_memory"):
                fitz.TOOLS.set_low_memory(True)
        except Exception:
            pass
        
        # Set icon cho window chính từ thư mục icons
        try:
            if getattr(sys, 'frozen', False):
                meipass = getattr(sys, '_MEIPASS', None)
                if meipass:
                    # Ưu tiên icons trong _internal (PyInstaller 6 onedir)
                    self.base_dir = meipass
                    icon_file = os.path.join(self.base_dir, 'icons', 'pdfman.ico')
                    if not os.path.exists(icon_file):
                        self.base_dir = os.path.dirname(meipass)
                else:
                    self.base_dir = os.path.dirname(os.path.abspath(__file__))
            else:
                self.base_dir = os.path.dirname(os.path.abspath(__file__))

            icon_file = os.path.join(self.base_dir, 'icons', 'pdfman.ico')
            if os.path.exists(icon_file):
                self.root.iconbitmap(icon_file)
        except Exception:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
            pass  # Sử dụng icon mặc định nếu không tìm thấy

        # --- Các biến trạng thái ---
        self.current_pdf_path = None
        self.opened_file_count = 0
        self.page_images = {}  # Dict: visual_idx -> PhotoImage (chỉ lưu trang đã render)
        self.page_checkboxes = [] # Lưu trữ các biến của checkbox (IntVar)
        self.page_color_elements = []  # Lưu trữ các elements cần đổi màu (header_frame, checkbox, label)
        self.page_containers = []  # Lưu trữ references đến page_container
        # Dictionary để lưu góc xoay hiện tại của từng trang: {page_index: angle}
        self.rotation_states = {}
        self.initial_rotation_states = {}  # Lưu trạng thái ban đầu để so sánh thay đổi
        self.deleted_pages = set()  # Lưu các trang bị xóa
        self.zoom_level = 0.80  # Tỷ lệ zoom mặc định (80%)
        self.zoom_timer = None  # Timer để debounce zoom bằng chuột
        self.btn_save = None  # Tham chiếu nút Lưu File PDF mới để enable/disable
        self.btn_open_pdf = None  # Tham chiếu nút Open PDF
        self.btn_close_pdf = None  # Tham chiếu nút Close PDF
        self.btn_select_all = None  # Tham chiếu nút Select All/Deselect All
        self.select_all_state = False  # False = Deselect All, True = Select All
        self.action_widgets = []  # Danh sách widgets trong action_frame
        self.bottom_widgets = []  # Danh sách widgets trong bottom_frame
        
        # --- Lazy loading variables ---
        self.fitz_doc = None  # Giữ fitz document mở cho lazy rendering
        self.page_data = []  # Thông tin từng trang: {original_idx, container, lbl_img, rendered, photo, width, height}
        self.page_original_indices = []  # Map visual index -> original page index
        self.scroll_check_timer = None  # Timer debounce kiểm tra trang hiển thị
        self._pixel_img = None  # Ảnh 1x1 pixel cho placeholder sizing
        self._layout_dirty = False  # Flag ngăn render khi layout đang thay đổi (zoom)
        self._gc_pending = 0  # Đếm số trang đã unload, gọi gc.collect() sau mỗi batch
        
        # --- Temp folder management ---
        self.temp_dir = os.path.join(self.base_dir, "temp")
        self.backup_pdf_path = None
        self.combined_pdf_path = None
        self._create_temp_dir()
        
        # Khởi tạo IconButtonManager để quản lý icon cho button
        self.icon_manager = IconButtonManager(os.path.join(self.base_dir, "icons"))
        
        # Gắn sự kiện đóng cửa sổ
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Thiết lập Drag and Drop
        try:
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', self.drop_files)
        except Exception:
            # Nếu drag and drop không được hỗ trợ, tiếp tục chạy bình thường
            pass 

        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            self._register_open_with()

        # --- Giao diện người dùng (GUI) ---
        
        # 1. Khung điều khiển trên cùng (Top Frame)
        top_frame = tk.Frame(root, pady=10, bg="#e1e1e1")
        top_frame.pack(side=tk.TOP, fill=tk.X)
        # 1.1. Điều khiển canh trái trên cùng
        font_size_top = 11   # font size mặc định để icon size thay đổi theo font size (icon size = font size * 2)
        self.btn_open_pdf = self.icon_manager.create_button_with_icon(top_frame, 'open_pdf.png', (font_size_top * 2, font_size_top * 2), "Open PDF", self.select_file, text_color="#FE3D03", font_size=font_size_top, font_weight="bold")
        self.btn_open_pdf.pack(side=tk.LEFT, padx=(10, 5), pady=(5, 5))
        Tooltip(self.btn_open_pdf, "Tìm file PDF để mở và quản lý\n(hoặc kéo thả PDF vào khung nội dung)")

        # self.btn_close_pdf = self.icon_manager.create_button_with_icon(top_frame, 'reset.png', (font_size_top * 2, font_size_top * 2), "Close PDF", self.close_pdf, text_color="#B00020", font_size=font_size_top, state=tk.DISABLED)
        self.btn_close_pdf=tk.Button(top_frame, width=14, text="✖ Close PDF", command=self.close_pdf, fg="#F88D01", font=("Consolas", font_size_top,"bold"), padx=2, state=tk.DISABLED)
        self.btn_close_pdf.pack(side=tk.LEFT, padx=(10, 5), pady=(5, 5))
        Tooltip(self.btn_close_pdf, "Đóng PDF hiện tại")
        self.lbl_file_info = tk.Label(top_frame, width=95, text="Chưa chọn file nào", anchor='w', bg="#e1e1e1", font=("Tahoma", 9))
        self.lbl_file_info.pack(side=tk.LEFT)
        Tooltip(self.lbl_file_info, "Thông tin file PDF hiện tại")
        
        # 1.2. Điều khiển canh phải trên cùng
        self.btn_save = self.icon_manager.create_button_with_icon(top_frame, 'save_pdf.png', (font_size_top * 2, font_size_top * 2), "SaveAs PDF", self.save_pdf, text_color="#00820F", font_size=font_size_top, state=tk.DISABLED)
        self.btn_save.pack(side=tk.RIGHT, padx=(5, 29))
        Tooltip(self.btn_save, "Lưu file PDF mới sau khi đã chỉnh sửa")

        # 2. Khung điều khiển hành động quản lý (Action Frame)
        action_frame = tk.Frame(root, pady=5, bg="#f0f0f0")
        action_frame.pack(side=tk.TOP, fill=tk.X)
        # 2.1. Điều khiển canh trái hành động
        
        # bỏ nhãn này không cần thiết (muốn lấy lại thì xóa dấu # ở đầu dòng)
        # tk.Label(action_frame, text="Chọn trang bên dưới và nhấn lệnh:", bg="#f0f0f0", font=("Consolas", 11)).pack(side=tk.LEFT, padx=(10,5))

        font_size_action = 11
        # btn_add_pdf = self.icon_manager.create_button_with_icon(action_frame, 'add_pdf.png', (font_size_action * 2, font_size_action * 2), "Add PDF", self.add_pdf, text_color="#009DFF", font_size=font_size_action, font_weight="bold")
        btn_add_pdf = tk.Button(action_frame, text="➕ Add PDF", command=self.add_pdf, fg="#009DFF", font=("Consolas", font_size_action, "bold"))
        btn_add_pdf.pack(side=tk.LEFT, padx=(10,10))
        Tooltip(btn_add_pdf, "Nối file PDF khác vào trước hoặc sau\ndanh sách trang của file PDF đang mở")

        # self.btn_select_all = self.icon_manager.create_button_with_icon(action_frame, 'select_all.png', (font_size_action * 2, font_size_action * 2), "Select All", self.toggle_select_all, text_color="#9400D3", font_size=font_size_action)
        self.btn_select_all = tk.Button(action_frame, width=14, text="☑ Select All", command=self.toggle_select_all, fg="#9400D3", font=("Consolas", font_size_action))
        self.btn_select_all.pack(side=tk.LEFT, padx=(5,5))
        Tooltip(self.btn_select_all, "Chọn hoặc bỏ chọn tất cả các trang hiển thị")

        btn_rotate_cw = self.icon_manager.create_button_with_icon(action_frame, 'rotate_cw.png', (font_size_action * 2, font_size_action * 2), "+90°", lambda: self.rotate_selected_pages(90), text_color="blue", font_size=font_size_action)
        btn_rotate_cw.pack(side=tk.LEFT, padx=(5,1))
        Tooltip(btn_rotate_cw, "Xoay các trang đã chọn 90° (sang phải)\ntheo chiều kim đồng hồ")

        btn_rotate_ccw = self.icon_manager.create_button_with_icon(action_frame, 'rotate_ccw.png', (font_size_action * 2, font_size_action * 2), "-90°", lambda: self.rotate_selected_pages(-90), text_color="blue", font_size=font_size_action)
        btn_rotate_ccw.pack(side=tk.LEFT, padx=(1,1))
        Tooltip(btn_rotate_ccw, "Xoay các trang đã chọn 90° (sang trái)\nngược chiều kim đồng hồ")

        # btn_rotate_180 = self.icon_manager.create_button_with_icon(action_frame, 'rotate_180.png', (font_size_action * 2, font_size_action * 2), "180°", lambda: self.rotate_selected_pages(180), text_color="blue", font_size=font_size_action)
        btn_rotate_180 = tk.Button(action_frame, text="⇅ 180°", command=lambda: self.rotate_selected_pages(180), fg="blue", font=("Consolas", font_size_action))
        btn_rotate_180.pack(side=tk.LEFT, padx=(1,1))
        Tooltip(btn_rotate_180, "Xoay các trang đã chọn ngược 180°")

        # btn_rotate_reset = self.icon_manager.create_button_with_icon(action_frame, 'reset.png', (font_size_action * 2, font_size_action * 2), "Reset 0°", self.reset_all_selected_pages, text_color="#9400D3", font_size=font_size_action)
        btn_rotate_reset = tk.Button(action_frame, text="↺ Reset 0°", command=self.reset_all_selected_pages, fg="#9400D3", font=("Consolas", font_size_action))
        btn_rotate_reset.pack(side=tk.LEFT, padx=(1,5))
        Tooltip(btn_rotate_reset, "Reset lại các trang đã chọn về 0°\n(trạng thái ban đầu khi mở file)")

        btn_move_up = self.icon_manager.create_button_with_icon(action_frame, 'move_up.png', (font_size_action * 2, font_size_action * 2), "Move Up", lambda: self.move_selected_pages(-1), text_color="#0066CC", font_size=font_size_action)
        btn_move_up.pack(side=tk.LEFT, padx=(5,1))
        Tooltip(btn_move_up, "Di chuyển các trang đã chọn lên trên\nmột vị trí trong danh sách")
        
        btn_move_down = self.icon_manager.create_button_with_icon(action_frame, 'move_down.png', (font_size_action * 2, font_size_action * 2), "Move Down", lambda: self.move_selected_pages(1), text_color="#0066CC", font_size=font_size_action)
        btn_move_down.pack(side=tk.LEFT, padx=(1,5))
        Tooltip(btn_move_down, "Di chuyển các trang đã chọn xuống dưới\nmột vị trí trong danh sách")
        
        btn_delete = self.icon_manager.create_button_with_icon(action_frame, 'delete.png', (font_size_action * 2, font_size_action * 2), "Delete", self.delete_selected_pages, text_color="#DC143C", font_size=font_size_action, font_weight="bold")
        btn_delete.pack(side=tk.LEFT, padx=(5,10))
        Tooltip(btn_delete, "Xóa các trang đã chọn khỏi danh sách (không thể khôi phục sau khi đã lưu file PDF mới)",show_duration=3000)

        # 2.2. Điều khiển canh phải hành động
        btn_reset_all = tk.Button(action_frame, width=13, text="⎌ Reset All", command=self.reset_all, fg="#9400D3", font=("Consolas", 11, "bold"))
        btn_reset_all.pack(side=tk.RIGHT, padx=(10,29))
        Tooltip(btn_reset_all, "Hoàn tác tất cả các thay đổi (xoay, xóa trang, di chuyển, thêm PDF) và tải lại file PDF ban đầu",show_duration=3000)

        self.action_widgets = [
            btn_add_pdf,
            self.btn_select_all,
            btn_rotate_cw,
            btn_rotate_ccw,
            btn_rotate_180,
            btn_rotate_reset,
            btn_move_up,
            btn_move_down,
            btn_delete,
            btn_reset_all,
        ]
        
        # 3. Khu vực hiển thị chính (Scrollable Canvas)
        main_container = tk.Frame(root)
        main_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=(10,10), pady=(0,10))

        self.canvas = tk.Canvas(main_container, bg="gray")
        self.scrollbar_y = ttk.Scrollbar(main_container, orient="vertical", command=self.canvas.yview)
        scrollbar_x = ttk.Scrollbar(main_container, orient="horizontal", command=self.canvas.xview)
        self.scrollable_frame = tk.Frame(self.canvas, bg="gray")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas.create_window((0, 0), window=self.scrollable_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self._on_yscroll_set, xscrollcommand=scrollbar_x.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar_y.grid(row=0, column=1, sticky="ns")
        scrollbar_x.grid(row=1, column=0, sticky="ew")
        main_container.grid_rowconfigure(0, weight=1)
        main_container.grid_columnconfigure(0, weight=1)

        # Hỗ trợ cuộn chuột và zoom bằng Ctrl+cuộn chuột
        self.canvas.bind_all("<MouseWheel>", self.on_mouse_wheel)
        
        # 5. Khung giới thiệu (Bottom Frame)
        about_frame = tk.Frame(root, pady=10, bg="#e1e1e1")
        about_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.lbl_about = tk.Label(about_frame, text="Copyright © 2026 by Hailúa", bg="#e1e1e1", font=("Consolas", 10, "bold"))
        self.lbl_about.pack(side=tk.LEFT, padx=(10, 6))

        link_url = "https://github.com/farmertek/pdf-manager"
        self.lbl_about_link = tk.Label(
            about_frame,
            text=link_url,
            bg="#e1e1e1",
            fg="#0066CC",
            cursor="hand2",
            font=("Consolas", 10, "underline")
        )
        self.lbl_about_link.pack(side=tk.LEFT, padx=(0, 20))
        self.lbl_about_link.bind("<Button-1>", lambda _e: webbrowser.open_new(link_url))

        # 5. Khung điều khiển dưới cùng (Bottom Frame)
        # 5.1. Các điều khiển canh trái dưới cùng
        # Thống kê
        view_frame = tk.Frame(root, pady=10, bg="#e1e1e1")
        view_frame.pack(side=tk.BOTTOM, fill=tk.X)
        
        self.lbl_page_count = tk.Label(view_frame, text="Tổng số trang: 0", bg="#e1e1e1", font=("Consolas", 11, "bold"))
        self.lbl_page_count.pack(side=tk.LEFT, padx=(10, 20))
        
        self.lbl_selected_count = tk.Label(view_frame, text="| Đã chọn: 0", bg="#e1e1e1", font=("Consolas", 11, "bold"), fg="#D26D01")
        self.lbl_selected_count.pack(side=tk.LEFT, padx=(0, 20))

        # 5.2.Các điều khiển canh phải dưới cùng
        # Zoom controls (canh phải nên dùng pack side=tk.RIGHT và đảo ngược thứ tự so với canh trái)
        # nút Apply Zoom
        btn_apply_zoom = tk.Button(view_frame, text="Apply", command=self.apply_zoom, font=("Consolas", 11))
        btn_apply_zoom.pack(side=tk.RIGHT, padx=(1,29))
        Tooltip(btn_apply_zoom, "Nhấn để áp dụng zoom PDF\ntheo tỷ lệ đã nhập trong ô zoom")

        # ô nhập tỷ lệ zoom
        self.zoom_entry = tk.Entry(view_frame, width=5, font=("Consolas", 11))
        self.zoom_entry.insert(0, "80")  # Mặc định 80%
        self.zoom_entry.pack(side=tk.RIGHT, padx=(2,1))
        self.zoom_entry.bind("<Return>", lambda e: self.apply_zoom())
        Tooltip(self.zoom_entry, "Nhập tỷ lệ zoom PDF (%)\nvà nhấn Enter hoặc Apply")
        # nhãn Zoom
        tk.Label(view_frame, text="Zoom (%):", bg="#e1e1e1", font=("Consolas", 11)).pack(side=tk.RIGHT, padx=(28, 5))

        self.bottom_widgets = [btn_apply_zoom, self.zoom_entry]

        self._set_ui_state(False)
        self._show_window()
        

    # --- Các hàm xử lý logic ---
    
    def _create_temp_dir(self):
        """Tạo thư mục temp nếu chưa có"""
        try:
            os.makedirs(self.temp_dir, exist_ok=True)
        except Exception as e:
            print(f"Lỗi khi tạo temp folder: {e}")

    def _show_window(self):
        """Đảm bảo cửa sổ hiển thị sau khi khởi tạo."""
        try:
            self.root.update_idletasks()
            self.root.deiconify()
            self.root.state("normal")
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass
    
    def _backup_pdf(self, keep_combined=False):
        """Backup PDF hiện tại vào temp folder"""
        try:
            self._cleanup_temp(keep_combined=keep_combined)  # Xóa backup cũ
            if self.current_pdf_path and os.path.exists(self.current_pdf_path):
                filename = os.path.basename(self.current_pdf_path)
                self.backup_pdf_path = os.path.join(self.temp_dir, f"backup_{filename}")
                shutil.copy2(self.current_pdf_path, self.backup_pdf_path)
        except Exception as e:
            print(f"Lỗi backup PDF: {e}")
    
    def _cleanup_temp(self, keep_combined=False):
        """Xóa file backup trong temp folder"""
        try:
            if self.backup_pdf_path and os.path.exists(self.backup_pdf_path):
                os.remove(self.backup_pdf_path)
                self.backup_pdf_path = None
            if (not keep_combined) and self.combined_pdf_path and os.path.exists(self.combined_pdf_path):
                os.remove(self.combined_pdf_path)
                self.combined_pdf_path = None
        except Exception as e:
            print(f"Lỗi cleanup backup: {e}")
    
    def _cleanup_all_temp(self):
        """Xóa toàn bộ temp folder khi đóng ứng dụng"""
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            print(f"Lỗi cleanup temp folder: {e}")

    def _set_ui_state(self, has_pdf):
        state = tk.NORMAL if has_pdf else tk.DISABLED
        if self.btn_open_pdf:
            self.btn_open_pdf.config(state=tk.DISABLED if has_pdf else tk.NORMAL)
        if self.btn_close_pdf:
            self.btn_close_pdf.config(state=tk.NORMAL if has_pdf else tk.DISABLED)
        if self.btn_save:
            self.btn_save.config(state=state if has_pdf else tk.DISABLED)  # type: ignore

        for widget in self.action_widgets:
            try:
                widget.config(state=state)
            except Exception:
                pass

        for widget in self.bottom_widgets:
            try:
                widget.config(state=state)
            except Exception:
                pass

    def _is_path_in_temp(self, path):
        try:
            temp_root = os.path.abspath(self.temp_dir)
            target = os.path.abspath(path)
            return target.startswith(temp_root + os.sep)
        except Exception:
            return False

    def _register_open_with(self):
        if winreg is None:
            return
        try:
            exe_path = os.path.abspath(sys.executable)
            exe_name = os.path.basename(exe_path)
            app_root = f"Software\\Classes\\Applications\\{exe_name}"
            command_key = app_root + "\\shell\\open\\command"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_key) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}" "%1"')

            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, app_root) as key:
                winreg.SetValueEx(key, "FriendlyAppName", 0, winreg.REG_SZ, "PDF Manager")

            default_icon_key = app_root + "\\DefaultIcon"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, default_icon_key) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}",0')

            self._add_to_open_with_list(exe_name)
        except Exception:
            return

    def _add_to_open_with_list(self, exe_name):
        if winreg is None:
            return
        try:
            owl_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\OpenWithList"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, owl_path) as key:
                existing = {}
                idx = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, idx)
                        existing[name] = value
                        idx += 1
                    except OSError:
                        break

                if exe_name in existing.values():
                    return

                for letter in "abcdefghijklmnopqrstuvwxyz":
                    if letter not in existing:
                        winreg.SetValueEx(key, letter, 0, winreg.REG_SZ, exe_name)
                        mru = existing.get("MRUList", "")
                        if letter not in mru:
                            mru = letter + mru
                        winreg.SetValueEx(key, "MRUList", 0, winreg.REG_SZ, mru)
                        break
        except Exception:
            return

    def _update_file_info_label(self):
        if not self.current_pdf_path:
            self.lbl_file_info.config(text="Chưa chọn file nào")
            return
        if self.opened_file_count > 1:
            self.lbl_file_info.config(text=f"Đang mở: {self.opened_file_count} file PDF")
        else:
            self.lbl_file_info.config(text=f"Đang mở: {os.path.basename(self.current_pdf_path)}")

    def open_pdf_file(self, file_path):
        """
        Mở file PDF từ đường dẫn được cung cấp
        
        Args:
            file_path: Đường dẫn file PDF sẽ mở
            
        Returns:
            True nếu mở thành công, False nếu thất bại
        """
        if not file_path or not os.path.exists(file_path):
            messagebox.showerror("Lỗi", "File không tồn tại hoặc đường dẫn không hợp lệ.")
            return False
        
        if not file_path.lower().endswith('.pdf'):
            messagebox.showerror("Lỗi", "Chỉ chấp nhận file PDF (.pdf)")
            return False
        
        # Kiểm tra và remove restrictions nếu có
        if not self.check_and_remove_pdf_restrictions(file_path):
            return False  # Nếu file bị khóa không thể remove, không mở
        
        # === GIẢI PHÓNG BỘ NHỚ FILE CŨ TRƯỚC KHI MỞ FILE MỚI ===
        self._close_fitz_doc()
        self._force_cleanup_all_images()
        
        self.current_pdf_path = file_path
        self.opened_file_count = 1
        self._update_file_info_label()
        self.rotation_states = {} # Reset trạng thái xoay khi mở file mới
        self.initial_rotation_states = {}  # Reset trạng thái ban đầu
        self.deleted_pages = set()  # Reset các trang bị xóa
        self._backup_pdf()  # Backup PDF vào temp folder
        self.btn_save.config(state=tk.NORMAL)  # type: ignore
        self.select_all_state = False  # Reset trạng thái Select All
        self.btn_select_all.config(text="☑ Select All")  # type: ignore
        self.load_pdf_thumbnails()
        self.update_page_count()
        self._set_ui_state(True)
        return True

    def select_file(self):
        file_paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if not file_paths:
            return
        self.open_pdf_files(list(file_paths))

    def drop_files(self, event):
        """Xử lý sự kiện thả file được kéo (drag and drop)"""
        try:
            # event.data chứa danh sách file được thả
            files = self.root.tk.splitlist(event.data)
            if files:
                # Chuẩn hóa danh sách file (loại bỏ {})
                file_paths = [f.strip('{}') for f in files if f]
                if not self.current_pdf_path:
                    # Chưa mở file nào -> mở nhiều file như Open PDF
                    self.open_pdf_files(file_paths)
                    return
                
                # Đang mở PDF -> hỏi thêm đầu/cuối rồi nối như Add PDF
                response = messagebox.askyesnocancel(
                    "Chọn vị trí thêm PDF",
                    "Mặc định PDF mới sẽ được thêm vào cuối PDF hiện tại (sau trang cuối cùng). Bạn muốn thêm PDF ở đâu?\n\nYes: Thêm vào cuối PDF (mặc định)\nNo: Thêm vào đầu PDF (không mặc định)\nCancel: Hủy"
                )
                if response is None:
                    return
                if response:
                    self._append_pdf_files(file_paths, position="end", show_message=True)
                else:
                    self._append_pdf_files(file_paths, position="start", show_message=True)
        except Exception as e:
            messagebox.showerror("Lỗi Drag and Drop", f"Không thể xử lý file được kéo thả:\n{str(e)}")

    def open_pdf_files(self, file_paths):
        """Mở nhiều file PDF cùng lúc (gộp vào một file tạm để Reset All khôi phục đầy đủ)."""
        if not file_paths:
            return False
        
        # Lọc file PDF hợp lệ
        valid_paths = [p for p in file_paths if p and p.lower().endswith('.pdf')]
        if not valid_paths:
            messagebox.showerror("Lỗi", "Chỉ chấp nhận file PDF (.pdf)")
            return False
        
        # Kiểm tra restrictions cho từng file
        for p in list(valid_paths):
            if not self.check_and_remove_pdf_restrictions(p):
                valid_paths.remove(p)
        if not valid_paths:
            return False
        if len(valid_paths) == 1:
            return self.open_pdf_file(valid_paths[0])
        
        # === GIẢI PHÓNG BỘ NHỚ FILE CŨ TRƯỚC KHI MỞ FILE MỚI ===
        self._close_fitz_doc()
        self._force_cleanup_all_images()
        
        # Gộp tất cả file vào file tạm
        combined_path, total_pages = self._build_combined_pdf(valid_paths)
        if not combined_path:
            return False
        
        self.current_pdf_path = combined_path
        self.opened_file_count = len(valid_paths)
        self._update_file_info_label()
        self.rotation_states = {}
        self.initial_rotation_states = {}
        self.deleted_pages = set()
        self._backup_pdf(keep_combined=True)
        self.btn_save.config(state=tk.NORMAL)  # type: ignore
        self.select_all_state = False
        self.btn_select_all.config(text="☑ Select All")  # type: ignore
        self.load_pdf_thumbnails()
        self.update_page_count()
        self._set_ui_state(True)
        
        messagebox.showinfo(
            "Thành công",
            f"Đã mở {len(valid_paths)} file PDF với tổng {total_pages} trang."
        )
        return True

    def close_pdf(self):
        """Đóng file PDF hiện tại và reset trạng thái UI"""
        if not self.current_pdf_path:
            return

        if self.is_file_modified():
            response = messagebox.askyesnocancel(
                "File chưa lưu",
                f"File '{os.path.basename(self.current_pdf_path)}' có thay đổi chưa được lưu.\n\nBạn có muốn lưu file trước khi đóng không?"
            )
            if response is None:
                return
            if response:
                self.save_pdf()
                if self.is_file_modified():
                    return

        self._close_fitz_doc()
        self._force_cleanup_all_images()

        self._cleanup_temp(keep_combined=False)
        if self.current_pdf_path and self._is_path_in_temp(self.current_pdf_path):
            try:
                if os.path.exists(self.current_pdf_path):
                    os.remove(self.current_pdf_path)
            except Exception:
                pass

        self.current_pdf_path = None
        self.opened_file_count = 0
        self.backup_pdf_path = None
        self.combined_pdf_path = None
        self.rotation_states = {}
        self.initial_rotation_states = {}
        self.deleted_pages = set()
        self.select_all_state = False
        if self.btn_select_all:
            self.btn_select_all.config(text="☑ Select All")

        self._update_file_info_label()
        self.lbl_selected_count.config(text="| Đã chọn: 0")
        self.update_page_count()
        self._set_ui_state(False)

    def _build_combined_pdf(self, file_paths):
        """Gộp nhiều PDF thành 1 file tạm, trả về (path, total_pages)."""
        try:
            # Xóa file tạm cũ nếu có
            if self.combined_pdf_path and os.path.exists(self.combined_pdf_path):
                os.remove(self.combined_pdf_path)
            
            combined_name = "combined_open.pdf"
            self.combined_pdf_path = os.path.join(self.temp_dir, combined_name)
            
            writer = PdfWriter()
            total_pages = 0
            for p in file_paths:
                reader = PdfReader(p)  # type: ignore
                for page in reader.pages:
                    writer.add_page(page)
                total_pages += len(reader.pages)
            
            with open(self.combined_pdf_path, "wb") as f:  # type: ignore
                writer.write(f)
            return self.combined_pdf_path, total_pages
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể gộp file PDF: {e}")
            return None, 0

    def _append_pdf_file(self, file_path):
        """Nối file PDF vào cuối file hiện tại (dùng cho drag & drop)."""
        if not file_path:
            return
        self._append_pdf_files([file_path], position="end", show_message=True)

    def check_and_remove_pdf_restrictions(self, file_path):
        """
        Kiểm tra xem file PDF có bị khóa (restrictions) hay không.
        Nếu có, cố gắng remove restrictions.
        
        Args:
            file_path: Đường dẫn file PDF
            
        Returns:
            True nếu file không bị khóa hoặc đã remove thành công restrictions
            False nếu file bị khóa không thể remove
        """
        try:
            # Mở file với pypdf để kiểm tra encryption
            reader = PdfReader(file_path)  # type: ignore
            
            # Kiểm tra xem file có bị encrypt không
            if reader.is_encrypted:
                # Cố gắng decrypt với password rỗng
                is_decrypted = reader.decrypt("")
                
                if not is_decrypted:
                    # Không thể decrypt → file có password → không thể edit
                    messagebox.showerror(
                        "File bị khóa",
                        f"File PDF '{os.path.basename(file_path)}' bị khóa bằng password.\n"
                        "Không thể mở khóa file mà không có password.\n\n"
                        "Vui lòng nhập password hoặc chọn file khác."
                    )
                    return False
                
                # Decrypt thành công → file chỉ có restrictions (không có password)
                # Tạo PDF mới không có restrictions (không hiển thị thông báo thành công)
                try:
                    writer = PdfWriter()
                    
                    # Copy tất cả pages từ reader sang writer
                    for page_num in range(len(reader.pages)):
                        page = reader.pages[page_num]
                        writer.add_page(page)
                    
                    # Ghi PDF mới không có restrictions
                    with open(file_path, "wb") as output_file:
                        writer.write(output_file)
                    
                    return True
                    
                except Exception as e:
                    messagebox.showerror(
                        "Lỗi",
                        f"Không thể mở khóa file PDF:\n{str(e)}\n\n"
                        "Vui lòng kiểm tra file và thử lại."
                    )
                    return False
            else:
                # File không bị encrypt → không có restrictions
                return True
                
        except Exception as e:
            messagebox.showerror(
                "Lỗi",
                f"Không thể kiểm tra file PDF:\n{str(e)}\n\n"
                "Vui lòng kiểm tra file và thử lại."
            )
            return False

    def load_pdf_thumbnails(self):
        """Tải PDF với lazy loading - chỉ render các trang đang hiển thị trong viewport"""
        # Đóng document cũ nếu có
        self._close_fitz_doc()
        
        # === GIẢI PHÓNG TRIỆT ĐỂ: ảnh, widgets, traces, refs ===
        # _force_cleanup_all_images đã xử lý: destroy widgets, clear lists, gc.collect, trim
        self._force_cleanup_all_images()
        
        self._layout_dirty = True  # Đánh dấu layout đang thay đổi
        
        # Tạo ảnh 1x1 pixel cho placeholder sizing (chỉ tạo 1 lần)
        if self._pixel_img is None:
            self._pixel_img = tk.PhotoImage(width=1, height=1)
        
        try:
            self.fitz_doc = fitz.open(self.current_pdf_path)
            
            # Tính số cột dựa trên mức zoom
            if self.zoom_level <= 0.25:
                columns_per_row = 5
            elif self.zoom_level <= 0.52:
                columns_per_row = 3
            elif self.zoom_level <= 0.80:
                columns_per_row = 2
            else:
                columns_per_row = 1
            
            row_count = 0
            col_count = 0
            visual_idx = 0
            
            for i in range(len(self.fitz_doc)):
                # Bỏ qua các trang bị xóa
                if i in self.deleted_pages:
                    continue
                
                page = self.fitz_doc[i]
                
                # Tính kích thước placeholder dựa trên kích thước trang và zoom
                rect = page.rect
                base_w = int(rect.width * self.zoom_level)
                base_h = int(rect.height * self.zoom_level)
                
                # Xử lý kích thước xoay
                current_angle = self.rotation_states.get(i, 0)
                if current_angle % 180 == 90:
                    base_w, base_h = base_h, base_w
                
                # Đảm bảo kích thước tối thiểu
                base_w = max(base_w, 50)
                base_h = max(base_h, 50)
                
                # 1. Tạo khung chứa cho mỗi trang (placeholder - chưa render ảnh)
                page_container = tk.Frame(self.scrollable_frame, bg="white", bd=2, relief=tk.RIDGE)
                page_container.grid(row=row_count, column=col_count, padx=10, pady=10, sticky="nsew")
                
                # 2. Header: Trang và góc xoay
                header_frame = tk.Frame(page_container, bg="lightblue")
                header_frame.pack(fill=tk.X)
                
                chk_var = tk.IntVar()
                
                chk = tk.Checkbutton(header_frame, text=f"Trang {i+1}", variable=chk_var, bg="lightblue", font=("consolas", 10, "bold"))
                chk.pack(side=tk.LEFT, padx=5)
                
                rotation_angle = self.rotation_states.get(i, 0)
                lbl_angle = tk.Label(header_frame, text=f"Current: {rotation_angle}°", bg="lightblue", font=("consolas", 9, "bold"), fg="darkgreen")
                lbl_angle.pack(side=tk.LEFT, padx=10)
                
                color_elements = {
                    'header': header_frame,
                    'checkbox': chk,
                    'label': lbl_angle
                }
                
                on_change = lambda *args, var=chk_var, elements=color_elements: self.update_page_colors(var, elements)
                chk_var.trace("w", on_change)
                
                # 3. Placeholder image (dùng pixel image trick để set kích thước pixel)
                # Chỉ tạo khung giữ chỗ, ảnh thật sẽ được render khi trang hiển thị (lazy loading)
                lbl_img = tk.Label(page_container, image=self._pixel_img, width=base_w, height=base_h, bg="#d0d0d0", compound='center')
                lbl_img.pack()
                
                # Bind click event vào toàn bộ trang để toggle selection
                for w in [page_container, header_frame, chk, lbl_angle, lbl_img]:
                    w.bind("<Button-1>", lambda event, var=chk_var: self.toggle_page_selection(var))
                
                # Lưu thông tin trang cho lazy loading
                page_info = {
                    'visual_idx': visual_idx,
                    'original_idx': i,
                    'container': page_container,
                    'lbl_img': lbl_img,
                    'rendered': False,
                    'photo': None,
                    'width': base_w,
                    'height': base_h,
                }
                
                self.page_data.append(page_info)
                self.page_checkboxes.append(chk_var)
                self.page_original_indices.append(i)
                self.page_color_elements.append(color_elements)
                self.page_containers.append(page_container)
                
                visual_idx += 1
                col_count += 1
                if col_count >= columns_per_row:
                    col_count = 0
                    row_count += 1
            
            self.update_selected_count()
            
            # Bỏ flag layout_dirty và lên lịch render các trang hiển thị
            self._layout_dirty = False
            self.root.after(100, self._check_visible_pages)
            
        except Exception as e:
            self._layout_dirty = False
            messagebox.showerror("Lỗi", f"Không thể đọc file PDF: {e}")

    def toggle_page_selection(self, chk_var):
        """Toggle trạng thái checkbox khi click vào trang"""
        current_value = chk_var.get()
        chk_var.set(1 - current_value)  # Toggle giữa 0 và 1

    # --- Lazy Loading Methods ---
    
    def _close_fitz_doc(self):
        """Đóng fitz document để giải phóng file lock và bộ nhớ"""
        if self.fitz_doc:
            try:
                self.fitz_doc.close()
            except Exception:
                pass
            self.fitz_doc = None
        # Thu nhỏ cache MuPDF sau khi đóng document
        self._shrink_fitz_cache()

    def _shrink_fitz_cache(self):
        """Thu nhỏ cache nội bộ của MuPDF để giải phóng RAM."""
        try:
            if hasattr(fitz, "TOOLS") and hasattr(fitz.TOOLS, "store_shrink"):
                fitz.TOOLS.store_shrink(100)
        except Exception:
            pass
    
    def _force_cleanup_all_images(self):
        """Dọn dẹp triệt để: ảnh, widgets, traces, callbacks — giải phóng RAM tối đa.
        
        QUAN TRỌNG - Thứ tự cleanup:
        1. Hủy tất cả pending timers (scroll, zoom)
        2. Gỡ ảnh khỏi label widgets (Tcl/Tk bỏ internal reference)
        3. Xóa IntVar traces (phá vỡ circular references lambda→widgets→IntVar)
        4. XÓA TRỰC TIẾP Tcl image data qua 'image delete' (giải phóng pixel data NGAY)
        5. Destroy tất cả widgets
        6. Xóa mọi Python references
        7. Reset _pixel_img (sẽ tạo lại khi load file mới)
        8. gc.collect() + trim working set
        
        GHI CHÚ: Phải gọi Tcl 'image delete' trực tiếp vì Python GC không đảm bảo
        giải phóng Tcl image pixel data kịp thời — đây là nguyên nhân chính gây rò rỉ RAM.
        """
        # Bước 1: Hủy TẤT CẢ pending timers
        if self.scroll_check_timer:
            self.root.after_cancel(self.scroll_check_timer)
            self.scroll_check_timer = None
        if self.zoom_timer is not None:
            self.root.after_cancel(self.zoom_timer)
            self.zoom_timer = None
        
        # Bước 2: Gỡ ảnh khỏi label widgets (Tcl/Tk bỏ internal reference tới pixel data)
        for page_info in self.page_data:
            try:
                lbl = page_info.get('lbl_img')
                if lbl and lbl.winfo_exists():
                    lbl.config(image='')
            except (tk.TclError, Exception):
                pass
        
        # Bước 3: Xóa trace callbacks trên IntVars
        # (trace callback lambda capture color_elements → widgets → tạo circular ref)
        for chk_var in self.page_checkboxes:
            try:
                for trace_info in chk_var.trace_info():
                    chk_var.trace_remove(trace_info[0], trace_info[1])
            except Exception:
                pass
        
        # Bước 4: XÓA TRỰC TIẾP Tcl image pixel data (CRITICAL — giải phóng RAM ngay lập tức)
        # Gọi Tcl 'image delete' TRƯỚC KHI xóa Python references
        # Đây là bước quan trọng nhất: không phụ thuộc vào Python GC
        _deleted_tcl_names = set()
        for page_info in self.page_data:
            photo = page_info.get('photo')
            if photo is not None:
                try:
                    tcl_name = str(photo)
                    if tcl_name not in _deleted_tcl_names:
                        self.root.tk.call('image', 'delete', tcl_name)
                        _deleted_tcl_names.add(tcl_name)
                except (tk.TclError, Exception):
                    pass
                page_info['photo'] = None
        
        for vis_idx in list(self.page_images.keys()):
            photo = self.page_images[vis_idx]
            if photo is not None:
                try:
                    tcl_name = str(photo)
                    if tcl_name not in _deleted_tcl_names:
                        self.root.tk.call('image', 'delete', tcl_name)
                        _deleted_tcl_names.add(tcl_name)
                except (tk.TclError, Exception):
                    pass
        _deleted_tcl_names.clear()
        self.page_images.clear()
        self.page_images = {}
        
        # Bước 5: Destroy tất cả child widgets trong scrollable_frame
        try:
            for widget in self.scrollable_frame.winfo_children():
                widget.destroy()
        except tk.TclError:
            pass
        
        # Bước 6: Xóa mọi Python references
        for page_info in self.page_data:
            page_info.clear()
        self.page_data.clear()
        self.page_checkboxes.clear()
        self.page_color_elements.clear()
        self.page_containers.clear()
        self.page_original_indices.clear()
        self._gc_pending = 0
        
        # Bước 7: Reset _pixel_img (sẽ được tạo lại trong load_pdf_thumbnails)
        if self._pixel_img is not None:
            try:
                self.root.tk.call('image', 'delete', str(self._pixel_img))
            except (tk.TclError, Exception):
                pass
            self._pixel_img = None
        
        # Bước 8: Thu hồi bộ nhớ Python và trả về cho OS
        gc.collect()  # Generation 0+1+2
        gc.collect()  # Lần 2 cho circular refs phức tạp
        self._shrink_fitz_cache()
        self._trim_working_set()
    
    def _trim_working_set(self):
        """Yêu cầu Windows thu hồi bộ nhớ không dùng từ process (giảm RAM thực tế)."""
        try:
            if sys.platform == 'win32':
                ctypes.windll.kernel32.SetProcessWorkingSetSize(
                    ctypes.windll.kernel32.GetCurrentProcess(), -1, -1
                )
        except Exception:
            pass
    
    def _on_yscroll_set(self, *args):
        """Wrapper cho scrollbar set - kích hoạt kiểm tra lazy loading khi scroll"""
        self.scrollbar_y.set(*args)
        self._schedule_visibility_check()
    
    def _schedule_visibility_check(self):
        """Lên lịch kiểm tra trang hiển thị (debounced 50ms)"""
        if self.scroll_check_timer:
            self.root.after_cancel(self.scroll_check_timer)
        self.scroll_check_timer = self.root.after(50, self._check_visible_pages)
    
    def _check_visible_pages(self):
        """Kiểm tra và render/unload các trang dựa trên viewport hiện tại.
        Chỉ render trang đang hiển thị + buffer, giải phóng RAM cho trang ngoài viewport."""
        if not self.page_data or not self.fitz_doc or self._layout_dirty:
            return
        
        try:
            canvas_height = self.canvas.winfo_height()
            if canvas_height <= 1:  # Canvas chưa layout xong
                self.root.after(100, self._check_visible_pages)
                return
            
            viewport_top = self.canvas.canvasy(0)
            viewport_bottom = self.canvas.canvasy(canvas_height)
            
            # Buffer: pre-render thêm 0.5 viewport height ở trên và dưới cho cuộn mượt
            buffer = canvas_height * 0.5
            render_top = viewport_top - buffer
            render_bottom = viewport_bottom + buffer
            
            # GIỚI HẠN: Chỉ render tối đa 5 trang mỗi lần check để tránh RAM spike
            # Khi scroll nhanh hoặc zoom nhỏ có thể có 20-30 trang trong viewport
            # → render từng batch nhỏ, GC sau mỗi batch
            pages_to_render = []
            pages_to_unload = []
            
            for page_info in self.page_data:
                container = page_info['container']
                try:
                    if not container.winfo_exists():
                        continue
                    cy = container.winfo_y()
                    ch = container.winfo_height()
                    if ch <= 1:  # Widget chưa layout xong
                        continue
                    cb = cy + ch
                except tk.TclError:
                    continue
                
                in_render_zone = cb > render_top and cy < render_bottom
                
                if in_render_zone and not page_info['rendered']:
                    pages_to_render.append(page_info)
                elif not in_render_zone and page_info['rendered']:
                    pages_to_unload.append(page_info)
            
            # Unload các trang ngoài viewport trước (giải phóng RAM trước khi render mới)
            unloaded_count = 0
            for page_info in pages_to_unload:
                self._unload_page(page_info)
                unloaded_count += 1
            
            # Render từng batch nhỏ (tối đa 5 trang/lần) để tránh RAM spike
            rendered_count = 0
            for page_info in pages_to_render[:5]:  # Chỉ render 5 trang đầu
                self._render_page(page_info)
                rendered_count += 1
            
            # Nếu còn trang chưa render, lên lịch check tiếp sau 50ms
            if len(pages_to_render) > 5:
                self.root.after(50, self._check_visible_pages)
            
            # GC ngay sau khi render batch (giải phóng Pixmap/PIL.Image trung gian)
            if rendered_count > 0:
                gc.collect()
            
            # GC + trim khi có trang unload
            if unloaded_count > 0:
                self._gc_pending += unloaded_count
            if self._gc_pending >= 2:  # Sau mỗi 2 trang unload, chạy GC + trim
                self._gc_pending = 0
                gc.collect()
                self._shrink_fitz_cache()
                self._trim_working_set()
                
        except Exception as e:
            print(f"Lỗi kiểm tra trang hiển thị: {e}")
    
    def _get_dpi_quality(self):
        """Tính chất lượng DPI dựa trên zoom level"""
        if self.zoom_level <= 0.52:
            return 0.8
        elif self.zoom_level <= 0.80:
            return 0.9
        else:
            return 1.0
    
    def _render_page(self, page_info):
        """Render một trang PDF cụ thể từ fitz document (lazy loading)"""
        if page_info['rendered'] or not self.fitz_doc:
            return
        
        original_idx = page_info['original_idx']
        dpi_quality = self._get_dpi_quality()
        page = None
        pix = None
        img = None
        img_scaled = None
        img_rotated = None  # Init cho rotation edge case
        
        try:
            page = self.fitz_doc[original_idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(self.zoom_level * dpi_quality, self.zoom_level * dpi_quality))
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            
            # Giải phóng pixmap ngay sau khi đã copy dữ liệu sang PIL
            # PyMuPDF: gọi del để force drop reference, không cần set None trước
            del pix
            pix = None
            
            # Scale lại nếu DPI giảm
            if dpi_quality < 1.0:
                target_width = int(img.width * (1.0 / dpi_quality))
                target_height = int(img.height * (1.0 / dpi_quality))
                img_scaled = img.resize((target_width, target_height), Image.Resampling.LANCZOS)
                img.close()  # Đóng ảnh gốc ngay, chỉ giữ ảnh scaled
                img = img_scaled
                img_scaled = None
            
            # Xoay ảnh nếu cần
            current_angle = self.rotation_states.get(original_idx, 0)
            if current_angle != 0:
                img_rotated = img.rotate(-current_angle, expand=True)
                img.close()  # Đóng ảnh trước khi xoay
                img = img_rotated
                img_rotated = None  # Drop reference trung gian
            
            photo = ImageTk.PhotoImage(img)
            
            # Đóng PIL Image ngay sau khi đã tạo PhotoImage (dữ liệu đã copy sang Tcl/Tk)
            img.close()
            img = None
            
            # Cập nhật label: bỏ placeholder, hiển thị ảnh thật
            page_info['lbl_img'].config(image=photo, width=0, height=0, bg="gray")
            page_info['photo'] = photo
            page_info['rendered'] = True
            self.page_images[page_info['visual_idx']] = photo  # Giữ tham chiếu
            
        except Exception as e:
            print(f"Lỗi render trang {original_idx}: {e}")
        finally:
            # Đảm bảo dọn dẹp mọi đối tượng trung gian dù có lỗi hay không
            if img is not None:
                try:
                    img.close()
                except Exception:
                    pass
                img = None
            if img_scaled is not None:
                try:
                    img_scaled.close()
                except Exception:
                    pass
                img_scaled = None
            if img_rotated is not None:
                try:
                    img_rotated.close()
                except Exception:
                    pass
                img_rotated = None
            pix = None
            page = None  # Giải phóng fitz.Page reference
    
    def _unload_page(self, page_info):
        """Giải phóng bộ nhớ của trang không hiển thị - thay bằng placeholder để giảm RAM.
        Gọi Tcl 'image delete' trực tiếp để giải phóng pixel data ngay lập tức."""
        if not page_info['rendered']:
            return
        
        # Lấy tên Tcl image TRƯỚC KHI thay đổi bất kỳ reference nào
        old_photo = page_info.get('photo')
        tcl_name = None
        if old_photo is not None:
            try:
                tcl_name = str(old_photo)
            except Exception:
                pass
        
        try:
            # Thay ảnh thật bằng placeholder (Tcl/Tk bỏ reference tới image)
            page_info['lbl_img'].config(
                image=self._pixel_img,
                width=page_info['width'],
                height=page_info['height'],
                bg="#d0d0d0"
            )
        except tk.TclError:
            pass
        
        # Xóa Python references
        vis_idx = page_info['visual_idx']
        if vis_idx in self.page_images:
            del self.page_images[vis_idx]
        page_info['photo'] = None
        page_info['rendered'] = False
        old_photo = None  # Drop local reference
        
        # XÓA TRỰC TIẾP Tcl image data — giải phóng RAM ngay lập tức
        if tcl_name:
            try:
                self.root.tk.call('image', 'delete', tcl_name)
            except (tk.TclError, Exception):
                pass
        # Thu nhỏ cache MuPDF sau khi unload
        self._shrink_fitz_cache()

    def toggle_select_all(self):
        """Toggle giữa Select All và Deselect All"""
        if not self.page_checkboxes:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file PDF trước.")
            return
        
        # Kiểm tra xem tất cả các trang đã được chọn chưa
        all_selected = all(chk.get() == 1 for chk in self.page_checkboxes)
        
        # Toggle trạng thái: nếu tất cả đã chọn, bỏ chọn tất cả; ngược lại, chọn tất cả
        if all_selected:
            # Bỏ chọn tất cả
            for chk in self.page_checkboxes:
                chk.set(0)
            self.btn_select_all.config(text="☑ Select All")  # type: ignore
            self.select_all_state = False
        else:
            # Chọn tất cả
            for chk in self.page_checkboxes:
                chk.set(1)
            self.btn_select_all.config(text="☐ Deselect All")  # type: ignore
            self.select_all_state = True

    def update_page_colors(self, chk_var, color_elements):
        """Cập nhật màu của tất cả elements (header, checkbox, label) khi trang được chọn/bỏ chọn"""
        if chk_var.get() == 1:  # Trang được chọn
            color = "#FFA500"  # Màu cam (orange)
        else:  # Trang không được chọn
            color = "lightblue"
        
        # Cập nhật màu cho tất cả elements
        color_elements['header'].config(bg=color)
        color_elements['checkbox'].config(bg=color)
        color_elements['label'].config(bg=color)
        
        # Cập nhật số trang được chọn
        self.update_selected_count()

    def update_selected_count(self):
        """Cập nhật tổng số trang được chọn"""
        selected_count = sum(1 for chk in self.page_checkboxes if chk.get() == 1)
        self.lbl_selected_count.config(text=f"| Đã chọn: {selected_count}")

    def apply_zoom(self):
        """Áp dụng tỷ lệ zoom từ ô nhập liệu"""
        try:
            # Hủy timer zoom chuột nếu đang chạy
            if self.zoom_timer is not None:
                self.root.after_cancel(self.zoom_timer)
                self.zoom_timer = None
            
            zoom_percent = int(self.zoom_entry.get())
            if zoom_percent < 10 or zoom_percent > 500:
                messagebox.showerror("Lỗi", "Tỷ lệ zoom phải nằm trong khoảng 10% - 500%")
                return
            self.zoom_level = zoom_percent / 100
            if self.current_pdf_path:
                self.load_pdf_thumbnails()
        except ValueError:
            messagebox.showerror("Lỗi", "Vui lòng nhập một số nguyên hợp lệ")
    
    def on_mouse_wheel(self, event):
        """Xử lý cuộn chuột: normal scroll hoặc Ctrl+scroll để zoom"""
        # Kiểm tra xem Ctrl có được nhấn không
        if event.state & 0x4:  # 0x4 là mã cho phím Ctrl
            # Ctrl + scroll = zoom
            self.on_mouse_wheel_zoom(event)
        else:
            # Normal scroll
            self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")
            self._schedule_visibility_check()
    
    def on_mouse_wheel_zoom(self, event):
        """Zoom bằng Ctrl+scroll chuột (với debouncing để tránh lag)"""
        if not self.current_pdf_path:
            return
        
        # Tính toán zoom mới
        # delta > 0 = scroll up = zoom in, delta < 0 = scroll down = zoom out
        zoom_increment = 0.05  # Tăng/giảm 5% mỗi lần scroll
        
        if event.delta > 0:
            # Zoom in (scroll up / wheel up)
            new_zoom = self.zoom_level + zoom_increment
        else:
            # Zoom out (scroll down / wheel down)
            new_zoom = self.zoom_level - zoom_increment
        
        # Giới hạn zoom trong khoảng 10% - 500%
        new_zoom = max(0.10, min(5.00, new_zoom))
        
        # Cập nhật zoom level và entry (nhanh, không chờ)
        self.zoom_level = new_zoom
        zoom_percent = int(new_zoom * 100)
        self.zoom_entry.delete(0, tk.END)
        self.zoom_entry.insert(0, str(zoom_percent))
        
        # Hủy timer cũ nếu có (nếu user tiếp tục zoom trước khi thumbnails được tải lại)
        if self.zoom_timer is not None:
            self.root.after_cancel(self.zoom_timer)
        
        # Đánh dấu layout đang thay đổi - ngăn lazy loading render với zoom cũ
        self._layout_dirty = True
        
        # Lên lịch reload thumbnails sau 300ms (debouncing)
        # Cách này giúp zoom mượt vì chỉ reload một lần khi user dừng zoom
        self.zoom_timer = self.root.after(300, self.load_pdf_thumbnails)

    def rotate_selected_pages(self, angle_change):
        if not self.current_pdf_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file PDF trước.")
            return
        
        selected_visual = [i for i, chk_var in enumerate(self.page_checkboxes) if chk_var.get() == 1]
        any_selected = False
        for visual_idx in selected_visual:
            any_selected = True
            original_idx = self.page_original_indices[visual_idx]
            current_angle = self.rotation_states.get(original_idx, 0)
            new_angle = (current_angle + angle_change) % 360
            self.rotation_states[original_idx] = new_angle
        
        if any_selected:
            # Tải lại giao diện để hiển thị trạng thái xoay mới
            self.load_pdf_thumbnails()
            # Khôi phục lại trạng thái checkbox đã chọn
            for idx in selected_visual:
                if idx < len(self.page_checkboxes):
                    self.page_checkboxes[idx].set(1)
        else:
            messagebox.showinfo("Thông báo", "Bạn chưa chọn trang nào để xoay.")

    def apply_rotation(self, angle):
        """Áp dụng góc xoay (không đóng dialog)"""
        selected_visual = [i for i, chk in enumerate(self.page_checkboxes) if chk.get() == 1]
        for visual_idx in selected_visual:
            original_idx = self.page_original_indices[visual_idx]
            current_angle = self.rotation_states.get(original_idx, 0)
            new_angle = (current_angle + angle) % 360
            self.rotation_states[original_idx] = new_angle
        self.load_pdf_thumbnails()
        # Khôi phục checkbox đã chọn
        for idx in selected_visual:
            if idx < len(self.page_checkboxes):
                self.page_checkboxes[idx].set(1)
    
    def reset_all_selected_pages(self):
        """Reset góc xoay của tất cả các trang được chọn về 0°"""
        selected_visual = [i for i, chk in enumerate(self.page_checkboxes) if chk.get() == 1]
        if not selected_visual:
            messagebox.showinfo("Thông báo", "Vui lòng chọn ít nhất 1 trang để reset.")
            return
        
        for visual_idx in selected_visual:
            original_idx = self.page_original_indices[visual_idx]
            self.rotation_states[original_idx] = 0
        self.load_pdf_thumbnails()
        # Khôi phục checkbox đã chọn
        for idx in selected_visual:
            if idx < len(self.page_checkboxes):
                self.page_checkboxes[idx].set(1)
    
    def move_selected_pages(self, direction):
        """Di chuyển các trang được chọn lên trên hoặc xuống dưới"""
        selected_pages = sorted([i for i, chk in enumerate(self.page_checkboxes) if chk.get() == 1])
        
        if not selected_pages:
            messagebox.showinfo("Thông báo", "Vui lòng chọn ít nhất 1 trang để di chuyển.")
            return
        
        # Không cho phép di chuyển khi có trang đã xóa (index mapping phức tạp)
        if self.deleted_pages:
            messagebox.showwarning("Cảnh báo", "Không thể di chuyển trang khi có trang đã xóa.\nVui lòng 'Reset All' hoặc lưu file trước khi di chuyển.")
            return
        
        # Đóng fitz document trước khi ghi file
        self._close_fitz_doc()
        
        try:
            # Đọc file hiện tại
            reader = PdfReader(self.current_pdf_path)  # type: ignore
            pages_list = list(reader.pages)
            new_selected_pages: list[int] = []  # Khởi tạo biến
            
            # Di chuyển trang
            if direction == -1:  # Di chuyển lên trên
                # Kiểm tra xem trang đầu tiên có thể di chuyển được không
                if selected_pages[0] == 0:
                    messagebox.showinfo("Thông báo", "Không thể di chuyển - các trang đã ở vị trí đầu tiên.")
                    return
                
                # Di chuyển lên: lấy trang trước trang được chọn đầu tiên, sau đó insert vào cuối trang được chọn
                for idx in selected_pages:
                    page_to_move = pages_list.pop(idx - 1)
                    pages_list.insert(idx, page_to_move)
                
                # Cập nhật index trong rotation_states và deleted_pages
                self.update_page_indices_after_move(selected_pages, direction)
                
                # Tính vị trí mới của trang sau khi di chuyển
                new_selected_pages = [p - 1 for p in selected_pages]
            
            elif direction == 1:  # Di chuyển xuống dưới
                # Kiểm tra xem trang cuối cùng có thể di chuyển được không
                if selected_pages[-1] == len(pages_list) - 1:
                    messagebox.showinfo("Thông báo", "Không thể di chuyển - các trang đã ở vị trí cuối cùng.")
                    return
                
                # Di chuyển xuống: lấy trang sau trang được chọn cuối cùng, sau đó insert vào đầu trang được chọn
                for idx in reversed(selected_pages):
                    page_to_move = pages_list.pop(idx + 1)
                    pages_list.insert(idx, page_to_move)
                
                # Cập nhật index trong rotation_states và deleted_pages
                self.update_page_indices_after_move(selected_pages, direction)
                
                # Tính vị trí mới của trang sau khi di chuyển
                new_selected_pages = [p + 1 for p in selected_pages]
            
            # Ghi lại file
            writer = PdfWriter()
            for page in pages_list:
                writer.add_page(page)
            
            with open(self.current_pdf_path, "wb") as f:  # type: ignore
                writer.write(f)
            
            self.load_pdf_thumbnails()
            self.update_page_count()
            # Khôi phục checkbox ở vị trí MỚI
            for idx in new_selected_pages:
                if idx < len(self.page_checkboxes):
                    self.page_checkboxes[idx].set(1)
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể di chuyển trang: {e}")
    
    def update_page_indices_after_move(self, selected_pages, direction):
        """Cập nhật index trong rotation_states và deleted_pages sau khi di chuyển"""
        if direction == -1:  # Di chuyển lên
            # Cập nhật rotation_states
            new_rotation_states = {}
            for old_idx, angle in self.rotation_states.items():
                if old_idx in selected_pages:
                    new_rotation_states[old_idx - 1] = angle
                elif old_idx == selected_pages[0] - 1:
                    new_rotation_states[selected_pages[-1]] = new_rotation_states.get(selected_pages[-1], 0)
                else:
                    new_rotation_states[old_idx] = angle
            self.rotation_states = new_rotation_states
            
            # Cập nhật deleted_pages
            new_deleted_pages = set()
            for del_idx in self.deleted_pages:
                if del_idx in selected_pages:
                    new_deleted_pages.add(del_idx - 1)
                elif del_idx == selected_pages[0] - 1:
                    new_deleted_pages.add(selected_pages[-1])
                else:
                    new_deleted_pages.add(del_idx)
            self.deleted_pages = new_deleted_pages
        
        elif direction == 1:  # Di chuyển xuống
            # Cập nhật rotation_states
            new_rotation_states = {}
            for old_idx, angle in self.rotation_states.items():
                if old_idx in selected_pages:
                    new_rotation_states[old_idx + 1] = angle
                elif old_idx == selected_pages[-1] + 1:
                    new_rotation_states[selected_pages[0]] = new_rotation_states.get(selected_pages[0], 0)
                else:
                    new_rotation_states[old_idx] = angle
            self.rotation_states = new_rotation_states
            
            # Cập nhật deleted_pages
            new_deleted_pages = set()
            for del_idx in self.deleted_pages:
                if del_idx in selected_pages:
                    new_deleted_pages.add(del_idx + 1)
                elif del_idx == selected_pages[-1] + 1:
                    new_deleted_pages.add(selected_pages[0])
                else:
                    new_deleted_pages.add(del_idx)
            self.deleted_pages = new_deleted_pages
    
    def delete_selected_pages(self, dialog=None):
        """Xóa các trang được chọn"""
        selected_visual = [i for i, chk in enumerate(self.page_checkboxes) if chk.get() == 1]
        if not selected_visual:
            messagebox.showinfo("Thông báo", "Vui lòng chọn ít nhất 1 trang để xóa.")
            return
        
        # Chuyển đổi visual index sang original page index
        selected_original = [self.page_original_indices[i] for i in selected_visual]
        
        # Xác nhận xóa
        if messagebox.askyesno("Xác nhận xóa", f"Bạn có chắc chắn muốn xóa {len(selected_visual)} trang được chọn?\n\n(Trang sẽ bị xóa khi lưu file)"):
            self.deleted_pages.update(selected_original)
            self.load_pdf_thumbnails()
            self.update_page_count()
            # Đóng dialog nếu được cung cấp
            if dialog:
                dialog.destroy()

    def save_pdf(self):
        if not self.current_pdf_path:
            messagebox.showwarning("Cảnh báo", "Chưa có file nào để lưu.")
            return
        
        # Kiểm tra xem có trang nào được xoay hoặc xóa không
        has_rotation = self.rotation_states and any(angle != 0 for angle in self.rotation_states.values())
        has_deletion = bool(self.deleted_pages)
        
        if not has_rotation and not has_deletion:
            if not messagebox.askyesno("Xác nhận", "Bạn chưa thực hiện chỉnh sửa/thay đổi trang nào cả. Bạn có cần thiết muốn lưu nguyên trạng bản gốc không?"):
                return

        output_path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF files", "*.pdf")],
            initialfile=os.path.basename(self.current_pdf_path)
        )

        if output_path:
            # Kiểm tra nếu đường dẫn và tên file trùng với file cũ
            normalized_output = os.path.normpath(os.path.abspath(output_path))
            normalized_current = os.path.normpath(os.path.abspath(self.current_pdf_path))
            
            if normalized_output == normalized_current:
                # Nếu trùng file gốc, hỏi có ghi đè không
                if not messagebox.askyesno("Ghi đè File", "File này trùng tên với file gốc. Bạn có muốn ghi đè file gốc không?\n\n(Chọn 'No' để lưu với tên 'byPDFMAN_' ở đầu)"):
                    # Nếu chọn No, thêm "byPDFMAN_" vào tên file
                    output_dir = os.path.dirname(output_path)
                    output_filename = os.path.basename(output_path)
                    output_path = os.path.join(output_dir, "byPDFMAN_" + output_filename)
            
            # Đóng fitz document trước khi ghi file
            self._close_fitz_doc()
            
            try:
                reader = PdfReader(self.current_pdf_path)  # type: ignore
                writer = PdfWriter()

                for i in range(len(reader.pages)):
                    # Bỏ qua các trang bị xóa
                    if i in self.deleted_pages:
                        continue
                    
                    page = reader.pages[i]
                    # Lấy góc xoay từ dictionary trạng thái (nếu không có thì là 0)
                    angle = self.rotation_states.get(i, 0)
                    if angle != 0:
                        page.rotate(angle)
                    writer.add_page(page)

                with open(output_path, "wb") as f:  # type: ignore
                    writer.write(f)
                
                delete_count = len(self.deleted_pages)
                message = f"Đã lưu file mới tại:\n{output_path}"
                if delete_count > 0:
                    message += f"\n\nĐã xóa {delete_count} trang."
                messagebox.showinfo("Thành công", message)
                # Cập nhật trạng thái ban đầu sau khi lưu
                self.initial_rotation_states = self.rotation_states.copy()
                self.deleted_pages = set()  # Reset danh sách xóa
                
                # Mở lại fitz document sau khi ghi
                try:
                    self.fitz_doc = fitz.open(self.current_pdf_path)
                except Exception:
                    pass

            except Exception as e:
                # Mở lại fitz document nếu có lỗi
                try:
                    self.fitz_doc = fitz.open(self.current_pdf_path)
                except Exception:
                    pass
                messagebox.showerror("Lỗi khi lưu", str(e))
    
    def is_file_modified(self):
        """Kiểm tra xem file PDF có thay đổi so với lần mở/lưu cuối cùng không"""
        return (self.rotation_states != self.initial_rotation_states) or bool(self.deleted_pages)
    
    def update_page_count(self):
        """Cập nhật và hiển thị số lượng trang hiện tại"""
        if not self.current_pdf_path:
            self.lbl_page_count.config(text="Tổng số trang: 0")
            return
        
        try:
            # Sử dụng fitz_doc đã mở nếu có, tránh mở document mới thừa thãi
            if self.fitz_doc:
                total_pages = len(self.fitz_doc)
            else:
                doc = fitz.open(self.current_pdf_path)
                total_pages = len(doc)
                doc.close()
            
            deleted_count = len(self.deleted_pages)
            remaining_pages = total_pages - deleted_count
            
            if deleted_count > 0:
                text = f"Tổng số trang: {total_pages} (sẽ còn {remaining_pages} trang)"
            else:
                text = f"Tổng số trang: {total_pages}"
            
            self.lbl_page_count.config(text=text)
        except Exception as e:
            self.lbl_page_count.config(text="Tổng số trang: Lỗi")
    
    def reset_all(self):
        """Reset All tất cả thay đổi về trạng thái gốc"""
        if not self.current_pdf_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file PDF trước.")
            return
        
        if messagebox.askyesno("Xác nhận Reset All", "Bạn có chắc chắn muốn khôi phục toàn bộ những thay đổi?\n\n(Tất cả xoay trang, xóa trang và thêm trang sẽ bị hủy)"):
            # Khôi phục từ backup file trong temp folder
            if self.backup_pdf_path and os.path.exists(self.backup_pdf_path):
                try:
                    shutil.copy2(self.backup_pdf_path, self.current_pdf_path)
                except Exception as e:
                    messagebox.showerror("Lỗi", f"Không thể khôi phục file PDF: {e}")
                    return
            
            # === GIẢI PHÓNG BỘ NHỚ TRIỆT ĐỂ TRƯỚC KHI TẢI LẠI ===
            self._close_fitz_doc()
            self._force_cleanup_all_images()
            
            # Reset trạng thái
            self.rotation_states = {}
            self.initial_rotation_states = {}
            self.deleted_pages = set()
            
            # Tải lại file PDF (load_pdf_thumbnails sẽ mở fitz_doc mới)
            self.load_pdf_thumbnails()
            self.update_page_count()
            messagebox.showinfo("Thành công", "Đã khôi phục trạng thái gốc của file.")
    
    def add_pdf(self):
        """Thêm file PDF vào đầu hoặc cuối file hiện tại"""
        if not self.current_pdf_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file PDF trước.")
            return
        
        # Hỏi người dùng chọn vị trí
        response = messagebox.askyesnocancel(
            "Chọn vị trí thêm PDF",
            "Mặc định PDF mới sẽ được thêm vào cuối PDF hiện tại (sau trang cuối cùng). Bạn muốn thêm PDF ở đâu?\n\nYes: Thêm vào cuối PDF (mặc định)\nNo: Thêm vào đầu PDF (không mặc định)\nCancel: Hủy"
        )
        
        if response is None:  # Nhấn Cancel
            return
        
        file_paths = filedialog.askopenfilenames(filetypes=[("PDF files", "*.pdf")])
        if not file_paths:
            return
        
        if response:  # Yes: Thêm vào cuối
            self._append_pdf_files(list(file_paths), position="end", show_message=True)
        else:  # No: Thêm vào đầu
            self._append_pdf_files(list(file_paths), position="start", show_message=True)
    
    def _append_pdf_files(self, file_paths, position="end", show_message=False):
        """Nối nhiều file PDF vào đầu hoặc cuối file hiện tại.
        position: "start" hoặc "end".
        """
        if not self.current_pdf_path:
            return
        
        # Lọc file hợp lệ
        valid_paths = [p for p in file_paths if p and p.lower().endswith('.pdf')]
        if not valid_paths:
            messagebox.showerror("Lỗi", "Chỉ chấp nhận file PDF (.pdf)")
            return
        
        # Kiểm tra restrictions cho từng file
        for p in list(valid_paths):
            if not self.check_and_remove_pdf_restrictions(p):
                valid_paths.remove(p)
        if not valid_paths:
            return
        
        # Đóng fitz document trước khi ghi file
        self._close_fitz_doc()
        
        try:
            # Tạo backup nếu chưa có (trong trường hợp chưa mở file để backup)
            if self.backup_pdf_path is None or (self.backup_pdf_path and not os.path.exists(self.backup_pdf_path)):  # type: ignore
                self._backup_pdf()
            
            # Đọc file hiện tại
            reader_current = PdfReader(self.current_pdf_path)  # type: ignore
            writer = PdfWriter()
            
            # Đọc các file mới và tính tổng số trang
            readers_new = [PdfReader(p) for p in valid_paths]  # type: ignore
            new_pages_count = sum(len(r.pages) for r in readers_new)
            
            if position == "start":
                # Thêm trang từ file mới vào đầu
                for r in readers_new:
                    for page in r.pages:
                        writer.add_page(page)
                
                # Cập nhật rotation_states: dịch tất cả các index hiện tại
                new_rotation_states = {}
                for old_idx, angle in self.rotation_states.items():
                    new_rotation_states[old_idx + new_pages_count] = angle
                self.rotation_states = new_rotation_states
                
                # Cập nhật deleted_pages: dịch tất cả các index
                new_deleted_pages = set()
                for old_idx in self.deleted_pages:
                    new_deleted_pages.add(old_idx + new_pages_count)
                self.deleted_pages = new_deleted_pages
                
                # Thêm trang từ file hiện tại
                for page in reader_current.pages:
                    writer.add_page(page)
            else:
                # Thêm trang từ file hiện tại
                for page in reader_current.pages:
                    writer.add_page(page)
                
                # Thêm trang từ file mới vào cuối
                for r in readers_new:
                    for page in r.pages:
                        writer.add_page(page)
            
            # Lưu tạm thời vào file hiện tại
            with open(self.current_pdf_path, "wb") as f:  # type: ignore
                writer.write(f)

            if self.opened_file_count <= 0:
                self.opened_file_count = 1
            self.opened_file_count += len(valid_paths)
            self._update_file_info_label()
            
            self.load_pdf_thumbnails()
            self.update_page_count()
            if show_message:
                position_text = "đầu" if position == "start" else "cuối"
                messagebox.showinfo(
                    "Thành công",
                    f"Đã thêm {len(valid_paths)} file với tổng {new_pages_count} trang vào {position_text} file."
                )
            
        except Exception as e:
            messagebox.showerror("Lỗi", f"Không thể thêm file PDF: {e}")
    
    def on_closing(self):
        """Xử lý sự kiện đóng cửa sổ"""
        if self.current_pdf_path and self.is_file_modified():
            # Nếu file đã thay đổi, hỏi có lưu không
            response = messagebox.askyesnocancel(
                "File chưa lưu",
                f"File '{os.path.basename(self.current_pdf_path)}' có thay đổi chưa được lưu.\n\nBạn có muốn lưu file trước khi đóng không?"
            )
            if response is None:  # Nhấn Cancel
                return
            elif response:  # Nhấn Yes
                self.save_pdf()
            # Nếu nhấn No, tiếp tục đóng
        
        # Hủy timer zoom nếu đang chạy
        if self.zoom_timer is not None:
            self.root.after_cancel(self.zoom_timer)
        
        # Giải phóng toàn bộ ảnh, widgets trước khi đóng
        self._force_cleanup_all_images()
        
        # Đóng fitz document nếu đang mở
        self._close_fitz_doc()
        
        # Cleanup temp folder trước khi đóng
        self._cleanup_all_temp()
        
        self.root.destroy()

        
def _write_startup_error(exc):
    try:
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        log_path = os.path.join(base_dir, "startup_error.txt")
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("Startup error:\n")
            f.write("".join(traceback.format_exception(exc)))
    except Exception:
        pass


if __name__ == "__main__":
    try:
        try:
            root = tkinterdnd2.Tk()
        except Exception:
            root = tk.Tk()
        app = PDFManagerApp(root)
        if len(sys.argv) > 1:
            arg_paths = [p for p in sys.argv[1:] if p and p.lower().endswith('.pdf') and os.path.exists(p)]
            if arg_paths:
                if len(arg_paths) == 1:
                    app.open_pdf_file(arg_paths[0])
                else:
                    app.open_pdf_files(arg_paths)
        root.mainloop()
    except Exception as exc:
        _write_startup_error(exc)
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Locking Tool - Lock/UnLock PDF with restrictions
Cho phép khóa/mở khóa PDF để ngăn chặn các tính năng chỉnh sửa thông thường
Khóa PDF bằng AES-256 với pypdf
"""

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import importlib
import webbrowser
from pypdf import PdfReader, PdfWriter  # type: ignore
from pypdf.constants import UserAccessPermissions  # type: ignore
try:
    from pypdf.generic import Destination  # type: ignore
except Exception:
    Destination = None  # type: ignore
from gui import Tooltip     # sử dụng tooltip text từ gui
import os
import sys
import traceback
try:
    import winreg
except Exception:
    winreg = None

tkinterdnd2 = None
DND_FILES = None
try:
    tkinterdnd2 = importlib.import_module("tkinterdnd2")
    DND_FILES = getattr(tkinterdnd2, "DND_FILES", None)
except Exception:
    tkinterdnd2 = None
    DND_FILES = None

AES256_ALGORITHM = "AES-256"


def _check_cryptography_for_aes():
    """
    Kiểm tra thư viện cryptography có sẵn và đủ phiên bản cho AES-256 không.
    Returns: (ok: bool, message: str)
    """
    try:
        import cryptography  # type: ignore[import-untyped]
    except ImportError:
        python_path = getattr(sys, "executable", "python")
        if getattr(sys, "frozen", False):
            return False, (
                "Bản exe chưa được build kèm thư viện 'cryptography'.\n\n"
                "Để tính năng Lock PDF (AES-256) chạy trong exe:\n"
                "1. Cài cryptography trong môi trường build:\n"
                "   pip install \"cryptography>=3.1\"\n"
                "2. Build lại exe (spec đã khai báo hiddenimports cryptography)."
            )
        # Trên PowerShell (Windows) cần dùng & trước đường dẫn có khoảng trắng
        _pip_cmd = f'"{python_path}" -m pip install "cryptography>=3.1"'
        if sys.platform == "win32" and " " in python_path:
            _pip_ps = f'& "{python_path}" -m pip install "cryptography>=3.1"'
            _pip_hint = f"PowerShell: {_pip_ps}\n  CMD / bash: {_pip_cmd}"
        else:
            _pip_hint = _pip_cmd
        return False, (
            "Thư viện 'cryptography' chưa có trong môi trường Python đang chạy ứng dụng.\n\n"
            "Ứng dụng đang dùng Python:\n  " + python_path + "\n\n"
            "Cài đúng cho Python trên:\n  " + _pip_hint
        )
    try:
        version = getattr(cryptography, "__version__", "0")
        # So sánh version (đơn giản: 3.1, 41.0, ...)
        parts = version.split(".")[:2]
        major = int(parts[0]) if parts else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        if (major, minor) < (3, 1):
            return False, (
                f"Phiên bản cryptography hiện tại là {version}.\n\n"
                "AES-256 yêu cầu cryptography >= 3.1.\n"
                "Nâng cấp bằng lệnh:\n  pip install --upgrade \"cryptography>=3.1\""
            )
        return True, ""
    except (ValueError, TypeError):
        return False, (
            "Không xác định được phiên bản cryptography.\n\n"
            "Thử nâng cấp: pip install --upgrade \"cryptography>=3.1\""
        )


def _build_outline_for_writer(reader, writer, page_index_map=None):
    """
    Sao chép/cập nhật toàn bộ outline từ reader sang writer.
    
    page_index_map: dict[old_index] -> new_index
    Nếu None: dùng ánh xạ 1-1 (0..N-1).
    """
    if Destination is None:
        return
    destination_cls = Destination
    try:
        outlines = reader.outline
    except Exception:
        return

    if not outlines:
        return

    if page_index_map is None:
        page_index_map = {i: i for i in range(len(reader.pages))}

    def _add_outline_list(items, parent=None):
        last_created_ref = {"item": None}
        for item in items:
            if isinstance(item, list):
                # Danh sách con: gán làm con của last_created (nếu có)
                target_parent = last_created_ref["item"] if last_created_ref["item"] is not None else parent
                _add_outline_list(item, parent=target_parent)
            else:
                if destination_cls is None or not isinstance(item, destination_cls):
                    continue
                try:
                    old_page = reader.get_destination_page_number(item)
                except Exception:
                    old_page = None
                if old_page is None:
                    continue
                if old_page not in page_index_map:
                    # Trang đã bị xóa → bỏ bookmark này
                    continue
                new_page = page_index_map[old_page]
                try:
                    title = getattr(item, "title", "") or ""
                except Exception:
                    title = ""
                try:
                    last_created_ref["item"] = writer.add_outline_item(
                        title=title,
                        page_number=new_page,
                        parent=parent,
                    )
                except Exception:
                    # Nếu có lỗi khi thêm outline thì bỏ qua node này
                    continue

    try:
        _add_outline_list(outlines, parent=None)
    except Exception:
        # Không để lỗi outline làm hỏng quá trình ghi PDF
        return


class PDFLockTool:
    """Công cụ khóa PDF với restrictions"""
    
    def __init__(self, root=None):
        """
        Khởi tạo PDF Lock Tool
        
        Args:
            root: Tkinter root window (optional)
        """
        self.root = root
    
    def lock_pdf(self, input_pdf_path, output_pdf_path=None, restrictions=None, password="", open_password=""):
        """
        Khóa file PDF với các restrictions
        
        Args:
            input_pdf_path: Đường dẫn file PDF gốc
            output_pdf_path: Đường dẫn file PDF đã khóa (nếu None, sẽ ghi đè file gốc)
            restrictions: Dictionary với các restrictions:
                - 'print': True/False - cho phép in
                - 'copy': True/False - cho phép copy text/graphics
                - 'modify': True/False - cho phép chỉnh sửa nội dung
                - 'annotate': True/False - cho phép thêm annotations/comments
                - 'fill': True/False - cho phép điền form
                - 'extract': True/False - cho phép extract text/images
            password: Password để unlock PDF (nếu rỗng, restriction sẽ có nhưng không cần password)
        
        Returns:
            True nếu thành công, False nếu lỗi
        """
        try:
            # Mặc định restrictions: khóa tất cả tính năng
            if restrictions is None:
                restrictions = {
                    'print': False,         # Không cho phép in
                    'copy': False,          # Không cho phép copy
                    'modify': False,        # Không cho phép sửa
                    'annotate': False,      # Không cho phép comment
                    'fill': False,          # Không cho phép fill form
                    'extract': False        # Không cho phép extract
                }
            
            # Nếu output path là None, dùng input path (ghi đè)
            if output_pdf_path is None:
                output_pdf_path = input_pdf_path
            
            # Kiểm tra file gốc có tồn tại không
            if not os.path.exists(input_pdf_path):
                return False, f"File không tồn tại: {input_pdf_path}"
            
            # Đọc PDF gốc
            reader = PdfReader(input_pdf_path)
            if reader.is_encrypted:
                candidate_passwords = []
                for candidate in (open_password, "", password):
                    normalized = (candidate or "").strip()
                    if normalized not in candidate_passwords:
                        candidate_passwords.append(normalized)

                decrypted = False
                for candidate in candidate_passwords:
                    try:
                        if reader.decrypt(candidate) != 0:
                            decrypted = True
                            break
                    except Exception:
                        continue

                if not decrypted:
                    return False, "Password mở file PDF không đúng hoặc bị thiếu."
            writer = PdfWriter()
            
            # Copy tất cả pages
            for page in reader.pages:
                writer.add_page(page)
            
            # Giữ nguyên bookmark/outline của PDF gốc
            try:
                _build_outline_for_writer(
                    reader=reader,
                    writer=writer,
                    page_index_map={i: i for i in range(len(reader.pages))}
                )
            except Exception:
                pass
            
            # Kiểm tra cryptography trước khi dùng AES-256
            crypto_ok, crypto_msg = _check_cryptography_for_aes()
            if not crypto_ok:
                return False, crypto_msg

            # Đặt encryption với restrictions
            # pypdf sử dụng user_password (password để mở) và owner_password (password để bypass restrictions)
            user_password = (password or "").strip()  # Password để mở PDF
            owner_password = "owner"   # Password để bypass restrictions (lưu trữ nội bộ)
            try:
                writer.encrypt(
                    user_password=user_password,
                    owner_password=owner_password,
                    permissions_flag=UserAccessPermissions(
                        self._generate_permissions_flag(restrictions)
                    ),
                    algorithm=AES256_ALGORITHM,
                )
            except Exception as enc_err:
                err_text = str(enc_err).strip().lower()
                if "cryptography" in err_text or "aes" in err_text:
                    return False, (
                        "Lỗi khi mã hóa AES-256.\n\n"
                        + (crypto_msg if not crypto_ok else f"Chi tiết: {enc_err}\n\nThử cài/cập nhật: pip install \"cryptography>=3.1\"")
                    )
                raise

            # Ghi file PDF đã khóa
            with open(output_pdf_path, "wb") as output_file:
                writer.write(output_file)
            
            return True, (
                f"PDF đã được khóa thành công: {os.path.basename(output_pdf_path)}"
                f"\nMã hóa: {AES256_ALGORITHM}"
            )
            
        except Exception as e:
            return False, f"Lỗi khi khóa PDF: {str(e)}"

    def unlock_pdf(self, input_pdf_path, output_pdf_path=None, open_password=""):
        try:
            if output_pdf_path is None:
                output_pdf_path = input_pdf_path

            if not os.path.exists(input_pdf_path):
                return False, f"File không tồn tại: {input_pdf_path}"

            reader = PdfReader(input_pdf_path)
            if reader.is_encrypted:
                decrypt_result = reader.decrypt(open_password or "")
                if decrypt_result == 0:
                    return False, "Password mở file PDF không đúng hoặc bị thiếu."

            writer = PdfWriter()
            for page in reader.pages:
                writer.add_page(page)

            # Giữ nguyên bookmark/outline của PDF gốc
            try:
                _build_outline_for_writer(
                    reader=reader,
                    writer=writer,
                    page_index_map={i: i for i in range(len(reader.pages))}
                )
            except Exception:
                pass

            with open(output_pdf_path, "wb") as output_file:
                writer.write(output_file)

            return True, f"PDF đã được mở khóa thành công: {os.path.basename(output_pdf_path)}"
        except Exception as e:
            return False, f"Lỗi khi mở khóa PDF: {str(e)}"
    
    def _generate_permissions_flag(self, restrictions):
        """
        Tạo permissions flag từ restrictions dictionary
        
        Args:
            restrictions: Dictionary với các restrictions
        
        Returns:
            Integer permissions flag cho pypdf
        """
        # pypdf sử dụng PDF standard permission flags
        # Bắt đầu với -1 (tất cả bits = 1 = tất cả quyền được cho phép)
        # Sau đó clear các bits tương ứng để khóa quyền
        
        # PDF Permission bits (PDF ISO 32000-1 specification):
        # Bit 2 (4): Printing
        # Bit 3 (8): Modifying contents
        # Bit 4 (16): Copying contents / Text extraction
        # Bit 5 (32): Adding annotations / Comments
        # Bit 6 (64): Filling forms / Signing
        # Bit 8 (256): Extracting text and images
        # Bit 9 (512): Assembling (inserting, rotating, deleting pages)
        # Bit 10 (1024): Printing in high quality
        
        # Bắt đầu với tất cả quyền được cho phép
        perms = -1  # 0xFFFFFFFF = tất cả bits = 1
        
        # Clear bits để khóa quyền (nếu restriction = True = khóa)
        # Sử dụng AND với bitwise NOT (~) để clear bit
        # Print (bit 2, value 4)
        if restrictions.get('print', False):
            perms &= ~4
        
        # Modify Contents (bit 3, value 8)
        if restrictions.get('modify', False):
            perms &= ~8
        
        # Copy/Text extraction (bit 4, value 16)
        if restrictions.get('copy', False):
            perms &= ~16
        
        # Adding annotations/Comments (bit 5, value 32)
        if restrictions.get('annotate', False):
            perms &= ~32
        
        # Filling forms/Signing (bit 6, value 64)
        if restrictions.get('fill', False):
            perms &= ~64
        
        # Extracting text and images (bit 8, value 256)
        if restrictions.get('extract', False):
            perms &= ~256
        
        # Copy text for accessibility (bit 9, value 512)
        # Khóa tính năng "Content copying for accessibility"
        if restrictions.get('copy_accessibility', False):
            perms &= ~512
        
        # Commenting/Markup (bit 12, value 4096)
        # Khóa tính năng "Commenting"
        if restrictions.get('comment', False):
            perms &= ~4096
        
        return perms


class PDFLockGUI:
    """GUI cho PDF Lock Tool"""
    
    def __init__(self, root):
        """Khởi tạo GUI"""
        self.root = root
        self.root.title("PDF lock/unlock Tool - Copyright © 2026 by Hailúa")
        self.root.geometry("800x680")
        self.root.resizable(False, False)

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
            pass
        
        self.locker = PDFLockTool(root)
        self.selected_file = None
        self.selected_files = []
        self.open_password = ""
        self.open_passwords = {}
        self.initial_restrictions = {}
        self.select_all_state = False
        self.ui_widgets = []
        self.restriction_checkbuttons = []
        self.restriction_checkbuttons_map = {}
        self.password_var = tk.StringVar()
        self.password_confirm_var = tk.StringVar()
        
        # === MAIN FRAME ===
        main_frame = tk.Frame(root, padx=10, pady=5)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === TIÊU ĐỀ ===
        title_label = tk.Label(
            main_frame,
            text="Tool lock/unlock PDF with Restrictions (Encryption AES-256)",
            font=("Consolas", 12, "bold"),
            fg="#ff01ff"
        )
        title_label.pack(pady=(0, 5))
        
        # === CHỌN FILE ===
        file_frame = tk.Frame(main_frame, padx=0, pady=5)
        file_frame.pack(fill=tk.X, pady=(0, 5))
                       
        self.btn_browse = tk.Button(
            file_frame,
            text="Open PDF",
            command=self.browse_file,
            # bg="#1a73e8",
            fg="#1a73e8",
            font=("Consolas", 11, "bold"),
            padx=10,
            pady=2,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.btn_browse.pack(side=tk.LEFT, anchor=tk.W, padx=(0, 5), pady=(5, 5))
        Tooltip(self.btn_browse, "Chọn file PDF để khóa/mở khóa\n(hoặc kéo thả file vào cửa sổ)")
        
        # tk.Label(file_frame, text="File PDF:", font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=5, pady=(5, 2))

        self.file_label = tk.Label(
            file_frame,
            text="Chưa chọn file",
            font=("Tahoma", 9),
            fg="#666",
            wraplength=765,
            justify=tk.LEFT,
            padx=5,
            pady=0
        )
        self.file_label.pack(side=tk.LEFT, anchor=tk.W, padx=0, pady=(0, 0))
        
        if tkinterdnd2 is not None and DND_FILES is not None:
            try:
                self.root.drop_target_register(DND_FILES)
                self.root.dnd_bind('<<Drop>>', self.drop_files)
            except Exception:
                pass

        if getattr(sys, 'frozen', False) and sys.platform == 'win32':
            self._register_open_with()
        
        # === RESTRICTIONS ===
        restrictions_frame = tk.LabelFrame(
            main_frame,
            text="Select Restrictions to lock/unlock",
            font=("Consolas", 11, "bold"),
            padx=5,
            pady=5
        )
        restrictions_frame.pack(fill=tk.X, pady=(0, 5))
        
        # Variables để lưu trạng thái checkbox
        self.check_vars = {}

        restrictions_controls = tk.Frame(restrictions_frame)
        restrictions_controls.pack(fill=tk.X, pady=(0, 10))

        self.btn_reset_restrictions = tk.Button(
            restrictions_controls,
            text="🔄 Reset",
            command=self.reset_restrictions,
            # bg="#ea8208",
            fg="blue",
            font=("Consolas", 11),
            padx=2,
            pady=2,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.btn_reset_restrictions.pack(side=tk.LEFT, padx=(150,5))
        Tooltip(self.btn_reset_restrictions, "Reset để quay trở về các tùy chọn lock/unlock tính năng ban đầu của PDF")
        
        self.btn_toggle_all = tk.Button(
            restrictions_controls,
            text="☑ Select All",
            command=self.toggle_select_all,
            width=14,
            # bg="#1a73e8",
            fg="blue",
            font=("Consolas", 11),
            padx=2,
            pady=2,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.btn_toggle_all.pack(side=tk.LEFT, padx=(5, 10))
        Tooltip(self.btn_toggle_all, "Chọn tất cả hoặc bỏ chọn tất cả lock/unlock tính năng của PDF")

        self.lbl_encryption_info = tk.Label(
            restrictions_controls,
            text="File không được mã hóa",
            font=("Consolas", 10),
            fg="#555",
            anchor=tk.W
        )
        self.lbl_encryption_info.pack(side=tk.LEFT, padx=(10, 0))
        
        restrictions = [
            ("print", "🚫 Khóa tính năng In (Print)"),
            ("copy", "🚫 Khóa tính năng Copy Text/Graphics"),
            ("modify", "🚫 Khóa tính năng Sửa nội dung (Modify)"),
            ("annotate", "🚫 Khóa tính năng Thêm Comments (Annotate)"),
            ("fill", "🚫 Khóa tính năng Điền Form (Fill)"),
            ("extract", "🚫 Khóa tính năng Extract Text/Images"),
            ("copy_accessibility", "🚫 Khóa Copy Text cho Accessibility"),
            ("comment", "🚫 Khóa tính năng Commenting (Markup)"),
        ]
        
        for key, label in restrictions:
            var = tk.BooleanVar(value=True)  # Mặc định khóa tất cả
            self.check_vars[key] = var
            
            chk = tk.Checkbutton(
                restrictions_frame,
                text=label,
                variable=var,
                font=("Consolas", 11),
                anchor=tk.W
            )
            chk.pack(fill=tk.X, padx=(150, 5), pady=1)
            self.restriction_checkbuttons.append(chk)
            self.restriction_checkbuttons_map[key] = chk
        
        # === PASSWORD ===
        password_frame = tk.LabelFrame(
            main_frame,
            text="Password (tùy chọn)",
            font=("Consolas", 11, "bold"),
            padx=10,
            pady=5
        )
        password_frame.pack(fill=tk.X, pady=(0, 5))
        
        tk.Label(password_frame, text="Nếu để trống, không cần password để mở PDF (chỉ khóa restrictions)", 
                font=("Consolas", 11), fg="#666").pack(anchor=tk.W, pady=(0, 1))
        
        tk.Label(password_frame, text="Password:", font=("Consolas", 11)).pack(anchor=tk.W)
        self.password_entry = tk.Entry(password_frame, textvariable=self.password_var, show="*", font=("Consolas", 11), width=40)
        self.password_entry.pack(fill=tk.X, padx=5, pady=(1, 1))

        tk.Label(password_frame, text="Nhập lại Password:", font=("Consolas", 11)).pack(anchor=tk.W)
        self.password_confirm_entry = tk.Entry(password_frame, textvariable=self.password_confirm_var, show="*", font=("Consolas", 11), width=40)
        self.password_confirm_entry.pack(fill=tk.X, padx=5, pady=(1, 1))
        
        # === NÚT HOẠT ĐỘNG ===
        button_frame = tk.Frame(main_frame)
        button_frame.pack(fill=tk.X)
        
        self.btn_lock = tk.Button(
            button_frame,
            text="🔒 Lock PDF",
            command=self.lock_pdf,
            bg="#d33b27",
            fg="white",
            font=("Consolas", 11, "bold"),
            padx=10,
            pady=2,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.btn_lock.pack(side=tk.LEFT, padx=(0, 10))
        Tooltip(self.btn_lock, "Khóa PDF với các restrictions đã chọn\nvà password đã nhập (nếu có)")

        self.btn_unlock = tk.Button(
            button_frame,
            text="🔓 Unlock PDF",
            command=self.unlock_pdf,
            bg="#1a73e8",
            fg="white",
            font=("Consolas", 11, "bold"),
            padx=8,
            pady=2,
            relief=tk.RAISED,
            cursor="hand2"
        )
        self.btn_unlock.pack(side=tk.LEFT)
        Tooltip(self.btn_unlock, "Mở khóa PDF đã bị khóa")
        
        tk.Label(button_frame, text="PDF được lock mã hóa AES-256, nên đặt password khó để bảo vệ file tốt hơn", font=("Consolas", 10, "bold")).pack(side=tk.LEFT, anchor=tk.W, padx=5, pady=(5, 2))

        # Khung giới thiệu (Bottom Frame)
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
        
        self.ui_widgets = [
            self.btn_reset_restrictions,
            self.btn_toggle_all,
            self.lbl_encryption_info,
            self.password_entry,
            self.password_confirm_entry,
            self.btn_lock,
            self.btn_unlock,
        ]
        self.ui_widgets.extend(self.restriction_checkbuttons)
        self._set_ui_state(False)
        self._show_window()
        self._bind_state_handlers()
    
    def browse_file(self):
        """Cho user chọn file PDF"""
        file_paths = filedialog.askopenfilenames(
            title="Chọn file PDF để lock/unlock",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        
        if file_paths:
            self.open_files(list(file_paths))

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

    def drop_files(self, event):
        try:
            files = self.root.tk.splitlist(event.data)
            if not files:
                return
            file_paths = [f.strip("{}") for f in files if f and f.strip("{}").lower().endswith('.pdf')]
            if file_paths:
                self.open_files(file_paths)
        except Exception:
            pass

    def open_files(self, file_paths):
        valid_paths = [p for p in file_paths if p and os.path.exists(p) and p.lower().endswith('.pdf')]
        if not valid_paths:
            messagebox.showerror("Lỗi", "Không có file PDF hợp lệ để mở.")
            return

        loaded_paths = []
        passwords = {}
        first_reader = None

        for file_path in valid_paths:
            try:
                reader = PdfReader(file_path)
                open_password = ""
                if reader.is_encrypted:
                    open_password = self._prompt_password(os.path.basename(file_path))
                    if open_password is None:
                        continue
                    decrypt_result = reader.decrypt(open_password)
                    if decrypt_result == 0:
                        messagebox.showerror("Lỗi", f"Password không đúng: {os.path.basename(file_path)}")
                        continue

                loaded_paths.append(file_path)
                passwords[file_path] = open_password or ""
                if first_reader is None:
                    first_reader = reader
            except Exception as e:
                messagebox.showerror("Lỗi", f"Không thể mở file '{os.path.basename(file_path)}': {e}")

        if not loaded_paths:
            return

        self.selected_files = loaded_paths
        self.selected_file = loaded_paths[0]
        self.open_passwords = passwords
        self.open_password = passwords.get(self.selected_file, "")

        if len(loaded_paths) == 1:
            self.file_label.config(text=os.path.basename(loaded_paths[0]), fg="#000")
        else:
            self.file_label.config(text=f"Đang chọn {len(loaded_paths)} file PDF", fg="#000")

        self._set_ui_state(True)
        self._set_password_fields("")

        if first_reader is not None:
            self._set_encryption_label(first_reader)
            restrictions = self._read_pdf_restrictions(first_reader)
            self.initial_restrictions = restrictions.copy()
            self._apply_restrictions_to_ui(restrictions)

        self._sync_select_all_state()
        self._update_lock_button_state()

    def open_file(self, file_path):
        self.open_files([file_path])
    
    def lock_pdf(self):
        """Khóa PDF với restrictions được chọn"""
        if not self.selected_files:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file PDF trước!")
            return
        
        # Tạo restrictions dictionary từ checkbox values
        restrictions = {
            'print': self.check_vars['print'].get(),
            'copy': self.check_vars['copy'].get(),
            'modify': self.check_vars['modify'].get(),
            'annotate': self.check_vars['annotate'].get(),
            'fill': self.check_vars['fill'].get(),
            'extract': self.check_vars['extract'].get(),
            'copy_accessibility': self.check_vars.get('copy_accessibility', tk.BooleanVar(value=False)).get(),
            'comment': self.check_vars.get('comment', tk.BooleanVar(value=False)).get(),
        }

        if not any(restrictions.values()) and not (self.password_var.get() or "").strip():
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn ít nhất 1 tính năng cần khóa hoặc nhập password.")
            return
        
        # Lấy password
        password = self.password_var.get()
        password_confirm = self.password_confirm_var.get()
        if password != password_confirm:
            messagebox.showerror("Lỗi", "Password nhập lại không khớp.")
            return
        
        success_files = []
        failed_files = []

        for input_path in self.selected_files:
            name, ext = os.path.splitext(input_path)
            output_path = f"{name}_locked{ext}"
            success, message = self.locker.lock_pdf(
                input_pdf_path=input_path,
                output_pdf_path=output_path,
                restrictions=restrictions,
                password=password,
                open_password=self.open_passwords.get(input_path, "")
            )
            if success:
                success_files.append(output_path)
            else:
                failed_files.append((input_path, message))

        if failed_files:
            fail_text = "\n".join([f"- {os.path.basename(p)}: {m}" for p, m in failed_files])
            messagebox.showerror(
                "Lỗi",
                f"Khóa PDF thất bại {len(failed_files)}/{len(self.selected_files)} file:\n{fail_text}"
            )

        if success_files:
            preview = "\n".join([f"- {os.path.basename(p)}" for p in success_files[:10]])
            if len(success_files) > 10:
                preview += f"\n... và {len(success_files) - 10} file khác"

            messagebox.showinfo(
                "Thành công",
                f"Đã khóa thành công {len(success_files)}/{len(self.selected_files)} file PDF.\n\n"
                f"Tên file lưu vẫn theo quy tắc cũ (_locked):\n{preview}"
            )
            if not failed_files:
                self.clear_form()

    def unlock_pdf(self):
        if not self.selected_files:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn file PDF trước!")
            return

        success_files = []
        failed_files = []

        for input_path in self.selected_files:
            base_open_password = self.open_passwords.get(input_path, "") or self.password_var.get()
            if base_open_password == "":
                base_open_password = self._prompt_password(os.path.basename(input_path)) or ""

            name, ext = os.path.splitext(input_path)
            output_path = f"{name}_unlocked{ext}"

            success, message = self.locker.unlock_pdf(
                input_pdf_path=input_path,
                output_pdf_path=output_path,
                open_password=base_open_password
            )

            if success:
                success_files.append(output_path)
            else:
                failed_files.append((input_path, message))

        if failed_files:
            fail_text = "\n".join([f"- {os.path.basename(p)}: {m}" for p, m in failed_files])
            messagebox.showerror(
                "Lỗi",
                f"Mở khóa PDF thất bại {len(failed_files)}/{len(self.selected_files)} file:\n{fail_text}"
            )

        if success_files:
            preview = "\n".join([f"- {os.path.basename(p)}" for p in success_files[:10]])
            if len(success_files) > 10:
                preview += f"\n... và {len(success_files) - 10} file khác"
            messagebox.showinfo(
                "Thành công",
                f"Đã mở khóa thành công {len(success_files)}/{len(self.selected_files)} file PDF.\n\n"
                f"Tên file lưu vẫn theo quy tắc cũ (_unlocked):\n{preview}"
            )
            if not failed_files:
                self.clear_form()

    def clear_form(self):
        """Reset form về trạng thái ban đầu"""
        self.selected_file = None
        self.selected_files = []
        self.open_password = ""
        self.open_passwords = {}
        self.initial_restrictions = {}
        self.file_label.config(text="Chưa chọn file", fg="#666")
        self._set_password_fields("")
        for var in self.check_vars.values():
            var.set(False)
        for key in self.check_vars.keys():
            self._update_restriction_style(key)
        self.select_all_state = False
        self._sync_select_all_state()
        self._set_encryption_label(None)
        self._set_ui_state(False)
        self._update_lock_button_state()

    def reset_restrictions(self):
        if self.initial_restrictions:
            self._apply_restrictions_to_ui(self.initial_restrictions)
        self._sync_select_all_state()
        self._update_lock_button_state()

    def toggle_select_all(self):
        if self.select_all_state:
            for var in self.check_vars.values():
                var.set(False)
            self.select_all_state = False
        else:
            for var in self.check_vars.values():
                var.set(True)
            self.select_all_state = True
        self._update_select_all_label()
        for key in self.check_vars.keys():
            self._update_restriction_style(key)
        self._update_lock_button_state()

    def _sync_select_all_state(self):
        all_selected = all(var.get() for var in self.check_vars.values())
        self.select_all_state = all_selected
        self._update_select_all_label()

    def _update_select_all_label(self):
        if self.select_all_state:
            self.btn_toggle_all.config(text="☐ Deselect All")
        else:
            self.btn_toggle_all.config(text="☑ Select All")

    def _bind_state_handlers(self):
        for key, var in self.check_vars.items():
            var.trace_add("write", lambda *_args, k=key: self._on_restriction_toggle(k))

        self.password_var.trace_add("write", lambda *_args: self._update_lock_button_state())
        self.password_confirm_var.trace_add("write", lambda *_args: self._update_lock_button_state())

        for key in self.check_vars.keys():
            self._update_restriction_style(key)
        self._update_lock_button_state()

    def _on_restriction_toggle(self, key):
        self._update_restriction_style(key)
        self._sync_select_all_state()
        self._update_lock_button_state()

    def _update_restriction_style(self, key):
        chk = self.restriction_checkbuttons_map.get(key)
        if not chk:
            return
        if self.check_vars.get(key, tk.BooleanVar(value=False)).get():
            chk.config(fg="#ea8208", font=("Consolas", 11, "bold"))
        else:
            chk.config(fg="#000", font=("Consolas", 11, "normal"))

    def _update_lock_button_state(self):
        if not self.selected_files:
            try:
                self.btn_lock.config(state=tk.DISABLED)
            except Exception:
                pass
            return

        has_restriction = any(var.get() for var in self.check_vars.values())
        password = (self.password_var.get() or "").strip()
        state = tk.NORMAL if (has_restriction or password) else tk.DISABLED
        try:
            self.btn_lock.config(state=state)
        except Exception:
            pass

    def _set_password_fields(self, password):
        self.password_var.set(password or "")
        self.password_confirm_var.set(password or "")

    def _prompt_password(self, filename):
        return simpledialog.askstring(
            "Nhập Password",
            f"Nhập password để mở PDF có 'restrictions'\n(nếu không đặt password thì bỏ trống => OK)\nFile: '{filename}'",
            show="*"
        )

    def _read_pdf_restrictions(self, reader):
        encrypt_dict = None
        try:
            encrypt_dict = reader.trailer.get("/Encrypt")
        except Exception:
            encrypt_dict = None

        if not encrypt_dict:
            return self._default_restrictions(False)

        try:
            encrypt_dict = encrypt_dict.get_object()
        except Exception:
            pass

        perms = None
        try:
            perms = int(encrypt_dict.get("/P"))
        except Exception:
            perms = None

        if perms is None:
            return self._default_restrictions(False)

        return self._restrictions_from_permissions(perms)

    def _restrictions_from_permissions(self, perms):
        p = perms & 0xFFFFFFFF
        return {
            "print": not bool(p & 4),
            "copy": not bool(p & 16),
            "modify": not bool(p & 8),
            "annotate": not bool(p & 32),
            "fill": not bool(p & 64),
            "extract": not bool(p & 256),
            "copy_accessibility": not bool(p & 512),
            "comment": not bool(p & 4096),
        }

    def _default_restrictions(self, locked):
        return {
            "print": locked,
            "copy": locked,
            "modify": locked,
            "annotate": locked,
            "fill": locked,
            "extract": locked,
            "copy_accessibility": locked,
            "comment": locked,
        }

    def _apply_restrictions_to_ui(self, restrictions):
        for key, var in self.check_vars.items():
            if key in restrictions:
                var.set(bool(restrictions[key]))
                self._update_restriction_style(key)
        self._update_lock_button_state()

    def _set_encryption_label(self, reader):
        if reader is None or not getattr(reader, "is_encrypted", False):
            self.lbl_encryption_info.config(text="File không được mã hóa")
            return

        encrypt_dict = None
        try:
            encrypt_dict = reader.trailer.get("/Encrypt")
        except Exception:
            encrypt_dict = None

        try:
            encrypt_dict = encrypt_dict.get_object() if encrypt_dict else None
        except Exception:
            pass

        method = "Không rõ"
        v = None
        r = None
        length = None
        cfm = None

        if encrypt_dict:
            try:
                v = encrypt_dict.get("/V")
                r = encrypt_dict.get("/R")
                length = encrypt_dict.get("/Length")
            except Exception:
                pass

            try:
                cf_dict = encrypt_dict.get("/CF")
                if cf_dict:
                    std_cf = cf_dict.get("/StdCF") or next(iter(cf_dict.values()), None)
                    if std_cf:
                        cfm = std_cf.get("/CFM")
            except Exception:
                pass

        if r in (5, 6) or v in (5, 6) or cfm == "/AESV3":
            method = "AES-256"
        elif r == 4 or v == 4 or cfm == "/AESV2":
            method = "AES-128"
        elif r in (2, 3) or v in (1, 2):
            method = "RC4"

        if length:
            self.lbl_encryption_info.config(text=f"File được mã hóa {method} ({length}-bit)")
        else:
            self.lbl_encryption_info.config(text=f"File được mã hóa {method}")

    def _set_ui_state(self, has_file):
        state = tk.NORMAL if has_file else tk.DISABLED
        for widget in self.ui_widgets:
            try:
                widget.config(state=state)
            except Exception:
                pass

        if not has_file:
            for var in self.check_vars.values():
                var.set(False)
            for entry in (self.password_entry, self.password_confirm_entry):
                try:
                    entry.config(state=tk.NORMAL)
                except Exception:
                    pass
            self._set_password_fields("")
            for entry in (self.password_entry, self.password_confirm_entry):
                try:
                    entry.config(state=state)
                except Exception:
                    pass
            self.select_all_state = False
            self._update_select_all_label()
            self.lbl_encryption_info.config(text="File không được mã hóa")
        self._update_lock_button_state()

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
                winreg.SetValueEx(key, "FriendlyAppName", 0, winreg.REG_SZ, "PDF Lock/Unlock Tool")

            default_icon_key = app_root + "\\DefaultIcon"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, default_icon_key) as key:
                winreg.SetValueEx(key, "", 0, winreg.REG_SZ, f'"{exe_path}",0')

            supported_types_key = app_root + "\\SupportedTypes"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, supported_types_key) as key:
                winreg.SetValueEx(key, ".pdf", 0, winreg.REG_SZ, "")

            self._add_to_open_with_list(exe_name)
            self._add_to_open_with_progids(exe_name)
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

    def _add_to_open_with_progids(self, exe_name):
        if winreg is None:
            return
        try:
            progids_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.pdf\OpenWithProgids"
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, progids_path) as key:
                winreg.SetValueEx(key, exe_name, 0, winreg.REG_SZ, "")
        except Exception:
            return


def main():
    """Hàm main để chạy PDF Lock Tool"""
    try:
        if tkinterdnd2 is not None:
            try:
                root = tkinterdnd2.Tk()
            except Exception:
                root = tk.Tk()
        else:
            root = tk.Tk()
        app = PDFLockGUI(root)
        if len(sys.argv) > 1:
            arg_paths = [
                p for p in sys.argv[1:]
                if p and p.lower().endswith('.pdf') and os.path.exists(p)
            ]
            if arg_paths:
                app.open_files(arg_paths)
        root.mainloop()
    except Exception as exc:
        _write_startup_error(exc)


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
    main()

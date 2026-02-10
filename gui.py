import tkinter as tk
import os
from PIL import Image, ImageDraw, ImageTk

# -----Tooltip class chú thích khi rà chuột vào widget-----
class Tooltip:
    """Class tạo chú thích khi rà chuột vào widget"""
    def __init__(self, widget, text, hover_delay=500, show_duration=2000, bg="#FFFFE1", wraplength=250, relief='solid', font_name='Tahoma', font_size=10):
        """
        Args:
            widget: Widget để attach tooltip
            text: Nội dung tooltip
            hover_delay: Thời gian chờ khi hover trước khi hiển thị tooltip (ms), mặc định 500
            show_duration: Thời gian hiển thị tooltip trước khi tự động ẩn (ms), ghi -1 để không tự động ẩn, mặc định 2000
            bg: Màu nền tooltip, mặc định "#FFFFE1"
            wraplength: Độ dài tối đa của text trước khi wrap (pixel), mặc định 250
            relief: Kiểu border (solid, raised, sunken, flat, ridge, groove), mặc định 'solid'
            font_name: Tên font, mặc định 'Tahoma'
            font_size: Kích thước font, mặc định 10
        """
        self.widget = widget
        self.text = text
        self.hover_delay = hover_delay
        self.show_duration = show_duration
        self.bg = bg
        self.wraplength = wraplength
        self.relief = relief
        self.font_name = font_name
        self.font_size = font_size
        self.tooltip_window = None
        self.tooltip_id = None  # ID của after task
        
        self.widget.bind("<Enter>", self.on_enter)
        self.widget.bind("<Leave>", self.on_leave)
        # Cleanup khi widget bị destroy
        self.widget.bind("<Destroy>", self.hide_tooltip)

    def on_enter(self, event=None):
        """Xử lý sự kiện Enter"""
        # Hủy bất kỳ tooltip pending nào
        if self.tooltip_id:
            self.widget.after_cancel(self.tooltip_id)
            self.tooltip_id = None
        
        # Nếu hover_delay <= 0, hiển thị tooltip ngay
        if self.hover_delay <= 0:
            self.show_tooltip()
        else:
            # Lên lịch hiển thị tooltip với hover_delay
            self.tooltip_id = self.widget.after(self.hover_delay, self.show_tooltip)

    def on_leave(self, event=None):
        """Xử lý sự kiện Leave"""
        # Hủy tooltip pending
        if self.tooltip_id:
            self.widget.after_cancel(self.tooltip_id)
            self.tooltip_id = None
        
        # Ẩn tooltip ngay lập tức
        self.hide_tooltip()

    def show_tooltip(self, event=None):
        """Hiển thị tooltip"""
        if self.tooltip_window or not self.widget.winfo_exists():
            return
        
        try:
            # Lấy tọa độ widget
            x = self.widget.winfo_rootx() + 20
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 5
            
            # Tạo tooltip window
            self.tooltip_window = tw = tk.Toplevel(self.widget)
            tw.wm_overrideredirect(True)  # Xóa title bar
            
            # Tạo label
            label = tk.Label(
                tw, 
                text=self.text, 
                justify='left',
                background=self.bg, 
                relief=self.relief, 
                borderwidth=1,
                font=(self.font_name, self.font_size, "normal"), 
                padx=5, 
                pady=2,
                wraplength=self.wraplength
            )
            label.pack()
            
            # Cập nhật vị trí (phải sau pack để lấy dimensions)
            tw.update_idletasks()
            tw_width = tw.winfo_width()
            tw_height = tw.winfo_height()
            screen_width = tw.winfo_screenwidth()
            screen_height = tw.winfo_screenheight()
            
            # Điều chỉnh vị trí nếu tooltip vượt ngoài màn hình
            if x + tw_width > screen_width:
                x = screen_width - tw_width - 10
            if y + tw_height > screen_height:
                y = self.widget.winfo_rooty() - tw_height - 5
            
            tw.wm_geometry(f"+{x}+{y}")
            
            # Tự động ẩn sau show_duration (nếu show_duration > 0)
            if self.show_duration > 0:
                self.tooltip_id = self.widget.after(self.show_duration, self.hide_tooltip)
        
        except tk.TclError:
            # Widget đã bị xóa
            self.hide_tooltip()

    def hide_tooltip(self, event=None):
        """Ẩn tooltip"""
        if self.tooltip_window:
            try:
                self.tooltip_window.destroy()
            except tk.TclError:
                pass
            self.tooltip_window = None
        
        if self.tooltip_id:
            try:
                self.widget.after_cancel(self.tooltip_id)
            except tk.TclError:
                pass
            self.tooltip_id = None

# -----quản lý icon và tạo button với icon-----
class IconButtonManager:
    """Quản lý icon và tạo button với icon"""
    
    def __init__(self, icons_dir="icons"):
        """
        Khởi tạo IconButtonManager
        
        Args:
            icons_dir: Đường dẫn thư mục chứa icon, mặc định "icons"
        """
        self.icons_dir = icons_dir
        self.photos = {}  # Lưu tham chiếu ảnh để tránh garbage collection
        
        # Tạo thư mục icons nếu chưa tồn tại
        self.ensure_icons_dir()
    
    def ensure_icons_dir(self):
        """
        Đảm bảo thư mục icons tồn tại.
        Tạo thư mục nếu chưa tồn tại và tạo default icons nếu cần.
        """
        if not os.path.exists(self.icons_dir):
            try:
                os.makedirs(self.icons_dir)
                print(f"[OK] Created icons folder: {os.path.abspath(self.icons_dir)}")
            except Exception as e:
                print(f"[ERROR] Failed to create icons folder: {e}")
        
        # Kiểm tra và tạo icons nếu thiếu
        self.check_and_create_missing_icons()
    
    def recover_icons_dir(self):
        """
        Khôi phục thư mục icons nếu bị mất.
        Tạo lại thư mục nếu không tồn tại.
        """
        if not os.path.exists(self.icons_dir):
            print(f"[WARNING] Icons folder not found at: {os.path.abspath(self.icons_dir)}")
            self.ensure_icons_dir()
            print(f"[OK] Icons folder recovered")
    
    def check_and_create_missing_icons(self):
        """
        Kiểm tra và tạo lại các icon bị thiếu.
        Danh sách icon cần thiết: open_pdf, add_pdf, select_all, rotate_cw, rotate_ccw, rotate_180,
                                  reset, move_up, move_down, delete, save_pdf
        """
        required_icons = ['open_pdf.png', 'add_pdf.png', 'select_all.png', 'rotate_cw.png', 
                         'rotate_ccw.png', 'rotate_180.png', 'reset.png', 'move_up.png', 'move_down.png', 
                         'delete.png', 'save_pdf.png']
        
        missing_icons = [icon for icon in required_icons 
                        if not os.path.exists(os.path.join(self.icons_dir, icon))]
        
        if missing_icons:
            print(f"[INFO] Missing icons: {missing_icons} - Creating them...")
            self.create_default_icons()
            print(f"[OK] Created missing icons")
        else:
            print(f"[OK] All icons exist in: {os.path.abspath(self.icons_dir)}")
    
    def create_default_icons(self):
        """Tạo các icon mặc định nếu chưa tồn tại"""
        try:
            # Icon Open PDF - Folder icon
            img_open = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_open)
            draw.rectangle([4, 8, 28, 28], outline='#FE3D03', width=2, fill='#FFF8DC')
            draw.polygon([4, 8, 16, 2, 28, 8], outline='#FE3D03', fill='#FFF8DC', width=2)
            img_open.save(os.path.join(self.icons_dir, 'open_pdf.png'))
            
            # Icon Add PDF - Plus sign
            img_add = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_add)
            draw.rectangle([3, 3, 29, 29], outline='#009DFF', width=2)
            draw.line([16, 8, 16, 24], fill='#009DFF', width=2)
            draw.line([8, 16, 24, 16], fill='#009DFF', width=2)
            img_add.save(os.path.join(self.icons_dir, 'add_pdf.png'))
            
            # Icon Select/Deselect - Checkbox
            img_select = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_select)
            draw.rectangle([3, 3, 29, 29], outline='#9400D3', width=2)
            draw.line([7, 16, 13, 23, 26, 10], fill='#9400D3', width=3)
            img_select.save(os.path.join(self.icons_dir, 'select_all.png'))
            
            # Icon Rotate CW - Right arrow
            img_rotate_cw = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_rotate_cw)
            draw.arc([5, 5, 27, 27], 45, 315, fill='blue', width=3)
            draw.polygon([24, 5, 27, 14, 19, 11], fill='blue')
            img_rotate_cw.save(os.path.join(self.icons_dir, 'rotate_cw.png'))
            
            # Icon Rotate CCW - Left arrow
            img_rotate_ccw = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_rotate_ccw)
            draw.arc([5, 5, 27, 27], 225, 135, fill='blue', width=3)
            draw.polygon([8, 5, 13, 14, 5, 11], fill='blue')
            img_rotate_ccw.save(os.path.join(self.icons_dir, 'rotate_ccw.png'))
            
            # Icon Rotate 180° - Circular arrow
            img_rotate_180 = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_rotate_180)
            draw.arc([5, 5, 27, 27], start=280, end=100, fill='blue', width=3)
            draw.polygon([27, 16, 32, 8, 22, 8], fill='blue')
            draw.arc([5, 5, 27, 27], start=100, end=280, fill='blue', width=3)
            draw.polygon([5, 16, 0, 24, 10, 24], fill='blue')
            img_rotate_180.save(os.path.join(self.icons_dir, 'rotate_180.png'))

            # Icon Reset - Circular arrow
            img_reset = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_reset)
            draw.arc([4, 4, 28, 28], 45, 315, fill='#9400D3', width=3)
            draw.polygon([25, 4, 28, 13, 20, 10], fill='#9400D3')
            img_reset.save(os.path.join(self.icons_dir, 'reset.png'))
            
            # Icon Move Up - Up arrow
            img_move_up = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_move_up)
            draw.polygon([16, 4, 26, 20, 21, 20, 21, 28, 11, 28, 11, 20, 6, 20], fill='#0066CC')
            img_move_up.save(os.path.join(self.icons_dir, 'move_up.png'))
            
            # Icon Move Down - Down arrow
            img_move_down = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_move_down)
            draw.polygon([16, 28, 26, 12, 21, 12, 21, 4, 11, 4, 11, 12, 6, 12], fill='#0066CC')
            img_move_down.save(os.path.join(self.icons_dir, 'move_down.png'))
            
            # Icon Delete - X mark
            img_delete = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_delete)
            draw.rectangle([3, 3, 29, 29], outline='#DC143C', width=2)
            draw.line([8, 8, 24, 24], fill='#DC143C', width=3)
            draw.line([24, 8, 8, 24], fill='#DC143C', width=3)
            img_delete.save(os.path.join(self.icons_dir, 'delete.png'))
            
            # Icon SaveAs - Floppy disk
            img_save = Image.new('RGB', (32, 32), color='#F0F0F0')
            draw = ImageDraw.Draw(img_save)
            draw.rectangle([4, 4, 28, 28], outline='#00820F', width=2)
            draw.rectangle([4, 4, 28, 12], outline='#00820F', fill='#90EE90')
            draw.rectangle([8, 14, 16, 26], outline='#00820F', fill='#90EE90')
            img_save.save(os.path.join(self.icons_dir, 'save_pdf.png'))
            
            print(f"[OK] Default icons created in: {os.path.abspath(self.icons_dir)}")
        except Exception as e:
            print(f"[ERROR] Error creating default icons: {e}")
    

    def load_icon(self, icon_name, size=(20, 20)):
        """
        Tải icon từ file và chuyển đổi thành PhotoImage
        
        Args:
            icon_name: Tên file icon
            size: Kộ thước icon (width, height), mặc định (20, 20)
            
        Returns:
            PhotoImage: Ảnh icon đã được load
        """
        
        # Đảm bảo thư mục icons tồn tại
        self.recover_icons_dir()
        
        icon_path = os.path.join(self.icons_dir, icon_name)
        try:
            if not os.path.exists(icon_path):
                print(f"[WARNING] Icon not found: {icon_path}")
                print(f"[INFO] Creating missing icon...")
                self.create_default_icons()
                
                # Kiểm tra lại xem file có được tạo không
                if not os.path.exists(icon_path):
                    raise FileNotFoundError(f"Icon file not found: {icon_path}")
            
            img = Image.open(icon_path)
            img = img.resize(size, Image.Resampling.LANCZOS)
            
            photo = ImageTk.PhotoImage(img)
            self.photos[icon_name] = photo  # Lưu tham chiếu
            print(f"[OK] Loaded: {icon_path} (size: {size})")
            return photo
        except Exception as e:
            print(f"[ERROR] Error loading {icon_name}: {e}")
            return None
    
    def create_button_with_icon(self, parent, icon_name, icon_size, text, command, 
                               text_color="black", font_name="Consolas", font_size=11, 
                               font_weight="normal", compound=tk.LEFT, padx=2, pady=2, **kwargs):
        """
        Tạo button với icon
        
        Args:
            parent: Frame cha chứa button
            icon_name: Tên file icon
            icon_size: Kích thước icon (width, height)
            text: Text của button
            command: Hàm callback khi click button
            text_color: Màu text, mặc định "black"
            font_name: Tên font, mặc định "Consolas"
            font_size: Kích thước font, mặc định 11
            font_weight: Độ dậy font ("normal", "bold"), mặc định "normal"
            compound: Vị trí text so với icon (tk.LEFT, tk.RIGHT, tk.TOP, tk.BOTTOM), mặc định tk.LEFT
            padx: Padding ngang, mặc định 2
            pady: Padding dọc, mặc định 2
            **kwargs: Tham số khác của tk.Button
            
        Returns:
            tk.Button: Button đã được tạo
        """
        icon = self.load_icon(icon_name, size=icon_size)
        
        button = tk.Button(
            parent,
            image=icon,
            text=text,
            compound=compound,
            command=command,
            fg=text_color,
            font=(font_name, font_size, font_weight),
            padx=padx,
            pady=pady,
            **kwargs
        )
        return button
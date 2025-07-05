import os
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext, Menu
import threading
import importlib.util
import json
from datetime import datetime

from auto_translate import AutoTranslator

# Đường dẫn thư mục chứa các module mở rộng
MODULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "modules")

def load_modules():
    """
    Quét thư mục modules/, tự động import các file .py có biến MENU_NAME và hàm run().
    Trả về danh sách tuple (menu_name, run_func, module_obj).
    """
    modules = []
    if not os.path.exists(MODULES_DIR):
        os.makedirs(MODULES_DIR)
    for filename in os.listdir(MODULES_DIR):
        if filename.endswith(".py") and not filename.startswith("_"):
            module_path = os.path.join(MODULES_DIR, filename)
            module_name = filename[:-3]
            spec = importlib.util.spec_from_file_location(module_name, module_path)
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)
                menu_name = getattr(mod, "MENU_NAME", module_name)
                run_func = getattr(mod, "run", None)
                if callable(run_func):
                    modules.append((menu_name, run_func, mod))
            except Exception as e:
                print(f"[LỖI] Không thể load module {filename}: {e}")
    return modules

class AutoTranslatorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Công Cụ Dịch Game Tự Động (Mở Rộng)")
        self.root.geometry("950x750")
        self.root.minsize(900, 650)
        self.modules = load_modules()
        self.module_buttons = []
        
        # Menu bar
        self.menu_bar = Menu(self.root)
        self.root.config(menu=self.menu_bar)
        self.tools_menu = Menu(self.menu_bar, tearoff=0)
        self.menu_bar.add_cascade(label="Công cụ", menu=self.tools_menu)
        self.tools_menu.add_command(label="Chọn công cụ ngoài", command=self.browse_external_tool)
        self.tools_menu.add_command(label="Chạy công cụ ngoài", command=self.run_external_tool)
        self.tools_menu.add_separator()
        self.tools_menu.add_command(label="Mở thư mục trích xuất (thủ công)", command=self.open_extracted_texts_folder)

        # Style
        self.style = ttk.Style()
        self.style.configure("TButton", padding=6, relief="flat", background="#ccc")
        self.style.configure("TFrame", background="#f0f0f0")
        self.style.configure("TLabel", background="#f0f0f0")

        # Trạng thái
        self.current_game_path = None
        self.translator = None
        self.game_info = None
        self.translation_thread = None
        self.is_translating = False
        self.auto_detect_var = tk.BooleanVar(value=True)
        self.external_tool_path = None

        # Biến cho tùy chọn quy trình
        self.auto_extract_var = tk.BooleanVar(value=True)
        self.auto_fix_pre_var = tk.BooleanVar(value=True)
        self.auto_fix_post_var = tk.BooleanVar(value=True)
        self.auto_repack_var = tk.BooleanVar(value=True)

        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.models_path = os.path.join(script_dir, "models_nllb_3_3B_ct2_fp16")
        self.output_path = os.path.join(script_dir, "output")
        os.makedirs(self.output_path, exist_ok=True)

        self.create_widgets()
        self._initialize_translator_object()
        self.load_translation_model()

    def create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)
        self.status_bar = ttk.Label(self.root, text="Sẵn sàng", relief=tk.SUNKEN, anchor=tk.W)
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)
        self.create_game_selection(main_frame)
        self.create_translation_options(main_frame)
        self.create_workflow_options(main_frame) # Thêm tùy chọn quy trình
        self.create_action_buttons(main_frame)
        self.create_progress_section(main_frame)
        self.create_log_section(main_frame)
        self.create_module_buttons(main_frame)

    def create_game_selection(self, parent):
        game_frame = ttk.LabelFrame(parent, text="Chọn Game", padding="10")
        game_frame.pack(fill=tk.X, pady=5)
        ttk.Label(game_frame, text="Thư mục game:").grid(row=0, column=0, sticky=tk.W, pady=5)
        path_frame = ttk.Frame(game_frame)
        path_frame.grid(row=0, column=1, sticky=tk.EW, pady=5)
        game_frame.columnconfigure(1, weight=1)
        self.game_path_var = tk.StringVar()
        self.game_path_entry = ttk.Entry(path_frame, textvariable=self.game_path_var)
        self.game_path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        browse_btn = ttk.Button(path_frame, text="Duyệt...", command=self.browse_game_folder)
        browse_btn.pack(side=tk.RIGHT, padx=5)
        analyze_btn = ttk.Button(path_frame, text="Phân tích", command=self.analyze_game)
        analyze_btn.pack(side=tk.RIGHT)
        info_frame = ttk.Frame(game_frame)
        info_frame.grid(row=1, column=0, columnspan=2, sticky=tk.EW, pady=5)
        self.game_info_text = scrolledtext.ScrolledText(info_frame, height=4, wrap=tk.WORD)
        self.game_info_text.pack(fill=tk.X)
        self.game_info_text.insert(tk.END, "Chưa chọn game. Vui lòng chọn thư mục game và nhấn 'Phân tích'.")
        self.game_info_text.config(state=tk.DISABLED)

    def create_translation_options(self, parent):
        options_frame = ttk.LabelFrame(parent, text="Tùy chọn dịch", padding="10")
        options_frame.pack(fill=tk.X, pady=5)
        ttk.Label(options_frame, text="Ngôn ngữ nguồn:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.source_lang_var = tk.StringVar(value="Tự động")
        self.source_lang_combo = ttk.Combobox(options_frame, textvariable=self.source_lang_var, state="readonly")
        self.source_lang_combo.grid(row=0, column=1, sticky=tk.W, pady=5)
        auto_detect_check = ttk.Checkbutton(options_frame, text="Tự động nhận diện", variable=self.auto_detect_var, command=self._toggle_auto_detect)
        auto_detect_check.grid(row=0, column=2, sticky=tk.W, pady=5)
        ttk.Label(options_frame, text="Ngôn ngữ đích:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.target_lang_var = tk.StringVar(value="Vietnamese")
        self.target_lang_combo = ttk.Combobox(options_frame, textvariable=self.target_lang_var, state="readonly")
        self.target_lang_combo.grid(row=1, column=1, sticky=tk.W, pady=5)
        ttk.Label(options_frame, text="Kích thước batch:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.batch_size_var = tk.IntVar(value=8)
        batch_size_entry = ttk.Spinbox(options_frame, from_=1, to=64, textvariable=self.batch_size_var, width=10)
        batch_size_entry.grid(row=2, column=1, sticky=tk.W, pady=5)
        ttk.Label(options_frame, text="Từ điển tùy chỉnh:").grid(row=2, column=2, sticky=tk.W, pady=5, padx=(20, 0))
        dict_frame = ttk.Frame(options_frame)
        dict_frame.grid(row=2, column=3, sticky=tk.W, pady=5)
        self.use_dict_var = tk.BooleanVar(value=True)
        use_dict_check = ttk.Checkbutton(dict_frame, text="Sử dụng", variable=self.use_dict_var)
        use_dict_check.pack(side=tk.LEFT)
        dict_btn = ttk.Button(dict_frame, text="Chọn...", command=self.browse_dictionary)
        dict_btn.pack(side=tk.LEFT, padx=5)
        ttk.Label(options_frame, text="Max Tokens (độ dài tối đa):").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.max_tokens_var = tk.IntVar(value=512)
        max_tokens_entry = ttk.Spinbox(options_frame, from_=50, to=1024, textvariable=self.max_tokens_var, width=10)
        max_tokens_entry.grid(row=3, column=1, sticky=tk.W, pady=5)
        ttk.Label(options_frame, text="Num Beams (chất lượng):").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.num_beams_var = tk.IntVar(value=1)
        num_beams_entry = ttk.Spinbox(options_frame, from_=1, to=10, textvariable=self.num_beams_var, width=10)
        num_beams_entry.grid(row=4, column=1, sticky=tk.W, pady=5)

    def create_workflow_options(self, parent):
        """
        Tạo các tùy chọn quy trình
        """
        workflow_frame = ttk.LabelFrame(parent, text="Quy trình tự động", padding="10")
        workflow_frame.pack(fill=tk.X, pady=5)
        
        self.auto_extract_var = tk.BooleanVar(value=True)
        auto_extract_check = ttk.Checkbutton(workflow_frame, text="Tự động giải nén", variable=self.auto_extract_var)
        auto_extract_check.grid(row=0, column=0, sticky=tk.W, pady=5)
        
        self.auto_fix_pre_var = tk.BooleanVar(value=True)
        auto_fix_pre_check = ttk.Checkbutton(workflow_frame, text="Tự động fix lỗi trước dịch", variable=self.auto_fix_pre_var)
        auto_fix_pre_check.grid(row=0, column=1, sticky=tk.W, pady=5)
        
        self.auto_fix_post_var = tk.BooleanVar(value=True)
        auto_fix_post_check = ttk.Checkbutton(workflow_frame, text="Tự động fix lỗi sau dịch", variable=self.auto_fix_post_var)
        auto_fix_post_check.grid(row=1, column=0, sticky=tk.W, pady=5)
        
        self.auto_repack_var = tk.BooleanVar(value=True)
        auto_repack_check = ttk.Checkbutton(workflow_frame, text="Tự động đóng gói", variable=self.auto_repack_var)
        auto_repack_check.grid(row=1, column=1, sticky=tk.W, pady=5)

    def create_progress_section(self, parent):
        progress_frame = ttk.LabelFrame(parent, text="Tiến trình", padding="10")
        progress_frame.pack(fill=tk.X, pady=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill=tk.X, pady=5)
        self.progress_label = ttk.Label(progress_frame, text="0/0 (0%)")
        self.progress_label.pack(anchor=tk.W)

    def create_log_section(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Log", padding="10")
        log_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        self.log_text = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        self.log("Khởi động công cụ dịch game...")
        self.log(f"Thư mục model: {self.models_path}")
        self.log(f"Thư mục đầu ra: {self.output_path}")

    def create_module_buttons(self, parent):
        """
        Tạo các nút động cho từng module mở rộng (giải nén, fix tự động, dịch tiếp, ghép game, dịch file lẻ, v.v.)
        """
        module_frame = ttk.LabelFrame(parent, text="Chức năng mở rộng (Module hóa)", padding="10")
        module_frame.pack(fill=tk.X, pady=5)
        for menu_name, run_func, mod in self.modules:
            btn = ttk.Button(module_frame, text=menu_name, command=lambda f=run_func: self.run_module(f))
            btn.pack(side=tk.LEFT, padx=5, pady=5)
            self.module_buttons.append(btn)

    def run_module(self, run_func):
        """
        Gọi hàm run() của module, truyền vào self (GUI) để module có thể thao tác với GUI nếu cần.
        """
        try:
            run_func(self)
        except Exception as e:
            self.log(f"Lỗi khi chạy module: {e}", level="error")
            messagebox.showerror("Lỗi", f"Lỗi khi chạy module: {e}")

    def log(self, message, level="info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = "[INFO]"
        tag = ""
        if level == "error":
            prefix = "[LỖI]"
            tag = "error"
        elif level == "warning":
            prefix = "[CẢNH BÁO]"
            tag = "warning"
        log_message = f"{timestamp} {prefix} {message}\n"
        self.log_text.config(state=tk.NORMAL)
        if tag:
            self.log_text.tag_config("error", foreground="red")
            self.log_text.tag_config("warning", foreground="orange")
            self.log_text.insert(tk.END, log_message, tag)
        else:
            self.log_text.insert(tk.END, log_message)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
        self.status_bar.config(text=message)
        self.root.update_idletasks()

    def update_progress(self, current, total, step=""):
        if not total:
            self.progress_var.set(0)
            self.progress_label.config(text=f"0/0 (0%) - {step}")
            return
        percent = (current / total) * 100
        self.progress_var.set(percent)
        self.progress_label.config(text=f"{current}/{total} ({percent:.1f}%) - {step}")
        self.root.update_idletasks()

    def _initialize_translator_object(self):
        try:
            self.log("Đang khởi tạo đối tượng AutoTranslator...")
            self.translator = AutoTranslator(
                models_path=self.models_path,
                output_base_path=self.output_path,
                status_callback=self.log,
                progress_callback=self.update_progress
            )
            self.log("Đã khởi tạo đối tượng AutoTranslator thành công.")
        except Exception as e:
            self.log(f"Lỗi khi khởi tạo đối tượng AutoTranslator: {str(e)}", level="error")
            messagebox.showerror("Lỗi", f"Không thể khởi tạo AutoTranslator: {str(e)}")

    def is_model_loaded(self):
        """
        Kiểm tra xem model dịch và SentencePiece model đã được tải hoàn chỉnh chưa.
        """
        return (
            self.translator is not None and
            getattr(self.translator, "translator", None) is not None and
            getattr(self.translator, "sp_model", None) is not None
        )

    def browse_game_folder(self):
        folder_path = filedialog.askdirectory(title="Chọn thư mục game")
        if folder_path:
            self.game_path_var.set(folder_path)
            self.current_game_path = folder_path
            self.log(f"Đã chọn thư mục game: {folder_path}")
            self.analyze_game()
            self._update_action_button_states()  # Đảm bảo cập nhật trạng thái nút sau khi chọn game

    def browse_dictionary(self):
        file_path = filedialog.askopenfilename(
            title="Chọn file từ điển",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if file_path:
            self.log(f"Đã chọn file từ điển: {file_path}")

    def analyze_game(self):
        game_path = self.game_path_var.get()
        if not game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        if not self.is_model_loaded():
            self.log("Translator chưa sẵn sàng. Không thể phân tích game. Vui lòng tải model trước.", level="error")
            messagebox.showerror("Lỗi", "Translator chưa sẵn sàng. Vui lòng kiểm tra log hoặc tải model trước.")
            return
        self.log(f"Đang phân tích game trong thư mục: {game_path}")
        try:
            # Sử dụng detect_game_engine từ translator để lấy engine_type
            engine_type = self.translator.detect_game_engine(game_path)
            # Giả định game_info sẽ bao gồm engine type
            self.game_info = {
                'name': os.path.basename(game_path),
                'engine': engine_type,
                'lines': 'N/A', # Số dòng văn bản cần được tính sau khi extract
                'can_continue': False, # Cần kiểm tra trạng thái dịch cũ
                'can_repack': False # Cần kiểm tra khả năng đóng gói sau khi extract/dịch
            }
            # Cập nhật thông tin game info dựa trên kết quả phân tích sâu hơn
            # Ví dụ, nếu có file text đã extract từ trước, có thể tính số dòng
            # và cập nhật 'can_continue' / 'can_repack'
            
            # Cập nhật hiển thị Game Info
            self.game_info_text.config(state=tk.NORMAL)
            self.game_info_text.delete(1.0, tk.END)
            info_text = f"Tên game: {self.game_info['name']}\n"
            info_text += f"Engine: {self.game_info['engine']}\n"
            info_text += f"Số dòng văn bản: {self.game_info['lines']}\n"
            info_text += f"Có thể tiếp tục dịch: {'Có' if self.game_info['can_continue'] else 'Không'}\n"
            info_text += f"Có thể đóng gói: {'Có' if self.game_info['can_repack'] else 'Không'}"
            self.game_info_text.insert(tk.END, info_text)
            self.game_info_text.config(state=tk.DISABLED)
            self.log("Phân tích game hoàn tất.")
            # Cập nhật trạng thái các nút sau khi phân tích
            self._update_action_button_states()
        except Exception as e:
            self.log(f"Lỗi khi phân tích game: {str(e)}", level="error")
            messagebox.showerror("Lỗi", f"Không thể phân tích game: {str(e)}")

    def load_translation_model(self):
        if not self.translator:
            messagebox.showwarning("Cảnh báo", "Đối tượng Translator chưa được khởi tạo. Vui lòng khởi động lại ứng dụng.")
            return
        self.log("Đang tải model dịch...")
        # Vô hiệu hóa nút tải model để tránh tải nhiều lần
        self.load_model_btn.config(state=tk.DISABLED)
        threading.Thread(target=self._load_model_thread, daemon=True).start()

    def _load_model_thread(self):
        try:
            self.translator.initialize()
            self.log("Đã tải model dịch thành công.")
            self.root.after(0, self._enable_action_buttons_after_model_load)
            self.root.after(0, self.update_language_list)
        except Exception as e:
            error_message = str(e)
            self.log(f"Lỗi khi tải model dịch: {error_message}", level="error")
            self.root.after(0, lambda err=error_message: messagebox.showerror("Lỗi", f"Không thể tải model dịch: {err}"))
            self.root.after(0, self._disable_action_buttons_on_error)
        finally:
            self.root.after(0, lambda: self.load_model_btn.config(state=tk.NORMAL)) # Re-enable load model button

    def open_extracted_texts_folder(self):
        if not self.current_game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        # Thay đổi đường dẫn đến thư mục chứa file đã giải nén
        game_name = os.path.basename(self.current_game_path)
        extracted_dir = os.path.join(self.output_path, "extracted_game_files", game_name)
        
        if not os.path.exists(extracted_dir):
            messagebox.showwarning("Cảnh báo", "Chưa có file đã giải nén. Hãy thực hiện bước giải nén trước.")
            return
        try:
            self.log(f"Mở thư mục chứa văn bản đã trích xuất: {extracted_dir}")
            if sys.platform == "win32":
                os.startfile(extracted_dir)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.call(['open', extracted_dir])
            else:
                import subprocess
                subprocess.call(['xdg-open', extracted_dir])
        except Exception as e:
            self.log(f"Lỗi khi mở thư mục: {str(e)}", level="error")
            messagebox.showerror("Lỗi", f"Không thể mở thư mục: {str(e)}")

    def browse_external_tool(self):
        file_path = filedialog.askopenfilename(
            title="Chọn công cụ ngoài (ví dụ: .exe, .bat, .py)",
            filetypes=[("Executable files", "*.exe;*.bat;*.py"), ("All files", "*.*")]
        )
        if file_path:
            self.external_tool_path = file_path
            self.log(f"Đã chọn công cụ ngoài: {file_path}")
            self._update_action_button_states() # Cập nhật trạng thái nút 'Chạy công cụ ngoài'

    def run_external_tool(self):
        if hasattr(self, "external_tool_path") and self.external_tool_path:
            try:
                self.log(f"Đang chạy công cụ ngoài: {self.external_tool_path}")
                if sys.platform == "win32":
                    os.startfile(self.external_tool_path)
                else:
                    os.system(f'"{self.external_tool_path}"')
            except Exception as e:
                self.log(f"Lỗi khi chạy công cụ ngoài: {str(e)}", level="error")
                messagebox.showerror("Lỗi", f"Không thể chạy công cụ ngoài: {str(e)}")
        else:
            messagebox.showwarning("Cảnh báo", "Chưa chọn công cụ ngoài nào!")

    def update_language_list(self):
        default_languages = ["English", "Japanese", "Chinese", "Korean", "French", "Russian", "Vietnamese"]
        language_names = default_languages.copy()
        if self.translator and self.translator.sp_model: # Kiểm tra sp_model thay vì tokenizer
            try:
                languages = self.translator.get_supported_languages()
                if languages and isinstance(languages, dict) and len(languages) > 0:
                    language_names = list(languages.keys())
                    self.log(f"Đã lấy {len(language_names)} ngôn ngữ từ translator.")
                else:
                    self.log("Translator không trả về danh sách ngôn ngữ hợp lệ, sử dụng danh sách mặc định.", level="warning")
            except Exception as e:
                self.log(f"Không thể lấy danh sách ngôn ngữ từ translator: {str(e)}", level="error")
        else:
            self.log("Translator hoặc SentencePiece model chưa sẵn sàng, sử dụng danh sách ngôn ngữ mặc định.", level="warning")
        self.log(f"Danh sách ngôn ngữ hiện tại: {language_names}")
        priority_languages = ["English", "Japanese", "Chinese", "Korean", "French", "Russian", "Vietnamese"]
        remaining_languages = sorted(list(set(language_names) - set(priority_languages)))
        sorted_languages = [lang for lang in priority_languages if lang in language_names] + remaining_languages
        source_languages = ["Tự động"] + sorted_languages
        self.source_lang_combo['values'] = source_languages
        self.target_lang_combo['values'] = sorted_languages
        if self.auto_detect_var.get():
            self.source_lang_var.set("Tự động")
            self.source_lang_combo.config(state="disabled")
        else:
            current_values = list(self.source_lang_combo['values'])
            if not current_values or (len(current_values) == 1 and current_values[0] == "Tự động"):
                self.update_language_list()
            self.source_lang_combo.config(state="readonly")
            if self.source_lang_var.get() == "Tự động":
                updated_values = list(self.source_lang_combo['values'])
                if "Tự động" in updated_values:
                    updated_values.remove("Tự động")
                if len(updated_values) > 0:
                    if "English" in updated_values:
                        self.source_lang_var.set("English")
                    else:
                        self.source_lang_var.set(updated_values[0])
                else:
                    self.source_lang_var.set("")
        if "Vietnamese" in sorted_languages:
            self.target_lang_var.set("Vietnamese")
        elif len(sorted_languages) > 0:
            self.target_lang_var.set(sorted_languages[0])
        else:
            self.target_lang_var.set("")
        self.log(f"Đã cập nhật danh sách ngôn ngữ cuối cùng cho UI: {source_languages} (Nguồn) và {sorted_languages} (Đích)")

    def _toggle_auto_detect(self):
        if self.auto_detect_var.get():
            self.source_lang_var.set("Tự động")
            self.source_lang_combo.config(state="disabled")
        else:
            current_values = list(self.source_lang_combo['values'])
            if not current_values or (len(current_values) == 1 and current_values[0] == "Tự động"):
                self.update_language_list()
            self.source_lang_combo.config(state="readonly")
            if self.source_lang_var.get() == "Tự động":
                updated_values = list(self.source_lang_combo['values'])
                if "Tự động" in updated_values:
                    updated_values.remove("Tự động")
                if len(updated_values) > 0:
                    if "English" in updated_values:
                        self.source_lang_var.set("English")
                    else:
                        self.source_lang_var.set(updated_values[0])
                else:
                    self.source_lang_var.set("")
    
    def create_action_buttons(self, parent):
        """Tạo các nút hành động."""
        actions_frame = ttk.LabelFrame(parent, text="Hành động", padding="10")
        actions_frame.pack(fill=tk.X, pady=5)
        
        # Hàng 1: Các nút chính
        btn_frame1 = ttk.Frame(actions_frame)
        btn_frame1.pack(fill=tk.X, pady=5)
        
        self.start_full_workflow_btn = ttk.Button(btn_frame1, text="Bắt đầu quy trình tự động", command=self.start_full_workflow)
        self.start_full_workflow_btn.pack(side=tk.LEFT, padx=5)

        self.new_translation_btn = ttk.Button(btn_frame1, text="Dịch mới (Chỉ Dịch)", command=self.start_new_translation)
        self.new_translation_btn.pack(side=tk.LEFT, padx=5)
        
        self.continue_translation_btn = ttk.Button(btn_frame1, text="Tiếp tục dịch (Chỉ Dịch)", command=self.continue_translation)
        self.continue_translation_btn.pack(side=tk.LEFT, padx=5)
        self.continue_translation_btn.config(state=tk.DISABLED)
        
        self.edit_translation_btn = ttk.Button(btn_frame1, text="Sửa bản dịch", command=self.edit_translation)
        self.edit_translation_btn.pack(side=tk.LEFT, padx=5)
        self.edit_translation_btn.config(state=tk.DISABLED)
        
        # Hàng 2: Các nút bổ sung
        btn_frame2 = ttk.Frame(actions_frame)
        btn_frame2.pack(fill=tk.X, pady=5)
        
        self.repack_game_btn = ttk.Button(btn_frame2, text="Đóng gói game (Chỉ đóng gói)", command=self.repack_game)
        self.repack_game_btn.pack(side=tk.LEFT, padx=5)
        self.repack_game_btn.config(state=tk.DISABLED)
        
        self.cancel_btn = ttk.Button(btn_frame2, text="Hủy", command=self.cancel_translation)
        self.cancel_btn.pack(side=tk.LEFT, padx=5)
        self.cancel_btn.config(state=tk.DISABLED)
        
        self.load_model_btn = ttk.Button(btn_frame2, text="Tải model", command=self.load_translation_model)
        self.load_model_btn.pack(side=tk.LEFT, padx=5)
        
        # Nút Mở thư mục trích xuất (thay thế nút "Dùng tool thủ công")
        self.open_extracted_texts_folder_btn = ttk.Button(btn_frame2, text="Mở thư mục trích xuất", command=self.open_extracted_texts_folder)
        self.open_extracted_texts_folder_btn.pack(side=tk.LEFT, padx=5)

        # Nút chọn và chạy công cụ ngoài
        self.browse_external_tool_btn = ttk.Button(btn_frame2, text="Chọn công cụ ngoài", command=self.browse_external_tool)
        self.browse_external_tool_btn.pack(side=tk.LEFT, padx=5)
        
        self.run_external_tool_btn = ttk.Button(btn_frame2, text="Chạy công cụ ngoài", command=self.run_external_tool)
        self.run_external_tool_btn.pack(side=tk.LEFT, padx=5)
    
    def _update_action_button_states(self):
        """Cập nhật trạng thái của các nút hành động dựa trên model và game info."""
        model_is_loaded = self.is_model_loaded()
        game_selected = self.current_game_path is not None
        can_continue = self.game_info and self.game_info.get('can_continue', False)
        can_repack = self.game_info and self.game_info.get('can_repack', False)

        # Cập nhật trạng thái các nút chính
        self.start_full_workflow_btn.config(state=tk.NORMAL if model_is_loaded and game_selected and not self.is_translating else tk.DISABLED)
        self.new_translation_btn.config(state=tk.NORMAL if model_is_loaded and game_selected and not self.is_translating else tk.DISABLED)
        self.continue_translation_btn.config(state=tk.NORMAL if model_is_loaded and game_selected and can_continue and not self.is_translating else tk.DISABLED)
        self.edit_translation_btn.config(state=tk.NORMAL if model_is_loaded and game_selected and can_repack and not self.is_translating else tk.DISABLED)
        self.repack_game_btn.config(state=tk.NORMAL if model_is_loaded and game_selected and can_repack and not self.is_translating else tk.DISABLED)
        
        # Các nút/menu liên quan đến thư mục/công cụ ngoài (ít phụ thuộc vào model tải)
        # và không bị vô hiệu hóa khi đang dịch các quy trình tự động khác
        self.open_extracted_texts_folder_btn.config(state=tk.NORMAL if game_selected and not self.is_translating else tk.DISABLED)
        self.browse_external_tool_btn.config(state=tk.NORMAL if not self.is_translating else tk.DISABLED) 
        self.run_external_tool_btn.config(state=tk.NORMAL if self.external_tool_path and not self.is_translating else tk.DISABLED) 

        # Cập nhật trạng thái menu
        self.tools_menu.entryconfig("Mở thư mục trích xuất (thủ công)", state="normal" if game_selected and not self.is_translating else "disabled")
        self.tools_menu.entryconfig("Chọn công cụ ngoài", state="normal" if not self.is_translating else "disabled")
        self.tools_menu.entryconfig("Chạy công cụ ngoài", state="normal" if self.external_tool_path and not self.is_translating else "disabled")
        
        # Nút "Hủy" chỉ bật khi đang dịch
        self.cancel_btn.config(state=tk.NORMAL if self.is_translating else tk.DISABLED)


    def _enable_action_buttons_after_model_load(self):
        """Kích hoạt các nút hành động sau khi model tải thành công."""
        self._update_action_button_states() # Gọi hàm cập nhật trạng thái tổng thể

    def _disable_action_buttons_on_error(self):
        """Vô hiệu hóa các nút hành động khi có lỗi tải model."""
        self.start_full_workflow_btn.config(state=tk.DISABLED)
        self.new_translation_btn.config(state=tk.DISABLED)
        self.continue_translation_btn.config(state=tk.DISABLED)
        self.edit_translation_btn.config(state=tk.DISABLED)
        self.repack_game_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.DISABLED)
        self.open_extracted_texts_folder_btn.config(state=tk.DISABLED)
        self.browse_external_tool_btn.config(state=tk.DISABLED)
        self.run_external_tool_btn.config(state=tk.DISABLED)
        self.tools_menu.entryconfig("Mở thư mục trích xuất (thủ công)", state="disabled")
        self.tools_menu.entryconfig("Chọn công cụ ngoài", state="disabled")
        self.tools_menu.entryconfig("Chạy công cụ ngoài", state="disabled")

    def start_new_translation(self):
        """Bắt đầu quá trình dịch mới (chỉ dịch)."""
        if not self.current_game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        
        if not self.is_model_loaded():
            messagebox.showwarning("Cảnh báo", "Model dịch chưa được tải. Vui lòng tải model trước.")
            return

        if messagebox.askyesno("Xác nhận", "Bắt đầu dịch mới sẽ xóa tất cả dữ liệu dịch cũ. Tiếp tục?"):
            self.update_progress(0, 1, "Bắt đầu dịch mới...") # Reset progress bar
            self._prepare_translation_thread(is_full_workflow=False, is_continue=False)
    
    def continue_translation(self):
        """Tiếp tục quá trình dịch từ trạng thái đã lưu (chỉ dịch)."""
        if not self.current_game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        
        if not self.is_model_loaded():
            messagebox.showwarning("Cảnh báo", "Model dịch chưa được tải. Vui lòng tải model trước.")
            return

        if not self.game_info or not self.game_info.get('can_continue', False):
            messagebox.showwarning("Cảnh báo", "Không thể tiếp tục dịch. Không tìm thấy trạng thái dịch trước đó.")
            return
        
        self.update_progress(0, 1, "Tiếp tục dịch...") # Reset progress bar
        self._prepare_translation_thread(is_full_workflow=False, is_continue=True)
    
    def edit_translation(self):
        """Mở thư mục chứa bản dịch đã tạo để chỉnh sửa thủ công."""
        if not self.current_game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        
        # Đường dẫn đến thư mục chứa các file đã dịch
        game_name = os.path.basename(self.current_game_path)
        translated_dir = os.path.join(self.output_path, "translated_game_files", game_name)

        if not os.path.exists(translated_dir):
            messagebox.showwarning("Cảnh báo", "Không tìm thấy bản dịch để sửa. Vui lòng dịch game trước.")
            return

        try:
            self.log(f"Mở thư mục chứa bản dịch để chỉnh sửa: {translated_dir}")
            if sys.platform == "win32":
                os.startfile(translated_dir)
            elif sys.platform == "darwin":
                import subprocess
                subprocess.call(['open', translated_dir])
            else:
                import subprocess
                subprocess.call(['xdg-open', translated_dir])
        except Exception as e:
            self.log(f"Lỗi khi mở thư mục chỉnh sửa: {str(e)}", level="error")
            messagebox.showerror("Lỗi", f"Không thể mở thư mục chỉnh sửa: {str(e)}")

    def repack_game(self):
        """Đóng gói game hoàn chỉnh (chỉ đóng gói)."""
        if not self.current_game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        
        if not self.is_model_loaded(): # Vẫn cần translator object để gọi repack_game
            messagebox.showwarning("Cảnh báo", "Model dịch chưa được tải. Vui lòng tải model trước.")
            return

        if not self.game_info or not self.game_info.get('can_repack', False):
            messagebox.showwarning("Cảnh báo", "Không thể đóng gói lại game. Không tìm thấy đủ dữ liệu đã dịch.")
            return
        
        # Lấy đường dẫn của các file đã dịch và engine type
        game_name = os.path.basename(self.current_game_path)
        translated_files_path = os.path.join(self.output_path, "translated_game_files", game_name)
        engine_type = self.translator.detect_game_engine(self.current_game_path)

        if not os.path.exists(translated_files_path):
            messagebox.showwarning("Cảnh báo", "Không tìm thấy thư mục chứa file đã dịch. Vui lòng dịch game trước.")
            return

        self.log("Bắt đầu đóng gói game...")
        self.update_progress(0, 1, "Đang đóng gói game...")
        
        self.is_translating = True # Coi như một hành động "dịch" lớn
        self._update_action_button_states()

        threading.Thread(
            target=self._repack_game_thread,
            args=(translated_files_path, self.current_game_path, engine_type),
            daemon=True
        ).start()

    def _repack_game_thread(self, translated_files_path, original_game_path, engine_type):
        """Luồng đóng gói game."""
        try:
            success = self.translator.repack_game(translated_files_path, original_game_path, engine_type)
            if success:
                self.log("Đóng gói game hoàn tất.", level="info")
                self.root.after(0, lambda: messagebox.showinfo("Thành công", "Đã đóng gói game thành công!"))
            else:
                self.log("Đóng gói game thất bại.", level="error")
                self.root.after(0, lambda: messagebox.showerror("Lỗi", "Đóng gói game thất bại. Kiểm tra log để biết chi tiết."))
        except Exception as e:
            self.log(f"Lỗi trong quá trình đóng gói game: {str(e)}", level="error")
            self.root.after(0, lambda err=str(e): messagebox.showerror("Lỗi", f"Lỗi trong quá trình đóng gói game: {err}"))
        finally:
            self.root.after(0, self._reset_ui_after_translation) # Reset UI sau khi đóng gói
            self.is_translating = False


    def cancel_translation(self):
        """Hủy quá trình dịch đang chạy."""
        if self.translation_thread and self.translation_thread.is_alive():
            # Cách an toàn để dừng thread là đặt một cờ và thread tự kiểm tra
            # Hiện tại AutoTranslator không có cờ này, nên đây chỉ là một placeholder
            # hoặc bạn cần thêm cơ chế dừng vào AutoTranslator.
            messagebox.showwarning("Cảnh báo", "Chức năng hủy hiện tại chưa được triển khai đầy đủ. Vui lòng đợi hoặc đóng ứng dụng.")
            self.log("Đã yêu cầu hủy, nhưng chức năng hủy thread chưa được hỗ trợ đầy đủ.", level="warning")
            # Nếu bạn thêm cờ stop vào AutoTranslator:
            # self.translator.stop_translation = True 
        else:
            self.log("Không có quá trình dịch nào đang chạy để hủy.", level="info")
            self._reset_ui_after_translation() # Vẫn reset UI nếu không có gì để hủy

    def start_full_workflow(self):
        """
        Thực hiện toàn bộ quy trình tự động trong một thread.
        """
        if not self.current_game_path:
            messagebox.showwarning("Cảnh báo", "Vui lòng chọn thư mục game trước.")
            return
        
        if not self.is_model_loaded():
            messagebox.showwarning("Cảnh báo", "Model dịch chưa được tải. Vui lòng tải model trước.")
            return

        if messagebox.askyesno("Xác nhận", "Bắt đầu quy trình tự động sẽ chạy toàn bộ các bước đã chọn. Tiếp tục?"):
            self.update_progress(0, 1, "Bắt đầu quy trình tự động...")
            self.is_translating = True
            self._update_action_button_states()

            threading.Thread(
                target=self._full_workflow_thread,
                args=(self.current_game_path, self.auto_extract_var.get(),
                      self.auto_fix_pre_var.get(), self.auto_fix_post_var.get(),
                      self.auto_repack_var.get()),
                daemon=True
            ).start()

    def _full_workflow_thread(self, game_path, auto_extract, auto_fix_pre, auto_fix_post, auto_repack):
        """Luồng thực hiện toàn bộ quy trình tự động."""
        try:
            self.translator.clean_previous_data(game_path) # Luôn làm sạch khi bắt đầu quy trình tự động mới
            engine_type = self.translator.detect_game_engine(game_path)
            
            extracted_files_path = None # Sẽ lưu đường dẫn các file đã giải nén
            translated_files_path = None # Sẽ lưu đường dẫn các file đã dịch

            # 1. Giải nén
            if auto_extract:
                self.log("Bắt đầu giải nén game...", level="info")
                if not self.translator.extract_game_files(game_path, engine_type):
                    self.log("Giải nén thất bại hoặc không có file để giải nén. Dừng quy trình.", level="error")
                    self.root.after(0, lambda: messagebox.showerror("Lỗi", "Giải nén thất bại. Kiểm tra log."))
                    return
                extracted_files_path = os.path.join(self.output_path, "extracted_game_files", os.path.basename(game_path))
                self.log(f"Đã giải nén vào: {extracted_files_path}", level="info")
            else:
                self.log("Bỏ qua bước giải nén game.", level="info")
                # Nếu không tự động giải nén, giả định file gốc đã được giải nén sẵn
                # và các file văn bản có thể được tìm thấy trực tiếp trong thư mục game hoặc một đường dẫn đã biết.
                # Tuy nhiên, để quy trình dịch và fix lỗi hoạt động, cần có dữ liệu đã extract.
                # Ở đây, ta sẽ đặt extracted_files_path thành game_path nếu bỏ qua giải nén,
                # nhưng điều này có thể cần tùy chỉnh thêm trong AutoTranslator
                # để xử lý trực tiếp file game mà không cần thư mục trung gian.
                # Tạm thời để đơn giản, nếu không extract, thì xem như không có dữ liệu để dịch.
                self.log("Cảnh báo: Nếu không tự động giải nén, quá trình dịch và fix lỗi có thể không tìm thấy dữ liệu đầu vào.", level="warning")
                # Đặt extracted_files_path để tiếp tục quy trình nếu người dùng biết rõ file dịch nằm ở đâu trong game_path
                extracted_files_path = game_path 


            # 2. Fix lỗi trước dịch
            if auto_fix_pre and extracted_files_path:
                self.log("Bắt đầu fix lỗi trước dịch...", level="info")
                self.translator.fix_pre_translation_issues(extracted_files_path, engine_type)
            else:
                self.log("Bỏ qua bước fix lỗi trước dịch.", level="info")

            # 3. Dịch
            self.log("Bắt đầu dịch game...", level="info")
            translation_params = {
                "source_lang": "auto" if self.auto_detect_var.get() else self.source_lang_var.get(),
                "target_lang": self.target_lang_var.get(),
                "batch_size": self.batch_size_var.get(),
                "use_dictionary": self.use_dict_var.get(),
                "auto_detect": self.auto_detect_var.get(),
                "max_tokens": self.max_tokens_var.get(),
                "num_beams": self.num_beams_var.get()
            }
            # Gọi translate_game với đường dẫn file đã giải nén
            success_translate = self.translator.translate_game(extracted_files_path, translation_params, is_continue=False)
            if not success_translate:
                self.log("Quá trình dịch thất bại. Dừng quy trình.", level="error")
                self.root.after(0, lambda: messagebox.showerror("Lỗi", "Quá trình dịch thất bại. Kiểm tra log."))
                return
            translated_files_path = os.path.join(self.output_path, "translated_game_files", os.path.basename(game_path))
            self.log(f"Đã dịch và lưu vào: {translated_files_path}", level="info")


            # 4. Fix lỗi sau dịch
            if auto_fix_post and translated_files_path:
                self.log("Bắt đầu fix lỗi sau dịch...", level="info")
                self.translator.fix_post_translation_issues(translated_files_path, engine_type)
            else:
                self.log("Bỏ qua bước fix lỗi sau dịch.", level="info")

            # 5. Đóng gói
            if auto_repack and translated_files_path:
                self.log("Bắt đầu đóng gói game...", level="info")
                if not self.translator.repack_game(translated_files_path, game_path, engine_type):
                    self.log("Đóng gói game thất bại. Kiểm tra log.", level="error")
                    self.root.after(0, lambda: messagebox.showerror("Lỗi", "Đóng gói game thất bại. Kiểm tra log."))
                    return
            else:
                self.log("Bỏ qua bước đóng gói game.", level="info")
            
            self.log("Hoàn tất quy trình tự động!", level="info")
            self.root.after(0, lambda: messagebox.showinfo("Thành công", "Quy trình tự động đã hoàn tất!"))

        except Exception as e:
            self.log(f"Lỗi trong quá trình tự động hóa: {str(e)}", level="error")
            self.root.after(0, lambda err=str(e): messagebox.showerror("Lỗi", f"Lỗi trong quy trình tự động hóa: {err}"))
        finally:
            self.root.after(0, self._reset_ui_after_translation)
            self.is_translating = False
    
    def _prepare_translation_thread(self, is_full_workflow, is_continue):
        """
        Chuẩn bị và bắt đầu quá trình dịch trong một thread riêng.
        is_full_workflow: cờ để biết nếu luồng này là một phần của quy trình tự động hoàn chỉnh.
                          Nếu là False, nó chỉ thực hiện bước DỊCH.
        """
        # Vô hiệu hóa các nút trong khi dịch
        self.new_translation_btn.config(state=tk.DISABLED)
        self.continue_translation_btn.config(state=tk.DISABLED)
        self.edit_translation_btn.config(state=tk.DISABLED)
        self.repack_game_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.start_full_workflow_btn.config(state=tk.DISABLED) # Vô hiệu hóa nút full workflow
        
        # Vô hiệu hóa các nút/menu liên quan đến thư mục/công cụ ngoài khi đang dịch
        self.open_extracted_texts_folder_btn.config(state=tk.DISABLED)
        self.browse_external_tool_btn.config(state=tk.DISABLED)
        self.run_external_tool_btn.config(state=tk.DISABLED)
        self.tools_menu.entryconfig("Mở thư mục trích xuất (thủ công)", state="disabled")
        self.tools_menu.entryconfig("Chọn công cụ ngoài", state="disabled")
        self.tools_menu.entryconfig("Chạy công cụ ngoài", state="disabled")

        
        # Chuẩn bị tham số dịch
        translation_params = {
            "source_lang": "auto" if self.auto_detect_var.get() else self.source_lang_var.get(),
            "target_lang": self.target_lang_var.get(),
            "batch_size": self.batch_size_var.get(),
            "use_dictionary": self.use_dict_var.get(),
            "auto_detect": self.auto_detect_var.get(),
            "max_tokens": self.max_tokens_var.get(),
            "num_beams": self.num_beams_var.get()
        }
        
        # Bắt đầu dịch trong một thread riêng
        self.is_translating = True
        self.translation_thread = threading.Thread(
            target=self._run_translation_only, # Sử dụng hàm riêng cho "chỉ dịch"
            args=(self.current_game_path, translation_params, is_continue),
            daemon=True
        )
        self.translation_thread.start()
    
    def _run_translation_only(self, game_path, params, is_continue):
        """Hàm chỉ dịch, không bao gồm extract hay repack."""
        try:
            # Điều này giả định rằng file text đã được trích xuất hoặc có sẵn để dịch.
            # Trong một workflow thực tế, bạn cần xác định đường dẫn này.
            # Ví dụ: game_path có thể là thư mục chứa các file TXT/JSON cần dịch.
            
            # Để đơn giản, giả sử extracted_files_path là game_path. 
            # Thực tế cần thông minh hơn để tìm đường dẫn của các file cần dịch.
            # Ví dụ, có thể là thư mục con 'extracted_game_files' nếu đã chạy extract thủ công.
            extracted_files_path = os.path.join(self.output_path, "extracted_game_files", os.path.basename(game_path))
            if not os.path.exists(extracted_files_path):
                self.log(f"Không tìm thấy thư mục chứa file đã giải nén tại '{extracted_files_path}'. Vui lòng giải nén trước hoặc kiểm tra lại đường dẫn.", level="error")
                self.root.after(0, lambda: messagebox.showerror("Lỗi", "Không tìm thấy file để dịch. Hãy giải nén game trước."))
                return False

            self.log(f"Bắt đầu {'tiếp tục ' if is_continue else ''}dịch các file trong '{extracted_files_path}'...", level="info")
            # `translate_game` trong AutoTranslator cần được điều chỉnh để làm việc với đường dẫn `extracted_files_path`
            success = self.translator.translate_game(extracted_files_path, params, is_continue)
            
            if success:
                self.log("Quá trình dịch đã hoàn thành.", level="info")
                self.root.after(0, self._translation_completed)
            else:
                self.log("Quá trình dịch thất bại.", level="error")
                self.root.after(0, lambda: messagebox.showerror("Lỗi", "Quá trình dịch thất bại. Kiểm tra log."))

        except Exception as e:
            self.log(f"Lỗi trong quá trình dịch: {str(e)}", level="error")
            self.root.after(0, lambda err=str(e): messagebox.showerror("Lỗi", f"Lỗi trong quá trình dịch: {err}"))
        finally:
            self.is_translating = False
            self.root.after(0, self._reset_ui_after_translation) # Luôn reset UI

    def _translation_completed(self):
        """Xử lý khi hoàn thành dịch (áp dụng cho cả dịch mới và tiếp tục dịch)."""
        self.log("Quá trình dịch đã hoàn thành.")
        messagebox.showinfo("Thành công", "Quá trình dịch đã hoàn thành.")
        self.root.after(0, self._reset_ui_after_translation) # Đảm bảo UI được reset sau khi hoàn thành
        
    def _reset_ui_after_translation(self):
        """Đặt lại trạng thái UI sau khi quá trình dịch/tự động hóa hoàn tất hoặc lỗi."""
        self.is_translating = False
        self._update_action_button_states()
        self.progress_var.set(0)
        self.progress_label.config(text="0/0 (0%) - Hoàn tất")
        # Gọi lại analyze_game để cập nhật game_info và trạng thái nút sau khi dịch/đóng gói
        if self.current_game_path:
            self.analyze_game() 


if __name__ == "__main__":
    root = tk.Tk()
    app = AutoTranslatorGUI(root)
    root.mainloop()
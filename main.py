import sys
import os
import re
import subprocess
import tempfile
import shutil
import unicodedata
from contextlib import contextmanager
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QFileDialog, 
                             QTextEdit, QSpinBox, QTabWidget, QMessageBox, 
                             QToolBar, QStyle, QFrame, QStatusBar, QLineEdit)
from PyQt6.QtCore import Qt, QUrl, QSize, QTimer
from PyQt6.QtGui import QAction, QIcon, QFont, QTextCursor, QKeySequence



SEPARATOR_TEXT = "=== 正文开始 (下方使用印刷页码) ==="

def roman_to_int(s):
    """Convert Roman numeral to integer."""
    roman = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}
    s = s.lower()
    num = 0
    for i in range(len(s)):
        if i > 0 and roman[s[i]] > roman[s[i - 1]]:
            num += roman[s[i]] - 2 * roman[s[i - 1]]
        else:
            num += roman[s[i]]
    return num

def int_to_roman(num):
    """Convert integer to Roman numeral."""
    val = [
        1000, 900, 500, 400,
        100, 90, 50, 40,
        10, 9, 5, 4,
        1
    ]
    sy = [
        "m", "cm", "d", "cd",
        "c", "xc", "l", "xl",
        "x", "ix", "v", "iv",
        "i"
    ]
    roman_num = ''
    i = 0
    while num > 0:
        for _ in range(num // val[i]):
            roman_num += sy[i]
            num -= val[i]
        i += 1
    return roman_num

def alpha_to_int(s):
    """Convert alphabetic string to integer (A=1, B=2... AA=27)."""
    s = s.upper()
    num = 0
    for char in s:
        if 'A' <= char <= 'Z':
            num = num * 26 + (ord(char) - ord('A') + 1)
        else:
            return 0
    return num

@contextmanager
def temp_file_context(suffix=".tmp"):
    """Context manager for temporary files that are deleted on exit."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def create_temp_file(suffix=".tmp"):
    """Create a temporary file that must be manually deleted."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    return path


def cleanup_temp_file(path):
    """Safely delete a temporary file."""
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def handle_cpdf_error(parent, error_msg, details=None):
    msg = QMessageBox(parent)
    msg.setIcon(QMessageBox.Icon.Critical)
    msg.setWindowTitle("Error")
    msg.setText(error_msg)
    if details:
        msg.setDetailedText(details)
    msg.exec()


# Check for WebEngine
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

class BookmarkEditor(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self._current_file_path = None
        
        file_layout = QHBoxLayout()
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self.btn_browse = QPushButton("Select PDF")
        self.btn_browse.clicked.connect(self.browse_file)
        file_layout.addWidget(self.btn_browse)
        file_layout.addWidget(self.file_path_label)
        self.layout.addLayout(file_layout)
        
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("正文起始物理页:"))
        self.spin_body_start = QSpinBox()
        self.spin_body_start.setRange(1, 9999)
        self.spin_body_start.setValue(1)
        self.spin_body_start.setToolTip("正文第1页对应的PDF物理页码\n例如：封面是第1页，正文从第11页开始，则填11")
        offset_layout.addWidget(self.spin_body_start)
        
        offset_layout.addSpacing(20)
        offset_layout.addWidget(QLabel("罗马数字起始页:"))
        self.spin_roman_start = QSpinBox()
        self.spin_roman_start.setRange(1, 9999)
        self.spin_roman_start.setValue(1)
        self.spin_roman_start.setToolTip("罗马数字 'i' 对应的物理页码\n通常用于目录或前言")
        offset_layout.addWidget(self.spin_roman_start)
        
        # Connect signals to invalidate cache
        self.spin_body_start.valueChanged.connect(self.on_setting_changed)
        self.spin_roman_start.valueChanged.connect(self.on_setting_changed)
        
        offset_layout.addStretch()
        self.layout.addLayout(offset_layout)
        
        toolbar_layout = QHBoxLayout()
        self.btn_indent = QPushButton("Indent (>)")
        self.btn_indent.clicked.connect(self.indent_text)
        self.btn_unindent = QPushButton("Unindent (<)")
        self.btn_unindent.clicked.connect(self.unindent_text)
        
        # 添加分隔符按钮
        self.btn_separator = QPushButton("插入正文分隔符")
        self.btn_separator.setStyleSheet("font-weight: bold; color: blue;")
        self.btn_separator.clicked.connect(self.insert_separator)
        
        toolbar_layout.addWidget(self.btn_indent)
        toolbar_layout.addWidget(self.btn_unindent)
        toolbar_layout.addSpacing(20)
        toolbar_layout.addWidget(self.btn_separator)
        toolbar_layout.addStretch()
        self.layout.addLayout(toolbar_layout)
        
        # 快捷插入按钮行
        insert_layout = QHBoxLayout()
        insert_layout.addWidget(QLabel("快捷插入:"))
        
        # 前言部分常用条目
        self.preface_items = ["封面", "版权页", "目录", "前言", "序", "简介", "致谢", "凡例"]
        self._next_preface_roman = 1  # 罗马数字计数器
        
        for item in self.preface_items:
            btn = QPushButton(item)
            btn.setMaximumWidth(60)
            btn.clicked.connect(lambda checked, name=item: self.insert_preface_item(name))
            insert_layout.addWidget(btn)
        
        insert_layout.addStretch()
        self.layout.addLayout(insert_layout)
        
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText(
            "格式: [缩进] 标题 页码\n\n"
            "分隔符上方:\n"
            "  - 输入数字 = 物理页码（所见即所得）\n"
            "  - 输入大写字母(A, B) = 物理页码(A=1, B=2...)\n"
            "  - 输入小写罗马数字(i, ii) = 自动计算(起始页 + 偏移)\n\n"
            f"{SEPARATOR_TEXT}\n\n"
            "分隔符下方:\n"
            "  - 输入数字 = 印刷页码（自动加上偏移量）\n\n"
            "示例:\n"
            "封面 A\n"
            "目录 i\n"
            "前言 iii\n"
            f"{SEPARATOR_TEXT}\n"
            "第一章 1\n"
            "\t第一节 5"
        )
        self.text_edit.setFont(QFont("Monospace"))
        self.text_edit.textChanged.connect(self.on_text_changed)
        self.layout.addWidget(self.text_edit)
        
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 12px;")
        self.layout.addWidget(self.status_label)
        
        self.validation_errors = []
        self._preview_cache = None
        self._last_text_hash = None
        
    @property
    def current_file_path(self):
        return self._current_file_path
    
    @current_file_path.setter
    def current_file_path(self, value):
        self._current_file_path = value
        self._preview_cache = None
        self._last_text_hash = None
    
    def on_text_changed(self):
        text = self.text_edit.toPlainText()
        current_hash = hash(text)
        if current_hash != self._last_text_hash:
            self._last_text_hash = current_hash
            self._preview_cache = None
            # 检查偏移量并更新状态
            self.check_offset_suggestion()
    
    def on_setting_changed(self):
        """Invalidate preview cache when settings change."""
        self._preview_cache = None

    def insert_preface_item(self, name):
        """在光标位置插入前言条目，使用罗马数字自动编号"""
        cursor = self.text_edit.textCursor()
        
        # 计算下一个罗马数字
        roman = int_to_roman(self._next_preface_roman)
        self._next_preface_roman += 1
        
        # 插入文本
        line = f"{name} {roman}\n"
        cursor.insertText(line)
        self.text_edit.setTextCursor(cursor)
    
    def reset_preface_counter(self):
        """重置前言页码计数器"""
        self._next_preface_roman = 1
    
    def check_offset_suggestion(self):
        """（暂时禁用）检查偏移量设置是否合理"""
        pass

    def browse_file(self):
        fname, _ = QFileDialog.getOpenFileName(self, "Open PDF", os.getcwd(), "PDF Files (*.pdf)")
        if fname:
            self.current_file_path = fname
            self.file_path_label.setText(os.path.basename(fname))
            self.load_existing_bookmarks()

    def load_existing_bookmarks(self):
        if not self.current_file_path:
            return

        if shutil.which("cpdf") is None:
            return
            
        cmd = ["cpdf", "-list-bookmarks", "-utf8", self.current_file_path]
        try:
            result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            output = result.stdout
        except subprocess.CalledProcessError:
            return

        if not output.strip():
            return

        lines = []
        for line in output.splitlines():
            match = re.search(r'^(\d+)\s+"(.*)"\s+(\d+)', line)
            if match:
                level = int(match.group(1))
                title = match.group(2)
                page = match.group(3)
                
                title = title.replace('\\"', '"')
                
                indent = "\t" * level
                lines.append(f"{indent}{title} {page}")
        
        if lines:
            self.text_edit.setPlainText("\n".join(lines))

    def indent_text(self):
        cursor = self.text_edit.textCursor()
        if cursor.hasSelection():
            # Process selected lines
            start = cursor.selectionStart()
            end = cursor.selectionEnd()
            cursor.setPosition(start)
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            start_block = cursor.blockNumber()
            cursor.setPosition(end)
            end_block = cursor.blockNumber()
            
            cursor.setPosition(start)
            cursor.beginEditBlock()
            for i in range(start_block, end_block + 1):
                block = self.text_edit.document().findBlockByNumber(i)
                cursor.setPosition(block.position())
                cursor.insertText("\t")
            cursor.endEditBlock()
        else:
            # Just insert tab at current line
            cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            cursor.insertText("\t")
            
    def unindent_text(self):
        cursor = self.text_edit.textCursor()
        # Similar logic but remove '\t' or spaces
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        start_block = cursor.blockNumber()
        cursor.setPosition(end)
        end_block = cursor.blockNumber()
        
        cursor.setPosition(start)
        cursor.beginEditBlock()
        for i in range(start_block, end_block + 1):
            block = self.text_edit.document().findBlockByNumber(i)
            text = block.text()
            if text.startswith("\t"):
                cursor.setPosition(block.position())
                cursor.deleteChar()
            elif text.startswith("    "): # Handle 4 spaces
                cursor.setPosition(block.position())
                for _ in range(4): cursor.deleteChar()
        cursor.endEditBlock()

    def insert_separator(self):
        """插入正文分隔符"""
        cursor = self.text_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.insertText(SEPARATOR_TEXT + "\n")
        self.text_edit.setTextCursor(cursor)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Bookmark Editor")
        self.resize(1000, 700)
        
        self.statusBar().showMessage("Ready")
        
        if not HAS_WEBENGINE:
            QMessageBox.warning(self, "Warning", 
                "PyQt6-WebEngine is not installed. Preview will not work.\n"
                "Please install it: pip install PyQt6-WebEngine")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        self.editor = BookmarkEditor()
        self.tabs.addTab(self.editor, "Edit Bookmarks")
        
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        
        if HAS_WEBENGINE:
            self.web_view = QWebEngineView()
            self.web_view.settings().setAttribute(self.web_view.settings().WebAttribute.PluginsEnabled, True)
            self.web_view.settings().setAttribute(self.web_view.settings().WebAttribute.PdfViewerEnabled, True)
            self.preview_layout.addWidget(self.web_view)
        else:
            self.web_view = QLabel("WebEngine not available.\nInstall PyQt6-WebEngine to enable preview.")
            self.web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_layout.addWidget(self.web_view)
            
        preview_bottom_layout = QHBoxLayout()
        self.btn_preview = QPushButton("Refresh Preview")
        self.btn_preview.clicked.connect(self.force_update_preview)
        self.btn_save = QPushButton("Save PDF")
        self.btn_save.setShortcut(QKeySequence("Ctrl+S"))
        self.btn_save.clicked.connect(self.save_pdf)
        preview_bottom_layout.addWidget(self.btn_preview)
        preview_bottom_layout.addWidget(self.btn_save)
        preview_bottom_layout.addStretch()
        self.preview_layout.addLayout(preview_bottom_layout)
        
        self.tabs.addTab(self.preview_container, "Preview")
        
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        self._cpdf_available = self.check_cpdf()
        if not self._cpdf_available:
            QMessageBox.critical(self, "Error", 
                "cpdf command not found. Please install cpdf tools.\n\n"
                "Download: https://community.coherentpdf.com/\n"
                "Or install via package manager:\n"
                "  Debian/Ubuntu: apt install cpdf\n"
                "  macOS: brew install cpdf")
        
        self._create_actions()
    
    def closeEvent(self, event):
        """Clean up temporary files on exit."""
        cleanup_temp_file(self.editor._preview_cache)
        super().closeEvent(event)
        
    def _create_actions(self):
        save_action = QAction("Save", self)
        save_action.setShortcut(QKeySequence("Ctrl+S"))
        save_action.triggered.connect(self.save_pdf)
        self.addAction(save_action)
        
        exit_action = QAction("Exit", self)
        exit_action.setShortcut(QKeySequence("Ctrl+Q"))
        exit_action.triggered.connect(self.close)
        self.addAction(exit_action)
        
        indent_action = QAction("Indent", self)
        indent_action.setShortcut(QKeySequence("Tab"))
        indent_action.triggered.connect(self.editor.indent_text)
        self.addAction(indent_action)
        
        unindent_action = QAction("Unindent", self)
        unindent_action.setShortcut(QKeySequence("Shift+Tab"))
        unindent_action.triggered.connect(self.editor.unindent_text)
        self.addAction(unindent_action)

    def check_cpdf(self):
        return shutil.which("cpdf") is not None

    def on_tab_changed(self, index):
        if index == 1:
            self.update_preview()

    def force_update_preview(self):
        self.editor._preview_cache = None
        self.update_preview()

    def parse_bookmarks(self):
        """
        解析书签文本，支持分隔符模式。
        
        逻辑：
        1. 分隔符上方：
           - 数字：直接视为物理页码
           - 罗马数字：视为前言页码，物理页 = 罗马起始页 + (roman - 1)
        2. 分隔符下方：
           - 数字：视为印刷页码，物理页 = 正文起始页 + (page - 1)
        """
        raw_text = self.editor.text_edit.toPlainText()
        body_start = self.editor.spin_body_start.value()  # 正文起始物理页
        roman_start = self.editor.spin_roman_start.value() # 罗马数字起始物理页
        
        cpdf_lines = []
        errors = []
        
        is_body_section = False  # 标记是否进入正文部分
        
        for line_raw in raw_text.splitlines():
            line_stripped = line_raw.strip()
            if not line_stripped:
                continue
            
            # 检查是否是分隔符
            if line_stripped == SEPARATOR_TEXT:
                is_body_section = True
                continue
            
            line = unicodedata.normalize('NFKC', line_raw)
            match = re.search(r"^(\s*)(.*?)(\s+)([\w-]+)\s*$", line)
            
            if match:
                indent_str = match.group(1)
                title = match.group(2)
                page_str = match.group(4)
                
                tab_count = indent_str.count('\t')
                space_count = indent_str.count(' ')
                level = tab_count + (space_count // 4)
                
                try:
                    physical_page = 1
                    
                    if is_body_section:
                        # 正文部分：输入是印刷页码
                        try:
                            print_page = int(page_str)
                            physical_page = body_start + (print_page - 1)
                        except ValueError:
                             errors.append(f"正文部分页码必须是数字: {page_str}")
                             continue
                    else:
                        # 前言部分：输入是物理页码 或 罗马数字 或 字母
                        try:
                            # 1. 尝试作为数字解析（物理页码）
                            physical_page = int(page_str)
                        except ValueError:
                            # 2. 尝试作为小写罗马数字解析 (i, ii, iv...)
                            if re.match(r'^[ivxlcdm]+$', page_str):
                                try:
                                    roman_val = roman_to_int(page_str)
                                    if roman_val > 0:
                                        physical_page = roman_start + (roman_val - 1)
                                    else:
                                        raise ValueError
                                except:
                                    errors.append(f"无效的罗马数字: {page_str}")
                                    continue
                            # 3. 尝试作为大写字母解析 (A, B, C...) -> 物理页码 (A=1)
                            elif re.match(r'^[A-Z]+$', page_str):
                                alpha_val = alpha_to_int(page_str)
                                if alpha_val > 0:
                                    physical_page = alpha_val
                                else:
                                    errors.append(f"无效的字母页码: {page_str}")
                                    continue
                            else:
                                errors.append(f"前言页码格式错误 (支持: 数字, i-xii, A-Z): {page_str}")
                                continue
                    
                    if physical_page < 1:
                        physical_page = 1
                        
                    safe_title = title.replace('\\', '\\\\').replace('"', '\\"')
                    cpdf_lines.append(f'{level} "{safe_title}" {physical_page}')
                except Exception as e:
                    errors.append(f"Error parsing line: {line_raw} ({str(e)})")
                    continue 
            else:
                errors.append(f"Format error: {line_raw}")
                
        if errors:
            error_text = "\n".join(errors[:10])
            if len(errors) > 10:
                error_text += f"\n... and {len(errors) - 10} more errors"
            self.statusBar().showMessage(f"Validation: {len(errors)} errors found", 5000)
        
        return cpdf_lines

    def generate_temp_pdf(self):
        if not self.editor.current_file_path:
            QMessageBox.warning(self, "Info", "Please select a PDF file in the Edit tab first.")
            self.tabs.setCurrentIndex(0)
            return None
            
        if not self._cpdf_available:
            handle_cpdf_error(self, "cpdf is not installed", 
                "Please install cpdf from https://community.coherentpdf.com/")
            return None
            
        if self.editor._preview_cache and os.path.exists(self.editor._preview_cache):
            return self.editor._preview_cache
            
        bookmarks = self.parse_bookmarks()
        if not bookmarks:
            msg = "No valid bookmarks found to add."
            if self.editor.text_edit.toPlainText().strip():
                msg += "\n\nPlease ensure each line ends with a page number.\nFormat: 'Title PageNum'"
            QMessageBox.information(self, "Info", msg)
            self.tabs.setCurrentIndex(0)
            return None
        
        # Use context manager for bookmark file (short-lived)
        with temp_file_context(suffix=".bmk") as bookmark_file:
            with open(bookmark_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(bookmarks))
            
            # Create temp PDF manually (long-lived, for preview caching)
            temp_pdf_path = create_temp_file(suffix=".pdf")
            cmd = ["cpdf", "-add-bookmarks", bookmark_file, 
                   self.editor.current_file_path, "-o", temp_pdf_path, "-utf8"]
            
            try:
                subprocess.run(cmd, check=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
                # Clean up old cache before storing new one
                cleanup_temp_file(self.editor._preview_cache)
                self.editor._preview_cache = temp_pdf_path
                return temp_pdf_path
            except subprocess.CalledProcessError as e:
                cleanup_temp_file(temp_pdf_path)
                handle_cpdf_error(self, "cpdf failed", e.stderr)
                return None

    def update_preview(self):
        if not self.editor.current_file_path:
            return

        if not self._cpdf_available:
            return

        temp_pdf = self.generate_temp_pdf()
        if temp_pdf and os.path.exists(temp_pdf):
            if HAS_WEBENGINE:
                self.web_view.setUrl(QUrl.fromLocalFile(temp_pdf))
            else:
                QMessageBox.information(self, "Preview", "Preview updated (WebEngine not available).")
            self.statusBar().showMessage("Preview updated", 3000)
            
    def save_pdf(self):
        if not self.editor.current_file_path:
            QMessageBox.warning(self, "Info", "No file loaded.")
            return

        if not self._cpdf_available:
            handle_cpdf_error(self, "cpdf is not installed", 
                "Please install cpdf from https://community.coherentpdf.com/")
            return

        dest_path, _ = QFileDialog.getSaveFileName(self, "Save PDF", 
            os.path.dirname(self.editor.current_file_path) or os.getcwd(), 
            "PDF Files (*.pdf)")
        if not dest_path:
            return
            
        bookmarks = self.parse_bookmarks()
        if not bookmarks:
            QMessageBox.warning(self, "Warning", "No bookmarks to save.")
            return

        # Use temp file for output to prevent overwriting input file directly
        temp_out_path = create_temp_file(suffix=".pdf")

        with temp_file_context(suffix=".bmk") as bookmark_file:
            with open(bookmark_file, 'w', encoding='utf-8') as f:
                f.write("\n".join(bookmarks))
                
            cmd = ["cpdf", "-add-bookmarks", bookmark_file, 
                   self.editor.current_file_path, "-o", temp_out_path, "-utf8"]
            
            try:
                subprocess.run(cmd, check=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True)
                
                # If successful, move temp file to destination
                if os.path.exists(dest_path):
                    try:
                        os.remove(dest_path)
                    except OSError:
                        pass # Try to overwrite anyway

                shutil.move(temp_out_path, dest_path)

                QMessageBox.information(self, "Success", f"Saved to {dest_path}")
                self.statusBar().showMessage(f"Saved: {dest_path}", 5000)
            except subprocess.CalledProcessError as e:
                cleanup_temp_file(temp_out_path)
                handle_cpdf_error(self, "Failed to save", e.stderr)
            except OSError as e:
                cleanup_temp_file(temp_out_path)
                QMessageBox.critical(self, "Error", f"File operation failed: {str(e)}")

if __name__ == "__main__":
    # Fix for WebEngine crash on Linux (GBM/Vulkan issues)
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

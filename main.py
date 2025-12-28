import sys
import os
import re
import subprocess
import tempfile
import shutil
import unicodedata
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLabel, QPushButton, QFileDialog, 
                             QTextEdit, QSpinBox, QTabWidget, QMessageBox, 
                             QToolBar, QStyle, QFrame)
from PyQt6.QtCore import Qt, QUrl, QSize
from PyQt6.QtGui import QAction, QIcon, QFont, QTextCursor

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
        
        # 1. File Selection
        file_layout = QHBoxLayout()
        self.file_path_label = QLabel("No file selected")
        self.file_path_label.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Sunken)
        self.btn_browse = QPushButton("Select PDF")
        self.btn_browse.clicked.connect(self.browse_file)
        file_layout.addWidget(self.btn_browse)
        file_layout.addWidget(self.file_path_label)
        self.layout.addLayout(file_layout)
        
        # 2. Offset
        offset_layout = QHBoxLayout()
        offset_layout.addWidget(QLabel("Page Offset:"))
        self.spin_offset = QSpinBox()
        self.spin_offset.setRange(-1000, 1000)
        self.spin_offset.setValue(0)
        self.spin_offset.setToolTip("Difference between TOC page number and physical page number.\n(e.g. if TOC says 1 but it's physical page 5, offset is 4)")
        offset_layout.addWidget(self.spin_offset)
        offset_layout.addStretch()
        self.layout.addLayout(offset_layout)
        
        # 3. Toolbar for Text Edit
        toolbar_layout = QHBoxLayout()
        self.btn_indent = QPushButton("Indent (>)")
        self.btn_indent.clicked.connect(self.indent_text)
        self.btn_unindent = QPushButton("Unindent (<)")
        self.btn_unindent.clicked.connect(self.unindent_text)
        toolbar_layout.addWidget(self.btn_indent)
        toolbar_layout.addWidget(self.btn_unindent)
        toolbar_layout.addStretch()
        self.layout.addLayout(toolbar_layout)
        
        # 4. Text Edit for Bookmarks
        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Format: [Indentation] Title PageNum\nExample:\nIntroduction 1\n\tChapter 1 5\n\t\tSection 1.1 10")
        self.text_edit.setFont(QFont("Monospace"))
        self.layout.addWidget(self.text_edit)
        
        self.current_file_path = None

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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Bookmark Editor")
        self.resize(1000, 700)
        
        if not HAS_WEBENGINE:
            QMessageBox.critical(self, "Error", "PyQt6-WebEngine is not installed. Preview will not work.\nPlease install it: pip install PyQt6-WebEngine")

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Tab 1: Editor
        self.editor = BookmarkEditor()
        self.tabs.addTab(self.editor, "Edit Bookmarks")
        
        # Tab 2: Preview
        self.preview_container = QWidget()
        self.preview_layout = QVBoxLayout(self.preview_container)
        
        if HAS_WEBENGINE:
            self.web_view = QWebEngineView()
            self.web_view.settings().setAttribute(self.web_view.settings().WebAttribute.PluginsEnabled, True)
            self.web_view.settings().setAttribute(self.web_view.settings().WebAttribute.PdfViewerEnabled, True)
            self.preview_layout.addWidget(self.web_view)
        else:
            self.web_view = QLabel("WebEngine not available")
            self.web_view.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.preview_layout.addWidget(self.web_view)
            
        # Save Button in Preview
        self.btn_save = QPushButton("Save PDF")
        self.btn_save.clicked.connect(self.save_pdf)
        self.preview_layout.addWidget(self.btn_save)
        
        self.tabs.addTab(self.preview_container, "Preview")
        
        # Connect Tab Change
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        # Check cpdf
        if not self.check_cpdf():
            QMessageBox.warning(self, "Warning", "cpdf command not found. Please install cpdf tools.")

    def check_cpdf(self):
        return shutil.which("cpdf") is not None

    def on_tab_changed(self, index):
        # Index 1 is Preview
        if index == 1:
            self.update_preview()

    def parse_bookmarks(self):
        raw_text = self.editor.text_edit.toPlainText()
        offset = self.editor.spin_offset.value()
        
        cpdf_lines = []
        
        for line_raw in raw_text.splitlines():
            if not line_raw.strip():
                continue
            
            # Normalize full-width characters (e.g. full-width spaces, digits) to half-width
            line = unicodedata.normalize('NFKC', line_raw)
                
            # Regex to find PageNum at end
            # Matches: (Level_Whitespace)(Title)(Whitespace)(PageNum)(Optional Trailing Whitespace)
            match = re.search(r"^(\s*)(.*?)(\s+)(\d+)\s*$", line)
            
            if match:
                indent_str = match.group(1)
                title = match.group(2)
                # group 3 is separator
                page_str = match.group(4)
                
                # Calculate level
                # Assuming 1 tab = 1 level, or 4 spaces = 1 level
                tab_count = indent_str.count('\t')
                space_count = indent_str.count(' ')
                level = tab_count + (space_count // 4)
                
                try:
                    page = int(page_str) + offset
                    if page < 1: page = 1
                    # cpdf format: level "Title" page
                    # Escape quotes in title
                    safe_title = title.replace('"', '\"')
                    cpdf_lines.append(f'{level} "{safe_title}" {page}')
                except ValueError:
                    print(f"Debug: ValueError processing line: {line}")
                    continue 
            else:
                # Debug logging for lines that failed to parse
                print(f"Debug: Failed to parse line: '{line_raw}' (Normalized: '{line}')")
                pass
                
        return cpdf_lines

    def generate_temp_pdf(self):
        if not self.editor.current_file_path:
            QMessageBox.warning(self, "Info", "Please select a PDF file in the Edit tab first.")
            self.tabs.setCurrentIndex(0)
            return None
            
        bookmarks = self.parse_bookmarks()
        if not bookmarks:
            msg = "No valid bookmarks found to add."
            if self.editor.text_edit.toPlainText().strip():
                msg += "\n\nPlease ensure each line ends with a page number.\nFormat: 'Title PageNum'"
            QMessageBox.information(self, "Info", msg)
            self.tabs.setCurrentIndex(0)
            return None
            
        # Create temp bookmark file
        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            f.write("\n".join(bookmarks))
            bookmark_file = f.name
            
        # Create temp output file
        fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        
        # Run cpdf
        # cpdf -add-bookmarks bookmarks.txt input.pdf -o output.pdf
        cmd = ["cpdf", "-add-bookmarks", bookmark_file, self.editor.current_file_path, "-o", temp_pdf_path, "-utf8"]
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Error", f"cpdf failed:\n{e.stderr.decode()}")
            os.unlink(bookmark_file)
            os.unlink(temp_pdf_path)
            return None
            
        os.unlink(bookmark_file)
        return temp_pdf_path

    def update_preview(self):
        # Avoid redundant updates if no file is selected yet
        if not self.editor.current_file_path:
            return

        temp_pdf = self.generate_temp_pdf()
        if temp_pdf:
            if HAS_WEBENGINE:
                self.web_view.setUrl(QUrl.fromLocalFile(temp_pdf))
            else:
                QMessageBox.information(self, "Preview", "Preview updated (WebEngine not available).")
            
    def save_pdf(self):
        if not self.editor.current_file_path:
            QMessageBox.warning(self, "Info", "No file loaded.")
            return

        dest_path, _ = QFileDialog.getSaveFileName(self, "Save PDF", os.getcwd(), "PDF Files (*.pdf)")
        if not dest_path:
            return
            
        # Re-generate to dest path
        bookmarks = self.parse_bookmarks()
        if not bookmarks:
             QMessageBox.warning(self, "Warning", "No bookmarks to save.")
             return

        with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as f:
            f.write("\n".join(bookmarks))
            bookmark_file = f.name
            
        cmd = ["cpdf", "-add-bookmarks", bookmark_file, self.editor.current_file_path, "-o", dest_path, "-utf8"]
        
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            QMessageBox.information(self, "Success", f"Saved to {dest_path}")
        except subprocess.CalledProcessError as e:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{e.stderr.decode()}")
        
        os.unlink(bookmark_file)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

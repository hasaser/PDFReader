import sys
import os
import json
import io
import numpy as np
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QTabWidget, QPushButton, QLineEdit, QLabel, QSlider,
                             QAction, QFileDialog, QMessageBox, QScrollArea, QShortcut)
from PyQt5.QtGui import QImage, QPixmap, QPainter, QFont
from PyQt5.QtCore import Qt, QRect, QTimer
import fitz  # PyMuPDF
from PIL import Image

colors = {
    "primary": "#708090",
    "secondary": "#5F6A6A",
    "success": "#7D8B8B",
    "info": "#A9A9A9",
    "light": "#D3D3D3",
    "dark": "#2F4F4F",
    "bg": "#333333",
    "fg": "#E0E0E0",
    "selectbg": "#5D6D7E",
    "selectfg": "#FFFFFF",
    "canvas_bg": "#444444",
    "canvas_fg": "#E0E0E0",
    "hover": "#5D6D7E",
    "reset": "#C0392B",
    "tooltip_bg": "#2C3E50",
    "tooltip_fg": "#ECF0F1"
}

# Custom stylesheet for PyQt5
STYLESHEET = f"""
    QMainWindow, QWidget {{
        background-color: {colors['bg']};
        color: {colors['fg']};
        font-family: Arial;
        font-size: 10pt;
    }}
    QTabWidget::pane {{
        background-color: {colors['bg']};
        border: none;
    }}
    QTabBar::tab {{
        background: {colors['secondary']};
        color: {colors['fg']};
        padding: 10px;
    }}
    QTabBar::tab:selected {{
        background: {colors['primary']};
        color: {colors['fg']};
    }}
    QTabBar::tab:hover {{
        background: {colors['info']};
    }}
    QPushButton {{
        background-color: {colors['secondary']};
        color: {colors['fg']};
        padding: 8px 4px;
        border: none;
        font-family: Segoe UI Symbol;
        font-size: 10pt;
    }}
    QPushButton:hover {{
        background-color: {colors['hover']};
    }}
    QPushButton#resetButton {{
        background-color: {colors['reset']};
    }}
    QPushButton#resetButton:hover {{
        background-color: {colors['hover']};
    }}
    QLineEdit {{
        background-color: {colors['bg']};
        color: {colors['fg']};
        border: 1px solid {colors['dark']};
        padding: 2px;
    }}
    QLabel {{
        background-color: {colors['bg']};
        color: {colors['fg']};
    }}
    QLabel#zoomInfo {{
        color: #4CAF50;
        font-weight: bold;
        padding: 5px 2px;
    }}
    QSlider::groove:horizontal {{
        background: {colors['dark']};
        height: 8px;
    }}
    QSlider::handle:horizontal {{
        background: {colors['fg']};
        width: 16px;
        border-radius: 8px;
    }}
    QTextEdit {{
        background-color: {colors['bg']};
        color: {colors['fg']};
        border: 1px solid {colors['dark']};
    }}
"""

class PDFCanvas(QWidget):
    def __init__(self, parent, tab_id, pdf_reader):
        super().__init__(parent)
        self.tab_id = tab_id
        self.pdf_reader = pdf_reader
        self.image = None
        self.setMouseTracking(True)
        self.zoom_rect_start = None
        self.setAcceptDrops(True)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.image:
            pixmap = QPixmap.fromImage(self.image)
            x = (self.width() - pixmap.width()) // 2 if self.width() > pixmap.width() else 0
            y = (self.height() - pixmap.height()) // 2 if self.height() > pixmap.height() else 0
            painter.drawPixmap(x, y, pixmap)

        if self.zoom_rect_start and hasattr(self, 'zoom_rect_end'):
            painter.setPen(Qt.red)
            rect = QRect(self.zoom_rect_start, self.zoom_rect_end)
            painter.drawRect(rect)

    def mousePressEvent(self, event):
        if self.pdf_reader.zoom_mode == 'rectangle':
            self.zoom_rect_start = event.pos()
            self.zoom_rect_end = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self.pdf_reader.zoom_mode == 'rectangle' and self.zoom_rect_start:
            self.zoom_rect_end = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.pdf_reader.zoom_mode == 'rectangle' and self.zoom_rect_start:
            x1, y1 = self.zoom_rect_start.x(), self.zoom_rect_start.y()
            x2, y2 = event.pos().x(), event.pos().y()
            width = abs(x2 - x1)
            height = abs(y2 - y1)
            if width > 10 and height > 10:
                zoom_x = self.width() / width
                zoom_y = self.height() / height
                new_zoom = min(zoom_x, zoom_y) * self.pdf_reader.zoom_levels.get(self.tab_id, 1.0)
                self.pdf_reader.zoom_levels[self.tab_id] = new_zoom
                self.pdf_reader.render_page(self.tab_id)
            self.zoom_rect_start = None
            self.zoom_rect_end = None
            self.pdf_reader.zoom_mode = None
            self.update()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.pdf_reader.zoom_in(self.tab_id)
            else:
                self.pdf_reader.zoom_out(self.tab_id)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if file_path.lower().endswith('.pdf'):
                self.pdf_reader.add_pdf_tab(file_path)
                self.pdf_reader.save_recent_files()
                self.pdf_reader.update_recent_menu()

class PDFReader(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Reader")
        self.setGeometry(100, 100, 900, 700)
        self.pdf_docs = {}
        self.current_pages = {}
        self.zoom_levels = {}
        self.tab_count = 0
        self.recent_files = []
        self.from_slide = False
        self.zoom_mode = None
        self.setup_ui()
        self.load_recent_files()  # Dosyadan recent_files'i yükle
        self.update_recent_menu()  # Menüyü güncelle
        self.load_state()
        self.setStyleSheet(STYLESHEET)
        self.setAcceptDrops(True)

    def setup_ui(self):
        # Menu Bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        open_action = QAction("Open PDF (Ctrl+N)", self)
        open_action.setShortcut("Ctrl+N")
        open_action.triggered.connect(self.open_pdf)
        file_menu.addAction(open_action)
        self.recent_menu = file_menu.addMenu("Recent Files")
        close_tab_action = QAction("Close Tab", self)
        close_tab_action.setShortcut("Ctrl+W")  # Kısayol ataması (opsiyonel)
        close_tab_action.triggered.connect(self.close_tab)  # Fonksiyon bağlantısı
        file_menu.addSeparator()  # Ayrı çizgi ekle
        file_menu.addAction(close_tab_action)

        # Main Widget
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)

        # Tab Widget
        self.notebook = QTabWidget()
        self.notebook.setTabsClosable(True)
        self.notebook.tabCloseRequested.connect(self.close_tab)
        self.main_layout.addWidget(self.notebook)

        # Status Bar
        status_label = QLabel("Drag and drop PDF files here")
        status_label.setAlignment(Qt.AlignCenter)
        status_label.setStyleSheet(f"color: {colors['info']}; font-style: italic;")
        self.main_layout.addWidget(status_label)

        # Shortcuts
        self.shortcut_prev = QShortcut("PgUp", self, activated=self.prev_page)
        self.shortcut_next = QShortcut("PgDown", self, activated=self.next_page)
        self.shortcut_switch = QShortcut("Ctrl+Tab", self, activated=self.switch_tab)

    def add_pdf_tab(self, file_path):
        # try:
        if True:
            pdf_doc = fitz.open(file_path)
            tab_id = f"tab_{self.tab_count}"
            self.tab_count += 1
            self.pdf_docs[tab_id] = pdf_doc
            self.current_pages[tab_id] = 0
            self.zoom_levels[tab_id] = 1.0

            # Tab Widget
            tab_widget = QWidget()
            tab_widget.setProperty("tab_id", tab_id)  # Özel özellik olarak tab_id'yi kaydet
            tab_layout = QVBoxLayout(tab_widget)
            canvas_frame = QWidget()
            canvas_layout = QHBoxLayout(canvas_frame)
            canvas = PDFCanvas(canvas_frame, tab_id, self)
            canvas.setStyleSheet(f"background-color: {colors['canvas_bg']};")
            canvas_layout.addWidget(canvas)
            scroll_area = QScrollArea()
            scroll_area.setWidget(canvas)
            scroll_area.setWidgetResizable(True)
            tab_layout.addWidget(scroll_area)

            # Overlay Frame
            overlay_frame = QWidget()
            overlay_layout = QHBoxLayout(overlay_frame)
            border_frame = QWidget()
            border_frame.setStyleSheet("border: 2px solid black;")
            border_layout = QHBoxLayout(border_frame)

            self.page_var = QLineEdit()
            self.page_var.setFixedWidth(40)
            self.page_var.setAlignment(Qt.AlignCenter)
            self.page_var.returnPressed.connect(lambda: self.go_to_page(tab_id))
            border_layout.addWidget(self.page_var)

            max_page_label = QLabel(f"/ {pdf_doc.page_count}")
            border_layout.addWidget(max_page_label)

            prev_button = QPushButton("⏮")
            prev_button.clicked.connect(self.prev_page)
            border_layout.addWidget(prev_button)
            next_button = QPushButton("⏭")
            next_button.clicked.connect(self.next_page)
            border_layout.addWidget(next_button)

            zoom_buttons = [
                ("⤡", lambda: self.fit_width(tab_id), "Fit Width (Genişliğe Sığdır)"),
                ("⤢", lambda: self.fit_height(tab_id), "Fit Height (Yüksekliğe Sığdır)"),
                ("⧉", lambda: self.setup_zoom_rectangle(tab_id), "Area Zoom (Alan Büyütme)"),
                ("⟲", lambda: self.zoom_reset(tab_id), "Reset Zoom (Varsayılan Boyut)")
            ]
            for icon, cmd, tip in zoom_buttons:
                btn = QPushButton(icon)
                btn.setFixedWidth(30)
                btn.clicked.connect(cmd)
                btn.setToolTip(tip)
                if icon == "⟲":
                    btn.setObjectName("resetButton")
                border_layout.addWidget(btn)

            zoom_out_button = QPushButton("➖")
            zoom_out_button.clicked.connect(lambda: self.zoom_out(tab_id))
            border_layout.addWidget(zoom_out_button)
            zoom_slider = QSlider(Qt.Horizontal)
            zoom_slider.setRange(10, 200)
            zoom_slider.setValue(100)
            zoom_slider.setFixedWidth(150)  # Sabit genişlik (örneğin 150 piksel)
            zoom_slider.valueChanged.connect(lambda v: self.on_zoom_slide(v, tab_id))
            border_layout.addWidget(zoom_slider)
            zoom_in_button = QPushButton("➕")
            zoom_in_button.clicked.connect(lambda: self.zoom_in(tab_id))
            border_layout.addWidget(zoom_in_button)

            self.zoom_label_var = QLabel("100%")
            self.zoom_label_var.setObjectName("zoomInfo")
            border_layout.addWidget(self.zoom_label_var)

            overlay_layout.addWidget(border_frame)
            # overlay_frame.hide()
            tab_layout.addWidget(overlay_frame)

            self.notebook.addTab(tab_widget, os.path.basename(file_path))
            self.notebook.setCurrentWidget(tab_widget)

            # Store references
            self.pdf_docs[f"{tab_id}_canvas"] = canvas
            self.pdf_docs[f"{tab_id}_overlay"] = overlay_frame
            self.pdf_docs[f"{tab_id}_slider"] = zoom_slider
            self.pdf_docs[f"{tab_id}_page_var"] = self.page_var
            self.pdf_docs[f"{tab_id}_max_label"] = max_page_label

            canvas.resizeEvent = lambda e: QTimer.singleShot(200, lambda: self.render_page(tab_id))
            self.render_page(tab_id)

            file_path = os.path.abspath(file_path)  # Mutlak yol garantisi
            if file_path not in self.recent_files:
                self.recent_files.insert(0, file_path)
                self.recent_files = self.recent_files[:10]  # En fazla 10 dosya
                self.save_recent_files()
                self.update_recent_menu()

        # except Exception as e:
        #     QMessageBox.critical(self, "Error", f"Failed to open PDF: {str(e)}")

    # def show_overlay(self, tab_id):
    #     overlay = self.pdf_docs.get(f"{tab_id}_overlay")
    #     if overlay:
    #         overlay.show()

    # def hide_overlay(self, tab_id):
    #     overlay = self.pdf_docs.get(f"{tab_id}_overlay")
    #     if overlay:
    #         overlay.hide()

    def render_page(self, tab_id):
        if tab_id not in self.pdf_docs:
            return
        pdf_doc = self.pdf_docs[tab_id]
        page_num = self.current_pages[tab_id]
        if page_num < 0 or page_num >= pdf_doc.page_count:
            return

        self.pdf_docs[f"{tab_id}_page_var"].setText(str(page_num + 1))
        self.pdf_docs[f"{tab_id}_max_label"].setText(f"/ {pdf_doc.page_count}")

        canvas = self.pdf_docs[f"{tab_id}_canvas"]
        zoom = self.zoom_levels[tab_id]
        page = pdf_doc.load_page(page_num)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = Image.open(io.BytesIO(pix.tobytes()))
        
        # Convert RGB to BGR for QImage
        img_rgb = img.convert('RGB')  # Ensure RGB mode
        img_array = np.array(img_rgb)
        qimage = QImage(img_array.data, img_array.shape[1], img_array.shape[0], 
                        img_array.strides[0], QImage.Format_RGB888)
        
        canvas.image = qimage
        canvas.setMinimumSize(pix.width, pix.height)
        canvas.update()

        self.notebook.setTabText(self.notebook.indexOf(canvas.parent().parent()),
                                 f"{os.path.basename(pdf_doc.name)} - Page {page_num+1}/{pdf_doc.page_count}")

        if not self.from_slide:
            self.pdf_docs[f"{tab_id}_slider"].setValue(int(zoom * 100))
            self.zoom_label_var.setText(f"{int(zoom * 100)}%")
        else:
            self.from_slide = False

    def close_tab(self, index=None):
        tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            self.pdf_docs[tab_id].close()
            del self.pdf_docs[tab_id]
            del self.pdf_docs[f"{tab_id}_canvas"]
            del self.pdf_docs[f"{tab_id}_overlay"]
            del self.pdf_docs[f"{tab_id}_slider"]
            del self.pdf_docs[f"{tab_id}_page_var"]
            del self.pdf_docs[f"{tab_id}_max_label"]
            del self.current_pages[tab_id]
            del self.zoom_levels[tab_id]
            self.notebook.removeTab(index)
            if self.notebook.count() == 0:
                self.close()

    def prev_page(self):
        index = self.notebook.currentIndex()
        if index == -1:
            return
        tab_id = self.get_tab_id(index)
        if tab_id:
            current_page = self.current_pages[tab_id]
            if current_page > 0:
                self.go_to_page(tab_id, current_page - 1)  # go_to_page fonksiyonunu çağır

    def next_page(self):
        index = self.notebook.currentIndex()
        if index == -1:
            return
        tab_id = self.get_tab_id(index)
        if tab_id:
            current_page = self.current_pages[tab_id]
            if current_page < self.pdf_docs[tab_id].page_count - 1:
                self.go_to_page(tab_id, current_page + 1)  # go_to_page fonksiyonunu çağır

    def go_to_page(self, tab_id, page_num=None):
        if page_num is None:
            try:
                page_num = int(self.pdf_docs[f"{tab_id}_page_var"].text()) - 1
            except ValueError:
                QMessageBox.critical(self, "Error", "Please enter a valid number")
                self.pdf_docs[f"{tab_id}_page_var"].setText(str(self.current_pages[tab_id] + 1))
                return

        if 0 <= page_num < self.pdf_docs[tab_id].page_count:
            self.current_pages[tab_id] = page_num
            self.pdf_docs[f"{tab_id}_page_var"].setText(str(page_num + 1))  # Sayfa numarasını güncelle
            self.render_page(tab_id)
            self.save_state()
        else:
            QMessageBox.critical(self, "Error", "Invalid page number")
            self.pdf_docs[f"{tab_id}_page_var"].setText(str(self.current_pages[tab_id] + 1))

    def get_tab_id(self, index):
        if index == -1:
            return None
        tab_widget = self.notebook.widget(index)
        if tab_widget:
            return tab_widget.property("tab_id")
        return None

    def zoom_in(self, tab_id=None):
        if tab_id is None:
            tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            self.zoom_levels[tab_id] *= 1.2
            self.render_page(tab_id)

    def zoom_out(self, tab_id=None):
        if tab_id is None:
            tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            self.zoom_levels[tab_id] /= 1.2
            if self.zoom_levels[tab_id] < 0.1:
                self.zoom_levels[tab_id] = 0.1
            self.render_page(tab_id)

    def switch_tab(self):
        current_index = self.notebook.currentIndex()
        next_index = (current_index + 1) % self.notebook.count()
        self.notebook.setCurrentIndex(next_index)

    def load_recent_files(self):
        try:
            with open("recent_files.json", "r") as f:
                self.recent_files = json.load(f)
        except FileNotFoundError:
            self.recent_files = []

    def save_recent_files(self):
        with open("recent_files.json", "w") as f:
            json.dump(self.recent_files, f)

    def update_recent_menu(self):
        self.recent_menu.clear()  # Eski öğeleri temizle
        for file_path in self.recent_files:
            action = QAction(os.path.basename(file_path), self)  # Sadece dosya adını göster
            action.setData(file_path)  # Tam yolu sakla
            action.triggered.connect(lambda checked, fp=file_path: self.add_pdf_tab(fp))
            self.recent_menu.addAction(action)

    def save_state(self):
        state = {
            "current_pages": self.current_pages,
            "zoom_levels": self.zoom_levels
        }
        with open("state.json", "w") as f:
            json.dump(state, f)

    def load_state(self):
        try:
            with open("state.json", "r") as f:
                state = json.load(f)
                self.current_pages.update(state.get("current_pages", {}))
                self.zoom_levels.update(state.get("zoom_levels", {}))
        except FileNotFoundError:
            pass

    def open_pdf(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open PDF", "", "PDF Files (*.pdf)")
        if file_path:
            self.add_pdf_tab(file_path)

    def fit_width(self, tab_id=None):
        if tab_id is None:
            tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            canvas = self.pdf_docs.get(f"{tab_id}_canvas")
            page = self.pdf_docs[tab_id].load_page(self.current_pages.get(tab_id, 0))
            page_width = page.rect.width
            canvas_width = canvas.width()
            if canvas_width > 0:
                self.zoom_levels[tab_id] = canvas_width / page_width
                self.render_page(tab_id)

    def fit_height(self, tab_id=None):
        if tab_id is None:
            tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            canvas = self.pdf_docs.get(f"{tab_id}_canvas")
            page = self.pdf_docs[tab_id].load_page(self.current_pages.get(tab_id, 0))
            page_height = page.rect.height
            canvas_height = canvas.height()
            if canvas_height > 0:
                self.zoom_levels[tab_id] = canvas_height / page_height
                self.render_page(tab_id)

    def zoom_reset(self, tab_id=None):
        if tab_id is None:
            tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            self.zoom_levels[tab_id] = 1.0
            self.render_page(tab_id)

    def on_zoom_slide(self, value, tab_id):
        self.from_slide = True
        self.zoom_levels[tab_id] = value / 100
        self.render_page(tab_id)

    def setup_zoom_rectangle(self, tab_id=None):
        if tab_id is None:
            tab_id = self.get_tab_id(self.notebook.currentIndex())
        if tab_id:
            self.zoom_mode = 'rectangle'
            QMessageBox.information(self, "Area Zoom", "Drag a rectangle to zoom to that area")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setFont(QFont("Segoe UI Symbol", 10))
    window = PDFReader()
    window.show()
    sys.exit(app.exec_())

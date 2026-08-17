from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from html import escape
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QSize, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QBrush, QCloseEvent, QColor, QIcon, QImageReader, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .accounts import AccountStore, CredentialStoreError
from .client import AuthenticationError, HiPersonalizationClient, HiPersonalizationError
from .config import Settings, app_data_dir
from .models import (
    ConfirmableProduct,
    DefinitionOption,
    ImageSubmissionTask,
    OrderSummary,
    ProductOption,
    RecustomContext,
    SellerShop,
    SelectOption,
    ShopProduct,
    StampReplacementContext,
    SubmissionResult,
    build_product_code,
)
from .resources import resource_path
from .store import SubmissionStore


class WorkerSignals(QObject):
    result = Signal(object)
    error = Signal(object)
    progress = Signal(object)
    finished = Signal()


class FunctionWorker(QRunnable):
    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(
                *self.args,
                progress_callback=self.signals.progress,
                **self.kwargs,
            )
        except Exception as exc:  # UI boundary: pass the original error to the main thread.
            self.signals.error.emit(exc)
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()


def load_scaled_pixmap(path: Path, maximum_size: QSize) -> QPixmap:
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    source_size = reader.size()
    if source_size.isValid():
        target_size = source_size.scaled(maximum_size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(target_size)
    image = reader.read()
    return QPixmap.fromImage(image) if not image.isNull() else QPixmap()


class ThumbnailLabel(QLabel):
    clicked = Signal(object)

    def __init__(self, image_path: Path):
        super().__init__()
        self.image_path = image_path
        self.setFixedSize(56, 56)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("点击查看较大预览")
        pixmap = load_scaled_pixmap(image_path, QSize(52, 52))
        if pixmap.isNull():
            self.setText("无法预览")
        else:
            self.setPixmap(pixmap)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.image_path)
        super().mouseReleaseEvent(event)


class ImagePreviewDialog(QDialog):
    def __init__(self, image_path: Path, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"图片预览 - {image_path.name}")
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = load_scaled_pixmap(image_path, QSize(1200, 900))
        if pixmap.isNull():
            image_label.setText("无法读取该图片。")
        else:
            image_label.setPixmap(pixmap)
        scroll.setWidget(image_label)
        layout.addWidget(scroll)


class RemoteThumbnailLabel(QLabel):
    clicked = Signal(object)

    def __init__(self, image_data: bytes, title: str, preview_url: str):
        super().__init__()
        self.preview_request = (title, preview_url)
        self.setFixedSize(56, 56)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        if pixmap.isNull():
            self.setText("无图片")
        else:
            self.setPixmap(
                pixmap.scaled(
                    QSize(52, 52),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("点击按需读取并查看原图")

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap() is not None:
            self.clicked.emit(self.preview_request)
        super().mouseReleaseEvent(event)


class ImageBytesPreviewDialog(QDialog):
    def __init__(self, image_data: bytes, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"图片预览 - {title}")
        self.resize(1000, 760)
        layout = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        image_label = QLabel()
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = QPixmap()
        pixmap.loadFromData(image_data)
        if pixmap.isNull():
            image_label.setText("无法读取该图片。")
        else:
            image_label.setPixmap(
                pixmap.scaled(
                    QSize(1200, 900),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        scroll.setWidget(image_label)
        layout.addWidget(scroll)


class FullTextComboBox(QComboBox):
    """Keeps the cell compact while expanding the popup to show complete option text."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.currentTextChanged.connect(self.setToolTip)

    def showPopup(self) -> None:
        content_width = self.width()
        metrics = self.fontMetrics()
        for index in range(self.count()):
            content_width = max(content_width, metrics.horizontalAdvance(self.itemText(index)) + 48)
        screen = QApplication.screenAt(self.mapToGlobal(self.rect().center()))
        if screen:
            content_width = min(content_width, screen.availableGeometry().width() - 60)
        self.view().setMinimumWidth(content_width)
        super().showPopup()


def compact_field(label: str, control: QWidget, *, expandable: bool = False) -> QWidget:
    """Keep a field label physically adjacent to its control at every window width."""
    field = QWidget()
    field.setSizePolicy(
        QSizePolicy.Policy.Expanding if expandable else QSizePolicy.Policy.Maximum,
        QSizePolicy.Policy.Preferred,
    )
    field_layout = QHBoxLayout(field)
    field_layout.setContentsMargins(0, 0, 0, 0)
    field_layout.setSpacing(6)
    field_layout.addWidget(QLabel(label))
    field_layout.addWidget(control, 1 if expandable else 0)
    return field


def feature_instructions(text: str) -> QLabel:
    label = QLabel(f"功能说明：\n{text}")
    label.setWordWrap(True)
    label.setStyleSheet(
        "background-color: #FCE4EC; color: #4A2633; "
        "border: 1px solid #F8BBD0; border-radius: 4px; padding: 8px;"
    )
    return label


class MainWindow(QMainWindow):
    IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp);;All files (*)"
    CONFIRMATION_ORDER_LIMIT = 20

    def __init__(self, settings: Settings):
        super().__init__()
        self.settings = settings
        self.client: HiPersonalizationClient | None = None
        self.logged_in_username = ""
        self.order_id = ""
        self.created_order_title = ""
        self.batch_completed_successfully = False
        self._pending_auto_types = False
        self._pending_auto_options = False
        self.available_type_options: list[SelectOption] = []
        self.confirmation_orders: list[OrderSummary] = []
        self.confirmation_order_thumbnails: dict[str, bytes] = {}
        self.confirmation_order_loaded_directly = False
        self.confirmation_products: list[ConfirmableProduct] = []
        self.confirmation_product_thumbnails: dict[str, bytes] = {}
        self.confirmation_requires_stamp = True
        self.seller_shops: list[SellerShop] = []
        self.shop_products: list[ShopProduct] = []
        self.shop_product_thumbnails: dict[int, bytes] = {}
        self.recustom_context: RecustomContext | None = None
        self.stamp_replacement_context: StampReplacementContext | None = None
        self.thread_pool = QThreadPool(self)
        self.thread_pool.setMaxThreadCount(1)
        self.thread_pool.setExpiryTimeout(1000)
        self.store = SubmissionStore(app_data_dir() / "history.db")
        self.account_store = AccountStore(app_data_dir() / "accounts.json")
        self._busy = False
        self._active_workers: set[FunctionWorker] = set()

        self.setWindowTitle("hipersonalization订单处理助手 v0.14 by Robin+Codex")
        self.setWindowIcon(QIcon(str(resource_path("assets/hipersonalization.ico"))))
        self.resize(1280, 820)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._build_ui()
        self._set_workflow_enabled(False)
        self._load_account_choices()
        QTimer.singleShot(0, self._auto_login_last_account)

    def _build_ui(self) -> None:
        root = QWidget(self)
        layout = QVBoxLayout(root)

        account_box = QGroupBox("1. Seller 登录")
        account_layout = QGridLayout(account_box)
        self.account_combo = QComboBox()
        self.account_combo.setEditable(True)
        self.account_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.account_combo.currentTextChanged.connect(self._account_changed)
        self.account_combo.activated.connect(self._saved_account_activated)
        self.account_combo.setMinimumWidth(280)
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMinimumWidth(280)
        self.login_button = QPushButton("登录并验证权限")
        self.login_button.clicked.connect(self._login)
        self.remove_account_button = QPushButton("删除本地账号")
        self.remove_account_button.clicked.connect(self._remove_account)
        self.login_status_label = QLabel("尚未登录，订单流程已锁定")
        account_layout.addWidget(QLabel("Seller 账号"), 0, 0)
        account_layout.addWidget(self.account_combo, 0, 1)
        account_layout.addWidget(QLabel("密码"), 0, 2)
        account_layout.addWidget(self.password_edit, 0, 3)
        account_layout.addWidget(self.login_button, 0, 4)
        account_layout.addWidget(self.remove_account_button, 0, 5)
        account_layout.addWidget(self.login_status_label, 1, 1, 1, 5)
        account_layout.setColumnStretch(1, 1)
        account_layout.setColumnStretch(3, 1)
        layout.addWidget(account_box)

        self.workflow_tabs = QTabWidget()
        self.submit_tab = QWidget()
        submit_layout = QVBoxLayout(self.submit_tab)
        self.sku_query_tab = QWidget()
        sku_query_layout = QVBoxLayout(self.sku_query_tab)
        self.confirmation_tab = QWidget()
        confirmation_layout = QVBoxLayout(self.confirmation_tab)
        self.recustom_tab = QWidget()
        recustom_layout = QVBoxLayout(self.recustom_tab)
        self.stamp_replacement_tab = QWidget()
        stamp_replacement_layout = QVBoxLayout(self.stamp_replacement_tab)
        self.workflow_tabs.addTab(self.submit_tab, "订单提交")
        self.workflow_tabs.addTab(self.confirmation_tab, "订单确认")
        self.workflow_tabs.addTab(self.recustom_tab, "替换设计")
        self.workflow_tabs.addTab(self.stamp_replacement_tab, "替补邮票")
        self.workflow_tabs.addTab(self.sku_query_tab, "SKU 查询")
        self.workflow_tabs.currentChanged.connect(self._workflow_tab_changed)
        layout.addWidget(self.workflow_tabs, 1)

        order_box = QGroupBox("2. 创建订单并搜索产品")
        order_layout = QVBoxLayout(order_box)
        self.order_title_edit = QLineEdit()
        self.order_title_edit.setPlaceholderText("例如：2026-08-04 Customer Name")
        self.sku_edit = QLineEdit()
        self.sku_edit.setPlaceholderText("Product SKU")
        self.prepare_order_button = QPushButton("创建 Order 并搜索 SKU")
        self.prepare_order_button.clicked.connect(self._prepare_order)
        self.continue_sku_button = QPushButton("当前 Order 继续添加 SKU")
        self.continue_sku_button.clicked.connect(self._continue_with_sku)
        self.existing_order_id_edit = QLineEdit()
        self.existing_order_id_edit.setPlaceholderText("仅填写数字 Order ID")
        self.existing_order_id_edit.setMaximumWidth(150)
        self.existing_sku_edit = QLineEdit()
        self.existing_sku_edit.setPlaceholderText("Product SKU")
        self.existing_sku_edit.setMaximumWidth(150)
        self.sku_edit.textChanged.connect(self.existing_sku_edit.setText)
        self.existing_sku_edit.textChanged.connect(self.sku_edit.setText)
        self.load_existing_order_button = QPushButton("载入已有 Order 并搜索 SKU")
        self.load_existing_order_button.clicked.connect(self._load_existing_order)
        self.new_order_button = QPushButton("开始新 Order")
        self.new_order_button.clicked.connect(self._start_new_order)
        self.order_id_label = QLabel("Order ID：尚未创建")
        self.sku_edit.setMaximumWidth(150)
        first_order_row = QHBoxLayout()
        first_order_row.addWidget(self.new_order_button)
        first_order_row.addWidget(self.order_id_label)
        first_order_row.addWidget(
            compact_field("Order Title", self.order_title_edit, expandable=True), 1
        )
        first_order_row.addWidget(compact_field("Product SKU", self.sku_edit))
        first_order_row.addWidget(self.prepare_order_button)
        first_order_row.addWidget(self.continue_sku_button)
        second_order_row = QHBoxLayout()
        second_order_row.addWidget(compact_field("已有 Order ID", self.existing_order_id_edit))
        second_order_row.addWidget(compact_field("Product SKU", self.existing_sku_edit))
        second_order_row.addWidget(self.load_existing_order_button)
        second_order_row.addWidget(QLabel("使用已有order提交设计图，不会创建新order"))
        second_order_row.addStretch(1)
        order_layout.addLayout(first_order_row)
        order_layout.addLayout(second_order_row)
        submit_layout.addWidget(order_box)

        choices_box = QGroupBox("3. 从网站读取配置")
        choices_layout = QGridLayout(choices_box)
        self.product_combo = QComboBox()
        self.definition_combo = QComboBox()
        self.type_combo = QComboBox()
        self.load_definitions_button = QPushButton("读取 Definitions")
        self.load_types_button = QPushButton("读取 Types")
        self.load_options_button = QPushButton("读取 Type Options")
        self.type_options_status_label = QLabel("尚未读取 Type Options")
        self.load_definitions_button.clicked.connect(self._load_definitions)
        self.load_types_button.clicked.connect(self._load_types)
        self.load_options_button.clicked.connect(self._load_type_options)
        self.definition_combo.currentIndexChanged.connect(self._auto_load_types)
        self.type_combo.currentIndexChanged.connect(self._auto_load_type_options)
        configuration_labels = (
            QLabel("Product"),
            QLabel("Definition"),
            QLabel("Product Type"),
        )
        for label in configuration_labels:
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        for button in (
            self.load_definitions_button,
            self.load_types_button,
            self.load_options_button,
        ):
            button.setFixedWidth(150)
        choices_layout.addWidget(configuration_labels[0], 0, 0)
        choices_layout.addWidget(self.product_combo, 0, 1)
        choices_layout.addWidget(self.load_definitions_button, 0, 2)
        choices_layout.addWidget(configuration_labels[1], 1, 0)
        choices_layout.addWidget(self.definition_combo, 1, 1)
        choices_layout.addWidget(self.load_types_button, 1, 2)
        choices_layout.addWidget(configuration_labels[2], 2, 0)
        choices_layout.addWidget(self.type_combo, 2, 1)
        choices_layout.addWidget(self.load_options_button, 2, 2)
        choices_layout.addWidget(self.type_options_status_label, 2, 3)
        choices_layout.setColumnStretch(1, 1)
        submit_layout.addWidget(choices_box)

        files_box = QGroupBox("4. 批量图片")
        files_layout = QVBoxLayout(files_box)
        defaults_layout = QHBoxLayout()
        self.batch_toolbar_layout = defaults_layout
        self.batch_type_option_combo = FullTextComboBox()
        self.batch_type_option_combo.setMinimumWidth(260)
        self.batch_type_option_combo.setMaximumWidth(520)
        self.batch_quantity_spin = QSpinBox()
        self.batch_quantity_spin.setRange(1, 999999)
        self.batch_quantity_spin.setValue(1)
        self.apply_defaults_button = QPushButton("应用到全部图片")
        self.apply_defaults_button.clicked.connect(self._apply_defaults_to_all)
        self.add_files_button = QPushButton("选择多张图片")
        self.remove_files_button = QPushButton("移除选中项")
        self.add_files_button.clicked.connect(self._add_files)
        self.remove_files_button.clicked.connect(self._remove_files)
        batch_type_option_group = QWidget()
        batch_type_option_layout = QHBoxLayout(batch_type_option_group)
        batch_type_option_layout.setContentsMargins(0, 0, 0, 0)
        batch_type_option_layout.setSpacing(6)
        batch_type_option_layout.addWidget(QLabel("批量 Type Option"))
        batch_type_option_layout.addWidget(self.batch_type_option_combo)
        batch_quantity_group = QWidget()
        batch_quantity_layout = QHBoxLayout(batch_quantity_group)
        batch_quantity_layout.setContentsMargins(0, 0, 0, 0)
        batch_quantity_layout.setSpacing(6)
        batch_quantity_layout.addWidget(QLabel("批量 Quantity"))
        batch_quantity_layout.addWidget(self.batch_quantity_spin)
        defaults_layout.addWidget(self.add_files_button)
        defaults_layout.addWidget(self.remove_files_button)
        defaults_layout.addWidget(batch_type_option_group)
        defaults_layout.addWidget(batch_quantity_group)
        defaults_layout.addWidget(self.apply_defaults_button)
        defaults_layout.addStretch(1)
        files_layout.addLayout(defaults_layout)

        self.file_table = QTableWidget(0, 9)
        self.file_table.setHorizontalHeaderLabels(
            [
                "缩略图",
                "图片名称",
                "order product code后缀备注",
                "生产位置",
                "Type Option",
                "Quantity",
                "大小",
                "状态",
                "信息",
            ]
        )
        self.file_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.file_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.file_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.file_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)
        self.file_table.setColumnWidth(0, 70)
        self.file_table.setColumnWidth(1, 105)
        self.file_table.setColumnWidth(2, 190)
        self.file_table.setColumnWidth(8, 130)
        files_layout.addWidget(self.file_table)
        submit_layout.addWidget(files_box, 1)

        action_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.submit_button = QPushButton("确认并批量提交")
        self.submit_button.clicked.connect(self._submit_batch)
        action_layout.addWidget(self.progress_bar, 1)
        action_layout.addWidget(self.submit_button)
        submit_layout.addLayout(action_layout)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMaximumHeight(130)
        submit_layout.addWidget(self.log_edit)
        self._build_sku_query_ui(sku_query_layout)
        self._build_confirmation_ui(confirmation_layout)
        self._build_recustom_ui(recustom_layout)
        self._build_stamp_replacement_ui(stamp_replacement_layout)
        self.setCentralWidget(root)

    def _build_sku_query_ui(self, layout: QVBoxLayout) -> None:
        controls = QGroupBox("2. 选择 Seller Shop")
        controls_layout = QHBoxLayout(controls)
        self.refresh_shops_button = QPushButton("读取 Shop 列表")
        self.refresh_shops_button.clicked.connect(self._load_seller_shops)
        self.seller_shop_combo = FullTextComboBox()
        self.seller_shop_combo.setMinimumWidth(360)
        self.load_shop_products_button = QPushButton("读取该 Shop Products")
        self.load_shop_products_button.clicked.connect(self._load_shop_products)
        self.shop_product_filter_edit = QLineEdit()
        self.shop_product_filter_edit.setPlaceholderText("按 Name 或 SKU 筛选")
        self.shop_product_filter_edit.textChanged.connect(self._filter_shop_products)
        controls_layout.addWidget(self.refresh_shops_button)
        controls_layout.addWidget(compact_field("Shop", self.seller_shop_combo), 0)
        controls_layout.addWidget(self.load_shop_products_button)
        controls_layout.addWidget(compact_field("筛选", self.shop_product_filter_edit, expandable=True), 1)
        layout.addWidget(controls)

        self.shop_products_table = QTableWidget(0, 3)
        self.shop_products_table.setHorizontalHeaderLabels(["Image", "Name", "SKU"])
        self.shop_products_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        shop_header = self.shop_products_table.horizontalHeader()
        shop_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        shop_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        shop_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.shop_products_table, 1)
        self.sku_query_status_label = QLabel("尚未读取 Shop Products")
        layout.addWidget(self.sku_query_status_label)

    def _build_recustom_ui(self, layout: QVBoxLayout) -> None:
        self.recustom_instructions_label = feature_instructions(
            "1.用于替换订单内product的设计，注意是填写Product ID。\n"
            "2.已confirm且未生产的订单亦可以替换（需和生产人员沟通清楚）。\n"
            "3.注意！已生产的订单请勿修改设计图。"
        )
        layout.addWidget(self.recustom_instructions_label)
        load_box = QGroupBox("2. 读取待替换设计")
        load_layout = QHBoxLayout(load_box)
        self.recustom_product_id_edit = QLineEdit()
        self.recustom_product_id_edit.setPlaceholderText("仅填写数字 Product ID")
        self.recustom_product_id_edit.setMaximumWidth(180)
        self.load_recustom_button = QPushButton("读取替换设计配置")
        self.load_recustom_button.clicked.connect(self._load_recustom_context)
        self.recustom_status_label = QLabel("尚未读取 Product")
        load_layout.addWidget(compact_field("Product ID", self.recustom_product_id_edit))
        load_layout.addWidget(self.load_recustom_button)
        load_layout.addWidget(self.recustom_status_label)
        load_layout.addStretch(1)
        layout.addWidget(load_box)

        form_box = QGroupBox("3. 替换设计内容")
        form_layout = QGridLayout(form_box)
        self.recustom_code_edit = QLineEdit()
        self.recustom_type_option_combo = FullTextComboBox()
        self.recustom_image_edit = QLineEdit()
        self.recustom_image_edit.setReadOnly(True)
        self.select_recustom_image_button = QPushButton("选择 First Image")
        self.select_recustom_image_button.clicked.connect(self._select_recustom_image)
        form_layout.addWidget(QLabel("Order Product Code"), 0, 0)
        form_layout.addWidget(self.recustom_code_edit, 0, 1, 1, 2)
        form_layout.addWidget(QLabel("Product Type Option"), 1, 0)
        form_layout.addWidget(self.recustom_type_option_combo, 1, 1, 1, 2)
        form_layout.addWidget(QLabel("First Image"), 2, 0)
        form_layout.addWidget(self.recustom_image_edit, 2, 1)
        form_layout.addWidget(self.select_recustom_image_button, 2, 2)
        form_layout.setColumnStretch(1, 1)
        layout.addWidget(form_box)
        self.submit_recustom_button = QPushButton("确认并提交替换设计")
        self.submit_recustom_button.clicked.connect(self._submit_recustom)
        layout.addWidget(self.submit_recustom_button, 0, Qt.AlignmentFlag.AlignRight)
        self.recustom_log_edit = QTextEdit()
        self.recustom_log_edit.setReadOnly(True)
        layout.addWidget(self.recustom_log_edit, 1)

    def _build_stamp_replacement_ui(self, layout: QVBoxLayout) -> None:
        self.stamp_replacement_instructions_label = feature_instructions(
            "1.只用于已confirm的订单，可替换订单的邮票（需和生产人员沟通清楚）。"
        )
        layout.addWidget(self.stamp_replacement_instructions_label)
        load_box = QGroupBox("2. 读取订单邮票配置")
        load_layout = QHBoxLayout(load_box)
        self.stamp_order_id_edit = QLineEdit()
        self.stamp_order_id_edit.setPlaceholderText("仅填写数字 Order ID")
        self.stamp_order_id_edit.setMaximumWidth(180)
        self.load_stamp_replacement_button = QPushButton("读取邮票提交配置")
        self.load_stamp_replacement_button.clicked.connect(self._load_stamp_replacement_context)
        self.stamp_replacement_status_label = QLabel("尚未读取 Order")
        load_layout.addWidget(compact_field("Order ID", self.stamp_order_id_edit))
        load_layout.addWidget(self.load_stamp_replacement_button)
        load_layout.addWidget(self.stamp_replacement_status_label)
        load_layout.addStretch(1)
        layout.addWidget(load_box)

        form_box = QGroupBox("3. 邮票文件")
        form_layout = QGridLayout(form_box)
        self.replacement_stamp_edit = QLineEdit()
        self.replacement_stamp_edit.setReadOnly(True)
        self.select_replacement_stamp_button = QPushButton("选择 Stamp PDF")
        self.select_replacement_stamp_button.clicked.connect(self._select_replacement_stamp)
        self.replacement_stamp_type_combo = QComboBox()
        self.replacement_gift_edit = QLineEdit()
        self.replacement_gift_edit.setReadOnly(True)
        self.select_replacement_gift_button = QPushButton("选择 Gift Message PDF（可选）")
        self.select_replacement_gift_button.clicked.connect(self._select_replacement_gift)
        form_layout.addWidget(QLabel("Stamp"), 0, 0)
        form_layout.addWidget(self.replacement_stamp_edit, 0, 1)
        form_layout.addWidget(self.select_replacement_stamp_button, 0, 2)
        form_layout.addWidget(QLabel("Stamp Type"), 1, 0)
        form_layout.addWidget(self.replacement_stamp_type_combo, 1, 1, 1, 2)
        form_layout.addWidget(QLabel("Gift Message"), 2, 0)
        form_layout.addWidget(self.replacement_gift_edit, 2, 1)
        form_layout.addWidget(self.select_replacement_gift_button, 2, 2)
        form_layout.setColumnStretch(1, 1)
        layout.addWidget(form_box)
        self.submit_stamp_replacement_button = QPushButton("确认并提交/替换邮票")
        self.submit_stamp_replacement_button.clicked.connect(self._submit_stamp_replacement)
        layout.addWidget(self.submit_stamp_replacement_button, 0, Qt.AlignmentFlag.AlignRight)
        self.stamp_replacement_log_edit = QTextEdit()
        self.stamp_replacement_log_edit.setReadOnly(True)
        layout.addWidget(self.stamp_replacement_log_edit, 1)

    def _build_confirmation_ui(self, layout: QVBoxLayout) -> None:
        order_box = QGroupBox("2. 选择待确认 Order")
        order_layout = QGridLayout(order_box)
        self.refresh_confirmation_orders_button = QPushButton("读取订单列表")
        self.refresh_confirmation_orders_button.clicked.connect(self._load_confirmation_orders)
        self.direct_confirmation_order_id_edit = QLineEdit()
        self.direct_confirmation_order_id_edit.setPlaceholderText("输入唯一数字 Order ID")
        self.open_confirmation_order_button = QPushButton("直接读取该 Order")
        self.open_confirmation_order_button.clicked.connect(self._open_confirmation_order_by_id)
        self.confirmation_order_filter_edit = QLineEdit()
        self.confirmation_order_filter_edit.setPlaceholderText("按 Order ID、Title 或 Status 筛选")
        self.confirmation_order_filter_edit.textChanged.connect(
            self._filter_confirmation_orders
        )
        self.confirmation_order_combo = FullTextComboBox()
        self.confirmation_order_combo.setIconSize(QSize(48, 48))
        self.confirmation_order_combo.currentIndexChanged.connect(
            self._confirmation_order_changed
        )
        self.load_confirmation_products_button = QPushButton("读取该 Order 产品")
        self.load_confirmation_products_button.clicked.connect(
            self._load_confirmation_products
        )
        self.confirmation_order_status_label = QLabel("尚未读取订单")
        self.confirmation_shipping_stamp_label = QLabel("Order Shipping Stamp：尚未读取")
        self.confirmation_shipping_stamp_label.setOpenExternalLinks(True)
        self.confirmation_shipping_stamp_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        order_layout.addWidget(self.refresh_confirmation_orders_button, 0, 0)
        order_layout.addWidget(QLabel("直接 Order ID"), 0, 1)
        order_layout.addWidget(self.direct_confirmation_order_id_edit, 0, 2)
        order_layout.addWidget(self.open_confirmation_order_button, 0, 3)
        order_layout.addWidget(QLabel("筛选"), 1, 1)
        order_layout.addWidget(self.confirmation_order_filter_edit, 1, 2)
        order_layout.addWidget(QLabel("Order"), 2, 1)
        order_layout.addWidget(self.confirmation_order_combo, 2, 2)
        order_layout.addWidget(self.load_confirmation_products_button, 2, 3)
        order_layout.addWidget(self.confirmation_order_status_label, 3, 2, 1, 2)
        order_layout.addWidget(self.confirmation_shipping_stamp_label, 4, 2, 1, 2)
        order_layout.setColumnStretch(2, 1)
        layout.addWidget(order_box)

        products_box = QGroupBox("3. Order 设计清单")
        products_layout = QVBoxLayout(products_box)
        self.confirmation_product_table = QTableWidget(0, 9)
        self.confirmation_product_table.setHorizontalHeaderLabels(
            [
                "缩略图",
                "Product ID",
                "设计名称",
                "产品状态",
                "Type Option",
                "Quantity",
                "Delete",
                "Recustom",
                "处理结果",
            ]
        )
        self.confirmation_product_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        confirmation_header = self.confirmation_product_table.horizontalHeader()
        confirmation_header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        confirmation_header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        confirmation_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        confirmation_header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        confirmation_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        confirmation_header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        confirmation_header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        confirmation_header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)
        confirmation_header.setSectionResizeMode(8, QHeaderView.ResizeMode.Interactive)
        self.confirmation_product_table.setColumnWidth(8, 180)
        products_layout.addWidget(self.confirmation_product_table)
        layout.addWidget(products_box, 1)

        documents_box = QGroupBox("4. 首张设计确认资料")
        documents_layout = QGridLayout(documents_box)
        self.shipping_stamp_edit = QLineEdit()
        self.shipping_stamp_edit.setReadOnly(True)
        self.shipping_stamp_button = QPushButton("选择 Shipping Stamp PDF")
        self.shipping_stamp_button.clicked.connect(self._select_shipping_stamp)
        self.confirmation_stamp_type_combo = QComboBox()
        self.gift_message_edit = QLineEdit()
        self.gift_message_edit.setReadOnly(True)
        self.gift_message_button = QPushButton("选择 Gift Message PDF（可选）")
        self.gift_message_button.clicked.connect(self._select_gift_message)
        self.confirmation_requirement_label = QLabel(
            "首次确认必须上传 Shipping Stamp 并选择 Stamp Type；Gift Message 可选。"
        )
        documents_layout.addWidget(QLabel("Shipping Stamp"), 0, 0)
        documents_layout.addWidget(self.shipping_stamp_edit, 0, 1)
        documents_layout.addWidget(self.shipping_stamp_button, 0, 2)
        documents_layout.addWidget(QLabel("Stamp Type"), 0, 3)
        documents_layout.addWidget(self.confirmation_stamp_type_combo, 0, 4)
        documents_layout.addWidget(QLabel("Gift Message"), 1, 0)
        documents_layout.addWidget(self.gift_message_edit, 1, 1, 1, 3)
        documents_layout.addWidget(self.gift_message_button, 1, 4)
        documents_layout.addWidget(self.confirmation_requirement_label, 2, 1, 1, 4)
        documents_layout.setColumnStretch(1, 1)
        layout.addWidget(documents_box)

        action_layout = QHBoxLayout()
        self.confirmation_progress_bar = QProgressBar()
        self.confirmation_progress_bar.setRange(0, 1)
        self.confirmation_progress_bar.setValue(0)
        self.confirm_order_button = QPushButton("确认并批量处理该 Order")
        self.confirm_order_button.clicked.connect(self._confirm_selected_order)
        action_layout.addWidget(self.confirmation_progress_bar, 1)
        action_layout.addWidget(self.confirm_order_button)
        layout.addLayout(action_layout)

        self.confirmation_log_edit = QTextEdit()
        self.confirmation_log_edit.setReadOnly(True)
        self.confirmation_log_edit.setMaximumHeight(120)
        layout.addWidget(self.confirmation_log_edit)

    def _append_log(self, message: str) -> None:
        self.log_edit.append(message)

    def _append_confirmation_log(self, message: str) -> None:
        self.confirmation_log_edit.append(message)

    def _show_confirmation_error(self, error: Exception | str) -> None:
        message = str(error)
        self._append_confirmation_log(f"失败：{message}")
        QMessageBox.critical(self, "订单确认操作失败", message)

    def _show_tab_error(self, log: QTextEdit, title: str, error: Exception | str) -> None:
        message = str(error)
        log.append(f"失败：{message}")
        QMessageBox.critical(self, title, message)

    def _load_seller_shops(self) -> None:
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_worker_error(exc)
            return

        def task(*, progress_callback: Any) -> list[SellerShop]:
            return client.fetch_seller_shops()

        def done(shops: list[SellerShop]) -> None:
            self.seller_shops = shops
            self.seller_shop_combo.clear()
            for shop in shops:
                self.seller_shop_combo.addItem(shop.label, shop)
            self.sku_query_status_label.setText(f"读取到 {len(shops)} 个 Shop")

        self._run("正在读取 Seller Shop 列表……", task, done)

    def _load_shop_products(self) -> None:
        shop = self.seller_shop_combo.currentData()
        if not isinstance(shop, SellerShop):
            self._show_worker_error("请先读取并选择 Shop。")
            return
        client = self._require_client()

        def task(
            *, progress_callback: Any
        ) -> tuple[list[ShopProduct], dict[int, bytes]]:
            products = client.fetch_shop_products(shop)
            thumbnails: dict[int, bytes] = {}
            for index, product in enumerate(products):
                if not product.image_url:
                    continue
                try:
                    thumbnails[index] = client.fetch_thumbnail_bytes(product.image_url)
                except Exception:
                    continue
            return products, thumbnails

        def done(result: tuple[list[ShopProduct], dict[int, bytes]]) -> None:
            self.shop_products, self.shop_product_thumbnails = result
            self._filter_shop_products(self.shop_product_filter_edit.text())
            self.sku_query_status_label.setText(
                f"Shop {shop.shop_id}：读取到 {len(self.shop_products)} 个 Products"
            )

        self._run("正在读取 Shop Products……", task, done)

    def _filter_shop_products(self, text: str) -> None:
        if not hasattr(self, "shop_products_table"):
            return
        needle = text.strip().casefold()
        matches = [
            (index, product)
            for index, product in enumerate(self.shop_products)
            if not needle
            or needle in product.name.casefold()
            or needle in product.sku.casefold()
        ]
        self.shop_products_table.setRowCount(0)
        for row, (source_index, product) in enumerate(matches):
            self.shop_products_table.insertRow(row)
            self.shop_products_table.setRowHeight(row, 64)
            image_label = QLabel("无图片")
            image_label.setFixedSize(56, 56)
            image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap()
            pixmap.loadFromData(self.shop_product_thumbnails.get(source_index, b""))
            if not pixmap.isNull():
                image_label.setText("")
                image_label.setPixmap(
                    pixmap.scaled(
                        QSize(52, 52),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            self.shop_products_table.setCellWidget(row, 0, image_label)
            self.shop_products_table.setItem(row, 1, QTableWidgetItem(product.name))
            self.shop_products_table.setItem(row, 2, QTableWidgetItem(product.sku))

    def _load_recustom_context(self) -> None:
        product_id = self.recustom_product_id_edit.text().strip()
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_tab_error(self.recustom_log_edit, "替换设计操作失败", exc)
            return

        def task(*, progress_callback: Any) -> RecustomContext:
            return client.prepare_recustom(product_id)

        def done(context: RecustomContext) -> None:
            self.recustom_context = context
            self.recustom_code_edit.setText(context.product_code)
            self.recustom_type_option_combo.clear()
            selected_index = 0
            for index, option in enumerate(context.type_options):
                self.recustom_type_option_combo.addItem(option.label, option)
                self.recustom_type_option_combo.setItemData(
                    index, option.label, Qt.ItemDataRole.ToolTipRole
                )
                if option.value == context.selected_type_option:
                    selected_index = index
            if self.recustom_type_option_combo.count():
                self.recustom_type_option_combo.setCurrentIndex(selected_index)
            self.recustom_image_edit.clear()
            self.recustom_status_label.setText(
                f"Product {context.product_id} 配置读取成功；请选择新的 First Image"
            )
            self.recustom_log_edit.append(f"已读取 Product {context.product_id}。")
            self._set_workflow_enabled(True)

        self._run(
            f"正在读取 Product {product_id} 的替换设计配置……",
            task,
            done,
            on_error=lambda error: self._show_tab_error(
                self.recustom_log_edit, "替换设计操作失败", error
            ),
            log_callback=self.recustom_log_edit.append,
        )

    def _select_recustom_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择新的 First Image", "", self.IMAGE_FILTER)
        if path:
            self.recustom_image_edit.setText(str(Path(path).resolve()))

    def _submit_recustom(self) -> None:
        context = self.recustom_context
        option = self.recustom_type_option_combo.currentData()
        image_path = self.recustom_image_edit.text().strip()
        if context is None:
            self._show_tab_error(self.recustom_log_edit, "替换设计操作失败", "请先读取 Product。")
            return
        if not isinstance(option, SelectOption) or not image_path:
            self._show_tab_error(
                self.recustom_log_edit,
                "替换设计操作失败",
                "请选择 Product Type Option 并上传新的 First Image。",
            )
            return
        if QMessageBox.question(
            self,
            "确认替换设计",
            f"即将替换 Product {context.product_id} 的设计图片和配置。是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> str:
            return client.submit_recustom(
                context,
                product_code=self.recustom_code_edit.text(),
                type_option_value=option.value,
                image_path=Path(image_path),
            )

        def done(result_url: str) -> None:
            self.recustom_log_edit.append(f"替换设计提交成功：{result_url}")
            self.recustom_status_label.setText(f"Product {context.product_id} 替换成功")
            self.recustom_context = None
            self._set_workflow_enabled(True)
            QMessageBox.information(self, "替换设计成功", f"Product {context.product_id} 已更新。")

        self._run(
            f"正在替换 Product {context.product_id} 的设计……",
            task,
            done,
            on_error=lambda error: self._show_tab_error(
                self.recustom_log_edit, "替换设计操作失败", error
            ),
            log_callback=self.recustom_log_edit.append,
        )

    def _load_stamp_replacement_context(self) -> None:
        order_id = self.stamp_order_id_edit.text().strip()
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_tab_error(self.stamp_replacement_log_edit, "替补邮票操作失败", exc)
            return

        def task(*, progress_callback: Any) -> StampReplacementContext:
            return client.prepare_stamp_replacement(order_id)

        def done(context: StampReplacementContext) -> None:
            self.stamp_replacement_context = context
            self.replacement_stamp_type_combo.clear()
            for option in context.stamp_types:
                self.replacement_stamp_type_combo.addItem(option.label, option)
            self.replacement_stamp_edit.clear()
            self.replacement_gift_edit.clear()
            self.stamp_replacement_status_label.setText(
                f"Order {order_id} 配置读取成功；请选择 Stamp PDF"
            )
            self.stamp_replacement_log_edit.append(f"已读取 Order {order_id} 邮票配置。")
            self._set_workflow_enabled(True)

        self._run(
            f"正在读取 Order {order_id} 的邮票配置……",
            task,
            done,
            on_error=lambda error: self._show_tab_error(
                self.stamp_replacement_log_edit, "替补邮票操作失败", error
            ),
            log_callback=self.stamp_replacement_log_edit.append,
        )

    def _select_replacement_stamp(self) -> None:
        path = self._select_confirmation_pdf("选择 Stamp PDF")
        if path:
            self.replacement_stamp_edit.setText(path)

    def _select_replacement_gift(self) -> None:
        path = self._select_confirmation_pdf("选择 Gift Message PDF（可选）")
        if path:
            self.replacement_gift_edit.setText(path)

    def _submit_stamp_replacement(self) -> None:
        context = self.stamp_replacement_context
        stamp_path = self.replacement_stamp_edit.text().strip()
        gift_path = self.replacement_gift_edit.text().strip()
        stamp_type = self.replacement_stamp_type_combo.currentData()
        order_id = self.stamp_order_id_edit.text().strip()
        if context is None or not stamp_path or not isinstance(stamp_type, SelectOption):
            self._show_tab_error(
                self.stamp_replacement_log_edit,
                "替补邮票操作失败",
                "请先读取 Order，并选择 Stamp PDF 和 Stamp Type。",
            )
            return
        if QMessageBox.question(
            self,
            "确认提交/替换邮票",
            f"即将为 Order {order_id} 提交或替换邮票文件。是否继续？",
        ) != QMessageBox.StandardButton.Yes:
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> str:
            return client.submit_stamp_replacement(
                context,
                stamp=Path(stamp_path),
                stamp_type=stamp_type.value,
                gift_message=Path(gift_path) if gift_path else None,
            )

        def done(result_url: str) -> None:
            self.stamp_replacement_log_edit.append(f"邮票提交成功：{result_url}")
            self.stamp_replacement_status_label.setText(f"Order {order_id} 邮票提交成功")
            self.stamp_replacement_context = None
            self._set_workflow_enabled(True)
            QMessageBox.information(self, "替补邮票成功", f"Order {order_id} 的邮票已提交。")

        self._run(
            f"正在为 Order {order_id} 提交/替换邮票……",
            task,
            done,
            on_error=lambda error: self._show_tab_error(
                self.stamp_replacement_log_edit, "替补邮票操作失败", error
            ),
            log_callback=self.stamp_replacement_log_edit.append,
        )

    def _set_workflow_enabled(self, enabled: bool) -> None:
        self.prepare_order_button.setEnabled(enabled and not self._busy and not self.order_id)
        self.continue_sku_button.setEnabled(
            enabled
            and not self._busy
            and bool(self.order_id)
            and self.batch_completed_successfully
        )
        self.new_order_button.setEnabled(enabled and not self._busy and bool(self.order_id))
        for widget in (
            self.load_definitions_button,
            self.load_types_button,
            self.load_options_button,
            self.apply_defaults_button,
            self.add_files_button,
            self.remove_files_button,
            self.submit_button,
            self.refresh_confirmation_orders_button,
            self.direct_confirmation_order_id_edit,
            self.open_confirmation_order_button,
            self.confirmation_order_filter_edit,
            self.confirmation_order_combo,
            self.load_confirmation_products_button,
            self.existing_order_id_edit,
            self.existing_sku_edit,
            self.load_existing_order_button,
            self.refresh_shops_button,
            self.seller_shop_combo,
            self.load_shop_products_button,
            self.shop_product_filter_edit,
            self.load_recustom_button,
            self.recustom_product_id_edit,
            self.load_stamp_replacement_button,
            self.stamp_order_id_edit,
            self.confirmation_product_table,
        ):
            widget.setEnabled(enabled and not self._busy)
        has_remaining = any(product.confirm_url for product in self.confirmation_products)
        confirmation_ready = enabled and not self._busy and has_remaining
        self.confirm_order_button.setEnabled(confirmation_ready)
        documents_enabled = confirmation_ready and self.confirmation_requires_stamp
        self.shipping_stamp_button.setEnabled(documents_enabled)
        self.confirmation_stamp_type_combo.setEnabled(documents_enabled)
        self.gift_message_button.setEnabled(documents_enabled)
        recustom_ready = enabled and not self._busy and self.recustom_context is not None
        self.recustom_code_edit.setEnabled(recustom_ready)
        self.recustom_type_option_combo.setEnabled(recustom_ready)
        self.select_recustom_image_button.setEnabled(recustom_ready)
        self.submit_recustom_button.setEnabled(recustom_ready)
        stamp_ready = enabled and not self._busy and self.stamp_replacement_context is not None
        self.replacement_stamp_type_combo.setEnabled(stamp_ready)
        self.select_replacement_stamp_button.setEnabled(stamp_ready)
        self.select_replacement_gift_button.setEnabled(stamp_ready)
        self.submit_stamp_replacement_button.setEnabled(stamp_ready)

    def _set_busy(self, busy: bool) -> None:
        was_busy = self._busy
        self._busy = busy
        self.login_button.setEnabled(not busy)
        self.remove_account_button.setEnabled(not busy)
        self.account_combo.setEnabled(not busy)
        self.password_edit.setEnabled(not busy)
        self._set_workflow_enabled(
            self.client is not None
            and self.client.logged_in
            and self.account_combo.currentText().strip() == self.logged_in_username
        )
        if busy and not was_busy:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        elif not busy and was_busy:
            QApplication.restoreOverrideCursor()

    def _workflow_tab_changed(self, index: int) -> None:
        if self._busy or self.client is None or not self.client.logged_in:
            return
        current = self.workflow_tabs.widget(index)
        if current is self.sku_query_tab and not self.seller_shop_combo.count():
            QTimer.singleShot(0, self._load_seller_shops)
        elif current is self.confirmation_tab and not self.confirmation_order_combo.count():
            QTimer.singleShot(0, self._load_confirmation_orders)

    def _clear_confirmation_products(self) -> None:
        self.confirmation_products = []
        self.confirmation_product_thumbnails = {}
        self.confirmation_requires_stamp = True
        self.confirmation_product_table.setRowCount(0)
        self.confirmation_stamp_type_combo.clear()
        self.shipping_stamp_edit.clear()
        self.gift_message_edit.clear()
        self.confirmation_progress_bar.setRange(0, 1)
        self.confirmation_progress_bar.setValue(0)
        self.confirmation_requirement_label.setText(
            "首次确认必须上传 Shipping Stamp 并选择 Stamp Type；Gift Message 可选。"
        )
        self.confirmation_shipping_stamp_label.setText("Order Shipping Stamp：尚未读取")

    def _reset_confirmation_state(self) -> None:
        if not hasattr(self, "confirmation_order_combo"):
            return
        self.confirmation_orders = []
        self.confirmation_order_loaded_directly = False
        self.confirmation_order_thumbnails = {}
        self.confirmation_order_filter_edit.blockSignals(True)
        self.confirmation_order_filter_edit.clear()
        self.confirmation_order_filter_edit.blockSignals(False)
        self.confirmation_order_combo.blockSignals(True)
        self.confirmation_order_combo.clear()
        self.confirmation_order_combo.blockSignals(False)
        self._clear_confirmation_products()
        self.confirmation_order_status_label.setText("尚未读取订单")
        self.confirmation_log_edit.clear()

    def _reset_auxiliary_state(self) -> None:
        if not hasattr(self, "seller_shop_combo"):
            return
        self.seller_shops = []
        self.shop_products = []
        self.shop_product_thumbnails = {}
        self.seller_shop_combo.clear()
        self.shop_products_table.setRowCount(0)
        self.shop_product_filter_edit.clear()
        self.sku_query_status_label.setText("尚未读取 Shop Products")
        self.recustom_context = None
        self.recustom_product_id_edit.clear()
        self.recustom_code_edit.clear()
        self.recustom_type_option_combo.clear()
        self.recustom_image_edit.clear()
        self.recustom_status_label.setText("尚未读取 Product")
        self.recustom_log_edit.clear()
        self.stamp_replacement_context = None
        self.stamp_order_id_edit.clear()
        self.replacement_stamp_edit.clear()
        self.replacement_stamp_type_combo.clear()
        self.replacement_gift_edit.clear()
        self.stamp_replacement_status_label.setText("尚未读取 Order")
        self.stamp_replacement_log_edit.clear()

    def _filter_confirmation_orders(self, text: str) -> None:
        selected = self.confirmation_order_combo.currentData()
        selected_id = selected.order_id if isinstance(selected, OrderSummary) else ""
        needle = text.strip().casefold()
        matches = [
            order
            for order in self.confirmation_orders
            if not needle
            or needle in order.order_id.casefold()
            or needle in order.title.casefold()
            or needle in order.status.casefold()
        ]
        self.confirmation_order_combo.blockSignals(True)
        self.confirmation_order_combo.clear()
        selected_index = 0
        for index, order in enumerate(matches):
            label = order.label if order.image_url else f"[无设计图] {order.label}"
            thumbnail = self.confirmation_order_thumbnails.get(order.order_id, b"")
            pixmap = QPixmap()
            if thumbnail:
                pixmap.loadFromData(thumbnail)
            if pixmap.isNull():
                self.confirmation_order_combo.addItem(label, order)
            else:
                icon = QIcon(
                    pixmap.scaled(
                        QSize(48, 48),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.confirmation_order_combo.addItem(icon, label, order)
            self.confirmation_order_combo.setItemData(
                index, label, Qt.ItemDataRole.ToolTipRole
            )
            if order.order_id == selected_id:
                selected_index = index
        if matches:
            self.confirmation_order_combo.setCurrentIndex(selected_index)
        self.confirmation_order_combo.blockSignals(False)
        self._confirmation_order_changed()

    def _confirmation_order_changed(self, *_: Any) -> None:
        self._clear_confirmation_products()
        order = self.confirmation_order_combo.currentData()
        if isinstance(order, OrderSummary):
            self.confirmation_order_status_label.setText(
                f"Order {order.order_id} 当前状态：{order.status or '-'}"
            )
        self._set_workflow_enabled(
            self.client is not None
            and self.client.logged_in
            and self.account_combo.currentText().strip() == self.logged_in_username
        )

    def _load_confirmation_orders(self) -> None:
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_confirmation_error(exc)
            return

        cached_thumbnails = dict(self.confirmation_order_thumbnails)

        def task(*, progress_callback: Any) -> tuple[list[OrderSummary], dict[str, bytes]]:
            orders = client.fetch_orders(limit=self.CONFIRMATION_ORDER_LIMIT)
            thumbnails: dict[str, bytes] = {}
            for order in orders:
                if not order.image_url:
                    continue
                if order.order_id in cached_thumbnails:
                    thumbnails[order.order_id] = cached_thumbnails[order.order_id]
                    continue
                try:
                    thumbnails[order.order_id] = client.fetch_thumbnail_bytes(order.image_url)
                except Exception:
                    # A broken thumbnail must not prevent the order list from loading.
                    continue
            return orders, thumbnails

        def done(result: tuple[list[OrderSummary], dict[str, bytes]]) -> None:
            orders, thumbnails = result
            self.confirmation_orders = orders
            self.confirmation_order_loaded_directly = False
            self.confirmation_order_thumbnails = thumbnails
            self._filter_confirmation_orders(self.confirmation_order_filter_edit.text())
            self._append_confirmation_log(
                f"读取到 {len(orders)} 个 Order（最多显示前 {self.CONFIRMATION_ORDER_LIMIT} 个）。"
            )

        self._run(
            f"正在读取订单列表（最多显示前 {self.CONFIRMATION_ORDER_LIMIT} 个；订单很多时最多等待 120 秒）……",
            task,
            done,
            on_error=self._show_confirmation_error,
            log_callback=self._append_confirmation_log,
        )

    def _open_confirmation_order_by_id(self) -> None:
        try:
            client = self._require_client()
            order = client.open_order_by_id(self.direct_confirmation_order_id_edit.text())
        except HiPersonalizationError as exc:
            self._show_confirmation_error(exc)
            return
        self.confirmation_orders = [order]
        self.confirmation_order_thumbnails = {}
        self.confirmation_order_loaded_directly = True
        self.confirmation_order_filter_edit.blockSignals(True)
        self.confirmation_order_filter_edit.clear()
        self.confirmation_order_filter_edit.blockSignals(False)
        self._filter_confirmation_orders("")
        self._append_confirmation_log(
            f"已按 Order ID {order.order_id} 直接打开；未读取完整订单列表。"
        )
        self._load_confirmation_products()

    def _load_confirmation_products(self) -> None:
        order = self.confirmation_order_combo.currentData()
        if not isinstance(order, OrderSummary):
            self._show_confirmation_error("请先读取并选择目标 Order。")
            return
        client = self._require_client()

        def task(
            *, progress_callback: Any
        ) -> tuple[list[ConfirmableProduct], list[SelectOption], dict[str, bytes], str]:
            products, shipping_stamp_url = client.fetch_order_products_page(order)
            first_remaining = next((product for product in products if product.confirm_url), None)
            stamp_types = (
                list(client.prepare_confirmation(first_remaining).stamp_types)
                if first_remaining
                else []
            )
            thumbnails: dict[str, bytes] = {}
            for product in products:
                if not product.image_url:
                    continue
                try:
                    thumbnails[product.product_id] = client.fetch_thumbnail_bytes(
                        product.image_url
                    )
                except Exception:
                    continue
            return products, stamp_types, thumbnails, shipping_stamp_url

        def done(
            result: tuple[
                list[ConfirmableProduct], list[SelectOption], dict[str, bytes], str
            ]
        ) -> None:
            products, stamp_types, thumbnails, shipping_stamp_url = result
            self.confirmation_products = products
            self.confirmation_product_thumbnails = thumbnails
            self.confirmation_requires_stamp = not any(
                product.status.casefold() == "image_confirmed" for product in products
            )
            self.confirmation_product_table.setRowCount(0)
            for row, product in enumerate(products):
                self.confirmation_product_table.insertRow(row)
                self.confirmation_product_table.setRowHeight(row, 64)
                thumbnail_data = thumbnails.get(product.product_id, b"")
                thumbnail = RemoteThumbnailLabel(
                    thumbnail_data, product.title or product.product_id, product.preview_url
                )
                thumbnail.clicked.connect(self._show_confirmation_image_preview)
                image_cell = QWidget()
                image_layout = QHBoxLayout(image_cell)
                image_layout.setContentsMargins(3, 3, 3, 3)
                image_layout.addWidget(thumbnail)
                image_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.confirmation_product_table.setCellWidget(row, 0, image_cell)
                values = (
                    product.product_id,
                    product.title,
                    product.status,
                    product.type_option,
                    product.quantity,
                )
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.confirmation_product_table.setItem(row, column + 1, item)
                delete_button = QPushButton("Delete")
                delete_button.setEnabled(bool(product.delete_url))
                delete_button.clicked.connect(
                    lambda _checked=False, selected=product: self._delete_confirmation_product(
                        selected
                    )
                )
                recustom_button = QPushButton("Recustom")
                recustom_button.setEnabled(bool(product.recustom_url))
                recustom_button.clicked.connect(
                    lambda _checked=False, selected=product: self._open_product_in_recustom(
                        selected
                    )
                )
                self.confirmation_product_table.setCellWidget(row, 6, delete_button)
                self.confirmation_product_table.setCellWidget(row, 7, recustom_button)
                result_item = QTableWidgetItem(
                    "待确认" if product.confirm_url else "已确认"
                )
                if not product.confirm_url:
                    self._set_success_item_style(result_item)
                self.confirmation_product_table.setItem(row, 8, result_item)
            self.confirmation_stamp_type_combo.clear()
            for option in stamp_types:
                self.confirmation_stamp_type_combo.addItem(option.label, option)
            remaining = sum(bool(product.confirm_url) for product in products)
            if not remaining:
                self.confirmation_requirement_label.setText("该 Order 的设计已全部确认。")
            elif self.confirmation_requires_stamp:
                self.confirmation_requirement_label.setText(
                    "首次确认：Shipping Stamp PDF 和 Stamp Type 必填；Gift Message PDF 可选。"
                )
            else:
                self.confirmation_requirement_label.setText(
                    "检测到已有 image_confirmed 设计；重试时仅直接 Submit 剩余设计，不会重复上传邮票。"
                )
            self.confirmation_order_status_label.setText(
                f"Order {order.order_id}：共 {len(products)} 个设计，待确认 {remaining} 个，订单状态 {order.status or '-'}"
            )
            if shipping_stamp_url:
                safe_url = escape(shipping_stamp_url, quote=True)
                self.confirmation_shipping_stamp_label.setText(
                    f'Order Shipping Stamp：<a href="{safe_url}">打开 PDF</a>'
                )
                self.confirmation_shipping_stamp_label.setToolTip(shipping_stamp_url)
            else:
                self.confirmation_shipping_stamp_label.setText(
                    "Order Shipping Stamp：该 Order 暂无邮票文件"
                )
                self.confirmation_shipping_stamp_label.setToolTip("")
            self._append_confirmation_log(
                f"Order {order.order_id} 读取完成：{len(products)} 个设计，待确认 {remaining} 个。"
            )

        self._run(
            f"正在读取 Order {order.order_id} 的设计清单……",
            task,
            done,
            on_error=self._show_confirmation_error,
            log_callback=self._append_confirmation_log,
        )

    def _delete_confirmation_product(self, product: ConfirmableProduct) -> None:
        if not product.delete_url:
            self._show_confirmation_error(f"Product {product.product_id} 没有 Delete 功能。")
            return
        answer = QMessageBox.warning(
            self,
            "确认删除设计",
            f"即将在线删除 Product {product.product_id}（{product.title}）。\n"
            "删除后无法由本工具恢复，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> str:
            return client.delete_order_product(product)

        def done(result_url: str) -> None:
            self._append_confirmation_log(
                f"Product {product.product_id} 已删除：{result_url}"
            )
            QMessageBox.information(
                self, "删除成功", f"Product {product.product_id} 已从订单中删除。"
            )
            QTimer.singleShot(0, self._load_confirmation_products)

        self._run(
            f"正在删除 Product {product.product_id}……",
            task,
            done,
            on_error=self._show_confirmation_error,
            log_callback=self._append_confirmation_log,
        )

    def _open_product_in_recustom(self, product: ConfirmableProduct) -> None:
        self.workflow_tabs.setCurrentWidget(self.recustom_tab)
        self.recustom_product_id_edit.setText(product.product_id)
        self.recustom_log_edit.append(
            f"从订单确认页载入 Product {product.product_id}。"
        )
        QTimer.singleShot(0, self._load_recustom_context)

    def _select_confirmation_pdf(self, title: str) -> str:
        path, _ = QFileDialog.getOpenFileName(self, title, "", "PDF files (*.pdf)")
        return str(Path(path).resolve()) if path else ""

    def _select_shipping_stamp(self) -> None:
        path = self._select_confirmation_pdf("选择 Shipping Stamp PDF")
        if path:
            self.shipping_stamp_edit.setText(path)

    def _select_gift_message(self) -> None:
        path = self._select_confirmation_pdf("选择 Gift Message PDF（可选）")
        if path:
            self.gift_message_edit.setText(path)

    def _show_confirmation_image_preview(self, request: tuple[str, str]) -> None:
        title, preview_url = request
        if not preview_url:
            self._show_confirmation_error("该设计没有可用的原图地址。")
            return
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_confirmation_error(exc)
            return

        def task(*, progress_callback: Any) -> bytes:
            return client.fetch_image_bytes(preview_url)

        def done(image_data: bytes) -> None:
            ImageBytesPreviewDialog(image_data, title, self).exec()

        self._run(
            f"正在读取设计原图：{title}……",
            task,
            done,
            on_error=self._show_confirmation_error,
            log_callback=self._append_confirmation_log,
        )

    def _confirm_selected_order(self) -> None:
        order = self.confirmation_order_combo.currentData()
        remaining = [product for product in self.confirmation_products if product.confirm_url]
        if not isinstance(order, OrderSummary) or not remaining:
            self._show_confirmation_error("当前 Order 没有待确认设计。")
            return
        shipping_path = self.shipping_stamp_edit.text().strip()
        gift_path = self.gift_message_edit.text().strip()
        stamp_type = self.confirmation_stamp_type_combo.currentData()
        if self.confirmation_requires_stamp:
            if not shipping_path:
                self._show_confirmation_error("首次确认必须选择 Shipping Stamp PDF。")
                return
            if not isinstance(stamp_type, SelectOption):
                self._show_confirmation_error("首次确认必须选择 Stamp Type。")
                return
        answer = QMessageBox.question(
            self,
            "确认 Order",
            f"即将确认 Order {order.order_id} 的 {len(remaining)} 个设计。\n"
            "该操作会修改线上订单状态，是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        client = self._require_client()
        requires_stamp = self.confirmation_requires_stamp
        self.confirmation_progress_bar.setRange(0, len(remaining))
        self.confirmation_progress_bar.setValue(0)

        def task(
            *, progress_callback: Any
        ) -> tuple[list[tuple[str, bool, str]], str]:
            results: list[tuple[str, bool, str]] = []
            for index, product in enumerate(remaining, start=1):
                progress_callback.emit((product.product_id, "提交中", "", index - 1))
                try:
                    context = client.prepare_confirmation(product)
                    first_with_stamp = index == 1 and requires_stamp
                    result_url = client.submit_confirmation(
                        context,
                        shipping_stamp=Path(shipping_path) if first_with_stamp else None,
                        stamp_type=(
                            stamp_type.value
                            if first_with_stamp and isinstance(stamp_type, SelectOption)
                            else ""
                        ),
                        gift_message=(
                            Path(gift_path) if first_with_stamp and gift_path else None
                        ),
                    )
                    message = f"确认成功：{result_url}"
                    results.append((product.product_id, True, message))
                    progress_callback.emit((product.product_id, "已确认", message, index))
                except Exception as exc:
                    message = str(exc)
                    results.append((product.product_id, False, message))
                    progress_callback.emit((product.product_id, "失败", message, index))
                    break
            try:
                if self.confirmation_order_loaded_directly:
                    final_products = client.fetch_order_products(order)
                    remaining_count = sum(bool(item.confirm_url) for item in final_products)
                    final_status = (
                        "all_confirmed（已直接核查订单设计清单）"
                        if not remaining_count
                        else f"仍有 {remaining_count} 个设计待确认"
                    )
                else:
                    final_status = client.fetch_order_status(order.order_id)
            except Exception as exc:
                final_status = f"状态读取失败：{exc}"
            return results, final_status

        def progress(value: tuple[str, str, str, int]) -> None:
            product_id, status, message, completed = value
            for row in range(self.confirmation_product_table.rowCount()):
                if self.confirmation_product_table.item(row, 1).text() == product_id:
                    self.confirmation_product_table.item(row, 8).setText(status)
                    self.confirmation_product_table.item(row, 8).setToolTip(message)
                    if status == "已确认":
                        self._set_success_item_style(
                            self.confirmation_product_table.item(row, 8)
                        )
                    break
            self.confirmation_progress_bar.setValue(completed)

        def done(result: tuple[list[tuple[str, bool, str]], str]) -> None:
            results, final_status = result
            successes = sum(success for _, success, _ in results)
            failures = len(results) - successes
            successful_ids = {product_id for product_id, success, _ in results if success}
            self.confirmation_products = [
                ConfirmableProduct(
                    product_id=product.product_id,
                    title=product.title,
                    status="image_confirmed" if product.product_id in successful_ids else product.status,
                    type_option=product.type_option,
                    quantity=product.quantity,
                    confirm_url="" if product.product_id in successful_ids else product.confirm_url,
                    image_url=product.image_url,
                    preview_url=product.preview_url,
                    delete_url=product.delete_url,
                    recustom_url=product.recustom_url,
                )
                for product in self.confirmation_products
            ]
            if successful_ids:
                self.confirmation_requires_stamp = False
                self.confirmation_requirement_label.setText(
                    "Shipping Stamp 已随首张设计提交；如需重试，只会直接 Submit 剩余设计。"
                )
                for row in range(self.confirmation_product_table.rowCount()):
                    if self.confirmation_product_table.item(row, 1).text() in successful_ids:
                        self.confirmation_product_table.item(row, 3).setText("image_confirmed")
                        result_item = self.confirmation_product_table.item(row, 8)
                        result_item.setText("已确认")
                        self._set_success_item_style(result_item)
            self.confirmation_order_status_label.setText(
                f"Order {order.order_id} 最新状态：{final_status}"
            )
            if not final_status.casefold().startswith("状态读取失败"):
                normalized_status = (
                    "all_confirmed"
                    if final_status.casefold().startswith("all_confirmed")
                    else final_status
                )
                updated_order = replace(order, status=normalized_status)
                self.confirmation_orders = [
                    updated_order if item.order_id == order.order_id else item
                    for item in self.confirmation_orders
                ]
                current_index = self.confirmation_order_combo.currentIndex()
                if current_index >= 0:
                    self.confirmation_order_combo.setItemData(
                        current_index, updated_order, Qt.ItemDataRole.UserRole
                    )
                    self.confirmation_order_combo.setItemText(
                        current_index, updated_order.label
                    )
            self._append_confirmation_log(
                f"Order {order.order_id}：成功 {successes}，失败 {failures}，最新状态 {final_status}。"
            )
            if final_status.casefold().startswith("all_confirmed"):
                QMessageBox.information(
                    self, "订单确认完成", f"Order {order.order_id} 状态已变为 all_confirmed。"
                )
            else:
                QMessageBox.warning(
                    self,
                    "订单尚未全部确认",
                    f"当前状态为 {final_status or '-'}。请根据失败信息修正后重新读取该 Order。",
                )

        self._run(
            f"开始批量确认 Order {order.order_id}……",
            task,
            done,
            progress,
            on_error=self._show_confirmation_error,
            log_callback=self._append_confirmation_log,
        )

    def _run(
        self,
        label: str,
        function: Callable[..., Any],
        on_result: Callable[[Any], None],
        on_progress: Callable[[Any], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        if self._busy:
            return
        (log_callback or self._append_log)(label)
        self._set_busy(True)
        worker = FunctionWorker(function)
        self._active_workers.add(worker)
        worker.signals.result.connect(on_result)
        worker.signals.error.connect(on_error or self._show_worker_error)
        if on_progress:
            worker.signals.progress.connect(on_progress)

        def finished() -> None:
            self._active_workers.discard(worker)
            self._set_busy(False)
            if self._pending_auto_types:
                self._pending_auto_types = False
                QTimer.singleShot(0, self._load_types)
            elif self._pending_auto_options:
                self._pending_auto_options = False
                QTimer.singleShot(0, self._load_type_options)

        worker.signals.finished.connect(finished)
        self.thread_pool.start(worker)

    def _show_worker_error(self, error: Exception | str) -> None:
        message = str(error)
        if not self.client or not self.client.logged_in:
            self.login_status_label.setText("操作失败")
        self._append_log(f"失败：{message}")
        QMessageBox.critical(self, "操作失败", message)

    def _load_account_choices(self, selected: str = "") -> None:
        accounts = self.account_store.accounts()
        selected = selected or self.account_store.last_account()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.account_combo.addItems(accounts)
        if selected:
            self.account_combo.setCurrentText(selected)
        self.account_combo.blockSignals(False)
        self._account_changed(self.account_combo.currentText())

    def _account_changed(self, username: str) -> None:
        self.password_edit.clear()
        if username.strip() in self.account_store.accounts():
            self.password_edit.setPlaceholderText("密码已安全保存在系统凭据库")
        else:
            self.password_edit.setPlaceholderText("首次登录或密码失效时填写")
        if self.logged_in_username and username.strip() != self.logged_in_username:
            self._reset_confirmation_state()
            self._reset_auxiliary_state()
            self.login_status_label.setText("账号已切换，请登录后继续")
            self._set_workflow_enabled(False)

    def _saved_account_activated(self, index: int) -> None:
        if self._busy or index < 0:
            return
        username = self.account_combo.itemText(index).strip()
        if not username or username == self.logged_in_username:
            return
        if username not in self.account_store.accounts():
            return
        try:
            password = self.account_store.password(username) or ""
        except CredentialStoreError as exc:
            self._show_worker_error(exc)
            return
        if not password:
            self.password_edit.setPlaceholderText("保存的密码已失效，请重新输入")
            self.password_edit.setFocus()
            self.login_status_label.setText("请重新输入密码后登录")
            return
        self._start_login(username, password, automatic=True)

    def _auto_login_last_account(self) -> None:
        username = self.account_store.last_account()
        password = self.account_store.password(username) if username else None
        if not username and self.settings.seller_username and self.settings.seller_password:
            username = self.settings.seller_username
            password = self.settings.seller_password
            self.account_combo.setCurrentText(username)
        if username and password:
            self._start_login(username, password, automatic=True)

    def _login(self) -> None:
        username = self.account_combo.currentText().strip()
        typed_password = self.password_edit.text()
        try:
            password = typed_password or self.account_store.password(username) or ""
        except CredentialStoreError as exc:
            self._show_worker_error(exc)
            return
        if not username or not password:
            self._show_worker_error("请选择或输入 Seller 账号，并填写密码。")
            return
        self._start_login(username, password, automatic=False)

    def _start_login(self, username: str, password: str, *, automatic: bool) -> None:
        base_url = self.settings.base_url
        if self.client:
            self.client.session.close()
        self.client = None
        self.logged_in_username = ""
        self._reset_order_state()
        self._reset_confirmation_state()
        self._reset_auxiliary_state()
        self.order_title_edit.clear()
        self.sku_edit.clear()
        self._set_workflow_enabled(False)
        self.login_status_label.setText("正在自动登录……" if automatic else "正在登录……")

        def task(*, progress_callback: Any) -> HiPersonalizationClient:
            client = HiPersonalizationClient(base_url)
            client.login(username, password)
            return client

        def done(client: HiPersonalizationClient) -> None:
            self._reset_order_state()
            self.client = client
            self.logged_in_username = username
            try:
                self.account_store.save(username, password)
            except CredentialStoreError as exc:
                QMessageBox.warning(self, "密码未保存", str(exc))
            self._load_account_choices(username)
            self.password_edit.clear()
            self.login_status_label.setText("登录成功，订单流程已解锁")
            self._append_log("Seller 登录成功。")
            QTimer.singleShot(
                0, lambda: self._workflow_tab_changed(self.workflow_tabs.currentIndex())
            )

        def failed(error: Exception) -> None:
            if isinstance(error, AuthenticationError):
                try:
                    self.account_store.forget_password(username)
                except CredentialStoreError:
                    pass
                self.password_edit.clear()
                self.password_edit.setPlaceholderText("密码错误或已失效，请重新输入")
                self.password_edit.setFocus()
                self.login_status_label.setText("登录失败，请重新输入密码")
                self._append_log(f"登录失败：{error}")
                QMessageBox.warning(self, "登录失败", str(error))
            else:
                self.login_status_label.setText("登录失败，请检查网络后重试")
                self._show_worker_error(error)

        self._run("正在自动登录上次账号……" if automatic else "正在登录 seller 账号……", task, done, on_error=failed)

    def _remove_account(self) -> None:
        username = self.account_combo.currentText().strip()
        if not username or username not in self.account_store.accounts():
            return
        if QMessageBox.question(self, "删除本地账号", f"是否从本机删除账号 {username} 及其保存的密码？") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.account_store.remove(username)
        except CredentialStoreError as exc:
            self._show_worker_error(exc)
            return
        if self.client:
            self.client.session.close()
        self.client = None
        self.logged_in_username = ""
        self._reset_order_state()
        self._reset_confirmation_state()
        self._reset_auxiliary_state()
        self._set_workflow_enabled(False)
        self.login_status_label.setText("账号已从本机删除，订单流程已锁定")
        self._load_account_choices()

    def _reset_order_state(self) -> None:
        self.order_id = ""
        self.created_order_title = ""
        self.batch_completed_successfully = False
        self._pending_auto_types = False
        self._pending_auto_options = False
        if hasattr(self, "order_id_label"):
            self.order_id_label.setText("Order ID：尚未创建")
        self.available_type_options = []
        for combo_name in (
            "product_combo",
            "definition_combo",
            "type_combo",
            "batch_type_option_combo",
        ):
            combo = getattr(self, combo_name, None)
            if combo is not None:
                combo.clear()
        if hasattr(self, "file_table"):
            self.file_table.setRowCount(0)
        if hasattr(self, "order_title_edit"):
            self.order_title_edit.setReadOnly(False)
        if hasattr(self, "existing_order_id_edit"):
            self.existing_order_id_edit.clear()
        if hasattr(self, "type_options_status_label"):
            self.type_options_status_label.setText("尚未读取 Type Options")

    def _reset_sku_state(self) -> None:
        self.available_type_options = []
        for combo in (
            self.product_combo,
            self.definition_combo,
            self.type_combo,
            self.batch_type_option_combo,
        ):
            combo.clear()
        self.file_table.setRowCount(0)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.batch_completed_successfully = False
        self._pending_auto_types = False
        self._pending_auto_options = False
        self.type_options_status_label.setText("尚未读取 Type Options")

    def _require_client(self) -> HiPersonalizationClient:
        if (
            not self.client
            or not self.client.logged_in
            or self.account_combo.currentText().strip() != self.logged_in_username
        ):
            raise HiPersonalizationError("请先登录 seller 账号。")
        return self.client

    def _prepare_order(self) -> None:
        if self.order_id:
            QMessageBox.information(self, "订单已创建", "当前窗口已经创建过订单，请勿重复提交。")
            return
        title = self.order_title_edit.text().strip()
        self.order_title_edit.setText(title)
        sku = self.sku_edit.text().strip()
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_worker_error(str(exc))
            return

        def task(*, progress_callback: Any) -> tuple[str, list[ProductOption]]:
            order_id = client.create_order(title)
            products = client.search_products(order_id, sku)
            return order_id, products

        def done(result: tuple[str, list[ProductOption]]) -> None:
            self.order_id, products = result
            self.created_order_title = title
            self.existing_order_id_edit.clear()
            self.order_title_edit.setReadOnly(True)
            self.batch_completed_successfully = False
            self.order_id_label.setText(f"Order ID：{self.order_id}")
            self.product_combo.clear()
            for option in products:
                self.product_combo.addItem(option.label, option)
            self.prepare_order_button.setEnabled(False)
            self._append_log(f"订单 {self.order_id} 已创建，找到 {len(products)} 个产品。")
            if len(products) == 1:
                QTimer.singleShot(0, self._load_definitions)

        self._run("正在创建订单并搜索 SKU……", task, done)

    def _continue_with_sku(self) -> None:
        if not self.order_id or not self.batch_completed_successfully:
            self._show_worker_error("当前 SKU 的图片需要全部提交成功后才能继续添加新 SKU。")
            return
        title = self.order_title_edit.text().strip()
        if title != self.created_order_title:
            self._show_worker_error("继续添加 SKU 时不能修改 Order Title。")
            return
        sku = self.sku_edit.text().strip()
        if not sku:
            self._show_worker_error("请填写新的 Product SKU。")
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> list[ProductOption]:
            return client.search_products(self.order_id, sku)

        def done(products: list[ProductOption]) -> None:
            self._reset_sku_state()
            for option in products:
                self.product_combo.addItem(option.label, option)
            self._append_log(
                f"继续使用 Order {self.order_id}，新 SKU 找到 {len(products)} 个产品。"
            )
            if len(products) == 1:
                QTimer.singleShot(0, self._load_definitions)

        self._run("正在为当前 Order 搜索新的 SKU……", task, done)

    def _load_existing_order(self) -> None:
        requested_order_id = self.existing_order_id_edit.text().strip()
        sku = self.sku_edit.text().strip()
        try:
            client = self._require_client()
        except HiPersonalizationError as exc:
            self._show_worker_error(exc)
            return
        if not requested_order_id or not requested_order_id.isdigit():
            self._show_worker_error("请填写数字格式的已有 Order ID。")
            return
        if not sku:
            self._show_worker_error("请在上方 Product SKU 输入框填写需要新增的 SKU。")
            return
        if self.order_id or self.file_table.rowCount():
            answer = QMessageBox.question(
                self,
                "切换到已有 Order",
                "载入已有 Order 会清空当前窗口中的本地图片和配置，但不会删除网站数据。是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        def task(*, progress_callback: Any) -> tuple[OrderSummary, list[ProductOption]]:
            order = client.fetch_order(requested_order_id, allow_confirmed=False)
            products = client.search_products(order.order_id, sku)
            return order, products

        def done(result: tuple[OrderSummary, list[ProductOption]]) -> None:
            order, products = result
            self._reset_order_state()
            self.order_id = order.order_id
            self.created_order_title = order.title.strip()
            self.batch_completed_successfully = False
            self.order_title_edit.setText(self.created_order_title)
            self.order_title_edit.setReadOnly(True)
            self.sku_edit.setText(sku)
            self.existing_order_id_edit.setText(order.order_id)
            self.order_id_label.setText(
                f"Order ID：{order.order_id}（已载入，状态：{order.status or '-'}）"
            )
            for option in products:
                self.product_combo.addItem(option.label, option)
            self._append_log(
                f"已载入已有 Order {order.order_id}，Title：{order.title}，找到 {len(products)} 个产品。"
            )
            if len(products) == 1:
                QTimer.singleShot(0, self._load_definitions)

        self._run(
            f"正在载入已有 Order {requested_order_id} 并搜索 SKU……",
            task,
            done,
        )

    def _start_new_order(self) -> None:
        try:
            self._require_client()
        except HiPersonalizationError as exc:
            self._show_worker_error(exc)
            return
        if self.file_table.rowCount() and not self.batch_completed_successfully:
            answer = QMessageBox.question(
                self,
                "开始新 Order",
                "当前 Order 还有未全部成功的图片任务。开始新 Order 只会清空本地界面，不会删除网站已有数据。是否继续？",
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
        previous_order = self.order_id
        self._reset_order_state()
        self.order_title_edit.clear()
        self.sku_edit.clear()
        self._set_workflow_enabled(True)
        self.order_title_edit.setFocus()
        self._append_log(f"已结束 Order {previous_order} 的本地流程，可以创建新的 Order。")

    def _load_definitions(self) -> None:
        product = self.product_combo.currentData()
        if not self.order_id or not isinstance(product, ProductOption):
            self._show_worker_error("请先创建订单并选择 Product。")
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> list[DefinitionOption]:
            return client.fetch_definitions(self.order_id, product.product_id)

        def done(options: list[DefinitionOption]) -> None:
            self.definition_combo.blockSignals(True)
            self.definition_combo.clear()
            for option in options:
                self.definition_combo.addItem(option.label, option)
            self.definition_combo.blockSignals(False)
            self._append_log(f"读取到 {len(options)} 个 Definition。")
            self._auto_load_types(self.definition_combo.currentIndex())

        self._run("正在读取 Definitions……", task, done)

    def _auto_load_types(self, index: int) -> None:
        if (
            index >= 0
            and self.order_id
            and isinstance(self.definition_combo.currentData(), DefinitionOption)
        ):
            if self._busy:
                self._pending_auto_types = True
            else:
                QTimer.singleShot(0, self._load_types)

    def _load_types(self) -> None:
        definition = self.definition_combo.currentData()
        if not self.order_id or not isinstance(definition, DefinitionOption):
            self._show_worker_error("请选择 Definition。")
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> list[SelectOption]:
            return client.fetch_types(self.order_id, definition.definition_id)

        def done(options: list[SelectOption]) -> None:
            self.type_combo.blockSignals(True)
            self.type_combo.clear()
            for option in options:
                self.type_combo.addItem(option.label, option)
            self.type_combo.blockSignals(False)
            self._append_log(f"读取到 {len(options)} 个 Product Type。")
            self._auto_load_type_options(self.type_combo.currentIndex())

        self._run("正在读取 Product Types……", task, done)

    def _auto_load_type_options(self, index: int) -> None:
        self._invalidate_type_options()
        if (
            index >= 0
            and self.order_id
            and isinstance(self.definition_combo.currentData(), DefinitionOption)
            and isinstance(self.type_combo.currentData(), SelectOption)
        ):
            if self._busy:
                self._pending_auto_options = True
            else:
                QTimer.singleShot(0, self._load_type_options)

    def _load_type_options(self) -> None:
        definition = self.definition_combo.currentData()
        product_type = self.type_combo.currentData()
        if not self.order_id or not isinstance(definition, DefinitionOption):
            self._show_worker_error("请选择 Definition。")
            return
        if not isinstance(product_type, SelectOption):
            self._show_worker_error("请选择 Product Type。")
            return
        client = self._require_client()

        def task(*, progress_callback: Any) -> list[SelectOption]:
            context = client.prepare_upload(
                self.order_id, definition.definition_id, product_type.value
            )
            return list(context.type_options)

        def done(options: list[SelectOption]) -> None:
            self.available_type_options = options
            self.batch_type_option_combo.clear()
            for option in options:
                self.batch_type_option_combo.addItem(option.label, option)
                self.batch_type_option_combo.setItemData(
                    self.batch_type_option_combo.count() - 1,
                    option.label,
                    Qt.ItemDataRole.ToolTipRole,
                )
            for row in range(self.file_table.rowCount()):
                combo = self.file_table.cellWidget(row, 4)
                if isinstance(combo, QComboBox) and combo.isEnabled():
                    self._fill_type_option_combo(combo)
            self.type_options_status_label.setText(f"已读取 {len(options)} 个 Type Options")
            self._append_log(f"读取到 {len(options)} 个 Type Option。")

        self._run("正在读取 Type Options……", task, done)

    def _invalidate_type_options(self, *_: Any) -> None:
        self.available_type_options = []
        self.batch_type_option_combo.clear()
        self.type_options_status_label.setText("Product Type 已变化，请重新读取 Type Options")
        for row in range(self.file_table.rowCount()):
            combo = self.file_table.cellWidget(row, 4)
            if isinstance(combo, QComboBox) and combo.isEnabled():
                combo.clear()

    def _fill_type_option_combo(self, combo: QComboBox, selected_value: str = "") -> None:
        combo.clear()
        selected_index = 0
        for index, option in enumerate(self.available_type_options):
            combo.addItem(option.label, option)
            combo.setItemData(index, option.label, Qt.ItemDataRole.ToolTipRole)
            if option.value == selected_value:
                selected_index = index
        if combo.count():
            combo.setCurrentIndex(selected_index)

    def _apply_defaults_to_all(self) -> None:
        default_option = self.batch_type_option_combo.currentData()
        if not isinstance(default_option, SelectOption):
            self._show_worker_error("请先读取并选择批量 Type Option。")
            return
        for row in range(self.file_table.rowCount()):
            combo = self.file_table.cellWidget(row, 4)
            quantity = self.file_table.cellWidget(row, 5)
            if isinstance(combo, QComboBox) and combo.isEnabled():
                for index in range(combo.count()):
                    option = combo.itemData(index)
                    if isinstance(option, SelectOption) and option.value == default_option.value:
                        combo.setCurrentIndex(index)
                        break
            if isinstance(quantity, QSpinBox) and quantity.isEnabled():
                quantity.setValue(self.batch_quantity_spin.value())
        self._append_log(f"已将相同的 Type Option 和 Quantity 应用到 {self.file_table.rowCount()} 张图片。")

    @staticmethod
    def _format_size(size: int) -> str:
        return f"{size / 1024 / 1024:.2f} MB"

    @staticmethod
    def _set_success_item_style(item: QTableWidgetItem) -> None:
        item.setBackground(QBrush(QColor("#C6EFCE")))
        item.setForeground(QBrush(QColor("#006100")))

    def _set_submission_row_status(
        self, row: int, status: str, message: str = ""
    ) -> None:
        if not 0 <= row < self.file_table.rowCount():
            return
        status_item = self.file_table.item(row, 7)
        message_item = self.file_table.item(row, 8)
        status_item.setText(status)
        message_item.setText(message)
        message_item.setToolTip(message)
        if status in {"成功", "已跳过"}:
            self._set_success_item_style(status_item)
            for column in range(2, 6):
                control = self.file_table.cellWidget(row, column)
                if control is not None:
                    control.setEnabled(False)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "选择设计图片", "", self.IMAGE_FILTER)
        for raw_path in paths:
            path = Path(raw_path).resolve()
            row = self.file_table.rowCount()
            self.file_table.insertRow(row)
            self.file_table.setRowHeight(row, 64)
            name_item = QTableWidgetItem(path.name)
            name_item.setData(256, str(path))
            name_item.setToolTip(str(path))
            self.file_table.setItem(row, 1, name_item)

            image_cell = QWidget()
            image_layout = QHBoxLayout(image_cell)
            image_layout.setContentsMargins(3, 3, 3, 3)
            thumbnail = ThumbnailLabel(path)
            thumbnail.clicked.connect(self._show_image_preview)
            image_layout.addWidget(thumbnail)
            image_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.file_table.setCellWidget(row, 0, image_cell)

            suffix_edit = QLineEdit()
            suffix_edit.setPlaceholderText("可选，英文数字、空格及 _ - = +，如A001")
            position_combo = QComboBox()
            position_combo.setMaximumWidth(115)
            position_combo.addItem("默认", False)
            position_combo.addItem("背面（BACK_）", True)
            option_combo = FullTextComboBox()
            self._fill_type_option_combo(
                option_combo,
                self.batch_type_option_combo.currentData().value
                if isinstance(self.batch_type_option_combo.currentData(), SelectOption)
                else "",
            )
            quantity_spin = QSpinBox()
            quantity_spin.setRange(1, 999999)
            quantity_spin.setValue(self.batch_quantity_spin.value())
            self.file_table.setCellWidget(row, 2, suffix_edit)
            self.file_table.setCellWidget(row, 3, position_combo)
            self.file_table.setCellWidget(row, 4, option_combo)
            self.file_table.setCellWidget(row, 5, quantity_spin)
            self.file_table.setItem(row, 6, QTableWidgetItem(self._format_size(path.stat().st_size)))
            self.file_table.setItem(row, 7, QTableWidgetItem("待提交"))
            self.file_table.setItem(row, 8, QTableWidgetItem(""))

    def _show_image_preview(self, image_path: Path) -> None:
        ImagePreviewDialog(image_path, self).exec()

    def _remove_files(self) -> None:
        rows = sorted({index.row() for index in self.file_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.file_table.removeRow(row)

    def _image_paths(self) -> list[Path]:
        return [
            Path(self.file_table.item(row, 1).data(256))
            for row in range(self.file_table.rowCount())
        ]

    def _submission_tasks(self) -> list[ImageSubmissionTask]:
        tasks: list[ImageSubmissionTask] = []
        for row in range(self.file_table.rowCount()):
            image_path = Path(self.file_table.item(row, 1).data(256))
            suffix = self.file_table.cellWidget(row, 2)
            position_combo = self.file_table.cellWidget(row, 3)
            option_combo = self.file_table.cellWidget(row, 4)
            quantity_spin = self.file_table.cellWidget(row, 5)
            option = option_combo.currentData() if isinstance(option_combo, QComboBox) else None
            if not isinstance(option, SelectOption):
                raise HiPersonalizationError(f"图片 {image_path.name} 尚未选择 Type Option。")
            quantity = quantity_spin.value() if isinstance(quantity_spin, QSpinBox) else 0
            code_suffix = suffix.text().strip() if isinstance(suffix, QLineEdit) else ""
            try:
                build_product_code("preview", code_suffix)
            except ValueError as exc:
                raise HiPersonalizationError(f"图片 {image_path.name}：{exc}") from exc
            tasks.append(
                ImageSubmissionTask(
                    image_path=image_path,
                    type_option=option,
                    quantity=quantity,
                    code_suffix=code_suffix,
                    is_back=bool(position_combo.currentData())
                    if isinstance(position_combo, QComboBox)
                    else False,
                )
            )
        return tasks

    def _submit_batch(self) -> None:
        definition = self.definition_combo.currentData()
        product_type = self.type_combo.currentData()
        if not self.order_id:
            self._show_worker_error("请先创建订单。")
            return
        if not isinstance(definition, DefinitionOption):
            self._show_worker_error("请选择 Definition。")
            return
        if not isinstance(product_type, SelectOption):
            self._show_worker_error("请选择 Product Type。")
            return
        if not self.file_table.rowCount():
            self._show_worker_error("请至少选择一张图片。")
            return
        try:
            submission_tasks = self._submission_tasks()
        except HiPersonalizationError as exc:
            self._show_worker_error(exc)
            return
        too_large = [
            task.image_path.name
            for task in submission_tasks
            if task.image_path.stat().st_size > HiPersonalizationClient.MAX_IMAGE_BYTES
        ]
        if too_large:
            self._show_worker_error("以下图片超过 80 MB：\n" + "\n".join(too_large))
            return

        answer = QMessageBox.question(
            self,
            "确认批量提交",
            f"Order ID：{self.order_id}\n图片数量：{len(submission_tasks)}\n"
            f"Type Option 种类：{len({task.type_option.value for task in submission_tasks})}\n\n"
            "提交会写入线上订单，是否继续？",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        client = self._require_client()
        order_title = self.order_title_edit.text().strip()
        self.progress_bar.setRange(0, len(submission_tasks))
        self.progress_bar.setValue(0)

        def task(*, progress_callback: Any) -> list[SubmissionResult]:
            results: list[SubmissionResult] = []
            for row_index, submission in enumerate(submission_tasks):
                index = row_index + 1
                image_path = submission.image_path
                code = build_product_code(
                    order_title,
                    submission.code_suffix,
                    is_back=submission.is_back,
                )
                submission_identity = {
                    "type_option": submission.type_option.value,
                    "quantity": submission.quantity,
                    "product_code": code,
                }
                if self.store.was_successful(
                    self.order_id, image_path, **submission_identity
                ):
                    result = SubmissionResult(
                        image_path, True, "相同图片、选项、数量及产品代码已成功提交，本次跳过。"
                    )
                    results.append(result)
                    progress_callback.emit((row_index, "已跳过", result.message, index))
                    continue
                self.store.record(
                    order_id=self.order_id,
                    image_path=image_path,
                    **submission_identity,
                    order_title=order_title,
                    status="running",
                )
                progress_callback.emit((row_index, "提交中", "", index - 1))
                try:
                    context = client.prepare_upload(
                        self.order_id, definition.definition_id, product_type.value
                    )
                    result_url = client.submit_image(
                        context,
                        type_option_value=submission.type_option.value,
                        quantity=submission.quantity,
                        image_path=image_path,
                        product_code=code,
                    )
                    message = f"提交成功：{result_url}"
                    result = SubmissionResult(image_path, True, message)
                    status = "success"
                except Exception as exc:  # Continue remaining images after an individual failure.
                    message = str(exc)
                    result = SubmissionResult(image_path, False, message)
                    status = "failed"
                self.store.record(
                    order_id=self.order_id,
                    image_path=image_path,
                    **submission_identity,
                    order_title=order_title,
                    status=status,
                    message=message,
                )
                results.append(result)
                progress_callback.emit(
                    (row_index, "成功" if result.success else "失败", message, index)
                )
            return results

        def progress(value: tuple[int, str, str, int]) -> None:
            row, status, message, completed = value
            self._set_submission_row_status(row, status, message)
            self.progress_bar.setValue(completed)

        def done(results: list[SubmissionResult]) -> None:
            successes = sum(result.success for result in results)
            failures = len(results) - successes
            self.batch_completed_successfully = failures == 0 and bool(results)
            self._append_log(f"批量提交完成：成功/跳过 {successes}，失败 {failures}。")
            if failures:
                QMessageBox.warning(
                    self,
                    "批量提交完成",
                    f"成功或跳过 {successes} 张，失败 {failures} 张。修正后再次点击提交只会重试失败项。",
                )
            else:
                QMessageBox.information(self, "批量提交完成", f"共处理 {successes} 张图片。")

        self._run("开始批量提交图片……", task, done, progress)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._busy or self._active_workers:
            # Python cannot safely cancel a requests call already running in a worker
            # thread.  Once the user closes the main window, terminate this dedicated
            # desktop process so PyInstaller's parent/child processes cannot remain
            # behind and keep the executable locked.
            self.thread_pool.clear()
            if self.client:
                self.client.session.close()
            event.accept()
            os._exit(0)
            return
        self.thread_pool.clear()
        if not self.thread_pool.waitForDone(5000):
            QMessageBox.warning(self, "暂时无法退出", "后台线程仍未结束，请稍后再次关闭。")
            event.ignore()
            return
        if self.client:
            self.client.session.close()
        event.accept()

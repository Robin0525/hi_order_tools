from __future__ import annotations

import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QTableWidgetItem

import hipersonalization_assistant.gui as gui_module
from hipersonalization_assistant.config import Settings
from hipersonalization_assistant.models import ConfirmableProduct, OrderSummary, SelectOption


root = Path(__file__).resolve().parents[1]
output = root / "output" / "ui-v0.10"
output.mkdir(parents=True, exist_ok=True)
os.environ["LOCALAPPDATA"] = str(output / "app-data")

images: list[str] = []
for name, color in (("front-design.png", "#82b1ff"), ("back-design.png", "#ffab91")):
    path = output / name
    image = QImage(900, 650, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    image.save(str(path))
    images.append(str(path))

app = QApplication.instance() or QApplication([])
window = gui_module.MainWindow(Settings())
window._auto_login_last_account = lambda: None
window.account_combo.setCurrentText("seller-test")
window.login_status_label.setText("已登录：seller-test")
window.order_title_edit.setText("robin test 2027")
window.sku_edit.setText("1234567")
window.order_id_label.setText("Order ID：158727")
window.product_combo.addItem("ID: 5947 | NAME: Example Product | SKU: 1234567")
window.definition_combo.addItem("ID: 82 | NAME: Standard Definition | SKU: 1234567")
window.type_combo.addItem("ID: 16 | NAME: Custom")
window.type_options_status_label.setText("已读取 3 个 Type Options")
options = [
    SelectOption("front", "Front / Main printing position — full production option name"),
    SelectOption("back", "Back / Reverse printing position — full production option name"),
    SelectOption("sleeve", "Left sleeve / Special placement — another very long option name"),
]
window.available_type_options = options
for option in options:
    window.batch_type_option_combo.addItem(option.label, option)

original_picker = gui_module.QFileDialog.getOpenFileNames
gui_module.QFileDialog.getOpenFileNames = lambda *args, **kwargs: (images, "Images")
try:
    window._add_files()
finally:
    gui_module.QFileDialog.getOpenFileNames = original_picker

window.file_table.cellWidget(1, 3).setCurrentIndex(1)
window.file_table.cellWidget(1, 4).setCurrentIndex(1)
window.file_table.cellWidget(1, 5).setValue(2)
window.show()
app.processEvents()
window.grab().save(str(output / "window.png"))
window.workflow_tabs.setCurrentIndex(1)
order = OrderSummary(
    "158860",
    "robin test script 01",
    "processing",
    "https://example/products",
    "https://example/front-design.png",
)
window.confirmation_orders = [order]
window.confirmation_order_thumbnails = {"158860": Path(images[0]).read_bytes()}
window._filter_confirmation_orders("")
window.confirmation_order_status_label.setText(
    "Order 158860：共 3 个设计，待确认 3 个，订单状态 processing"
)
products = [
    ConfirmableProduct("215895", "BACK_robin test script 01_123", "image_created", "LIU_BNNR_STD_1", "6", "https://example/1", "https://example/1_small.png", "https://example/1.png"),
    ConfirmableProduct("215896", "robin test script 01_456", "image_created", "LIU_BNNR_DC_1", "3", "https://example/2", "https://example/2_small.png", "https://example/2.png"),
    ConfirmableProduct("215899", "BACK_robin test script 01_333", "image_created", "W_TAG_RA_2x3.5_FULL_A4_SHEET_10", "6", "https://example/3", "https://example/3_small.png", "https://example/3.png"),
]
window.confirmation_products = products
for row, product in enumerate(products):
    window.confirmation_product_table.insertRow(row)
    window.confirmation_product_table.setRowHeight(row, 64)
    thumbnail_data = Path(images[row % len(images)]).read_bytes()
    window.confirmation_product_table.setCellWidget(
        row,
        0,
        gui_module.RemoteThumbnailLabel(thumbnail_data, product.title, product.preview_url),
    )
    for column, value in enumerate((product.product_id, product.title, product.status, product.type_option, product.quantity, "待确认")):
        window.confirmation_product_table.setItem(row, column + 1, QTableWidgetItem(value))
for value in ("letter", "package", "priority"):
    window.confirmation_stamp_type_combo.addItem(value, SelectOption(value, value))
window.shipping_stamp_edit.setText("C:/Orders/158860-shipping-stamp.pdf")
window.gift_message_edit.setText("C:/Orders/158860-gift-message.pdf")
app.processEvents()
window.grab().save(str(output / "confirmation.png"))
window.close()
app.processEvents()

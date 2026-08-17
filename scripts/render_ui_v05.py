from __future__ import annotations

import os
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QTableWidgetItem

import hipersonalization_assistant.gui as gui_module
from hipersonalization_assistant.config import Settings
from hipersonalization_assistant.models import (
    ConfirmableProduct,
    OrderSummary,
    SellerShop,
    SelectOption,
    ShopProduct,
)


root = Path(__file__).resolve().parents[1]
output = root / "output" / "ui-v0.14"
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
window._set_submission_row_status(0, "成功", "提交成功：示例")
window.show()
window.resize(1600, 900)
app.processEvents()
window.grab().save(str(output / "window.png"))
window.workflow_tabs.setCurrentWidget(window.sku_query_tab)
shop = SellerShop("653", "Robin Shop", "https://example/products")
window.seller_shop_combo.addItem(shop.label, shop)
window.shop_products = [
    ShopProduct("Product One", "132183"),
    ShopProduct("Product Two", "132229"),
]
window._filter_shop_products("")
window.sku_query_status_label.setText("Shop 653：读取到 2 个 Products")
app.processEvents()
window.grab().save(str(output / "sku-query.png"))
window.workflow_tabs.setCurrentWidget(window.confirmation_tab)
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
    ConfirmableProduct("215895", "BACK_robin test script 01_123", "image_created", "LIU_BNNR_STD_1", "6", "https://example/1", "https://example/1_small.png", "https://example/1.png", "https://example/delete/1", "https://example/recustom/1"),
    ConfirmableProduct("215896", "robin test script 01_456", "image_created", "LIU_BNNR_DC_1", "3", "https://example/2", "https://example/2_small.png", "https://example/2.png", "https://example/delete/2", "https://example/recustom/2"),
    ConfirmableProduct("215899", "BACK_robin test script 01_333", "image_created", "W_TAG_RA_2x3.5_FULL_A4_SHEET_10", "6", "https://example/3", "https://example/3_small.png", "https://example/3.png", "https://example/delete/3", "https://example/recustom/3"),
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
    for column, value in enumerate((product.product_id, product.title, product.status, product.type_option, product.quantity)):
        window.confirmation_product_table.setItem(row, column + 1, QTableWidgetItem(value))
    window.confirmation_product_table.setCellWidget(row, 6, gui_module.QPushButton("Delete"))
    window.confirmation_product_table.setCellWidget(row, 7, gui_module.QPushButton("Recustom"))
    result_item = QTableWidgetItem("已确认" if row == 0 else "待确认")
    if row == 0:
        gui_module.MainWindow._set_success_item_style(result_item)
    window.confirmation_product_table.setItem(row, 8, result_item)
for value in ("letter", "package", "priority"):
    window.confirmation_stamp_type_combo.addItem(value, SelectOption(value, value))
window.shipping_stamp_edit.setText("C:/Orders/158860-shipping-stamp.pdf")
window.gift_message_edit.setText("C:/Orders/158860-gift-message.pdf")
app.processEvents()
window.grab().save(str(output / "confirmation.png"))
window.workflow_tabs.setCurrentWidget(window.recustom_tab)
window.recustom_product_id_edit.setText("220486")
window.recustom_code_edit.setText("robin test22222")
window.recustom_type_option_combo.addItems(["Option A", "Option B"])
window.recustom_image_edit.setText("C:/Orders/new-design.png")
window.recustom_status_label.setText("Product 220486 配置读取成功")
app.processEvents()
window.grab().save(str(output / "recustom.png"))
window.workflow_tabs.setCurrentWidget(window.stamp_replacement_tab)
window.stamp_order_id_edit.setText("162372")
window.replacement_stamp_edit.setText("C:/Orders/stamp.pdf")
window.replacement_stamp_type_combo.addItems(["letter", "package", "priority"])
window.replacement_gift_edit.setText("C:/Orders/gift.pdf")
window.stamp_replacement_status_label.setText("Order 162372 配置读取成功")
app.processEvents()
window.grab().save(str(output / "stamp-replacement.png"))
window.close()
app.processEvents()

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit, QSpinBox

import hipersonalization_assistant.gui as gui_module
from hipersonalization_assistant.config import Settings
from hipersonalization_assistant.models import (
    ConfirmationContext,
    ConfirmableProduct,
    DefinitionOption,
    OrderSummary,
    ProductOption,
    SelectOption,
    UploadContext,
    build_product_code,
)


def test_product_code_defaults_to_order_title_and_appends_suffix():
    assert build_product_code("Order 100") == "Order 100"
    assert build_product_code(" robin test 2027 ") == "robin test 2027"
    assert build_product_code("Order 100", "A001") == "Order 100_A001"
    assert build_product_code("Order 100", "A 001-1_+=") == "Order 100_A 001-1_+="
    assert build_product_code(" robin test2026 ", is_back=True) == "BACK_robin test2026"
    assert build_product_code("robin test2026", "B002", is_back=True) == (
        "BACK_robin test2026_B002"
    )
    with pytest.raises(ValueError, match="英文、数字"):
        build_product_code("Order 100", "正面-1")


def test_each_image_can_have_independent_option_quantity_and_suffix(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    first = tmp_path / "front.png"
    second = tmp_path / "back.png"
    first.write_bytes(b"front")
    second.write_bytes(b"back")
    monkeypatch.setattr(
        gui_module.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(first), str(second)], "Images"),
    )

    window = gui_module.MainWindow(Settings())
    options = [SelectOption("front", "Front"), SelectOption("back", "Back")]
    window.available_type_options = options
    for option in options:
        window.batch_type_option_combo.addItem(option.label, option)
    window._add_files()

    first_option = window.file_table.cellWidget(0, 4)
    second_option = window.file_table.cellWidget(1, 4)
    first_quantity = window.file_table.cellWidget(0, 5)
    second_quantity = window.file_table.cellWidget(1, 5)
    first_suffix = window.file_table.cellWidget(0, 2)
    second_suffix = window.file_table.cellWidget(1, 2)
    assert isinstance(first_option, QComboBox)
    assert isinstance(second_option, QComboBox)
    assert isinstance(first_quantity, QSpinBox)
    assert isinstance(second_quantity, QSpinBox)
    assert isinstance(first_suffix, QLineEdit)
    assert isinstance(second_suffix, QLineEdit)

    second_option.setCurrentIndex(1)
    first_quantity.setValue(2)
    second_quantity.setValue(5)
    first_suffix.setText("A001")
    second_suffix.setText("B002")
    second_position = window.file_table.cellWidget(1, 3)
    assert isinstance(second_position, QComboBox)
    second_position.setCurrentIndex(1)
    tasks = window._submission_tasks()

    assert [
        (task.type_option.value, task.quantity, task.code_suffix, task.is_back) for task in tasks
    ] == [
        ("front", 2, "A001", False),
        ("back", 5, "B002", True),
    ]
    window.close()
    application.processEvents()


def test_same_image_can_be_added_more_than_once(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    image = tmp_path / "same.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        gui_module.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(image)], "Images"),
    )
    window = gui_module.MainWindow(Settings())

    window._add_files()
    window._add_files()

    assert window.file_table.rowCount() == 2
    assert window.file_table.item(0, 1).data(256) == window.file_table.item(1, 1).data(256)
    window.close()
    application.processEvents()


def test_successful_submission_row_is_green_and_configuration_is_locked(
    tmp_path: Path, monkeypatch
):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    image = tmp_path / "success.png"
    image.write_bytes(b"image")
    monkeypatch.setattr(
        gui_module.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: ([str(image)], "Images"),
    )
    window = gui_module.MainWindow(Settings())
    window.available_type_options = [SelectOption("001", "Option 001")]
    window._add_files()

    window._set_submission_row_status(0, "成功", "提交成功")

    assert window.file_table.item(0, 7).text() == "成功"
    assert window.file_table.item(0, 7).background().color().name() == "#c6efce"
    assert all(
        not window.file_table.cellWidget(0, column).isEnabled()
        for column in range(2, 6)
    )
    window.close()
    application.processEvents()


def test_apply_defaults_updates_all_image_rows(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    images = []
    for name in ("one.png", "two.png"):
        path = tmp_path / name
        path.write_bytes(b"image")
        images.append(str(path))
    monkeypatch.setattr(
        gui_module.QFileDialog,
        "getOpenFileNames",
        lambda *args, **kwargs: (images, "Images"),
    )

    window = gui_module.MainWindow(Settings())
    options = [SelectOption("a", "Option A"), SelectOption("b", "Option B")]
    window.available_type_options = options
    for option in options:
        window.batch_type_option_combo.addItem(option.label, option)
    window._add_files()
    window.batch_type_option_combo.setCurrentIndex(1)
    window.batch_quantity_spin.setValue(12)
    window._apply_defaults_to_all()

    tasks = window._submission_tasks()
    assert [(task.type_option.value, task.quantity) for task in tasks] == [("b", 12), ("b", 12)]
    window.close()
    application.processEvents()


def test_product_type_selection_automatically_loads_type_options(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")

    class FakeClient:
        logged_in = True

        def fetch_types(self, order_id, definition_id):
            return [SelectOption("custom", "Custom")]

        def prepare_upload(self, order_id, definition_id, type_value):
            return UploadContext(
                "https://example/upload",
                (("state", "token"),),
                (SelectOption("front", "Front"), SelectOption("back", "Back")),
            )

    window = gui_module.MainWindow(Settings())
    window.account_combo.setCurrentText("seller-one")
    window.logged_in_username = "seller-one"
    window.client = FakeClient()
    window.order_id = "162372"
    window.definition_combo.blockSignals(True)
    window.definition_combo.addItem("Definition", DefinitionOption("10", "Definition"))
    window.definition_combo.blockSignals(False)

    def run_now(label, function, on_result, on_progress=None, **kwargs):
        on_result(function(progress_callback=None))

    monkeypatch.setattr(window, "_run", run_now)
    window._load_types()
    application.processEvents()

    assert [
        window.batch_type_option_combo.itemData(index).value
        for index in range(window.batch_type_option_combo.count())
    ] == ["front", "back"]
    window.client = None
    window.close()
    application.processEvents()


def test_continue_sku_button_requires_successful_batch_and_preserves_order(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    window = gui_module.MainWindow(Settings())
    window.account_combo.setCurrentText("seller-one")
    window.logged_in_username = "seller-one"
    window.client = type("LoggedInClient", (), {"logged_in": True})()
    window.order_id = "12345"
    window.created_order_title = "Order A"

    window.batch_completed_successfully = False
    window._set_workflow_enabled(True)
    assert not window.continue_sku_button.isEnabled()

    window.batch_completed_successfully = True
    window._set_workflow_enabled(True)
    assert window.continue_sku_button.isEnabled()
    window._reset_sku_state()
    assert window.order_id == "12345"
    assert window.created_order_title == "Order A"
    assert not window.batch_completed_successfully

    window.order_title_edit.setText("Order A")
    window.order_title_edit.setReadOnly(True)
    window.sku_edit.setText("123456")
    window._start_new_order()
    assert window.order_id == ""
    assert not window.order_title_edit.isReadOnly()
    assert window.order_title_edit.text() == ""
    assert window.sku_edit.text() == ""

    window.client = None
    window.close()
    application.processEvents()


def test_close_while_worker_is_busy_forces_process_exit(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    exit_codes: list[int] = []
    monkeypatch.setattr(gui_module.os, "_exit", exit_codes.append)

    window = gui_module.MainWindow(Settings())
    window._busy = True
    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted()
    assert exit_codes == [0]
    window._busy = False
    window.close()
    application.processEvents()


def test_workflow_tabs_and_configuration_layout(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    window = gui_module.MainWindow(Settings())

    assert window.windowTitle() == "hipersonalization订单处理助手 v0.14 by Robin+Codex"
    assert window.account_combo.minimumWidth() == window.password_edit.minimumWidth()
    assert not window.windowIcon().isNull()
    assert window.workflow_tabs.count() == 5
    assert window.workflow_tabs.tabText(0) == "订单提交"
    assert window.workflow_tabs.tabText(1) == "订单确认"
    assert window.workflow_tabs.tabText(2) == "替换设计"
    assert window.workflow_tabs.tabText(3) == "替补邮票"
    assert window.workflow_tabs.tabText(4) == "SKU 查询"
    shop_header = window.shop_products_table.horizontalHeader()
    assert shop_header.sectionResizeMode(1) == gui_module.QHeaderView.ResizeMode.Stretch
    assert shop_header.sectionResizeMode(2) == gui_module.QHeaderView.ResizeMode.Stretch
    for label in (
        window.recustom_instructions_label,
        window.stamp_replacement_instructions_label,
    ):
        assert label.text().startswith("功能说明：\n")
        assert not label.font().bold()
        assert label.font().pointSize() == window.font().pointSize()
        assert "background-color: #FCE4EC" in label.styleSheet()
    assert window.recustom_instructions_label.text().splitlines() == [
        "功能说明：",
        "1.用于替换订单内product的设计，注意是填写Product ID。",
        "2.已confirm且未生产的订单亦可以替换（需和生产人员沟通清楚）。",
        "3.注意！已生产的订单请勿修改设计图。",
    ]
    assert window.stamp_replacement_instructions_label.text().splitlines() == [
        "功能说明：",
        "1.只用于已confirm的订单，可替换订单的邮票（需和生产人员沟通清楚）。",
    ]

    for control in (
        window.order_title_edit,
        window.sku_edit,
        window.existing_order_id_edit,
        window.existing_sku_edit,
        window.batch_type_option_combo,
        window.batch_quantity_spin,
    ):
        field_layout = control.parentWidget().layout()
        assert field_layout.indexOf(control) == 1
        assert field_layout.itemAt(0).widget() is not None

    choices_layout = window.load_definitions_button.parentWidget().layout()
    for control in (window.product_combo, window.definition_combo, window.type_combo):
        assert choices_layout.getItemPosition(choices_layout.indexOf(control))[1] == 1
    for button in (
        window.load_definitions_button,
        window.load_types_button,
        window.load_options_button,
    ):
        assert choices_layout.getItemPosition(choices_layout.indexOf(button))[1] == 2
        assert button.width() == 150

    window.resize(1920, 820)
    window.show()
    application.processEvents()
    for control in (
        window.order_title_edit,
        window.sku_edit,
        window.existing_order_id_edit,
        window.existing_sku_edit,
        window.batch_type_option_combo,
        window.batch_quantity_spin,
    ):
        field_layout = control.parentWidget().layout()
        label = field_layout.itemAt(0).widget()
        assert label is not None
        assert control.geometry().left() - label.geometry().right() <= 7
    assert window.batch_toolbar_layout.indexOf(window.add_files_button) < (
        window.batch_toolbar_layout.indexOf(window.batch_type_option_combo.parentWidget())
    )
    assert window.batch_type_option_combo.parentWidget().layout().indexOf(
        window.batch_type_option_combo
    ) == 1
    assert window.batch_quantity_spin.parentWidget().layout().indexOf(
        window.batch_quantity_spin
    ) == 1

    window.close()
    application.processEvents()


def test_confirmation_controls_distinguish_first_run_and_retry(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    window = gui_module.MainWindow(Settings())
    window.account_combo.setCurrentText("seller-one")
    window.logged_in_username = "seller-one"
    window.client = type("LoggedInClient", (), {"logged_in": True})()
    window.confirmation_products = [
        ConfirmableProduct("1", "Front", "image_created", "FRONT", "1", "https://example/confirm")
    ]

    window.confirmation_requires_stamp = True
    window._set_workflow_enabled(True)
    assert window.confirm_order_button.isEnabled()
    assert window.shipping_stamp_button.isEnabled()
    assert window.confirmation_stamp_type_combo.isEnabled()

    window.confirmation_requires_stamp = False
    window._set_workflow_enabled(True)
    assert window.confirm_order_button.isEnabled()
    assert not window.shipping_stamp_button.isEnabled()
    assert not window.gift_message_button.isEnabled()

    window.client = None
    window.close()
    application.processEvents()


def test_loading_confirmed_products_shows_stamp_and_keeps_recustom_enabled(
    tmp_path: Path, monkeypatch
):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    stamp_url = "https://hipersonalization.com/uploads/shipping-label.pdf"

    class FakeClient:
        logged_in = True

        def fetch_order_products_page(self, order):
            return (
                [
                    ConfirmableProduct(
                        "220486",
                        "Front",
                        "image_confirmed",
                        "FRONT",
                        "1",
                        recustom_url=(
                            "https://hipersonalization.com/recustom-order-generate-image/"
                            "?image_order_product_id=220486"
                        ),
                    )
                ],
                stamp_url,
            )

    window = gui_module.MainWindow(Settings())
    window.account_combo.setCurrentText("seller-one")
    window.logged_in_username = "seller-one"
    window.client = FakeClient()
    order = OrderSummary("162372", "Order A", "all_confirmed", "https://example/products")
    window.confirmation_order_combo.addItem(order.label, order)

    def run_now(label, function, on_result, on_progress=None, **kwargs):
        on_result(function(progress_callback=None))

    monkeypatch.setattr(window, "_run", run_now)
    window._load_confirmation_products()

    assert stamp_url in window.confirmation_shipping_stamp_label.toolTip()
    assert "打开 PDF" in window.confirmation_shipping_stamp_label.text()
    recustom_button = window.confirmation_product_table.cellWidget(0, 7)
    assert recustom_button.isEnabled()
    result_item = window.confirmation_product_table.item(0, 8)
    assert result_item.text() == "已确认"
    assert result_item.background().color().name() == "#c6efce"

    window.client = None
    window.close()
    application.processEvents()


def test_confirmation_batch_uploads_stamp_only_to_first_design(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    monkeypatch.setattr(
        gui_module.QMessageBox,
        "question",
        lambda *args, **kwargs: gui_module.QMessageBox.StandardButton.Yes,
    )
    monkeypatch.setattr(gui_module.QMessageBox, "information", lambda *args, **kwargs: None)
    shipping = tmp_path / "shipping.pdf"
    gift = tmp_path / "gift.pdf"
    shipping.write_bytes(b"%PDF-1.4 shipping")
    gift.write_bytes(b"%PDF-1.4 gift")
    calls = []

    class FakeClient:
        logged_in = True

        def prepare_confirmation(self, product):
            return ConfirmationContext(
                product.confirm_url,
                (("input_1", "image_confirmed"),),
                (SelectOption("letter", "letter"),),
            )

        def submit_confirmation(self, context, **kwargs):
            calls.append(kwargs)
            return context.url

        def fetch_order_status(self, order_id):
            return "all_confirmed"

    class Progress:
        def __init__(self, callback):
            self.callback = callback

        def emit(self, value):
            self.callback(value)

    window = gui_module.MainWindow(Settings())
    window.account_combo.setCurrentText("seller-one")
    window.logged_in_username = "seller-one"
    window.client = FakeClient()
    order = OrderSummary("100", "Order A", "processing", "https://example/products")
    window.confirmation_order_combo.addItem(order.label, order)
    window.confirmation_products = [
        ConfirmableProduct("1", "Front", "image_created", "FRONT", "1", "https://example/1"),
        ConfirmableProduct("2", "Back", "image_created", "BACK", "1", "https://example/2"),
    ]
    for row, product in enumerate(window.confirmation_products):
        window.confirmation_product_table.insertRow(row)
        for column, value in enumerate(
            (
                product.product_id,
                product.title,
                product.status,
                product.type_option,
                product.quantity,
            )
        ):
            window.confirmation_product_table.setItem(
                row, column + 1, gui_module.QTableWidgetItem(value)
            )
        window.confirmation_product_table.setItem(
            row, 8, gui_module.QTableWidgetItem("待确认")
        )
    window.confirmation_stamp_type_combo.addItem("letter", SelectOption("letter", "letter"))
    window.shipping_stamp_edit.setText(str(shipping))
    window.gift_message_edit.setText(str(gift))

    def run_now(label, function, on_result, on_progress=None, **kwargs):
        on_result(function(progress_callback=Progress(on_progress)))

    monkeypatch.setattr(window, "_run", run_now)
    window._confirm_selected_order()

    assert calls[0]["shipping_stamp"] == shipping
    assert calls[0]["stamp_type"] == "letter"
    assert calls[0]["gift_message"] == gift
    assert calls[1]["shipping_stamp"] is None
    assert calls[1]["stamp_type"] == ""
    assert calls[1]["gift_message"] is None
    assert all(not product.confirm_url for product in window.confirmation_products)
    assert window.confirmation_order_combo.currentData().status == "all_confirmed"
    assert all(
        window.confirmation_product_table.item(row, 3).text() == "image_confirmed"
        for row in range(window.confirmation_product_table.rowCount())
    )
    assert all(
        window.confirmation_product_table.item(row, 8).text() == "已确认"
        and window.confirmation_product_table.item(row, 8).background().color().name()
        == "#c6efce"
        for row in range(window.confirmation_product_table.rowCount())
    )

    window.client = None
    window.close()
    application.processEvents()


def test_selecting_saved_account_starts_automatic_login(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    window = gui_module.MainWindow(Settings())
    window.account_combo.clear()
    window.account_combo.addItem("saved-seller")
    monkeypatch.setattr(window.account_store, "accounts", lambda: ["saved-seller"])
    monkeypatch.setattr(window.account_store, "password", lambda username: "saved-password")
    calls = []
    monkeypatch.setattr(
        window,
        "_start_login",
        lambda username, password, *, automatic: calls.append((username, password, automatic)),
    )

    window._saved_account_activated(0)

    assert calls == [("saved-seller", "saved-password", True)]
    window.close()
    application.processEvents()


def test_existing_and_primary_sku_fields_stay_synchronized(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    window = gui_module.MainWindow(Settings())

    window.sku_edit.setText("1234567")
    assert window.existing_sku_edit.text() == "1234567"
    window.existing_sku_edit.setText("7654321")
    assert window.sku_edit.text() == "7654321"

    window.close()
    application.processEvents()


def test_confirmation_order_combo_shows_thumbnail_and_no_design_label(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")
    window = gui_module.MainWindow(Settings())
    with_image = OrderSummary("1", "With image", "processing", "https://example/1", "https://example/1.png")
    without_image = OrderSummary("2", "No image", "created", "https://example/2")
    window.confirmation_orders = [with_image, without_image]
    logo = Path(__file__).resolve().parents[1] / "assets" / "shopkeeper-logo.png"
    window.confirmation_order_thumbnails = {"1": logo.read_bytes()}

    window._filter_confirmation_orders("")

    assert not window.confirmation_order_combo.itemIcon(0).isNull()
    assert window.confirmation_order_combo.itemText(1).startswith("[无设计图]")
    window.close()
    application.processEvents()


def test_load_existing_order_uses_id_and_existing_title(tmp_path: Path, monkeypatch):
    application = QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui_module, "app_data_dir", lambda: tmp_path / "app-data")

    class FakeClient:
        logged_in = True

        def fetch_order(self, order_id, *, allow_confirmed):
            assert order_id == "158860"
            assert not allow_confirmed
            return OrderSummary("158860", "Existing Order", "processing", "https://example/products")

        def search_products(self, order_id, sku):
            assert (order_id, sku) == ("158860", "1234567")
            return [ProductOption("1", "Product 1"), ProductOption("2", "Product 2")]

    class Progress:
        def emit(self, value):
            pass

    window = gui_module.MainWindow(Settings())
    window.account_combo.setCurrentText("seller-one")
    window.logged_in_username = "seller-one"
    window.client = FakeClient()
    window.existing_order_id_edit.setText("158860")
    window.sku_edit.setText("1234567")

    def run_now(label, function, on_result, **kwargs):
        on_result(function(progress_callback=Progress()))

    monkeypatch.setattr(window, "_run", run_now)
    window._load_existing_order()

    assert window.order_id == "158860"
    assert window.created_order_title == "Existing Order"
    assert window.order_title_edit.text() == "Existing Order"
    assert window.order_title_edit.isReadOnly()
    assert window.product_combo.count() == 2
    assert "已载入" in window.order_id_label.text()

    window.client = None
    window.close()
    application.processEvents()

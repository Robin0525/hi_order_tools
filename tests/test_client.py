from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from hipersonalization_assistant.client import HiPersonalizationClient, HiPersonalizationError
from hipersonalization_assistant.models import (
    ConfirmationContext,
    ConfirmableProduct,
    OrderSummary,
    RecustomContext,
    SellerShop,
    SelectOption,
    StampReplacementContext,
)


class FakeResponse:
    def __init__(self, text: str, url: str = "https://hipersonalization.com/page"):
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.status_code = 200

    def raise_for_status(self):
        return None


def test_order_rows_extract_order_id_and_row_text():
    html = """
    <table><tr><td>123</td><td>My Batch</td><td>
      <a href="/list-order-products-by-order-id/?order_id=123">products</a>
    </td></tr></table>
    """
    assert HiPersonalizationClient._order_rows(html) == [("123", "123 My Batch products")]


def test_find_orders_url_uses_home_page_link():
    html = """
    <nav>
      <a href="/search-my-order">search my orders</a>
      <a href="/list-my-image-orders/?product_seller=224">list-my-orders</a>
    </nav>
    """
    assert HiPersonalizationClient._find_orders_url(html, "https://hipersonalization.com/") == (
        "https://hipersonalization.com/list-my-image-orders/?product_seller=224"
    )


def test_product_and_definition_labels_only_keep_id_name_and_sku():
    soup = BeautifulSoup(
        """
        <table>
          <tr><th>ID</th><th>SHOP</th><th>NAME</th><th>INDEX</th><th>SKU</th><th>OWNER</th></tr>
          <tr><td>5947</td><td>Shop A</td><td>Magnet</td><td>7</td><td>ABC123</td><td>Owner</td></tr>
        </table>
        """,
        "html.parser",
    )
    label = HiPersonalizationClient._summarize_row(soup.find_all("tr")[1])
    assert label == "ID: 5947 | NAME: Magnet | SKU: ABC123"
    assert "SHOP" not in label
    assert "OWNER" not in label


def test_replace_fields_preserves_duplicate_unrelated_fields():
    fields = (("MAX_FILE_SIZE", "1"), ("input_3", "old"), ("MAX_FILE_SIZE", "2"))
    result = HiPersonalizationClient._replace_fields(fields, {"input_3": "new"})
    assert result == [("MAX_FILE_SIZE", "1"), ("MAX_FILE_SIZE", "2"), ("input_3", "new")]


def test_submit_image_rejects_oversized_file(tmp_path: Path):
    path = tmp_path / "big.png"
    path.write_bytes(b"x")
    client = HiPersonalizationClient()
    client.MAX_IMAGE_BYTES = 0

    with pytest.raises(HiPersonalizationError, match="80 MB"):
        client.submit_image(
            context=None,  # type: ignore[arg-type]
            type_option_value="1",
            quantity=1,
            image_path=path,
            product_code="code",
        )


def test_fetch_orders_and_order_products_parse_confirmation_state(monkeypatch):
    orders_html = """
    <table>
      <tr><th>ID</th><th>TITLE</th><th>STATUS</th><th>FUNCTIONS</th></tr>
      <tr><td>158860</td><td>Order A</td><td>processing</td><td>
        <a href="/list-order-products-by-order-id/?order_id=158860">products</a>
      </td></tr>
    </table>
    """
    products_html = """
    <table>
      <tr><th>ID</th><th>TITLE</th><th>IMAGE</th><th>STATUS</th><th>option</th><th>qty</th><th>FUNCTIONS</th></tr>
      <tr><td>215895</td><td>Front</td><td><img src="/uploads/215895_small.png"></td><td>image_created</td><td>FRONT</td><td>2</td><td>
        <a href="/confirm-image-order-product-image/?image_order_product_id=215895">confirm</a>
      </td></tr>
      <tr><td>215896</td><td>Back</td><td></td><td>image_confirmed</td><td>BACK</td><td>2</td><td>view</td></tr>
    </table>
    """
    client = HiPersonalizationClient()
    client.orders_page_url = "https://hipersonalization.com/list-my-image-orders/?product_seller=224"

    def fake_get(url: str, **_kwargs):
        return FakeResponse(
            products_html if "list-order-products-by-order-id" in url else orders_html,
            url,
        )

    monkeypatch.setattr(client, "_get", fake_get)
    orders = client.fetch_orders()
    assert orders == [
        OrderSummary(
            "158860",
            "Order A",
            "processing",
            "https://hipersonalization.com/list-order-products-by-order-id/?order_id=158860",
        )
    ]
    products = client.fetch_order_products(orders[0])
    assert [(p.product_id, p.status, p.type_option, p.quantity, bool(p.confirm_url)) for p in products] == [
        ("215895", "image_created", "FRONT", "2", True),
        ("215896", "image_confirmed", "BACK", "2", False),
    ]
    assert products[0].image_url == "https://hipersonalization.com/uploads/215895_small.png"
    assert products[1].recustom_url.endswith(
        "/recustom-order-generate-image/?image_order_product_id=215896"
    )
    assert products[0].preview_url == "https://hipersonalization.com/uploads/215895.png"


def test_prepare_confirmation_reads_stamp_types(monkeypatch):
    html = """
    <form id="gform_47" action="/confirm-image-order-product-image/">
      <select name="input_1"><option value="image_confirmed" selected>image_confirmed</option></select>
      <input type="file" name="input_4">
      <select name="input_5"><option value="">select</option><option value="letter">letter</option><option value="package">package</option></select>
      <input type="file" name="input_6">
      <input type="hidden" name="state_47" value="token">
    </form>
    """
    client = HiPersonalizationClient()
    monkeypatch.setattr(client, "_get", lambda url, **_kwargs: FakeResponse(html, url))
    product = ConfirmableProduct("1", "Front", "image_created", "FRONT", "1", "https://hipersonalization.com/confirm")

    context = client.prepare_confirmation(product)

    assert [(option.value, option.label) for option in context.stamp_types] == [
        ("letter", "letter"),
        ("package", "package"),
    ]
    assert ("state_47", "token") in context.fields


def test_submit_confirmation_uploads_pdfs_only_when_provided(tmp_path: Path, monkeypatch):
    shipping = tmp_path / "shipping.pdf"
    gift = tmp_path / "gift.pdf"
    shipping.write_bytes(b"%PDF-1.4 shipping")
    gift.write_bytes(b"%PDF-1.4 gift")
    client = HiPersonalizationClient()
    calls = []

    def fake_post(url, *, data, files=None):
        calls.append((data, sorted(files or {})))
        return FakeResponse('<div id="gform_confirmation_message_47">done</div>', url)

    monkeypatch.setattr(client, "_post", fake_post)
    context = ConfirmationContext(
        "https://hipersonalization.com/confirm",
        (("input_1", "image_confirmed"), ("input_5", ""), ("state_47", "token")),
        (SelectOption("letter", "letter"),),
    )

    client.submit_confirmation(
        context,
        shipping_stamp=shipping,
        stamp_type="letter",
        gift_message=gift,
    )
    client.submit_confirmation(context)

    assert calls[0][1] == ["input_4", "input_6"]
    assert ("input_5", "letter") in calls[0][0]
    assert calls[1][1] == []
    assert ("input_5", "") in calls[1][0]


def test_confirmation_rejects_non_pdf(tmp_path: Path):
    invalid = tmp_path / "shipping.pdf"
    invalid.write_bytes(b"not a pdf")
    with pytest.raises(HiPersonalizationError, match="有效的 PDF"):
        HiPersonalizationClient._validate_pdf(invalid, "Shipping Stamp")


def test_fetch_order_rejects_confirmed_order(monkeypatch):
    client = HiPersonalizationClient()
    order = OrderSummary("200", "Finished", "all_confirmed", "https://example/products")
    monkeypatch.setattr(client, "fetch_orders", lambda: [order])

    assert client.fetch_order("200") == order
    with pytest.raises(HiPersonalizationError, match="all_confirmed"):
        client.fetch_order("200", allow_confirmed=False)
    with pytest.raises(HiPersonalizationError, match="没有找到"):
        client.fetch_order("201", allow_confirmed=False)


def test_open_order_by_id_does_not_read_full_order_list():
    client = HiPersonalizationClient()
    client.orders_page_url = "https://hipersonalization.com/list-my-image-orders/?product_seller=224"

    order = client.open_order_by_id(" 123 ")

    assert order.order_id == "123"
    assert order.products_url == "https://hipersonalization.com/list-order-products-by-order-id/?order_id=123"


def test_fetch_orders_reads_image_url(monkeypatch):
    html = """
    <table>
      <tr><th>ID</th><th>TITLE</th><th>IMAGE</th><th>STATUS</th><th>FUNCTIONS</th></tr>
      <tr><td>123</td><td>With image</td><td><img src="/uploads/123_small.png"></td><td>processing</td><td>
        <a href="/list-order-products-by-order-id/?order_id=123">products</a>
      </td></tr>
    </table>
    """
    client = HiPersonalizationClient()
    client.orders_page_url = "https://hipersonalization.com/list-my-image-orders/"
    monkeypatch.setattr(client, "_get", lambda url, **_kwargs: FakeResponse(html, url))

    order = client.fetch_orders()[0]

    assert order.image_url == "https://hipersonalization.com/uploads/123_small.png"


def test_fetch_orders_stops_after_requested_limit(monkeypatch):
    html = """
    <table>
      <tr><th>ID</th><th>TITLE</th><th>STATUS</th><th>FUNCTIONS</th></tr>
      <tr><td>1</td><td>First</td><td>processing</td><td><a href="/list-order-products-by-order-id/?order_id=1">products</a></td></tr>
      <tr><td>2</td><td>Second</td><td>processing</td><td><a href="/list-order-products-by-order-id/?order_id=2">products</a></td></tr>
    </table>
    """
    client = HiPersonalizationClient()
    client.orders_page_url = "https://hipersonalization.com/list-my-image-orders/"
    calls = []

    def fake_get(url, **kwargs):
        calls.append(kwargs)
        return FakeResponse(html, url)

    monkeypatch.setattr(client, "_get", fake_get)

    assert [order.order_id for order in client.fetch_orders(limit=1)] == ["1"]
    assert calls == [{"timeout": 120}]
    with pytest.raises(ValueError, match="大于 0"):
        client.fetch_orders(limit=0)


def test_preview_image_url_removes_small_suffix_only():
    assert HiPersonalizationClient._preview_image_url(
        "https://hipersonalization.com/uploads/123_small.png"
    ) == "https://hipersonalization.com/uploads/123.png"
    assert HiPersonalizationClient._preview_image_url(
        "https://hipersonalization.com/uploads/123.png"
    ) == "https://hipersonalization.com/uploads/123.png"


def test_fetch_order_products_reads_delete_and_recustom_links(monkeypatch):
    html = """
    <table>
      <tr><th>ID</th><th>TITLE</th><th>STATUS</th><th>option</th><th>qty</th><th>FUNCTIONS</th></tr>
      <tr><td>220486</td><td>Front</td><td>image_created</td><td>FRONT</td><td>1</td><td>
        <a href="/confirm-image-order-product-image/?image_order_product_id=220486">confirm</a>
        <a href="/delete-unconfirmed-order-product/?image_order_product_id=220486">delete</a>
        <a href="/recustom-order-generate-image/?image_order_product_id=220486">recustom</a>
      </td></tr>
    </table>
    """
    client = HiPersonalizationClient()
    monkeypatch.setattr(client, "_get", lambda url: FakeResponse(html, url))
    product = client.fetch_order_products(
        OrderSummary("162372", "Test", "processing", "https://hipersonalization.com/products")
    )[0]
    assert "delete-unconfirmed-order-product" in product.delete_url
    assert "recustom-order-generate-image" in product.recustom_url


def test_order_products_page_reads_shipping_stamp_pdf(monkeypatch):
    html = """
    <div>order shipping stamp:
      <a href="/uploads/shipping-label.pdf">shipping-label.pdf</a>
    </div>
    <table><tr><th>ID</th><th>TITLE</th></tr>
      <tr><td>220486</td><td>Front</td></tr>
    </table>
    """
    client = HiPersonalizationClient()
    monkeypatch.setattr(client, "_get", lambda url: FakeResponse(html, url))
    products, stamp_url = client.fetch_order_products_page(
        OrderSummary("162372", "Test", "all_confirmed", "https://hipersonalization.com/products")
    )
    assert products[0].recustom_url.endswith("image_order_product_id=220486")
    assert stamp_url == "https://hipersonalization.com/uploads/shipping-label.pdf"


def test_delete_order_product_rejects_unexpected_url():
    client = HiPersonalizationClient()
    product = ConfirmableProduct(
        "1",
        "Design",
        "image_created",
        "FRONT",
        "1",
        delete_url="https://example.com/delete-unconfirmed-order-product/?id=1",
    )
    with pytest.raises(HiPersonalizationError, match="不属于"):
        client.delete_order_product(product)


def test_delete_order_product_opens_and_submits_confirmation_form(monkeypatch):
    product = ConfirmableProduct(
        "220531",
        "Delete test",
        "image_created",
        "FRONT",
        "1",
        delete_url=(
            "https://hipersonalization.com/delete-unconfirmed-order-product/"
            "?image_order_product_id=220531"
        ),
    )
    page = """
    <form id="gform_104" action="/delete-unconfirmed-order-product/?image_order_product_id=220531">
      <input name="state_104" value="token">
      <input name="gform_submit" value="104">
      <button type="submit" id="gform_submit_button_104">Submit</button>
    </form>
    """
    calls = []
    client = HiPersonalizationClient()
    monkeypatch.setattr(client, "_get", lambda url: FakeResponse(page, url))

    def fake_post(url, *, data, files=None):
        calls.append((url, data, files))
        return FakeResponse('<div id="gform_confirmation_message_104">deleted</div>', url)

    monkeypatch.setattr(client, "_post", fake_post)
    result = client.delete_order_product(product)
    assert result.endswith("image_order_product_id=220531")
    assert calls[0][1] == [("state_104", "token"), ("gform_submit", "104")]


def test_fetch_seller_shops_and_shop_products(monkeypatch):
    shops_html = """
    <table><tr><th>ID</th><th>NAME</th><th>Functions</th></tr>
      <tr><td>653</td><td>Robin Shop</td><td><a href="/list-image-products-by-image-shop-id-for-seller/?image_shop_id=653">products</a></td></tr>
    </table>
    """
    products_html = """
    <table><tr><th>NAME</th><th>IMAGE</th><th>SKU</th></tr>
      <tr><td>Product One</td><td><a href="/uploads/p1.png"><img src="/uploads/p1.png"></a></td><td>132183</td></tr>
    </table>
    """
    client = HiPersonalizationClient()
    client.shops_page_url = "https://hipersonalization.com/list-seller-shop/?shop_seller=224"
    monkeypatch.setattr(
        client,
        "_get",
        lambda url: FakeResponse(products_html if "image_shop_id" in url else shops_html, url),
    )
    shop = client.fetch_seller_shops()[0]
    assert shop == SellerShop(
        "653",
        "Robin Shop",
        "https://hipersonalization.com/list-image-products-by-image-shop-id-for-seller/?image_shop_id=653",
    )
    product = client.fetch_shop_products(shop)[0]
    assert (product.name, product.sku, product.image_url) == (
        "Product One",
        "132183",
        "https://hipersonalization.com/uploads/p1_120.png",
    )


def test_prepare_recustom_and_stamp_replacement_read_live_field_mappings(monkeypatch):
    recustom_html = """
    <form id="gform_48" action="/recustom">
      <input name="input_21" value="Code 1">
      <select name="input_22"><option value="a">A</option><option value="b" selected>B</option></select>
      <select name="input_7"><option value="no_frame" selected>no frame</option></select>
      <textarea name="input_8">preserve me</textarea><input type="file" name="input_9">
    </form>
    """
    stamp_html = """
    <form id="gform_241" action="/stamp">
      <input type="file" name="input_3">
      <select name="input_4"><option value="letter">letter</option><option value="package">package</option></select>
      <input type="file" name="input_5">
    </form>
    """
    client = HiPersonalizationClient()
    monkeypatch.setattr(
        client,
        "_get",
        lambda url: FakeResponse(recustom_html if "recustom" in url else stamp_html, url),
    )
    recustom = client.prepare_recustom("220486")
    assert recustom.product_code == "Code 1"
    assert recustom.selected_type_option == "b"
    assert ("input_8", "preserve me") in recustom.fields
    stamp = client.prepare_stamp_replacement("162372")
    assert [option.value for option in stamp.stamp_types] == ["letter", "package"]


def test_recustom_and_stamp_replacement_submit_expected_fields_and_files(
    tmp_path: Path, monkeypatch
):
    image = tmp_path / "new.png"
    stamp = tmp_path / "stamp.pdf"
    gift = tmp_path / "gift.pdf"
    image.write_bytes(b"image")
    stamp.write_bytes(b"%PDF-1.4 stamp")
    gift.write_bytes(b"%PDF-1.4 gift")
    calls = []
    client = HiPersonalizationClient()

    def fake_post(url, *, data, files=None):
        calls.append((url, data, sorted(files or {})))
        form_id = "48" if "recustom" in url else "241"
        return FakeResponse(
            f'<div id="gform_confirmation_message_{form_id}">done</div>', url
        )

    monkeypatch.setattr(client, "_post", fake_post)
    client.submit_recustom(
        RecustomContext(
            "https://hipersonalization.com/recustom",
            (("input_7", "no_frame"), ("input_8", "preserve")),
            "220486",
            "Old",
            (SelectOption("5502", "Option"),),
            "5502",
        ),
        product_code="New Code",
        type_option_value="5502",
        image_path=image,
    )
    client.submit_stamp_replacement(
        StampReplacementContext(
            "https://hipersonalization.com/stamp",
            (("state", "token"),),
            (SelectOption("letter", "letter"),),
        ),
        stamp=stamp,
        stamp_type="letter",
        gift_message=gift,
    )
    assert ("input_21", "New Code") in calls[0][1]
    assert ("input_22", "5502") in calls[0][1]
    assert calls[0][2] == ["input_9"]
    assert ("input_4", "letter") in calls[1][1]
    assert calls[1][2] == ["input_3", "input_5"]

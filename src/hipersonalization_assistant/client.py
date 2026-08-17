from __future__ import annotations

import mimetypes
from contextlib import ExitStack
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

from .forms import (
    clean_text,
    find_form,
    form_action,
    select_options,
    serialize_form,
    validation_messages,
)
from .models import (
    ConfirmationContext,
    ConfirmableProduct,
    DefinitionOption,
    OrderSummary,
    ProductOption,
    RecustomContext,
    SellerShop,
    SelectOption,
    ShopProduct,
    StampReplacementContext,
    UploadContext,
)


class HiPersonalizationError(RuntimeError):
    pass


class AuthenticationError(HiPersonalizationError):
    pass


class RemoteValidationError(HiPersonalizationError):
    pass


class HiPersonalizationClient:
    MAX_IMAGE_BYTES = 80 * 1024 * 1024
    # 订单列表由网站在服务器端一次性生成。seller 的历史订单很多时，
    # 这个页面比普通页面需要更长的响应时间；不要因此拖慢上传等其他操作。
    ORDER_LIST_TIMEOUT = 120

    def __init__(self, base_url: str = "https://hipersonalization.com", timeout: int = 45):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "HiPersonalization-Assistant/0.1"})
        self.logged_in = False
        self.orders_page_url = ""
        self.shops_page_url = ""
        self._product_seller = ""

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

    def _get(self, url: str, *, timeout: int | None = None) -> requests.Response:
        response = self.session.get(url, timeout=timeout or self.timeout)
        response.raise_for_status()
        self._ensure_authenticated(response)
        return response

    def _post(
        self,
        url: str,
        *,
        data: list[tuple[str, str]],
        files: dict[str, tuple[str, object, str]] | None = None,
    ) -> requests.Response:
        response = self.session.post(
            url,
            data=data,
            files=files,
            timeout=max(self.timeout, 120 if files else self.timeout),
            allow_redirects=True,
        )
        response.raise_for_status()
        self._ensure_authenticated(response)
        return response

    @staticmethod
    def _ensure_authenticated(response: requests.Response) -> None:
        path = urlparse(response.url).path.rstrip("/")
        if path.endswith("wp-login.php"):
            raise AuthenticationError("登录状态失效，请重新登录。")
        if "Sorry, you are not authorized to submit this page!" in response.text:
            raise AuthenticationError("当前 seller 账号没有访问该页面的权限。")

    def login(self, username: str, password: str) -> None:
        if not username or not password:
            raise AuthenticationError("Seller 账号和密码不能为空。")
        login_url = self._url("/wp-login.php")
        self.session.get(login_url, timeout=self.timeout).raise_for_status()
        response = self.session.post(
            login_url,
            data={
                "log": username,
                "pwd": password,
                "wp-submit": "Log In",
                "redirect_to": f"{self.base_url}/",
                "testcookie": "1",
            },
            timeout=self.timeout,
            allow_redirects=True,
        )
        response.raise_for_status()
        if urlparse(response.url).path.rstrip("/").endswith("wp-login.php"):
            raise AuthenticationError("Seller 登录失败，请检查账号和密码。")
        if "id=\"wpadminbar\"" not in response.text and "class=\"logged-in" not in response.text:
            verification = self.session.get(self._url("/wp-admin/profile.php"), timeout=self.timeout)
            if urlparse(verification.url).path.rstrip("/").endswith("wp-login.php"):
                raise AuthenticationError("Seller 登录失败，请检查账号和密码。")
        self.logged_in = True
        home = self._get(self._url("/"))
        self.orders_page_url = self._find_orders_url(home.text, home.url)
        self.shops_page_url = self._find_seller_shops_url(home.text, home.url)
        self._product_seller = parse_qs(urlparse(self.orders_page_url).query).get(
            "product_seller", [""]
        )[0]
        if not self._product_seller:
            self.logged_in = False
            raise AuthenticationError("已登录，但首页 list-my-orders 链接缺少 seller 参数。")

    @staticmethod
    def _find_orders_url(html: str, current_url: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            text = clean_text(link.get_text(" ", strip=True)).casefold()
            if text == "list-my-orders":
                return urljoin(current_url, str(link["href"]))
        raise AuthenticationError("已登录，但首页没有找到 list-my-orders 链接。")

    @staticmethod
    def _find_seller_shops_url(html: str, current_url: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            text = clean_text(link.get_text(" ", strip=True)).casefold()
            target = urljoin(current_url, str(link["href"]))
            if text == "list-my-seller-shops" or "list-seller-shop" in urlparse(target).path:
                return target
        raise AuthenticationError("已登录，但首页没有找到 list-my-seller-shops 链接。")

    @staticmethod
    def _with_query(path: str, **values: str) -> str:
        parsed = urlparse(path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        query.update({key: [value] for key, value in values.items()})
        return urlunparse(
            parsed._replace(query=urlencode([(key, item) for key, items in query.items() for item in items]))
        )

    @staticmethod
    def _order_rows(html: str) -> list[tuple[str, str]]:
        soup = BeautifulSoup(html, "html.parser")
        rows: list[tuple[str, str]] = []
        for link in soup.find_all("a", href=True):
            parsed = urlparse(urljoin("https://placeholder.invalid/", str(link["href"])))
            if "list-order-products-by-order-id" not in parsed.path:
                continue
            order_id = parse_qs(parsed.query).get("order_id", [""])[0]
            row = link.find_parent("tr")
            row_text = clean_text(row.get_text(" ", strip=True)) if row else ""
            if order_id:
                rows.append((order_id, row_text))
        return rows

    @staticmethod
    def _summarize_row(row: object, fields: tuple[str, ...] = ("ID", "NAME", "SKU")) -> str:
        if not hasattr(row, "find_parent"):
            return ""
        table = row.find_parent("table")
        if table is None:
            return ""
        headers = [clean_text(cell.get_text(" ", strip=True)).upper() for cell in table.find_all("th")]
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td", recursive=False)]
        values = dict(zip(headers, cells))
        return " | ".join(f"{field}: {values.get(field, '-') or '-'}" for field in fields)

    def create_order(self, title: str) -> str:
        title = title.strip()
        if not title:
            raise HiPersonalizationError("Order Title 不能为空。")
        if not self.orders_page_url:
            raise AuthenticationError("请先登录 seller 账号。")

        page_url = self.orders_page_url
        before_page = self._get(page_url)
        before_ids = {order_id for order_id, _ in self._order_rows(before_page.text)}
        form = find_form(before_page.text, "gform_40")
        response = self._post(
            form_action(form, before_page.url),
            data=serialize_form(form, {"input_2": title}),
        )
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))

        after_page = self._get(page_url)
        rows = self._order_rows(after_page.text)
        new_rows = [(order_id, text) for order_id, text in rows if order_id not in before_ids]
        exact = [order_id for order_id, text in new_rows if title.casefold() in text.casefold()]
        if exact:
            return exact[0]
        if len(new_rows) == 1:
            return new_rows[0][0]
        raise HiPersonalizationError(
            "订单表单已提交，但无法从列表中唯一确定新 Order ID。请到网站确认后再重试。"
        )

    @staticmethod
    def _table_values(row: object) -> dict[str, str]:
        if not hasattr(row, "find_parent"):
            return {}
        table = row.find_parent("table")
        if table is None:
            return {}
        headers = [clean_text(cell.get_text(" ", strip=True)).upper() for cell in table.find_all("th")]
        cells = [clean_text(cell.get_text(" ", strip=True)) for cell in row.find_all("td", recursive=False)]
        return dict(zip(headers, cells))

    def fetch_orders(self, *, limit: int | None = None) -> list[OrderSummary]:
        if limit is not None and limit <= 0:
            raise ValueError("订单读取数量必须大于 0。")
        if not self.orders_page_url:
            raise AuthenticationError("请先登录 seller 账号。")
        response = self._get(
            self.orders_page_url,
            timeout=max(self.timeout, self.ORDER_LIST_TIMEOUT),
        )
        soup = BeautifulSoup(response.text, "html.parser")
        orders: list[OrderSummary] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            target = urljoin(response.url, str(link["href"]))
            parsed = urlparse(target)
            if "list-order-products-by-order-id" not in parsed.path:
                continue
            order_id = parse_qs(parsed.query).get("order_id", [""])[0]
            if not order_id or order_id in seen:
                continue
            values = self._table_values(link.find_parent("tr"))
            row = link.find_parent("tr")
            image = row.find("img") if row else None
            image_url = (
                urljoin(response.url, str(image.get("src") or "")) if image else ""
            )
            orders.append(
                OrderSummary(
                    order_id=order_id,
                    title=values.get("TITLE", ""),
                    status=values.get("STATUS", ""),
                    products_url=target,
                    image_url=image_url,
                )
            )
            seen.add(order_id)
            if limit is not None and len(orders) >= limit:
                break
        if not orders:
            raise HiPersonalizationError("订单列表中没有找到可读取的 Order。")
        return orders

    def fetch_order(self, order_id: str, *, allow_confirmed: bool = True) -> OrderSummary:
        normalized = order_id.strip()
        if not normalized or not normalized.isdigit():
            raise HiPersonalizationError("Order ID 必须是数字。")
        order = next((item for item in self.fetch_orders() if item.order_id == normalized), None)
        if order is None:
            raise HiPersonalizationError(
                f"当前 seller 的订单列表中没有找到 Order {normalized}。"
            )
        if not allow_confirmed and order.status.casefold() == "all_confirmed":
            raise HiPersonalizationError(
                f"Order {normalized} 已是 all_confirmed，不能继续增加设计。"
            )
        return order

    def open_order_by_id(self, order_id: str) -> OrderSummary:
        """Open one known order without first downloading the seller's full order list."""
        normalized = order_id.strip()
        if not normalized or not normalized.isdigit():
            raise HiPersonalizationError("Order ID 必须是数字。")
        if not self.orders_page_url:
            raise AuthenticationError("请先登录 seller 账号。")
        return OrderSummary(
            order_id=normalized,
            title="",
            status="",
            products_url=self._url(
                f"/list-order-products-by-order-id/?order_id={normalized}"
            ),
        )

    def fetch_thumbnail_bytes(self, image_url: str) -> bytes:
        return self.fetch_image_bytes(image_url, max_bytes=5 * 1024 * 1024)

    def fetch_image_bytes(self, image_url: str, *, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
        if not image_url:
            return b""
        if urlparse(image_url).netloc.casefold() != urlparse(self.base_url).netloc.casefold():
            raise HiPersonalizationError("Order 缩略图地址不属于 HiPersonalization 网站。")
        response = self.session.get(image_url, timeout=self.timeout)
        response.raise_for_status()
        self._ensure_authenticated(response)
        content_type = response.headers.get("Content-Type", "").casefold()
        if content_type and not content_type.startswith("image/"):
            raise HiPersonalizationError("Order 缩略图返回了非图片内容。")
        content = response.content
        if len(content) > max_bytes:
            raise HiPersonalizationError("图片文件过大，已停止读取。")
        return content

    @staticmethod
    def _preview_image_url(image_url: str) -> str:
        parsed = urlparse(image_url)
        stem, separator, extension = parsed.path.rpartition(".")
        if separator and stem.endswith("_small"):
            return urlunparse(parsed._replace(path=f"{stem[:-6]}.{extension}"))
        return image_url

    @staticmethod
    def _thumbnail_120_url(image_url: str) -> str:
        """Use the site's small derivative instead of downloading a full product image."""
        parsed = urlparse(image_url)
        stem, separator, extension = parsed.path.rpartition(".")
        if not separator or stem.endswith("_120"):
            return image_url
        return urlunparse(parsed._replace(path=f"{stem}_120.{extension}"))

    @staticmethod
    def _shipping_stamp_url(soup: BeautifulSoup, current_url: str) -> str:
        for node in soup.find_all(string=lambda value: value and "order shipping stamp" in value.casefold()):
            current = node.parent
            for _ in range(4):
                if current is None:
                    break
                for link in current.find_all("a", href=True):
                    target = urljoin(current_url, str(link["href"]))
                    if urlparse(target).path.casefold().endswith(".pdf"):
                        return target
                current = current.parent
        return ""

    def fetch_order_products_page(
        self, order: OrderSummary
    ) -> tuple[list[ConfirmableProduct], str]:
        response = self._get(order.products_url)
        soup = BeautifulSoup(response.text, "html.parser")
        products: list[ConfirmableProduct] = []
        for row in soup.find_all("tr"):
            values = self._table_values(row)
            product_id = values.get("ID", "")
            if not product_id:
                continue
            confirm_url = ""
            delete_url = ""
            recustom_url = ""
            image = row.find("img")
            image_url = (
                urljoin(response.url, str(image.get("src") or "")) if image else ""
            )
            for link in row.find_all("a", href=True):
                function_name = clean_text(link.get_text(" ", strip=True)).casefold()
                target = urljoin(response.url, str(link["href"]))
                if function_name == "confirm":
                    confirm_url = target
                elif function_name == "delete":
                    delete_url = target
                elif function_name == "recustom":
                    recustom_url = target
            if product_id and not recustom_url:
                recustom_url = self._url(
                    f"/recustom-order-generate-image/?image_order_product_id={product_id}"
                )
            products.append(
                ConfirmableProduct(
                    product_id=product_id,
                    title=values.get("TITLE", ""),
                    status=values.get("STATUS", ""),
                    type_option=values.get("OPTION", ""),
                    quantity=values.get("QTY", ""),
                    confirm_url=confirm_url,
                    image_url=image_url,
                    preview_url=self._preview_image_url(image_url),
                    delete_url=delete_url,
                    recustom_url=recustom_url,
                )
            )
        if not products:
            raise HiPersonalizationError(f"Order {order.order_id} 中没有找到设计产品。")
        return products, self._shipping_stamp_url(soup, response.url)

    def fetch_order_products(self, order: OrderSummary) -> list[ConfirmableProduct]:
        products, _shipping_stamp_url = self.fetch_order_products_page(order)
        return products

    def delete_order_product(self, product: ConfirmableProduct) -> str:
        if not product.delete_url:
            raise HiPersonalizationError(f"设计 {product.product_id} 没有可用的 Delete 功能。")
        parsed = urlparse(product.delete_url)
        if parsed.netloc.casefold() != urlparse(self.base_url).netloc.casefold():
            raise HiPersonalizationError("Delete 地址不属于 HiPersonalization 网站。")
        if "delete-unconfirmed-order-product" not in parsed.path:
            raise HiPersonalizationError("Delete 地址与预期页面不一致，已停止操作。")
        page = self._get(product.delete_url)
        if "Sorry, you are not authorized" in page.text:
            raise AuthenticationError("当前 seller 没有删除该设计的权限。")
        form = find_form(page.text, "gform_104")
        response = self._post(form_action(form, page.url), data=serialize_form(form))
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find("form", id="gform_104") is not None and soup.find(
            id="gform_confirmation_message_104"
        ) is None:
            raise RemoteValidationError("网站仍停留在删除确认表单，但没有返回明确的成功提示。")
        return response.url

    def fetch_seller_shops(self) -> list[SellerShop]:
        if not self.shops_page_url:
            raise AuthenticationError("请先登录 seller 账号。")
        response = self._get(self.shops_page_url)
        soup = BeautifulSoup(response.content, "html.parser")
        shops: list[SellerShop] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            target = urljoin(response.url, str(link["href"]))
            parsed = urlparse(target)
            if "list-image-products-by-image-shop-id-for-seller" not in parsed.path:
                continue
            shop_id = parse_qs(parsed.query).get("image_shop_id", [""])[0]
            if not shop_id or shop_id in seen:
                continue
            values = self._table_values(link.find_parent("tr"))
            shops.append(
                SellerShop(
                    shop_id=shop_id,
                    name=values.get("NAME", "") or f"Shop {shop_id}",
                    products_url=target,
                )
            )
            seen.add(shop_id)
        if not shops:
            raise HiPersonalizationError("当前 seller 的 Shop 列表中没有找到可读取的 Shop。")
        return shops

    def fetch_shop_products(self, shop: SellerShop) -> list[ShopProduct]:
        parsed = urlparse(shop.products_url)
        if parsed.netloc.casefold() != urlparse(self.base_url).netloc.casefold():
            raise HiPersonalizationError("Shop Products 地址不属于 HiPersonalization 网站。")
        response = self._get(shop.products_url)
        soup = BeautifulSoup(response.content, "html.parser")
        products: list[ShopProduct] = []
        for row in soup.find_all("tr"):
            values = self._table_values(row)
            name = values.get("NAME", "")
            sku = values.get("SKU", "")
            if not name and not sku:
                continue
            image_url = ""
            image = row.find("img")
            if image:
                image_url = urljoin(
                    response.url,
                    str(image.get("src") or image.get("data-src") or ""),
                )
            if not image_url:
                for link in row.find_all("a", href=True):
                    candidate = urljoin(response.url, str(link["href"]))
                    if urlparse(candidate).path.casefold().endswith(
                        (".png", ".jpg", ".jpeg", ".webp")
                    ):
                        image_url = candidate
                        break
            if image_url:
                image_url = self._thumbnail_120_url(image_url)
            products.append(ShopProduct(name=name, sku=sku, image_url=image_url))
        if not products:
            raise HiPersonalizationError(f"Shop {shop.shop_id} 中没有找到产品。")
        return products

    def prepare_confirmation(self, product: ConfirmableProduct) -> ConfirmationContext:
        if not product.confirm_url:
            raise HiPersonalizationError(f"设计 {product.product_id} 已确认或没有 Confirm 功能。")
        response = self._get(product.confirm_url)
        form = find_form(response.text, "gform_47")
        return ConfirmationContext(
            url=form_action(form, response.url),
            fields=tuple(serialize_form(form)),
            stamp_types=tuple(select_options(form, "input_5")),
        )

    @classmethod
    def _validate_pdf(cls, path: Path, label: str) -> Path:
        resolved = path.resolve()
        if not resolved.is_file():
            raise HiPersonalizationError(f"{label} PDF 不存在：{resolved}")
        if resolved.suffix.casefold() != ".pdf":
            raise HiPersonalizationError(f"{label} 只支持 PDF 文件。")
        if resolved.stat().st_size > cls.MAX_IMAGE_BYTES:
            raise HiPersonalizationError(f"{label} PDF 超过 80 MB：{resolved.name}")
        with resolved.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise HiPersonalizationError(f"{label} 文件内容不是有效的 PDF。")
        return resolved

    def submit_confirmation(
        self,
        context: ConfirmationContext,
        *,
        shipping_stamp: Path | None = None,
        stamp_type: str = "",
        gift_message: Path | None = None,
    ) -> str:
        if shipping_stamp is None and (stamp_type or gift_message is not None):
            raise HiPersonalizationError("Stamp Type 或 Gift Message 只能随 Shipping Stamp 一起提交。")
        available_stamp_types = {option.value for option in context.stamp_types}
        if shipping_stamp is not None and stamp_type not in available_stamp_types:
            raise HiPersonalizationError("请选择有效的 Stamp Type。")
        shipping = self._validate_pdf(shipping_stamp, "Shipping Stamp") if shipping_stamp else None
        gift = self._validate_pdf(gift_message, "Gift Message") if gift_message else None
        data = self._replace_fields(
            context.fields,
            {"input_1": "image_confirmed", "input_5": stamp_type if shipping else ""},
        )
        with ExitStack() as stack:
            files: dict[str, tuple[str, object, str]] = {}
            if shipping:
                files["input_4"] = (
                    shipping.name,
                    stack.enter_context(shipping.open("rb")),
                    "application/pdf",
                )
            if gift:
                files["input_6"] = (
                    gift.name,
                    stack.enter_context(gift.open("rb")),
                    "application/pdf",
                )
            response = self._post(context.url, data=data, files=files or None)
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find("form", id="gform_47") is not None and soup.find(
            id="gform_confirmation_message_47"
        ) is None:
            raise RemoteValidationError("网站仍停留在确认表单，但没有返回明确的成功提示。")
        return response.url

    @staticmethod
    def _normalized_numeric_id(value: str, label: str) -> str:
        normalized = value.strip()
        if not normalized or not normalized.isdigit():
            raise HiPersonalizationError(f"{label} 必须是数字。")
        return normalized

    def prepare_recustom(self, product_id: str) -> RecustomContext:
        normalized = self._normalized_numeric_id(product_id, "Product ID")
        url = self._url(
            f"/recustom-order-generate-image/?image_order_product_id={normalized}"
        )
        response = self._get(url)
        form = find_form(response.text, "gform_48")
        options = tuple(select_options(form, "input_22"))
        code_field = form.find(attrs={"name": "input_21"})
        type_field = form.find("select", attrs={"name": "input_22"})
        selected = type_field.find("option", selected=True) if type_field else None
        return RecustomContext(
            url=form_action(form, response.url),
            fields=tuple(serialize_form(form)),
            product_id=normalized,
            product_code=str(code_field.get("value") or "") if code_field else "",
            type_options=options,
            selected_type_option=str(selected.get("value") or "") if selected else "",
        )

    def submit_recustom(
        self,
        context: RecustomContext,
        *,
        product_code: str,
        type_option_value: str,
        image_path: Path,
    ) -> str:
        code = product_code.strip()
        if not code:
            raise HiPersonalizationError("Order Product Code 不能为空。")
        available = {option.value for option in context.type_options}
        if type_option_value not in available:
            raise HiPersonalizationError("请选择有效的 Product Type Option。")
        image = image_path.resolve()
        if not image.is_file():
            raise HiPersonalizationError(f"First Image 不存在：{image}")
        if image.stat().st_size > self.MAX_IMAGE_BYTES:
            raise HiPersonalizationError(f"First Image 超过 80 MB：{image.name}")
        data = self._replace_fields(
            context.fields,
            {"input_21": code, "input_22": type_option_value},
        )
        mime_type = mimetypes.guess_type(image.name)[0] or "application/octet-stream"
        with image.open("rb") as stream:
            response = self._post(
                context.url,
                data=data,
                files={"input_9": (image.name, stream, mime_type)},
            )
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find("form", id="gform_48") is not None and soup.find(
            id="gform_confirmation_message_48"
        ) is None:
            raise RemoteValidationError("网站仍停留在替换设计表单，但没有返回明确的成功提示。")
        return response.url

    def prepare_stamp_replacement(self, order_id: str) -> StampReplacementContext:
        normalized = self._normalized_numeric_id(order_id, "Order ID")
        url = self._url(f"/add_stamp_to_order_by_order_id/?order_id={normalized}")
        response = self._get(url)
        form = find_form(response.text, "gform_241")
        return StampReplacementContext(
            url=form_action(form, response.url),
            fields=tuple(serialize_form(form)),
            stamp_types=tuple(select_options(form, "input_4")),
        )

    def submit_stamp_replacement(
        self,
        context: StampReplacementContext,
        *,
        stamp: Path,
        stamp_type: str,
        gift_message: Path | None = None,
    ) -> str:
        available = {option.value for option in context.stamp_types}
        if stamp_type not in available:
            raise HiPersonalizationError("请选择有效的 Stamp Type。")
        stamp_pdf = self._validate_pdf(stamp, "Stamp")
        gift_pdf = self._validate_pdf(gift_message, "Gift Message") if gift_message else None
        data = self._replace_fields(context.fields, {"input_4": stamp_type})
        with ExitStack() as stack:
            files: dict[str, tuple[str, object, str]] = {
                "input_3": (
                    stamp_pdf.name,
                    stack.enter_context(stamp_pdf.open("rb")),
                    "application/pdf",
                )
            }
            if gift_pdf:
                files["input_5"] = (
                    gift_pdf.name,
                    stack.enter_context(gift_pdf.open("rb")),
                    "application/pdf",
                )
            response = self._post(context.url, data=data, files=files)
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find("form", id="gform_241") is not None and soup.find(
            id="gform_confirmation_message_241"
        ) is None:
            raise RemoteValidationError("网站仍停留在替补邮票表单，但没有返回明确的成功提示。")
        return response.url

    def fetch_order_status(self, order_id: str) -> str:
        for order in self.fetch_orders():
            if order.order_id == order_id:
                return order.status
        raise HiPersonalizationError(f"订单列表中没有找到 Order {order_id}。")

    def search_products(self, order_id: str, sku: str) -> list[ProductOption]:
        sku = sku.strip()
        if not sku:
            raise HiPersonalizationError("Product SKU 不能为空。")
        if not self._product_seller:
            raise AuthenticationError("请先登录 seller 账号。")
        url = self._url(
            f"/search-my-product-to-add-my-order/?order_id={order_id}"
            f"&product_seller={self._product_seller}"
        )
        page = self._get(url)
        form = find_form(page.text, "gform_42")
        response = self._post(
            form_action(form, page.url),
            data=serialize_form(form, {"input_3": sku}),
        )
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        soup = BeautifulSoup(response.text, "html.parser")
        products: list[ProductOption] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            target = urljoin(response.url, str(link["href"]))
            parsed = urlparse(target)
            if "list-product-definition-by-product-id-for-add-to-order" not in parsed.path:
                continue
            product_id = parse_qs(parsed.query).get("product_id", [""])[0]
            if not product_id or product_id in seen:
                continue
            row = link.find_parent("tr")
            label = self._summarize_row(row) if row else ""
            products.append(ProductOption(product_id=product_id, label=label or f"Product {product_id}"))
            seen.add(product_id)
        if not products:
            raise HiPersonalizationError(f"没有找到 SKU 为 {sku} 的产品。")
        return products

    def fetch_definitions(self, order_id: str, product_id: str) -> list[DefinitionOption]:
        url = self._url(
            f"/list-product-definition-by-product-id-for-add-to-order/"
            f"?order_id={order_id}&product_id={product_id}"
        )
        response = self._get(url)
        soup = BeautifulSoup(response.text, "html.parser")
        definitions: list[DefinitionOption] = []
        seen: set[str] = set()
        for link in soup.find_all("a", href=True):
            target = urljoin(response.url, str(link["href"]))
            parsed = urlparse(target)
            if "get-product-type-for-product-add-to-order" not in parsed.path:
                continue
            definition_id = parse_qs(parsed.query).get("product_definition_id", [""])[0]
            if not definition_id or definition_id in seen:
                continue
            row = link.find_parent("tr")
            label = self._summarize_row(row) if row else ""
            label = label or f"Definition {definition_id}"
            definitions.append(DefinitionOption(definition_id=definition_id, label=label))
            seen.add(definition_id)
        if not definitions:
            raise HiPersonalizationError("该产品没有可用的 Definition。")
        return definitions

    def fetch_types(self, order_id: str, definition_id: str) -> list[SelectOption]:
        url = self._url(
            f"/get-product-type-for-product-add-to-order/"
            f"?product_definition_id={definition_id}&order_id={order_id}"
        )
        response = self._get(url)
        form = find_form(response.text, "gform_45")
        options = select_options(form, "input_2")
        if not options:
            raise HiPersonalizationError("该 Definition 没有可用的 Product Type。")
        return options

    def prepare_upload(self, order_id: str, definition_id: str, type_value: str) -> UploadContext:
        url = self._url(
            f"/get-product-type-for-product-add-to-order/"
            f"?product_definition_id={definition_id}&order_id={order_id}"
        )
        page = self._get(url)
        type_form = find_form(page.text, "gform_45")
        response = self._post(
            form_action(type_form, page.url),
            data=serialize_form(type_form, {"input_2": type_value}),
        )
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        upload_form = find_form(response.text, "gform_46")
        options = select_options(upload_form, "input_3")
        if not options:
            raise HiPersonalizationError("所选 Product Type 没有可用的 Type Option。")
        return UploadContext(
            url=form_action(upload_form, response.url),
            fields=tuple(serialize_form(upload_form)),
            type_options=tuple(options),
        )

    @staticmethod
    def _replace_fields(
        fields: tuple[tuple[str, str], ...], overrides: dict[str, str]
    ) -> list[tuple[str, str]]:
        result = [(name, value) for name, value in fields if name not in overrides]
        result.extend(overrides.items())
        return result

    def submit_image(
        self,
        context: UploadContext,
        *,
        type_option_value: str,
        quantity: int,
        image_path: Path,
        product_code: str,
    ) -> str:
        image_path = image_path.resolve()
        if not image_path.is_file():
            raise HiPersonalizationError(f"图片不存在：{image_path}")
        if image_path.stat().st_size > self.MAX_IMAGE_BYTES:
            raise HiPersonalizationError(f"图片超过 80 MB：{image_path.name}")
        available_values = {option.value for option in context.type_options}
        if type_option_value not in available_values:
            raise HiPersonalizationError("所选 Type Option 已失效，请重新读取网页选项。")
        if quantity <= 0:
            raise HiPersonalizationError("Quantity 必须大于 0。")
        code = product_code.strip() or image_path.stem
        data = self._replace_fields(
            context.fields,
            {
                "input_2": code,
                "input_3": type_option_value,
                "input_4": str(quantity),
            },
        )
        mime_type = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
        with image_path.open("rb") as stream:
            response = self._post(
                context.url,
                data=data,
                files={"input_9": (image_path.name, stream, mime_type)},
            )
        errors = validation_messages(response.text)
        if errors:
            raise RemoteValidationError("；".join(errors))
        soup = BeautifulSoup(response.text, "html.parser")
        if soup.find("form", id="gform_46") is not None and soup.find(id="gform_confirmation_message_46") is None:
            raise RemoteValidationError("网站仍停留在上传表单，但没有返回明确的成功提示。")
        return response.url

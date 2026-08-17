from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class SelectOption:
    value: str
    label: str

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class ProductOption:
    product_id: str
    label: str

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class SellerShop:
    shop_id: str
    name: str
    products_url: str

    @property
    def label(self) -> str:
        return f"ID: {self.shop_id} | NAME: {self.name}"


@dataclass(frozen=True)
class ShopProduct:
    name: str
    sku: str
    image_url: str = ""


@dataclass(frozen=True)
class DefinitionOption:
    definition_id: str
    label: str

    def __str__(self) -> str:
        return self.label


@dataclass(frozen=True)
class UploadContext:
    url: str
    fields: tuple[tuple[str, str], ...]
    type_options: tuple[SelectOption, ...]


@dataclass(frozen=True)
class OrderSummary:
    order_id: str
    title: str
    status: str
    products_url: str
    image_url: str = ""

    @property
    def label(self) -> str:
        return f"ID: {self.order_id} | TITLE: {self.title} | STATUS: {self.status}"


@dataclass(frozen=True)
class ConfirmableProduct:
    product_id: str
    title: str
    status: str
    type_option: str
    quantity: str
    confirm_url: str = ""
    image_url: str = ""
    preview_url: str = ""
    delete_url: str = ""
    recustom_url: str = ""


@dataclass(frozen=True)
class ConfirmationContext:
    url: str
    fields: tuple[tuple[str, str], ...]
    stamp_types: tuple[SelectOption, ...]


@dataclass(frozen=True)
class StampReplacementContext:
    url: str
    fields: tuple[tuple[str, str], ...]
    stamp_types: tuple[SelectOption, ...]


@dataclass(frozen=True)
class RecustomContext:
    url: str
    fields: tuple[tuple[str, str], ...]
    product_id: str
    product_code: str
    type_options: tuple[SelectOption, ...]
    selected_type_option: str = ""


@dataclass(frozen=True)
class ImageSubmissionTask:
    image_path: Path
    type_option: SelectOption
    quantity: int
    code_suffix: str = ""
    is_back: bool = False


@dataclass(frozen=True)
class SubmissionResult:
    image_path: Path
    success: bool
    message: str


def build_product_code(order_title: str, suffix: str = "", *, is_back: bool = False) -> str:
    title = order_title.strip()
    note = suffix.strip()
    if note and not re.fullmatch(r"[A-Za-z0-9 _\-=+]+", note):
        raise ValueError(
            "Order Product Code 后缀只支持英文、数字、空格及半角 _ - = +，例如 A001-1。"
        )
    code = f"{title}_{note}" if note else title
    return f"BACK_{code}" if is_back else code

from __future__ import annotations

from collections.abc import Iterable, Mapping
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import SelectOption


class FormNotFoundError(RuntimeError):
    pass


def clean_text(value: str) -> str:
    return " ".join(value.split())


def find_form(html: str, form_id: str) -> Tag:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form", id=form_id)
    if form is None:
        raise FormNotFoundError(f"Page does not contain expected form {form_id}.")
    return form


def form_action(form: Tag, current_url: str) -> str:
    return urljoin(current_url, str(form.get("action") or current_url))


def serialize_form(
    form: Tag,
    overrides: Mapping[str, str] | None = None,
) -> list[tuple[str, str]]:
    replacements = dict(overrides or {})
    fields: list[tuple[str, str]] = []
    for element in form.find_all(["input", "select", "textarea"]):
        name = element.get("name")
        if not name or element.has_attr("disabled") or name in replacements:
            continue
        input_type = str(element.get("type") or "").lower()
        if input_type in {"file", "submit", "button", "image", "reset"}:
            continue
        if input_type in {"checkbox", "radio"} and not element.has_attr("checked"):
            continue
        if element.name == "select":
            selected = element.find("option", selected=True) or element.find("option")
            value = str(selected.get("value") or "") if selected else ""
        elif element.name == "textarea":
            value = element.get_text()
        else:
            value = str(element.get("value") or "")
        fields.append((str(name), value))
    fields.extend((key, value) for key, value in replacements.items())
    return fields


def select_options(form: Tag, name: str) -> list[SelectOption]:
    select = form.find("select", attrs={"name": name})
    if select is None:
        raise FormNotFoundError(f"Form does not contain select field {name}.")
    options: list[SelectOption] = []
    for option in select.find_all("option"):
        value = str(option.get("value") or "").strip()
        label = clean_text(option.get_text(" ", strip=True))
        if value:
            options.append(SelectOption(value=value, label=label))
    return options


def validation_messages(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    selectors: Iterable[str] = (
        ".validation_error",
        ".validation_message:not(.validation_message--hidden-on-empty)",
        ".gform_validation_errors",
    )
    messages: list[str] = []
    for selector in selectors:
        for node in soup.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if text and text not in messages:
                messages.append(text)
    return messages

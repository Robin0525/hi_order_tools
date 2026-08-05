from hipersonalization_assistant.forms import find_form, select_options, serialize_form, validation_messages


def test_serialize_form_keeps_hidden_defaults_and_applies_overrides():
    form = find_form(
        """
        <form id="gform_45" action="/next">
          <input type="hidden" name="token" value="abc">
          <input type="text" name="input_2" value="old">
          <input type="file" name="input_9">
          <input type="checkbox" name="unchecked" value="1">
          <input type="checkbox" name="checked" value="yes" checked>
          <select name="choice"><option value="a">A</option><option value="b" selected>B</option></select>
        </form>
        """,
        "gform_45",
    )

    fields = serialize_form(form, {"input_2": "new"})

    assert ("token", "abc") in fields
    assert ("input_2", "new") in fields
    assert ("input_2", "old") not in fields
    assert ("checked", "yes") in fields
    assert not any(name == "unchecked" for name, _ in fields)
    assert ("choice", "b") in fields
    assert not any(name == "input_9" for name, _ in fields)


def test_select_options_excludes_placeholder():
    form = find_form(
        """
        <form id="gform_45">
          <select name="input_2">
            <option value="">select a type</option>
            <option value="20">Type 20</option>
          </select>
        </form>
        """,
        "gform_45",
    )

    assert [(option.value, option.label) for option in select_options(form, "input_2")] == [
        ("20", "Type 20")
    ]


def test_validation_messages_are_deduplicated():
    html = """
    <div class="validation_error">Please correct this field.</div>
    <div class="validation_message">Please correct this field.</div>
    """
    assert validation_messages(html) == ["Please correct this field."]

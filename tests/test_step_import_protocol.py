from palletlab.importers.step_import_protocol import consume_messages, encode_message


def test_protocol_keeps_a_fragmented_message_until_its_line_is_complete():
    line = encode_message("progress", value=42, label="Читаем модель")

    messages, tail = consume_messages("", line[:12])
    assert messages == []
    assert tail == line[:12]

    messages, tail = consume_messages(tail, line[12:])
    assert messages == [{"kind": "progress", "value": 42, "label": "Читаем модель"}]
    assert tail == ""


def test_protocol_ignores_unknown_and_malformed_stdout_lines():
    messages, tail = consume_messages(
        "",
        "library warning\n{not json}\n" + encode_message("progress", value=150, label="Готово"),
    )

    assert messages == [{"kind": "progress", "value": 100, "label": "Готово"}]
    assert tail == ""


def test_protocol_rejects_a_message_from_another_version():
    messages, tail = consume_messages("", '{"version": 999, "kind": "done"}\n')

    assert messages == []
    assert tail == ""

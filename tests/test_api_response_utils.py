"""Regression coverage for the first safe extraction from ``api.routes``."""
from api.main import app
from api.response_utils import (
    attach_download_to_table_data,
    clean_reply_text,
    friendly_error_message,
    normalize_download_file,
)
from api import routes


def test_clean_reply_text_removes_json_blocks_and_extra_blank_lines():
    reply = """结果如下：

```json
{"curve": [1, 2, 3]}
```

结论。


"""

    assert clean_reply_text(reply) == "结果如下：\n\n结论。"


def test_friendly_error_message_handles_connection_failures():
    message = friendly_error_message(RuntimeError("APIConnectionError: unexpected EOF during TLS handshake"))

    assert "上游大模型连接失败" in message
    assert "HTTP(S)_PROXY" in message


def test_normalize_and_attach_download_metadata_preserve_existing_shape():
    download = normalize_download_file(
        {"path": "/tmp/result file.xlsx", "filename": "result file.xlsx"},
        session_id="session-123",
        message_id="message-456",
        user_id="guest user",
    )

    table_data = attach_download_to_table_data({"type": "table"}, download)

    assert download == {
        "path": "/tmp/result file.xlsx",
        "filename": "result file.xlsx",
        "file_id": "session-123",
        "message_id": "message-456",
        "url": "/api/file/download/message/session-123/message-456?user_id=guest%20user",
    }
    assert table_data == {
        "type": "table",
        "download": {
            "url": "/api/file/download/message/session-123/message-456?user_id=guest%20user",
            "filename": "result file.xlsx",
        },
        "file_id": "session-123",
    }


def test_routes_module_keeps_helper_names_and_health_route_registration():
    assert routes.clean_reply_text is clean_reply_text
    assert routes.friendly_error_message is friendly_error_message
    assert routes.normalize_download_file is normalize_download_file
    assert routes.attach_download_to_table_data is attach_download_to_table_data

    route_paths = {route.path for route in app.routes}
    assert "/api/health" in route_paths

"""应用入口测试"""
from fastapi.testclient import TestClient

from src.app.main import app


def test_app_enables_cors_for_local_report_html():
    """本地打开 HTML 报告时，应允许跨域调用正文评审 API"""
    client = TestClient(app)

    response = client.options(
        "/api/v1/evaluation/chat/ask",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "*"

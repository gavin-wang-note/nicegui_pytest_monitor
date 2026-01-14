# test_broken.py
import pytest
import requests


class TestBroken:
    def test_connection_refused_broken(self):
        """连接被拒绝 → 抛出 requests.ConnectionError → broken"""
        # 故意访问一个本地不存在的服务端口
        requests.get("http://127.0.0.1:59999", timeout=1)

    def test_fixture_crash_broken(self, crash_fixture):
        """依赖的 fixture 内部崩溃 → broken"""
        assert crash_fixture == "never_reached"

    def test_assertion_error_not_caught(self):
        """未捕获的断言 → 失败（failed）*对比用*"""
        assert 1 == 2


@pytest.fixture
def crash_fixture():
    """模拟第三方服务突然不可用"""
    raise RuntimeError("数据库连接超时 - 服务不可用")


def test_zero_division_broken():
    """除零异常 → broken"""
    _ = 1 / 0

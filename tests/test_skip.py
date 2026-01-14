import pytest
import sys


@pytest.mark.skip(reason="需求变更，用例暂时不执行")
def test_mark_skip():
    """1. 显式标记跳过"""
    assert 1 == 2   # 永远不会跑到


@pytest.mark.skipif(sys.version_info < (3, 9), reason="需要 Python≥3.9")
def test_skipif_python_version():
    """2. 条件跳过：Python 版本过低"""
    assert True


def test_imperative_skip():
    """3. 运行时根据环境动态跳过"""
    db_online = False              # 模拟数据库离线
    if not db_online:
        pytest.skip("数据库未上线，跳过相关用例")
    # 下面代码不会执行
    assert db_online is True

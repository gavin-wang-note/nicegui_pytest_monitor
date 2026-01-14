# test_xdist_demo.py
import json
import random
import time
import uuid
from pathlib import Path

import pytest
import requests


# 1. 独立临时目录（xdist 安全）
@pytest.fixture(scope="function")
def worker_tmp_path(tmp_path_factory) -> Path:
    """
    每个 worker、每条用例独享目录，避免并发写冲突
    """
    return tmp_path_factory.mktemp(f"worker_{pytest.worker_id}")


# 2. 获取当前 worker 名称（方便日志观察）
@pytest.fixture(scope="session", autouse=True)
def set_worker_id(request):
    """
    把 worker 名称注入到 pytest 全局变量，供用例打印
    """
    worker = getattr(request.config, "workerinput", {}).get("workerid", "master")
    pytest.worker_id = worker
    return worker


# 3. 用例集合（全部无共享状态）
# ----------------------------------------------------------
class TestXdistPass:
    @pytest.mark.parametrize("seed", range(10))
    def test_pass_with_random_delay(self, seed: int):
        """
        纯 CPU / 随机睡眠，无共享数据 → 任意并发
        """
        print(f"[{pytest.worker_id}] seed={seed} start")
        time.sleep(random.uniform(0.01, 0.1))
        assert seed ** 2 >= 0
        print(f"[{pytest.worker_id}] seed={seed} pass")


class TestXdistFail:
    @pytest.mark.parametrize("seed", range(5))
    def test_fail_on_odd(self, seed: int):
        print(f"[{pytest.worker_id}] fail seed={seed}")
        assert seed % 2 == 0, f"odd number {seed} will fail"


class TestXdistSkip:
    @pytest.mark.parametrize("env", ["dev", "staging", "prod"])
    def test_skip_on_dev(self, env: str):
        if env == "dev":
            pytest.skip("dev 环境不跑此用例")
        assert env in ("staging", "prod")


class TestXdistXFail:
    @pytest.mark.xfail(reason="需求 #666 尚未实现")
    def test_xfail_but_assert_fail(self):
        assert 1 == 2

    @pytest.mark.xfail(reason="预期抛 ValueError")
    def test_xfail_but_exception_type_wrong(self):
        # 预期 ValueError，实际 ZeroDivisionError → broken
        1 / 0


class TestXdistError:
    def test_connection_refused(self):
        # 任意非预期异常 → error
        requests.get("http://127.0.0.1:59999", timeout=1)


class TestXdistReRun:
    @pytest.mark.flaky(reruns=3, reruns_delay=0.5)
    def test_flaky_eventually_pass(self):
        """
        前 1~2 次大概率失败，第 3 次成功 → Allure 展示最终 Pass + 重跑痕迹
        """
        # 利用 worker 编号 + 时间戳生成伪随机，避免多 worker 间重复
        worker = pytest.worker_id
        ts = int(time.time() * 1000) % 100
        lucky = (hash(worker) + ts) % 4
        print(f"[{worker}] lucky={lucky}")
        assert lucky == 3, f"not lucky yet {lucky}"


class TestXdistBroken:
    @pytest.mark.xfail(reason="应抛 ValueError")
    def test_broken_wrong_exception(self):
        # 期望 ValueError，实际抛 RuntimeError → broken
        raise RuntimeError("服务突然不可用")


# 4. 进程安全日志（每条用例写独立文件，方便分布式调试）
@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_logreport(report):
    if report.when == "call":
        worker = getattr(pytest, "worker_id", "master")
        log = {
            "worker": worker,
            "nodeid": report.nodeid,
            "outcome": report.outcome,
            "duration": round(report.duration, 3),
            "timestamp": int(time.time()),
        }
        # 写入当前 worker 专属日志
        log_file = Path(f"reports/xdist_{worker}.log")
        log_file.parent.mkdir(exist_ok=True)
        with log_file.open("a", encoding="utf8") as f:
            f.write(json.dumps(log, ensure_ascii=False) + "\n")

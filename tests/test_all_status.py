# test_allure_outcomes.py
import pytest
import requests
import allure


# 1. Pass -----------------------------------------------
@allure.title("正常通过用例")
def test_pass():
    assert 1 + 1 == 2


# 2. Fail -----------------------------------------------
@allure.title("断言失败用例")
def test_fail():
    assert 1 == 2, "显然不相等"


# 3. Skip -----------------------------------------------
@allure.title("显式跳过用例")
@pytest.mark.skip(reason="需求未就绪")
def test_skip():
    assert False, "永远不会执行"


# 4. XFail（预期失败 & 确实失败） ------------------------
@allure.title("XFail-预期失败且失败")
@pytest.mark.xfail(reason="需求 #123 尚未实现")
def test_xfail():
    # 这里确实失败了 → 符合预期 → Allure 标记 XFail（灰色）
    assert 1 == 2


# 5. XPass（预期失败却通过） ----------------------------
@allure.title("XPass-预期失败却通过")
@pytest.mark.xfail(reason="应该抛异常，但开发提前完成")
def test_xpass():
    # 没有抛任何异常 → 与预期不符 → Allure 标记 XPass（黄色）
    assert 1 == 1


# 6. Error（未捕获异常） --------------------------------
@allure.title("未捕获异常-Error")
def test_error():
    # 任何非预期异常都会被 Allure 记为 Error（橙色）
    _ = 1 / 0


# 7. ReRun（自动重跑） ----------------------------------
# 使用 pytest-rerunfailures 插件即可生成重跑记录
@allure.title("重跑示例-最终通过")
@pytest.mark.flaky(reruns=2, reruns_delay=1)  # 需要 pip install pytest-rerunfailures
def test_rerun_eventually_pass():
    # 第一次/第二次失败，第三次通过 → Allure 保留最后一次 Pass 结果
    import random
    rnd = random.randint(1, 3)
    assert rnd == 3, f"随机值 {rnd} != 3（前两次会失败）"

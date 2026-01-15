import subprocess
import threading
import time
import uuid
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
import os
from app.models import TestRun, TestLog, TestQueueItem
from app.services.storage_service import storage_service
from app.services.monitor_service import monitor_service
from app.utils.process_utils import ProcessUtils
from config.settings import settings

# 配置日志
def _setup_logger():
    log_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'logs')
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f'app_{datetime.now().strftime("%Y%m%d")}.log')
    
    logger = logging.getLogger('RemoteTestMonitor.TestService')
    logger.setLevel(logging.DEBUG)
    
    # 清除已有处理器
    logger.handlers.clear()
    
    # 文件处理器
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
    
    return logger

logger = _setup_logger()

class TestService:
    def __init__(self):
        self._current_test_run: Optional[Dict[str, Any]] = None
        self._test_queue: List[TestQueueItem] = []
        self._test_log_callbacks = []
        self._test_status_callbacks = []
        self._processing_queue = False
        self._queue_thread = None
        
        # 初始化时清理卡住的测试
        self._cleanup_stuck_tests()
    
    def start_test(self, test_path: str) -> str:
        """开始执行测试"""
        run_id = str(uuid.uuid4())
        
        # 创建测试运行记录
        test_run = TestRun(
            run_id=run_id,
            start_time=datetime.now(),
            status="running",
            test_path=test_path
        )
        storage_service.save_test_run(test_run)
        
        # 启动测试进程
        self._execute_test(run_id, test_path)
        
        return run_id
    
    def stop_test(self, run_id: str) -> bool:
        """停止正在执行的测试"""
        if self._current_test_run and self._current_test_run["run_id"] == run_id:
            # 终止测试进程及其子进程
            if ProcessUtils.kill_process(self._current_test_run["process"].pid, recursive=True):
                # 更新测试状态
                self._update_test_status(run_id, "stopped")
                self._current_test_run = None
                return True
        return False
    
    def _execute_test(self, run_id: str, test_path: str):
        """执行测试的内部方法"""
        os.makedirs(settings.TEST_REPORTS_PATH, exist_ok=True)
        
        log_file_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}.log")
        report_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}_report.html")
        
        log_file = open(log_file_path, 'w', encoding='utf-8')
        
        test_command = [
            "python", "-m", "pytest",
            test_path,
            "-v",
            "--tb=short",
            "--durations=10",
            f"--html={report_path}",
            "--self-contained-html"
        ]
        
        process = subprocess.Popen(
            test_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        self._current_test_run = {
            "run_id": run_id,
            "process": process,
            "report_path": report_path,
            "log_file_path": log_file_path
        }
        
        monitor_service.monitor_external_process(process.pid)
        
        log_thread = threading.Thread(
            target=self._read_test_logs, 
            args=(run_id, process, log_file),
            daemon=True
        )
        log_thread.start()
        
        status_thread = threading.Thread(
            target=self._monitor_test_status, 
            args=(run_id, process, report_path),
            daemon=True
        )
        status_thread.start()
    
    def _read_test_logs(self, run_id: str, process: subprocess.Popen, log_file):
        """读取测试日志并解析测试统计"""
        logger.info(f"日志读取线程已启动: run_id={run_id}")

        if process.stdout:
            line_count = 0
            for line in iter(process.stdout.readline, ''):
                line = line.strip()
                if line:
                    line_count += 1
                    log_line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {line}\n"

                    try:
                        log_file.write(log_line)
                        log_file.flush()
                        logger.debug(f"日志已写入文件 #{line_count}: {line[:50]}...")
                    except Exception as e:
                        logger.error(f"写入日志文件失败: {e}")

                    test_log = TestLog(
                        run_id=run_id,
                        timestamp=datetime.now(),
                        level=self._determine_log_level(line),
                        message=line
                    )
                    storage_service.save_test_log(test_log)

                    # 触发日志回调
                    self._trigger_log_callbacks(test_log)
                    logger.debug(f"日志回调已触发 #{line_count}: {line[:50]}...")

                    # 解析单个测试用例结果并更新统计
                    self._parse_test_result_line(line, run_id)
                    
                    # 解析测试汇总统计
                    self._parse_test_statistics(line, run_id)
            
            logger.info(f"日志读取完成，共读取 {line_count} 行日志")
            
            try:
                log_file.close()
                logger.info(f"日志文件已关闭: {log_file.name}")
            except Exception as e:
                logger.error(f"关闭日志文件失败: {e}")
                
        process.stdout.close()
    
    def _determine_log_level(self, line: str) -> str:
        """根据日志内容确定日志级别"""
        line_upper = line.upper()
        if " FAILED" in line_upper or " ERROR" in line_upper or " FAILED\t" in line_upper:
            return "ERROR"
        elif "WARNING" in line_upper or "WARN" in line_upper:
            return "WARNING"
        return "INFO"
    
    def _parse_test_result_line(self, line: str, run_id: str):
        """解析单个测试用例结果行，动态更新统计"""
        import re
        
        line_stripped = line.strip()
        
        if not line_stripped:
            return
        
        is_passed = False
        is_failed = False
        
        pattern_passed = r'^[✅✔✓]\s*通过[:：]\s*.+'
        pattern_failed = r'^[❌✗×]\s*失败[:：]\s*.+'
        
        if re.match(pattern_passed, line_stripped):
            is_passed = True
        elif re.match(pattern_failed, line_stripped):
            is_failed = True
        elif re.search(r'PASSED\s+', line_stripped):
            is_passed = True
        elif re.search(r'FAILED\s+', line_stripped):
            is_failed = True
        
        if not is_passed and not is_failed:
            return
        
        logger.debug(f"[Parse] 匹配到测试结果行: {line_stripped[:80]}...")
        
        test_run = storage_service.get_test_run(run_id)
        if not test_run:
            logger.debug(f"[Parse] 错误：找不到测试记录 {run_id}")
            return
        
        old_passed = test_run.passed_tests
        old_failed = test_run.failed_tests
        old_skipped = test_run.skipped_tests
        
        if is_passed:
            test_run.passed_tests += 1
            logger.debug(f"[Parse] 检测到通过用例")
        elif is_failed:
            test_run.failed_tests += 1
            logger.debug(f"[Parse] 检测到失败用例")
        
        test_run.total_tests = test_run.passed_tests + test_run.failed_tests + test_run.skipped_tests
        storage_service.save_test_run(test_run)
        
        logger.debug(f"[Parse] 统计更新: 通过 {old_passed}->{test_run.passed_tests}, 失败 {old_failed}->{test_run.failed_tests}, 跳过 {old_skipped}->{test_run.skipped_tests}")
        
        self._trigger_status_callbacks(test_run)
    
    def _parse_test_statistics(self, line: str, run_id: str):
        """解析测试统计信息"""
        import re
        
        line_lower = line.lower().strip()
        
        if '=' not in line_lower:
            return
        
        summary_match = re.search(r'=+\s*(.+?)\s*=+\s*$', line_lower)
        if not summary_match:
            return
        
        summary_text = summary_match.group(1)
        logger.debug(f"[Summary] 解析汇总文本: {summary_text}")
        
        try:
            passed_tests_local = 0
            failed_tests_local = 0
            skipped_tests_local = 0
            
            passed_match = re.search(r'(\d+)\s+passed', summary_text)
            failed_match = re.search(r'(\d+)\s+failed', summary_text)
            skipped_match = re.search(r'(\d+)\s+skipped', summary_text)
            
            if passed_match:
                passed_tests_local = int(passed_match.group(1))
                logger.debug(f"[Summary] 解析到 passed: {passed_tests_local}")
            
            if failed_match:
                failed_tests_local = int(failed_match.group(1))
                logger.debug(f"[Summary] 解析到 failed: {failed_tests_local}")
            
            if skipped_match:
                skipped_tests_local = int(skipped_match.group(1))
                logger.debug(f"[Summary] 解析到 skipped: {skipped_tests_local}")
            
            if passed_tests_local > 0 or failed_tests_local > 0 or skipped_tests_local > 0:
                total_tests_local = passed_tests_local + failed_tests_local + skipped_tests_local
                logger.debug(f"[Summary] 汇总统计: 通过={passed_tests_local}, 失败={failed_tests_local}, 跳过={skipped_tests_local}, 总数={total_tests_local}")
                self._update_test_statistics(run_id, total_tests_local, passed_tests_local, failed_tests_local, skipped_tests_local)
        except Exception as e:
            logger.debug(f"[Summary] 解析统计失败: {e}")
    
    def _update_test_statistics(self, run_id: str, total_tests: int, passed_tests: int, failed_tests: int, skipped_tests: int):
        """更新测试统计数据"""
        logger.debug(f"更新测试统计: run_id={run_id}, 总数={total_tests}, 通过={passed_tests}, 失败={failed_tests}, 跳过={skipped_tests}")
        test_run = storage_service.get_test_run(run_id)
        if test_run:
            logger.debug(f"更新前的测试状态: {test_run.status}")
            test_run.total_tests = total_tests
            test_run.passed_tests = passed_tests
            test_run.failed_tests = failed_tests
            test_run.skipped_tests = skipped_tests
            storage_service.save_test_run(test_run)
            logger.debug("测试统计已保存到数据库")
            
            # 触发状态回调以更新UI
            self._trigger_status_callbacks(test_run)
            logger.debug("状态回调已触发，UI将更新")
        else:
            logger.error(f"错误：找不到测试运行记录来更新统计: run_id={run_id}")
    
    def _monitor_test_status(self, run_id: str, process: subprocess.Popen, report_path: str):
        """监控测试状态"""
        try:
            exit_code = process.wait()
            logger.debug(f"[Monitor] 测试结束: run_id={run_id}, exit={exit_code}")
            
            test_run = storage_service.get_test_run(run_id)
            
            if test_run:
                if test_run.passed_tests == 0 and test_run.failed_tests == 0:
                    logger.debug(f"[Monitor] 警告: 统计仍为0，尝试解析日志文件获取最终统计...")
                    self._parse_log_file_for_statistics(run_id)
                    
                    test_run = storage_service.get_test_run(run_id)
                    logger.debug(f"[Monitor] 解析后: 通过={test_run.passed_tests}, 失败={test_run.failed_tests}, 跳过={test_run.skipped_tests}")
                
                total = test_run.passed_tests + test_run.failed_tests
                success_rate = (test_run.passed_tests / total * 100) if total > 0 else 0
                
                final_status = "completed" if (exit_code == 0 or (exit_code == 1 and success_rate >= 95)) else "failed"
                
                logger.debug(f"[Monitor] 测试完成: run_id={run_id}, 通过={test_run.passed_tests}, 失败={test_run.failed_tests}, 跳过={test_run.skipped_tests}, 成功率={success_rate:.1f}%, 状态={final_status}")
                
                self._update_test_status(run_id, final_status, report_path, exit_code)
        except Exception as e:
            logger.debug(f"[Monitor] Error: {e}")
            try:
                self._update_test_status(run_id, "failed", report_path)
            except:
                pass
    
    def _parse_log_file_for_statistics(self, run_id: str):
        """解析日志文件获取最终统计信息"""
        log_file_path = os.path.join(settings.TEST_REPORTS_PATH, f"{run_id}.log")
        
        if not os.path.exists(log_file_path):
            logger.debug(f"[ParseLog] 日志文件不存在: {log_file_path}")
            return
        
        logger.debug(f"[ParseLog] 开始解析日志文件: {log_file_path}")
        
        passed = 0
        failed = 0
        skipped = 0
        summary_parsed = False
        
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    
                    self._parse_test_result_line(line, run_id)
                    
                    if '=' in line and not summary_parsed:
                        self._parse_test_statistics(line, run_id)
                        summary_parsed = True
            
            logger.debug(f"[ParseLog] 日志解析完成")
            
            test_run = storage_service.get_test_run(run_id)
            if test_run:
                logger.debug(f"[ParseLog] 最终统计: 通过={test_run.passed_tests}, 失败={test_run.failed_tests}, 跳过={test_run.skipped_tests}")
        except Exception as e:
            logger.debug(f"[ParseLog] 解析日志文件失败: {e}")
    
    def _cleanup_stuck_tests(self):
        """清理卡在running状态的测试记录"""
        logger.debug("检查卡在running状态的测试...")
        all_tests = storage_service.get_all_test_runs()
        current_time = datetime.now()
        
        for test_run in all_tests:
            # 检查是否是卡住的测试（running状态但统计为0，且开始时间超过30分钟）
            if (test_run.status == 'running' and 
                test_run.total_tests == 0 and 
                test_run.passed_tests == 0 and 
                test_run.failed_tests == 0 and 
                test_run.skipped_tests == 0):
                
                # 检查运行时间
                time_diff = (current_time - test_run.start_time).total_seconds()
                if time_diff > 1800:  # 30分钟
                    logger.debug(f"清理卡住的测试: run_id={test_run.run_id}, 运行时间={time_diff:.0f}秒")
                    self._update_test_status(test_run.run_id, "failed", test_run.report_path, -1)
    
    def _update_test_status(self, run_id: str, status: str, report_path: Optional[str] = None, exit_code: Optional[int] = None):
        """更新测试状态"""
        existing_test_run = storage_service.get_test_run(run_id)
        if existing_test_run:
            logger.debug(f"[Status] 更新状态: run_id={run_id}, {existing_test_run.status} -> {status}")
            existing_test_run.status = status
            existing_test_run.end_time = datetime.now()
            if report_path:
                existing_test_run.report_path = report_path
            if exit_code is not None:
                existing_test_run.exit_code = exit_code
            storage_service.save_test_run(existing_test_run)
            
            self._trigger_status_callbacks(existing_test_run)
        else:
            logger.warning(f"[Status] 错误：找不到测试运行记录: run_id={run_id}")
    
    def add_to_queue(self, test_path: str, priority: int = 0) -> str:
        """添加测试到队列"""
        queue_id = str(uuid.uuid4())
        queue_item = TestQueueItem(
            queue_id=queue_id,
            test_path=test_path,
            priority=priority,
            status="queued",
            created_at=datetime.now()
        )
        
        # 保存到队列
        storage_service.save_test_queue_item(queue_item)
        self._test_queue.append(queue_item)
        
        # 开始处理队列
        self._start_queue_processing()
        
        return queue_id
    
    def _start_queue_processing(self):
        """开始处理测试队列"""
        if not self._processing_queue and not self._current_test_run:
            self._processing_queue = True
            self._queue_thread = threading.Thread(target=self._process_queue, daemon=True)
            self._queue_thread.start()
    
    def _process_queue(self):
        """处理测试队列"""
        while self._test_queue and not self._current_test_run:
            # 获取优先级最高的队列项
            self._test_queue.sort(key=lambda x: (-x.priority, x.created_at))
            queue_item = self._test_queue.pop(0)
            
            # 更新队列项状态
            storage_service.update_test_queue_item(queue_item.queue_id, "running")
            
            # 执行测试
            self.start_test(queue_item.test_path)
            
            # 等待测试开始
            time.sleep(1)
        
        self._processing_queue = False
    
    def _process_next_in_queue(self):
        """处理队列中的下一个测试"""
        self._start_queue_processing()
    
    def get_test_queue(self) -> List[TestQueueItem]:
        """获取测试队列"""
        return storage_service.get_test_queue()
    
    def register_log_callback(self, callback):
        """注册日志回调函数"""
        if callback not in self._test_log_callbacks:
            self._test_log_callbacks.append(callback)
    
    def unregister_log_callback(self, callback):
        """注销日志回调函数"""
        if callback in self._test_log_callbacks:
            self._test_log_callbacks.remove(callback)
    
    def register_status_callback(self, callback):
        """注册状态回调函数"""
        if callback not in self._test_status_callbacks:
            self._test_status_callbacks.append(callback)
    
    def unregister_status_callback(self, callback):
        """注销状态回调函数"""
        if callback in self._test_status_callbacks:
            self._test_status_callbacks.remove(callback)
    
    def _trigger_log_callbacks(self, test_log: TestLog):
        """触发日志回调"""
        for callback in self._test_log_callbacks:
            try:
                callback(test_log)
            except Exception as e:
                logger.error(f"Log callback error: {e}")
    
    def _trigger_status_callbacks(self, test_run: TestRun):
        """触发状态回调"""
        for callback in self._test_status_callbacks:
            try:
                callback(test_run)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    def get_test_reports(self) -> List[Dict[str, Any]]:
        """获取测试报告列表"""
        # 从数据库获取所有测试运行
        # 注意：这里需要实现从数据库获取所有测试运行的方法
        # 暂时返回空列表
        return []
    
    def get_test_logs(self, run_id: str) -> List[TestLog]:
        """获取测试日志"""
        return storage_service.get_test_logs(run_id)

# 创建全局测试服务实例
test_service = TestService()

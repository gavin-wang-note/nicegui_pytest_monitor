import subprocess
import threading
import time
import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
import os
from app.models import TestRun, TestLog, TestQueueItem
from app.services.storage_service import storage_service
from app.services.monitor_service import monitor_service
from app.utils.process_utils import ProcessUtils
from config.settings import settings

class TestService:
    def __init__(self):
        self._current_test_run: Optional[Dict[str, Any]] = None
        self._test_queue: List[TestQueueItem] = []
        self._test_log_callbacks = []
        self._test_status_callbacks = []
        self._processing_queue = False
        self._queue_thread = None
    
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
        # 确保报告目录存在
        os.makedirs(settings.TEST_REPORTS_PATH, exist_ok=True)
        
        # 构建测试命令
        report_path = os.path.join(settings.TEST_REPORTS_PATH, f"report_{run_id}.html")
        test_command = [
            "python", "-m", "pytest",
            test_path,
            "-v",
            f"--html={report_path}"
        ]
        
        # 启动测试进程
        process = subprocess.Popen(
            test_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        
        # 记录当前测试运行信息
        self._current_test_run = {
            "run_id": run_id,
            "process": process,
            "report_path": report_path
        }
        
        # 开始监控测试进程资源
        monitor_service.monitor_external_process(process.pid)
        
        # 启动日志读取线程
        log_thread = threading.Thread(
            target=self._read_test_logs, 
            args=(run_id, process),
            daemon=True
        )
        log_thread.start()
        
        # 启动状态监控线程
        status_thread = threading.Thread(
            target=self._monitor_test_status, 
            args=(run_id, process, report_path),
            daemon=True
        )
        status_thread.start()
    
    def _read_test_logs(self, run_id: str, process: subprocess.Popen):
        """读取测试日志并解析测试统计"""
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        # 同时读取stdout和stderr
        import threading
        
        def read_stream(stream, stream_name):
            """读取单个流的输出"""
            for line in iter(stream.readline, ''):
                line = line.strip()
                if line:
                    self._process_log_line(run_id, line, stream_name)
                    
                    # 解析测试统计信息（通常在最后几行）
                    self._parse_test_statistics(run_id, line, stream_name)
        
        # 启动线程读取stdout
        if process.stdout:
            stdout_thread = threading.Thread(
                target=read_stream,
                args=(process.stdout, 'stdout'),
                daemon=True
            )
            stdout_thread.start()
        
        # 启动线程读取stderr  
        if process.stderr:
            stderr_thread = threading.Thread(
                target=read_stream,
                args=(process.stderr, 'stderr'),
                daemon=True
            )
            stderr_thread.start()
        
        # 等待线程完成
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        
        # 等待子进程结束
        process.wait()
        
        # 强制更新最终统计数据
        self._update_test_statistics(run_id, total_tests, passed_tests, failed_tests, skipped_tests)
    
    def _parse_test_statistics(self, run_id: str, line: str, stream_name: str):
        """解析测试统计信息"""
        import re
        
        # 匹配各种pytest输出格式
        # 格式1: "3 passed, 1 failed, 2 skipped in 10.50s"
        # 格式2: "1 failed in 5.20s" 
        # 格式3: "3 passed in 8.30s"
        # 格式4: "2 failed, 1 skipped in 12.34s"
        
        total_tests = 0
        passed_tests = 0
        failed_tests = 0
        skipped_tests = 0
        
        # 使用正则表达式匹配测试统计格式
        patterns = [
            r'(\d+)\s+passed.*?(\d+)\s+failed.*?(\d+)\s+skipped',
            r'(\d+)\s+passed.*?(\d+)\s+failed',
            r'(\d+)\s+failed.*?(\d+)\s+skipped',
            r'(\d+)\s+passed.*?(\d+)\s+skipped',
            r'(\d+)\s+passed',
            r'(\d+)\s+failed',
            r'(\d+)\s+skipped',
        ]
        
        matched = False
        for pattern in patterns:
            match = re.search(pattern, line)
            if match:
                matched = True
                groups = match.groups()
                
                # 根据匹配的格式提取数据
                if len(groups) == 3:  # 包含pass, fail, skip
                    passed_tests = int(groups[0])
                    failed_tests = int(groups[1])
                    skipped_tests = int(groups[2])
                elif len(groups) == 2:  # 包含两种统计
                    # 判断是passed+failed还是failed+skip等
                    if "passed" in line and "failed" in line:
                        passed_tests = int(groups[0])
                        failed_tests = int(groups[1])
                    elif "failed" in line and "skipped" in line:
                        failed_tests = int(groups[0])
                        skipped_tests = int(groups[1])
                    elif "passed" in line and "skipped" in line:
                        passed_tests = int(groups[0])
                        skipped_tests = int(groups[1])
                elif len(groups) == 1:  # 只有一种统计
                    if "passed" in line:
                        passed_tests = int(groups[0])
                    elif "failed" in line:
                        failed_tests = int(groups[0])
                    elif "skipped" in line:
                        skipped_tests = int(groups[0])
                break
        
        # 如果没有匹配到，尝试手动解析
        if not matched and ("passed" in line or "failed" in line or "skipped" in line):
            try:
                # 简单的字符串分割解析
                parts = line.replace(" in ", " ").split(",")
                for part in parts:
                    part = part.strip()
                    if "passed" in part:
                        # 提取数字
                        numbers = re.findall(r'\d+', part)
                        if numbers:
                            passed_tests = int(numbers[0])
                    elif "failed" in part:
                        numbers = re.findall(r'\d+', part)
                        if numbers:
                            failed_tests = int(numbers[0])
                    elif "skipped" in part:
                        numbers = re.findall(r'\d+', part)
                        if numbers:
                            skipped_tests = int(numbers[0])
            except Exception as e:
                print(f"手动解析失败: {e}")
        
        total_tests = passed_tests + failed_tests + skipped_tests
        
        # 更新测试统计数据（只有当有实际数据时才更新）
        if total_tests > 0:
            self._update_test_statistics(run_id, total_tests, passed_tests, failed_tests, skipped_tests)
            print(f"更新统计数据: 总数={total_tests}, 通过={passed_tests}, 失败={failed_tests}, 跳过={skipped_tests} (来源: {stream_name})")
        elif matched:
            print(f"匹配到统计行但解析失败: {line}")
    
    def _process_log_line(self, run_id: str, line: str, stream_name: str):
        """处理单行日志"""
        # 确定日志级别
        log_level = "INFO"
        if "FAILED" in line.upper() or "ERROR" in line.upper():
            log_level = "ERROR"
        elif "WARNING" in line.upper() or "WARN" in line.upper():
            log_level = "WARNING"
        elif "DEBUG" in line.upper():
            log_level = "DEBUG"
        
        # 创建日志记录
        test_log = TestLog(
            run_id=run_id,
            timestamp=datetime.now(),
            level=log_level,
            message=line
        )
        
        # 保存日志
        storage_service.save_test_log(test_log)
        
        # 触发日志回调
        self._trigger_log_callbacks(test_log)
    
    def _update_test_statistics(self, run_id: str, total_tests: int, passed_tests: int, failed_tests: int, skipped_tests: int):
        """更新测试统计数据"""
        test_run = storage_service.get_test_run(run_id)
        if test_run:
            test_run.total_tests = total_tests
            test_run.passed_tests = passed_tests
            test_run.failed_tests = failed_tests
            test_run.skipped_tests = skipped_tests
            storage_service.save_test_run(test_run)
            
            # 触发状态回调以更新UI
            self._trigger_status_callbacks(test_run)
    
    def _monitor_test_status(self, run_id: str, process: subprocess.Popen, report_path: str):
        """监控测试状态"""
        process.wait()
        
        # 停止监控该进程
        monitor_service.stop_monitoring_process()
        
        # 更新测试状态
        if process.returncode == 0:
            status = "completed"
        else:
            status = "failed"
        
        self._update_test_status(run_id, status, report_path)
        
        # 清理当前测试运行信息
        self._current_test_run = None
        
        # 处理下一个队列项
        self._process_next_in_queue()
    
    def _update_test_status(self, run_id: str, status: str, report_path: Optional[str] = None):
        """更新测试状态"""
        existing_test_run = storage_service.get_test_run(run_id)
        if existing_test_run:
            # 只更新状态相关字段，保留已解析的统计数据
            existing_test_run.status = status
            existing_test_run.end_time = datetime.now()
            if report_path:
                existing_test_run.report_path = report_path
            storage_service.save_test_run(existing_test_run)
            
            # 触发状态回调
            self._trigger_status_callbacks(existing_test_run)
    
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
                print(f"Log callback error: {e}")
    
    def _trigger_status_callbacks(self, test_run: TestRun):
        """触发状态回调"""
        for callback in self._test_status_callbacks:
            try:
                callback(test_run)
            except Exception as e:
                print(f"Status callback error: {e}")
    
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

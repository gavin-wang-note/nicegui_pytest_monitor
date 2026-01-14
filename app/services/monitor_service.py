import psutil
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional
from app.models import SystemData
from app.services.storage_service import storage_service
from app.utils.process_utils import ProcessUtils
from config.settings import settings

class MonitorService:
    def __init__(self):
        self._monitoring = False
        self._interval = settings.MONITOR_INTERVAL
        self._thread = None
        self._target_process_id = None
        self._system_data_callbacks = []
    
    def start_monitoring(self, process_id: Optional[int] = None):
        """启动监控服务"""
        if not self._monitoring:
            self._monitoring = True
            self._target_process_id = process_id
            self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._thread.start()
    
    def stop_monitoring(self):
        """停止监控服务"""
        self._monitoring = False
        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None
    
    def set_interval(self, interval: int):
        """设置监控频率（秒）"""
        if settings.MIN_MONITOR_INTERVAL <= interval <= settings.MAX_MONITOR_INTERVAL:
            self._interval = interval
    
    def get_interval(self) -> int:
        """获取当前监控频率"""
        return self._interval
    
    def register_system_data_callback(self, callback):
        """注册系统数据回调函数"""
        if callback not in self._system_data_callbacks:
            self._system_data_callbacks.append(callback)
    
    def unregister_system_data_callback(self, callback):
        """注销系统数据回调函数"""
        if callback in self._system_data_callbacks:
            self._system_data_callbacks.remove(callback)
    
    def _monitor_loop(self):
        """监控循环"""
        while self._monitoring:
            start_time = time.time()
            
            # 收集系统数据
            system_data = self._collect_system_data()
            
            # 保存到数据库
            storage_service.save_system_data(system_data)
            
            # 触发回调
            for callback in self._system_data_callbacks:
                try:
                    callback(system_data)
                except Exception as e:
                    print(f"Callback error: {e}")
            
            # 等待下一个监控周期
            elapsed_time = time.time() - start_time
            sleep_time = max(0, self._interval - elapsed_time)
            time.sleep(sleep_time)
    
    def _collect_system_data(self) -> SystemData:
        """收集系统数据"""
        # 获取系统级资源使用情况
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        
        # 获取网络统计信息
        net_io = psutil.net_io_counters()
        
        process_id = None
        process_name = None
        
        # 如果指定了目标进程，获取其资源使用情况
        if self._target_process_id:
            process_info = ProcessUtils.get_process_info(self._target_process_id)
            if process_info:
                process_id = self._target_process_id
                process_name = process_info["name"]
                
                # 计算进程及其子进程的总资源使用
                process_resources = ProcessUtils.calculate_total_resource_usage(self._target_process_id)
                cpu_percent = process_resources["total_cpu"]
                memory_percent = process_resources["total_memory"]
            else:
                # 进程不存在，重置目标进程ID
                self._target_process_id = None
                memory_percent = memory.percent
        else:
            # 使用系统级资源
            memory_percent = memory.percent
        
        return SystemData(
            timestamp=datetime.now(),
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            disk_percent=disk.percent,
            network_sent=net_io.bytes_sent,
            network_recv=net_io.bytes_recv,
            process_id=process_id,
            process_name=process_name
        )
    
    def get_current_system_data(self) -> SystemData:
        """获取当前系统数据"""
        return self._collect_system_data()
    
    def get_process_resources(self, pid: int) -> Dict[str, Any]:
        """获取特定进程及其子进程的资源使用情况"""
        return ProcessUtils.calculate_total_resource_usage(pid)
    
    def monitor_external_process(self, pid: int):
        """开始监控外部进程"""
        self._target_process_id = pid
        if not self._monitoring:
            self.start_monitoring(pid)
    
    def stop_monitoring_process(self):
        """停止监控特定进程，恢复系统级监控"""
        self._target_process_id = None

# 创建全局监控服务实例
monitor_service = MonitorService()

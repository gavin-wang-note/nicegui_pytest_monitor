from typing import List, Dict, Any, Callable
from datetime import datetime
from app.models import SystemData, TestRun
from app.services.monitor_service import monitor_service
from app.services.test_service import test_service
from config.settings import settings

class AlertService:
    def __init__(self):
        self._alert_callbacks = []
        self._alerts = []
        self._register_callbacks()
    
    def _register_callbacks(self):
        """注册回调函数，监听系统数据和测试结果"""
        monitor_service.register_system_data_callback(self._check_system_alerts)
        test_service.register_status_callback(self._check_test_alerts)
    
    def _check_system_alerts(self, system_data: SystemData):
        """检查系统资源告警"""
        alerts = []
        
        # 检查CPU使用率
        if system_data.cpu_percent > settings.CPU_ALERT_THRESHOLD:
            alerts.append({
                "type": "cpu",
                "message": f"CPU使用率过高: {system_data.cpu_percent:.1f}%",
                "timestamp": system_data.timestamp,
                "value": system_data.cpu_percent,
                "threshold": settings.CPU_ALERT_THRESHOLD
            })
        
        # 检查内存使用率
        if system_data.memory_percent > settings.MEMORY_ALERT_THRESHOLD:
            alerts.append({
                "type": "memory",
                "message": f"内存使用率过高: {system_data.memory_percent:.1f}%",
                "timestamp": system_data.timestamp,
                "value": system_data.memory_percent,
                "threshold": settings.MEMORY_ALERT_THRESHOLD
            })
        
        # 检查磁盘使用率
        if system_data.disk_percent > settings.DISK_ALERT_THRESHOLD:
            alerts.append({
                "type": "disk",
                "message": f"磁盘使用率过高: {system_data.disk_percent:.1f}%",
                "timestamp": system_data.timestamp,
                "value": system_data.disk_percent,
                "threshold": settings.DISK_ALERT_THRESHOLD
            })
        
        # 处理告警
        for alert in alerts:
            self._trigger_alert(alert)
    
    def _check_test_alerts(self, test_run: TestRun):
        """检查测试结果告警"""
        if test_run.status == "failed":
            alert = {
                "type": "test_failure",
                "message": f"测试失败: {test_run.test_path}",
                "timestamp": datetime.now(),
                "run_id": test_run.run_id,
                "test_path": test_run.test_path
            }
            self._trigger_alert(alert)
    
    def _trigger_alert(self, alert: Dict[str, Any]):
        """触发告警"""
        # 保存告警
        self._alerts.append(alert)
        # 触发告警回调
        self._notify_callbacks(alert)
        # 发送通知（这里可以扩展为邮件、消息等）
        self._send_notification(alert)
    
    def _notify_callbacks(self, alert: Dict[str, Any]):
        """通知所有注册的回调函数"""
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                print(f"Alert callback error: {e}")
    
    def _send_notification(self, alert: Dict[str, Any]):
        """发送告警通知"""
        # 这里可以扩展为邮件、Slack、企业微信等通知方式
        # 目前只打印到控制台
        print(f"[ALERT] {alert['timestamp']} - {alert['message']}")
    
    def register_alert_callback(self, callback: Callable):
        """注册告警回调函数"""
        if callback not in self._alert_callbacks:
            self._alert_callbacks.append(callback)
    
    def unregister_alert_callback(self, callback: Callable):
        """注销告警回调函数"""
        if callback in self._alert_callbacks:
            self._alert_callbacks.remove(callback)
    
    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """获取最近的告警记录"""
        return self._alerts[-limit:]
    
    def clear_alerts(self):
        """清空告警记录"""
        self._alerts.clear()
    
    def set_threshold(self, resource_type: str, threshold: float):
        """设置告警阈值"""
        if resource_type == "cpu":
            settings.CPU_ALERT_THRESHOLD = threshold
        elif resource_type == "memory":
            settings.MEMORY_ALERT_THRESHOLD = threshold
        elif resource_type == "disk":
            settings.DISK_ALERT_THRESHOLD = threshold
    
    def get_threshold(self, resource_type: str) -> float:
        """获取告警阈值"""
        if resource_type == "cpu":
            return settings.CPU_ALERT_THRESHOLD
        elif resource_type == "memory":
            return settings.MEMORY_ALERT_THRESHOLD
        elif resource_type == "disk":
            return settings.DISK_ALERT_THRESHOLD
        return 0.0

# 创建全局告警服务实例
alert_service = AlertService()

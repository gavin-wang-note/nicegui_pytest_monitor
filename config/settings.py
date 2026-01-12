from pydantic_settings import BaseSettings
from typing import Optional
import os

class Settings(BaseSettings):
    # 应用配置
    APP_NAME: str = "Remote Test Monitor"
    APP_VERSION: str = "1.0.0"
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    
    # 安全认证配置
    AUTH_ENABLED: bool = True
    APP_USERNAME: str = "admin"  # 使用APP_前缀避免与系统环境变量冲突
    APP_PASSWORD: str = "admin123"  # 使用APP_前缀避免与系统环境变量冲突
    
    # 系统监控配置
    MONITOR_INTERVAL: int = 5  # 默认监控频率（秒）
    MAX_MONITOR_INTERVAL: int = 60  # 最大监控频率（秒）
    MIN_MONITOR_INTERVAL: int = 5  # 最小监控频率（秒）
    
    # 告警配置
    CPU_ALERT_THRESHOLD: float = 80.0  # CPU 使用率告警阈值（%）
    MEMORY_ALERT_THRESHOLD: float = 80.0  # 内存使用率告警阈值（%）
    DISK_ALERT_THRESHOLD: float = 80.0  # 磁盘使用率告警阈值（%）
    
    # 数据库配置
    DB_PATH: str = os.path.join("db", "monitor.db")
    
    # 测试配置
    TEST_REPORTS_PATH: str = os.path.join("reports")
    PYTEST_ARGS: list = ["-v", "--html=report.html"]
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_PATH: str = os.path.join("reports", "logs")
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # 忽略系统环境变量USERNAME，避免冲突
        extra = "ignore"
    
    @property
    def USERNAME(self) -> str:
        """为兼容性提供USERNAME属性"""
        return self.APP_USERNAME
    
    @property
    def PASSWORD(self) -> str:
        """为兼容性提供PASSWORD属性"""
        return self.APP_PASSWORD

settings = Settings()

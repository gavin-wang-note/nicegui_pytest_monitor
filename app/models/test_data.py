from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class TestResult(BaseModel):
    """测试结果模型"""
    test_id: str
    name: str
    status: str  # passed, failed, skipped
    duration: float
    message: Optional[str] = None
    traceback: Optional[str] = None
    timestamp: datetime

    class Config:
        orm_mode = True

class TestRun(BaseModel):
    """测试运行模型"""
    run_id: str
    start_time: datetime
    end_time: Optional[datetime] = None
    status: str  # running, completed, failed, stopped
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    test_path: str
    report_path: Optional[str] = None
    node_name: str = "localhost"
    exit_code: Optional[int] = None  # 记录pytest退出码
    execution_type: str = "local"  # local or remote

    class Config:
        orm_mode = True

class TestQueueItem(BaseModel):
    """测试队列项模型"""
    queue_id: str
    test_path: str
    priority: int = 0
    status: str  # queued, running, completed
    created_at: datetime

    class Config:
        orm_mode = True

class TestLog(BaseModel):
    """测试日志模型"""
    run_id: str
    timestamp: datetime
    level: str
    message: str

    class Config:
        orm_mode = True

from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class SystemData(BaseModel):
    """系统监控数据模型"""
    timestamp: datetime
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    network_sent: int
    network_recv: int
    process_id: Optional[int] = None
    process_name: Optional[str] = None
    node_name: str = "localhost"

    class Config:
        orm_mode = True

class ProcessData(BaseModel):
    """进程监控数据模型"""
    pid: int
    name: str
    cpu_percent: float
    memory_percent: float
    children: list['ProcessData'] = []

    class Config:
        orm_mode = True

ProcessData.update_forward_refs()

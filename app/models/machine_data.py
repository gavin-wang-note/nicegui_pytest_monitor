from pydantic import BaseModel
from typing import Optional
from enum import Enum

class MachinePlatform(str, Enum):
    """机器平台类型"""
    WINDOWS = "windows"
    LINUX = "linux"

class MachineStatus(str, Enum):
    """机器连接状态"""
    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"

class RemoteMachine(BaseModel):
    """远程机器配置模型"""
    machine_id: str
    name: str
    host: str
    port: int
    platform: str  # windows 或 linux
    username: str
    password: Optional[str] = None
    private_key_path: Optional[str] = None
    description: Optional[str] = None
    status: str = MachineStatus.UNKNOWN.value
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    class Config:
        orm_mode = True

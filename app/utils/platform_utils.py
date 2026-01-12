import platform
import os

class PlatformUtils:
    @staticmethod
    def get_platform() -> str:
        """获取当前操作系统平台"""
        return platform.system().lower()
    
    @staticmethod
    def is_windows() -> bool:
        """检查是否为Windows系统"""
        return PlatformUtils.get_platform() == "windows"
    
    @staticmethod
    def is_linux() -> bool:
        """检查是否为Linux系统"""
        return PlatformUtils.get_platform() == "linux"
    
    @staticmethod
    def is_macos() -> bool:
        """检查是否为macOS系统"""
        return PlatformUtils.get_platform() == "darwin"
    
    @staticmethod
    def get_process_identifier() -> str:
        """获取进程标识符（跨平台）"""
        if PlatformUtils.is_windows():
            return "pid"
        else:
            return "pid"
    
    @staticmethod
    def get_path_separator() -> str:
        """获取路径分隔符"""
        return os.sep
    
    @staticmethod
    def get_absolute_path(path: str) -> str:
        """获取绝对路径"""
        return os.path.abspath(path)
    
    @staticmethod
    def join_paths(*paths) -> str:
        """拼接路径"""
        return os.path.join(*paths)

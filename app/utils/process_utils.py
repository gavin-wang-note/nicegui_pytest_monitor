import psutil
from typing import List, Dict, Any
from app.models import ProcessData

class ProcessUtils:
    @staticmethod
    def get_process_info(pid: int) -> Dict[str, Any]:
        """获取进程信息"""
        try:
            process = psutil.Process(pid)
            return {
                "pid": pid,
                "name": process.name(),
                "cpu_percent": process.cpu_percent(interval=0.1),
                "memory_percent": process.memory_percent(),
                "status": process.status(),
                "create_time": process.create_time()
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return None
    
    @staticmethod
    def get_all_processes() -> List[Dict[str, Any]]:
        """获取所有进程信息"""
        processes = []
        for process in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
            try:
                processes.append({
                    "pid": process.info['pid'],
                    "name": process.info['name'],
                    "cpu_percent": process.info['cpu_percent'] or 0.0,
                    "memory_percent": process.info['memory_percent'] or 0.0
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        return processes
    
    @staticmethod
    def get_process_children(pid: int, recursive: bool = True) -> List[int]:
        """获取进程的子进程ID列表"""
        try:
            process = psutil.Process(pid)
            children = process.children(recursive=recursive)
            return [child.pid for child in children]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return []
    
    @staticmethod
    def get_process_tree(pid: int) -> ProcessData:
        """获取进程树结构"""
        try:
            process = psutil.Process(pid)
            process_data = ProcessData(
                pid=pid,
                name=process.name(),
                cpu_percent=process.cpu_percent(interval=0.1),
                memory_percent=process.memory_percent(),
                children=[]
            )
            
            # 递归获取子进程
            for child in process.children(recursive=False):
                child_tree = ProcessUtils.get_process_tree(child.pid)
                process_data.children.append(child_tree)
            
            return process_data
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            raise
    
    @staticmethod
    def calculate_total_resource_usage(pid: int) -> Dict[str, float]:
        """计算进程及其所有子进程的总资源使用情况"""
        try:
            # 获取主进程资源
            process = psutil.Process(pid)
            total_cpu = process.cpu_percent(interval=0.1)
            total_memory = process.memory_percent()
            
            # 递归获取所有子进程资源
            for child_pid in ProcessUtils.get_process_children(pid, recursive=True):
                try:
                    child_process = psutil.Process(child_pid)
                    total_cpu += child_process.cpu_percent(interval=0.05)
                    total_memory += child_process.memory_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
            
            return {
                "total_cpu": total_cpu,
                "total_memory": total_memory
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return {
                "total_cpu": 0.0,
                "total_memory": 0.0
            }
    
    @staticmethod
    def kill_process(pid: int, recursive: bool = True) -> bool:
        """终止进程"""
        try:
            if recursive:
                # 先终止所有子进程
                for child_pid in ProcessUtils.get_process_children(pid, recursive=True):
                    try:
                        psutil.Process(child_pid).terminate()
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            
            # 终止主进程
            psutil.Process(pid).terminate()
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False
    
    @staticmethod
    def is_process_running(pid: int) -> bool:
        """检查进程是否正在运行"""
        try:
            return psutil.pid_exists(pid)
        except:
            return False

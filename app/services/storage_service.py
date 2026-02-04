import sqlite3
import os
import logging
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app.models import SystemData, TestResult, TestRun, TestQueueItem, TestLog
from config.settings import settings

def _setup_logger():
    logger = logging.getLogger('RemoteTestMonitor.StorageService')
    logger.setLevel(logging.DEBUG)
    return logger

logger = _setup_logger()

class StorageService:
    def __init__(self):
        self.db_path = settings.DB_PATH
        self._initialize_db()
    
    def _initialize_db(self):
        """初始化数据库，创建所需的表"""
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            # 创建系统监控数据表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS system_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME NOT NULL,
                    cpu_percent REAL NOT NULL,
                    memory_percent REAL NOT NULL,
                    disk_percent REAL NOT NULL,
                    network_sent INTEGER NOT NULL,
                    network_recv INTEGER NOT NULL,
                    process_id INTEGER,
                    process_name TEXT,
                    node_name TEXT NOT NULL DEFAULT 'localhost'
                )
            ''')
            
            # 创建测试运行表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_runs (
                    run_id TEXT PRIMARY KEY,
                    start_time DATETIME NOT NULL,
                    end_time DATETIME,
                    status TEXT NOT NULL,
                    total_tests INTEGER DEFAULT 0,
                    passed_tests INTEGER DEFAULT 0,
                    failed_tests INTEGER DEFAULT 0,
                    skipped_tests INTEGER DEFAULT 0,
                    test_path TEXT NOT NULL,
                    report_path TEXT,
                    node_name TEXT NOT NULL DEFAULT 'localhost',
                    exit_code INTEGER,
                    execution_type TEXT NOT NULL DEFAULT 'local'
                )
            ''')
            
            # 如果 exit_code 列不存在，添加它
            try:
                cursor.execute('ALTER TABLE test_runs ADD COLUMN exit_code INTEGER')
            except sqlite3.OperationalError:
                pass  # 列已存在
            
            # 如果 execution_type 列不存在，添加它
            try:
                cursor.execute('ALTER TABLE test_runs ADD COLUMN execution_type TEXT NOT NULL DEFAULT "local"')
            except sqlite3.OperationalError:
                pass  # 列已存在
            
            # 创建测试结果表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    test_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    duration REAL NOT NULL,
                    message TEXT,
                    traceback TEXT,
                    timestamp DATETIME NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES test_runs (run_id)
                )
            ''')
            
            # 创建测试队列表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_queue (
                    queue_id TEXT PRIMARY KEY,
                    test_path TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    status TEXT NOT NULL,
                    created_at DATETIME NOT NULL
                )
            ''')
            
            # 创建测试日志表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS test_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    timestamp DATETIME NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES test_runs (run_id)
                )
            ''')
            
            # 创建远程机器配置表
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS remote_machines (
                    machine_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    username TEXT NOT NULL,
                    password TEXT,
                    private_key_path TEXT,
                    description TEXT,
                    status TEXT DEFAULT 'unknown',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME
                )
            ''')
            
            conn.commit()
    
    def save_system_data(self, data: SystemData):
        """保存系统监控数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO system_data 
                (timestamp, cpu_percent, memory_percent, disk_percent, network_sent, network_recv, process_id, process_name, node_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data.timestamp.isoformat(),
                data.cpu_percent,
                data.memory_percent,
                data.disk_percent,
                data.network_sent,
                data.network_recv,
                data.process_id,
                data.process_name,
                data.node_name
            ))
            conn.commit()
    
    def get_system_data(self, start_time: datetime, end_time: datetime, node_name: str = "localhost") -> List[SystemData]:
        """获取指定时间范围的系统监控数据"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            # 检查连接状态
            cursor = conn.cursor()
            
            # 执行查询
            cursor.execute('''
                SELECT timestamp, cpu_percent, memory_percent, disk_percent, network_sent, network_recv, process_id, process_name, node_name
                FROM system_data
                WHERE timestamp BETWEEN ? AND ? AND node_name = ?
                ORDER BY timestamp
            ''', (start_time.isoformat(), end_time.isoformat(), node_name))
            
            rows = cursor.fetchall()
            result = [
                SystemData(
                    timestamp=datetime.fromisoformat(row[0]),
                    cpu_percent=row[1],
                    memory_percent=row[2],
                    disk_percent=row[3],
                    network_sent=row[4],
                    network_recv=row[5],
                    process_id=row[6],
                    process_name=row[7],
                    node_name=row[8]
                ) for row in rows
            ]
            return result
        except sqlite3.DatabaseError as e:
            logger.error(f"获取系统数据时数据库错误: {e}")
            logger.info("尝试检查和修复数据库...")
            
            # 尝试修复数据库
            if conn:
                try:
                    conn.close()
                except:
                    pass
                    
            # 重新连接并运行完整性检查
            try:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('PRAGMA integrity_check')
                check_result = cursor.fetchone()
                
                if check_result and check_result[0] != 'ok':
                    logger.error(f"数据库完整性检查失败: {check_result[0]}")
                    # 返回空列表避免应用崩溃
                    return []
                else:
                    # 完整性检查通过，可能是临时连接问题
                    logger.info("数据库完整性检查通过，重新尝试查询")
                    return []
            except Exception as e2:
                logger.error(f"修复数据库时发生错误: {e2}")
                return []
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    
    def get_running_tests(self) -> List[TestRun]:
        """获取所有正在运行的测试（只返回真正活跃的测试）"""
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(hours=1)  # 1小时前
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code
                FROM test_runs
                WHERE status = 'running'
                  AND start_time > ?
                ORDER BY start_time DESC
            ''', (cutoff_time.isoformat(),))
            
            rows = cursor.fetchall()
            active_tests = []
            
            for row in rows:
                test_run = TestRun(
                    run_id=row[0],
                    start_time=datetime.fromisoformat(row[1]),
                    end_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    status=row[3],
                    total_tests=row[4],
                    passed_tests=row[5],
                    failed_tests=row[6],
                    skipped_tests=row[7],
                    test_path=row[8],
                    report_path=row[9],
                    node_name=row[10],
                    exit_code=row[11]
                )
                
                # 进一步过滤：只保留有实际测试进展的测试
                has_progress = (test_run.total_tests > 0 or 
                              test_run.passed_tests > 0 or 
                              test_run.failed_tests > 0 or 
                              test_run.skipped_tests > 0)
                
                if has_progress or (current_time - test_run.start_time).total_seconds() < 600:  # 10分钟内开始的
                    active_tests.append(test_run)
            
            logger.debug(f"筛选后的活跃测试数量: {len(active_tests)}")
            return active_tests
    
    def save_test_run(self, test_run: TestRun):
        """保存测试运行数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO test_runs 
                (run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code, execution_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                test_run.run_id,
                test_run.start_time.isoformat(),
                test_run.end_time.isoformat() if test_run.end_time else None,
                test_run.status,
                test_run.total_tests,
                test_run.passed_tests,
                test_run.failed_tests,
                test_run.skipped_tests,
                test_run.test_path,
                test_run.report_path,
                test_run.node_name,
                test_run.exit_code,
                test_run.execution_type
            ))
            conn.commit()
    
    def get_test_run(self, run_id: str) -> Optional[TestRun]:
        """获取指定测试运行数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code, execution_type
                FROM test_runs
                WHERE run_id = ?
            ''', (run_id,))
            
            row = cursor.fetchone()
            if row:
                return TestRun(
                    run_id=row[0],
                    start_time=datetime.fromisoformat(row[1]),
                    end_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    status=row[3],
                    total_tests=row[4],
                    passed_tests=row[5],
                    failed_tests=row[6],
                    skipped_tests=row[7],
                    test_path=row[8],
                    report_path=row[9],
                    node_name=row[10],
                    exit_code=row[11],
                    execution_type=row[12] if row[12] else "local"
                )
            return None
    
    def save_test_result(self, result: TestResult):
        """保存测试结果"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO test_results 
                (run_id, test_id, name, status, duration, message, traceback, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                result.test_id,
                result.test_id,
                result.name,
                result.status,
                result.duration,
                result.message,
                result.traceback,
                result.timestamp.isoformat()
            ))
            conn.commit()
    
    def save_test_queue_item(self, item: TestQueueItem):
        """保存测试队列项"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO test_queue 
                (queue_id, test_path, priority, status, created_at)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                item.queue_id,
                item.test_path,
                item.priority,
                item.status,
                item.created_at.isoformat()
            ))
            conn.commit()
    
    def update_test_queue_item(self, queue_id: str, status: str):
        """更新测试队列项状态"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE test_queue
                SET status = ?
                WHERE queue_id = ?
            ''', (status, queue_id))
            conn.commit()
    
    def get_test_queue(self) -> List[TestQueueItem]:
        """获取测试队列"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT queue_id, test_path, priority, status, created_at
                FROM test_queue
                ORDER BY priority DESC, created_at
            ''')
            
            rows = cursor.fetchall()
            return [
                TestQueueItem(
                    queue_id=row[0],
                    test_path=row[1],
                    priority=row[2],
                    status=row[3],
                    created_at=datetime.fromisoformat(row[4])
                ) for row in rows
            ]
    
    def save_test_log(self, log: TestLog):
        """保存测试日志"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO test_logs 
                (run_id, timestamp, level, message)
                VALUES (?, ?, ?, ?)
            ''', (
                log.run_id,
                log.timestamp.isoformat(),
                log.level,
                log.message
            ))
            conn.commit()
    
    def get_test_logs(self, run_id: str) -> List[TestLog]:
        """获取指定测试运行的日志"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT run_id, timestamp, level, message
                FROM test_logs
                WHERE run_id = ?
                ORDER BY timestamp
            ''', (run_id,))
            
            rows = cursor.fetchall()
            return [
                TestLog(
                    run_id=row[0],
                    timestamp=datetime.fromisoformat(row[1]),
                    level=row[2],
                    message=row[3]
                ) for row in rows
            ]
    
    def get_all_test_runs(self, limit: int = 100) -> List[TestRun]:
        """获取所有测试运行记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code, execution_type
                FROM test_runs
                ORDER BY start_time DESC
                LIMIT ?
            ''', (limit,))
            
            rows = cursor.fetchall()
            return [
                TestRun(
                    run_id=row[0],
                    start_time=datetime.fromisoformat(row[1]),
                    end_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    status=row[3],
                    total_tests=row[4],
                    passed_tests=row[5],
                    failed_tests=row[6],
                    skipped_tests=row[7],
                    test_path=row[8],
                    report_path=row[9],
                    node_name=row[10],
                    exit_code=row[11],
                    execution_type=row[12] if row[12] else "local"
                )
                for row in rows
            ]
    
    def get_test_runs_by_time_range(self, start_time: datetime, end_time: datetime) -> List[TestRun]:
        """根据时间范围获取测试运行记录"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code, execution_type
                FROM test_runs
                WHERE start_time BETWEEN ? AND ?
                ORDER BY start_time ASC
            ''', (start_time.isoformat(), end_time.isoformat()))
            
            rows = cursor.fetchall()
            return [
                TestRun(
                    run_id=row[0],
                    start_time=datetime.fromisoformat(row[1]),
                    end_time=datetime.fromisoformat(row[2]) if row[2] else None,
                    status=row[3],
                    total_tests=row[4],
                    passed_tests=row[5],
                    failed_tests=row[6],
                    skipped_tests=row[7],
                    test_path=row[8],
                    report_path=row[9],
                    node_name=row[10],
                    exit_code=row[11],
                    execution_type=row[12] if row[12] else "local"
                )
                for row in rows
            ]
    
    def delete_test_run(self, run_id: str) -> bool:
        """删除指定测试运行记录"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 删除相关的测试日志
                cursor.execute('DELETE FROM test_logs WHERE run_id = ?', (run_id,))
                
                # 删除相关的测试结果
                cursor.execute('DELETE FROM test_results WHERE run_id = ?', (run_id,))
                
                # 删除测试运行记录
                cursor.execute('DELETE FROM test_runs WHERE run_id = ?', (run_id,))
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"删除测试运行记录失败: {str(e)}")
            return False
    
    def delete_test_logs(self, run_id: str) -> bool:
        """删除指定测试运行的所有日志"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM test_logs WHERE run_id = ?', (run_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"删除测试日志失败: {str(e)}")
            return False
    
    def delete_all_test_runs(self) -> bool:
        """删除所有测试运行记录、日志和结果"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 删除所有测试日志
                cursor.execute('DELETE FROM test_logs')
                
                # 删除所有测试结果
                cursor.execute('DELETE FROM test_results')
                
                # 删除所有测试运行记录
                cursor.execute('DELETE FROM test_runs')
                
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"删除所有测试运行记录失败: {str(e)}")
            return False
    
    def export_to_csv(self, table_name: str, file_path: str, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None):
        """导出数据到CSV文件"""
        import csv
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            
            query = f"SELECT * FROM {table_name}"
            params = []
            
            if start_time and end_time:
                query += " WHERE timestamp BETWEEN ? AND ?"
                params.extend([start_time.isoformat(), end_time.isoformat()])
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            headers = [description[0] for description in cursor.description]
            
            with open(file_path, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(headers)
                writer.writerows(rows)
    
    def save_remote_machine(self, machine) -> bool:
        """保存远程机器配置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO remote_machines 
                    (machine_id, name, host, port, platform, username, password, private_key_path, description, status, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    machine.machine_id,
                    machine.name,
                    machine.host,
                    machine.port,
                    machine.platform,
                    machine.username,
                    machine.password,
                    machine.private_key_path,
                    machine.description,
                    machine.status,
                    machine.created_at,
                    machine.updated_at
                ))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"保存远程机器配置失败: {str(e)}")
            return False
    
    def get_remote_machine(self, machine_id: str):
        """获取指定远程机器配置"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT machine_id, name, host, port, platform, username, password, private_key_path, description, status, created_at, updated_at
                FROM remote_machines
                WHERE machine_id = ?
            ''', (machine_id,))
            
            row = cursor.fetchone()
            if row:
                from app.models import RemoteMachine
                return RemoteMachine(
                    machine_id=row[0],
                    name=row[1],
                    host=row[2],
                    port=row[3],
                    platform=row[4],
                    username=row[5],
                    password=row[6],
                    private_key_path=row[7],
                    description=row[8],
                    status=row[9],
                    created_at=row[10],
                    updated_at=row[11]
                )
            return None
    
    def get_all_remote_machines(self) -> List:
        """获取所有远程机器配置"""
        from app.models import RemoteMachine
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT machine_id, name, host, port, platform, username, password, private_key_path, description, status, created_at, updated_at
                FROM remote_machines
                ORDER BY name
            ''')
            
            rows = cursor.fetchall()
            return [
                RemoteMachine(
                    machine_id=row[0],
                    name=row[1],
                    host=row[2],
                    port=row[3],
                    platform=row[4],
                    username=row[5],
                    password=row[6] if row[6] else None,
                    private_key_path=row[7] if row[7] else None,
                    description=row[8] if row[8] else None,
                    status=row[9],
                    created_at=row[10],
                    updated_at=row[11]
                ) for row in rows
            ]
    
    def delete_remote_machine(self, machine_id: str) -> bool:
        """删除远程机器配置"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM remote_machines WHERE machine_id = ?', (machine_id,))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"删除远程机器配置失败: {str(e)}")
            return False
    
    def check_machine_exists(self, host: str, port: int, username: str) -> bool:
        """检查机器配置是否已存在"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT COUNT(*) FROM remote_machines
                WHERE host = ? AND port = ? AND username = ?
            ''', (host, port, username))
            
            count = cursor.fetchone()[0]
            return count > 0
    
    def update_machine_status(self, machine_id: str, status: str) -> bool:
        """更新机器状态"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    UPDATE remote_machines
                    SET status = ?, updated_at = ?
                    WHERE machine_id = ?
                ''', (status, datetime.now().isoformat(), machine_id))
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"更新机器状态失败: {str(e)}")
            return False

# 创建全局存储服务实例
storage_service = StorageService()

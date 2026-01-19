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
                    exit_code INTEGER
                )
            ''')
            
            # 如果 exit_code 列不存在，添加它
            try:
                cursor.execute('ALTER TABLE test_runs ADD COLUMN exit_code INTEGER')
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
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT timestamp, cpu_percent, memory_percent, disk_percent, network_sent, network_recv, process_id, process_name, node_name
                FROM system_data
                WHERE timestamp BETWEEN ? AND ? AND node_name = ?
                ORDER BY timestamp
            ''', (start_time.isoformat(), end_time.isoformat(), node_name))
            
            rows = cursor.fetchall()
            return [
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
                (run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                test_run.exit_code
            ))
            conn.commit()
    
    def get_test_run(self, run_id: str) -> Optional[TestRun]:
        """获取指定测试运行数据"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name, exit_code
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
                    exit_code=row[11]
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
                SELECT run_id, start_time, end_time, status, total_tests, passed_tests, failed_tests, skipped_tests, test_path, report_path, node_name
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
                    node_name=row[10]
                ) for row in rows
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

# 创建全局存储服务实例
storage_service = StorageService()

from nicegui import ui, app
from typing import List, Dict, Any
from datetime import datetime, timedelta
from app.models import SystemData
from app.services import monitor_service, storage_service
from config.settings import settings
import logging
import time

class SystemMonitor:
    def __init__(self):
        self.cpu_data = []
        self.memory_data = []
        self.disk_data = []
        self.network_sent_data = []
        self.network_recv_data = []
        self.max_data_points = 100  # 最大数据点数量
        self.current_interval = monitor_service.get_interval()

    def create_dashboard(self):
        """创建系统监控仪表板"""
        with ui.card().classes('w-full p-4'):
            ui.label('系统监控').classes('text-3xl font-bold mb-6 text-gray-700')

            # 监控频率调整 - 现代化样式
            with ui.card().classes('mb-6 bg-blue-50 border border-blue-100 rounded-lg'):
                with ui.row().classes('items-center justify-between p-4'):
                    self.interval_label = ui.label(f'监控频率: {self.current_interval}秒').classes('text-lg font-medium text-blue-700')
                    with ui.column().classes('flex-grow items-center ml-6'):
                        with ui.row().classes('w-full items-center justify-between mb-1 min-w-64'):
                            ui.label('慢').classes('text-sm text-gray-500')
                            ui.label('快').classes('text-sm text-gray-500')
                        with ui.row().classes('w-full items-center justify-center mb-1 min-w-64'):
                            ui.slider(
                                min=settings.MIN_MONITOR_INTERVAL,
                                max=settings.MAX_MONITOR_INTERVAL,
                                value=self.current_interval,
                                on_change=self._update_interval,
                            ).props('color=blue').classes('w-full')
            
            # 系统资源概览卡片 - 现代化样式
            with ui.grid(columns=2).classes('w-full gap-4 mb-6'):
                # CPU 使用率卡片
                with ui.card().classes('w-full bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-all duration-200'):
                    ui.label('CPU 使用率').classes('text-lg font-semibold mb-3 text-gray-700')
                    self.cpu_value = ui.label('0.0%').classes('text-4xl font-bold text-center text-blue-500')
                    self.cpu_progress = ui.linear_progress(value=0).props('color=blue').classes('mt-3')
                
                # 内存使用率卡片
                with ui.card().classes('w-full bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-all duration-200'):
                    ui.label('内存使用率').classes('text-lg font-semibold mb-3 text-gray-700')
                    self.memory_value = ui.label('0.0%').classes('text-4xl font-bold text-center text-green-500')
                    self.memory_progress = ui.linear_progress(value=0).props('color=green').classes('mt-3')
                
                # 磁盘使用率卡片
                with ui.card().classes('w-full bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-all duration-200'):
                    ui.label('磁盘使用率').classes('text-lg font-semibold mb-3 text-gray-700')
                    self.disk_value = ui.label('0.0%').classes('text-4xl font-bold text-center text-orange-500')
                    self.disk_progress = ui.linear_progress(value=0).props('color=orange').classes('mt-3')
                
                # 网络流量卡片
                with ui.card().classes('w-full bg-white border border-gray-200 rounded-lg shadow-sm hover:shadow-md transition-all duration-200'):
                    ui.label('网络流量').classes('text-lg font-semibold mb-3 text-gray-700')
                    with ui.row().classes('justify-between mt-2'):
                        self.network_sent_value = ui.label('发送: 0 KB/s').classes('text-base text-purple-500')
                        self.network_recv_value = ui.label('接收: 0 KB/s').classes('text-base text-indigo-500')
            
            # 实时图表
            with ui.tabs().classes('w-full mb-2') as tabs:
                cpu_tab = ui.tab('CPU 使用率')
                memory_tab = ui.tab('内存使用率')
                disk_tab = ui.tab('磁盘使用率')
                network_tab = ui.tab('网络流量')
            
            with ui.tab_panels(tabs, value=cpu_tab).classes('w-full'):
                # CPU 使用率图表
                with ui.tab_panel(cpu_tab):
                    self.cpu_chart = ui.echart({
                        'xAxis': {
                            'type': 'category',
                            'boundaryGap': False,
                            'data': [item[0] for item in self.cpu_data]
                        },
                        'yAxis': {
                            'type': 'value',
                            'axisLabel': {
                                'formatter': '{value} %'
                            }
                        },
                        'series': [{
                            'name': 'CPU',
                            'type': 'line',
                            'data': [item[1] for item in self.cpu_data],
                            'smooth': True,
                            'areaStyle': {}
                        }],
                        'tooltip': {
                            'trigger': 'axis',
                            'formatter': '{b0}: {c0}%'
                        }
                    }).classes('w-full h-64')
                
                # 内存使用率图表
                with ui.tab_panel(memory_tab):
                    self.memory_chart = ui.echart({
                        'xAxis': {
                            'type': 'category',
                            'boundaryGap': False,
                            'data': [item[0] for item in self.memory_data]
                        },
                        'yAxis': {
                            'type': 'value',
                            'axisLabel': {
                                'formatter': '{value} %'
                            }
                        },
                        'series': [{
                            'name': 'Memory',
                            'type': 'line',
                            'data': [item[1] for item in self.memory_data],
                            'smooth': True,
                            'areaStyle': {}
                        }],
                        'tooltip': {
                            'trigger': 'axis',
                            'formatter': '{b0}: {c0}%'
                        }
                    }).classes('w-full h-64')
                
                # 磁盘使用率图表
                with ui.tab_panel(disk_tab):
                    self.disk_chart = ui.echart({
                        'xAxis': {
                            'type': 'category',
                            'boundaryGap': False,
                            'data': [item[0] for item in self.disk_data]
                        },
                        'yAxis': {
                            'type': 'value',
                            'axisLabel': {
                                'formatter': '{value} %'
                            }
                        },
                        'series': [{
                            'name': 'Disk',
                            'type': 'line',
                            'data': [item[1] for item in self.disk_data],
                            'smooth': True,
                            'areaStyle': {}
                        }],
                        'tooltip': {
                            'trigger': 'axis',
                            'formatter': '{b0}: {c0}%'
                        }
                    }).classes('w-full h-64')
                
                # 网络流量图表
                with ui.tab_panel(network_tab):
                    self.network_chart = ui.echart({
                        'xAxis': {
                            'type': 'category',
                            'boundaryGap': False,
                            'data': [item[0] for item in self.network_sent_data]
                        },
                        'yAxis': {
                            'type': 'value',
                            'axisLabel': {
                                'formatter': '{value} KB/s'
                            }
                        },
                        'series': [
                            {
                                'name': 'Sent',
                                'type': 'line',
                                'data': [item[1] for item in self.network_sent_data],
                                'smooth': True
                            },
                            {
                                'name': 'Received',
                                'type': 'line',
                                'data': [item[1] for item in self.network_recv_data],
                                'smooth': True
                            }
                        ],
                        'tooltip': {
                            'trigger': 'axis',
                            'formatter': '{b0}<br/>{a0}: {c0} KB/s<br/>{a1}: {c1} KB/s'
                        }
                    }).classes('w-full h-64')
        
        # 初始化数据
        self._initialize_data()
        # 注册数据更新回调
        monitor_service.register_system_data_callback(self._update_data)
    
    def _initialize_data(self):
        """初始化历史数据"""
        # 获取最近10分钟的数据
        end_time = datetime.now()
        start_time = end_time - timedelta(minutes=10)
        
        # 从数据库获取历史数据
        historical_data = storage_service.get_system_data(start_time, end_time)
        
        # 初始化图表数据
        for data in historical_data:
            self._add_data_point(data)
        
        # 更新当前值
        if historical_data:
            latest_data = historical_data[-1]
            self._update_current_values(latest_data)
    
    def _update_data(self, system_data: SystemData):
        """更新系统数据"""
        self._add_data_point(system_data)
        self._update_current_values(system_data)
    
    def _add_data_point(self, system_data: SystemData):
        """添加数据点到图表"""
        timestamp = system_data.timestamp.strftime('%H:%M:%S')
        
        # 添加CPU数据
        self.cpu_data.append((timestamp, system_data.cpu_percent))
        if len(self.cpu_data) > self.max_data_points:
            self.cpu_data.pop(0)
        
        # 更新CPU图表 - 添加错误处理
        if hasattr(self, 'cpu_chart') and self.cpu_chart:
            try:
                self.cpu_chart.options['xAxis']['data'] = [item[0] for item in self.cpu_data]
                self.cpu_chart.options['series'][0]['data'] = [item[1] for item in self.cpu_data]
            except Exception as e:
                # 记录错误但不中断更新过程
                logging.error(f"更新CPU图表时出错: {str(e)}")
        
        # 添加内存数据
        self.memory_data.append((timestamp, system_data.memory_percent))
        if len(self.memory_data) > self.max_data_points:
            self.memory_data.pop(0)
        
        # 更新内存图表 - 添加错误处理
        if hasattr(self, 'memory_chart') and self.memory_chart:
            try:
                self.memory_chart.options['xAxis']['data'] = [item[0] for item in self.memory_data]
                self.memory_chart.options['series'][0]['data'] = [item[1] for item in self.memory_data]
            except Exception as e:
                # 记录错误但不中断更新过程
                logging.error(f"更新内存图表时出错: {str(e)}")
        
        # 添加磁盘数据
        self.disk_data.append((timestamp, system_data.disk_percent))
        if len(self.disk_data) > self.max_data_points:
            self.disk_data.pop(0)
        
        # 更新磁盘图表 - 添加错误处理
        if hasattr(self, 'disk_chart') and self.disk_chart:
            try:
                self.disk_chart.options['xAxis']['data'] = [item[0] for item in self.disk_data]
                self.disk_chart.options['series'][0]['data'] = [item[1] for item in self.disk_data]
            except Exception as e:
                # 记录错误但不中断更新过程
                logging.error(f"更新磁盘图表时出错: {str(e)}")
        
        # 添加网络数据（转换为KB/s）
        sent_kb = system_data.network_sent / 1024
        recv_kb = system_data.network_recv / 1024
        self.network_sent_data.append((timestamp, sent_kb))
        self.network_recv_data.append((timestamp, recv_kb))
        
        if len(self.network_sent_data) > self.max_data_points:
            self.network_sent_data.pop(0)
            self.network_recv_data.pop(0)
        
        # 更新网络图表 - 添加错误处理
        if hasattr(self, 'network_chart') and self.network_chart:
            try:
                self.network_chart.options['xAxis']['data'] = [item[0] for item in self.network_sent_data]
                self.network_chart.options['series'][0]['data'] = [item[1] for item in self.network_sent_data]
                self.network_chart.options['series'][1]['data'] = [item[1] for item in self.network_recv_data]
            except Exception as e:
                # 记录错误但不中断更新过程
                logging.error(f"更新网络图表时出错: {str(e)}")
    
    def _update_current_values(self, system_data: SystemData):
        """更新当前值显示"""
        # 更新文本值 - 添加错误处理
        try:
            self.cpu_value.text = f'{system_data.cpu_percent:.1f}%'
            self.memory_value.text = f'{system_data.memory_percent:.1f}%'
            self.disk_value.text = f'{system_data.disk_percent:.1f}%'
            
            # 转换网络流量为KB/s
            sent_kb = system_data.network_sent / 1024
            recv_kb = system_data.network_recv / 1024
            self.network_sent_value.text = f'发送: {sent_kb:.1f} KB/s'
            self.network_recv_value.text = f'接收: {recv_kb:.1f} KB/s'
        except Exception as e:
            logging.error(f"更新系统监控文本值时出错: {str(e)}")
        
        # 更新进度条 - 重要：进度条值需要除以100
        try:
            self.cpu_progress.value = system_data.cpu_percent / 100
            self.memory_progress.value = system_data.memory_percent / 100
            self.disk_progress.value = system_data.disk_percent / 100
        except Exception as e:
            logging.error(f"更新系统监控进度条时出错: {str(e)}")
    
    def _update_interval(self, event):
        """更新监控频率"""
        new_interval = int(event.value)
        monitor_service.set_interval(new_interval)
        self.current_interval = new_interval
        # 更新显示的频率值 - 使用我们存储的标签引用
        self.interval_label.text = f'监控频率: {new_interval}秒'

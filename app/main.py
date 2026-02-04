from nicegui import ui, app
from app.authentication import auth
from app.dashboards import SystemMonitor, TestMonitor
from app.services import monitor_service, storage_service
from config.settings import settings
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any

class RemoteTestMonitorApp:
    def __init__(self):
        self.system_monitor = SystemMonitor()
        self.test_monitor = TestMonitor()
        self.log_dir = settings.LOG_PATH
        os.makedirs(self.log_dir, exist_ok=True)
        
        self._setup_logging()
        self._setup_exception_handler()
    
    def _setup_logging(self):
        """设置日志记录"""
        log_file = os.path.join(self.log_dir, f"app_{datetime.now().strftime('%Y%m%d')}.log")
        
        logging.basicConfig(
            level=logging.DEBUG,
            format=settings.LOG_FORMAT,
            datefmt=settings.LOG_DATE_FORMAT,
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
            ]
        )
        
        self.logger = logging.getLogger('RemoteTestMonitor')
        self.logger.info("应用日志系统已启动")
    
    def _setup_exception_handler(self):
        """设置全局异常处理，防止NiceGUI并发问题导致应用崩溃"""
        def handle_exception(e: Exception):
            try:
                self.logger.error(f"捕获到异常: {type(e).__name__}: {str(e)}")
            except Exception:
                pass
        
        app.on_exception(handle_exception)
    
    def _create_log_panel(self):
        """创建日志面板"""
        with ui.card().classes('w-full p-4'):
            ui.label('系统日志').classes('text-2xl font-bold mb-4 text-gray-700')
            
            # 日志控制区 - 现代化样式
            with ui.card().classes('mb-4 bg-blue-50 border border-blue-100 rounded-lg'):
                with ui.row().classes('items-center justify-between p-4 flex-wrap gap-4'):
                    # 左侧：自动刷新开关
                    with ui.row().classes('items-center'):
                        self.auto_refresh = ui.switch('自动刷新', value=False)
                    
                    # 中间：日志级别筛选
                    with ui.row().classes('items-center'):
                        ui.label('级别:').classes('text-sm text-gray-600 mr-2')
                        self.log_level = ui.select(
                            ['全部', 'DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                            value='全部',
                            on_change=self._refresh_logs
                        ).classes('w-24')
                    
                    # 右侧：刷新间隔设置（根据自动刷新开关显示/隐藏）
                    with ui.row().classes('items-center'):
                        ui.label('刷新:').classes('text-sm text-gray-600 mr-2')
                        with ui.row().classes('items-center') as self.refresh_slider_container:
                            self.refresh_interval = ui.slider(
                                min=1, max=30, value=2, step=1, 
                                on_change=self._on_interval_change,
                            ).props('color=blue').classes('w-32')
                            self.interval_label = ui.label('2秒').classes('text-sm text-blue-600 font-bold')
                    
                    # 监听自动刷新开关来控制滑块显示/隐藏
                    self.auto_refresh.on_value_change(self._toggle_refresh_slider)
                    
                    # 根据自动刷新的初始值设置滑块的可见性
                    self.refresh_slider_container.visible = self.auto_refresh.value
                    
                    # 按钮组
                    with ui.row().classes('items-center'):
                        ui.button('刷新日志', on_click=self._refresh_logs).props('color=primary').classes('mr-2')
                        ui.button('清空显示', on_click=self._clear_logs).props('color=negative')
            
            # 日志显示区域
            self.log_output = ui.log().classes('w-full h-96')
            
            # 日志信息显示
            with ui.row().classes('justify-between mt-2 text-sm text-gray-500'):
                self.log_info = ui.label('准备就绪')
                self.log_time = ui.label('')
            
            # 初始化日志内容
            self._refresh_logs()
            
            # 设置自动刷新定时器 - 确保只有一个定时器实例
            self.logger.debug(f"正在创建日志自动刷新定时器，间隔: {self.refresh_interval.value}秒，自动刷新开关状态: {self.auto_refresh.value}")
            
            # 移除旧的定时器
            if hasattr(self, 'log_timer') and self.log_timer:
                self.logger.debug(f"移除旧的日志自动刷新定时器")
                self.log_timer.cancel()
                
            # 创建新的定时器，始终运行，但只在开关开启时执行刷新操作
            self.log_timer = ui.timer(interval=self.refresh_interval.value, callback=self._auto_refresh_logs, active=True)
            self.logger.debug(f"新的日志自动刷新定时器已创建并启动")
    
    def _on_interval_change(self, e):
        """刷新间隔变化时的处理"""
        self.interval_label.text = f'{e.value}秒'
        if hasattr(self, 'log_timer') and self.log_timer:
            self.log_timer.interval = e.value

    def _toggle_refresh_slider(self, e):
        """控制刷新滑块的显示/隐藏"""
        visible = e.value
        self.refresh_slider_container.visible = visible
        
        # 定时器始终运行，由_auto_refresh_logs方法内部的条件判断控制是否执行刷新操作
        self.logger.debug(f"自动刷新状态切换为: {'开启' if visible else '关闭'}")
    
    def _auto_refresh_logs(self):
        """自动刷新日志"""
        try:
            if self.auto_refresh.value:
                self.logger.debug(f"执行日志自动刷新，当前时间: {datetime.now()}")
                self._refresh_logs()
        except Exception as e:
            self.logger.error(f"自动刷新日志失败: {str(e)}")
            self.log_output.push(f'自动刷新日志失败: {str(e)}')
    
    def _find_latest_log_file(self):
        """查找最近的日志文件"""
        try:
            if not os.path.exists(self.log_dir):
                return None
            
            log_files = [f for f in os.listdir(self.log_dir) if f.startswith('app_') and f.endswith('.log')]
            if not log_files:
                return None
            
            # 按文件名排序，获取最新的日志文件
            log_files.sort(reverse=True)
            return os.path.join(self.log_dir, log_files[0])
        except Exception as e:
            self.logger.error(f"查找日志文件失败: {str(e)}")
            return None
    
    def _refresh_logs(self):
        """刷新日志内容"""
        try:
            # 获取当前日志文件路径
            today = datetime.now().strftime('%Y%m%d')
            log_file = os.path.join(self.log_dir, f"app_{today}.log")
            
            # 检查今天的日志文件是否存在，如果不存在则查找最近的日志文件
            if not os.path.exists(log_file):
                log_file = self._find_latest_log_file()
                if not log_file:
                    self.log_output.push('日志文件不存在')
                    self.log_info.text = '日志文件不存在'
                    return
                else:
                    self.log_info.text = f'显示历史日志: {os.path.basename(log_file)}'
            
            # 读取日志内容 - 优化性能
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    # 检查文件大小，对于大文件只读取最后5000行
                    f.seek(0, 2)
                    file_size = f.tell()
                    
                    # 如果文件大于5MB，只读取最后5000行
                    if file_size > 5 * 1024 * 1024:
                        lines = []
                        buffer = ''
                        f.seek(max(0, file_size - 500000))  # 从文件末尾附近开始读取
                        
                        while True:
                            chunk = f.read(1024)
                            if not chunk:
                                break
                            buffer += chunk
                            
                            # 按行分割
                            if '\n' in buffer:
                                parts = buffer.split('\n')
                                lines.extend(parts[:-1])
                                buffer = parts[-1]
                        
                        if buffer:
                            lines.append(buffer)
                            
                        # 取最后5000行
                        log_content = '\n'.join(lines[-5000:])
                    else:
                        # 小文件直接读取全部
                        f.seek(0)
                        log_content = f.read()
            except Exception as e:
                self.logger.error(f"读取日志文件失败: {str(e)}")
                self.log_output.push(f'读取日志文件失败: {str(e)}')
                self.log_info.text = '读取日志失败'
                return
            
            # 根据级别筛选日志
            level_filter = self.log_level.value
            if level_filter != '全部':
                # 优化的日志级别筛选
                filtered_lines = []
                for line in log_content.split('\n'):
                    if line and level_filter in line:
                        filtered_lines.append(line)
                log_content = '\n'.join(filtered_lines)
            
            # 更新日志显示
            self.log_output.clear()
            self.log_output.push(log_content)
            
            # 更新日志信息
            log_lines = len([l for l in log_content.split('\n') if l.strip()])
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            self.log_info.text = f'显示 {log_lines} 行日志 - 自动刷新: {self.auto_refresh.value} 间隔: {self.refresh_interval.value}秒'
            self.log_time.text = f'最后更新: {current_time}'
            self.logger.debug(f"日志刷新完成，行: {log_lines}，时间: {current_time}")
            
        except Exception as e:
            self.logger.error(f"读取日志文件失败: {str(e)}")
            self.log_output.push(f'读取日志文件失败: {str(e)}')
            self.log_info.text = '读取日志失败'
    
    def _clear_logs(self):
        """清空日志显示"""
        self.log_output.clear()
        self.log_info.text = '日志显示已清空'
    
    def run(self):
        """运行应用"""
        # 启动系统监控服务
        monitor_service.start_monitoring()
        
        # 定义报告文件访问路由
        @ui.page('/report/{run_id}')
        def report_page(run_id: str):
            """报告查看页面"""
            # 获取测试运行信息
            test_run = storage_service.get_test_run(run_id)
            if not test_run or not test_run.report_path:
                ui.label('报告不存在').classes('text-red-500 text-xl')
                return
            
            # 检查报告文件是否存在
            report_path = test_run.report_path
            if not os.path.exists(report_path):
                ui.label('报告文件不存在').classes('text-red-500 text-xl')
                return
            
            # 设置页面标题
            ui.page_title = f'测试报告 - {run_id}'
            
            # 读取报告文件内容
            try:
                with open(report_path, 'r', encoding='utf-8') as f:
                    report_content = f.read()
                
                # 显示报告内容 (使用add_body_html处理包含script标签的HTML)
                ui.add_body_html(report_content)
                
            except Exception as e:
                ui.label(f'读取报告失败: {str(e)}').classes('text-red-500 text-xl')
        
        # 定义页面路由
        @ui.page('/')
        def index_page():
            """应用首页"""
            if auth.is_authenticated():
                # 已认证，显示主界面
                app.page_title = settings.APP_NAME
                
                with ui.header(elevated=True).classes('items-center justify-between'):
                    ui.label(settings.APP_NAME).classes('text-xl font-bold')
                    ui.button('登出', on_click=self._handle_logout)
                
                # 通知区域 - 使用模态对话框
                self.notification_area = None
                
                # 创建通知模态区域 - 修复黄色背景导致的文字清晰度问题
                with ui.dialog() as self.notification_dialog:
                    with ui.card().classes('p-6 bg-white border border-gray-300 rounded-lg shadow-lg'):
                        self.notification_text = ui.label('').classes('text-gray-800 text-base leading-relaxed mb-4')
                        with ui.row().classes('w-full justify-end mt-4'):
                            ui.button('确定', on_click=self._close_notification).props('flat color=primary')
                
                def show_notification(message, timeout=3.0):
                    """显示通知"""
                    self.notification_text.text = message
                    self.notification_dialog.open()
                    
                    # 自动关闭
                    if timeout > 0:
                        ui.timer(interval=timeout, callback=self._close_notification, once=True)
                
                # 保存通知函数
                ui.show_notification = show_notification
                
                with ui.footer().classes('text-center text-gray-500 text-sm'):
                    ui.label(f'{settings.APP_NAME} v{settings.APP_VERSION}')
                
                with ui.page_sticky(position='bottom-right', x_offset=20, y_offset=20):
                    ui.button(on_click=lambda: self._show_welcome_message(), icon='info')
                
                # 主内容区域
                with ui.row().classes('w-full items-center mb-2'):
                    ui.label('📊').classes('text-2xl')
                    ui.label('远程测试监控系统').classes('text-xl font-bold text-gray-800')
                
                with ui.tabs().classes('w-full') as tabs:
                    system_tab = ui.tab('🖥️ 系统监控').classes('text-base font-medium')
                    test_tab = ui.tab('🧪 测试监控').classes('text-base font-medium')
                    log_tab = ui.tab('📋 日志').classes('text-base font-medium')
                
                with ui.tab_panels(tabs, value=system_tab).classes('w-full'):
                    # 系统监控面板
                    with ui.tab_panel(system_tab):
                        self.system_monitor.create_dashboard()
                    
                    # 测试监控面板
                    with ui.tab_panel(test_tab):
                        self.test_monitor.create_dashboard()
                    
                    # 日志面板
                    with ui.tab_panel(log_tab):
                        self._create_log_panel()
            else:
                # 未认证，显示登录界面
                self._show_login_page()
        
        # 运行 NiceGUI 应用
        ui.run(
            title=settings.APP_NAME,
            host=settings.HOST,
            port=settings.PORT,
            show=False
        )
    
    def _show_login_page(self):
        """显示登录页面"""
        
        with ui.card().classes('w-96 mx-auto mt-20'):
            ui.label('远程测试监控系统').classes('text-xl font-bold mb-4 text-center')
            
            username_input = ui.input(label='用户名').classes('mb-2')
            password_input = ui.input(label='密码', password=True).classes('mb-4')
            
            error_label = ui.label('').classes('text-red-500 mb-2')
            
            def handle_login():
                self.logger.info(f"尝试登录，用户名: {username_input.value}")
                if auth.login(username_input.value, password_input.value):
                    # 登录成功，刷新页面
                    self.logger.info(f"用户 {username_input.value} 登录成功")
                    ui.notify('登录成功！')
                    ui.navigate.to('/')
                else:
                    error_label.text = '用户名或密码错误'
                    self.logger.warning(f"用户 {username_input.value} 登录失败")
            
            ui.button('登录', on_click=handle_login).classes('w-full')
    
    def _close_notification(self):
        """关闭通知"""
        self.notification_dialog.close()
    
    def _show_welcome_message(self):
        """显示欢迎消息"""
        ui.show_notification('欢迎使用远程测试监控系统！', 3.0)
    
    def _handle_logout(self):
        """处理用户登出"""
        username = auth.get_username()
        auth.logout()
        ui.notify('已成功登出')
        if username:
            self.logger.info(f"用户 {username} 登出成功")
        else:
            self.logger.info("用户登出成功")
        ui.navigate.to('/login')

# 创建应用实例
app_instance = RemoteTestMonitorApp()

# 运行应用（如果直接执行该文件）
if __name__ in {"__main__", "__mp_main__"}:
    app_instance.run()

from nicegui import ui, app
from app.authentication import auth
from app.dashboards import SystemMonitor, TestMonitor
from app.services import monitor_service
from config.settings import settings
import logging
import os
import time
from datetime import datetime

class RemoteTestMonitorApp:
    def __init__(self):
        self.system_monitor = SystemMonitor()
        self.test_monitor = TestMonitor()
        # 创建日志目录
        self.log_dir = settings.LOG_PATH
        os.makedirs(self.log_dir, exist_ok=True)
        
        # 配置日志
        self._setup_logging()
    
    def _setup_logging(self):
        """设置日志记录"""
        # 创建日志文件路径
        log_file = os.path.join(self.log_dir, f"app_{datetime.now().strftime('%Y%m%d')}.log")
        
        # 配置日志记录器
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8')
            ]
        )
        
        # 获取应用日志记录器
        self.logger = logging.getLogger('RemoteTestMonitor')
        self.logger.info("应用日志系统已启动")
    
    def _create_log_panel(self):
        """创建日志面板"""
        with ui.card().classes('w-full'):
            ui.label('系统日志').classes('text-xl font-bold mb-4')
            
            # 日志控制区
            with ui.row().classes('w-full mb-4'):
                # 自动刷新开关
                self.auto_refresh = ui.switch('自动刷新', value=True).classes('mr-4')
                
                # 日志级别筛选
                self.log_level = ui.select(['全部', 'DEBUG', 'INFO', 'WARNING', 'ERROR'], value='全部').classes('mr-4')
                
                # 刷新按钮
                ui.button('刷新日志', on_click=self._refresh_logs).classes('mr-2')
                
                # 清空日志按钮
                ui.button('清空显示', on_click=self._clear_logs)
            
            # 日志显示区域
            self.log_output = ui.log().classes('w-full h-96')
            
            # 日志信息显示
            with ui.row().classes('justify-between mt-2 text-sm text-gray-500'):
                self.log_info = ui.label('准备就绪')
                self.log_time = ui.label('')
            
            # 初始化日志内容
            self._refresh_logs()
            
            # 设置自动刷新定时器
            if not hasattr(self, 'log_timer'):
                self.log_timer = ui.timer(interval=2.0, callback=self._auto_refresh_logs)
    
    def _auto_refresh_logs(self):
        """自动刷新日志"""
        if self.auto_refresh.value:
            self._refresh_logs()
    
    def _refresh_logs(self):
        """刷新日志内容"""
        try:
            # 获取当前日志文件路径
            log_file = os.path.join(self.log_dir, f"app_{datetime.now().strftime('%Y%m%d')}.log")
            
            # 检查文件是否存在
            if not os.path.exists(log_file):
                self.log_output.push('日志文件不存在')
                self.log_info.text = '日志文件不存在'
                return
            
            # 读取日志内容
            with open(log_file, 'r', encoding='utf-8') as f:
                log_content = f.read()
            
            # 根据级别筛选日志
            level_filter = self.log_level.value
            if level_filter != '全部':
                # 简单的日志级别筛选
                filtered_lines = []
                for line in log_content.split('\n'):
                    if level_filter in line:
                        filtered_lines.append(line)
                log_content = '\n'.join(filtered_lines)
            
            # 更新日志显示
            self.log_output.clear()
            self.log_output.push(log_content)
            
            # 更新日志信息
            log_lines = len([l for l in log_content.split('\n') if l.strip()])
            self.log_info.text = f'显示 {log_lines} 行日志'
            self.log_time.text = f'最后更新: {datetime.now().strftime("%H:%M:%S")}'
            
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
                
                # 创建通知模态区域
                with ui.dialog() as self.notification_dialog:
                    with ui.card().classes('p-4 bg-blue-50 border border-blue-200 rounded-lg'):
                        self.notification_text = ui.label('')
                        with ui.row().classes('w-full justify-end mt-2'):
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
                with ui.tabs().classes('w-full') as tabs:
                    system_tab = ui.tab('系统监控')
                    test_tab = ui.tab('测试监控')
                    log_tab = ui.tab('日志')
                
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

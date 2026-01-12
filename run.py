#!/usr/bin/env python3
import sys
import argparse
from app.main import RemoteTestMonitorApp
from app.services import monitor_service


def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='远程测试监控系统')
    parser.add_argument('--monitor-only', action='store_true', help='仅启动监控服务，不启动Web界面')
    args = parser.parse_args()
    
    if args.monitor_only:
        # 仅启动监控服务
        print("启动监控服务...")
        monitor_service.start_monitoring()
        print("监控服务已启动，按 Ctrl+C 停止")
        try:
            # 保持进程运行
            while True:
                pass
        except KeyboardInterrupt:
            print("\n监控服务已停止")
            monitor_service.stop_monitoring()
            sys.exit(0)
    else:
        # 启动完整应用
        app = RemoteTestMonitorApp()
        app.run()


if __name__ in {"__main__", "__mp_main__"}:
    main()

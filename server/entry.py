"""桌面子进程入口：凭据经 stdin 传递，stdout 仅报告本机就绪地址。"""
from pathlib import Path
import argparse
import json
import os
import socket
import sys
import threading
import uvicorn
from server.app import create_app

def main():
    for output in (sys.stdin,sys.stdout,sys.stderr):
        if hasattr(output,'reconfigure'):
            output.reconfigure(encoding='utf-8',errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--bootstrap',action='store_true')
    parser.add_argument('--data-dir',default='.dev-data')
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = json.loads(sys.stdin.readline()) if args.bootstrap else {
        'data_dir':args.data_dir,'builtin_dir':str(root/'resources/builtin'),'ui_dir':str(root/'ui'),'token':''}
    restored = Path(config['data_dir'])/'builtin'
    builtin = restored if (restored/'kb.sqlite').is_file() else config['builtin_dir']
    app = create_app(config['data_dir'],builtin,config['ui_dir'],config.get('token',''))
    if config.get('model'):
        app.state.gateway.configure(config['model'])
        from server import legacy
        legacy.DS_KEY = 'configured' if app.state.gateway.public()['configured'] else ''
    sock = socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    sock.bind(('127.0.0.1',0 if args.bootstrap else args.port))
    sock.listen(128)
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,log_level='warning',access_log=False))
    if args.bootstrap:
        def watch_parent():
            # 父进程结束或发出 shutdown 后退出，避免孤立后台服务。
            for line in sys.stdin:
                if line.strip()=='shutdown':
                    break
            server.should_exit=True
        threading.Thread(target=watch_parent,daemon=True).start()
    print(json.dumps({'event':'ready','port':port}),flush=True)
    server.run(sockets=[sock])

if __name__=='__main__':
    main()

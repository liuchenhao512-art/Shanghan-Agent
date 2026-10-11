"""兼容接口客户端。密钥仅由桌面主进程注入内存，日志不输出请求凭据。"""
from __future__ import annotations
import json
import re
import threading
from urllib.parse import urlparse
import httpx

class ModelGateway:
    def __init__(self):
        self._config = {'base_url':'https://api.deepseek.com/v1','model':'deepseek-chat','api_key':''}
        self.lock = threading.RLock()

    def configure(self, values):
        base = str(values.get('base_url','')).strip().rstrip('/')
        parsed = urlparse(base)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('模型服务地址格式不正确')
        if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('在线模型地址应使用 HTTPS')
        if base.endswith('/chat/completions'):
            base = base[:-len('/chat/completions')]
        model = str(values.get('model','')).strip()
        if not model:
            raise ValueError('请填写模型名称')
        with self.lock:
            self._config = {'base_url':base,'model':model,'api_key':str(values.get('api_key',''))}
        return self.public()

    def public(self):
        with self.lock:
            return {'base_url':self._config['base_url'],'model':self._config['model'],'configured':bool(self._config['api_key'])}

    def config(self):
        with self.lock:
            if not self._config['api_key']:
                raise ValueError('请先在“设置与备份”配置在线模型')
            return dict(self._config)

    async def complete(self, messages, max_tokens=4000):
        config = self.config()
        async with httpx.AsyncClient(timeout=httpx.Timeout(120,connect=20),follow_redirects=False) as client:
            try:
                resp = await client.post(config['base_url']+'/chat/completions',headers={'Authorization':'Bearer '+config['api_key']},
                    json={'model':config['model'],'messages':messages,'stream':False,'max_tokens':max_tokens})
                resp.raise_for_status()
                data = resp.json()
                return data['choices'][0]['message']['content'],data.get('usage',{})
            except httpx.HTTPStatusError as e:
                raise ValueError(f'模型服务返回 HTTP {e.response.status_code}，请检查模型设置、额度或服务状态') from None
            except (httpx.HTTPError,KeyError,ValueError,TypeError):
                raise ValueError('模型连接中断或返回格式不兼容，请核对服务设置后重试') from None

    def stream(self, messages, temperature=0.4):
        config = self.config()
        try:
            with httpx.Client(timeout=httpx.Timeout(120,connect=20),follow_redirects=False) as client:
                with client.stream('POST',config['base_url']+'/chat/completions',headers={'Authorization':'Bearer '+config['api_key']},
                    json={'model':config['model'],'messages':messages,'temperature':temperature,'stream':True}) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        if line.startswith('data:'):
                            data = line[5:].strip()
                            if data=='[DONE]':
                                break
                            try:
                                text = json.loads(data)['choices'][0]['delta'].get('content','')
                                if text:
                                    yield text
                            except (ValueError,KeyError,IndexError):
                                continue
        except httpx.HTTPError:
            yield '\n[SHANGHAN_ERROR]模型连接失败，请检查设置后重新生成。'

def parse_json(text):
    value = text.strip()
    if value.startswith('```'):
        value = re.sub(r'^```(?:json)?\s*','',value)
        value = re.sub(r'\s*```$','',value)
    try:
        result = json.loads(value)
    except (ValueError,TypeError):
        raise ValueError('模型未返回约定的结构化内容，已保留任务，可重试') from None
    if not isinstance(result,dict):
        raise ValueError('模型输出应为结构化对象')
    return result

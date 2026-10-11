"""提取既有阅读界面的样式与脚本，兼容桌面 CSP；保留原有交互逻辑。"""
from pathlib import Path
import re
root = Path(__file__).resolve().parents[1]
index = root/'ui/classic.html'
text = index.read_text(encoding='utf-8')
style = re.search(r'<style>(.*?)</style>',text,re.S)
script = re.search(r'<script>(.*?)</script>',text,re.S)
if style and script:
    (root/'ui/classic.css').write_text(style[1],encoding='utf-8')
    js = script[1].replace("AION?'DeepSeek 已接入'", "AION?'在线模型已接入'")
    js = js.replace('未检测到 DeepSeek API Key（.env）。配置后重启即可启用「本条导读」与问答。','尚未配置在线模型。请在“设置与备份”填写服务地址、模型和密钥。')
    js += '''
window.addEventListener('message',async event=>{
  if(event.source!==parent||event.data?.type!=='model-updated')return;
  META=await api('/api/meta');AION=META.ai;
  $('#aist').textContent=AION?'在线模型已接入':'AI 未配置';
  $('.ai-input').style.display=AION?'':'none';$('#regen').style.display=AION?'':'none';
  if(AION&&$('#chat .ai-off'))$('#chat').innerHTML='';
  for(const key of Object.keys(summaryCache))delete summaryCache[key];
});
'''
    (root/'ui/classic.js').write_text(js,encoding='utf-8')
    text = text.replace(style[0],'<link rel="stylesheet" href="/assets/classic.css">')
    text = text.replace(script[0],'<script src="/assets/classic.js"></script>')
    index.write_text(text,encoding='utf-8')
    print('经典界面已适配独立资源与模型设置刷新。')

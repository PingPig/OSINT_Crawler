import time
import random
import re
import os
import json
from playwright.sync_api import sync_playwright

# ================= 配置区域 =================
KEYWORD = "山东航空"          # 搜索关键词
STATE_FILE = "state.json"    # 登录Cookie保存文件
HEADLESS = True              # True=后台静默运行, False=显示浏览器观察
OUTPUT_FILE = "weibo_osint_data.json" 
# ===========================================

# --- 辅助工具 1: 数字转换 ---
def extract_number(text):
    """提取并转换数字（处理万/亿单位）"""
    if not text: return "0"
    clean_text = re.sub(r'[^\d\.万亿]', '', text)
    try:
        if '万' in clean_text:
            num = float(clean_text.replace('万', '')) * 10000
            return str(int(num))
        elif '亿' in clean_text:
            num = float(clean_text.replace('亿', '')) * 100000000
            return str(int(num))
        else:
            return clean_text
    except:
        return "0"

# --- 辅助工具 2: 联系方式提取 (核心新增) ---
def extract_contacts(text):
    """
    从文本中提取联系方式（手机、座机/热线、微信、QQ）
    """
    if not text:
        return {"mobile": [], "landline": [], "wechat": [], "qq": []}

    contacts = {
        "mobile": [],
        "landline": [],
        "wechat": [],
        "qq": []
    }

    # 1. 手机号 (1开头, 11位)
    mobile_pattern = r'(?<!\d)(1[3-9]\d{9})(?!\d)'
    contacts['mobile'] = list(set(re.findall(mobile_pattern, text)))

    # 2. 座机/热线 (含 400/800 及 95xxx 短号)
    landline_patterns = [
        r'(?<!\d)(0\d{2,3}-?\d{7,8})(?!\d)',  # 常规座机 010-88888888
        r'(?<!\d)(400-?\d{3}-?\d{4})(?!\d)',  # 400电话
        r'(?<!\d)(800-?\d{3}-?\d{4})(?!\d)',  # 800电话
        r'(?<!\d)(95\d{3,4})(?!\d)',          # 95开头的短号 (如 95369)
        r'(?<!\d)(1\d{4})(?!\d)'              # 1开头的运营商短号
    ]
    for pat in landline_patterns:
        found = re.findall(pat, text)
        contacts['landline'].extend(found)
    contacts['landline'] = list(set(contacts['landline']))

    # 3. QQ (匹配 "QQ/扣扣" 后跟随的数字)
    qq_pattern = r'(?i)(?:qq|扣扣|Q群|加Q)[\s:：]*(\d{5,11})'
    contacts['qq'] = list(set(re.findall(qq_pattern, text)))

    # 4. 微信/公众号 (支持中文公众号名称)
    # 匹配常规微信号 (字母数字下划线)
    wx_id_pattern = r'(?i)(?:vx|v\+|wechat|微信)[\s:：]*([a-zA-Z0-9_\-]{6,20})'
    # 匹配公众号名称 (含中文，遇空格或标点停止)
    wx_pub_pattern = r'(?:公众号|公号)[\s:：]*([a-zA-Z0-9_\-\u4e00-\u9fa5]+)'
    
    raw_wx = re.findall(wx_id_pattern, text) + re.findall(wx_pub_pattern, text)
    clean_wx = []
    for wx in raw_wx:
        w = wx.strip()
        # 简单过滤误匹配的单字或常用动词
        if len(w) > 1 and w not in ["搜索", "关注", "点击", "是"]: 
            clean_wx.append(w)
    contacts['wechat'] = list(set(clean_wx))

    return contacts

# --- 阶段一：PC模式搜索 ---
def run_search_phase(browser, keyword):
    print(f"\n[*] === 阶段一：PC模式搜索关键词 [{keyword}] ===")
    
    if os.path.exists(STATE_FILE):
        context = browser.new_context(storage_state=STATE_FILE)
    else:
        context = browser.new_context()
        
    page = context.new_page()
    # 伪造 Referer 绕过部分搜索风控
    target_url = f"https://s.weibo.com/user?q={keyword}&Refer=weibo_user"
    
    try:
        page.goto(target_url, wait_until="domcontentloaded")
        # 等待搜索结果卡片加载
        page.wait_for_selector("div.card.card-user-b", timeout=8000)
    except:
        print("[-] 未找到搜索结果或网络超时。")
        context.close()
        return []

    cards = page.locator("div.card.card-user-b").all()
    print(f"[+] 找到 {len(cards)} 个目标，开始解析 UID...")

    users_list = []
    for card in cards:
        user = {}
        try:
            user['nickname'] = card.locator("a.name").inner_text().strip()
        except:
            user['nickname'] = "未知"
        
        # 提取UID策略：优先从关注按钮提取，其次从链接提取
        try:
            action_btn = card.locator("a[action-data*='uid=']").first
            if action_btn.count() > 0:
                uid_match = re.search(r'uid=(\d+)', action_btn.get_attribute("action-data"))
                user['uid'] = uid_match.group(1) if uid_match else None
            else:
                href = card.locator("a.name").get_attribute("href") or ""
                if "/u/" in href:
                    user['uid'] = href.split("/u/")[1].split("?")[0]
                else:
                    user['uid'] = None
        except:
            user['uid'] = None

        if user['uid']:
            print(f"    -> 锁定: {user['nickname']} (UID: {user['uid']})")
            users_list.append(user)
    
    context.close() 
    return users_list

# --- 阶段二：iPhone 模式数据采集 ---
def run_mobile_detail_phase(browser, users_list):
    print(f"\n[*] === 阶段二：切换 Mobile Context 深度采集 ===")
    
    # 模拟 iPhone X 指纹
    iphone_device = {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 375, "height": 812},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True
    }

    if os.path.exists(STATE_FILE):
        context = browser.new_context(**iphone_device, storage_state=STATE_FILE)
    else:
        context = browser.new_context(**iphone_device)

    page = context.new_page()
    
    # 预热：访问首页激活 Session
    try:
        page.goto("https://m.weibo.cn", wait_until="domcontentloaded")
        time.sleep(1.5)
    except:
        pass

    for i, user in enumerate(users_list):
        uid = user['uid']
        print(f"[{i+1}/{len(users_list)}] 解析中: {user['nickname']} ...")
        
        # 调用 Mobile API
        api_url = f"https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}"
        
        try:
            response = page.goto(api_url)
            content = page.locator("body").inner_text()
            
            # 清洗非 JSON 字符
            if not content.startswith("{"):
                try:
                    content = page.locator("pre").inner_text()
                except:
                    pass

            try:
                data_obj = json.loads(content)
            except:
                print("    [-] JSON 解析失败 (可能触发滑块)")
                user['description'] = "Error"
                continue
            
            # 提取字段
            if data_obj.get('ok') == 1 and 'userInfo' in data_obj.get('data', {}):
                info = data_obj['data']['userInfo']
                
                # 1. 简介原文
                desc_text = info.get('description', '')
                user['description'] = desc_text if desc_text else '无简介'
                
                # 2. [NEW] 提取联系方式
                contacts = extract_contacts(desc_text)
                user['contact_mobile'] = "; ".join(contacts['mobile'])
                user['contact_landline'] = "; ".join(contacts['landline'])
                user['contact_wechat'] = "; ".join(contacts['wechat'])
                user['contact_qq'] = "; ".join(contacts['qq'])

                # 3. 统计数据
                user['followers_count'] = info.get('followers_count', 0)
                user['statuses_count'] = info.get('statuses_count', 0)
                user['verified_reason'] = info.get('verified_reason', '未认证')
                
                print(f"    -> [提取] 简介长度: {len(user['description'])}")
                if user['contact_landline'] or user['contact_mobile']:
                    print(f"    -> [发现] 电话: {user['contact_landline']} {user['contact_mobile']}")
                if user['contact_wechat']:
                    print(f"    -> [发现] 微信: {user['contact_wechat']}")

            else:
                print(f"    [-] API 状态异常: {data_obj.get('msg', 'unknown error')}")
                user['description'] = "无数据"

        except Exception as e:
            print(f"    [-] 请求异常: {e}")
            
        time.sleep(random.uniform(1.2, 2.5)) # 随机延迟

    context.close()
    return users_list

# --- 主程序 ---
def main():
    with sync_playwright() as p:
        print("[*] 正在初始化引擎...")
        
        # 检查登录状态
        if not os.path.exists(STATE_FILE):
            print("[!] 未检测到 Cookie，启动扫码登录程序...")
            browser = p.chromium.launch(headless=False, slow_mo=500)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://weibo.com")
            
            try:
                print(">>> 请在浏览器弹窗中扫码登录 <<<")
                # 锚点：等待“消息”图标或“发微博”按钮出现，代表登录成功
                page.wait_for_selector('div[title="消息"], a[href="/compose/"]', state='visible', timeout=120000)
                print("[+] 登录成功，保存 Session...")
                time.sleep(3)
                context.storage_state(path=STATE_FILE)
                browser.close()
            except:
                print("[-] 登录超时，请重试。")
                return

        # 启动任务
        browser = p.chromium.launch(headless=HEADLESS)
        
        # Step 1: 搜索
        results = run_search_phase(browser, KEYWORD)
        
        if results:
            # Step 2: 详情采集 + 正则提取
            final_data = run_mobile_detail_phase(browser, results)
            
            # Step 3: 保存
            print(f"\n[*] 写入文件: {OUTPUT_FILE}")
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                json.dump(final_data, f, ensure_ascii=False, indent=4)
            print("[=] 任务全部完成。")
        else:
            print("[-] 无任务执行。")
        
        browser.close()

if __name__ == "__main__":
    main()
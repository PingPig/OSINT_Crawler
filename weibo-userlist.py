import time
import random
import re
import os
import json
from playwright.sync_api import sync_playwright

# ================= 配置区域 =================
KEYWORD = "山东航空"          
STATE_FILE = "state.json"    # 登录Cookie保存文件
HEADLESS = True              # True=后台运行
OUTPUT_FILE = "final_weibo_data.json" 
# ===========================================

# --- 辅助工具 ---
def extract_number(text):
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

# --- 阶段一：PC模式搜索 (保留，因为PC搜索最好用) ---
def run_search_phase(browser, keyword):
    print(f"\n[*] === 阶段一：PC模式搜索关键词 [{keyword}] ===")
    
    # 创建 PC 上下文
    if os.path.exists(STATE_FILE):
        context = browser.new_context(storage_state=STATE_FILE)
    else:
        context = browser.new_context()
        
    page = context.new_page()
    target_url = f"https://s.weibo.com/user?q={keyword}&Refer=weibo_user"
    
    try:
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_selector("div.card.card-user-b", timeout=8000)
    except:
        print("[-] 未找到搜索结果。")
        context.close()
        return []

    cards = page.locator("div.card.card-user-b").all()
    print(f"[+] 找到 {len(cards)} 个用户，提取UID...")

    users_list = []
    for card in cards:
        user = {}
        try:
            user['nickname'] = card.locator("a.name").inner_text().strip()
        except:
            user['nickname'] = "未知"
        
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
            print(f"    -> 命中: {user['uid']} | {user['nickname']}")
            users_list.append(user)
    
    context.close() # 搜索完关闭PC上下文
    return users_list

# --- 阶段二：iPhone 模式抓取 (核心必杀技) ---
def run_mobile_detail_phase(browser, users_list):
    print(f"\n[*] === 阶段二：切换为 iPhone X 模式采集详情 ===")
    
    # 【关键】定义 iPhone 的指纹信息
    iphone_device = {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1",
        "viewport": {"width": 375, "height": 812},
        "device_scale_factor": 3,
        "is_mobile": True,
        "has_touch": True
    }

    # 使用 iPhone 指纹创建新上下文
    if os.path.exists(STATE_FILE):
        context = browser.new_context(
            **iphone_device, 
            storage_state=STATE_FILE
        )
    else:
        context = browser.new_context(**iphone_device)

    page = context.new_page()
    
    # 1. 先访问移动端首页，激活 Cookie
    print("[*] 正在激活移动端会话...")
    try:
        page.goto("https://m.weibo.cn", wait_until="domcontentloaded")
        time.sleep(2)
    except:
        pass

    for i, user in enumerate(users_list):
        uid = user['uid']
        print(f"[{i+1}/{len(users_list)}] 获取: {user['nickname']} (UID: {uid}) ...")
        
        # 2. 访问移动端数据接口
        api_url = f"https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}"
        
        try:
            response = page.goto(api_url)
            # 获取纯文本
            content = page.locator("body").inner_text()
            
            # 清洗可能存在的非JSON字符
            if not content.startswith("{"):
                try:
                    content = page.locator("pre").inner_text()
                except:
                    pass

            data_obj = json.loads(content)
            
            # 3. 提取数据 (Mobile API 结构)
            if data_obj.get('ok') == 1 and 'userInfo' in data_obj.get('data', {}):
                info = data_obj['data']['userInfo']
                
                # === 这里就是你要的简介 ===
                user['description'] = info.get('description', '无简介')
                
                # === 获取高清粉丝数 ===
                user['followers_count'] = info.get('followers_count', 0)
                user['statuses_count'] = info.get('statuses_count', 0)
                user['gender'] = info.get('gender', 'n/a')
                
                print(f"    -> [成功] 简介: {user['description']}")
                print(f"    -> [数据] 粉丝: {user['followers_count']}")
            else:
                print(f"    [-] 接口返回异常: {str(data_obj)[:50]}")
                user['description'] = "无数据"

        except Exception as e:
            print(f"    [-] 请求报错: {e}")
            user['description'] = "请求失败"
            
        time.sleep(random.uniform(1.5, 3.0))

    context.close()
    return users_list

# --- 主程序 ---
def main():
    with sync_playwright() as p:
        print("[*] 初始化...")
        has_state = os.path.exists(STATE_FILE)
        
        # 如果没登录，先用PC模式扫码
        if not has_state:
            print("[!] 请先扫码登录...")
            browser = p.chromium.launch(headless=False, slow_mo=500)
            context = browser.new_context()
            page = context.new_page()
            page.goto("https://weibo.com")
            
            try:
                # 等待直到出现消息图标
                page.wait_for_selector('div[title="消息"]', state='visible', timeout=300000)
                print("[+] 登录成功，保存状态...")
                time.sleep(3)
                context.storage_state(path=STATE_FILE)
                browser.close()
                has_state = True
            except:
                print("[-] 登录超时退出")
                return

        # 正式开始：启动浏览器
        browser = p.chromium.launch(headless=HEADLESS)

        # 1. 搜索 (PC模式)
        search_results = run_search_phase(browser, KEYWORD)
        
        if not search_results:
            print("[-] 没搜到人，撤了。")
            browser.close()
            return

        # 2. 抓取 (iPhone模式)
        final_data = run_mobile_detail_phase(browser, search_results)

        # 3. 保存
        print(f"\n[*] 保存中: {OUTPUT_FILE}")
        with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
        
        print(f"[=] 完成！")
        browser.close()

if __name__ == "__main__":
    main()
import asyncio
import json
import random
import os
import re
from playwright.async_api import async_playwright

# ==========================================
# 👇👇👇 【用户配置区域】 👇👇👇
# ==========================================

CONFIG = {
    "keyword": "测试目标",        
    "target_count": 20,          
    "save_file_name": "users_cleaned.json",
    "headless_mode": True 
}

# ==========================================
# 👆👆👆 配置结束 👆👆👆
# ==========================================

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def extract_info(raw_data):
    """
    提取逻辑修正版 V7：
    1. 昵称 & 简介清洗 (V6逻辑保持)
    2. 联系方式提取 (V6逻辑保持)
    3. 🔥 新增：粉丝数 & 获赞数提取
    """
    cleaned_list = []
    
    # --- 正则表达式 ---

    # 1. 昵称切割
    re_nickname_clean = re.compile(r'^(.+?)(?=\s+(?:关注|抖音号|认证徽章))')

    # 2. 简介切割
    re_bio_after_stats = re.compile(r'(?:粉丝|获赞|关注)\s+(.*)')
    re_bio_after_id = re.compile(r'抖音号[:：]\s*[a-zA-Z0-9_.-]+\s+(.*)')

    # 3. 抖音号
    re_douyin = re.compile(r'抖音号[:：]\s*([a-zA-Z0-9_.-]+)')

    # 4. 🔥 粉丝数 & 获赞数 (新增)
    # 匹配逻辑：数字 + 可选的小数点 + 可选的单位(万/w/W/亿) + 关键词
    # 例子：1.8万获赞, 3686粉丝, 1.2w获赞
    re_likes = re.compile(r'(\d+(?:\.\d+)?[万wW亿]?)\s*获赞')
    re_followers = re.compile(r'(\d+(?:\.\d+)?[万wW亿]?)\s*粉丝')

    # 5. 联系方式正则组
    re_mobile_loose = re.compile(r'(?:手机|电话|联系|V|VX|vx|微信|合作)[:：]?\s*(1[3-9](?:[\s-]*\d){9})')
    re_landline = re.compile(r'(?<!\d)(0\d{2,3}[-\s]?\d{7,8})(?!\d)')
    re_hotline = re.compile(r'(?<!\d)(400[-\s]?\d{3}[-\s]?\d{4})(?!\d)')
    re_wechat = re.compile(r'(?:微信|V|VX|vx|微)[:：]?\s*([a-zA-Z][a-zA-Z0-9_-]{5,19})')
    re_qq = re.compile(r'(?:QQ|qq|Q)[:：]?\s*(\d{5,11})')
    re_email = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')

    for item in raw_data:
        # 获取最全的文本
        raw_text = item.get('details', '') 
        if len(item.get('nickname', '')) > len(raw_text):
            raw_text = item.get('nickname', '')
        
        # 统一符号
        raw_text = clean_text(raw_text).replace('：', ':')
        
        # --- 🅰️ 昵称清洗 ---
        nickname_match = re_nickname_clean.search(raw_text)
        nickname = nickname_match.group(1).strip() if nickname_match else raw_text[:20].strip()

        # --- 🅱️ 抖音号提取 ---
        douyin_match = re_douyin.search(raw_text)
        douyin_id = douyin_match.group(1) if douyin_match else "未找到"

        # --- 🅾️ 粉丝数 & 获赞数提取 (新增) ---
        likes_match = re_likes.search(raw_text)
        likes = likes_match.group(1) if likes_match else "0"

        followers_match = re_followers.search(raw_text)
        followers = followers_match.group(1) if followers_match else "0"

        # --- ©️ 简介清洗 ---
        bio = ""
        bio_stats_match = re_bio_after_stats.search(raw_text)
        if bio_stats_match:
            bio = bio_stats_match.group(1).strip()
        else:
            bio_id_match = re_bio_after_id.search(raw_text)
            bio = bio_id_match.group(1).strip() if bio_id_match else ""

        # --- 🅾️ 联系方式提取 ---
        raw_mobiles = re_mobile_loose.findall(raw_text)
        clean_mobiles = [re.sub(r'[\s-]', '', m) for m in raw_mobiles]

        all_landlines = list(set(re_landline.findall(raw_text) + re_hotline.findall(raw_text)))
        wechat_match = re_wechat.findall(raw_text)
        qq_match = re_qq.findall(raw_text)
        email_match = re_email.findall(raw_text)
        
        cleaned_item = {
            "nickname": nickname,
            "douyin_id": douyin_id,
            "description": bio,
            "profile_url": item.get('profileUrl', ''),
            # 🔥 新增 stats 字段
            "stats": {
                "likes": likes,
                "followers": followers
            },
            "contacts": {
                "mobile": list(set(clean_mobiles)),
                "landline": all_landlines,
                "wechat": list(set(wechat_match)),
                "qq": list(set(qq_match)),
                "email": list(set(email_match))
            }
        }
        cleaned_list.append(cleaned_item)
        
    return cleaned_list

async def run():
    # ... (主程序逻辑保持不变，复制 V6 的 run 函数即可) ...
    user_data_dir = os.path.join(os.getcwd(), 'douyin_user_data')
    if not os.path.exists(user_data_dir):
        os.makedirs(user_data_dir)

    print(f'🚀 启动任务...')
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir,
            channel="chrome",
            headless=CONFIG["headless_mode"],
            viewport={'width': 1920, 'height': 1080},
            args=['--start-maximized', '--no-sandbox', '--disable-blink-features=AutomationControlled', '--ignore-certificate-errors'],
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.pages[0]
        await page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        try:
            await page.goto("https://www.douyin.com", wait_until='domcontentloaded')
        except: pass

        if not CONFIG["headless_mode"]:
            input("👉 确认登录就绪后，请按【回车键】继续...")
        else:
            await asyncio.sleep(3)

        search_url = f"https://www.douyin.com/search/{CONFIG['keyword']}?type=user"
        await page.goto(search_url, wait_until='domcontentloaded')
        await asyncio.sleep(3)

        unique_users_map = {}
        no_new_data_count = 0
        
        print('⬇️ 开始抓取数据...')

        while len(unique_users_map) < CONFIG['target_count']:
            current_batch = await page.evaluate('''() => {
                function getTextWithSpaces(node) {
                    if (node.nodeType === 3) return node.nodeValue;
                    if (node.nodeType === 1) {
                        let s = "";
                        node.childNodes.forEach(child => s += getTextWithSpaces(child));
                        return s + " "; 
                    }
                    return "";
                }
                const items = [];
                const userLinks = document.querySelectorAll('a[href*="/user/"]');
                userLinks.forEach(link => {
                    const href = link.href;
                    const text = getTextWithSpaces(link).trim(); 
                    if (href.includes('/user/') && !href.includes('self') && !href.includes('from_nav')) {
                        if (text.length > 0) {
                            items.push({
                                'nickname': text, 
                                'profileUrl': href.split('?')[0], 
                                'details': text 
                            });
                        }
                    }
                });
                return items;
            }''')

            size_before = len(unique_users_map)
            for user in current_batch:
                url = user['profileUrl']
                if url not in unique_users_map:
                    unique_users_map[url] = user
                else:
                    if len(user['details']) > len(unique_users_map[url]['details']):
                        unique_users_map[url] = user
            
            size_after = len(unique_users_map)
            print(f"📊 当前有效用户: {size_after} / {CONFIG['target_count']}")

            if size_after >= CONFIG['target_count']: break
            if size_after == size_before:
                no_new_data_count += 1
                if no_new_data_count > 5: break
            else:
                no_new_data_count = 0 

            await page.evaluate('window.scrollBy(0, document.body.scrollHeight)')
            await asyncio.sleep(random.uniform(2.0, 4.0))

        raw_data = list(unique_users_map.values())[:CONFIG['target_count']]
        
        print("🧹 正在进行数据清洗和提取...")
        final_data = extract_info(raw_data)

        with open(CONFIG['save_file_name'], 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 数据已清洗并保存: {CONFIG['save_file_name']}")

if __name__ == '__main__':
    asyncio.run(run())
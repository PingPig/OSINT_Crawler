import asyncio
import json
import re
import random
import os
from playwright.async_api import async_playwright

# ================= 配置区域 =================
KEYWORD = "哈尔滨电气集团 联系方式"
TARGET_COUNT = 10
FILENAME = "sogou_sda_source_trace.json" # 文件名改一下，代表带溯源
HEADLESS = True  
# ===========================================

def clean_text(text):
    if not text: return ""
    return re.sub(r'\s+', ' ', text).strip()

def extract_structured_data_with_source(full_text):
    lines = full_text.split('\n')
    
    # 1. 严格的公司名正则 (用于识别独立的标题行)
    re_company_strict = re.compile(r'^[\u4e00-\u9fa5()（）a-zA-Z0-9-]{4,35}(?:公司|集团|厂|院|中心|店|局|部|社|委员会|分公司)$')
    
    # 2. 🔥 新增：宽松的公司名正则 (用于从长句开头提取)
    # 逻辑：匹配行首的公司名，即使后面有其他文字
    re_company_loose = re.compile(r'^([\u4e00-\u9fa5()（）a-zA-Z0-9-]{4,35}(?:公司|集团|厂|院|中心|店|局|部|社|委员会|分公司))')

    re_person = re.compile(r'(?:联系人|咨询|报名|人事|干事)[:：\s]*([\u4e00-\u9fa5]{2,4})')
    
    patterns = {
        "mobile": re.compile(r'(?<!\d)(1[3-9]\d{9})(?!\d)'),
        "email": re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
        "landline": re.compile(r'(?<!\d)(0\d{2,3}[- ]?\d{7,8})(?!\d)'),
        "wechat": re.compile(r'(?:微信|vx|WeChat)[:：\s]*([a-zA-Z][a-zA-Z\d_-]{5,19})', re.IGNORECASE)
    }

    blocks = []
    current_block = []
    
    # 增加一个全局变量记录文章中最像公司名的那个词（作为默认值）
    # 如果某一段找不到公司名，就用这个全局的
    global_company_candidate = "未识别主体"

    for line in lines:
        line = line.strip()
        if len(line) < 2: continue 

        is_new_block = False
        
        # 策略 A: 严格匹配 (整行就是公司名)
        if re_company_strict.match(line) and "招聘" not in line and "联系" not in line:
            is_new_block = True
            global_company_candidate = line # 更新全局候选
        
        # 策略 B: 宽松匹配 (行首是公司名)
        # 只有当这一行很长，且以公司名开头时才触发
        elif len(line) > 35:
            match = re_company_loose.match(line)
            if match:
                # 提取出来的公司名
                extracted_name = match.group(1)
                # 如果这个名字看起来很靠谱（不是"本公司"这种），就认领
                if len(extracted_name) > 6:
                    # 注意：这里我们不一定要切分 Block，因为长段落通常包含正文
                    # 我们只是更新全局候选，方便后面的电话挂靠
                    global_company_candidate = extracted_name

        if is_new_block:
            if current_block:
                blocks.append(current_block)
            current_block = [line]
        else:
            current_block.append(line)
    
    if current_block:
        blocks.append(current_block)

    results = []
    
    for block in blocks:
        block_text = "\n".join(block)
        
        # 确定主体：优先看块的第一行，如果不行，就用全局候选
        first_line = block[0]
        if re_company_strict.match(first_line) and "招聘" not in first_line:
            entity = first_line
        else:
            # 🔥 使用全局抓取到的公司名兜底
            entity = global_company_candidate

        contact_person = "未知"
        for line in block:
            p_match = re_person.search(line)
            if p_match:
                contact_person = p_match.group(1)
                break

        for line in block:
            if "邮编" in line: continue
            
            for p_type, regex in patterns.items():
                matches = regex.findall(line)
                for val in matches:
                    if p_type == 'wechat':
                        if val.lower() in ['jpg', 'png', 'pdf', 'doc', 'com', 'cn', 'net']: continue

                    results.append({
                        "entity": entity,
                        "contact_person": contact_person,
                        "type": p_type,
                        "value": val,
                        "context": line,
                        "origin_data": block_text
                    })

    # 去重
    unique_results = []
    seen = set()
    for r in results:
        fingerprint = f"{r['entity']}_{r['type']}_{r['value']}"
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique_results.append(r)

    return unique_results

async def run():
    print(f"[*] 启动溯源采集器...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=HEADLESS, args=['--disable-blink-features=AutomationControlled'])
        context = await browser.new_context(viewport={'width': 1920, 'height': 1080}, user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        page = await context.new_page()
        print(f"[*] 正在搜索: {KEYWORD}")
        await page.goto(f"https://weixin.sogou.com/weixin?type=2&query={KEYWORD}&ie=utf8", wait_until="domcontentloaded")
        
        if "antispider" in page.url or "验证码" in await page.content():
            print("⚠️  触发验证码。")
            await browser.close()
            return

        data_list = []
        try: await page.wait_for_selector(".news-list li", timeout=5000)
        except: return

        search_results = await page.query_selector_all(".news-list li")
        print(f"[*] 找到 {len(search_results)} 篇文章...")

        for i, item in enumerate(search_results):
            if i >= TARGET_COUNT: break
            try:
                title_el = await item.query_selector("h3 a")
                title = await title_el.inner_text()
                account_el = await item.query_selector(".s-p")
                account = await account_el.inner_text() if account_el else "未知"
                
                print(f"\n[{i+1}/{TARGET_COUNT}] 解析文章: {title[:20]}...")
                async with context.expect_page() as new_page_info: await title_el.click()
                article_page = await new_page_info.value
                try: await article_page.wait_for_selector("#js_content", timeout=8000)
                except: continue
                
                content_element = await article_page.query_selector("#js_content")
                if not content_element: content_element = await article_page.query_selector("body")
                full_text = await content_element.inner_text()
                
                # 🔥 调用分块提取函数
                contacts = extract_structured_data_with_source(full_text)
                
                if contacts:
                    print(f"    ✅ 提取到 {len(contacts)} 条数据")
                    # 打印第一条数据看看 origin_data 效果
                    if len(contacts) > 0:
                        print(f"       示例溯源:\n{contacts[0]['origin_data'][:100]}...") # 打印前100字
                
                data_list.append({
                    "title": title,
                    "account": account,
                    "url": article_page.url,
                    "extracted_data": contacts
                })

                await article_page.close()
                await asyncio.sleep(random.uniform(2, 4))
            except Exception as e: continue

        with open(FILENAME, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, ensure_ascii=False, indent=4)
        print(f"\n[*] 溯源数据已保存至: {FILENAME}")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(run())
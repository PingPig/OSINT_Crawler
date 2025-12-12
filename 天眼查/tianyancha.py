import requests
import json
import os
import sys
import time

# --- 0. 配置加载 (模拟生产环境配置) ---
try:
    # 尝试从你的项目中导入配置，如果不存在则使用默认值
    from config_loader import get_tianyancha_token, get_general_settings
except ImportError:
    def get_tianyancha_token():
        # 这里返回空字符串，强制依赖传入参数或默认Token
        return ""
    def get_general_settings():
        return {"request_timeout": 30, "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) OSINT-Collector/1.0"}

# --- 1. 全局辅助函数 ---

def fetch_api_data(url, params, headers, timeout=30):
    """
    发起API请求的通用封装。
    """
    try:
        # 简单打印日志，实际生产中建议使用 logging 模块
        print(f"  [API请求] {url} | 参数: {params.get('pageNum', 1)}")
        
        response = requests.get(url, params=params, headers=headers, timeout=timeout)
        response.raise_for_status()
        
        data = response.json()
        
        # 检查业务逻辑错误码 (假设非0为错误，需根据实际API文档调整)
        if data.get("error_code", 0) != 0:
            print(f"  [API警告] 接口返回业务错误: {data.get('reason', '未知错误')}")
        
        return data
    except requests.exceptions.RequestException as e:
        return {"error_code": -1, "reason": f"网络请求失败: {str(e)}"}
    except json.JSONDecodeError:
        return {"error_code": -2, "reason": "响应内容不是有效的JSON"}

# --- 2. 核心逻辑 (Coze/MCP 兼容入口) ---

def handler(args):
    """
    核心业务逻辑入口。
    args: 包含 input 对象 (token, keyword)
    """
    # 1. 参数解析
    input_params = getattr(args, "input", None)
    if not input_params:
        return {"error": "参数异常: 未找到 input 对象"}

    token = getattr(input_params, "token", None)
    keyword = getattr(input_params, "keyword", None)

    if not keyword:
        return {"error": "缺少必需参数: keyword"}

    # Token 回退机制
    if not token:
        token = get_tianyancha_token()
    
    # 如果仍然没有 Token，且不是在测试环境，这会导致失败
    if not token and not getattr(args, "is_test", False):
         # 注意：实际使用时，请确保 Token 有效
         pass 

    # 2. 环境准备
    general = get_general_settings()
    headers = {
        "Authorization": token if token else "",
        "User-Agent": general.get("user_agent")
    }
    timeout = general.get("request_timeout", 30)
    
    # 结果容器
    all_results = {
        "target": keyword,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "data": {}
    }

    print(f"[*] 开始收集情报: {keyword}")

    # --- 任务 A: 对外投资 ---
    print("[-] 正在获取: 对外投资...")
    url_invest = "http://open.api.tianyancha.com/services/open/ic/inverst/2.0"
    all_results["data"]["对外投资"] = fetch_api_data(
        url_invest, 
        {"keyword": keyword, "pageNum": 1, "pageSize": 20}, 
        headers, timeout
    )

    # --- 任务 B: 供应商 (含自动翻页) ---
    print("[-] 正在获取: 供应商 (可能需要多次请求)...")
    url_supply = "http://open.api.tianyancha.com/services/open/m/supply/2.0"
    supply_params = {"keyword": keyword, "pageNum": 1, "pageSize": 20}
    
    first_page = fetch_api_data(url_supply, supply_params, headers, timeout)
    
    # 翻页逻辑
    if first_page.get("error_code") == 0 and first_page.get("result"):
        page_bean = first_page["result"].get("pageBean", {})
        total = page_bean.get("total", 0)
        all_suppliers = page_bean.get("result", [])
        
        print(f"  > 发现供应商总数: {total}")

        # 限制最大翻页数以防 Token 耗尽 (例如最多翻5页)
        MAX_PAGES = 5 
        page_size = 20
        total_pages = (total + page_size - 1) // page_size
        
        # 实际翻页循环
        for page_num in range(2, min(total_pages, MAX_PAGES) + 1):
            supply_params["pageNum"] = page_num
            page_data = fetch_api_data(url_supply, supply_params, headers, timeout)
            if page_data.get("error_code") == 0 and page_data.get("result"):
                new_items = page_data["result"].get("pageBean", {}).get("result", [])
                all_suppliers.extend(new_items)
            time.sleep(0.5) # 礼貌性延时，防止触发风控

        first_page["result"]["pageBean"]["result"] = all_suppliers
        first_page["result"]["pageBean"]["fetched_count"] = len(all_suppliers)
        if total_pages > MAX_PAGES:
            first_page["note"] = f"数据量过大，仅抓取前 {MAX_PAGES} 页"

    all_results["data"]["供应商"] = first_page

    # --- 任务 C: 组织架构 ---
    print("[-] 正在获取: 组织架构...")
    url_org = "http://open.api.tianyancha.com/services/open/ic/companyType/v2"
    all_results["data"]["组织架构"] = fetch_api_data(
        url_org, 
        {"keyword": keyword, "pageNum": 1, "pageSize": 20}, 
        headers, timeout
    )

    # --- 任务 D: 联系方式 ---
    print("[-] 正在获取: 企业联系方式...")
    url_contact = "https://open.api.tianyancha.com/services/open/ic/contact"
    all_results["data"]["联系方式"] = fetch_api_data(
        url_contact, 
        {"keyword": keyword}, 
        headers, timeout
    )

    return all_results

# --- 3. 本地运行入口 (CLI + 文件保存) ---

if __name__ == "__main__":
    # 配置区
    # 请替换为你真实的天眼查 Token，否则接口会报错 
    # (注意：这是示例Token，实际不可用)
    MY_TOKEN = "284a8d48-f624-48e2-9a76-362d8d7331b9" 
    
    # 检查命令行参数
    if len(sys.argv) < 2:
        print("\n使用方法: python tianyancha_tool.py <公司名称>")
        print("示例: python tianyancha_tool.py 腾讯科技")
        sys.exit(1)
        
    target_company = sys.argv[1]

    # 模拟 Coze 传参结构
    class MockInput:
        def __init__(self, token, keyword):
            self.token = token
            self.keyword = keyword
    class MockArgs:
        def __init__(self, token, keyword):
            self.input = MockInput(token, keyword)
            self.is_test = True # 标记为本地测试

    # 执行核心逻辑
    try:
        args = MockArgs(MY_TOKEN, target_company)
        result_data = handler(args)
        
        # --- 文件保存逻辑 ---
        
        # 1. 确定保存目录
        output_dir = "data"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        # 2. 生成文件名 (公司名_时间戳.json)
        # 清理文件名中的非法字符 (Windows下常见问题)
        safe_name = target_company.replace('"', '').replace("'", "").replace(" ", "_")
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        file_name = f"{output_dir}/{safe_name}_{timestamp}.json"
        
        # 3. 写入文件
        print(f"\n[*] 正在保存数据到本地...")
        with open(file_name, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, ensure_ascii=False, indent=2)
            
        abs_path = os.path.abspath(file_name)
        print(f"[SUCCESS] 任务完成！")
        print(f"文件路径: {abs_path}")
        
    except Exception as e:
        print(f"\n[ERROR] 脚本执行过程中发生严重错误: {e}")
        import traceback
        traceback.print_exc()
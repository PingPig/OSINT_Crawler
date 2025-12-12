from typing import Optional, List, Dict, Any
import requests
import math
import json
from datetime import datetime
from dataclasses import dataclass
import time
import re

# ================= 配置区域 =================
try:
    from config_loader import get_qianlima_token, get_general_settings
except Exception:
    def get_qianlima_token(): return ""
    def get_general_settings(): return {"request_timeout": 30, "user_agent": "Mozilla/5.0"}

@dataclass
class Input:
    text: str

class Config:
    XAuthToken = get_qianlima_token() or "24e28c65-2f94-48a7-a871-dca8a511d9f7"
    _general = get_general_settings()
    REQUEST_TIMEOUT = _general.get("request_timeout", 30)
    USER_AGENT = _general.get("user_agent", "Mozilla/5.0")

# ================= 验证函数 (保持不变) =================
def validate_company_search(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    required_fields = ['name', 'companyNameEncrypt', 'tenderCount', 'outBidCount', 'companyContacts']
    for field in required_fields:
        if field not in data: return None
    return {
        'name': str(data.get('name', '')),
        'companyNameEncrypt': str(data.get('companyNameEncrypt', '')),
        'phoneNumber': data.get('phoneNumber'),
        'tenderCount': int(data.get('tenderCount', 0)),
        'outBidCount': int(data.get('outBidCount', 0)),
        'regStatus': data.get('regStatus'),
        'companyContacts': int(data.get('companyContacts', 0))
    }

def validate_contract_list_item(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    required_fields = ['id', 'companyId', 'source', 'contentId', 'count']
    for field in required_fields:
        if field not in data: return None
    return {
        'id': int(data.get('id', 0)),
        'linkMan': data.get('linkMan'),
        'phone': data.get('phone'),
        'companyId': int(data.get('companyId', 0)),
        'source': int(data.get('source', 0)),
        'mobile': data.get('mobile'),
        'tuoMinMobile': data.get('tuoMinMobile'),
        'contentId': int(data.get('contentId', 0)),
        'title': data.get('title'),
        'count': int(data.get('count', 0))
    }

def validate_contract_list(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if 'dataList' not in data: return None
    validated_data_list = []
    for item in data.get('dataList', []):
        validated_item = validate_contract_list_item(item)
        if validated_item: validated_data_list.append(validated_item)
    return {'dataList': validated_data_list, 'totalCount': int(data.get('totalCount', len(validated_data_list)))}

def validate_real_phone(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if 'fromRecord' not in data: return None
    return {'fromRecord': bool(data.get('fromRecord', False)), 'vmMobile': data.get('vmMobile')}

def get_user_input(input_data) -> str:
    if hasattr(input_data, 'get') and callable(getattr(input_data, 'get')):
        keyword = input_data.get('keyword', '') or input_data.get('text', '') or input_data.get('query', '')
        return keyword.strip()
    elif hasattr(input_data, 'keyword'): return getattr(input_data, 'keyword', '').strip()
    elif hasattr(input_data, 'text'): return getattr(input_data, 'text', '').strip()
    else: return str(input_data).strip()

def make_request(url: str) -> Optional[Dict[str, Any]]:
    try:
        response = requests.get(
            url,
            headers={'User-Agent': Config.USER_AGENT, 'x-auth-token': Config.XAuthToken},
            timeout=Config.REQUEST_TIMEOUT
        )
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"请求错误: {e}")
        return None

# ================= 业务逻辑 =================
def do_search(_keyword: str) -> Optional[Dict[str, Any]]:
    url = f'https://search.vip.qianlima.com/rest/enterprise/enterprise/companySearch?keyword={_keyword}&_={int(time.time() * 1000)}'
    ret_json = make_request(url)
    if ret_json and ret_json.get('code', 0) == 200:
        return validate_company_search(ret_json.get('data', {}))
    return None

def get_contracts(company_id: str, page_no: int = 1, page_size: int = 20) -> Optional[Dict[str, Any]]:
    url = f'https://search.vip.qianlima.com/rest/enterprise/enterprise/contacts/list?company={company_id}&pageNo={page_no}&pageSize={page_size}&requestType=website&phoneType=&_={int(time.time() * 1000)}'
    ret_json = make_request(url)
    if ret_json and ret_json.get('code', 0) == 200:
        data = ret_json.get('data', {})
        if 'totalCount' not in data: data['totalCount'] = len(data.get('dataList', []))
        return validate_contract_list(data)
    return None

def get_all_contracts(company_id: str, total_contacts: int, page_size: int = 20) -> List[Dict[str, Any]]:
    all_contracts = []
    total_pages = math.ceil(total_contacts / page_size)
    max_pages_limit = 3 
    actual_pages = min(total_pages, max_pages_limit)
    
    for page_no in range(1, actual_pages + 1):
        contract_list = get_contracts(company_id, page_no, page_size)
        if contract_list and contract_list.get('dataList'):
            all_contracts.extend(contract_list['dataList'])
    return all_contracts

def get_real_phone(mobile_hash: str) -> Optional[Dict[str, Any]]:
    url = f'https://search.vip.qianlima.com/rest/enterprise/virtual/phone/bind/{mobile_hash}'
    ret_json = make_request(url)
    if ret_json and ret_json.get('code', 0) == 200:
        return validate_real_phone(ret_json.get('data', {}))
    return None

def process_company_data(company: Dict[str, Any]) -> Dict[str, Any]:
    all_contracts = get_all_contracts(company['companyNameEncrypt'], company['companyContacts'])
    contacts = []
    
    for contract in all_contracts:
        decrypted_mobile = None
        if contract.get('mobile'):
            real_phone = get_real_phone(contract['mobile'])
            if real_phone and real_phone.get('vmMobile'):
                decrypted_mobile = real_phone['vmMobile']
        
        contacts.append({
            'name': contract.get('linkMan', '未知'),
            'phone': contract.get('phone'),
            'decrypted_mobile': decrypted_mobile,
            'title': contract.get('title')
        })
    
    return {
        'name': company.get('name', ''),
        'company_id_encrypt': company.get('companyNameEncrypt', ''),
        'phone': company.get('phoneNumber'),
        'reg_status': company.get('regStatus'),
        'tender_count': company.get('tenderCount', 0),
        'outbid_count': company.get('outBidCount', 0),
        
        # [关键修复] 将原始的统计总数透传出来
        'total_contacts_raw': company.get('companyContacts', 0),
        
        'contacts': contacts
    }

# ================= 格式转换 =================
def transform_to_osint_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    转换为 OSINT 标准格式 V3
    包含: 上下文关联、智能简介、完整计数
    """
    
    mobile_list = []
    landline_list = []
    high_value_clues = [] 

    if data.get('phone'):
        landline_list.append(f"{data['phone']} (企业注册电话)")

    for contact in data.get('contacts', []):
        name = contact.get('name') or '未命名'
        title = contact.get('title') or '未知来源'
        short_title = (title[:12] + '...') if len(title) > 12 else title
        source_info = f"{name}-{short_title}"
        
        if contact.get('decrypted_mobile'):
            num = contact['decrypted_mobile']
            fmt_str = f"{num} ({source_info})"
            mobile_list.append(fmt_str)
            high_value_clues.append(f"{name}:{num}")
            
        if contact.get('phone'):
            num = contact['phone']
            if num != data.get('phone'):
                fmt_str = f"{num} ({source_info})"
                landline_list.append(fmt_str)

    # 智能简介：加入计数概览
    raw_count = data.get('total_contacts_raw', 0)
    fetched_count = len(data.get('contacts', []))
    
    stats_desc = (
        f"注册状态：{data.get('reg_status', '未知')}；"
        f"活跃度：投标{data.get('tender_count', 0)}次/中标{data.get('outbid_count', 0)}次；"
        f"收录联系人：{raw_count}个（已抓取{fetched_count}个详情）"
    )
    
    if high_value_clues:
        clues_desc = "；核心线索：" + "，".join(high_value_clues[:3]) 
    else:
        clues_desc = ""
        
    full_description = stats_desc + clues_desc

    return {
        "nickname": data.get('name', '未知企业'),
        "uid": data.get('company_id_encrypt', ''), 
        
        "description": full_description,
        
        "contact_mobile": "; ".join(mobile_list), 
        "contact_landline": "; ".join(landline_list),
        "contact_wechat": "", 
        "contact_qq": "",
        
        "followers_count": str(data.get('tender_count', 0)),
        "statuses_count": data.get('outbid_count', 0),
        
        # [关键修复] 显式增加联系人数量字段
        "total_contacts_count": raw_count,
        
        "verified_reason": f"企业认证: {data.get('reg_status', '')}",
        "details_raw": data.get('contacts', [])
    }

# ================= 主程序 =================
def local_main():
    print("=== 企业 OSINT 信息采集工具 V3 ===")
    user_text = input("请输入要查询的公司名称: ").strip()
    if not user_text: return

    print(f"[*] 正在搜索: {user_text} ...")
    company = do_search(user_text)
    
    if not company:
        print(json.dumps({"error": "未找到公司"}, ensure_ascii=False))
        return

    print("[*] 正在解析联系人与解密手机号...")
    processed_data = process_company_data(company)
    
    final_json = transform_to_osint_json(processed_data)
    
    print("\n" + "="*20 + " 采集结果 (JSON) " + "="*20)
    print(json.dumps(final_json, ensure_ascii=False, indent=4))
    print("="*60)

def handler(event):
    try:
        keyword = get_user_input(event)
        if not keyword: return {"error": "无关键词"}
        
        company = do_search(keyword)
        if not company: return {"error": "未找到公司"}
        
        processed_data = process_company_data(company)
        return transform_to_osint_json(processed_data)
        
    except Exception as e:
        return {"error": str(e)}

if __name__ == '__main__':
    local_main()
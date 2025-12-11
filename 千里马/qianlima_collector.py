"""
千里马信息收集插件
集成千里马招标网API，收集企业招投标信息、联系人数据等
"""
import requests
import time
import math
from typing import Dict, Any, Optional, List
from datetime import datetime

import random

from app.core.base_collector import BaseCollector
from app.exceptions import AntiSpiderException, CollectorException, DataValidationException


class QianlimaCollector(BaseCollector):
    """
    千里马收集器
    调用千里马招标网API收集企业招投标信息和联系人数据
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化千里马收集器

        Args:
            config: 配置参数
                - x_auth_token: 千里马API认证Token
                - timeout: 请求超时时间 (秒)
                - mock_mode: 是否使用Mock模式
                - user_agent: 用户代理字符串
        """
        super().__init__(config)
        self.version = "1.0.0"
        self.plugin_type = "procurement_info"

        # 配置参数
        self.x_auth_token = self.config.get("x_auth_token", "5a412c9b-468e-421d-a3b6-f61a55ce1e15")
        self.timeout = self.config.get("timeout", 30)
        self.mock_mode = self.config.get("mock_mode", False)
        self.user_agent = self.config.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        # API基础URL
        self.base_urls = {
            "company_search": "https://search.vip.qianlima.com/rest/enterprise/enterprise/companySearch",
            "contacts_list": "https://search.vip.qianlima.com/rest/enterprise/enterprise/contacts/list",
            "decrypt_phone": "https://search.vip.qianlima.com/rest/enterprise/virtual/phone/bind"
        }

        # 请求头
        self.headers = {
            "User-Agent": self.user_agent,
            "x-auth-token": self.x_auth_token,
        }

    def run(self, target_name: str) -> Dict[str, Any]:
        """
        执行千里马数据收集

        Args:
            target_name: 目标公司名称

        Returns:
            标准化的数据字典
        """
        self.log(f"开始收集千里马数据: {target_name}")

        try:
            if self.mock_mode:
                self.log("使用Mock模式，返回模拟数据")
                return self._mock_collect(target_name)
            else:
                self.log("使用真实API模式")
                return self._real_collect(target_name)

        except AntiSpiderException:
            self.log("遇到反爬虫机制", level="WARNING")
            raise
        except Exception as e:
            self.log(f"收集失败: {str(e)}", level="ERROR")
            raise CollectorException(f"千里马数据收集失败: {str(e)}")

    def _real_collect(self, target_name: str) -> Dict[str, Any]:
        """
        真实API模式：调用千里马API收集数据

        Args:
            target_name: 目标公司名称

        Returns:
            标准化数据
        """
        # 1. 搜索公司信息
        company_info = self._search_company(target_name)
        if not company_info:
            raise CollectorException(f"未找到公司: {target_name}")

        # 2. 获取联系人信息
        contacts = self._get_all_contacts(company_info["companyNameEncrypt"], company_info["companyContacts"])

        # 3. 构建标准化的目标数据
        target_data = self._build_target_data(company_info)

        # 4. 标准化联系人数据
        persons_data = self._standardize_contacts(contacts)

        return self.get_standard_response(
            success=True,
            target_data=target_data,
            persons_data=persons_data,
            metadata={
                "data_source": "qianlima_api",
                "collection_mode": "API",
                "raw_company_info": company_info,
                "reliability": 0.9
            }
        )

    def _search_company(self, keyword: str) -> Optional[Dict[str, Any]]:
        """
        搜索公司信息

        Args:
            keyword: 搜索关键词

        Returns:
            公司信息字典或None
        """
        url = f"{self.base_urls['company_search']}?keyword={keyword}&_={int(time.time() * 1000)}"

        try:
            response = self._make_request(url)
            if response and response.get("code") == 200:
                return response.get("data", {})
            return None
        except Exception as e:
            self.log(f"搜索公司失败: {str(e)}", level="ERROR")
            return None

    def _get_contacts(self, company_id: str, page_no: int = 1, page_size: int = 20) -> Optional[Dict[str, Any]]:
        """
        获取联系人列表

        Args:
            company_id: 公司ID
            page_no: 页码
            page_size: 每页大小

        Returns:
            联系人列表数据或None
        """
        url = f"{self.base_urls['contacts_list']}?company={company_id}&pageNo={page_no}&pageSize={page_size}&requestType=website&phoneType=&_={int(time.time() * 1000)}"

        try:
            response = self._make_request(url)
            if response and response.get("code") == 200:
                data = response.get("data", {})
                # 确保有totalCount字段
                if "totalCount" not in data:
                    data["totalCount"] = len(data.get("dataList", []))
                return data
            return None
        except Exception as e:
            self.log(f"获取联系人失败: {str(e)}", level="ERROR")
            return None

    def _get_all_contacts(self, company_id: str, total_contacts: int, page_size: int = 20) -> List[Dict[str, Any]]:
        """
        获取所有页的联系人信息

        Args:
            company_id: 公司ID
            total_contacts: 联系人总数
            page_size: 每页大小

        Returns:
            完整的联系人列表
        """
        all_contacts = []
        total_pages = math.ceil(total_contacts / page_size)

        for page_no in range(1, total_pages + 1):
            self.log(f"正在获取第 {page_no}/{total_pages} 页联系人...")
            contacts_page = self._get_contacts(company_id, page_no, page_size)

            if contacts_page and contacts_page.get("dataList"):
                all_contacts.extend(contacts_page["dataList"])
                time.sleep(0.5)  # 避免请求过快

        return all_contacts

    def _decrypt_phone(self, mobile_hash: str) -> Optional[str]:
        """
        解密电话号码

        Args:
            mobile_hash: 加密的电话号码哈希

        Returns:
            解密后的电话号码或None
        """
        url = f"{self.base_urls['decrypt_phone']}/{mobile_hash}"

        try:
            response = self._make_request(url)
            if response and response.get("code") == 200:
                data = response.get("data", {})
                return data.get("vmMobile")
            return None
        except Exception as e:
            self.log(f"解密电话失败: {str(e)}", level="WARNING")
            return None

    def _make_request(self, url: str) -> Optional[Dict[str, Any]]:
        """
        发起HTTP请求

        Args:
            url: 请求URL

        Returns:
            响应数据或None

        Raises:
            AntiSpiderException: 遇到反爬虫
            CollectorException: 请求失败
        """
        try:
            self.log(f"请求URL: {url}")
            response = requests.get(url, headers=self.headers, timeout=self.timeout)

            # 检查反爬虫
            if response.status_code == 403:
                raise AntiSpiderException("访问被拒绝，可能触发反爬虫")
            elif response.status_code == 429:
                raise AntiSpiderException("请求频率过高，已被限流")
            elif response.status_code != 200:
                raise CollectorException(f"请求失败，状态码: {response.status_code}")

            return response.json()

        except requests.exceptions.Timeout:
            raise CollectorException("请求超时")
        except requests.exceptions.RequestException as e:
            raise CollectorException(f"请求异常: {str(e)}")

    def _mock_collect(self, target_name: str) -> Dict[str, Any]:
        """
        Mock模式：返回模拟的千里马数据

        Args:
            target_name: 目标公司名称

        Returns:
            模拟的标准化数据
        """
        time.sleep(2)  # 模拟API延迟

        # 模拟公司信息
        mock_company_info = {
            "name": target_name,
            "companyNameEncrypt": f"encrypted_{hash(target_name)}",
            "phoneNumber": self._generate_mock_phone(),
            "regStatus": "存续",
            "tenderCount": 15,
            "outBidCount": 8,
            "companyContacts": 12
        }

        # 模拟联系人数据
        mock_contacts = self._generate_mock_contacts(target_name)

        # 构建标准化的目标数据
        target_data = self._build_target_data(mock_company_info)

        # 标准化联系人数据
        persons_data = self._standardize_contacts(mock_contacts)

        return self.get_standard_response(
            success=True,
            target_data=target_data,
            persons_data=persons_data,
            metadata={
                "data_source": "mock",
                "collection_mode": "MOCK",
                "raw_company_info": mock_company_info,
                "reliability": 0.5
            }
        )

    def _build_target_data(self, company_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        根据公司信息构建目标数据

        Args:
            company_info: 公司信息

        Returns:
            标准化的目标数据
        """
        target_name = company_info.get("name", "未知公司")

        target_data = {
            "name": target_name,
            "domain": self._generate_domain(target_name),
            "industry_type": "other",  # 千里马主要面向各行业，默认设为other
            "description": f"{target_name}的招投标信息，通过千里马招标网收集",
            "location": company_info.get("location", "中国"),
            "employee_count": company_info.get("companyContacts", 0),
            "website": f"https://www.{self._generate_domain(target_name)}",
            "phone": company_info.get("phoneNumber", ""),
            "reg_status": company_info.get("regStatus", ""),
            "tender_count": company_info.get("tenderCount", 0),
            "outbid_count": company_info.get("outBidCount", 0)
        }

        # 如果有招投标数据，更新描述
        tender_count = target_data["tender_count"]
        outbid_count = target_data["outbid_count"]

        if tender_count > 0 or outbid_count > 0:
            target_data["description"] += f"。历史参与投标{tender_count}次，中标{outbid_count}次"

        return target_data

    def _standardize_contacts(self, contacts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        标准化联系人数据

        Args:
            contacts: 原始联系人数据

        Returns:
            标准化的联系人列表
        """
        persons = []

        for contact in contacts:
            # 尝试解密手机号
            decrypted_mobile = None
            if contact.get("mobile"):
                decrypted_mobile = self._decrypt_phone(contact["mobile"])

            person = {
                "name": contact.get("linkMan", "未知"),
                "position": contact.get("title", "员工"),
                "department": "",  # 千里马数据中可能没有部门信息
                "email": self._generate_email_from_name(contact.get("linkMan", "")),
                "phone": contact.get("phone", ""),
                "mobile": contact.get("mobile", ""),
                "decrypted_mobile": decrypted_mobile,
                "linkedin_url": "",  # 千里马通常不包含LinkedIn信息
                "data_source": "qianlima",
                "source_confidence": 0.8
            }

            persons.append(person)

        return persons

    def _generate_mock_contacts(self, target_name: str) -> List[Dict[str, Any]]:
        """
        生成模拟联系人数据

        Args:
            target_name: 公司名称

        Returns:
            模拟联系人列表
        """
        import random

        names = ["张经理", "李总监", "王主任", "赵主管", "刘代表"]
        titles = ["采购经理", "项目经理", "商务总监", "技术主管", "销售代表"]

        contacts = []

        for i in range(random.randint(3, 7)):
            contact = {
                "id": i + 1,
                "companyId": 1,
                "source": 1,
                "linkMan": random.choice(names),
                "title": random.choice(titles),
                "phone": self._generate_mock_phone(),
                "mobile": f"encrypted_{random.randint(100000, 999999)}",
                "contentId": i + 1,
                "count": 1
            }
            contacts.append(contact)

        return contacts

    def _generate_domain(self, company_name: str) -> str:
        """生成域名"""
        import re
        domain = re.sub(r'[^\w]', '', company_name.lower())[:20]
        return f"{domain}.com"

    def _generate_email_from_name(self, name: str) -> str:
        """根据姓名生成邮箱"""
        if not name:
            return "unknown@example.com"
        import re
        name_clean = re.sub(r'[^\w]', '', name.lower())
        return f"{name_clean}@company.com"

    def _generate_mock_phone(self) -> str:
        """生成模拟手机号"""
        import random
        return f"13{random.randint(100000000, 999999999)}"

    def validate(self, data: Dict[str, Any]) -> bool:
        """
        验证数据格式

        Args:
            data: 待验证的数据

        Returns:
            是否验证通过

        Raises:
            DataValidationException: 数据格式不符合要求
        """
        # 调用基础结构验证
        self.validate_basic_structure(data)

        # 验证目标数据
        target = data["target"]
        if not target.get("name"):
            raise DataValidationException("目标公司名称不能为空")

        # 验证千里马特有的字段
        if "tender_count" in target and not isinstance(target["tender_count"], int):
            raise DataValidationException("投标数量必须是整数")

        if "outbid_count" in target and not isinstance(target["outbid_count"], int):
            raise DataValidationException("中标数量必须是整数")

        # 验证metadata中是否有千里马特有的数据
        metadata = data.get("metadata", {})
        if "raw_company_info" in metadata:
            company_info = metadata["raw_company_info"]
            if not isinstance(company_info, dict):
                raise DataValidationException("原始公司信息数据格式错误")

        self.log("数据验证通过")
        return True


# ===== 测试函数 =====
def test_qianlima_collector():
    """测试千里马收集器"""
    print("=" * 60)
    print("千里马收集器测试")
    print("=" * 60)

    # 测试Mock模式
    print("\n[测试] Mock模式")
    collector = QianlimaCollector(config={
        "mock_mode": True,
        "x_auth_token": "test_token"
    })

    try:
        result = collector.run("测试工程有限公司")
        print(f"✅ Mock模式测试成功")
        print(f"   公司名称: {result['target']['name']}")
        print(f"   投标次数: {result['target'].get('tender_count', 0)}")
        print(f"   中标次数: {result['target'].get('outbid_count', 0)}")
        print(f"   员工数量: {len(result['persons'])}")
        print(f"   数据源: {result['metadata']['data_source']}")

    except Exception as e:
        print(f"❌ Mock模式测试失败: {str(e)}")


if __name__ == "__main__":
    test_qianlima_collector()
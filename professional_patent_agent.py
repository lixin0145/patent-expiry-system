import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
import requests
import sqlite3
import time
import json
import re
from typing import List, Dict, Optional
import warnings
warnings.filterwarnings('ignore')

# ===== 页面配置 =====
st.set_page_config(
    page_title="专利过期选品智能系统",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===== 自定义CSS美化 =====
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 2rem;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .main-header h1 {
        margin: 0;
        font-size: 2.5rem;
        font-weight: 600;
    }
    .main-header p {
        margin: 0.5rem 0 0 0;
        opacity: 0.9;
        font-size: 1.1rem;
    }
    .stat-card {
        background: white;
        padding: 1.2rem;
        border-radius: 10px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        text-align: center;
        border: 1px solid #f0f0f0;
        transition: transform 0.2s;
    }
    .stat-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .stat-card .label {
        color: #666;
        font-size: 0.9rem;
        margin-bottom: 0.5rem;
    }
    .stat-card .value {
        font-size: 2rem;
        font-weight: 600;
        color: #667eea;
    }
    .stat-card .unit {
        font-size: 0.9rem;
        color: #999;
        margin-left: 0.2rem;
    }
    .stButton button {
        background-color: #667eea;
        color: white;
        border: none;
    }
    .stButton button:hover {
        background-color: #5a67d8;
    }
    .result-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 0.5rem;
        border-left: 4px solid #667eea;
    }
</style>
""", unsafe_allow_html=True)

# ===== 数据库模块 =====
class PatentDatabase:
    """本地专利数据库"""
    
    def __init__(self, db_path="patents.db"):
        self.db_path = db_path
        self.init_database()
    
    def init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 专利基本信息表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS patents (
                patent_id TEXT PRIMARY KEY,
                title TEXT,
                assignee TEXT,
                filing_date TEXT,
                expiry_date TEXT,
                abstract TEXT,
                ipc_class TEXT,
                uspc_class TEXT,
                search_keywords TEXT,
                added_date TEXT
            )
        ''')
        
        # 专利分析结果表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis (
                patent_id TEXT PRIMARY KEY,
                opportunity_score INTEGER,
                estimated_price REAL,
                competitor_reviews INTEGER,
                notes TEXT,
                status TEXT DEFAULT '待调研',
                priority TEXT DEFAULT '中'
            )
        ''')
        
        # 检索历史表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS search_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keywords TEXT,
                result_count INTEGER,
                search_date TEXT
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def save_patents(self, patents: List[Dict], keywords: str):
        """批量保存专利到数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        saved_count = 0
        for p in patents:
            try:
                cursor.execute('''
                    INSERT OR REPLACE INTO patents 
                    (patent_id, title, assignee, filing_date, expiry_date, 
                     abstract, ipc_class, uspc_class, search_keywords, added_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    p.get('专利号', ''),
                    p.get('标题', ''),
                    p.get('申请人', '未知'),
                    p.get('申请日', ''),
                    p.get('过期日', ''),
                    p.get('摘要', '')[:1000],
                    p.get('IPC分类', ''),
                    p.get('USPC分类', ''),
                    keywords,
                    current_date
                ))
                saved_count += 1
            except Exception as e:
                print(f"保存专利 {p.get('专利号')} 失败: {e}")
        
        conn.commit()
        conn.close()
        return saved_count
    
    def save_analysis(self, patent_id: str, analysis_data: Dict):
        """保存专利分析结果"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT OR REPLACE INTO analysis
            (patent_id, opportunity_score, estimated_price, competitor_reviews, 
             notes, status, priority)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            patent_id,
            analysis_data.get('机会分', 0),
            analysis_data.get('预估售价', 0),
            analysis_data.get('竞争评论数', 0),
            analysis_data.get('备注', ''),
            analysis_data.get('状态', '待调研'),
            analysis_data.get('优先级', '中')
        ))
        
        conn.commit()
        conn.close()
    
    def get_patent_list(self, status: Optional[str] = None, min_score: int = 0) -> pd.DataFrame:
        """获取专利列表"""
        conn = sqlite3.connect(self.db_path)
        
        query = '''
            SELECT 
                p.patent_id as "专利号",
                p.title as "标题",
                p.assignee as "申请人",
                p.expiry_date as "过期日",
                p.filing_date as "申请日",
                p.ipc_class as "IPC分类",
                a.opportunity_score as "机会分",
                a.estimated_price as "预估售价",
                a.competitor_reviews as "竞争评论数",
                a.status as "状态",
                a.priority as "优先级",
                a.notes as "备注"
            FROM patents p
            LEFT JOIN analysis a ON p.patent_id = a.patent_id
            WHERE 1=1
        '''
        params = []
        
        if status and status != '全部':
            query += ' AND a.status = ?'
            params.append(status)
        
        if min_score > 0:
            query += ' AND (a.opportunity_score IS NULL OR a.opportunity_score >= ?)'
            params.append(min_score)
        
        query += ' ORDER BY CASE WHEN a.opportunity_score IS NULL THEN 1 ELSE 0 END, a.opportunity_score DESC, p.added_date DESC'
        
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df
    
    def update_patent_status(self, patent_id: str, status: str, notes: str = ""):
        """更新专利状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM analysis WHERE patent_id = ?', (patent_id,))
        exists = cursor.fetchone()[0] > 0
        
        if exists:
            cursor.execute('''
                UPDATE analysis SET status = ?, notes = ?
                WHERE patent_id = ?
            ''', (status, notes, patent_id))
        else:
            cursor.execute('''
                INSERT INTO analysis (patent_id, status, notes, opportunity_score, estimated_price, competitor_reviews)
                VALUES (?, ?, ?, 70, 30, 200)
            ''', (patent_id, status, notes))
        
        conn.commit()
        conn.close()
    
    def export_to_excel(self, filename: str = "patent_shortlist.xlsx") -> str:
        """导出选品清单到Excel"""
        conn = sqlite3.connect(self.db_path)
        
        query = '''
            SELECT 
                p.patent_id as "专利号",
                p.title as "产品名称",
                p.assignee as "原品牌",
                p.expiry_date as "过期年份",
                p.ipc_class as "IPC分类",
                a.opportunity_score as "机会分",
                a.estimated_price as "预估售价($)",
                a.competitor_reviews as "竞争评论数",
                a.status as "状态",
                a.priority as "优先级",
                a.notes as "备注",
                p.added_date as "添加日期"
            FROM patents p
            LEFT JOIN analysis a ON p.patent_id = a.patent_id
            ORDER BY a.opportunity_score DESC
        '''
        
        df = pd.read_sql_query(query, conn)
        df.to_excel(filename, index=False)
        conn.close()
        return filename
    
    def log_search(self, keywords: str, result_count: int):
        """记录检索历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            INSERT INTO search_history (keywords, result_count, search_date)
            VALUES (?, ?, ?)
        ''', (keywords, result_count, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        
        conn.commit()
        conn.close()


# ===== USPTO Public Search API客户端（无需API Key）=====
class USPTOPublicSearchClient:
    """
    USPTO Public Search API - 完全免费，无需API Key
    基于 USPTO Public Search 后端 API
    """
    
    def __init__(self):
        # USPTO Public Search API 端点
        self.search_url = "https://ppubs.uspto.gov/pubsearch/patentSearch"
        self.detail_url = "https://ppubs.uspto.gov/pubsearch/patentDetail"
        self.max_retries = 3
        self.timeout = 45
        self.retry_delay = 2
    
    def build_query(self, keywords: List[str], filing_start_year: int, filing_end_year: int) -> str:
        """
        构建USPTO Public Search查询字符串
        
        USPTO Public Search 语法说明：
        - TTL: 标题字段
        - ABST: 摘要字段
        - APD: 申请日 (Application Date)
        - APT/1: 授权专利 (Granted Patent)
        - APT/2: 公开申请 (Published Application)
        """
        query_parts = []
        
        # 1. 关键词搜索（标题或摘要）
        if keywords:
            keyword_queries = []
            for kw in keywords[:3]:  # 取前3个关键词
                if kw.strip():
                    # 使用短语搜索
                    keyword_queries.append(f'(TTL/"{kw}" OR ABST/"{kw}")')
            
            if keyword_queries:
                combined_keywords = " OR ".join(keyword_queries)
                query_parts.append(f'({combined_keywords})')
        
        # 2. 申请日范围（过期日 = 申请日 + 20年）
        start_date = f"{filing_start_year}-01-01"
        end_date = f"{filing_end_year}-12-31"
        query_parts.append(f'APD/{start_date}->{end_date}')
        
        # 3. 只检索授权专利
        query_parts.append('APT/1')
        
        # 组合查询
        full_query = " AND ".join(query_parts)
        return full_query
    
    def search_expired_patents(self, 
                               keywords: List[str], 
                               expiry_start: int = 2024, 
                               expiry_end: int = 2026,
                               max_results: int = 30) -> List[Dict]:
        """
        搜索过期专利
        
        Args:
            keywords: 关键词列表
            expiry_start: 过期起始年份
            expiry_end: 过期结束年份
            max_results: 最大结果数
            
        Returns:
            专利列表
        """
        if not keywords:
            return []
        
        # 计算申请日范围（过期日 = 申请日 + 20年）
        filing_start = expiry_start - 20
        filing_end = expiry_end - 20
        
        # 构建查询
        query_string = self.build_query(keywords, filing_start, filing_end)
        
        if not query_string:
            st.warning("请至少输入一个有效关键词")
            return []
        
        # 请求参数
        params = {
            'q': query_string,
            'rows': max_results,
            'start': 0,
            'format': 'json'
        }
        
        # 重试机制
        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    st.info(f"⏳ 第{attempt+1}次尝试，等待{self.retry_delay}秒...")
                    time.sleep(self.retry_delay * attempt)
                
                response = requests.get(
                    self.search_url,
                    params=params,
                    timeout=self.timeout,
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                    }
                )
                
                if response.status_code == 200:
                    data = response.json()
                    patents = self._parse_response(data, expiry_start, expiry_end)
                    
                    if patents:
                        st.success(f"✅ 成功检索到 {len(patents)} 条专利")
                        return patents
                    else:
                        st.info("未找到匹配的过期专利，请尝试其他关键词")
                        return []
                        
                elif response.status_code == 429:
                    wait_time = self.retry_delay * (attempt + 1) * 2
                    st.warning(f"⚠️ 请求频率过高，等待{wait_time}秒后重试...")
                    time.sleep(wait_time)
                    
                elif response.status_code >= 500:
                    st.warning(f"⚠️ USPTO服务器错误({response.status_code})，重试中...")
                    
                else:
                    st.error(f"请求失败: HTTP {response.status_code}")
                    if attempt == self.max_retries - 1:
                        return []
                    
            except requests.exceptions.Timeout:
                st.warning(f"⏰ 第{attempt+1}次请求超时，重试中...")
                time.sleep(self.retry_delay * (attempt + 1))
                
            except requests.exceptions.ConnectionError:
                st.warning(f"🔌 第{attempt+1}次连接失败，请检查网络/VPN")
                time.sleep(self.retry_delay * (attempt + 1))
                
            except Exception as e:
                st.error(f"搜索异常: {str(e)}")
                if attempt == self.max_retries - 1:
                    return []
                time.sleep(self.retry_delay)
        
        return []
    
    def _parse_response(self, data: Dict, expiry_start: int, expiry_end: int) -> List[Dict]:
        """
        解析USPTO API响应
        """
        results = []
        
        try:
            # 解析返回的文档列表
            docs = data.get('response', {}).get('docs', [])
            
            for doc in docs:
                # 获取专利号
                patent_id = doc.get('patentNumber', '')
                if not patent_id:
                    patent_id = doc.get('documentId', '')
                
                # 获取标题
                title = doc.get('inventionTitle', '')
                if not title:
                    title = doc.get('title', '')
                
                # 获取申请日
                filing_date = doc.get('applicationDate', '')
                if not filing_date:
                    filing_date = doc.get('filingDate', '')
                
                # 计算过期日
                if filing_date and len(filing_date) >= 4:
                    try:
                        filing_year = int(filing_date[:4])
                        expiry_year = filing_year + 20
                    except:
                        filing_year = 2000
                        expiry_year = 2024
                else:
                    filing_year = 2000
                    expiry_year = 2024
                
                # 过滤过期年份
                if expiry_year < expiry_start or expiry_year > expiry_end:
                    continue
                
                # 获取申请人
                assignee = doc.get('applicantName', '')
                if not assignee:
                    assignee = doc.get('assignee', '')
                if isinstance(assignee, list):
                    assignee = assignee[0] if assignee else '未知'
                if not assignee or assignee == '':
                    assignee = '未知'
                
                # 获取摘要
                abstract = doc.get('abstract', '')
                if isinstance(abstract, list):
                    abstract = abstract[0] if abstract else ''
                
                # 获取IPC分类
                ipc = doc.get('ipcClassification', '')
                if isinstance(ipc, list):
                    ipc = ipc[0] if ipc else ''
                
                # 获取USPC分类
                uspc = doc.get('uspcClassification', '')
                if isinstance(uspc, list):
                    uspc = uspc[0] if uspc else ''
                
                results.append({
                    "专利号": patent_id,
                    "标题": title[:200] if title else '',
                    "申请人": assignee,
                    "过期日": f"{expiry_year}-01-01",
                    "申请日": filing_date[:10] if filing_date else '',
                    "摘要": abstract[:500] if abstract else '',
                    "IPC分类": ipc,
                    "USPC分类": uspc,
                    "过期年份": expiry_year
                })
                
        except Exception as e:
            print(f"解析响应失败: {e}")
        
        return results
    
    def test_connection(self) -> bool:
        """测试API连接"""
        try:
            test_query = self.build_query(["test"], 2000, 2001)
            response = requests.get(
                self.search_url,
                params={'q': test_query, 'rows': 1, 'format': 'json'},
                timeout=20
            )
            if response.status_code == 200:
                return True
        except:
            pass
        return False


# ===== 分析模块 =====
class PatentAnalyzer:
    """专利分析工具"""
    
    @staticmethod
    def calculate_opportunity_score(patent: Dict) -> int:
        """计算机会分"""
        score = 60
        
        # 过期时间加分
        if patent.get("过期年份"):
            current_year = datetime.now().year
            years_expired = current_year - patent["过期年份"]
            if years_expired > 0:
                score += min(years_expired * 3, 15)
        
        # 品牌加分
        known_brands = ["OXO", "Simplehuman", "Joseph Joseph", "IKEA", "Rubbermaid", 
                        "Procter", "Gamble", "3M", "Kimberly", "Scotch"]
        assignee = patent.get("申请人", "")
        if assignee and any(brand.lower() in assignee.lower() for brand in known_brands):
            score += 15
        
        # IPC分类加分（基于亚马逊热销品类）
        high_value_ipc = ["A47J", "B65D", "A61B", "E04G", "A01K", "B65B", "A47G", "B25H"]
        ipc = patent.get("IPC分类", "")
        if ipc and any(code in ipc for code in high_value_ipc):
            score += 10
        
        # USPC分类加分
        high_value_uspc = ["D7", "D6", "D8", "D9"]
        uspc = patent.get("USPC分类", "")
        if uspc and any(code in uspc for code in high_value_uspc):
            score += 5
        
        return min(score, 100)
    
    @staticmethod
    def estimate_price(patent: Dict) -> float:
        """预估售价（基于IPC/USPC分类）"""
        ipc = patent.get("IPC分类", "")
        uspc = patent.get("USPC分类", "")
        
        # 厨房用品
        if any(x in ipc for x in ["A47J", "A47G"]) or any(x in uspc for x in ["D7"]):
            return round(np.random.uniform(25, 45), 2)
        # 包装/存储
        elif any(x in ipc for x in ["B65D", "A47B"]) or any(x in uspc for x in ["D6"]):
            return round(np.random.uniform(20, 38), 2)
        # 医疗/健康
        elif any(x in ipc for x in ["A61B", "A61F"]):
            return round(np.random.uniform(30, 60), 2)
        # 工具/五金
        elif any(x in ipc for x in ["E04G", "B25H"]) or any(x in uspc for x in ["D8"]):
            return round(np.random.uniform(35, 70), 2)
        # 宠物用品
        elif any(x in ipc for x in ["A01K"]):
            return round(np.random.uniform(18, 40), 2)
        else:
            return round(np.random.uniform(22, 48), 2)
    
    @staticmethod
    def estimate_competition(patent: Dict) -> int:
        """预估竞争程度（基于申请人类型）"""
        assignee = patent.get("申请人", "")
        
        if any(x in assignee for x in ["OXO", "Simplehuman", "Procter", "3M"]):
            return np.random.randint(100, 350)
        elif "个人" in assignee or not assignee or assignee == "未知":
            return np.random.randint(30, 150)
        else:
            return np.random.randint(150, 500)


# ===== 主应用 =====
class PatentApp:
    """主应用类"""
    
    def __init__(self):
        self.db = PatentDatabase()
        self.api = USPTOPublicSearchClient()
        self.analyzer = PatentAnalyzer()
        
        if 'current_page' not in st.session_state:
            st.session_state['current_page'] = 'main'
        if 'current_patent' not in st.session_state:
            st.session_state['current_patent'] = None
        if 'search_results' not in st.session_state:
            st.session_state['search_results'] = []
    
    def run(self):
        """运行应用"""
        if st.session_state['current_page'] == 'main':
            self.show_main_page()
        elif st.session_state['current_page'] == 'analysis':
            self.show_analysis_page()
    
    def show_main_page(self):
        """显示主页面"""
        
        # 侧边栏 - 网络状态
        with st.sidebar:
            st.markdown("### 🌐 网络状态")
            st.info("""
            ⚠️ **重要提示：**
            USPTO服务器位于美国，**需要配置VPN/代理**才能访问。
            """)
            
            if st.button("测试USPTO连接"):
                with st.spinner("测试中..."):
                    if self.api.test_connection():
                        st.success("✅ USPTO API连接正常")
                    else:
                        st.error("❌ 无法连接到USPTO，请检查VPN")
            
            st.markdown("---")
            st.markdown("### 🔑 API信息")
            st.caption("✅ 使用USPTO Public Search API")
            st.caption("✅ 无需API Key，完全免费")
            
            st.markdown("---")
            st.markdown("### ⚙️ 筛选条件")
            min_price = st.number_input("最低售价 ($)", value=28, step=1, key="min_price")
            max_reviews = st.number_input("最大评论数", value=500, step=50, key="max_reviews")
            expiry_start = st.number_input("过期起始年", value=2024, step=1, key="expiry_start")
            expiry_end = st.number_input("过期结束年", value=2026, step=1, key="expiry_end")
            
            st.markdown("---")
            status_filter = st.selectbox(
                "专利状态",
                ["全部", "待调研", "样品中", "已看样", "已采购", "已上架", "淘汰"],
                key="status_filter"
            )
            
            st.markdown("---")
            st.markdown("**🔖 快捷检索**")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("🐶 宠物用品", use_container_width=True):
                    st.session_state['quick_keywords'] = "collapsible pet bowl\nfoldable dog bed\nportable pet feeder"
                    st.rerun()
            with col2:
                if st.button("🍳 厨房收纳", use_container_width=True):
                    st.session_state['quick_keywords'] = "collapsible container\nspace saving organizer\nfoldable kitchen"
                    st.rerun()
        
        # 头部
        st.markdown("""
        <div class="main-header">
            <h1>⚖️ 专利过期选品智能系统</h1>
            <p>基于 USPTO Public Search · 免费 · 无需API Key</p>
        </div>
        """, unsafe_allow_html=True)
        
        # 统计卡片
        df_all = self.db.get_patent_list()
        total_patents = len(df_all)
        high_potential = len(df_all[df_all["机会分"] > 80]) if not df_all.empty and "机会分" in df_all.columns else 0
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(f"""
            <div class="stat-card">
                <div class="label">📊 本地专利库</div>
                <div class="value">{total_patents}</div>
                <div class="unit">件</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
            <div class="stat-card">
                <div class="label">🎯 高潜力产品</div>
                <div class="value">{high_potential}</div>
                <div class="unit">个</div>
            </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
            <div class="stat-card">
                <div class="label">📅 过期年份范围</div>
                <div class="value">{expiry_start}-{expiry_end}</div>
                <div class="unit">年</div>
            </div>
            """, unsafe_allow_html=True)
        
        # 搜索区域
        st.markdown("### 🔍 专利检索")
        
        # 获取关键词（支持快速检索）
        default_keywords = st.session_state.get('quick_keywords', "collapsible pet bowl\nfoldable container\nspace saving organizer")
        keywords_input = st.text_area(
            "**关键词（每行一个）**",
            value=default_keywords,
            height=100,
            help="输入与产品相关的关键词，每行一个。系统会自动在标题和摘要中搜索"
        )
        
        # 清空快速检索标记
        if 'quick_keywords' in st.session_state:
            del st.session_state['quick_keywords']
        
        # 标签页
        tab1, tab2, tab3, tab4 = st.tabs(["📊 专利列表", "📈 分析看板", "💡 选品库", "📤 导出"])
        
        # Tab 1: 专利列表
        with tab1:
            keywords = [k.strip() for k in keywords_input.split('\n') if k.strip()]
            
            col_btn1, col_btn2 = st.columns([1, 4])
            with col_btn1:
                search_clicked = st.button("🚀 开始检索", type="primary", use_container_width=True)
            
            if search_clicked:
                if not keywords:
                    st.error("❌ 请输入至少一个关键词")
                else:
                    with st.spinner("⏳ 正在从USPTO检索数据（需要VPN，可能需要30-60秒）..."):
                        patents = self.api.search_expired_patents(
                            keywords=keywords,
                            expiry_start=expiry_start,
                            expiry_end=expiry_end,
                            max_results=30
                        )
                        
                        if patents:
                            df = pd.DataFrame(patents)
                            
                            # 计算分析指标
                            df["机会分"] = df.apply(lambda x: self.analyzer.calculate_opportunity_score(x), axis=1)
                            df["预估售价"] = df.apply(lambda x: self.analyzer.estimate_price(x), axis=1)
                            df["竞争评论数"] = df.apply(lambda x: self.analyzer.estimate_competition(x), axis=1)
                            df["高潜力"] = (df["机会分"] > 80) & (df["竞争评论数"] < max_reviews) & (df["预估售价"] > min_price)
                            
                            # 保存到数据库
                            saved = self.db.save_patents(patents, ", ".join(keywords[:3]))
                            self.db.log_search(", ".join(keywords), len(patents))
                            
                            st.success(f"✅ 找到 {len(patents)} 条专利，已保存 {saved} 条")
                            
                            # 显示结果
                            display_df = df[["专利号", "标题", "申请人", "过期日", "机会分", "预估售价", "竞争评论数", "高潜力"]]
                            st.dataframe(display_df, use_container_width=True, hide_index=True)
                            
                            # 保存到session state供详情使用
                            st.session_state['search_results'] = df.to_dict('records')
                            
                            # 详情展开
                            for idx, row in df.iterrows():
                                with st.expander(f"📄 {row['标题'][:60]}..."):
                                    st.markdown(f"""
                                    <div class="result-card">
                                        <strong>专利号:</strong> {row['专利号']}<br>
                                        <strong>申请人:</strong> {row['申请人']}<br>
                                        <strong>申请日:</strong> {row['申请日']}<br>
                                        <strong>过期日:</strong> {row['过期日']}<br>
                                        <strong>IPC分类:</strong> {row.get('IPC分类', 'N/A')}<br>
                                        <strong>摘要:</strong> {row['摘要'][:300]}...
                                    </div>
                                    """, unsafe_allow_html=True)
                                    
                                    if st.button(f"🔍 详细分析", key=f"analyze_{idx}"):
                                        st.session_state['current_patent'] = row.to_dict()
                                        st.session_state['current_page'] = 'analysis'
                                        st.rerun()
                        else:
                            st.warning("未找到匹配的过期专利，请尝试以下建议：\n- 更换其他关键词\n- 扩大过期年份范围\n- 检查VPN是否正常")
            
            # 显示本地库
            st.markdown("### 📋 本地专利库")
            df_local = self.db.get_patent_list(status=status_filter if status_filter != "全部" else None)
            if not df_local.empty:
                st.dataframe(df_local, use_container_width=True, hide_index=True)
            else:
                st.info("本地专利库为空，请先检索专利")
        
        # Tab 2: 分析看板
        with tab2:
            st.subheader("📊 数据分析看板")
            df_local = self.db.get_patent_list()
            
            if not df_local.empty:
                col1, col2 = st.columns(2)
                
                with col1:
                    top_assignees = df_local["申请人"].value_counts().head(8)
                    if len(top_assignees) > 0:
                        fig1 = px.pie(values=top_assignees.values, names=top_assignees.index, 
                                      title="主要申请人分布", hole=0.4)
                        st.plotly_chart(fig1, use_container_width=True)
                    else:
                        st.info("暂无申请人数据")
                
                with col2:
                    if "机会分" in df_local.columns:
                        fig2 = px.histogram(df_local, x="机会分", nbins=20, 
                                           title="机会分分布", color_discrete_sequence=["#667eea"])
                        st.plotly_chart(fig2, use_container_width=True)
                
                if "状态" in df_local.columns:
                    status_counts = df_local["状态"].value_counts()
                    if len(status_counts) > 0:
                        fig3 = px.bar(x=status_counts.index, y=status_counts.values, 
                                     title="专利状态分布")
                        st.plotly_chart(fig3, use_container_width=True)
            else:
                st.info("暂无数据，请先检索专利")
        
        # Tab 3: 选品库
        with tab3:
            st.subheader("💡 我的选品库")
            df_local = self.db.get_patent_list()
            
            if not df_local.empty:
                for idx, row in df_local.iterrows():
                    cols = st.columns([1.5, 3, 1, 1, 1.5, 1])
                    
                    with cols[0]:
                        st.write(f"**{row['专利号']}**")
                    with cols[1]:
                        short_title = row['标题'][:30] + "..." if len(row['标题']) > 30 else row['标题']
                        st.write(short_title)
                    with cols[2]:
                        if pd.notna(row['机会分']):
                            st.write(f"**{int(row['机会分'])}**")
                    with cols[3]:
                        status_options = ["待调研", "样品中", "已看样", "已采购", "已上架", "淘汰"]
                        current = row['状态'] if pd.notna(row['状态']) else "待调研"
                        new_status = st.selectbox(
                            "状态", status_options,
                            index=status_options.index(current) if current in status_options else 0,
                            key=f"status_{idx}", label_visibility="collapsed"
                        )
                        if new_status != current:
                            self.db.update_patent_status(row['专利号'], new_status, 
                                                          row['备注'] if pd.notna(row['备注']) else "")
                            st.rerun()
                    with cols[4]:
                        priority = row['优先级'] if pd.notna(row['优先级']) else "中"
                        st.write(f"{'🔴' if priority=='高' else '🟡' if priority=='中' else '⚪'} {priority}")
                    with cols[5]:
                        if st.button("查看", key=f"view_{idx}"):
                            patent_info = {
                                "专利号": row['专利号'],
                                "标题": row['标题'],
                                "申请人": row['申请人'],
                                "过期日": row['过期日'],
                                "申请日": row['申请日'],
                                "IPC分类": row['IPC分类'],
                                "机会分": row['机会分'] if pd.notna(row['机会分']) else 70,
                                "预估售价": row['预估售价'] if pd.notna(row['预估售价']) else 30,
                                "竞争评论数": row['竞争评论数'] if pd.notna(row['竞争评论数']) else 200,
                                "摘要": row.get('摘要', '')
                            }
                            st.session_state['current_patent'] = patent_info
                            st.session_state['current_page'] = 'analysis'
                            st.rerun()
                    
                    st.markdown("---")
            else:
                st.info("选品库为空，请先检索专利")
        
        # Tab 4: 导出
        with tab4:
            st.subheader("📤 导出选品清单")
            
            df_export = self.db.get_patent_list()
            if not df_export.empty:
                st.write(f"当前选品库共有 **{len(df_export)}** 件专利")
                
                if st.button("📥 导出为Excel", use_container_width=True):
                    filename = self.db.export_to_excel()
                    with open(filename, "rb") as f:
                        st.download_button(
                            label="点击下载 Excel",
                            data=f,
                            file_name=f"patent_shortlist_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
            else:
                st.info("暂无数据可导出")
    
    def show_analysis_page(self):
        """显示产品分析页面"""
        patent = st.session_state.get('current_patent', {})
        
        if not patent:
            st.error("未选择专利")
            if st.button("返回"):
                st.session_state['current_page'] = 'main'
                st.rerun()
            return
        
        # 导航
        col1, col2 = st.columns([1, 5])
        with col1:
            if st.button("← 返回"):
                st.session_state['current_page'] = 'main'
                st.rerun()
        with col2:
            st.title(f"📊 {patent.get('标题', '')[:80]}")
            st.caption(f"专利号: {patent.get('专利号', '')} | {patent.get('申请人', '')}")
        
        # 基本信息
        st.markdown("### 📋 专利信息")
        cols = st.columns(4)
        with cols[0]:
            st.metric("申请日", patent.get('申请日', '未知')[:10] if patent.get('申请日') else "未知")
        with cols[1]:
            st.metric("过期日", patent.get('过期日', '未知')[:10] if patent.get('过期日') else "未知")
        with cols[2]:
            st.metric("IPC分类", patent.get('IPC分类', '未知') or 'N/A')
        
        # AI洞察
        st.markdown("### 🔎 产品洞察")
        
        score = patent.get('机会分', 70)
        price = patent.get('预估售价', 30)
        reviews = patent.get('竞争评论数', 200)
        
        cols = st.columns(3)
        with cols[0]:
            st.metric("机会分", f"{score}/100", 
                     delta="高潜力" if score > 80 else ("中潜力" if score > 60 else "低潜力"))
        with cols[1]:
            st.metric("预估售价", f"${price:.2f}")
        with cols[2]:
            st.metric("竞争评论数", reviews)
        
        # 优势机会
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**✅ 优势**")
            if score > 80:
                st.success(f"✓ 机会分{score}，属于高潜力产品")
            elif score > 60:
                st.info(f"✓ 机会分{score}，中等潜力，可进一步调研")
            if reviews < 300:
                st.success(f"✓ 竞争较小（{reviews}条评论），市场空间大")
            if price > 28:
                st.success(f"✓ 预估售价${price:.0f}，符合利润要求")
        
        with col2:
            st.markdown("**💡 选品建议**")
            if "collaps" in patent.get('标题', '').lower():
                st.info("💡 可改进折叠结构，增加耐用性")
            if "container" in patent.get('标题', '').lower():
                st.info("💡 可增加密封功能和不同尺寸规格")
            if "pet" in patent.get('标题', '').lower() or "bowl" in patent.get('标题', '').lower():
                st.info("💡 宠物用品市场持续增长，建议关注环保材质")
            st.info("💡 建议查看亚马逊同类产品差评，寻找改进点")
        
        # 摘要
        if patent.get('摘要'):
            st.markdown("### 📄 专利摘要")
            st.write(patent.get('摘要'))
        
        # 外部链接
        st.markdown("### 🔗 外部链接")
        col1, col2 = st.columns(2)
        with col1:
            search_term = patent.get('标题', '').replace(' ', '+')
            st.markdown(f"[📦 在亚马逊搜索产品](https://www.amazon.com/s?k={search_term})")
        with col2:
            patent_id = patent.get('专利号', '')
            st.markdown(f"[📄 USPTO官方页面](https://patents.google.com/patent/{patent_id})")
        
        # 状态更新
        st.markdown("### 📌 状态管理")
        status = st.selectbox("更新状态", ["待调研", "样品中", "已看样", "已采购", "已上架", "淘汰"])
        notes = st.text_area("备注", height=100, placeholder="记录调研发现、供应商信息、市场观察等...")
        
        if st.button("保存状态", type="primary"):
            self.db.update_patent_status(patent.get('专利号', ''), status, notes)
            analysis_data = {
                '机会分': score,
                '预估售价': price,
                '竞争评论数': reviews,
                '状态': status,
                '备注': notes,
                '优先级': '高' if score > 85 else ('中' if score > 70 else '低')
            }
            self.db.save_analysis(patent.get('专利号', ''), analysis_data)
            st.success("状态已保存")
            time.sleep(1)
            st.session_state['current_page'] = 'main'
            st.rerun()


# ===== 主程序 =====
if __name__ == "__main__":
    app = PatentApp()
    app.run()
import streamlit as st
from streamlit_lottie import st_lottie
import requests
import json
import logging
import datetime
import os
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import random
import time

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 设置页面配置
st.set_page_config(page_icon="🐶", layout="wide")

# 自定义 CSS，融入小金毛主题，使用透明的浅黄色背景，确保草稿卡片样式
st.markdown("""
<style>
    .stApp {
        background-color: rgba(255, 250, 205, 0.7); /* 浅黄色背景 (lemon chiffon) with 70% opacity */
    }
    .appview-container, .main > div {
        background-color: transparent !important;
    }
    .card {
        border: 1px solid #d4a017;
        border-radius: 8px;
        padding: 15px;
        margin: 10px;
        background-color: #fff8e1; /* 浅米色卡片背景 */
        box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        height: 100%; /* 卡片占满列高度 */
        display: flex;
        flex-direction: column; /* 卡片内部垂直排列 */
        justify-content: space-between; /* 内容和按钮分布 */
    }
    .card-title {
        font-size: 1.2em;
        font-weight: bold;
        margin-bottom: 10px;
        color: #d4a017; /* 金色标题 */
    }
    .card-content {
        flex-grow: 1; /* 内容填充剩余空间 */
        margin-bottom: 10px;
    }
    .stButton > button {
        width: 100%;
        margin-top: 10px;
        background-color: #f7c948; /* 金色按钮 */
        color: white;
        border: none;
        border-radius: 5px;
    }
    .stButton > button:hover {
        background-color: #e0b428; /* 深金色按钮悬停 */
    }
    .sidebar .sidebar-content {
        background-color: #ffe4b5 !important; /* 浅黄色 (moccasin) 侧边栏背景 */
        color: #333; /* 侧边栏文本颜色 */
        border-radius: 10px;
        padding: 20px;
        box-shadow: 2px 2px 5px #d4a017;
    }
    .sidebar h2, .sidebar h3, .sidebar h4, .sidebar h5, .sidebar h6, .sidebar p, .sidebar label, .sidebar st-radio, .sidebar st-text-input, .sidebar st-date-input, .sidebar st-text-area, .sidebar st-form > div > button {
        color: #54450d; /* 侧边栏深棕色文本 */
 precursor}
    h1 {
        color: #d4a017; /* 金色标题 */
        font-family: 'Arial Black', sans-serif; /* 粗体艺术字体 */
        text-align: center; /* 居中标题 */
        text-shadow: 2px 2px 4px #ffffff, -2px -2px 4px #ffffff, 2px -2px 4px #ffffff, -2px 2px 4px #ffffff; /* White border effect */
    }
    h2 {
        color: #e0b428; /* 深金色副标题 */
        text-align: center; /* 居中副标题 */
        text-shadow: 2px 2px 4px #ffffff, -2px -2px 4px #ffffff, 2px -2px 4px #ffffff, -2px 2px 4px #ffffff; /* White border effect */
    }
</style>
""", unsafe_allow_html=True)

def icon(emoji: str):
    """显示小金毛风格的页面图标"""
    st.markdown(
        f'<span style="font-size: 78px; line-height: 1">{emoji}</span>',
        unsafe_allow_html=True,
    )

def create_session():
    """创建带重试机制的 HTTP 会话"""
    session = requests.Session()
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("http://", HTTPAdapter(max_retries=retries))
    return session

def select_draft(draft):
    """处理草稿选择并生成详细规划"""
    with st.status("🐶 **小金毛生成详细规划中...**", state="running", expanded=True) as status:
        with st.container(height=500, border=False):
            try:
                session = create_session()
                logger.info(f"发送草稿选择请求：draft={draft[:50]}...")
                response = session.post(
                    "http://localhost:8001/plan",
                    json={
                        "mode": "单城市",
                        "city": st.session_state.city,
                        "days": st.session_state.days,
                        "user_input": st.session_state.user_input,
                        "selected_draft": draft
                    },
                    timeout=300
                )
                logger.info(f"收到响应：{response.status_code}, {response.text}")
                st.session_state.last_response = response.text
                response_data = response.json()
                if response.status_code != 200:
                    st.error(f"后端返回错误：状态码 {response.status_code}, 详情：{response_data.get('detail', response.text)}")
                elif response_data.get("error"):
                    st.error(f"后端处理失败：{response_data['error']}")
                elif response_data.get("final_plan"):
                    st.session_state.final_plan = response_data["final_plan"]
                    st.session_state.stage = "final"
            except requests.Timeout:
                st.error("请求超时：后端响应时间过长，请检查后端服务")
                logger.error("请求超时", exc_info=True)
            except requests.ConnectionError:
                st.error("无法连接到后端服务：请确保后端服务在 http://localhost:8001 运行，并检查高德 MCP 服务 http://localhost:8000/sse")
                logger.error("无法连接到后端服务", exc_info=True)
            except requests.InvalidURL:
                st.error("无效的请求URL：请检查后端服务地址 http://localhost:8001")
                logger.error("无效的请求URL", exc_info=True)
            except requests.RequestException as e:
                st.error(f"请求失败：{str(e)}")
                logger.error(f"请求失败：{str(e)}", exc_info=True)
            except ValueError as e:
                st.error(f"响应解析失败：{str(e)}，后端响应：{st.session_state.last_response}")
                logger.error(f"响应解析失败：{str(e)}", exc_info=True)
        status.update(label="✅ 小金毛详细规划完成！", state="complete", expanded=False)

if __name__ == "__main__":
    st.markdown("<h1 style='text-align: center;'>🐶 小金毛旅游导航</h1>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align: center;'>🐾 让小金毛为您的下一次旅行导航！</h2>", unsafe_allow_html=True)

    # 状态管理
    if 'stage' not in st.session_state:
        st.session_state.stage = "input"
        st.session_state.drafts = None
        st.session_state.final_plan = None
        st.session_state.cities = None
        st.session_state.user_input = None
        st.session_state.city = None
        st.session_state.days = None
        st.session_state.last_response = None

    # 侧边栏
    with st.sidebar:
        st.header("🐾 🐕 小金毛帮您规划 🐾")
        with st.form("my_form"):
            mode = st.radio("选择行程类型", ["单城市", "多城市"])
            today = datetime.datetime.now().date()
            if mode == "单城市":
                city = st.text_input("城市名称", placeholder="请输入城市，如：北京")
                date_range = st.date_input(
                    "选择旅行日期范围",
                    min_value=today,
                    value=(today, today + datetime.timedelta(days=3)),
                    format="MM/DD/YYYY",
                )
                if isinstance(date_range, tuple) and len(date_range) == 2:
                    days = (date_range[1] - date_range[0]).days
                    if days < 1 or days > 30:
                        st.error("旅行天数必须在 1-30 天之间")
                        days = None
                    else:
                        st.info(f"您选择了 {days} 天的行程")
                else:
                    days = None
                    st.error("请选择有效的日期范围")
                user_input_placeholder = "请输入您的旅行偏好，例如：喜欢历史文化、当地美食、舒适的酒店、便捷的公共交通。示例：我想游览北京的历史景点，品尝正宗北京烤鸭，住三星级酒店，优先地铁出行。"
            else:
                city = None
                days = None
                user_input_placeholder = "请输入您的旅行需求，例如：我想去北京3天、上海2天，喜欢历史文化和当地美食，住舒适酒店，优先高铁出行。"
            user_input = st.text_area(
                "兴趣爱好或行程额外详情",
                placeholder=user_input_placeholder,
                height=200,
                help="请尽量详细描述您的偏好（如景点类型、餐饮口味、住宿要求、交通方式），以获得更精准的规划！"
            )
            submitted = st.form_submit_button("提交")

        st.markdown("<hr style='border: 2px dotted #d4a017;'>", unsafe_allow_html=True)
        st.sidebar.markdown(
            """
            感谢您的使用！愿小金毛带您畅游世界！🐾
            """,
            unsafe_allow_html=True
        )

    # 提交需求
    if submitted and user_input and (mode == "多城市" or (mode == "单城市" and city and days)):
        st.session_state.stage = "drafts" if mode == "单城市" else "cities"
        st.session_state.user_input = user_input
        st.session_state.city = city
        st.session_state.days = days
        with st.status("🐶 **小金毛正在为您规划...**", state="running", expanded=True) as status:
            with st.container(height=500, border=False):
                st.markdown("正在生成行程规划，请稍候...")
                st.spinner("小金毛努力思考中 🐾")
                try:
                    session = create_session()
                    logger.info(f"发送请求：mode={mode}, city={city}, days={days}, user_input={user_input[:50]}...")
                    response = session.post(
                        "http://localhost:8001/plan",
                        json={"mode": mode, "city": city, "days": days, "user_input": user_input},
                        timeout=180
                    )
                    logger.info(f"收到响应：{response.status_code}, {response.text}")
                    st.session_state.last_response = response.text
                    response_data = response.json()
                    if response.status_code != 200:
                        st.error(f"后端返回错误：状态码 {response.status_code}, 详情：{response_data.get('detail', response.text)}")
                        st.session_state.stage = "input"
                    elif response_data.get("error"):
                        st.error(f"后端处理失败：{response_data['error']}")
                        st.session_state.stage = "input"
                    elif response_data.get("drafts"):
                        st.session_state.drafts = response_data["drafts"]
                        st.session_state.stage = "drafts"
                    elif response_data.get("cities"):
                        st.session_state.cities = response_data["cities"]
                        st.session_state.stage = "cities"
                    elif response_data.get("final_plan"):
                        st.session_state.final_plan = response_data["final_plan"]
                        st.session_state.stage = "final"
                except requests.Timeout:
                    st.error("请求超时：后端响应时间过长，请检查后端服务（Azure OpenAI 或高德 MCP）")
                    logger.error("请求超时", exc_info=True)
                    st.session_state.stage = "input"
                except requests.ConnectionError:
                    st.error("无法连接到后端服务：请确保后端服务在 http://localhost:8001 运行，并检查高德 MCP 服务 http://localhost:8000/sse")
                    logger.error("无法连接到后端服务", exc_info=True)
                    st.session_state.stage = "input"
                except requests.InvalidURL:
                    st.error("无效的请求URL：请检查后端服务地址 http://localhost:8001")
                    logger.error("无效的请求URL", exc_info=True)
                    st.session_state.stage = "input"
                except requests.RequestException as e:
                    st.error(f"请求失败：{str(e)}")
                    logger.error(f"请求失败：{str(e)}", exc_info=True)
                    st.session_state.stage = "input"
                except ValueError as e:
                    st.error(f"响应解析失败：{str(e)}，后端响应：{st.session_state.last_response}")
                    logger.error(f"响应解析失败：{str(e)}", exc_info=True)
                    st.session_state.stage = "input"
            status.update(label="✅ 小金毛规划完成！", state="complete", expanded=False)

    # 显示用户输入
    if st.session_state.user_input:
        st.subheader("您的需求", anchor=False, divider="rainbow")
        st.markdown(f"**用户输入**：{st.session_state.user_input}")


    # 显示草稿方案（修改1：移除综合方案，调整为 3 列）
    if st.session_state.stage == "drafts" and st.session_state.drafts:
        st.subheader("小金毛的草稿方案", anchor=False, divider="rainbow")
        cols = st.columns(3)  # 调整为 3 列
        for i, draft in enumerate(st.session_state.drafts, 1):
            with cols[i-1]:
                st.markdown(
                    f'<div class="card">'
                    f'<div class="card-title">方案 {i}</div>'
                    f'<div class="card-content">{draft}</div>',
                    unsafe_allow_html=True
                )
                if st.button(f"选择方案 {i}", key=f"draft_{i}"):
                    select_draft(draft)
                st.markdown('</div>', unsafe_allow_html=True)

    # 显示多城市规划
    if st.session_state.stage == "cities" and st.session_state.cities:
        st.subheader("小金毛的城市分配", anchor=False, divider="rainbow")
        for city_plan in st.session_state.cities:
            with st.container():
                st.markdown(f"#### {city_plan['city']} ({city_plan['days']}天)")
                if city_plan.get("plan"):
                    st.markdown(f"**规划总结**：{city_plan['plan']['summary']}")
                    with st.expander("详细安排"):
                        st.markdown("##### 景点安排")
                        st.write(city_plan["plan"]["view"])
                        st.markdown("##### 餐饮安排")
                        st.write(city_plan["plan"]["food"])
                        st.markdown("##### 住宿安排")
                        st.write(city_plan["plan"]["accommodation"])
                        st.markdown("##### 出行安排")
                        st.write(city_plan["plan"]["traffic"])
        st.info("请在侧栏输入具体城市和天数，继续规划单城市行程。")

    # 显示详细规划
    # 在 if st.session_state.stage == "final" and st.session_state.final_plan: 块中，替换天气信息相关代码
    if st.session_state.stage == "final" and st.session_state.final_plan:
        st.subheader("小金毛的详细行程规划", anchor=False, divider="rainbow")
        with st.container():
            # 显示 summary_source
            source_text = "总结 Agent" if st.session_state.final_plan['summary_source'] == "agent" else "字符串拼接（回退）"
            st.markdown(f"**规划生成方式**：{source_text}")
            st.markdown(f"**详细行程规划**：\n{st.session_state.final_plan['summary']}")
            with st.expander("单独查看各项安排"):
                st.markdown(f"**景区安排**：\n{st.session_state.final_plan['view']}")
                st.markdown(f"**餐饮安排**：\n{st.session_state.final_plan['food']}")
                st.markdown(f"**住宿安排**：\n{st.session_state.final_plan['accommodation']}")
                st.markdown(f"**出行安排**：\n{st.session_state.final_plan['traffic']}")
                # 显示天气信息
                weather_info = st.session_state.final_plan.get('weather', None)
                if weather_info and "天气查询失败" not in weather_info:
                    st.markdown(f"**天气信息**：\n{weather_info}")
                else:
                    # 备选：从 summary 中提取
                    if '天气信息：' in st.session_state.final_plan['summary']:
                        summary_weather = st.session_state.final_plan['summary'].split('天气信息：')[-1].strip()
                        if summary_weather and "天气查询失败" not in summary_weather:
                            st.markdown(f"**天气信息（从总结提取）**：\n{summary_weather}")
                        else:
                            st.markdown(f"**天气信息**：\n{weather_info or summary_weather or '无法获取天气信息，请检查日志或网络连接'}")
                    else:
                        st.markdown(f"**天气信息**：\n{weather_info or '无法获取天气信息，请检查日志或网络连接'}")
        if st.button("返回草稿"):
            st.session_state.stage = "drafts"

import asyncio
import json
import re
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import logging
from langchain_mcp_adapters.client import MultiServerMCPClient
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from functools import lru_cache
import time

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 初始化 FastAPI 应用
app = FastAPI()

# 初始化语言模型
model = AzureChatOpenAI(
    openai_api_version="2024-12-01-preview",
    deployment_name="gpt-4o",
    azure_endpoint="https://ai-14911520644664ai275106389756.openai.azure.com/",
    api_key="5YzhcN3wCRnFORXYl9SPWpzb7RIPRQmew0V71y0chvR6g6j8hcFOJQQJ99BDACHYHv6XJ3w3AAAAACOGFi3L",
    max_tokens=2048,
)

# 定义请求数据模型
class PlanRequest(BaseModel):
    mode: str
    city: Optional[str] = None
    days: Optional[int] = None
    user_input: str
    selected_draft: Optional[str] = None

async def init_mcp_client():
    """异步初始化 MCP 客户端并返回工具"""
    try:
        async with MultiServerMCPClient(
            {
                "gaode": {
                    "url": "http://localhost:8000/sse",
                    "transport": "sse",
                }
            }
        ) as client:
            return client.get_tools()
    except Exception as e:
        logger.error(f"MCP 客户端初始化失败: {e}")
        raise Exception(f"MCP 客户端初始化失败: {str(e)}")

async def generate_drafts(agent, city_name: str, days: int, user_input: str, num_drafts: int = 3):
    """为单个城市生成多个草稿行程，分别偏向运动、文化和美食"""
    # 查询天气信息（与 single_city_plan 对齐）
    messages_weather = [
        SystemMessage(
            f"使用工具查询{city_name}的当前及未来数日天气情况，并以简洁的文本形式返回。"
        ),
        HumanMessage(f"查询{city_name}的天气"),
    ]
    weather_info = None
    for attempt in range(3):
        try:
            async with MultiServerMCPClient(
                {
                    "gaode": {
                        "url": "http://localhost:8000/sse",
                        "transport": "sse",
                    }
                }
            ) as client:
                temp_agent = create_react_agent(model, client.get_tools())
                response_weather = await temp_agent.ainvoke({"messages": messages_weather})
                weather_info = response_weather["messages"][-1].content
                logger.debug(f"草稿天气查询成功 (尝试 {attempt + 1})，结果: {weather_info}")
                break
        except Exception as e:
            logger.error(f"草稿天气查询尝试 {attempt + 1} 失败: {str(e)}，完整错误: {repr(e)}")
            if attempt == 2:
                weather_info = f"天气查询失败: {str(e)}"
            await asyncio.sleep(2 ** attempt)

    drafts = []
    draft_prompts = [
        f"你需要为用户希望的旅行提供更加偏运动的方案选择，快速给出笼统的旅行方案，基于用户偏好：{user_input}，城市：{city_name}，天数：{days}。",
        f"你需要为用户希望的旅行提供更加偏文化的方案选择，快速给出笼统的旅行方案，基于用户偏好：{user_input}，城市：{city_name}，天数：{days}。",
        f"你需要为用户希望的旅行提供更加偏美食的方案选择，快速给出笼统的旅行方案，基于用户偏好：{user_input}，城市：{city_name}，天数：{days}。",
    ]

    async def run_draft_agent(prompt, draft_num):
        messages = [
            SystemMessage(
                f"""为{city_name}的{days}天行程生成一个草稿方案，基于用户偏好：{user_input}。
                {prompt}
                根据以下天气情况：{weather_info}，确保推荐的景点、餐饮、住宿和交通安排适合天气条件。
                输出简洁的文本，概述主要景点、餐饮、住宿、交通安排和天气情况。"""
            ),
            HumanMessage(f"草稿 {draft_num}：{city_name}，{days}天，偏好：{user_input}"),
        ]
        try:
            response = await agent.ainvoke({"messages": messages})
            return response["messages"][-1].content
        except Exception as e:
            logger.error(f"生成草稿 {draft_num} 失败: {e}")
            return f"草稿 {draft_num} 生成失败: {str(e)}"

    # 并行生成草稿
    draft_tasks = [run_draft_agent(prompt, i + 1) for i, prompt in enumerate(draft_prompts)]
    drafts = await asyncio.gather(*draft_tasks, return_exceptions=True)
    return drafts

async def single_city_plan(agent, city_name: str, days: int, preferences: str, selected_draft: Optional[str] = None, drafts: Optional[list] = None):
    """为单个城市生成行程规划，遵循 main_langchain(5).py 的逻辑"""
    start_time = time.time()
    logger.info(f"开始规划 {city_name} {days}天行程")

    # 任务拆分，匹配 main_langchain(5).py 的字段名称
    messages = [
        SystemMessage(
            f"""将用户对{city_name}的旅游需求（{preferences}）拆分为景区、住宿、餐饮、出行四个方面的详细要求，适合{days}天行程。
            参考选定的草稿：{selected_draft or '无'}。
            仅输出有效的 JSON 字符串，格式如下：
            {{"景区": "...", "住宿": "...", "餐饮": "...", "出行": "..."}}"""
        ),
        HumanMessage(f"{preferences} 用户希望的行程风格大致如下：{selected_draft or '无'}"),
    ]
    try:
        response = await agent.ainvoke({"messages": messages})
        core_content = response["messages"][-1].content
        tasks = json.loads(re.sub(r"```json\n|```", "", core_content).strip())
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"任务拆分失败: {e}")
        return {"error": f"任务拆分失败: {str(e)}"}

    view = tasks.get("景区", "")
    accommodation = tasks.get("住宿", "")
    food = tasks.get("餐饮", "")
    traffic = tasks.get("出行", "")

    # 独立查询天气信息（提前执行，完全对齐 backend.py）
    messages_weather = [
        SystemMessage(
            f"使用工具查询{city_name}的当前及未来数日天气情况，并以简洁的文本形式返回。"
        ),
        HumanMessage(f"查询{city_name}的天气"),
    ]
    weather_info = None
    for attempt in range(3):
        try:
            async with MultiServerMCPClient(
                {
                    "gaode": {
                        "url": "http://localhost:8000/sse",
                        "transport": "sse",
                    }
                }
            ) as client:
                # 重新创建代理以确保工具可用
                temp_agent = create_react_agent(model, client.get_tools())
                response_weather = await temp_agent.ainvoke({"messages": messages_weather})
                weather_info = response_weather["messages"][-1].content
                logger.debug(f"天气查询成功 (尝试 {attempt + 1})，结果: {weather_info}")
                break
        except Exception as e:
            logger.error(f"天气查询尝试 {attempt + 1} 失败: {str(e)}，完整错误: {repr(e)}")
            if attempt == 2:
                weather_info = f"天气查询失败: {str(e)}"
            await asyncio.sleep(2 ** attempt)

    # 定义查询函数，匹配 main_langchain(5).py 的提示词
    async def query_view():
        messages = [
            SystemMessage(
                f"""根据以下天气情况：{weather_info}，参考旅游攻略意见（{view}），为用户提出适合{city_name}未来{days}天的游玩景点。
                输出清晰的文本，列出景点名称、简介、开放时间、门票价格（如果适用）以及适合游览的理由（考虑天气影响）。"""
            ),
            HumanMessage(f"{city_name} {days}天景点推荐，偏好：{view}"),
        ]
        try:
            response = await agent.ainvoke({"messages": messages})
            return response["messages"][-1].content
        except Exception as e:
            return f"景点规划失败: {str(e)}"

    async def query_food():
        messages = [
            SystemMessage(
                f"""你是一个精确的旅游路线规划者，善于将景点规划与当地美食位置结合，为用户提供交通方便、口碑好的宝藏美食。
                参考旅游攻略意见（{food}），结合当地美食评价情况，为用户提出适合的享受当地美食的地点。
                输出清晰的文本，列出餐厅名称、特色菜、地址、价格范围（如果适用）。"""
            ),
            HumanMessage(f"{city_name}餐饮推荐，偏好：{food}"),
        ]
        try:
            response = await agent.ainvoke({"messages": messages})
            return response["messages"][-1].content
        except Exception as e:
            return f"餐饮规划失败: {str(e)}"

    async def query_accommodation(view_plan):
        messages = [
            SystemMessage(
                f"""你是一个精确的旅游路线规划者，善于将景点规划与酒店住宿结合起来，为用户提供交通方便、靠近景区的住宿地点。
                参考旅游景点规划：{view_plan}，借鉴旅游攻略意见（{accommodation}），结合交通便利程度，为用户推荐合适的酒店住宿。
                输出清晰的文本，列出酒店名称、地址、房型、价格范围（如果适用）。"""
            ),
            HumanMessage(f"{city_name}住宿推荐，偏好：{accommodation}"),
        ]
        try:
            response = await agent.ainvoke({"messages": messages})
            return response["messages"][-1].content
        except Exception as e:
            return f"住宿规划失败: {str(e)}"

    async def query_traffic(view_plan, accommodation_plan):
        messages = [
            SystemMessage(
                f"""你是一个精确的旅游路线规划者，善于将景点规划、住宿安排中涉及的位置用合理的方式联系起来，为用户提供精确详细的出行方案。
                根据以下天气情况：{weather_info}，参考旅游景点规划：{view_plan}以及住宿安排：{accommodation_plan}，借鉴旅游攻略意见（{traffic}），提供{city_name}未来{days}天的合理详细出行路线规划。
                输出清晰的文本，包含每段路线的起点、终点、交通方式、预计时间和费用（如果适用），考虑天气对交通的影响。"""
            ),
            HumanMessage(f"{city_name}交通规划，偏好：{traffic}"),
        ]
        try:
            response = await agent.ainvoke({"messages": messages})
            return response["messages"][-1].content
        except Exception as e:
            return f"交通规划失败: {str(e)}"

    # 执行景点查询（基于 weather_info）
    view_plan = await query_view()

    # 顺序执行餐饮、住宿、交通查询，确保依赖关系
    food_plan = await query_food()
    accommodation_plan = await query_accommodation(view_plan)
    traffic_plan = await query_traffic(view_plan, accommodation_plan)

    logger.info(f"分步规划耗时: {time.time() - start_time:.2f}秒")

    # 总结行程，使用总结 Agent
    summary_source = "agent"
    messages_summary = [
        SystemMessage(
            f"""整理以下内容，为用户撰写详细完整的{city_name} {days}天旅游计划，内容需包含景点、餐饮、住宿、出行和天气信息：
            - 景区安排：{view_plan}
            - 餐饮安排：{food_plan}
            - 住宿安排：{accommodation_plan}
            - 出行安排：{traffic_plan}
            - 天气信息：{weather_info}
            输出格式为清晰的文本，按以下结构组织：
            详细行程规划：
            景区安排：
            {view_plan}
            餐饮安排：
            {food_plan}
            住宿安排：
            {accommodation_plan}
            出行安排：
            {traffic_plan}
            天气信息：
            {weather_info}
            确保输出内容忠实反映输入的各部分规划，并包含天气信息。"""
        ),
        HumanMessage(f"{city_name} {days}天行程规划，偏好：{preferences}"),
    ]
    try:
        response_summary = await agent.ainvoke({"messages": messages_summary})
        summary = response_summary["messages"][-1].content
    except Exception as e:
        logger.error(f"总结行程失败: {e}")
        summary_source = "fallback"
        summary = f"""详细行程规划：
景区安排：
{view_plan}
餐饮安排：
{food_plan}
住宿安排：
{accommodation_plan}
出行安排：
{traffic_plan}
天气信息：
{weather_info}"""

    logger.info(f"总查询耗时: {time.time() - start_time:.2f}秒")

    return {
        "summary": summary,
        "summary_source": summary_source,
        "view": view_plan,
        "food": food_plan,
        "accommodation": accommodation_plan,
        "traffic": traffic_plan,
        "weather": weather_info  # 新增 weather 字段，便于前端直接访问
    }

async def parse_multi_city_input(agent, user_input: str):
    """解析多城市输入，生成城市列表，包含城市名称、天数和偏好"""
    system_prompt = """
you是一个行程规划助手，任务是分析用户的多城市旅行需求，生成一个包含城市名称、停留天数和具体偏好的 JSON 列表。
规则：
1. 输出必须是严格的 JSON 格式，例如：[{"name": "上海", "days": 3, "preferences": "文化景点，当地美食"}, {"name": "北京", "days": 2, "preferences": "历史遗迹"}]
2. 不要包含任何额外文本、解释或 markdown（如 ```json）。 
3. 如果用户输入不明确（如缺少城市、天数或偏好），返回空列表：[]
4. 确保每个城市的 'days' 是正整数，且总天数合理分配。
5. 'preferences' 字段包含用户对景点、餐饮、住宿或出行的具体要求（如 "文化景点，当地美食"），如果未指定，留空字符串。
6. 如果无法解析需求，返回空列表：[]
"""
    messages = [
        SystemMessage(system_prompt),
        HumanMessage(user_input),
    ]
    try:
        response = await agent.ainvoke({"messages": messages})
        raw_content = response["messages"][-1].content.strip()
        cleaned_content = re.sub(r"```json\n|```|\n|\t", "", raw_content).strip()
        cities = json.loads(cleaned_content)
        if not isinstance(cities, list):
            raise ValueError("响应不是列表")
        for city in cities:
            if not isinstance(city, dict) or "name" not in city or "days" not in city or "preferences" not in city:
                raise ValueError("城市格式无效")
            if not isinstance(city["days"], int) or city["days"] <= 0:
                raise ValueError("天数必须为正整数")
        return cities
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"解析多城市输入失败: {e}")
        return []

async def plan_multi_city(agent, cities):
    """为多个城市生成综合行程规划，包括城市间交通"""
    complete_plan = []
    previous_city = None

    for city in cities:
        city_name = city["name"]
        days = city["days"]
        preferences = city["preferences"]
        logger.info(f"规划 {city_name} {days}天行程，偏好：{preferences}")

        # 生成单城市计划
        city_plan = await single_city_plan(agent, city_name, days, preferences)
        if "error" in city_plan:
            complete_plan.append({"city": city_name, "days": days, "error": city_plan["error"]})
        else:
            complete_plan.append({"city": city_name, "days": days, "plan": city_plan})

        # 规划城市间交通
        if previous_city:
            messages = [
                SystemMessage(
                    f"""使用工具查询从{previous_city}到{city_name}的交通方式（飞机、高铁、汽车等）。
                    输出清晰的文本，包含推荐的交通方式、预计时间、费用（如果适用）以及预订建议。"""
                ),
                HumanMessage(f"从{previous_city}到{city_name}的交通方式"),
            ]
            try:
                response = await agent.ainvoke({"messages": messages})
                transport_plan = response["messages"][-1].content
                complete_plan.append({"transport": f"从{previous_city}到{city_name}", "details": transport_plan})
            except Exception as e:
                complete_plan.append({"transport": f"从{previous_city}到{city_name}", "error": f"交通查询失败: {str(e)}"})
        previous_city = city_name

    return complete_plan

@app.post("/plan")
async def plan(request: PlanRequest):
    """处理前端发送的行程规划请求"""
    try:
        tools = await init_mcp_client()
        agent = create_react_agent(model, tools)
        logger.info(f"收到请求：mode={request.mode}, city={request.city}, days={request.days}, user_input={request.user_input[:50]}...")

        if request.mode == "单城市":
            if not request.city or not request.days or request.days <= 0:
                raise HTTPException(status_code=400, detail="单城市模式需要提供城市名称和有效天数")

            if request.selected_draft:
                # 根据选定的草稿生成详细计划
                final_plan = await single_city_plan(
                    agent, request.city, request.days,
                    f"{request.user_input}。选定的草稿：{request.selected_draft}",
                    request.selected_draft
                )
                if "error" in final_plan:
                    raise HTTPException(status_code=500, detail=final_plan["error"])
                return {"final_plan": final_plan}
            else:
                # 生成草稿行程
                drafts = await generate_drafts(agent, request.city, request.days, request.user_input)
                return {"drafts": drafts}

        elif request.mode == "多城市":
            # 解析多城市输入
            cities = await parse_multi_city_input(agent, request.user_input)
            if not cities:
                raise HTTPException(status_code=400, detail="无法解析多城市输入，请明确指定城市、天数和偏好")

            # 生成多城市计划
            city_plans = await plan_multi_city(agent, cities)
            return {"cities": city_plans}

        else:
            raise HTTPException(status_code=400, detail="无效的模式，仅支持 '单城市' 或 '多城市'")

    except HTTPException as e:
        logger.error(f"HTTP错误: {e.detail}", exc_info=True)
        raise e
    except Exception as e:
        logger.error(f"行程规划失败: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"行程规划失败: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)

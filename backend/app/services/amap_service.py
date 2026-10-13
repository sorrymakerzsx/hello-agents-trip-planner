"""高德地图MCP服务封装"""

import json
from typing import List, Dict, Any, Optional
from hello_agents.tools import MCPTool
from ..config import get_settings
from ..models.schemas import Location, POIInfo, WeatherInfo
from ..harness.resilience import ResilientExecutor

# 全局MCP工具实例
_amap_mcp_tool = None


def get_amap_mcp_tool() -> MCPTool:
    """
    获取高德地图MCP工具实例(单例模式)
    
    Returns:
        MCPTool实例
    """
    global _amap_mcp_tool
    
    if _amap_mcp_tool is None:
        settings = get_settings()
        
        if not settings.amap_api_key:
            raise ValueError("高德地图API Key未配置,请在.env文件中设置AMAP_API_KEY")
        
        # 创建MCP工具
        _amap_mcp_tool = MCPTool(
            name="amap",
            description="高德地图服务,支持POI搜索、路线规划、天气查询等功能",
            # amap-mcp-server 当前依赖旧版 Pydantic 内部 API；通过 uvx
            # 单独约束其运行环境，避免和后端自身的 Pydantic 版本冲突。
            server_command=["uvx", "--with", "pydantic<2.12", "amap-mcp-server"],
            env={"AMAP_MAPS_API_KEY": settings.amap_api_key},
            auto_expand=True  # 自动展开为独立工具
        )
        
        print(f"✅ 高德地图MCP工具初始化成功")
        print(f"   工具数量: {len(_amap_mcp_tool._available_tools)}")
        
        # 打印可用工具列表
        if _amap_mcp_tool._available_tools:
            print("   可用工具:")
            for tool in _amap_mcp_tool._available_tools[:5]:  # 只打印前5个
                print(f"     - {tool.get('name', 'unknown')}")
            if len(_amap_mcp_tool._available_tools) > 5:
                print(f"     ... 还有 {len(_amap_mcp_tool._available_tools) - 5} 个工具")
    
    return _amap_mcp_tool


class AmapService:
    """高德地图服务封装类"""
    
    def __init__(self):
        """初始化服务"""
        self.mcp_tool = get_amap_mcp_tool()
        settings = get_settings()
        self.resilience = ResilientExecutor(
            cache_ttl_seconds=settings.resilience_cache_ttl_seconds,
            timeout_seconds=settings.resilience_timeout_seconds,
            max_retries=settings.resilience_max_retries,
            retry_delay_seconds=settings.resilience_retry_delay_seconds,
            circuit_failure_threshold=settings.resilience_circuit_failure_threshold,
            circuit_recovery_seconds=settings.resilience_circuit_recovery_seconds,
        )

    def _call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        """Call an Amap MCP tool through the resilience layer."""
        key = f"amap:{tool_name}:{json.dumps(arguments, ensure_ascii=False, sort_keys=True)}"
        return self.resilience.call(
            key,
            lambda: self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": tool_name,
                "arguments": arguments,
            }),
        )
    
    def _search_poi_legacy(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        """
        搜索POI
        
        Args:
            keywords: 搜索关键词
            city: 城市
            citylimit: 是否限制在城市范围内
            
        Returns:
            POI信息列表
        """
        try:
            # 调用MCP工具
            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": "maps_text_search",
                "arguments": {
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower()
                }
            })
            
            # 解析结果
            # 注意: MCP工具返回的是字符串,需要解析
            # 这里简化处理,实际应该解析JSON
            print(f"POI搜索结果: {result[:200]}...")  # 打印前200字符
            
            # TODO: 解析实际的POI数据
            return []
            
        except Exception as e:
            print(f"❌ POI搜索失败: {str(e)}")
            return []
    
    # Override the legacy implementation above with a parser for the current
    # amap-mcp-server response format.  The MCP result is usually a text
    # wrapper followed by a JSON object containing a ``pois`` list.
    def search_poi(self, keywords: str, city: str, citylimit: bool = True) -> List[POIInfo]:
        import json
        import re

        try:
            result = self._call_tool(
                "maps_text_search",
                {
                    "keywords": keywords,
                    "city": city,
                    "citylimit": str(citylimit).lower(),
                },
            )
            text = str(result).strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                payload = json.loads(match.group(0)) if match else {}

            raw_pois = payload.get("pois", []) if isinstance(payload, dict) else []
            pois: List[POIInfo] = []
            for item in raw_pois:
                if not isinstance(item, dict):
                    continue
                location = item.get("location", "")
                # maps_text_search may omit coordinates. Fetch the detail
                # record for that POI, which contains a location field.
                if not location and item.get("id"):
                    try:
                        detail_result = self._call_tool(
                            "maps_search_detail",
                            {"id": str(item["id"])},
                        )
                        detail_text = str(detail_result).strip()
                        try:
                            detail_payload = json.loads(detail_text)
                        except json.JSONDecodeError:
                            detail_match = re.search(r"\{.*\}", detail_text, re.DOTALL)
                            detail_payload = json.loads(detail_match.group(0)) if detail_match else {}
                        location = detail_payload.get("location", "") if isinstance(detail_payload, dict) else ""
                    except Exception:
                        location = ""
                try:
                    if isinstance(location, dict):
                        longitude = float(location.get("longitude", location.get("lng")))
                        latitude = float(location.get("latitude", location.get("lat")))
                    else:
                        longitude_text, latitude_text = str(location).split(",", 1)
                        longitude = float(longitude_text)
                        latitude = float(latitude_text)

                    pois.append(POIInfo(
                        id=str(item.get("id", "")),
                        name=str(item.get("name", "")),
                        type=str(item.get("type", item.get("typecode", "景点"))),
                        address=str(item.get("address", "")),
                        location=Location(longitude=longitude, latitude=latitude),
                        tel=item.get("tel") or None,
                    ))
                except (TypeError, ValueError, AttributeError):
                    continue

            print(f"Parsed {len(pois)} POIs from amap MCP response")
            return pois
        except Exception as e:
            print(f"POI search failed while parsing amap response: {e}")
            return []

    def get_weather(self, city: str) -> List[WeatherInfo]:
        """
        查询天气
        
        Args:
            city: 城市名称
            
        Returns:
            天气信息列表
        """
        try:
            # 调用MCP工具
            result = self.mcp_tool.run({
                "action": "call_tool",
                "tool_name": "maps_weather",
                "arguments": {
                    "city": city
                }
            })
            
            print(f"天气查询结果: {result[:200]}...")
            
            # TODO: 解析实际的天气数据
            return []
            
        except Exception as e:
            print(f"❌ 天气查询失败: {str(e)}")
            return []
    
    # Parse the current maps_weather response, which contains a forecasts list.
    def get_weather(self, city: str) -> List[WeatherInfo]:
        import json
        import re

        try:
            result = self._call_tool("maps_weather", {"city": city})
            text = str(result).strip()
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", text, re.DOTALL)
                payload = json.loads(match.group(0)) if match else {}

            forecasts = payload.get("forecasts", []) if isinstance(payload, dict) else []
            return [
                WeatherInfo(
                    date=str(item.get("date", "")),
                    day_weather=str(item.get("dayweather", "")),
                    night_weather=str(item.get("nightweather", "")),
                    day_temp=item.get("daytemp", 0),
                    night_temp=item.get("nighttemp", 0),
                    wind_direction=str(item.get("daywind", "")),
                    wind_power=str(item.get("daypower", "")),
                )
                for item in forecasts
                if isinstance(item, dict)
            ]
        except Exception as e:
            print(f"Weather parsing failed: {e}")
            return []

    def plan_route(
        self,
        origin_address: str,
        destination_address: str,
        origin_city: Optional[str] = None,
        destination_city: Optional[str] = None,
        route_type: str = "walking"
    ) -> Dict[str, Any]:
        """
        规划路线
        
        Args:
            origin_address: 起点地址
            destination_address: 终点地址
            origin_city: 起点城市
            destination_city: 终点城市
            route_type: 路线类型 (walking/driving/transit)
            
        Returns:
            路线信息
        """
        try:
            # 根据路线类型选择工具
            tool_map = {
                "walking": "maps_direction_walking_by_address",
                "driving": "maps_direction_driving_by_address",
                "transit": "maps_direction_transit_integrated_by_address"
            }
            
            tool_name = tool_map.get(route_type, "maps_direction_walking_by_address")
            
            # 构建参数
            arguments = {
                "origin_address": origin_address,
                "destination_address": destination_address
            }
            
            # 公共交通需要城市参数
            if route_type == "transit":
                if origin_city:
                    arguments["origin_city"] = origin_city
                if destination_city:
                    arguments["destination_city"] = destination_city
            else:
                # 其他路线类型也可以提供城市参数提高准确性
                if origin_city:
                    arguments["origin_city"] = origin_city
                if destination_city:
                    arguments["destination_city"] = destination_city
            
            # 调用MCP工具
            result = self._call_tool(tool_name, arguments)
            
            print(f"路线规划结果: {result[:200]}...")
            
            # TODO: 解析实际的路线数据
            return {}
            
        except Exception as e:
            print(f"❌ 路线规划失败: {str(e)}")
            return {}
    
    def geocode(self, address: str, city: Optional[str] = None) -> Optional[Location]:
        """
        地理编码(地址转坐标)

        Args:
            address: 地址
            city: 城市

        Returns:
            经纬度坐标
        """
        try:
            arguments = {"address": address}
            if city:
                arguments["city"] = city

            result = self._call_tool("maps_geo", arguments)

            print(f"地理编码结果: {result[:200]}...")

            # TODO: 解析实际的坐标数据
            return None

        except Exception as e:
            print(f"❌ 地理编码失败: {str(e)}")
            return None

    def get_poi_detail(self, poi_id: str) -> Dict[str, Any]:
        """
        获取POI详情

        Args:
            poi_id: POI ID

        Returns:
            POI详情信息
        """
        try:
            result = self._call_tool("maps_search_detail", {"id": poi_id})

            print(f"POI详情结果: {result[:200]}...")

            # 解析结果并提取图片
            import json
            import re

            # 尝试从结果中提取JSON
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return data

            return {"raw": result}

        except Exception as e:
            print(f"❌ 获取POI详情失败: {str(e)}")
            return {}


# 创建全局服务实例
_amap_service = None


def get_amap_service() -> AmapService:
    """获取高德地图服务实例(单例模式)"""
    global _amap_service
    
    if _amap_service is None:
        _amap_service = AmapService()
    
    return _amap_service

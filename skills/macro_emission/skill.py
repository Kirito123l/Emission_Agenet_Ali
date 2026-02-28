from pathlib import Path
from typing import Dict, Tuple, Optional, List
import logging
from ..base import BaseSkill, SkillResult, HealthCheckResult
from shared.standardizer.vehicle import get_vehicle_standardizer
from shared.standardizer.pollutant import get_pollutant_standardizer
from shared.standardizer.constants import SEASON_MAPPING
from .calculator import MacroEmissionCalculator
from .excel_handler import ExcelHandler
from llm.client import get_llm

logger = logging.getLogger(__name__)

class MacroEmissionSkill(BaseSkill):
    """宏观排放计算Skill"""

    # 参数定义
    REQUIRED_PARAMS = ["links_data"]  # 必需参数
    OPTIONAL_PARAMS = {  # 可选参数及默认值
        "model_year": 2020,  # 默认2020年
        "pollutants": ["CO2", "NOx"],
        "season": "夏季",
        "default_fleet_mix": None,  # 默认车队组成
        "links_data": None,  # 路段数据（与input_file二选一）
        "input_file": None,  # Excel输入文件路径
        "output_file": None,  # Excel输出文件路径
    }

    def __init__(self):
        self._vehicle_std = get_vehicle_standardizer()
        self._pollutant_std = get_pollutant_standardizer()
        self._calculator = MacroEmissionCalculator()
        # 获取LLM客户端用于智能列名映射
        try:
            llm_client = get_llm("agent")  # 使用agent的LLM配置
            self._excel_handler = ExcelHandler(llm_client=llm_client)
            logger.info("[宏观排放] 已启用智能列名映射")
        except Exception as e:
            logger.warning(f"[宏观排放] 无法获取LLM客户端，使用硬编码映射: {e}")
            self._excel_handler = ExcelHandler(llm_client=None)

    @property
    def name(self):
        return "calculate_macro_emission"

    @property
    def description(self):
        return "基于MOVES-Matrix方法计算道路路段级机动车排放"

    def get_brief_description(self) -> str:
        return "宏观排放计算（必需：links_data；可选：model_year, pollutants, season, default_fleet_mix）"

    def _fix_common_errors(self, links_data: List[Dict]) -> List[Dict]:
        """自动修复常见的参数错误"""
        fixed_links = []

        for link in links_data:
            fixed_link = {}

            # 字段名映射：正确名称 -> 可能的错误名称
            field_mapping = {
                "link_length_km": ["length", "link_length", "length_km", "road_length"],
                "traffic_flow_vph": ["traffic_volume_veh_h", "traffic_flow", "flow", "volume", "traffic_volume"],
                "avg_speed_kph": ["avg_speed_kmh", "speed", "avg_speed", "average_speed"],
                "fleet_mix": ["vehicle_composition", "vehicle_mix", "composition", "fleet_composition"],
                "link_id": ["id", "road_id", "segment_id"]
            }

            for correct_name, possible_names in field_mapping.items():
                # 先检查正确名称
                if correct_name in link:
                    fixed_link[correct_name] = link[correct_name]
                else:
                    # 检查可能的错误名称
                    for wrong_name in possible_names:
                        if wrong_name in link:
                            fixed_link[correct_name] = link[wrong_name]
                            logger.info(f"自动修复字段名: {wrong_name} -> {correct_name}")
                            break

            # 修复fleet_mix格式（如果是数组，转换为对象）
            if "fleet_mix" in fixed_link:
                fleet_mix = fixed_link["fleet_mix"]
                if isinstance(fleet_mix, list):
                    # 转换数组为对象
                    fixed_fleet_mix = {}
                    for item in fleet_mix:
                        if isinstance(item, dict):
                            if "vehicle_type" in item and "percentage" in item:
                                fixed_fleet_mix[item["vehicle_type"]] = item["percentage"]
                            elif "type" in item and "percentage" in item:
                                fixed_fleet_mix[item["type"]] = item["percentage"]
                    if fixed_fleet_mix:
                        fixed_link["fleet_mix"] = fixed_fleet_mix
                        logger.info("自动修复fleet_mix格式: 数组 -> 对象")

            fixed_links.append(fixed_link)

        return fixed_links

    def get_full_schema(self) -> Dict:
        """返回完整的参数schema"""
        return {
            "type": "object",
            "properties": {
                "links_data": {
                    "type": "array",
                    "description": "路段数据 [{\"link_id\": \"L1\", \"link_length_km\": 1.5, \"traffic_flow_vph\": 1000, \"avg_speed_kph\": 60, \"fleet_mix\": {...}}, ...]",
                    "required": True,
                    "items": {
                        "type": "object",
                        "properties": {
                            "link_id": {"type": "string", "description": "路段ID（可选）"},
                            "link_length_km": {"type": "number", "description": "路段长度(km)"},
                            "traffic_flow_vph": {"type": "number", "description": "交通流量(辆/小时)"},
                            "avg_speed_kph": {"type": "number", "description": "平均速度(km/h)"},
                            "fleet_mix": {
                                "type": "object",
                                "description": "车队组成（可选，百分比）",
                                "additionalProperties": {"type": "number"}
                            }
                        },
                        "required": ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
                    }
                },
                "pollutants": {
                    "type": "array",
                    "description": "污染物列表",
                    "items": {"type": "string"},
                    "default": ["CO2", "NOx"],
                },
                "model_year": {
                    "type": "integer",
                    "description": "车辆年份（1995-2025）",
                    "default": 2020,
                    "minimum": 1995,
                    "maximum": 2025,
                },
                "season": {
                    "type": "string",
                    "description": "季节",
                    "enum": ["春季", "夏季", "秋季", "冬季"],
                    "default": "夏季",
                },
                "default_fleet_mix": {
                    "type": "object",
                    "description": "默认车队组成（百分比，如果路段未指定）",
                    "additionalProperties": {"type": "number"},
                    "default": None,
                },
                "input_file": {
                    "type": "string",
                    "description": "Excel输入文件路径（.xlsx或.csv）- 与links_data二选一",
                    "required": False,
                },
                "output_file": {
                    "type": "string",
                    "description": "Excel输出文件路径（.xlsx或.csv）",
                    "required": False,
                },
            },
            "required": [],
        }

    def validate_params(self, params: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        验证参数完整性

        Returns:
            (is_valid, error_message, missing_params_info)
        """
        missing = []
        missing_info = {}

        # 检查links_data或input_file至少有一个
        has_links_data = params.get("links_data") is not None and params.get("links_data") != ""
        has_input_file = params.get("input_file") is not None and params.get("input_file") != ""

        if not has_links_data and not has_input_file:
            missing.append("links_data/input_file")
            missing_info["links_data"] = {
                "description": "路段数据或输入文件",
                "format": "[{\"link_length_km\": 1.5, \"traffic_flow_vph\": 1000, \"avg_speed_kph\": 60}, ...]",
                "note": "可以提供links_data数组，或使用input_file指定Excel文件路径"
            }

        # 验证links_data格式（如果提供）
        if has_links_data:
            links = params["links_data"]
            if not isinstance(links, list):
                return False, "links_data必须是列表", {}
            if len(links) == 0:
                return False, "links_data不能为空", {}

            required_fields = ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
            for i, link in enumerate(links):
                if not isinstance(link, dict):
                    return False, f"links_data[{i}]必须是对象", {}
                for field in required_fields:
                    if field not in link:
                        return False, f"links_data[{i}]缺少必需字段: {field}", {}

        if missing:
            return False, f"缺少必需参数: {', '.join(missing)}", missing_info

        return True, None, None

    def execute(self, **params) -> SkillResult:
        context = {"skill": self.name}

        # Map file_path to input_file if provided (parameter name compatibility)
        if "file_path" in params and "input_file" not in params:
            params["input_file"] = params["file_path"]
            logger.info(f"Mapped file_path to input_file: {params['file_path']}")

        logger.info(f"[MacroEmission] Received parameters: {list(params.keys())}")
        logger.debug(f"[MacroEmission] Full parameters: {params}")

        # 1. 验证必需参数
        is_valid, error, missing_info = self.validate_params(params)
        if not is_valid:
            return SkillResult(
                success=False,
                error=error,
                metadata={
                    "missing_params": missing_info,
                    "needs_clarification": True,
                }
            )

        # 2. 提取参数
        input_file = params.get("input_file")
        output_file = params.get("output_file")

        # 3. 获取路段数据（从参数或文件）
        if input_file:
            # 从Excel文件读取
            success, links_data, read_error = self._excel_handler.read_links_from_excel(input_file)
            if not success:
                return SkillResult(
                    success=False,
                    error=f"读取输入文件失败: {read_error}",
                    metadata={"input_file": input_file}
                )
        else:
            # 使用提供的links_data
            links_data = params["links_data"]

        # 自动修复常见错误
        links_data = self._fix_common_errors(links_data)

        model_year = params.get("model_year", self.OPTIONAL_PARAMS["model_year"])
        pollutants = params.get("pollutants", self.OPTIONAL_PARAMS["pollutants"])
        season = params.get("season", self.OPTIONAL_PARAMS["season"])
        default_fleet_mix = params.get("default_fleet_mix", self.OPTIONAL_PARAMS["default_fleet_mix"])

        # 4. 标准化污染物列表
        standardized_pollutants = []
        for pollutant in pollutants:
            p_result = self._pollutant_std.standardize(pollutant, context)
            if p_result.standard:
                standardized_pollutants.append(p_result.standard)

        if not standardized_pollutants:
            return SkillResult(
                success=False,
                error=f"无法识别任何污染物: {pollutants}",
                metadata={"needs_clarification": True}
            )

        # 5. 标准化车队组成（如果提供）
        standardized_fleet_mix = None
        if default_fleet_mix:
            standardized_fleet_mix = self._standardize_fleet_mix(default_fleet_mix, context)

        # 6. 标准化每个路段的车队组成
        standardized_links = []
        for link in links_data:
            std_link = link.copy()
            if "fleet_mix" in link and link["fleet_mix"]:
                std_link["fleet_mix"] = self._standardize_fleet_mix(link["fleet_mix"], context)
            standardized_links.append(std_link)

        # 7. 标准化季节
        season_std = SEASON_MAPPING.get(season.lower(), season)
        if season_std not in ["春季", "夏季", "秋季", "冬季"]:
            season_std = "夏季"

        # 8. 执行计算
        result = self._calculator.calculate(
            links_data=standardized_links,
            pollutants=standardized_pollutants,
            model_year=model_year,
            season=season_std,
            default_fleet_mix=standardized_fleet_mix,
        )

        # 9. 处理计算结果
        if result.get("status") == "error":
            return SkillResult(
                success=False,
                error=result.get("message", result.get("error")),
                metadata={
                    "error_code": result.get("error_code"),
                    "query_params": {
                        "pollutants": {"input": pollutants, "standard": standardized_pollutants},
                        "model_year": model_year,
                        "season": season_std,
                        "links_count": len(links_data),
                    }
                },
            )

        # 10. 写入输出文件（如果指定）
        if output_file:
            # 从result中提取结果数据
            results_data = result["data"].get("results", [])

            # 构建输出数据
            output_results = []
            for link_result in results_data:
                output_results.append({
                    "link_id": link_result.get("link_id", ""),
                    "link_length_km": link_result.get("link_length_km", 0),
                    "traffic_flow_vph": link_result.get("traffic_flow_vph", 0),
                    "avg_speed_kph": link_result.get("avg_speed_kph", 0),
                    "total_emissions": link_result.get("total_emissions_kg_per_hr", {})
                })

            write_success, write_error = self._excel_handler.write_results_to_excel(
                output_file,
                output_results
            )

            if not write_success:
                # 写入失败不影响计算结果，只记录警告
                result["data"]["output_file_warning"] = f"写入输出文件失败: {write_error}"
            else:
                result["data"]["output_file"] = output_file

        # 10.5. 生成下载文件（如果有input_file）
        download_info = None
        if input_file:
            try:
                from config import get_config
                config = get_config()
                outputs_dir = str(config.outputs_dir)

                # 从result中提取排放数据
                results_data = result["data"].get("results", [])

                # 生成结果Excel
                success, output_path, filename, error = self._excel_handler.generate_result_excel(
                    original_file_path=input_file,
                    emission_results=results_data,
                    pollutants=standardized_pollutants,
                    output_dir=outputs_dir
                )

                if success:
                    download_info = {
                        "path": output_path,
                        "filename": filename,
                        "description": "包含原始路段数据和排放计算结果的完整文件"
                    }
                    logger.info(f"生成下载文件成功: {filename}")
                else:
                    logger.warning(f"生成下载文件失败: {error}")
            except Exception as e:
                logger.exception("生成下载文件时出错")

        # 11. 返回成功结果
        return SkillResult(
            success=True,
            data=result["data"],
            metadata={
                "query_params": {
                    "pollutants": {"input": pollutants, "standard": standardized_pollutants},
                    "model_year": model_year,
                    "season": season_std,
                    "input_file": input_file,
                    "output_file": output_file,
                },
                "download_file": download_info,  # 添加下载文件信息
            }
        )

    def _standardize_fleet_mix(self, fleet_mix: Dict, context: Dict) -> Dict:
        """标准化车队组成中的车型名称"""
        standardized = {}
        for vehicle_name, percentage in fleet_mix.items():
            v_result = self._vehicle_std.standardize(vehicle_name, context)
            if v_result.standard:
                standardized[v_result.standard] = percentage
        return standardized

    def health_check(self) -> HealthCheckResult:
        checks = {}
        errors = []

        # 检查数据文件
        data_path = Path(__file__).parent / "data"
        checks["data_directory"] = data_path.exists()
        if not checks["data_directory"]:
            errors.append(f"数据目录不存在: {data_path}")

        csv_files = ["atlanta_2025_1_35_60 .csv", "atlanta_2025_4_75_65.csv", "atlanta_2025_7_80_60.csv"]
        for csv_file in csv_files:
            csv_path = data_path / csv_file
            checks[f"csv_{csv_file}"] = csv_path.exists()
            if not csv_path.exists():
                errors.append(f"CSV文件不存在: {csv_path}")

        return HealthCheckResult(
            healthy=all(checks.values()),
            checks=checks,
            errors=errors
        )


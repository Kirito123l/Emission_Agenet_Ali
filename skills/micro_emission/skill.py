from pathlib import Path
from typing import Dict, Tuple, Optional, List
import logging
from ..base import BaseSkill, SkillResult, HealthCheckResult
from shared.standardizer.vehicle import get_vehicle_standardizer
from shared.standardizer.pollutant import get_pollutant_standardizer
from shared.standardizer.constants import SEASON_MAPPING
from .calculator import MicroEmissionCalculator
from .excel_handler import ExcelHandler
from llm.client import get_llm

logger = logging.getLogger(__name__)

class MicroEmissionSkill(BaseSkill):
    """微观排放计算Skill"""

    # 参数定义
    REQUIRED_PARAMS = ["vehicle_type"]  # 必需参数（trajectory_data或input_file二选一）
    OPTIONAL_PARAMS = {  # 可选参数及默认值
        "model_year": 2020,  # 默认2020年
        "pollutants": ["CO2", "NOx"],
        "season": "夏季",
        "trajectory_data": None,  # 轨迹数据（与input_file二选一）
        "input_file": None,  # Excel输入文件路径
        "output_file": None,  # Excel输出文件路径
    }

    def __init__(self):
        self._vehicle_std = get_vehicle_standardizer()
        self._pollutant_std = get_pollutant_standardizer()
        self._calculator = MicroEmissionCalculator()
        # 获取LLM客户端用于智能列名映射
        try:
            llm_client = get_llm("agent")  # 使用agent的LLM配置
            self._excel_handler = ExcelHandler(llm_client=llm_client)
            logger.info("[微观排放] 已启用智能列名映射")
        except Exception as e:
            logger.warning(f"[微观排放] 无法获取LLM客户端，使用硬编码映射: {e}")
            self._excel_handler = ExcelHandler(llm_client=None)

    @property
    def name(self):
        return "calculate_micro_emission"

    @property
    def description(self):
        return "基于车辆轨迹数据计算逐秒排放量"

    def get_brief_description(self) -> str:
        return "微观排放计算（必需：vehicle_type + (trajectory_data或input_file)；可选：model_year, pollutants, season, output_file）"

    def get_full_schema(self) -> Dict:
        """返回完整的参数schema"""
        return {
            "type": "object",
            "properties": {
                "trajectory_data": {
                    "type": "array",
                    "description": "轨迹数据 [{\"t\": 0, \"speed_kph\": 60, \"acceleration_mps2\": 0.5, \"grade_pct\": 0}, ...]",
                    "required": True,
                    "items": {
                        "type": "object",
                        "properties": {
                            "t": {"type": "number", "description": "时间(秒)"},
                            "speed_kph": {"type": "number", "description": "速度(km/h)"},
                            "acceleration_mps2": {"type": "number", "description": "加速度(m/s²)，可选"},
                            "grade_pct": {"type": "number", "description": "坡度(%)，可选"}
                        },
                        "required": ["speed_kph"]
                    }
                },
                "vehicle_type": {
                    "type": "string",
                    "description": "车型（支持中英文，如：小汽车、公交车）",
                    "required": True,
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
                "input_file": {
                    "type": "string",
                    "description": "Excel输入文件路径（.xlsx或.csv）- 与trajectory_data二选一",
                    "required": False,
                },
                "output_file": {
                    "type": "string",
                    "description": "Excel输出文件路径（.xlsx或.csv）",
                    "required": False,
                },
            },
            "required": ["vehicle_type"],
        }

    def validate_params(self, params: Dict) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """
        验证参数完整性

        Returns:
            (is_valid, error_message, missing_params_info)
        """
        missing = []
        missing_info = {}

        # 检查必需参数
        for param in self.REQUIRED_PARAMS:
            if param not in params or params[param] is None or params[param] == "":
                missing.append(param)

                # 提供参数说明
                if param == "vehicle_type":
                    missing_info[param] = {
                        "description": "车型",
                        "examples": ["小汽车", "公交车", "重型货车"],
                    }

        # 检查trajectory_data或input_file至少有一个
        has_trajectory = params.get("trajectory_data") is not None and params.get("trajectory_data") != ""
        has_input_file = params.get("input_file") is not None and params.get("input_file") != ""

        if not has_trajectory and not has_input_file:
            missing.append("trajectory_data/input_file")
            missing_info["trajectory_data"] = {
                "description": "轨迹数据或输入文件",
                "format": "[{\"t\": 0, \"speed_kph\": 60}, {\"t\": 1, \"speed_kph\": 65}, ...]",
                "note": "可以提供trajectory_data数组，或使用input_file指定Excel文件路径"
            }

        # 验证trajectory_data格式（如果提供）
        if has_trajectory:
            traj = params["trajectory_data"]
            if not isinstance(traj, list):
                return False, "trajectory_data必须是列表", {}
            if len(traj) == 0:
                return False, "trajectory_data不能为空", {}
            if not all(isinstance(p, dict) and "speed_kph" in p for p in traj):
                return False, "trajectory_data中每个点必须包含speed_kph字段", {}

        if missing:
            return False, f"缺少必需参数: {', '.join(missing)}", missing_info

        return True, None, None

    def execute(self, **params) -> SkillResult:
        context = {"skill": self.name}

        # Map file_path to input_file if provided (parameter name compatibility)
        if "file_path" in params and "input_file" not in params:
            params["input_file"] = params["file_path"]
            logger.info(f"Mapped file_path to input_file: {params['file_path']}")

        logger.info(f"[MicroEmission] Received parameters: {list(params.keys())}")
        logger.debug(f"[MicroEmission] Full parameters: {params}")

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
        vehicle_type = params["vehicle_type"]
        model_year = params.get("model_year", self.OPTIONAL_PARAMS["model_year"])
        pollutants = params.get("pollutants", self.OPTIONAL_PARAMS["pollutants"])
        season = params.get("season", self.OPTIONAL_PARAMS["season"])
        input_file = params.get("input_file")
        output_file = params.get("output_file")

        # 3. 获取轨迹数据（从参数或文件）
        if input_file:
            # 从Excel文件读取
            success, trajectory_data, read_error = self._excel_handler.read_trajectory_from_excel(input_file)
            if not success:
                return SkillResult(
                    success=False,
                    error=f"读取输入文件失败: {read_error}",
                    metadata={"input_file": input_file}
                )
        else:
            # 使用提供的trajectory_data
            trajectory_data = params["trajectory_data"]

        # 4. 标准化车型
        v_result = self._vehicle_std.standardize(vehicle_type, context)
        if not v_result.standard:
            return SkillResult(
                success=False,
                error=f"无法识别车型: {vehicle_type}",
                metadata={
                    "needs_clarification": True,
                    "clarification_type": "invalid_vehicle_type",
                    "input_value": vehicle_type,
                }
            )

        # 5. 标准化污染物列表
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

        # 6. 标准化季节
        season_std = SEASON_MAPPING.get(season.lower(), season)
        if season_std not in ["春季", "夏季", "秋季", "冬季"]:
            season_std = "夏季"

        # 7. 执行计算
        result = self._calculator.calculate(
            trajectory_data=trajectory_data,
            vehicle_type=v_result.standard,
            pollutants=standardized_pollutants,
            model_year=model_year,
            season=season_std,
        )

        # 8. 处理计算结果
        if result.get("status") == "error":
            return SkillResult(
                success=False,
                error=result.get("message", result.get("error")),
                metadata={
                    "error_code": result.get("error_code"),
                    "query_params": {
                        "vehicle_type": {"input": vehicle_type, "standard": v_result.standard},
                        "pollutants": {"input": pollutants, "standard": standardized_pollutants},
                        "model_year": model_year,
                        "season": season_std,
                        "trajectory_points": len(trajectory_data),
                    }
                },
            )

        # 9. 写入输出文件（如果指定）
        if output_file:
            # 从result中提取结果数据
            results_data = result["data"].get("results", [])

            # 构建轨迹数据（包含VSP）
            trajectory_for_excel = []
            emissions_for_excel = []

            for point in results_data:
                trajectory_for_excel.append({
                    "t": point.get("t", 0),
                    "speed_kph": point.get("speed_kph", 0),
                    "acceleration_mps2": 0,  # 从VSP反推不准确，使用0
                    "grade_pct": 0,  # 从VSP反推不准确，使用0
                    "VSP": point.get("vsp", 0)
                })
                emissions_for_excel.append(point.get("emissions", {}))

            write_success, write_error = self._excel_handler.write_results_to_excel(
                output_file,
                trajectory_for_excel,
                emissions_for_excel,
                standardized_pollutants
            )

            if not write_success:
                # 写入失败不影响计算结果，只记录警告
                result["data"]["output_file_warning"] = f"写入输出文件失败: {write_error}"
            else:
                result["data"]["output_file"] = output_file

        # 9.5. 生成下载文件（如果有input_file）
        download_info = None
        if input_file:
            try:
                from config import get_config
                config = get_config()
                outputs_dir = str(config.outputs_dir)

                # 从result中提取排放数据
                results_data = result["data"].get("results", [])
                emission_list = [point.get("emissions", {}) for point in results_data]

                # 生成结果Excel
                success, output_path, filename, error = self._excel_handler.generate_result_excel(
                    original_file_path=input_file,
                    emission_results=emission_list,
                    pollutants=standardized_pollutants,
                    output_dir=outputs_dir
                )

                if success:
                    download_info = {
                        "path": output_path,
                        "filename": filename,
                        "description": "包含原始轨迹数据和排放计算结果的完整文件"
                    }
                    logger.info(f"生成下载文件成功: {filename}")
                else:
                    logger.warning(f"生成下载文件失败: {error}")
            except Exception as e:
                logger.exception("生成下载文件时出错")

        # 10. 返回成功结果
        return SkillResult(
            success=True,
            data=result["data"],
            metadata={
                "query_params": {
                    "vehicle_type": {"input": vehicle_type, "standard": v_result.standard},
                    "pollutants": {"input": pollutants, "standard": standardized_pollutants},
                    "model_year": model_year,
                    "season": season_std,
                    "input_file": input_file,
                    "output_file": output_file,
                },
                "standardization": {
                    "vehicle": {
                        "confidence": v_result.confidence,
                        "method": v_result.method
                    }
                },
                "download_file": download_info,  # 添加下载文件信息
            }
        )

    def health_check(self) -> HealthCheckResult:
        checks = {}
        errors = []

        # 检查数据文件
        data_path = Path(__file__).parent / "data"
        checks["data_directory"] = data_path.exists()
        if not checks["data_directory"]:
            errors.append(f"数据目录不存在: {data_path}")

        csv_files = ["atlanta_2025_1_55_65.csv", "atlanta_2025_4_75_65.csv", "atlanta_2025_7_90_70.csv"]
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

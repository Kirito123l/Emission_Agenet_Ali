"""
Excel输入/输出处理器
支持宏观排放计算的Excel文件读写
"""
import difflib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from config import get_config

logger = logging.getLogger(__name__)


class ExcelHandler:
    """Excel文件处理器"""

    REQUIRED_FIELDS = ("link_length_km", "traffic_flow_vph", "avg_speed_kph")
    OPTIONAL_FIELDS = ("link_id", "geometry")
    ALL_FIELDS = REQUIRED_FIELDS + OPTIONAL_FIELDS

    # 用于 direct match / 语义 fallback 的通用短语，不针对单一样本文件硬编码
    FIELD_ALIASES = {
        "link_length_km": ["link_length_km", "length_km", "length", "distance", "road_length", "路段长度", "长度", "距离"],
        "traffic_flow_vph": ["traffic_flow_vph", "flow_vph", "flow", "traffic", "volume", "veh_per_hour", "交通流量", "流量", "交通量"],
        "avg_speed_kph": ["avg_speed_kph", "speed_kph", "speed_kmh", "speed", "avg_speed", "velocity", "平均速度", "速度"],
        "link_id": ["link_id", "segment_id", "id", "link", "路段id", "路段编号", "编号", "名称", "name"],
        "geometry": ["geometry", "geom", "wkt", "shape", "几何", "路段几何", "坐标"],
    }

    STANDARD_VEHICLE_TYPES = [
        "Motorcycle",
        "Passenger Car",
        "Passenger Truck",
        "Light Commercial Truck",
        "Intercity Bus",
        "Transit Bus",
        "School Bus",
        "Refuse Truck",
        "Single Unit Short-haul Truck",
        "Single Unit Long-haul Truck",
        "Motor Home",
        "Combination Short-haul Truck",
        "Combination Long-haul Truck",
    ]

    AGGREGATE_TRUCK_KEY = "__TRUCK_TOTAL__"
    TRUCK_DISTRIBUTION = {
        "Passenger Truck": 20.0,
        "Light Commercial Truck": 5.0,
        "Combination Long-haul Truck": 2.0,
    }

    VEHICLE_ALIASES = {
        "motorcycle": "Motorcycle",
        "摩托车": "Motorcycle",
        "passenger car": "Passenger Car",
        "car": "Passenger Car",
        "taxi": "Passenger Car",
        "出租车": "Passenger Car",
        "网约车": "Passenger Car",
        "小汽车": "Passenger Car",
        "轿车": "Passenger Car",
        "乘用车": "Passenger Car",
        "passenger truck": "Passenger Truck",
        "客车": "Passenger Truck",
        "皮卡": "Passenger Truck",
        "light commercial truck": "Light Commercial Truck",
        "light truck": "Light Commercial Truck",
        "轻型货车": "Light Commercial Truck",
        "小货车": "Light Commercial Truck",
        "intercity bus": "Intercity Bus",
        "长途客车": "Intercity Bus",
        "transit bus": "Transit Bus",
        "bus": "Transit Bus",
        "公交车": "Transit Bus",
        "巴士": "Transit Bus",
        "school bus": "School Bus",
        "校车": "School Bus",
        "refuse truck": "Refuse Truck",
        "垃圾车": "Refuse Truck",
        "single unit short-haul truck": "Single Unit Short-haul Truck",
        "single unit long-haul truck": "Single Unit Long-haul Truck",
        "motor home": "Motor Home",
        "房车": "Motor Home",
        "combination short-haul truck": "Combination Short-haul Truck",
        "combination long-haul truck": "Combination Long-haul Truck",
        "heavy truck": "Combination Long-haul Truck",
        "重型货车": "Combination Long-haul Truck",
        "大货车": "Combination Long-haul Truck",
    }

    # 默认车队组成（与calculator.py保持一致）
    DEFAULT_FLEET_MIX = {
        "Passenger Car": 70.0,
        "Passenger Truck": 20.0,
        "Light Commercial Truck": 5.0,
        "Transit Bus": 3.0,
        "Combination Long-haul Truck": 2.0,
    }

    def __init__(self, llm_client: Optional[Any] = None):
        self.llm_client = llm_client
        self.runtime_config = get_config()

    def _get_completion_override(
        self,
        completion_overrides: Optional[Dict[str, Any]],
        field_name: str,
    ) -> Optional[Dict[str, Any]]:
        payload = (completion_overrides or {}).get(field_name)
        return dict(payload) if isinstance(payload, dict) else None

    def _apply_field_override_to_mapping(
        self,
        field_to_column: Dict[str, str],
        completion_overrides: Optional[Dict[str, Any]],
        available_columns: List[str],
    ) -> Dict[str, str]:
        updated = dict(field_to_column or {})
        for field_name in self.REQUIRED_FIELDS:
            override = self._get_completion_override(completion_overrides, field_name)
            if not override:
                continue
            mode = str(override.get("mode") or "").strip().lower()
            if mode not in {"source_column_derivation", "use_derivation"}:
                continue
            source_column = str(override.get("source_column") or "").strip()
            if source_column and source_column in available_columns:
                updated[field_name] = source_column
        return updated

    def _extract_required_value(
        self,
        row: pd.Series,
        *,
        field_name: str,
        field_to_column: Dict[str, str],
        completion_overrides: Optional[Dict[str, Any]],
    ) -> Any:
        if field_name in field_to_column:
            source_column = field_to_column[field_name]
            return row[source_column]

        override = self._get_completion_override(completion_overrides, field_name)
        if not override:
            return None

        mode = str(override.get("mode") or "").strip().lower()
        if mode == "uniform_scalar":
            return override.get("value")
        if mode in {"source_column_derivation", "use_derivation"}:
            source_column = str(override.get("source_column") or "").strip()
            if source_column and source_column in row.index:
                return row[source_column]
        return None

    def read_links_from_excel(
        self,
        file_path: str,
        completion_overrides: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[List[Dict]], Optional[str]]:
        """从Excel文件读取路段数据"""
        try:
            path = Path(file_path)
            if not path.exists():
                return False, None, f"文件不存在: {file_path}"

            if path.suffix.lower() == ".csv":
                df = pd.read_csv(file_path)
            elif path.suffix.lower() in [".xlsx", ".xls"]:
                df = pd.read_excel(file_path)
            else:
                return False, None, f"不支持的文件格式: {path.suffix}，仅支持 .xlsx, .xls, .csv"

            if df.empty:
                return False, None, "Excel文件为空"

            df.columns = [str(col).strip() for col in df.columns]
            logger.info(f"[MacroEmission] 读取列名: {list(df.columns)}")

            mapping_result = self._resolve_column_mapping(df)
            field_to_column = self._apply_field_override_to_mapping(
                mapping_result["field_to_column"],
                completion_overrides,
                list(df.columns),
            )

            missing_fields = []
            for field_name in self.REQUIRED_FIELDS:
                if field_name in field_to_column:
                    continue
                override = self._get_completion_override(completion_overrides, field_name)
                if override and str(override.get("mode") or "").strip().lower() == "uniform_scalar":
                    continue
                missing_fields.append(field_name)
            if missing_fields:
                return False, None, self._build_mapping_error(df, mapping_result, missing_fields)

            vehicle_columns = mapping_result["fleet_columns"]
            links_data: List[Dict] = []

            for i, row in df.iterrows():
                flow_raw = self._extract_required_value(
                    row,
                    field_name="traffic_flow_vph",
                    field_to_column=field_to_column,
                    completion_overrides=completion_overrides,
                )
                flow_vph = self._normalize_flow_to_vph(
                    flow_raw,
                    field_to_column.get("traffic_flow_vph", "traffic_flow_vph")
                )
                link_data = {
                    "link_length_km": self._safe_float(
                        self._extract_required_value(
                            row,
                            field_name="link_length_km",
                            field_to_column=field_to_column,
                            completion_overrides=completion_overrides,
                        )
                    ),
                    "traffic_flow_vph": flow_vph,
                    "avg_speed_kph": self._safe_float(
                        self._extract_required_value(
                            row,
                            field_name="avg_speed_kph",
                            field_to_column=field_to_column,
                            completion_overrides=completion_overrides,
                        )
                    ),
                }

                link_id_col = field_to_column.get("link_id")
                if link_id_col is not None and pd.notna(row[link_id_col]):
                    link_data["link_id"] = str(row[link_id_col]).strip()
                else:
                    link_data["link_id"] = f"Link_{i + 1}"

                fleet_mix = self._parse_fleet_mix(row, vehicle_columns)
                if fleet_mix:
                    link_data["fleet_mix"] = fleet_mix

                # Preserve geometry column if present
                geometry_col = field_to_column.get("geometry")
                if geometry_col is not None and pd.notna(row[geometry_col]):
                    geom_value = str(row[geometry_col]).strip()
                    if geom_value:
                        link_data["geometry"] = geom_value

                links_data.append(link_data)

            return True, links_data, None

        except Exception as e:
            return False, None, f"读取Excel文件失败: {str(e)}"

    @staticmethod
    def write_results_to_excel(
        file_path: str,
        results: List[Dict],
        pollutants: Optional[List[str]] = None
    ) -> Tuple[bool, Optional[str]]:
        """
        将计算结果写入Excel文件

        Args:
            file_path: 输出文件路径
            results: 结果列表，每个元素包含link_id和排放数据

        Returns:
            (success, error_message)
        """
        try:
            # 1. 构建输出数据
            output_data = []

            for result in results:
                row = {
                    "link_id": result.get("link_id", ""),
                    "link_length_km": result.get("link_length_km", 0),
                    "traffic_flow_vph": result.get("traffic_flow_vph", 0),
                    "avg_speed_kph": result.get("avg_speed_kph", 0),
                }

                # 添加排放数据（kg/h）
                emissions = result.get("total_emissions_kg_per_hr", {}) or result.get("total_emissions", {})
                output_pollutants = pollutants or ["CO2", "NOx", "PM2.5"]
                for pollutant in output_pollutants:
                    row[f"{pollutant}_kg_per_h"] = emissions.get(pollutant, 0)

                output_data.append(row)

            # 2. 创建DataFrame
            df = pd.DataFrame(output_data)

            # 3. 写入文件
            path = Path(file_path)
            if path.suffix.lower() == '.csv':
                df.to_csv(file_path, index=False, encoding='utf-8-sig')
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df.to_excel(file_path, index=False, engine='openpyxl')
            else:
                return False, f"不支持的输出格式: {path.suffix}，仅支持 .xlsx, .csv"

            return True, None

        except Exception as e:
            return False, f"写入Excel文件失败: {str(e)}"

    def _resolve_column_mapping(self, df: pd.DataFrame) -> Dict[str, Any]:
        """统一列映射流程：direct match -> AI语义映射 -> 相似度fallback"""
        columns = [str(c) for c in df.columns]
        sample_rows = self._build_sample_rows(df)

        direct_candidates = self._direct_mapping_candidates(columns) if self.runtime_config.is_macro_mapping_mode_enabled("direct") else []
        ai_result = self._ai_mapping(columns, sample_rows) if self.runtime_config.is_macro_mapping_mode_enabled("ai") else {
            "used": False,
            "field_candidates": [],
            "fleet_mapping": {},
        }
        fuzzy_candidates = self._fuzzy_mapping_candidates(columns) if self.runtime_config.is_macro_mapping_mode_enabled("fuzzy") else []

        selected: Dict[str, str] = {}
        selected_meta: Dict[str, Dict[str, Any]] = {}
        used_columns = set()

        candidates = []
        candidates.extend(direct_candidates)
        candidates.extend(ai_result.get("field_candidates", []))
        candidates.extend(fuzzy_candidates)
        candidates.sort(key=lambda x: x["score"], reverse=True)

        for cand in candidates:
            field = cand["field"]
            col = cand["column"]
            if field in selected or col in used_columns:
                continue
            selected[field] = col
            selected_meta[field] = {"score": cand["score"], "source": cand["source"]}
            used_columns.add(col)

        fleet_columns = self._resolve_fleet_columns(columns, ai_result, used_columns)

        return {
            "field_to_column": selected,
            "fleet_columns": fleet_columns,
            "meta": selected_meta,
            "ai_used": bool(ai_result.get("used")),
        }

    def _direct_mapping_candidates(self, columns: List[str]) -> List[Dict[str, Any]]:
        candidates = []
        lookup = {self._normalize_text(col): col for col in columns}
        for field, aliases in self.FIELD_ALIASES.items():
            for alias in aliases:
                norm_alias = self._normalize_text(alias)
                if norm_alias in lookup:
                    candidates.append(
                        {"field": field, "column": lookup[norm_alias], "score": 1.0, "source": "direct"}
                    )
                    break
        return candidates

    def _fuzzy_mapping_candidates(self, columns: List[str]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        for field, aliases in self.FIELD_ALIASES.items():
            best_col = None
            best_score = 0.0
            for col in columns:
                score = self._column_semantic_score(col, aliases)
                if score > best_score:
                    best_score = score
                    best_col = col
            if best_col and best_score >= 0.52:
                candidates.append(
                    {"field": field, "column": best_col, "score": round(best_score, 4), "source": "fuzzy"}
                )
        return candidates

    def _ai_mapping(self, columns: List[str], sample_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not self.llm_client:
            return {"used": False, "field_candidates": [], "fleet_mapping": {}}

        system_prompt = (
            "你是交通排放数据表头语义映射器。"
            "根据列名和样例数据，映射到标准字段并输出JSON。"
            "禁止输出解释性文字，只返回JSON对象。"
        )
        user_prompt = f"""
标准字段定义:
- link_length_km: 路段长度（单位通常为km）
- traffic_flow_vph: 每小时交通流量（辆/小时）
- avg_speed_kph: 平均速度（km/h）
- link_id: 路段标识（可选）
- fleet_mapping: 车型占比列，值是13类MOVES标准车型名之一

可用车型:
{json.dumps(self.STANDARD_VEHICLE_TYPES, ensure_ascii=False)}

输入列名:
{json.dumps(columns, ensure_ascii=False)}

样例数据(前几行):
{json.dumps(sample_rows, ensure_ascii=False)}

输出格式:
{{
  "field_mapping": {{"原列名": "标准字段名"}},
  "fleet_mapping": {{"原列名": "标准车型名"}},
  "confidence": {{"link_length_km": 0.0, "traffic_flow_vph": 0.0, "avg_speed_kph": 0.0, "link_id": 0.0}}
}}
"""
        try:
            raw = self.llm_client.chat_json(user_prompt, system=system_prompt)
            field_mapping = raw.get("field_mapping", {}) if isinstance(raw, dict) else {}
            fleet_mapping = raw.get("fleet_mapping", {}) if isinstance(raw, dict) else {}
            confidence = raw.get("confidence", {}) if isinstance(raw, dict) else {}

            field_candidates = []
            for col, field in field_mapping.items():
                if col not in columns or field not in self.ALL_FIELDS:
                    continue
                conf = float(confidence.get(field, 0.72))
                if conf < 0.55:
                    continue
                field_candidates.append(
                    {"field": field, "column": col, "score": min(conf, 0.96), "source": "ai"}
                )

            normalized_fleet: Dict[str, str] = {}
            for col, vehicle in fleet_mapping.items():
                if col not in columns:
                    continue
                std_vehicle = self._standardize_vehicle_name(str(vehicle))
                if std_vehicle:
                    normalized_fleet[col] = std_vehicle

            return {
                "used": True,
                "field_candidates": field_candidates,
                "fleet_mapping": normalized_fleet,
            }
        except Exception as e:
            logger.warning(f"[MacroEmission] AI列映射失败，回退到本地语义匹配: {e}")
            return {"used": False, "field_candidates": [], "fleet_mapping": {}}

    def _resolve_fleet_columns(
        self,
        columns: List[str],
        ai_result: Dict[str, Any],
        used_columns: set,
    ) -> Dict[str, List[str]]:
        # 先用AI映射结果
        vehicle_columns: Dict[str, List[str]] = {}
        ai_fleet = ai_result.get("fleet_mapping", {})
        for col, vehicle in ai_fleet.items():
            if col in used_columns:
                continue
            vehicle_columns.setdefault(vehicle, []).append(col)

        if vehicle_columns:
            return vehicle_columns

        # 回退：通用启发式识别（非特例规则）
        for col in columns:
            if col in used_columns:
                continue
            standardized = self._standardize_vehicle_name(col)
            if standardized:
                vehicle_columns.setdefault(standardized, []).append(col)
                continue

            # 对带百分号的列做一次弱语义识别
            col_norm = self._normalize_text(col)
            if "%" in str(col) or "pct" in col_norm or "比例" in col_norm or "占比" in col_norm:
                standardized = self._standardize_vehicle_name(col_norm.replace("%", ""))
                if standardized:
                    vehicle_columns.setdefault(standardized, []).append(col)

        return vehicle_columns

    def _column_semantic_score(self, col: str, aliases: List[str]) -> float:
        col_norm = self._normalize_text(col)
        best = 0.0
        for alias in aliases:
            alias_norm = self._normalize_text(alias)
            seq_score = difflib.SequenceMatcher(None, col_norm, alias_norm).ratio()
            token_score = self._token_overlap_score(col_norm, alias_norm)
            score = max(seq_score, token_score)
            if alias_norm in col_norm or col_norm in alias_norm:
                score = max(score, 0.72)
            best = max(best, score)
        return best

    def _token_overlap_score(self, a: str, b: str) -> float:
        a_tokens = set(filter(None, re.split(r"[_\s\-]+", a)))
        b_tokens = set(filter(None, re.split(r"[_\s\-]+", b)))
        if not a_tokens or not b_tokens:
            return 0.0
        inter = len(a_tokens & b_tokens)
        union = len(a_tokens | b_tokens)
        return inter / union if union else 0.0

    def _normalize_text(self, text: str) -> str:
        text = str(text).strip().lower()
        text = text.replace("（", "(").replace("）", ")").replace("％", "%")
        text = text.replace("(km/h)", "kmh").replace("(kmh)", "kmh").replace("(kph)", "kph")
        text = re.sub(r"[^\w%\u4e00-\u9fff]+", "_", text)
        return re.sub(r"_+", "_", text).strip("_")

    def _build_sample_rows(self, df: pd.DataFrame, max_rows: int = 4) -> List[Dict[str, Any]]:
        sample = df.head(max_rows).copy()
        safe_rows = []
        for _, row in sample.iterrows():
            safe_row: Dict[str, Any] = {}
            for col in sample.columns:
                value = row[col]
                if pd.isna(value):
                    safe_row[col] = None
                else:
                    safe_row[col] = str(value)
            safe_rows.append(safe_row)
        return safe_rows

    def _build_mapping_error(
        self,
        df: pd.DataFrame,
        mapping_result: Dict[str, Any],
        missing_fields: List[str],
    ) -> str:
        field_to_column = mapping_result.get("field_to_column", {})
        mapped_desc = ", ".join([f"{k}<-{v}" for k, v in field_to_column.items()]) or "无"
        cols_desc = ", ".join([str(c) for c in df.columns[:20]])
        if len(df.columns) > 20:
            cols_desc += f" ... (共{len(df.columns)}列)"

        return (
            f"列语义映射失败，缺少必需字段: {', '.join(missing_fields)}。"
            f"已识别映射: {mapped_desc}。"
            f"检测到列名: {cols_desc}。"
            f"请在提问中明确列含义，或将文件列名调整为“长度/流量/速度”语义明确的名称后重试。"
        )

    def _safe_float(self, value: Any) -> float:
        if pd.isna(value):
            raise ValueError("存在空值，无法转换为数值")
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip().replace(",", "")
        text = text.replace("％", "%")
        if text.endswith("%"):
            text = text[:-1]
        return float(text)

    def _normalize_flow_to_vph(self, value: Any, source_column: str) -> float:
        """
        Normalize traffic flow to vehicles per hour.
        Supports common daily-traffic semantics such as `daily_traffic`, `aadt`, `日交通量`.
        """
        flow = self._safe_float(value)
        col_norm = self._normalize_text(source_column)

        daily_markers = [
            "daily", "per_day", "day", "aadt", "adt", "daily_traffic",
            "日", "天", "每日", "日均", "日交通量"
        ]
        if any(marker in col_norm for marker in daily_markers):
            return flow / 24.0

        return flow

    def _standardize_vehicle_name(self, name: str) -> Optional[str]:
        if not name:
            return None
        norm = self._normalize_text(name).replace("%", "")
        norm = norm.replace("pct", "").replace("ratio", "").replace("share", "")
        norm = norm.strip("_ ")

        # 通用“货车”列在城市道路表中通常表示货车总占比，按默认货车结构拆分
        if norm in {"truck", "trucks", "货车", "卡车"}:
            return self.AGGREGATE_TRUCK_KEY

        if name in self.STANDARD_VEHICLE_TYPES:
            return name
        if norm in self.VEHICLE_ALIASES:
            return self.VEHICLE_ALIASES[norm]

        # 包含匹配
        for alias, std in self.VEHICLE_ALIASES.items():
            if alias in norm or norm in alias:
                return std

        # 与标准车型做一次模糊匹配
        best_std = None
        best_score = 0.0
        for std in self.STANDARD_VEHICLE_TYPES:
            score = difflib.SequenceMatcher(None, norm, self._normalize_text(std)).ratio()
            if score > best_score:
                best_score = score
                best_std = std
        if best_std and best_score >= 0.62:
            return best_std
        return None

    def _parse_fleet_mix(self, row: pd.Series, vehicle_columns: Dict[str, List[str]]) -> Optional[Dict[str, float]]:
        """解析车型分布"""
        if not vehicle_columns:
            return None

        fleet_mix = {}
        total = 0.0

        for standard_name, col_names in vehicle_columns.items():
            if isinstance(col_names, str):
                col_names = [col_names]
            aggregated_value = 0.0
            for col_name in col_names:
                value = row[col_name]
                if pd.isna(value):
                    continue
                try:
                    parsed = self._safe_float(value)
                except Exception:
                    continue
                if parsed > 0:
                    aggregated_value += parsed
            if aggregated_value > 0:
                fleet_mix[standard_name] = aggregated_value
                total += aggregated_value

        # “Truck%”等聚合列拆分到可计算的MOVES标准车型
        truck_total = fleet_mix.pop(self.AGGREGATE_TRUCK_KEY, 0.0)
        if truck_total > 0:
            dist_total = sum(self.TRUCK_DISTRIBUTION.values())
            for vehicle_type, ratio in self.TRUCK_DISTRIBUTION.items():
                fleet_mix[vehicle_type] = fleet_mix.get(vehicle_type, 0.0) + truck_total * ratio / dist_total

        if not fleet_mix or total == 0:
            return None

        if abs(total - 100.0) > 1e-6:
            for vehicle_type in fleet_mix:
                fleet_mix[vehicle_type] = (fleet_mix[vehicle_type] / total) * 100.0

        return fleet_mix

    def generate_result_excel(
        self,
        original_file_path: str,
        emission_results: List[Dict],
        pollutants: List[str],
        output_dir: str,
        fleet_fill_info: Optional[Dict[str, Any]] = None
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        生成包含排放结果的增强版Excel文件（原始数据 + 排放列）

        Args:
            original_file_path: 原始输入文件路径
            emission_results: 排放计算结果列表（每个路段的排放量）
            pollutants: 污染物列表
            output_dir: 输出目录

        Returns:
            (success, output_path, filename, error_message)
        """
        try:
            from datetime import datetime
            import os

            # 1. 读取原始文件
            path = Path(original_file_path)

            # Handle ZIP files: extract and read the contained file
            if path.suffix.lower() == '.zip':
                import zipfile
                import tempfile

                with zipfile.ZipFile(original_file_path, 'r') as zip_ref:
                    file_list = zip_ref.namelist()

                    # Check for Shapefile first
                    shp_files = [f for f in file_list if f.endswith('.shp')]
                    if shp_files:
                        # For Shapefile, create a DataFrame from emission_results
                        # since we can't easily read the original Shapefile structure
                        df_original = pd.DataFrame(emission_results)
                        # Remove emission columns to get original structure
                        emission_cols = [col for col in df_original.columns if any(p in col for p in pollutants)]
                        df_original = df_original.drop(columns=emission_cols, errors='ignore')
                    else:
                        # Check for Excel/CSV files
                        excel_files = [f for f in file_list if f.endswith(('.xlsx', '.xls', '.csv'))]
                        if excel_files:
                            with tempfile.TemporaryDirectory() as tmp_dir:
                                extracted_path = os.path.join(tmp_dir, excel_files[0])
                                with zip_ref.open(excel_files[0]) as source:
                                    with open(extracted_path, 'wb') as target:
                                        target.write(source.read())

                                if excel_files[0].endswith('.csv'):
                                    df_original = pd.read_csv(extracted_path)
                                else:
                                    df_original = pd.read_excel(extracted_path)
                        else:
                            return False, None, None, "ZIP文件中未找到支持的数据文件"
            elif path.suffix.lower() == '.csv':
                df_original = pd.read_csv(original_file_path)
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df_original = pd.read_excel(original_file_path)
            else:
                return False, None, None, f"不支持的文件格式: {path.suffix}"

            # 2. 添加排放列
            for pollutant in pollutants:
                # 提取该污染物的排放值（从total_emissions_kg_per_hr中）
                emission_values = [
                    link.get("total_emissions_kg_per_hr", {}).get(pollutant, 0)
                    for link in emission_results
                ]

                # 宏观排放单位: kg/h（千克/小时）
                col_name = f"{pollutant}_kg_h"
                df_original[col_name] = emission_values

            # 2.1 对“整行车型占比为空”的路段，按实际计算使用的fleet mix回填原车型列
            fill_rows = set((fleet_fill_info or {}).get("filled_row_indices", []))
            if fill_rows:
                fleet_columns = self._resolve_fleet_columns(
                    columns=[str(c).strip() for c in df_original.columns],
                    ai_result={"fleet_mapping": {}},
                    used_columns=set(),
                )
                column_split = self._build_column_split(df_original, fleet_columns)

                for idx in fill_rows:
                    if idx < 0 or idx >= len(df_original) or idx >= len(emission_results):
                        continue
                    row_result = emission_results[idx]
                    used_mix = row_result.get("fleet_composition", {})
                    if not used_mix:
                        continue
                    vehicle_pct = {
                        k: float(v.get("percentage", 0.0))
                        for k, v in used_mix.items()
                        if isinstance(v, dict)
                    }

                    for vehicle_key, cols in fleet_columns.items():
                        if isinstance(cols, str):
                            cols = [cols]
                        if not cols:
                            continue

                        if vehicle_key == self.AGGREGATE_TRUCK_KEY:
                            pct_total = (
                                vehicle_pct.get("Passenger Truck", 0.0)
                                + vehicle_pct.get("Light Commercial Truck", 0.0)
                                + vehicle_pct.get("Combination Long-haul Truck", 0.0)
                            )
                        else:
                            pct_total = vehicle_pct.get(vehicle_key, 0.0)

                        if pct_total <= 0:
                            continue

                        splits = column_split.get(vehicle_key) or {}
                        if not splits:
                            equal = 1.0 / len(cols)
                            splits = {c: equal for c in cols}

                        for col in cols:
                            value = pct_total * float(splits.get(col, 0.0))
                            if pd.isna(df_original.at[idx, col]) or str(df_original.at[idx, col]).strip() == "":
                                df_original.at[idx, col] = round(value, 4)

            # 3. 生成输出文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_name = path.stem  # 不含扩展名的文件名
            output_filename = f"{original_name}_emission_results_{timestamp}.xlsx"
            output_path = os.path.join(output_dir, output_filename)

            # 4. 保存Excel
            df_original.to_excel(output_path, index=False, engine='openpyxl')

            return True, output_path, output_filename, None

        except Exception as e:
            logger.exception("生成结果Excel失败")
            return False, None, None, f"生成结果文件失败: {str(e)}"

    def _build_column_split(
        self,
        df: pd.DataFrame,
        fleet_columns: Dict[str, List[str]],
    ) -> Dict[str, Dict[str, float]]:
        """
        为同一车型对应多个列（如Car%+Taxi%）构建分配比例。
        比例来自非空历史行均值；无有效样本时回退均分。
        """
        split: Dict[str, Dict[str, float]] = {}
        for vehicle_name, cols in fleet_columns.items():
            if isinstance(cols, str):
                cols = [cols]
            if not cols:
                continue
            if len(cols) == 1:
                split[vehicle_name] = {cols[0]: 1.0}
                continue

            col_avgs: Dict[str, float] = {}
            for col in cols:
                numeric = pd.to_numeric(df[col], errors="coerce")
                mean_val = float(numeric.mean()) if numeric.notna().any() else 0.0
                col_avgs[col] = max(mean_val, 0.0)

            total_avg = sum(col_avgs.values())
            if total_avg <= 0:
                equal = 1.0 / len(cols)
                split[vehicle_name] = {c: equal for c in cols}
            else:
                split[vehicle_name] = {c: v / total_avg for c, v in col_avgs.items()}

        return split

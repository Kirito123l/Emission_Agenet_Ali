"""
Excel输入/输出处理器
支持微观排放计算的Excel文件读写
"""
import pandas as pd
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)


class ExcelHandler:
    """Excel文件处理器"""

    def __init__(self, llm_client: Optional[Any] = None):
        """
        初始化Excel处理器

        Args:
            llm_client: 可选的LLM客户端，用于智能列名映射
        """
        self.llm_client = llm_client

    # 列名映射（支持多种命名方式）
    SPEED_COLUMNS = ["speed_kph", "speed_kmh", "speed", "车速", "速度"]  # 添加 speed_kmh
    ACCELERATION_COLUMNS = ["acceleration", "acc", "acceleration_mps2", "acceleration_m_s2", "加速度"]  # 添加 acceleration_m_s2
    GRADE_COLUMNS = ["grade_pct", "grade", "坡度"]
    TIME_COLUMNS = ["t", "time", "time_sec", "时间"]  # 添加 time_sec

    def read_trajectory_from_excel(self, file_path: str) -> Tuple[bool, Optional[List[Dict]], Optional[str]]:
        """
        从Excel文件读取轨迹数据

        Args:
            file_path: Excel文件路径

        Returns:
            (success, trajectory_data, error_message)
        """
        try:
            # 1. 检查文件是否存在
            path = Path(file_path)
            if not path.exists():
                return False, None, f"文件不存在: {file_path}"

            # 2. 读取文件
            if path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path)
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            else:
                return False, None, f"不支持的文件格式: {path.suffix}，仅支持 .xlsx, .xls, .csv"

            if df.empty:
                return False, None, "Excel文件为空"

            # 添加调试日志
            import sys
            sys.stdout.write(f"[DEBUG] 文件列名: {list(df.columns)}\n")
            sys.stdout.write(f"[DEBUG] 列名repr: {[repr(c) for c in df.columns]}\n")
            sys.stdout.flush()

            # 清理列名：去除前后空格
            df.columns = df.columns.str.strip()
            sys.stdout.write(f"[DEBUG] 清理后列名: {list(df.columns)}\n")
            sys.stdout.flush()

            # 3. 查找速度列（必需）
            speed_col = self._find_column(df, self.SPEED_COLUMNS)
            if speed_col is None:
                return False, None, f"未找到速度列，支持的列名: {', '.join(self.SPEED_COLUMNS)}"

            # 4. 查找可选列
            acc_col = self._find_column(df, self.ACCELERATION_COLUMNS)
            grade_col = self._find_column(df, self.GRADE_COLUMNS)
            time_col = self._find_column(df, self.TIME_COLUMNS)

            # 5. 构建轨迹数据
            trajectory_data = []
            speeds = df[speed_col].tolist()

            # 如果没有时间列，自动生成
            if time_col is None:
                times = list(range(len(speeds)))
            else:
                times = df[time_col].tolist()

            # 如果没有加速度列，根据速度差计算
            if acc_col is None:
                accelerations = self._calculate_acceleration(speeds)
            else:
                accelerations = df[acc_col].tolist()

            # 如果没有坡度列，默认为0
            if grade_col is None:
                grades = [0.0] * len(speeds)
            else:
                grades = df[grade_col].tolist()

            # 6. 组装数据
            for i in range(len(speeds)):
                point = {
                    "t": float(times[i]),
                    "speed_kph": float(speeds[i]),
                    "acceleration_mps2": float(accelerations[i]),
                    "grade_pct": float(grades[i])
                }
                trajectory_data.append(point)

            return True, trajectory_data, None

        except Exception as e:
            return False, None, f"读取Excel文件失败: {str(e)}"

    @staticmethod
    def write_results_to_excel(
        file_path: str,
        trajectory_data: List[Dict],
        emission_results: List[Dict],
        pollutants: List[str]
    ) -> Tuple[bool, Optional[str]]:
        """
        将计算结果写入Excel文件

        Args:
            file_path: 输出文件路径
            trajectory_data: 轨迹数据（包含t, speed_kph, acceleration_mps2, grade_pct, VSP）
            emission_results: 排放结果（每个时间点的排放量）
            pollutants: 污染物列表

        Returns:
            (success, error_message)
        """
        try:
            # 1. 构建输出数据
            output_data = []

            for i, traj_point in enumerate(trajectory_data):
                row = {
                    "t": traj_point.get("t", i),
                    "speed_kph": traj_point.get("speed_kph", 0),
                    "acc_mps2": traj_point.get("acceleration_mps2", 0),
                    "grade_pct": traj_point.get("grade_pct", 0),
                    "VSP": traj_point.get("VSP", 0)
                }

                # 添加排放数据
                if i < len(emission_results):
                    emissions = emission_results[i]
                    for pollutant in pollutants:
                        # 根据污染物类型确定单位
                        if pollutant == "CO2":
                            col_name = f"{pollutant}_g_per_s"
                            value = emissions.get(pollutant, 0)
                        else:
                            col_name = f"{pollutant}_mg_per_s"
                            value = emissions.get(pollutant, 0) * 1000  # g -> mg

                        row[col_name] = value

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

    def _find_column(self, df: pd.DataFrame, possible_names: List[str]) -> Optional[str]:
        """
        在DataFrame中查找列名

        Args:
            df: DataFrame
            possible_names: 可能的列名列表

        Returns:
            找到的列名，如果未找到返回None
        """
        df_columns_lower = {col.lower(): col for col in df.columns}

        for name in possible_names:
            name_lower = name.lower()
            if name_lower in df_columns_lower:
                return df_columns_lower[name_lower]

        return None

    def _calculate_acceleration(self, speeds: List[float], dt: float = 1.0) -> List[float]:
        """
        根据速度序列计算加速度

        Args:
            speeds: 速度列表 (km/h)
            dt: 时间间隔 (秒)

        Returns:
            加速度列表 (m/s²)
        """
        accelerations = []

        for i in range(len(speeds)):
            if i == 0:
                # 第一个点：使用前向差分
                if len(speeds) > 1:
                    speed_diff = speeds[1] - speeds[0]
                else:
                    speed_diff = 0
            elif i == len(speeds) - 1:
                # 最后一个点：使用后向差分
                speed_diff = speeds[i] - speeds[i - 1]
            else:
                # 中间点：使用中心差分
                speed_diff = (speeds[i + 1] - speeds[i - 1]) / 2.0

            # 转换单位: km/h -> m/s -> m/s²
            # km/h -> m/s: 除以3.6
            # 速度差 / 时间间隔 = 加速度
            acc = (speed_diff / 3.6) / dt
            accelerations.append(acc)

        return accelerations

    def generate_result_excel(
        self,
        original_file_path: str,
        emission_results: List[Dict],
        pollutants: List[str],
        output_dir: str
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str]]:
        """
        生成包含排放结果的增强版Excel文件（原始数据 + 排放列）

        Args:
            original_file_path: 原始输入文件路径
            emission_results: 排放计算结果列表（每个时间点的排放量）
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
            if path.suffix.lower() == '.csv':
                df_original = pd.read_csv(original_file_path)
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df_original = pd.read_excel(original_file_path)
            else:
                return False, None, None, f"不支持的文件格式: {path.suffix}"

            # 2. 添加排放列
            for pollutant in pollutants:
                # 提取该污染物的排放值
                emission_values = [point.get(pollutant, 0) for point in emission_results]

                # 微观排放单位: g（克）
                col_name = f"{pollutant}_g"
                df_original[col_name] = emission_values

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

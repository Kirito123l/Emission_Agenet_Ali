"""
VSP (Vehicle Specific Power) 计算器
严格按照 MOVES 模型实现
"""
from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS

class VSPCalculator:
    """VSP计算器"""

    def __init__(self):
        self.params = VSP_PARAMETERS
        self.g = 9.81  # 重力加速度 m/s²

    def calculate_vsp(self, speed_mps: float, acc: float, grade_pct: float,
                     vehicle_type_id: int) -> float:
        """
        计算VSP值

        公式: VSP = (A×v + B×v² + C×v³ + M×v×a + M×v×g×grade/100) / m

        Args:
            speed_mps: 速度 (m/s)
            acc: 加速度 (m/s²)
            grade_pct: 坡度 (%)
            vehicle_type_id: 车型ID

        Returns:
            VSP值 (kW/ton)
        """
        if vehicle_type_id not in self.params:
            raise ValueError(f"不支持的车型ID: {vehicle_type_id}")

        p = self.params[vehicle_type_id]
        v = speed_mps

        # VSP公式
        vsp = (
            p["A"] * v +
            p["B"] * v ** 2 +
            p["C"] * v ** 3 +
            p["M"] * v * acc +
            p["M"] * v * self.g * (grade_pct / 100.0)
        ) / p["m"]

        return round(vsp, 3)

    def vsp_to_bin(self, vsp: float) -> int:
        """VSP值转Bin编号 (1-14)"""
        for bin_id, (lower, upper) in VSP_BINS.items():
            if lower < vsp <= upper:
                return bin_id
        return 14  # 默认返回最高Bin

    def vsp_to_opmode(self, speed_mph: float, vsp: float) -> int:
        """
        VSP和速度 → opMode 映射

        opMode 范围: 0-40
        - 0: 怠速
        - 11-16: 低速区间 (1-25 mph)
        - 21-30: 中速区间 (25-50 mph)
        - 33-40: 高速区间 (>50 mph)
        """
        if speed_mph < 1:
            return 0  # 怠速

        elif speed_mph < 25:
            # 低速模式 (11-16)
            if vsp < 0:      return 11
            elif vsp < 3:    return 12
            elif vsp < 6:    return 13
            elif vsp < 9:    return 14
            elif vsp < 12:   return 15
            else:            return 16

        elif speed_mph < 50:
            # 中速模式 (21-30)
            if vsp < 0:      return 21
            elif vsp < 3:    return 22
            elif vsp < 6:    return 23
            elif vsp < 9:    return 24
            elif vsp < 12:   return 25
            elif vsp < 15:   return 26
            elif vsp < 18:   return 27
            elif vsp < 21:   return 28
            elif vsp < 24:   return 29
            else:            return 30

        else:  # speed >= 50
            # 高速模式 (33-40)
            if vsp < 3:      return 33
            elif vsp < 9:    return 35
            elif vsp < 15:   return 37
            elif vsp < 24:   return 38
            elif vsp < 30:   return 39
            else:            return 40

    def calculate_trajectory_vsp(self, trajectory: list, vehicle_type_id: int) -> list:
        """
        批量计算轨迹的VSP和opMode

        Args:
            trajectory: 轨迹数据列表
            vehicle_type_id: 车型ID

        Returns:
            添加了vsp和opmode字段的轨迹列表
        """
        results = []

        for i, point in enumerate(trajectory):
            # 获取速度
            speed_kph = point.get("speed_kph", 0)
            speed_mps = speed_kph / 3.6
            speed_mph = speed_kph * 0.621371

            # 获取或计算加速度
            acc = point.get("acceleration_mps2")
            if acc is None and i > 0:
                # 从速度差计算
                prev_speed = trajectory[i-1].get("speed_kph", speed_kph)
                dt = point.get("t", i) - trajectory[i-1].get("t", i-1)
                if dt > 0:
                    acc = (speed_kph - prev_speed) / (3.6 * dt)
                else:
                    acc = 0
            elif acc is None:
                acc = 0

            # 获取坡度
            grade = point.get("grade_pct", 0)

            # 计算VSP和opMode
            vsp = self.calculate_vsp(speed_mps, acc, grade, vehicle_type_id)
            vsp_bin = self.vsp_to_bin(vsp)
            opmode = self.vsp_to_opmode(speed_mph, vsp)

            results.append({
                **point,
                "speed_mps": round(speed_mps, 2),
                "speed_mph": round(speed_mph, 2),
                "acceleration_calculated": acc if point.get("acceleration_mps2") is None else None,
                "vsp": vsp,
                "vsp_bin": vsp_bin,
                "opmode": opmode
            })

        return results

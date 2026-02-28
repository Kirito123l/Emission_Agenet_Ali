"""
种子数据生成脚本
从 README.md 和现有代码中提取别名映射，生成种子数据
"""
import json
from pathlib import Path
from typing import Dict, List

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"

# ============================================================================
# 1. 车型标准化种子数据
# ============================================================================

# 13种MOVES标准车型及其别名（从README.md和constants.py提取）
VEHICLE_TYPE_ALIASES = {
    "Motorcycle": [
        # 标准名
        "Motorcycle", "motorcycle", "MOTORCYCLE",
        # 中文正式名
        "摩托车",
        # 中文口语/别名
        "机车", "两轮车", "电动摩托", "燃油摩托", "踏板车", "骑士车", "重机", "电摩",
        # 英文变体
        "motorbike", "moto", "bike",
    ],

    "Passenger Car": [
        # 标准名
        "Passenger Car", "passenger car", "PASSENGER CAR",
        # 中文正式名
        "乘用车", "小汽车", "轿车",
        # 中文口语/别名
        "私家车", "出租车", "网约车", "滴滴", "uber", "私家轿车", "家用车",
        "紧凑型轿车", "中型轿车", "豪华轿车", "经济型轿车",
        "SUV", "越野车", "旅行车", "掀背车", "三厢车", "两厢车", "跑车", "轿跑",
        "新能源车", "电动汽车", "混动车", "乘用车辆", "小型汽车", "家庭用车",
        "代步车", "买菜车", "新能源小汽车", "电动轿车", "插电混动", "纯电动车",
        # 英文变体
        "sedan", "car", "passenger_car",
    ],

    "Passenger Truck": [
        # 标准名
        "Passenger Truck", "passenger truck", "PASSENGER TRUCK",
        # 中文正式名
        "客货两用车", "皮卡",
        # 中文口语/别名
        "客货车", "小型客车", "面包车", "商务车", "MPV", "7座车",
        "五菱", "金杯", "微面", "小客车", "轻客",
        "商务MPV", "家用MPV", "GL8", "奥德赛", "艾力绅",
        # 英文变体
        "pickup", "pickup truck", "passenger_truck",
    ],

    "Light Commercial Truck": [
        # 标准名
        "Light Commercial Truck", "light commercial truck", "LIGHT COMMERCIAL TRUCK",
        # 中文正式名
        "轻型货车", "小货车",
        # 中文口语/别名
        "轻卡", "厢式货车", "微卡", "轻型卡车", "城市配送车",
        "快递车", "物流车", "小型货运", "4米2", "蓝牌货车",
        "轻型厢货", "城配车", "配送货车",
        # 英文变体
        "light truck", "light_commercial_truck",
    ],

    "Intercity Bus": [
        # 标准名
        "Intercity Bus", "intercity bus", "INTERCITY BUS",
        # 中文正式名
        "城际客车", "长途客车",
        # 中文口语/别名
        "大巴", "长途大巴", "客运大巴", "旅游大巴", "省际客车",
        "豪华大巴", "卧铺客车", "长途汽车", "省际大巴", "跨城客车",
        # 英文变体
        "intercity_bus", "intercity coach",
    ],

    "Transit Bus": [
        # 标准名
        "Transit Bus", "transit bus", "TRANSIT BUS",
        # 中文正式名
        "公交车", "公共汽车",
        # 中文口语/别名
        "市内公交", "城市公交", "BRT", "快速公交", "电动公交",
        "新能源公交", "巴士", "公交巴士", "市区公交", "常规公交",
        "通勤巴士", "公交", "公汽", "无轨电车",
        # 英文变体
        "city bus", "transit_bus", "trolleybus",
    ],

    "School Bus": [
        # 标准名
        "School Bus", "school bus", "SCHOOL BUS",
        # 中文正式名
        "校车",
        # 中文口语/别名
        "学生校车", "幼儿园校车", "接送车", "通勤班车",
        "学校巴士", "接送校车", "黄色校车",
        # 英文变体
        "school_bus",
    ],

    "Refuse Truck": [
        # 标准名
        "Refuse Truck", "refuse truck", "REFUSE TRUCK",
        # 中文正式名
        "垃圾车", "环卫车",
        # 中文口语/别名
        "清运车", "垃圾清运", "压缩垃圾车", "环卫垃圾车",
        "垃圾压缩车", "垃圾收集车", "环卫作业车",
        # 英文变体
        "garbage truck", "refuse_truck",
    ],

    "Single Unit Short-haul Truck": [
        # 标准名
        "Single Unit Short-haul Truck", "single unit short-haul truck",
        # 中文正式名
        "单体短途货车", "短途货车",
        # 中文口语/别名
        "城市货车", "配送货车", "中型货车", "4.2米货车", "箱货",
        "城市配送", "短途配送车", "市内货车", "中卡", "黄牌货车",
        # 英文变体
        "single_unit_short_haul_truck",
    ],

    "Single Unit Long-haul Truck": [
        # 标准名
        "Single Unit Long-haul Truck", "single unit long-haul truck",
        # 中文正式名
        "单体长途货车", "中长途货车",
        # 中文口语/别名
        "9.6米货车", "厢式长途货车", "长途货运", "干线货车",
        # 英文变体
        "single_unit_long_haul_truck",
    ],

    "Motor Home": [
        # 标准名
        "Motor Home", "motor home", "MOTOR HOME",
        # 中文正式名
        "房车", "旅居车",
        # 中文口语/别名
        "RV", "露营车", "自行式房车", "旅行房车", "自驾房车",
        # 英文变体
        "motorhome", "recreational vehicle", "motor_home",
    ],

    "Combination Short-haul Truck": [
        # 标准名
        "Combination Short-haul Truck", "combination short-haul truck",
        # 中文正式名
        "组合短途货车", "半挂短途",
        # 中文口语/别名
        "短途半挂", "城际半挂", "区域配送半挂", "短途挂车",
        # 英文变体
        "combination_short_haul_truck",
    ],

    "Combination Long-haul Truck": [
        # 标准名
        "Combination Long-haul Truck", "combination long-haul truck",
        # 中文正式名
        "重型货车", "重型卡车",
        # 中文口语/别名
        "大货车", "半挂车", "拖头", "18轮", "重卡", "长途货车",
        "半挂长途", "挂车", "牵引车", "大型货车", "集装箱卡车",
        "大挂车", "重型半挂", "长途运输车", "干线运输车",
        "大卡车", "大车", "大挂", "半挂牵引车", "集卡", "货车",
        # 英文变体
        "combination_long_haul_truck",
    ],
}

# ============================================================================
# 2. 污染物标准化种子数据
# ============================================================================

# 7种标准污染物及其别名（从README.md和constants.py提取）
POLLUTANT_ALIASES = {
    "CO2": [
        # 标准名
        "CO2", "co2", "CO₂",
        # 中文正式名
        "二氧化碳",
        # 中文口语/别名
        "碳排放", "碳", "温室气体", "二氧化碳排放", "碳dioxide",
        # 英文变体
        "carbon dioxide", "carbon_dioxide",
    ],

    "CO": [
        # 标准名
        "CO", "co",
        # 中文正式名
        "一氧化碳",
        # 中文口语/别名
        "CO气体", "一氧化碳排放",
        # 英文变体
        "carbon monoxide", "carbon_monoxide",
    ],

    "NOx": [
        # 标准名
        "NOx", "nox", "NOX",
        # 中文正式名
        "氮氧化物",
        # 中文口语/别名
        "氮氧化合物", "NO和NO2", "氮氧", "氮氧化物排放",
        # 英文变体
        "nitrogen oxides", "nitrogen_oxides",
    ],

    "PM2.5": [
        # 标准名
        "PM2.5", "pm2.5", "PM 2.5", "pm2_5", "PM25", "pm25",
        # 中文正式名
        "细颗粒物",
        # 中文口语/别名
        "2.5微米颗粒物", "细粒子", "颗粒物",
        # 英文变体
        "fine particulate matter",
    ],

    "PM10": [
        # 标准名
        "PM10", "pm10", "PM 10", "pm_10",
        # 中文正式名
        "可吸入颗粒物",
        # 中文口语/别名
        "10微米颗粒物", "粗颗粒物",
        # 英文变体
        "particulate matter",
    ],

    "THC": [
        # 标准名
        "THC", "thc",
        # 中文正式名
        "总碳氢化合物",
        # 中文口语/别名
        "碳氢化合物", "HC", "VOC", "挥发性有机物", "总烃", "烃类",
        # 英文变体
        "hydrocarbon", "total hydrocarbon",
    ],

    "SO2": [
        # 标准名
        "SO2", "so2", "SO₂",
        # 中文正式名
        "二氧化硫",
        # 中文口语/别名
        "硫化物", "硫排放",
        # 英文变体
        "sulfur dioxide", "sulfur_dioxide",
    ],
}

# ============================================================================
# 3. 列名映射种子数据
# ============================================================================

# 微观排放标准字段及其别名
MICRO_EMISSION_COLUMNS = {
    "time_sec": [
        "time", "t", "时间", "time_sec", "time_s", "秒", "timestamp",
        "时间戳", "time(s)", "时间(秒)", "Time", "TIME", "时间s",
    ],

    "speed_kph": [
        "speed", "速度", "车速", "speed_kph", "speed_kmh", "速度km/h",
        "velocity", "v", "speed(km/h)", "车速(km/h)", "瞬时速度",
        "实时速度", "spd", "Speed", "SPEED", "速度(km/h)", "speed_kmph",
        "车速km/h", "速度kmh", "link_avg_speed_kmh", "avg_speed_kmh",
    ],

    "acceleration_mps2": [
        "acceleration", "加速度", "acc", "a", "accel", "acceleration_mps2",
        "加速度m/s2", "加速度(m/s²)", "accel_mps2", "acc_mps2",
        "Acceleration", "加速度m/s²", "acceleration_m_s2",
    ],

    "grade_pct": [
        "grade", "坡度", "slope", "gradient", "坡度%", "grade_pct",
        "grade_percent", "道路坡度", "路面坡度", "Grade", "GRADE",
    ],
}

# 宏观排放标准字段及其别名
MACRO_EMISSION_COLUMNS = {
    "link_id": [
        "link_id", "路段ID", "路段编号", "id", "segment_id", "road_id",
        "link", "编号", "LinkID", "ID", "路段id", "link_ID",
    ],

    "link_length_km": [
        "length", "长度", "link_length", "路段长度", "距离", "length_km",
        "link_length_km", "len", "路段长度(km)", "distance", "里程",
        "Length", "LENGTH", "路段长度km", "长度km", "长度(km)",
    ],

    "traffic_flow_vph": [
        "flow", "流量", "traffic_flow", "交通流量", "volume",
        "traffic_flow_vph", "vol", "车流量", "小时流量",
        "link_volume_veh_per_hour", "volume_vph", "流量(辆/h)",
        "Flow", "FLOW", "交通量", "hourly_volume", "流量vph",
        "volume_veh_per_hour", "每小时流量",
    ],

    "avg_speed_kph": [
        "speed", "速度", "avg_speed", "平均速度", "mean_speed",
        "avg_speed_kph", "link_avg_speed_kmh", "平均车速",
        "average_speed", "速度(km/h)", "Speed", "SPEED",
        "avg_speed_kmh", "平均速度(km/h)", "速度kph",
    ],
}

# 车队组成列名（用于宏观排放）
FLEET_MIX_COLUMNS = {
    "Passenger Car": [
        "小汽车%", "passenger_car", "car_pct", "小汽车比例", "pc_pct",
        "乘用车%", "轿车比例", "私家车%", "小汽车", "Passenger Car",
        "passenger_car_pct", "car_ratio", "小轿车%",
    ],
    "Transit Bus": [
        "公交车%", "transit_bus", "bus_pct", "公交比例", "公交车比例",
        "巴士%", "Transit Bus", "transit_bus_pct", "公交", "公交%",
    ],
    "Light Commercial Truck": [
        "轻型货车%", "light_truck", "light_truck_pct", "轻卡%",
        "Light Commercial Truck", "小货车%", "轻型货车比例",
    ],
    "Combination Long-haul Truck": [
        "重型货车%", "heavy_truck", "truck_pct", "重卡%", "大货车%",
        "Combination Long-haul Truck", "半挂车%", "重型货车比例",
    ],
}

# ============================================================================
# 4. 生成种子数据文件
# ============================================================================

def generate_vehicle_seed_data() -> List[Dict]:
    """生成车型标准化种子数据"""
    seed_data = []
    for standard_type, aliases in VEHICLE_TYPE_ALIASES.items():
        for alias in aliases:
            seed_data.append({
                "input": alias,
                "output": standard_type,
                "category": "vehicle"
            })
    return seed_data


def generate_pollutant_seed_data() -> List[Dict]:
    """生成污染物标准化种子数据"""
    seed_data = []
    for standard_pollutant, aliases in POLLUTANT_ALIASES.items():
        for alias in aliases:
            seed_data.append({
                "input": alias,
                "output": standard_pollutant,
                "category": "pollutant"
            })
    return seed_data


def generate_column_mapping_seed_data() -> List[Dict]:
    """生成列名映射种子数据"""
    seed_data = []

    # 微观排放列名映射
    for standard_col, aliases in MICRO_EMISSION_COLUMNS.items():
        for alias in aliases:
            seed_data.append({
                "input": alias,
                "output": standard_col,
                "task_type": "micro_emission",
                "category": "column_mapping"
            })

    # 宏观排放列名映射
    for standard_col, aliases in MACRO_EMISSION_COLUMNS.items():
        for alias in aliases:
            seed_data.append({
                "input": alias,
                "output": standard_col,
                "task_type": "macro_emission",
                "category": "column_mapping"
            })

    # 车队组成列名映射
    for vehicle_type, aliases in FLEET_MIX_COLUMNS.items():
        for alias in aliases:
            seed_data.append({
                "input": alias,
                "output": vehicle_type,
                "task_type": "macro_emission",
                "category": "fleet_mix_column"
            })

    return seed_data


def main():
    """主函数：生成所有种子数据文件"""
    # 确保输出目录存在
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 生成车型种子数据
    vehicle_seed = generate_vehicle_seed_data()
    vehicle_file = DATA_RAW_DIR / "vehicle_type_seed.json"
    with open(vehicle_file, "w", encoding="utf-8") as f:
        json.dump(vehicle_seed, f, ensure_ascii=False, indent=2)
    print(f"[OK] 车型种子数据已生成: {vehicle_file}")
    print(f"  - 数据量: {len(vehicle_seed)} 条")
    print(f"  - 覆盖车型: {len(VEHICLE_TYPE_ALIASES)} 种")

    # 2. 生成污染物种子数据
    pollutant_seed = generate_pollutant_seed_data()
    pollutant_file = DATA_RAW_DIR / "pollutant_seed.json"
    with open(pollutant_file, "w", encoding="utf-8") as f:
        json.dump(pollutant_seed, f, ensure_ascii=False, indent=2)
    print(f"[OK] 污染物种子数据已生成: {pollutant_file}")
    print(f"  - 数据量: {len(pollutant_seed)} 条")
    print(f"  - 覆盖污染物: {len(POLLUTANT_ALIASES)} 种")

    # 3. 生成列名映射种子数据
    column_seed = generate_column_mapping_seed_data()
    column_file = DATA_RAW_DIR / "column_mapping_seed.json"
    with open(column_file, "w", encoding="utf-8") as f:
        json.dump(column_seed, f, ensure_ascii=False, indent=2)
    print(f"[OK] 列名映射种子数据已生成: {column_file}")
    print(f"  - 数据量: {len(column_seed)} 条")

    print("\n" + "="*60)
    print("种子数据生成完成！")
    print(f"总数据量: {len(vehicle_seed) + len(pollutant_seed) + len(column_seed)} 条")
    print("="*60)


if __name__ == "__main__":
    main()


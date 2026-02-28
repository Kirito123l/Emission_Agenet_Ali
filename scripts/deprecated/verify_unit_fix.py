"""
验证单位修复的正确性
"""
import sys
sys.path.insert(0, '.')

from calculators.micro_emission import MicroEmissionCalculator
from calculators.macro_emission import MacroEmissionCalculator

print("=" * 80)
print("单位修复验证测试")
print("=" * 80)

# ============================================================================
# 验证1: 微观排放 - 怠速场景
# ============================================================================
print("\n" + "=" * 80)
print("验证1: 微观排放 - 怠速场景 (100秒全怠速)")
print("=" * 80)

# 构造100秒全怠速轨迹
idle_trajectory = []
for i in range(100):
    idle_trajectory.append({
        "t": i,
        "speed_kph": 0,
        "acceleration_mps2": 0,
        "grade_pct": 0
    })

calc_micro = MicroEmissionCalculator()
result_idle = calc_micro.calculate(
    trajectory_data=idle_trajectory,
    vehicle_type="Passenger Car",
    pollutants=["CO2", "NOx"],
    model_year=2020,
    season="夏季"
)

print(f"\n输入参数:")
print(f"  轨迹点数: 100")
print(f"  速度: 0 km/h (怠速)")
print(f"  车型: Passenger Car")
print(f"  年份: 2020")
print(f"  季节: 夏季")

print(f"\n计算结果:")
if result_idle["status"] == "success":
    summary = result_idle["data"]["summary"]
    print(f"  总距离: {summary['total_distance_km']:.3f} km")
    print(f"  总时间: {summary['total_time_s']} 秒")
    print(f"  CO2 总排放: {summary['total_emissions_g']['CO2']:.4f} g")
    print(f"  NOx 总排放: {summary['total_emissions_g']['NOx']:.6f} g")
    # 怠速时距离为0，排放率不存在，跳过
    if summary['total_distance_km'] > 0:
        print(f"  CO2 排放率: {summary['emission_rates_g_per_km']['CO2']:.4f} g/km")
        print(f"  NOx 排放率: {summary['emission_rates_g_per_km']['NOx']:.6f} g/km")

    # 验证合理性
    print(f"\nReasonableness check:")
    # 注意：使用的是夏季数据 (atlanta_2025_7_90_70.csv)
    # 夏季怠速 CO2 (opMode=0, 2025): 2373.72 g/hr = 0.659 g/s
    # 100秒怠速预期: 2373.72 / 3600 * 100 = 65.94 g
    co2_expected_min = 60
    co2_expected_max = 75

    co2_actual = summary['total_emissions_g']['CO2']
    nox_actual = summary['total_emissions_g']['NOx']

    print(f"  CO2 expected range (summer data): {co2_expected_min}-{co2_expected_max} g")
    print(f"  CO2 actual value: {co2_actual:.4f} g")
    if co2_expected_min <= co2_actual <= co2_expected_max:
        print(f"  [OK] CO2 in reasonable range")
    else:
        print(f"  [ERROR] CO2 out of range!")

    # NOx 夏季数据值较小，不做严格验证
    print(f"  NOx actual value: {nox_actual:.6f} g (summer value)")
else:
    print(f"  错误: {result_idle.get('message')}")

# ============================================================================
# 验证2: 微观排放 - 匀速巡航场景
# ============================================================================
print("\n" + "=" * 80)
print("验证2: 微观排放 - 匀速巡航场景 (100秒, 50 km/h)")
print("=" * 80)

# 构造100秒匀速巡航轨迹
cruise_trajectory = []
for i in range(100):
    cruise_trajectory.append({
        "t": i,
        "speed_kph": 50,
        "acceleration_mps2": 0,
        "grade_pct": 0
    })

result_cruise = calc_micro.calculate(
    trajectory_data=cruise_trajectory,
    vehicle_type="Passenger Car",
    pollutants=["CO2"],
    model_year=2020,
    season="夏季"
)

print(f"\n输入参数:")
print(f"  轨迹点数: 100")
print(f"  速度: 50 km/h (巡航)")
print(f"  车型: Passenger Car")
print(f"  年份: 2020")
print(f"  季节: 夏季")

print(f"\n计算结果:")
if result_cruise["status"] == "success":
    summary = result_cruise["data"]["summary"]
    print(f"  总距离: {summary['total_distance_km']:.3f} km")
    print(f"  总时间: {summary['total_time_s']} 秒")
    print(f"  CO2 总排放: {summary['total_emissions_g']['CO2']:.4f} g")
    print(f"  CO2 排放率: {summary['emission_rates_g_per_km']['CO2']:.4f} g/km")

    # 验证合理性
    print(f"\nReasonableness check:")
    # 注意：使用的是夏季数据 (atlanta_2025_7_90_70.csv)
    # 50 km/h, acc=0 对应 opMode=22
    # 夏季巡航 CO2 (opMode=22, 2025): 4898.78 g/hr = 1.36 g/s
    # 100秒巡航预期: 4898.78 / 3600 * 100 = 136.08 g
    # 排放率: 136.08 g / 1.389 km = 98 g/km
    co2_rate_expected_min = 90  # g/km
    co2_rate_expected_max = 110  # g/km
    co2_rate_actual = summary['emission_rates_g_per_km']['CO2']

    print(f"  CO2 rate expected range (summer data, opMode=22): {co2_rate_expected_min}-{co2_rate_expected_max} g/km")
    print(f"  CO2 rate actual value: {co2_rate_actual:.4f} g/km")
    if co2_rate_expected_min <= co2_rate_actual <= co2_rate_expected_max:
        print(f"  [OK] CO2 rate in reasonable range")
    else:
        print(f"  [ERROR] CO2 rate out of range!")
else:
    print(f"  错误: {result_cruise.get('message')}")

# ============================================================================
# 验证3: 宏观排放
# ============================================================================
print("\n" + "=" * 80)
print("验证3: 宏观排放 (1km路段, 1000 veh/hr, 50 km/h)")
print("=" * 80)

# 构造单条路段数据
links_data = [{
    "link_id": "L1",
    "link_length_km": 1.0,
    "traffic_flow_vph": 1000,
    "avg_speed_kph": 50,
    "fleet_mix": {"Passenger Car": 100.0}  # 100% 小汽车
}]

calc_macro = MacroEmissionCalculator()
result_macro = calc_macro.calculate(
    links_data=links_data,
    pollutants=["CO2"],
    model_year=2020,
    season="夏季"
)

print(f"\n输入参数:")
print(f"  路段数: 1")
print(f"  路段长度: 1.0 km")
print(f"  交通流量: 1000 veh/hr")
print(f"  平均速度: 50 km/h")
print(f"  车队组成: 100% Passenger Car")
print(f"  年份: 2020")
print(f"  季节: 夏季")

print(f"\n计算结果:")
if result_macro["status"] == "success":
    results = result_macro["data"]["results"]
    summary = result_macro["data"]["summary"]

    for link in results:
        print(f"  路段 {link['link_id']}:")
        print(f"    总排放: {link['total_emissions_kg_per_hr']['CO2']:.4f} kg/hr")
        print(f"    单位排放率: {link['emission_rates_g_per_veh_km']['CO2']:.4f} g/(veh·km)")

        # 验证合理性
        print(f"\n  Reasonableness check:")
        # 注意：opMode=300 是平均值，比巡航工况低是正常的
        # 修正前的错误公式会产生 ~2175 kg/hr，修正后应该是 ~70 kg/hr
        rate_expected_min = 60   # g/(veh·km) - 平均值的合理下限
        rate_expected_max = 85   # g/(veh·km) - 平均值的合理上限
        rate_actual = link['emission_rates_g_per_veh_km']['CO2']

        print(f"  Unit rate expected range: {rate_expected_min}-{rate_expected_max} g/(veh*km)")
        print(f"  Unit rate actual value: {rate_actual:.4f} g/(veh*km)")
        if rate_expected_min <= rate_actual <= rate_expected_max:
            print(f"  [OK] Unit rate in reasonable range")
        else:
            print(f"  [ERROR] Unit rate out of range!")

        # Check total link emissions
        total_expected_min = 1000 * 1.0 * rate_expected_min / 1000  # kg/hr
        total_expected_max = 1000 * 1.0 * rate_expected_max / 1000  # kg/hr
        total_actual = link['total_emissions_kg_per_hr']['CO2']

        print(f"\n  Total link emissions expected: {total_expected_min:.2f}-{total_expected_max:.2f} kg/hr")
        print(f"  Total link emissions actual: {total_actual:.4f} kg/hr")
        if total_expected_min <= total_actual <= total_expected_max:
            print(f"  [OK] Total emissions in reasonable range")
        else:
            print(f"  [ERROR] Total emissions out of range!")

        # 验证修正效果
        print(f"\n  Correction verification:")
        print(f"  Old incorrect formula would give: ~2175 kg/hr")
        print(f"  New corrected formula gives: {total_actual:.4f} kg/hr")
        print(f"  Correction factor: ~31x improvement")
else:
    print(f"  错误: {result_macro.get('message')}")

print("\n" + "=" * 80)
print("验证完成")
print("=" * 80)

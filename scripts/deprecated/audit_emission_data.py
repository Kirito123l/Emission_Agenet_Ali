"""
排放数据单位审计脚本
分析所有CSV文件中EmissionQuant字段的数值范围
"""
import pandas as pd
from pathlib import Path
from collections import defaultdict

def analyze_csv(filepath, name):
    """分析单个CSV文件的EmissionQuant数值范围"""
    print(f"\n{'='*60}")
    print(f"文件: {name}")
    print(f"路径: {filepath}")
    print(f"{'='*60}")

    try:
        # 读取CSV
        if "macro" in str(filepath).lower():
            # macro数据没有表头
            df = pd.read_csv(filepath, header=None,
                            names=['opModeID', 'pollutantID', 'sourceTypeID', 'modelYearID', 'EmissionQuant', 'extra'])
        else:
            # micro和emission_factors数据有表头
            df = pd.read_csv(filepath)

        # 获取EmissionQuant列
        eq_col = 'EmissionQuant'

        # 基本统计
        print(f"\n数据行数: {len(df)}")
        print(f"EmissionQuant 统计:")
        print(f"  最小值: {df[eq_col].min():.6f}")
        print(f"  最大值: {df[eq_col].max():.6f}")
        print(f"  平均值: {df[eq_col].mean():.6f}")
        print(f"  中位数: {df[eq_col].median():.6f}")

        # 按污染物分组统计
        if 'pollutantID' in df.columns:
            print(f"\n按污染物分组统计:")
            pollutant_names = {
                1: "THC", 2: "CO", 3: "NOx", 5: "VOC",
                30: "SO2", 35: "NH3", 79: "NMHC", 90: "CO2",
                91: "Energy", 100: "PM10", 110: "PM2.5"
            }
            for pid, group in df.groupby('pollutantID'):
                pname = pollutant_names.get(int(pid), f"ID{pid}")
                print(f"  {pname} (ID={pid}):")
                print(f"    范围: [{group[eq_col].min():.6f}, {group[eq_col].max():.6f}]")
                print(f"    平均: {group[eq_col].mean():.6f}")

        # 检查是否有负值或异常值
        negative = (df[eq_col] < 0).sum()
        zero = (df[eq_col] == 0).sum()
        print(f"\n数据质量:")
        print(f"  负值数量: {negative}")
        print(f"  零值数量: {zero}")

        # 显示前10行样本
        print(f"\n前10行样本:")
        print(df.head(10).to_string())

        return {
            'min': df[eq_col].min(),
            'max': df[eq_col].max(),
            'mean': df[eq_col].mean(),
            'rows': len(df)
        }
    except Exception as e:
        print(f"错误: {e}")
        return None

def main():
    project_root = Path(__file__).parent

    print("=" * 80)
    print("排放数据单位一致性审计")
    print("=" * 80)

    # 1. Micro Emission 数据
    print("\n" + "="*80)
    print("1. 微观排放数据 (skills/micro_emission/data/)")
    print("="*80)

    micro_files = {
        "冬季": "skills/micro_emission/data/atlanta_2025_1_55_65.csv",
        "春季": "skills/micro_emission/data/atlanta_2025_4_75_65.csv",
        "夏季": "skills/micro_emission/data/atlanta_2025_7_90_70.csv"
    }

    for season, rel_path in micro_files.items():
        filepath = project_root / rel_path
        analyze_csv(filepath, f"微观排放 - {season}")

    # 2. Macro Emission 数据
    print("\n" + "="*80)
    print("2. 宏观排放数据 (skills/macro_emission/data/)")
    print("="*80)

    macro_files = {
        "冬季": "skills/macro_emission/data/atlanta_2025_1_35_60 .csv",
        "春季": "skills/macro_emission/data/atlanta_2025_4_75_65.csv",
        "夏季": "skills/macro_emission/data/atlanta_2025_7_80_60.csv"
    }

    for season, rel_path in macro_files.items():
        filepath = project_root / rel_path
        analyze_csv(filepath, f"宏观排放 - {season}")

    # 3. Emission Factors 数据
    print("\n" + "="*80)
    print("3. 排放因子数据 (skills/emission_factors/data/emission_matrix/)")
    print("="*80)

    ef_files = {
        "冬季": "skills/emission_factors/data/emission_matrix/atlanta_2025_1_55_65.csv",
        "春季": "skills/emission_factors/data/emission_matrix/atlanta_2025_4_75_65.csv",
        "夏季": "skills/emission_factors/data/emission_matrix/atlanta_2025_7_90_70.csv"
    }

    for season, rel_path in ef_files.items():
        filepath = project_root / rel_path
        analyze_csv(filepath, f"排放因子 - {season}")

    print("\n" + "="*80)
    print("审计完成")
    print("="*80)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
测试数据快速验证脚本

用法:
    python3 test_data/verify_test_files.py
"""

import pandas as pd
import zipfile
import os
from pathlib import Path

def verify_excel(filepath):
    """验证 Excel 文件"""
    print(f"\n{'='*60}")
    print(f"验证: {filepath}")
    print('='*60)

    df = pd.read_excel(filepath)
    print(f"✓ 行数: {len(df)}")
    print(f"✓ 列: {list(df.columns)}")

    # 检查必需列
    required_cols = ['link_id', 'length', 'flow', 'speed']
    missing = [col for col in required_cols if col not in df.columns]
    if missing:
        print(f"✗ 缺少必需列: {missing}")
        return False

    # 检查几何信息
    if 'geometry' in df.columns:
        geo_sample = df['geometry'].iloc[0]
        point_count = geo_sample.count(',') + 1
        print(f"✓ 包含几何信息")
        print(f"  - 首条路段坐标点数: {point_count}")
        print(f"  - 几何预览: {geo_sample[:60]}...")

        # 统计所有路段的坐标点数
        all_points = [g.count(',') + 1 for g in df['geometry']]
        print(f"  - 坐标点数统计: min={min(all_points)}, max={max(all_points)}, avg={sum(all_points)/len(all_points):.1f}")
    else:
        print(f"✓ 无几何信息（预期行为）")

    # 显示数据样本
    print(f"\n数据样本（前2行）:")
    print(df.head(2).to_string(index=False, max_colwidth=50))

    return True

def verify_shapefile_zip(filepath):
    """验证 Shapefile ZIP 文件"""
    print(f"\n{'='*60}")
    print(f"验证: {filepath}")
    print('='*60)

    with zipfile.ZipFile(filepath) as zf:
        files = zf.namelist()
        print(f"✓ 包含文件: {len(files)} 个")

        # 检查必需的 Shapefile 组件
        required_exts = ['.shp', '.shx', '.dbf']
        for ext in required_exts:
            if any(fn.endswith(ext) for fn in files):
                matching = [fn for fn in files if fn.endswith(ext)][0]
                print(f"  ✓ {ext}: {matching}")
            else:
                print(f"  ✗ 缺少 {ext}")
                return False

        # 检查可选组件
        optional_exts = ['.prj', '.cpg']
        for ext in optional_exts:
            if any(fn.endswith(ext) for fn in files):
                matching = [fn for fn in files if fn.endswith(ext)][0]
                print(f"  ✓ {ext}: {matching}")

    return True

def main():
    print("="*60)
    print("测试数据验证")
    print("="*60)

    test_dir = Path(__file__).parent

    # 验证所有测试文件
    test_files = [
        ('test_6links.xlsx', verify_excel),
        ('test_20links.xlsx', verify_excel),
        ('test_no_geometry.xlsx', verify_excel),
        ('test_6links.zip', verify_shapefile_zip),
        ('test_20links.zip', verify_shapefile_zip),
    ]

    results = {}
    for filename, verify_func in test_files:
        filepath = test_dir / filename
        if filepath.exists():
            try:
                results[filename] = verify_func(str(filepath))
            except Exception as e:
                print(f"\n✗ 验证失败: {e}")
                results[filename] = False
        else:
            print(f"\n✗ 文件不存在: {filepath}")
            results[filename] = False

    # 总结
    print(f"\n{'='*60}")
    print("验证总结")
    print('='*60)

    for filename, success in results.items():
        status = "✓ 通过" if success else "✗ 失败"
        print(f"{status}: {filename}")

    all_passed = all(results.values())
    print(f"\n{'='*60}")
    if all_passed:
        print("✓ 所有测试文件验证通过！")
        print("\n可以开始测试排放计算和地图可视化功能。")
    else:
        print("✗ 部分测试文件验证失败，请检查。")
    print('='*60)

    return 0 if all_passed else 1

if __name__ == '__main__':
    exit(main())

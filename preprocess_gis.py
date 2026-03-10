import geopandas as gpd
import json
import os

os.makedirs('static_gis', exist_ok=True)

# 1. 处理行政区划底图
print('处理行政区划底图...')
gdf_base = gpd.read_file('GIS文件/上海市底图/上海市.shp')
# 简化几何（减小文件）
gdf_base_simple = gdf_base.copy()
gdf_base_simple['geometry'] = gdf_base_simple.geometry.simplify(0.001)
# 只保留必要字段
gdf_base_simple = gdf_base_simple[['name', 'geometry']]
gdf_base_simple.to_file('static_gis/basemap.geojson', driver='GeoJSON')
size = os.path.getsize('static_gis/basemap.geojson') / 1024
print(f'  basemap.geojson: {size:.1f} KB')

# 2. 处理路网
print('处理路网...')
gdf_road = gpd.read_file('GIS文件/上海市路网/opt_link.shp')
# 简化几何
gdf_road_simple = gdf_road.copy()
gdf_road_simple['geometry'] = gdf_road_simple.geometry.simplify(0.0005)
# 只保留必要字段
keep_cols = ['geometry']
if 'highway' in gdf_road_simple.columns:
    keep_cols.append('highway')
if 'name' in gdf_road_simple.columns:
    keep_cols.append('name')
gdf_road_simple = gdf_road_simple[keep_cols]
gdf_road_simple.to_file('static_gis/roadnetwork.geojson', driver='GeoJSON')
size = os.path.getsize('static_gis/roadnetwork.geojson') / 1024
print(f'  roadnetwork.geojson: {size:.1f} KB')

# 3. 查看文件大小对比
print('\n=== 文件大小对比 ===')
for f in os.listdir('static_gis'):
    path = os.path.join('static_gis', f)
    size = os.path.getsize(path)
    if size > 1024*1024:
        print(f'  {f}: {size/1024/1024:.1f} MB')
    else:
        print(f'  {f}: {size/1024:.1f} KB')

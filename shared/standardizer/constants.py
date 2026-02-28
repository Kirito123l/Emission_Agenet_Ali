VEHICLE_TYPE_MAPPING = {
    "Passenger Car": ("乘用车", ["小汽车", "轿车", "私家车", "SUV", "网约车", "出租车", "滴滴"]),
    "Passenger Truck": ("皮卡", ["轻型客货车", "pickup"]),
    "Light Commercial Truck": ("轻型货车", ["小货车", "面包车", "轻卡"]),
    "Transit Bus": ("公交车", ["城市公交", "公交"]),
    "Intercity Bus": ("城际客车", ["长途大巴", "旅游巴士"]),
    "School Bus": ("校车", ["学生巴士"]),
    "Refuse Truck": ("垃圾车", ["环卫车"]),
    "Single Unit Short-haul Truck": ("中型货车", ["城配货车", "中卡"]),
    "Single Unit Long-haul Truck": ("长途货车", []),
    "Motor Home": ("房车", ["旅居车"]),
    "Combination Short-haul Truck": ("半挂短途", []),
    "Combination Long-haul Truck": ("重型货车", ["重卡", "大货车", "挂车"]),
    "Motorcycle": ("摩托车", ["电动摩托", "机车"]),
}

VEHICLE_ALIAS_TO_STANDARD = {}
for std, (cn, aliases) in VEHICLE_TYPE_MAPPING.items():
    VEHICLE_ALIAS_TO_STANDARD[std.lower()] = std
    VEHICLE_ALIAS_TO_STANDARD[cn] = std
    for a in aliases:
        VEHICLE_ALIAS_TO_STANDARD[a] = std

STANDARD_VEHICLE_TYPES = list(VEHICLE_TYPE_MAPPING.keys())

POLLUTANT_MAPPING = {
    "CO2": ("二氧化碳", ["碳排放", "温室气体"]),
    "CO": ("一氧化碳", []),
    "NOx": ("氮氧化物", ["氮氧"]),
    "PM2.5": ("细颗粒物", ["颗粒物"]),
    "PM10": ("可吸入颗粒物", []),
    "THC": ("总碳氢化合物", ["总烃"]),
}

POLLUTANT_ALIAS_TO_STANDARD = {}
for std, (cn, aliases) in POLLUTANT_MAPPING.items():
    POLLUTANT_ALIAS_TO_STANDARD[std.lower()] = std
    POLLUTANT_ALIAS_TO_STANDARD[cn] = std
    for a in aliases:
        POLLUTANT_ALIAS_TO_STANDARD[a.lower()] = std

STANDARD_POLLUTANTS = list(POLLUTANT_MAPPING.keys())

SEASON_MAPPING = {
    "春": "春季", "春天": "春季", "spring": "春季",
    "夏": "夏季", "夏天": "夏季", "summer": "夏季",
    "秋": "秋季", "秋天": "秋季", "fall": "秋季",
    "冬": "冬季", "冬天": "冬季", "winter": "冬季",
}

# VSP计算参数（MOVES Atlanta 2014+）
VSP_PARAMETERS = {
    11: {"A": 0.0251, "B": 0.0, "C": 0.000315, "M": 0.285, "m": 0.285},      # Motorcycle
    21: {"A": 0.156461, "B": 0.002001, "C": 0.000492, "M": 1.4788, "m": 1.4788}, # Passenger Car
    31: {"A": 0.22112, "B": 0.002837, "C": 0.000698, "M": 1.86686, "m": 1.8668}, # Passenger Truck
    32: {"A": 0.235008, "B": 0.003038, "C": 0.000747, "M": 2.05979, "m": 2.0597}, # Light Commercial Truck
    41: {"A": 1.23039, "B": 0.0, "C": 0.003714, "M": 17.1, "m": 19.593},        # Intercity Bus
    42: {"A": 1.03968, "B": 0.0, "C": 0.003587, "M": 17.1, "m": 16.556},        # Transit Bus
    43: {"A": 0.709382, "B": 0.0, "C": 0.002175, "M": 17.1, "m": 9.0698},       # School Bus
    51: {"A": 1.50429, "B": 0.0, "C": 0.003572, "M": 17.1, "m": 23.113},        # Refuse Truck
    52: {"A": 0.596526, "B": 0.0, "C": 0.001603, "M": 17.1, "m": 8.5389},       # Single-Unit Short Haul
    53: {"A": 0.529399, "B": 0.0, "C": 0.001473, "M": 17.1, "m": 6.9844},       # Single-Unit Long Haul
    54: {"A": 0.655376, "B": 0.0, "C": 0.002105, "M": 17.1, "m": 7.5257},       # Motor Home
    61: {"A": 1.43052, "B": 0.0, "C": 0.003792, "M": 17.1, "m": 22.828},        # Combination Short Haul
    62: {"A": 1.47389, "B": 0.0, "C": 0.003681, "M": 17.1, "m": 24.419},        # Combination Long Haul
}

# VSP分箱
VSP_BINS = {
    1: (-float('inf'), -2),
    2: (-2, 0),
    3: (0, 1),
    4: (1, 4),
    5: (4, 7),
    6: (7, 10),
    7: (10, 13),
    8: (13, 16),
    9: (16, 19),
    10: (19, 23),
    11: (23, 28),
    12: (28, 33),
    13: (33, 39),
    14: (39, float('inf'))
}

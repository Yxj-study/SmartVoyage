"""Small, auditable travel knowledge used by the public SmartVoyage demo."""

TRAVEL_PROFILES: dict[str, dict[str, str]] = {
    # 北京
    "故宫": {"city": "北京", "nearby": "景山公园", "transport": "地铁 1 号线", "feature": "明清宫廷建筑"},
    "天坛": {"city": "北京", "nearby": "前门", "transport": "地铁 5 号线", "feature": "古代祭祀建筑群"},
    "颐和园": {"city": "北京", "nearby": "圆明园", "transport": "地铁 4 号线", "feature": "皇家园林"},
    # 上海
    "外滩": {"city": "上海", "nearby": "南京东路", "transport": "地铁 2 号线", "feature": "城市天际线"},
    "东方明珠": {"city": "上海", "nearby": "上海中心", "transport": "地铁 2 号线", "feature": "城市观景"},
    "豫园": {"city": "上海", "nearby": "城隍庙", "transport": "地铁 10 号线", "feature": "江南古典园林"},
    # 南京
    "中山陵": {"city": "南京", "nearby": "明孝陵", "transport": "地铁 2 号线", "feature": "近代历史地标"},
    "明孝陵": {"city": "南京", "nearby": "中山陵", "transport": "地铁 2 号线", "feature": "明代皇家陵寝"},
    "南京博物院": {"city": "南京", "nearby": "明故宫遗址", "transport": "地铁 2 号线", "feature": "历史文化馆藏"},
    # 杭州
    "西湖": {"city": "杭州", "nearby": "雷峰塔", "transport": "地铁 1 号线", "feature": "湖泊与人文景观"},
    "灵隐寺": {"city": "杭州", "nearby": "飞来峰", "transport": "公交 7 路", "feature": "佛教文化"},
    "雷峰塔": {"city": "杭州", "nearby": "苏堤", "transport": "地铁 4 号线", "feature": "西湖观景"},
    # 西安
    "兵马俑": {"city": "西安", "nearby": "华清宫", "transport": "地铁 9 号线", "feature": "秦代历史遗址"},
    "大雁塔": {"city": "西安", "nearby": "大唐不夜城", "transport": "地铁 3 号线", "feature": "唐代佛教建筑"},
    "西安城墙": {"city": "西安", "nearby": "钟楼", "transport": "地铁 2 号线", "feature": "古城防御建筑"},
    # 成都
    "宽窄巷子": {"city": "成都", "nearby": "人民公园", "transport": "地铁 4 号线", "feature": "川西街巷文化"},
    "武侯祠": {"city": "成都", "nearby": "锦里", "transport": "地铁 3 号线", "feature": "三国文化"},
    "成都大熊猫繁育研究基地": {"city": "成都", "nearby": "成都植物园", "transport": "地铁 3 号线", "feature": "大熊猫保护与科普"},
    # 重庆
    "洪崖洞": {"city": "重庆", "nearby": "解放碑", "transport": "轨道交通 2 号线", "feature": "山城夜景"},
    "解放碑": {"city": "重庆", "nearby": "洪崖洞", "transport": "轨道交通 2 号线", "feature": "城市商业地标"},
    "磁器口古镇": {"city": "重庆", "nearby": "白公馆", "transport": "轨道交通 1 号线", "feature": "巴渝古镇文化"},
    # 长沙
    "橘子洲头": {"city": "长沙", "nearby": "岳麓山", "transport": "地铁 2 号线", "feature": "湘江风光与青年毛泽东艺术雕塑"},
    "岳麓山": {"city": "长沙", "nearby": "岳麓书院", "transport": "地铁 4 号线", "feature": "山岳与书院文化"},
    "湖南博物院": {"city": "长沙", "nearby": "烈士公园", "transport": "地铁 6 号线", "feature": "马王堆汉墓馆藏"},
    # 广州
    "广州塔": {"city": "广州", "nearby": "海心沙", "transport": "地铁 3 号线", "feature": "城市观景"},
    "陈家祠": {"city": "广州", "nearby": "荔枝湾", "transport": "地铁 1 号线", "feature": "岭南建筑艺术"},
    "沙面": {"city": "广州", "nearby": "永庆坊", "transport": "地铁 1 号线", "feature": "近代建筑群"},
    # 苏州
    "拙政园": {"city": "苏州", "nearby": "苏州博物馆", "transport": "地铁 6 号线", "feature": "苏州古典园林"},
    "虎丘": {"city": "苏州", "nearby": "山塘街", "transport": "轨道交通 6 号线", "feature": "历史名胜"},
    "平江路": {"city": "苏州", "nearby": "狮子林", "transport": "地铁 1 号线", "feature": "江南历史街区"},
    # 武汉
    "黄鹤楼": {"city": "武汉", "nearby": "户部巷", "transport": "地铁 5 号线", "feature": "江南名楼与长江景观"},
    "湖北省博物馆": {"city": "武汉", "nearby": "东湖", "transport": "地铁 8 号线", "feature": "曾侯乙墓与楚文化馆藏"},
    # 青岛
    "栈桥": {"city": "青岛", "nearby": "天主教堂", "transport": "地铁 1 号线", "feature": "滨海城市地标"},
    "崂山": {"city": "青岛", "nearby": "仰口景区", "transport": "公共交通", "feature": "山海景观与道教文化"},
    # 厦门
    "鼓浪屿": {"city": "厦门", "nearby": "日光岩", "transport": "轮渡", "feature": "世界文化遗产与近代建筑"},
    "厦门大学": {"city": "厦门", "nearby": "南普陀寺", "transport": "公共交通", "feature": "滨海校园与人文景观"},
    # 三亚
    "亚龙湾": {"city": "三亚", "nearby": "亚龙湾热带天堂森林公园", "transport": "公共交通", "feature": "热带滨海景观"},
    "天涯海角": {"city": "三亚", "nearby": "西岛", "transport": "公共交通", "feature": "海滨礁石与文化地标"},
    # 天津
    "天津之眼": {"city": "天津", "nearby": "古文化街", "transport": "地铁 4 号线", "feature": "海河城市观景"},
    "五大道": {"city": "天津", "nearby": "民园广场", "transport": "地铁 1 号线", "feature": "近代建筑街区"},
    # 哈尔滨
    "圣索菲亚教堂": {"city": "哈尔滨", "nearby": "中央大街", "transport": "地铁 2 号线", "feature": "历史建筑与城市记忆"},
    "冰雪大世界": {"city": "哈尔滨", "nearby": "太阳岛", "transport": "地铁 2 号线", "feature": "季节性冰雪艺术"},
    # 沈阳
    "沈阳故宫": {"city": "沈阳", "nearby": "张学良旧居", "transport": "地铁 1 号线", "feature": "清代宫廷建筑"},
    "九一八历史博物馆": {"city": "沈阳", "nearby": "北陵公园", "transport": "地铁 4 号线", "feature": "近代历史专题展陈"},
    # 大连
    "星海广场": {"city": "大连", "nearby": "星海公园", "transport": "地铁 1 号线", "feature": "滨海广场与城市景观"},
    "老虎滩海洋公园": {"city": "大连", "nearby": "渔人码头", "transport": "地铁 5 号线", "feature": "海洋主题与滨海风光"},
    # 济南
    "趵突泉": {"city": "济南", "nearby": "五龙潭", "transport": "公共交通", "feature": "泉水文化景观"},
    "大明湖": {"city": "济南", "nearby": "曲水亭街", "transport": "公共交通", "feature": "湖泊与古城文化"},
    # 洛阳
    "龙门石窟": {"city": "洛阳", "nearby": "香山寺", "transport": "公共交通", "feature": "世界文化遗产与石刻艺术"},
    "洛阳博物馆": {"city": "洛阳", "nearby": "隋唐城遗址植物园", "transport": "地铁 2 号线", "feature": "古都历史馆藏"},
    # 开封
    "清明上河园": {"city": "开封", "nearby": "龙亭公园", "transport": "公共交通", "feature": "宋文化主题园区"},
    "开封府": {"city": "开封", "nearby": "包公祠", "transport": "公共交通", "feature": "宋代府衙文化展示"},
    # 郑州
    "河南博物院": {"city": "郑州", "nearby": "郑州动物园", "transport": "地铁 2 号线", "feature": "中原文明馆藏"},
    "少林寺": {"city": "郑州", "nearby": "嵩山", "transport": "旅游交通", "feature": "禅宗文化与武术传统"},
    # 昆明
    "滇池": {"city": "昆明", "nearby": "海埂大坝", "transport": "地铁 5 号线", "feature": "高原湖泊与候鸟景观"},
    "云南民族村": {"city": "昆明", "nearby": "滇池", "transport": "地铁 5 号线", "feature": "云南民族文化展示"},
    # 大理
    "大理古城": {"city": "大理", "nearby": "崇圣寺三塔", "transport": "公共交通", "feature": "白族历史街区"},
    "洱海": {"city": "大理", "nearby": "双廊古镇", "transport": "环湖交通", "feature": "高原湖泊与苍山景观"},
    # 丽江
    "丽江古城": {"city": "丽江", "nearby": "黑龙潭", "transport": "公共交通", "feature": "世界文化遗产与纳西文化"},
    "玉龙雪山": {"city": "丽江", "nearby": "蓝月谷", "transport": "旅游交通", "feature": "高山冰川与自然景观"},
    # 贵阳
    "青岩古镇": {"city": "贵阳", "nearby": "花溪公园", "transport": "公共交通", "feature": "明清古镇与地方文化"},
    "黔灵山公园": {"city": "贵阳", "nearby": "弘福寺", "transport": "地铁 3 号线", "feature": "城市山地公园"},
    # 桂林
    "象鼻山": {"city": "桂林", "nearby": "两江四湖", "transport": "公共交通", "feature": "喀斯特山水地标"},
    "漓江": {"city": "桂林", "nearby": "阳朔", "transport": "游船", "feature": "喀斯特山水长廊"},
    # 南宁
    "青秀山": {"city": "南宁", "nearby": "南宁园博园", "transport": "地铁 3 号线", "feature": "亚热带植物与城市山景"},
    "广西民族博物馆": {"city": "南宁", "nearby": "青秀山", "transport": "公共交通", "feature": "广西民族文化馆藏"},
    # 福州
    "三坊七巷": {"city": "福州", "nearby": "林则徐纪念馆", "transport": "地铁 1 号线", "feature": "历史街区与闽都文化"},
    "鼓山": {"city": "福州", "nearby": "涌泉寺", "transport": "地铁 2 号线", "feature": "山岳与佛教文化"},
    # 泉州
    "开元寺": {"city": "泉州", "nearby": "西街", "transport": "公共交通", "feature": "海丝文化与古代寺院"},
    "清源山": {"city": "泉州", "nearby": "老君岩", "transport": "公共交通", "feature": "山岳石刻与道教文化"},
}

LANDMARK_ALIASES: dict[str, str] = {
    "毛泽东青年艺术雕塑": "橘子洲头",
    "青年毛泽东艺术雕塑": "橘子洲头",
    "青年毛泽东雕像": "橘子洲头",
    "橘子洲": "橘子洲头",
    "秦始皇兵马俑": "兵马俑",
    "秦始皇帝陵博物院": "兵马俑",
    "熊猫基地": "成都大熊猫繁育研究基地",
    "成都熊猫基地": "成都大熊猫繁育研究基地",
    "南京博物馆": "南京博物院",
    "湖南省博物馆": "湖南博物院",
    "东方明珠塔": "东方明珠",
    "西安古城墙": "西安城墙",
    "橘子洲毛泽东雕像": "橘子洲头",
    "毛主席青年艺术雕塑": "橘子洲头",
    "索菲亚教堂": "圣索菲亚教堂",
    "圣索菲亚大教堂": "圣索菲亚教堂",
    "大熊猫基地": "成都大熊猫繁育研究基地",
    "象山景区": "象鼻山",
    "龙门": "龙门石窟",
}

"""信息源配置。只用公开、免费、允许程序访问的来源。

level_floor：这个来源的消息最低给到哪一级（官方来源至少黄色）。
every：抓取间隔（秒）。请不要调得太小，以免被对方限流。
"""

NEWS_SOURCES = [
    # ---- 官方 ----
    dict(name="美联储", url="https://www.federalreserve.gov/feeds/press_all.xml", kind="rss", every=120, cred=3, level_floor=None),
    dict(name="SEC", url="https://www.sec.gov/news/pressreleases.rss", kind="rss", every=300, cred=3, level_floor=None),
    dict(name="CFTC", url="https://www.cftc.gov/RSS/RSSGP/rssgp.xml", kind="rss", every=600, cred=3, level_floor=None),
    dict(name="币安公告", url="https://www.binance.com/bapi/composite/v1/public/cms/article/list/query?type=1&pageNo=1&pageSize=20",
         kind="binance", every=60, cred=3, level_floor=None),
    # ---- 加密媒体 ----
    dict(name="CoinDesk", url="https://www.coindesk.com/arc/outboundfeeds/rss", kind="rss", every=90, cred=2, level_floor=None),
    dict(name="Cointelegraph", url="https://cointelegraph.com/rss", kind="rss", every=90, cred=2, level_floor=None),
    dict(name="The Block", url="https://www.theblock.co/rss.xml", kind="rss", every=90, cred=2, level_floor=None),
    dict(name="Decrypt", url="https://decrypt.co/feed", kind="rss", every=120, cred=2, level_floor=None),
    dict(name="Bitcoin Magazine", url="https://bitcoinmagazine.com/.rss/full/", kind="rss", every=300, cred=2, level_floor=None),
    dict(name="Odaily快讯", url="https://rss.odaily.news/rss/newsflash", kind="rss", every=60, cred=2, level_floor=None),
    # ---- 全网聚合（直接 + 间接） ----
    dict(name="Google新闻·比特币", url="https://news.google.com/rss/search?q=bitcoin+OR+BTC+OR+crypto+when:1h&hl=en-US&gl=US&ceid=US:en",
         kind="rss", every=120, cred=1, level_floor=None),
    dict(name="Google新闻·宏观", url="https://news.google.com/rss/search?q=(Fed+OR+Powell+OR+inflation+OR+%22rate+hike%22+OR+%22rate+cut%22+OR+tariff+OR+Treasury+yields)+when:1h&hl=en-US&gl=US&ceid=US:en",
         kind="rss", every=180, cred=1, level_floor=None),
    dict(name="Google新闻·地缘", url="https://news.google.com/rss/search?q=(war+OR+missile+OR+invasion+OR+sanctions+OR+%22oil+prices%22+OR+coup+OR+default)+when:1h&hl=en-US&gl=US&ceid=US:en",
         kind="rss", every=180, cred=1, level_floor=None),
    dict(name="Google新闻·中文", url="https://news.google.com/rss/search?q=%E6%AF%94%E7%89%B9%E5%B8%81+OR+%E7%BE%8E%E8%81%94%E5%82%A8+when:1h&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
         kind="rss", every=180, cred=1, level_floor=None),
    dict(name="GDELT全球", url="https://api.gdeltproject.org/api/v2/doc/doc?query=(bitcoin%20OR%20cryptocurrency%20OR%20%22federal%20reserve%22)&mode=artlist&format=json&timespan=30min&maxrecords=50&sort=datedesc",
         kind="gdelt", every=900, cred=1, level_floor=None),
]

CALENDAR_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"   # ForexFactory 本周经济日历
CALENDAR_EVERY = 3 * 3600

BINANCE = "https://fapi.binance.com"
SYMBOL = "BTCUSDT"

# Yahoo 跨市场：代码 → (名称, 5 分钟内变动超过多少 % 算异动)
CROSS_ASSETS = {
    "NQ=F": ("纳指期货", 0.6),
    "GC=F": ("黄金期货", 0.8),
    "CL=F": ("原油期货", 2.0),
    "DX-Y.NYB": ("美元指数", 0.35),
    "JPY=X": ("美元兑日元", 0.6),
    "^TNX": ("美债10年收益率", 2.0),
}
YAHOO_SPARK = "https://query1.finance.yahoo.com/v7/finance/spark?symbols={syms}&range=1d&interval=5m"

# 与 BTC 联动的美股（面板「美股联动」卡片同一份名单）。实时价由面板直连币安股票永续；
# 这里抓 Yahoo 的官方价：收盘价、盘前盘后最后成交、含夜盘的全时段最新价，作为对照
US_STOCKS = ["QQQ", "SPY", "IWM", "NVDA", "MSTR", "COIN", "BMNR", "CRCL", "HOOD", "MARA", "IREN", "BITO"]
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?interval=1m&range=1d&includePrePost=true"

# 美股（NYSE）休市日：这些日子不提醒美股开盘
US_MARKET_HOLIDAYS = {
    "2026-11-26", "2026-12-25",
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26", "2027-05-31", "2027-06-18",
    "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24",
}

# 已经公布的重大事件（美东时间）。ForexFactory 只提供本周日历，这里补上更远的；已核实的才写进来
SCHEDULED_EVENTS = [
    ("FOMC 利率决议", "2026-10-28T14:00:00-04:00"),
    ("美国 CPI（10 月）", "2026-11-10T08:30:00-05:00"),
]

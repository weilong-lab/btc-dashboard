"""新闻分级规则：关键词 + 来源可信度 + 多源印证。

red    = 可能马上引起大波动：黑客 / 交易所出事 / 战争 / 央行意外动作 / 重大监管
yellow = 今天内可能影响：ETF 资金流、宏观数据、美联储讲话、关税、大机构买卖、监管进展
gray   = 背景信息，只记日志

方向标签（偏多 / 偏空）只是字面猜测，不可靠，仅供参考；等事件日志积累后再回测。
"""
import re

DIRECT = re.compile(r"\b(bitcoin|btc|crypto|cryptocurrenc\w*|stablecoin|tether|usdt|usdc|ether(eum)?|binance|coinbase|blackrock\s+ibit|ibit|microstrategy|strategy\s+inc|saylor|spot\s+etf)\b|比特币|加密|币安|稳定币|以太坊|交易所", re.I)
INDIRECT = re.compile(r"\b(fed|fomc|powell|federal reserve|inflation|cpi|ppi|payrolls?|jobs report|unemployment|rate (hike|cut)s?|interest rates?|treasur(y|ies)|yields?|dollar|tariffs?|sanctions?|war|missile|invasion|airstrikes?|oil|opec|nasdaq|s&p 500|recession|default|bank (run|failure)|boj|bank of japan|yen)\b|美联储|鲍威尔|通胀|非农|加息|降息|关税|制裁|战争|导弹|原油|美债|日元|日本央行|纳指|衰退", re.I)

RED = [
    r"\b(insolven\w*|bankrupt\w*|collapse[sd]?)\b",
    r"\b(halt(s|ed)?|suspend(s|ed)?|pause[sd]?)\s+(all\s+)?(withdrawals?|deposits?|trading)\b", r"\bdepeg\w*\b",
    r"\bemergency\b", r"\b(unexpected|surprise|unscheduled)\b.*\b(rate|hike|cut|meeting)\b",
    r"\b(invasion|invades?|invaded|missile (strike|attack)s?|airstrikes?|nuclear (strike|attack|test)|declares? war|coup|martial law)\b",
    r"\bfomc statement\b|\b(fed|federal reserve)\b.*\b(raises|lowers|cuts|hikes)\b.*\brates?\b",
    r"\b(ban(s|ned)?)\b.*\b(bitcoin|crypto)\b", r"\b(sec|doj|cftc)\b.*\b(sues?|charges?|indict\w*)\b",
    r"\bdelist\w*\b", r"\b(flash crash|circuit breaker)\b",
    r"\b(liquidat\w+)\b.*\$?\d+(\.\d+)?\s*(billion|bn)\b",
    r"暂停提[现币]|暴雷|跑路|破产|脱锚|紧急|意外(加息|降息)|宣战|导弹袭击|空袭|入侵|政变|禁止.*(比特币|加密)|闪崩|熔断",
    r"(SEC|美国证监会|司法部|DOJ|CFTC).*(起诉|指控|逮捕)",
]
HACK = re.compile(r"\b(hack(ed|s)?|exploit(ed|s)?|drain(ed)?|stolen|breach(ed)?)\b|被盗|黑客", re.I)
AMOUNT = re.compile(r"\$\s?(\d+(?:\.\d+)?)\s*(billion|bn|b|million|mn|m)\b|(\d+(?:\.\d+)?)\s*亿美元", re.I)
FED_POLICY = re.compile(r"\b(fomc|monetary policy|interest rates?|federal funds|discount rate|powell|minutes|economic projections|beige book|emergency)\b", re.I)
YELLOW = [
    r"\betfs?\b.*\b(inflows?|outflows?|flows?)\b", r"\b(cpi|ppi|payrolls?|jobs report|pce|gdp)\b", r"\b(fomc|powell|fed (chair|governor|official)s?)\b",
    r"\brate (hike|cut)s?\b", r"\btariffs?\b", r"\bsanctions?\b", r"\b(treasury yields?|bond yields?)\b",
    r"\b(strategy|microstrategy|saylor|blackrock|fidelity|tesla|government)\b.*\b(buy|bought|sell|sold|acquire\w*|transfer\w*)\b",
    r"\b(mt\.? ?gox|silk road|seized)\b", r"\bliquidat\w+\b", r"\bwhales?\b", r"\b(regulat\w+|bill|senate|congress)\b.*\b(crypto|stablecoin|bitcoin)\b",
    r"\b(oil prices?|opec)\b", r"\b(bank of japan|boj)\b", r"\bshort squeeze\b",
    r"美联储|鲍威尔|非农|通胀|加息|降息|关税|制裁|ETF.*(流入|流出)|增持|减持|抛售|巨鲸|爆仓|监管|法案|原油|日本央行|空头挤压",
]
BULL = re.compile(r"\b(inflows?|approv\w+|buys?|bought|accumulat\w+|rate cut|cuts rates|rall(y|ies)|surg\w+|record high|adopt\w+)\b|流入|批准|增持|降息|上涨|新高", re.I)
BEAR = re.compile(r"\b(outflows?|hack\w*|ban\w*|sues?|sell-?off|sold|dump\w*|rate hike|hikes rates|plung\w+|crash\w*|war|tariffs?|sanctions?|liquidat\w+)\b|流出|被盗|禁止|起诉|抛售|加息|下跌|暴跌|战争|关税|制裁|爆仓", re.I)

RED_RE = [re.compile(p, re.I) for p in RED]
YELLOW_RE = [re.compile(p, re.I) for p in YELLOW]
ORDER = {"gray": 0, "yellow": 1, "red": 2}


def classify(title, summary, source):
    text = f"{title} {summary}"
    direct = bool(DIRECT.search(text))
    indirect = bool(INDIRECT.search(text))
    if not direct and not indirect:
        return None  # 与 BTC 无关，丢弃
    hits = [p.pattern for p in RED_RE if p.search(text)]
    if HACK.search(text):
        usd = 0.0
        for m in AMOUNT.finditer(text):
            if m.group(3):
                usd = max(usd, float(m.group(3)) * 1e8)
            else:
                usd = max(usd, float(m.group(1)) * (1e9 if m.group(2).lower() in ("billion", "bn", "b") else 1e6))
        # 单笔 ≥ 1 亿美元、且不是「年度累计」类报道才算红色
        if usd >= 1e8 and not re.search(r"\b(in 20\d\d|so far|this year|year-to-date|ytd)\b|今年|累计", text, re.I):
            hits.append("hack>=100M")
    level = "red" if hits else None
    if level is None and (any(p.search(text) for p in YELLOW_RE) or (HACK.search(text) and direct)):
        level = "yellow"
    if level is None:
        level = "gray"
    # 币安公告大多是山寨币上下架，只有提到 BTC 的才保留级别
    if source["kind"] == "binance" and not re.search(r"\b(btc|bitcoin)\b|比特币", text, re.I):
        level = "gray"
    # 美联储新闻稿大多是银行监管，只有货币政策相关的才算
    if source["name"] == "美联储":
        level = level if FED_POLICY.search(text) else "gray"
        if level == "gray" and FED_POLICY.search(text):
            level = "yellow"
    floor = source.get("level_floor")
    if floor and ORDER[floor] > ORDER[level]:
        level = floor
    bull, bear = len(BULL.findall(text)), len(BEAR.findall(text))
    lean = "利多" if bull > bear else "利空" if bear > bull else "中性"
    if lean != "中性" and (level == "gray" or not direct):
        lean += "（弱）"
    return dict(level=level, relevance="直接" if direct else "间接", lean=lean, matched=hits[:3])


_WORD = re.compile(r"[a-z0-9]+|[一-鿿]")


def tokens(title):
    t = re.sub(r"\s+-\s+[^-]+$", "", title.lower())  # 去掉 Google 新闻标题末尾的「 - 媒体名」
    return set(w for w in _WORD.findall(t) if len(w) > 2 or re.match(r"[一-鿿]", w))


def similar(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)

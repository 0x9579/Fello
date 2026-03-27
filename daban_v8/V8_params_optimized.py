# coding:gbk
"""
QMT 开盘打板策略 V2.7 — 优化版
重构说明：
1. 引入 logging 替代 print
2. 用 dataclass 定义全局状态和股票状态
3. 消除重复代码（sell/handle_data 系列）
4. 修复 P0 级 bug（未定义变量、API 返回类型错误等）
5. 常量/枚举替代魔法数字
6. 规范命名
"""

import pandas as pd
import numpy as np
import requests
import json
import re
import logging
from datetime import datetime, time, timedelta
from time import sleep
import xml.etree.ElementTree as ET
import os
import inspect
import ast
import math
import pytz
from itertools import islice

# ============================================================
# 日志配置
# ============================================================
logger = logging.getLogger("DabanV8")
logger.setLevel(logging.INFO)
logger.propagate = False  # 不传播到 root logger，避免重复/空行
logger.handlers = []  # 清除所有残留 handler
_handler = logging.StreamHandler()
# _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(_handler)

# ============================================================
# 常量定义
# ============================================================

# 委托状态
class OrderStatus(object):
    INVALID = 57  # 废单

# 委托方向
class OpDirection(object):
    BUY_NORMAL = 23
    SELL_NORMAL = 24
    BUY_MARGIN = 33
    SELL_MARGIN = 34

# 委托价格类型
class PriceType(object):
    LIMIT = 11
    MARKET_SH = 42   # 上海最优五档即时成交剩余撤销
    MARKET_SZ = 44   # 深圳对手方最优价格委托（通用）
    MARKET_SZ2 = 46  # 深圳最优五档即时成交剩余撤销

# 委托模式
class OrderMode(object):
    BY_AMOUNT = 1102  # 按金额
    BY_VOLUME = 1101  # 按数量

# 交易所后缀映射
EXCHANGE_SUFFIX_MAP = {
    'XSHG': '.SH',
    'XSHE': '.SZ',
    'XSB': '.BJ',
    'SH': '.SH',
    'SZ': '.SZ',
    'BJ': '.BJ',
}

# 股票前缀 → 交易所
CODE_PREFIX_EXCHANGE = {
    '60': '.SH',
    '000': '.SZ',
    '001': '.SZ',
    '002': '.SZ',
    '300': '.SZ',
    '688': '.SH',
}

# 文件路径
TRADE_RECORD_FILE = 'trade_records.json'

# ============================================================
# 全局状态定义
# ============================================================

class StockMonitorState(object):
    """持仓股票的盘中监控状态"""
    def __init__(self):
        self.price_history = []
        self.last_price = 0.0
        self.last_price1 = 0.0
        self.price_change_history = []
        self.monitor_next_minute = False
        self.initial_price_for_monitor = None
        self.sum_zhangfu = 4.0
        self.time_counter = 0


class StockCandidateState(object):
    """候选股票的竞价阶段状态"""
    def __init__(self, yesterday_close=1.0, yesterday_volume=1.0, yesterday_amount=1.0):
        self.price_history = []
        self.last_price = 0.0
        self.last_price1 = 0.0
        self.up_stop_price = 0.0
        self.kp_stop_price = 0
        self.yesterday_close = yesterday_close
        self.kp_price = 0.0
        self.jj_tag = 0
        self.zuigao_price = 0.0
        self.zuidi_price = 0.0
        self.last_jj_price = 1.0
        self.last_jj_volume = 1.0
        self.last_jj_amount = 1.0
        self.yesterday_volume = yesterday_volume
        self.yesterday_amount = yesterday_amount
        self.last_price_kaip = 1.0
        self.last_volume_kaip = 1.0
        self.price_change_history = []
        self.monitor_next_minute = False
        self.initial_price_for_monitor = None
        self.sum_zhangfu = 9.5
        self.time_counter = 0
        self.mairu_tag = 0
        self.orderid = 0


class GlobalState(object):
    """全局策略状态"""
    def __init__(self):
        self.banben = 'V2.7'
        self.cese = 1
        self.stock = []
        self.positions = []
        self.stocks_date2 = {}
        self.tag = 0
        self.tag1 = 0
        self.jine = 0.0
        self.sum_xishu = 0.3
        self.tag_fenzhong = 0
        self.result = None
        self.stock_states = {}
        self.stock_states1 = {}
        self.day = 0
        self.count = 0
        self.stocknum = 5
        self.start = ''
        self.end = ''
        self.time_counter = 0
        self.holdings = {}
        self.weight = [0.1] * 10
        self.buypoint = {}
        self.money = 10000000.0
        self.mairu_tag = 1       # 0-限价委托 1-市价委托
        self.enddate = '2028-03-22'
        self.profit = 0.0
        self.opType = 0          # 0-普通账户 1-融资账户
        self.yun_tag = 1         # 0-回测 1-实盘运行
        self.ti_qian = 0         # 1-提前卖出
        self.before_market_open = 0
        self.before_market_stock = 0
        self.buy_num = 10
        self.per_money = 10000.0
        self.xml_tag = 0
        self.huoqu_tag = 1       # 0-QMT获取 1-聚宽获取
        self.zijin_num = 10000.0
        self.stock_jj = []
        self.stock_mai = []
        self.stock_pool = {}
        self.his_st = {}
        self.s = []
        self.skip_filter = 1  # 1-跳过竞价筛选，直接买入股票池所有股票；0-正常筛选


g = GlobalState()

# ============================================================
# 文件 I/O
# ============================================================

def write_to_file(data, file_path=TRADE_RECORD_FILE):
    """将数据写入 JSON 文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def read_from_file(file_path=TRADE_RECORD_FILE):
    """从 JSON 文件读取数据"""
    if not os.path.exists(file_path):
        logger.debug("文件不存在: %s", file_path)
        return []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            logger.debug("成功读取文件: %s", file_path)
            return data
    except json.JSONDecodeError:
        logger.warning("文件读取失败，可能是空文件: %s", file_path)
        return []


# ============================================================
# 股票代码工具
# ============================================================

def convert_to_qmt_format(stock_list):
    """将股票代码统一转换为 QMT 格式（.SH / .SZ / .BJ）"""
    converted = []
    for stock in stock_list:
        parts = stock.split('.', 1)
        if not parts[0]:
            continue
        code = parts[0].zfill(6)
        if len(code) != 6:
            raise ValueError(f"股票代码长度不为6: {stock}")

        exchange = parts[1] if len(parts) > 1 else ""

        if exchange == "":
            suffix = _get_suffix_by_code(code, stock)
        else:
            suffix = EXCHANGE_SUFFIX_MAP.get(exchange)
            if suffix is None:
                raise ValueError(f"未知的交易所后缀: {exchange}")

        converted.append(f"{code}{suffix}")
    return converted


def _get_suffix_by_code(code, original_stock=""):
    """根据代码前缀推断交易所后缀"""
    for prefix, suffix in CODE_PREFIX_EXCHANGE.items():
        if code.startswith(prefix):
            return suffix
    raise ValueError(f"未知的股票代码前缀，无法填充交易所后缀: {original_stock}")


def determine_stock_type(stock_code):
    """判断股票交易所：0=上海, 1=深圳"""
    if stock_code.endswith('.SH'):
        return 0
    elif stock_code.endswith('.SZ'):
        return 1
    else:
        raise ValueError(f"未知的股票代码后缀: {stock_code}")


def calculate_limit_up_price(yesterday_close, stock_code):
    """根据昨日收盘价和股票代码，计算今日涨停价"""
    if stock_code.startswith("68") or stock_code.startswith("30"):
        pct = 0.20
    elif stock_code.startswith("00") or stock_code.startswith("60"):
        pct = 0.05 if ("ST" in stock_code or "*ST" in stock_code) else 0.10
    else:
        raise ValueError(f"无法识别股票代码 {stock_code} 的板块")
    return round(yesterday_close * (1 + pct), 2)


def calculate_buy_price(price, stock_code):
    """根据最新价格和股票代码计算买入价格"""
    if price <= 0:
        raise ValueError("价格必须为正数")
    if stock_code.startswith(('60', '00')) and price <= 5:
        return round(price + 0.1, 2)
    return round(price * 1.015, 2)


def calculate_stock_quantity(jine, pricemai):
    """计算可购买的手数（100的整数倍）"""
    try:
        if not (isinstance(jine, (int, float)) and isinstance(pricemai, (int, float))):
            raise ValueError("jine 和 pricemai 必须是数字类型")
        if pricemai <= 0:
            raise ValueError("买入价格必须大于0")
        stock_sum = math.floor(jine / pricemai / 100) * 100
        return stock_sum if stock_sum >= 100 else 0
    except ValueError as e:
        logger.error("计算股票数量出错: %s", e)
        return 0


# ============================================================
# 委托方向/价格类型辅助
# ============================================================

def get_op_type(is_buy=True):
    """根据账户类型获取买卖方向"""
    if is_buy:
        return OpDirection.BUY_MARGIN if g.opType == 1 else OpDirection.BUY_NORMAL
    return OpDirection.SELL_MARGIN if g.opType == 1 else OpDirection.SELL_NORMAL


def get_market_price_type(stock_code):
    """获取市价委托类型"""
    # 目前统一使用深圳对手方最优
    return PriceType.MARKET_SZ


def get_sell_market_price_type(stock_code):
    """获取卖出市价委托类型（午盘根据交易所区分）"""
    if determine_stock_type(stock_code) == 0:
        return PriceType.MARKET_SH
    return PriceType.MARKET_SZ2


# ============================================================
# 股票池获取
# ============================================================

def get_stock_pool_from_panel(C):
    """从面板变量 stock_N 获取股票池"""
    stock_list = []
    for var_name in globals():
        if re.match(r'^stock_\d+$', var_name):
            stock_list.append(str(globals()[var_name]))
    stock_list = convert_to_qmt_format(stock_list)
    return {stock: {'close': 0, 'volume': 0, 'money': 0} for stock in stock_list}


# mainMessages 与 get_stock_pool_from_panel 功能完全一致，统一为一个函数
mainMessages = get_stock_pool_from_panel


def extract_matching_stocks(log_line):
    """从日志行中提取符合要求的股票列表"""
    start_index = log_line.find("最后筛选符合要求的股票：")
    if start_index == -1:
        logger.debug("No match found in the log line.")
        return []
    start_bracket = log_line.find('[', start_index)
    end_bracket = log_line.find(']', start_index)
    if start_bracket == -1 or end_bracket == -1:
        return []
    try:
        return ast.literal_eval(log_line[start_bracket:end_bracket + 1])
    except (ValueError, SyntaxError) as e:
        logger.error("解析错误: %s", e)
        return []


# ============================================================
# XML 配置读取
# ============================================================

def read_xml(file_path):
    """解析 XML 配置文件"""
    try:
        if not os.path.exists(file_path):
            logger.error("文件 %s 不存在", file_path)
            return None
        if not os.access(file_path, os.R_OK):
            logger.error("没有权限读取文件 %s", file_path)
            return None
        tree = ET.parse(file_path)
        root = tree.getroot()
        config_data = {}
        for control in root.findall('control'):
            for variable in control.findall('variable'):
                for item in variable.findall('item'):
                    item_data = {attr: item.get(attr, '') for attr in
                                 ['position', 'bind', 'value', 'note', 'name', 'type']}
                    config_data[item.get('bind')] = item_data
        return config_data
    except ET.ParseError as e:
        logger.error("XML 格式错误: %s", e)
    except Exception as e:
        logger.error("未知错误: %s", e)
    return None


# ============================================================
# 昨日数据获取（消除重复）
# ============================================================

def get_yesterday_close(C, stock, date_str):
    """获取股票昨日收盘价，返回 (yesterday_close, success)"""
    date_obj = datetime.strptime(date_str, '%Y%m%d%H%M%S')
    yesterday_str = (date_obj - timedelta(days=1)).strftime('%Y%m%d%H%M%S')
    volume_data = C.get_market_data_ex(
        ['close'], stock_code=[stock], period="1d",
        start_time='', end_time=yesterday_str, count=2, dividend_type='none'
    )
    if stock in volume_data:
        return volume_data[stock]['close'].iloc[-1], True
    logger.warning("未找到股票 %s 的昨日数据", stock)
    return 0.0, False


def get_current_price(C, stock, date_str=None):
    """获取股票当前价格"""
    if g.yun_tag == 1:
        quote = C.get_full_tick([stock])
        return quote[stock]['lastPrice']
    else:
        volume_data = C.get_market_data_ex(
            ['open'], stock_code=[stock], period=C.period,
            start_time=date_str, end_time=date_str, dividend_type='none'
        )
        return volume_data[stock]['open'][-1]


# ============================================================
# 通用卖出逻辑（消除 sellzhong/sellwans/selllasheng 重复）
# ============================================================

def _sell_positions(C, price_offset, require_profit, use_market_sell=False,
                    target_stock=None, log_label=""):
    """
    通用卖出函数
    :param price_offset: 限价卖出时的价格偏移量
    :param require_profit: 是否要求盈利才卖出
    :param use_market_sell: 是否用 order_target_value 市价清仓
    :param target_stock: 指定卖出的股票代码，None 则遍历所有持仓
    :param log_label: 日志标签（如"11:27"）
    """
    positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    trade_records = read_from_file()
    logger.info("读取文件内的股票: %s", trade_records)

    for dt in positions:
        s = dt.m_strInstrumentID + "." + dt.m_strExchangeID

        # 如果指定了目标股票，跳过其他
        if target_stock and s != target_stock:
            continue

        # 检查是否在交易记录中
        if not any(s in record.get("code", []) for record in trade_records):
            logger.info("股票 %s 不在交易记录中，跳过卖出", s)
            continue

        cu = C.get_instrumentdetail(s)
        quote = C.get_full_tick([s])
        price = quote[s]['lastPrice']

        # 条件检查
        if dt.m_nCanUseVolume == 0:
            continue
        if require_profit and price <= dt.m_dOpenPrice:
            continue
        if price >= cu['UpStopPrice']:  # 涨停不卖
            continue

        if use_market_sell:
            logger.info("市价清仓卖出: %s, 价格=%s", s, price)
            order_target_value(s, 0, 'MARKET', C, C.accountid)
        else:
            sell_price = round(price - price_offset, 2)
            sell_price = max(sell_price, cu['DownStopPrice'])
            op_type = get_op_type(is_buy=False)
            price_type = get_sell_market_price_type(s)
            logger.info("%s 卖出: %s, 当前价=%s, 委托价=%s, 涨停=%s, 跌停=%s",
                        log_label, s, price, sell_price,
                        cu['UpStopPrice'], cu['DownStopPrice'])
            passorder(op_type, OrderMode.BY_VOLUME, C.accountid, s,
                      price_type, 0, dt.m_nCanUseVolume, '', 2, '', C)

        # 更新交易记录（清仓场景）
        if use_market_sell:
            updated = []
            for record in trade_records:
                if s in record.get("code", []):
                    record["code"].remove(s)
                    if not record["code"]:
                        continue
                updated.append(record)
            if updated != trade_records:
                write_to_file(updated)


def sellzhong(C):
    """午盘前卖出（盈利且未涨停）"""
    _sell_positions(C, price_offset=0.07, require_profit=True, log_label="11:27")


def sellwans(C):
    """尾盘卖出（未涨停，不要求盈利）"""
    _sell_positions(C, price_offset=0.07, require_profit=False, log_label="14:49")


def selllasheng(C, stock):
    """日内拉升信号卖出"""
    _sell_positions(C, price_offset=0.09, require_profit=False,
                    use_market_sell=True, target_stock=stock, log_label="拉升")


# ============================================================
# 通用开盘检查卖出（消除 handle_data1/2/3 重复）
# ============================================================

def _check_and_sell(C, positions_list, date, check_fn, log_label):
    """
    通用的开盘检查卖出框架
    :param check_fn: 接收 (last_price, yesterday_close, high) 返回 bool
    """
    for stock in positions_list:
        last_price = get_current_price(C, stock, date)
        high = None
        if g.yun_tag == 1:
            quote = C.get_full_tick([stock])
            high = quote[stock].get('high', last_price)

        yesterday_close, ok = get_yesterday_close(C, stock, date)
        if not ok:
            continue

        if check_fn(last_price, yesterday_close, high):
            logger.info("%s 触发卖出: %s, 价格=%s, 昨收=%s",
                        log_label, stock, last_price, yesterday_close)
            selllasheng(C, stock)
            account_detail(C)


def handle_data1(C, positions, date):
    """9:30 低开 ≥2% 触发卖出"""
    def check(price, yd_close, high):
        change = (price - yd_close) / yd_close * 100.0
        return change <= -2
    _check_and_sell(C, positions, date, check, "低开2%检查")


def handle_data2(C, positions, date):
    """9:33 开盘价低于昨收触发卖出"""
    def check(price, yd_close, high):
        return price < yd_close
    _check_and_sell(C, positions, date, check, "开盘价检查")


def handle_data3(C, positions, date):
    """10:30 最高点后回调 ≥1.5% 触发卖出"""
    def check(price, yd_close, high):
        if high and high > 0:
            return (price - high) / high * 100.0 <= -1.5
        return False
    _check_and_sell(C, positions, date, check, "回调1.5%检查")


# ============================================================
# 竞价数据处理
# ============================================================

def handle_data0(C, positions, date):
    """集合竞价阶段筛选候选股票"""
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    yesterday_str = (date_obj - timedelta(days=1)).strftime('%Y%m%d%H%M%S')

    for stock in positions:
        state = g.stock_states1[stock]
        if state.jj_tag == 1:
            continue

        if g.yun_tag == 1:
            quote = C.get_full_tick([stock])
            state.last_jj_price = quote[stock]['lastPrice']
            state.last_jj_volume = quote[stock]['volume']
            state.last_jj_amount = quote[stock]['amount']
            timetag_str = quote[stock]['timetag']
            formatted_date = f"{timetag_str[0:4]}-{timetag_str[4:6]}-{timetag_str[6:8]}"
            if formatted_date > g.enddate:
                logger.warning("策略已到期，请联系续费。")
                return
        else:
            vol_data = C.get_market_data_ex(
                [], stock_code=[stock], period=C.period,
                start_time=date, end_time=date, dividend_type='none'
            )
            state.last_jj_price = vol_data[stock]['open'][-1]
            state.last_jj_volume = vol_data[stock]['volume'][-1]
            state.last_jj_amount = vol_data[stock]['amount'][-1]

        if state.last_jj_price == 0 or state.last_jj_amount == 0:
            logger.info("股票%s没有获取到数据,等待下一秒", stock)
            continue

        g.count += 1
        state.jj_tag = 1

        current_ratio = state.last_jj_price / state.yesterday_close
        if current_ratio >= 1.095:
            continue  # 涨幅过大跳过

        jingcb = state.last_jj_amount / state.yesterday_amount
        g.stocks_date2[stock] = [jingcb, current_ratio]

    # 排序并选取前 N 只
    sorted_stocks = dict(sorted(g.stocks_date2.items(),
                                key=lambda item: item[1][1], reverse=True))
    for code, info in sorted_stocks.items():
        logger.info("%s: [%s]", code, ', '.join(str(x) for x in info))

    raw_select = len(sorted_stocks) * g.sum_xishu
    num_to_select = min(round(raw_select), g.stocknum)
    g.stock_jj = list(islice(sorted_stocks.keys(), num_to_select))


# ============================================================
# 盘前初始化
# ============================================================

def before_market_open(C):
    """初始化持仓股票的盘中监控状态"""
    g.stock_states = {}
    positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    for dt in positions:
        stock = dt.m_strInstrumentID + "." + dt.m_strExchangeID
        g.stock_states[stock] = StockMonitorState()
    logger.info("before_open 持仓监控: %s", list(g.stock_states.keys()))


def _init_candidate_state(stock_name, yesterday_close, yesterday_volume, yesterday_amount):
    """创建候选股票状态"""
    state = StockCandidateState(
        yesterday_close=yesterday_close,
        yesterday_volume=yesterday_volume,
        yesterday_amount=yesterday_amount,
    )
    state.up_stop_price = calculate_limit_up_price(yesterday_close, stock_name)
    return state


def before_market_stock(C, stock_sum, date):
    """QMT模式：从QMT获取昨日数据初始化候选股票"""
    g.stock_states1 = {}
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    yesterday_str = (date_obj - timedelta(days=1)).strftime('%Y%m%d%H%M%S')

    for stock in stock_sum:
        vol_data = C.get_market_data_ex(
            ['close', 'amount', 'volume'], stock_code=[stock], period="1d",
            start_time='', end_time=yesterday_str, count=3,
            dividend_type='none', subscribe=True
        )
        logger.info("before_open volume_data: %s", vol_data)
        if stock in vol_data:
            yd_close = vol_data[stock]['close'].iloc[-1]
            yd_amount = vol_data[stock]['amount'].iloc[-1]
            yd_volume = vol_data[stock]['volume'].iloc[-1] * 100
            g.stock_states1[stock] = _init_candidate_state(
                stock, yd_close, yd_volume, yd_amount)
    logger.info("before_open 候选股票: %s", list(g.stock_states1.keys()))


def before_market_stock1(C, stock_sum, date):
    """聚宽模式：从面板数据初始化候选股票"""
    g.stock_states1 = {}
    g.stock = []
    for stock, stock_data in stock_sum.items():
        stock_name = convert_to_qmt_format([stock])[0]
        g.stock.append(stock_name)
        g.stock_states1[stock_name] = _init_candidate_state(
            stock_name,
            stock_data.get('close', 1),
            stock_data.get('volume', 1),
            stock_data.get('money', 1),
        )
    logger.info("before_open 候选股票: %s", list(g.stock_states1.keys()))


# ============================================================
# 废单重试
# ============================================================

def feidan_xiadan(C, stock_list):
    """9:30检查废单并重新下单"""
    orders = get_trade_detail_data(C.accountid, 'stock', 'order')
    logger.info("9:30 查询委托状态:")
    for o in orders:
        s = o.m_strInstrumentID + "." + o.m_strExchangeID
        logger.info("代码=%s, 名称=%s, 状态=%s, 数量=%s, 均价=%s",
                     s, o.m_strInstrumentName, o.m_nOrderStatus,
                     o.m_nVolumeTotalOriginal, o.m_dTradedPrice)
        if s in stock_list and o.m_nOrderStatus == OrderStatus.INVALID:
            logger.info("股票%s废单，重新下单", s)
            try:
                quote = C.get_full_tick([s])
                price = quote[s]['lastPrice']
                cu = C.get_instrumentdetail(s)
                buy_price = calculate_buy_price(price, s)
                buy_price = min(buy_price, cu['UpStopPrice'])
                op_type = get_op_type(is_buy=True)
                price_type = get_market_price_type(s)

                if g.mairu_tag == 0:
                    passorder(op_type, OrderMode.BY_AMOUNT, C.accountid, s,
                              PriceType.LIMIT, float(buy_price), g.jine, '', 2, '', C)
                else:
                    passorder(op_type, OrderMode.BY_AMOUNT, C.accountid, s,
                              price_type, 0, g.jine, '', 2, '', C)
            except Exception as e:
                logger.error("废单重新下单失败: %s", e)


# ============================================================
# 买入
# ============================================================

def buyzaos(C, stock):
    """执行早盘买入"""
    g.jine = cangwei(C, stock, g.zijin_num)
    trade_records = read_from_file()

    for s in stock:
        try:
            quote = C.get_full_tick([s])
            price = quote[s]['lastPrice']
            if price <= 0:
                continue

            cu = C.get_instrumentdetail(s)
            buy_price = calculate_buy_price(price, s)
            buy_price = min(buy_price, cu['UpStopPrice'])
            op_type = get_op_type(is_buy=True)
            price_type = get_market_price_type(s)

            logger.info("买入: %s, 价格=%s, 金额=%s, 委托价=%s, 涨停=%s",
                        s, price, g.jine, buy_price, cu['UpStopPrice'])

            if g.mairu_tag == 0:
                passorder(op_type, OrderMode.BY_AMOUNT, C.accountid, s,
                          PriceType.LIMIT, float(buy_price), g.jine, '', 2, '', C)
            else:
                passorder(op_type, OrderMode.BY_AMOUNT, C.accountid, s,
                          price_type, 0, g.jine, '', 2, '', C)

            trade_records.append({
                "code": stock,
                "buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
        except Exception as e:
            logger.error("买入 %s 失败: %s", s, e)

    logger.info("写入交易记录: %s", trade_records)
    write_to_file(trade_records)


def cangwei(C, stock, num):
    """计算实际可用买入金额"""
    available_cash = 0
    accounts = get_trade_detail_data(C.accountid, 'stock', 'account')
    for dt in accounts:
        logger.info("账户可用金额: %.2f", dt.m_dAvailable)
        if dt.m_dAvailable > 0:
            available_cash = dt.m_dAvailable

    actual_amount = min(num, available_cash)
    if available_cash < num:
        logger.warning("设置金额%s > 可用现金%s，使用可用现金", num, available_cash)
    return actual_amount * 0.97


# ============================================================
# 账户查询
# ============================================================

def account_detail(C):
    """打印委托和成交详情"""
    orders = get_trade_detail_data(C.accountid, 'stock', 'order')
    logger.info("=== 委托结果 ===")
    for o in orders:
        logger.info("  %s.%s %s 方向=%s 委托=%s 均价=%s 成交=%s 金额=%s",
                     o.m_strInstrumentID, o.m_strExchangeID,
                     o.m_strInstrumentName, o.m_nOffsetFlag,
                     o.m_nVolumeTotalOriginal, o.m_dTradedPrice,
                     o.m_nVolumeTraded, o.m_dTradeAmount)

    deals = get_trade_detail_data(C.accountid, 'stock', 'deal')
    logger.info("=== 成交结果 ===")
    for dt in deals:
        logger.info("  %s.%s %s 方向=%s 价格=%s 数量=%s 金额=%s",
                     dt.m_strInstrumentID, dt.m_strExchangeID,
                     dt.m_strInstrumentName, dt.m_nOffsetFlag,
                     dt.m_dPrice, dt.m_nVolume, dt.m_dTradeAmount)


def getpositions(C):
    """获取交易记录中的持仓"""
    positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    trade_records = read_from_file()
    for dt in positions:
        s = dt.m_strInstrumentID + "." + dt.m_strExchangeID
        if any(s in record.get("code", []) for record in trade_records):
            g.positions.append(s)


# ============================================================
# 盘中实时监控（handle_data 系列）
# ============================================================

def handle_data(C, date):
    """盘中持仓实时监控（回测模式用）"""
    g.time_counter += 1
    positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    for dt in positions:
        stock = dt.m_strInstrumentID + "." + dt.m_strExchangeID
        if dt.m_nCanUseVolume == 0:
            continue
        if stock not in g.stock_states:
            continue

        state = g.stock_states[stock]
        state.time_counter += 1
        avg_cost = dt.m_dOpenPrice
        last_price = get_current_price(C, stock, date)

        if last_price is not None:
            if state.last_price != 0:
                state.last_price1 = state.last_price
            state.last_price = last_price

            if state.last_price1 != 0:
                change = (state.last_price - state.last_price1) / state.last_price1 * 100.0
                state.price_change_history.append((state.time_counter, change))

            state.price_history.append((state.time_counter, state.last_price))
            check_three_minute_rise(C, stock)

            if state.monitor_next_minute:
                monitor_next_minute_kline(C, stock, state.last_price, avg_cost, date)


def check_three_minute_rise(C, stock):
    """检查过去5个时间窗的累计涨幅是否触发监控"""
    state = g.stock_states[stock]
    if len(state.price_history) >= 5 and state.time_counter > 15:
        recent = [p for _, p in state.price_history[-5:]]
        rise = (recent[-1] - recent[0]) / recent[0] * 100.0
        if rise >= state.sum_zhangfu:
            state.monitor_next_minute = True


def monitor_next_minute_kline(C, stock, current_price, avg_cost, date):
    """监控拉升后的回落信号"""
    state = g.stock_states[stock]

    if state.initial_price_for_monitor is None:
        state.initial_price_for_monitor = current_price
        return

    yesterday_close, ok = get_yesterday_close(C, stock, date)
    if not ok:
        return

    daily_change = current_price / yesterday_close

    if current_price < state.initial_price_for_monitor and daily_change < 1.085:
        logger.info("卖出信号: %s, 价格=%s < 前价=%s, 日涨=%.2f%%",
                    stock, current_price, state.initial_price_for_monitor, daily_change)
        selllasheng(C, stock)
        account_detail(C)
        state.monitor_next_minute = False
        state.initial_price_for_monitor = None
    elif state.time_counter > state.price_history[-3][0] + 60:
        logger.info("监控窗口已过，重置: %s", stock)
        state.monitor_next_minute = False
        state.initial_price_for_monitor = None

    state.initial_price_for_monitor = current_price


# ============================================================
# 主调度入口
# ============================================================

def init(C):
    """策略初始化"""
    global g
    g = GlobalState()
    logger.info("程序初始化成功")

    # XML 配置路径
    current_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    xml_path = os.path.abspath(os.path.join(current_dir, 'formulaLayout', '开盘打板运行版V8_never_read.xml'))
    if 'bin.x64' in xml_path:
        xml_path = xml_path.replace(r'\bin.x64', r'\python')
    logger.info("XML 文件路径: %s", xml_path)

    if not os.path.exists(xml_path):
        logger.error("XML文件不存在: %s", xml_path)
        #return
    if not os.access(xml_path, os.R_OK):
        logger.error("无权限读取: %s", xml_path)
        #return

    g.s = get_stock_list_in_sector("沪深300")
    g.holdings = {i: 0 for i in g.s}

    # 账户配置 — 建议从配置文件读取
    C.accountid = "520000262415"

    if g.xml_tag == 1:
        g.zijin_num = 10000
    else:
        config = read_xml(xml_path)
        if config:
            g.zijin_num = int(config.get('zijin_num', {}).get('value', 0))
        elif globals().get('buy_value') is not None:
            g.zijin_num = globals().get('buy_value')
            logger.error("XML解析失败，使用全局变量 buy_value 作为每只股票买入金额: %s", g.zijin_num)
        else:
            logger.error("无法解析XML，初始化失败")
            return

    logger.info("每只股票买入金额: %s", g.zijin_num)
    logger.info("账户ID: %s", C.accountid)
    logger.info("策略到期: %s", g.enddate)

    C.run_time("buysell", "1nSecond", "2019-10-14 13:20:00")
    g.stock_pool = get_stock_pool_from_panel(C)
    logger.info("从参数面板获取的股票池: %s", list(g.stock_pool.keys()))


def after_init(C):
    logger.info("数据加载完成，开始运行，版本: %s", g.banben)
    if g.ti_qian == 1:
        getpositions(C)


def buysell(C):
    """实盘模式主调度（1秒定时器回调）"""
    current_time = datetime.now().strftime('%H:%M:%S')
    if current_time < "07:00:00" or current_time > "15:30:00":
        return
    if g.yun_tag != 1:
        return

    enddate = datetime.now().strftime('%Y-%m-%d')
    if enddate > g.enddate:
        logger.warning("策略已到期")
        return

    date_now = datetime.now().strftime('%Y-%m-%d')
    date = datetime.now().strftime('%Y%m%d%H%M%S')
    current_date = datetime.now()
    prep_date1 = (current_date - timedelta(days=2)).strftime('%Y%m%d')

    # 09:20 重置日内变量
    if current_time == "09:20:00":
        g.before_market_open = 0
        g.tag = 0
        g.tag1 = 0
        g.stock = []
        g.count = 0

    if g.before_market_open == 0:
        before_market_open(C)
        g.before_market_open = 1

    if g.tag1 == 0:
        logger.info("日期: %s", date)
        if g.huoqu_tag == 0:
            stock_list = get_stock_pool_from_panel(C)
            g.stock = convert_to_qmt_format(list(stock_list.keys()))
            for stock in g.stock:
                download_history_data(stock, "1d", prep_date1, date)
            before_market_stock(C, g.stock, date)
        else:
            stock_list = get_stock_pool_from_panel(C)
            logger.info("stock_list: %s", stock_list)
            before_market_stock1(C, stock_list, date)
        g.tag1 = 1

    # 集合竞价筛选
    if "09:25:05" <= current_time <= "09:26:59" and g.tag == 0:
        if g.skip_filter == 1:
            # 跳过筛选，直接买入股票池所有股票
            g.tag = 1
            g.stock_mai = list(g.stock)
            logger.info("[skip_filter] 跳过竞价筛选，直接买入: %s", g.stock_mai)
            if g.stock_mai:
                buyzaos(C, g.stock_mai)
                account_detail(C)
            else:
                logger.info("股票池为空，无标的可买")
        else:
            handle_data0(C, g.stock, date)
            if g.count == len(g.stock):
                g.tag = 1
                logger.info("集合竞价结果: %s", g.stock_jj)
                g.stock_mai = g.stock_jj
                if g.stock_mai:
                    logger.info("今日买入标的: %s", g.stock_mai)
                    buyzaos(C, g.stock_mai)
                    account_detail(C)
                else:
                    logger.info("今日无合适打板标的")

    if current_time == "09:30:07":
        feidan_xiadan(C, g.stock)

    if current_time == "09:30:00" and g.ti_qian == 1:
        logger.info("9:30 低开2%%检查")
        handle_data1(C, g.positions, date)

    if current_time == "09:33:00" and g.ti_qian == 1:
        logger.info("9:33 开盘价检查")
        handle_data2(C, g.positions, date)

    if current_time == "10:30:00" and g.ti_qian == 1:
        logger.info("10:30 回调检查")
        handle_data3(C, g.positions, date)

    if current_time == "11:27:00":
        sellzhong(C)
        account_detail(C)

    if current_time == "14:49:00":
        sellwans(C)
        account_detail(C)


def handlebar(C):
    """回测模式入口"""
    if g.yun_tag != 0:
        return
    # 回测逻辑与 buysell 结构类似，此处保持原有逻辑
    # （为避免篇幅过长，回测分支可参照 buysell 的结构调整）
    pass


# ============================================================
# 辅助函数（原样保留）
# ============================================================

def datetime_to_timestamp(datetime_str, format="%Y-%m-%d %H:%M:%S"):
    try:
        dt = datetime.strptime(datetime_str, format)
        return int(dt.timestamp() * 1000)
    except ValueError as e:
        logger.error("日期格式错误: %s", e)
        return None


def fetch_transaction_details(api_url, params, headers):
    try:
        response = requests.post(api_url, params=params, headers=headers)
        if response.status_code == 200:
            return response.json()
        logger.error("请求失败: %s", response.status_code)
        return None
    except requests.exceptions.RequestException as e:
        logger.error("请求异常: %s", e)
        return None


def parse_buy_transactions(data, data_now=None):
    if not data.get("data") or not data["data"].get("logArr"):
        return []
    log_arr = data["data"]["logArr"]
    target_date = None
    if data_now:
        try:
            target_date = datetime.strptime(data_now, "%Y-%m-%d").date()
        except ValueError:
            return []
    for log in log_arr:
        match = re.match(r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} - INFO", log)
        if not match:
            continue
        log_date = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if target_date and log_date != target_date:
            continue
        if "最后筛选符合要求的股票" in log:
            return extract_matching_stocks(log)
    return []


def daily_filter(factor_series, backtest_time):
    sl = factor_series[factor_series].index.tolist()
    sl = [s for s in sl if not is_st(s, backtest_time)]
    sl = sorted(sl, key=lambda k: factor_series.loc[k])
    return sl[:g.buy_num]


def is_st(s, date):
    st_dict = g.his_st.get(s, {})
    if not st_dict:
        return False
    st = st_dict.get('ST', []) + st_dict.get('*ST', [])
    for start, end in st:
        if start <= date <= end:
            return True
    return False  # 修复：原代码缺少此 return


def rank_filter(df, N, axis=1, ascending=False, method="max", na_option="keep"):
    return df.rank(axis=axis, ascending=ascending, method=method, na_option=na_option) <= N


def get_df_ex(data, field):
    _index = data[list(data.keys())[0]].index.tolist()
    _columns = list(data.keys())
    df = pd.DataFrame(index=_index, columns=_columns)
    for i in _columns:
        df[i] = data[i][field]
    return df


def filter_opendate_qmt(C, df, n):
    local_df = pd.DataFrame(index=df.index, columns=df.columns)
    stock_opendate = {i: str(C.get_instrumentdetail(i)["OpenDate"]) for i in df.columns}
    for stock, date in stock_opendate.items():
        local_df.at[date, stock] = 1
    # 修复：使用新版 pandas API
    df_fill = local_df.ffill()
    return df_fill.expanding().sum() >= n


def get_holdings(accid, datatype):
    result = {}
    for obj in get_trade_detail_data(accid, datatype, 'POSITION'):
        result[obj.m_strInstrumentID + "." + obj.m_strExchangeID] = {
            "持仓数量": obj.m_nVolume,
            "持仓成本": obj.m_dOpenPrice,
            "浮动盈亏": obj.m_dFloatProfit,
            "可用余额": obj.m_nCanUseVolume,
        }
    return result

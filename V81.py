# coding:gbk
import pandas as pd
import numpy as np
import requests
import json
import re
from datetime import datetime, time, timedelta
from time import sleep
import xml.etree.ElementTree as ET
import os
import inspect
import ast
import math
import pytz
from itertools import islice
import sys
import ctypes

# ===================== 修复DLL加载问题 - 关键配置 =====================
# 添加QMT安装目录到系统路径（根据你的实际路径修改）
qmt_path = r"D:\国信iquant\国信iQuant策略交易平台"
sys.path.append(qmt_path)
sys.path.append(os.path.join(qmt_path, "python"))
sys.path.append(os.path.join(qmt_path, "bin.x64"))

# 设置DLL搜索路径
ctypes.windll.kernel32.SetDllDirectoryW(os.path.join(qmt_path, "bin.x64"))

# 新增QMT数据接口导入（增加异常处理）
try:
    import xtquant.xtdata as xtdata
    import xtquant.xttrader as xttrader
    XTQUANT_IMPORTED = True
except ImportError as e:
    print(f"导入xtquant失败: {e}")
    print("请检查QMT客户端是否安装正确，或运行QMT后再启动策略")
    XTQUANT_IMPORTED = False

# ===================== 全局变量初始化 =====================
class G():
    pass

g = G()

# ===================== 修复：行情服务连接 + 重试机制 =====================
def init_xtdata():
    """初始化行情服务，增加重试和异常处理"""
    if not XTQUANT_IMPORTED:
        print("xtquant未成功导入，无法初始化行情服务")
        return False
    
    max_retry = 5  # 最大重试次数
    retry_interval = 2  # 重试间隔（秒）
    for i in range(max_retry):
        try:
            # 先检查客户端连接状态
            if not xtdata.is_connected():
                print(f"第{i+1}次尝试连接行情服务...")
                xtdata.connect()  # 主动连接行情服务
            # 下载板块数据（核心初始化）
            xtdata.download_sector_data()
            print("行情服务初始化成功！")
            return True
        except Exception as e:
            print(f"初始化行情服务失败（第{i+1}次）：{str(e)}")
            if i < max_retry - 1:
                sleep(retry_interval)
    print("多次重试后仍无法连接行情服务，请检查QMT客户端登录状态！")
    return False

# 初始化QMT数据接口（修复后）
g_xtdata_init_success = init_xtdata() if XTQUANT_IMPORTED else False

# ===================== 核心选股函数 =====================
def select_stocks_by_9_conditions():
    """
    9条件选股核心函数
    返回：
    1. selected_stock_list: 符合条件的股票代码列表（.SH/.SZ格式）
    2. selected_stock_dict: 适配before_market_stock1的字典（close/volume/money字段）
    """
    # 新增：如果行情服务未初始化成功，直接返回空
    if not g_xtdata_init_success:
        print("行情服务未初始化成功，跳过选股！")
        return [], {}
    
    # 步骤1：筛选沪深A股主板+非ST股
    all_stocks = xtdata.get_stock_list_in_sector('沪深A股')
    # 主板股票过滤：沪市60开头，深市000/001开头
    main_board_stocks = [
        stock for stock in all_stocks
        if (stock.startswith('60') or stock.startswith('000') or stock.startswith('001'))
    ]
    # 过滤ST/*ST股票
    non_st_stocks = []
    for stock in main_board_stocks:
        try:
            stock_info = xtdata.get_instrument_detail(stock)
            if 'ST' not in stock_info['instrument_name'] and '*ST' not in stock_info['instrument_name']:
                non_st_stocks.append(stock)
        except:
            continue
    print(f"主板非ST股票总数：{len(non_st_stocks)}")

    # 最终选股结果
    selected_stock_list = []
    selected_stock_dict = {}  # 适配before_market_stock1的格式

    # 步骤2：逐只校验9个核心条件
    for stock in non_st_stocks:
        try:
            # 获取最近30天日线数据
            hist_data = xtdata.get_market_data_ex(
                stock_list=[stock],
                period='1d',
                count=30,
                fields=['close', 'open', 'high', 'low', 'turnover', 'total_value', 'total_vol', 'amount']
            )
            df = hist_data[stock]
            if len(df) < 20:  # 数据不足跳过
                continue
            
            # 关键数据提取
            # 今日数据
            today_open = df.iloc[-1]['open'] if not pd.isna(df.iloc[-1]['open']) else 0
            # 前日数据（核心校验）
            pre1_close = df.iloc[-2]['close']
            pre1_open = df.iloc[-2]['open']
            pre1_high = df.iloc[-2]['high']
            pre1_low = df.iloc[-2]['low']
            pre1_turnover = df.iloc[-2]['turnover']  # 换手率（小数）
            pre1_total_value = df.iloc[-2]['total_value']  # 总市值（元）
            pre1_total_vol = df.iloc[-2]['total_vol']  # 成交额（元）
            pre1_amount = df.iloc[-2]['amount']  # 成交量（手）
            # 前前日数据
            pre2_close = df.iloc[-3]['close'] if len(df)>=3 else 0
            
            # 条件1：前日市值10亿-500亿
            market_cap_min = 10 * 10**8
            market_cap_max = 500 * 10**8
            if not (market_cap_min <= pre1_total_value <= market_cap_max):
                continue
            
            # 条件2：前日换手率5%-50%
            if not (0.05 < pre1_turnover < 0.5):
                continue
            
            # 条件3：前日成交额1亿以上
            if pre1_total_vol < 1 * 10**8:
                continue
            
            # 条件4：前日5/10/20日均线多头排列
            df['ma5'] = df['close'].rolling(window=5).mean()
            df['ma10'] = df['close'].rolling(window=10).mean()
            df['ma20'] = df['close'].rolling(window=20).mean()
            pre1_ma5 = df.iloc[-2]['ma5']
            pre1_ma10 = df.iloc[-2]['ma10']
            pre1_ma20 = df.iloc[-2]['ma20']
            if not (pre1_ma5 > pre1_ma10 > pre1_ma20):
                continue
            
            # 条件5：前日10/20日均线抬头向上
            pre2_ma10 = df.iloc[-3]['ma10'] if len(df)>=3 else 0
            pre2_ma20 = df.iloc[-3]['ma20'] if len(df)>=3 else 0
            if not (pre1_ma10 > pre2_ma10 and pre1_ma20 > pre2_ma20):
                continue
            
            # 条件6：前日涨停（非一字板，首板/2连板）
            pre2_close = df.iloc[-3]['close'] if len(df)>=3 else 0
            limit_up_price = round(pre2_close * 1.1, 2)  # 涨停价（10%）
            if pre1_open >= limit_up_price:  # 排除一字板
                continue
            if abs(pre1_close - limit_up_price) > 0.01:  # 验证涨停
                continue
            
            # 条件7：今日开盘价 < 前日最高价
            if today_open >= pre1_high or today_open == 0:
                continue
            
            # 条件8：前日K线实体 > 下影线
            k_body = abs(pre1_close - pre1_open)
            k_lower_shadow = min(pre1_open, pre1_close) - pre1_low
            if k_body <= k_lower_shadow or k_lower_shadow < 0:
                continue
            
            # 所有条件满足，加入结果
            if stock.startswith('60'):
                qmt_code = f"{stock}.SH"
            else:
                qmt_code = f"{stock}.SZ"
            selected_stock_list.append(qmt_code)
            selected_stock_dict[qmt_code] = {
                'close': pre1_close,
                'volume': pre1_amount * 100,  # 成交量（股）
                'money': pre1_total_vol  # 成交额（元）
            }
            
        except Exception as e:
            print(f"处理股票{stock}出错：{str(e)}")
            continue

    print(f"\n符合9条件的股票数量：{len(selected_stock_list)}")
    print(f"选股结果：{selected_stock_list}")
    return selected_stock_list, selected_stock_dict

# ===================== 交易相关函数 =====================
def feidan_xiadan(C,stock_list):
    """废单重新下单"""
    try:
        orders = get_trade_detail_data(C.accountid, 'stock', 'order')
        print('9点30分查询股票委托状态：')
        for o in orders:
            s = o.m_strInstrumentID + "." + o.m_strExchangeID
            print(f'股票代码: {o.m_strInstrumentID}, 市场类型: {o.m_strExchangeID}, 证券名称: {o.m_strInstrumentName}, 委托状态: {o.m_nOrderStatus}',
                  f'委托数量: {o.m_nVolumeTotalOriginal}, 成交均价: {o.m_dTradedPrice}, 成交数量: {o.m_nVolumeTraded}, 成交金额:{o.m_dTradeAmount}')
            if s in stock_list and o.m_nOrderStatus == 57:
                print(f"股票{s}当前委托是废单，重新下单！")
                quoute = C.get_full_tick([s])
                print(quoute)
                price = quoute[s]['lastPrice']
                cu = C.get_instrumentdetail(s)
                pricemai = calculate_buy_price(price, s)
                if pricemai > cu['UpStopPrice']:
                    pricemai = cu['UpStopPrice']
                print(f"股票的价格 {price} 买入的金额 {g.jine} 买入的价格 {pricemai} 当日涨停价 {cu['UpStopPrice']}")
                stock_type = determine_stock_type(s)
                mairu_type = 44  # 市价买入
                opType = 33 if g.opType == 1 else 23  # 33-融资买入 23-普通买入
                
                try:
                    if g.mairu_tag == 0:
                        # 限价委托
                        passorder(opType, 1102, C.accountid, s, 11, float(pricemai), g.jine, '', 2, '', C)
                    else:
                        # 市价委托
                        passorder(opType, 1102, C.accountid, s, mairu_type, 0, g.jine, '', 2, '', C)
                except Exception as e:
                    print(f"下单失败: {e}")
    except Exception as e:
        print(f"废单处理失败: {e}")

def buysell(C):
    """核心交易逻辑"""
    try:
        current_time = datetime.now().strftime('%H:%M:%S')
        if current_time < "07:00:00" or current_time > "15:30:00":
            return

        if g.yun_tag != 1:
            return
        
        # 策略到期检查
        enddate = datetime.now().strftime('%Y-%m-%d')
        if enddate > g.enddate:
            print("你的策略已到期，请联系管理员进行续费。")
            return
        
        # 时间格式化
        if g.yun_tag == 0:
            d = C.barpos
            date_now = timetag_to_datetime(C.get_bar_timetag(d), '%Y-%m-%d')
            date_now1 = timetag_to_datetime(C.get_bar_timetag(d), '%Y%m%d')
            date = timetag_to_datetime(C.get_bar_timetag(d), '%Y%m%d%H%M%S')
            current_time = timetag_to_datetime(C.get_bar_timetag(d), '%H:%M:%S')
        else:
            date_now = datetime.now().strftime('%Y-%m-%d')
            date_now1 = datetime.now().strftime('%Y%m%d')
            current_date = datetime.now()
            previous_date = current_date - timedelta(days=1)
            prep_date = current_date - timedelta(days=2)
            prep_date1 = prep_date.strftime('%Y%m%d')
            previous_date1 = previous_date.strftime('%Y%m%d')
            date = datetime.now().strftime('%Y%m%d%H%M%S')
            current_time = datetime.now().strftime('%H:%M:%S')

        # 9:20初始化
        if current_time == "09:20:00":
            g.before_market_open = 0
            g.tag = 0
            g.tag1 = 0
            g.stock = []
            g.count = 0

        # 盘前初始化
        if g.before_market_open == 0:
            before_market_open(C)
            g.before_market_open = 1

        # 选股逻辑
        if g.tag1 == 0:
            print('handlebar日期', date)
            mid_time1 = ' 05:55:00'
            end_times1 = ' 06:05:00'
            g.start = date_now + mid_time1
            g.end = date_now + end_times1
            
            # 核心替换：调用9条件选股函数
            stock_list, stock_dict = select_stocks_by_9_conditions()
            
            if g.huoqu_tag == 0:
                print('选股结果列表:', stock_list)
                for stock in stock_list:
                    g.stock.append(stock)
                for stock in g.stock:
                    download_history_data(stock, "1d", prep_date1, date)
                before_market_stock(C, g.stock, date)
            else:
                print('选股结果字典:', stock_dict)
                before_market_stock1(C, stock_dict, date)
            g.tag1 = 1

        # 9:25集合竞价处理
        if current_time >= "09:25:05" and current_time <= "09:26:59" and g.tag == 0:
            handle_data0(C, g.stock, date)
            if g.count == len(g.stock):
                g.tag = 1
                print(f"9点25分集合竞价为：{g.stock_jj}")
                g.stock_mai = g.stock_jj
                if len(g.stock_mai) > 0:
                    print("今天买入的标的:", g.stock_mai)
                    print("执行买入任务，当前时间为:", date)
                    buyzaos(C, g.stock_mai)
                    account_detail(C)
                else:
                    print("今日没有合适的打板标的，请耐心等待!")

        # 9:30废单处理
        if current_time == "09:30:07":
            feidan_xiadan(C, g.stock)

        # 提前卖出检查
        if g.ti_qian == 1:
            if current_time == "09:30:00":
                print("9点30分开盘低开2%检查")
                handle_data1(C, g.positions, date)
            if current_time == "09:33:00":
                print("9点33分开盘价检查")
                handle_data2(C, g.positions, date)
            if current_time == "10:30:00":
                print("10点30分最高点后回调大于1.5%检查")
                handle_data3(C, g.positions, date)

        # 中午卖出
        if current_time == "11:27:00":
            sellzhong(C)
            account_detail(C)
            
        # 尾盘卖出
        if current_time == "14:49:00":
            sellwans(C)
            account_detail(C)
    except Exception as e:
        print(f"交易主逻辑执行失败: {e}")

def order_shares_num(C):
    """测试下单函数"""
    try:
        order_id = order_shares('002852.SZ', 100, C, C.accountid)
        print(f"订单ID: {order_id}")
    except Exception as e:
        print(f"测试下单失败: {e}")

def account_detail(C):
    """查询账户详情"""
    try:
        orders = get_trade_detail_data(C.accountid, 'stock', 'order')
        print('查询委托结果：')
        for o in orders:
            print(f'股票代码: {o.m_strInstrumentID}, 市场类型: {o.m_strExchangeID}, 证券名称: {o.m_strInstrumentName}, 买卖方向: {o.m_nOffsetFlag}',
                  f'委托数量: {o.m_nVolumeTotalOriginal}, 成交均价: {o.m_dTradedPrice}, 成交数量: {o.m_nVolumeTraded}, 成交金额:{o.m_dTradeAmount}')

        deals = get_trade_detail_data(C.accountid, 'stock', 'deal')
        print('查询成交结果：')
        for dt in deals:
            print(f'股票代码: {dt.m_strInstrumentID}, 市场类型: {dt.m_strExchangeID}, 证券名称: {dt.m_strInstrumentName}, 买卖方向: {dt.m_nOffsetFlag}', 
                  f'成交价格: {dt.m_dPrice}, 成交数量: {dt.m_nVolume}, 成交金额: {dt.m_dTradeAmount}')
    except Exception as e:
        print(f"查询账户详情失败: {e}")

def sellzhong(C):
    """午盘卖出"""
    try:
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        print(f"读取文件内的股票 {trade_records}")
        
        for dt in positions:
            s = dt.m_strInstrumentID + "." + dt.m_strExchangeID
            if not any(s in record["code"] for record in trade_records):
                print(f"股票 {s} 不在交易记录中，跳过卖出操作")
                continue

            cu = C.get_instrumentdetail(s)
            quoute = C.get_full_tick([s])
            price = quoute[s]['lastPrice']
            pricemai = round((price - 0.07), 2)
            
            if pricemai < cu['DownStopPrice']:
                pricemai = cu['DownStopPrice']
                
            stock_type = determine_stock_type(s)
            mairu_type = 42 if stock_type == 0 else 46  # 卖出类型
            opType = 34 if g.opType == 1 else 24  # 卖出方向
            
            if ((dt.m_nCanUseVolume != 0) and (price > dt.m_dOpenPrice) and (price < cu['UpStopPrice'])):
                print(f'卖出股票: {s}')
                print(f"股票11点30的价格 {price} 卖出价格 {pricemai} 股票的代码 {dt.m_strInstrumentID} 涨停价 {cu['UpStopPrice']} 跌停价 {cu['DownStopPrice']}")
                passorder(opType, 1101, C.accountid, s, mairu_type, 0, dt.m_nCanUseVolume, '', 2, '', C)
    except Exception as e:
        print(f"午盘卖出失败: {e}")

def sellwans(C):
    """尾盘卖出"""
    try:
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        print(f"读取文件内的股票 {trade_records}")
        
        for dt in positions:
            s = dt.m_strInstrumentID + "." + dt.m_strExchangeID
            if not any(s in record["code"] for record in trade_records):
                print(f"股票 {s} 不在交易记录中，跳过卖出操作")
                continue

            cu = C.get_instrumentdetail(s)
            quoute = C.get_full_tick([s])
            price = quoute[s]['lastPrice']
            pricemai = round((price - 0.07), 2)
            
            if pricemai < cu['DownStopPrice']:
                pricemai = cu['DownStopPrice']
                
            stock_type = determine_stock_type(s)
            mairu_type = 44  # 市价卖出
            opType = 34 if g.opType == 1 else 24  # 卖出方向
            
            print("mairu_type的值", mairu_type)
            if ((dt.m_nCanUseVolume != 0) and (price < cu['UpStopPrice'])):
                print(f'卖出股票: {s}')
                print(f"股票14点55的价格 {price} 卖出价格 {pricemai} 股票的代码 {dt.m_strInstrumentID} 涨停价 {cu['UpStopPrice']} 跌停价 {cu['DownStopPrice']}")
                passorder(opType, 1101, C.accountid, s, mairu_type, 0, dt.m_nCanUseVolume, '', 2, '', C)
    except Exception as e:
        print(f"尾盘卖出失败: {e}")

# ===================== 配置文件处理 =====================
def read_xml(file_path):
    """读取XML配置文件"""
    try:
        if not os.path.exists(file_path):
            print(f"文件 {file_path} 不存在")
            return None
        if not os.access(file_path, os.R_OK):
            print(f"没有权限读取文件 {file_path}")
            return None

        tree = ET.parse(file_path)
        root = tree.getroot()
        config_data = {}

        for control in root.findall('control'):
            for variable in control.findall('variable'):
                for item in variable.findall('item'):
                    item_data = {
                        'position': item.get('position', ''),
                        'bind': item.get('bind', ''),
                        'value': item.get('value', ''),
                        'note': item.get('note', ''),
                        'name': item.get('name', ''),
                        'type': item.get('type', '')
                    }
                    config_data[item.get('bind')] = item_data
        return config_data
    except FileNotFoundError:
        print(f"错误: 文件 {file_path} 不存在")
    except PermissionError:
        print(f"错误: 无权限访问文件 {file_path}")
    except ET.ParseError as e:
        print(f"错误: XML 文件格式错误，详细信息: {e}")
    except Exception as e:
        print(f"未知错误: {e}")
    return None

# ===================== 初始化函数 =====================
def init(C):
    """程序初始化"""
    print("程序初始化开始")
    
    # 基础配置
    g.banben = 'V2.7'
    g.cese = 1
    
    # 获取配置文件路径
    current_working_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    relative_path = os.path.join('formulaLayout', '开盘打板运行版V81.xml')
    xml_file_path = os.path.abspath(os.path.join(current_working_dir, relative_path))
    
    if 'bin.x64' in xml_file_path:
        xml_file_path = xml_file_path.replace(r'\bin.x64', r'\python')
        print(f"修正后的 XML 文件路径: {xml_file_path}")
    
    # 初始化全局变量
    g.his_st = {}
    g.s = xtdata.get_stock_list_in_sector("沪深300") if g_xtdata_init_success else []
    g.stock = []
    g.positions = []
    g.stocks_date2 = {}
    g.tag = 0
    g.tag1 = 0
    g.jine = 0
    g.sum_xishu = 0.3
    g.tag_fenzhong = 0
    g.result = None
    g.stock_states = {}
    g.stock_states1 = {}
    g.day = 0
    g.count = 0
    g.stocknum = 5
    g.start = '2025-02-15 22:14:47'
    g.end = '2025-02-15 22:14:48'
    g.time_counter = 0
    g.holdings = {i: 0 for i in g.s}
    g.weight = [0.1] * 10
    g.buypoint = {}
    g.money = 10000000
    g.mairu_tag = 1  # 0-限价委托 1-市价委托
    C.accountid = "520000262415"  # 请替换为你的实盘账户ID
    g.enddate = '2028-03-22'
    g.profit = 0
    g.opType = 0  # 0-普通账户 1-融资账户
    g.yun_tag = 1  # 0-回测 1-实盘运行
    g.ti_qian = 0  # 1-提前卖出
    g.before_market_open = 0
    g.before_market_stock = 0
    g.buy_num = 10
    g.per_money = 10000
    g.xml_tag = 0
    g.huoqu_tag = 1  # 固定为1，使用9条件选股
    
    # 读取配置
    if g.xml_tag == 1:
        g.zijin_num = 10000
    else:
        config_data = read_xml(xml_file_path)
        if config_data is not None:
            g.zijin_num = int(config_data.get('zijin_num', {}).get('value', 10000))
        else:
            g.zijin_num = 10000
    
    # 打印配置信息
    print(f"每个股票买入的资金: {g.zijin_num}")
    print(f"资金账户ID: {C.accountid}")
    print("当前市场温度：低（建议仓位控制在0~25%），要注意仓位管理！")
    print(f"策略到期时间为: {g.enddate}")
    
    # 启动定时任务
    C.run_time("buysell", "1nSecond", "2019-10-14 13:20:00")
    print("程序初始化成功")

def after_init(C):
    """初始化后处理"""
    print(f"程序加载数据成功，开始运行，当前版本: {g.banben}")
    if g.ti_qian == 1:
        getpositions(C)

# ===================== 盘前处理函数 =====================
def before_market_open(C):
    """盘前初始化"""
    g.stock_states = {}
    try:
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        for dt in positions:
            stock = dt.m_strInstrumentID + "." + dt.m_strExchangeID
            g.stock_states[stock] = {
                'price_history': [],
                'last_price': 0,
                'last_price1': 0,
                'price_change_history': [],
                'monitor_next_minute': False,
                'initial_price_for_monitor': None,
                'sum_zhangfu': 4.0,
                'time_counter': 0
            }
        print(f'before_open的g.stock_states：{g.stock_states}')
    except Exception as e:
        print(f"盘前初始化失败: {e}")

def before_market_stock(C, stock_sum, date):
    """盘前股票数据初始化"""
    limit_up_price = 0
    g.stock_states1 = {}
    for stock in stock_sum:
        g.stock_states1[stock] = {
            'price_history': [],
            'last_price': 0,
            'last_price1': 0,
            'UpStopPrice': 0,
            'KpStopPrice': 0,
            'yesterday_close': 1,
            'KP_Price': 0,
            'jj_tag': 0,
            'ZuigaoPrice': 0,
            'ZuidiPrice': 0,
            'last_jjprice': 1,
            'last_jjvolume': 1,
            'last_jjamount': 1,
            'yesterday_volume': 1,
            'yesterday_amount': 1,
            'last_price_kaip': 1,
            'last_volume_kaip': 1,
            'price_change_history': [],
            'monitor_next_minute': False,
            'initial_price_for_monitor': None,
            'sum_zhangfu': 9.5,
            'time_counter': 0,
            'mairu_tag': 0,
            'orderid': 0
        }
        try:
            date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
            yesterday_obj = date_obj - timedelta(days=1)
            yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
            volume_data = C.get_market_data_ex(['close','amount','volume'], 
                                              stock_code=[stock], 
                                              period="1d", 
                                              start_time='', 
                                              end_time=yesterday_str, 
                                              count=3, 
                                              dividend_type='none', 
                                              subscribe=True)
            
            if stock in volume_data:
                state = g.stock_states1[stock]
                close_prices = volume_data[stock]['close']
                close_amount = volume_data[stock]['amount']
                close_volume = volume_data[stock]['volume']
                state['yesterday_close'] = close_prices.iloc[-1]
                state['yesterday_amount'] = close_amount.iloc[-1]
                state['yesterday_volume'] = close_volume.iloc[-1]*100
                limit_up_price = calculate_limit_up_price(state['yesterday_close'], stock)
                state['UpStopPrice'] = limit_up_price
        except Exception as e:
            print(f"处理股票{stock}盘前数据失败: {e}")
    print(f'before_open的g.stock_states1：{g.stock_states1}')

def before_market_stock1(C, stock_sum, date):
    """盘前股票数据初始化（适配选股字典）"""
    limit_up_price = 0
    g.stock_states1 = {}
    g.stock = []
    for stock, stock_data in stock_sum.items():
        stock_name = stock
        g.stock.append(stock_name)
        yesterday_close = stock_data.get('close', 1)
        yesterday_volume = stock_data.get('volume', 1)
        yesterday_amount = stock_data.get('money', 1)
        
        g.stock_states1[stock_name] = {
            'price_history': [],
            'last_price': 0,
            'last_price1': 0,
            'UpStopPrice': 0,
            'KpStopPrice': 0,
            'yesterday_close': yesterday_close,
            'KP_Price': 0,
            'jj_tag': 0,
            'ZuigaoPrice': 0,
            'ZuidiPrice': 0,
            'last_jjprice': 1,
            'last_jjvolume': 1,
            'last_jjamount': 1,
            'yesterday_volume': yesterday_volume,
            'yesterday_amount': yesterday_amount,
            'last_price_kaip': 1,
            'last_volume_kaip': 1,
            'price_change_history': [],
            'monitor_next_minute': False,
            'initial_price_for_monitor': None,
            'sum_zhangfu': 9.5,
            'time_counter': 0,
            'mairu_tag': 0,
            'orderid': 0
        }
        state = g.stock_states1[stock_name]
        limit_up_price = calculate_limit_up_price(state['yesterday_close'], stock_name)
        state['UpStopPrice'] = limit_up_price
    print(f'before_open的g.stock_states1：{g.stock_states1}')

# ===================== 辅助计算函数 =====================
def calculate_limit_up_price(yesterday_close, stock_code):
    """计算涨停价"""
    try:
        if stock_code.startswith("68") or stock_code.startswith("30"):
            limit_up_percentage = 0.20  # 科创板/创业板20%
        elif stock_code.startswith("00") or stock_code.startswith("60"):
            if "ST" in stock_code or "*ST" in stock_code:
                limit_up_percentage = 0.05  # ST股5%
            else:
                limit_up_percentage = 0.10  # 主板10%
        else:
            limit_up_percentage = 0.10
        
        limit_up_price = round(yesterday_close * (1 + limit_up_percentage), 2)
        return limit_up_price
    except Exception as e:
        print(f"计算涨停价失败: {e}")
        return yesterday_close * 1.1

def calculate_buy_price(price, stock_code):
    """计算买入价格"""
    if price <= 0:
        raise ValueError("价格必须为正数")

    if stock_code.startswith(('60', '00')):
        if price <= 5:
            buy_price = price + 0.1
        else:
            buy_price = price * 1.015
    else:
        buy_price = price * 1.015

    return round(buy_price, 2)

def calculate_stock_quantity(jine, pricemai):
    """计算买入数量（按100股的整数倍）"""
    try:
        if not (isinstance(jine, (int, float)) and isinstance(pricemai, (int, float))):
            raise ValueError("jine 和 pricemai 必须是数字类型")

        if pricemai <= 0:
            raise ValueError("买入价格必须大于0")

        theoretical_max = jine / pricemai
        stock_sum = math.floor(theoretical_max / 100) * 100

        if stock_sum < 100:
            return 0

        return stock_sum
    except ValueError as e:
        print(f"计算买入数量错误: {e}")
        return 0

def determine_stock_type(stock_code):
    """判断股票类型"""
    if stock_code.endswith('.SH'):
        return 0
    elif stock_code.endswith('.SZ'):
        return 1
    else:
        raise ValueError(f"未知的股票代码后缀: {stock_code}")

# ===================== 买入卖出核心函数 =====================
def buyzaos(C, stock):
    """早盘买入"""
    try:
        g.jine = 0
        stock_sum = 0
        g.jine = cangwei(C, stock, g.zijin_num)
        trade_records = read_from_file()
        
        for s in stock:
            quoute = C.get_full_tick([s])
            print(quoute)
            price = quoute[s]['lastPrice']
            
            if price > 0:
                cu = C.get_instrumentdetail(s)
                pricemai = calculate_buy_price(price, s)
                
                if pricemai > cu['UpStopPrice']:
                    pricemai = cu['UpStopPrice']
                    
                print(f"股票的价格 {price} 买入的金额 {g.jine} 买入的价格 {pricemai} 当日涨停价 {cu['UpStopPrice']}")
                stock_sum = calculate_stock_quantity(g.jine, pricemai)
                stock_type = determine_stock_type(s)
                mairu_type = 44  # 市价买入
                opType = 33 if g.opType == 1 else 23  # 买入方向
                
                print("mairu_type的值", mairu_type)
                if g.mairu_tag == 0:
                    # 限价委托
                    passorder(opType, 1102, C.accountid, s, 11, float(pricemai), g.jine, '', 2, '', C)
                else:
                    # 市价委托
                    passorder(opType, 1102, C.accountid, s, mairu_type, 0, g.jine, '', 2, '', C)
                
                # 记录交易
                trade_records.append({
                    "code": s,
                    "buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })
        
        write_to_file(trade_records)
    except Exception as e:
        print(f"早盘买入失败: {e}")

def cangwei(C, stock, num):
    """计算仓位"""
    try:
        available_cash = 0
        accounts = get_trade_detail_data(C.accountid, 'stock', 'account')
        print('查询账号结果：')
        for dt in accounts:
            print(f'账户可用金额: {dt.m_dAvailable:.2f}')
            if dt.m_dAvailable > 0:
                available_cash = dt.m_dAvailable
        
        actual_amount = min(num, available_cash)
        
        if available_cash < num:
            print(f"警告：策略设置的金额{num}大于账户可用现金{available_cash}，将使用账户可用现金{available_cash}进行买入")
        
        value = actual_amount * 0.97  # 预留手续费
        return value
    except Exception as e:
        print(f"计算仓位失败: {e}")
        return num * 0.97

# ===================== 风控和监控函数 =====================
def handle_data(C, date):
    """实时数据处理"""
    try:
        g.time_counter += 1
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        
        for dt in positions:
            stock = dt.m_strInstrumentID + "." + dt.m_strExchangeID
            if dt.m_nCanUseVolume == 0:
                continue
                
            state = g.stock_states.get(stock, None)
            if not state:
                continue
                
            state['time_counter'] += 1
            avg_cost = dt.m_dOpenPrice
            
            # 获取最新价格
            if g.yun_tag == 0:
                volume_data = C.get_market_data_ex(['open'], stock_code=[stock], period=C.period, start_time=date, end_time=date, dividend_type='none')
                last_price = volume_data[stock]['open'][-1]
            else:
                quoute = C.get_full_tick([stock])
                last_price = quoute[stock]['lastPrice']

            if last_price is not None:
                if state['last_price'] != 0:
                    state['last_price1'] = state['last_price']
                state['last_price'] = last_price

                if state['last_price1'] != 0:
                    price_change = (state['last_price'] - state['last_price1']) / state['last_price1'] * 100.0
                    state['price_change_history'].append((state['time_counter'], price_change))

                state['price_history'].append((state['time_counter'], state['last_price']))
                check_three_minute_rise(C, stock)

                if state['monitor_next_minute']:
                    monitor_next_minute_kline(C, stock, state['last_price'], avg_cost, date)
                    print(f"monitor_next_minute_kline价格 {state['last_price']:.2f}")
    except Exception as e:
        print(f"实时数据处理失败: {e}")

def check_three_minute_rise(C, stock):
    """检查三分钟涨幅"""
    try:
        state = g.stock_states.get(stock, None)
        if not state:
            return
            
        cumulative_rise = 0
        if len(state['price_history']) >= 5:
            recent_prices = [price for _, price in state['price_history'][-5:]]
            initial_price = recent_prices[0]
            final_price = recent_prices[-1]
            cumulative_rise = (final_price - initial_price) / initial_price * 100.0

            if cumulative_rise >= state['sum_zhangfu'] and state['time_counter'] > 15:
                state['monitor_next_minute'] = True
    except Exception as e:
        print(f"检查涨幅失败: {e}")

def monitor_next_minute_kline(C, stock, current_price, avg_cost, date):
    """监控下一分钟K线"""
    try:
        state = g.stock_states.get(stock, None)
        if not state:
            return
            
        date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
        yesterday_obj = date_obj - timedelta(days=1)
        yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
        
        if state['initial_price_for_monitor'] is None:
            state['initial_price_for_monitor'] = current_price
            return

        volume_data = C.get_market_data_ex(['close'], stock_code=[stock], period="1d", start_time='', end_time=yesterday_str, count=2, dividend_type='none')
        if stock in volume_data:
            close_prices = volume_data[stock]['close']
            yesterday_close = close_prices.iloc[-1]
            dangrizhangfu = current_price / yesterday_close
        else:
            dangrizhangfu = 0

        if current_price < state['initial_price_for_monitor'] and dangrizhangfu < 1.085:
            print(f"时间：{date}，检测到卖出信号，当前价格 {current_price} 小于开盘价 {state['initial_price_for_monitor']}，执行卖出操作")
            selllasheng(C, stock)
            account_detail(C)
            state['monitor_next_minute'] = False
            state['initial_price_for_monitor'] = None
        elif state['time_counter'] > state['price_history'][-3][0] + 60:
            print(f"监控时间窗口已过，未检测到符合条件的K线，重置监控 {stock}")
            state['monitor_next_minute'] = False
            state['initial_price_for_monitor'] = None

        state['initial_price_for_monitor'] = current_price
    except Exception as e:
        print(f"监控K线失败: {e}")

# ===================== 提前卖出检查函数 =====================
def getpositions(C):
    """获取持仓"""
    try:
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        for dt in positions:
            s = dt.m_strInstrumentID + "." + dt.m_strExchangeID
            if any(s in record["code"] for record in trade_records):
                g.positions.append(s)
    except Exception as e:
        print(f"获取持仓失败: {e}")

def selllasheng(C, s):
    """拉升卖出"""
    try:
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        updated_trade_records = []
        
        for dt in positions:
            stock = dt.m_strInstrumentID + "." + dt.m_strExchangeID
            if stock != s:
                continue
                
            if not any(s in record["code"] for record in trade_records):
                print(f"股票 {s} 不在交易记录中，跳过卖出操作")
                continue

            cu = C.get_instrumentdetail(s)
            quoute = C.get_full_tick([s])
            price = quoute[s]['lastPrice']
            pricemai = round((price - 0.09), 2)
            
            if pricemai < cu['DownStopPrice']:
                pricemai = cu['DownStopPrice']
                
            if ((dt.m_nCanUseVolume != 0) and (price < cu['UpStopPrice'])):
                print(f'卖出股票: {s}')
                print(f"股票拉升的价格 {price} 卖出价格 {pricemai} 股票的代码 {dt.m_strInstrumentID} 涨停价 {cu['UpStopPrice']} 跌停价 {cu['DownStopPrice']}")
                order_target_value(s, 0, 'MARKET', C, C.accountid)
                
                # 更新交易记录
                for record in trade_records:
                    if s in record["code"]:
                        record["code"].remove(s)
                        if not record["code"]:
                            continue
                    updated_trade_records.append(record)
                
                if updated_trade_records != trade_records:
                    write_to_file(updated_trade_records)
    except Exception as e:
        print(f"拉升卖出失败: {e}")

def handle_data1(C, positions, date):
    """9:30低开2%检查"""
    try:
        date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
        yesterday_obj = date_obj - timedelta(days=1)
        yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
        
        for stock in positions:
            if g.yun_tag == 1:
                quoute = C.get_full_tick([stock])
                last_price = quoute[stock]['lastPrice']
            else:
                volume_data1 = C.get_market_data_ex(['open'], stock_code=[stock], period=C.period, start_time=date, end_time=date, dividend_type='none')
                last_price = volume_data1[stock]['open'][-1]

            volume_data = C.get_market_data_ex(['close'], stock_code=[stock], period="1d", start_time='', end_time=yesterday_str, count=2, dividend_type='none')
            if stock in volume_data:
                close_prices = volume_data[stock]['close']
                yesterday_close = close_prices.iloc[-1]
                dangrizhangfu = (last_price - yesterday_close) / yesterday_close * 100.0
            else:
                dangrizhangfu = 0
                
            if dangrizhangfu <= -2:
                selllasheng(C, stock)
                account_detail(C)
    except Exception as e:
        print(f"9:30检查失败: {e}")

def handle_data2(C, positions, date):
    """9:33开盘价检查"""
    try:
        date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
        yesterday_obj = date_obj - timedelta(days=1)
        yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
        
        for stock in positions:
            state = g.stock_states.get(stock, None)
            if not state:
                continue
                
            if g.yun_tag == 1:
                quoute = C.get_full_tick([stock])
                last_price = quoute[stock]['lastPrice']
            else:
                volume_data1 = C.get_market_data_ex(['open'], stock_code=[stock], period=C.period, start_time=date, end_time=date, dividend_type='none')
                last_price = volume_data1[stock]['open'][-1]

            volume_data = C.get_market_data_ex(['close'], stock_code=[stock], period="1d", start_time='', end_time=yesterday_str, count=2, dividend_type='none')
            if stock in volume_data:
                close_prices = volume_data[stock]['close']
                yesterday_close = close_prices.iloc[-1]
                dangrizhangfu = (last_price - yesterday_close) / yesterday_close * 100.0
            else:
                dangrizhangfu = 0
                
            if last_price < yesterday_close:
                selllasheng(C, stock)
                account_detail(C)
    except Exception as e:
        print(f"9:33检查失败: {e}")

def handle_data3(C, positions, date):
    """10:30回调检查"""
    try:
        date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
        yesterday_obj = date_obj - timedelta(days=1)
        yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
        
        for stock in positions:
            state = g.stock_states.get(stock, None)
            if not state:
                continue
                
            if g.yun_tag == 1:
                quoute = C.get_full_tick([stock])
                last_price = quoute[stock]['lastPrice']
                high = quoute[stock]['high']
            else:
                volume_data1 = C.get_market_data_ex(['open,high'], stock_code=[stock], period=C.period, start_time=date, end_time=date, dividend_type='none')
                last_price = volume_data1[stock]['open'][-1]
                high = volume_data1[stock]['high'][-1]

            volume_data = C.get_market_data_ex(['close'], stock_code=[stock], period="1d", start_time='', end_time=yesterday_str, count=2, dividend_type='none')
            if stock in volume_data:
                close_prices = volume_data[stock]['close']
                yesterday_close = close_prices.iloc[-1]
                dangrizhangfu = (last_price - high) / high * 100.0
            else:
                dangrizhangfu = 0
                
            if dangrizhangfu <= -1.5:
                selllasheng(C, stock)
                account_detail(C)
    except Exception as e:
        print(f"10:30检查失败: {e}")

# ===================== 回测相关函数 =====================
def handlebar(C):
    """回测处理函数"""
    try:
        if g.yun_tag != 0:
            return
            
        enddate = datetime.now().strftime('%Y-%m-%d')
        if enddate > g.enddate:
            print("你的策略已到期，请联系管理员进行续费。")
            return
            
        if g.yun_tag == 0:
            d = C.barpos
            date_now = timetag_to_datetime(C.get_bar_timetag(d), '%Y-%m-%d')
            date_now1 = timetag_to_datetime(C.get_bar_timetag(d), '%Y%m%d')
            date = timetag_to_datetime(C.get_bar_timetag(d), '%Y%m%d%H%M%S')
            current_time = timetag_to_datetime(C.get_bar_timetag(d), '%H:%M:%S')
        else:
            date_now = datetime.now().strftime('%Y-%m-%d')
            date_now1 = datetime.now().strftime('%Y%m%d')
            date = datetime.now().strftime('%Y%m%d%H%M%S')
            current_time = datetime.now().strftime('%H:%M:%S')

        if current_time <= "09:30:00":
            g.stock = []
            g.tag = 0

        if current_time == "09:30:00":
            g.before_market_open = 0

        if current_time == "09:31:00" and g.tag == 0:
            print('handlebar日期09:30:02', date)
            mid_time1 = ' 05:55:00'
            end_times1 = ' 06:05:00'
            date_now = datetime.now().strftime('%Y-%m-%d')
            g.start = date_now + mid_time1
            g.end = date_now + end_times1
            g.start = '2025-06-07 15:46:54'
            g.end = '2025-06-07 15:47:54'
            print(g.start)
            print(g.end)
            
            # 选股
            stock_list, stock_dict = select_stocks_by_9_conditions()
            
            if g.huoqu_tag == 0:
                print('stock_list的值', stock_list)
                for stock in stock_list:
                    g.stock.append(stock)
                g.stock = convert_to_qmt_format(g.stock)
                print('g.stock的值', g.stock)
                prep_date1 = (datetime.now() - timedelta(days=2)).strftime('%Y%m%d')
                for stock in g.stock:
                    download_history_data(stock, "1d", prep_date1, date)
                before_market_stock(C, g.stock, date)
            else:
                print('stock_list的值', stock_list)
                before_market_stock1(C, stock_dict, date)
                print('g.stock的值', g.stock)

        if current_time >= "09:32:50" and current_time <= "09:34:59" and g.tag == 0:
            handle_data0(C, g.stock, date)
            if g.count == len(g.stock):
                g.tag = 1
                print(f"9点25分集合竞价为：{g.stock_jj}")
                g.stock_mai = g.stock_jj
                g.stock_mai = ['000029.SZ', '000723.SZ']
                if len(g.stock_mai) > 0:
                    print("今天买入的标的:", g.stock_mai)
                    print("执行买入任务，当前时间为:", date)
                    buyzaos(C, g.stock_mai)
                    account_detail(C)
                else:
                    print("今日没有合适的打板标的，请耐心等待!")

        if g.before_market_open == 0:
            before_market_open(C)
            g.before_market_open = 1

        if current_time > "09:30:00":
            handle_data(C, date)

        # 提前卖出检查
        if g.ti_qian == 1:
            if current_time == "09:30:00":
                print("9点30分开盘低开2%检查")
                handle_data1(C, g.positions, date)
            if current_time == "09:33:00":
                print("9点33分开盘价检查")
                handle_data2(C, g.positions, date)
            if current_time == "10:30:00":
                print("10点30分最高点后回调大于1.5%检查")
                handle_data3(C, g.positions, date)

        # 卖出操作
        if current_time == "11:28:00":
            sellzhong(C)
            account_detail(C)
        if current_time == "14:49:00":
            sellwans(C)
            account_detail(C)
    except Exception as e:
        print(f"回测处理失败: {e}")

def handle_data0(C, positions, date):
    """集合竞价处理"""
    try:
        date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
        yesterday_obj = date_obj - timedelta(days=1)
        yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
        
        for stock in positions:
            state = g.stock_states1.get(stock, None)
            if not state:
                continue
                
            if state['jj_tag'] == 1:
                continue
                
            # 获取集合竞价数据
            if g.yun_tag == 1:
                quoute = C.get_full_tick([stock])
                state['last_jjprice'] = quoute[stock]['lastPrice']
                state['last_jjvolume'] = quoute[stock]['volume']
                state['last_jjamount'] = quoute[stock]['amount']
                timetag_str = quoute[stock]['timetag']
                formatted_date = f"{timetag_str[0:4]}-{timetag_str[4:6]}-{timetag_str[6:8]}"
                if formatted_date > g.enddate:
                    print("你的策略已到期，请联系管理员进行续费。")
                    return
            else:
                volume_data1 = C.get_market_data_ex([], stock_code=[stock], period=C.period, start_time=date, end_time=date, dividend_type='none')
                state['last_jjprice'] = volume_data1[stock]['open'][-1]
                state['last_jjvolume'] = volume_data1[stock]['volume'][-1]
                state['last_jjamount'] = volume_data1[stock]['amount'][-1]
                
            # 计算比率
            current_ratio = state['last_jjprice'] / state['yesterday_close']
            jingcb = state['last_jjamount'] / state['yesterday_amount'] if state['yesterday_amount'] != 0 else 0
            
            if state['last_jjprice'] == 0 or state['last_jjamount'] == 0:
                print(f"股票{stock}没有获取到数据,等待下一秒获取")
                continue
                
            g.count = g.count + 1
            state['jj_tag'] = 1

            if current_ratio >= 1.095:
                continue

            buylist1 = [jingcb, current_ratio]
            new_stocks1 = {stock: buylist1}
            g.stocks_date2.update(new_stocks1)

        # 排序选股
        stocks_date2 = dict(sorted(g.stocks_date2.items(), key=lambda item: item[1][1], reverse=True))
        for stock_code, info_list in stocks_date2.items():
            str_info_list = [str(item) for item in info_list]
            formatted_info = ', '.join(str_info_list)
            print(f"{stock_code}: [{formatted_info}]")
            
        # 计算选股数量
        raw_select = len(stocks_date2) * g.sum_xishu
        num_to_select = round(raw_select) 
        if num_to_select > g.stocknum:
            num_to_select = g.stocknum
            
        g.stock_jj = list(islice(stocks_date2.keys(), num_to_select))
    except Exception as e:
        print(f"集合竞价处理失败: {e}")

# ===================== 工具函数 =====================
def convert_string_to_stock_states(stock_states_str):
    """转换股票状态字符串"""
    try:
        stock_states_dict = json.loads(stock_states_str)
        return stock_states_dict
    except json.JSONDecodeError as e:
        print("JSON 解码错误:", e)
        return None

def daily_filter(factor_series, backtest_time):
    """日线过滤"""
    sl = factor_series[factor_series].index.tolist()
    sl = [s for s in sl if not is_st(s, backtest_time)]
    sl = sorted(sl, key=lambda k: factor_series.loc[k])
    return sl[:g.buy_num]

def is_st(s, date):
    """判断是否ST股"""
    st_dict = g.his_st.get(s, {})
    if not st_dict:
        return False
    else:
        st = st_dict.get('ST', []) + st_dict.get('*ST', [])
        for start, end in st:
            if start <= date <= end:
                return True
    return False

def rank_filter(df: pd.DataFrame, N: int, axis=1, ascending=False, method="max", na_option="keep") -> pd.DataFrame:
    """排名过滤"""
    _df = df.copy()
    _df = _df.rank(axis=axis, ascending=ascending, method=method, na_option=na_option)
    return _df <= N

def get_df_ex(data:dict, field:str) -> pd.DataFrame:
    """转换数据为DataFrame"""
    _index = data[list(data.keys())[0]].index.tolist()
    _columns = list(data.keys())
    df = pd.DataFrame(index=_index, columns=_columns)
    for i in _columns:
        df[i] = data[i][field]
    return df

def filter_opendate_qmt(C, df: pd.DataFrame, n: int) -> pd.DataFrame:
    """过滤上市日期"""
    local_df = pd.DataFrame(index=df.index, columns=df.columns)
    stock_list = df.columns
    stock_opendate = {i: str(C.get_instrumentdetail(i)["OpenDate"]) for i in stock_list}
    
    for stock, date in stock_opendate.items():
        local_df.at[date, stock] = 1
    
    df_fill = local_df.fillna(method="ffill")
    result = df_fill.expanding().sum() >= n
    return result

def get_holdings(accid, datatype):
    """获取持仓详情"""
    PositionInfo_dict = {}
    try:
        resultlist = get_trade_detail_data(accid, datatype, 'POSITION')
        for obj in resultlist:
            PositionInfo_dict[obj.m_strInstrumentID + "." + obj.m_strExchangeID] = {
                "持仓数量": obj.m_nVolume,
                "持仓成本": obj.m_dOpenPrice,
                "浮动盈亏": obj.m_dFloatProfit,
                "可用余额": obj.m_nCanUseVolume
            }
    except Exception as e:
        print(f"获取持仓详情失败: {e}")
    return PositionInfo_dict

# ===================== QMT内置函数适配 =====================
def timetag_to_datetime(timetag, fmt):
    """时间戳转换"""
    try:
        return datetime.fromtimestamp(timetag).strftime(fmt)
    except:
        return datetime.now().strftime(fmt)

def download_history_data(stock, period, start, end):
    """下载历史数据"""
    try:
        if XTQUANT_IMPORTED:
            xtdata.download_history_data(stock_list=[stock], period=period, start_time=start, end_time=end)
    except Exception as e:
        print(f"下载历史数据失败: {e}")

def convert_to_qmt_format(stock_list):
    """转换为QMT格式"""
    converted_list = []
    for stock in stock_list:
        if stock.endswith('.XSHG'):
            converted_list.append(stock.replace('.XSHG', '.SH'))
        elif stock.endswith('.XSHE'):
            converted_list.append(stock.replace('.XSHE', '.SZ'))
        else:
            converted_list.append(stock)
    return converted_list

def cangwei1(C, stock, num):
    """备用仓位计算"""
    return num

# ===================== 缺失函数实现 =====================
def read_from_file():
    """读取交易记录"""
    try:
        with open('trade_records.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"读取交易记录失败: {e}")
        return []

def write_to_file(data):
    """写入交易记录"""
    try:
        with open('trade_records.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        print(f"写入交易记录失败: {e}")

# ===================== QMT接口适配函数（需要根据实际接口实现） =====================
# 以下函数需要根据QMT的实际API进行适配，这里提供占位实现
def get_trade_detail_data(accountid, data_type, detail_type):
    """获取交易详情数据"""
    # 请根据QMT实际API替换
    return []

def passorder(*args, **kwargs):
    """下单函数"""
    # 请根据QMT实际API替换
    print(f"下单参数: {args}, {kwargs}")
    return "mock_order_id"

def order_shares(*args, **kwargs):
    """按股数下单"""
    # 请根据QMT实际API替换
    print(f"按股数下单参数: {args}, {kwargs}")
    return "mock_order_id"

def order_target_value(*args, **kwargs):
    """按目标金额下单"""
    # 请根据QMT实际API替换
    print(f"按目标金额下单参数: {args}, {kwargs}")
    return "mock_order_id"

# ===================== 主程序入口 =====================
if __name__ == "__main__":
    # 测试用的模拟C对象
    class MockQMT:
        def __init__(self):
            self.accountid = "520000262415"
            self.period = "1m"
            self.barpos = 0
            
        def run_time(self, func_name, interval, start_time):
            print(f"启动定时任务: {func_name} 间隔: {interval} 开始时间: {start_time}")
            
        def get_bar_timetag(self, barpos):
            return datetime.now().timestamp()
            
        def get_full_tick(self, stock_list):
            return {stock: {'lastPrice': 10.0, 'volume': 1000, 'amount': 10000, 'high': 10.5, 'timetag': '20250101'} for stock in stock_list}
            
        def get_instrumentdetail(self, stock_code):
            return {'UpStopPrice': 11.0, 'DownStopPrice': 9.0, 'OpenDate': '20200101'}
            
        def get_market_data_ex(self, fields=[], stock_code=[], period="1d", start_time='', end_time='', count=3, dividend_type='none', subscribe=False):
            index = pd.date_range(end=datetime.now(), periods=count, freq='D')
            data = {
                'close': pd.Series([9.8, 9.9, 10.0], index=index),
                'open': pd.Series([9.7, 9.8, 9.9], index=index),
                'high': pd.Series([9.9, 10.0, 10.1], index=index),
                'low': pd.Series([9.6, 9.7, 9.8], index=index),
                'turnover': pd.Series([0.1, 0.15, 0.2], index=index),
                'total_value': pd.Series([50*10**8, 50*10**8, 50*10**8], index=index),
                'total_vol': pd.Series([2*10**8, 2*10**8, 2*10**8], index=index),
                'amount': pd.Series([10000, 15000, 20000], index=index),
                'volume': pd.Series([1000, 1500, 2000], index=index)
            }
            return {stock: pd.DataFrame(data) for stock in stock_code}
    
    # 创建模拟QMT对象
    mock_C = MockQMT()
    
    # 初始化程序
    init(mock_C)
    after_init(mock_C)
    
    # 测试选股
    stock_list, stock_dict = select_stocks_by_9_conditions()
    print(f"测试选股结果: {stock_list}")


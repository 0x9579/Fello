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

class G():
    pass

g = G()

# 文件路径
#TRADE_RECORD_FILE = 'D:\国金证券QMT交易端\bin.x64\trade_records.json'
TRADE_RECORD_FILE = 'trade_records.json'

def write_to_file(data, file_path=TRADE_RECORD_FILE):
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def read_from_file(file_path=TRADE_RECORD_FILE):
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")  # 调试输出
        return []
    with open(file_path, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
            print(f"成功读取文件: {file_path}")  # 调试输出
        except json.JSONDecodeError:
            print(f"文件读取失败，可能是空文件: {file_path}")  # 调试输出
            data = []
    return data

def extract_matching_stocks(log_line):
    # 查找“最后筛选符合要求的股票：”的位置
    start_index = log_line.find("最后筛选符合要求的股票：")
    
    if start_index != -1:
        # 提取方括号内的内容
        start_bracket = log_line.find('[', start_index)
        end_bracket = log_line.find(']', start_index)
        
        if start_bracket != -1 and end_bracket != -1:
            # 提取方括号内的内容
            stock_codes_str = log_line[start_bracket:end_bracket + 1]
            #print(f"Extracted stock codes string: {stock_codes_str}")  # 调试信息
            
            try:
                # 使用 ast.literal_eval 解析为 Python 列表
                matching_stocks = ast.literal_eval(stock_codes_str)
                return matching_stocks
            except (ValueError, SyntaxError) as e:
                print(f"解析错误: {e}")
                return []
    
    # 如果没有找到匹配的日志行，返回空列表
    print("No match found in the log line.")  # 调试信息
    return []    

def extract_stock_codes(stock_list):
    
    return [stock.split('(')[1].split(')')[0] for stock in stock_list]

def parse_buy_transactions(data, data_now=None):
    """
    解析JSON数据，提取"最后筛选符合要求的股票"的日志行中的股票代码列表，并根据传入的时间进行筛选。
    
    :param data: JSON格式的响应数据
    :param data_now: 用于筛选日志的时间字符串（格式：YYYY-MM-DD），默认为None，表示不进行时间筛选
    :return: 匹配的股票代码列表，如果没有找到则返回空列表
    """
    # 检查"data"和"logArr"是否存在
    if not data.get("data") or not data["data"].get("logArr"):
        print("Invalid data format")
        return []

    log_arr = data["data"]["logArr"]
    matching_stocks = []

    # 如果提供了data_now，解析为日期对象
    target_date = None
    if data_now:
        try:
            target_date = datetime.strptime(data_now, "%Y-%m-%d").date()
        except ValueError:
            print("Invalid date format. Please use YYYY-MM-DD.")
            return []

    # 遍历日志数组，查找符合条件的日志行
    for log in log_arr:
        # 提取日志的时间戳
        match = re.match(r"(\d{4}-\d{2}-\d{2}) \d{2}:\d{2}:\d{2} - INFO", log)
        if not match:
            continue  # 跳过不符合格式的日志行

        log_date_str = match.group(1)
        log_date = datetime.strptime(log_date_str, "%Y-%m-%d").date()

        # 如果提供了data_now且日期不匹配，则跳过该日志
        if target_date and log_date != target_date:
            continue

        # 定义一个模式来匹配包含“最后筛选符合要求的股票”的日志行
        pattern = r"最后筛选符合要求的股票：\s*$(.*?)$"
    
        # 检查日志行是否包含“最后筛选符合要求的股票”
        if "最后筛选符合要求的股票" in log:
            # 使用正则表达式提取股票代码列表
            #print("1111111",log)
            matching_stocks=extract_matching_stocks(log)
            break

    return matching_stocks

def fetch_transaction_details(api_url, params, headers):
    """
    发送POST请求以获取交易详情，并返回解析后的JSON数据。
    :param api_url: API的URL
    :param params: 请求参数字典
    :param headers: 请求头字典
    :return: 解析后的JSON数据或None（如果请求失败）
    """
    try:
        # 发送POST请求
        response = requests.post(api_url, params=params, headers=headers)
        # 检查响应状态码
        if response.status_code == 200:
            # 尝试解析JSON响应
            data = response.json()
            return data
        else:
            print(f"Request failed with status code: {response.status_code}")
            print("Response content:", response.text)
            return None
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        return None
    except ValueError:
        print("Invalid JSON response")
        return None



def convert_to_qmt_format(stock_list):
    """
    将股票代码处理为 QMT 的 .SH 和 .SZ 格式，兼容聚宽风格后缀和裸数字格式。
    :param stock_list: 包含股票代码的列表
    :return: 转换后的股票代码列表
    """
    converted_list = []
    for stock in stock_list:
        # 处理聚宽风格后缀或增加标准后缀
        split_res = stock.split('.', 1)
        if split_res[0] == "":
            continue
        code = split_res[0]
        if len(split_res) == 1:
            exchange = ""
        else:
            exchange = split_res[1]
        if len(code) < 6:
            code = str(code).zfill(6)
        if len(code) != 6:
            raise ValueError(f"股票代码长度不为6: {stock}")
        if exchange == "":
            # 增加标准后缀
            if code.startswith('60'):
                new_suffix = '.SH'
            elif code.startswith('000') or code.startswith('001') or code.startswith('002'):
                new_suffix = '.SZ'
            elif code.startswith('300'):
                new_suffix = '.SZ'
            elif code.startswith('688'):
                new_suffix = '.SH'
            else:
                raise ValueError(f"未知的股票代码前缀，无法填充交易所后缀: {stock}")
        else:
            # 处理聚宽风格后缀
            if exchange == 'XSHG':
                new_suffix = '.SH'
            elif exchange == 'XSHE':
                new_suffix = '.SZ'
            elif exchange == 'XSB':
                new_suffix = '.BJ'
            # 兼容QMT返回的格式
            elif exchange == 'SH':
                new_suffix = '.SH'
            elif exchange == 'SZ':
                new_suffix = '.SZ'
            elif exchange == 'BJ':
                new_suffix = '.BJ'
            else:
                raise ValueError(f"未知的交易所后缀: {exchange}")
        # 构建新的股票代码
        converted_code = f"{code}{new_suffix}"
        converted_list.append(converted_code)

    return converted_list

def feidan_xiadan(C,stock_list):
    orders = get_trade_detail_data(C.accountid, 'stock', 'order')
    print('9点30分查询股票委托状态：')
    for o in orders:
        s=o.m_strInstrumentID + "." + o.m_strExchangeID
        print(f'股票代码: {o.m_strInstrumentID}, 市场类型: {o.m_strExchangeID}, 证券名称: {o.m_strInstrumentName}, 委托状态: {o.m_nOrderStatus}',
        f'委托数量: {o.m_nVolumeTotalOriginal}, 成交均价: {o.m_dTradedPrice}, 成交数量: {o.m_nVolumeTraded}, 成交金额:{o.m_dTradeAmount}')
        if s in stock_list and o.m_nOrderStatus==57:
            print(f"股票{s}当前委托是废单，重新下单！")
            quoute = C.get_full_tick([s])
            print(quoute)
            price = quoute[s]['lastPrice']
            cu=C.get_instrumentdetail(s)
            pricemai=calculate_buy_price(price,s)
            if pricemai>cu['UpStopPrice']:
                pricemai=cu['UpStopPrice']
            print("股票的价格", price,"买入的金额",g.jine,"买入的价格",pricemai,"当日涨停价",cu['UpStopPrice'])
            stock_type=determine_stock_type(s)
            if stock_type==0:
                mairu_type=44
            else:
                mairu_type=44
            if g.opType==1:
                opType=33
            else:
                opType=23
            try:
                if g.mairu_tag==0:
                    passorder(opType, 1102, C.accountid, s, 11, float(pricemai),g.jine,'',2,'', C)
                else:
                    passorder(opType, 1102, C.accountid, s, mairu_type, 0, g.jine, '',2,'',C)
            except Exception as e:
                print(f"下单失败: {e}")

# 使用示例
# 使用示例
def mainMessages(C):
    stock_list = []
    # global_var_list = list(globals())[200:]
    for var_name in globals():
        # 2. 正则匹配：只匹配 stock_数字 格式
        if re.match(r'^stock_\d+$', var_name):
            # 获取变量值
            value = str(globals()[var_name])
            stock_list.append(value)
    
    stock_list=convert_to_qmt_format(stock_list)
    stock_list_dict = {}
    for stock in stock_list:
        stock_list_dict[stock] = {'close': 0, 'volume': 0, 'money': 0}
    return stock_list_dict

def datetime_to_timestamp(datetime_str, format="%Y-%m-%d %H:%M:%S"):
    """
    将日期时间字符串转换为毫秒级时间戳
    :param datetime_str: 日期时间字符串，例如 "2024-07-10 09:50:19"
    :param format: 日期时间格式，默认为 "%Y-%m-%d %H:%M:%S"
    :return: 毫秒级时间戳（整数）
    """
    try:
        # 将字符串解析为 datetime 对象
        dt = datetime.strptime(datetime_str, format)
        
        # 转换为时间戳（秒级），然后乘以 1000 转换为毫秒级
        timestamp_ms = int(dt.timestamp() * 1000)
        
        return timestamp_ms
    except ValueError as e:
        print(f"日期时间格式错误: {e}")
        return None

def buysell(C):
    current_time = datetime.now().strftime('%H:%M:%S')
    if current_time < "07:00:00" or current_time > "15:30:00":
        return

    if g.yun_tag!=1:
        return
    #print("buysell")
    enddate = datetime.now().strftime('%Y-%m-%d')
    if enddate>g.enddate:
        print("你的策略已到期，请联系QQ：40290092 进行付费。")
        return
    if g.yun_tag==0:
        d = C.barpos
        date_now = timetag_to_datetime(C.get_bar_timetag(d),'%Y-%m-%d')
        date_now1 = timetag_to_datetime(C.get_bar_timetag(d),'%Y%m%d')
        date = timetag_to_datetime(C.get_bar_timetag(d), '%Y%m%d%H%M%S')
        current_time = timetag_to_datetime(C.get_bar_timetag(d),'%H:%M:%S')
        #print('handlebar日期', date)
    else:
        date_now = datetime.now().strftime('%Y-%m-%d')
        date_now1 = datetime.now().strftime('%Y%m%d')
        # 获取当前日期时间
        current_date = datetime.now()
        # 减去一天得到前一天的日期
        previous_date = current_date - timedelta(days=1)
        prep_date = current_date - timedelta(days=2)
        # 格式化为 'YYYYMMDD' 格式的字符串
        prep_date1 = prep_date.strftime('%Y%m%d')
        previous_date1 = previous_date.strftime('%Y%m%d')
        date = datetime.now().strftime('%Y%m%d%H%M%S')
        current_time = datetime.now().strftime('%H:%M:%S')
        #print('程序正在运行：', date)
    #print(current_time)
    #print("当前时间为:",date)
    # 检查是否是9:27:30或11:28:00

    if current_time == "09:20:00":
        g.before_market_open=0
        g.tag=0
        g.tag1=0
        g.stock=[]
        g.count=0

    if g.before_market_open==0:
        before_market_open(C)
        g.before_market_open=1

    if g.tag1 == 0:
    #if g.tag == 0:
        #g.tag=1
        print('handlebar日期', date)
        mid_time1 = ' 05:55:00'
        end_times1 = ' 06:05:00'
        g.start = date_now + mid_time1
        g.end = date_now + end_times1
        #g.start='2025-06-07 15:45:54'
        #g.end='2025-06-07 15:47:54'
        #print(g.start)
        #print(g.end)
        #g.stock=['001212.XSHE', '002297.XSHE', '600300.XSHG', '600370.XSHG', '600490.XSHG', '600505.XSHG', '600644.XSHG', '603637.XSHG', '603991.XSHG']
        if g.huoqu_tag==0:
            stock_list=mainMessages(C)
            print('stock_list的值', stock_list)
            for stock, stock_data in stock_list.items():  # 使用 items() 同时获取键和值
                g.stock.append(stock)
            g.stock=convert_to_qmt_format(g.stock)
            #print('g.stock的值', g.stock)
            for stock in g.stock:
                download_history_data(stock,"1d",prep_date1,date)
            before_market_stock(C,g.stock,date)
        else:
            stock_list=mainMessages(C)
            print('stock_list的值', stock_list)
            before_market_stock1(C,stock_list,date)
            #print('g.stock的值', g.stock)
        g.tag1=1

    if current_time >= "09:25:05" and current_time <= "09:26:59" and g.tag == 0:
        #print("9点25分集合竞价")
        handle_data0(C,g.stock,date)
        #print(f"9点25分集合竞价为：{g.stock_jj}")
        if g.count==len(g.stock):
            g.tag=1
            print(f"9点25分集合竞价为：{g.stock_jj}")
            g.stock_mai=g.stock_jj
            if len(g.stock_mai)>0:
                print("今天买入的标的:", g.stock_mai)
                print("执行买入任务，当前时间为:", date)
                buyzaos(C,g.stock_mai)
                account_detail(C)
            else:
                print("今日没有合适的打板标的，请耐心等待,等待不亏钱!")

    #if current_time > "09:30:00":
        #handle_data(C,date)

    if current_time == "09:30:07":
        feidan_xiadan(C,g.stock)

    if current_time == "09:30:00":
        if g.ti_qian==1:
            print("9点30分开盘低开2%检查")
            handle_data1(C,g.positions,date)

    if current_time == "09:33:00":
        if g.ti_qian==1:
            print("9点33分开盘价检查")
            handle_data2(C,g.positions,date)

    if current_time == "10:30:00":
        if g.ti_qian==1:
            print("10点30分最高点后回调大于1.5%检查")
            handle_data3(C,g.positions,date)

    if current_time == "11:27:00":
        sellzhong(C)
        account_detail(C)
    if current_time == "14:49:00":
        sellwans(C)
        account_detail(C)



def order_shares_num(C):
    order_id = order_shares('002852.SZ', 100, C, C.accountid)
    #order_id = passorder(23, 1101, C.accountid, s, 11, float(price), 100, '', 1, '', C)
    print(f"订单ID: {order_id}")

def account_detail(C):
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

    #positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    #print('查询持仓结果：')
    #for dt in positions:
        #print(f'股东账户: {dt.m_strStockHolder},股票代码: {dt.m_strInstrumentID}, 市场类型: {dt.m_strExchangeID}, 证券名称: {dt.m_strInstrumentName}, 持仓量: {dt.m_nVolume}, 可用数量: {dt.m_nCanUseVolume}',
        #f'成本价: {dt.m_dOpenPrice:.2f}, 市值: {dt.m_dInstrumentValue:.2f}, 持仓成本: {dt.m_dPositionCost:.2f}, 盈亏: {dt.m_dPositionProfit:.2f}')
    #accounts = get_trade_detail_data(C.accountid, 'stock', 'account')
    #print('查询账户结果：')
    #for dt in accounts:
        #print(f'总资产: {dt.m_dBalance:.2f}, 净资产: {dt.m_dAssureAsset:.2f}, 总市值: {dt.m_dInstrumentValue:.2f}', 
        #f'总负债: {dt.m_dTotalDebit:.2f}, 可用金额: {dt.m_dAvailable:.2f}, 盈亏: {dt.m_dPositionProfit:.2f}')
    #for obj in account:
        #print(dir(obj))
        #print(obj)

def sellzhong(C):
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        print(f"读取文件内的股票",trade_records)
        updated_trade_records = []
        for dt in positions:
            s=dt.m_strInstrumentID + "." + dt.m_strExchangeID
                    # 检查是否在交易记录中
            if not any(s in record["code"] for record in trade_records):
                print(f"股票 {s} 不在交易记录中，跳过卖出操作")
                continue

            cu=C.get_instrumentdetail(s)
            #price = C.get_market_data (['open'],stock_code=[s],period=C.period,dividend_type='none')
            quoute = C.get_full_tick([s])
            price = quoute[s]['lastPrice']
            pricemai=round((price-0.07),2)
            if pricemai<cu['DownStopPrice']:
                pricemai=cu['DownStopPrice']
            stock_type=determine_stock_type(s)
            if stock_type==0:
                mairu_type=42
            else:
                mairu_type=46
            if g.opType==1:
                opType=34
            else:
                opType=24
            if ((dt.m_nCanUseVolume != 0) and (price > dt.m_dOpenPrice) and (price<cu['UpStopPrice'])):
                print(f'卖出股票: {s}')
                print("股票11点30的价格", price,"卖出价格", pricemai,'股票的代码',dt.m_strInstrumentID,'股票的涨停价',cu['UpStopPrice'],'股票的跌停价',cu['DownStopPrice'])
                #passorder(24, 1101, C.accountid, s, 11, float(pricemai), dt.m_nCanUseVolume,'',2,'', C)
                passorder(opType, 1101, C.accountid, s, mairu_type, 0, dt.m_nCanUseVolume, '',2,'',C)
                #order_shares(s,-dt.m_nCanUseVolume,'fix',float(pricemai),C,C.accountid)
                # 从交易记录中移除已卖出的股票
                # 更新交易记录：移除已卖出的股票代码
                #for record in trade_records:
                    #if s in record["code"]:
                    # 移除该股票代码
                        #record["code"].remove(s)
                    # 如果该记录中没有其他股票代码，则完全移除该记录
                        #if not record["code"]:
                            #continue
                    #updated_trade_records.append(record)
                #print(f'更新文件: {updated_trade_records}')
                # 如果有更新，则写回文件
                #if updated_trade_records != trade_records:
                    #write_to_file(updated_trade_records)

def sellwans(C):
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        print(f"读取文件内的股票",trade_records)
        updated_trade_records = []
        for dt in positions:
            s=dt.m_strInstrumentID + "." + dt.m_strExchangeID
            # 检查是否在交易记录中
            if not any(s in record["code"] for record in trade_records):
                print(f"股票 {s} 不在交易记录中，跳过卖出操作")
                continue

            cu=C.get_instrumentdetail(s)
            price = C.get_market_data (['open'],stock_code=[s],period=C.period,dividend_type='none')
            pricemai=round((price-0.07),2)
            if pricemai<cu['DownStopPrice']:
                pricemai=cu['DownStopPrice']
            stock_type=determine_stock_type(s)
            if stock_type==0:
                mairu_type=44
            else:
                mairu_type=44
            if g.opType==1:
                opType=34
            else:
                opType=24
            print("mairu_type的值", mairu_type)
            if ((dt.m_nCanUseVolume != 0) and (price<cu['UpStopPrice'])):
                print(f'卖出股票: {s}')
                print("股票14点55的价格", price,"卖出价格", pricemai,'股票的代码',dt.m_strInstrumentID,'股票的涨停价',cu['UpStopPrice'],'股票的跌停价',cu['DownStopPrice'])
                #passorder(24, 1101, C.accountid, s, 11, float(pricemai), dt.m_nCanUseVolume,'',2,'', C)
                passorder(opType, 1101, C.accountid, s, mairu_type, 0, dt.m_nCanUseVolume, '',2,'',C)
                #order_shares(s,-dt.m_nCanUseVolume,'fix',float(pricemai),C,C.accountid)
                # 从交易记录中移除已卖出的股票
                # 更新交易记录：移除已卖出的股票代码
                #for record in trade_records:
                    #if s in record["code"]:
                    # 移除该股票代码
                        #record["code"].remove(s)
                    # 如果该记录中没有其他股票代码，则完全移除该记录
                        #if not record["code"]:
                            #continue
                    #updated_trade_records.append(record)
                #print(f'更新文件: {updated_trade_records}')
                # 如果有更新，则写回文件
                #if updated_trade_records != trade_records:
                    #write_to_file(updated_trade_records)

def read_xml(file_path):
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            print(f"文件 {file_path} 不存在")
            return None
        if not os.access(file_path, os.R_OK):
            print(f"没有权限读取文件 {file_path}")
            return None

        # 解析XML文件
        tree = ET.parse(file_path)
        root = tree.getroot()
        # 打印根元素标签
        #print(f"根元素: {root.tag}")
        # 存储解析后的配置信息
        config_data = {}

        # 遍历 <control> 和 <variable> 元素
        for control in root.findall('control'):
            for variable in control.findall('variable'):
                for item in variable.findall('item'):
                    # 提取每个 <item> 元素的属性
                    item_data = {
                        'position': item.get('position', ''),
                        'bind': item.get('bind', ''),
                        'value': item.get('value', ''),
                        'note': item.get('note', ''),
                        'name': item.get('name', ''),
                        'type': item.get('type', '')
                    }
                    # 将提取的数据存储到字典中
                    config_data[item.get('bind')] = item_data
                    # 打印每个 <item> 元素的详细信息
                    #print(f"  子元素: {item.tag}, 属性: {item_data}")
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

def init(C):
    # ------------------------参数设定-----------------------------
    print("程序初始化成功")
    g.banben='V2.7'
    g.cese=1
    # 获取当前工作目录
    #current_working_dir = os.getcwd()
    # 获取当前脚本的绝对路径
    current_working_dir = os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe())))
    # 构建相对路径
    relative_path = os.path.join('formulaLayout', '开盘打板运行版V8.xml')

    # 构建完整的文件路径
    xml_file_path = os.path.abspath(os.path.join(current_working_dir, relative_path))
    # 打印文件路径以确认
    print(f"XML 文件路径: {xml_file_path}")
# 检查路径中是否包含 "bin.x64"，并将其替换为 "python"
    if 'bin.x64' in xml_file_path:
        # 使用 replace() 方法将 "bin.x64" 替换为 "python"
        xml_file_path = xml_file_path.replace(r'\bin.x64', r'\python')
        print(f"修正后的 XML 文件路径: {xml_file_path}")
    # 定义XML文件路径
    # 获取当前脚本的绝对路径
    #xml_file_path = r'D:\迅投QMT实盘交易端_一创证券版\python\formulaLayout\开盘打板运行版.xml'
    # 检查文件是否存在和权限
    if not os.path.exists(xml_file_path):
        print(f"文件 {xml_file_path} 不存在")
        return
    if not os.access(xml_file_path, os.R_OK):
        print(f"没有权限读取文件 {xml_file_path}")
        return
    g.his_st = {}
    g.s = get_stock_list_in_sector("沪深300")  # 获取沪深300股票列表
    # print(g.s)
    # g.s = ['000001.SZ']
    g.stock=[]
    g.positions=[]
    g.stocks_date2={}
    g.tag=0
    g.tag1=0
    g.jine=0
    g.sum_xishu=0.3
    g.tag_fenzhong=0
    g.result = None
    g.stock_states = {}
    g.stock_states1 = {}
    g.day = 0
    g.count=0
    g.stocknum=5
    g.start='2025-02-15 22:14:47'
    g.end='2025-02-15 22:14:48'
    g.time_counter=0
    g.holdings = {i: 0 for i in g.s}
    g.weight = [0.1] * 10
    g.buypoint = {}
    g.money = 10000000  # C.capital
    g.mairu_tag=1  #0-限价委托 1-市价委托
    #g.accid = '8883122959'
    #print(f"资金账户1ID: {C.account_id}")
    C.accountid="520000262415"
    g.enddate='2028-03-22'
    g.profit = 0
    g.opType = 0 #0-普通账户买入卖出 1-融资买入卖出
    g.yun_tag=1  #0-回测 1-运行
    g.ti_qian = 0  #1-提前卖出
    # 因子权重
    g.before_market_open=0
    g.before_market_stock=0
    g.buy_num = 10  # 买排名前5的股票，在过滤中会用到
    g.per_money = 10000
        # 读取并解析XML文件
    g.xml_tag=0  #1-直接设置资金额度
    g.huoqu_tag=1  #0-代表QMT获取，1-聚宽获取
    if g.xml_tag==1:
        g.zijin_num=10000
        print(f"每个股票买入的资金: {g.zijin_num}")
        print(f"资金账户ID: {C.accountid}")
        print("当前市场温度：低（建议仓位0~25%），市场有风险，要学会控制仓位！")
        print(f"策略到期时间为: {g.enddate}，到期后请及时续费")
    else:
        config_data = read_xml(xml_file_path)
        if config_data is not None:
        # 处理解析后的配置数据
        #print("解析到的配置数据:")
        #for key, value in config_data.items():
            #print(f"  {key}: {value}")

        # 示例：从配置数据中提取并存储关键信息
            g.zijin_num = int(config_data.get('zijin_num', {}).get('value', 0))
            #g.acct_id = config_data.get('acct_id', {}).get('value', '')

            print(f"每个股票买入的资金: {g.zijin_num}")
            print(f"资金账户ID: {C.accountid}")
            print("当前市场温度：低（建议仓位控制在0~25%），要注意仓位管理！")
            print(f"策略到期时间为: {g.enddate}，到期后请及时续费")

            # 你可以在这里继续处理其他配置项
        else:
            print("无法解析XML文件，策略初始化失败")
    C.run_time("buysell","1nSecond","2019-10-14 13:20:00")
    g.stock_pool=mainMessages(C)
    print("从面板读取的股票池", g.stock_pool.keys()) 

def after_init(C):
    print("程序加载数据成功，开始运行，当前版本:",g.banben)
    if g.ti_qian==1:
        getpositions(C)

# 假设我们有一个全局变量来存储所有的 last_price 和对应的时间
def before_market_open(C):
    g.stock_states = {}
    # 重置每日变量
    positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    for dt in positions:
        stock=dt.m_strInstrumentID + "." + dt.m_strExchangeID
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
        
    print('before_open的g.stock_states：%s'%g.stock_states)

# 假设我们有一个全局变量来存储所有的 last_price 和对应的时间
def before_market_stock(C,stock_sum,date):
    limit_up_price=0
    g.stock_states1 = {}
    for stock in stock_sum:
        g.stock_states1[stock] = {
            'price_history': [],
            'last_price': 0,
            'last_price1': 0,
            'UpStopPrice': 0,  #涨停价格
            'KpStopPrice': 0,  #1-涨停开盘，2高开或平开开盘，3低开开盘
            'yesterday_close': 1,  #昨日收盘价
            'KP_Price': 0,
            'jj_tag': 0,
            'ZuigaoPrice': 0,
            'ZuidiPrice': 0,
            'last_jjprice': 1,  #竞价的价格
            'last_jjvolume': 1,  #竞价的成交量
            'last_jjamount': 1,  #竞价的成交额
            'yesterday_volume': 1,  #昨日成交量
            'yesterday_amount': 1,  #昨日成交额
            'last_price_kaip': 1,  #开盘一分钟价格
            'last_volume_kaip': 1,  #开盘一分钟成交量
            'price_change_history': [],
            'monitor_next_minute': False,
            'initial_price_for_monitor': None,
            'sum_zhangfu': 9.5,
            'time_counter': 0,
            'mairu_tag': 0,
            'orderid': 0
        }
        date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
        # 计算昨天的日期
        yesterday_obj = date_obj - timedelta(days=1)
        # 将datetime对象格式化为字符串
        yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
        volume_data = C.get_market_data_ex (['close','amount','volume'],stock_code=[stock],period="1d",start_time = '', end_time = yesterday_str,count = 3,dividend_type='none',subscribe=True)
        print('before_open的volume_data：%s'%volume_data)
        # 确认 volume_data 中有相应的股票代码键
        if stock in volume_data:
            state = g.stock_states1[stock]
            # 从 DataFrame 中提取收盘价数据
            close_prices = volume_data[stock]['close']
            close_amount = volume_data[stock]['amount']
            close_volume = volume_data[stock]['volume']
            state['yesterday_close'] = close_prices.iloc[-1]
            state['yesterday_amount'] = close_amount.iloc[-1]
            state['yesterday_volume'] = close_volume.iloc[-1]*100
            # 获取最新的收盘价（即昨日收盘价）
            limit_up_price = calculate_limit_up_price(state['yesterday_close'], stock)
            state['UpStopPrice'] = limit_up_price
    print('before_open的g.stock_states1：%s'%g.stock_states1)

# 假设我们有一个全局变量来存储所有的 last_price 和对应的时间
def before_market_stock1(C,stock_sum,date):
    limit_up_price=0
    g.stock_states1 = {}
    g.stock=[]
    for stock, stock_data in stock_sum.items():  # 使用 items() 同时获取键和值
        stock_list=[stock]
        stock_name_list=convert_to_qmt_format(stock_list)
        stock_name = stock_name_list[0]
        g.stock.append(stock_name)
        yesterday_close=stock_data.get('close', 1)
        yesterday_volume=stock_data.get('volume', 1)
        yesterday_amount=stock_data.get('money', 1)  
        g.stock_states1[stock_name] = {
            'price_history': [],
            'last_price': 0,
            'last_price1': 0,
            'UpStopPrice': 0,  #涨停价格
            'KpStopPrice': 0,  #1-涨停开盘，2高开或平开开盘，3低开开盘
            'yesterday_close': yesterday_close,  #昨日收盘价
            'KP_Price': 0,
            'jj_tag': 0,
            'ZuigaoPrice': 0,
            'ZuidiPrice': 0,
            'last_jjprice': 1,  #竞价的价格
            'last_jjvolume': 1,  #竞价的成交量
            'last_jjamount': 1,  #竞价的成交额
            'yesterday_volume': yesterday_volume,  #昨日成交量
            'yesterday_amount': yesterday_amount,  #昨日成交额
            'last_price_kaip': 1,  #开盘一分钟价格
            'last_volume_kaip': 1,  #开盘一分钟成交量
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
    print('before_open的g.stock_states1：%s'%g.stock_states1)

def calculate_limit_up_price(yesterday_close, stock_code):
    """
    根据昨日收盘价和股票代码，计算今日股票的涨停价。

    参数:
        yesterday_close (float): 昨日收盘价
        stock_code (str): 股票代码，用于判断所属板块

    返回:
        float: 今日涨停价
    """
    # 判断股票所属板块并设置涨停幅度
    if stock_code.startswith("68") or stock_code.startswith("30"):  # 科创板或创业板
        limit_up_percentage = 0.20  # 涨幅 20%
    elif stock_code.startswith("00") or stock_code.startswith("60"):  # 主板或深圳市场
        if "ST" in stock_code or "*ST" in stock_code:  # ST板块
            limit_up_percentage = 0.05  # 涨幅 5%
        else:
            limit_up_percentage = 0.10  # 涨幅 10%
    else:
        raise ValueError(f"无法识别股票代码 {stock_code} 的板块，请检查输入。")

    # 计算涨停价
    limit_up_price = round(yesterday_close * (1 + limit_up_percentage), 2)

    return limit_up_price


def handle_data(C,date):
    g.time_counter += 1
    #print("当前计数:%s"%(g.time_counter))
    positions = get_trade_detail_data(C.accountid, 'stock', 'position')
    for dt in positions:
        stock=dt.m_strInstrumentID + "." + dt.m_strExchangeID
        if (dt.m_nCanUseVolume == 0):
            continue
        state = g.stock_states[stock]
        state['time_counter'] += 1
        avg_cost=dt.m_dOpenPrice
        if g.yun_tag==0:
        #volume_data = C.get_market_data_ex (['open'],stock_code=[s],period=C.period,count = 10,dividend_type='none')
            volume_data = C.get_market_data_ex (['open'],stock_code=[stock],period=C.period, start_time = date, end_time = date,dividend_type='none')
            last_price=volume_data[stock]['open'][-1]
        else:
            quoute = C.get_full_tick([stock])
        #print(quoute)
            last_price = quoute[stock]['lastPrice']

        if last_price is not None:
            if state['last_price'] != 0:
                state['last_price1'] = state['last_price']
            state['last_price'] = last_price

            if state['last_price1'] != 0:
                # 计算涨幅
                #print("1分钟价格", state['last_price1'],"1分钟价格1", state['last_price'])
                price_change = (state['last_price'] - state['last_price1']) / state['last_price1'] * 100.0
                # 存储涨幅和当前时间
                state['price_change_history'].append((state['time_counter'], price_change))

            # 将当前价格存入价格历史
            state['price_history'].append((state['time_counter'], state['last_price']))

            # 打印信息以便调试（可选）
            #print(f"Time: {current_time}, Last Price for {stock}: {state['last_price']}")

            # 检查过去三分钟的累计涨幅
            check_three_minute_rise(C, stock)

            # 如果正在监控下一分钟的K线
            if state['monitor_next_minute']:
                monitor_next_minute_kline(C, stock, state['last_price'],avg_cost,date)
                print(f"monitor_next_minute_kline价格 {state['last_price']:.2f}")

# 检查过去三分钟的累计涨幅是否达到或超过 5%
def check_three_minute_rise(C, stock):
    state = g.stock_states[stock]
    cumulative_rise = 0

    # 确保有足够的数据点来计算三分钟的涨幅
    if len(state['price_history']) >= 5:
        # 取出最近三个有效价格数据点
        recent_prices = [price for _, price in state['price_history'][-5:]]

        # 计算这三个价格的累计涨幅
        initial_price = recent_prices[0]
        final_price = recent_prices[-1]
        cumulative_rise = (final_price - initial_price) / initial_price * 100.0

        if cumulative_rise >= state['sum_zhangfu'] and state['time_counter']>15:
            #print(f"在过去三分钟内，{stock} 的累计涨幅达到了 {cumulative_rise:.2f}%")
            # 启动监控下一分钟的K线
            state['monitor_next_minute'] = True
            #state['initial_price_for_monitor'] = final_price  # 记录触发监控时的开盘价

# 监控下一分钟的K线
def monitor_next_minute_kline(C, stock, current_price,avg_cost,date):
    state = g.stock_states[stock]
    # 将字符串转换为datetime对象
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    # 计算昨天的日期
    yesterday_obj = date_obj - timedelta(days=1)
    # 将datetime对象格式化为字符串
    yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
    # 如果是第一次进入监控状态，记录当前价格作为开盘价
    if state['initial_price_for_monitor'] is None:
        state['initial_price_for_monitor'] = current_price
        return

    print(f"当前价格1 {current_price} 前面价 {state['initial_price_for_monitor']} 对应股票 {stock}")

    volume_data = C.get_market_data_ex (['close'],stock_code=[stock],period="1d",start_time = '', end_time = yesterday_str,count = 2,dividend_type='none')
    print(f"当前股票2{stock} ，当日：{yesterday_str}的收盘价2：{volume_data}")
    # 确认 volume_data 中有相应的股票代码键
    if stock in volume_data:
        # 从 DataFrame 中提取收盘价数据
        close_prices = volume_data[stock]['close']
        # 获取最新的收盘价（即昨日收盘价）
        yesterday_close = close_prices.iloc[-1]
        # 假设 current_price 已经定义
        dangrizhangfu = current_price / yesterday_close
        print(f"当前价格5{current_price} ，上一分钟价格5：{state['initial_price_for_monitor']}，昨日收盘价5：{yesterday_close}，成本价：{avg_cost}，累计涨幅 {dangrizhangfu:.2f}%")
    else:
        print(f"未找到股票 {stock} 的数据")
        print(f"当前价格5 {current_price} ，上一分钟价格5 ：{state['initial_price_for_monitor']}，昨日收盘价5：{yesterday_close}，成本价：{avg_cost}，累计涨幅 {dangrizhangfu:.2f}%")

    # 检查当前价格是否小于开盘价（即出现阴线）
    #if current_price < state['initial_price_for_monitor'] and dangrizhangfu<1.085 and state['initial_price_for_monitor']>=avg_cost:
    if current_price < state['initial_price_for_monitor'] and dangrizhangfu<1.085 :
        print(f"时间：{date}，检测到卖出信号，当前价格 {current_price} 小于开盘价 {state['initial_price_for_monitor']}，执行卖出操作")

        # 执行卖出操作（这里可以替换为实际的下单逻辑）
        selllasheng(C,stock)
        account_detail(C)

        print("日内实时监控卖出股票%s，价格1：%s"%(stock,current_price))

        # 重置监控标志
        state['monitor_next_minute'] = False
        state['initial_price_for_monitor'] = None

    # 如果已经过了监控的时间窗口（例如一分钟后），也重置监控标志
    elif state['time_counter'] > state['price_history'][-3][0] + 60:
        print(f"监控时间窗口已过，未检测到符合条件的K线，重置监控 {stock}")
        state['monitor_next_minute'] = False
        state['initial_price_for_monitor'] = None

    state['initial_price_for_monitor'] = current_price

def getpositions(C):
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        print(f"读取文件内的股票",trade_records)
        updated_trade_records = []
        for dt in positions:
            s=dt.m_strInstrumentID + "." + dt.m_strExchangeID
                    # 检查是否在交易记录中
            if not any(s in record["code"] for record in trade_records):
                continue
            g.positions.append(s)

def selllasheng(C,s):
        positions = get_trade_detail_data(C.accountid, 'stock', 'position')
        trade_records = read_from_file()
        print(f"读取文件内的股票",trade_records)
        updated_trade_records = []
        for dt in positions:
            stock=dt.m_strInstrumentID + "." + dt.m_strExchangeID
            # 检查是否在交易记录中
            if stock!=s:
                continue
            if not any(s in record["code"] for record in trade_records):
                print(f"股票 {s} 不在交易记录中，跳过卖出操作")
                continue

            cu=C.get_instrumentdetail(s)
            #price = C.get_market_data (['open'],stock_code=[s],period=C.period,dividend_type='none')
            quoute = C.get_full_tick([s])
            price = quoute[s]['lastPrice']
            pricemai=round((price-0.09),2)
            if pricemai<cu['DownStopPrice']:
                pricemai=cu['DownStopPrice']
            if ((dt.m_nCanUseVolume != 0) and (price<cu['UpStopPrice'])):
                print(f'卖出股票: {s}')
                print("股票拉升的价格", price,"卖出价格", pricemai,'股票的代码',dt.m_strInstrumentID,'股票的涨停价',cu['UpStopPrice'],'股票的跌停价',cu['DownStopPrice'])
                #passorder(24, 1101, C.accountid, s, 11, float(pricemai), dt.m_nCanUseVolume,'',2,'', C)
                #order_shares(s,-dt.m_nCanUseVolume,'fix',float(pricemai),C,C.accountid)
                order_target_value(s, 0, 'MARKET', C, C.accountid)
                # 从交易记录中移除已卖出的股票
                # 更新交易记录：移除已卖出的股票代码
                for record in trade_records:
                    if s in record["code"]:
                    # 移除该股票代码
                        record["code"].remove(s)
                    # 如果该记录中没有其他股票代码，则完全移除该记录
                        if not record["code"]:
                            continue
                    updated_trade_records.append(record)
                print(f'更新文件: {updated_trade_records}')
                # 如果有更新，则写回文件
                if updated_trade_records != trade_records:
                    write_to_file(updated_trade_records)

def handle_data1(C,positions,date):
    # 将字符串转换为datetime对象
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    # 计算昨天的日期
    yesterday_obj = date_obj - timedelta(days=1)
    # 将datetime对象格式化为字符串
    yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
    for stock in positions:
        if g.yun_tag==1:
            quoute = C.get_full_tick([stock])
            #print(quoute)
            last_price = quoute[stock]['lastPrice']
        else:
            volume_data1 = C.get_market_data_ex (['open'],stock_code=[stock],period=C.period, start_time = date, end_time = date,dividend_type='none')
            last_price=volume_data1[stock]['open'][-1]

        volume_data = C.get_market_data_ex (['close'],stock_code=[stock],period="1d",start_time = '', end_time = yesterday_str,count = 2,dividend_type='none')
        #print(f"当前股票2{stock} ，昨日收盘价2：{volume_data}")
        # 确认 volume_data 中有相应的股票代码键
        if stock in volume_data:
            # 从 DataFrame 中提取收盘价数据
            close_prices = volume_data[stock]['close']
            # 获取最新的收盘价（即昨日收盘价）
            yesterday_close = close_prices.iloc[-1]
            # 假设 current_price 已经定义
            dangrizhangfu = (last_price - yesterday_close) / yesterday_close * 100.0
            #print(f"当前价格{last_price} ，昨日收盘价：{yesterday_close}，累计涨幅 {dangrizhangfu:.2f}%")
        else:
            print(f"未找到股票 {stock} 的数据")
            
        if dangrizhangfu <= -2:
            selllasheng(C,stock)
            account_detail(C)

def handle_data2(C,positions,date):
    # 将字符串转换为datetime对象
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    # 计算昨天的日期
    yesterday_obj = date_obj - timedelta(days=1)
    # 将datetime对象格式化为字符串
    yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
    for stock in positions:
        state = g.stock_states[stock]
        if g.yun_tag==1:
            quoute = C.get_full_tick([stock])
            #print(quoute)
            last_price = quoute[stock]['lastPrice']
        else:
            volume_data1 = C.get_market_data_ex (['open'],stock_code=[stock],period=C.period, start_time = date, end_time = date,dividend_type='none')
            last_price=volume_data1[stock]['open'][-1]

        volume_data = C.get_market_data_ex (['close'],stock_code=[stock],period="1d",start_time = '', end_time = yesterday_str,count = 2,dividend_type='none')
        #print(f"当前股票2{stock} ，昨日收盘价2：{volume_data}")
        # 确认 volume_data 中有相应的股票代码键
        if stock in volume_data:
            # 从 DataFrame 中提取收盘价数据
            close_prices = volume_data[stock]['close']
            # 获取最新的收盘价（即昨日收盘价）
            yesterday_close = close_prices.iloc[-1]
            # 假设 current_price 已经定义
            dangrizhangfu = (last_price - yesterday_close) / yesterday_close * 100.0
            #print(f"当前价格{last_price} ，昨日收盘价：{yesterday_close}，累计涨幅 {dangrizhangfu:.2f}%")
        else:
            print(f"未找到股票 {stock} 的数据")
            
        if last_price < yesterday_close:
            selllasheng(C,stock)
            account_detail(C)

def handle_data3(C,positions,date):
    # 将字符串转换为datetime对象
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    # 计算昨天的日期
    yesterday_obj = date_obj - timedelta(days=1)
    # 将datetime对象格式化为字符串
    yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
    for stock in positions:
        state = g.stock_states[stock]
        if g.yun_tag==1:
            quoute = C.get_full_tick([stock])
            #print(quoute)
            last_price = quoute[stock]['lastPrice']
            high=quoute[stock]['high']
        else:
            volume_data1 = C.get_market_data_ex (['open,high'],stock_code=[stock],period=C.period, start_time = date, end_time = date,dividend_type='none')
            last_price=volume_data1[stock]['open'][-1]
            high=volume_data1[stock]['high'][-1]

        volume_data = C.get_market_data_ex (['close'],stock_code=[stock],period="1d",start_time = '', end_time = yesterday_str,count = 2,dividend_type='none')
        #print(f"当前股票2{stock} ，昨日收盘价2：{volume_data}")
        # 确认 volume_data 中有相应的股票代码键
        if stock in volume_data:
            # 从 DataFrame 中提取收盘价数据
            close_prices = volume_data[stock]['close']
            # 获取最新的收盘价（即昨日收盘价）
            yesterday_close = close_prices.iloc[-1]
            # 假设 current_price 已经定义
            dangrizhangfu = (last_price - high) / high * 100.0
            #print(f"当前价格{last_price} ，昨日收盘价：{yesterday_close}，累计涨幅 {dangrizhangfu:.2f}%")
        else:
            print(f"未找到股票 {stock} 的数据")
            
        if dangrizhangfu <=-1.5:
            selllasheng(C,stock)
            account_detail(C)

# 定义一个函数，将字符串转换回 g.stock_states
def convert_string_to_stock_states(stock_states_str):
    try:
        # 使用 json.loads 将字符串转换为字典
        stock_states_dict = json.loads(stock_states_str)
        return stock_states_dict
    except json.JSONDecodeError as e:
        print("JSON 解码错误:", e)
        return None



def get_stock_pool_from_panel(C):
    stock_list = []
    # global_var_list = list(globals())[200:]
    for var_name in globals():
        # 2. 正则匹配：只匹配 stock_数字 格式
        if re.match(r'^stock_\d+$', var_name):
            # 获取变量值
            value = str(globals()[var_name])
            stock_list.append(value)
    
    stock_list=convert_to_qmt_format(stock_list)
    stock_list_dict = {}
    for stock in stock_list:
        stock_list_dict[stock] = {'close': 0, 'volume': 0, 'money': 0}
    return stock_list_dict


def handlebar(C):
    if g.yun_tag!=0:
        return
    #print("handlebar")
    enddate = datetime.now().strftime('%Y-%m-%d')
    if enddate>g.enddate:
        print("你的策略已到期，请联系QQ：40290092 进行付费。")
        return
    if g.yun_tag==0:
        d = C.barpos
        date_now = timetag_to_datetime(C.get_bar_timetag(d),'%Y-%m-%d')
        date_now1 = timetag_to_datetime(C.get_bar_timetag(d),'%Y%m%d')
        date = timetag_to_datetime(C.get_bar_timetag(d), '%Y%m%d%H%M%S')
        current_time = timetag_to_datetime(C.get_bar_timetag(d),'%H:%M:%S')
        #print('handlebar日期', date)
    else:
        date_now = datetime.now().strftime('%Y-%m-%d')
        date_now1 = datetime.now().strftime('%Y%m%d')
        date = datetime.now().strftime('%Y%m%d%H%M%S')
        current_time = datetime.now().strftime('%H:%M:%S')
        #print('run日期', date)
    #print(current_time)
    #print("当前时间为:",date)
    # 检查是否是9:27:30或11:28:00


    if current_time <= "09:30:00":
        g.stock=[]
        g.tag=0

    if current_time == "09:30:00":
        g.before_market_open=0

    if current_time == "09:31:00" and g.tag == 0:
        print('handlebar日期09:30:02', date)
        mid_time1 = ' 05:55:00'
        end_times1 = ' 06:05:00'
        date_now = datetime.now().strftime('%Y-%m-%d')
        g.start = date_now + mid_time1
        g.end = date_now + end_times1
        g.start='2025-06-07 15:46:54'
        g.end='2025-06-07 15:47:54'
        print(g.start)
        print(g.end)
        if g.huoqu_tag==0:
            stock_list=mainMessages(C)
            print('stock_list的值', stock_list)
            for stock, stock_data in stock_list.items():  # 使用 items() 同时获取键和值
                g.stock.append(stock)
            g.stock=convert_to_qmt_format(g.stock)
            print('g.stock的值', g.stock)
            for stock in g.stock:
                download_history_data(stock,"1d",prep_date1,date)
            #g.stock=['001212.XSHE', '002297.XSHE', '600300.XSHG', '600370.XSHG', '600490.XSHG', '600505.XSHG', '600644.XSHG', '603637.XSHG', '603991.XSHG']
            before_market_stock(C,g.stock,date)
        else:
            stock_list=get_stock_pool_from_panel(C)
            print('stock_list的值', stock_list)
            # stock_list={'000029.XSHE': {'close': 20.53, 'volume': 21867460.0, 'money': 431234313.14}, '000723.XSHE': {'close': 4.99, 'volume': 353469362.0, 'money': 1736841946.06}, '000935.XSHE': {'close': 20.38, 'volume': 38208662.0, 'money': 755985525.74}, '002459.XSHE': {'close': 11.81, 'volume': 214240964.0, 'money': 2456877300.32}, '002506.XSHE': {'close': 2.86, 'volume': 507672214.0, 'money': 1421853359.3}, '002546.XSHE': {'close': 6.31, 'volume': 123052113.0, 'money': 762932128.03}, '002657.XSHE': {'close': 31.79, 'volume': 117816082.0, 'money': 3657235113.31}, '600606.XSHG': {'close': 1.89, 'volume': 324388367.0, 'money': 602621198.53}, '601718.XSHG': {'close': 4.33, 'volume': 547831652.0, 'money': 2267563934.58}, '603439.XSHG': {'close': 13.02, 'volume': 31757538.0, 'money': 402083222.8}}
            before_market_stock1(C,stock_list,date)
            print('g.stock的值', g.stock)

    if current_time >= "09:32:50" and current_time <= "09:34:59" and g.tag == 0:
        #print("9点25分集合竞价")
        handle_data0(C,g.stock,date)
        #print(f"9点25分集合竞价为：{g.stock_jj}")
        if g.count==len(g.stock):
            g.tag=1
            print(f"9点25分集合竞价为：{g.stock_jj}")
            g.stock_mai=g.stock_jj
            g.stock_mai=['000029.SZ', '000723.SZ']
            if len(g.stock_mai)>0:
                print("今天买入的标的:", g.stock_mai)
                print("执行买入任务，当前时间为:", date)
                buyzaos(C,g.stock_mai)
                account_detail(C)
            else:
                print("今日没有合适的打板标的，请耐心等待,等待不亏钱!")

    if g.before_market_open==0:
        before_market_open(C)
        g.before_market_open=1

    if current_time > "09:30:00":
        handle_data(C,date)

    if current_time == "09:30:00":
        if g.ti_qian==1:
            print("9点30分开盘低开2%检查")
            handle_data1(C,g.positions,date)

    if current_time == "09:33:00":
        if g.ti_qian==1:
            print("9点33分开盘价检查")
            handle_data2(C,g.positions,date)

    if current_time == "10:30:00":
        if g.ti_qian==1:
            print("10点30分最高点后回调大于1.5%检查")
            handle_data3(C,g.positions,date)

    if current_time == "11:28:00":
        sellzhong(C)
        account_detail(C)
    if current_time == "14:49:00":
        sellwans(C)
        account_detail(C)


def handle_data0(C,positions,date):
    # 将字符串转换为datetime对象
    date_obj = datetime.strptime(date, '%Y%m%d%H%M%S')
    # 计算昨天的日期
    yesterday_obj = date_obj - timedelta(days=1)
    # 将datetime对象格式化为字符串
    yesterday_str = yesterday_obj.strftime('%Y%m%d%H%M%S')
    for stock in positions:
        state = g.stock_states1[stock]
        if state['jj_tag']==1:
            continue
        if g.yun_tag==1:
            quoute = C.get_full_tick([stock])
            #print(quoute)
            state['last_jjprice']= quoute[stock]['lastPrice']
            state['last_jjvolume']= quoute[stock]['volume']
            state['last_jjamount']= quoute[stock]['amount']
            timetag_str = quoute[stock]['timetag']
            formatted_date = f"{timetag_str[0:4]}-{timetag_str[4:6]}-{timetag_str[6:8]}"
            if formatted_date>g.enddate:
                print("你的策略已到期，请联系QQ：40290092 进行付费。")
                return
        else:
            volume_data1 = C.get_market_data_ex ([],stock_code=[stock],period=C.period, start_time = date, end_time = date,dividend_type='none')
            state['last_jjprice']=volume_data1[stock]['open'][-1]
            state['last_jjvolume']=volume_data1[stock]['volume'][-1]
            state['last_jjamount']= volume_data1[stock]['amount'][-1]
            
        current_ratio = state['last_jjprice'] / state['yesterday_close']
        jingcb = state['last_jjamount']/state['yesterday_amount']
        
        if state['last_jjprice']==0 or state['last_jjamount']==0:
            print(f"股票{stock}没有获取到数据,等待下一秒获取")
            continue
        g.count=g.count+1
        state['jj_tag']=1

        if current_ratio >= 1.095:
            #print(f"3符合的股票{stock}昨天成交额{state['yesterday_amount']} 今日竞价额：{state['last_jjamount']}，开盘涨幅 {current_ratio:.5f}%")
            continue

        buylist1=[]
        buylist1.append(jingcb)
        buylist1.append(current_ratio)
        new_stocks1 = {
            stock:buylist1,
            }
        g.stocks_date2.update(new_stocks1)

    #print(f"符合要求的股票：{g.stocks_date2} ")

    stocks_date2 = dict(sorted(g.stocks_date2.items(), key=lambda item: item[1][1], reverse=True))  #False代表升序，True代表降序
    #print("按照股票的价格比排序：")
    for stock_code, info_list in stocks_date2.items():
        str_info_list = [str(item) for item in info_list]
        formatted_info = ', '.join(str_info_list)
        print(f"{stock_code}: [{formatted_info}]")
    raw_select = len(stocks_date2) * g.sum_xishu
    num_to_select = round(raw_select) 
    if num_to_select > g.stocknum:
        num_to_select=g.stocknum
    g.stock_jj = list(islice(stocks_date2.keys(), num_to_select))

def calculate_stock_quantity(jine, pricemai):
    """
    计算可以购买的股票数量，并确保数量是100股或其整数倍。
    
    参数:
    jine -- 可用资金 (float or int)
    pricemai -- 单股价格 (float or int)
    
    返回:
    stock_sum -- 可以购买的股票数量 (int)，保证是100的整数倍
    """
    try:
        if not (isinstance(jine, (int, float)) and isinstance(pricemai, (int, float))):
            raise ValueError("jine 和 pricemai 必须是数字类型")

        if pricemai <= 0:
            raise ValueError("买入价格必须大于0")

        # 计算理论上可以购买的最大股份数量
        theoretical_max = jine / pricemai

        # 向下取整到最接近的100股的倍数
        stock_sum = math.floor(theoretical_max / 100) * 100

        # 如果结果小于100股，则返回0
        if stock_sum < 100:
            return 0

        return stock_sum

    except ValueError as e:
        print(f"发生错误: {e}")
        return 0

# 定义判断股票类型的函数
def determine_stock_type(stock_code):
    if stock_code.endswith('.SH'):
        return 0
    elif stock_code.endswith('.SZ'):
        return 1
    else:
        raise ValueError(f"未知的股票代码后缀: {stock_code}")


def buyzaos(C,stock):
    g.jine=0
    stock_sum=0
    mid_time1 = '09:15:00'
    end_times1 =  '09:25:01'
    g.jine=cangwei(C,stock,g.zijin_num)
    trade_records = read_from_file()
    for s in  stock:
        #当前开盘价
        #price = C.get_market_data (['open'],stock_code=[s],period=C.period,dividend_type='none')
        #tick = C.get_market_data_ex([],[s], period = "tick", start_time = date_now, end_time = date_now)
        #quoute = C.get_market_data_ex([],[s],period='1m',end_time=date_now,count=1)
        #print(quoute)
        quoute = C.get_full_tick([s])
        print(quoute)
        price = quoute[s]['lastPrice']
        #latest_stime = quoute[s].index[-1]  # 获取最新时间戳
        #price = quoute[s].loc[latest_stime, 'close']  # 获取最新时间戳对应的 'close' 值
        # 确保tick是一个非空的DataFrame
        if price > 0:
            cu=C.get_instrumentdetail(s)
            pricemai=calculate_buy_price(price,s)
            if pricemai>cu['UpStopPrice']:
                pricemai=cu['UpStopPrice']
            print("股票的价格", price,"买入的金额",g.jine,"买入的价格",pricemai,"当日涨停价",cu['UpStopPrice'])
            stock_sum = calculate_stock_quantity(g.jine, pricemai)
            stock_type=determine_stock_type(s)
            if stock_type==0:
                mairu_type=44
            else:
                mairu_type=44
            if g.opType==1:
                opType=33
            else:
                opType=23
            print("mairu_type的值", mairu_type)
            if g.mairu_tag==0:
                passorder(opType, 1102, C.accountid, s, 11, float(pricemai),g.jine,'',2,'', C)
            else:
                passorder(opType, 1102, C.accountid, s, mairu_type, 0, g.jine, '',2,'',C)
            #passorder(23, 1102, C.accountid, s, 11, float(pricemai-0.05),jine,'',2,'', C) 
            #order_shares(s,stock_sum,'fix',float(pricemai),C,C.accountid)
            #order_value(s,jine,'fix',float(pricemai-0.02),C,C.accountid)
            #order_shares_num(C)
            # 将买入的股票信息添加到交易记录中
            trade_records.append({
            "code": stock,
            "buy_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            })
    # 写入新的交易记录
    print("写入文件的股票",trade_records)
    write_to_file(trade_records)


def calculate_buy_price(price, stock_code):
    """
    根据股票的最新价格和股票代码，计算买入价格。

    参数:
    - price (float): 股票的最新价格
    - stock_code (str): 股票代码，例如 '600519' 或 '300059'

    返回:
    - float: 计算后的买入价格
    """

    # 检查输入的价格是否为正数
    if price <= 0:
        raise ValueError("价格必须为正数")

    # 判断股票代码是否为主板
    if stock_code.startswith(('60', '00')):
        # 主板股票的买入规则
        if price <= 5:
            buy_price = price + 0.1
        else:
            buy_price = price * 1.015
            #buy_price = price + 0.1
    else:
        # 其他市场的股票（默认使用 1.011 的规则）
        buy_price = price * 1.015

    # 返回计算后的买入价格，保留两位小数
    return round(buy_price, 2)

def cangwei1(C,stock,num):
    value = num
    return value

def cangwei(C, stock, num):
    # 获取当前账户的可用现金
    available_cash=0
    accounts = get_trade_detail_data(C.accountid, 'stock', 'account')
    print('查询账号结果：')
    for dt in accounts:
        print(f'账户可用金额: {dt.m_dAvailable:.2f}')
        if dt.m_dAvailable > 0:
            available_cash = dt.m_dAvailable  # 可用资金
    
    # 比较设置的金额和可用现金，取较小值
    actual_amount = min(num, available_cash)
    
    # 如果可用现金不足，输出警告信息
    if available_cash < num:
        print(f"警告：策略设置的金额{num}大于账户可用现金{available_cash}，将使用账户可用现金{available_cash}进行买入")
    
    # 平均分配到每只股票
    value = actual_amount*0.97
    return value

def daily_filter(factor_series, backtest_time):
    # 将 factor_series 中值 True 的index，转化成列表
    print(len(factor_series))
    sl = factor_series[factor_series].index.tolist()
    print(len(sl))
    # exit()
    # st过滤
    sl = [s for s in sl if not is_st(s, backtest_time)]
    sl = sorted(sl, key=lambda k: factor_series.loc[k])
    return sl[:g.buy_num]


def is_st(s, date):
    # 判断某日在历史上是不是st *st
    st_dict = g.his_st.get(s, {})
    if not st_dict:
        return False
    else:
        st = st_dict.get('ST', []) + st_dict.get('*ST', [])
        for start, end in st:
            if start <= date <= end:
                return True


def rank_filter(df: pd.DataFrame, N: int, axis=1, ascending=False, method="max", na_option="keep") -> pd.DataFrame:
    """
    Args:
        df: 标准数据的df
        N: 判断是否是前N名
        axis: 默认是横向排序
        ascending : 默认是降序排序
        na_option : 默认保留nan值,但不参与排名
    Return:
        pd.DataFrame:一个全是bool值的df
    """
    _df = df.copy()

    _df = _df.rank(axis=axis, ascending=ascending, method=method, na_option=na_option)

    return _df <= N

def get_df_ex(data:dict,field:str) -> pd.DataFrame:
    '''
    ToDo:用于在使用get_market_data_ex的情况下，取到标准df
    
    Args:
        data: get_market_data_ex返回的dict
        field: ['time', 'open', 'high', 'low', 'close', 'volume','amount', 'settelementPrice', 'openInterest', 'preClose', 'suspendFlag']
        
    Return:
        一个以时间为index，标的为columns的df
    
    '''
    _index = data[list(data.keys())[0]].index.tolist()
    _columns = list(data.keys())
    df = pd.DataFrame(index=_index,columns=_columns)
    for i in _columns:
        df[i] = data[i][field]
    return df


def filter_opendate_qmt(C, df: pd.DataFrame, n: int) -> pd.DataFrame:
    '''

    ToDo: 判断传入的df.columns中，上市天数是否大于N日，返回的值是一个全是bool值的df

    Args:
        C:contextinfo类
        df:index为时间，columns为stock_code的df,目的是为了和策略中的其他df对齐
        n:用于判断上市天数的参数，如要判断是否上市120天,则填写
    Return:pd.DataFrame

    '''
    # print(df.index)
    local_df = pd.DataFrame(index=df.index, columns=df.columns)
    # print(local_df)
    # print(type(list(local_df.index)[0]))
    stock_list = df.columns
    # 这里的索引数据类型不一样
    stock_opendate = {i: str(C.get_instrumentdetail(i)["OpenDate"]) for i in stock_list}
    # stock_opendate = {i: C.get_instrumentdetail(i)["OpenDate"] for i in stock_list}
    # print(type(stock_opendate["000001.SZ"]), stock_opendate["000001.SZ"])
    # print("+================================+\n")
    
    for stock, date in stock_opendate.items():
        local_df.at[date, stock] = 1
    
    df_fill = local_df.fillna(method="ffill")

    result = df_fill.expanding().sum() >= n
    # print(result)
    return result

def get_holdings(accid, datatype):
    '''
    Arg:
        accondid:账户id
        datatype:
            'FUTURE'：期货
            'STOCK'：股票
            ......
    return:
        {股票名:{'手数':int,"持仓成本":float,'浮动盈亏':float,"可用余额":int}}
    '''
    PositionInfo_dict = {}
    resultlist = get_trade_detail_data(accid, datatype, 'POSITION')
    for obj in resultlist:
        PositionInfo_dict[obj.m_strInstrumentID + "." + obj.m_strExchangeID] = {
            "持仓数量": obj.m_nVolume,
            "持仓成本": obj.m_dOpenPrice,
            "浮动盈亏": obj.m_dFloatProfit,
            "可用余额": obj.m_nCanUseVolume
        }
    return PositionInfo_dict
    




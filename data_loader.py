"""
一进二打板策略 - 数据加载器
============================================
支持多种数据源:
  1. 本地 CSV 文件 (通过 AkShare/Tushare 预下载)
  2. AkShare 在线下载 (需要安装 akshare)
  3. 模拟数据 (用于演示和调试)
"""

import os
import datetime
import random
import math
import backtrader as bt
import config as cfg


class AStockCSVData(bt.feeds.GenericCSVData):
    """
    A股 CSV 数据加载器
    -----------------------------------------------
    预期 CSV 格式 (无需表头, 或使用 header=True):
      date, open, high, low, close, volume, turnover

    也可以通过 AkShare 或 Tushare 下载 CSV 后加载

    示例 CSV:
      2024-01-02,10.50,10.80,10.30,10.75,12345678,135000000
    """
    params = (
        ('dtformat', '%Y-%m-%d'),
        ('datetime', 0),
        ('open', 1),
        ('high', 2),
        ('low', 3),
        ('close', 4),
        ('volume', 5),
        ('openinterest', -1),
        ('headers', True),
    )


def load_csv_data(cerebro, data_dir=None, stock_codes=None,
                  fromdate=None, todate=None):
    """
    从目录批量加载 CSV 数据

    参数:
      cerebro: Backtrader Cerebro 实例
      data_dir: CSV 数据目录
      stock_codes: 指定加载的股票代码列表 (None=加载所有)
      fromdate: 开始日期 (datetime.date)
      todate: 结束日期 (datetime.date)

    CSV 文件命名规则: {stock_code}.csv
      例如: 000001.csv, 600519.csv
    """
    if data_dir is None:
        data_dir = cfg.DATA_DIR

    if not os.path.exists(data_dir):
        raise FileNotFoundError(f"数据目录不存在: {data_dir}")

    # 排除非行情文件（如 sector_map.csv）
    EXCLUDED_FILES = {'sector_map.csv'}
    csv_files = [
        f for f in os.listdir(data_dir)
        if f.endswith('.csv') and f not in EXCLUDED_FILES
    ]

    if stock_codes:
        csv_files = [f for f in csv_files
                     if f.replace('.csv', '') in stock_codes]

    loaded = 0
    for csv_file in sorted(csv_files):
        stock_code = csv_file.replace('.csv', '')
        filepath = os.path.join(data_dir, csv_file)

        try:
            data = AStockCSVData(
                dataname=filepath,
                fromdate=fromdate or datetime.datetime(2020, 1, 1),
                todate=todate or datetime.datetime(2025, 12, 31),
            )
            cerebro.adddata(data, name=stock_code)
            loaded += 1
        except Exception as e:
            print(f"[DataLoader] 加载 {stock_code} 失败: {e}")

    print(f"[DataLoader] 成功加载 {loaded} 只股票数据")
    return loaded


def download_data_akshare(stock_codes, start_date, end_date,
                          save_dir=None):
    """
    通过 AkShare 下载A股日线数据

    参数:
      stock_codes: list, 股票代码列表 (如 ['000001', '600519'])
      start_date: str, 开始日期 'YYYY-MM-DD'
      end_date: str, 结束日期 'YYYY-MM-DD'
      save_dir: str, 保存目录

    需要安装: pip install akshare
    """
    try:
        import akshare as ak
    except ImportError:
        print("请先安装 akshare: pip install akshare")
        return

    if save_dir is None:
        save_dir = cfg.DATA_DIR
    os.makedirs(save_dir, exist_ok=True)

    start_dt = start_date.replace('-', '')
    end_dt = end_date.replace('-', '')

    for code in stock_codes:
        try:
            # 判断沪深市场
            if code.startswith(('6', '9')):
                symbol = f"sh{code}"
            else:
                symbol = f"sz{code}"

            print(f"[AkShare] 下载 {code} ...")
            df = ak.stock_zh_a_hist(
                symbol=code,
                period='daily',
                start_date=start_dt,
                end_date=end_dt,
                adjust='qfq'  # 前复权
            )

            if df is not None and len(df) > 0:
                # 重命名列以匹配我们的格式
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '最高': 'high',
                    '最低': 'low',
                    '收盘': 'close',
                    '成交量': 'volume',
                    '成交额': 'amount',
                })
                df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
                filepath = os.path.join(save_dir, f'{code}.csv')
                df.to_csv(filepath, index=False)
                print(f"  ✅ {code}: {len(df)} 条记录")
            else:
                print(f"  ⚠️ {code}: 无数据")

        except Exception as e:
            print(f"  ❌ {code}: {e}")


def generate_demo_data(stock_codes=None, num_stocks=30,
                       days=250, save_dir=None):
    """
    生成模拟A股数据 (用于演示和调试)
    -----------------------------------------------
    模拟特征:
      - 随机生成涨停、跌停事件
      - 模拟板块联动效应
      - 生成合理的量价关系

    参数:
      stock_codes: 指定股票代码列表 (None = 自动生成)
      num_stocks: 股票数量 (当 stock_codes=None 时使用)
      days: 交易天数
      save_dir: 保存目录
    """
    if save_dir is None:
        save_dir = cfg.DATA_DIR
    os.makedirs(save_dir, exist_ok=True)

    # 清除旧的行情 CSV，避免多次运行时文件累积
    _EXCLUDE = {'sector_map.csv'}
    for old_file in os.listdir(save_dir):
        if old_file.endswith('.csv') and old_file not in _EXCLUDE:
            os.remove(os.path.join(save_dir, old_file))

    if stock_codes is None:
        # 生成一批模拟代码
        prefixes = ['000', '002', '300', '600', '601', '603']
        stock_codes = []
        for i in range(num_stocks):
            prefix = random.choice(prefixes)
            suffix = f"{random.randint(1, 999):03d}"
            code = f"{prefix}{suffix}"
            if code not in stock_codes:
                stock_codes.append(code)

    # 将股票分配到模拟板块
    sectors = ['新能源', '半导体', '人工智能', '医药生物', '消费电子',
               '白酒', '银行', '房地产', '军工', '汽车']
    sector_map = {}
    for i, code in enumerate(stock_codes):
        sector = sectors[i % len(sectors)]
        sector_map[code] = sector

    # 保存板块映射
    sector_file = os.path.join(save_dir, 'sector_map.csv')
    with open(sector_file, 'w', encoding='utf-8') as f:
        f.write('stock_code,sector_name\n')
        for code, sector in sector_map.items():
            f.write(f'{code},{sector}\n')

    # 生成日期序列 (排除周末)
    base_date = datetime.date(2024, 1, 2)
    dates = []
    d = base_date
    while len(dates) < days:
        if d.weekday() < 5:  # 排除周末
            dates.append(d)
        d += datetime.timedelta(days=1)

    print(f"[DemoData] 生成 {len(stock_codes)} 只模拟股票, {days} 个交易日")

    # 模拟板块联动: 某些天某个板块整体上涨
    sector_hot_days = {}
    for sector in sectors:
        hot_count = random.randint(5, 15)  # 每个板块有 5-15 个热门日
        hot_indices = random.sample(range(20, days), min(hot_count, days - 20))
        sector_hot_days[sector] = set(hot_indices)

    for code in stock_codes:
        sector = sector_map[code]
        is_gem = code.startswith(('300', '301', '688', '689'))
        limit_pct = 0.20 if is_gem else 0.10

        # 初始价格
        price = random.uniform(8, 50)
        base_volume = random.randint(5000000, 50000000)

        rows = []
        for i, date in enumerate(dates):
            # 基础随机波动
            daily_return = random.gauss(0.0005, 0.015)

            # 板块联动: 板块热门日额外加成
            if i in sector_hot_days.get(sector, set()):
                daily_return += random.uniform(0.02, 0.06)

            # 随机涨停事件 (约 2% 概率触发涨停)
            force_limit_up = random.random() < 0.02
            if force_limit_up:
                daily_return = limit_pct

            # 模拟连板: 如果前一天涨停，有 25% 概率继续涨停
            if i > 0 and len(rows) > 0:
                prev_row = rows[-1]
                prev_return = (prev_row['close'] - price) / price if i == 1 else \
                    (prev_row['close'] - rows[-2]['close']) / rows[-2]['close'] if len(rows) >= 2 else 0
                if abs(prev_return - limit_pct) < 0.005:
                    if random.random() < 0.25:
                        daily_return = limit_pct

            # 限制涨跌幅
            daily_return = max(-limit_pct, min(limit_pct, daily_return))

            prev_close = rows[-1]['close'] if rows else price

            # 生成 OHLCV
            new_close = round(prev_close * (1 + daily_return), 2)

            if abs(daily_return - limit_pct) < 0.005:
                # 涨停日: 开盘价可能就是涨停价 (一字板) 或低开拉涨停
                if random.random() < 0.3:
                    # 一字板
                    open_p = new_close
                    high_p = new_close
                    low_p = new_close
                else:
                    open_p = round(prev_close * (1 + random.uniform(0, limit_pct * 0.8)), 2)
                    high_p = new_close
                    low_p = round(min(open_p, prev_close * (1 + random.uniform(-0.02, 0.02))), 2)

                volume = int(base_volume * random.uniform(1.5, 4.0))
            elif abs(daily_return + limit_pct) < 0.005:
                # 跌停日
                open_p = round(prev_close * (1 + random.uniform(-limit_pct * 0.5, 0)), 2)
                high_p = round(max(open_p, new_close * (1 + random.uniform(0, 0.02))), 2)
                low_p = new_close
                volume = int(base_volume * random.uniform(2.0, 5.0))
            else:
                intraday_range = abs(daily_return) + random.uniform(0.005, 0.03)
                open_p = round(prev_close * (1 + random.uniform(-0.02, 0.02)), 2)
                high_p = round(max(open_p, new_close) * (1 + random.uniform(0, intraday_range / 2)), 2)
                low_p = round(min(open_p, new_close) * (1 - random.uniform(0, intraday_range / 2)), 2)
                volume = int(base_volume * random.uniform(0.5, 2.5))

            # 确保价格有效
            high_p = max(high_p, open_p, new_close)
            low_p = min(low_p, open_p, new_close)
            low_p = max(low_p, 0.01)
            new_close = max(new_close, 0.01)

            rows.append({
                'date': date.strftime('%Y-%m-%d'),
                'open': open_p,
                'high': high_p,
                'low': low_p,
                'close': new_close,
                'volume': volume,
            })

        # 写入 CSV
        filepath = os.path.join(save_dir, f'{code}.csv')
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('date,open,high,low,close,volume\n')
            for row in rows:
                f.write(f"{row['date']},{row['open']:.2f},{row['high']:.2f},"
                        f"{row['low']:.2f},{row['close']:.2f},{row['volume']}\n")

    print(f"[DemoData] ✅ 数据已保存至 {save_dir}/")
    print(f"[DemoData] ✅ 板块映射已保存至 {sector_file}")
    return stock_codes, sector_map


if __name__ == '__main__':
    # 独立运行时生成模拟数据
    codes, smap = generate_demo_data(num_stocks=30, days=250)
    print(f"\n生成的股票代码: {codes}")
    print(f"板块映射: {smap}")

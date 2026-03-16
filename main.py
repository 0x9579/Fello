"""
一进二打板策略 - 回测主入口
============================================
使用方法:
  1. 生成模拟数据:
     python main.py --demo

  2. 运行回测:
     python main.py --run

  3. 使用 AkShare 下载真实数据后回测:
     python main.py --download --codes 000001,600519,300750
     python main.py --run

  4. 完整模式 (生成数据 + 回测):
     python main.py --demo --run
"""

import argparse
import datetime
import os
import sys

import backtrader as bt

import config as cfg
from strategy import LimitUpStrategy
from data_loader import load_csv_data, generate_demo_data, download_data_akshare
from analyzers import DetailedTradeAnalyzer, DrawdownAnalyzer, SectorPerformance


def setup_cerebro(fromdate=None, todate=None, stock_codes=None):
    """
    配置并返回 Cerebro 实例
    """
    cerebro = bt.Cerebro()

    # ----- 加载数据 -----
    loaded = load_csv_data(
        cerebro,
        data_dir=cfg.DATA_DIR,
        stock_codes=stock_codes,
        fromdate=fromdate,
        todate=todate,
    )

    if loaded == 0:
        print("❌ 未加载任何数据! 请检查数据目录或先运行 --demo 生成模拟数据")
        sys.exit(1)

    # ----- 添加策略 -----
    cerebro.addstrategy(LimitUpStrategy)

    # ----- 资金设置 -----
    cerebro.broker.setcash(cfg.INITIAL_CASH)

    # ----- 佣金设置 -----
    cerebro.broker.setcommission(commission=cfg.COMMISSION)

    # ----- 滑点设置 -----
    cerebro.broker.set_slippage_perc(cfg.SLIPPAGE_PCT)

    # ----- 添加分析器 -----
    cerebro.addanalyzer(DetailedTradeAnalyzer, _name='detailed_trades')
    cerebro.addanalyzer(DrawdownAnalyzer, _name='drawdown')
    cerebro.addanalyzer(SectorPerformance, _name='sector_perf')
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe',
                        timeframe=bt.TimeFrame.Days, compression=1)
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')

    return cerebro


def print_results(results):
    """
    打印回测结果
    """
    strat = results[0]

    print(f"\n{'='*70}")
    print(f"  📊 详细回测分析报告")
    print(f"{'='*70}")

    # ----- 交易统计 -----
    trade_analysis = strat.analyzers.detailed_trades.get_analysis()
    print(f"\n  【交易统计】")
    print(f"  ├── 总交易次数:     {trade_analysis['total']}")
    print(f"  ├── 盈利次数:       {trade_analysis['won']}")
    print(f"  ├── 亏损次数:       {trade_analysis['lost']}")
    print(f"  ├── 胜率:           {trade_analysis['win_rate']:.1f}%")
    print(f"  ├── 总盈亏:         {trade_analysis.get('total_pnl', 0):,.2f}")
    print(f"  ├── 平均每笔盈亏:   {trade_analysis['avg_pnl']:,.2f}")
    print(f"  ├── 平均盈利:       {trade_analysis['avg_win']:,.2f}")
    print(f"  ├── 平均亏损:       {trade_analysis['avg_loss']:,.2f}")
    print(f"  ├── 最大单笔盈利:   {trade_analysis['max_win']:,.2f}")
    print(f"  ├── 最大单笔亏损:   {trade_analysis['max_loss']:,.2f}")
    print(f"  ├── 盈亏比:         {trade_analysis['profit_factor']:.2f}")
    print(f"  ├── 平均持仓天数:   {trade_analysis['avg_bars']:.1f}")
    print(f"  └── 总手续费:       {trade_analysis['total_commission']:,.2f}")

    # ----- 回撤分析 -----
    dd_analysis = strat.analyzers.drawdown.get_analysis()
    print(f"\n  【回撤分析】")
    print(f"  ├── 最大回撤金额:   {dd_analysis['max_drawdown']:,.2f}")
    print(f"  ├── 最大回撤比例:   {dd_analysis['max_drawdown_pct']:.2f}%")
    print(f"  └── 最长回撤天数:   {dd_analysis['max_drawdown_duration']}")

    # ----- 收益分析 -----
    returns = strat.analyzers.returns.get_analysis()
    sharpe = strat.analyzers.sharpe.get_analysis()
    print(f"\n  【收益分析】")
    total_return = returns.get('rtot', 0) * 100
    print(f"  ├── 总收益率:       {total_return:.2f}%")
    avg_daily = returns.get('ravg', 0) * 100
    print(f"  ├── 日均收益率:     {avg_daily:.4f}%")
    annualized = ((1 + returns.get('rtot', 0)) ** (252 / max(returns.get('len', 1), 1)) - 1) * 100
    print(f"  ├── 年化收益率:     {annualized:.2f}%")
    sharpe_ratio = sharpe.get('sharperatio', 0) or 0
    print(f"  └── 夏普比率:       {sharpe_ratio:.4f}")

    # ----- 板块交易分析 -----
    sector_analysis = strat.analyzers.sector_perf.get_analysis()
    if sector_analysis:
        print(f"\n  【板块交易表现】")
        sorted_sectors = sorted(sector_analysis.items(),
                                key=lambda x: x[1]['total_pnl'], reverse=True)
        for sector, info in sorted_sectors:
            emoji = "🟢" if info['total_pnl'] > 0 else "🔴"
            print(f"  {emoji} {sector:<10} | "
                  f"交易{info['total']}次 | "
                  f"胜率{info['win_rate']:.0f}% | "
                  f"盈亏{info['total_pnl']:+,.0f}")

    print(f"\n{'='*70}\n")


# MA60 需要60根K线预热，真正产生交易信号至少还需要若干天，因此设置下限
MIN_DAYS_REQUIRED = 65


def run_backtest(fromdate=None, todate=None, stock_codes=None, plot=False):
    """
    执行回测
    """
    print(f"\n{'='*70}")
    print(f"  🚀 开始运行一进二打板策略回测")
    print(f"{'='*70}")

    if fromdate:
        print(f"  起始日期: {fromdate}")
    if todate:
        print(f"  结束日期: {todate}")
    print(f"  初始资金: {cfg.INITIAL_CASH:,.0f}")
    print(f"  佣金费率: {cfg.COMMISSION*10000:.0f} 万分之")
    print(f"  滑点: {cfg.SLIPPAGE_PCT*100:.1f}%")
    print(f"{'='*70}\n")

    cerebro = setup_cerebro(
        fromdate=fromdate,
        todate=todate,
        stock_codes=stock_codes,
    )

    results = cerebro.run()
    print_results(results)

    if plot:
        try:
            cerebro.plot(style='candlestick', volume=True)
        except Exception as e:
            print(f"绘图失败: {e}")
            print("提示: 多股票回测时绘图可能不支持，可忽略此错误")


def main():
    parser = argparse.ArgumentParser(
        description='一进二打板策略回测系统',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py --demo                          生成模拟数据
  python main.py --run                           运行回测
  python main.py --demo --run                    生成模拟数据并回测
  python main.py --demo --run --stocks 20        生成20只模拟股票并回测
  python main.py --run --from 2024-03-01         指定起始日期
  python main.py --download --codes 000001,600519  用 AkShare 下载真实数据
        """
    )

    parser.add_argument('--demo', action='store_true',
                        help='生成模拟数据')
    parser.add_argument('--run', action='store_true',
                        help='运行回测')
    parser.add_argument('--download', action='store_true',
                        help='从 AkShare 下载真实数据')
    parser.add_argument('--codes', type=str, default='',
                        help='股票代码列表 (逗号分隔)')
    parser.add_argument('--stocks', type=int, default=30,
                        help='模拟股票数量 (默认30)')
    parser.add_argument('--days', type=int, default=250,
                        help='模拟交易天数 (默认250)')
    parser.add_argument('--from', dest='fromdate', type=str, default='',
                        help='回测起始日期 (YYYY-MM-DD)')
    parser.add_argument('--to', dest='todate', type=str, default='',
                        help='回测结束日期 (YYYY-MM-DD)')
    parser.add_argument('--plot', action='store_true',
                        help='是否绘制回测图表')

    args = parser.parse_args()

    # 如果没有任何参数，默认 demo + run
    if not args.demo and not args.run and not args.download:
        args.demo = True
        args.run = True

    # ----- 下载数据 -----
    if args.download:
        if not args.codes:
            print("请指定股票代码: --codes 000001,600519,300750")
            sys.exit(1)

        codes = [c.strip() for c in args.codes.split(',')]
        start = args.fromdate or '2024-01-01'
        end = args.todate or '2025-12-31'
        download_data_akshare(codes, start, end)

    # ----- 生成模拟数据 -----
    if args.demo:
        if args.days < MIN_DAYS_REQUIRED:
            print(f"\n⚠️  警告: --days 参数为 {args.days}，低于最小要求 {MIN_DAYS_REQUIRED} 天。")
            print(f"   原因: MA60 指标需要 60 根 K 线预热，之后还需要足够天数产生交易信号。")
            print(f"   已自动调整为 {MIN_DAYS_REQUIRED} 天。\n")
            args.days = MIN_DAYS_REQUIRED
        if args.codes:
            codes = [c.strip() for c in args.codes.split(',')]
            generate_demo_data(stock_codes=codes, days=args.days)
        else:
            generate_demo_data(num_stocks=args.stocks, days=args.days)

    # ----- 运行回测 -----
    if args.run:
        fromdate = None
        todate = None
        stock_codes = None

        if args.fromdate:
            fromdate = datetime.datetime.strptime(args.fromdate, '%Y-%m-%d')
        if args.todate:
            todate = datetime.datetime.strptime(args.todate, '%Y-%m-%d')
        if args.codes:
            stock_codes = [c.strip() for c in args.codes.split(',')]

        run_backtest(
            fromdate=fromdate,
            todate=todate,
            stock_codes=stock_codes,
            plot=args.plot,
        )


if __name__ == '__main__':
    main()

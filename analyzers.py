"""
一进二打板策略 - 自定义分析器
============================================
用于评估策略表现的 Backtrader 分析器:
  - TradeAnalyzer: 交易明细与统计
  - DailyReturn: 每日收益率
  - DrawdownAnalyzer: 最大回撤分析
"""

import backtrader as bt
from collections import defaultdict


class DetailedTradeAnalyzer(bt.Analyzer):
    """
    详细交易分析器
    -----------------------------------------------
    记录每笔交易的完整信息，并统计:
      - 总交易次数
      - 胜率
      - 平均盈利 / 平均亏损
      - 最大单笔盈利 / 亏损
      - 盈亏比
      - 连续盈利/亏损次数
    """

    def __init__(self):
        self.trades = []
        self.open_trades = {}

    def notify_trade(self, trade):
        if trade.isclosed:
            self.trades.append({
                'code': trade.data._name,
                'pnl': trade.pnl,
                'pnlcomm': trade.pnlcomm,
                'barlen': trade.barlen,
                'size': trade.size,
                'price': trade.price,
                'value': trade.value,
                'commission': trade.commission,
            })

    def get_analysis(self):
        if not self.trades:
            return {
                'total': 0,
                'won': 0,
                'lost': 0,
                'win_rate': 0,
                'avg_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'max_win': 0,
                'max_loss': 0,
                'profit_factor': 0,
                'avg_bars': 0,
                'total_commission': 0,
            }

        won = [t for t in self.trades if t['pnlcomm'] > 0]
        lost = [t for t in self.trades if t['pnlcomm'] <= 0]

        total_pnl = sum(t['pnlcomm'] for t in self.trades)
        total_commission = sum(t['commission'] for t in self.trades)

        avg_win = sum(t['pnlcomm'] for t in won) / len(won) if won else 0
        avg_loss = sum(t['pnlcomm'] for t in lost) / len(lost) if lost else 0

        total_wins = sum(t['pnlcomm'] for t in won)
        total_losses = abs(sum(t['pnlcomm'] for t in lost))

        return {
            'total': len(self.trades),
            'won': len(won),
            'lost': len(lost),
            'win_rate': len(won) / len(self.trades) * 100 if self.trades else 0,
            'total_pnl': total_pnl,
            'avg_pnl': total_pnl / len(self.trades) if self.trades else 0,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'max_win': max((t['pnlcomm'] for t in self.trades), default=0),
            'max_loss': min((t['pnlcomm'] for t in self.trades), default=0),
            'profit_factor': total_wins / total_losses if total_losses > 0 else float('inf'),
            'avg_bars': sum(t['barlen'] for t in self.trades) / len(self.trades),
            'total_commission': total_commission,
            'trades': self.trades,
        }


class DrawdownAnalyzer(bt.Analyzer):
    """
    回撤分析器
    -----------------------------------------------
    跟踪最大回撤和回撤持续时间
    """

    def __init__(self):
        self.peak = 0
        self.max_dd = 0
        self.max_dd_pct = 0
        self.dd_duration = 0
        self.max_dd_duration = 0
        self._in_drawdown = False

    def next(self):
        value = self.strategy.broker.getvalue()

        if value > self.peak:
            self.peak = value
            self._in_drawdown = False
            self.dd_duration = 0
        else:
            self._in_drawdown = True
            self.dd_duration += 1
            self.max_dd_duration = max(self.max_dd_duration, self.dd_duration)

            dd = self.peak - value
            dd_pct = dd / self.peak * 100 if self.peak > 0 else 0

            if dd > self.max_dd:
                self.max_dd = dd
            if dd_pct > self.max_dd_pct:
                self.max_dd_pct = dd_pct

    def get_analysis(self):
        return {
            'max_drawdown': self.max_dd,
            'max_drawdown_pct': self.max_dd_pct,
            'max_drawdown_duration': self.max_dd_duration,
        }


class SectorPerformance(bt.Analyzer):
    """
    板块维度的交易表现分析
    -----------------------------------------------
    按板块统计交易的胜率和收益
    """

    def __init__(self):
        self.sector_trades = defaultdict(list)

    def notify_trade(self, trade):
        if trade.isclosed:
            code = trade.data._name
            # 尝试从策略中获取板块信息
            sector = '未知'
            if hasattr(self.strategy, 'sector_analyzer'):
                sectors = self.strategy.sector_analyzer.stock_sectors.get(code, [])
                if sectors:
                    sector = sectors[0]

            self.sector_trades[sector].append({
                'code': code,
                'pnl': trade.pnlcomm,
            })

    def get_analysis(self):
        result = {}
        for sector, trades in self.sector_trades.items():
            won = [t for t in trades if t['pnl'] > 0]
            total_pnl = sum(t['pnl'] for t in trades)
            result[sector] = {
                'total': len(trades),
                'won': len(won),
                'win_rate': len(won) / len(trades) * 100 if trades else 0,
                'total_pnl': total_pnl,
            }
        return result

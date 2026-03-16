"""
一进二打板策略 - Backtrader 核心策略
============================================
核心逻辑:
  1. 每日扫描所有股票，找出当日涨停的股票
  2. 对涨停股进行多维度评分
  3. 按综合得分排序，选出得分最高的N只
  4. 次日开盘买入 (模拟打板 / 排板)
  5. 按止损止盈和最大持有天数规则卖出

适用场景:
  - 市场情绪较好时，一进二成功率较高
  - 热门板块的龙头股一进二概率更大
  - 涨停质量好(封板早、不开板)的连板概率更高
"""

import backtrader as bt
import config as cfg
from indicators import (LimitUpDetector, LimitUpQuality,
                         VolumeFeature, TrendStrength, TurnoverRate)
from sector_heat import SectorHeatAnalyzer
from scoring import MarketSentiment, StockScorer, rank_candidates, \
    filter_candidates, format_report


class LimitUpStrategy(bt.Strategy):
    """
    一进二打板策略 (Backtrader Strategy)
    -----------------------------------------------
    工作流程 (每个交易日):
      1. prenext / next: 等待足够的数据预热
      2. 扫描全市场涨停股
      3. 计算市场情绪得分
      4. 更新板块热度
      5. 对涨停股逐一评分
      6. 排序、筛选候选
      7. 生成买入信号
      8. 检查持仓止损止盈
    """
    params = (
        # 涨停相关
        ('limit_pct_main', cfg.LIMIT_UP_PCT_MAIN),
        ('limit_pct_gem', cfg.LIMIT_UP_PCT_GEM),
        ('limit_tolerance', cfg.LIMIT_TOLERANCE),
        # 仓位管理
        ('max_position_pct', cfg.MAX_POSITION_PCT),
        ('max_holdings', cfg.MAX_HOLDINGS),
        ('max_buy_per_day', cfg.MAX_BUY_PER_DAY),
        # 止损止盈
        ('stop_loss_pct', cfg.STOP_LOSS_PCT),
        ('take_profit_pct', cfg.TAKE_PROFIT_PCT),
        ('max_hold_days', cfg.MAX_HOLD_DAYS),
        # 板块映射
        ('sector_map_file', cfg.SECTOR_MAP_FILE),
        # 最低买入评分
        ('min_buy_score', 50),
        # 是否打印详细日志
        ('verbose', True),
    )

    def __init__(self):
        # ----- 板块热度分析器 -----
        self.sector_analyzer = SectorHeatAnalyzer()
        self.sector_analyzer.load_sector_map(self.p.sector_map_file)

        # ----- 市场情绪分析器 -----
        self.market_sentiment = MarketSentiment()

        # ----- 综合评分器 -----
        self.scorer = StockScorer()

        # ----- 为每只股票创建指标 -----
        self.stock_indicators = {}
        for data in self.datas:
            code = data._name
            is_gem = code.startswith(('300', '301', '688', '689'))
            limit_pct = self.p.limit_pct_gem if is_gem else self.p.limit_pct_main

            inds = {}
            inds['limit_detector'] = LimitUpDetector(
                data, limit_pct=limit_pct, tolerance=self.p.limit_tolerance
            )
            inds['limit_quality'] = LimitUpQuality(
                data, limit_pct=limit_pct, tolerance=self.p.limit_tolerance
            )
            inds['volume_feature'] = VolumeFeature(data)
            inds['trend_strength'] = TrendStrength(data)
            inds['turnover'] = TurnoverRate(data)

            self.stock_indicators[code] = inds

        # ----- 持仓管理 -----
        # {stock_code: {'entry_date': datetime, 'entry_price': float, 'hold_days': int}}
        self.holdings = {}

        # ----- 交易日志 -----
        self.trade_log = []
        self.daily_reports = []

        # ----- 统计 -----
        self.total_trades = 0
        self.win_trades = 0
        self.loss_trades = 0

    def next(self):
        current_date = self.datas[0].datetime.date(0)

        # ===== STEP 1: 扫描全市场，收集涨停信息 =====
        stock_performances = {}
        limit_up_stocks = []
        total_up = 0
        total_down = 0
        total_limit_up = 0
        total_limit_down = 0
        max_consecutive = 0

        for data in self.datas:
            code = data._name
            inds = self.stock_indicators.get(code)
            if inds is None:
                continue

            # 确保有足够的数据访问前一根K线 (close[-1])
            # 指标自身的合法性已由 Backtrader _runonce 阶段保证
            if len(data) < 2:
                continue

            pct_change = inds['limit_detector'].limit_up_pct[0]
            is_limit_up = inds['limit_detector'].is_limit_up[0] > 0.5
            is_prev_limit = inds['limit_detector'].prev_limit_up[0] > 0.5

            # 统计涨跌
            if pct_change > 0:
                total_up += 1
            elif pct_change < 0:
                total_down += 1

            # 判定涨停/跌停
            is_gem = code.startswith(('300', '301', '688', '689'))
            limit_pct = self.p.limit_pct_gem if is_gem else self.p.limit_pct_main

            if is_limit_up:
                total_limit_up += 1
            if pct_change <= -(limit_pct - self.p.limit_tolerance):
                total_limit_down += 1

            # 连板判断
            if is_limit_up and is_prev_limit:
                # 至少2连板，检查更高连板
                consec = 2
                for j in range(2, min(10, len(data))):
                    if len(data) > j:
                        try:
                            prev_pct = (data.close[-j] - data.close[-(j+1)]) / data.close[-(j+1)]
                            if prev_pct >= (limit_pct - self.p.limit_tolerance):
                                consec += 1
                            else:
                                break
                        except (IndexError, ZeroDivisionError):
                            break
                max_consecutive = max(max_consecutive, consec)

            stock_performances[code] = {
                'pct_change': pct_change,
                'is_limit_up': is_limit_up,
                'is_prev_limit_up': is_prev_limit,
            }

            # 收集当日涨停股 (只关注"首板"涨停，即前一日非涨停)
            if is_limit_up and not is_prev_limit:
                limit_up_stocks.append(code)

        # ===== STEP 2: 更新市场情绪 =====
        self.market_sentiment.update(current_date, {
            'limit_up_count': total_limit_up,
            'limit_down_count': total_limit_down,
            'failed_limit_count': 0,  # 日线级别无法精确判断炸板
            'max_consecutive': max_consecutive,
            'up_count': total_up,
            'down_count': total_down,
        })
        sentiment_score = self.market_sentiment.get_score()

        # ===== STEP 3: 更新板块热度 =====
        self.sector_analyzer.update_daily(current_date, stock_performances)

        # ===== STEP 4: 检查现有持仓 (止损/止盈/超时) =====
        self._check_holdings(current_date)

        # ===== STEP 5: 对首板涨停股评分 =====
        candidates = []
        for code in limit_up_stocks:
            inds = self.stock_indicators[code]

            # 各维度得分
            limit_quality_score = inds['limit_quality'].quality_score[0]
            trend_score = inds['trend_strength'].trend_score[0]
            volume_score = inds['volume_feature'].vol_score[0]
            turnover_score = inds['turnover'].turnover_score[0]

            # 技术面综合 = 趋势 * 0.6 + 换手率 * 0.4
            technical_score = trend_score * 0.6 + turnover_score * 0.4

            # 板块热度
            sector_score, sector_name = self.sector_analyzer.get_sector_score(code)

            # 生成详细报告
            report = self.scorer.get_detail_report(
                stock_code=code,
                limit_quality_score=limit_quality_score,
                technical_score=technical_score,
                volume_score=volume_score,
                sector_score=sector_score,
                sentiment_score=sentiment_score,
                sector_name=sector_name,
            )
            candidates.append(report)

        # ===== STEP 6: 排序和筛选 =====
        candidates = filter_candidates(candidates, min_score=self.p.min_buy_score)
        candidates = rank_candidates(candidates)

        # 打印报告
        if candidates and self.p.verbose:
            report_str = format_report(candidates, date=current_date)
            self.log(report_str)
            self.daily_reports.append({
                'date': current_date,
                'candidates': candidates,
                'sentiment': sentiment_score,
            })

        # ===== STEP 7: 生成买入信号 =====
        if self.market_sentiment.is_tradeable():
            self._generate_buy_signals(candidates, current_date)
        elif candidates and self.p.verbose:
            self.log(f"  ⛔ 市场情绪不佳 (得分={sentiment_score:.0f}), 今日不操作")

    def _check_holdings(self, current_date):
        """
        检查持仓，执行止损/止盈/超时卖出
        """
        codes_to_sell = []

        for code, info in self.holdings.items():
            data = self._get_data_by_name(code)
            if data is None:
                continue

            current_price = data.close[0]
            entry_price = info['entry_price']
            hold_days = info['hold_days']
            pnl_pct = (current_price - entry_price) / entry_price

            sell_reason = None

            # 止损
            if pnl_pct <= self.p.stop_loss_pct:
                sell_reason = f'止损 ({pnl_pct:.1%})'

            # 止盈
            elif pnl_pct >= self.p.take_profit_pct:
                sell_reason = f'止盈 ({pnl_pct:.1%})'

            # 超时卖出
            elif hold_days >= self.p.max_hold_days:
                sell_reason = f'持股超{self.p.max_hold_days}天 ({pnl_pct:.1%})'

            # 未涨停且已持有1天以上，可考虑卖出
            elif hold_days >= 1:
                is_gem = code.startswith(('300', '301', '688', '689'))
                limit_pct = self.p.limit_pct_gem if is_gem else self.p.limit_pct_main
                daily_pct = (data.close[0] - data.close[-1]) / data.close[-1] if len(data) > 1 else 0

                # 买入次日未能涨停(二板失败)则卖出
                if hold_days == 1 and daily_pct < (limit_pct - self.p.limit_tolerance):
                    sell_reason = f'次日未封板 (涨幅{daily_pct:.1%})'

            if sell_reason:
                codes_to_sell.append((code, sell_reason, pnl_pct))

        # 执行卖出
        for code, reason, pnl_pct in codes_to_sell:
            data = self._get_data_by_name(code)
            if data is not None:
                pos = self.getposition(data)
                if pos.size > 0:
                    self.sell(data=data, size=pos.size)
                    if self.p.verbose:
                        self.log(f"  🔴 卖出 {code} | 原因: {reason}")

                    # 统计胜率
                    self.total_trades += 1
                    if pnl_pct > 0:
                        self.win_trades += 1
                    else:
                        self.loss_trades += 1

                    self.trade_log.append({
                        'action': 'SELL',
                        'code': code,
                        'date': self.datas[0].datetime.date(0),
                        'reason': reason,
                        'pnl_pct': pnl_pct,
                    })

            if code in self.holdings:
                del self.holdings[code]

        # 更新持有天数
        for code in self.holdings:
            self.holdings[code]['hold_days'] += 1

    def _generate_buy_signals(self, candidates, current_date):
        """
        根据评分排名生成买入信号

        买入逻辑:
          - 选取评分最高的N只 (N = max_buy_per_day)
          - 检查是否已满仓
          - 等比分配资金
        """
        current_holdings = len(self.holdings)
        available_slots = self.p.max_holdings - current_holdings

        if available_slots <= 0:
            return

        buy_count = min(
            len(candidates),
            self.p.max_buy_per_day,
            available_slots,
        )

        if buy_count <= 0:
            return

        # 计算每只股票可用资金
        total_value = self.broker.getvalue()
        cash = self.broker.getcash()
        per_stock_cash = min(
            cash / buy_count,
            total_value * self.p.max_position_pct,
        )

        for i in range(buy_count):
            c = candidates[i]
            code = c['code']

            # 跳过已持仓的
            if code in self.holdings:
                continue

            data = self._get_data_by_name(code)
            if data is None:
                continue

            # 计算可买数量 (A股最少100股，买入以手为单位)
            current_price = data.close[0]
            if current_price <= 0:
                continue

            # 预估次日开盘价 (涨停股次日可能高开)
            estimated_price = current_price * 1.03  # 预留3%高开空间
            size = int(per_stock_cash / estimated_price / 100) * 100

            if size >= 100:
                self.buy(data=data, size=size)

                self.holdings[code] = {
                    'entry_date': current_date,
                    'entry_price': current_price,  # 实际成交价由 notify_order 更新
                    'hold_days': 0,
                    'score': c['final_score'],
                }

                if self.p.verbose:
                    self.log(f"  🟢 买入 {code} | 评分={c['final_score']:.1f} | "
                             f"数量={size}股 | 板块={c.get('sector', '')}")

                self.trade_log.append({
                    'action': 'BUY',
                    'code': code,
                    'date': current_date,
                    'score': c['final_score'],
                    'size': size,
                })

    def _get_data_by_name(self, name):
        """根据名称查找 data feed"""
        for data in self.datas:
            if data._name == name:
                return data
        return None

    def notify_order(self, order):
        """订单状态通知"""
        if order.status in [order.Completed]:
            code = order.data._name
            if order.isbuy():
                # 更新实际成交价
                if code in self.holdings:
                    self.holdings[code]['entry_price'] = order.executed.price
                if self.p.verbose:
                    self.log(f"    ✅ {code} 买入成交 | "
                             f"价格={order.executed.price:.2f} | "
                             f"数量={order.executed.size:.0f}")
            else:
                if self.p.verbose:
                    self.log(f"    ✅ {code} 卖出成交 | "
                             f"价格={order.executed.price:.2f} | "
                             f"数量={order.executed.size:.0f}")

        elif order.status in [order.Canceled, order.Margin, order.Rejected]:
            if self.p.verbose:
                code = order.data._name
                self.log(f"    ❌ {code} 订单失败: {order.getstatusname()}")
            # 如果买入失败，移除持仓记录
            code = order.data._name
            if code in self.holdings and order.isbuy():
                del self.holdings[code]

    def notify_trade(self, trade):
        """交易关闭通知"""
        if trade.isclosed:
            if self.p.verbose:
                self.log(f"    💰 {trade.data._name} 交易完成 | "
                         f"盈亏={trade.pnl:.2f} | "
                         f"净盈亏={trade.pnlcomm:.2f}")

    def log(self, msg):
        """策略日志"""
        dt = self.datas[0].datetime.date(0)
        print(f'[{dt}] {msg}')

    def stop(self):
        """策略结束时输出统计"""
        print(f"\n{'='*70}")
        print(f"  📈 一进二打板策略回测结果")
        print(f"{'='*70}")
        print(f"  总交易次数: {self.total_trades}")
        print(f"  胜出次数:   {self.win_trades}")
        print(f"  亏损次数:   {self.loss_trades}")
        if self.total_trades > 0:
            win_rate = self.win_trades / self.total_trades * 100
            print(f"  胜率:       {win_rate:.1f}%")
        print(f"  最终资金:   {self.broker.getvalue():,.2f}")
        print(f"  初始资金:   {cfg.INITIAL_CASH:,.2f}")
        total_return = (self.broker.getvalue() - cfg.INITIAL_CASH) / cfg.INITIAL_CASH * 100
        print(f"  总收益率:   {total_return:.2f}%")
        print(f"{'='*70}\n")

"""
一进二打板策略 - 自定义技术指标
============================================
包含:
  - LimitUpDetector: 涨停板检测指标
  - LimitUpQuality: 涨停质量评估
  - VolumeFeature: 成交量特征指标
  - TrendStrength: 趋势强度指标
"""

import backtrader as bt
import config as cfg


class LimitUpDetector(bt.Indicator):
    """
    涨停检测指标
    -----------------------------------------------
    检测当日是否涨停(收盘价 >= 前日收盘价 * (1 + 涨停幅度))

    输出线:
      - is_limit_up: 1 = 涨停, 0 = 未涨停
      - limit_up_pct: 当日涨幅
      - prev_limit_up: 前一日是否涨停 (用于判断连板)
    """
    lines = ('is_limit_up', 'limit_up_pct', 'prev_limit_up',)
    params = (
        ('limit_pct', cfg.LIMIT_UP_PCT_MAIN),
        ('tolerance', cfg.LIMIT_TOLERANCE),
    )

    def __init__(self):
        # 计算涨幅
        self.lines.limit_up_pct = (self.data.close - self.data.close(-1)) / self.data.close(-1)

    def next(self):
        pct_change = self.lines.limit_up_pct[0]
        limit_threshold = self.p.limit_pct - self.p.tolerance

        # 当日是否涨停
        self.lines.is_limit_up[0] = 1.0 if pct_change >= limit_threshold else 0.0

        # 前一日是否涨停 (需要至少2根K线)
        if len(self) >= 2:
            prev_pct = (self.data.close[-1] - self.data.close[-2]) / self.data.close[-2]
            self.lines.prev_limit_up[0] = 1.0 if prev_pct >= limit_threshold else 0.0
        else:
            self.lines.prev_limit_up[0] = 0.0


class LimitUpQuality(bt.Indicator):
    """
    涨停质量评估指标
    -----------------------------------------------
    从多个维度评估涨停的质量:
      1. 涨停强度: 收盘价是否紧贴涨停价 (一字板 > T字板 > 普通涨停)
      2. 量价配合: 涨停时的成交量是否合理
      3. 上影线长度: 上影线越短越好 (说明封板稳固)

    输出线:
      - quality_score: 综合质量评分 (0-100)
    """
    lines = ('quality_score',)
    params = (
        ('limit_pct', cfg.LIMIT_UP_PCT_MAIN),
        ('tolerance', cfg.LIMIT_TOLERANCE),
    )

    def next(self):
        if len(self) < 2:
            self.lines.quality_score[0] = 0.0
            return

        close = self.data.close[0]
        open_price = self.data.open[0]
        high = self.data.high[0]
        low = self.data.low[0]
        prev_close = self.data.close[-1]

        pct_change = (close - prev_close) / prev_close
        limit_threshold = self.p.limit_pct - self.p.tolerance

        if pct_change < limit_threshold:
            self.lines.quality_score[0] = 0.0
            return

        score = 0.0
        limit_price = prev_close * (1 + self.p.limit_pct)

        # ------ 1. 封板形态评分 (0-40分) ------
        # 一字板: 开盘即涨停，全天无波动
        price_range = high - low
        if price_range < prev_close * 0.001:
            # 一字涨停 (最强)
            score += 40
        elif abs(open_price - limit_price) / prev_close < 0.005:
            # T字板: 开盘即涨停，盘中有开板但收回
            score += 30
        else:
            # 普通涨停: 盘中拉升封板
            # 开盘涨幅越大，说明越强
            open_pct = (open_price - prev_close) / prev_close
            score += max(10, min(25, open_pct / self.p.limit_pct * 25))

        # ------ 2. 上影线评分 (0-30分) ------
        # 上影线长度占涨停价的比例
        upper_shadow = high - close
        upper_shadow_ratio = upper_shadow / prev_close if prev_close > 0 else 0

        if upper_shadow_ratio < 0.001:
            score += 30  # 几乎没有上影线
        elif upper_shadow_ratio < 0.005:
            score += 20
        elif upper_shadow_ratio < 0.01:
            score += 10
        else:
            score += 0   # 上影线较长，封板不稳

        # ------ 3. 振幅评分 (0-30分) ------
        # 振幅越小说明封板越稳
        amplitude = (high - low) / prev_close
        if amplitude < 0.02:
            score += 30  # 振幅很小，一字板特征
        elif amplitude < 0.05:
            score += 20
        elif amplitude < 0.08:
            score += 10
        else:
            score += 5

        self.lines.quality_score[0] = min(100.0, score)


class VolumeFeature(bt.Indicator):
    """
    成交量特征指标
    -----------------------------------------------
    分析成交量的状态:
      - 相对前N日均量的放大/缩小倍数
      - 量能趋势

    输出线:
      - vol_ratio: 当日成交量 / N日均量
      - vol_score: 成交量评分 (0-100)
    """
    lines = ('vol_ratio', 'vol_score',)
    params = (
        ('vol_ma_period', cfg.VOL_MA_PERIOD),
        ('amplify_ratio', cfg.VOL_AMPLIFY_RATIO),
    )

    def __init__(self):
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.vol_ma_period)

    def next(self):
        if self.vol_ma[0] > 0:
            self.lines.vol_ratio[0] = self.data.volume[0] / self.vol_ma[0]
        else:
            self.lines.vol_ratio[0] = 1.0

        ratio = self.lines.vol_ratio[0]
        score = 0.0

        # 量能评分逻辑:
        # 一进二理想的成交量: 适度放量(1.5-3倍)
        # 缩量涨停(< 1.0倍): 筹码锁定好，给高分
        # 温和放量(1.0-2.0倍): 正常健康换手
        # 过度放量(> 3.0倍): 分歧较大，给低分
        if ratio < 0.5:
            score = 40   # 极度缩量，可能是一字板
        elif ratio < 1.0:
            score = 70   # 缩量涨停，筹码锁定
        elif ratio < 1.5:
            score = 85   # 温和放量
        elif ratio < 2.5:
            score = 75   # 适度放量
        elif ratio < 4.0:
            score = 50   # 放量较大，有分歧
        else:
            score = 25   # 巨量涨停，抛压大

        self.lines.vol_score[0] = score


class TrendStrength(bt.Indicator):
    """
    趋势强度评估指标
    -----------------------------------------------
    综合均线排列、MACD状态、近期涨幅等评估趋势

    输出线:
      - trend_score: 趋势评分 (0-100)
      - ma_alignment: 均线多头排列程度 (0=空头, 1=多头)
    """
    lines = ('trend_score', 'ma_alignment',)
    params = (
        ('ma_periods', cfg.MA_PERIODS),
        ('macd_fast', cfg.MACD_FAST),
        ('macd_slow', cfg.MACD_SLOW),
        ('macd_signal', cfg.MACD_SIGNAL),
    )

    def __init__(self):
        self.mas = []
        for period in self.p.ma_periods:
            ma = bt.indicators.SMA(self.data.close, period=period)
            self.mas.append(ma)

        self.macd = bt.indicators.MACD(
            self.data.close,
            period_me1=self.p.macd_fast,
            period_me2=self.p.macd_slow,
            period_signal=self.p.macd_signal,
        )

    def next(self):
        score = 0.0

        # ------ 1. 均线多头排列评分 (0-40分) ------
        # 检查均线是否按 MA5 > MA10 > MA20 > MA60 排列
        alignment_count = 0
        total_pairs = 0
        for i in range(len(self.mas) - 1):
            total_pairs += 1
            if self.mas[i][0] > self.mas[i + 1][0]:
                alignment_count += 1

        if total_pairs > 0:
            alignment_ratio = alignment_count / total_pairs
        else:
            alignment_ratio = 0

        self.lines.ma_alignment[0] = alignment_ratio
        score += alignment_ratio * 40

        # ------ 2. 价格与均线关系 (0-20分) ------
        # 收盘价在所有均线之上
        above_count = sum(1 for ma in self.mas if self.data.close[0] > ma[0])
        score += (above_count / len(self.mas)) * 20

        # ------ 3. MACD 状态评分 (0-20分) ------
        macd_val = self.macd.macd[0]
        signal_val = self.macd.signal[0]

        if macd_val > 0 and macd_val > signal_val:
            score += 20  # MACD在零轴上方且金叉
        elif macd_val > 0:
            score += 15  # MACD在零轴上方
        elif macd_val > signal_val:
            score += 10  # MACD金叉但在零轴下方
        else:
            score += 0   # MACD空头排列

        # ------ 4. 近期涨幅趋势 (0-20分) ------
        # 最近5日累计涨幅
        if len(self) > 5 and self.data.close[-5] > 0:
            recent_gain = (self.data.close[0] - self.data.close[-5]) / self.data.close[-5]
            if 0 < recent_gain < 0.15:
                score += 15  # 温和上涨趋势
            elif recent_gain >= 0.15:
                score += 20  # 强势上涨
            elif recent_gain > -0.05:
                score += 10  # 横盘整理
            else:
                score += 0   # 下跌趋势
        else:
            score += 10

        self.lines.trend_score[0] = min(100.0, score)


class TurnoverRate(bt.Indicator):
    """
    换手率指标 (近似计算)
    -----------------------------------------------
    由于日线数据通常不包含流通股本信息，
    这里用 成交量 / 近N日平均成交量 来近似评估换手活跃度

    如果数据中有流通股本字段，可以直接计算真实换手率

    输出线:
      - turnover_score: 换手率评分 (0-100)
    """
    lines = ('turnover_score',)
    params = (
        ('period', 20),
        ('optimal_low', cfg.TURNOVER_OPTIMAL_LOW),
        ('optimal_high', cfg.TURNOVER_OPTIMAL_HIGH),
    )

    def __init__(self):
        self.vol_ma = bt.indicators.SMA(self.data.volume, period=self.p.period)

    def next(self):
        if self.vol_ma[0] > 0:
            relative_turnover = self.data.volume[0] / self.vol_ma[0]
        else:
            relative_turnover = 1.0

        # 换手率评分:
        # 一进二打板理想换手率不宜过高也不宜过低
        # 适中的换手率说明有资金接力但不至于分歧过大
        if 0.8 <= relative_turnover <= 2.0:
            score = 80   # 适度换手
        elif 0.5 <= relative_turnover <= 3.0:
            score = 60   # 可接受范围
        elif relative_turnover < 0.5:
            score = 50   # 缩量，可能无人接力
        else:
            score = 30   # 换手过高，分歧太大

        self.lines.turnover_score[0] = score

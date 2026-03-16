"""
一进二打板策略 - 综合评分系统
============================================
将各维度指标得分加权汇总，输出最终选股评分排名

评分维度:
  1. 涨停质量 (30%) - 封板形态、上影线、振幅
  2. 技术面 (25%)   - 均线、MACD、趋势
  3. 成交量 (15%)   - 量比、量能配合
  4. 板块热度 (20%) - 板块涨停数、板块涨幅
  5. 市场情绪 (10%) - 全市场涨停数、连板高度、炸板率
"""

import config as cfg


class MarketSentiment:
    """
    市场情绪评估器
    -----------------------------------------------
    统计全市场指标来评估当日整体情绪:
      - 涨停家数
      - 跌停家数
      - 炸板率 (盘中涨停后打开的比例)
      - 最高连板高度
      - 涨跌比
    """

    def __init__(self):
        self._cache_date = None
        self._sentiment_score = 50  # 默认中性
        self._stats = {}

    def update(self, date, market_data):
        """
        更新市场情绪数据

        参数:
          date: 日期
          market_data: dict
            {
                'limit_up_count': int,       # 涨停家数 (不含ST)
                'limit_down_count': int,      # 跌停家数
                'failed_limit_count': int,    # 炸板家数 (盘中涨停后打开)
                'max_consecutive': int,       # 最高连板高度
                'up_count': int,              # 上涨家数
                'down_count': int,            # 下跌家数
            }
        """
        if self._cache_date == date:
            return

        self._cache_date = date
        self._stats = market_data

        limit_up = market_data.get('limit_up_count', 0)
        limit_down = market_data.get('limit_down_count', 0)
        failed = market_data.get('failed_limit_count', 0)
        max_consec = market_data.get('max_consecutive', 0)
        up_count = market_data.get('up_count', 0)
        down_count = market_data.get('down_count', 0)

        score = 0.0

        # ------ 1. 涨停家数评分 (0-30分) ------
        if limit_up >= cfg.MARKET_LIMIT_UP_HOT:
            score += 30  # 市场情绪亢奋
        elif limit_up >= 50:
            score += 25
        elif limit_up >= cfg.MARKET_LIMIT_UP_COLD:
            score += 15
        elif limit_up >= 10:
            score += 8
        else:
            score += 0   # 情绪冰点

        # ------ 2. 涨跌比评分 (0-20分) ------
        total = up_count + down_count
        if total > 0:
            up_ratio = up_count / total
            if up_ratio >= 0.7:
                score += 20  # 普涨
            elif up_ratio >= 0.5:
                score += 12
            elif up_ratio >= 0.4:
                score += 5
            else:
                score += 0   # 普跌

        # ------ 3. 炸板率评分 (0-20分) ------
        total_touched_limit = limit_up + failed
        if total_touched_limit > 0:
            fail_rate = failed / total_touched_limit
            if fail_rate <= 0.10:
                score += 20  # 封板成功率极高
            elif fail_rate <= 0.20:
                score += 15
            elif fail_rate <= cfg.FAILED_LIMIT_RATE_THRESHOLD:
                score += 8
            else:
                score += 0   # 炸板率太高，情绪差

        # ------ 4. 连板高度评分 (0-15分) ------
        if max_consec >= 5:
            score += 15  # 市场有高度，赚钱效应强
        elif max_consec >= cfg.MAX_CONSECUTIVE_BOARDS:
            score += 10
        elif max_consec >= 2:
            score += 5
        else:
            score += 0

        # ------ 5. 跌停惩罚 (0 ~ -15分) ------
        if limit_down >= 20:
            score -= 15  # 大面积跌停，恐慌
        elif limit_down >= 10:
            score -= 8
        elif limit_down >= 5:
            score -= 3

        self._sentiment_score = max(0, min(100, score))

    def get_score(self):
        """返回当前市场情绪得分 (0-100)"""
        return self._sentiment_score

    def is_tradeable(self):
        """
        判断市场情绪是否适合一进二打板

        当情绪得分过低时，不建议操作
        """
        return self._sentiment_score >= 25

    def get_stats(self):
        """返回详细的市场情绪统计"""
        return self._stats.copy()


class StockScorer:
    """
    个股综合评分器
    -----------------------------------------------
    汇总各维度得分，输出最终加权评分

    使用方式:
      scorer = StockScorer()
      final_score = scorer.calculate(
          limit_quality_score=85,
          technical_score=70,
          volume_score=75,
          sector_score=60,
          sentiment_score=50,
      )
    """

    def __init__(self, weights=None):
        self.weights = weights or cfg.SCORE_WEIGHT

    def calculate(self, limit_quality_score, technical_score,
                  volume_score, sector_score, sentiment_score):
        """
        计算加权综合得分

        参数:
          limit_quality_score: 涨停质量得分 (0-100)
          technical_score: 技术面得分 (0-100)
          volume_score: 成交量得分 (0-100)
          sector_score: 板块热度得分 (0-100)
          sentiment_score: 市场情绪得分 (0-100)

        返回:
          final_score: 综合得分 (0-100)
        """
        final = (
            limit_quality_score * self.weights['limit_quality']
            + technical_score * self.weights['technical']
            + volume_score * self.weights['volume']
            + sector_score * self.weights['sector_heat']
            + sentiment_score * self.weights['market_sentiment']
        )
        return round(min(100.0, max(0.0, final)), 2)

    def get_detail_report(self, stock_code, limit_quality_score,
                          technical_score, volume_score,
                          sector_score, sentiment_score,
                          sector_name=''):
        """
        生成详细的评分报告

        返回 dict:
          {
              'code': stock_code,
              'final_score': float,
              'breakdown': {各维度评分},
              'sector': sector_name,
          }
        """
        final = self.calculate(
            limit_quality_score, technical_score,
            volume_score, sector_score, sentiment_score
        )

        return {
            'code': stock_code,
            'final_score': final,
            'breakdown': {
                'limit_quality': {
                    'score': limit_quality_score,
                    'weight': self.weights['limit_quality'],
                    'weighted': round(limit_quality_score * self.weights['limit_quality'], 2),
                },
                'technical': {
                    'score': technical_score,
                    'weight': self.weights['technical'],
                    'weighted': round(technical_score * self.weights['technical'], 2),
                },
                'volume': {
                    'score': volume_score,
                    'weight': self.weights['volume'],
                    'weighted': round(volume_score * self.weights['volume'], 2),
                },
                'sector_heat': {
                    'score': sector_score,
                    'weight': self.weights['sector_heat'],
                    'weighted': round(sector_score * self.weights['sector_heat'], 2),
                },
                'market_sentiment': {
                    'score': sentiment_score,
                    'weight': self.weights['market_sentiment'],
                    'weighted': round(sentiment_score * self.weights['market_sentiment'], 2),
                },
            },
            'sector': sector_name,
        }


def rank_candidates(candidates):
    """
    对候选股票按综合得分排序

    参数:
      candidates: list of dict (来自 StockScorer.get_detail_report)

    返回:
      排序后的列表 (得分从高到低)
    """
    return sorted(candidates, key=lambda x: x['final_score'], reverse=True)


def filter_candidates(candidates, min_score=50):
    """
    过滤掉得分低于阈值的候选股票

    参数:
      candidates: list of dict
      min_score: 最低分数阈值

    返回:
      过滤后的列表
    """
    return [c for c in candidates if c['final_score'] >= min_score]


def format_report(ranked_candidates, date=None):
    """
    格式化打印选股报告

    参数:
      ranked_candidates: 已排序的候选列表
      date: 日期
    """
    header = f"\n{'='*70}"
    if date:
        header += f"\n  📊 一进二打板选股报告 | {date}"
    else:
        header += f"\n  📊 一进二打板选股报告"
    header += f"\n{'='*70}"

    lines = [header]

    if not ranked_candidates:
        lines.append("  ⚠️  今日无符合条件的候选股票")
        lines.append(f"{'='*70}\n")
        return '\n'.join(lines)

    lines.append(f"  {'排名':<4} {'代码':<10} {'综合评分':<8} "
                 f"{'涨停质量':<8} {'技术面':<8} {'成交量':<8} "
                 f"{'板块热度':<8} {'市场情绪':<8} {'所属板块'}")
    lines.append(f"  {'-'*90}")

    for i, c in enumerate(ranked_candidates, 1):
        bd = c['breakdown']
        lines.append(
            f"  {i:<4} {c['code']:<10} {c['final_score']:<8.1f} "
            f"{bd['limit_quality']['score']:<8.0f} "
            f"{bd['technical']['score']:<8.0f} "
            f"{bd['volume']['score']:<8.0f} "
            f"{bd['sector_heat']['score']:<8.0f} "
            f"{bd['market_sentiment']['score']:<8.0f} "
            f"{c.get('sector', '')}"
        )

    lines.append(f"{'='*70}\n")
    return '\n'.join(lines)

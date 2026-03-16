"""
一进二打板策略 - 板块热度分析
============================================
分析各板块的热度:
  - 统计板块内涨停个股数量
  - 计算板块整体涨幅
  - 识别当日热门板块 (龙头板块)
  - 评估个股所属板块的热度得分
"""

import os
import csv
from collections import defaultdict
import config as cfg


class SectorHeatAnalyzer:
    """
    板块热度分析器
    -----------------------------------------------
    功能:
      1. 加载板块-个股映射关系
      2. 每日统计各板块涨停数量和平均涨幅
      3. 为每只涨停股计算板块热度得分

    使用方式:
      analyzer = SectorHeatAnalyzer()
      analyzer.load_sector_map('sector_map.csv')
      # 每个交易日调用
      analyzer.update_daily(date, stock_data_dict)
      score = analyzer.get_sector_score(stock_code)
    """

    def __init__(self):
        # stock_code -> [sector1, sector2, ...]  一只股票可能属于多个概念板块
        self.stock_sectors = defaultdict(list)
        # sector_name -> [stock_code1, stock_code2, ...]
        self.sector_stocks = defaultdict(list)
        # 当日分析结果缓存
        self._daily_cache = {}
        self._cache_date = None

    def load_sector_map(self, filepath=None):
        """
        加载板块映射文件

        CSV格式:
          stock_code, sector_name
          000001, 银行
          000001, 金融科技
          000002, 房地产
          ...
        """
        if filepath is None:
            filepath = cfg.SECTOR_MAP_FILE

        if not os.path.exists(filepath):
            print(f"[SectorHeat] 警告: 板块映射文件不存在: {filepath}")
            print("[SectorHeat] 将使用默认板块分配 (按股票代码前缀)")
            self._use_default_sectors()
            return

        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            header = next(reader, None)  # 跳过表头
            for row in reader:
                if len(row) >= 2:
                    code = row[0].strip()
                    sector = row[1].strip()
                    if code and sector:
                        self.stock_sectors[code].append(sector)
                        self.sector_stocks[sector].append(code)

        print(f"[SectorHeat] 加载完成: {len(self.stock_sectors)} 只股票, "
              f"{len(self.sector_stocks)} 个板块")

    def _use_default_sectors(self):
        """
        当没有板块映射文件时，按股票代码前缀做简单分类
        这只是一个fallback方案，实际使用应提供板块映射数据
        """
        self._default_sector_rules = {
            '600': '沪市主板', '601': '沪市主板', '603': '沪市主板', '605': '沪市主板',
            '000': '深市主板', '001': '深市主板',
            '002': '中小板',
            '300': '创业板', '301': '创业板',
            '688': '科创板', '689': '科创板',
        }

    def _get_default_sector(self, stock_code):
        """根据股票代码前缀获取默认板块"""
        for prefix, sector in getattr(self, '_default_sector_rules', {}).items():
            if stock_code.startswith(prefix):
                return [sector]
        return ['其他']

    def update_daily(self, date, stock_performances):
        """
        更新每日板块数据

        参数:
          date: 日期
          stock_performances: dict 
            {
                stock_code: {
                    'pct_change': float,      # 当日涨幅
                    'is_limit_up': bool,       # 是否涨停
                    'is_prev_limit_up': bool,  # 前日是否涨停
                }
            }
        """
        if self._cache_date == date:
            return  # 避免重复计算

        self._cache_date = date
        self._daily_cache = {}

        # 统计每个板块的涨停和涨幅数据
        sector_stats = defaultdict(lambda: {
            'limit_up_count': 0,
            'consecutive_count': 0,   # 板块内连板数量
            'total_stocks': 0,
            'total_pct': 0.0,
            'max_pct': 0.0,
        })

        for code, perf in stock_performances.items():
            # 获取该股票所属板块
            sectors = self.stock_sectors.get(code)
            if not sectors:
                sectors = self._get_default_sector(code)

            for sector in sectors:
                stats = sector_stats[sector]
                stats['total_stocks'] += 1
                stats['total_pct'] += perf.get('pct_change', 0)
                stats['max_pct'] = max(stats['max_pct'], perf.get('pct_change', 0))

                if perf.get('is_limit_up', False):
                    stats['limit_up_count'] += 1

                if perf.get('is_prev_limit_up', False) and perf.get('is_limit_up', False):
                    stats['consecutive_count'] += 1

        # 计算每个板块的热度得分
        for sector, stats in sector_stats.items():
            if stats['total_stocks'] > 0:
                avg_pct = stats['total_pct'] / stats['total_stocks']
            else:
                avg_pct = 0

            heat_score = self._calc_sector_heat_score(
                limit_up_count=stats['limit_up_count'],
                consecutive_count=stats['consecutive_count'],
                avg_pct=avg_pct,
                total_stocks=stats['total_stocks'],
            )
            self._daily_cache[sector] = {
                'heat_score': heat_score,
                'limit_up_count': stats['limit_up_count'],
                'consecutive_count': stats['consecutive_count'],
                'avg_pct': avg_pct,
            }

    def _calc_sector_heat_score(self, limit_up_count, consecutive_count,
                                avg_pct, total_stocks):
        """
        计算板块热度得分 (0-100)

        评分维度:
          1. 板块涨停数量 (0-40分): 涨停越多越热
          2. 连板数量 (0-25分): 有连板说明板块持续性强
          3. 板块平均涨幅 (0-20分): 整体上涨
          4. 涨停占比 (0-15分): 涨停数/总数 比例
        """
        score = 0.0

        # 1. 涨停数量评分 (0-40)
        if limit_up_count >= 5:
            score += 40
        elif limit_up_count >= 3:
            score += 30
        elif limit_up_count >= 2:
            score += 20
        elif limit_up_count >= 1:
            score += 10

        # 2. 连板数量评分 (0-25)
        if consecutive_count >= 3:
            score += 25
        elif consecutive_count >= 2:
            score += 18
        elif consecutive_count >= 1:
            score += 10

        # 3. 板块平均涨幅评分 (0-20)
        if avg_pct >= 0.05:
            score += 20
        elif avg_pct >= 0.03:
            score += 15
        elif avg_pct >= 0.02:
            score += 10
        elif avg_pct >= 0.01:
            score += 5

        # 4. 涨停占比评分 (0-15)
        if total_stocks > 0:
            limit_ratio = limit_up_count / total_stocks
            if limit_ratio >= 0.30:
                score += 15
            elif limit_ratio >= 0.20:
                score += 10
            elif limit_ratio >= 0.10:
                score += 5

        return min(100.0, score)

    def get_sector_score(self, stock_code):
        """
        获取某只股票的板块热度得分

        如果股票属于多个板块，取最高热度板块的得分
        (资金更愿意追逐最热板块的龙头)

        返回: (score, best_sector_name)
        """
        sectors = self.stock_sectors.get(stock_code)
        if not sectors:
            sectors = self._get_default_sector(stock_code)

        best_score = 0.0
        best_sector = '未知'

        for sector in sectors:
            info = self._daily_cache.get(sector, {})
            s = info.get('heat_score', 0)
            if s > best_score:
                best_score = s
                best_sector = sector

        return best_score, best_sector

    def get_hot_sectors(self, top_n=5):
        """
        获取当日最热门的N个板块

        返回: [(sector_name, heat_info), ...]
        """
        sorted_sectors = sorted(
            self._daily_cache.items(),
            key=lambda x: x[1].get('heat_score', 0),
            reverse=True
        )
        return sorted_sectors[:top_n]

    def get_daily_summary(self):
        """返回当日板块热度汇总信息"""
        hot_sectors = self.get_hot_sectors(5)
        total_sectors_with_limit = sum(
            1 for info in self._daily_cache.values()
            if info.get('limit_up_count', 0) > 0
        )
        return {
            'hot_sectors': hot_sectors,
            'sectors_with_limit_up': total_sectors_with_limit,
            'total_sectors': len(self._daily_cache),
        }

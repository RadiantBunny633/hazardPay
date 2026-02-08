"""
ML Pipeline for HazardPay.
Phased approach: metadata enrichment -> return labeling -> baselines -> ML evaluation.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

from pymongo import ASCENDING, DESCENDING

from .database import get_db, Database
from .scraper import FutbinScraper

logger = logging.getLogger(__name__)


class MLPipeline:
    """Manages the practical ML path for signal improvement."""

    def __init__(self, db: Database = None, platform: str = 'ps'):
        self.db = db or get_db()
        self.platform = platform
        self.scraper = FutbinScraper(platform=platform)

    # ========== STEP 1: Card Metadata Enrichment ==========

    def enrich_player(self, futbin_id: int, slug: str, force: bool = False) -> Dict:
        """
        Enrich a single player with card_type and first_seen_at.

        Returns dict with: card_type, first_seen_at, source ('scraped'/'inferred')
        """
        player = self.db.db.players.find_one({'futbin_id': futbin_id})
        if not player:
            return {'error': f'Player {futbin_id} not found'}

        # Skip if already enriched (unless forced)
        if not force and player.get('card_type'):
            return {
                'card_type': player['card_type'],
                'first_seen_at': player.get('first_seen_at'),
                'source': 'existing',
                'skipped': True,
            }

        # Try scraping metadata from Futbin page
        card_type = None
        version_raw = None
        source = 'inferred'

        metadata = self.scraper.get_player_metadata(futbin_id, slug)
        if metadata and metadata.get('card_type'):
            card_type = metadata['card_type']
            version_raw = metadata.get('version_raw')
            source = 'scraped'
        else:
            card_type = FutbinScraper.infer_card_type_from_id(futbin_id)

        # Derive first_seen_at from longterm cache
        first_seen_at = self._derive_first_seen_at(futbin_id, player)

        # Store
        self.db.update_player_metadata(
            futbin_id=futbin_id,
            card_type=card_type,
            first_seen_at=first_seen_at,
            version_raw=version_raw,
        )

        return {
            'card_type': card_type,
            'first_seen_at': first_seen_at,
            'version_raw': version_raw,
            'source': source,
            'skipped': False,
        }

    def enrich_all_players(self, force: bool = False) -> List[Dict]:
        """Backfill card_type + first_seen_at for all active players."""
        players = self.db.get_active_players()
        results = []

        for i, player in enumerate(players):
            futbin_id = player['futbin_id']
            slug = player.get('slug') or player.get('name', '').lower().replace(' ', '-')

            result = self.enrich_player(futbin_id, slug, force=force)
            result['name'] = player.get('name', 'Unknown')
            result['futbin_id'] = futbin_id
            results.append(result)

            # Delay between scrape requests (only if we actually scraped)
            if result.get('source') == 'scraped':
                time.sleep(1)

            if (i + 1) % 10 == 0:
                logger.info(f"Enriched {i + 1}/{len(players)} players...")

        return results

    def _derive_first_seen_at(self, futbin_id: int, player: dict) -> Optional[datetime]:
        """Derive first_seen_at from longterm cache or created_at."""
        # Try longterm cache first
        cache_key = f"{futbin_id}_{self.platform}"
        cached = self.db.db.longterm_cache.find_one({'cache_key': cache_key})

        first_seen = None
        if cached and cached.get('data') and cached['data'].get('prices'):
            prices = cached['data']['prices']
            if prices:
                first_ts_ms = prices[0][0]
                first_seen = datetime.fromtimestamp(first_ts_ms / 1000)

        # Fall back to created_at
        created_at = player.get('created_at')
        if first_seen and created_at:
            return min(first_seen, created_at)
        return first_seen or created_at

    # ========== STEP 2: Return Labeling ==========

    def label_signals(self, min_age_days: int = 7) -> Dict:
        """
        Label signal_log entries with actual price outcomes.

        Only labels signals at least min_age_days old (so T+7d price exists).
        Returns stats: {labeled, skipped_too_recent, skipped_no_price, already_labeled}
        """
        stats = {
            'labeled': 0,
            'skipped_too_recent': 0,
            'skipped_no_price': 0,
            'already_labeled': 0,
        }

        cutoff = datetime.now() - timedelta(days=min_age_days)

        signals = list(self.db.db.signal_log.find({
            'timestamp': {'$lte': cutoff}
        }))

        for signal in signals:
            signal_id = signal['_id']

            # Skip if already labeled
            if self.db.db.labeled_signals.find_one({'signal_id': signal_id}):
                stats['already_labeled'] += 1
                continue

            signal_ts = signal.get('timestamp')
            signal_price = signal.get('price', 0)
            player_id = signal.get('player_id')

            if not signal_price or not player_id:
                stats['skipped_no_price'] += 1
                continue

            # Find prices at T+2d and T+7d
            price_2d = self._find_price_at_offset(player_id, signal_ts, days=2)
            price_7d = self._find_price_at_offset(player_id, signal_ts, days=7)

            if price_2d is None and price_7d is None:
                stats['skipped_no_price'] += 1
                continue

            # Get player info for denormalization
            player = self.db.db.players.find_one({'_id': player_id}) if not isinstance(player_id, str) else None
            if not player:
                player = self.db.db.players.find_one({'futbin_id': int(player_id)}) if str(player_id).isdigit() else None
            if not player:
                # Try matching by player_id as string _id
                from bson import ObjectId
                try:
                    player = self.db.db.players.find_one({'_id': ObjectId(player_id)})
                except Exception:
                    pass

            card_type = player.get('card_type', 'UNKNOWN') if player else 'UNKNOWN'
            player_name = player.get('name', 'Unknown') if player else 'Unknown'

            # Compute returns
            return_2d = ((price_2d - signal_price) / signal_price * 100) if price_2d else None
            return_7d = ((price_7d - signal_price) / signal_price * 100) if price_7d else None

            labeled_doc = {
                'signal_id': signal_id,
                'player_id': player_id,
                'player_name': player_name,
                'card_type': card_type,
                'platform': signal.get('platform', 'ps'),
                'direction': signal.get('direction'),
                'signal_timestamp': signal_ts,
                'signal_price': signal_price,
                'final_score': signal.get('final_score'),
                'raw_score': signal.get('raw_score'),
                'components': signal.get('components', {}),
                'velocity_state': signal.get('velocity_state'),
                'buy_readiness': signal.get('buy_readiness'),
                'market_state': signal.get('market_state'),
                'signal_type': signal.get('signal_type'),
                'price_2d': price_2d,
                'return_2d_pct': round(return_2d, 2) if return_2d is not None else None,
                'price_7d': price_7d,
                'return_7d_pct': round(return_7d, 2) if return_7d is not None else None,
                'outcome_2d': self._classify_outcome(return_2d),
                'outcome_7d': self._classify_outcome(return_7d),
                'labeled_at': datetime.now(),
            }

            self.db.db.labeled_signals.insert_one(labeled_doc)
            stats['labeled'] += 1

        return stats

    def _find_price_at_offset(self, player_id, signal_ts: datetime,
                              days: int) -> Optional[int]:
        """Find price approximately 'days' after signal_ts."""
        target_ts = signal_ts + timedelta(days=days)
        window = timedelta(hours=6)

        # Try price_history first (more precise)
        price_record = self.db.db.price_history.find_one({
            'player_id': player_id,
            'platform': self.platform,
            'recorded_at': {
                '$gte': target_ts - window,
                '$lte': target_ts + window,
            }
        }, sort=[('recorded_at', ASCENDING)])

        if price_record and price_record.get('price'):
            return price_record['price']

        # Fallback: longterm_cache daily data
        # Need to resolve player_id -> futbin_id
        player = None
        if isinstance(player_id, str) and player_id.isdigit():
            player = self.db.db.players.find_one({'futbin_id': int(player_id)})
        if not player:
            from bson import ObjectId
            try:
                player = self.db.db.players.find_one({'_id': ObjectId(player_id)})
            except Exception:
                pass

        if not player:
            return None

        cache_key = f"{player['futbin_id']}_{self.platform}"
        cached = self.db.db.longterm_cache.find_one({'cache_key': cache_key})

        if cached and cached.get('data') and cached['data'].get('prices'):
            target_ms = target_ts.timestamp() * 1000
            prices = cached['data']['prices']

            best_price = None
            best_diff = float('inf')
            for ts_ms, price in prices:
                diff = abs(ts_ms - target_ms)
                if diff < best_diff:
                    best_diff = diff
                    best_price = price

            # Accept if within 36 hours (daily data has ~24h gaps)
            if best_diff < 36 * 3600 * 1000:
                return best_price

        return None

    @staticmethod
    def _classify_outcome(return_pct: Optional[float]) -> Optional[str]:
        if return_pct is None:
            return None
        if return_pct > 2:
            return 'WIN'
        if return_pct < -2:
            return 'LOSS'
        return 'FLAT'

    def get_label_stats(self) -> Dict:
        """Get statistics about labeled data."""
        total = self.db.db.labeled_signals.count_documents({})
        if total == 0:
            return {'total': 0}

        pipeline = [
            {'$group': {
                '_id': {'direction': '$direction', 'card_type': '$card_type'},
                'count': {'$sum': 1},
                'avg_return_7d': {'$avg': '$return_7d_pct'},
                'avg_score': {'$avg': '$final_score'},
            }}
        ]
        groups = list(self.db.db.labeled_signals.aggregate(pipeline))

        by_direction = defaultdict(int)
        by_card_type = defaultdict(lambda: {'count': 0, 'avg_return_7d': None})
        for g in groups:
            direction = g['_id']['direction']
            card_type = g['_id']['card_type']
            by_direction[direction] += g['count']
            ct = by_card_type[card_type]
            ct['count'] += g['count']
            ct['avg_return_7d'] = g.get('avg_return_7d')

        return {
            'total': total,
            'by_direction': dict(by_direction),
            'by_card_type': dict(by_card_type),
        }

    # ========== STEP 3: Statistical Baselines ==========

    def compute_baselines(self, direction: str = 'BUY') -> Dict:
        """
        Compute baseline statistics grouped by card_type and score range.

        Returns: {card_type: {total_signals, by_score_range: [...]}}
        """
        score_ranges = [
            (0, 39, 'AVOID (0-39)'),
            (40, 59, 'HOLD (40-59)'),
            (60, 74, 'BUY (60-74)'),
            (75, 100, 'STRONG BUY (75-100)'),
        ]

        labeled = list(self.db.db.labeled_signals.find({
            'direction': direction,
            'return_7d_pct': {'$ne': None},
        }))

        by_type = defaultdict(list)
        for sig in labeled:
            by_type[sig.get('card_type', 'UNKNOWN')].append(sig)

        baselines = {}
        for card_type, signals in sorted(by_type.items()):
            type_baselines = []

            for lo, hi, range_label in score_ranges:
                range_signals = [s for s in signals if lo <= (s.get('final_score') or 0) <= hi]

                if not range_signals:
                    type_baselines.append({'range': range_label, 'n': 0})
                    continue

                returns_2d = [s['return_2d_pct'] for s in range_signals if s.get('return_2d_pct') is not None]
                returns_7d = [s['return_7d_pct'] for s in range_signals if s.get('return_7d_pct') is not None]

                type_baselines.append({
                    'range': range_label,
                    'n': len(range_signals),
                    'avg_return_2d': sum(returns_2d) / len(returns_2d) if returns_2d else None,
                    'avg_return_7d': sum(returns_7d) / len(returns_7d) if returns_7d else None,
                    'hit_rate_2d': sum(1 for r in returns_2d if r > 0) / len(returns_2d) * 100 if returns_2d else None,
                    'hit_rate_7d': sum(1 for r in returns_7d if r > 0) / len(returns_7d) * 100 if returns_7d else None,
                    'win_rate_7d': sum(1 for r in returns_7d if r > 2) / len(returns_7d) * 100 if returns_7d else None,
                    'avg_score': sum(s.get('final_score', 0) for s in range_signals) / len(range_signals),
                })

            baselines[card_type] = {
                'total_signals': len(signals),
                'by_score_range': type_baselines,
            }

        return baselines

    def compute_new_card_patterns(self) -> List[Dict]:
        """
        For cards with first_seen_at, compute how many days after release
        they typically bottom out. Group by card_type.
        """
        players = list(self.db.db.players.find({
            'first_seen_at': {'$exists': True},
            'card_type': {'$exists': True},
        }))

        results_by_type = defaultdict(list)

        for player in players:
            card_type = player.get('card_type', 'UNKNOWN')
            first_seen = player['first_seen_at']

            cache_key = f"{player['futbin_id']}_{self.platform}"
            cached = self.db.db.longterm_cache.find_one({'cache_key': cache_key})

            if not cached or not cached.get('data') or not cached['data'].get('prices'):
                continue

            prices = cached['data']['prices']
            if len(prices) < 10:
                continue

            price_values = [p[1] for p in prices]
            first_price = price_values[0]
            if first_price <= 0:
                continue

            min_price = min(price_values)
            min_idx = price_values.index(min_price)
            min_ts = datetime.fromtimestamp(prices[min_idx][0] / 1000)

            days_to_bottom = (min_ts - first_seen).days
            drop_pct = (first_price - min_price) / first_price * 100

            if days_to_bottom >= 0:
                results_by_type[card_type].append({
                    'player': player['name'],
                    'days_to_bottom': days_to_bottom,
                    'drop_pct': round(drop_pct, 1),
                    'first_price': first_price,
                    'bottom_price': min_price,
                })

        summary = []
        for card_type, entries in sorted(results_by_type.items()):
            days = sorted([e['days_to_bottom'] for e in entries])
            drops = [e['drop_pct'] for e in entries]

            summary.append({
                'card_type': card_type,
                'sample_size': len(entries),
                'avg_days_to_bottom': round(sum(days) / len(days), 1),
                'median_days_to_bottom': days[len(days) // 2],
                'avg_drop_pct': round(sum(drops) / len(drops), 1),
                'entries': entries,
            })

        return summary

    # ========== STEP 4: ML Evaluation ==========

    def _build_feature_matrix(self):
        """
        Build feature matrix from labeled BUY signals.

        Returns: (DataFrame X, Series y_return, Series y_class, Series signal_ids)
        """
        import pandas as pd
        import numpy as np

        labeled = list(self.db.db.labeled_signals.find({
            'direction': 'BUY',
            'return_7d_pct': {'$ne': None},
        }).sort('signal_timestamp', ASCENDING))

        if len(labeled) < 50:
            raise ValueError(f"Need at least 50 labeled BUY signals, have {len(labeled)}")

        records = []
        for sig in labeled:
            components = sig.get('components', {})

            # Calculate days_since_release
            days_since_release = -1
            player = self.db.db.players.find_one({'futbin_id': int(sig['player_id'])}) if str(sig.get('player_id', '')).isdigit() else None
            if player and player.get('first_seen_at') and sig.get('signal_timestamp'):
                days_since_release = (sig['signal_timestamp'] - player['first_seen_at']).days

            records.append({
                'signal_id': sig['signal_id'],
                'final_score': sig.get('final_score', 50),
                'raw_score': sig.get('raw_score', 50),
                'comp_market': components.get('market', 0),
                'comp_timing': components.get('timing', 0),
                'comp_position': components.get('position', 0),
                'comp_bounce': components.get('bounce_penalty', 0),
                'velocity_state': sig.get('velocity_state', 'UNKNOWN'),
                'buy_readiness': sig.get('buy_readiness', 'UNKNOWN'),
                'market_state': sig.get('market_state', 'UNKNOWN'),
                'card_type': sig.get('card_type', 'UNKNOWN'),
                'log_price': np.log1p(sig.get('signal_price', 0)),
                'days_since_release': days_since_release,
                'return_7d': sig['return_7d_pct'],
                'outcome_7d': sig.get('outcome_7d', 'FLAT'),
            })

        df = pd.DataFrame(records)

        # One-hot encode categoricals
        df = pd.get_dummies(df, columns=['velocity_state', 'buy_readiness',
                                          'market_state', 'card_type'])

        feature_cols = [c for c in df.columns if c not in
                        ['signal_id', 'return_7d', 'outcome_7d']]

        X = df[feature_cols].astype(float)
        y_return = df['return_7d']
        y_class = df['outcome_7d']

        return X, y_return, y_class, df['signal_id']

    def evaluate_ml(self) -> Dict:
        """
        Train gradient boosting on labeled signals and compare to baselines.

        Uses time-based 70/30 train/test split.
        Returns comparison metrics + feature importances + recommendation.
        """
        from sklearn.ensemble import GradientBoostingRegressor
        from sklearn.metrics import mean_absolute_error

        X, y_return, y_class, signal_ids = self._build_feature_matrix()

        # Time-based split
        split_idx = int(len(X) * 0.7)
        X_train, X_test = X[:split_idx], X[split_idx:]
        y_train, y_test = y_return[:split_idx], y_return[split_idx:]

        # Baseline: predict avg return per score bucket
        def baseline_predict(row):
            score = row['final_score']
            return (score - 50) * 0.1

        baseline_preds = X_test.apply(baseline_predict, axis=1)

        # ML model
        model = GradientBoostingRegressor(
            n_estimators=100, max_depth=4, learning_rate=0.1,
            random_state=42,
        )
        model.fit(X_train, y_train)
        ml_preds = model.predict(X_test)

        # Compare
        baseline_mae = mean_absolute_error(y_test, baseline_preds)
        ml_mae = mean_absolute_error(y_test, ml_preds)

        baseline_hits = sum(
            1 for pred, actual in zip(baseline_preds, y_test)
            if (pred > 0) == (actual > 0)
        ) / len(y_test) * 100

        ml_hits = sum(
            1 for pred, actual in zip(ml_preds, y_test)
            if (pred > 0) == (actual > 0)
        ) / len(y_test) * 100

        # Feature importances
        feature_importance = sorted(
            zip(X.columns, model.feature_importances_),
            key=lambda x: x[1], reverse=True,
        )[:10]

        improvement = ((baseline_mae - ml_mae) / baseline_mae * 100) if baseline_mae > 0 else 0

        return {
            'sample_size': len(X),
            'train_size': len(X_train),
            'test_size': len(X_test),
            'baseline_mae': round(baseline_mae, 2),
            'ml_mae': round(ml_mae, 2),
            'improvement_pct': round(improvement, 1),
            'baseline_hit_rate': round(baseline_hits, 1),
            'ml_hit_rate': round(ml_hits, 1),
            'top_features': [(str(f), round(float(i), 4)) for f, i in feature_importance],
            'recommendation': 'ADOPT_ML' if improvement > 15 else 'KEEP_BASELINES',
        }

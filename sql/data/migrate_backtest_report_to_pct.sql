-- 一次性迁移：把 backtest_report 列名 / 数值 / JSONB key 统一到百分数语义
--
-- 历史背景：vbt framework.py:306,310 的 stats_daily 字典里 ["Total Return [%]"] / ["Max Drawdown [%]"]
-- 等 key 标注了百分数但实际值混合（total_return 是小数 0.5397、max_dd 是已乘100的 -18.55），
-- 列名也没表达语义。本次迁移统一为：
--   - 列名加 _pct 后缀（total_return → total_return_pct；sharpe → sharpe_ratio）
--   - 列和 JSONB 的数值统一为百分数
--   - JSONB key 改为 *_pct / sharpe_ratio / trading_days 形式
--
-- 一次性脚本，跑过即可（idempotent：会跳过已迁移的列）

-- 1) Rename 列
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='backtest_report'
          AND column_name='total_return'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='backtest_report'
          AND column_name='total_return_pct'
    ) THEN
        ALTER TABLE public.backtest_report RENAME COLUMN total_return TO total_return_pct;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='backtest_report' AND column_name='annual_return')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='backtest_report' AND column_name='annual_return_pct') THEN
        ALTER TABLE public.backtest_report RENAME COLUMN annual_return TO annual_return_pct;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='backtest_report' AND column_name='max_dd')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='backtest_report' AND column_name='max_dd_pct') THEN
        ALTER TABLE public.backtest_report RENAME COLUMN max_dd TO max_dd_pct;
    END IF;

    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='backtest_report' AND column_name='sharpe')
       AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='backtest_report' AND column_name='sharpe_ratio') THEN
        ALTER TABLE public.backtest_report RENAME COLUMN sharpe TO sharpe_ratio;
    END IF;
END$$;

-- 2) 列 ×100（老数据假设为小数比例；脚本假设此前从未迁过）
UPDATE public.backtest_report
SET total_return_pct = total_return_pct * 100,
    annual_return_pct = annual_return_pct * 100,
    max_dd_pct = max_dd_pct * 100;

-- 3) JSONB key 重命名 + ×100 同步
UPDATE public.backtest_report br
SET stats_daily = sub.new_obj
FROM (
    SELECT
        run_id,
        jsonb_object_agg(
            CASE k
                WHEN 'Total Return [%]' THEN 'total_return_pct'
                WHEN 'Annualized Return [%]' THEN 'annual_return_pct'
                WHEN 'Annualized Volatility [%]' THEN 'annualized_volatility_pct'
                WHEN 'Sharpe Ratio' THEN 'sharpe_ratio'
                WHEN 'Max Drawdown [%]' THEN 'max_dd_pct'
                WHEN 'Trading Days' THEN 'trading_days'
                ELSE k
            END,
            CASE
                WHEN k IN ('Total Return [%]','Annualized Return [%]','Annualized Volatility [%]','Max Drawdown [%]')
                     AND jsonb_typeof(stats_daily -> k) = 'number'
                     AND abs((stats_daily ->> k)::numeric) < 100
                    THEN to_jsonb(((stats_daily ->> k)::numeric) * 100)
                ELSE stats_daily -> k
            END
        ) AS new_obj
    FROM public.backtest_report,
         LATERAL jsonb_object_keys(stats_daily) AS k
    WHERE stats_daily IS NOT NULL
    GROUP BY run_id
) sub
WHERE br.run_id = sub.run_id;
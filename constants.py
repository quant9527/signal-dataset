EXCHANGE_AS = "as"
EXCHANGE_EM = "em"
EXCHANGE_THS = "ths"
EXCHANGE_BINANCE = "binance"
EXCHANGE_ASINDEX = "asindex"
EXCHANGE_HYPERLIQUID = "hyperliquid"
EXCHANGE_AS_ALL = "as_all"
EXCHANGE_CRYPTO = "crypto"

# K 线页（Flight tag 前缀）：含指数 asindex，不含 em/binance 单列项。
# 下拉额外提供聚合项（为展示用，非真实交易所）：
#   as_all  = as / ths / asindex 合集
#   crypto  = binance / hyperliquid 合集
KLINE_EXCHANGE_OPTIONS = (EXCHANGE_AS, EXCHANGE_THS, EXCHANGE_ASINDEX, EXCHANGE_HYPERLIQUID)
KLINE_EXCHANGE_SELECT_OPTIONS = (*KLINE_EXCHANGE_OPTIONS, EXCHANGE_AS_ALL, EXCHANGE_CRYPTO)

KLINE_DEFAULT_FREQ = "1d"
# 周期列表按交易所类型区分，权威定义在 atlas：
#   - pkg/intervaltime/asinterval.go    AsIntervalList（ashare）
#   - pkg/intervaltime/standard.go      StandardIntervalList（24h/crypto）
#   - etc/klinefeature.yaml             exchange → IntervalType
# ashare（as/asindex/em/ths）flow 工厂默认范围 5m~1d（1m 不落库）；
# 24h（binance*/hyperliquid）为 1m~1M；`1w` / `1M` 为派生周期，
# 由服务端在 1d 数据上聚合，两类交易所均支持；`*_utc` 存储变体不在 UI 展示。
KLINE_FREQ_OPTIONS_AS = ("1d", "2h", "1h", "30m", "15m", "5m", "1w")
KLINE_FREQ_OPTIONS_CRYPTO = (
    "1M", "1w", "1d", "12h", "8h", "6h", "4h", "2h",
    "1h", "30m", "15m", "5m", "3m", "1m",
)
# 并集：URL token 协议层校验用；某交易所可用的列表见 kline_freq_options_for_exchange。
KLINE_FREQ_OPTIONS = tuple(dict.fromkeys((*KLINE_FREQ_OPTIONS_AS, *KLINE_FREQ_OPTIONS_CRYPTO)))
KLINE_FREQ_SET = frozenset(KLINE_FREQ_OPTIONS)

# crypto 家族（含聚合项）；binancespot 为 atlas 侧 exchange 名
KLINE_FREQ_CRYPTO_EXCHANGES = frozenset(
    {EXCHANGE_BINANCE, "binancespot", EXCHANGE_HYPERLIQUID, EXCHANGE_CRYPTO}
)


def kline_freq_options_for_exchange(exchange: str) -> tuple[str, ...]:
    """返回该交易所可用的 K 线周期列表（ashare → AS，24h/crypto → CRYPTO）。

    未知 exchange 兜底返回 AS 列表，与历史默认行为一致。
    """
    ex = str(exchange or "").strip().lower()
    if ex in KLINE_FREQ_CRYPTO_EXCHANGES:
        return KLINE_FREQ_OPTIONS_CRYPTO
    return KLINE_FREQ_OPTIONS_AS

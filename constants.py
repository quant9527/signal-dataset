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
KLINE_FREQ_OPTIONS = ("1d", "2h", "1h", "30m", "15m", "5m", "1w")
KLINE_FREQ_SET = frozenset(KLINE_FREQ_OPTIONS)

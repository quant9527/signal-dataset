"""信号系列常量：前缀用于 startswith / SQL LIKE；全名列表用于 isin 等。"""

# ---------------------------------------------------------------------------
# 前缀（与库表 signal_name 一致）
# ---------------------------------------------------------------------------
NESTED_2BC_PREFIX: str = "nested_2bc"
PAIR_SEG_PREFIX: str = "pair_seg"
CL2B_PAIR_PREFIX: str = "cl2b_pair"
CL2B_TRIANGLE_PREFIX: str = "cl2b_triangle"
BC_XD4_PREFIX: str = "bc_xd4"
CL3B_MACD_PREFIX: str = "cl3b_macd"
CL3B_ZSX_PREFIX: str = "cl3b_zsx"
CMP_PREFIX: str = "cmp"

# ---------------------------------------------------------------------------
# AS 模式范围：所有 AS 模式页面（Signal Filters / AS 模式）的 SQL 都应限制
# 在以下 exchange 取值范围内，避免 crypto（hyperliquid）等混入。
# ---------------------------------------------------------------------------
AS_ALL_EXCHANGES: tuple[str, ...] = ("as", "ths", "asindex")

# ---------------------------------------------------------------------------
# nested_2bc 已知全名（可按库内实际继续追加）
# ---------------------------------------------------------------------------
NESTED_2BC_SIGNAL_NAMES: list[str] = [
    "nested_2bc_macd_1b",
    "nested_2bc_ma5ma10_1b",
]

# ---------------------------------------------------------------------------
# CMP（同花顺板块等）— 全名列表
# ---------------------------------------------------------------------------
CMP_SIGNAL_NAMES: list[str] = [
    "cmp_rebound_pioneer_ma5ma10",
    "cmp_zs_macd",
    "cmp_xsx_ma5ma10",
    "cmp_xsx_macd",
]

# ---------------------------------------------------------------------------
# 全局预拉：侧边栏 df 若缺某系列则按前缀补 load（多页共用）
# ---------------------------------------------------------------------------
SIGNAL_NAME_PREFIXES_PRELOAD: tuple[str, ...] = (
    NESTED_2BC_PREFIX,
    PAIR_SEG_PREFIX,
    CL3B_MACD_PREFIX,
    CL3B_ZSX_PREFIX,
    CMP_PREFIX,
)

# ---------------------------------------------------------------------------
# Performance 页「功能」默认勾选用的前缀组合
# ---------------------------------------------------------------------------
PERFORMANCE_PRESET_AS_PREFIXES: tuple[str, ...] = (
    NESTED_2BC_PREFIX,
    PAIR_SEG_PREFIX,
    CL3B_MACD_PREFIX,
    CMP_PREFIX,
)
PERFORMANCE_PRESET_THS_PREFIXES: tuple[str, ...] = (
    CMP_PREFIX,
    CL3B_MACD_PREFIX,
)

# ---------------------------------------------------------------------------
# AS 页：active_vol_then_nestedbc — 小周期
# ---------------------------------------------------------------------------
ACTIVE_VOL_NESTED_SHORT_FREQS: tuple[str, ...] = ("5m", "15m")

# ---------------------------------------------------------------------------
# AS 页：nested_bc — nested_2bc 系列，周线 / 日线
# ---------------------------------------------------------------------------
NESTED_2BC_LONG_FREQS: tuple[str, ...] = ("1w", "1d","2h","1h","30m")

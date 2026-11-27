from decimal import ROUND_HALF_UP, Decimal


def round_vnd(x: Decimal) -> Decimal:
    return Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def format_vnd(x: Decimal) -> str:
    n = int(round_vnd(x))
    s = f"{abs(n):,}".replace(",", ".")
    return f"-{s}" if n < 0 else s


_DIGITS = ["không", "một", "hai", "ba", "bốn", "năm", "sáu", "bảy", "tám", "chín"]
_SCALES = ["", "nghìn", "triệu", "tỷ"]


def _read_group(n: int, leading: bool) -> str:
    """Đọc một nhóm 3 chữ số (n > 0)."""
    h, t, u = n // 100, (n // 10) % 10, n % 10
    words = []
    if h or not leading:
        words += [_DIGITS[h], "trăm"]
    if t == 0:
        if u:
            words += ["linh", _DIGITS[u]] if (h or not leading) else [_DIGITS[u]]
    elif t == 1:
        words.append("mười")
        if u:
            words.append("lăm" if u == 5 else _DIGITS[u])
    else:
        words += [_DIGITS[t], "mươi"]
        if u:
            words.append("mốt" if u == 1 else "lăm" if u == 5 else _DIGITS[u])
    return " ".join(words)


def _scale_name(i: int) -> str:
    # i = chỉ số nhóm từ phải sang trái; chu kỳ: "", nghìn, triệu, tỷ, nghìn tỷ, triệu tỷ, tỷ tỷ...
    if i == 0:
        return ""
    q, r = divmod(i, 3)
    parts = []
    if r:
        parts.append(_SCALES[r])
    parts += ["tỷ"] * q
    return " ".join(parts)


def amount_in_words_vi(x: Decimal) -> str:
    n = int(round_vnd(x))
    if n == 0:
        return "Không đồng"
    neg = n < 0
    n = abs(n)
    groups = []
    while n:
        n, g = divmod(n, 1000)
        groups.append(g)
    words = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if g == 0:
            continue
        leading = i == len(groups) - 1
        text = _read_group(g, leading)
        scale = _scale_name(i)
        words.append(f"{text} {scale}".strip())
    s = " ".join(words)
    s = ("Âm " + s) if neg else s
    return s[0].upper() + s[1:] + " đồng"

def format_large_number(n):
    """Format a number as T/B/M/K (e.g. 2.98T, 847.3B). Returns '—' for None/invalid."""
    if n is None:
        return '—'
    try:
        n = float(n)
    except (TypeError, ValueError):
        return '—'

    negative = n < 0
    magnitude = abs(n)

    if magnitude >= 1_000_000_000_000:
        result = f'{magnitude / 1_000_000_000_000:.1f}T'
    elif magnitude >= 1_000_000_000:
        result = f'{magnitude / 1_000_000_000:.1f}B'
    elif magnitude >= 1_000_000:
        result = f'{magnitude / 1_000_000:.1f}M'
    elif magnitude >= 1_000:
        result = f'{magnitude / 1_000:.1f}K'
    else:
        result = str(int(magnitude))

    return f'-{result}' if negative else result

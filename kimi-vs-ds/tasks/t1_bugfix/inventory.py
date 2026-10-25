from datetime import date, timedelta

class Inventory:
    def __init__(self):
        self.items = {}  # sku -> list of (qty, expiry)

    def add(self, sku, qty, expiry):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self.items.setdefault(sku, []).append((qty, expiry))

    def total(self, sku, today):
        return sum(q for q, e in self.items.get(sku, []) if e >= today)

    def remove(self, sku, qty, today):
        """Remove qty using FEFO (first expiring first out), skipping expired lots."""
        if self.total(sku, today) < qty:
            raise ValueError("insufficient stock")
        lots = sorted(self.items[sku], key=lambda x: x[1], reverse=True)
        remaining = qty
        new = []
        for q, e in lots:
            if e < today:
                continue
            if remaining > 0:
                take = min(q, remaining)
                remaining -= take
                q -= take
            new.append((q, e))
        self.items[sku] = new

    def expiring_within(self, today, days):
        cutoff = today + timedelta(days=days)
        out = []
        for sku, lots in self.items.items():
            for q, e in lots:
                if today < e < cutoff:
                    out.append((sku, q, e))
        return sorted(out, key=lambda x: x[2])

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
        if qty <= 0:
            raise ValueError("qty must be positive")
        if self.total(sku, today) < qty:
            raise ValueError("insufficient stock")
        # Earliest expiry first.
        lots = sorted(self.items[sku], key=lambda x: x[1])
        remaining = qty
        new = []
        for q, e in lots:
            if e < today:
                # Expired stock is not usable: drop it.
                continue
            if remaining > 0:
                take = min(q, remaining)
                remaining -= take
                q -= take
            if q > 0:  # never keep empty lots around
                new.append((q, e))
        self.items[sku] = new

    def expiring_within(self, today, days):
        # Window is inclusive of both today and the cutoff day.
        cutoff = today + timedelta(days=days)
        out = []
        for sku, lots in self.items.items():
            for q, e in lots:
                if today <= e <= cutoff:
                    out.append((sku, q, e))
        return sorted(out, key=lambda x: x[2])

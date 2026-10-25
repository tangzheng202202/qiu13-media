class FakeClock:
    def __init__(self, t=0.0): self.t = t
    def __call__(self): return self.t
    def advance(self, d): self.t += d

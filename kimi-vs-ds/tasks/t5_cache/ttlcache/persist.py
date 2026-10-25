import json, os
from .cache import Cache

def save(cache, path):
    entries = [{"k": k, "v": v, "exp": rem} for k, v, rem in cache._remaining()]
    with open(path, "w") as f:
        json.dump({"entries": entries}, f)

def load(path, maxsize, clock=None):
    with open(path) as f:
        data = json.load(f)
    c = Cache(maxsize, clock=clock) if clock else Cache(maxsize)
    for e in reversed(data["entries"]):
        c.set(e["k"], e["v"], ttl=e["exp"])
    return c

from __future__ import annotations
from fastapi import FastAPI
from .storage import read_extrema
app = FastAPI()
@app.get("/health")
def health(): return {"ok": True}
@app.get("/extrema")
def extrema(): return read_extrema()

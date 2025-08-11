from flask import Flask, request, jsonify
from datetime import datetime, timezone
import json, os, threading, tempfile

app = Flask(__name__)

# Gdzie trzymamy plik z danymi:
DATA_PATH = os.environ.get("DATA_PATH", "/tmp/gps_data.json")
_lock = threading.Lock()

# Struktura pliku: {"last": {...}, "history": [ {...}, ... ]}
DEFAULT_LAST = {
    "timestamp": None,
    "lat": 0.0,
    "lon": 0.0,
    "speed": 0.0,
    "acc_z": 0.0,
    "tilt_angle": 0.0,
    "altitude": 0.0,
}

def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()

def _load():
    if not os.path.exists(DATA_PATH):
        return {"last": DEFAULT_LAST.copy(), "history": []}
    try:
        with open(DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if "last" not in data: data["last"] = DEFAULT_LAST.copy()
            if "history" not in data: data["history"] = []
            return data
    except Exception:
        # gdy plik uszkodzony – zacznij od zera
        return {"last": DEFAULT_LAST.copy(), "history": []}

def _atomic_write(obj):
    # zapis atomowy: najpierw do pliku tymczasowego, potem podmiana
    d = os.path.dirname(DATA_PATH) or "."
    os.makedirs(d, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", delete=False, dir=d, encoding="utf-8") as tmp:
        json.dump(obj, tmp, ensure_ascii=False)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_name = tmp.name
    os.replace(tmp_name, DATA_PATH)

# wczytaj stan przy starcie
_state = _load()

@app.get("/gps")
def get_gps():
    with _lock:
        last = _state["last"].copy()
    if not last["timestamp"]:
        last["timestamp"] = _utcnow_iso()
    # upewnij się, że liczby są float
    for k in ("lat","lon","speed","acc_z","tilt_angle","altitude"):
        last[k] = float(last.get(k, 0.0) or 0.0)
    return jsonify(last)

@app.get("/history")
def get_history():
    limit = request.args.get("limit", default=100, type=int)
    with _lock:
        hist = _state["history"][-max(0, limit):]
    return jsonify(hist)

@app.post("/ingest")
def ingest():
    data = request.get_json(silent=True) or request.form
    try:
        entry = {
            "timestamp": _utcnow_iso(),
            "lat": float(data.get("lat", _state["last"]["lat"])),
            "lon": float(data.get("lon", _state["last"]["lon"])),
            "speed": float(data.get("speed", _state["last"]["speed"])),
            "acc_z": float(data.get("acc_z", _state["last"]["acc_z"])),
            "tilt_angle": float(data.get("tilt_angle", _state["last"]["tilt_angle"])),
            "altitude": float(data.get("altitude", _state["last"]["altitude"])),
        }
    except Exception as e:
        return jsonify({"ok": False, "error": f"Invalid payload: {e}"}), 400

    with _lock:
        _state["last"] = entry
        _state["history"].append(entry)
        # (opcjonalnie) obetnij historię, np. do 100k wpisów:
        if len(_state["history"]) > 100_000:
            _state["history"] = _state["history"][-100_000:]
        _atomic_write(_state)

    return jsonify({"ok": True})

if __name__ == "__main__":
    # Lokalny test: python app.py
    app.run(host="0.0.0.0", port=8000)

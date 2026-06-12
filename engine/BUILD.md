# OlbosQuant C++ Engine — Build Guide

## Requirements

- C++20 compiler: GCC 11+ or Clang 13+
- CMake 3.20+
- pybind11 (for Python bridge only)
- Linux recommended (CPU pinning uses pthreads)

## Install dependencies

```bash
# Ubuntu/Debian
sudo apt-get install -y g++ cmake libpthread-stubs0-dev

# pybind11 for Python bridge
pip install pybind11
```

## Build options

### Option A: CMake (recommended)

```bash
cd engine
mkdir build && cd build

# Release build (maximum performance)
cmake .. -DCMAKE_BUILD_TYPE=Release
make -j$(nproc)

# Outputs:
#   build/olbosquant_standalone    ← test without Python
#   build/olbosquant_engine.so     ← Python importable module
```

### Option B: Direct g++ (quick test)

```bash
cd engine

# Standalone executable
g++ -std=c++20 -O3 -march=native -mtune=native \
    -fno-exceptions -fno-rtti \
    -flto \
    -I include \
    src/engine.cpp \
    -lpthread \
    -o olbosquant_standalone

./olbosquant_standalone
```

### Option C: Python module (manual)

```bash
cd engine

PYTHON_INCLUDES=$(python3 -m pybind11 --includes)
PYTHON_EXT=$(python3-config --extension-suffix)

g++ -std=c++20 -O3 -march=native \
    -shared -fPIC \
    -DOLBOSQUANT_PYTHON_MODULE \
    ${PYTHON_INCLUDES} \
    -I include \
    bridge/python_bridge.cpp \
    src/engine.cpp \
    -lpthread \
    -o olbosquant_engine${PYTHON_EXT}

# Test import
python3 -c "import olbosquant_engine; print('Engine loaded OK')"
```

## Verify the build

```bash
# Standalone test
./olbosquant_standalone
# Expected: "Order dispatched: id=1 latency=X μs"

# Python bridge test
python3 -c "
import olbosquant_engine as eng
e = eng.ExecutionEngine()
e.start()
import time; time.sleep(1)
s = eng.Signal()
s.type = eng.SignalType.BullPut
s.signal_score = 0.73
s.limit_price = 1.25
e.submit_signal(s)
time.sleep(0.5)
r = e.get_last_result()
print(f'Result: {r}')
e.stop()
"
```

## Integration with OlbosQuant Python

Copy the `.so` file to the backend directory:

```bash
cp build/olbosquant_engine*.so ../backend/
```

Then in `paper_trader.py`, the engine is used as:

```python
try:
    import olbosquant_engine as cpp_engine
    HAS_CPP_ENGINE = True
except ImportError:
    HAS_CPP_ENGINE = False  # Falls back to pure Python dispatch
```

## Compiler flags explained

| Flag | Why |
|---|---|
| `-O3` | Full optimization: loop unrolling, vectorization, inlining |
| `-march=native` | Use CPU-specific instructions (AVX2, BMI2) — not portable but fastest |
| `-mtune=native` | Tune instruction scheduling for this CPU's pipeline |
| `-fno-exceptions` | Remove exception table overhead from every function |
| `-fno-rtti` | Remove type info tables (no dynamic_cast in hot path) |
| `-flto` | Link-time optimization: inlines across translation units |
| `-fPIC` | Position-independent code (required for .so shared library) |

## Performance expectations on a $24/mo DO Droplet (2 vCPU, 4GB)

| Operation | Typical latency |
|---|---|
| Ring buffer push/pop | 10-30 ns |
| Signal evaluation (all checks) | 50-150 ns |
| Order construction (pool alloc) | 20-50 ns |
| JSON formatting (snprintf) | 100-300 ns |
| Total signal-to-wire | 500 ns - 2 μs |
| Network to Tradier (NYC3 droplet) | 2-8 ms |
| Network to IBKR TWS | 5-50 ms |

**The engine contributes < 2μs. The broker network contributes 5-50ms.**
This is why co-location matters for HFT — and why for retail options trading,
the C++ engine's primary value is reliability and memory safety, not latency.

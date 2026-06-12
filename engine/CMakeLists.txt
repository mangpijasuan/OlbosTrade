cmake_minimum_required(VERSION 3.20)
project(olbosquant_engine CXX)

# ── C++20 required ─────────────────────────────────────────────────────────────
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)  # -std=c++20 not -std=gnu++20

# ── Compiler detection ─────────────────────────────────────────────────────────
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
    add_compile_options(
        -O3                    # Maximum optimization
        -march=native          # CPU-specific instructions (AVX2, etc.)
        -mtune=native          # Tune scheduling for this CPU
        -fno-exceptions        # Disable exception overhead in hot path
        -fno-rtti              # Disable RTTI (no dynamic_cast in hot path)
        -Wall -Wextra          # All warnings
        -Wpedantic
        -Wno-unused-parameter
        # Link-time optimization — lets compiler optimize across TUs
        -flto
    )
    # Release mode: add -DNDEBUG to disable assert() calls
    add_compile_definitions($<$<CONFIG:Release>:NDEBUG>)
endif()

# ── Standalone executable (for testing without Python) ────────────────────────
add_executable(olbosquant_standalone
    src/engine.cpp
)
target_include_directories(olbosquant_standalone PRIVATE include)
target_link_libraries(olbosquant_standalone PRIVATE pthread)
# Link-time optimization
set_target_properties(olbosquant_standalone PROPERTIES
    INTERPROCEDURAL_OPTIMIZATION TRUE
)

# ── Python module (requires pybind11) ─────────────────────────────────────────
find_package(Python3 COMPONENTS Interpreter Development QUIET)
find_package(pybind11 QUIET)

if(pybind11_FOUND AND Python3_FOUND)
    pybind11_add_module(olbosquant_engine
        bridge/python_bridge.cpp
        src/engine.cpp
    )
    target_include_directories(olbosquant_engine PRIVATE include)
    target_compile_definitions(olbosquant_engine PRIVATE OLBOSQUANT_PYTHON_MODULE)
    target_link_libraries(olbosquant_engine PRIVATE pthread)
    message(STATUS "Python bridge will be built: olbosquant_engine")
else()
    message(STATUS "pybind11/Python3 not found — Python module skipped")
endif()

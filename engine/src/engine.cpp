/**
 * engine.cpp — Main execution engine: thread management and event loop.
 *
 * ARCHITECTURE OVERVIEW:
 *
 *   Thread 1: Market Data Thread (producer)
 *   ─────────────────────────────────────────
 *   Receives raw bytes from broker WebSocket/TCP socket.
 *   Parses into MarketUpdate using MarketDataParser.
 *   Pushes to SPSC ring buffer. Never blocks.
 *   CPU-pinned to core 0 for deterministic scheduling.
 *
 *   Thread 2: Execution Thread (consumer)
 *   ─────────────────────────────────────────
 *   Pops MarketUpdate from ring buffer (busy-poll — no sleep, no mutex).
 *   Updates OrderBook.
 *   Receives Signal from Python via shared_signal_ atomic.
 *   Runs SignalGenerator::evaluate().
 *   If approved: builds Order via ExecutionManager, dispatches.
 *   CPU-pinned to core 1.
 *
 *   Python Process (upstream)
 *   ─────────────────────────────────────────
 *   Runs regime classification, IV surface, XGBoost inference.
 *   Writes Signal to shared_signal_ via the Python bridge (pybind11).
 *   Reads ExecutionResult via bridge.
 *   Writes kill_switch to GuardrailState atomics.
 *
 * BUSY-POLL vs SLEEP:
 *   The execution thread busy-polls the ring buffer instead of using
 *   condition variables or semaphores. This burns one CPU core 100% but
 *   eliminates wake-up latency (a condition_variable::notify() + wake
 *   costs ~5-10 microseconds on Linux). For a $24/mo 2-vCPU droplet,
 *   we accept this tradeoff during market hours only.
 *
 *   std::this_thread::yield() is called when the queue is empty to
 *   prevent the OS from scheduling us away (yield is a hint to the
 *   scheduler to switch to another thread if one is waiting, but the
 *   thread stays runnable and wakes up as soon as possible).
 *
 * CPU PINNING (Linux only):
 *   pthread_setaffinity_np pins a thread to a specific CPU core.
 *   This prevents the OS from migrating threads between cores, which
 *   causes cache misses as the new core's L1/L2 is cold.
 */

#include "engine.hpp"

#include <iostream>
#include <thread>
#include <atomic>
#include <chrono>
#include <csignal>
#include <stdexcept>

#ifdef __linux__
#include <pthread.h>
#include <sched.h>
#endif

namespace olbosquant {

// ── Global shutdown flag (signal handler sets this) ────────────────────────────
static std::atomic<bool> g_shutdown{false};

static void signal_handler(int sig) noexcept {
    // async-signal-safe: only atomic store and write() are safe here
    g_shutdown.store(true, std::memory_order_seq_cst);
    // The loops check g_shutdown and exit cleanly
}

// ── CPU pinning ────────────────────────────────────────────────────────────────
static void pin_thread_to_core(int core_id) noexcept {
#ifdef __linux__
    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(core_id, &cpuset);
    const int rc = pthread_setaffinity_np(
        pthread_self(), sizeof(cpu_set_t), &cpuset
    );
    if (rc != 0) {
        // Non-fatal — engine continues, just without pinning
        std::cerr << "[WARN] Could not pin thread to core " << core_id
                  << " (rc=" << rc << ")\n";
    }
#endif
}

// ── ExecutionEngine implementation ─────────────────────────────────────────────
ExecutionEngine::ExecutionEngine()
    : guardrails_{}
    , order_pool_{}
    , md_queue_{}
    , signal_gen_(guardrails_)
    , exec_mgr_(guardrails_, order_pool_)
    , running_{false}
    , shared_signal_{}
    , has_new_signal_{false}
{
    // Register OS signal handlers for clean shutdown
    std::signal(SIGINT,  signal_handler);
    std::signal(SIGTERM, signal_handler);
}

ExecutionEngine::~ExecutionEngine() {
    stop();
}

void ExecutionEngine::start() {
    if (running_.exchange(true)) {
        throw std::runtime_error("ExecutionEngine already running");
    }

    md_thread_   = std::thread(&ExecutionEngine::market_data_loop, this);
    exec_thread_ = std::thread(&ExecutionEngine::execution_loop, this);
}

void ExecutionEngine::stop() noexcept {
    running_.store(false, std::memory_order_seq_cst);
    if (md_thread_.joinable())   md_thread_.join();
    if (exec_thread_.joinable()) exec_thread_.join();
}

/**
 * market_data_loop — Thread 1: Parse incoming market data and push to queue.
 *
 * In production: replace the simulated updates below with real socket reads.
 * This is where you'd integrate:
 *   - Tradier WebSocket: read JSON frames from the websocket fd
 *   - IBKR TWS: read binary frames from the TWS socket
 *   - Raw UDP (co-located HFT): read from kernel-bypass socket
 */
void ExecutionEngine::market_data_loop() {
    pin_thread_to_core(0);

    // Pre-allocate update on stack — reused every iteration (no heap)
    MarketUpdate update{};
    update.symbol = Symbol{"SPY"};

    // Simulated market feed — replace with real socket reads
    Price  base_bid = to_price(449.50);
    Price  base_ask = to_price(449.60);
    int    tick = 0;

    while (running_.load(std::memory_order_relaxed) && !g_shutdown.load()) {
        // In production: blocking socket read goes here
        // ssize_t n = recv(socket_fd, raw_buf.data(), raw_buf.size(), 0);
        // if (n > 0) { MarketDataParser::parse_tradier_quote({raw_buf.data(), n}, update); }

        // Simulate price movement (remove in production)
        update.bid_price   = base_bid + (tick % 5) * 10;   // ±$0.0050 moves
        update.ask_price   = base_ask + (tick % 5) * 10;
        update.bid_size    = 50 + (tick % 20);
        update.ask_size    = 30 + (tick % 15);
        update.received_at = std::chrono::steady_clock::now();
        ++tick;

        // Push to ring buffer — non-blocking
        if (!md_queue_.try_push(update)) [[unlikely]] {
            // Queue full — execution thread is lagging
            // In production: increment a backpressure counter, log to stats
        }

        // Throttle simulation to ~100 updates/sec (remove for real feed)
        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }
}

/**
 * execution_loop — Thread 2: Consume market data, evaluate signals, dispatch orders.
 *
 * Busy-poll pattern: we spin on try_pop() rather than blocking.
 * The yield() call gives the CPU to other threads when queue is empty,
 * preventing 100% CPU waste while still waking within ~1 microsecond.
 */
void ExecutionEngine::execution_loop() {
    pin_thread_to_core(1);

    // Pre-allocate everything on the stack — the loop allocates NOTHING
    MarketUpdate update{};
    OrderBook<5> book{};
    book.symbol = Symbol{"SPY"};

    while (running_.load(std::memory_order_relaxed) && !g_shutdown.load()) {

        // ── Consume all pending market updates ────────────────────────────
        bool had_update = false;
        while (md_queue_.try_pop(update)) {
            book.apply_update(update);
            had_update = true;
        }

        if (!had_update) {
            // Queue empty — yield to other threads rather than spinning 100%
            std::this_thread::yield();
            continue;
        }

        // ── Check for a new signal from Python ────────────────────────────
        // has_new_signal_ is written by Python bridge, read here
        bool expected = true;
        if (!has_new_signal_.compare_exchange_weak(
                expected, false,
                std::memory_order_acq_rel,
                std::memory_order_relaxed)) {
            continue;  // No new signal from Python
        }

        // Read the signal (copy — Python may update shared_signal_ again)
        const Signal signal = shared_signal_.load_signal();
        if (signal.type == Signal::Type::None) continue;

        const auto now = std::chrono::steady_clock::now();

        // ── Evaluate signal ────────────────────────────────────────────────
        const auto eval = signal_gen_.evaluate(
            book, signal.signal_score, signal.type, now
        );

        if (!eval.approved) {
            // Log rejection reason — to stats buffer, not stdout
            last_rejection_ = eval.reason;
            continue;
        }

        // ── Build and dispatch order ───────────────────────────────────────
        Order* order = exec_mgr_.build_order(eval.signal);
        if (!order) [[unlikely]] {
            // Pool exhausted — extremely rare
            continue;
        }

        const ExecutionResult result = exec_mgr_.dispatch(*order);

        // Write result back for Python bridge to read
        last_result_.store_result(result);

        // Increment trades counter (Python guardrails read this)
        guardrails_.trades_today.fetch_add(1, std::memory_order_relaxed);

        if (!result.success) {
            exec_mgr_.release_order(order);
            continue;
        }

        // Order submitted — in production: wait for fill confirmation
        // via the broker's async callback/confirmation channel.
        // For template: immediately release (production: release on fill)
        exec_mgr_.release_order(order);
    }
}

/**
 * submit_signal_from_python — Called by Python bridge to inject a signal.
 *
 * This is the primary integration point between Python (upstream AI pipeline)
 * and the C++ execution engine. Called from Python thread.
 *
 * Writes the signal to a shared atomic struct and sets the has_new_signal_
 * flag. The execution thread picks it up on the next loop iteration.
 */
void ExecutionEngine::submit_signal_from_python(const Signal& signal) noexcept {
    shared_signal_.store_signal(signal);
    has_new_signal_.store(true, std::memory_order_release);
}

/**
 * get_last_result — Called by Python bridge to retrieve execution result.
 */
ExecutionResult ExecutionEngine::get_last_result() const noexcept {
    return last_result_.load_result();
}

void ExecutionEngine::engage_kill_switch() noexcept {
    exec_mgr_.engage_kill_switch();
}

}  // namespace olbosquant


// ── Standalone main (for testing without Python) ──────────────────────────────
#ifndef OLBOSQUANT_PYTHON_MODULE

int main() {
    using namespace olbosquant;

    std::cout << "OlbosQuant C++ Execution Engine\n";
    std::cout << "Initializing...\n";

    ExecutionEngine engine;

    // Inject a test signal (in production: comes from Python)
    Signal test_signal{};
    test_signal.type         = Signal::Type::BullPut;
    test_signal.signal_score = 0.72f;
    test_signal.generated_at = std::chrono::steady_clock::now();
    test_signal.limit_price  = to_price(1.25);

    engine.start();
    std::cout << "Engine started. Press Ctrl+C to stop.\n";

    // Submit test signal after 2 seconds
    std::this_thread::sleep_for(std::chrono::seconds(2));
    engine.submit_signal_from_python(test_signal);
    std::cout << "Test signal submitted.\n";

    std::this_thread::sleep_for(std::chrono::seconds(1));

    const auto result = engine.get_last_result();
    if (result.success) {
        std::cout << "Order dispatched: id=" << result.order_id
                  << " latency=" << result.latency_us << "μs\n";
    } else {
        std::cout << "Order not dispatched: " << result.error_msg << "\n";
    }

    engine.stop();
    std::cout << "Engine stopped cleanly.\n";
    return 0;
}

#endif

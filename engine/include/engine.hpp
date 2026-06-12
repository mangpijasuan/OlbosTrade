/**
 * engine.hpp — ExecutionEngine class declaration.
 * Public interface used by both standalone main() and Python bridge.
 */

#pragma once

#include "types.hpp"
#include "ring_buffer.hpp"
#include "memory_pool.hpp"
#include "market_data.hpp"
#include "signal_generator.hpp"
#include "execution_manager.hpp"

#include <atomic>
#include <thread>
#include <mutex>

namespace olbosquant {

/**
 * AtomicSignal — lock-free Signal exchange between Python thread and exec thread.
 *
 * We cannot use std::atomic<Signal> directly because Signal is not trivially
 * copyable in the lock-free sense (too large for a single CAS instruction).
 * Instead we use a mutex-protected struct with a sequence number to detect
 * stale reads. The mutex is only held for a few nanoseconds (memcpy of ~64 bytes).
 *
 * Alternative for ultra-low-latency: use a seqlock (sequence lock) which
 * allows lock-free reads at the cost of retry logic. For this template,
 * the mutex is sufficient since Python writes signals at most 3x/day.
 */
struct AtomicSignal {
    mutable std::mutex mu;
    Signal             value{};
    uint64_t           version{0};

    void store_signal(const Signal& s) noexcept {
        std::lock_guard<std::mutex> lock(mu);
        value = s;
        ++version;
    }

    [[nodiscard]] Signal load_signal() const noexcept {
        std::lock_guard<std::mutex> lock(mu);
        return value;
    }
};

struct AtomicResult {
    mutable std::mutex mu;
    ExecutionResult    value{};

    void store_result(const ExecutionResult& r) noexcept {
        std::lock_guard<std::mutex> lock(mu);
        value = r;
    }

    [[nodiscard]] ExecutionResult load_result() const noexcept {
        std::lock_guard<std::mutex> lock(mu);
        return value;
    }
};

// ── ExecutionEngine ────────────────────────────────────────────────────────────
class ExecutionEngine {
public:
    ExecutionEngine();
    ~ExecutionEngine();

    // Non-copyable, non-movable — owns threads and shared state
    ExecutionEngine(const ExecutionEngine&)            = delete;
    ExecutionEngine& operator=(const ExecutionEngine&) = delete;

    void start();
    void stop() noexcept;

    // ── Python bridge interface ───────────────────────────────────────────────
    // These are the ONLY methods the Python bridge should call.
    void            submit_signal_from_python(const Signal& signal) noexcept;
    ExecutionResult get_last_result() const noexcept;
    void            engage_kill_switch() noexcept;

    // Guardrail state setters (called by Python bridge)
    void set_kill_switch(bool engaged) noexcept {
        guardrails_.kill_switch_engaged.store(engaged, std::memory_order_seq_cst);
    }
    void set_capital_preservation(bool active) noexcept {
        guardrails_.capital_preservation.store(active, std::memory_order_relaxed);
    }
    void set_max_daily_loss(int64_t cents) noexcept {
        guardrails_.max_daily_loss_cents.store(cents, std::memory_order_relaxed);
    }
    void reset_daily_counters() noexcept {
        guardrails_.trades_today.store(0, std::memory_order_relaxed);
        guardrails_.daily_pnl_cents.store(0, std::memory_order_relaxed);
    }

    [[nodiscard]] double avg_dispatch_latency_us() const noexcept {
        return exec_mgr_.avg_dispatch_latency_us();
    }
    [[nodiscard]] RejectionReason last_rejection() const noexcept {
        return last_rejection_;
    }

private:
    void market_data_loop();
    void execution_loop();

    // ── Engine components (all stack/static — no heap) ────────────────────────
    GuardrailState                  guardrails_;
    MemoryPool<Order, 256>          order_pool_;
    SPSCRingBuffer<MarketUpdate, 1024> md_queue_;  // 1024 = power of 2
    SignalGenerator                 signal_gen_;
    ExecutionManager                exec_mgr_;

    // ── Thread management ─────────────────────────────────────────────────────
    std::atomic<bool>   running_{false};
    std::thread         md_thread_;
    std::thread         exec_thread_;

    // ── Cross-thread communication ────────────────────────────────────────────
    AtomicSignal        shared_signal_{};
    std::atomic<bool>   has_new_signal_{false};
    AtomicResult        last_result_{};
    RejectionReason     last_rejection_{RejectionReason::None};
};

}  // namespace olbosquant

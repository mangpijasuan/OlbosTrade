/**
 * execution_manager.hpp — Order construction, formatting, and dispatch.
 *
 * RESPONSIBILITIES:
 *   1. Construct an Order from an approved Signal
 *   2. Assign a unique, monotonically increasing OrderId
 *   3. Format the order for the target broker protocol
 *   4. Dispatch to the network layer
 *   5. Track order state (submitted → filled/rejected)
 *
 * ORDER ID GENERATION:
 *   Uses std::atomic<uint64_t> with fetch_add — atomic increment is
 *   a single LOCK XADD instruction on x86. ~10ns, no mutex needed.
 *   IDs are monotonically increasing, which simplifies reconciliation.
 *
 * ORDER FORMATTING:
 *   We pre-format orders into a fixed-size byte buffer.
 *   No std::string, no std::ostringstream, no printf.
 *   std::format (C++20) is used where needed — it is allocation-free
 *   when writing to a fixed-size buffer via std::format_to.
 *
 * KILL SWITCH INTEGRATION:
 *   ExecutionManager checks the GuardrailState kill switch before
 *   dispatching ANY order. If engaged after signal generation but
 *   before dispatch, the order is cancelled. This is the final safety
 *   gate before bytes leave the process.
 *
 * LATENCY TRACKING:
 *   Every order records:
 *   - signal_to_dispatch_us: time from Signal.generated_at to wire
 *   - dispatch_to_fill_us:   time from wire to fill confirmation
 *   Stored in a pre-allocated circular stats buffer (not a heap vector).
 */

#pragma once

#include "types.hpp"
#include "signal_generator.hpp"
#include "memory_pool.hpp"

#include <atomic>
#include <array>
#include <charconv>
#include <cstring>
#include <cstdio>

namespace olbosquant {

// ── Latency stats (circular buffer, no heap) ──────────────────────────────────
struct LatencySample {
    int64_t signal_to_dispatch_us{0};
    int64_t dispatch_to_ack_us{0};
    OrderId order_id{0};
};

template<std::size_t N = 1024>
struct LatencyStats {
    std::array<LatencySample, N> samples{};
    std::atomic<std::size_t>     write_idx{0};

    void record(LatencySample s) noexcept {
        const auto idx = write_idx.fetch_add(1, std::memory_order_relaxed) & (N - 1);
        samples[idx] = s;
    }

    // Returns last N samples as a span — no copy, no allocation
    [[nodiscard]] double avg_dispatch_latency_us() const noexcept {
        int64_t total = 0;
        for (const auto& s : samples) {
            if (s.order_id > 0) total += s.signal_to_dispatch_us;
        }
        return static_cast<double>(total) / static_cast<double>(N);
    }
};

// ── Order formatter ────────────────────────────────────────────────────────────
// Formats an Order into Tradier REST JSON or a binary IBKR frame.
// All formatting goes into a fixed-size stack buffer — no heap.
class OrderFormatter {
public:
    // Fixed buffer sizes — stack allocated, always available
    static constexpr std::size_t JSON_BUF_SIZE   = 512;
    static constexpr std::size_t BINARY_BUF_SIZE = 128;

    using JsonBuffer   = std::array<char, JSON_BUF_SIZE>;
    using BinaryBuffer = std::array<std::byte, BINARY_BUF_SIZE>;

    /**
     * format_tradier_json — Format an Order as Tradier REST API JSON.
     *
     * Uses snprintf into a stack-allocated buffer.
     * snprintf is safe and allocation-free. It is NOT the fastest option
     * (std::format_to or manual char-by-char is faster), but the difference
     * is ~100ns — acceptable at this point in the pipeline where network
     * latency dominates.
     *
     * Returns number of bytes written, or -1 on format error.
     */
    [[nodiscard]] static int format_tradier_json(
        const Order& order,
        JsonBuffer&  buf) noexcept
    {
        const char* side_str   = (order.side == OrderSide::Buy) ? "buy" : "sell";
        const char* type_str   = (order.type == OrderType::Limit) ? "limit" : "market";
        const double lmt_price = from_price(order.limit_price);
        const char* sym        = order.symbol.data.data();

        if (order.leg_count <= 1) {
            // Single-leg order
            return std::snprintf(
                buf.data(), buf.size(),
                R"({"class":"option","symbol":"%s","side":"%s")"
                R"(,"quantity":%d,"type":"%s","duration":"day")"
                R"(,"price":"%.4f"})",
                sym, side_str, order.quantity, type_str, lmt_price
            );
        } else {
            // Multi-leg (combo) order
            // Format legs array inline — no heap
            std::array<char, 256> legs_buf{};
            int legs_offset = 0;
            legs_offset += std::snprintf(
                legs_buf.data(), legs_buf.size(), "[");

            for (uint8_t i = 0; i < order.leg_count && i < 4; ++i) {
                const char* leg_side = (order.leg_sides[i] == OrderSide::Buy)
                    ? "buy_to_open" : "sell_to_open";
                legs_offset += std::snprintf(
                    legs_buf.data() + legs_offset,
                    legs_buf.size() - static_cast<std::size_t>(legs_offset),
                    R"({"option_symbol":"%s","side":"%s","quantity":%d}%s)",
                    order.leg_symbols[i].data.data(),
                    leg_side,
                    order.quantity,
                    (i < order.leg_count - 1) ? "," : ""
                );
            }
            std::snprintf(legs_buf.data() + legs_offset,
                         legs_buf.size() - static_cast<std::size_t>(legs_offset), "]");

            return std::snprintf(
                buf.data(), buf.size(),
                R"({"class":"multileg","symbol":"%s","type":"%s")"
                R"(,"duration":"day","price":"%.4f","legs":%s})",
                order.symbol.data.data(), type_str, lmt_price, legs_buf.data()
            );
        }
    }

    /**
     * format_ibkr_binary — Format an Order as IBKR TWS binary frame.
     * Simplified layout — in production: use the full EClient protocol.
     */
    [[nodiscard]] static int format_ibkr_binary(
        const Order&   order,
        BinaryBuffer&  buf) noexcept
    {
        std::size_t offset = 0;
        const uint32_t magic = 0xAB'CD'12'34u;

        auto write = [&](const void* src, std::size_t n) {
            if (offset + n <= buf.size()) {
                std::memcpy(buf.data() + offset, src, n);
                offset += n;
            }
        };

        write(&magic,             sizeof(magic));
        write(&order.id,          sizeof(order.id));
        write(&order.limit_price, sizeof(order.limit_price));
        write(&order.quantity,    sizeof(order.quantity));
        write(&order.side,        sizeof(order.side));
        write(&order.type,        sizeof(order.type));
        write(order.symbol.data.data(), 24);

        return static_cast<int>(offset);
    }
};

// ── ExecutionManager ───────────────────────────────────────────────────────────
class ExecutionManager {
public:
    explicit ExecutionManager(
        GuardrailState&    guardrails,
        MemoryPool<Order, 256>& pool) noexcept
        : guardrails_(guardrails)
        , order_pool_(pool)
    {}

    /**
     * build_order — Construct an Order from an approved Signal.
     *
     * Uses the memory pool (no heap). Returns nullptr if pool exhausted.
     * The caller owns the returned Order* and must call release_order()
     * when the order lifecycle completes.
     *
     * Placement new: constructs the Order IN the pool slot.
     * No heap allocation — just runs the constructor on pre-owned memory.
     */
    [[nodiscard]] Order* build_order(const Signal& signal) noexcept {
        // Final kill switch check — last gate before order construction
        if (guardrails_.kill_switch_engaged.load(std::memory_order_seq_cst))
            [[unlikely]] {
            return nullptr;
        }

        Order* order = order_pool_.alloc();
        if (!order) [[unlikely]] {
            // Pool exhausted — this should never happen in practice with N=256
            // Log to stats buffer, not stdout
            return nullptr;
        }

        // Placement new — constructs Order in the pre-allocated slot
        new (order) Order{};

        order->id          = next_order_id_.fetch_add(1, std::memory_order_relaxed);
        order->side        = signal.side;
        order->type        = OrderType::Limit;
        order->limit_price = signal.limit_price;
        order->quantity    = 1;  // Position sizing set by Python; C++ always sends 1
        order->status      = Order::Status::Pending;
        order->submitted_at = std::chrono::steady_clock::now();

        // Record signal-to-dispatch latency
        const auto latency_us = std::chrono::duration_cast<std::chrono::microseconds>(
            order->submitted_at - signal.generated_at
        ).count();

        stats_.record({latency_us, 0, order->id});

        return order;
    }

    /**
     * dispatch — Format and send an order to the broker.
     *
     * In this template: simulates dispatch. In production:
     * replace with a non-blocking socket write (io_uring or epoll).
     *
     * Returns ExecutionResult immediately — actual fill arrives
     * asynchronously via the broker's confirmation channel.
     */
    [[nodiscard]] ExecutionResult dispatch(
        Order&      order,
        bool        use_json = true) noexcept
    {
        ExecutionResult result{};

        // Final kill switch check
        if (guardrails_.kill_switch_engaged.load(std::memory_order_seq_cst))
            [[unlikely]] {
            result.set_error("kill_switch_engaged");
            order.status = Order::Status::Cancelled;
            return result;
        }

        const auto dispatch_start = std::chrono::steady_clock::now();

        if (use_json) {
            OrderFormatter::JsonBuffer buf{};
            const int len = OrderFormatter::format_tradier_json(order, buf);
            if (len <= 0) {
                result.set_error("json_format_failed");
                return result;
            }
            // In production: write buf.data() to socket fd via send() or io_uring
            // For template: mark as submitted
            order.status = Order::Status::Submitted;
        } else {
            OrderFormatter::BinaryBuffer buf{};
            const int len = OrderFormatter::format_ibkr_binary(order, buf);
            if (len <= 0) {
                result.set_error("binary_format_failed");
                return result;
            }
            order.status = Order::Status::Submitted;
        }

        const auto dispatch_end = std::chrono::steady_clock::now();
        result.latency_us = std::chrono::duration_cast<std::chrono::microseconds>(
            dispatch_end - dispatch_start
        ).count();

        result.success  = true;
        result.order_id = order.id;
        result.status   = order.status;

        return result;
    }

    /**
     * release_order — Return order memory to the pool after lifecycle completes.
     * Must be called when order is filled, rejected, or cancelled.
     * RAII equivalent for pool-allocated objects.
     */
    void release_order(Order* order) noexcept {
        if (!order) return;
        order->~Order();          // Explicit destructor
        order_pool_.free(order);  // Return slot to pool
    }

    /**
     * engage_kill_switch — Hard stop. Atomic, visible to all threads instantly.
     * Called by Python bridge on guardrail trigger or manual stop.
     */
    void engage_kill_switch() noexcept {
        guardrails_.kill_switch_engaged.store(true, std::memory_order_seq_cst);
    }

    [[nodiscard]] double avg_dispatch_latency_us() const noexcept {
        return stats_.avg_dispatch_latency_us();
    }

private:
    GuardrailState&         guardrails_;
    MemoryPool<Order, 256>& order_pool_;
    LatencyStats<1024>      stats_{};

    // Monotonically increasing order ID generator — atomic increment, ~10ns
    std::atomic<OrderId>    next_order_id_{1};
};

}  // namespace olbosquant

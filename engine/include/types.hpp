/**
 * types.hpp — Core value types for the OlbosQuant execution engine.
 *
 * Design principles applied throughout this file:
 *
 * 1. NO HEAP ALLOCATION in the hot path.
 *    Every struct here is either stack-allocated or lives in a pre-allocated
 *    pool. The `new` keyword never appears in the trading loop. Dynamic
 *    allocation triggers the kernel allocator which is non-deterministic
 *    latency — unacceptable when microseconds matter.
 *
 * 2. CACHE-LINE ALIGNMENT.
 *    A cache line is 64 bytes on x86. If a struct straddles two cache lines,
 *    reading it requires two memory fetches instead of one. alignas(64)
 *    pins frequently-read structs to a single cache line boundary.
 *
 * 3. FIXED-POINT PRICE REPRESENTATION.
 *    Floating-point arithmetic is non-deterministic across platforms and
 *    compiler settings. Options prices are stored as int64 with an implicit
 *    4-decimal-place scale (i.e., $1.2345 = 12345). This gives exact
 *    comparison, zero rounding error, and is faster than IEEE 754 on
 *    most modern processors.
 *
 * 4. trivially_copyable structs.
 *    All hot-path structs are trivially copyable — no virtual functions,
 *    no user-defined constructors. This allows memcpy-speed copies and
 *    safe placement into lock-free queues.
 */

#pragma once

#include <cstdint>
#include <cstring>
#include <string_view>
#include <chrono>
#include <array>

namespace olbosquant {

// ── Price representation ───────────────────────────────────────────────────────
// Fixed-point: 4 decimal places. $1.2345 → 12345
// Range: ±$922,337,203,685.4775 (int64 max) — sufficient for any options price
using Price     = int64_t;
using Quantity  = int32_t;
using OrderId   = uint64_t;
using Timestamp = std::chrono::time_point<std::chrono::steady_clock>;

// Price scaling factor — divide by this to get a double for display
static constexpr Price PRICE_SCALE = 10'000;

// Convert double to fixed-point Price
// constexpr: evaluated at compile time when given a literal
[[nodiscard]] constexpr Price to_price(double d) noexcept {
    return static_cast<Price>(d * PRICE_SCALE + 0.5);  // +0.5 for rounding
}

// Convert fixed-point Price back to double (display/logging only)
[[nodiscard]] constexpr double from_price(Price p) noexcept {
    return static_cast<double>(p) / static_cast<double>(PRICE_SCALE);
}

// ── Option type ────────────────────────────────────────────────────────────────
enum class OptionType : uint8_t { Call = 0, Put = 1 };
enum class OrderSide  : uint8_t { Buy  = 0, Sell = 1 };
enum class OrderType  : uint8_t { Limit = 0, Market = 1 };

// ── Ticker symbol — fixed-size, no heap ────────────────────────────────────────
// std::string requires heap allocation. We use a fixed 16-char array instead.
// 16 chars covers all OCC option symbols (e.g., "SPY240119P00450000" = 18 chars)
// We use 24 to be safe.
struct Symbol {
    std::array<char, 24> data{};
    uint8_t              len{0};

    // Construct from string_view — no allocation, just memcpy
    explicit Symbol(std::string_view sv) noexcept {
        len = static_cast<uint8_t>(std::min(sv.size(), data.size() - 1));
        std::memcpy(data.data(), sv.data(), len);
        data[len] = '\0';
    }

    Symbol() noexcept = default;

    [[nodiscard]] std::string_view view() const noexcept {
        return {data.data(), len};
    }

    [[nodiscard]] bool operator==(const Symbol& other) const noexcept {
        return len == other.len &&
               std::memcmp(data.data(), other.data.data(), len) == 0;
    }
};

// ── Market data update — what arrives from the broker feed ────────────────────
// alignas(64): pins to one cache line so all fields load in a single fetch.
// 64 bytes: Price(8) + Price(8) + Qty(4) + Qty(4) + Symbol(25) + padding = 64
struct alignas(64) MarketUpdate {
    Price     bid_price{0};
    Price     ask_price{0};
    Quantity  bid_size{0};
    Quantity  ask_size{0};
    Timestamp received_at{};
    Symbol    symbol{};
    uint8_t   sequence{0};     // Wrap-around sequence number for ordering

    // Derived: mid price (display only — never use for order pricing)
    [[nodiscard]] double mid() const noexcept {
        return from_price((bid_price + ask_price) / 2);
    }

    // Derived: spread as % of mid (for liquidity check)
    [[nodiscard]] double spread_pct() const noexcept {
        if (bid_price + ask_price == 0) return 999.0;
        const double mid_p = static_cast<double>(bid_price + ask_price) / 2.0;
        return (static_cast<double>(ask_price - bid_price) / mid_p) * 100.0;
    }
};
static_assert(sizeof(MarketUpdate) <= 64,
    "MarketUpdate exceeds one cache line — check alignment");
static_assert(std::is_trivially_copyable_v<MarketUpdate>,
    "MarketUpdate must be trivially copyable for lock-free queue use");

// ── Signal — output of SignalGenerator, input to ExecutionManager ─────────────
// Deliberately minimal: only what the execution layer needs to know.
struct alignas(32) Signal {
    enum class Type : uint8_t {
        None      = 0,
        BullPut   = 1,   // Bull Put Spread
        BearCall  = 2,   // Bear Call Spread
        IronCon   = 3,   // Iron Condor
        BullCall  = 4,   // Bull Call Debit Spread
        KillSwitch = 255
    };

    Type      type{Type::None};
    OrderSide side{OrderSide::Buy};
    Price     short_strike{0};
    Price     long_strike{0};
    Quantity  quantity{0};
    Price     limit_price{0};      // Net credit/debit limit
    float     signal_score{0.0f};  // From Python AI scorer
    Timestamp generated_at{};
};

// ── Order — what gets sent to the broker ──────────────────────────────────────
struct alignas(64) Order {
    enum class Status : uint8_t {
        Pending   = 0,
        Submitted = 1,
        Filled    = 2,
        Rejected  = 3,
        Cancelled = 4,
        PartialFill = 5
    };

    OrderId   id{0};
    Symbol    symbol{};
    OrderSide side{OrderSide::Buy};
    OrderType type{OrderType::Limit};
    Price     limit_price{0};
    Quantity  quantity{0};
    Quantity  filled_qty{0};
    Price     avg_fill_price{0};
    Status    status{Status::Pending};
    Timestamp submitted_at{};
    Timestamp filled_at{};

    // Leg count for multi-leg spread orders
    uint8_t   leg_count{0};
    std::array<Symbol, 4> leg_symbols{};  // Max 4 legs (Iron Condor)
    std::array<OrderSide, 4> leg_sides{};
    std::array<Price, 4> leg_prices{};
};

// ── Execution result — returned to Python via the bridge ─────────────────────
struct ExecutionResult {
    bool      success{false};
    OrderId   order_id{0};
    Order::Status status{Order::Status::Pending};
    int64_t   latency_us{0};   // Microseconds from signal to submission
    char      error_msg[128]{};

    void set_error(std::string_view msg) noexcept {
        success = false;
        const auto len = std::min(msg.size(), sizeof(error_msg) - 1);
        std::memcpy(error_msg, msg.data(), len);
        error_msg[len] = '\0';
    }
};

}  // namespace olbosquant

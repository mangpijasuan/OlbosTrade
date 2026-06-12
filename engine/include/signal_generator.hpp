/**
 * signal_generator.hpp — C++ Signal Generator.
 *
 * RELATIONSHIP TO PYTHON SIGNAL SCORER:
 *   The Python AI scorer (XGBoost + SHAP) runs UPSTREAM of this module.
 *   Python generates a signal with a score and serializes it to shared memory
 *   or the SPSC queue. This C++ module receives that signal and applies
 *   the final fast-path validation rules before order construction.
 *
 *   The split is intentional:
 *   - Python: regime classification, IV surface, XGBoost inference (~50ms)
 *   - C++: final price validation, Greeks check, order construction (~5μs)
 *
 * SIGNAL VALIDATION RULES (fast path — no Python involvement):
 *   1. Spread quality: ask - bid must be within configured max %
 *   2. Bid/ask freshness: update timestamp must be within MAX_QUOTE_AGE_US
 *   3. Minimum size: bid/ask size must meet minimum liquidity threshold
 *   4. Kill switch: atomic flag checked first on every evaluation
 *   5. Score threshold: signal_score from Python must exceed threshold
 *
 * constexpr THRESHOLDS:
 *   Using constexpr instead of runtime config for frequently-evaluated
 *   thresholds allows the compiler to fold them into immediate operands
 *   in the generated assembly — zero memory reads during evaluation.
 */

#pragma once

#include "types.hpp"
#include "market_data.hpp"

#include <atomic>
#include <chrono>
#include <cstdint>

namespace olbosquant {

// ── Configurable thresholds (constexpr = zero-cost evaluation) ────────────────
namespace config {
    // Maximum quote age before considering data stale (90 seconds in μs)
    inline constexpr int64_t MAX_QUOTE_AGE_US   = 90'000'000LL;

    // Minimum AI score to allow order generation (matches Python config)
    inline constexpr float   MIN_SIGNAL_SCORE   = 0.65f;

    // Bull/Bear spread signal: bid_size must exceed ask_size by this ratio
    inline constexpr float   SIZE_IMBALANCE_RATIO = 2.0f;

    // Maximum spread as % of mid before rejecting (matches ExecutionDispatcher)
    inline constexpr double  MAX_SPREAD_PCT     = 15.0;

    // Minimum bid/ask size to consider the market tradeable
    inline constexpr Quantity MIN_QUOTE_SIZE    = 5;

    // Capital preservation mode: raised score threshold
    inline constexpr float   PRESERVATION_SCORE = 0.80f;
}

// ── Guardrail state (set by Python via shared memory / bridge) ────────────────
// These atomics are written by the Python process and read by the C++ hot path.
// memory_order_relaxed is safe for these reads — we don't need sequential
// consistency, just eventual visibility. A stale kill_switch read might allow
// one extra order through, which is acceptable for the common case.
// For kill_switch specifically, we use seq_cst to guarantee immediate visibility.
struct alignas(64) GuardrailState {
    std::atomic<bool>    kill_switch_engaged{false};   // seq_cst required
    std::atomic<bool>    capital_preservation{false};
    std::atomic<int32_t> trades_today{0};
    std::atomic<int32_t> max_trades_today{3};
    std::atomic<int64_t> daily_pnl_cents{0};           // P&L in cents
    std::atomic<int64_t> max_daily_loss_cents{0};
};

// ── Rejection reason (for logging, no allocation) ─────────────────────────────
enum class RejectionReason : uint8_t {
    None            = 0,
    KillSwitch      = 1,
    StaleQuote      = 2,
    SpreadTooWide   = 3,
    SizeTooSmall    = 4,
    ScoreTooLow     = 5,
    DailyLossLimit  = 6,
    TradeCap        = 7,
    InsufficientEdge = 8,
};

// ── Signal evaluation result ──────────────────────────────────────────────────
struct EvaluationResult {
    bool             approved{false};
    Signal           signal{};
    RejectionReason  reason{RejectionReason::None};
    int64_t          eval_latency_ns{0};   // Nanoseconds for this evaluation
};

// ── SignalGenerator ────────────────────────────────────────────────────────────
class SignalGenerator {
public:
    explicit SignalGenerator(GuardrailState& guardrails) noexcept
        : guardrails_(guardrails) {}

    /**
     * evaluate — Core signal evaluation. Called from execution thread.
     *
     * This function must complete in < 1 microsecond. Every branch is
     * ordered by probability of rejection (cheapest checks first):
     *   1. Kill switch (atomic read, ~5ns)
     *   2. Quote staleness (arithmetic comparison, ~2ns)
     *   3. Trade cap (atomic read, ~5ns)
     *   4. Spread width (arithmetic, ~2ns)
     *   5. Size check (comparison, ~2ns)
     *   6. Score threshold (float comparison, ~2ns)
     *   7. Strategy-specific logic (branch + arithmetic, ~10ns)
     *
     * Total typical path: ~30ns
     *
     * noexcept: no exceptions in the hot path — ever.
     * [[nodiscard]]: caller must process the result.
     */
    [[nodiscard]] EvaluationResult evaluate(
        const OrderBook<5>& book,
        float               signal_score,
        Signal::Type        strategy_type,
        const Timestamp&    now) const noexcept
    {
        const auto start = std::chrono::steady_clock::now();
        EvaluationResult result{};

        // ── 1. Kill switch — hardest stop, checked first ────────────────────
        // memory_order_seq_cst: must see the most recent value immediately
        if (guardrails_.kill_switch_engaged.load(std::memory_order_seq_cst))
            [[unlikely]] {
            result.reason = RejectionReason::KillSwitch;
            goto done;
        }

        // ── 2. Quote staleness ──────────────────────────────────────────────
        {
            const auto age_us = std::chrono::duration_cast<std::chrono::microseconds>(
                now - book.updated_at
            ).count();
            if (age_us > config::MAX_QUOTE_AGE_US) [[unlikely]] {
                result.reason = RejectionReason::StaleQuote;
                goto done;
            }
        }

        // ── 3. Daily trade cap ──────────────────────────────────────────────
        if (guardrails_.trades_today.load(std::memory_order_relaxed) >=
            guardrails_.max_trades_today.load(std::memory_order_relaxed))
            [[unlikely]] {
            result.reason = RejectionReason::TradeCap;
            goto done;
        }

        // ── 4. Daily loss limit ─────────────────────────────────────────────
        if (guardrails_.daily_pnl_cents.load(std::memory_order_relaxed) <=
            guardrails_.max_daily_loss_cents.load(std::memory_order_relaxed))
            [[unlikely]] {
            result.reason = RejectionReason::DailyLossLimit;
            goto done;
        }

        // ── 5. Spread quality check ─────────────────────────────────────────
        {
            const double spread_pct =
                from_price(book.best_ask() - book.best_bid()) /
                (from_price(book.best_bid() + book.best_ask()) * 0.5) * 100.0;
            if (spread_pct > config::MAX_SPREAD_PCT) {
                result.reason = RejectionReason::SpreadTooWide;
                goto done;
            }
        }

        // ── 6. Minimum quote size ───────────────────────────────────────────
        if (book.best_bid_size() < config::MIN_QUOTE_SIZE ||
            book.best_ask_size() < config::MIN_QUOTE_SIZE) {
            result.reason = RejectionReason::SizeTooSmall;
            goto done;
        }

        // ── 7. AI score threshold ───────────────────────────────────────────
        {
            const float threshold = guardrails_.capital_preservation
                .load(std::memory_order_relaxed)
                ? config::PRESERVATION_SCORE
                : config::MIN_SIGNAL_SCORE;

            if (signal_score < threshold) {
                result.reason = RejectionReason::ScoreTooLow;
                goto done;
            }
        }

        // ── 8. Strategy-specific signal logic ──────────────────────────────
        {
            Signal sig{};
            sig.type         = strategy_type;
            sig.signal_score = signal_score;
            sig.generated_at = now;

            switch (strategy_type) {
            case Signal::Type::BullPut:
                // Bull Put Spread signal: buy pressure > sell pressure
                // bid_size / ask_size > SIZE_IMBALANCE_RATIO = bullish
                if (static_cast<float>(book.best_bid_size()) <
                    static_cast<float>(book.best_ask_size()) * config::SIZE_IMBALANCE_RATIO)
                {
                    result.reason = RejectionReason::InsufficientEdge;
                    goto done;
                }
                sig.side  = OrderSide::Sell;  // Sell the put spread (credit)
                sig.limit_price = book.best_bid_price_for_spread();
                break;

            case Signal::Type::BearCall:
                // Bear Call Spread: ask_size > bid_size = sell pressure
                if (static_cast<float>(book.best_ask_size()) <
                    static_cast<float>(book.best_bid_size()) * config::SIZE_IMBALANCE_RATIO)
                {
                    result.reason = RejectionReason::InsufficientEdge;
                    goto done;
                }
                sig.side = OrderSide::Sell;
                sig.limit_price = book.best_ask_price_for_spread();
                break;

            case Signal::Type::IronCon:
                // Iron Condor: no directional bias needed
                // Both bid and ask sizes must be healthy
                if (book.best_bid_size() < config::MIN_QUOTE_SIZE * 2 ||
                    book.best_ask_size() < config::MIN_QUOTE_SIZE * 2)
                {
                    result.reason = RejectionReason::SizeTooSmall;
                    goto done;
                }
                sig.side = OrderSide::Sell;
                break;

            case Signal::Type::KillSwitch:
                // Python explicitly sent a kill switch signal
                guardrails_.kill_switch_engaged.store(true, std::memory_order_seq_cst);
                result.reason = RejectionReason::KillSwitch;
                goto done;

            default:
                result.reason = RejectionReason::InsufficientEdge;
                goto done;
            }

            result.signal   = sig;
            result.approved = true;
        }

    done:
        const auto end = std::chrono::steady_clock::now();
        result.eval_latency_ns =
            std::chrono::duration_cast<std::chrono::nanoseconds>(end - start).count();
        return result;
    }

private:
    GuardrailState& guardrails_;  // Reference to shared atomic state
};

}  // namespace olbosquant
